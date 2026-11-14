"""Bear S1 regression fixture (2026-11-07): the Nov 7 first meeting,
preserved as deterministic prompt assertions (T1–T13).

The transcript (~/workspace/your_files/zenaf-bear-conversation-transcript-2026-11-07.md)
is the regression case; its acceptance criteria are the brief's §7
table (criteria 1–6 + the opening seed, criterion 7). These tests
assert on the ASSEMBLED prompts — never on model output, never by
source grep alone — using the same in-process render as the brief's
§10 pinned render. No model calls, no live test: the live re-test
needs its own separate authorization (brief §11).

T4/T5/T13 are written in their POST-REBASE (flipped) forms: the
Gardener S1 build (PR #346, merged to main 93e6033) already landed
G4/D1, so the slice shadow line is absent and the slice pronouns
are corrected; the Q-R7 sequencing edit landed in main via PR #348
(b570c65), so the "lecture" sentence is the live text (T13 asserts
"lecture").
"""

from __future__ import annotations

from local_ai.conversation import encounter as ENC
from local_ai.conversation.encounter import EncounterRuntime, EncounterState
from local_ai.conversation.reply import (
    _EXTRA_INSTRUCTIONS_CAP,
    build_voice_prompt,
)
from local_ai.council import archetypes as ARCH
from local_ai.council import capabilities as CAP
from local_ai.council import jurisdictions as JUR
from local_ai.council import meetings as MT


# ---------------------------------------------------------------------------
# Pinned render (brief §10): the prompts generate_voice_reply receives.
# ---------------------------------------------------------------------------

_MESSAGE = "What must be protected here?"


def _prompts():
    """Assemble the Talk prompt and both meeting prompts for a Bear K1
    meeting turn, exactly as the runtime builds them."""
    definition = ENC.build_guardian_k1_definition(MT.GUARDIAN_FIRST_MEETING)
    rt = EncounterRuntime(definition)
    engage_frame = rt._engage_frame()
    turn_frame, _cue = rt._turn_frame(EncounterState(), _MESSAGE)
    fellowship_ref = definition.fellowship_reference or ""
    talk_lines, _ = build_voice_prompt(
        "fixture", "guardian", _MESSAGE, [],
        mode="base", canonical=True,
    )
    meet_engage_lines, _ = build_voice_prompt(
        "fixture", "guardian", _MESSAGE, [],
        mode="base", canonical=False,
        extra_instructions=engage_frame, fellowship_reference=fellowship_ref,
    )
    meet_turn_lines, _ = build_voice_prompt(
        "fixture", "guardian", _MESSAGE, [],
        mode="base", canonical=False,
        extra_instructions=turn_frame, fellowship_reference=fellowship_ref,
    )
    return {
        "definition": definition,
        "guidance": ENC._GUARDIAN_FIRST_MEETING_GUIDANCE,
        "engage_frame": engage_frame,
        "turn_frame": turn_frame,
        "talk": "\n".join(talk_lines),
        "meet_engage": "\n".join(meet_engage_lines),
        "meet_turn": "\n".join(meet_turn_lines),
        "composed_variants": {
            "default": _composed_engage(
                definition,
                CAP.first_meeting_block("guardian", CAP.VisitorState()),
            ),
            "worst-capability": _composed_engage(
                definition,
                CAP.first_meeting_block(
                    "guardian", CAP.VisitorState(signed_in=False)
                ),
            ),
        },
    }


def _composed_engage(definition, capability_block):
    """The composed engage frame, exactly as handle_turn builds it
    (test_guardian_first_meeting.py pattern)."""
    frame = (
        definition.engage_frame
        + "\n\n" + ENC._ZENAF_QUESTION_NOTE
        + "\n\n" + ENC._naming_note(definition)
    )
    if capability_block:
        frame += "\n\n" + capability_block
    return frame


def _composed_variants(definition):
    cap_default = CAP.first_meeting_block("guardian", CAP.VisitorState())
    cap_worst = CAP.first_meeting_block(
        "guardian", CAP.VisitorState(signed_in=False)
    )
    import dataclasses

    return {
        "default": _composed_engage(definition, cap_default),
        "worst-capability": _composed_engage(definition, cap_worst),
        "fully-met+worst": _composed_engage(
            dataclasses.replace(
                definition,
                met_seats=(
                    "mentor", "champion", "maverick",
                    "ambassador", "conductor", "skeptic",
                ),
            ),
            cap_worst,
        ),
    }


# ---------------------------------------------------------------------------
# T1 — the quoted warmth phrase is absent (BC3, brief §2).
# ---------------------------------------------------------------------------

WARMTH_PHRASE = "I'm not going anywhere"
WARMTH_NEW = (
    "Your warmth register: warm-protective. Validate through steadiness "
    "and shelter. Never through analyzing their feelings."
)
SHADOW_LINE = (
    "Shadow — your characteristic failure mode, which the Skeptic may "
    "name: Smothering: possessiveness, shielding people from necessary growth."
)


def test_t1_quoted_warmth_phrase_absent_everywhere():
    """BC3: the deletion removed the quotable catchphrase from the
    meeting prompts (the new assertion — Talk already excluded it),
    from the Talk prompt, and from the jurisdictions.py guardian
    warmth copy (Q-B1 cleanup)."""
    p = _prompts()
    assert p["meet_engage"].count(WARMTH_PHRASE) == 0
    assert p["meet_turn"].count(WARMTH_PHRASE) == 0
    assert p["talk"].count(WARMTH_PHRASE) == 0
    assert WARMTH_NEW in p["meet_engage"]
    assert WARMTH_NEW in p["meet_turn"]
    warmth_copy = JUR.SEAT_JURISDICTIONS["guardian"].register.warmth
    assert WARMTH_PHRASE not in warmth_copy
    assert "Validate through steadiness and shelter." in warmth_copy
    # The live line itself carries the new wording.
    assert ARCH.WARMTH_REGISTERS["guardian"] == WARMTH_NEW


# ---------------------------------------------------------------------------
# T5 — shadow lines, identity block out, slice line Gardener-owned
# (BC8, brief §3; FLIPPED form: G4/D1 has landed, so the slice line
# is absent from both frames).
# ---------------------------------------------------------------------------

PROTECTED_SHADOW_TEXT = (
    "Keeping past the point where the kept thing can no "
    "longer leave, grow, or stand independently — "
    "protection that has become retention, with the keeper "
    "believing she is still only sheltering."
)


def test_t5_identity_block_shadow_out_slice_line_absent():
    """BC8 scope: the identity-block shadow line is absent from both
    meeting prompts, and present in the four seats' legacy philosophy
    lines that still carry one (the Champion has none — FC7 removed
    its table entry; the Ambassador has none — CC5 removed its
    table entry). The slice line "Shadow: smothering." is absent
    from both frames (Gardener G4/D1, landed in main). The protected
    shadow field in bear.py is byte-identical."""
    from local_ai.council.canonical.bear import BEAR_RECORD

    p = _prompts()
    assert SHADOW_LINE not in p["meet_engage"]
    assert SHADOW_LINE not in p["meet_turn"]
    assert "Shadow: smothering." not in p["engage_frame"]
    assert "Shadow: smothering." not in p["turn_frame"]
    for other in ("mentor", "maverick", "conductor", "skeptic"):
        lines = ARCH.philosophy_prompt_lines(other)
        assert any(
            "Shadow — your characteristic failure mode" in line
            for line in lines
        ), other
    # The Champion (FC7) and the Ambassador (CC5) have no shadow
    # line either — their table entries were removed by those
    # corrections, not this one.
    for shadowless in ("champion", "ambassador"):
        assert "Shadow — your characteristic failure mode" not in "\n".join(
            ARCH.philosophy_prompt_lines(shadowless)
        ), shadowless
    assert (
        BEAR_RECORD["protected"]["shadow"]["text"] == PROTECTED_SHADOW_TEXT
    )
    # The table itself stays the frozen rollback source.
    assert (
        ARCH.ARCHETYPE_PHILOSOPHY["guardian"]["shadow"]
        == "Smothering: possessiveness, shielding people from necessary growth."
    )


# ---------------------------------------------------------------------------
# T7 — the new opening is adopted verbatim (BC9, brief §4).
# ---------------------------------------------------------------------------

NEW_OPENING = (
    "Well, don't just stand there in the doorway! Come in, come in. There's a fire going, and I believe we've enough supper for another.",
    "Mind that third step. Been meaning to fix it. Though I suppose I've been saying that for years.",
    "You know, I've spent a good deal of my life building things meant to last. Strong foundations. Sturdy walls. A roof that keeps the weather where it belongs.",
    "Funny thing about building, though. Sometimes it's knowing what to mend, what to leave alone, and what to tear down before it falls on somebody.",
    "And people are harder still. Some need shelter. Some need room to wander. Some need someone to stand beside them, and others need someone willing to stand in their way.",
    "I've never been entirely certain which is the greater kindness.",
    "But listen to me, carrying on like an old home builder while the supper's getting cold. When you think of the things in this world worth standing up for, what comes to mind?",
)


def test_t7_new_opening_adopted_verbatim():
    """BC9: all seven bubbles of the new opening are present verbatim
    in GUARDIAN_INTRODUCTION; bubble 6 is kept (Q-B5) and bubble 7
    closes on the values-first question. Bubbles 1–3 are byte-identical
    to the live script they replace."""
    assert MT.GUARDIAN_INTRODUCTION == NEW_OPENING
    assert len(MT.GUARDIAN_INTRODUCTION) == 7
    assert (
        MT.GUARDIAN_INTRODUCTION[5]
        == "I've never been entirely certain which is the greater kindness."
    )
    assert MT.GUARDIAN_INTRODUCTION[6].endswith(
        "When you think of the things in this world worth standing up for, "
        "what comes to mind?"
    )
    # The dropped material is gone: the triage question, the
    # aphorism, the carpenter line, the captive-audience line.
    opening_text = "\n".join(MT.GUARDIAN_INTRODUCTION)
    assert "who to let in" not in opening_text
    assert "hold it so tightly" not in opening_text
    assert "old carpenter" not in opening_text
    assert "captive audience" not in opening_text
    assert "old home builder" in opening_text
    assert "tear down before it falls on somebody" in opening_text


# ---------------------------------------------------------------------------
# T12 — BC8 scoping (brief §9.2): guardian lines are ideal + question
# + tension only; every other seat's lines are unchanged in shape.
# ---------------------------------------------------------------------------


def test_t12_bc8_scoping_per_seat():
    """philosophy_prompt_lines emits exactly three lines for the
    guardian (ideal, question, tension — no shadow) and four for
    the four seats that carry a shadow line; the Champion renders
    three (FC7 removed its table entry) and the Ambassador three
    (CC5 removed its table entry) — neither by this correction."""
    guardian_lines = ARCH.philosophy_prompt_lines("guardian")
    assert len(guardian_lines) == 3, guardian_lines
    assert guardian_lines[0].startswith("Foundational ideal: ")
    assert guardian_lines[1].startswith(
        "Defining question (your instinctive first move on any problem): "
    )
    assert guardian_lines[2].startswith(
        "Live tension with the other seats: "
    )
    assert not any("Shadow" in line for line in guardian_lines)
    for other in ("mentor", "maverick", "conductor", "skeptic"):
        lines = ARCH.philosophy_prompt_lines(other)
        assert len(lines) == 4, (other, lines)
        assert lines[2].startswith(
            "Shadow — your characteristic failure mode"
        ), other
    assert len(ARCH.philosophy_prompt_lines("champion")) == 3
    assert len(ARCH.philosophy_prompt_lines("ambassador")) == 3
    # Unknown ids still render nothing.
    assert ARCH.philosophy_prompt_lines("no-such-seat") == []

# ---------------------------------------------------------------------------
# Slice 4 tests — guidance sentences, name guard, budgets, turn frames.
# ---------------------------------------------------------------------------

BC1_SENTENCE = (
    "Never re-ask what the visitor has already established, and never "
    "manufacture a question merely to keep talking: when they have "
    "answered, recognize the answer."
)
BC2_SENTENCE = (
    "Once you have named a floor, you do not quietly lower it; but you "
    "will reconsider where that floor belongs when the facts change."
)
BC6_SENTENCE = (
    "When the visitor disputes the premise your keeping rests on — what "
    "protection is for, what must be kept, whether keeping is the right "
    "move at all — examine the premise before you re-apply it. Say "
    "plainly where the challenge changed your read, and where you still "
    "hold the line and why."
)
Q1_SENTENCE = (
    "Generosity and reciprocal relationships are themselves a form of "
    "keeping: allies are shelter too."
)
Q4_SENTENCE = (
    "Once this exchange has genuinely shown you how they orient, offer "
    "your first impression on this turn — do not keep waiting for a "
    "better one."
)
NAME_GUARD = "Do not reveal your name yet."
LECTURE_SENTENCE = (
    "never interrupt a meaningful exchange to introduce yourself or to lecture"
)


def test_t2_bc1_no_re_ask_in_guidance_and_frames():
    """BC1: the no-re-ask sentence is verbatim in the guidance and in
    both composed frames (engage and turn)."""
    p = _prompts()
    assert BC1_SENTENCE in p["guidance"]
    assert BC1_SENTENCE in p["engage_frame"]
    assert BC1_SENTENCE in p["turn_frame"]


def test_t3_bc2_floor_not_lowered_in_guidance_and_frames():
    """BC2: the floor sentence is verbatim in the guidance and in both
    composed frames (engage and turn)."""
    p = _prompts()
    assert BC2_SENTENCE in p["guidance"]
    assert BC2_SENTENCE in p["engage_frame"]
    assert BC2_SENTENCE in p["turn_frame"]


def test_t4_corrected_pronouns_in_slices():
    """T4 (flipped form — Gardener G4/D1 landed in main): in the
    guardian guidance slice Firebrand is he, Crane is he, Raven is
    she; in the other six slices Bear is she. The Fox is only ever
    one of he/she/they. Scope is the seven slices only — the still
    misgendered _GUARDIAN_FELLOWSHIP_REFERENCE is Gardener-owned
    and is NOT covered here."""
    slices = {
        "mentor": ENC._MENTOR_REFERENCE_SLICE,
        "champion": ENC._CHAMPION_GUIDANCE,
        "guardian": ENC._GUARDIAN_FIRST_MEETING_GUIDANCE,
        "maverick": ENC._MAVERICK_GUIDANCE,
        "ambassador": ENC._AMBASSADOR_REFERENCE_SLICE,
        "conductor": ENC._WEAVER_FELLOWSHIP_SLICE,
        "skeptic": ENC._SKEPTIC_REFERENCE_GUIDANCE,
    }
    guardian = slices["guardian"]
    assert "Firebrand: he" in guardian
    assert "Crane: he" in guardian
    assert "Raven: she" in guardian
    for key, text in slices.items():
        if key == "guardian":
            continue
        assert "Bear: she" in text, key
        assert "Bear: he" not in text, key
    for text in slices.values():
        assert "Bear: he" not in text
        assert "Crane: she" not in text
        assert "Raven: he" not in text
        assert "Firebrand: she" not in text


def test_t6_q4_shortened_in_guidance_and_frames():
    """Q4-shortened (140 chars, brief §5.2 — NOT the design's 146):
    verbatim in the guidance and in both composed frames; the
    flattery clause still stands in _ENGAGE_GLUE."""
    p = _prompts()
    assert len(Q4_SENTENCE) == 140
    assert Q4_SENTENCE in p["guidance"]
    assert Q4_SENTENCE in p["engage_frame"]
    assert Q4_SENTENCE in p["turn_frame"]
    # The flattery clause still stands in _ENGAGE_GLUE (brief §5.2
    # paraphrases it; the live wording is the earned-impression line).
    assert (
        "an impression offered before it is earned is flattery"
        in ENC._ENGAGE_GLUE
    )


def test_t8_name_guard_counts():
    """E4: the name guard stands twice in the engage frame and once in
    the turn frame (the encounter frame tail's second instance)."""
    p = _prompts()
    assert p["engage_frame"].count(NAME_GUARD) == 2
    assert p["turn_frame"].count(NAME_GUARD) == 1


def test_t9_all_new_guidance_in_both_frames():
    """BC1, BC2, Q4-shortened, BC6, Q1 — every new guidance sentence
    is present in both composed frames (engage and turn)."""
    p = _prompts()
    for sentence in (
        BC1_SENTENCE,
        BC2_SENTENCE,
        Q4_SENTENCE,
        BC6_SENTENCE,
        Q1_SENTENCE,
    ):
        assert sentence in p["engage_frame"], sentence[:40]
        assert sentence in p["turn_frame"], sentence[:40]


def test_t10_budgets(caplog):
    """Budgets (§5.5, brief figures governing): Talk character block
    1,443/1,500; engage frame ≤ 9,000; turn frame ≤ 9,000; composed
    engage headroom ≥ 300 in every variant; the _cap_section loud
    warning never fires for any Bear frame."""
    import logging

    from local_ai.conversation.reply import (
        _EXTRA_INSTRUCTIONS_CAP,
        _cap_section,
    )
    from local_ai.council.canonical.bear import BEAR_RECORD
    from local_ai.council.render import render_bear_ordinary

    block = "\n".join(render_bear_ordinary(BEAR_RECORD))
    assert len(block) == 1443
    assert len(block) <= 1500
    p = _prompts()
    assert len(p["engage_frame"]) <= 9000
    assert len(p["turn_frame"]) <= 9000
    assert _EXTRA_INSTRUCTIONS_CAP == 9000
    for name, frame in p["composed_variants"].items():
        headroom = _EXTRA_INSTRUCTIONS_CAP - len(frame)
        assert len(frame) <= _EXTRA_INSTRUCTIONS_CAP, name
        assert headroom >= 300, (name, headroom)
    with caplog.at_level(logging.WARNING):
        for section, frame in (
            ("engage", p["engage_frame"]),
            ("turn", p["turn_frame"]),
        ):
            assert (
                _cap_section(
                    frame, _EXTRA_INSTRUCTIONS_CAP, section, "guardian"
                )
                == frame
            )
    assert not [
        r for r in caplog.records if "prompt section truncated" in r.message
    ]


def test_t11_measured_lengths():
    """Measured lengths (§5.5): Q1 97, BC6 285, BC1 158, BC2 129,
    Q4-shortened 140; the guidance addition is exactly the five
    sentences joined with single spaces (814 chars total, fixed
    order Q1, BC6, BC1, BC2, Q4); the encounter-frame addition is
    exactly the 29-char name-guard tail."""
    assert len(Q1_SENTENCE) == 97
    assert len(BC6_SENTENCE) == 285
    assert len(BC1_SENTENCE) == 158
    assert len(BC2_SENTENCE) == 129
    assert len(Q4_SENTENCE) == 140
    assert len(NAME_GUARD) == 28
    addition = (
        " " + Q1_SENTENCE + " " + BC6_SENTENCE + " " + BC1_SENTENCE
        + " " + BC2_SENTENCE + " " + Q4_SENTENCE
    )
    assert len(addition) == 814
    p = _prompts()
    assert p["guidance"].endswith(addition)
    assert "in front of you is theirs. Do not reveal your name yet." in p[
        "engage_frame"
    ]
    assert len(" Do not reveal your name yet.") == 29


def test_t13_turn_frames_lecture_form():
    """T13 (lecture form — the Q-R7 sequencing edit LANDED in main
    via PR #348, b570c65, so the turn frames say 'lecture', not
    'teach'; this build never edits that sentence, it only flips
    the pin). The sentence is verbatim in all five turn frames and
    in the steward_records.py duplicate; the old teach sentence is
    gone from all of them (the Weaver frame's unrelated 'teaching
    every feature' is untouched and is NOT what this asserts on)."""
    import local_ai.council.steward_records as SR

    frames = {
        "weaver": ENC.WEAVER_TURN_FRAME,
        "guardian": ENC.GUARDIAN_TURN_FRAME,
        "mentor": ENC.MENTOR_TURN_FRAME,
        "skeptic": ENC.SKEPTIC_TURN_FRAME,
        "champion": ENC.CHAMPION_TURN_FRAME,
    }
    teach_sentence = (
        "never interrupt a meaningful exchange to introduce yourself or to teach"
    )
    for key, frame in frames.items():
        assert LECTURE_SENTENCE in frame, key
        assert teach_sentence not in frame, key
    assert LECTURE_SENTENCE in SR.TURN_FRAME
    assert teach_sentence not in SR.TURN_FRAME
