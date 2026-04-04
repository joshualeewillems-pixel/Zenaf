# Execution steps — design note (first-class primitive)

**Status:** **Phase 1 implemented** (rows + CRUD + initiative UI + materialize/replace rules). **Phase 2+** below are **future** (promotion, assignment, routing).  
**Legacy bridge:** `../NEXT_STEPS_MEDIATION_NOTE.md` describes **`next_step_ai` as transitional** now that rows exist.  
**Alignment:** Vision Execution trunk (`vision_execution.db`, `storage.py`, `VISION_EXECUTION_API`); no new global subsystems; see `../01_TRUTH/CODEBASE_TRUTH_RULES.md`.

---

## 1. Current state (Phase 1 shipped)

**Implemented:**

- **`execution_steps`** table with `scope_type` / `scope_id` (initiative + project in schema/API; **project checklist UI deferred**).
- CRUD, reorder, materialize (`replace: false` blocked by **409** when rows exist; **`replace: true`** replaces all after explicit user action).
- Initiative **Execution** section: list, add, edit title, done toggle, reorder, delete; evaluation **Apply** materializes when empty; **Replace** path when rows already exist.
- **`next_step_ai`:** retained for import / legacy only; not the system of record for new execution.
- **Project UI** does **not** mirror this checklist; see **`./MEDIATION_EXECUTION_DIRECTION.md`** for **Suggested work (AI)** (future) and planned step actions (convert to task, move to project, promote, replace/break down — not in the live ⋯ menu until wired).

**Historical note — why the blob was insufficient (pre–Phase 1):**

| Gap | Why the blob fails |
|-----|-------------------|
| **Identity** | Steps have no stable `id`; reordering, merge, or sync across clients is fragile. |
| **Audit & learning** | Completion is opaque JSON; hard to attach `decisions`, timestamps, or “who completed.” |
| **Promotion** | No foreign keys to `tasks` / `projects`; “convert to task” cannot be a durable link. |
| **Assignment** | No `person_id` (or team) per step; routing and capacity views cannot see execution work. |
| **Scope** | Blob is initiative-centric; **projects** that need the same primitive either duplicate ad-hoc text or diverge. |
| **API** | PATCH replaces the whole string; partial updates, optimistic UI, and permissions are awkward. |
| **Outward routing** | “Hire out” / capacity request needs a **target** entity or signal keyed off a step id — not a string index. |

**Conclusion:** The blob was an acceptable **bridge**; execution steps need to become **rows** (or equivalent first-class records), not a smarter JSON document.

---

## 2. Proposed execution model

Keep these **four concepts** separate:

| Concept | Role | Mutable by user? |
|--------|------|------------------|
| **AI-suggested next steps** | Ephemeral or snapshot output from **Run evaluation** (3–5 strings + metadata). | Apply **materializes** into persisted steps; suggestion itself is not the system of record. |
| **Persisted execution step items** | Checklist rows: title, order, done state, source, optional assignee, optional links. | Yes — add, edit, reorder, check off. |
| **Promoted child task / project** | A **Task** row under a Project and/or a **Project** under an Initiative (existing VE entities). | Created from a step; step keeps **link** (`promoted_task_id` / `promoted_project_id`) for traceability. |
| **Assignee / routing actions** | Person (or future “routing target”) on the **step**; later, outward signals (e.g. seat request, external vendor flag) **reference** step id. | Assignment is Phase 3+; routing is Phase 4 without building a marketplace. |

**Flow (conceptual):**

1. Evaluation → **proposal** (`next_steps[]` in response or stored proposal snapshot — already partially in `decisions`).
2. User Apply / “Add to execution” → **insert** `execution_step` rows (`source=ai`).
3. User checks off / edits → update **rows**.
4. “Convert to task” → create **Task** (and parent Project if needed), set **link** on step.
5. Later: assign person, emit **signal** for hire-out (no marketplace engine required).

---

## 3. Minimal first-class schema proposal

**Goal:** smallest new structure that supports checklist, ordering, source, promotion, optional assignee — **without** a dependency DAG or workflow engine.

### 3.1 Table: `execution_steps` (single table MVP)

| Column | Type | Notes |
|--------|------|--------|
| `id` | TEXT PK | UUID |
| `user_id` | TEXT | Owner scope (match VE pattern) |
| `scope_type` | TEXT | `'initiative'` \| `'project'` (extensible later) |
| `scope_id` | TEXT | FK to `initiatives.id` or `projects.id` |
| `title` | TEXT | One line; optional longer `description` later |
| `sort_order` | INTEGER | Stable ordering (gap or renumber on save) |
| `is_done` | INTEGER | 0/1; set `completed_at` optional |
| `completed_at` | TEXT NULL | ISO |
| `source` | TEXT | `'ai'` \| `'user'` \| `'import'` |
| `source_evaluation_id` | TEXT NULL | Optional link to decision / evaluation snapshot id |
| `promoted_task_id` | TEXT NULL | FK → `tasks.id` |
| `promoted_project_id` | TEXT NULL | FK → `projects.id` (if “spawn project” is allowed) |
| `assignee_person_id` | TEXT NULL | FK → `persons.id` |
| `created_at` / `updated_at` | TEXT | Same as VE |

**Indexes:** `(scope_type, scope_id, sort_order)`, `(user_id, scope_id)`.

**Rules:**

- **Uniqueness:** not required on title; duplicates allowed.
- **Promotion:** at most one of task/project non-null for v1, or allow both only if product defines “task under spawned project.”
- **Legacy:** `next_step_ai` can remain for **migration**: one-time import into `execution_steps`, then deprecated for new writes (keep read-only or strip after migration).

### 3.2 API (minimal)

- `GET /initiatives/:id/execution-steps` / `GET /projects/:id/execution-steps`
- `POST` create, `PATCH` partial update (toggle done, reorder, assign), `DELETE` soft or hard (pick one; prefer hard delete for MVP).

**No** generic workflow engine; **no** dependency edges table in Phase 1.

---

## 4. UI proposal — Execution tab

**Placement:** A dedicated **Execution** sub-area on the initiative (and optionally project) detail experience — **not** buried only inside “Decision fields.” Reuse existing tab/section patterns (`DetailSection`, amber execution styling) without redesigning the whole app.

**Behaviors:**

| Action | UI |
|--------|-----|
| **List** | Ordered list; done items struck through or checked; show assignee chip if set. |
| **Check off** | Toggle `is_done` (optimistic PATCH). |
| **Add / edit** | Inline add row + edit title; optional “description” later. |
| **Convert to task** | Button on row → modal: pick parent **project** (default: first linked project or “create minimal project”) → `POST` task + PATCH step with `promoted_task_id`. |
| **Convert to project** | Optional Phase 2 — creates **Project** under initiative, links step. |
| **Assign owner** | Person select on row (Phase 3); until then, hide or read-only. |
| **AI steps** | “Import from last evaluation” or auto-on-Apply: materialize proposal into rows with `source=ai`. |
| **Later: route outward** | Button “Request capacity / hire out” → creates **Signal** (existing Layer 1) with `linked_*` + payload `execution_step_id` (Phase 4). |

**Blob field:** Stop **writing** new progression into `next_step_ai`; show migrated steps only until backfill completes.

---

## 5. Phased rollout

| Phase | Scope | Deliverable |
|-------|--------|-------------|
| **1** | Real **execution_step** records | **Done:** table + migrations + CRUD API + initiative Execution UI + materialize/replace semantics; `next_step_ai` transitional. |
| **2** | **Promotion** | **Future:** “Create task” (and optionally “Create project”) from step; persist `promoted_*_id`; project execution UI if desired. |
| **3** | **Assignment** | **Future:** `assignee_person_id` + person picker; optional filter on radar / “my execution steps.” |
| **4** | **Outward routing** | **Future:** `POST /signals` (or thin wrapper) from step: hire-out / capacity intent; **no** marketplace matching engine — signal + human triage only. |

Each phase should ship **without** requiring the next phase’s UI.

---

## 6. Constraints

- **No broad rewrite** — additive schema + focused routes; keep initiative/project PATCH for non-step fields as today.
- **No marketplace subsystem** — Phase 4 is **signals** or metadata only.
- **No giant dependency engine** — task dependencies remain separate; execution steps are a **linear/ordered checklist** until product demands DAGs.
- **VE trunk** — one SQLite family, `storage.py` migrations, FastAPI under existing VE mount; frontend uses **`VISION_EXECUTION_API`**.
- **Documentation** — `NEXT_STEPS_MEDIATION_NOTE.md` and `docs/01_TRUTH/CODEBASE_INVENTORY.md` updated for Phase 1.

---

## Relation to existing code

- **Today:** `initiative_evaluate.py` → `next_steps[]`; UI **materializes rows** on Apply (when none exist) and uses **`execution_steps`** APIs; `next_step_ai` for legacy import only.
- **Truth rules:** New endpoints are a **branch** (execution steps under VE), not a second trunk; reuse `persons`, `tasks`, `projects`, `signals` as linked entities.
