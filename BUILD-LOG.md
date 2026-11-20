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
