# Vision → Execution Engine — Design

## 1. Backend file/module structure

```
local_ai/vision_execution/
  __init__.py       # Public API surface
  models.py         # Pydantic request/response models + schema constants (table names, column lists)
  schema.sql        # SQLite DDL (CREATE TABLE) — single source of truth for DB shape
  storage.py        # SQLite connection, init_db(), CRUD per entity (raw sqlite3)
  service.py        # Business layer: calls storage, enforces invariants (Phase 1: thin pass-through)
  scoring.py        # Phase 2: derived fields (weightedScore, approvalReady, etc.)
  council.py        # Phase 4: council integration for recommendations
  ai.py             # Phase 4: flesh-out, assess valuation, next-step suggestions

api/routes/
  __init__.py
  vision_execution.py   # FastAPI router prefix="/vision-execution"; CRUD endpoints
```

- **Not** under `tools/` (this is strategy/execution, not file ops).
- **Not** in `POST /run`; dedicated routes only.
- DB file: e.g. `data/vision_execution.db` (created on first use).

---

## 2. SQLite schema (normalized MVP)

- **Single DB file**, one schema. Tables use `id` (TEXT UUID) as primary key unless noted.
- **JSON columns** for list-of-IDs (linkedPeople, tags, dependencyIds, etc.) to avoid many join tables in Phase 1; can normalize later.

### Tables

| Table | Purpose | Key columns |
|-------|---------|-------------|
| **core_profiles** | Core Profile ("Digital Phil") | id, name, core_definition, current_goals, growth_focus_12_months, economic_engine, non_negotiables, strategic_filter, current_constraints, capacity_limit, kill_philosophy, strength_positioning, created_at, updated_at |
| **ideas** | Raw idea capture | id, title, summary, description, status, tags (JSON), created_by, desired_outcome, linked_people (JSON), linked_assets (JSON), linked_ideas (JSON), created_at, updated_at |
| **initiatives** | Evaluated opportunity | id, source_idea_id, title, brief, status, owner_id, priority_rank_manual, strategic_value_manual, energy_impact_manual, estimated_cost_ai, estimated_timeframe_ai, philosophical_alignment_ai, next_step_ai, required_people (JSON), required_assets (JSON), dependencies, risks, recommendation, counts_toward_capacity, manual_override, kill_criteria, notes, created_at, updated_at |
| **projects** | Implementation container | id, initiative_id, title, brief, status, owner_id, supporting_owner_ids (JSON), priority, start_date, end_date, estimated_weekly_hours, deliverables, complexity, current_focus, next_step_ai, notes, created_at, updated_at |
| **tasks** | Smallest work unit | id, project_id, parent_task_id, title, description, assignee_id, status, priority, estimated_hours, due_date, dependency_ids (JSON), completion_criteria, notes, created_at, updated_at |
| **persons** | Real people | id, name, role, relationship_type, contact_info, strengths, needs, wants, availability, notes, created_at, updated_at |
| **capacity_profiles** | Weekly capacity per person | person_id (PK), weekly_capacity_hours, created_at, updated_at |
| **assets** | Material relationships | id, name, asset_type, owner_id, status, availability, cost, time_availability, linked_idea_ids (JSON), linked_initiative_ids (JSON), linked_project_ids (JSON), notes, created_at, updated_at |
| **decisions** | Decision history (append-only) | id, user_id, entity_type, entity_id, decision_type, ai_proposal_snapshot (JSON), final_values_snapshot (JSON), created_at |

**Status enums** stored as TEXT; application validates against allowed values.

**ExecutiveSnapshot** and roadmap-specific tables deferred to Phase 5.

---

## 3. API routes

**Prefix:** ` /vision-execution`

| Method | Path | Description |
|--------|------|-------------|
| **Core profiles** | | |
| GET | /core-profiles | List (expect 0–1 for MVP) |
| POST | /core-profiles | Create |
| GET | /core-profiles/{id} | Get one |
| PATCH | /core-profiles/{id} | Update |
| **Ideas** | | |
| GET | /ideas | List (filter by status optional) |
| POST | /ideas | Create |
| GET | /ideas/{id} | Get one |
| PATCH | /ideas/{id} | Update |
| **Initiatives** | | |
| GET | /initiatives | List |
| POST | /initiatives | Create |
| GET | /initiatives/{id} | Get one |
| PATCH | /initiatives/{id} | Update |
| **Projects** | | |
| GET | /projects | List |
| POST | /projects | Create |
| GET | /projects/{id} | Get one |
| PATCH | /projects/{id} | Update |
| **Tasks** | | |
| GET | /tasks | List (optional ?project_id=) |
| POST | /tasks | Create |
| GET | /tasks/{id} | Get one |
| PATCH | /tasks/{id} | Update |
| **Persons** | | |
| GET | /persons | List |
| POST | /persons | Create |
| GET | /persons/{id} | Get one |
| PATCH | /persons/{id} | Update |
| **Capacity** | | |
| GET | /capacity-profiles | List |
| PUT | /capacity-profiles | Upsert by person_id (body: person_id, weekly_capacity_hours) |
| GET | /capacity-profiles/{person_id} | Get one |
| **Assets** | | |
| GET | /assets | List |
| POST | /assets | Create |
| GET | /assets/{id} | Get one |
| PATCH | /assets/{id} | Update |
| **Decisions** | | |
| POST | /decisions | Record one decision (append-only) |
| GET | /decisions | List (optional ?entity_type=, ?entity_id=, ?limit=) |
| **Radar** | | |
| GET | /radar | Strategic radar (act_now, blocked, overcapacity, unanchored, high_value_stalled, kill_candidates) |

All request bodies and responses use snake_case JSON. 404 on missing resource; 400 on validation errors.

---

## 4. Frontend insertion point and component structure

- **Replace** the existing "Idea Lab" top-level nav and `IdeaLabView` with **Vision → Execution** (label e.g. "Vision & Execution" or "Vision Execution").
- **mainView** continues as `'workspace' | 'perspectives' | 'idea_lab'` → change `'idea_lab'` to `'vision_execution'` and render a new `VisionExecutionView`.
- **VisionExecutionView** (single widget container):
  - **Sub-views** (tabs or sidebar): Core Profile, Ideas, Initiatives, Projects, Tasks, People & Capacity, Assets, Roadmap (placeholder), Executive (placeholder).
  - **Phase 1:** List + detail + create/edit for Core Profile, Ideas, Initiatives, Projects, Tasks, Persons, Capacity, Assets. Roadmap and Executive show a “Coming in Phase 5” (or similar) message.
  - **Data:** All from `GET/POST/PATCH` on `http://127.0.0.1:8010/vision-execution/...`. No local-only state for persistence; backend is source of truth.
- **Idea Lab** code (IdeaLabView, idea_lab API usage, Idea Lab nav) is removed or fully replaced so the app no longer exposes Idea Lab.

---

## 5. Ambiguities and simplifications

- **Core Profile cardinality:** One “Digital Phil” profile for MVP. List returns 0 or 1; UI can show single edit form. No “create second profile” in Phase 1.
- **IDs:** UUIDs (v4) generated server-side; stored as TEXT in SQLite.
- **List-of-ID fields:** Stored as JSON arrays (e.g. `["id1","id2"]`) in TEXT columns. Simplifies Phase 1; no link tables yet.
- **CapacityProfile:** One row per person; `person_id` unique. PUT upsert by `person_id`.
- **Timestamps:** ISO 8601 strings (UTC); `created_at` / `updated_at` set by backend.
- **Derived fields (weightedScore, approvalReady, etc.):** Not stored in Phase 1; computed in Phase 2 and exposed via same or extended endpoints.
- **ExecutiveSnapshot:** No table in Phase 1; Phase 5.
- **Roadmap:** View-only in Phase 5; no roadmap table in Phase 1.
- **Status values:** Enforced in API (Pydantic) and optionally in DB (CHECK or app-level). Phase 1: validate in API only.

---

## 6. Phase 1 implementation scope

- **Backend:** `local_ai/vision_execution/` with `models.py`, `schema.sql`, `storage.py`, `service.py`, `__init__.py`. SQLite init on first use; CRUD for core_profiles, ideas, initiatives, projects, tasks, persons, capacity_profiles, assets.
- **API:** `api/routes/vision_execution.py` with router and all CRUD endpoints above; register in `main.py` with prefix `"/vision-execution"`.
- **Frontend:** Replace Idea Lab with Vision Execution: nav entry + `VisionExecutionView` with tabs/sections for Core Profile, Ideas, Initiatives, Projects, Tasks, People & Capacity, Assets; list + detail + create/edit using the new API. Placeholder panels for Roadmap and Executive.
- **Idea Lab:** Remove from nav and from `main.py` router include; remove or replace `IdeaLabView` and any Idea Lab–specific API base URL usage. Old Idea Lab backend files can remain in repo but unmounted.

No AI, no scoring, no council in Phase 1.

---

## 7. Future: Initiative Tree (design only — no rewrite yet)

This section is **planning only**. Current implementation stays as four entities (Ideas, Initiatives, Projects, Tasks) with separate CRUD and tables.

### 7.1 Current vs tree intuition

| Current entity | Tree role | Current “parent” (FK) |
|----------------|-----------|------------------------|
| Idea | Unconstrained branch (root or loose node) | None (linked_ideas is many-to-many, not hierarchy) |
| Initiative | Weighted/approved branch | `source_idea_id` (optional) |
| Project | Operational branch | `initiative_id` (optional) |
| Task | Execution leaf | `project_id` (required) or `parent_task_id` (subtask) |
| Roadmap | — | View over approved/active path through the tree |

The existing FKs already form a **chain**: Idea → Initiative → Project → Task(s), with optional Task subtrees. So the current model is a “sparse tree” across four tables; no schema change is required to *conceive* of it as a tree.

### 7.2 Should the current entity model stay as-is now?

**Yes.** Keep Ideas, Initiatives, Projects, Tasks as separate tables and CRUD. Reasons:

- Clear semantics per entity (idea vs initiative vs project vs task).
- Existing API and frontend are built around these types.
- A single “node” table would require a large refactor and migration; not justified for current scope.

### 7.3 Would an Initiative Tree abstraction simplify later?

**Yes, as a view/abstraction layer**, not necessarily as a single table:

- **Unified tree view**: A virtual or materialized “node” set where each row has `node_type` (idea | initiative | project | task), `parent_id` (derived from existing FKs), and a stable `id` (current primary keys). Roadmap = filter to “current trunk” (e.g. status in Approved/Active, ordered by path).
- **Benefits later**: One place to query “everything under this idea” or “path from root to this task”; simpler roadmap/executive queries; possible future “branching” (e.g. one idea → many initiatives) without reworking the mental model.
- **Implementation options**: (1) Keep four tables, add a view or service that computes `parent_id` and optional `lineage_path` from existing columns; or (2) later introduce a single `nodes` table and migrate/mirror current rows into it. Option 1 is backward-compatible and sufficient for “tree” queries.

### 7.4 Mapping current records into a future tree (without breaking MVP)

| Table | Row → tree node | Parent in tree |
|-------|------------------|----------------|
| ideas | One node per row; `node_type = 'idea'` | `parent_id = null` (or future “workspace” root) |
| initiatives | One node per row; `node_type = 'initiative'` | `parent_id = source_idea_id` |
| projects | One node per row; `node_type = 'project'` | `parent_id = initiative_id` |
| tasks | One node per row; `node_type = 'task'` | `parent_id = parent_task_id ?? project_id` |

No new columns are required to *define* this mapping: it uses `source_idea_id`, `initiative_id`, `project_id`, and `parent_task_id`. A future view or service can derive `parent_id` and, if desired, a materialized `lineage_path` (e.g. `/ideas/{id}/initiatives/{id}/projects/{id}/tasks/{id}`).

### 7.5 Optional future-proofing fields (evaluate later)

- **parent_node_id** — Redundant with existing FKs unless we collapse into one table; skip for now.
- **source_lineage_id** — “Root” of the lineage (e.g. idea id). Initiatives already have `source_idea_id`; projects could denormalize “root idea” for “all under this idea” queries. Useful later, not required for MVP.
- **lineage_path** — Materialized path (e.g. `/idea-123/initiative-456/project-789`). Helps “trunk” and “everything under X” queries without walking FKs. Can be added later and backfilled; no need to add in MVP.
- **node_type** — Only needed if we merge into one table; current table name is the type. Skip.

### 7.6 Recommended stance and minimum change now

- **A. Stance now:** Keep the current entity model and CRUD as-is. Do not collapse entities or add tree-specific columns for MVP. Treat the tree as a **future view/abstraction** layered on top of existing FKs.
- **B. Future tree concept:** One logical tree: nodes = ideas (roots), initiatives (child of idea), projects (child of initiative), tasks (child of project or task). Parent derived from `source_idea_id`, `initiative_id`, `project_id`, `parent_task_id`. Roadmap = selected path(s) through this tree (e.g. approved/active nodes in order).
- **C. Minimum safe change now:** **None.** No new columns or application logic. Document this section so a later refactor can introduce a tree view or optional `lineage_path` / `lineage_root_id` without re-deriving the mapping. If a single additive change were desired later, the smallest would be an optional `lineage_path` (TEXT, nullable) on initiatives, projects, and tasks, left null until backfilled—but not recommended for current pass.

---

## 8. Phase 2: Detail/Edit, Derived Fields, Evaluate Initiative

### 8.1 Detail/Edit UI structure (Phase 2A)

- **Initiatives (first):** In the Initiatives tab, clicking a row opens a **detail panel** (below the list or right sidebar). Panel shows:
  - Header: title (editable), status (dropdown), Close button
  - Sections: Brief (textarea), Owner (dropdown from persons), Source idea (dropdown: ideas list; "None" option)
  - AI fields: estimated cost, timeframe, philosophical alignment, next step, recommendation (editable text)
  - Manual scores: priority rank, strategic value, energy impact (number inputs)
  - Lists: required people, required assets (comma-separated or tag input for MVP)
  - Text: dependencies, risks, kill criteria, notes
  - **Linked:** "Projects from this initiative" — list projects where `initiative_id` = this initiative
  - Actions: Save (PATCH), Cancel (close panel)
- **Same pattern** for Ideas, Projects, Tasks, People, Assets: click opens detail panel with editable fields and PATCH on Save. List/create flows unchanged.

### 8.2 Where derived fields are computed (Phase 2B)

- **Backend only.** New module `local_ai/vision_execution/derived.py` (or extend `scoring.py`) computes:
  - **Initiative:** `weightedScore`, `approvalReady`, `returnOnTime` from stored fields
  - **Project:** `duration`, `completionReadiness`, `unanchoredFlag`
  - **Capacity:** `activeWeeklyHours`, `capacityDelta`, `overcapacity` (from projects/tasks + capacity_profiles)
- **When:** Attach to the dict returned by `get_*` / `list_*` in the **service layer** (after storage returns). Do not store derived values in the DB for MVP.
- **API:** No new endpoints; GET responses include derived fields.

### 8.3 Evaluate Initiative flow (Phase 2C)

- **Backend:** `POST /vision-execution/initiatives/:id/evaluate` — request optional (e.g. core_profile_id). Returns **proposed values only:** `{ estimatedCostAi, estimatedTimeframeAi, philosophicalAlignmentAi, nextStepAi, recommendation }`. Single LLM call (initiative title/brief + optional core profile). No PATCH; no silent overwrite.
- **UX:** In Initiative detail panel, button "Evaluate Initiative". Call endpoint → show modal or inline "Proposed values" → user clicks "Apply" (copy into form) or "Discard". User can then edit and Save, or Save without applying.

---

## 9. Derived fields — formulas and rules (Phase 2B)

All derived fields are **computed in the backend only** and attached to GET/list responses. They are **read-only** in the frontend. Implemented in `local_ai/vision_execution/derived.py`.

### 9.1 Initiative

| Field | Type | Formula / rule |
|-------|------|-----------------|
| **weightedScore** | number \| null | Weighted average of `priority_rank_manual` (0.4), `strategic_value_manual` (0.4), `energy_impact_manual` (0.2), each normalized to 0–5, then scaled to 0–100. If any of the three is null, `weightedScore` is null. |
| **approvalReady** | boolean | `true` when: (1) `weightedScore` is not null and ≥ 60, (2) `brief` is non-empty, (3) `status` is `Draft` or `Evaluating`. |
| **returnOnTime** | number (0–1) | 1.0 if both `estimated_cost_ai` and `estimated_timeframe_ai` are non-empty; 0.5 if exactly one is non-empty; 0.0 if neither. |

### 9.2 Project

| Field | Type | Formula / rule |
|-------|------|-----------------|
| **duration** | number \| null | Calendar days between `start_date` and `end_date` (inclusive). Null if either date is null or invalid. |
| **completionReadiness** | number (0–1) | +0.4 if status is `Ready` or `Active`; +0.3 if `deliverables` non-empty; +0.3 if `next_step_ai` non-empty. Capped at 1.0. |
| **unanchoredFlag** | boolean | `true` when `initiative_id` is null (project not linked to an initiative). |

### 9.3 Capacity (per person)

| Field | Type | Formula / rule |
|-------|------|-----------------|
| **activeWeeklyHours** | number | Sum of `project.estimated_weekly_hours` for projects where this person is `owner_id` or in `supporting_owner_ids`, and project `status` is `Ready` or `Active`. |
| **capacityDelta** | number | `activeWeeklyHours - weekly_capacity_hours`. Positive = over-committed. |
| **overcapacity** | boolean | `true` when `capacityDelta` > 0. |

---

## 10. Technical debt / future normalization

- **required_people, required_assets, dependencies (and similar list/text fields):** Currently stored or edited as comma-separated strings or JSON arrays in the UI where applicable. This is a **temporary compromise**. Later, these should become proper relational links or normalized references (e.g. many-to-many link tables, or structured references) so that we can query and validate by entity id. Document in code where these are handled as comma-separated or single-text.

---

## 11. Decision records (personality learning dataset)

Append-only **decisions** table captures major user decisions in the Vision → Execution workflow. Purpose: future dataset for personality learning and decision-graph analysis. No personality training or inference is implemented yet; this is capture only.

### 11.1 Schema

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | UUID |
| user_id | TEXT | Optional; no auth yet |
| entity_type | TEXT | e.g. `initiative`, `project` |
| entity_id | TEXT | ID of the entity the decision refers to |
| decision_type | TEXT | See below |
| ai_proposal_snapshot | TEXT (JSON) | Optional; AI-suggested values at decision time |
| final_values_snapshot | TEXT (JSON) | Optional; values actually applied/saved |
| created_at | TEXT | ISO 8601 |

### 11.2 Decision types (recorded today)

| decision_type | When recorded |
|---------------|----------------|
| **evaluation_applied** | User clicks Apply on initiative evaluation proposal; snapshots = proposal and applied values. |
| **initiative_approved** | User saves initiative with status = Approved; final_values_snapshot = saved payload. |
| **initiative_rejected** | User saves initiative with status = Killed; final_values_snapshot = saved payload. |

Planned (not yet wired): **evaluation_overridden** (user discards proposal and saves different values), **priority_change**, **manual_score_override**.

### 11.3 API

- **POST /vision-execution/decisions** — Body: `DecisionCreate` (user_id, entity_type, entity_id, decision_type, ai_proposal_snapshot?, final_values_snapshot?). Records one decision.
- **GET /vision-execution/decisions** — Query: optional `entity_type`, `entity_id`, `limit`. List decisions for analysis/export.

Workflows are unchanged; recording is best-effort (frontend POSTs decision then performs the action; recording failure does not block the action).

---

## 12. Strategic Radar (orientation layer)

Read-only view that surfaces what needs attention using existing data. No new tables, no heavy AI, no schema changes.

### 12.1 Bucket rules

| Bucket | Rule | Item type |
|--------|------|-----------|
| **act_now** | Initiatives with status in `Approved`, `Active` and at least one of: no owner (`owner_id` null/empty), no next step (`next_step_ai` empty), or no linked projects (no project with `initiative_id` = this initiative). | initiative |
| **blocked** | Projects with `status = 'Blocked'`; tasks with `status = 'Blocked'`. | project, task |
| **overcapacity** | People (capacity profiles) where derived `overcapacity` is true (activeWeeklyHours > weekly_capacity_hours). | person |
| **unanchored** | Projects where `initiative_id` is null (derived `unanchoredFlag` true). | project |
| **high_value_stalled** | Initiatives with derived `weightedScore` ≥ 70 and `status` not in `Active`, `Complete`, `Killed` (stricter to avoid cluttering with merely decent initiatives). | initiative |
| **kill_candidates** | Initiatives with `weightedScore` < 45 and `status` not in `Complete`, `Killed`. Paused initiatives are not automatically included. | initiative |

### 12.2 API

- **GET /vision-execution/radar** — Returns a single JSON object with one key per bucket; each value is an array of minimal item objects (type, id, title/name, and optional context fields). Snake_case. Read-only.

### 12.3 Response shape

```json
{
  "act_now": [{ "type": "initiative", "id": "...", "title": "...", "status": "Approved", "reason": "no_owner" }],
  "blocked": [{ "type": "project", "id": "...", "title": "...", "status": "Blocked" }, { "type": "task", "id": "...", "title": "...", "project_id": "...", "status": "Blocked" }],
  "overcapacity": [{ "type": "person", "id": "...", "name": "...", "active_weekly_hours": 45, "weekly_capacity_hours": 40 }],
  "unanchored": [{ "type": "project", "id": "...", "title": "..." }],
  "high_value_stalled": [{ "type": "initiative", "id": "...", "title": "...", "weighted_score": 72, "status": "Approved" }],
  "kill_candidates": [{ "type": "initiative", "id": "...", "title": "...", "weighted_score": 35, "status": "Draft" }]
}
```

### 12.4 Frontend

- New **Radar** tab. On select, fetch `GET /vision-execution/radar`. Render one card per bucket with heading and list of items (type + title/name). Read-only; no workflow actions. Optional: link each item to the relevant entity tab later.

---
## 13. UI Operational Notes (merged from `VISION_EXECUTION_UI_PASS.md`)
This section records the UI “operational truth” updates for Vision → Execution detail panels and workflow affordances that were previously documented as a pass/deliverables document.

### 13.1 Sectioned detail panels (reduce “admin form” feel)
All major entity detail panels are split into collapsible sections instead of a single long form:
- **Ideas**: Basics, Intent, Relationships, Notes.
- **Initiatives**: Basics, Strategic evaluation, Requirements, Risks / kill criteria, Relationships, Notes / diagnostics.
- **Projects**: Basics, Execution, Owners / capacity, Deliverables, Dependencies / risks, Notes (+ optional derived/read-only and tasks list).
- **Tasks**: Basics, Assignment, Timing / effort, Dependencies, Completion criteria, Notes.
- **Assets**: Basics, Ownership / availability, Relationships, Notes.
- **People**: Basics, Role / relationship, Capacity, Strengths / needs / wants, Notes.

### 13.2 Hidden / metadata / read-only areas
`DetailSection` + `MetadataSection` collapse admin/debug fields so the main UI stays decision-oriented:
- IDs and timestamps are shown in collapsed metadata areas.
- Derived/computed fields are shown as read-only in collapsed “Derived (read-only)” sections.

### 13.3 Relationship editors use multi-selects (no free-text IDs)
- **Ideas**: `linked_people`, `linked_assets`, `linked_ideas` via `EntityMultiSelect`.
- **Initiatives**: `seats` (role/assignee/effort editor) + `required_assets` via `EntityMultiSelect`. (`required_people` is legacy/compat transport only.)
- **Projects**: `supporting_owner_ids` via `EntityMultiSelect`.
- **Tasks**: `dependency_ids` via `EntityMultiSelect`.
- **Assets**: linked entity IDs via `EntityMultiSelect`.

### 13.4 Initiative AI evaluation is treated as an explicit action
Initiative AI fields are presented as decision support outputs:
- “Run evaluation” is a dedicated action button.
- AI proposal is shown as read-only outputs.
- Apply decision / Edit / Defer / Dismiss make the action model explicit.

### 13.5 Meeting capture UX simplifications
- chunk progress uses a single progress bar + short status text
- detailed per-chunk diagnostics move under a collapsible “Technical details” section

### 13.6 Roadmap and Executive as views over existing entities
Roadmap and Executive screens are orientation views (no new core entities):
- Roadmap = filterable/ordered view over initiatives/projects/tasks.
- Executive = synthesized dashboard cards fed by existing data + radar/capacity signals.

### 13.7 Initiative seats as an operational resourcing signal
Initiative resourcing now treats `seats` as a practical decision input in the UI (not just a hidden editor field):
- **Seats summary (compact card in “Resourcing”):**
  - total seats (`seats.length`)
  - filled vs unfilled seats (filled = seats with an assigned person; unfilled = total - filled)
  - total estimated effort (heuristic): parses the first number from each seat’s `estimated_effort` string and sums it when at least one effort value is parseable.
- **Critical gaps surfaced in “Resourcing” warning block:**
  - missing role names (e.g. “N seats missing role name(s)”)
  - unfilled seats (e.g. “N seat(s) unfilled”)
  - role rows with no assignee (e.g. “Writer seat has no assignee”, limited to a couple examples)
  - missing effort estimates (e.g. “No effort estimates for N seat(s)”)
- **Decision connection (light heuristic indicator):**
  - “Resourcing readiness: low / medium / high” is derived from completeness ratios for assignees, role names, and effort estimates (score-based; no deeper capacity/dependency modeling yet).
