# Active design (`02_ACTIVE_DESIGN`)

This folder defines **how the system is intended to work** — product and UX intent, target behavior, and architecture direction.

- Docs here **may describe behavior not yet implemented** or only partially shipped.
- If **code conflicts with design**, use the conflict order in **`docs/01_TRUTH/README.md`**; as-built record is **`ACTIVE_VS_PLANNED.md`**.
- **Do not assume design = reality.** Design informs roadmap; truth docs and the codebase describe what actually runs today.

See also **`docs/README.md`** for how this layer fits with `01_TRUTH` and future `03` / `04` / `05` folders.

**Open source:** clone and contribute via root [CONTRIBUTING.md](../../CONTRIBUTING.md); publish checklist [PUBLISHING.md](../../PUBLISHING.md).

## Active design docs (index)

- **`AI_ACTION_TRACE_AND_ROUTING_DESIGN.md`** — Product-wide AI action substrate (surfaces, action kinds, traces, outcomes); VE-first implementation in `frontend/src/ai-actions/` (no chain-of-thought storage).
- **`AI_EXECUTION_POLICY_ROUTING.md`** — Shared execution policy: user priorities + resolver from substrate metadata (`surface`, `action_kind`, `action_intent`) → provider/model/fallback chain; integrates with existing `get_default_provider` / `/run` without redesigning the whole provider system.
- **`CONTENT_SUBSTRATE_ROUTING_PREP.md`** — Content module: centralized `/run` path, intent map (`content_brief_*`), and optional `routing_context` seam after Workspace.
- **`MEETING_EXTRACTION_TRACE_PREP.md`** — Meeting extract → review → commit: proposed `action_kind`, `action_intent` strings, emit point, and outcome hooks (prep; not yet emitted in code).
- **`PRIVACY_MODE_AND_EXECUTION_POLICY.md`** — Privacy modes (`normal` / `protected` / `restricted` / `local_only`): allowlists, trace redaction, fallback rules; **not** auto-local for protected/restricted; merge with execution policy resolver.
- **`PRIVACY_EXTERNALIZATION_AND_REBINDING.md`** — Complementary **data-washing** layer: `externalization_strategy` / placeholder mapping, rebind after cloud `generate`; **after** gating, **before** provider call; risks and minimal v1 target.
- **`EXTERNALIZATION_V1_NEXT_STEP.md`** — **Implemented** v1: `workspace_next_step` + OpenAI + `subject_id` / `subject_ref.id`, hook in `_run_next_step`, integrity rules, tests.
- **`COMPILED_DELEGATION_V1.md`** — **Implemented (narrow):** structured cloud delegation for `workspace_next_step`, `initiative_evaluate`, and `core_profile_reconcile` + OpenAI + `routing_context`; shared strict rebind helpers; providers transport-only.
- **`TIERED_DELEGATION_AND_LEARNING.md`** — **Partially implemented (v1):** three delegation tiers (general / structured / strict secure), in-memory `LearningRecord` buffer + hooks on structured paths, `general_lane.py` seam for broad cloud calls; no model training yet.
- **`HUMAN_AI_SYMBIOSIS_DIRECTION.md`** — North-star principles for human–AI symbiosis (agency, consent, tentative interpretation, no premature persistence); current reality vs future; archived philosophical note — **direction only**, not a build spec.
- **`CORE_PROFILE_SUBSTRATE_PREP.md`** — Next substrate target: Core profile reconcile + conversation; emit points, kind/intent map, outcomes; vs TranscriptSorter.
- **`CONTEXT_ACTION_BAR_DESIGN.md`** — Focus context strip + registry-backed actions + voice-to-field; **Phase 1 bar rules + cockpit extensions implemented** (see doc header and `../01_TRUTH/ACTIVE_VS_PLANNED.md`).
- **`VISION_EXECUTION_DESIGN.md`** — VE tabs, entities, Radar; aligns with focus regions and execution CRUD.
- **`CORE_PROFILE_ARCHITECTURE.md`** — Core profile UI (chat, notes, synthesis), reconcile, **prompt anchoring** (conversation-first, FINAL OVERRIDE, deterministic note cap), **one-core / many-perspectives** ontology direction, future Perspectives modulation.
- **`SINGULAR_CORE_PROFILE_CONVERGENCE_AUDIT.md`** — File-by-file audit, conflicts, smallest patch sequence for **one canonical core** ( **`is_primary` already in DB** ); UI/copy + canonical resolver first.
- **`PROFILE_IDENTITY_ONTOLOGY.md`** — Law vs user canonical core vs legacy rows vs system perspectives; `is_canonical`, meeting guidance, influence de-peering; **user weights stay orthogonal** to default identity.
- **`CONVERSATION_TRUNK_ARCHITECTURE.md`** — Target **unified conversation pipeline** (trunk: classification + context + response contract; branches: VE / map / workspace / training enrichments only). Addresses split-brain behavior across council, map chat, VE, and training; includes draft contract + Cursor prompt for phased implementation.
- **`SOIL_LAYER_FILESYSTEM_SPEC.md`** — **Soil v1 complete (parked):** spec + kernel + CLI + soil API + dev append + checklist §12.3; **no** read hooks / auto-capture / council. Re-open only with an explicit charter; until then prefer core convergence work.
- **`OPERATOR_BURDEN.md`** — Product law for attention compression: one `now_item`, ingest prune, smallest-next-slice bias; governs supervisor feed + notification surfaces.
- **`OPERATOR_SUPERVISOR.md`** — Unified operator queue (Studio tab + cockpit strip); orchestrated pause/resume; API fields `now_item`, `burden_message`, `overflow_count`. Launcher: **`operator_console.bat`** at repo root (sync + Studio supervisor tab + cockpit).
- **`NOTIFICATIONS.md`** — Rare SMS triggers, cooldown, dry-run; deep-links to supervisor tab.
