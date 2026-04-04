# Global Philosophy Integration Matrix

<!--
Status: Canonical (convergence map)
Last updated: 2026-04-03
Companion: partial integration narrative in chat / seed from ATRIA_SYSTEM_CHARTER.md, ACTIVE_VS_PLANNED.md, CODEBASE_TRUTH_RULES.md, MIRROR_GRAPH_INTERPRETATION_SYSTEM_NOTE.md
-->

**Purpose:** For each **philosophy** (architectural law we already declared), record **where it is real**, **where it is partial**, **what is exempt or parked**, **how to classify urgency**, and **what enforcement prevents drift**—without redesigning features.

**Promotion rule:** A checker may be matrix-gated in `global_philosophy_integration_matrix.json` / `run_all.py` **only if** it verifies the law at the row’s scope (e.g. path-level enforcement vs structural “file still exists”). Do not wire smoke or exploratory checks into `automation.checker_ids` until they meet that bar—keep them manual or documented outside the registry.

**Legend — classification (col “Class”):**

| Code | Meaning |
|------|---------|
| **A** | **Must be globally integrated now** — gaps create silent inconsistency or charter violation at scale |
| **B** | **Can remain partial with explicit boundary** — document + enforce the boundary (registry, matrix row, exempt id) |
| **C** | **Intentionally parked** — re-charter before expanding scope |

---

## Matrix

| # | Philosophy | Law (one sentence) | Intended global scope | Currently implemented (surfaces / modules) | Partial / incomplete | Exempt or parked | Class | Enforcement mechanism (anti-drift) |
|---|------------|-------------------|------------------------|--------------------------------------------|----------------------|------------------|-------|--------------------------------------|
| 1 | **Traceability** | Every AI-touching path emits a **client trace**, **server trace**, or a **named exempt** in `aiTraceExemptRegistry.ts`. | All cockpit LLM/AI outcomes: VE API routes, `/run` modes, content, meeting extract, core profile LLM, transcribe, operator tools if ever unified. | VE Rewrite + suggested work + idea/initiative evaluate (success trace); Workspace `/run` modes via `workspaceRunWithTrace`; server: `trace_core_profile_llm_route`, `trace_meeting_debug_extract_route` on instrumented routes; exempt registry for transcribe/settings/studio/heuristic. | Content `/run` + distill + sort; meeting extract + review; core profile chat/reconcile **client** ring; evaluate **apply/dismiss** not on trace; many VE LLM routes lack **in-body** server trace marker (per `scripts/charter_enforcement_check.py`). | Studio (`studio_admin_surface`); transcribe (`voice_transcribe_only`); settings LLM test; heuristic no-provider. | **A** | **Keep** `AI_ACTION_SUBSTRATE_COVERAGE_MATRIX.md` + `charter_enforcement_check.py` + **`scripts/philosophy_enforcement/checkers/check_trace_coverage.py`** (client trace vs `ai_trace_exemptions.json`); **require** new routes to add row or exempt comment `# charter-trace-exempt:`; optional pytest: matrix rows match registry + script output. |
| 2 | **Mirror graph interpretation** | Evidence is **classified against a graph** and yields **inspectable `action` + `payload`** before durable writes—not only free text. | Intake → VE, meetings → VE, profile reconcile, file steward, presort, harvest when graph-addressable. | Meeting post-extract: `graph_interpretation.py` + FE staging types. | Intake queue; core profile reconcile (propose/apply without shared envelope); file steward/folder; presort surface vocabulary; harvest. | None global; harvest “shallow until scoped” per system note. | **B** | **Design doc as contract:** `MIRROR_GRAPH_INTERPRETATION_SYSTEM_NOTE.md` + **checklist** on PRs touching extract/commit flows; **shared TS/Python types** package (single import path) when touching a second surface—no new ad hoc “proposal” shapes without doc update. |
| 3 | **Data access policy** | Reads of **sensitive depth** (Tier B/C, external egress) go through **`data_access`** with explicit tier/justification. | Any module that could fetch raw body, external destinations, or future Tier B/C UI. | Intake `get_item_with_content()`; product UI stays Tier A. | Council, File Steward, VE LLM paths **do not** call policy; `destination=EXTERNAL` unused; Tier C storage placeholder. | Tier B/C **not** in product contract (`TRUTH_CONVERGENCE.md`). | **B** | **Lint/grep gate:** new `get_item_with_content` or raw-body fetch **must** import from `policy.data_access`; **document** “policy not applicable” per route in `CODEBASE_INVENTORY.md` with reason; **forbid** new Tier B/C API without TRUTH_CONVERGENCE update. Exploratory scaffold only: `scripts/philosophy_enforcement/checkers/check_data_access_surface.py` (**not** matrix-gated). |
| 4 | **Judgment substrate** | **SubjectRef + JudgmentTrunk** (and approved choke points like `append_execution_flow_reading`) are the **canonical** shape for persisted interpretation rows—not parallel ad hoc tables. | Council, node memory, coordination readings, any new “verdict” persistence. | `append_node_judgment`, council stream runs, coordination `execution_flow_reading` choke point, integrity envelopes. | Intake judgments in **mirror** tables; other verdict kinds **not** funneled through coordination choke (`CODEBASE_TRUTH_RULES` §5c). | Tombstoned: `node_adapters` / `subject_adapters`. | **B** | **Rule already in** `CODEBASE_TRUTH_RULES.md` §5b–5c; **enforcement:** PR checklist “new judgment row → substrate or documented exception”; **no revival** of tombstoned modules (grep CI). |
| 5 | **Coordination spine** | **ActivityEvent** (`activity.log`) + optional **`execution_flow_reading`** judgments link **human/server execution facts** to **bounded interpretation** for guidance—not a second currency DB. | All meaningful execution checkpoints that should influence “how it’s going” without new stores. | Client-checkpoint → activity + judgment (narrow positive rule for applied suggestions); council neutral `execution_flow_reading`; GET readings; developmental consumption (hypothesis-first). | Other activity types without matching judgment; negative human readings not yet emitted; guidance caps/scoped omission. | None exempt; philosophy is **narrow by design**. | **B** | **Extend** `tests/test_coordination_signals.py` when adding checkpoint types; **document** in `CODEBASE_TRUTH_RULES.md` §5c only; **forbid** new `append_node_judgment` for `execution_flow_reading` outside `coordination_signals.py`. |
| 6 | **Canonical core identity** | **One canonical core profile** per user/workspace **as product truth**, with **perspectives as lenses**—not many competing “cores.” | All core profile list/detail/training/reconcile flows; server perspective definitions. | `is_primary`, `PATCH set-primary`, list ordering; server `user_council_workspace` for seat defaults. | UI still multi-profile “Add”; localStorage perspective defs vs server; ad hoc `profiles[0]` picks. | None parked—directional convergence. | **B** | **Single resolver helper** (FE + BE) for “active core for user” per `SINGULAR_CORE_PROFILE_CONVERGENCE_AUDIT.md`; **TRUTH_CONVERGENCE** + **checklist** on new core-profile UI; **`canonical_identity_leaks` + `check_canonical_identity`** in `scripts/philosophy_enforcement/` (`profiles[0]` FE, alternate list names, `api/` + **`local_ai/`** `profiles[0]`, risky `.find`). |
| 7 | **Execution seam coherence** | **Routed** VE/`/run` execution uses **seam + principal** with declared **ollama/openai** primaries unless extended in **truth rules + main.py** together. | All user-attributed LLM calls that should honor settings and blocking. | `_run_ve_llm_with_routing`, `apply_seam_routing`, council seat providers, resolver paths on idea/initiative evaluate + distill. | Non-routed `/run` default provider; adapter registry **not** on hot paths; extra primaries on seam need explicit wiring. | Documented in `CODEBASE_TRUTH_RULES.md` §1. | **B** | **No new `get_default_provider` call sites** without CODEBASE_TRUTH_RULES update; **`execution_seam_bypasses`** in `scripts/philosophy_enforcement/` (get_default_provider scan + structural checks); **doc table** in inventory listing resolver vs default vs seam per feature; **pytest** smoke on one routed + one non-routed path when touching `api/main.py` routing. Exploratory scaffold only: `check_execution_seam_surface.py` (**not** matrix-gated). |
| 8 | **Honest commit / explicit payload** | **Confirmed writes** use **explicit structured payload** (e.g. `[DRAFT_VALUE:]`, patches)—not silent inference from chat text. | Council integration commit, VE field apply, any “AI said save” path. | `integration_commit.py` strip/tag contract; API comments on `pending["value"]`. | `infer_draft_value_from_context` narrow fallback in `atria_tools.py`. | None. | **B** | **Charter script** + **`check_deterministic_commit`** (`scripts/philosophy_enforcement/`): contract fragments in `integration_commit.py`, audited `infer_draft` call sites; **log** when fallback path runs; **checklist** on new commit surfaces. |
| 9 | **HTTP client frontier consistency** | **VE subtree** uses **proxied relative** `VISION_EXECUTION_API`; **organizer** uses **`API_BASE`**—no third ad-hoc origin for same product. | All frontend fetchers to backend. | Established split per `CODEBASE_TRUTH_RULES.md` §4. | New files sometimes risk mixing patterns. | None. | **B** | **ESLint rule or codemod grep** in CI: `fetch('http` outside allowed files; **CONTRIBUTING** one-liner; **code review** checklist. |
| 10 | **Intake operational completeness** | If schema claims **sync/mailbox observability**, **writers** must exist on the real poll path—or docs must say “not wired.” | Poll, queue, mirror_sync, mailbox_action. | Queue + judgment + Tier A reads. | **No** `set_sync_state` after poll; **no** mailbox mutation; no background poll. | Product truth: “not a story until wired” (`TRUTH_CONVERGENCE`). | **B** | **BOOT_FLOW.md** + **ACTIVE_VS_PLANNED** explicit list; **optional integration test** when poll is touched: assert sync updated or assert documented skip; **no new mirror tables** without writer plan. |
| 11 | **Product honesty (no phantom capability)** | **UI labels and nav** must match **runtime behavior** (Tier A only, no fake AI, no hidden tiers). | All user-visible cockpit strings and entry routes. | Tier A contract documented; Idea Lab stub documented in matrix; Soil dev-gated. | “Clarify with AI” stub button; any copy implying Tier B/C. | Tier B/C code exists but **out of contract**; Soil v1 **parked** feature-wide. | **A** (stub) / **B** (tiers) | **charter_enforcement_check.py** Clarify stub; **`product_honesty_phantom` + `check_product_honesty`** in `scripts/philosophy_enforcement/`; **TRUTH_CONVERGENCE** gate on Tier UI; rename stub or disclose **before** adding similar buttons. |
| 12 | **Developmental guidance boundary** | Guidance is **hypothesis-level, optional context** for council—**not** silent routing, **not** durable profile truth. | Council preflight + cockpit panel only until re-chartered. | `buildDevelopmentalGuidanceContext`, `developmental_guidance.py`, enriched context block; scoped digression drops block. | Next-step/harvest/scripts not wired; packet size limits. | Scoped council **omits** developmental by design. | **B** | **Charter §** in `ATRIA_SYSTEM_CHARTER.md`; **forbid** new consumers without doc row in `SYSTEM_REFERENCE.md`; **test** scoped path does not inject guidance. |
| 13 | **Shared artifacts / Radar / node substrate (roadmap)** | **Planned** durable artifacts and radar aggregation—not current product law. | Future council runs, next-step, signals UI. | Partial scaffolding per `SYSTEM_REFERENCE.md` phases. | Most phases **planned** only. | Explicitly **not** claiming completion. | **C** | **Do not implement** without updating `SYSTEM_REFERENCE.md` phase + TRUTH_CONVERGENCE; **milestone checklist** per phase; avoid duplicate “memory” stores. |
| 14 | **Soil filesystem substrate** | **v1 frozen**: append/promote only; **no** read hooks, council consumption, or vectors until re-charter. | Dev tooling + explicit promote only. | `POST soil/append`, promote, dev UI behind `import.meta.env.DEV`. | v2+ undefined. | **Parked** for product (`ACTIVE_VS_PLANNED`). | **C** | **TRUTH_CONVERGENCE** or charter pointer; **CI** ensure soil routes not in user-facing nav prod build; **doc** SOIL_LAYER spec as boundary. |
| 15 | **Operator / Studio surfaces** | **Cockpit trace law** does not apply until Studio is aligned with `AiActionTrace` contract. | Studio, bakeoffs, prompt tooling. | Exempt id `studio_admin_surface`. | N/A | **Explicitly exempt** from full trace parity. | **B** | **Keep** exempt in registry; **review** on any Studio merge into main cockpit; **one sentence** in charter or TRUTH_CONVERGENCE. |

---

## Ranked implementation order (anti-drift, not feature redesign)

Order is **by leverage**: stop silent inconsistency first, then tighten boundaries, then protect parked areas.

| Rank | Philosophy # | Why this order |
|------|----------------|----------------|
| 1 | **1 Traceability** | Largest gap vs declared law (`TRUTH_CONVERGENCE` 6a); prevents re-litigating “did we log AI?” every release. |
| 2 | **11 Product honesty** | Stub labels and tier claims erode trust; cheap fixes (rename/disclose) + matrix row. |
| 3 | **8 Honest commit** | Small surface area; inference path must stay **visible and rare**—charter script + logging. |
| 4 | **4 Judgment substrate** | Prevents second trunk of ad hoc verdict tables; mostly **process + grep** on `append_node_judgment`. |
| 5 | **5 Coordination spine** | Keep **one choke point** for `execution_flow_reading`; extend tests when adding checkpoints. |
| 6 | **3 Data access policy** | Important before any Tier B/C or egress expansion; until then **boundary docs + grep** suffice. |
| 7 | **6 Canonical core** | UX/resolver convergence; reduces wrong-profile bugs without big bang migration. |
| 7 | **7 Execution seam** | Extend only when adding providers/modes; tie to `CODEBASE_TRUTH_RULES` edits. |
| 9 | **2 Mirror interpretation** | Deep alignment work per surface; **prevent new envelope types** until doc updated. |
| 10 | **9 HTTP client** | Low frequency of violation; lint/checklist. |
| 11 | **10 Intake sync/mailbox** | Operational honesty when intake is touched. |
| 12 | **12 Developmental guidance** | Prevent silent new consumers; already bounded in charter. |
| 13 | **15 Studio exempt** | Maintain explicit exempt; revisit only if Studio merges with cockpit. |
| 14 | **13 Roadmap substrates** | **C** — no enforcement beyond “phase gate” docs. |
| 15 | **14 Soil** | **C** — frozen contract; re-charter to expand. |

---

## Related documents

| Document | Role |
|----------|------|
| `ATRIA_SYSTEM_CHARTER.md` | Enforceable laws (overlaps rows 1, 2, 3, 5, 8, 11, 12); **§9.1** compositional discipline (trunk/branch/reuse) |
| `ATRIA_CHARTER_VIOLATION_LEDGER.md` | Known violations + `charter_enforcement_check.py` |
| `ACTIVE_VS_PLANNED.md` | As-built vs planned surfaces |
| `CODEBASE_TRUTH_RULES.md` | LLM routing, persistence, judgment, coordination; **§6 Branch law** (trunk vs branch, no accidental second trunk); **§2** and peers for **reuse of shared primitives**—operational home for compositional discipline (charter §9.1) |
| `docs/02_ACTIVE_DESIGN/CONVERSATION_TRUNK_ARCHITECTURE.md` | Active design: unified conversation **trunk** + feature **branches** (enrichment only)—narrative complement to truth rules |
| `AI_ACTION_SUBSTRATE_COVERAGE_MATRIX.md` | Trace row per flow |
| `MIRROR_GRAPH_INTERPRETATION_SYSTEM_NOTE.md` | Interpretation envelope North Star |
| `TRUTH_CONVERGENCE.md` | Locked product/API truth |
| `global_philosophy_integration_matrix.json` | Machine-readable registry for automation (`scripts/philosophy_enforcement/run_all.py`) |
| `AUTONOMOUS_REPAIR_POLICY.md` | Bounds for local auto-repair + Git checkpoints (`scripts/philosophy_enforcement/auto_repair.py`, `repair_registry.json`) |

---

## Maintenance rule

When **philosophy or scope** changes: update **this matrix** in the same PR as **TRUTH_CONVERGENCE** or **charter** edits—so the matrix cannot silently rot.
