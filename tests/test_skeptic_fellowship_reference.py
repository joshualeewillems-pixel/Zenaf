"""Raven Fellowship reference, uncapped (six-seat Raven build,
2026-10-29). Mirrors tests/test_weaver_fellowship_reference.py
for the Skeptic. What this pins:

- The Raven's reference names all six other seats in his own
  perspective sketches (corrected doc §6, adapted — never copied
  from another seat's sketches), with friction intact and the
  closing mention / no-invented-memories lines.
- ARCHETYPAL INVARIANCE, SITUATIONAL ADAPTABILITY: he may
  recognize a conclusion is well supported, but never surrenders
  examination as his orienting principle.
- The shared doctrine rides from ONE common constant (naming
  three ways apart; no-arrangement) — not per-seat verbatim
  repetition — and the availability note is computed from the
  gates minus self, never a hardcoded snapshot.
- What the reference deliberately does NOT carry: no per-seat
  direct-question paragraph (direct-question precedence already
  rides shared move-branch machinery and the seat's guidance);
  no capability-slice section (the Raven's slice is PROPOSED,
  never decided, and slice content is not added here); no
  statement, hint, or scaffolding of his own blind spot (blind
  spots are the LAST REVEAL KEYSTONE — they show only implicitly).
- The capped frames do NOT carry the new material (budget
  safety), and no other seat gains a reference from this change.

No model calls anywhere.
"""

from __future__ import annotations

from local_ai.conversation import encounter as ENC
from local_ai.council import meetings as MT


def _skeptic_definition():
    return ENC.get_definition(MT.SKEPTIC_FIRST_MEETING)


def test_reference_names_all_six_other_seats_in_perspective():
    ref = _skeptic_definition().fellowship_reference
    assert ref, "Skeptic must carry a Fellowship reference"
    for role in ("Gardener", "Firebrand", "Bear", "Fox", "Crane", "Weaver"):
        assert role in ref, role
    # Sketches are perspective, not the drafting formula: no seat
    # is reduced to a balanced understand/misunderstand narration.
    assert "I understand" not in ref
    assert "I misunderstand" not in ref
    # Doc §6 voice: the question nobody in the room is asking,
    # marked in the margin.
    assert "the question nobody in the room is asking" in ref
    assert "mark it in the margin" in ref


def test_reference_is_not_merely_instrumental():
    ref = _skeptic_definition().fellowship_reference
    assert "affection, exasperation, curiosity, admiration" in ref
    assert "Never invent shared memories" in ref
    assert "a playful guess is a guess, not a fact" in ref


def test_archetypal_invariance_situational_adaptability():
    ref = _skeptic_definition().fellowship_reference
    # He may recognize a conclusion is well supported...
    assert "actually well supported" in ref
    assert "that is the best part of the work" in ref
    # ...but examination stays his orienting principle.
    assert "examination is not resistance to belief" in ref
    assert "a commitment to discovering what deserves belief" in ref
    assert "I change my mind when the evidence moves" in ref


def test_shared_doctrine_from_common_constant():
    ref = _skeptic_definition().fellowship_reference
    # The builder composes exactly the shared constant: the
    # reference contains it verbatim, and the constant is the
    # single source (not a per-seat rewrite).
    assert ENC._FELLOWSHIP_SHARED_DOCTRINE.strip() in ref
    assert "three ways apart" in ref
    assert "always sayable" in ref
    assert "answer with the role, never with a description alone" in ref
    assert "unlock only when you have met them" in ref
    assert "a third, separate state" in ref
    assert "You cannot arrange meetings with other seats" in ref
    assert "no such action exists" in ref
    assert "never offer to set one up" in ref


def test_no_per_seat_direct_question_paragraph():
    ref = _skeptic_definition().fellowship_reference
    # Direct-question precedence rides shared machinery, so the
    # reference carries no per-seat paragraph for it — while the
    # capped guidance still states answer-first for the seat.
    assert "A direct question comes first" not in ref
    assert "An impression never displaces an answer" not in ref
    definition = _skeptic_definition()
    assert "Answer a direct question first, in plain words" in (
        definition.turn_frame + definition.engage_frame
    )


def test_no_slice_content_and_no_blind_spot_disclosure():
    ref = _skeptic_definition().fellowship_reference
    # Slice PROPOSED, never decided: no slice section is added.
    assert "System slice" not in ref
    assert "PROPOSED" not in ref
    assert "never present it as decided" not in ref
    # Blind spots are the LAST REVEAL KEYSTONE: the reference
    # never states, hints, or scaffolds his own blind spot.
    assert "blind spot" not in ref.lower()
    assert "paralysis" not in ref
    assert "cynicism" not in ref


def test_availability_note_computed_from_gates_minus_self():
    ref = _skeptic_definition().fellowship_reference
    note = ref.splitlines()[-1]
    assert note.startswith("First-meeting openness right now")
    # Current gate truth, computed: Conductor open; Champion held;
    # Guardian/Maverick written-unreleased; Mentor/Ambassador
    # unregistered.
    assert "Gardener — not open to begin yet" in note
    assert "Firebrand — held, not open yet" in note
    assert "Bear — not open yet" in note
    assert "Fox — not open yet" in note
    assert "Crane — not open to begin yet" in note
    assert "Weaver — open now" in note
    # The note covers the other seats, not the Raven himself.
    assert "Raven —" not in note


def test_availability_note_recomputes_when_gates_change(monkeypatch):
    # Proof it is computed, not a hardcoded snapshot: registering
    # the Mentor's script (test-only, reverted after) moves the
    # Gardener from "not open to begin yet" to "not open yet".
    monkeypatch.setitem(MT.SCRIPTS, ("mentor", 1), MT.MENTOR_FIRST_MEETING)
    ref = _skeptic_definition().fellowship_reference
    note = ref.splitlines()[-1]
    assert "Gardener — not open yet" in note
    assert "Gardener — not open to begin yet" not in note


def test_new_material_not_in_capped_frames():
    definition = _skeptic_definition()
    for text in (definition.turn_frame, definition.engage_frame):
        assert "three ways apart" not in text
        assert "You cannot arrange meetings" not in text
        assert "First-meeting openness right now" not in text
        assert "mark it in the margin" not in text
    # Capped frames stay within the voice builder's budget.
    assert len(definition.engage_frame) <= 7700
    assert len(definition.turn_frame) < 8000


def test_other_seats_gain_no_reference():
    guardian = ENC.get_definition(MT.get_script("guardian", 1))
    assert guardian.fellowship_reference == ""
    # The Weaver's shipped reference is untouched by this PR.
    weaver = ENC.get_definition(MT.get_script("conductor", 1))
    assert "I understand him as the deepener of one thread" in (
        weaver.fellowship_reference
    )
