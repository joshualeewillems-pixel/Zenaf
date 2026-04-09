# Zenaf Boot Flow

<!--
Last updated: 2026-04-04 — mirror_sync / perspectives aligned with poll path + TRUTH_CONVERGENCE.
-->

What happens on startup and during normal operation. Based on the current codebase.

---

## 1. Startup Sequence

1. **Process start**  
   - `uvicorn api.main:app --reload --host 127.0.0.1 --port 8010` (or via `open-cockpit.ps1`).

2. **Path setup**  
   - `api/main.py` inserts repo root into `sys.path` so `local_ai` and `tools` are importable.

3. **Router registration**  
   - Vision Execution router: `api.routes.vision_execution.router` (prefix `/vision-execution`) — loaded in try/except.  
   - Intake router: `api.routes.intake_routes.router` (prefix `/intake`) — loaded in try/except.  
   - Auth router: `api.routes.auth_routes.router` (prefix `/auth`) — login, logout, `GET/PATCH /auth/me`.  
   - Settings router: `api.routes.settings_router` with **`prefix="/settings"`** — LLM profile, encrypted credentials, test, notification prefs (each in try/except like other routers).  
   - Transcript, transcribe, and Studio routers as in `api/main.py`.

4. **`@app.on_event("startup")` → `_on_startup()`**  
   - **Step A:** `_check_startup_dependencies()`  
     - Imports: `pandas`, `duckduckgo_search`, `local_ai`, `local_ai.zenaf_tools`, `local_ai.providers`.  
     - Prints ok/fail per module; does not abort the process.  
   - **Step B:** `mirror.load_into_memory()`  
     - If `intake_mirror.db` does not exist: returns `False`; nothing loaded.  
     - If it exists:  
       - `local_ai.judgment.clear_records()`.  
       - Load all rows from `mirror_judgment` into the in-memory judgment store via `add_record()`.  
       - Load all rows from `mirror_item` into the in-memory queue via `queue_store.replace_with_items()`.  
     - Idempotent; safe to call once per startup.

5. **Vision Execution DB**  
   - Not opened or migrated at API startup.  
   - First request that hits `local_ai.vision_execution.storage` triggers `get_connection()` → `init_db(conn)` and schema creation from `schema.sql`.  
   - During init, `_ensure_default_owner_and_backfill` creates **`owner@local.zenaf`** (admin) when missing, then **`phil@local.zenaf`** / display **Phil** (non-admin) when missing — for local multi-user checks. Passwords: `ZENAF_BOOTSTRAP_PASSWORD` or dev fallback `local-dev-owner`; `ZENAF_PHIL_BOOTSTRAP_PASSWORD` or dev fallback `phil-local-dev`.  
   - Admins may create additional accounts via **`POST /auth/admin/users`** (cookie session of an admin user required).

---

## 2. What Loads From the Persistent Mirror

- **Intake mirror** (`intake_mirror.db`):  
  - **mirror_judgment** → in-memory judgment layer (`local_ai.judgment`).  
  - **mirror_item** → in-memory queue (`local_ai.intake.queue_store`).  
  - Only Tier A fields are present in the in-memory queue; Tier B (`sanitized_body_text`) is in the DB but not in the in-memory item dicts when loaded (see `_dict_from_item_row(..., include_tier_b=False)` in `mirror.py`).

- **Not loaded at startup:**  
  - `mirror_sync` (poll cursors / last poll time) — **written** on successful poll (`set_sync_state` after readonly IMAP `SELECT`); rows are **not** bulk-loaded into RAM at boot (read on demand if needed).  
  - `mailbox_action` — audit log; read when needed, not loaded into memory at boot.

---

## 3. What Remains In-Memory Only

- **Queue working set:** The list and dict in `queue_store` (`_order`, `_items`) are the runtime source for GET queue and PATCH item. They are rebuilt from the mirror on startup and updated on add/update; they are not read again from disk on each request.
- **Judgment store:** The in-memory dicts in `local_ai.judgment` are the runtime source for “get judgment for entity” and supersession chains. Persistence is write-through from queue_store and mirror (see below).
- **Perspectives / council:** Signed-in users hydrate seat definitions from **`GET /vision-execution/council-workspace/perspectives`** (`user_council_workspace`); `localStorage` is cache + anonymous fallback. Council **packets** and Zenaf contracts are assembled server-side (`council_preflight`, `response_trunk`, `integration_commit`); see **`TRUTH_CONVERGENCE.md`** and **`CODEBASE_TRUTH_RULES.md`** §9.
- **File Steward:** No persistent store; each call is stateless (folder path → result).

---

## 4. When Polling Happens

- **No automatic poll on startup or on a timer.**  
- Poll runs only when the client calls **POST /intake/email/poll** (e.g. from the cockpit “Email Intake” flow).  
- Implementation: `intake_routes` → `email_ingestion.poll_ingest_emails()` → for each mailbox config, `_poll_one_mailbox()` → for each message, `run_pipeline()` → `queue_store.add_item()` (which also writes to the mirror).  
- **Sync telemetry:** After a successful readonly IMAP connect + `SELECT`, `_poll_one_mailbox` calls `mirror.set_sync_state(...)` with a stable id per mailbox source and UTC `last_poll_at`. `cursor` is reserved for a future UID/cursor strategy (not set in v1).

---

## 5. How Queue Items Are Created and Updated

- **Create:**  
  - Ingest path: `poll_ingest_emails` → `run_pipeline()` → `IntakeItem` → `queue_store.add_item(item)`.  
  - `add_item()`: (1) writes to in-memory `_items` and `_order`, (2) calls `mirror.upsert_item(d, sanitized_body_text=...)` and `mirror.upsert_judgment_chain_for_entity(item.id)`.  
  - Manual ingest: POST /intake/email or POST /intake/fax → same pipeline → same `add_item()`.

- **Update:**  
  - PATCH /intake/queue/{item_id} → `queue_store.update_item(item_id, ...)`.  
  - `update_item()`: (1) updates in-memory `_items[item_id]`, (2) if `lane_override` + `correction_note` are provided, calls `create_correction_record()` and sets `judgment_id` on the item, (3) calls `mirror.upsert_item(d)` and `mirror.upsert_judgment_chain_for_entity(item_id)`.

So: **in-memory queue and judgment store are the source of truth at runtime;** the mirror is updated on every add and update (write-through). On restart, the mirror is the source of truth and repopulates memory.

---

## 6. How Judgments Are Persisted

- **Creation:**  
  - When an item is first added, `create_intake_judgment()` is called from the pipeline (in `run_pipeline`), and the returned `judgment_id` is set on the item.  
  - `add_item()` then calls `mirror.upsert_judgment_chain_for_entity(item.id)`, which loads all in-memory judgment records for that entity and calls `mirror.upsert_judgment_record(r.to_dict())` for each.

- **Correction (override):**  
  - When the user sets a lane override with a correction note, `update_item()` calls `create_correction_record(entity_id, supersedes_judgment_id=..., proposed_action_override={...}, correction_note=...)`.  
  - The new record is linked via `superseded_by` on the previous record.  
  - Then `mirror.upsert_judgment_chain_for_entity(item_id)` again persists all records for that entity.

- **Persistence:**  
  - Judgment records live in `local_ai.judgment` in memory.  
  - The **only** persistent copy is in `mirror_judgment` in `intake_mirror.db`.  
  - There is no separate “judgment service” that writes to its own DB; intake mirror owns judgment persistence.

---

## 7. How Overrides / Corrections Work

- **Lane override:**  
  - Stored on the queue item as `lane_override`.  
  - If the UI displays “effective lane”, it should show `lane_override` when set, else `lane`.  
  - When the user sets both `lane_override` and `correction_note`, a new judgment record is created with `create_correction_record()` (superseding the previous judgment), and the item’s `judgment_id` is updated to this new record.  
  - Both the updated item and the full judgment chain for that entity are written to the mirror by `update_item()` → `mirror.upsert_item()` and `mirror.upsert_judgment_chain_for_entity()`.

- **Other fields:**  
  - `status`, `notes`, `assigned_to`, `archived` are editable via PATCH and persisted to the mirror via `upsert_item()`; they do not create a new judgment record.

---

## 8. Source of Truth by Subsystem

| Subsystem | Runtime source of truth | Persistent source of truth | Notes |
|-----------|--------------------------|----------------------------|-------|
| Intake queue (list, item fields) | `queue_store._items`, `_order` | `intake_mirror.db` → `mirror_item` | Rebuilt from mirror on startup; write-through on add/update. |
| Intake judgments | `local_ai.judgment` in-memory store | `intake_mirror.db` → `mirror_judgment` | Rebuilt from mirror on startup; write-through when item is added/updated. |
| Intake sync state | N/A (not a hot in-memory cache) | `mirror_sync` table | Updated after successful poll (`set_sync_state`); `mailbox_action` still unwired until mailbox mutations exist. |
| Mailbox actions | N/A | `mailbox_action` table | Audit only; no in-memory cache. |
| Vision Execution (ideas, initiatives, etc.) | N/A (stateless read/write) | `data/vision_execution/vision_execution.db` | Each API call reads/writes via storage layer. Includes **user_llm_profile**, **user_llm_provider_credentials** (encrypted), **user_notification_settings**, **`user_council_workspace`** (perspective agent JSON when signed in). |
| Council / perspectives (seat definitions) | React state hydrated from API or `localStorage` | `user_council_workspace.perspectives_json` per user | Signed-in: **`GET`/`PUT /vision-execution/council-workspace/perspectives`**. Anonymous: `localStorage` only. Each `/run` still assembles council **packet + Zenaf contract** server-side (`response_trunk`, `integration_commit`); see **`docs/01_TRUTH/CODEBASE_TRUTH_RULES.md`** §9. |
| File Steward | N/A | None | Stateless per request. |

---

## 9. Operational Scripts

- **open-cockpit.bat / open-cockpit.ps1:** Start API in one window, frontend in another, then open browser to app and API docs. No DB init or poll; just process start.
- **scripts/seed_vision_execution.py:** Seeds Vision Execution DB; run manually.
- **scripts/dump_needs_attention.py, review_intake_failures.py, evaluate_intake_synthetic_data.py, generate_*_synthetic*.py:** CLI tools; do not run at boot.
