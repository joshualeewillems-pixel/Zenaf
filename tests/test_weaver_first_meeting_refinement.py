"""Weaver first-meeting refinement (adopted baseline v3, 2026-10-28).

Prompt-local guidance, appended to the Weaver K1 definition's turn and
engage frames at build time — so it governs both live generation paths
(the conversational turn frame and the substantive engage frame) — and
to no other seat. The scripted opening, the three-intentions structure,
and the steward record source are untouched: the steward and rollback
turn frames remain identical twins, and the guidance applies identically
on both paths.

What this pins, per v3:
- Intention shift: meet / reveal personality / awaken curiosity;
  synthesis only if the visitor brings something suitable.
- Relationship-led introduction, emergent never a tour, by role for
  unmet seats, with the invented-history guardrail implied by the
  matrix-grounded framing (no invented incidents are invited anywhere).
- Tension-listening as an available relational framework: no compulsory
  classification; recognition is not assignment; evidence is not
  certainty; noticing is not speaking; the matrix is relational, not
  diagnostic.
- C38: a direct question is answered first, before interpretation.
- No orientation gate, no mode selection, no probe counting.
- Tree/capability wording limited to verified functionality: planned
  means planned; unverified workflows are never described as verified;
  the meeting itself is not a Tree record.
- Both composed generation paths stay under the voice builder's 8000
  character extra-instructions cap, so no frame is silently truncated.
"""

from __future__ import annotations

from local_ai.conversation import encounter as ENC
from local_ai.council import meetings as MT
from local_ai.council import steward_records as SR


def _weaver_definition():
    return ENC.get_definition(MT.get_script("conductor", 1))


# ---------------------------------------------------------------------------
# The guidance rides both live generation paths, Weaver K1 only.
# ---------------------------------------------------------------------------

def test_refinement_guidance_on_both_frames():
    definition = _weaver_definition()
    for name, text in (("turn", definition.turn_frame),
                       ("engage", definition.engage_frame)):
        assert "awaken curiosity about the Fellowship" in text, name
        assert "simply enjoy meeting someone new" in text, name
        assert "Never manufacture a problem" in text, name
        assert "never press for a tension" in text, name


def test_generic_definitions_carry_no_refinement():
    # build_definition is the generic path (and the Weaver builder's
    # base); only the authored Weaver K1 builder appends the guidance.
    generic = ENC.build_definition(MT.get_script("conductor", 1))
    assert "awaken curiosity about the Fellowship" not in generic.turn_frame
    assert "awaken curiosity about the Fellowship" not in generic.engage_frame


def test_steward_and_rollback_turn_frames_still_identical():
    # The refinement appends at definition build; it never edits the
    # GENERATED steward record or its rollback twin in encounter.py.
    assert SR.TURN_FRAME == ENC.WEAVER_TURN_FRAME


def test_opening_and_intentions_untouched():
    definition = _weaver_definition()
    assert definition.opening == MT.WEAVER_INTRODUCTION
    assert "Be yourself above all" in definition.turn_frame
    assert "intentions, not speeches" in definition.turn_frame
    assert "being yourself governs" in definition.turn_frame
    assert "never interrupt a meaningful exchange" in definition.turn_frame


# ---------------------------------------------------------------------------
# Relationship-led introduction: emergent, never a tour, by role.
# ---------------------------------------------------------------------------

def test_relationship_led_introduction():
    definition = _weaver_definition()
    for text in (definition.turn_frame, definition.engage_frame):
        assert "through your relationships with the other seats" in text
        assert "admiration and friction together" in text
        assert "never as a tour" in text
        assert "no checklist of seats" in text
        assert "no required order" in text
        assert "Refer to seats not yet met by role" in text
        assert "names come only after meeting" in text


# ---------------------------------------------------------------------------
# Tension-listening as an available framework, not classification.
# ---------------------------------------------------------------------------

def test_tension_listening_is_framework_not_classification():
    definition = _weaver_definition()
    for text in (definition.turn_frame, definition.engage_frame):
        assert "as an available framework, never a classification" in text
        assert "no pair assignment is required for any utterance" in text
        assert "Recognizing a resemblance is not assigning" in text
        assert "it does not establish certainty" in text
        assert "noticing something does not mean announcing it" in text
        assert "not diagnoses of the visitor" in text
        # No instruction-shaped failure mode: no mandatory per-turn
        # classification, no pair-hunt, no diagnostic conclusion.
        assert "before each response, classify" not in text
        assert "for every utterance, assign" not in text
        assert "conclude that the visitor has" not in text


def test_restraint_for_the_visitor_with_nothing_on_their_mind():
    # The adopted restraint test, as instruction: a visitor who is
    # simply enjoying the conversation must not trigger a
    # manufactured conflict or a pair-hunt.
    definition = _weaver_definition()
    for text in (definition.turn_frame, definition.engage_frame):
        assert "never treat a visitor with nothing on their mind" in text
        assert "as a failure to fix" in text


# ---------------------------------------------------------------------------
# C38, no gates, no counting.
# ---------------------------------------------------------------------------

def test_direct_answer_before_interpretation_no_gates_no_counting():
    definition = _weaver_definition()
    for text in (definition.turn_frame, definition.engage_frame):
        assert "Answer a direct question first, in plain words" in text
        assert "before any interpretation of it" in text
        assert "no orientation question to ask" in text
        assert "no mode to select" in text
        assert "never from counting probes or attempts" in text


# ---------------------------------------------------------------------------
# Tree / capability honesty, bounded to verified functionality.
# ---------------------------------------------------------------------------

def test_tree_and_capability_honesty():
    definition = _weaver_definition()
    for text in (definition.turn_frame, definition.engage_frame):
        assert "say only what the capability lines in this frame state" in text
        assert "planned means planned, never available" in text
        assert "never described as verified" in text
        assert "This conversation is not a Tree record" in text
        assert "it lives in its transcript and in the review queue" in text
        assert "teaching the Tree is not your job here" in text


# ---------------------------------------------------------------------------
# No per-generation duplicates; both composed paths fit the cap.
# ---------------------------------------------------------------------------

def test_no_per_generation_duplicates_with_refinement():
    # Extends the existing duplicate guard: the appended guidance
    # repeats none of the phrases counted once per path.
    definition = _weaver_definition()
    for name, text in (("turn", definition.turn_frame),
                       ("engage", definition.engage_frame)):
        low = text.lower()
        assert low.count("reveal your name yet") == 1, name
        assert low.count("think in music") == 1, name
        assert low.count("mime") == 1, name


def test_composed_frames_fit_the_voice_builder_cap():
    # reply.build_voice_prompt truncates extra_instructions at 8000
    # characters; a frame past the cap would corrupt the turn's
    # contract silently. Both composed runtime paths stay under it.
    definition = _weaver_definition()
    runtime = ENC.EncounterRuntime(definition)
    turn_frame, _cue = runtime._turn_frame(
        ENC.EncounterState(), "Hello.")
    assert len(turn_frame) < 8000
    engage_frame = definition.engage_frame
    engage_frame += "\n\n" + ENC._ZENAF_QUESTION_NOTE
    engage_frame += "\n\n" + ENC._naming_note(definition)
    if definition.capability_context:
        engage_frame += "\n\n" + definition.capability_context
    assert len(engage_frame) < 8000
