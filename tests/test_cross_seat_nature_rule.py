"""Q6 cross-seat nature rule tests (Firebrand, 2026-11-07).

The adopted rule (founder, 2026-11-07 ~16:44 PT): a seat's nature
determines what it notices, what it values, what it questions, and
how it expresses itself; it does not prescribe the outcome of every
exchange. Per-turn application is too often; the rule is at least
heavily encouraged, if not forced.

Enforcement is forced where it can be (this file) and encouraged
where it cannot (review rule, design §5.4): the sentence and the
brake are forced by test; the forward-looking "no outcome-prescribing
language without a counterweight" rule is reviewed at PR time, not
tested — a mechanical denylist was considered and rejected (design
§5.4), because it false-positives on legitimate directional lines
(Firebrand's own agency line, Bear's "Do not move on" line).

No model calls, no generations, no staging changes anywhere here:
every test is deterministic prompt inspection.
"""

from __future__ import annotations

import pytest

from local_ai.conversation import encounter as ENC

# The adopted sentence, second-person rendering for guidances
# (design §5.3). The canonical third-person rule as the founder
# adopted it is recorded in the constant's comment in encounter.py.
ADOPTED_SENTENCE = (
    "Your nature determines what you notice, what you value, what you "
    "question, and how you express yourself; it does not prescribe the "
    "outcome of every exchange."
)

# Rollout table (design §5.3): one shared sentence, identical
# wording, in all seven guidances. Firebrand is present in this
# build; the other six join as their corrections land. Each entry
# names the owning correction so a "not yet present" assertion is a
# documented rollout state, not a false failure.
ROLLOUT = [
    # (seat, guidance constant getter, owning correction)
    (
        "champion",
        lambda: ENC._CHAMPION_GUIDANCE,
        "Firebrand S1 build (this build)",
    ),
    (
        "conductor",
        lambda: ENC._WEAVER_REFINEMENT_GUIDANCE,
        "Weaver's next correction, or a single follow-up build",
    ),
    (
        "ambassador",
        lambda: ENC._AMBASSADOR_FIRST_MEETING_GUIDANCE,
        "Crane verdict round (not started)",
    ),
    (
        "maverick",
        lambda: ENC._MAVERICK_GUIDANCE,
        "Maverick S1 build (running)",
    ),
    (
        "guardian",
        lambda: ENC._GUARDIAN_FIRST_MEETING_GUIDANCE,
        "Bear S1 build (authorized, queued)",
    ),
    (
        "skeptic",
        lambda: ENC._SKEPTIC_REFERENCE_GUIDANCE,
        "Raven's correction (not started)",
    ),
    (
        "mentor",
        lambda: ENC._MENTOR_REFERENCE_SLICE,
        "Gardener S1 build (running) — OQ4 ruled 'Create a Mentor "
        "guidance', so the Mentor entry moves to _MENTOR_GUIDANCE "
        "when that constant lands",
    ),
]


def test_n1_the_shared_sentence():
    """N1: the constant equals the adopted sentence (second-person
    rendering, §5.3), and Firebrand's guidance contains it — as the
    last sentence of the new guidance paragraph (§1.2)."""
    assert ENC._SHARED_NATURE_RULE == ADOPTED_SENTENCE
    assert ADOPTED_SENTENCE in ENC._CHAMPION_GUIDANCE
    # Last sentence of the paragraph: nothing follows it in the guidance.
    assert ENC._CHAMPION_GUIDANCE.rstrip().endswith(ADOPTED_SENTENCE)


@pytest.mark.parametrize("seat,guidance,owner", ROLLOUT, ids=[r[0] for r in ROLLOUT])
def test_n2_rollout_table(seat, guidance, owner):
    """N2: the rollout table. Firebrand is present; the six other
    seats are asserted as NOT YET PRESENT with the owning correction
    named. Each seat's correction flips its entry to present. (A
    test that fails until other builds land would be a false
    failure; a table that documents the rollout is the honest
    form.)"""
    text = guidance()
    if seat == "champion":
        assert ADOPTED_SENTENCE in text, seat
    else:
        assert ADOPTED_SENTENCE not in text, (
            f"{seat}: the rule is already present — flip this entry "
            f"to present (owner: {owner})"
        )
