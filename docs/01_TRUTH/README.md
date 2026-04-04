# 01_TRUTH

Authoritative law, convergence truth, and program execution state for Atria.

- [Atria Convergence Program Plan](ATRIA_CONVERGENCE_PROGRAM_PLAN.md) — system-wide execution plan for philosophy integration and autonomy (human-readable narrative and mirror of program state).
- [convergence_program_state.json](convergence_program_state.json) — **machine source of truth** for active phase, active objectives (max 3), blocked items, notes, and operating loop. The philosophy enforcement runner reads **only** this file for program state—not the Markdown plan.

**Promotion rule:** A checker may be registered in [`global_philosophy_integration_matrix.json`](global_philosophy_integration_matrix.json) (matrix-gated in `run_all.py`) **only if** it verifies the law at that row’s scope—for example path-level behavior vs mere structural presence of a module must match what the row’s law claims. Exploratory or smoke checks stay out of `automation.checker_ids` until they meet that bar.
