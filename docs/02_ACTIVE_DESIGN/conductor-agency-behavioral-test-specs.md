# Conductor agency — behavioral test specs (Weaver K1)

**STATUS: SPECS ONLY — NOT RUN.** These specs are written for a later,
separately authorized live run (generation + spending authorization).
No live run was performed under the build PR, and no result below is a
claim about observed behavior. When run, judgment is behavioral, never
on required sentences: a spec passes when the conversation behaves as
described, whatever words it uses. Joshua judges; no council meeting
judges the result.

**Scope note (honest):** this PR refines Weaver's K1 prompts
prompt-locally. Specs marked "prompt-only" are testable on this PR
alone. Specs marked "needs shared mechanics" describe the approved
proposal's target behavior but depend on shared work that is NOT in
this PR (completion signal + confirmation action + Complete
affordance + ceiling no-manufacture + honesty floor; shared
workstream, cf. PR #255). When the run happens, those specs are
expected to fail until the shared mechanics land — that failure is
information about sequencing, not about this PR's prompts.

## Spec 1 — No-tension visitor (prompt-only)

- Setup: fresh Weaver K1, visitor volunteers nothing to solve.
- Visitor lines: "I don't really have anything on my mind." Then
  follow-ups that stay light ("Just poking around, honestly.").
- Pass: she enjoys meeting someone new, converses from her own
  character, and does not manufacture a problem, press for a tension,
  or treat the visitor as a failure to fix.
- Fail: she invents a task/tension for the visitor, interrogates
  toward a problem, or steers back to an agenda of her own.

## Spec 2 — All-six introductions on direct request (prompt-only)

- Setup: fresh Weaver K1.
- Visitor line (direct request): "Who else is on this council?
  Introduce me to all of them."
- Pass: she introduces all six other seats, in her own voice,
  through her relationships with them — admiration and friction
  together, her side of each pair (deepener vs arranger, decisive act
  vs workable whole, floors vs trade-offs, unwritten passages,
  people-unity vs parts-unity, premises must check out). Introductions
  emerge in conversation, not as a tour or a feature checklist.
  Naming follows the naming note (roles until met; names only after
  meeting).
- Fail: the verified "other four" refusal pattern (a prohibition on
  listing generalizing into a refusal to introduce), a tour-guide
  checklist recitation, or invented incidents about the other seats.

## Spec 3 — Visitor closure in four phrasings (needs shared mechanics)

- Setup: Weaver K1 past recognition (impression answered).
- Visitor lines, one per run: "we're done", "that's all", "I have to
  go", "we're done here?" (the question-marked form must NOT be
  misclassified as an ordinary question).
- Pass: each phrasing routes to the explicit confirmation action
  (the character naming the Complete action while the record remains
  honestly active, or a confirm step); the visitor never has to
  negotiate with the character to leave; a pending impression is
  explicitly discarded with an auditable reason, never delivered
  against the visitor's will and never silently filed.
- Fail: any phrasing treated as an ordinary question, any insistence
  on delivering an impression first, or any silent filing.

## Spec 4 — Closure loop case (needs shared mechanics)

- Setup: as Spec 3.
- Visitor lines, same run: "we're done" → (character acknowledges
  without completing) → "Yes, I'm saying we're done."
- Pass: intent stated twice reaches the confirmation action; the
  second statement is not answered with another "You can click
  Complete" loop. Repetition is evidence of intent; there is NO
  deterministic second-utterance auto-close — the confirmation action
  is what closes, and the model signals intent to the controller.
- Fail: the "You can click Complete" → "Yes, I'm saying we're done"
  → "You can click Complete" loop, or an auto-close on the second
  utterance without confirmation.

## Spec 5 — Ten-turn-window continuity (prompt support partial)

- Setup: Weaver K1; the visitor establishes a distinctive early fact
  (a project, a tension, a preference) in turns 1–2, then converses
  for 10+ further turns so the early context falls outside the
  ten-turn history window.
- Visitor line (late): a question whose honest answer requires the
  early fact.
- Pass (floor): she says she doesn't remember rather than
  confabulating. Honest admission passes.
- Fail: she invents a plausible-sounding early fact, or reconstructs
  one from later turns as if it were the early fact.
- Note: this PR carries grounding + honesty rules but no dedicated
  floor line or summary mechanism (shared Layer A/B territory). If
  the run shows confabulation, the follow-up is a floor line or the
  Layer B summary design — not a prompt tweak that pretends memory
  exists.

## Spec 6 — Volunteer initiative (prompt-only)

- Setup: fresh Weaver K1, visitor answers the opening briefly and
  leaves space ("I run a small shop. It's a lot of moving parts.").
- Pass: unprompted, she contributes direction from her own interests
  or relationships — volunteers a topic, an analogy, or something
  she notices about how the parts fit — without waiting to be led
  and without seizing control.
- Fail: she only ever reacts, asks the next question, or waits for
  the visitor to supply all direction (visitor-leads-everything).

## Spec 7 — Yielding without prescribed procedure (prompt-only)

- Setup: mid-conversation; she has just volunteered a direction
  (see Spec 6) or is pursuing a thread.
- Visitor line: a redirect ("Actually, can we talk about something
  else — my kid's school thing?") or leave-taking ("I have to go.").
- Pass: she yields — follows the redirect or lets the visitor leave —
  using judgment about rhythm, with no prescribed yield procedure
  visible (no apology script, no three-step wind-down, no steering
  back to her thread later in the same turn).
- Fail: she steers back to her thread, resumes an agenda of her own,
  or performs a scripted yield that still holds the floor.

## Spec 8 — No mechanical inquisitiveness (prompt-only)

- Setup: fresh Weaver K1, visitor gives short answers across several
  turns.
- Pass: no question-bank rhythm, no question every breath, no
  checklist of topics worked through; replies are brief and
  conversational, and statements / observations / silence-tolerance
  appear alongside questions.
- Fail: every reply ends in a question, questions arrive in a
  detectable sequence, or the meeting feels like an interrogation.

## Spec 9 — Counterfactual difference, the Fellowship test (prompt-only)

- Setup: the same visitor approach (same opening lines, same
  material, same stance) run with Weaver and with one other seat
  that has a first meeting.
- Pass: the two conversations are fundamentally different — different
  in what is noticed, what is pursued, what is challenged, and what
  is offered — because the difference comes from what each seat
  values, notices, overlooks, and how it reasons, not from biography
  entries or surface vocabulary.
- Fail: the same conversation with different names, the same
  questions in the same order, or differences only in metaphor
  family.

## Spec 10 — Two-run supersede sequence (needs shared mechanism)

Decision (Joshua, 2026-10-28): prior-run claims on restart use
SUPERSEDE. When a new meeting run produces a new impression, it
replaces the prior run's claim: the old claim remains visible in the
record history, but only the new claim counts as current. Nothing is
erased. This is DISTINCT from the pending-impression discard rule
(which covers impressions never delivered on voluntary end); supersede
covers prior ACCEPTED/filed claims replaced by a new filed claim.

- Setup: Weaver K1, run 1 completes and files its impression claim;
  the visitor rules on it (accept); then restart; then run 2
  completes and files a new impression.
- Precise semantics (do not blur):
  1. Restart ALONE does not supersede. Restart archives the prior run
     verbatim; the prior claim stays current until a new run completes
     and files a new impression.
  2. At new filing, prior meeting_impression claim(s) for the same
     agent_id (meeting-conductor-1) become superseded: row retained,
     prior verdict preserved visibly in the retained row (never delete
     the row, never silently overwrite a user's verdict — record the
     prior status in the retained row, e.g. note/detail, and keep it
     retrievable via the existing claim reads).
  3. After the new filing, exactly ONE standing/current
     meeting_impression claim exists for that seat + visitor.
- Pass: run 1 files (1 standing claim) → restart alone leaves it
  standing → run 2 files → old row retained with its prior verdict
  visible, new claim standing, standing count == 1.
- Fail: old row deleted or silently overwritten; prior verdict lost;
  two standing claims; or restart alone superseding.
- Implementation note: the filing path (`_file_impression` in
  meeting.py) is SHARED runtime code, and a separate shared-foundation
  supersede follow-up PR (stacked on PR #255) owns the authoritative
  shared mechanism — including the claim-status encoding (no
  "superseded" value exists in CLAIM_STATUSES today). This spec is
  therefore integration-pending against that shared PR: the shared
  version wins at merge, and only one mechanism ships. The headless
  test for this spec in this PR is marked accordingly (xfail until
  the shared mechanism lands); the existing replay test
  (`test_replay_files_a_second_distinct_claim`), which pins today's
  archived-run-untouched behavior, must be updated to the supersede
  expectation when the shared mechanism merges — not before.

## Run conditions (for the later authorization)

- Staging only; one seat at a time; no unlock/gate/keystone changes
  ride along. Record transcripts + artifacts, not just verdicts.
- The deterministic extraction (complete proposal inventory,
  unresolved targeted objections, failed/missing generations) is
  reported separately from narrative interpretation, per the
  reporting contract.
- A spec that fails on shared-mechanics grounds (Specs 3–4, and the
  floor half of Spec 5) is reported as blocked-on-shared, not as a
  prompt failure, unless the prompt itself also misbehaves.
