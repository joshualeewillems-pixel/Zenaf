# Aria's Grounded Expression — Increment 1 build log

Branch `aria-expression`, base origin/main a038cbe.
Governing spec: `zenaf-aria-expression-gate-b-brief-2026-11-19.md`
(Increments + §5 tests), AS REVISED by the Founder Clarification
(Aria's Compass Orientation) at the brief's end, plus
`aria-grounded-expression-map-2026-11-19.md`.

## Plan

1. `local_ai/atelier/__init__.py` — thin package marker + public surface.
2. `local_ai/atelier/aria_expression.py` — pure derivation
   `derive_aria_expression(...)` → frozen `AriaExpressionSpec`.
   ACTIVITY-dimension substrate + recorded relations ONLY
   (Revision scope). No writes, no generation imports, no calls.
3. `tests/test_aria_expression.py` — brief §5 tests 1–9
   (test 10, baseline discipline, is the parent agent's job).

## Conservative readings chosen up front (open questions for Gate C)

- **OQ1 — entity → narrative thread mapping.** No store field links
  a Vision-Execution entity to a narrative thread. The derivation
  adopts the steward's own PRECISE subject convention
  (`narrative/derivation.subject_key_for_thread`): a thread belongs
  to the entity iff the DOMINANT `entity_ref` across its annotated
  evidence rows equals `"<entity_type>:<entity_id>"` (most frequent;
  ties break lexicographically first — derivation's deterministic
  rule, re-implemented locally to avoid importing the S1 module).
  Threads with unannotated evidence are invisible; any-mention
  matching was rejected as over-claiming. All precisely-matched
  threads contribute; their ids are recorded in coverage.
- **OQ2 — "presented" impression claims.** Presentation is recorded
  ONLY as Weaver-round markers in conversation message context
  (`round.py` derives round state from them per conversation; no
  claim-side presented flag, no global ledger exists). The
  derivation scans markers under the round's own history bound:
  the most recent 100 messages of each conversation from
  `list_conversations` (≤100 conversations). A claim presented
  outside that window reads as unpresented and contributes
  nothing — undercount, never fabrication.
- **OQ3 — changes.** Only CONFIRMED thread changes enter
  `interactions`. Proposed changes are unconfirmed proposals and
  contribute nothing anywhere in this increment; dismissed changes
  likewise. A confirmed `contradicted` change is kind `tension`,
  never `resolution`.
- **OQ4 — strand activity (growth).** A strand counts as active
  iff it holds ≥1 strand source OR a resolved strand thread whose
  conversation holds ≥1 message. A resolved-but-empty thread
  (panel opened, never spoken in) is NOT activity. Growth mask =
  active strands − strands carrying any explicit topic boundary
  (boundaries exclude absolutely, even the dominant strand).
- **OQ5 — complexity quantization.** Substance per family =
  strand sources held + PRESENTED strand-tagged pending claims
  citing the family. Tiers (3, bounded): 0 → 0, 1–2 → 1, ≥3 → 2.
  The quantization is artistic interpretation (per the map); the
  inputs are records. Unpresented claims contribute nothing.
- **OQ6 — capacities.** Weighed ⇒ `capacity_f = blend_f ×
  (1 + weight_f)` (blend = conductor archetype weights, verbatim),
  rounded to 6dp: monotone non-decreasing in the Work's weight per
  family, bounded in [blend_f, 2·blend_f]. Unweighed ⇒ every
  family exactly `BASE_CAPACITY = 1.0`, uniform — her blend's
  differentiation is NOT substituted for the Work's missing
  weights (brief test 1: no family differs from another).

## Progress

- Spec + map read in full; read APIs verified against the
  worktree (entity_strands.get_entity_strands; narrative store
  threads_for/evidence_for/links_for/changes_for/readings_for/
  fittings_for/correspondences_for; conversation store
  get_strand_thread/list_strand_sources/list_topic_boundaries/
  count_messages/history/list_conversations; agent store
  pending_impressions; signals.claim_strands for claim strands).
- Files written and committed per file:
  939bfe0 (package marker + this log), 7f65a09
  (aria_expression.py), 55a370e (test suite).
- `local_ai/atelier/aria_expression.py` is 529 lines vs the
  brief's ~300–400 estimate — the overage is docstring: the
  module carries the Revision's scope declaration and all six
  conservative readings (OQ1–OQ6) in full, per the brief's own
  instruction to document them prominently. Footprint unchanged:
  three new files, zero modifications.
- One additive test beyond §5's nine:
  test_recorded_relations_render pins the positive path for
  thread links + accepted correspondences (interactions) vs a
  merely-proposed correspondence (provisional), which tests 4/5
  cover only from the empty/tension side.

## Results (2026-11-19, this worktree)

- New suite: `tests/test_aria_expression.py` — **10 passed**
  (164.7s; runtime is store-construction-bound on this VM).
- Non-interference subset: `tests/test_narrative_steward_s0.py`
  + `tests/test_steward_phase3.py` — **66 passed**.
- Baseline spot-check: `tests/test_raven_regression_fixture.py
  ::test_t8_budgets_hold` — **fails identically** (frame-length
  budget assertion, main-carried; this branch touches no prompt
  or frame code).
- Combined subset run: 66 passed, 1 failed (the baseline above),
  479.5s. Full output was captured to subset-run.log during the
  run and removed after these results were recorded here.
- No ENOSPC encountered; TMPDIR was pointed at
  ~/workspace/.tmp-pytest pre-emptively for all runs.

## Deviations

- None from the brief's substance. The module-size overage and
  the one additive test are noted above. BUILD-LOG.md sits at the
  worktree root per instructions (dropped before any merge).
- Not pushed, not merged, no PR opened.
