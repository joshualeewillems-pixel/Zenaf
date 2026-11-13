"""The canonical instruction tier (Level 1, 2026-11-10): the standing
instruction lines that are constant across all seven seats (the four
Level 1 lines, plus RC1 added by Raven S1), carried once as a single
uncapped prompt section immediately before the capped
``extra_instructions`` frame on the meeting path only (``meeting.py``
passes ``canonical_tier=True``; Talk and demo leave the flag off and
are byte-identical to before).

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
* RC1 (Raven S1) is the tier's fifth line — the universal
  challenge-grounding discipline, ratified for this placement in
  the Level 1 brief §7 (founder review 2026-11-10, item 3). It sits
  before the honesty guard so the guard remains the tier's last
  line, adjacent to the frame it constrains.
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

#: RC1 (Raven S1; founder ruling Q2, 2026-11-09): the universal
#: challenge-grounding discipline — challenge only what the visitor
#: actually assumes, grounded non-literally (their words, or a
#: metaphor or parallel tracking them), and only when the seat can
#: back it up when questioned; otherwise ask. 198 chars.
ASSUMPTION_GROUNDING = (
    "Challenge only what the visitor actually assumes — "
    "in their words, or in a metaphor or parallel tracking "
    "them. If you cannot back it up when questioned, do not "
    "make it; ask what they assume instead."
)

#: The tier, assembled: the precedence header + the five lines,
#: joined "\n\n". 1,113 chars total (182 header + 921 lines +
#: 5 joins x 2). The honesty guard is last, adjacent to the
#: capability bullets that open the frame that follows.
CANONICAL_TIER_L1 = "\n\n".join([
    CANONICAL_TIER_HEADER,
    QUESTION_NOTE,
    INTENTION_LINE,
    SCOPE_LINE,
    ASSUMPTION_GROUNDING,
    HONESTY_GUARD,
])
