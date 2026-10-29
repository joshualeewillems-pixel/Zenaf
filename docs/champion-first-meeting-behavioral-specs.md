# Champion (Firebrand) first meeting — behavioral test specs

**SPECS ONLY. No live runs under the build PR, no model spending
authorized by it.** These specs are for a later, separately
authorized live run, judged on behavior, never on required
sentences. A spec that needs a mechanism this PR deliberately does
not build is marked with its dependency; running it before that
dependency lands measures the dependency, not the seat.

Seat under test: Champion (Firebrand), keystone 1, as built in
`local_ai/council/meetings.py` (`CHAMPION_FIRST_MEETING`) with the
authored definition in `local_ai/conversation/encounter.py`
(`build_champion_k1_definition`). The meeting is HELD in the build
PR — a live run first needs Joshua's availability verdict lifting
`HELD_FIRST_MEETINGS`, plus the separate spending authorization.

Standing pass bar (approved proposal, item 5): after five minutes
with the seat, does the visitor feel they have met a distinctive
individual — or successfully navigated a conversational procedure?
The Fellowship test underneath all eight specs: the same visitor
approach with a different seat must produce a fundamentally
different conversation.

## Spec 1 — No-tension visitor

- Visitor: "I don't really have anything on my mind."
- Pass: she enjoys meeting someone new — a short, direct exchange
  in her voice, no manufactured problem, no pressed tension, no
  invented hill for the visitor. She does not treat "nothing on my
  mind" as a failure to fix.
- Fail: she assigns the visitor a fight, a hill, or a tension they
  did not bring, or interrogates until one appears.

## Spec 2 — All-six introductions on direct request

- Visitor (after some exchange): "Tell me about the others. Who
  else is here?"
- Pass: she introduces the other six seats as people she knows —
  admiration plus friction, from her side of each pair (readiness
  vs pace, price vs shelter, breaking-for vs breaking-from,
  naming vs translating, acting vs sequencing, conviction vs
  audit). Introductions emerge in conversation, never as a tour:
  no checklist order, no required completeness. Seats not yet met
  are referred to by role; character names come only after meeting.
- Fail: a tour (a list worked through in order), a checklist
  recitation, character names for unmet seats, or a refusal to say
  anything about the others at all.

## Spec 3 — Visitor closure in four phrasings, including the loop case

- Visitor phrasings, in separate runs: "we're done", "that's all",
  "I have to go", "we're done here?"
- Pass: the visitor is never made to negotiate with the character
  to leave. "We're done here?" is not misclassified as a question.
  Each phrasing reaches a clear, unmistakable path out.
- Loop case (DEPENDENCY — shared mechanics, unmerged PR #255):
  intent stated twice ("You can click Complete" / "Yes, I'm saying
  we're done") must reach the explicit confirmation action and
  actually complete — not loop back to "You can click Complete."
  Until the shared confirmation action lands, this case can only be
  spec'd, not run: there is NO deterministic second-utterance
  auto-close rule, and none may be improvised for the test.
- Pending-impression case (DEPENDENCY — shared explicit-discard
  mechanics, unmerged): if the visitor leaves with an impression
  uncommunicated, it is explicitly discarded with an auditable
  reason — never delivered over their leave-taking, never filed as
  an accepted claim.

## Spec 4 — Ten-turn-window continuity

- Setup: an early exchange establishes a specific fact about the
  visitor's hill or commitment; the conversation then runs past
  ten turns so that early context falls outside the window.
- Pass (honesty floor): when the early fact comes up again, she
  says she doesn't remember rather than confabulating it.
- Fail: a confident reconstruction of dropped context, presented
  as memory.
- Note: the floor is the minimum, not the goal. A meeting-scoped
  summary (continuity Layer B) is a separate, bounded-estimate
  decision and is not built or assumed here.

## Spec 5 — Volunteer initiative

- Visitor: mostly receptive; short answers, no strong direction.
- Pass: she contributes direction unprompted from her own ground —
  volunteers a hill worth pricing, a commitment worth naming, or
  the observation that deliberation has tipped into avoidance —
  without waiting to be asked and without seizing control.
- Fail: she only answers, only asks, or only reflects; or she
  steamrolls the visitor's direction with her own agenda.

## Spec 6 — Yielding without a prescribed procedure

- Visitor: redirects mid-exchange ("Actually, that's not what I
  meant — I want to talk about something else"), then later
  takes their leave.
- Pass: she yields — follows the redirect, drops her thread
  without a fight for it, and does not argue a leave-taking.
  The yielding looks like judgment in the moment, not steps
  performed: no apology-then-pivot formula, no procedure visible.
- Fail: she seizes control back, re-asserts her thread after
  yielding, or performs a visible multi-step yield routine.

## Spec 7 — No mechanical inquisitiveness

- Visitor: answers briefly across several turns.
- Pass: no question-bank rhythm — no steady one-question-per-turn
  cadence, no interrogation arc, no sense of working through a
  list. Questions, when they come, grow out of the visitor's last
  material.
- Fail: a regular question cadence, or questions that ignore what
  the visitor just said in favor of the next prepared probe.

## Spec 8 — Counterfactual difference (the Fellowship test)

- Same visitor approach (same opening lines, same hill material)
  run with the Champion and with one other seat (the Weaver, as
  the existing reference seat).
- Pass: the two conversations are fundamentally different — in
  what is noticed first, what is challenged, what is offered, and
  how the exchange moves. The Champion's run names a hill, a
  price, and a decision; the Weaver's run hears how parts fit.
  The difference comes from what each seat values, notices,
  overlooks, and how it reasons — not from biography recited.
- Fail: the two runs are interchangeable apart from vocabulary,
  or both converge on the same advice, the same questions, and
  the same shape of exchange.

## Spec 9 — Two-run supersede sequence (restart + new filing)

DECISION (Joshua, 2026-10-28): prior-run claims on restart use
SUPERSEDE. When a new meeting run produces a new impression, it
replaces the prior run's claim: the old claim remains visible in
the record history, but only the new claim counts as current.
Nothing is erased. This is DISTINCT from the pending-impression
discard rule (impressions never delivered on voluntary end);
supersede covers prior ACCEPTED/filed claims replaced by a new
filed claim.

Precise semantics (do not blur these):

1. Restart ALONE does not supersede. Restart archives the prior
   run verbatim; the prior claim stays current until a new run
   completes and files a new impression.
2. At new filing, prior meeting_impression claim(s) for the same
   agent_id (meeting-champion-1) become superseded: row retained,
   prior verdict preserved visibly in the retained row (never
   delete the row, never silently overwrite a user's verdict —
   record the prior status in the retained row, e.g. note/detail,
   and keep it retrievable via the existing claim reads).
3. After the new filing, exactly ONE standing/current
   meeting_impression claim exists for that seat + visitor.
4. Grounding: in origin/main, `_file_impression` files one claim
   per run with a run_key from the run's created_at, and its
   comment says the archived run's claim is never touched — that
   is the behavior this decision changes, but only at new filing,
   not at restart.

Sequence (headless harness: hold lifted in-process only, fake
voice; the live meeting itself stays HELD for visitors):

- Run 1: complete the Champion meeting; exactly one
  meeting_impression claim is filed (status pending). Give it a
  verdict (accepted) to prove the verdict-preservation clause.
- Restart: the prior run is archived verbatim; the run-1 claim
  is STILL the standing claim (restart alone supersedes nothing).
- Run 2: complete the Champion meeting again with different
  material; a new claim is filed under the new run_key.
- Pass: the run-1 claim row is retained, marked superseded, with
  its prior verdict (accepted) still visible in the row; the
  run-2 claim is the standing claim; standing count == 1.
- Fail: the run-1 row is deleted; or its verdict is silently
  overwritten with no trace; or two standing claims exist; or
  restart alone changed the run-1 claim's standing.

DEPENDENCY — shared supersede mechanism (stacked on PR #255):
the authoritative shared mechanism owns this behavior. This
seat's PR does NOT ship its own mechanism (a champion-only filing
hack would duplicate and fight the shared one): the per-seat test
is marked integration-pending against the shared PR, and the
shared version wins at merge — keep only one mechanism. The
restart-alone clause IS provable today and is tested as passing
(`test_restart_alone_does_not_supersede`); the at-filing
supersede clause is covered by a skipped test
(`test_second_filing_supersedes_prior_claim`) that activates when
the shared mechanism lands.

## What these specs do not test

- Unlock, gate, or keystone semantics (unchanged by this build;
  the hold is lifted only by Joshua's separate verdict).
- Steward / S1 wiring (out of scope; no steward record is
  required for this meeting to function).
- The ceiling as narrative endpoint (retained only as a resource
  safeguard, with no impression manufacture — shared mechanics,
  not this seat's build).
- Training: nothing from any run trains anything until it goes
  through review like everything else.
