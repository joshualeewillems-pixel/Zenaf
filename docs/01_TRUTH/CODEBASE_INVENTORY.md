# Atria Codebase Inventory

Comprehensive inventory of implemented modules, files, responsibilities, and current status. Based on the current repository state.

**Use this doc as the primary “overview + build/tooling notes”** for the repo (including frontend `npm run build`, `tsconfig` policy, Vite proxy paths, Settings API, and env vars). Pair with **`docs/FILE_TREE_OVERVIEW.md`** for a path-level tree. For **what is partial, stubbed, or next on the roadmap**, pair with **`docs/01_TRUTH/ACTIVE_VS_PLANNED.md`**. For **locked source-of-truth ownership**, pair with **`docs/01_TRUTH/TRUTH_CONVERGENCE.md`**. Run/setup quickstarts: **`api/README.md`**, **`frontend/README.md`**. **Enforcement-style laws** (LLM routing, persistence, branches vs trunks): **`CODEBASE_TRUTH_RULES.md`** (same folder).

---

## 1. API / Routes

| Item | Details |
|------|---------|
| **Module/directory** | `api/` |
| **Purpose** | FastAPI bridge to local_ai engine; HTTP endpoints for cockpit frontend. |
| **Key files** | `api/main.py` (app, startup, `/run`, `/run/stream`, `_begin_run_routing` / `routing_context` / `council_user_id`, `/health`), `api/routes/intake_routes.py`, `api/routes/vision_execution.py`, `api/routes/auth_routes.py` (session, `/auth/me` incl. PATCH display name, admin **`POST /auth/admin/users`**), `api/routes/settings_routes.py` (mounted at `/settings`) |
| **Main entry points** | `uvicorn api.main:app`; `app.on_event("startup")` → `_on_startup()`; `POST /run` dispatches by `mode` to atria_tools. |
| **Important functions** | `_on_startup()`, `_check_startup_dependencies()`, `run()`, `run_stream()`, intake/vision-execution/auth/settings route handlers. |
| **Status** | **Implemented.** Vision Execution and Intake routers are mounted. |
| **Dependencies** | `local_ai` (atria_tools, intake, judgment, vision_execution, providers). |
| **Gaps/caveats** | No explicit route that calls `mirror.get_item_with_content()`; intake queue returns Tier A only from `get_queue`/`get_item` (**product contract** — see **`TRUTH_CONVERGENCE.md`** / **`ACTIVE_VS_PLANNED.md`**). |

---

## 2. Intake

| Item | Details |
|------|---------|
| **Module/directory** | `local_ai/intake/` |
| **Purpose** | Clinic email/fax → classification, PHI detection, redaction → structured queue items. Mirror-only (no mailbox mutation). |
| **Key files** | `pipeline.py`, `queue_store.py`, `email_ingestion.py`, `mirror.py`, `classifier.py`, `redaction.py`, `lanes.py`, `email_router.py`, `fax_router.py`, `gmail_oauth.py`, `access_policy.py` (shim) |
| **Main entry points** | `run_pipeline()`, `add_item()` / `get_queue()` / `update_item()` / `get_by_external_id()`, `poll_ingest_emails()`, `load_into_memory()` (mirror), `process_email()` / `process_fax()`. |
| **Important classes/functions** | `IntakeItem` (pipeline), `classify()` (classifier), `detect_phi()` / `redact()` (redaction), `derive_lane()` (lanes), `upsert_item()` / `load_into_memory()` / `get_item_with_content()` (mirror). |
| **Status** | **Implemented.** End-to-end: ingest → pipeline → queue → mirror; startup loads mirror into memory. |
| **Dependencies** | `local_ai.judgment`, `local_ai.policy.data_access` (via mirror.get_item_with_content), `local_ai.intake.mirror`. |
| **Gaps/caveats** | Poll is on-demand only (POST /intake/email/poll); no background poll. No mailbox mutation. |

---

## 3. Mirror / Persistence

| Item | Details |
|------|---------|
| **Module/directory** | `local_ai/intake/mirror.py` (intake mirror); `local_ai/vision_execution/storage.py` (Vision Execution DB). |
| **Purpose** | Intake: SQLite `intake_mirror.db` as durable operational memory (items, judgments, sync state, mailbox_action). Vision Execution: SQLite `data/vision_execution/vision_execution.db`. |
| **Key files** | `local_ai/intake/mirror.py`, `local_ai/vision_execution/storage.py`, `local_ai/vision_execution/schema.sql` |
| **Main entry points** | `init_schema()`, `upsert_item()`, `upsert_judgment_record()` / `upsert_judgment_chain_for_entity()`, `load_into_memory()`, `get_item_with_content()`, `set_sync_state()` / `get_sync_state()`, `record_mailbox_action()`. |
| **Important functions** | `_conn()`, `_migrate_schema()`, `_dict_from_item_row()`. Vision: `get_connection()`, `init_db()`, full CRUD per entity (core_profiles, ideas, initiatives, projects, tasks, persons, assets, decisions, capacity_profiles), plus **`execution_steps`** (first-class checklist per initiative/project scope), plus user settings tables: **`user_llm_profile`** (includes **`llm_provider_prefs_json`**: per-provider enable flags and **`__council_seats`** seat→`llm_provider` map), **`user_llm_provider_credentials`** (Fernet-encrypted keys when `ATRIA_SETTINGS_ENCRYPTION_KEY` is set), **`user_notification_settings`** (JSON prefs). |
| **Status** | **Implemented.** Intake mirror: schema with mirror_item, mirror_judgment, mirror_sync, mailbox_action; Tier A/B/C columns; migration for existing DBs. Vision: full schema and CRUD. |
| **Dependencies** | Intake mirror: `local_ai.judgment`, `local_ai.policy.data_access` (for get_item_with_content), `queue_store.replace_with_items`. Vision: `local_ai.vision_execution.models`. |
| **Gaps/caveats** | `mirror_sync` and `mailbox_action` are not yet wired to poll (set_sync_state not called after poll). Raw Tier C storage is placeholder only (`raw_content_ref`). |

---

## 4. Judgment Layer

| Item | Details |
|------|---------|
| **Module/directory** | `local_ai/judgment/` |
| **Purpose** | Shared protocol for reasoning events: one record per interpretation/action; supersession for corrections. Intake domain only in implementation. |
| **Key files** | `local_ai/judgment/__init__.py`, `local_ai/judgment/README.md` |
| **Main entry points** | `create_intake_judgment()`, `create_correction_record()`, `add_record()`, `clear_records()`, `get_record()`, `get_for_entity()`, `get_supersession_chain()`. |
| **Important classes** | `JudgmentRecord` (id, domain, entity_id, interpretation, proposed_action, confidence, signal/interpretation/policy codes, observation_ref, superseded_by, correction_note). |
| **Status** | **Implemented.** In-memory store only; persistence is via intake mirror (mirror writes/reads judgment records). |
| **Dependencies** | None (used by intake pipeline and queue_store/update_item). |
| **Gaps/caveats** | No generic multi-domain persistence in judgment layer itself; intake mirror holds the only persistent copy of judgment data. |

---

## 5. Policy / Data Access

| Item | Details |
|------|---------|
| **Module/directory** | `local_ai/policy/data_access.py`; `local_ai/intake/access_policy.py` (shim). |
| **Purpose** | Shared data access policy: Tier A/B/C, local vs external destination, justification for raw. Prevent accidental outward leakage; do not overconstrain local workflows. |
| **Key files** | `local_ai/policy/data_access.py` |
| **Main entry points** | `request_access(level, justification=..., destination=...)`, `require_access(...)`, `access_level_to_tier()`, `tier_satisfies()`. Constants: `METADATA_ONLY`, `SANITIZED_TEXT`, `RAW_CONTENT_REQUIRED`, `DEST_LOCAL`, `DEST_EXTERNAL`. |
| **Important** | `DataTier` enum; destination parameter added for future egress gating; Tier C requires justification unless `allow_without_justification`. |
| **Status** | **Implemented.** Only intake mirror’s `get_item_with_content()` calls it. Council and File Steward do not use the policy layer yet. |
| **Dependencies** | None. |
| **Gaps/caveats** | No call site uses `destination="external"` yet. Documented “all modules must use” is not enforced; only intake mirror does. |

---

## 6. Adapters

| Item | Details |
|------|---------|
| **Module/directory** | `local_ai/adapters/` |
| **Purpose** | Thin connectors to external systems; registry by kind+name; protocols for LLM and Mailbox. |
| **Key files** | `local_ai/adapters/__init__.py`, `local_ai/adapters/README.md` |
| **Main entry points** | `register_adapter()`, `get_adapter()`, `get_adapter_optional()`, `list_adapters()`. `_register_defaults()` registers `llm.ollama` (OllamaProvider). |
| **Important** | `LLMAdapter` and `MailboxAdapter` protocols. No Mailbox adapter implementation is registered; intake uses `email_ingestion` + Gmail OAuth directly. |
| **Status** | **Partially implemented.** Registry and LLM default exist; mailbox/council/atria_tools do not go through adapters for their LLM or mailbox access. |
| **Dependencies** | `local_ai.providers.ollama`. |
| **Gaps/caveats** | Intake does not use `get_adapter("mailbox", ...)`; it uses `email_ingestion` and `gmail_oauth` directly. |

---

## 7. Storage

| Item | Details |
|------|---------|
| **Purpose** | Two persistent stores: (1) Intake mirror `intake_mirror.db` at repo root; (2) Vision Execution `data/vision_execution/vision_execution.db` (entities + **user LLM / notification settings** tables). |
| **Key files** | `local_ai/intake/mirror.py`, `local_ai/vision_execution/storage.py`, `local_ai/vision_execution/schema.sql` |
| **Status** | **Implemented.** Both SQLite; init on first use; Vision Execution uses `schema.sql`. |
| **Gaps/caveats** | Intake mirror path is `Path(__file__).resolve().parent.parent.parent / "intake_mirror.db"` (repo root). No configurable path. |

---

## 8. Frontend

| Item | Details |
|------|---------|
| **Module/directory** | `frontend/` (Vite + React + TypeScript). |
| **Purpose** | Cockpit UI: modes (analyze, recommend, assess, simulate, council, web research, next step, email/fax intake, ordering queue), perspectives, vision-execution view, **Settings** (account, **Model connections**: provider enable/disable, keys, test connection, **council seat** default LLM per seat id), notification prefs. |
| **Key files** | `frontend/src/App.tsx` (workspace + council UI: question **textarea**, answers **aside** with viewport-based height `calc(100vh-8rem)`, scrollable thread; Foundation detail/training/editor in a **Foundation-local right pane**, separate from the global council/chat aside), `frontend/src/settings/` (`SettingsView.tsx`, `sections/ModelConnectionsSection.tsx`, `api.ts`), `frontend/src/perspectives/`, `frontend/src/vision-execution/`, `frontend/package.json`, `frontend/vite.config.ts` (proxies `/auth`, `/settings`, `/run`, … to API), `frontend/tsconfig.json` |
| **Main entry points** | Single-page app; mode selection; POST `/run` / `/run/stream` with `mode`, params, and **`routing_context`** for policy seam on workspace flows. Council: per-seat **`llm_provider`** on `perspective_definitions` (Auto vs named provider); streaming. Intake: config, OAuth, poll, queue list, PATCH queue item, judgment chain. Auth gate + session cookies; Settings calls `/settings/*` and `PATCH /auth/me` for display name. |
| **Status** | **Implemented.** Large single App.tsx; perspectives, vision-execution, and settings are separate views. Ordering queue and intake flows are wired. |
| **Dependencies** | API at 8010; CORS allows localhost:5173. Dev server proxies `/auth`, `/settings`, `/run`, etc. (see `vite.config.ts`). |
| **Gaps/caveats** | No route in frontend that requests Tier B/C via `get_item_with_content` (**product contract:** Tier A only — **`TRUTH_CONVERGENCE.md`**). Notification prefs are stored only (no delivery pipeline). Non-council `/run` modes without `routing_context` still follow legacy default provider; see **`CODEBASE_TRUTH_RULES.md`** and **`docs/02_ACTIVE_DESIGN/POLICY_PROVIDER_EXECUTION.md`**. |

### 8b. Vision map (projection UI)

| Item | Details |
|------|---------|
| **Directory** | `frontend/src/vision-map/` |
| **Purpose** | Spatial **live projection** of VE entities (idea/initiative/project/task/outcome metaphor); optional zen sand rake; right panel **growth triad** (Water / Soil / Fruit) computed from existing payload + bundle. |
| **Key files** | `VisionMapView.tsx`, `liveProjection.ts`, `ontology.ts`, `mapGrowthMetrics.ts`, `MapGrowthTriad.tsx`, `MapChatShell.tsx`, `ZenSandCanvas.tsx`, `sandHeightField.ts`, `mapVitalForces.ts`, `mapAesthetics.css` |
| **Truth doc** | **`docs/01_TRUTH/VISION_MAP_AND_ZEN_PROJECTION.md`** — current state, direction, canonical file list. |
| **Status** | **Implemented** (client-only heuristics; no map-specific API). |

---

## 9. Council / Perspectives

| Item | Details |
|------|---------|
| **Module/directory** | Council: `local_ai/atria_tools.py` (`run_council`, `run_council_stream`), `local_ai/llm/council_seat_provider.py` (per-seat adapter from prefs + registry). Perspectives: frontend `frontend/src/perspectives/` (types, list, detail, creator, import/export). |
| **Purpose** | Multi-role or multi-perspective reasoning; optional Atria synthesis; **per-seat LLM** (Auto follows execution seam; explicit provider uses user keys when enabled in Settings). |
| **Key files** | `local_ai/atria_tools.py` (run_council, run_council_stream; **single-voice Zenaf** path `_run_council_conversational_partner_body` with **`COUNCIL_CONVERSATIONAL_PARTNER_SYSTEM`** = **System Interface** copy + **15s** `provider.generate` timeout), `local_ai/response_trunk.py` (**RESPONSE CONTRACT — TECHNICAL HEADER**: `syntax_rules`, `grounding_fences`, `mode_directives` incl. **field checklist**; **priority** turns require **`[DRAFT_VALUE]`** + **`[ID]`** in contract text), `local_ai/conversation_trunk.py` (mediation + trunk instructions), `local_ai/integration_commit.py` ( **`[DRAFT_VALUE: …]`** parsing, pending integration, `infer_draft_value_from_context` narrow auto-fill), `local_ai/council_preflight.py` (enriched council context; **`priority_resolution`** may omit prior thread — amnesia slice; optional **`developmental_guidance`**), `local_ai/developmental_guidance.py`, `local_ai/execution_policy/seam_routing.py` (`apply_seam_routing`: council + OpenAI primary but **no key** → **Ollama seam fallback** with `council_seam_fallback_ollama` meta), `local_ai/llm/provider_registry.py`, `frontend/src/perspectives/*`, `frontend/src/perspectives/types.ts`, `frontend/src/developmentalGuidance/*`, `frontend/src/components/EntityMentionText.tsx` (greedy **`[ID: …]`** regex → clickable entity chips in raw assistant text) |
| **Main entry points** | `run_council(..., council_user_id=...)`, `run_council_stream(..., council_user_id=...)`. API: `POST /run` and `/run/stream` with `mode=council`, **`routing_context`**, and session → **`council_user_id`** from cookie for seat resolution and OpenAI key (env then Settings). |
| **Status** | **Implemented.** Cockpit always sends ≥1 seat (default first seat **Thinking Partner**). All-TP runs: conversational output, no synthesis; mixed with structured roles: structured seats + optional synthesis. During routed council requests, `get_default_provider()` / `get_council_provider()` see policy overrides from **`apply_seam_routing`** (`api/main.py`); each seat may use **`build_council_seat_provider`** (registry + encrypted credentials). Unsupported or disabled providers yield a clear block for that seat rather than silent wrong model. |
| **Dependencies** | `local_ai.providers`, `local_ai.context.phil_context` (load_phil_context) for packet, `local_ai.vision_execution.storage` for profile/prefs when `council_user_id` set. |
| **Gaps/caveats** | Perspective **definitions** still live in frontend localStorage (`atria-perspective-agents`); only **seat→LLM defaults** persist server-side under `__council_seats`. Shared **data access policy** is not applied to council payloads. |

---

## 10. Ideas / Vision-to-Execution

| Item | Details |
|------|---------|
| **Module/directory** | `local_ai/vision_execution/` (service, storage, models, radar, derived, initiative_evaluate, meeting_extract); API `api/routes/vision_execution.py`. |
| **Purpose** | Ideas → initiatives → projects → tasks; people, assets, capacity; decisions; radar; core profiles. |
| **Key files** | `vision_execution/service.py`, `vision_execution/storage.py`, `vision_execution/models.py`, `vision_execution/radar.py`, `vision_execution/derived.py`, `vision_execution/initiative_evaluate.py`, `vision_execution/meeting_extract.py`, `vision_execution/schema.sql`; API includes **`GET`/`PUT /vision-execution/council-workspace/perspectives`** (server-owned council seat actor definitions). |
| **Main entry points** | Service pass-through to storage; `get_radar()`; API under `/vision-execution` prefix (CRUD + council workspace + learning signals). |
| **Status** | **Implemented.** Full CRUD and radar; separate DB from intake mirror. |
| **Execution steps** | **`execution_steps`** on the VE trunk: scoped checklist rows (`scope_type` initiative/project), API under `vision_execution` routes (`…/execution-steps`, materialize with explicit `replace`), initiative UI in `VisionExecutionView.tsx`; project scope API/storage without project checklist UI yet (`docs/02_ACTIVE_DESIGN/EXECUTION_STEPS_DESIGN.md`). |
| **Dependencies** | None on intake or policy. |
| **Gaps/caveats** | No use of shared policy layer. Idea/initiative evaluation can use `get_llm_adapter_for_user(user_id)` when the API passes `user_id` (see `local_ai/llm/resolver.py`). **Core profiles:** DB/API support **multiple** rows per user; **Perspectives → Foundation** UI lists them with **Add**. **Product direction:** one canonical core per workspace/person, perspectives as lenses — see **`docs/01_TRUTH/SYSTEM_REFERENCE.md`** §1.4a / **`docs/01_TRUTH/ACTIVE_VS_PLANNED.md`**. **Identity/judgment:** **`local_ai/judgment_substrate.py`** (SubjectRef, JudgmentTrunk, …) is the live primitive; **`node_adapters.py` / `subject_adapters.py`** are **tombstoned** — not for new wiring (see **`CODEBASE_TRUTH_RULES.md`** §5b). |

---

## 10b. User settings & per-user LLM (minimal layer)

| Item | Details |
|------|---------|
| **Purpose** | Authenticated **Settings**: account (email, display name via `PATCH /auth/me`, logout), **Model connections** (per-provider enable/disable, keys, default provider/model, test connection), **council seat** LLM mapping (`PUT /settings/llm/council-seats/{seat_id}`), notification JSON prefs (storage only). |
| **API** | `api/routes/settings_routes.py` → `GET /settings/llm` (includes `providers` status rows + `council_seat_providers`), `GET /settings/llm/providers`, `PUT /settings/llm/providers/{provider}` (enabled flag), `PUT /settings/llm/council-seats/{seat_id}`, `PUT /settings/llm/profile`, `PUT /settings/llm/credentials/{provider}`, `POST /settings/llm/test`, `GET/PUT /settings/notifications`. All require session. Credential writes return **503** if `ATRIA_SETTINGS_ENCRYPTION_KEY` is missing/invalid (no plaintext fallback). |
| **Storage** | `local_ai/vision_execution/schema.sql` + `storage.py`: Fernet encryption for keys; `llm_provider_prefs_json` merges **provider enabled** map and **`__council_seats`**; CRUD for profile, credentials, notifications. |
| **LLM routing** | **`local_ai/llm/provider_registry.py`** — `execution_provider_gate_message` (seam + council seats), `user_llm_adapter_gate_message` (resolver). **`local_ai/llm/resolver.py`** → `get_llm_adapter_for_user(user_id)` respects prefs; blocked adapters surface explicit messages. **`apply_seam_routing`** (`seam_routing.py`) — OpenAI primary uses `OPENAI_API_KEY` then saved user key when `user_id` is set; council-only fallback to Ollama when OpenAI unavailable (see §9). |
| **Frontend** | `frontend/src/settings/*` (`ModelConnectionsSection.tsx`); header **Settings** → `mainView === 'settings'`. |
| **Python deps** | `cryptography` in `api/requirements.txt` for Fernet. |

---

## 10c. Build specification (frontend)

| Item | Details |
|------|---------|
| **Scripts** | `npm run dev` — Vite dev server (default port 5173). `npm run build` — **`tsc -b` then `vite build`** → output under `frontend/dist/`. |
| **TypeScript** | `frontend/tsconfig.json`: `strict: true`; **`noUnusedLocals` / `noUnusedParameters` are `false`** so production build is not blocked by unused symbols across the large cockpit codebase (prefer fixing real type errors; re-enable stricter unused checks when cleaning dead code). |
| **Proxy (dev)** | `frontend/vite.config.ts`: **`/run`**, **`/auth`**, **`/vision-execution`**, **`/settings`** → `http://127.0.0.1:8010` so the SPA can use same-origin relative fetch with `credentials: 'include'`. |
| **Production** | Serve `dist/` behind any static host; API must allow CORS + cookies for the chosen origin, or use a reverse proxy that forwards `/auth` and `/settings` to the API. |

---

## 11. File Sorting / File Steward

| Item | Details |
|------|---------|
| **Module/directory** | `tools/file_steward/app.py` (Streamlit); orchestration in `local_ai/atria_tools.py`. |
| **Purpose** | Analyze folder, recommend children, assess uncertainty, simulate folder plan; optional LLM second pass. |
| **Key files** | `local_ai/atria_tools.py` (analyze_folder_structure, recommend_child_folders, assess_plan_strength, simulate_folder_plan, simulate_folder_plan_with_llm, reassess_low_confidence), `tools/file_steward/app.py` |
| **Main entry points** | `_get_steward_app()` lazy-imports `tools/file_steward/app`; atria_tools wraps app functions. POST /run modes: analyze, recommend, assess_uncertainty, simulate, reassess_low_confidence. |
| **Status** | **Implemented.** File Steward is a separate tool; atria_tools adds path and calls it. No policy layer. |
| **Dependencies** | `tools.file_steward.app` (sys.path), `local_ai.providers` for LLM second pass. |
| **Gaps/caveats** | File Steward runs as separate app or via atria_tools; not a registered adapter. |

---

## 12. Mailbox / Ingestion

| Item | Details |
|------|---------|
| **Module/directory** | `local_ai/intake/email_ingestion.py`, `local_ai/intake/gmail_oauth.py`. |
| **Purpose** | IMAP poll (read-only), Gmail OAuth; normalize body → pipeline → add_item. No mailbox mutation. |
| **Key files** | `email_ingestion.py` (MailboxConfig, get_imap_config, save_imap_config, _poll_one_mailbox, poll_ingest_emails), `gmail_oauth.py` (OAuth flow, token exchange, build_xoauth2_string). |
| **Main entry points** | `poll_ingest_emails()`, `get_imap_config()`, `save_imap_config()`; Gmail OAuth via API routes (callback, start, status). |
| **Status** | **Implemented.** Poll is on-demand (POST /intake/email/poll). Config from env or file `intake_imap_config.json`. |
| **Dependencies** | `local_ai.intake.pipeline.run_pipeline`, `local_ai.intake.queue_store.add_item`, `local_ai.intake.queue_store.get_by_external_id`. |
| **Gaps/caveats** | No background poll. `mirror_sync` / set_sync_state not called after poll. No MailboxAdapter in adapters. |

---

## 13. Synthetic Data / Evaluation / Review Tools

| Item | Details |
|------|---------|
| **Module/directory** | `scripts/`, `datasets/`, `tests/`. |
| **Purpose** | Generate labeled synthetic intake cases; evaluate pipeline (category/lane); export failures; regression tests. |
| **Key files** | `scripts/generate_intake_synthetic_data.py`, `scripts/generate_synthetic_intake_dataset.py`, `scripts/evaluate_intake_synthetic_data.py`, `scripts/review_intake_failures.py`, `scripts/dump_needs_attention.py`, `tests/test_intake_quality.py`, `tests/test_intake_synthetic_regression.py` |
| **Main entry points** | CLI scripts (run from repo root); pytest for test_intake_quality and test_intake_synthetic_regression. |
| **Status** | **Implemented.** Datasets: `datasets/intake_synthetic_cases.json`, `intake_synthetic_failures.json`, `intake_synthetic_reviews.json`; `data/synthetic_intake_dataset.json`. |
| **Dependencies** | `local_ai.intake.pipeline.run_pipeline`, `local_ai.judgment.get_record` (evaluate). |
| **Gaps/caveats** | Two generate scripts (generate_intake_synthetic_data.py vs generate_synthetic_intake_dataset.py); unclear which is canonical. |

---

## 14. Startup / Boot Flow

| Item | Details |
|------|---------|
| **Entry** | `api/main.py` → `app.on_event("startup")` → `_on_startup()`. |
| **Sequence** | (1) `_check_startup_dependencies()` — import pandas, duckduckgo_search, local_ai, atria_tools, providers. (2) `mirror.load_into_memory()` — if `intake_mirror.db` exists, clear judgment store, load mirror_judgment into judgment layer, load mirror_item into queue_store. |
| **Status** | **Implemented.** No explicit poll on startup; frontend or user must trigger poll. |
| **Gaps/caveats** | Vision Execution DB is not initialized at API startup; it initializes on first request to vision-execution routes. |

---

## 15. Tests

| Item | Details |
|------|---------|
| **Location** | `tests/` |
| **Key files** | `tests/test_intake_quality.py` (lane/category assertions on run_pipeline), `tests/test_intake_synthetic_regression.py` |
| **Entry points** | `pytest tests/` or `python -m pytest tests/test_intake_quality.py -v`. |
| **Status** | **Implemented** for intake pipeline quality and synthetic regression. No tests for mirror, judgment persistence, policy, or API startup. |
| **Gaps/caveats** | No tests for load_into_memory, get_item_with_content, or policy layer. |

---

## Summary Table

| Area | Status | Notes |
|------|--------|-------|
| API / routes | Implemented | — |
| Intake | Implemented | End-to-end with mirror |
| Mirror / persistence | Implemented | Intake + Vision Execution DBs |
| Judgment layer | Implemented | In-memory; persisted via mirror |
| Policy / data access | Implemented | Only intake mirror uses it |
| Adapters | Partially implemented | LLM registered; mailbox not used by intake |
| Storage | Implemented | Two SQLite DBs |
| Frontend | Implemented | Single app; Settings + auth session; council perspectives server-sync when signed in |
| User settings / per-user LLM | Implemented | `/settings` + prefs JSON + provider registry gating; routed `/run` + council seats use session user where wired |
| Frontend build | Implemented | `tsc -b` + Vite; unused locals/parameters relaxed in tsconfig |
| Council / perspectives | Implemented | Routed council: seam + per-seat providers + OpenAI-missing → Ollama fallback for Auto; no data-access policy on payloads |
| Vision-to-execution | Implemented | Full CRUD + radar |
| File Steward | Implemented | Via atria_tools; not adapter |
| Mailbox / ingestion | Implemented | On-demand poll only |
| Synthetic / evaluation | Implemented | Multiple scripts |
| Startup / boot | Implemented | Mirror load on startup |
| Tests | Implemented (narrow) | Intake pipeline only |
| Nightly self-exercise | Implemented | `tools/run_nightly_self_exercise.py` — profiles `quick` / `standard` / `full`; morning digest + run-to-run deltas in `NIGHTLY_REPORT.md`; optional budgeted cloud sample via `ATRIA_NIGHTLY_CLOUD_BUDGET_USD`; scratch VE cleanup in `cleanup.py`; desktop launcher `tools/nightly_harness_gui.py` / `tools/NightlyHarness.bat`; reports under `logs/nightly_self_exercise/` |
