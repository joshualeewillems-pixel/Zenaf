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
