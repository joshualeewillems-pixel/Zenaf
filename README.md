# Atria — developer handoff

Local-first **workflow cockpit**: workspace organizer (File Steward + `/run` modes), intake/email queue, **Vision → Execution** (ideas → initiatives → projects → tasks), content tools, **Settings** (account, LLM keys, notification prefs). **FastAPI** backend + **React / Vite** SPA.

**Not production-hardened** by default: cookie auth, local SQLite, dev-oriented CORS.

Use this README to **clone, run, and orient** another developer on this build.

---

## Receiving developer — do this first

1. **Get the tree** — full repo checkout at a path with no spaces if possible (fewer tooling edge cases).
2. **Python 3.11+** — `python --version` (or `python3`).
3. **Node.js LTS** + npm — `node -v`, `npm -v`.
4. **Virtualenv (recommended)** — from repo root:
   - Windows: `python -m venv .venv` then `.\.venv\Scripts\Activate.ps1`
   - macOS/Linux: `python3 -m venv .venv` then `source .venv/bin/activate`
5. **Install API deps** — still from **repo root** (so `local_ai` imports work):
   ```bash
   pip install -r api/requirements.txt
   ```
6. **Install frontend deps:**
   ```bash
   cd frontend && npm install && cd ..
   ```
7. **Optional — encrypted LLM keys in Settings:** set `ATRIA_SETTINGS_ENCRYPTION_KEY` (see [Environment](#environment)). The Settings UI will warn if it is missing; without it, **saving** API keys fails (503); much of the app still runs for local/workflow use.
8. **Start stack** — Windows: `.\open-cockpit.ps1` from root, or use [Manual run](#manual-run-all-platforms) below.
9. **Sanity check:** browser **http://localhost:5173** (app) and **http://127.0.0.1:8010/docs** (OpenAPI). Optional: `curl http://127.0.0.1:8010/health`.

---

## Prerequisites

| Need | Notes |
|------|--------|
| **Python 3.11+** | API + `local_ai`; run uvicorn from **repo root**. |
| **Node + npm** | `frontend/` only. |
| **Ollama (typical)** | Default LLM for many `/run` paths; optional cloud keys via Settings. See `local_ai` config in repo. |
| **Repo layout** | Do **not** run the API from inside `api/` only — `api/main.py` expects `local_ai` on `sys.path` from root. |

---

## Quick start (Windows)

From repo root:

```powershell
.\open-cockpit.ps1
```

Or double-click **`open-cockpit.bat`** (runs the same script).

Starts API on **127.0.0.1:8010** and frontend on **5173**, opens the app and Swagger in the browser.

---

## Manual run (all platforms)

Two terminals, both usable from **repo root** (with venv activated if you use one).

**Terminal 1 — API**

```bash
pip install -r api/requirements.txt   # once
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8010
```

**Terminal 2 — frontend**

```bash
cd frontend
npm install    # once
npm run dev
```

| URL | What |
|-----|------|
| http://localhost:5173 | Cockpit SPA |
| http://127.0.0.1:8010/docs | OpenAPI / Swagger |
| http://127.0.0.1:8010/health | JSON health |

Frontend dev server **proxies** `/run`, `/auth`, `/vision-execution`, `/settings` to port **8010** (`frontend/vite.config.ts`). Intake/workspace calls use **`API_BASE`** in `frontend/src/App.tsx` — keep API on **8010** unless you change both.

---

## Verify a clean handoff

```bash
# From repo root, API running
curl -s http://127.0.0.1:8010/health

# Production-style frontend build (optional)
cd frontend && npm run build
```

---

## Environment

| Variable | When needed |
|----------|-------------|
| **`ATRIA_SETTINGS_ENCRYPTION_KEY`** | Fernet key (URL-safe base64) to **store** LLM API keys via Settings. If unset, credential saves return **503** (by design). Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. **Separate from** learning JSONL below — that key encrypts settings secrets only. |
| **`ATRIA_LEARNING_EXPORT_ENABLED`** | Set to `1` / `true` / `yes` / `on` to allow authenticated **GET** export/inspect/stats for in-memory learning records (`/vision-execution/learning-records/*`). Default: off (**403**). |
| **`ATRIA_LEARNING_PERSIST_PATH`** | Optional path to an **append-only JSONL** file for `LearningRecord` rows (same redacted shape as capture). Loaded on API startup into the ring buffer; new rows append after each capture/outcome update. Missing file is OK; corrupt lines skipped with a warning. |
| **`ATRIA_LEARNING_PERSIST_MAX_MB`** | Optional. If set, when the JSONL exceeds this size (MiB), it is rotated to `*.YYYYMMDD-HHMMSS.rotated` before the next append. |
| **Ollama / provider config** | Default local LLM; cloud providers optional via Settings UI when encryption key is set. |

---

## Data & persistence

| Store | Location | Notes |
|-------|-----------|--------|
| **Intake mirror** | `intake_mirror.db` (repo root) | Queue + judgments; loaded into memory on API startup — see **`docs/01_TRUTH/BOOT_FLOW.md`**. |
| **Vision Execution** | `data/vision_execution/vision_execution.db` | Init on first VE API use. |
| **Learning records (optional)** | Path from **`ATRIA_LEARNING_PERSIST_PATH`** | Append-only JSONL of post-capture rows (privacy modes already applied — no full prompts). Also kept in an in-memory ring buffer for fast access. |

Back up those files if you care about local data. **Lock down** any learning JSONL path (OS permissions) like other operational logs.

---

## Delegation learning loop (export → disk → offline analysis)

Non-blocking capture of **delegated** (often cloud) calls into **`LearningRecord`** rows: intent, surface, tier, provider/model, validation outcome, optional user outcome, redacted snippets, prompt hash prefix only.

| Step | What |
|------|------|
| **Live buffer** | `local_ai/delegation/learning_capture.py` — ring buffer; clients can POST user outcomes by `learning_record_id`. |
| **HTTP export** | With `ATRIA_LEARNING_EXPORT_ENABLED`, logged-in users can hit **`GET /vision-execution/learning-records/{stats,inspect,export}`** (paginated; JSONL or JSON). |
| **Durable log** | Set `ATRIA_LEARNING_PERSIST_PATH`; API startup replays JSONL into the buffer (last line per `record_id` wins). |
| **Offline prep** | `python scripts/atria_learning_jsonl_prep.py <paths...> -o cleaned.jsonl` — merge active + `*.rotated` files, dedupe, optional `--summary-json`. |
| **Evidence report** | `python scripts/atria_learning_analysis.py cleaned.jsonl` — validation/outcome/capture breakdowns, heuristic **surface** recommendations, coarse distillation gate; optional `--json-out`. |

**Design reference:** **`docs/02_ACTIVE_DESIGN/TIERED_DELEGATION_AND_LEARNING.md`**.

---

## Repo map

| Path | Role |
|------|------|
| `api/main.py` | FastAPI app: `/run`, routers, startup, intake mirror load |
| `api/routes/` | `vision_execution`, intake, `auth`, `settings`, … |
| `local_ai/` | Engine: `atria_tools.py`, `vision_execution/`, `intake/`, `llm/resolver.py`, … |
| `frontend/` | Vite SPA; `App.tsx`; `src/vision-execution/`, `src/settings/`, … |
| `docs/` | See **`docs/README.md`** for folder layout (`01_TRUTH`, `02_ACTIVE_DESIGN`, …) |

---

## Documentation for the next owner

| Read | Why |
|------|-----|
| **`docs/README.md`** | How docs are organized; what to trust first. |
| **`docs/01_TRUTH/ACTIVE_VS_PLANNED.md`** | What is implemented vs stubbed vs not built. |
| **`docs/01_TRUTH/CODEBASE_INVENTORY.md`** | Overview, build/tooling, routes, DBs. |
| **`docs/01_TRUTH/CODEBASE_TRUTH_RULES.md`** | LLM routing, `/auth` vs `/settings`, persistence expectations. |
| **`docs/01_TRUTH/BOOT_FLOW.md`** | API startup and mirror load order. |
| **`docs/02_ACTIVE_DESIGN/TIERED_DELEGATION_AND_LEARNING.md`** | Tiers, `LearningRecord`, export/persist, offline scripts, privacy modes. |
| **`api/README.md`** | API install, auth/settings endpoints. |
| **`frontend/README.md`** | Dev proxy, production build, TS policy. |
| **`docs/FILE_TREE_OVERVIEW.md`** | Path-level tree. |

---

## Tests & scripts

```bash
# From repo root (with same Python env as API)
pytest tests/
```

| Script | Purpose |
|--------|---------|
| **`scripts/atria_learning_jsonl_prep.py`** | Dedupe merged JSONL; write cleaned file + optional summary JSON. |
| **`scripts/atria_learning_analysis.py`** | Analysis report on **cleaned** JSONL (prompt/validator prioritization). |
| *Others* | Seeds, intake helpers, vision execution seeds — browse `scripts/`. |

---

## Troubleshooting

| Symptom | Check |
|---------|--------|
| **`ModuleNotFoundError: local_ai`** | Run `uvicorn` from **repo root**, not from `api/`. |
| **Frontend 404 / network errors on API** | API on **8010**; `npm run dev` running; proxy in `vite.config.ts`. |
| **CORS / cookie issues** | Use the Vite dev URL (**5173**) so requests go through the proxy for scoped routes. |
| **503 on LLM credential save** | Set **`ATRIA_SETTINGS_ENCRYPTION_KEY`** or skip storing keys and use default local provider. |
| **403 on learning export/inspect** | Set **`ATRIA_LEARNING_EXPORT_ENABLED=1`** and call the API **authenticated** (same session as the app). |
| **Learning file not growing** | Confirm **`ATRIA_LEARNING_PERSIST_PATH`** is set **before** API start; path writable; check API logs for persist warnings. |
| **Intake queue empty after restart** | Expected if `intake_mirror.db` missing or not yet populated; see **BOOT_FLOW**. |

---

## Support

Confirm commands from **repo root**, API **8010**, and frontend proxy / **`API_BASE`** alignment in `frontend/src/App.tsx` and `frontend/vite.config.ts`.
