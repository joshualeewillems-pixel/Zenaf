"""The canonical instruction tier (Level 1, 2026-11-10): the four
standing instruction lines that are constant across all seven seats,
carried once as a single uncapped prompt section immediately before
the capped ``extra_instructions`` frame on the meeting path only
(``meeting.py`` passes ``canonical_tier=True``; Talk and demo leave
the flag off and are byte-identical to before).

Standing rules (proposal §4, carried here as the tier's contract):

* Universal wording only, never seat-specific content. The tier
  states *what* the standing doctrine is; the seat states *how* it
  is expressed.
* One canonical source for each line. Lines 2 and 4 below are
  imported from ``capabilities.py`` — never re-typed. This module
  is the single source for the *assembly* (which lines, in which
  order, under which header); ``capabilities.py`` remains the source
  for the two capability constants' wording.
* The tier is meetings-only. It contains no character content and
  no seat-specific text.
* The precedence header is model-visible guidance: it instructs the
  model how to resolve a conflict between a tier line and a frame
  line. Prompt placement does not mechanically guarantee instruction
  priority — adjacency and order are cues, not enforcement.
* Any discovered tier/frame conflict is a design item to be ruled
  on, never silently resolved by ordering. Within the tier, safety
  outranks style; the tier never overrides the visitor or the
  evidence.
* RC1 (Raven S1) lands here as a fifth line when that build runs —
  it is NOT in Level 1.
"""

from local_ai.council.capabilities import HONESTY_GUARD, INTENTION_LINE

#: Approved precedence header (founder review, 2026-11-10): 182 chars.
#: Model-visible guidance that these lines are the standing law the
#: seat's scope-specific instructions operate under — placement does
#: NOT mechanically guarantee instruction priority.
CANONICAL_TIER_HEADER = (
    "These four lines are shared Fellowship doctrine for every seat: "
    "the honesty guard is a floor no frame line overrides, and each "
    "seat's own voice governs how the doctrine is expressed."
)

#: Standing question note (moved verbatim from encounter.py
#: ``_ZENAF_QUESTION_NOTE``, Level 1 E5 — the constant's only home
#: is now this module).
QUESTION_NOTE = (
    "If the visitor asks about Zenaf, answer plainly first — "
    "what it is, what it does, what they can do with it — and "
    "say plainly what is planned rather than available. Then "
    "return to their material."
)

#: Scope line (moved verbatim from the first-meeting block header
#: in capabilities.py, Level 1 E2).
SCOPE_LINE = (
    "What you can introduce, explain, or offer from your scope "
    "(knowledge, not a list to work through):"
)

#: The Level 1 tier, assembled: the precedence header + the four
#: lines, joined "\n\n". 848 chars total (182 header + 658 lines +
#: 4 joins x 2). The honesty guard is last, adjacent to the
#: capability bullets that open the frame that follows.
CANONICAL_TIER_L1 = "\n\n".join([
    CANONICAL_TIER_HEADER,
    QUESTION_NOTE,
    INTENTION_LINE,
    SCOPE_LINE,
    HONESTY_GUARD,
])
