# Mediation-driven execution — direction (structure first)

**Status:** **Design / UI scaffolding only.** No new backend schema in this pass. Execution checklist rows remain **initiative-scoped** in the UI; projects gain narrative + task-forward layout until a separate **Suggested work (AI)** concept ships.

---

## 1. Project vs initiative (do not copy checklist UI)

| Surface | Role |
|---------|------|
| **Initiative — Execution** | Canonical **checklist** (`execution_steps`): add, done, reorder, materialize from evaluation. |
| **Project — Plan & cadence** | **Coordination**: owner, **priority 1–5**, dates, capacity hint, **Brief (scope & outcomes)**. Reserved copy block for future **Suggested work (AI)** (mediation), *not* a duplicate of the initiative checklist. |

---

## 2. “Suggested work (AI)” (project) — Phase 1 shipped

- **POST** `/vision-execution/projects/{id}/suggested-work` returns coordination hints (`missing_ownership`, `uncovered_work`, `coordination_gap`, `unclear_scope`) — **not** execution steps and **no** task creation.
- UI: Project **Plan & cadence** → **Generate suggestions**; items render as a **checklist**; **checked** state is **localStorage** only (`atria-project-suggested-work-v1`). Regenerating clears checks and replaces items.
- Implementation: `local_ai/vision_execution/project_suggested_work.py`.

---

## 3. Initiative execution — future suggestion inputs (no implementation yet)

When mediation expands **initiative** suggestions, they should draw on more than one-shot **evaluation** text:

- **Dependencies** — explicit gaps, blockers, and external commitments.
- **Uncovered areas** — scope not yet represented in steps or tasks.
- **Missing assignments** — seats, owners, or tasks without a clear assignee.

Evaluation output remains one **input**; the above are **cross-checks** so suggestions stay grounded in execution reality.

---

## 4. Execution step ⋯ menu (live vs planned)

In **Initiative** execution rows, the overflow (**⋯**) menu lists **only actions that are implemented** (e.g. Remove, Duplicate). **Planned** promotion / routing flows (not in the menu until wired):

- **Convert to task…**
- **Move to project…**
- **Promote to initiative…**
- **Replace / break down…**

See `./EXECUTION_STEPS_DESIGN.md` Phase 2+ and the passive note under **Execution** in the initiative detail panel for roadmap visibility.

---

## 5. Related docs

- `./EXECUTION_STEPS_DESIGN.md` — rows, materialize, promotion model.
- `../03_IMPLEMENTATION_PLANS/PROJECT_TASK_PANEL_UI_CLEANUP_PLAN.md` — shipped project panel structure.
- `../NEXT_STEPS_MEDIATION_NOTE.md` — `next_step_ai` / legacy bridge (where applicable).
