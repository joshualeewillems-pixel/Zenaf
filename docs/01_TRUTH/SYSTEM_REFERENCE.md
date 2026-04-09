# Zenaf system reference (merged)

<!--
Status: Canonical
Last updated: 2026-04-04
-->

Single reference combining: **intent & philosophy**, **projection & stages**, **definitions & machine-readable reference**, and **consolidated current-state map**.  
Supersedes: `docs/05_ARCHIVE/SYSTEM_INTENT.md`, `docs/05_ARCHIVE/SYSTEM_STAGES_AND_PROJECTION.md`, `docs/05_ARCHIVE/SYSTEM_DEFINITIONS.md`. Update this file when layers, entities, APIs, or staged plans change.

**Operational gaps (stubbed flows, partial wiring, “what to build next” in plain terms):** prefer **`docs/01_TRUTH/ACTIVE_VS_PLANNED.md`**, which is kept in sync for surfaces and AI flow coverage.

---

# Part I — Intent & philosophy

## 1.1 Zenaf as a symbiosis layer

- **Zenaf is not “an AI assistant.”** It is a **human–AI symbiosis layer** that sits between people and their tools. It coordinates context, decisions, and execution across modules; it does not try to replace every system underneath.
- Humans remain the **source of judgment, taste, and final decisions**. Zenaf’s job is to surface patterns, propose actions, and wire tools together so that humans can steer more effectively.
- The architecture should always favor: **augment judgment and workflow** rather than “automate away the human.”

## 1.2 The core loop

1. **Human signal** — The user acts or expresses intent: asks a question, edits content, triages inbox, makes a VE decision, runs transcript sorter, etc.
2. **System distillation** — Modules compress raw activity into **signals** (e.g. decisions, preferences, drift, risk) and **profiles** (distilled cognitive models), never into opaque logs.
3. **Advisory simulation** — Council, profiles + mandates, and other reasoning modes simulate perspectives and propose options (“advice, not orders”).
4. **Execution amplification** — When the user chooses, Zenaf fans out work into the right tools (tasks, content drafts, handoffs, queues) with structured context.
5. **Human steering** — The human reviews, accepts/rejects/edits, and the outcome feeds back into distillation (through explicit, versioned updates), closing the loop.

Every step has a clear input, explicit state changes, and a human checkpoint before lasting decisions or profile updates.

## 1.3 Signals as first-class inputs

- **Signals, not raw logs.** Zenaf consumes **signals** from modules: transcript sorter, Content, Vision Execution decisions, inbox triage, folder sorting, intake corrections, etc. Signals describe *what changed* and *why it matters*.
- Signals drive: Radar and orientation (“what needs attention”); distillation for profiles and decision fingerprints; council prompts (recent decisions, context, constraints).
- Signals should be **summarized and structured** and **scoped and purpose-limited**, not a monolithic “memory dump.”

## 1.4 Profiles and seats

- **Profiles** are distilled cognitive models (versioned, explicitly updated via proposals; no silent self-training). See `PERSONALITY_PROFILE.md`.
- **Seats** = Profile × Mandate at runtime (responsibility/role, capability/access). The profile remains a static cognitive model until explicitly versioned; the seat controls where and how that profile is allowed to act.

### 1.4a Core profile vs perspectives (ontology)

- **Target product model:** **One core profile** per person/workspace context — the single structured “decision engine” / identity synthesis (name, definition, goals, constraints, etc.). **Perspectives** (user-defined agents, council seats) are **expressive lenses or modes** on that core, not peer copies of the whole profile. Users should not need multiple interchangeable “core profiles” (e.g. “Holistic Healer” vs “Business Operator”) to get different voices; that is what perspectives are for.
- **As-built (today):** Storage and API still support **multiple** `core_profiles` rows per user (`list_core_profiles`); the **Perspectives** Foundation UI lists them and allows **Add**. **Direction:** simplify UI and copy toward a **canonical** profile (deterministic selection or single-row convention) without an immediate requirement for a large migration; optional schema flag later if needed. Canonical detail: **`docs/02_ACTIVE_DESIGN/CORE_PROFILE_ARCHITECTURE.md`**.

## 1.5 Amplify judgment; guardrails

- **Do:** Surface drift, risk, opportunities; offer multi-perspective advice; turn decisions into tasks and handoffs. **Do not:** auto-commit high-impact actions without clear human checkpoints; hide irreversible changes; pretend to be “the decider.”
- **No black-box personality engines.** Personality and style must be in interpretable structures (profiles, mandates, constraints), not opaque embeddings. No uncontrolled self-training; profile evolution via distillation reports and explicit versioning.

---

# Part II — Projection (direction of travel)

## 2.1 Subject/Node and Mandelbrot scaling

- **Long-term:** Evolve toward a **Mandelbrot-scaling cognitive operating system** — the same loop (observation → judgment → decision → execution → outcome) at many levels (task, project, initiative, venture, org). *(ARCHITECTURE_SUBJECT_PRIMITIVE)*
- **Subject/Node primitive:** A generic “thing” that can be captured, classified, judged, prioritized, tracked, related. Current entities (VE initiatives/projects/tasks, content briefs, intake items, council artifacts) are **typed specializations**; the system does **not** refactor into this model yet — **documentation and breadcrumbs only**.
- **Judgment substrate** (SubjectRef, JudgmentSnapshot, CouncilRunArtifact) is deliberately generic so it can point at any Subject.

## 2.2 Content and orchestration

- Zenaf is the **conductor** of the media pipeline (shared brief, tool-shaped handoffs, production/distribution tracking). It does **not** replace specialist tools. Vision Execution remains the system of record; content work is in service of VE. *(CONTENT_PIPELINE)*
- **Minimal pipeline stages (content):** Source distillation → Content brief creation → Script/copy generation → Media asset packaging → Distribution planning → Export/publish handoff.

## 2.3 Cockpit and progression

- **Progression:** User-controlled; one processor at a time. No automatic chaining; suggested next actions are visible and user-chosen. No hidden state. *(COCKPIT_PROGRESSION_DESIGN)*
- **Truth sources:** No single shared prompt builder; each module constructs its own prompt. **Exception (Zenaf / all–Thinking Partner council):** turn-specific contract is centralized in **`local_ai/response_trunk.py`** and prepended as **RESPONSE CONTRACT — TECHNICAL HEADER** (see **§2.7**). Structured memory is often used for attribution and storage **without** being pasted into prompts; **exceptions** include **core profile** reconcile/conversation (structured fields + `raw_notes` + thread — see **§2.6**). *(ZENAF_PROMPT_AND_TRUTH_ARCHITECTURE — general pattern; core profile is a deliberate inclusion.)*
- **Focus mediation (header strip — implemented slice):** A single **Focus context** strip reflects **registered field focus** across cockpit views: Vision Execution fields (`VeFocusRegion`), Execution inline creates, and Workspace **council “Your reply”** (synthetic `council` / `__council_reply__`). **Rewrite** stays registry-gated; **voice** records, transcribes (`/api/transcribe`), and inserts at the captured cursor. **Goal:** keep mediation explicit (what field is “hot”) and avoid misrouting transcripts; **not** a full catalog of every input in the app.

## 2.4 Developmental influence (direction)

- **Intent:** Use **signals** (map triad, traces, council patterns, etc.) to form **hypotheses** about strengths, friction, and edges — and surface them **transparently** (labeled in UI / council packet), not as hidden “user modeling” or diagnostic claims.
- **Smallest slice (implemented):** Client-assembled **`DevelopmentalGuidanceContext`** on **`council_preflight.developmental_guidance`**, normalized in **`local_ai/developmental_guidance.py`**, appended to enriched council context; cockpit transparency panel. **Not** a full engine; **no** durable cross-session store yet.
- **Larger projection:** Optional persistence, shared artifact bus, and bounded influence on next-step / harvest / guidance script ordering — still hypothesis-first and inspectable.

## 2.5 Mirror graph interpretation (strong architectural intent)

- **North Star:** Treat evidence (meetings, intake, files, profile notebooks, etc.) as **relative to an existing graph** and emit a **shared interpretation envelope**: classification (`type`), **proposed graph operation** (`action`), optional **`payload`** prefill, **`targetId`**, **`confidence`**—with **human mediation before durable writes**. Cheap rule-based interpretation first; extractors stay separate from “what to do on the graph.”
- **Reference slice:** Meeting pipeline—`post_process_extraction` → `interpret_against_graph` (`local_ai/vision_execution/graph_interpretation.py`); staging/types in `frontend/src/meeting-intelligence/`.
- **Direction:** Extend the same contract to **core profile reconcile**, **intake/mirror**, **file sorting**, and other classifiers when those code paths are touched; do not require a Subject/Node refactor to start.
- **Full note (priority map, principles, sequencing):** `docs/02_ACTIVE_DESIGN/MIRROR_GRAPH_INTERPRETATION_SYSTEM_NOTE.md`.

## 2.6 Core profile evidence and singularity (current + direction)

- **LLM behavior (shipped):** Core profile **conversation** and **reconcile** prompts (including structured **delegation** synthesis) state an evidence hierarchy (conversation → digest/scaffold → raw source → current structured snapshot), an explicit rule that **any contradiction is resolved in favor of the conversation**, a **FINAL OVERRIDE** block placed **immediately before** output instructions, and **deterministic** truncation of long `raw_notes` when conversation turns exist — so recency/length of training text does not override user corrections. Implementation: `local_ai/vision_execution/core_profile_reconcile.py`, `core_profile_conversation.py`, `local_ai/delegation/core_profile_reconcile.py`. Spec: **`docs/02_ACTIVE_DESIGN/CORE_PROFILE_ARCHITECTURE.md`**.
- **UX / data singularity (direction):** Align the product with **§1.4a** — one canonical core in the Foundation UI; keep perspectives as the multi-voice layer. Prefer incremental UI and selection rules before new tables.

## 2.7 Zenaf / single-voice council — response contract & integration *(implemented)*

- **Role:** When every active seat is **Thinking Partner**, the council run uses a **conversational** body (`_run_council_conversational_partner_body` in **`local_ai/zenaf_tools.py`**) instead of structured seat templates + synthesis.
- **System layer:** **`COUNCIL_CONVERSATIONAL_PARTNER_SYSTEM`** identifies the model as a **System Interface** (concise operational voice; parser-safe tags).
- **Turn contract:** **`local_ai/response_trunk.build_response_control_block`** prepends **RESPONSE CONTRACT — TECHNICAL HEADER** with **`mode_directives`** (routing, **PRIORITY AMNESIA** when `question_kind == priority_resolution`, **field checklist** — e.g. **`[DRAFT_VALUE]`** + **`[ID]`** on priority turns), **`syntax_rules`** (ID + draft tag discipline; no code fences for saves), **`grounding_fences`** (lane / PRIMARY authority).
- **Latency budget:** Provider call for this path uses a **15 second** timeout — prompts are expected to stay within that budget.
- **Precision writes:** **`local_ai/integration_commit.py`** strips **`[DRAFT_VALUE: …]`** from user-visible text and builds **`pending_integration`**; on affirmation, **`commit_precision`** writes VE rows. Backend may **infer** a missing draft in a **narrow** case (e.g. focused **task** with empty **description**) via **`infer_draft_value_from_context`**.
- **UI:** **`frontend/src/components/EntityMentionText.tsx`** parses raw assistant text with a tolerant **`[ID: …]`** pattern so entity mentions render as **chips/buttons** when the wrapper is present.

## 2.8 Conversation trunk + mediation *(implemented slice)*

- **Role:** **`local_ai/conversation_trunk.py`** classifies **`QuestionKind`**, selects **`OutputContract`**, derives **`MediationProfile`**, and emits trunk instructions (including **THIS TURN — MEDIATION CONTROL**) consumed by Zenaf assembly and related paths; **`local_ai/response_trunk.py`** imports trunk types for the **RESPONSE CONTRACT — TECHNICAL HEADER**. **`api/main.py`** and **`local_ai/council_preflight.py`** use **`classify_question_kind`** where wired.
- **Direction:** Extend the same trunk vocabulary across remaining conversational surfaces so branches only enrich—see **`docs/02_ACTIVE_DESIGN/CONVERSATION_TRUNK_ARCHITECTURE.md`** (Phase 1–2 marked implemented there; full unification remains trajectory).

---

# Part III — Staged processes (phases and minimal paths)

*Source details in the referenced design docs; this section is the map.*

## 3.1 Shared artifact memory *(SHARED_ARTIFACT_MEMORY_PLAN — not implemented)*

| Phase | Scope | Status |
|-------|--------|--------|
| Phase 1 | Store and schema only: SharedArtifact model, write_artifact, list_artifacts, get_recent_for_context; append-only. No call-site changes. | Planned |
| Phase 2 | Council path: after run_council write seat + summary artifacts; optional council packet augmentation. | Planned |
| Phase 3 | General path: after suggest_next_step optionally write judgment artifact; optionally prepend recent artifacts to next-step context. | Planned |
| Defer | Content/transcript/intake → artifact write; automatic injection; outcome artifacts; any “learning” logic. | Deferred |

## 3.2 Node substrate *(NODE_SUBSTRATE_IMPLEMENTATION_PLAN — not implemented)*

| Phase | Scope | Status |
|-------|--------|--------|
| Phase 1 | Substrate only: NodeRef, NodeSnapshot, normalize_node_ref, node_ref_to_subject_ref. ~~`node_adapters`~~ **retired (tombstoned)** — attempted then superseded by **SubjectRef** + **JudgmentTrunk** (`judgment_substrate.py`). No call-site changes. | Partial / adapters not pursued |
| Phase 2 | Optional use at seams: callers with NodeRef can pass subject_ref; new features can use NodeRef/NodeSnapshot. | Planned |
| Phase 3 | Later: workspace_id/owner_user_id in storage; shared “node” table or graph. | Out of scope for “smallest now” |

## 3.3 Radar and Signal *(current)*

- **Implemented:** Signal as Layer 1 canonical entity; Radar is a **view** over Signal (reads `list_signals(status_not_in=['resolved','dismissed'])`). No Radar-specific signal storage. Minimal Radar actions: Acknowledge, Resolve, Dismiss, Link (to initiative/project/task). Activity events logged for signal lifecycle. *(docs/05_ARCHIVE/SYSTEM_DEFINITIONS.md, docs/02_ACTIVE_DESIGN/VISION_EXECUTION_DESIGN.md)*
- **Planned / later:** Other modules emit signals (transcript_sorter, content, inbox_cleanup, council); aggregate into shared Radar UI (Execution view + Signals view). First phase = synchronous “on read” aggregation; no event bus, no ML, no overbuilt persistence. *(RADAR_SYSTEM)*

## 3.4 Folder council / Workspace Organizer

| Phase | Scope | Status |
|-------|--------|--------|
| Phase 1 | Display council output; folder-specific key_constraints + role_limit when workflow_kind === 'folder'. No parsing or “Suggested folders” card. | Implemented |
| Phase 2 | Folder-workflow-specific renderer; parse “Folder — reason” and “Add to recommendations”. | Optional / not yet |

## 3.5 Council working memory, truth order

- When subject_ref has entity_type/entity_id: pull list_decisions(entity_type, entity_id, limit=N) into “Related decisions” block. *(COUNCIL_WORKING_MEMORY_DESIGN)*
- **Truth-source order (council):** Task (context + question) first, then system facts, then operator priorities, then constraints. No structured memory injection until artifact store and retrieval hooks exist. *(ZENAF_PROMPT_AND_TRUTH_ARCHITECTURE)*

## 3.6 Zenaf field checklist & priority amnesia *(implemented)*

- **Field checklist** is declared in **`response_trunk`** `mode_directives` (backend-mandated required fields per `question_kind`; priority turns list **`[DRAFT_VALUE]`** then **`[ID]`**).
- **Priority amnesia:** For **`priority_resolution`**, prior thread lines may be omitted from the enriched packet so the model does not replay broken templates — see **`local_ai/council_preflight.py`** (merged history policy).

---

# Part IV — Current state and evolution

## 4.1 Active and working

- **Intake:** POST email/fax → pipeline → queue → mirror; GET/PATCH queue; judgment creation and correction; mirror load on API startup.
- **Vision Execution:** Full CRUD (core profiles, ideas, initiatives, projects, tasks, persons, assets, capacity, decisions); **Signal** entity + API (POST/GET/PATCH signals); **Radar** as view over Signal + buckets from initiatives/projects/tasks/capacity; SQLite; API under /vision-execution. **Focus + voice:** Detail fields and inline create (idea / initiative / project / task) register in `VisionExecutionFocusProvider`; context bar **Rewrite** where `fieldCapabilityRegistry` allows; voice insert via `veVoiceRecordingContext` + field selection capture.
- **Activity:** ActivityEvent log (activity.log); enums ActivityType, ActivityEntityType; get_recent_activity(limit); signal lifecycle events (created, acknowledged, linked, resolved, dismissed).
- **Council:** run_council / run_council_stream; POST /run and /run/stream mode=council; **`perspective_definitions`** (always at least one seat; default **Thinking Partner** / **Zenaf** in cockpit). **All seats Thinking Partner** → **Zenaf** conversational path (**System Interface** system text + **RESPONSE CONTRACT — TECHNICAL HEADER** from **`local_ai/response_trunk.py`**, mediation/trunk slice from **`local_ai/conversation_trunk.py`**, **15s** LLM timeout, **`integration_commit`** for **`[DRAFT_VALUE]`** / pending saves), **no synthesis**. **Mixed with structured roles** → structured seat prompts + **synthesis** when enabled. **`council_preflight`** may include **`developmental_guidance`** (read model → bounded packet block via **`local_ai/council_preflight.py`** + **`local_ai/developmental_guidance.py`**). **`priority_resolution`** may use **thread amnesia** (no prior messages in packet). **Your reply** participates in the same **focus / voice** strip as VE (`CouncilQuestionTextarea` in `App.tsx`: synthetic focus + `ZENAF_VOICE_TRANSCRIPT_DOM_FIRST` / `ZENAF_VE_FOCUS_INSERT_TEXT` handlers). Assistant **`[ID: …]`** mentions render as chips via **`EntityMentionText`** when the UI uses it on raw text.
- **Perspectives:** Frontend types, list, detail, creator, import/export; localStorage; passed to council as custom definitions.
- **Foundation shell split (as-built):** In `mainView === 'perspectives'`, actor/detail/training/editor content is rendered in a Foundation-local right pane. The global council/chat aside remains the shared shell surface and is not repurposed by Foundation detail state.
- **File Steward:** Analyze, Recommend, Assess, Simulate; folder picker; simulation tree with effective target folders and filtered overrides.
- **Web research / Next step:** zenaf_tools; wired to /run.
- **Intake API:** Config, Gmail OAuth, POST email/fax, POST email/poll, GET/PATCH queue, judgment.
- **Policy layer:** data_access with tiers and request_access; used by mirror.get_item_with_content().
- **Synthetic intake:** Generate cases, evaluate pipeline, export failures; pytest intake quality and synthetic regression.
- **Startup:** Dependency checks, mirror load; VE DB init on first use. **Launcher:** open-cockpit.bat / open-cockpit.ps1.
- **Vision map (frontend):** Live React Flow projection of VE entities (ideas→fruit metaphor), zen sand rake layer, right-panel **growth triad** (Water / Soil / Fruit) from existing VE fields — see **`docs/01_TRUTH/VISION_MAP_AND_ZEN_PROJECTION.md`**.
- **Council/chat panel visuals (as-built):** Unchanged shell behavior — right-side by default across cockpit surfaces, with vision map retaining its existing left-oriented inspector/chat behavior.

## 4.2 Implemented but incomplete

- Intake mirror sync state (mirror_sync, mailbox_action exist; poll does not call set_sync_state or record_mailbox_action).
- Tier B/C access (get_item_with_content and policy check implemented; no API route or UI calls it).
- Adapters: Registry + LLM adapter (Ollama); Mailbox adapter protocol exists, no implementation.
- Policy adoption: Only intake mirror uses policy; council and File Steward do not.

## 4.3 Planned / not yet built

- **AI traces + outcomes:** Extend `createAiActionTrace` / panel usage to Workspace and Content; persist `trace_id` from server; record evaluate **apply/dismiss** on traces. (See **`ACTIVE_VS_PLANNED.md`** near-term list.)
- **Developmental guidance:** v1 is council-packet + UI transparency only; optional **persistence**, server-side assembly, and additional product sinks (next-step, harvest, guidance scripts) remain open (see Part **2.4**).
- Council / File Steward using policy when touching Tier B/C or external.
- Mailbox adapter implementation; intake via adapter registry. LLM via adapters (tools use providers directly).
- Sync state and mailbox action used in poll. API or UI for Tier B/C content.
- Configurable mirror path and VE DB path.
- **Shared artifact store** (Phase 1–3). **Node substrate** (Phase 1–2).
- **Radar:** Other modules emitting signals; aggregate into shared Radar UI (Execution + Signals view).

## 4.4 Open questions

*(See OPEN_QUESTIONS.md for full list.)* Examples: Judgment layer scope; policy enforcement/adoption; queue/mirror as generic primitive; sync state in poll; VE DB init strategy; Tier B/C in UI; mailbox mutation and audit; adapters vs providers; configurable paths; access_policy shim removal.

## 4.5 Summary: projection vs current state

| Area | Intended projection | Current state |
|------|---------------------|----------------|
| **Identity** | Subject/Node primitive; Mandelbrot scaling; judgment substrate generic. | Concrete entities in VE, Content, Intake, council; SubjectRef in substrate; no NodeRef yet. |
| **Memory** | Shared artifact store; opt-in read/write; inspectable. | Not built. Only recent VE decisions (council path) and conversation history (cockpit) reach prompts. |
| **Node layer** | NodeRef/NodeSnapshot + adapters; optional use at seams. | Not built. |
| **Radar / Signal** | One Radar, many emitters; Signal as first-class entity; Execution + Signals view. | **Signal** entity and API in place; **Radar** is a view over Signal; VE radar buckets + signals; no other emitters yet. |
| **Profiles** | Versioned; proposed updates only; no silent self-training. **Core vs perspectives:** one canonical core, many perspectives as lenses (§1.4a). | **Core profile:** structured fields + reconcile/conversation; **prompt anchoring** enforces conversation over training text (§2.6). **Multiple `core_profiles` rows** still allowed in DB/UI; **singular UX** is planned. **Perspectives:** frontend localStorage; versioning/distillation pipeline for personality layer not implemented. |
| **Content** | Conductor of pipeline; brief → drafts → packages → handoff tracking; VE-linked. | Content tab and generation exist; full pipeline stages and handoff tracking partial. |
| **Council folder** | Constraint + role_limit for folder workflow; optional Phase 2 parse + “Add to recommendations”. | Constraint and folder advisor implemented; Phase 2 parser not. |
| **Progression** | User-controlled; one run at a time; suggested next actions visible. | Current cockpit has modes and last result; progression as in COCKPIT_PROGRESSION_DESIGN not fully applied. |
| **Policy** | All Tier B/C and external egress through shared data access policy. | Only intake mirror get_item_with_content uses it. |
| **Vision map** | Spatial/orienting view of execution tree + interpretive growth UI; optional link to signals/council depth. | **Implemented** as projection + panel; heuristics client-only; no map-specific API. Details: **`VISION_MAP_AND_ZEN_PROJECTION.md`**. |
| **Developmental guidance** | Hypothesis-level read model; transparent to user; influences prompts as **optional labeled context**, not silent routing. | **v1 implemented:** client assembly + **`council_preflight.developmental_guidance`** + enriched council string + cockpit panel. No unified durable store; not yet wired to next-step / harvest / scripts beyond council. |
| **Focus context + voice** | Registered field focus in header; voice inserts at cursor; no transcript misrouting to wrong field. | **Implemented:** universal strip + VE regions + Execution inline creates + council **Your reply** (`council` synthetic entity); registry-backed Rewrite; transcribe API; DOM-first event for council. Not every textarea in the app is registered. |
| **Zenaf / council precision** | Turn-level contract in backend; **`[DRAFT_VALUE]`** / **`[ID]`** discipline; fast LLM budget; optional thread amnesia on priority turns. | **Implemented:** **`local_ai/response_trunk.py`**, **`local_ai/integration_commit.py`**, **`local_ai/council_preflight.py`** (history policy), **`local_ai/zenaf_tools.py`** conversational path (**15s** timeout), **`EntityMentionText`** for **`[ID: …]`** chips. Detail: **§2.7**, **§3.6**; law: **`CODEBASE_TRUTH_RULES.md`** §9. |

---

# Part V — Definitions & machine-readable reference

## 5.1 Layer model

| Layer | Name | Scope |
|-------|------|--------|
| 1 | Universal Core | Cross-source entities and primitives: Signal, ActivityEvent. Storage and API for these. |
| 2 | Domain profile | Extraction profiles, signal kinds, severity/grouping rules per domain. |
| 3 | Organization instance | Org-specific benchmarks, fixtures, dashboards (e.g. Healing Haven). |

## 5.2 Canonical entities (Layer 1)

### Signal

- **Ownership:** Layer 1. Single source of truth for attention/risk/opportunity/blocker/info.
- **Storage:** `signals` table (vision_execution SQLite). Module: `local_ai/signals/`.
- **Fields (snake_case in API):** `id`, `kind`, `title`, `detail`, `source`, `source_excerpt`, `source_ref`, `confidence`, `linked_initiative_id`, `linked_project_id`, `linked_task_id`, `status`, `created_at`, `updated_at`
- **Status values:** `new` | `acknowledged` | `linked` | `resolved` | `dismissed`
- **Kind values:** `attention` | `risk` | `opportunity` | `blocker` | `info`
- **API:**
  - `POST /vision-execution/signals` — bulk create (body: array of SignalCreate).
  - `GET /vision-execution/signals` — list (query: `status`, `status_not`, `source`).
  - `PATCH /vision-execution/signals/{id}` — update `status` and/or `linked_initiative_id`, `linked_project_id`, `linked_task_id`.

### ActivityEvent

- **Ownership:** Layer 1. Append-only log; not event sourcing.
- **Storage:** JSONL file `activity.log` at repo root. Module: `local_ai/activity.py`.
- **Fields:** `id`, `type`, `entity_type`, `entity_id`, `related_entity_id`, `actor`, `source`, `detail`, `created_at`
- **Reader:** `get_recent_activity(limit=100)` — returns events newest-first.

## 5.3 Activity type enums (machine-readable)

**ActivityType (event type):**

```json
["meeting_processed", "signal_created", "signal_acknowledged", "signal_linked", "signal_resolved", "signal_dismissed", "task_created", "task_completed", "initiative_created"]
```

**ActivityEntityType (entity type):**

```json
["meeting", "signal", "task", "project", "initiative"]
```

## 5.4 Views (must not become models)

| View | Canonical model | Rule |
|------|-----------------|------|
| Radar | Signal (and initiatives/projects/tasks/capacity for buckets) | Radar reads via `list_signals(status_not_in=[resolved,dismissed])` and displays; no Radar-specific storage for signals. |
| Chunk progress / chunk results | None (processing state) | Ephemeral UI state only; not persisted. |
| Meeting extraction staging | Ideas, initiatives, projects, tasks, assets, persons, signals (after commit) | StagingArea is a review view; commit writes to canonical APIs. |
| Timeline / Gantt | Initiative, Project, Task | TimelineRow is derived by `buildTimelineRows()`; not persisted. |
| Inbox triage staging | InboxItem, Signal (when pushed) | Staging is review state; do not persist a separate triage entity. |

## 5.5 Signal lifecycle (backend)

- **Create:** `create_signal` / `create_signals` in `local_ai/signals/storage.py` → logs `signal_created`.
- **Update:** `update_signal` → calls `_log_signal_lifecycle_activity(signal_id, old_status, new_status, updated)`.
- **Logged transitions:** `acknowledged`, `linked`, `resolved`, `dismissed`. For `linked`, `related_entity_id` is set from `linked_project_id` or `linked_initiative_id` or `linked_task_id`.

## 5.6 Frontend conventions (Vision Execution)

- **API base:** `VISION_EXECUTION_API` → `/vision-execution`. Paths relative: e.g. `/signals`, `/signals/{id}`.
- **Radar:** Fetches `GET /radar`; `radarData.signals` are Signal-shaped with optional `status`, `severity` (derived). Actions call `apiPatch('/signals/' + id, body)` then `fetchRadar()`.
- **Linking:** PATCH body for link: `{ status: 'linked', linked_initiative_id | linked_project_id | linked_task_id }`. Only one linked id set per request.
- **Types:** `RadarSignalItem` includes optional `status`; linked targets displayed by resolving id to title from initiatives/projects/tasks lists in memory.

## 5.7 File and module map

| Concern | Location |
|---------|----------|
| **AI action traces (client), result panel, field rewrite `action_intent` map** | `frontend/src/ai-actions/` (`types.ts`, `traceHelpers.ts`, `traceSink.ts`, `AiActionResultPanel.tsx`, `fieldRewriteIntent.ts`); VE wiring: `vision-execution/focus/ContextActionBarContent.tsx`, `VisionExecutionView.tsx` |
| **Focus context strip, voice recording, DOM-first transcript routing** | `frontend/src/App.tsx` (`UniversalContextStrip`, `CouncilQuestionTextarea`, council event listeners); `vision-execution/focus/VisionExecutionFocusContext.tsx`, `VeFocusRegion.tsx`, `veVoiceRecordingContext.tsx`, `FocusContextRecordButton.tsx`, `insertTextEvent.ts` (`ZENAF_VOICE_TRANSCRIPT_DOM_FIRST`, `ZENAF_VE_FOCUS_INSERT_TEXT`), `fieldCapabilityRegistry.ts`, `types.ts` (`EntityType` includes `council`) |
| Signal model, service, storage | `local_ai/signals/models.py`, `service.py`, `storage.py` |
| Activity events, enums, log, reader | `local_ai/activity.py` |
| Radar (view) | `local_ai/vision_execution/radar.py` — uses `SigS.list_signals(status_not_in=[...])`, `_signal_to_radar_item()` |
| Signals API | `api/routes/vision_execution.py` — POST/GET/PATCH under `/signals` |
| Radar UI + signal actions + link UI | `frontend/src/vision-execution/VisionExecutionView.tsx` |
| Core Signal type (frontend) | `frontend/src/meeting-intelligence/types.ts` — `CoreSignal`, `CoreSignalStatus` |
| Radar response type | `frontend/src/vision-execution/types.ts` — `RadarSignalItem`, `RadarResponse` |

---

# Part VI — How to use this doc

- **Staged work:** When implementing a planned phase, use the source doc (e.g. SHARED_ARTIFACT_MEMORY_PLAN, NODE_SUBSTRATE_IMPLEMENTATION_PLAN) for exact steps and file touch list; this doc is the map.
- **Direction:** When making design choices, align with Part I (intent) and Part II (projection) so the system moves toward the intended architecture without big-bang refactors.
- **Status:** For “what’s done vs planned” *by surface and flow* (including AI trace coverage), use **`ACTIVE_VS_PLANNED.md`** first; use **Part IV here** for the same story in the context of intent + projection + definitions. For unresolved decisions and gaps, use OPEN_QUESTIONS.md.
- **Definitions:** When layers, entities, or APIs change, update Part V and the relevant “current state” bullets in Part IV.

Update this document when major phases are completed, when new staged plans are added, or when the intended projection is refined in source docs.
