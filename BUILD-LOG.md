# Steward Recognition — build log

Branch `steward-recognition`, base origin/main a038cbe.
Governing spec: `~/workspace/goals/seven-seat-worlds/files/zenaf-steward-recognition-gate-b-brief-2026-11-19.md`
(+ scoping proposal Rev 1 §§2–4, 10–11 and Rev 2 §§15–21).

## Plan

1. `local_ai/narrative/recognition.py` (new) — assess_thread / assess_pairs / propose_all / run_recognition_pass.
2. `tests/test_narrative_recognition.py` (new) — brief §4 suite (R1–R7 + carried validation/shape/bridge tests).
3. `local_ai/narrative/sweep.py` — one gated call site in run_sweep_for_user (after friction, before prune).
4. `local_ai/narrative/context.py` — standing-frame fact lines (accepted fitting name; accepted correspondence count).
5. `api/routes/steward_review_routes.py` — "Explore with Aria" affordance (POST /{kind}/{row_id}/explore).

## Progress

- Spec read in full (brief + proposal §§2–4, 10–11, Rev 2 §§15–22).
- Code anchors verified against the worktree: discovery.py shape;
  store.propose_reading (evidence ids as strings resolve via
  _attach_evidence), set_fitting Phase 4 T2 durable rejection,
  is_dismissed/record_dismissal signature regime, snapshot_for_read,
  get_erasure_tombstone; derivation generate_fn seam (prompt,
  provider_id=, user_id=, operation=, timeout=) returning raw text
  or NONE; relevance.py token/stem matching idiom (local copies);
  lenses.py canon fit_signals verbatim; correspondence
  .propose_correspondence abstention contract; sweep
  run_sweep_for_user structure (friction → prune, per-user lock,
  _gate_open); context.py _render_block facts; review routes +
  phase1/phase2/phase3 test idioms.

## Commits

(appended as work lands)

## Test runs

(appended as work lands)
- recognition.py written: 1,279 lines (brief estimated 450–600;
  the overage is docstring density in the house style — footprint
  is exactly the one specified module). Syntax + import check OK;
  switches verified (ZENAF_RECOGNITION on ⇒ enabled; corr-gen
  stays off independently).
- sweep.py: recognition call site added inside run_sweep_for_user
  (after friction, before prune; ZENAF_RECOGNITION + _gate_open;
  per-user lock already held; failure-isolated). SweepResult gains
  a `recognition` dict field. Import check OK.
- context.py: standing-frame fact lines — accepted fitting renders
  as `fitting: <lens name> (accepted)`, accepted correspondences
  as a count, both only for ACCEPTED frames; facts dicts gain
  fitting_name / correspondence_count. Import check OK.
- steward_review_routes.py: POST /{kind}/{row_id}/explore —
  "Explore with Aria" for reading/fitting/correspondence pending
  items; builds the proposal summary, resolves the user's strand
  thread, and calls ConversationStore.add_strand_source
  (kind=paste, ref=steward:<kind>:<row_id>). 404 discipline mirrors
  the verdict endpoints. Import check OK.
- tests/test_narrative_recognition.py: brief §4 suite (R1–R7,
  T1.1–T7.3) + carried validation/shape/bridge tests + §6.2
  seven-seat twin + import-separation test. First full run:
  24 passed / 5 failed — all five were test-side API mismatches
  (result.detections field name, propose_reading keyword form,
  ThreadReading.progression attribute, Correspondence has no
  proposer field, route closes stores so the bridge test re-opens).
  Fixed; second full run: 29 passed, 0 failed.

## Final verification (2026-11-19)
- New suite: tests/test_narrative_recognition.py — 29 passed, 0 failed.
- Existing suites (23 files matching *narrative* / *steward*):
  552 passed, 0 failed — no regressions.
- Baseline spot-check: tests/test_raven_regression_fixture.py::
  test_t8_budgets_hold fails with AssertionError, identical to its
  main-carried baseline behavior.
- Branch NOT pushed, no PR opened — left local for Gate C.
