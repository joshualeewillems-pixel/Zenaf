"""Crane (Ambassador) Fellowship reference, uncapped (six-seat
relational references, 2026-10-29 — Crane PR, mirroring the Weaver
fellowship-reference suite). What this pins:

- The Crane's reference names all six other seats from her own side
  of her pairs (comparison DRAFT §5, adapted — not the compressed
  one-liners, which stay capped in the orientation slice).
- Dwell-on-one-person is a TENDENCY of attention, never a quota (C2).
- The Weaver–Ambassador disagreement is carried on the Crane's side
  ONLY here (C3): her line is that a place isn't the same as
  belonging, neither side concedes — and the line does NOT leak
  into the Weaver's shipped reference (the Weaver-side addition is
  explicitly not part of this PR).
- Shared doctrine rides one common constant: naming three ways
  apart + the no-arrangement rule. There is NO per-seat
  direct-question paragraph: direct-question precedence is already
  shared runtime machinery (see test_crane_recognition_moment.py).
- NO capability slice content in the reference (G5: only Guardian
  and Champion slices are decided; the Crane's slice is proposed
  and lives only in the prompt-local guidance, marked proposed).
- NO blind-spot statement, hint, or scaffolding: the Crane's own
  blind spot is the last reveal keystone and shows only implicitly.
- NO invented shared histories (Revision 2): attitudes only, never
  fabricated past-interaction framings.
- The availability note is COMPUTED from the gates minus self, not
  a hardcoded snapshot of the doc's gate table — and the
  parameterized form reproduces the Weaver's note exactly for
  exclude="conductor" (the Weaver's own function is untouched).
- The new material rides the uncapped section, NOT the capped
  frames, and no other seat gains a reference from this change.

No model calls anywhere.
"""

from __future__ import annotations

from local_ai.conversation import encounter as ENC
from local_ai.council import meetings as MT


def _crane_definition():
    return ENC.get_definition(MT.AMBASSADOR_FIRST_MEETING)


def test_reference_names_all_six_other_seats():
    ref = _crane_definition().fellowship_reference
    assert ref, "Crane must carry a Fellowship reference"
    for header in (
        "- Gardener (Mentor):",
        "- Firebrand (Champion):",
        "- Bear (Guardian):",
        "- Fox (Maverick):",
        "- Weaver (Conductor):",
        "- Raven (Skeptic):",
    ):
        assert header in ref, header


def test_reference_is_not_merely_instrumental():
    ref = _crane_definition().fellowship_reference
    assert "affection, exasperation, curiosity, admiration" in ref
    assert "Never invent shared memories" in ref
    assert "a playful guess is a guess, not a fact" in ref


def test_dwell_is_a_tendency_never_a_quota():
    ref = _crane_definition().fellowship_reference
    assert "I tend to dwell on one person at a time" in ref
    assert "That is a tendency of attention, not a rule" in ref
    assert "I can speak of several when the meeting calls for it" in ref


def test_c3_disagreement_carried_on_crane_side_only():
    ref = _crane_definition().fellowship_reference
    assert "a place isn't the same as belonging" in ref
    assert "a group can function beautifully while its members feel profoundly alienated" in ref
    assert "Neither of us has moved, and that's the point." in ref
    # One-sided scope: the Weaver's shipped reference carries no
    # Crane-side C3 line, and her Crane sketch is unchanged.
    weaver_ref = ENC.get_definition(MT.get_script("conductor", 1)).fellowship_reference
    assert "a place isn't the same as belonging" not in weaver_ref
    assert "I understand her as the unifier of people by translation" in weaver_ref


def test_shared_doctrine_naming_and_no_arrangement():
    ref = _crane_definition().fellowship_reference
    assert "always sayable" in ref
    assert "answer with the role, never with a description alone" in ref
    assert "unlock only when you have met them" in ref
    assert "a third, separate state" in ref
    assert "You cannot arrange meetings with other seats" in ref
    assert "no such action exists" in ref
    assert "never offer to set one up" in ref
    # The shared constant is the single source for this content.
    assert ENC._FELLOWSHIP_SHARED_DOCTRINE in ref


def test_no_per_seat_direct_question_paragraph():
    # Direct-question precedence is shared runtime machinery
    # (_DIRECT_QUESTION_PRECEDENCE, appended on direct-question
    # turns for every seat), so the Crane's reference carries no
    # per-seat paragraph for it — unlike the Weaver's shipped
    # reference, which keeps its own.
    ref = _crane_definition().fellowship_reference
    assert "A direct question comes first" not in ref
    assert "An impression never displaces an answer" not in ref
    assert ENC._DIRECT_QUESTION_PRECEDENCE  # the shared machinery exists


def test_no_capability_slice_content_in_reference():
    # G5: the Crane's slice is PROPOSED, never decided — and this
    # PR adds no slice content to the reference at all.
    ref = _crane_definition().fellowship_reference
    assert "how perspectives meet" not in ref
    assert "PROPOSED" not in ref


def test_no_blind_spot_statement_or_scaffolding():
    ref = _crane_definition().fellowship_reference
    for phrase in ("my blind spot", "my shadow", "I appease",
                   "I am appeasing", "my appeasement"):
        assert phrase not in ref, phrase


def test_no_invented_shared_histories():
    ref = _crane_definition().fellowship_reference
    for phrase in ("shown me", "I used to", "I've learned",
                   "these days", "still learning"):
        assert phrase not in ref, phrase


def test_availability_note_computed_from_gates_minus_self():
    ref = _crane_definition().fellowship_reference
    note = ref.split("First-meeting openness right now")[-1]
    # All-six release truth, computed: every other seat open now.
    assert "Firebrand — open now" in note
    assert "Bear — open now" in note
    assert "Fox — open now" in note
    assert "Gardener — open now" in note
    assert "Weaver — open now" in note
    assert "Raven — open now" in note
    # The note covers the other seats, not the Crane herself.
    assert "Crane —" not in note


def test_availability_note_is_computed_not_hardcoded(monkeypatch):
    # Releasing the Guardian in the test-only gate view moves the
    # note — proof it is computed at build, not a doc snapshot.
    monkeypatch.setattr(
        MT, "RELEASED_FIRST_MEETING_SEATS",
        MT.RELEASED_FIRST_MEETING_SEATS | {"guardian"},
    )
    ref = _crane_definition().fellowship_reference
    assert "Bear — open now" in ref


def test_parameterized_note_reproduces_weaver_note():
    # The Weaver's own function is untouched; the parameterized
    # form agrees with it exactly for exclude="conductor".
    assert (
        ENC._fellowship_availability_note("conductor")
        == ENC._weaver_availability_note()
    )


def test_new_material_not_in_capped_frames():
    definition = _crane_definition()
    for text in (definition.turn_frame, definition.engage_frame):
        assert "I tend to dwell on one person at a time" not in text
        assert "a place isn't the same as belonging" not in text
        assert "First-meeting openness right now" not in text
        assert "three ways apart" not in text
        assert "You cannot arrange meetings" not in text


def test_other_seats_carry_their_own_references():
    # All-seven references (all-six release): the Guardian's
    # definition carries its OWN reference — the note line equals
    # the Guardian's own computed note, so a leak from another
    # seat's builder would fail here. (Previously the Guardian had
    # no reference; the six-seat merges gave it its own.)
    guardian = ENC.get_definition(MT.get_script("guardian", 1))
    assert guardian.fellowship_reference != ""
    assert ENC._fellowship_availability_note("guardian") in guardian.fellowship_reference
    generic = ENC.build_definition(MT.AMBASSADOR_FIRST_MEETING)
    assert generic.fellowship_reference == ""
