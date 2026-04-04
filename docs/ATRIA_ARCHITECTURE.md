# Atria Architecture: Hub-and-Spoke Orchestration

## Architectural stance

- **Atria is the intelligence and orchestration shell.** It coordinates work and decisions; it does not replace mature tools.
- **External systems remain the systems of record** where appropriate. Gmail, calendar, file storage, project management tools, and social schedulers own their data; Atria reads and coordinates.
- **Atria sits above them and coordinates them.** We buy or integrate infrastructure; we build the orchestration, council, decision memory, intake intelligence, and personality framework.

---

## Core principle

| We do | We do not |
|-------|-----------|
| Build orchestration, council, decision memory, intake routing, radar/trunk/executive orientation, and (future) personality and coherence | Rebuild or replace Gmail, calendar, file storage, PM tools, or social schedulers |
| Integrate best-in-class tools via thin adapters | Put core decision logic inside adapters |
| Own the “why” and “what next”; delegate “where it lives” to external systems | Duplicate system-of-record responsibility inside Atria |

---

## 1. Atria Core (owned / differentiated)

These domains are **native to Atria** and must remain under our control. They contain the decision logic and intelligence layer.

| Domain | Location (current) | Responsibility |
|--------|--------------------|----------------|
| **Council / perspectives** | `local_ai/atria_tools.py` (`run_council`, `run_council_stream`) | Multi-perspective reasoning; no single adapter owns this. |
| **Vision → execution engine** | `local_ai/vision_execution/` (service, radar, initiative_evaluate, meeting_extract) | Ideas → initiatives → projects → tasks; derived fields; strategic radar. |
| **Intake routing / triage logic** | `local_ai/intake/pipeline.py`, classifier, redaction, lanes | Classify, PHI detect, redact, assign category/priority/lane; **not** the mechanics of fetching mail. |
| **Decision memory** | `local_ai/vision_execution/` (decisions table, service, storage) | Append-only record of decisions for learning and consistency. |
| **Radar / trunk / executive orientation** | `local_ai/vision_execution/radar.py`, service `get_radar()` | Act now, blocked, overcapacity, unanchored, kill candidates. |
| **Future: personality learning** | Planned; decision memory is the substrate | Learn from decisions and feedback; keep in core. |
| **Future: coherence / pattern-understanding** | Planned | Cross-entity patterns; keep in core. |

**Rule:** Core must not depend on adapter internals. Adapters produce **normalized internal objects**; core consumes them and owns all routing, scoring, and next-step logic.

---

## 2. Integration adapters (thin connectors)

Adapters are **thin**: they authenticate, fetch/send, and normalize. They **never** contain core decision logic (no triage rules, no council, no radar).

| Adapter category | Examples | Adapter responsibilities only |
|------------------|----------|------------------------------|
| **Mailbox / comms** | Gmail, Google Workspace; Outlook, Microsoft 365 | Auth, fetch messages (mirror-only where applicable), send; normalize to internal message/item shape. |
| **Docs / files** | Google Drive, OneDrive, local files | Auth, list/read/write; normalize to internal doc/file references. |
| **Workflow tracker** | Linear, Asana, Jira, Notion, etc. | Auth, fetch/sync tasks and projects; push updates; normalize to internal task/project shape. |
| **Social scheduler** | Buffer, Hootsuite, etc. | Auth, fetch scheduled posts; publish; normalize to internal post/schedule shape. |
| **Fax / communications** | Twilio, e-fax providers | Auth, send/receive; normalize to same intake channel as email (e.g. IntakeItem). |
| **LLM providers** | Ollama, OpenAI, Anthropic, etc. | Auth (if needed), send prompt, return text; no orchestration. |

**Contract (see `local_ai/adapters/README.md`):**

- **Authenticate** — tokens, refresh, config; adapter-owned.
- **Fetch / send** — raw API calls; adapter-owned.
- **Normalize** — map external DTOs to **internal objects** (e.g. `IntakeItem`, `NormalizedTask`, `NormalizedMessage`); adapter-owned.
- **Never** — routing rules, priority logic, council prompts, radar logic, or decision recording; those live in core.

---

## 2b. Judgment Layer (shared, neutral protocol)

The **Judgment Layer** is shared infrastructure used by modules (e.g. intake). It is **not** fused into Atria Core and **not** the same as the future personality-training layer.

| Concept | Meaning |
|--------|--------|
| **JudgmentRecord** | One structured reasoning event: interpretation, proposed action, confidence, reason codes; optional observation_ref, superseded_by, correction_note. |
| **PersonalityProfile / JudgmentProfile** | (Future.) Reusable style/lens that influences many judgments over time; pluggable, not the same as judgment itself. |

- **Atria Core** = orchestration / system coordination.
- **Judgment Layer** = shared protocol for observations, interpretation, proposed action, confidence, reason codes, review/correction.
- **Modules** (intake, vision→execution, council) use the judgment layer.
- **Future personality** = pluggable lenses that shape judgment; built on top of this protocol.

Current implementation: intake domain only; minimal `JudgmentRecord` with **signal_codes** (what was observed), **interpretation_codes** (what classifier inferred), **policy_codes** (why lane was chosen); **observation_ref** (subject_preview, body_length, matched_signals—no raw content). The **latest non-superseded record** is the canonical source of interpretation/action; `lane_override` on the item is a convenience mirror for UI/filtering. In-memory store is short-term; persistence recommended for auditability. No generic framework yet. See `local_ai/judgment/`.

---

## 3. Storage strategy

- **Keep the current modular backend.** Vision Execution: SQLite + `storage.py` + `service.py`. Intake: persistent mirror (SQLite `intake_mirror.db`) + in-memory queue as working set; see §4.
- **Service layers** (e.g. `vision_execution/service.py`, intake pipeline) sit above storage so **storage can migrate** (e.g. Postgres, tenant-aware) without changing core or API contracts.
- **State vs event memory** remain distinct:
  - **State:** current entities (ideas, initiatives, projects, tasks, queue items).
  - **Event / decision memory:** append-only `decisions` (and future event log if added); not overwritten.
- **Workspace / tenant:** schema and API are prepared for `workspace_id` / tenant boundaries later; no immediate requirement to add columns until multi-tenant is needed.

---

## 4. Intake: mailbox, mirror, and data tiers

The intake path uses a **three-layer model** so that the mailbox stays the source of truth, Atria has durable operational memory, and content access is scoped by tier.

### 4.1 Layers

| Layer | Role |
|-------|------|
| **Mailbox** | External source of truth (read-only for now). Gmail/IMAP; we poll and never mutate in this pass. |
| **Persistent mirror** | Atria’s durable local projection (SQLite `intake_mirror.db`). Stores metadata, judgment history, sanitized content, sync state, and mailbox action log. Survives restart; single source for rebuild. |
| **In-memory queue** | Working set for UI and orchestration. Rebuilt from the mirror on startup; updated on poll and on PATCH. |

Future **mailbox edits** (e.g. mark read, move, archive) should be driven from the **persistent mirror and mailbox action log**, not from ephemeral memory alone — so we have auditability, idempotency, and replay.

### 4.2 Data tiers

Mailbox-derived content is split into three tiers so most code uses operational or sanitized data and raw content is restricted.

| Tier | Name | Contents | Typical use |
|------|------|----------|-------------|
| **A** | Operational | external_id, thread_id, sender, subject, timestamps, summary, category, lane, confidence, judgment refs, lane_override, status, notes, archived, sync metadata, mailbox action history | UI, queue list, filters, orchestration |
| **B** | Sanitized | Cleaned/normalized body text (PHI-redacted where applied). Stored in mirror; not in in-memory queue by default. | Triage, summarization, routing, internal reasoning, future external model calls where raw PHI is not needed. Not legally de-identified; treat as lower-exposure. |
| **C** | Raw | Full unsanitized body/content. Placeholder only (`raw_content_ref`); full raw storage deferred. | Only when a task truly requires full content; tightly scoped and explicitly justified. |

- **Default:** Most operations use Tier A or B. Tier C requires an explicit access justification (internal policy primitive in `local_ai/policy/data_access.py`).
- **Access levels:** `metadata_only` (A), `sanitized_text` (A+B), `raw_content_required` (A+B+C when implemented). Code that needs Tier B or C declares the level and, for C, a short justification.
- **Mirror schema:** `mirror_item` holds Tier A fields plus `sanitized_body_text` (B) and `raw_content_ref` (C placeholder). `mailbox_action` stores action_type, payload, created_at, applied_at, mailbox_id, result_status, error_message for audit.

See `local_ai/policy/data_access.py`, `local_ai/intake/mirror.py`, and `mirror.get_item_with_content()` for the policy and tiered read path. All modules that touch Tier B or Tier C content (intake, council/perspectives, File Steward/file sorting, future connectors) must go through this shared data access policy layer before accessing or emitting that content.

---

## Proposal A: Cleanest adapter architecture for the current codebase

1. **Introduce a small adapter layer** under `local_ai/adapters/`:
   - **Contract:** Abstract base or protocol per **adapter kind** (e.g. `MailboxAdapter`, `LLMProvider`, `WorkflowTrackerAdapter`) with methods: `auth`, `fetch` (and optionally `send`), and **return normalized internal types**.
   - **Registry:** A single registry (e.g. `ADAPTER_REGISTRY`) mapping adapter kind + name (e.g. `mailbox.gmail`, `llm.ollama`) to an instance or factory. Core and API resolve adapters by key; no direct imports of concrete implementations in core.
   - **Internal types:** Define shared normalized types (e.g. `IntakeItem` already; add `NormalizedTask`, `NormalizedMessage` when adding workflow/mailbox adapters) in `local_ai/adapters/types.py` or next to the domain (e.g. intake keeps `IntakeItem`).

2. **Refactor existing integrations into adapters** without changing behavior:
   - **Mailbox:** Move Gmail OAuth + IMAP fetch + body normalization behind a `MailboxAdapter` implementation; keep pipeline (classify → PHI → redact → `IntakeItem`) in core. The adapter returns “raw” normalized messages or a minimal struct; core intake runs pipeline and enqueues.
   - **LLM:** Keep `local_ai/providers/` but have the default provider registered as the `llm.ollama` adapter; other providers (OpenAI, Anthropic) added as further adapter implementations.
   - **Fax:** Remain “paste” or a small adapter that accepts raw text and produces the same input shape as mailbox (so pipeline stays shared).

3. **API and core** call the registry (e.g. “get mailbox adapter `gmail`”, “get LLM adapter `ollama`”) instead of importing `gmail_oauth` or `providers/ollama` directly. This keeps the codebase scalable when adding Outlook, a second LLM, or a workflow tracker.

4. **Document** the contract and registry in `local_ai/adapters/README.md` (see that file); this doc references it.

---

## Proposal B: Integrate vs rebuild — by category

| Category | Recommendation | Rationale |
|----------|----------------|-----------|
| **Mailbox / email** | **Integrate.** Use Gmail and Outlook via adapters; keep existing pipeline and queue. | Mature; we only need mirror + normalize. |
| **Calendar** | **Integrate.** When needed, add Google Calendar / Outlook Calendar adapters; core owns “what to do with” events, not storage. | Same as mailbox. |
| **Docs / files** | **Integrate.** Use Drive, OneDrive, or shared storage; adapter normalizes to internal doc/file refs. | Don’t build a doc store. |
| **Workflow / PM** | **Integrate.** Linear, Asana, Jira, Notion, etc. as workflow-tracker adapters; Vision Execution stays the strategy layer; tracker is source of record for tasks. | Best-in-class tools; we orchestrate. |
| **Social scheduling** | **Integrate.** Buffer, Hootsuite, etc. as content-distribution adapters. | Commodity; we don’t replace. |
| **Fax / comms** | **Integrate.** Use a provider (e.g. Twilio); adapter normalizes to same intake path as email. | No need to build fax stack. |
| **LLM** | **Integrate.** Ollama, OpenAI, Anthropic, etc. as LLM adapters. | We own prompts and orchestration; they own inference. |

**Rebuild:** None of the above. Atria does not replace any of these systems; it only adds the orchestration and intelligence layer on top.

---

## Proposal C: Differentiated vs commodity — what stays native to Atria

**Differentiated (native):**

- **Council / multi-perspective reasoning** — unique to Atria.
- **Vision → execution engine** — ideas, initiatives, projects, tasks, radar, trunk, executive view; strategy and “what to do next” live here even when tasks are synced to an external tracker.
- **Intake routing and triage** — classification, PHI, redaction, lanes, suggested_action; pipeline and rules in core.
- **Decision memory** — append-only decisions; future personality and coherence depend on it.
- **Radar / trunk / executive orientation** — derived from Vision Execution state (and later from external sync); logic stays in core.
- **Future personality and coherence layers** — learning and pattern-understanding on top of decision memory and context.

**Commodity (integrate, do not rebuild):**

- Mailbox, calendar, docs, file storage, workflow tracker, social scheduler, fax, LLM inference — all integrated via adapters; no duplicate system-of-record logic in Atria.

---

## Proposal D: Order of integration

Recommended sequence so each step delivers value and builds on the previous one:

1. **Workflow tracker**  
   - Enables “one place” for strategic view (Vision Execution) while tasks live in Linear/Asana/Jira.  
   - Add `WorkflowTrackerAdapter` contract; implement one provider (e.g. Linear).  
   - Core: sync read (import tasks/projects into radar/trunk) and optionally push “next steps” or links back.  
   - No need to move existing Vision Execution tasks into the tracker first; can run in parallel and sync gradually.

2. **Mailbox / file layer**  
   - Already partially done (Gmail/IMAP, intake pipeline).  
   - Harden adapter split (mailbox adapter → normalized message → core pipeline).  
   - Add Outlook adapter; optionally add a minimal “files” adapter (e.g. list recent Drive files) for context.  
   - Keeps intake and comms as a single conceptual layer with one pipeline.

3. **Content distribution layer**  
   - Social scheduler adapters (e.g. Buffer): fetch scheduled posts, publish, normalize to internal “post” or “schedule” type.  
   - Core can suggest content or times; adapter only sends and reports status.  
   - Builds on same pattern as workflow and mailbox.

4. **Future personality layer**  
   - After decision memory and usage are stable: add learning from decisions and feedback, then coherence/pattern layer.  
   - Depends on core decision memory and possibly on richer context from the above integrations; do this last.

---

## Proposal E: Immediate refactors for scalability (without overbuilding)

1. **Adapter boundary (minimal):**
   - Add `local_ai/adapters/` with a **protocol/ABC and registry** (see Proposal A).  
   - Move “fetch + normalize” for email behind a mailbox adapter interface; keep pipeline in `local_ai/intake/`.  
   - Register Ollama as the default LLM adapter so new LLM providers are “add adapter, register, use same key.”

2. **Intake queue persistence:**
   - Replace in-memory queue with a small persistence layer (e.g. SQLite table or same DB as Vision Execution) behind the existing `queue_store` API so `add_item`, `get_queue`, `update_item`, `get_by_external_id` stay the same.  
   - Enables restart-safe intake and a path to event log later without changing core logic.

3. **Ideas:** Use Vision Execution only (`/vision-execution`); standalone Idea Lab stack was removed (see **`docs/01_TRUTH/TRUTH_CONVERGENCE.md`**).

4. **Single “orchestration” entry point (optional, lightweight):**
   - Document that `api/main.py` + `local_ai/atria_tools.py` form the orchestration entry (mode dispatch → tools → council, next_step, etc.). No need for a big new framework; ensure new features (e.g. “sync from Linear”) are invoked from this layer or from explicit routes that call core services + adapters.

5. **Do not yet:**
   - Add workspace_id/tenant columns until multi-tenant is a requirement.  
   - Build a generic “event bus” or message queue until intake or workflow sync clearly needs it.  
   - Move Vision Execution to another DB; keep SQLite and service layer as-is for now.

---

## Summary

- **Atria = intelligence/orchestration shell.** External systems remain systems of record.  
- **Core:** council, vision→execution, intake routing, decision memory, radar/trunk/executive, future personality/coherence.  
- **Adapters:** thin — auth, fetch/send, normalize; no core logic.  
- **Storage:** keep modular backend; service layer over storage; state vs decision memory distinct; workspace/tenant later.  
- **Integrate:** mailbox, calendar, docs, workflow tracker, social, fax, LLM. **Rebuild:** nothing.  
- **Order:** (1) workflow tracker, (2) mailbox/file, (3) content distribution, (4) personality layer.  
- **Immediate refactors:** adapter contract + registry, intake queue persistence, no overbuild.
