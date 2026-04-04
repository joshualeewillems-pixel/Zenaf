# Execution steps — Phase 1 implementation plan

**Source:** `docs/02_ACTIVE_DESIGN/EXECUTION_STEPS_DESIGN.md` §3, §4, §5 (Phase 1 only).  
**Out of scope for this phase:** promotion to task/project, assignee, outward routing, dependency engine, marketplace, broad VE refactor.

---

## 1. Files to create / modify

### Create

| File | Purpose |
|------|---------|
| `docs/03_IMPLEMENTATION_PLANS/EXECUTION_STEPS_PHASE1_PLAN.md` | This plan (implementation checklist). |
| *(optional)* `frontend/src/vision-execution/ExecutionStepsPanel.tsx` | Checklist UI + local reorder/drag or button-driven reorder; keep thin if preferred inline in `VisionExecutionView.tsx`. |

### Modify

| File | Purpose |
|------|---------|
| `local_ai/vision_execution/schema.sql` | Add `execution_steps` table + indexes. |
| `local_ai/vision_execution/storage.py` | Migration `_ensure_execution_steps_table`, CRUD + reorder + materialize helpers; `init_db` hook. |
| `local_ai/vision_execution/models.py` | Pydantic: `ExecutionStepCreate`, `ExecutionStepUpdate`, `ExecutionStepOut` (or inline dicts if team prefers minimal typing). |
| `local_ai/vision_execution/service.py` | Thin wrappers calling storage (match existing pattern). |
| `api/routes/vision_execution.py` | Nested routes under initiatives/projects. |
| `frontend/src/vision-execution/types.ts` | `ExecutionStep` interface. |
| `frontend/src/vision-execution/VisionExecutionView.tsx` | Execution tab/section, wire API, Apply → materialize, dual-read fallback. |
| `frontend/src/vision-execution/nextStepsPayload.ts` | *(if kept)* reuse **only** for parsing legacy `next_step_ai` during migration import — or move import helper into `ExecutionStepsPanel` / a small `executionStepsMigrate.ts`. |
| `docs/02_ACTIVE_DESIGN/EXECUTION_STEPS_DESIGN.md` | *(after ship)* add “Phase 1 implemented” one-liner + link to inventory. |
| `docs/NEXT_STEPS_MEDIATION_NOTE.md` | Note Phase 1 row storage + when blob is still read. |
| `docs/01_TRUTH/CODEBASE_INVENTORY.md` | Bullet under VE: `execution_steps` + routes. |

**Do not modify in Phase 1:** `radar.py` (optional later), `initiative_evaluate.py` contract (still returns `next_steps[]`), `derived.py` unless a derived flag explicitly needed.

---

## 2. Proposed schema SQL

**Phase 1 DDL only** — omit `promoted_task_id`, `promoted_project_id`, and `assignee_person_id` until Phase 2/3 (fewer dead columns; add via `ALTER TABLE` then). Omit `source_evaluation_id` unless you already persist a decision id on Apply (optional null for future).

```sql
-- Execution checklist rows (initiative or project scope). Phase 1: no promotion/assignee columns.
CREATE TABLE IF NOT EXISTS execution_steps (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  scope_type TEXT NOT NULL CHECK (scope_type IN ('initiative', 'project')),
  scope_id TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  sort_order INTEGER NOT NULL DEFAULT 0,
  is_done INTEGER NOT NULL DEFAULT 0 CHECK (is_done IN (0, 1)),
  completed_at TEXT,
  source TEXT NOT NULL DEFAULT 'user' CHECK (source IN ('ai', 'user', 'import')),
  source_evaluation_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_execution_steps_scope ON execution_steps (scope_type, scope_id, sort_order);
CREATE INDEX IF NOT EXISTS idx_execution_steps_user_scope ON execution_steps (user_id, scope_id);
```

**Integrity (application-level Phase 1):** Before insert/list, verify `scope_id` resolves to an initiative or project owned by `user_id` (same checks as `get_initiative` / `get_project`). Optional: `ON DELETE CASCADE` from initiatives/projects — SQLite FKs require `PRAGMA foreign_keys=ON` and `REFERENCES initiatives(id)` if you want cascade delete when initiative removed; mirror `initiative_seats` pattern (likely CASCADE on initiative delete).

**Recommended:** add `FOREIGN KEY (scope_id)` only if `scope_type` is enforced in app (SQLite cannot do conditional FK per row cleanly); **Phase 1:** app validation only, same as many existing VE tables.

---

## 3. Storage methods (`storage.py`)

Implement in `storage.py` (names indicative):

| Method | Behavior |
|--------|----------|
| `_migrate_execution_steps(conn)` | `CREATE TABLE IF NOT EXISTS` + indexes (idempotent). Call from `init_db` after other migrations. |
| `list_execution_steps(scope_type, scope_id, user_id)` | `SELECT … WHERE scope_type=? AND scope_id=? AND user_id=? ORDER BY sort_order, id`. |
| `get_execution_step(step_id, user_id)` | Single row or None. |
| `create_execution_step(user_id, scope_type, scope_id, title, sort_order, source, source_evaluation_id?)` | Insert; return dict. |
| `update_execution_step(step_id, user_id, patch: dict)` | Partial update: `title`, `sort_order`, `is_done`, `completed_at` (set ISO when done=1, clear when 0). |
| `delete_execution_step(step_id, user_id)` | Hard delete (MVP). |
| `replace_execution_steps_from_titles(user_id, scope_type, scope_id, titles: list[str], source, clear_existing: bool)` | **Materialize AI:** if `clear_existing`, delete all rows for scope; then insert each title with `sort_order = i`, `source='ai'`. Transactional. |
| `reorder_execution_steps(user_id, scope_type, scope_id, ordered_ids: list[str])` | Validate all ids belong to scope/user; set `sort_order` by index; `updated_at`. |

**Helpers (same module or small util):**

| Helper | Behavior |
|--------|----------|
| `_assert_scope_owned(conn, user_id, scope_type, scope_id)` | Raise `ValueError` if initiative/project not found for user. |
| `import_execution_steps_from_next_step_ai_blob(user_id, scope_type, scope_id, next_step_ai_text)` | Parse JSON / legacy string via existing `nextStepsPayload` logic (ported to Python or duplicated once): if steps non-empty and **no rows yet** for scope, insert rows `source='import'`, then optionally clear blob (product choice — see §6). |

**Row serializer:** `row_to_execution_step(row: tuple) -> dict` in `models.py` (mirror `row_to_initiative`).

---

## 4. API routes (`api/routes/vision_execution.py`)

All `Depends(get_current_user)`; 404 if scope not owned.

| Method | Path | Body | Response |
|--------|------|------|----------|
| GET | `/initiatives/{id}/execution-steps` | — | `ExecutionStepOut[]` |
| GET | `/projects/{id}/execution-steps` | — | `ExecutionStepOut[]` |
| POST | `/initiatives/{id}/execution-steps` | `{ title, sort_order? }` | created row |
| POST | `/projects/{id}/execution-steps` | same | created row |
| PATCH | `/execution-steps/{step_id}` | `{ title?, sort_order?, is_done? }` | updated row |
| DELETE | `/execution-steps/{step_id}` | — | `{ ok: true }` |
| POST | `/initiatives/{id}/execution-steps/materialize` | `{ titles: string[], replace?: bool }` | `ExecutionStepOut[]` |
| POST | `/projects/{id}/execution-steps/materialize` | same | `ExecutionStepOut[] |

**Materialize:** `titles` length 1–20 (cap); `replace=true` deletes existing steps for that scope then inserts; `replace=false` appends with `sort_order` after max existing. Used by **Apply evaluation** and optional **“Import from evaluation”** button.

**Reorder:** Either `PATCH` per row with new `sort_order`, or dedicated `PUT …/execution-steps/reorder` with `{ ordered_ids: string[] }` — second is fewer round-trips; **recommend `POST …/execution-steps/reorder`** scoped under initiative/project:

- `POST /initiatives/{id}/execution-steps/reorder` body `{ ordered_ids: string[] }`
- `POST /projects/{id}/execution-steps/reorder` body `{ ordered_ids: string[] }`

**Service layer:** `service.list_execution_steps_for_initiative(initiative_id, user_id)` etc., delegating to storage.

---

## 5. Frontend components / state

### Types (`types.ts`)

```ts
export interface ExecutionStep {
  id: string
  scope_type: 'initiative' | 'project'
  scope_id: string
  title: string
  sort_order: number
  is_done: boolean
  completed_at: string | null
  source: 'ai' | 'user' | 'import'
  source_evaluation_id: string | null
  created_at: string
  updated_at: string
}
```

### State (initiative detail panel)

- `executionSteps: ExecutionStep[]` — load on panel open / `initiativeId` change via `GET …/execution-steps`.
- Mutations: optimistic `PATCH` for checkbox; debounced or explicit save for title edit; reorder calls `POST …/reorder`.

### UI — “Execution” section

- New `DetailSection` **Execution** (or sub-tab if tabs already exist): title **Execution**.
- Checklist: each row — checkbox (`is_done`), inline title edit (blur or small Save), drag-handle optional **Phase 1 minimal:** ↑/↓ buttons calling reorder API.
- **Add step:** input + button → `POST` with `sort_order = max+1`.
- **Materialize from AI:** On **Apply decision** after evaluation, call `materialize` with `evaluateProposal.next_steps` and `replace: true` (product choice: replace vs merge — **default replace** when applying fresh evaluation to avoid duplicates).
- **Remove** row: `DELETE` with confirm optional.

### Project detail panel

- Mirror the same section + `GET/POST /projects/{id}/execution-steps` if projects get a detail panel in VE (if not, **initiative-only UI first** is acceptable Phase 1 slice — document as such).

### Legacy `next_step_ai` UI

- **Dual-read:** If `GET execution-steps` returns **empty** and `next_step_ai` has parseable steps, show **banner** “Import to execution checklist” → one-shot `materialize` or `import_*` helper; hide blob checklist UI after import (see §6).

---

## 6. Migration / transition from `next_step_ai`

| Step | Action |
|------|--------|
| **Read path** | Primary: `execution_steps` rows. **Dual-read:** if no rows and `next_step_ai` non-empty, UI may show legacy `nextStepsPayload` parser **or** only a CTA to import. |
| **Write path (Phase 1)** | On **Apply evaluation:** call `materialize` (rows) and **stop writing** progression JSON to `next_step_ai` **or** write empty string / keep text summary only — **recommend:** clear `next_step_ai` to `''` after successful materialize to avoid two sources of truth. |
| **One-time import** | Optional `POST …/execution-steps/import-legacy` or button that reads current `next_step_ai`, creates rows `source='import'`, clears blob. |
| **Radar / derived** | Phase 1 can leave `radar.py` using `_initiative_has_next_steps_content` until Phase 1.1 adds `OR EXISTS (SELECT 1 FROM execution_steps …)` — **not blocking** for checklist MVP. |
| **Seeds** | `seed_vision_execution.py`: after creating initiatives, optionally insert execution steps from old `next_step_ai` strings or leave empty. |

---

## 7. Top 3 implementation risks

1. **Two sources of truth** — If both `next_step_ai` and rows stay populated with different content, users and radar disagree. **Mitigation:** on Apply + import, clear or freeze blob; document single writer (rows only) in `NEXT_STEPS_MEDIATION_NOTE.md`.

2. **Reorder race / partial failures** — Multiple `PATCH sort_order` calls can clash. **Mitigation:** single `reorder` endpoint in one transaction; UI sends full `ordered_ids` after local reorder.

3. **Scope ownership bugs** — Steps inserted for wrong `user_id` or wrong `scope_id` leak across tenants. **Mitigation:** every storage method filters `user_id`; materialize/reorder validates all ids belong to scope; add one integration test or manual script per route.

---

## Implementation order (suggested)

1. Schema + migration + `row_to_execution_step` + storage CRUD + reorder + materialize.  
2. Service + API routes + manual curl/smoke test.  
3. Frontend types + fetch on initiative load + Execution section UI.  
4. Wire Apply → materialize + stop writing blob.  
5. Dual-read banner + import button + docs/inventory updates.
