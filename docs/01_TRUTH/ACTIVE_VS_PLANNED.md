# Active vs Planned

<!--
Status: Canonical
Last updated: 2026-04-03
-->

Reality vs roadmap: what is working, partial, stubbed, deprecated, or not yet built. Based on the current codebase.

**System law (enforceable rules + violation ledger + mechanical checks):**

- **`ATRIA_SYSTEM_CHARTER.md`** — charter v0
- **`ATRIA_CHARTER_VIOLATION_LEDGER.md`** — audit status, first-pass violations, automation pointer
- **`scripts/charter_enforcement_check.py`** — run: `python scripts/charter_enforcement_check.py` (optional `CHARTER_ENFORCE_STRICT=1` to fail CI on selected severities)
- **`GLOBAL_PHILOSOPHY_INTEGRATION_MATRIX.md`** — each declared philosophy: law, scope, implemented vs partial vs parked, class A/B/C, enforcement mechanism, ranked order

For **philosophy, layered definitions, and API/entity reference**, see **`SYSTEM_REFERENCE.md`**. This file is the **operational** truth: surfaces, flows, gaps, and near-term build targets. For **module/file-level inventory and build notes**, see **`CODEBASE_INVENTORY.md`** (the other half of "as-built + direction"). For **locked source-of-truth decisions** (council seats, traces, intake tiers, field naming), see **`TRUTH_CONVERGENCE.md`**.

---

## Truth convergence (product contract snippets)

- **Intake tiers:** The **product** exposes **Tier A** queue behavior only. Tier B/C code paths in the mirror/policy layer are **not** part of the public contract until explicitly shipped (no half-documented "maybe tiers").
- **Council perspective agents:** When signed in, definitions are **server-owned** (`GET`/`PUT /vision-execution/council-workspace/perspectives`, table `user_council_workspace`). `localStorage` is a **cache** for fast load and anonymous sessions.
- **AI traces:** Policy is **full coverage** or **declared exempt** — see `frontend/src/ai-actions/aiTraceExemptRegistry.ts` (exempt list is reviewed when adding LLM paths).

---

## User-facing surfaces (cockpit)

| Surface | Location (typical) | Role |
|---------|-------------------|------|
| **Vision & Execution** | `VisionExecutionView` | System of record: ideas → initiatives → projects → tasks; people/capacity; core profile editor (training + reconcile) opened from Team; meeting extract + review; Radar/signals. **Focus context strip** (shared with app header): registered fields get **Rewrite** (where in `fieldCapabilityRegistry`) and **voice-to-field** (record → transcribe → insert at cursor). Detail panels and inline **create** flows (idea / initiative / project / task) use `VeFocusRegion` + synthetic ids `__ve_new_*__` before save. |
| **Perspectives** | `App.tsx` **Foundation** region + `PerspectivesView` | **Foundation** (top): lists **core profiles** from `GET /vision-execution/core-profiles`, optional create (**Add**), detail via `CoreProfileDetailPanel` (synthesis, training, reconcile, influences). In Foundation view, actor/detail/training/editor render in a **Foundation-local right pane**; this is distinct from the global council/chat aside. **Below:** perspective agents — **server-owned** when signed in (`GET`/`PUT /vision-execution/council-workspace/perspectives`), with **`localStorage` as cache** and anonymous fallback — influences, fed into **Workspace** council seats. **Product direction:** treat **one canonical core profile** per person/workspace; **perspectives** as lenses/modes on that core — storage/API still allow multiple `core_profiles` rows today; UX simplification is planned without requiring an immediate schema migration (see **`SYSTEM_REFERENCE.md`** §1.4a, **`CORE_PROFILE_ARCHITECTURE.md`**). No dedicated `/run` or trace emission on the perspectives-only panel today. |
| **Workspace Organizer** | `App.tsx` (workspace mode) | Folder path, File Steward modes (analyze / recommend / assess / simulate), **AI Agents / council** (streaming, **per-seat LLM** on perspective rows, **Your reply** textarea registers as synthetic **`council`** focus so the header strip + voice target the chat field, not a stale VE field), answers **aside** with tall scrollable layout, **always ≥1 seat** (default first seat **Thinking Partner** / **Atria**), web research, next step, reassess, folder advisor stream; **POST `/run`** / **`/run/stream`** with **`routing_context`** for execution-policy seam. Optional **developmental guidance** object on `council_preflight` (see below). |
| **Content** | `ContentView` | Briefs, `ContentBriefEditor`, script/newsletter generation via **`/run`** (`content_script` / `content_newsletter`), `distill-source`, transcript sorter → **`/transcripts/sort`**. |
| **Intake** | Same app, intake panels | Queue, poll, OAuth, fax/email submit; mirror-backed. |
| **Settings** | App settings / config areas | IMAP, Gmail OAuth config, etc. |

Top-level navigation emphasizes **Perspectives** (Foundation = core profile + perspectives) alongside VE and Workspace. Core profile deep editing is also reachable from VE **Team** context.

### Mirror graph interpretation (cross-cutting direction)

**Strong intent:** Push every "extract → classify → commit" style flow toward the same **interpretation envelope** (graph-relative classification + proposed **`action`** + **`payload`** + review before write). Canonical narrative: **`docs/02_ACTIVE_DESIGN/MIRROR_GRAPH_INTERPRETATION_SYSTEM_NOTE.md`**. Summary pointer: **`SYSTEM_REFERENCE.md`** Part II §2.5. *Meetings are the reference implementation; profile reconcile, intake, file steward, and presort are the next conceptual adopters when touched.*

---

## AI-assisted flows vs shared trace substrate

**Shared module:** `frontend/src/ai-actions/` — `AiActionTrace` (in-memory ring buffer), `action_kind` (`field_text_rewrite` \| `suggestion_batch` \| `structured_evaluation`), optional **`action_intent`** (snake_case pipeline id, not an enum), `AiActionResultPanel`, outcomes (`applied` \| `dismissed` \| …). Design: **`docs/02_ACTIVE_DESIGN/AI_ACTION_TRACE_AND_ROUTING_DESIGN.md`**.

**Row-level coverage (all surfaces):** **`docs/01_TRUTH/AI_ACTION_SUBSTRATE_COVERAGE_MATRIX.md`**.

| Flow | Trace? | Panel? | Notes |
|------|--------|--------|------|
| VE focus **Rewrite** | Yes | Yes | `field_text_rewrite` + per-field `action_intent` (e.g. `idea_title_rewrite`, `initiative_brief_rewrite`). |
| VE / council **Voice → insert** | No | No | `POST /api/transcribe` after record stop; insert via `ATRIA_VE_FOCUS_INSERT_TEXT` or cancelable **`ATRIA_VOICE_TRANSCRIPT_DOM_FIRST`** for council textarea; not traced as `AiActionTrace` today. |
| Project **Suggested work** | Yes | Yes | `suggestion_batch` / `project_suggested_work`. |
| Initiative / Idea **Evaluate** | Yes (compact output) | Custom UI | `structured_evaluation` / `initiative_evaluate` \| `idea_evaluate`; apply/dismiss not yet written back to trace outcomes. |
| Meeting **extract** pipelines | No | Custom review | `interpret_against_graph` adds **`interpretation`** (`type`, `action`, `payload`, …) after `post_process_extraction`; staging carries it. **Cross-surface alignment** is active intent—see **`docs/02_ACTIVE_DESIGN/MIRROR_GRAPH_INTERPRETATION_SYSTEM_NOTE.md`**. Still legacy relative to `AiActionTrace` substrate. |
| Core profile **chat / reconcile** | No | Custom | Legacy relative to `AiActionTrace` substrate. **Prompt behavior (implemented):** conversation is explicitly primary over digest/raw notes; a **FINAL OVERRIDE** block is appended immediately before output instructions in reconcile + conversation prompts (vision execution + structured delegation prompt); when conversation turns exist, **raw training notes are deterministically capped** (~8000 chars) to reduce tail dominance — see **`docs/02_ACTIVE_DESIGN/CORE_PROFILE_ARCHITECTURE.md`**. |
| Workspace **`/run`** / **`/run/stream`** (analyze, simulate, assess, recommend, council, folder advisor, web research, next step, reassess) | Yes | Various | Traces via `workspaceRunWithTrace.ts` after successful calls; **no** `AiActionResultPanel`; user outcomes not hooked to UI yet. |
| Content **`/run`** + distill + transcript sort | No | Various | Legacy; future migration. |
| Idea **"Clarify with AI"** | No | N/A | **Stub** (timed local fill); no LLM call. |

---

## Active and Working

- **Intake end-to-end:** POST email/fax → pipeline → queue → mirror; GET/PATCH queue; judgment creation and correction; mirror load on API startup (`mirror.load_into_memory()`).
- **Vision Execution:** Full CRUD for core profiles, ideas, initiatives, projects, tasks, persons, assets, capacity profiles, decisions; radar; separate SQLite DB; API under `/vision-execution`.
- **Core profile LLM prompts:** Reconcile and conversation paths (`local_ai/vision_execution/core_profile_reconcile.py`, `core_profile_conversation.py`, `local_ai/delegation/core_profile_reconcile.py`) enforce **conversation-first** evidence hierarchy in text, explicit **contradiction → conversation wins**, end-of-prompt **FINAL OVERRIDE** anchoring, and **deterministic** raw-note compression when the thread is non-empty (no extra LLM call).
- **Council:** `run_council` / `run_council_stream` in atria_tools; POST /run and /run/stream with `mode=council`, **`routing_context`**, and signed-in **`council_user_id`** for OpenAI key resolution and **per-seat** adapters. **`apply_seam_routing`**: if policy picks OpenAI but no env/settings key, **council** falls back to **local Ollama** for "Auto" seats (meta `council_seam_fallback_ollama`); explicit per-seat providers still use configured keys when enabled. **`perspective_definitions`** from frontend (no zero-seat path): **all seats Thinking Partner** → **Zenaf** conversational path (**System Interface** system preamble in `COUNCIL_CONVERSATIONAL_PARTNER_SYSTEM`), **RESPONSE CONTRACT — TECHNICAL HEADER** from **`local_ai/response_trunk.py`** (field checklist + syntax/grounding), **15s** LLM timeout on `_run_council_conversational_partner_body`, **no** structured Core move / Pushback / Next action per TP seat, **no synthesis** (single TP seat uses one conversational body; multiple TP seats stay per-seat conversational). **Precision integration:** **`[DRAFT_VALUE: …]`** handled in **`local_ai/integration_commit.py`** (strip from visible reply, `pending_integration`); narrow **`infer_draft_value_from_context`** when the model omits the tag but the focused task description is empty. **`priority_resolution`** may omit prior thread from the packet (**priority amnesia** — **`council_preflight`**). **Any structured role** present → full council mode with structured seat limits and **synthesis allowed** when requested. **Thinking Partner** built-in persona `thinking_partner` / `BUILT_IN_PERSONA_DEFINITIONS` in `atria_tools.py`. **`council_preflight.developmental_guidance`**: client-assembled read model (`local_ai/developmental_guidance.py` normalizes + formats); **`council_preflight.build_enriched_council_context`** appends a bounded **DEVELOPMENTAL GUIDANCE** block to the council packet. Cockpit: **`buildDevelopmentalGuidanceContext`** + collapsible **How Atria is reading your patterns** panel (`frontend/src/developmentalGuidance/`); map triad snapshot via **`VisionMapView`** `onDevelopmentalSignalsChange`. Thread UI may use **`EntityMentionText`** for tolerant **`[ID: …]`** chips on raw assistant text.
- **Council panel placement (cockpit shell):** Global council/conversation aside visuals remain unchanged (right-side by default; vision map keeps its existing left-side behavior). Foundation detail/training no longer overrides that global aside; it lives in the Foundation-local right pane.
- **Perspectives:** Frontend types, list, detail, creator, import/export; **definitions** in localStorage; **`llm_provider`** per seat in UI; **server-persisted** seat defaults via Settings (`PUT /settings/llm/council-seats/{seat_id}`).
- **Provider registry (Settings + execution):** `local_ai/llm/provider_registry.py` gates seam and resolver; prefs in **`llm_provider_prefs_json`**; `GET/PUT /settings/llm/providers*`, `BlockedLLMAdapter` / clear errors when a provider is off or missing a key.
- **File Steward–backed modes:** Analyze, Recommend, Assess, Simulate (and reassess low-confidence) via atria_tools; POST /run with corresponding modes.
- **Web research / Next step:** Implemented in atria_tools; wired to /run.
- **Intake API:** Config, Gmail OAuth, POST email/fax, POST email/poll, GET/PATCH queue, GET queue item judgment.
- **Policy layer:** `local_ai.policy.data_access` with tiers and `request_access`; used by `mirror.get_item_with_content()`.
- **Synthetic data scripts:** Generate synthetic cases, evaluate pipeline, export failures, review; pytest intake quality and synthetic regression.
- **Startup:** Dependency checks and mirror load on API startup; Vision Execution DB init on first use.
- **Operational launcher:** `open-cockpit.bat` / `open-cockpit.ps1` start API + frontend and open browser.
- **Vision map:** Live graph from `buildLiveVisionMapGraph`; context chat shell with triad metrics from `mapGrowthMetrics.ts`; guidance scripts / weak-area copy (`guidanceScripts.ts`, `guidanceConversationalSeed.ts`, `MapChatShell.tsx`); sand deformation in `sandHeightField.ts` (no backend persistence for rake patterns). Triad snapshot can feed **developmental guidance** for council (see Council bullet).
- **Focus context strip + voice (cockpit header):** `UniversalContextStrip` in `App.tsx` wraps **`FocusContextRecordButton`** + **`ContextActionBarContent`** in **`VeVoiceRecordingProvider`** under **`VisionExecutionFocusProvider`**. Registered focus drives Rewrite (registry-backed) and **microphone → `POST /api/transcribe` → insert**. **`ATRIA_VOICE_TRANSCRIPT_DOM_FIRST`** (cancelable) lets council **Your reply** take transcripts before **`ATRIA_VE_FOCUS_INSERT_TEXT`**; council uses synthetic focus `entity_type: council`, `entity_id: __council_reply__`, `field_key: reply` with listeners in `App.tsx` for insert/apply-rewrite. `FocusContextRecordButton` uses **`onBarPointerDownCapture`** so clicking record does not drop focus before capture.
- **Soil layer v1 (parked):** Interpretive filesystem substrate **shipped and frozen** unless explicitly re-chartered. **`docs/02_ACTIVE_DESIGN/SOIL_LAYER_FILESYSTEM_SPEC.md`** (full contract); **`local_ai/soil/`** kernel; **`python -m local_ai.soil.cli`**; **`POST /vision-execution/soil/append`** & **`…/soil/promote`** (session auth, VE row guard, audit-only promote); dev-only **Soil (dev)** on task panel (`import.meta.env.DEV`); §12.3 manual checklist. **Not built by design (v1):** read hooks, auto-capture, council consumption, indexing/vectors. **Soil v2+** is not scheduled — use convergence work (traces, guidance, core profile, mirror interpretation, etc.) first.

---

## Implemented but Incomplete

- **Intake mirror sync state:** Poll updates **`mirror_sync`** via `set_sync_state` after each successful readonly IMAP `SELECT` (see `email_ingestion._record_successful_poll_sync`). **`mailbox_action`** remains unwired until mailbox mutations exist (exempt tag in `mirror.py`; see Stubbed / Placeholder).
- **Tier B/C access:** `get_item_with_content()` implements Tier B (and Tier C placeholder) with policy check. **Not** exposed via API or UI — **by product contract** (see **`TRUTH_CONVERGENCE.md`**); code may remain until you ship Tier B/C or delete it.
- **Adapters:** Registry and LLM adapter (Ollama) are registered. Mailbox adapter protocol exists but no implementation is registered; intake uses `email_ingestion` and Gmail OAuth directly, not adapters.
- **Policy adoption:** Architecture says "all modules that touch Tier B or Tier C … must go through shared data access policy". Only intake mirror's `get_item_with_content()` does; council and File Steward do not use the policy layer.

---

## Stubbed / Placeholder

- **Tier C (raw content):** Mirror has `raw_content_ref` column; no code stores or retrieves full raw content. Policy supports `RAW_CONTENT_REQUIRED` and justification; no real Tier C data path.
- **Mailbox mutation:** No mark-read, move, or delete. `mailbox_action` table is ready for audit of future actions; no code writes to it for actual mailbox operations.
- **Destination (external):** `request_access(..., destination=Destination.EXTERNAL)` is in the API; no call site passes external; egress gating is not implemented.
- **Background poll:** Poll is on-demand only (POST /intake/email/poll); no scheduler or background job.

---

## Deprecated / Compatibility Shims

- **`local_ai/intake/access_policy.py`:** Deprecated. Re-exports everything from `local_ai.policy.data_access` for backward compatibility. New code should import from `local_ai.policy.data_access` only. Docstring in file states this.

---

## Planned / Not Yet Built

### Near-term product / AI substrate (not exhaustive)

- **Singular core profile (ontology + UI):** Product truth = **one canonical core** per user + **perspectives as lenses**. **As-built:** `core_profiles.is_primary` and **`PATCH …/set-primary`** already exist; `list_core_profiles` orders primary first. **Remaining:** UI/copy alignment, shared **canonical resolver** (replace ad hoc `profiles[0]` / multi-row influence pickers), optional **POST /core-profiles** gate — see **`docs/02_ACTIVE_DESIGN/SINGULAR_CORE_PROFILE_CONVERGENCE_AUDIT.md`**. Ontology refs: **`CORE_PROFILE_ARCHITECTURE.md`**, **`SYSTEM_REFERENCE.md`** §1.4a.
- **Developmental guidance (beyond v1 slice):** Optional persistence / server assembly of `DevelopmentalGuidanceContext`; wire **user_outcome** and intake judgment patterns into hypotheses; influence `suggest_next_step`, harvest recall line, and guidance script ordering — without silent routing changes (hypothesis-first, user-visible).
- **Trace + panel parity:** Emit `AiActionTrace` (and optionally `AiActionResultPanel`) for high-traffic legacy flows: Workspace `/run` modes, Content generation/distill, meeting extract review, core profile reconcile; align **user outcomes** on evaluate-style flows (apply/dismiss → trace).
- **Server-side trace ids:** Correlate client outcomes with persisted rows when AI routes return `trace_id`.
- **Execution policy breadth:** Seam today supports **ollama** and **openai** as primaries; additional cloud primaries on the same seam need explicit wiring (see **`docs/02_ACTIVE_DESIGN/POLICY_PROVIDER_EXECUTION.md`** / **`AI_EXECUTION_POLICY_ROUTING.md`**). Per-seat council can already target Anthropic, Google, xAI, etc. via user credentials when enabled.
- **Truth rules vs product:** **`CODEBASE_TRUTH_RULES.md`** still encodes conservative defaults for `/run`; reconcile that doc when expanding "always honor Settings" beyond routed modes.
- **Policy & data access:** Council/File Steward/intake LLM paths and Tier B/C **UI** — shared **`data_access`** adoption remains open (unchanged intent).

### Backlog (from older inventory)

- **Council / File Steward using policy:** Documented intent that these modules use the shared data access policy when touching Tier B/C or external; not implemented.
- **Mailbox adapter:** Protocol in adapters; no concrete mailbox adapter; intake does not use adapter registry for fetch.
- **LLM via adapters:** Hot paths still use **`get_default_provider()`** / **`get_llm_adapter_for_user()`** / council seat builders, not `local_ai.adapters.get_adapter("llm", …)` — registry remains optional for legacy tooling.
- **Mailbox action audit in poll:** Poll does not call `record_mailbox_action` (no mailbox mutations in v1). Sync state after poll is covered by `set_sync_state` (see Implemented but Incomplete → Intake mirror sync state).
- **API or UI for Tier B/C content:** No route that calls `get_item_with_content()` with sanitized or raw level; no UI to "view body" through policy.
- **Configurable mirror path:** Intake mirror path is fixed at repo root; no env or config to override.

---

## Explicit Partial Wiring

- **Intake:** End-to-end wired except: (1) `mailbox_action` audit rows (parked until mutations), (2) any consumer of Tier B/C via `get_item_with_content`.
- **Policy:** Implemented and used only at one call site (mirror); rest of "must use" is not wired.
- **Adapters:** Registry and one LLM adapter; no integration with intake (mailbox) or atria_tools (LLM).
