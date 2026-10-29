"""Champion (Firebrand) Fellowship reference, uncapped (six-seat
references, 2026-10-29) — mirrors tests/test_weaver_fellowship_reference.py.

The capped turn/engage frames keep only the prompt-local guidance,
so the Firebrand's richer relational knowledge, the shared doctrine,
and the availability note ride the uncapped meeting-scoped prompt
section (`fellowship_reference`), which every live generation
carries — not the capped frames. What this pins:

- The reference carries all six other seats as perspective sketches
  adapted from the corrected doc's Firebrand section (§2, Revision 2)
  — live disagreement, never a resolved self-diagnosis — plus the
  mention line (affection, exasperation, curiosity, admiration) and
  the never-invent-shared-memories rule.
- The shared doctrine rides as ONE common constant composed at build
  time: naming three ways apart, and the no-arrangement rule.
- Direct-question precedence has NO per-seat paragraph here: it is
  already shared machinery (the move-branch constant, applied to
  every seat), and the turn frame already carries it — so the
  reference does not repeat it.
- The availability note is computed from the static gates, minus
  self, so it stays true as gates change — and it currently reports
  the post-merge truth (Conductor open; the rest not open).
- No capability-slice content rides this reference, and no
  blind-spot disclosure: the blind spot is the LAST REVEAL KEYSTONE,
  never stated, hinted, or scaffolded here.
- The capped frames do NOT carry the new material, and no other
  seat gains a reference from this change; the Weaver's shipped
  reference is untouched.

No model calls anywhere.
"""

from __future__ import annotations

from local_ai.conversation import encounter as ENC
from local_ai.council import meetings as MT


def _champion_definition():
    return ENC.get_definition(MT.get_script("champion", 1))


def test_reference_names_all_six_other_seats_as_sketches():
    ref = _champion_definition().fellowship_reference
    assert ref, "Champion must carry a Fellowship reference"
    for role in ("Gardener", "Bear", "Fox", "Crane", "Weaver", "Raven"):
        assert role in ref, role
    # Sketches adapted from the corrected doc §2, in her voice.
    assert "I notice the hill, the price" in ref
    assert "another season\" is a hill going untaken" in ref
    assert "He keeps the ledger of what must survive" in ref
    assert "I break for a cause; he breaks from a frame" in ref
    assert "the disagreement is live" in ref
    assert "I still name the side first. She still asks what it needs" in ref
    assert "Neither of us has conceded" in ref
    assert "I want the bold version today; she wants it to survive the week" in ref
    assert "He checks the conviction; the decision stays mine" in ref


def test_reference_is_not_merely_instrumental():
    ref = _champion_definition().fellowship_reference
    assert "affection, exasperation, curiosity, admiration" in ref
    assert "Never invent shared memories" in ref
    assert "a playful guess is a guess, not a fact" in ref


def test_shared_doctrine_composed_from_one_common_constant():
    definition = _champion_definition()
    ref = definition.fellowship_reference
    # Build-time composition from the single shared source.
    assert ENC._FELLOWSHIP_SHARED_DOCTRINE in ref
    # Naming, three ways apart.
    assert "always sayable" in ref
    assert "answer with the role, never with a description alone" in ref
    assert "unlock only when you have met them" in ref
    assert "a third, separate state" in ref
    # No-arrangement rule.
    assert "You cannot arrange meetings with other seats" in ref
    assert "no such action exists" in ref
    assert "never offer to set one up" in ref


def test_no_per_seat_direct_question_paragraph():
    ref = _champion_definition().fellowship_reference
    # Precedence is shared machinery (the move-branch constant),
    # not a paragraph repeated per seat.
    assert "A direct question comes first" not in ref
    assert "An impression never displaces an answer" not in ref
    # ...but the turn frame still carries it, so the behavior stands.
    assert "Answer a direct question first, in plain words" in (
        _champion_definition().turn_frame
    )


def test_availability_note_computed_from_gates_minus_self():
    ref = _champion_definition().fellowship_reference
    note = ref.splitlines()[-1]
    assert note.startswith("First-meeting openness right now")
    # Post-merge truth: Conductor open; Guardian/Maverick written
    # but unreleased; Mentor/Ambassador/Skeptic unregistered.
    assert "Gardener — not open to begin yet" in note
    assert "Bear — not open yet" in note
    assert "Fox — not open yet" in note
    assert "Crane — not open to begin yet" in note
    assert "Weaver — open now" in note
    assert "Raven — not open to begin yet" in note
    # The note covers the other seats, not the Firebrand herself.
    assert "Firebrand —" not in note
    # And it is the computed function, not a pasted snapshot.
    assert note == ENC._fellowship_availability_note("champion")


def test_availability_note_recomputes_when_gates_change(monkeypatch):
    # Release the Guardian in-process only: the note must follow
    # the gates, proving it is computed at build time.
    monkeypatch.setattr(
        MT, "RELEASED_FIRST_MEETING_SEATS",
        frozenset({"conductor", "guardian"}),
    )
    ref = ENC.get_definition(MT.get_script("champion", 1)).fellowship_reference
    assert "Bear — open now" in ref.splitlines()[-1]


def test_no_slice_content_and_no_blind_spot_disclosure():
    ref = _champion_definition().fellowship_reference
    # Slices do not appear in these references at all.
    assert "vision execution" not in ref
    # The blind spot is the LAST REVEAL KEYSTONE: never stated,
    # hinted, or scaffolded — the code-context shadow stays out.
    assert "martyrdom" not in ref
    assert "Shadow" not in ref


def test_new_material_not_in_capped_frames():
    definition = _champion_definition()
    for text in (definition.turn_frame, definition.engage_frame):
        assert "three ways apart" not in text
        assert "You cannot arrange meetings" not in text
        assert "First-meeting openness right now" not in text
        assert "I break for a cause; he breaks from a frame" not in text
    # Capped frames byte-stable under the budget test's headroom.
    assert len(definition.engage_frame) < 8000
    assert 8000 - len(definition.engage_frame) >= 300
    assert len(definition.turn_frame) < 8000
    assert 8000 - len(definition.turn_frame) >= 300


def test_other_seats_gain_no_reference_and_weaver_untouched():
    # Registered seats with builders of their own gain nothing here.
    # Mentor, Ambassador, and Skeptic are unregistered (get_script
    # is None), so no definition exists that could carry one.
    for arch_id in ("guardian", "maverick"):
        definition = ENC.get_definition(MT.get_script(arch_id, 1))
        assert definition.fellowship_reference == "", arch_id
    # The Weaver's shipped reference is untouched by this PR.
    weaver = ENC.get_definition(MT.get_script("conductor", 1))
    assert "I understand her as the decisive actor" in (
        weaver.fellowship_reference
    )
    assert weaver.fellowship_reference.splitlines()[-1].startswith(
        "First-meeting openness right now"
    )
