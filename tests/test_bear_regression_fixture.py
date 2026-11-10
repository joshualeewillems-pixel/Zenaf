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
are corrected; the Q-R7 sequencing edit has NOT landed, so the
"teach" sentence is still the live text (T13 asserts "teach").
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
        "engage_frame": engage_frame,
        "turn_frame": turn_frame,
        "talk": "\n".join(talk_lines),
        "meet_engage": "\n".join(meet_engage_lines),
        "meet_turn": "\n".join(meet_turn_lines),
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
