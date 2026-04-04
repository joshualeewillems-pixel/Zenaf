# Codebase Truth Rules

Laws for future work so **branches stay branches** and do not grow into second trunks.  
Plain facts about **current** code — not a target architecture.

### In case of conflict

- **Runtime behavior** beats aspirational docs.
- **Truth rules** beat older deep-dive docs.
- **`docs/01_TRUTH/CODEBASE_INVENTORY.md`** names the current structure; **this file** governs future changes.
- When **code** violates these rules, either **fix the code** or **update the rule** here explicitly — do not “interpret around” silence.

---

## 1. LLM routing law

- **`get_default_provider()`** (`local_ai/providers/__init__.py`) — use for **`/run`** and anything that must stay **identical to today’s global default** (Ollama config from env / provider module) **when no execution seam is active**. During **`apply_seam_routing`** (`local_ai/execution_policy/seam_routing.py`), overrides may replace the default (Ollama model token, OpenAI instance). Today this includes bulk of **`local_ai/atria_tools.py`** (council, web research paths that call it), **`local_ai/vision_execution/meeting_extract.py`**, **`local_ai/vision_execution/core_profile_conversation.py`**, **`local_ai/vision_execution/core_profile_reconcile.py`**, unless a deliberate change is made and documented.

- **`get_llm_adapter_for_user(user_id)`** (`local_ai/llm/resolver.py`) — use when the call chain **already has `user_id`** and the product decision is “honor stored LLM profile + keys + **provider enable prefs**.” **`get_provider_shim_for_legacy_generate(user_id)`** wraps that for code that expects `.generate(prompt, timeout=...)`. Today: **`local_ai/vision_execution/idea_evaluate.py`**, **`local_ai/vision_execution/initiative_evaluate.py`**, and **`distill_content_source`** (and any other path in `atria_tools` explicitly wired to the resolver).

- **`/run`** — **Routed** requests (`routing_context` present, see **`api/main.py` `_begin_run_routing`**) may use the **session user’s saved OpenAI key** (after env `OPENAI_API_KEY`) and pass **`council_user_id`** into council for **per-seat** LLM resolution (`build_council_seat_provider`). **Non-routed** `/run` modes remain **default provider only** unless extended here and in **`api/main.py`** together.

- **`DefaultProviderAdapter`** (`local_ai/llm/adapter.py`) means “same as **`get_default_provider().generate`**”; **`get_llm_adapter_for_user(None)`** falls through to defaults when no user or no key.

---

## 2. JSON parsing law

- **Brace-aware extraction from messy LLM text** — today implemented as **`_extract_json_object`** in **`local_ai/vision_execution/idea_evaluate.py`**. **Initiative evaluation** imports it (`initiative_evaluate.py`); **do not** reimplement `index("{")` / `rindex("}")` slicing for nested JSON.

- **Schema + validation** stays **feature-local**: idea contract in **`idea_evaluate.py`** (`CONTRACT_KEYS`, `_validate_contract`, etc.); initiative contract in **`initiative_evaluate.py`**; meeting extract stays in **`meeting_extract.py`**.

- **Shared vs local:** only move extraction to a shared module **after** a second feature needs the same primitive **and** bugs repeat; until then, **import `_extract_json_object` from `idea_evaluate`** or duplicate the law in comments — do not invent a “framework.”

---

## 3. Settings law

- **`/auth`** (`api/routes/auth_routes.py`) — **session identity only**: login, logout, **`GET /auth/me`**, **`PATCH /auth/me`** (e.g. display name). No LLM keys, no notification JSON blobs.

- **`/settings`** (`api/routes/settings_routes.py`, mounted in **`api/main.py`**) — **user prefs and secrets**: LLM profile, encrypted provider credentials (Fernet + **`ATRIA_SETTINGS_ENCRYPTION_KEY`**), notification **`prefs`**, **`POST /settings/llm/test`**. Storage: **`local_ai/vision_execution/storage.py`** (same SQLite family as VE entities).

---

## 4. API client law

- **Vision Execution UI** — use **`VISION_EXECUTION_API`** (`frontend/src/vision-execution/types.ts`, currently **`'/vision-execution'`**) + **`credentials: 'include'`** for session. Relies on dev proxy ( **`frontend/vite.config.ts`**: `/vision-execution`, `/auth`, `/settings`, `/run` → backend).

- **Organizer / intake / direct `/run` from `App.tsx`** — today uses **`API_BASE`** (`http://127.0.0.1:8010` in **`frontend/src/App.tsx`**). **Rule:** new cockpit code must match the **same pattern as its view** (VE subtree = relative + proxy; organizer = `API_BASE` until unified). **Do not** introduce a third convention without replacing the other two in the same change.

---

## 5. Persistence law

- **Intake** — **`local_ai/intake/mirror.py`**, DB **`intake_mirror.db`** (repo root). **Startup:** **`api/main.py` `_on_startup`** → **`mirror.load_into_memory()`** repopulates queue + judgment. Runtime truth is in-memory + write-through to mirror.

- **Vision Execution** — **`data/vision_execution/vision_execution.db`**, **`local_ai/vision_execution/storage.py`**. **No init at API startup**; **`get_connection()`** / first use runs schema from **`schema.sql`**.

- **Rule:** do not assume “DB is warm at boot” for VE; do assume mirror reload for intake after restart.

---

## 5b. Identity and judgment law

- **Universal identity + structured judgment** for council, node memory, and related seams: **`local_ai/judgment_substrate.py`** — **SubjectRef**, **JudgmentTrunk** / SeatJudgment, CouncilRunArtifact, etc. VE row **dicts** remain the persistence/API shape at boundaries unless a feature explicitly maps to SubjectRef.

- **`local_ai/node_adapters.py`** and **`local_ai/subject_adapters.py`** are **tombstoned (retired).** Do **not** adopt, import, or extend them. Any doc or plan that treated them as “next wiring” is superseded by **SubjectRef + JudgmentTrunk** + existing VE storage (e.g. `node_vitality`, `council_stream_runs`).

---

## 5c. Coordination layer (activity + execution_flow_reading) — do not mis-map

- **Purpose:** Cheap, auditable signals for “how execution is going” without a second prompt trunk or a new currency DB. Two primitives only: **`ActivityEvent`** in **`activity.log`** (`local_ai/activity.py`) and **`node_judgment_history`** rows whose trunk verdict kind is **`execution_flow_reading`** (`local_ai/vision_execution/coordination_signals.py` → **`append_execution_flow_reading`** → **`append_node_judgment`**).

- **`ActivityEvent.source`** (JSONL) is **not** the same string family as judgment **`coordination_evidence_source` / `evidence_source`** in observation context. Server checkpoints use **`server-execution`**; client-reported checkpoints use **`atria-client-trace`**. Council-linked judgments use **`council_stream`** only with **`pointer_kind=council_stream_run`**.

- **Council pointer contract (truth-critical):** For **`pointer_kind=council_stream_run`**, **`observation.pointer`** and **`refs.council_stream_run_id`** must be the **primary key** **`council_stream_runs.id`** — i.e. the return value of **`append_council_stream_run`** in **`local_ai/vision_execution/storage.py`**. Do **not** use **`integrity_run_id`**, client correlation ids, or the meta key name **`council_artifact_id`** as if it were a different id space: today the stream still echoes that key in done metadata, but the **value** must remain the **`council_stream_runs` row id**. **`append_execution_flow_reading`** rejects pointers that do not resolve via **`get_council_stream_run_for_user`**.

- **Client assembly:** **`buildDevelopmentalGuidanceContext`** may ingest **`GET /vision-execution/coordination/execution-flow-readings`** as **evidence bullets** and **at most light hypothesis enrichment** — it must **not** drive map triad numbers or visible “flow scores” in v1.

- **Global audit:** Do **not** wrap every **`append_node_judgment`** call site; only **`execution_flow_reading`** is funneled through **`append_execution_flow_reading`**. Other judgment kinds remain feature-local until a deliberate audit.

---

## 6. Branch law

- **Branch (allowed):** a **router + storage + `local_ai` module family** that answers one product area (e.g. **`/intake/*`**, **`/vision-execution/*`**, **`/settings/*`**) and calls **trunk** (`local_ai`, FastAPI) without re-owning the whole stack.

- **Accidental second trunk (forbidden pattern):** a parallel **entrypoint**, **duplicate global LLM selector**, **second “the” user store**, or **copy-paste persistence boot** for the same domain. **Symptoms:** same policy implemented in two places (e.g. new `get_provider_*`); new global singleton DB loader for VE; frontend that bypasses **`VISION_EXECUTION_API`** / **`API_BASE`** with ad-hoc origins scattered in new files.

---

## 7. Documentation law

- **Canonical system overview + build/tooling notes:** **`docs/01_TRUTH/CODEBASE_INVENTORY.md`** (states what exists; points to **`api/README.md`**, **`frontend/README.md`**).

- **Path tree:** **`docs/FILE_TREE_OVERVIEW.md`**.

- **Boot / mirror behavior:** **`docs/01_TRUTH/BOOT_FLOW.md`**.

- **Zenaf / single-voice council (response trunk + integration):** **`CODEBASE_TRUTH_RULES.md`** §9; narrative **`docs/01_TRUTH/SYSTEM_REFERENCE.md`** §2.7 / §3.6.

- **Supporting deep dives:** everything else under **`docs/*.md`** for a single concern (council, intake design, VE tabs, etc.). **Do not** treat them as the master truth if they contradict **`CODEBASE_INVENTORY.md`** — fix or mark stale.

- **Core profile reconcile / conversation:** Evidence ordering, end-of-prompt **FINAL OVERRIDE**, and deterministic note compression are defined in **`docs/02_ACTIVE_DESIGN/CORE_PROFILE_ARCHITECTURE.md`**. Changes to those behaviors should stay **without** new LLM round-trips for “compression” unless product explicitly expands scope.

---

## 8. Refactor trigger law

**Reconcile a seam (minimal change, no rewrite)** only when:

| Symptom | Minimal reconciliation |
|--------|-------------------------|
| **`/run` or council picks up user API keys** | Restore **`get_default_provider`**-only path; audit **`atria_tools`** call chain. |
| **Wrong host in prod: VE vs organizer** | One frontend config for API origin; keep backend unchanged. |
| **Second JSON slice bug** (nested `{` / partial object) | Shared `extract_json` helper; **do not** merge idea vs meeting contracts. |
| **Contributors use `local_ai/adapters.get_adapter` for LLM** but hot path never did | Document “registry optional” or wire **one** call site — pick one. |
| **Cross-user data in VE** | Incremental **`user_id`** filters in **`storage.py`**, not a new platform layer. |

**Do not** open a “unification” project until one of the above **fires**; until then **document the rule** (this file + comments at **`resolver.py`** / **`get_default_provider`**).

---

## 9. Zenaf / single-voice council — response contract trunk

- **Turn-specific system contract** for the conversational (all–Thinking Partner) path lives in **`local_ai/response_trunk.py`**: `build_response_control_block` prepends **RESPONSE CONTRACT — TECHNICAL HEADER** to the Zenaf system layer (`COUNCIL_CONVERSATIONAL_PARTNER_SYSTEM` in **`local_ai/atria_tools.py`**). Contract fields: **`mode_directives`** (incl. **field checklist** / **PRIORITY AMNESIA** when applicable), **`syntax_rules`**, **`grounding_fences`**.

- **Do not** reintroduce duplicate “nuclear” syntax blocks in ad-hoc prompts for that path; extend **`response_trunk`** or **`local_ai/conversation_trunk.py`** and keep **`atria_tools`** as the assembler.

- **Precision integration** (`[DRAFT_VALUE: …]`, pending commit, VE writes) is defined in **`local_ai/integration_commit.py`**. Backend may **auto-fill** a missing draft in a **narrow** case (e.g. task **description** empty + inferrable summary) instead of failing the turn silently.

- **Single-voice LLM timeout** for `_run_council_conversational_partner_body` is **15 seconds** (product: keep prompts small enough to finish in that budget).

---

*Last aligned with repo patterns: 2026-04-02 — coordination §5c (`coordination_signals.py`, `storage.get_council_stream_run_for_user`, `App.tsx` + `buildDevelopmentalGuidanceContext` execution-flow readings); FastAPI `api/main.py` (`_begin_run_routing`, `council_user_id`), `local_ai/execution_policy/seam_routing.py`, `local_ai/llm/provider_registry.py`, `local_ai/llm/resolver.py`, `local_ai/providers/__init__.py`, `idea_evaluate.py`, `initiative_evaluate.py`, core profile prompt modules (`core_profile_reconcile.py`, `core_profile_conversation.py`, `local_ai/delegation/core_profile_reconcile.py`), `frontend/src/vision-execution/types.ts`, `frontend/src/App.tsx`; **Zenaf trunk:** `local_ai/response_trunk.py`, conversational path in `local_ai/atria_tools.py` (`COUNCIL_CONVERSATIONAL_PARTNER_SYSTEM`, `_run_council_conversational_partner_body`), `local_ai/integration_commit.py` (`infer_draft_value_from_context`), `frontend/src/components/EntityMentionText.tsx`.*
