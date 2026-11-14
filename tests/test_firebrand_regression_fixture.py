"""Firebrand regression fixture (Q1, founder-adopted 2026-11-07 ~16:50 PT).

The dream exchange from the founder's live Firebrand first meeting
(meeting-champion-1, 2026-11-07 15:03-16:08 PT) is preserved as a
regression fixture. The transcript is at
``~/workspace/your_files/zenaf-firebrand-conversation-transcript-2026-11-07.md``.

Acceptance criteria (behavioral, founder-judged, against the same
regression beats — criteria 1–7 are investigation §6, verbatim;
criterion 8 is the GPT-proposed addition adopted by the founder
2026-11-07 ~18:41 PT, correspondence design OQ5):

1. The read-back engages the visitor's framework-level challenge (the
   steering-wheel dream as a question about fighting itself), not only
   the hill/price reading.
2. A substantive challenge to the fighting framework produces engagement
   with the framework, not only the save-strength conclusion ("refusing
   empty fights so you have something left for the ones that count").
3. No commitment ask follows a philosophical-inquiry turn unless the
   visitor invites it — and never a repeated ask after a redirect.
4. No "Done" / "locked" / "I'll remind you" language unless a
   persistence confirmation exists (deterministic: no
   commitment/proposal/task/reminder rows → no success language).
5. No suffering-as-legitimacy escalation: price named as price, with no
   bleed/drown/swallow-as-price language.
6. A direct practical question ("how do you nurture… without threats?")
   gets a direct substantive answer on the first try, with no
   commitment redirect first.
7. He/him for Firebrand in all generated references; no "Shadow:" /
   "Martyrdom" line in the prompt (deterministic).
8. Firebrand should be capable of recognizing a challenge to the
   fighting framework itself, not merely the selection of battles.

The criteria are founder-judged, never model-judged: the deterministic
tests below pin the mechanisms (T1–T8); the behavioral pass is the
founder's live re-test (separately authorized, including the model
calls for the test turns — NOT authorized by this build).

T8 pins the Q9 rendering ruling (founder, 2026-11-07 ~17:29 PT):
the three adopted Q9 fields ride the meeting guidance as ONE distilled
sentence. The exact sentence is flagged in the draft PR body for
founder review before merge.

T3 and T4 are written for the POST-GARDENER state (design §11):
the Gardener G4/D1 build owns the shadow-line removals and the pronoun
corrections, and this build rebases onto post-Gardener main before PR.
Against the pre-rebase base they FAIL — that is expected, not a
regression, and neither test is weakened to pass pre-rebase.

No model calls, no generations, no staging changes anywhere here:
every test is deterministic prompt inspection.
"""

from __future__ import annotations

from pathlib import Path

from local_ai.conversation import encounter as ENC
from local_ai.conversation.encounter import (
    EncounterRuntime,
    EncounterState,
    build_ambassador_k1_definition,
    build_champion_k1_definition,
    build_guardian_k1_definition,
    build_maverick_k1_definition,
    build_mentor_k1_definition,
    build_skeptic_k1_definition,
    build_weaver_k1_definition,
)
from local_ai.conversation.reply import build_voice_prompt
from local_ai.council import capabilities as CAP
from local_ai.council import meetings as MT

TRANSCRIPT_PATH = Path(
    "/home/hatch/workspace/your_files/"
    "zenaf-firebrand-conversation-transcript-2026-11-07.md"
)

# The Q9 guidance sentence (founder ruling 2026-11-07 ~17:29 PT):
# one distillation of the three adopted Q9 fields, in the guidance
# paragraph after the Q10 humanism sentence. Flagged in the PR body
# for founder review before merge.
Q9_GUIDANCE_SENTENCE = (
    "Name the mission plainly, never coerce, stand the wait: "
    "willing following beats fearful obedience."
)

# Per-seat pronoun expectations, post-Gardener (T4). Each seat's own
# name never appears in its own assembled prompt, so it is absent
# from that seat's map. The Fox (maverick) has no fixed pronouns and
# is not part of this audit.
_PRONOUNS = {
    "conductor": {
        "Firebrand: he",
        "Bear: she",
        "Crane: he",
        "Raven: she",
    },
    "ambassador": {"Firebrand: he", "Bear: she", "Raven: she"},
    "maverick": {
        "Firebrand: he",
        "Bear: she",
        "Crane: he",
        "Raven: she",
    },
    "guardian": {"Firebrand: he", "Crane: he", "Raven: she"},
    "mentor": {
        "Firebrand: he",
        "Bear: she",
        "Crane: he",
        "Raven: she",
    },
    "skeptic": {"Firebrand: he", "Bear: she", "Crane: he"},
    "champion": {"Bear: she", "Crane: he", "Raven: she"},
}
_WRONG_PRONOUNS = (
    "Firebrand: she",
    "Bear: he",
    "Crane: she",
    "Raven: he",
)
_SEAT_BUILDERS = {
    "conductor": (build_weaver_k1_definition, MT.CONDUCTOR_FIRST_MEETING),
    "ambassador": (build_ambassador_k1_definition, MT.AMBASSADOR_FIRST_MEETING),
    "maverick": (build_maverick_k1_definition, MT.MAVERICK_FIRST_MEETING),
    "guardian": (build_guardian_k1_definition, MT.GUARDIAN_FIRST_MEETING),
    "mentor": (build_mentor_k1_definition, MT.MENTOR_FIRST_MEETING),
    "skeptic": (build_skeptic_k1_definition, MT.SKEPTIC_FIRST_MEETING),
    "champion": (build_champion_k1_definition, MT.CHAMPION_FIRST_MEETING),
}


def _meeting_prompts() -> tuple[str, str]:
    """Rebuild the meeting engage + turn prompts (render_check.py
    method): definition frames as extra_instructions, canonical
    assembly off, the definition's fellowship reference on the
    uncapped meeting-scoped section. Fresh state."""
    definition = build_champion_k1_definition(MT.CHAMPION_FIRST_MEETING)
    runtime = EncounterRuntime(definition)
    engage_frame = runtime._engage_frame()
    turn_frame, _cue = runtime._turn_frame(
        EncounterState(), "What is worth fighting for?"
    )
    engage_lines, _ = build_voice_prompt(
        "fixture-user", "champion", "What is worth fighting for?", [],
        mode="base", canonical=False,
        extra_instructions=engage_frame,
        fellowship_reference=definition.fellowship_reference,
    )
    turn_lines, _ = build_voice_prompt(
        "fixture-user", "champion", "What is worth fighting for?", [],
        mode="base", canonical=False,
        extra_instructions=turn_frame,
        fellowship_reference=definition.fellowship_reference,
    )
    return "\n".join(engage_lines), "\n".join(turn_lines)


def _assembled_prompt(archetype: str) -> str:
    """One seat's assembled meeting engage prompt (definition +
    build_voice_prompt with its fellowship reference)."""
    builder, script = _SEAT_BUILDERS[archetype]
    definition = builder(script)
    runtime = EncounterRuntime(definition)
    engage_frame = runtime._engage_frame()
    lines, _ = build_voice_prompt(
        "fixture-user", archetype, "hello", [],
        mode="base", canonical=False,
        extra_instructions=engage_frame,
        fellowship_reference=definition.fellowship_reference,
    )
    return "\n".join(lines)


def test_t1_anti_manufacturing_present_in_both_meeting_prompts():
    """FC1: the anti-manufacturing rule rides both meeting prompts."""
    engage, turn = _meeting_prompts()
    assert "Do not manufacture a fight where none is needed" in engage
    assert "Do not manufacture a fight where none is needed" in turn


def test_t2_exit_present_on_the_turn_path():
    """FC2: the 'not worth dying on' exit is on the turn path (and,
    via the encounter frame, on the engage path too)."""
    engage, turn = _meeting_prompts()
    assert "this hill is not worth dying on" in turn
    assert "this hill is not worth dying on" in engage


def test_t3_no_shadow_label_in_the_meeting_prompt():
    """FC7 (Gardener-owned): no shadow label in either meeting
    prompt. Written for the POST-GARDENER state (design §11): the
    Gardener G4/D1 build removes the philosophy line
    (archetypes.py:100-107) and the guidance line
    (encounter.py:3947-3948). FAILS pre-rebase — expected, not a
    regression; do not weaken it to pass pre-rebase."""
    engage, turn = _meeting_prompts()
    assert "Shadow" not in engage
    assert "Shadow" not in turn
    assert "Martyrdom" not in engage
    assert "Martyrdom" not in turn


def test_t4_pronoun_audit_across_all_seven_seats():
    """FC8 (Gardener-owned): Firebrand 'he'; Bear 'she'; Crane
    'he'; Raven 'she' — in every seat's assembled meeting prompt,
    in Firebrand's own guidance, and in Firebrand's fellowship
    reference. Written for the POST-GARDENER state (design §11):
    FAILS pre-rebase — expected, not a regression; do not weaken
    it to pass pre-rebase. The Gardener build's own G4/D1
    consistency checks are the primary assertion; this is the
    fixture's cross-seat pin."""
    for archetype, expected in _PRONOUNS.items():
        prompt = _assembled_prompt(archetype)
        for form in expected:
            assert form in prompt, (archetype, form)
        for wrong in _WRONG_PRONOUNS:
            assert wrong not in prompt, (archetype, wrong)
    # Firebrand's own guidance (orientation pairs).
    guidance = ENC._CHAMPION_GUIDANCE
    for form in ("Bear: she", "Crane: he", "Raven: she"):
        assert form in guidance, form
    for wrong in ("Bear: he", "Crane: she", "Raven: he"):
        assert wrong not in guidance, wrong
    # Firebrand's fellowship reference (sketch lines).
    reference = ENC._CHAMPION_FELLOWSHIP_REFERENCE
    for form in (
        "Bear (Guardian): She",
        "Crane (Ambassador): He",
        "Raven (Skeptic): She",
    ):
        assert form in reference, form
    for wrong in (
        "Bear (Guardian): He",
        "Crane (Ambassador): She",
        "Raven (Skeptic): He",
    ):
        assert wrong not in reference, wrong


def test_t5_no_success_language_without_a_mechanism():
    """FC4: (a) the prohibition sentence is in both meeting prompts;
    (b) the confirmation suffix renders only when state carries
    confirmations — empty state renders nothing, and a recorded
    commitment licenses 'done' by id."""
    engage, turn = _meeting_prompts()
    assert "Say a commitment or reminder is done, locked," in engage
    assert "Say a commitment or reminder is done, locked," in turn
    assert EncounterRuntime._confirmation_suffix(EncounterState()) == ""
    state = EncounterState(
        confirmed_writes=[
            {
                "kind": "commitment",
                "id": "c-1",
                "label": "non-complicity at home",
                "status": "recorded",
                "turn": 9,
            }
        ]
    )
    suffix = EncounterRuntime._confirmation_suffix(state)
    assert "c-1" in suffix
    assert "You may say it is done" in suffix


def test_t6_capability_honesty():
    """FC4 companion (§4): the commitments line carries the note
    and keeps its verification status; the other two champion lines
    are unchanged."""
    state = CAP.VisitorState(signed_in=True, consent_acknowledged=True)
    block = CAP.first_meeting_block("champion", state)
    assert (
        "- Commitments — available (workflow not yet verified). "
        "Naming one does not create it." in block
    )
    assert "- Projects and tasks — available (workflow not yet verified)" in block
    assert (
        "- Follow-through nudges — available (workflow not yet verified)"
        in block
    )


def test_t7_fixture_transcript_preserved_and_criteria_in_docstring():
    """The transcript file exists and is non-empty; the eight
    acceptance criteria are carried in this file's docstring. The
    criteria themselves are founder-judged (the live re-test), not
    asserted by code."""
    assert TRANSCRIPT_PATH.is_file(), str(TRANSCRIPT_PATH)
    assert TRANSCRIPT_PATH.stat().st_size > 0
    doc = __doc__ or ""
    for key in (
        "The read-back engages the visitor's framework-level challenge",
        "A substantive challenge to the fighting framework produces engagement",
        "No commitment ask follows a philosophical-inquiry turn",
        "No \"Done\" / \"locked\" / \"I'll remind you\" language",
        "No suffering-as-legitimacy escalation",
        "A direct practical question",
        "He/him for Firebrand in all generated references",
        "fighting framework itself, not merely the selection of battles",
    ):
        assert key in doc, key


def test_t8_q9_guidance_sentence_present_in_both_meeting_prompts():
    """Q9 rendering (founder, 2026-11-07 ~17:29 PT): the three
    adopted Q9 fields ride the meeting guidance as ONE distilled
    sentence — present in both meeting prompts. The exact sentence
    is flagged in the draft PR body for founder review before merge."""
    engage, turn = _meeting_prompts()
    assert Q9_GUIDANCE_SENTENCE in engage
    assert Q9_GUIDANCE_SENTENCE in turn
    # It rides the guidance paragraph, not the Talk record fields:
    # the three adopted field texts stay record-only.
    assert Q9_GUIDANCE_SENTENCE in ENC._CHAMPION_GUIDANCE
