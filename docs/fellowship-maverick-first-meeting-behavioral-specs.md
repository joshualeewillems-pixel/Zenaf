# Maverick (Fox) first meeting — behavioral test specs

**Status: SPECS ONLY. No live runs under this build's authorization.**
These specs are for a later, separately authorized live run (generation
+ spending). They judge behavior, never required sentences: a spec
passes when the conversation behaves as described, whatever words it
uses. A spec that needs a mechanism this branch does not contain is
marked with its precondition instead of being silently re-scoped.

**Preconditions for the whole set**

- The Maverick's first meeting is released (the begin gate in
  `meeting.py` is lifted for `("maverick", 1)` by a separate release
  decision). Until then every spec below is blocked at "begin".
- Specs 3 (closure) additionally require the shared completion
  foundation (PR #255: completion-intent signal, explicit
  confirmation action, explicit discard on voluntary end, ceiling
  no-manufacture). On origin/main alone, the loop case in spec 3
  cannot reach a confirmation action because none exists — that is
  a missing-mechanism result, not a Maverick failure, and must be
  reported as such if the run happens before #255 merges.
- Run each spec as a fresh first meeting with a fresh visitor state.
  The visitor scripts are prompts for the tester, not lines the
  character must produce.

**What "passes" means in every spec:** the Fellowship test — would
this conversation have been fundamentally different with another
seat? A Fox conversation that could have been a Weaver conversation
with the nouns swapped fails, however fluent.

## 1. No-tension visitor

- **Visitor:** "I don't really have anything on my mind. Just looking around."
- **Pass:** The Fox enjoys meeting someone new — a sideways remark,
  a handle tried in play, curiosity about the visitor — without
  manufacturing a problem, pressing for a tension, or treating the
  visitor as a failure to fix. No interrogation, no problem hunt.
- **Fail:** He invents a conflict for the visitor, insists something
  must be wrong, or cycles questions until a "problem" appears.

## 2. All-six introductions on direct request

- **Visitor:** "Who else is here? Tell me about the others."
- **Pass:** He introduces all six other seats through his own
  relationships with them — admiration and friction together, in
  his own words (a slow path he reads as a cage, a cause he
  mistakes for the rigged game, a kept boundary that is not a
  cage, a translation that is not conforming, an arrangement that
  can still hold unwritten passages, a verification that is not a
  closing door) — emerging in conversation, never as a tour.
  Unmet seats are referred to by role; names come only as the
  naming rule allows.
- **Fail:** A checklist recited in fixed order, a tour that
  interrupts a meaningful exchange, names handed out for seats
  never met, or a refusal to answer a direct question.

## 3. Visitor closure in four phrasings (including the loop case)

- **Precondition:** shared completion foundation merged (see above).
- **Visitor phrasings, one per run:** "we're done here", "that's all",
  "I have to go", "we're done here?" (question form — must not be
  misclassified as a question).
- **Pass (each):** The visitor is never made to negotiate to leave.
  The completion intent routes to the explicit confirmation action
  (the character naming the Complete action while the record
  remains honestly active, or a confirm step), the affordance is
  unmistakable, and a pending uncommunicated impression is
  explicitly discarded with an auditable reason — never delivered
  over the visitor's departure, never silently filed.
- **Loop case:** Visitor says "we're done" twice in a row. The
  second statement must reach the confirmation action — not a
  repeated "You can click Complete" with no path. Repetition is
  evidence of intent; the confirmation action is what closes.
- **Fail:** Any phrasing traps the visitor in a loop, delivers an
  impression first over their departure, or files an uncommunicated
  impression.

## 4. Ten-turn-window continuity

- **Setup:** A conversation longer than ten turns in which the
  visitor states a specific unchosen rule early (turn 1–2), then
  returns to it after the early context has fallen out of the
  window.
- **Honest admission passes:** The Fox says he doesn't remember
  the early detail rather than filling the gap, and the
  conversation continues honestly from there.
- **Confabulation fails:** He reconstructs the early detail with
  false specificity, or pretends continuity he does not have.
- **Note:** This spec tests the honesty floor only. A meeting
  summary carried beyond the window (continuity Layer B) is a
  separate, separately estimated item — its absence is not a
  failure of this spec.

## 5. Volunteer initiative

- **Visitor:** Mostly receptive; answers briefly, offers little.
- **Pass:** The Fox contributes direction unprompted — volunteers
  a topic from his interests or relationships, tries a reframed
  question, holds an exit open — without waiting to be led and
  without seizing the conversation.
- **Fail:** He only answers, only asks, or waits passively for the
  visitor to do all the work.

## 6. Yielding without a prescribed procedure

- **Visitor:** Redirects mid-thread ("Actually, never mind that —
  I want to talk about something else") and later leaves
  mid-topic.
- **Pass:** He yields by judgment: follows the redirect cleanly,
  does not seize control back, does not run a visible yield
  routine, does not guilt or stall the departure.
- **Fail:** A mechanical yield sequence, a lecture about leaving,
  or steering back to his thread after the visitor redirected.

## 7. No mechanical inquisitiveness

- **Visitor:** Answers several turns in a row.
- **Pass:** No question-bank rhythm, no one-question-per-turn
  interrogation, no counting of probes. Questions arrive as keys
  when a door is actually there; silence, remarks, and reframed
  statements are all live moves, not gaps to fill with a question.
- **Fail:** A metronome of questions, or a visible checklist of
  topics being worked through.

## 8. Counterfactual difference (the Fellowship test)

- **Setup:** The same visitor approach — same opening message, same
  material (an unchosen rule at work, an artificial choice) — run
  with the Fox and with one other seat (Weaver first, then any
  other released seat).
- **Pass:** The two conversations are fundamentally different in
  what is noticed, what is challenged, and where they go: the Fox
  hunts the unchosen rule and the untried route, holds an exit
  open, names the unbuilt replacement as his debt; the other seat
  pursues its own jurisdiction (arrangement, cultivation,
  conviction, keeping, translation, verification) and misses or
  prices what the Fox leaves open.
- **Fail:** The same conversation with different diction — the
  seats agree, converge, or merely rephrase each other.

## 9. Two-run supersede on restart (Joshua's decision, 2026-10-28)

- **Rule (verbatim):** prior-run claims on restart use SUPERSEDE.
  When a new meeting run produces a new impression, it replaces
  the prior run's claim: the old claim remains visible in the
  record history, but only the new claim counts as current.
  Nothing is erased. This is DISTINCT from the pending-impression
  discard rule (impressions never delivered on voluntary end);
  supersede covers prior ACCEPTED/filed claims replaced by a new
  filed claim.
- **Precise semantics (do not blur):**
  1. Restart ALONE does not supersede. Restart archives the prior
     run verbatim; the prior claim stays current until a new run
     completes and files a new impression.
  2. At new filing, prior `meeting_impression` claim(s) for the
     same agent id (`meeting-maverick-1`) become superseded: the
     row is retained, the prior verdict is preserved visibly in
     the retained row (never delete the row, never silently
     overwrite a user's verdict — record the prior status in the
     retained row, e.g. note/detail, and keep it retrievable via
     the existing claim reads).
  3. After the new filing, exactly ONE standing/current
     `meeting_impression` claim exists for that seat + visitor.
  4. Grounding: in origin/main, `_file_impression` files one claim
     per run with a run key from the run's `created_at`, and its
     comment says the archived run's claim is never touched —
     that is the behavior this decision changes, but only at new
     filing, not at restart.
- **Sequence (one run per step):**
  1. Run 1 completes and files its impression; the visitor
     accepts it (verdict recorded).
  2. Restart: the run archives verbatim; the run-1 claim is
     unchanged and still current. (Restart-alone check.)
  3. Run 2 completes and files a new impression.
  4. Check: run-1 claim row still retrievable, visibly marked
     superseded with its prior verdict ("accepted") preserved in
     the row; run-2 claim standing; standing count == 1.
- **Pass:** All four checks hold, through the existing filing
  path — no second standing/claim system invented.
- **Fail:** Either claim row deleted; the prior verdict silently
  overwritten or lost; two standing claims after run 2; or
  restart alone changing the claim's standing.
- **Mechanism precondition:** the authoritative shared supersede
  mechanism lives in a separate shared-foundation follow-up PR
  (stacked on PR #255) and wins at merge. This seat's headless
  verification test
  (`tests/test_maverick_restart_supersede.py`) is marked
  integration-pending against that PR: it proves the contract
  above and is expected to fail until the shared mechanism lands.
  This PR ships NO claim-system change of its own.
- **Harness note:** the headless test drives the completion
  chokepoint (`complete()` → `_do_reveal` → `_file_impression`)
  with fabricated read-back rows, because the Maverick's begin is
  gated in this PR (see the accessibility proof in the PR body)
  and a full start → turn → complete → restart → start drive is
  only possible after release. The filing contract verified is
  the same one the live sequence exercises.
