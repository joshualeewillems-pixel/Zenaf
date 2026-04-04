# Intake → Vision Execution Bridge

Design spec for graduating intake items into the Vision Execution core. Intake is staging/triage; Vision Execution is the durable center. This document defines the bridge layer only—no second parallel system.

**Durable decision anchoring:** Intake is not a durable center of meaning. When recording decisions in Vision Execution, prefer anchoring to a **core entity** when one exists: `task`, `project`, `initiative`, `person`, or `asset`. Use `entity_type="intake"` only as an **interim or transitional** anchor (e.g. “triaged, not yet graduated”) when no core entity exists yet. If we need a durable record before any core entity is created, use an explicit bridge record (e.g. a minimal record that references intake_item_id and later links to the created task/decision) rather than treating the intake item id as the long-term home for decisions.

---

## Bridge outcomes

When an intake item is “done” with triage, it can graduate in one of these ways:

| Outcome | Description |
|--------|-------------|
| **1. Archive / remain intake-only** | Item stays in intake; marked done/archived. No Vision Execution entity created. |
| **2. Create task** | Create a Vision Execution task (under a project) from the item. |
| **3. Record decision** | Record a durable decision in Vision Execution, linked to the intake context. |
| **4. Attach / update existing initiative or project** | Link the item to an existing initiative or project (e.g. add note, update brief, or create a task under that project). |
| **5. Link / create person or asset reference** | Associate the item with a person or asset (existing or new) in Vision Execution. |

---

## Per-outcome definition

### 1. Archive / remain intake-only

| Field | Value |
|-------|--------|
| **When to use** | Item is triaged, no execution commitment. Junk, FYI, or “handled outside Atria.” |
| **Minimal fields** | None for Vision Execution (no entity created). Intake: set `status=done` and optionally `archived=true`. |
| **Source intake item** | Referenced by `intake_item_id`; queue/mirror item remains the only record. |
| **Source judgment** | Optional `source_judgment_id` for audit (why we archived). |
| **Human confirmation** | Not required for archive; operator can mark done without graduating. |
| **AI can propose** | AI can propose “archive” (e.g. likely_junk); human can confirm or override. No automatic archive without user action. |

---

### 2. Create task

| Field | Value |
|-------|--------|
| **When to use** | Item implies a concrete action; we want a task in the execution backlog. |
| **Minimal fields** | **Required:** `project_id` (Vision Execution project to attach to), `title` (from subject or summary). **Optional:** `description` (summary or sanitized snippet), `assignee_id`, `priority`, `status=Todo`, `notes`. |
| **Source intake item** | Stored on bridge proposal and, after apply, in Vision Execution decision or task notes: `intake_item_id`. Vision Execution task has no formal “intake_item_id” column today; store in `notes` or a single `source_intake_item_id` field if added. |
| **Source judgment** | `source_judgment_id` on the bridge proposal; optional snapshot of interpretation/proposed_action in decision if we record a decision for the create. |
| **Human confirmation** | **Required.** Creating a task is a commitment; confirm before calling Vision Execution task create. |
| **AI can propose** | Yes. AI (or rules) can propose “create task” with suggested project, title, summary. Human confirms or edits then applies. |

---

### 3. Record decision

| Field | Value |
|-------|--------|
| **When to use** | We want a durable record that a decision was made (e.g. “create task approved,” “attached to project X,” “lane override”). Ties intake outcome to execution history. |
| **Minimal fields** | **Required:** `entity_type`, `entity_id`, `decision_type`. **Preferred entity_type:** a core entity—`task`, `project`, `initiative`, `person`, or `asset`—when one exists (e.g. new task id after “create task,” or project id after “attach to project”). **Interim only:** `entity_type="intake"` with `entity_id=intake_item_id` when no core entity exists yet (e.g. triage/override before graduation). **Optional:** `ai_proposal_snapshot`, `final_values_snapshot` (e.g. lane, category, judgment_id, intake_item_id for traceability). |
| **Source intake item** | Keep intake as staging: reference via `final_values_snapshot.intake_item_id` (and optional `judgment_id`) for traceability. Prefer `entity_id` = core entity id (task, project, initiative, person, asset), not intake item id. |
| **Source judgment** | Captured in `final_values_snapshot` or `ai_proposal_snapshot` (e.g. `judgment_id`, lane, proposed_action). |
| **Human confirmation** | Required when the decision represents a commitment (e.g. lane override, graduate to task). Optional for pure “record that we triaged” if we ever do that. |
| **AI can propose** | Yes. AI proposes; human confirms; we record decision with proposal + final values. |

---

### 4. Attach / update existing initiative or project

| Field | Value |
|-------|--------|
| **When to use** | Item clearly belongs to an existing initiative or project (e.g. “refill request” under “Pharmacy operations” project). Either attach as context or create a task under that project. |
| **Minimal fields** | **Required:** `target_entity_type` (`initiative` or `project`), `target_entity_id`. **Optional:** `proposed_title` / `proposed_summary` for a new task under that project; or notes/brief update for the initiative/project. |
| **Source intake item** | `intake_item_id` on bridge proposal; after apply, link is via task (if we create one) or via decision (entity_type=initiative/project, entity_id=that id, decision_type e.g. `"intake_attached"`). |
| **Source judgment** | `source_judgment_id` on proposal; can be stored in decision snapshot. |
| **Human confirmation** | **Required.** Attaching to an initiative/project is a commitment; user selects target and confirms. |
| **AI can propose** | Yes. AI can suggest initiative/project (and optionally task title); human picks target and confirms. |

---

### 5. Link / create person or asset reference

| Field | Value |
|-------|--------|
| **When to use** | Item involves a specific person (e.g. sender, assignee) or asset; we want that reflected in Vision Execution (person record or asset record, or link from task/decision). |
| **Minimal fields** | **For link:** `target_entity_type` (`person` or `asset`), `target_entity_id`. **For create:** Person: `name`, optional `role`, `contact_info`; Asset: `name`, `asset_type`, optional `notes`. |
| **Source intake item** | `intake_item_id`; relationship is contextual (e.g. “task created from intake item X is assigned to person Y”). |
| **Source judgment** | `source_judgment_id` optional; useful if we inferred the person/asset from content. |
| **Human confirmation** | **Required** for create; **recommended** for link (avoid wrong association). |
| **AI can propose** | Yes. AI can suggest “link to person X” or “create person Y”; human confirms. |

---

## Bridge proposal / object shape

Minimal shape for a **graduation proposal** (one per intended outcome, before apply):

```json
{
  "intake_item_id": "uuid",
  "source_judgment_id": "uuid | null",
  "graduation_type": "archive | create_task | record_decision | attach_to_initiative_or_project | link_or_create_person_or_asset",
  "target_entity_type": "task | decision | initiative | project | person | asset | null",
  "target_entity_id": "uuid | null",
  "proposed_title": "string",
  "proposed_summary": "string",
  "linked_people": ["person_id"],
  "linked_assets": ["asset_id"],
  "proposed_by": "ai | human | system",
  "status": "proposed | confirmed | applied"
}
```

- **intake_item_id** — Required. Which queue item this proposal is for.
- **source_judgment_id** — Optional. The judgment record that supports this graduation (e.g. latest for the item).
- **graduation_type** — Required. One of the five outcomes.
- **target_entity_type** — For create_task → `task`; record_decision → `decision`; attach → `initiative` or `project`; link/create person/asset → `person` or `asset`. Null for archive.
- **target_entity_id** — Set after apply (e.g. new task id, new decision id); or required when attaching/linking to existing (initiative/project/person/asset id).
- **proposed_title** — Suggested title (e.g. for a task); can be from subject/summary.
- **proposed_summary** — Suggested description/summary.
- **linked_people** — Person ids to associate (e.g. assignee).
- **linked_assets** — Asset ids to associate.
- **proposed_by** — Who proposed: `ai` (model/rules), `human` (operator), `system` (e.g. rule).
- **status** — `proposed` (draft), `confirmed` (human approved, not yet applied), `applied` (Vision Execution entity created/updated).

**Persistence:** Proposals can live in memory or a small table (e.g. `intake_graduation_proposal`) keyed by `intake_item_id` and optional `id`. No separate “bridge” DB; prefer one table or in-memory + optional mirror column. Keep the bridge thin.

---

## First 2–3 bridge actions to implement (priority order)

| Priority | Action | Scope |
|----------|--------|--------|
| **1** | **Create task from intake item** | API: accept intake_item_id, project_id, title, optional description/assignee/notes; optionally source_judgment_id. Create Vision Execution task via existing storage; store intake_item_id in task notes or a single `source_intake_item_id` if we add it. Require human confirmation (UI confirms before POST). Optionally record a decision (entity_type=task, entity_id=new task id, decision_type=`intake_graduate_task`) after create. |
| **2** | **Attach intake item to existing project or initiative** | API: accept intake_item_id, target_entity_type (project | initiative), target_entity_id. Either (a) create a task under that project with title/summary from item and link in notes, or (b) record a decision linking intake to that initiative/project. Human selects target and confirms. |
| **3** | **Record decision from intake item** | API: accept intake_item_id, decision_type, optional source_judgment_id, optional final_values_snapshot. When a core entity exists (e.g. after creating a task or attaching to project), call DecisionCreate with **entity_type=that core** (task, project, initiative, etc.) and entity_id=that id; store intake_item_id and judgment_id in final_values_snapshot for traceability. Use entity_type=`intake` and entity_id=intake_item_id **only as interim** when no core entity exists (e.g. triage/override before any graduation). Prefer creating a task or attaching to project first so the decision anchors to core. |

Implementation notes:

- Add a single **bridge module** (e.g. `local_ai/intake/bridge.py` or `local_ai/bridge/intake_to_core.py`) that takes a proposal or explicit params and calls Vision Execution storage (create_task, create_decision). No new persistence beyond optional proposal table or task notes.
- Expose via **API** under `/intake` (e.g. POST `/intake/graduate` or POST `/intake/queue/{id}/create-task`, etc.) so the cockpit can call after user confirmation.
- **Do not** add a full “bridge workflow” engine or a second queue; keep it as a thin layer: intake item + user choice → one or two Vision Execution calls.

**Implemented (Priority 1 — Create task):**

- **API:** POST `/intake/queue/{item_id}/create-task` with body `{ project_id, title?, summary?, notes?, source_judgment_id? }`.
- **Module:** `local_ai/intake/bridge.py` → `create_task_from_intake_item()`. Creates Vision Execution task and a Decision (entity_type=task, entity_id=task_id, decision_type=`intake_graduate_task`).
- **Lifecycle linkage (no dedicated table):** (1) Task notes end with a parseable line: `[Atria lifecycle] intake_item_id=<id> judgment_id=<id>`. (2) Decision `final_values_snapshot` = `{ intake_item_id, judgment_id?, task_id }`.

---

## Summary

| Outcome | Human confirm? | AI can propose? | First implementation |
|---------|-----------------|------------------|------------------------|
| Archive | No (mark done in intake only) | Yes (suggest archive) | Existing PATCH queue item |
| Create task | **Yes** | Yes | **Priority 1** |
| Record decision | **Yes** (for commitments) | Yes | **Priority 3** |
| Attach to initiative/project | **Yes** | Yes | **Priority 2** |
| Link/create person or asset | **Yes** | Yes | Later |

Bridge object: minimal proposal shape with intake_item_id, source_judgment_id, graduation_type, target_entity_type/id, proposed_title/summary, linked_people/assets, proposed_by, status. First implementations: (1) create task, (2) attach to project/initiative, (3) record decision.
