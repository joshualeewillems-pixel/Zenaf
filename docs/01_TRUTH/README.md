# 01_TRUTH

Authoritative law, convergence truth, and program execution state for Zenaf.

## What best represents the “global” system

Use these in order when you want the **whole product + architecture story** vs **locked contracts** vs **how work is sequenced**:

| Priority | Document | Role |
|----------|----------|------|
| 1 | [SYSTEM_REFERENCE.md](SYSTEM_REFERENCE.md) | **Primary global narrative:** intent, projection, staged plans, definitions, and Part IV as-built vs direction—single merged map of “what Zenaf is.” |
| 2 | [TRUTH_CONVERGENCE.md](TRUTH_CONVERGENCE.md) | **Locked product/API truth**—what the codebase may treat as authoritative (ideas path, intake tiers, traces, perspectives ownership, field naming). |
| 3 | [ZENAF_SYSTEM_CHARTER.md](ZENAF_SYSTEM_CHARTER.md) | **Enforceable laws** (behavioral constitution); pairs with charter scripts and violation ledger. |
| 4 | [GLOBAL_PHILOSOPHY_INTEGRATION_MATRIX.md](GLOBAL_PHILOSOPHY_INTEGRATION_MATRIX.md) + [global_philosophy_integration_matrix.json](global_philosophy_integration_matrix.json) | **Convergence map:** each declared philosophy, scope, class A/B/C, enforcement—human table + machine registry for `run_all.py`. |
| 5 | [ACTIVE_VS_PLANNED.md](ACTIVE_VS_PLANNED.md) | **Operational as-built:** surfaces, AI flows, stubs, and near-term targets (complements Part IV of `SYSTEM_REFERENCE.md`). |
| 6 | [CODEBASE_TRUTH_RULES.md](CODEBASE_TRUTH_RULES.md) | **Implementation law** for routing, persistence, judgment substrate, coordination, council/Zenaf contracts—how code should obey the charter day to day. |
| 7 | [ZENAF_CONVERGENCE_PROGRAM_PLAN.md](ZENAF_CONVERGENCE_PROGRAM_PLAN.md) + [convergence_program_state.json](convergence_program_state.json) | **Program trajectory** for philosophy enforcement and bounded autonomy phases—JSON is the runner’s program state; Markdown is the human mirror and backlog narrative. |
| 8 | [wave_autonomy_protocol.md](wave_autonomy_protocol.md) | **Online autonomy layer** (wave-gated CI, exit gate, optional SMS/promotion)—repo operations, not runtime cockpit behavior. |

Supporting: [CODEBASE_INVENTORY.md](CODEBASE_INVENTORY.md) (file/module map), [BOOT_FLOW.md](BOOT_FLOW.md) (startup and persistence), [AUTONOMOUS_REPAIR_POLICY.md](AUTONOMOUS_REPAIR_POLICY.md) (what automation may change), [FRUIT_MINT_POLICY.md](FRUIT_MINT_POLICY.md) (integration-artifact mint law — locked via `TRUTH_CONVERGENCE.md`; implementation may lag), [TOKENOMICS_DIRECTION_NOTE.md](TOKENOMICS_DIRECTION_NOTE.md) (tokenomics **deferred** — activation conditions; not active work), [../02_ACTIVE_DESIGN/ARC_DETECTION_FIXTURE_SPEC.md](../02_ACTIVE_DESIGN/ARC_DETECTION_FIXTURE_SPEC.md) (arc detector **lab** — synthetic lane, glossary, fixtures; not real-user truth).

---

- [Zenaf Convergence Program Plan](ZENAF_CONVERGENCE_PROGRAM_PLAN.md) — system-wide execution plan for philosophy integration and autonomy (human-readable narrative and mirror of program state).
- [convergence_program_state.json](convergence_program_state.json) — **machine source of truth** for active phase, active objectives (max 3), blocked items, notes, and operating loop. The philosophy enforcement runner reads **only** this file for program state—not the Markdown plan.
- [wave_autonomy_protocol.md](wave_autonomy_protocol.md) — online **wave-gated** autonomy (GitHub Actions concurrency, `wave_exit_gate.py`, rich `wave_exit_report.json`, `wave_sms_body.py` for actionable SMS, optional success SMS via dispatch `notify_on_success`, optional `promote_next_wave` + `wave_promote.py`). SMS secrets: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, `NOTIFY_TO_NUMBER` (optional; notify skips if unset).

**Promotion rule:** A checker may be registered in [`global_philosophy_integration_matrix.json`](global_philosophy_integration_matrix.json) (matrix-gated in `run_all.py`) **only if** it verifies the law at that row’s scope—for example path-level behavior vs mere structural presence of a module must match what the row’s law claims. Exploratory or smoke checks stay out of `automation.checker_ids` until they meet that bar.
