# Next steps (mediation) — storage and future integration

**Canonical execution checklist:** First-class **`execution_steps`** rows on the Vision Execution trunk (initiative and project scope). Spec and phases: **`docs/02_ACTIVE_DESIGN/EXECUTION_STEPS_DESIGN.md`**. This file summarizes how **legacy `next_step_ai`** fits in **after Phase 1**.

## Current truth (post–Phase 1)

- **System of record:** `execution_steps` table — per-step `id`, `title`, `sort_order`, `is_done`, `source`, scoped by `user_id` + `(scope_type, scope_id)`.
- **API:** `GET/POST …/execution-steps`, `POST …/materialize` (requires `replace: true` if rows already exist — otherwise **409**), `POST …/reorder`, `PATCH/DELETE /execution-steps/{id}`. See `api/routes/vision_execution.py`.
- **UI (initiative):** **Execution** section lists rows; add, edit, check, reorder, remove; **Apply decision** materializes evaluation `next_steps` only when **no** rows exist; explicit **Replace all execution steps** when rows exist + confirmation.
- **`initiatives.next_step_ai` (TEXT):** **Transitional only.** Still present for backward compatibility and **one-way import** into rows (“Import legacy next steps”). When checklist rows exist, the initiative UI **does not** rely on `next_step_ai` for progression; saves may **clear** it once rows are canonical. **Do not** treat the JSON blob as durable execution state for new work.

## Evaluation contract (unchanged shape)

- **Run evaluation** returns `next_steps` as **3–5** short strings.
- **Apply** copies proposal into **decision fields** and, when appropriate, **materializes** those strings into **`execution_steps`** (not into `next_step_ai` as the primary store).

## Legacy / bridge behaviors

- **Idea → initiative promote** paths may still serialize a payload into `next_step_ai` for migration UX; users should **import to rows** or rely on **Apply** on the initiative when no rows exist.
- **No task subsystem** for steps yet: checklist is initiative-/project-local; no `tasks` link from steps in Phase 1.

## Future integration (not implemented)

1. **Task system:** Optional `Task` rows from a step, with explicit opt-in (`docs/02_ACTIVE_DESIGN/EXECUTION_STEPS_DESIGN.md` Phase 2).
2. **Recursive planning:** Re-run evaluation for follow-on steps; merge/version with explicit replace rules (same **no silent replace** posture as materialize).
3. **Decision trees:** Tie step outcomes to `decisions` / `signals`.
4. **Dependencies:** Only after tasks exist — avoid encoding DAGs in mediation strings or blob fields.

Keep progression **linear and local** to the checklist until promotion and dependency work land.
