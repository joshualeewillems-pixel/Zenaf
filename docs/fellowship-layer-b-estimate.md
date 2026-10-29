# Continuity Layer B — bounded estimate (Fellowship shared foundation, 2026-10-28)

**Status: ESTIMATE ONLY. Nothing in this document is built.**
Layer A (the continuity honesty floor — "I don't remember" rather
than confabulation when early context has left the ten-turn window)
is built in this round as shared machinery in
`local_ai/conversation/reply.py`. This document estimates Layer B —
a minimal meeting-scoped rolling summary that preserves conversational
context WITHOUT manufacturing psychological interpretations — and
recommends DEFER (reasons below).

## What Layer B would have to do

Carry something from turns 1..N-10 into turns N+ so the character can
develop and return to a subject, instead of treating every visitor
message as an isolated exchange — while never inventing a read of the
visitor (no traits, no tensions, no motives, no "you are someone who…").

## What it would touch

1. `local_ai/conversation/encounter.py` — a new `EncounterState`
   field (e.g. `rolling_context: str`, capped) persisted in
   `state_json` via `to_json`/`from_json`, plus the update rule.
2. `local_ai/conversation/meeting.py` — `turn()` passes the rolling
   context into `_generate_framed`; `restart()` already deletes the
   live row, which is what makes the scope meeting-only.
3. `local_ai/conversation/reply.py` — `build_voice_prompt` accepts
   the rolling context as one more uncapped-or-capped prompt section
   (same placement mechanism as `fellowship_reference`).
4. Tests — window-drop tests (fact in turn 2, referenced in turn 13,
   correctly recalled or honestly missed), cap tests (context never
   exceeds its budget), no-interpretation tests (summary contains no
   trait/tension language), restart tests (new run starts clean).

## Can it avoid persistent memory, training, and steward architecture?

YES, but only for the deterministic variant, and only strictly:

- **Persistent memory:** avoided IF the rolling context lives only in
  the live meeting row's `state_json` (deleted by `restart()`, never
  copied to any profile, thread, or claim store). The archive path
  (`archive_run`) stores transcript + claim, not state — that must
  stay true, or the summary leaks into a permanent record.
- **Training:** avoided — the summary is never filed as a claim and
  never feeds any training signal. (The existing invariant — nothing
  trains without a user verdict on a filed claim — is untouched.)
- **Steward architecture:** avoided — no steward record, no S1
  wiring, no arc state. The summary is prompt-local context for one
  meeting, like the frames.
- **The catch:** the avoidance holds only while the summary is
  produced WITHOUT a model call. A model-written summary is itself an
  interpretation engine: it selects, compresses, and reframes, which
  is exactly how a psychological read ("you keep returning to control")
  gets manufactured from neutral turns. Guarding that with a
  "no-interpretation" instruction is a prompt hope, not a mechanism —
  it cannot be unit-tested into a guarantee.

## The two variants, sized

### Variant D — deterministic extractive carry (the only minimal one)

No model call. When a turn falls out of the ten-turn window, its
verbatim user text (truncated, e.g. first 300 chars per turn, at most
~3 turns) is appended to the rolling context in `state_json`. The
character sees quoted early turns, labeled as such ("Earlier in this
meeting, you said: …"). Nothing is paraphrased, so nothing is
interpreted — but this is honestly a **window extension with
attribution**, not a summary: it preserves exact words, not gist,
and its token cost grows with the meeting (bounded only by the cap,
which then drops the oldest quotes — the same cliff, moved).

- Size: ~150–250 lines of code + ~150 lines of tests. Small.
- Risk: low, but the payoff is also low: it does not give the
  character a *sense* of the thread, only more quoted lines.

### Variant M — model-written rolling summary (the real Layer B)

One extra generation per turn (or every k turns) rewriting the
rolling context from the window + prior summary. This is the version
that would actually let her "develop and return to a subject" — and
it fails the round's constraint in practice:

- Cost: a full extra generation per turn (latency + spend on every
  meeting turn, against the $0.50/meeting ceiling culture of the
  build-council work); a parse-failure mode with a fallback rule.
- Interpretation risk: untestable-by-construction. The acceptance
  test ("summary contains no psychological interpretation") can only
  check a denylist of words, not the absence of framing.
- Size: ~400–600 lines + an evaluation harness (sample meetings
  judged for invented reads) — substantial new machinery, plus a
  standing spend commitment.

## Recommendation: DEFER

Variant D is minimal and clean but is not a summary — it buys quoted
lines at token cost and should be judged as a window change, not
approved as Layer B. Variant M is a real summary but needs substantial
new machinery (an extra generation per turn, an interpretation
evaluation harness, a spend commitment) and cannot satisfy
"without manufacturing psychological interpretations" by mechanism,
only by instruction. The honest floor — Layer A, built this round —
already covers the failure mode that matters (confabulation). Revisit
Layer B after the per-seat builds, as a bounded pilot with a measured
token budget and a judged sample, not as part of this round.

## Open points for the revisit

- Cap for the rolling context (chars) and drop rule when it fills.
- Whether the rolling context is shown to the visitor (transparency)
  or prompt-only (it should be inspectable; the meeting transcript
  already is, the prompt is not).
- Whether Variant D's quoted carry is worth its tokens at all, versus
  simply widening the history window from 10 turns (one constant,
  same cliff shape, no new machinery) — that comparison belongs in
  the revisit, not smuggled in here.
