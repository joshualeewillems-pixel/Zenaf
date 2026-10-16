# Zenaf API



Thin FastAPI bridge for the cockpit frontend. Calls the existing `local_ai` engine; no duplicated business logic.



## Setup



From the **Zenaf repo root**:



```bash

pip install -r api/requirements.txt

```



Dependencies include **`cryptography`** (Fernet) for encrypting user LLM API keys stored via `/settings`.



## Run



From the **Zenaf repo root** (so `local_ai` is importable):



```bash

uvicorn api.main:app --reload --host 127.0.0.1 --port 8010

```



- API: http://127.0.0.1:8010

- Docs: http://127.0.0.1:8010/docs

- **Dev SPA:** use **http://127.0.0.1:5173** (see `frontend/vite.config.ts`). `localhost` is a different host than `127.0.0.1`; mixing them breaks cookie auth for paths that call the API by absolute URL.



## Environment (Settings / LLM keys)



- **`ZENAF_SETTINGS_ENCRYPTION_KEY`** — Fernet key (URL-safe base64-encoded 32-byte key). Required to **store** LLM API keys via `PUT /settings/llm/credentials/{provider}`. If missing or invalid, those requests return **503** with a clear message (no plaintext storage). All `ATRIA_*` legacy environment variable fallbacks were removed in the 2026-10-16 clean break.

- **LLM keys** — Saved keys are per `users.id`. To migrate keys between users, run `python scripts/port_user_llm_stack.py apply --from … --to … --confirm PORT`.

- **`ZENAF_OPERATOR_BRIEF_ENABLED`** — When `0`, `false`, `no`, or `off` (case-insensitive), council **does not** load `local_ai/context/operator_brand_brief.md` for operator priorities (even if the file exists). When unset, loading is **enabled** (backward compatible). See `local_ai/context/operator_context.py`.



## Endpoints (overview)



- **POST /run** — Run one cockpit mode. Body: `{ "mode": "analyze", "params": { "folder_path": "..." } }`. **Does not** use per-user LLM settings; continues to use the default provider (Ollama).

- **GET /health** — Health check.

- **POST /auth/login**, **POST /auth/logout**, **GET /auth/me**, **PATCH /auth/me** — Session cookie auth; PATCH updates `display_name` (min 1 char).

- **Dev users** — On first Vision Execution DB init, **`owner@local.zenaf`** (admin) is created if missing. Password: `ZENAF_BOOTSTRAP_PASSWORD` or fallback `local-dev-owner`. **Changing `.env` later does not change existing password hashes.** If login fails, try `local-dev-owner`, or run `python scripts/set_dev_user_password.py --email owner@local.zenaf --password <new>` (API off). **Change bootstrap passwords before any shared or public deployment.**

- **POST /auth/admin/users** — Admin only (session cookie). JSON body: `email`, `password`, optional `display_name`, optional `is_admin`. Creates another login account.

- **GET/PUT /settings/llm**, **PUT /settings/llm/profile**, **PUT /settings/llm/credentials/{provider}**, **POST /settings/llm/test**, **GET/PUT /settings/notifications** — Authenticated user settings (see `api/routes/settings_routes.py`).



## Phase 1A Auth Scope (Transitional)



- Only `content_briefs` and `core_profiles` are user-scoped in Phase 1A.

- Other Vision Execution entities (ideas, initiatives, projects, tasks, people, assets, decisions, signals) are still unscoped.

- Mixed-scope behavior is temporary and will be unified in a later phase.



## MVP note



The original MVP note in this file referred to analyze-only; the cockpit now exposes many modes. See `docs/01_TRUTH/CODEBASE_INVENTORY.md` for current surface area.


