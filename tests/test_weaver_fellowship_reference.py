"""Weaver Fellowship reference, uncapped (no-scripting build, 2026-10-29).

The capped turn/engage frames have ~300 chars of headroom at build
time and less live, so the Weaver's richer relational knowledge,
naming clarification, and capability grounding ride the uncapped
meeting-scoped prompt section (`fellowship_reference`), which every
live generation carries — not the capped frames. What this pins:

- The Weaver's reference names all six other seats with an
  understanding AND a misunderstanding each (draft section (b),
  adapted — not the compressed one-liners, which stay capped).
- The naming three-way distinction is explicit: role labels are
  public and always sayable (especially on a direct request);
  personal names/faces unlock only on meeting; openness is a
  third, separate state.
- The no-arrangement rule is explicit: no such action exists.
- The availability note is computed from the static gates, so it
  stays true as gates change — and it currently reports the
  post-merge truth (Conductor open; the rest not open).
- The capped frames do NOT carry the new material (budget safety),
  and no other seat gains a reference from this change (the
  Guardian gains one later, in its own six-seat PR — see
  test_guardian_recognition_moment.py).
- The stale capabilities-registry line ("Only the Conductor's
  first meeting is scripted") is gone.

No model calls anywhere.
"""

from __future__ import annotations

from local_ai.conversation import encounter as ENC
from local_ai.council import capabilities as CAP
from local_ai.council import meetings as MT


def _weaver_definition():
    return ENC.get_definition(MT.get_script("conductor", 1))


def test_reference_names_all_six_with_understand_and_misunderstand():
    ref = _weaver_definition().fellowship_reference
    assert ref, "Weaver must carry a Fellowship reference"
    for role in ("Gardener", "Firebrand", "Bear", "Fox", "Crane", "Raven"):
        assert role in ref, role
    # Each sketch carries both sides of the pair (draft section (b)).
    assert ref.count("I understand") >= 6
    assert ref.count("I misunderstand") >= 6


def test_reference_is_not_merely_instrumental():
    ref = _weaver_definition().fellowship_reference
    assert "affection, exasperation, curiosity, admiration" in ref
    assert "Never invent shared memories" in ref
    assert "a playful guess is a guess, not a fact" in ref


def test_naming_three_way_distinction_explicit():
    ref = _weaver_definition().fellowship_reference
    assert "always sayable" in ref
    assert "answer with the role, never with a description alone" in ref
    assert "unlock only when you have met them" in ref
    assert "a third, separate state" in ref


def test_no_arrangement_rule_explicit():
    ref = _weaver_definition().fellowship_reference
    assert "You cannot arrange meetings with other seats" in ref
    assert "no such action exists" in ref
    assert "never offer to set one up" in ref


def test_direct_question_precedence_stated():
    ref = _weaver_definition().fellowship_reference
    assert "A direct question comes first" in ref
    assert "An impression never displaces an answer" in ref


def test_availability_note_computed_from_gates():
    ref = _weaver_definition().fellowship_reference
    note = ref.splitlines()[-1]
    assert note.startswith("First-meeting openness right now")
    # Post-merge truth: Conductor open (excluded — this is about the
    # other seats); Guardian written-unreleased; Champion held;
    # Maverick unreleased; Mentor/Ambassador/Skeptic unregistered.
    assert "Firebrand — held, not open yet" in note
    assert "Bear — not open yet" in note
    assert "Fox — not open yet" in note
    assert "Gardener — not open to begin yet" in note
    assert "Crane — not open to begin yet" in note
    assert "Raven — not open to begin yet" in note
    # The note covers the other seats, not the Weaver herself.
    assert "Weaver —" not in note


def test_new_material_not_in_capped_frames():
    definition = _weaver_definition()
    for text in (definition.turn_frame, definition.engage_frame):
        assert "three ways apart" not in text
        assert "You cannot arrange meetings" not in text
        assert "First-meeting openness right now" not in text
    # Capped frames byte-stable: the budget test's headroom stands.
    assert len(definition.engage_frame) == 6465
    assert len(definition.turn_frame) == 4992


def test_all_seats_carry_a_reference():
    # The six-seat build completed the set: every written seat now
    # carries a fellowship_reference. This guard inverts the old
    # no-reference guard — each six-seat merge removed its seat
    # from the empty set, and Bear's removes the last — so a rebase
    # that drops a seat's reference fails here instead of silently.
    for definition in (
        ENC.get_definition(MT.get_script("conductor", 1)),
        ENC.get_definition(MT.get_script("champion", 1)),
        ENC.get_definition(MT.get_script("guardian", 1)),
        ENC.get_definition(MT.get_script("maverick", 1)),
        ENC.get_definition(MT.MENTOR_FIRST_MEETING),
        ENC.get_definition(MT.AMBASSADOR_FIRST_MEETING),
        ENC.get_definition(MT.SKEPTIC_FIRST_MEETING),
    ):
        assert definition.fellowship_reference != ""


def test_capabilities_registry_line_no_longer_stale():
    first_meetings = next(
        c for c in CAP.CAPABILITIES if c.id == "first_meetings"
    )
    assert "Only the Conductor's first meeting is scripted" not in (
        first_meetings.prerequisite_note or ""
    )
    assert "only the Conductor's is open to begin right now" in (
        first_meetings.prerequisite_note or ""
    )
