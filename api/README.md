# Atria API



Thin FastAPI bridge for the cockpit frontend. Calls the existing `local_ai` engine; no duplicated business logic.



## Setup



From the **Atria repo root**:



```bash

pip install -r api/requirements.txt

```



Dependencies include **`cryptography`** (Fernet) for encrypting user LLM API keys stored via `/settings`.



## Run



From the **Atria repo root** (so `local_ai` is importable):



```bash

uvicorn api.main:app --reload --host 0.0.0.0 --port 8010

```



- API: http://localhost:8010

- Docs: http://localhost:8010/docs



## Environment (Settings / LLM keys)



- **`ATRIA_SETTINGS_ENCRYPTION_KEY`** — Fernet key (URL-safe base64-encoded 32-byte key). Required to **store** LLM API keys via `PUT /settings/llm/credentials/{provider}`. If missing or invalid, those requests return **503** with a clear message (no plaintext storage).
- **`ATRIA_OPERATOR_BRIEF_ENABLED`** — When `0`, `false`, `no`, or `off` (case-insensitive), council **does not** load `local_ai/context/phil_brand_brief.md` for operator priorities (even if the file exists). When unset, loading is **enabled** (backward compatible). See `local_ai/context/phil_context.py`.



## Endpoints (overview)



- **POST /run** — Run one cockpit mode. Body: `{ "mode": "analyze", "params": { "folder_path": "..." } }`. **Does not** use per-user LLM settings; continues to use the default provider (Ollama).

- **GET /health** — Health check.

- **POST /auth/login**, **POST /auth/logout**, **GET /auth/me**, **PATCH /auth/me** — Session cookie auth; PATCH updates `display_name` (min 1 char).

- **Dev users** — On first Vision Execution DB init, **`owner@local.atria`** (admin) and **`phil@local.atria`** / display **Phil** (non-admin) are created if missing. Passwords: `ATRIA_BOOTSTRAP_PASSWORD` or fallback `local-dev-owner`; `ATRIA_PHIL_BOOTSTRAP_PASSWORD` or fallback `phil-local-dev`.

- **POST /auth/admin/users** — Admin only (session cookie). JSON body: `email`, `password`, optional `display_name`, optional `is_admin`. Creates another login account.

- **GET/PUT /settings/llm**, **PUT /settings/llm/profile**, **PUT /settings/llm/credentials/{provider}**, **POST /settings/llm/test**, **GET/PUT /settings/notifications** — Authenticated user settings (see `api/routes/settings_routes.py`).



## Phase 1A Auth Scope (Transitional)



- Only `content_briefs` and `core_profiles` are user-scoped in Phase 1A.

- Other Vision Execution entities (ideas, initiatives, projects, tasks, people, assets, decisions, signals) are still unscoped.

- Mixed-scope behavior is temporary and will be unified in a later phase.



## MVP note



The original MVP note in this file referred to analyze-only; the cockpit now exposes many modes. See `docs/01_TRUTH/CODEBASE_INVENTORY.md` for current surface area.


