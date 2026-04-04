# Information Lifecycle

How information moves through Atria from observation to outcome, and how the system records this lifecycle. The lifecycle **links** Vision Execution (durable core), Intake (staging/triage), and Judgment (reasoning) without duplicating them.

---

## Five lifecycle stages

| Stage | Meaning | Owner |
|-------|---------|--------|
| **1. Observation** | External input captured (e.g. intake email, file, user message). | Intake (or future: File Steward, council input). |
| **2. Judgment** | AI or human interpretation (signals, classification, proposals). | Judgment layer (reasoning); persisted today via intake mirror for intake domain. |
| **3. Decision** | Durable commitment recorded in Vision Execution (e.g. decision record or task creation). | Vision Execution. |
| **4. Action** | Execution steps taken (task assignment, file change, external operation). | Vision Execution + external systems; Atria records intent or result. |
| **5. Outcome** | Final result or resolution: **derived** (inferred from task/decision state) or **explicit** (human/AI assessment when completion ≠ success). | Vision Execution; derived by default; explicit assessment optional for learning. |

---

## Stage 1: Observation

| Field | Value |
|-------|--------|
| **Owned by** | Intake (for email/fax); in future, other subsystems for other input types. |
| **Object types** | Intake: **queue item** (in-memory + mirror_item). Fields: id, external_id, subject, sender, summary, created_at, source (email/fax). Future: file scan result, user message, etc. |
| **Identifiers to link** | **observation_id** = intake item `id` (or external_id for mailbox correlation). Lifecycle record should store this as the origin. |
| **Minimal metadata to record** | For lifecycle: observation_id, observation_type (e.g. `intake_email`), observed_at (created_at). Do not copy full body or attachments; reference the owning subsystem. |

---

## Stage 2: Judgment

| Field | Value |
|-------|--------|
| **Owned by** | Judgment layer (reasoning); persistence today is intake mirror (mirror_judgment) for intake domain. |
| **Object types** | **JudgmentRecord**: id, entity_id (e.g. intake item id), domain, interpretation, proposed_action, confidence, signal_codes, interpretation_codes, policy_codes, observation_ref, superseded_by, correction_note. |
| **Identifiers to link** | **judgment_id** = the JudgmentRecord id. For a lifecycle we care about “the judgment that led to a decision”; typically the latest non-superseded record for the entity, or the one explicitly chosen at graduation. |
| **Minimal metadata to record** | For lifecycle: judgment_id, entity_id (links to observation when entity = intake item). Optional: decision_type hint (e.g. proposed lane). Do not duplicate full interpretation/proposed_action in the lifecycle record; reference judgment_id and read from judgment store or mirror when needed. |

---

## Stage 3: Decision

| Field | Value |
|-------|--------|
| **Owned by** | Vision Execution. |
| **Object types** | **Decision** (Vision Execution): id, entity_type, entity_id, decision_type, ai_proposal_snapshot, final_values_snapshot, created_at. **Task** (when “decision” is to create work): task id, project_id, title, etc. The creation of a task is itself a commitment; optionally also record a Decision with entity_type=task, entity_id=task_id. |
| **Identifiers to link** | **decision_id** (Vision Execution decision record id) and/or **task_id** (if the decision was “create task”). Lifecycle record should reference decision_id and, if applicable, task_id or other created entity. |
| **Minimal metadata to record** | For lifecycle: decision_id, optional task_id (or initiative_id, etc.), decision_type, decided_at. Snapshot content stays in Vision Execution; lifecycle stores only IDs and type. |

---

## Stage 4: Action

| Field | Value |
|-------|--------|
| **Owned by** | Vision Execution (task updates, assignment, status) and external systems (mailbox move, file write). Atria records intent or result where it has visibility. |
| **Object types** | Task status/assignee updates; mailbox_action (audit); future: outbound API calls, file operations. |
| **Identifiers to link** | **action_ref**: task_id + action type (e.g. `status_change`, `assigned`), or mailbox_action id, or external system id. Lifecycle can reference one or more action refs. |
| **Minimal metadata to record** | For lifecycle: action_type (e.g. `task_created`, `task_assigned`, `task_done`, `mailbox_marked_read`), target_entity_type, target_entity_id, optional at (timestamp). Do not log full payloads; reference the owning store. |

---

## Stage 5: Outcome

Outcome can be represented in two ways. Keep the lifecycle **lightweight** by default; add explicit assessment only when needed for learning (e.g. when “completion” is not “successful outcome”).

### 1. Derived outcome

- **Meaning:** Inferred from existing task / decision / project state. No separate human or AI write.
- **Source:** Task status (e.g. Done, Dropped), decision_type, project/initiative status. Query Vision Execution when needed.
- **Examples:** Task status=Done → derived outcome `completed`; status=Dropped → `cancelled`; no task yet → `pending`.
- **Use:** Default for lifecycle. No extra persistence. Enables “what’s the state of this chain?” without over-logging.

### 2. Explicit outcome assessment

- **Meaning:** A human- or AI-authored evaluation of what actually happened. “Completed” in the system may not mean “succeeded” in practice.
- **When to use:** When we want to learn from outcomes (e.g. task was marked Done but the real result was “deferred” or “partially failed”), or when we need a short rationale or follow-up note.
- **Minimal shape:** Optional. One of: (a) a simple label (e.g. `succeeded`, `deferred`, `failed`, `superseded`) plus optional free-text note or (b) a reference to a separate “outcome assessment” record (Vision Execution or thin table) with entity_id (task/decision), assessor (human|ai), label, optional note, assessed_at.
- **Owned by:** Vision Execution (e.g. a small outcome_assessment table or a decision_type like `outcome_assessed` with snapshot). Do not duplicate task/decision content; store only the assessment and link by entity_id.

| Field | Value |
|-------|--------|
| **Owned by** | Vision Execution. Derived outcome = inferred from state. Explicit assessment = optional record (human/AI-authored). |
| **Object types** | Derived: task status, decision_type (no new object). Explicit: optional outcome_assessment or Decision with decision_type e.g. `outcome_assessed`; fields: entity_type, entity_id, outcome_label, optional note, assessor, assessed_at. |
| **Identifiers to link** | task_id, decision_id. For explicit: outcome_entity_id (task or decision that was assessed). |
| **Minimal metadata to record** | Lifecycle: **derived** outcome (e.g. `completed`, `cancelled`, `pending`) and outcome_at when available from state; **explicit** only if present: outcome_label, assessed_at, optional assessor. Do not require explicit assessment for every lifecycle. |

---

## Minimal lifecycle record structure

A **lifecycle record** is a thin link object. It points at existing objects; it does not duplicate their content.

**Option A — Dedicated lifecycle table (minimal):**

| Field | Type | Purpose |
|-------|------|--------|
| id | string | Unique lifecycle record id. |
| observation_id | string | Origin (e.g. intake item id). |
| observation_type | string | e.g. `intake_email`. |
| judgment_id | string \| null | Judgment that led to decision (optional). |
| decision_id | string \| null | Vision Execution decision id (when created). |
| task_id | string \| null | Vision Execution task id (if task was created). |
| outcome | string \| null | Derived outcome (e.g. `completed`, `cancelled`, `pending`). Inferred from task/decision state when not stored. |
| outcome_assessed_at | string \| null | Optional. When an explicit outcome assessment was recorded (human or AI). |
| outcome_assessment_label | string \| null | Optional. Explicit assessment label (e.g. `succeeded`, `deferred`, `failed`) when present; distinct from derived outcome. |
| created_at | string | When lifecycle record was created. |
| updated_at | string \| null | When outcome or last stage was set. |

**Option B — No dedicated table; use Vision Execution decision as the link:**

- When an intake item graduates (e.g. create task), create a Vision Execution **Decision** with:
  - entity_type = `"intake"` or `"task"`
  - entity_id = intake_item_id or new task_id
  - decision_type = e.g. `"intake_graduate_task"`, `"intake_triage"`
  - final_values_snapshot = minimal: `{ "intake_item_id", "judgment_id", "task_id" (if created) }`
- Lifecycle = “all decisions where entity_type=intake or decision_type contains intake_*”. No separate lifecycle table; query decisions + task notes (source_intake_item_id) to reconstruct.

**Recommendation:** Start with **Option B** to avoid new persistence. Add Option A only if we need to query “all lifecycles” or “outcome by observation” without scanning decisions. If we add Option A, populate it when we create a Vision Execution decision from intake (single write; no duplicate content).

---

## Example: Intake email becomes a task

1. **Observation** — Email arrives; intake pipeline creates queue item. observation_id = intake_item.id (e.g. `item-uuid-1`). observation_type = `intake_email`. observed_at = item.created_at.

2. **Judgment** — Pipeline creates JudgmentRecord. judgment_id = record.id; entity_id = intake_item.id. Proposed action: lane=needs_attention, category=referral. Operator may add a correction judgment (lane_override).

3. **Decision** — User confirms “Create task.” Vision Execution creates Task (project_id, title from subject, notes include intake_item_id). Optionally create Decision: entity_type=`task`, entity_id=new task_id, decision_type=`intake_graduate_task`, final_values_snapshot = `{ "intake_item_id": "item-uuid-1", "judgment_id": "judgment-uuid-1" }`.

4. **Action** — Task is assigned; status changes to In Progress. Action refs: task_id + status_change. (Mailbox actions, if we add them, would be separate action refs.)

5. **Outcome** — **Derived:** Task marked Done → outcome = `completed`; outcome_entity_id = task_id; outcome_at = task.updated_at (inferred from state or stored in lifecycle row). **Explicit (optional):** Later, user or AI adds “actually deferred” with a short note → outcome_assessment_label = `deferred`, outcome_assessed_at set; derived outcome remains `completed` for system state; explicit assessment enables learning that completion ≠ success.

**Identifiers linked end-to-end:** observation_id (intake item) → judgment_id → decision_id and task_id → outcome (derived; optional explicit assessment). All stored in existing subsystems; lifecycle is the chain of IDs (in Decision snapshot or in a single lifecycle row).

**Implemented:** The first path (intake item → task) is implemented. POST `/intake/queue/{item_id}/create-task` creates the task and a Vision Execution Decision; task notes include a parseable `[Atria lifecycle] intake_item_id=... judgment_id=...` line; Decision `final_values_snapshot` holds intake_item_id, judgment_id, task_id. See `local_ai/intake/bridge.py` and INTAKE_TO_CORE_BRIDGE.md.

---

## Rules for when a lifecycle should be created

| Trigger | Create lifecycle? | How |
|---------|-------------------|-----|
| Intake item created | No separate lifecycle record. Observation exists (queue item); judgment exists when pipeline runs. | N/A |
| Intake item graduated to Vision Execution (task, decision, attach to project) | **Yes.** Create a Vision Execution Decision that links intake + judgment + created entity (Option B). Optionally add one row to a lifecycle table (Option A) with observation_id, judgment_id, decision_id, task_id. | On bridge apply (create task / record decision / attach). |
| Intake item archived or marked done with no graduation | Optional. If we want “closed without graduation” in analytics, record a Decision with entity_type=`intake`, entity_id=intake_item_id, decision_type=`intake_archive`. Otherwise no lifecycle record. | On archive/done, if we choose to record. |
| Council or Idea Lab creates/updates Vision Execution entity | Yes, when we implement. Decision (and optional lifecycle row) with entity_type and entity_id pointing at the created idea/initiative/task; snapshot can reference council session or idea id. | When bridge from council/Idea Lab to core is implemented. |
| Task status → Done (or Dropped) | Do not create a new lifecycle record. **Derived outcome:** infer from task status (Done → completed, Dropped → cancelled) when querying, or update outcome on existing lifecycle row. **Explicit assessment:** optional; create only when someone records an outcome assessment (e.g. “succeeded” / “deferred” / “failed”) for learning. | Update existing lifecycle row (Option A) or leave outcome to Vision Execution state; add explicit assessment record only when needed. |

**Rule of thumb:** Create a lifecycle link (Decision + optional lifecycle row) **whenever an intake item (or future observation) causes a Vision Execution entity to be created or a durable decision to be recorded.** Do not create a lifecycle for every judgment or every queue update—only when crossing into the core.

---

## Guidance: avoid over-logging and duplication

| Do | Don’t |
|----|--------|
| Store **identifiers** (observation_id, judgment_id, decision_id, task_id) in the lifecycle or in Decision snapshot. | Copy full observation content (body, attachments) into the lifecycle or decision snapshot. |
| Use **existing** Vision Execution decisions and task notes (e.g. source_intake_item_id) as the link. | Create a second “lifecycle” copy of the same decision or task. |
| Create **one** Decision per graduation event (one row in Vision Execution). | Create multiple lifecycle records for the same observation→decision path. |
| Use **derived outcome** (inferred from task/decision/project state) as the default; add **explicit outcome assessment** only when needed for learning (completion ≠ successful outcome). | Require explicit assessment for every lifecycle; or duplicate full task/decision state into an outcome table. |
| Record **minimal** final_values_snapshot (ids + decision_type, not full item/judgment payload). | Store full judgment interpretation or full queue item in the snapshot. |
| Treat lifecycle as **reference chain**: observation → judgment → decision → task → outcome. | Build a parallel “lifecycle” store that replicates intake mirror or Vision Execution tables. |

**Principle:** The lifecycle is a **link layer** so Atria can later analyze “which observations led to which decisions and outcomes.” The source of truth for each stage remains its owning subsystem (Intake mirror, Judgment/mirror, Vision Execution). Lifecycle records only connect them by id. **Outcome:** Prefer **derived** (inferred from state) to keep the model lightweight; add **explicit outcome assessment** (human or AI) when “completion” is not the same as “successful outcome” and we want to learn from it.
