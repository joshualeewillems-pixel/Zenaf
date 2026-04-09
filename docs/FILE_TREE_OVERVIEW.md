# File Tree Overview

Concise tree of architecture-relevant files and directories with one-line descriptions. Not every file is listed.

```
Zenaf/
├── api/
│   ├── main.py                    # FastAPI app; startup (dependency check + mirror load); POST /run, /run/stream, /health; mounts auth + settings
│   └── routes/
│       ├── intake_routes.py        # /intake: config, OAuth, email/fax, poll, queue CRUD, judgment
│       ├── auth_routes.py         # /auth: login, logout, GET/PATCH /me (display name)
│       ├── settings_routes.py     # /settings: LLM profile, credentials (Fernet), test, notifications JSON
│       └── vision_execution.py    # /vision-execution: CRUD for ideas, initiatives, projects, tasks, etc.
├── local_ai/
│   ├── zenaf_tools.py              # File Steward wrappers, council, web research, next step, reassess; used by /run
│   ├── zenaf.py                    # CLI/orchestration; run_tool, ask_model (separate from API)
│   ├── providers/
│   │   ├── __init__.py             # get_default_provider() → OllamaProvider
│   │   ├── ollama.py               # OllamaProvider
│   │   ├── openai.py               # Minimal generate + test (Settings / resolver)
│   │   ├── anthropic.py
│   │   ├── google_genai.py
│   │   └── xai.py
│   ├── llm/
│   │   ├── adapter.py              # Legacy/default adapter notes; resolver in resolver.py
│   │   └── resolver.py           # get_llm_adapter_for_user(user_id); Ollama fallback
│   ├── adapters/
│   │   ├── __init__.py             # Registry; LLM + Mailbox protocols; only llm.ollama registered
│   │   └── README.md
│   ├── policy/
│   │   └── data_access.py          # Tiers, AccessLevel, request_access, require_access; used by mirror.get_item_with_content
│   ├── judgment/
│   │   └── __init__.py             # In-memory judgment store; create_intake_judgment, create_correction_record; no direct persistence
│   ├── intake/
│   │   ├── __init__.py             # Pipeline, queue_store, email_ingestion, mirror exports
│   │   ├── pipeline.py             # run_pipeline, IntakeItem, classifier + redaction + lanes + judgment
│   │   ├── queue_store.py          # In-memory queue; add_item, get_queue, update_item; write-through to mirror
│   │   ├── mirror.py               # SQLite intake_mirror.db; schema, upsert_item, load_into_memory, get_item_with_content
│   │   ├── email_ingestion.py      # IMAP/Gmail poll, normalize body, run_pipeline, add_item; no sync_state after poll
│   │   ├── classifier.py           # classify(subject, body) → category, priority
│   │   ├── lanes.py                # derive_lane(...)
│   │   ├── redaction.py            # detect_phi, redact
│   │   ├── email_router.py         # process_email (thin wrapper)
│   │   ├── fax_router.py           # process_fax (thin wrapper)
│   │   ├── gmail_oauth.py          # OAuth flow, token, xoauth2 string
│   │   └── access_policy.py        # Deprecated shim → local_ai.policy.data_access
│   ├── vision_execution/
│   │   ├── storage.py              # SQLite vision_execution.db; full CRUD for all entity types
│   │   ├── service.py              # Pass-through to storage; get_radar
│   │   ├── models.py               # Pydantic create/update models; row_to_* helpers
│   │   ├── schema.sql              # Table definitions (+ user_llm_*, user_notification_settings)
│   │   ├── radar.py                # get_radar()
│   │   ├── derived.py              # add_initiative_derived, add_project_derived, add_capacity_derived
│   │   ├── initiative_evaluate.py  # evaluate_initiative
│   │   └── meeting_extract.py      # extract_meeting
│   ├── context/
│   │   └── phil_context.py         # load_phil_context (used in council packet)
├── tools/
│   ├── file_steward/
│   │   └── app.py                  # Streamlit/file steward; scan_folder, analyze, recommend, etc. (lazy-imported by zenaf_tools)
│       └── handlers.py             # List/create/update ideas, people, resources; ai_analyze, ai_prioritize, ai_hypothetical
├── frontend/
│   └── src/
│       ├── App.tsx                 # Single app; modes; mainView includes settings; perspectives + vision-execution
│       ├── settings/               # SettingsView, sections (Account, Model connections, Notifications), api.ts
│       ├── auth/                   # AuthGate, session (cookie fetch to /auth/me, PATCH display name)
│       ├── perspectives/           # Types, list, detail, creator, import/export
│       └── vision-execution/       # Vision Execution UI
├── scripts/
│   ├── generate_intake_synthetic_data.py   # Template-based synthetic cases → datasets/intake_synthetic_cases.json
│   ├── generate_synthetic_intake_dataset.py
│   ├── evaluate_intake_synthetic_data.py   # Run pipeline on cases; compare expected vs actual; export failures
│   ├── review_intake_failures.py
│   ├── dump_needs_attention.py
│   └── seed_vision_execution.py
├── tests/
│   ├── test_intake_quality.py      # Lane/category assertions on run_pipeline
│   └── test_intake_synthetic_regression.py
├── datasets/                       # intake_synthetic_cases.json, failures, reviews
├── data/                           # vision_execution DB dir; synthetic_intake_dataset.json
├── docs/
│   ├── README.md
│   ├── 01_TRUTH/
│   │   ├── CODEBASE_INVENTORY.md
│   │   ├── CODEBASE_TRUTH_RULES.md
│   │   ├── BOOT_FLOW.md
│   │   ├── ACTIVE_VS_PLANNED.md
│   │   └── SYSTEM_REFERENCE.md
│   ├── 02_ACTIVE_DESIGN/
│   │   ├── README.md
│   │   ├── VISION_EXECUTION_DESIGN.md
│   │   ├── CORE_PROFILE_ARCHITECTURE.md
│   │   ├── CONTEXT_ACTION_BAR_DESIGN.md
│   │   ├── EXECUTION_STEPS_DESIGN.md
│   │   └── MEDIATION_EXECUTION_DIRECTION.md
│   ├── DATA_FLOW.md
│   ├── FILE_TREE_OVERVIEW.md
│   ├── OPEN_QUESTIONS.md
│   └── ZENAF_ARCHITECTURE.md
├── open-cockpit.bat                # Launcher: run open-cockpit.ps1
├── open-cockpit.ps1                # Start API + frontend; open browser (app + API docs)
└── intake_mirror.db                # Created at repo root by intake mirror (when first write)
```

**Key DBs:**

- `intake_mirror.db` (repo root): mirror_item, mirror_judgment, mirror_sync, mailbox_action.
- `data/vision_execution/vision_execution.db`: Vision Execution entities (core_profiles, ideas, initiatives, projects, tasks, persons, assets, decisions, capacity_profiles) plus **user LLM profile, encrypted provider credentials, notification prefs** (see `schema.sql`).
