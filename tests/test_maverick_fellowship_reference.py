"""Maverick Fellowship reference, uncapped (six-seat references,
2026-10-29). Mirrors the Weaver reference suite, for the Fox.

What this pins:

- The Fox's reference names all six other seats in his own voice,
  adapted from §3 of the six-seat relational references comparison
  DRAFT, Revision 2 corrected text (the working baseline — NOT
  canonical: Joshua's voice correction for this section is still
  pending, flagged in the PR body, and no voice change is invented
  here).
- Shared doctrine rides the ONE common constant
  (_FELLOWSHIP_SHARED_DOCTRINE: naming + no-arrangement),
  composed at build time — no per-seat direct-question paragraph,
  because direct-question precedence is already shared move-branch
  machinery (the frames still carry direct-answer-first).
- The availability note is computed from the static gates, minus
  self — never the doc's gate snapshot hardcoded — and currently
  reports the post-merge truth (Weaver open; the rest not open).
- The reference states NO capability slice: the Fox's slice
  (unchosen rules/untried routes) is PROPOSED, never decided,
  and slice content does not appear here.
- The Fox's own blind spot is never stated, hinted, or scaffolded
  (LAST REVEAL KEYSTONE): it shows only implicitly. No
  self-diagnosis language appears.
- ARCHETYPAL INVARIANCE, SITUATIONAL ADAPTABILITY: he may
  recognize a structure is useful but never surrenders
  questioning constraining assumptions as his orienting
  principle.
- The capped frames do NOT carry the new material (budget safety),
  no other seat gains a reference from this change, and the
  Weaver's shipped reference is untouched (her inline text, not
  the shared constant).

No model calls anywhere.
"""

from __future__ import annotations

from local_ai.conversation import encounter as ENC
from local_ai.council import meetings as MT


def _maverick_definition():
    return ENC.get_definition(MT.get_script("maverick", 1))


def test_reference_names_all_six_in_fox_voice():
    ref = _maverick_definition().fellowship_reference
    assert ref, "Maverick must carry a Fellowship reference"
    for role in ("Gardener", "Firebrand", "Bear", "Crane", "Weaver", "Raven"):
        assert role in ref, role
    # Sketches from the corrected doc, in his voice.
    assert "a different kind of experiment" in ref  # Gardener
    assert "We're both probably right, on different days" in ref  # Firebrand
    assert "Fair trade, mostly" in ref  # Bear
    assert "I'm still testing whether that's true" in ref  # Crane
    assert "where arrangement ends and cage begins" in ref  # Weaver
    assert "allergic to beginnings" in ref  # Raven
    # The orienting question, not an escape hatch.
    assert "what else we might build here" in ref
    assert "including the freedom to stay" in ref


def test_reference_is_not_merely_instrumental():
    ref = _maverick_definition().fellowship_reference
    assert "affection, exasperation, curiosity, admiration" in ref
    assert "Never invent shared memories" in ref
    assert "a playful guess is a guess, not a fact" in ref


def test_shared_doctrine_composed_from_one_common_constant():
    definition = _maverick_definition()
    ref = definition.fellowship_reference
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


def test_no_per_seat_direct_question_paragraph_in_reference():
    # Direct-question precedence is shared move-branch machinery;
    # the reference carries no DQ paragraph of its own. The frames
    # still carry direct-answer-first (pre-existing guidance).
    ref = _maverick_definition().fellowship_reference
    assert "A direct question comes first" not in ref
    assert "An impression never displaces an answer" not in ref
    definition = _maverick_definition()
    assert "Answer a direct question first, in plain words" in definition.turn_frame
    assert "Answer a direct question first, in plain words" in definition.engage_frame


def test_availability_note_computed_from_gates_minus_self():
    ref = _maverick_definition().fellowship_reference
    note = ref.splitlines()[-1]
    assert note.startswith("First-meeting openness right now")
    # Post-merge truth, computed — not the doc's snapshot pasted in:
    # Weaver open; Firebrand held; Bear unreleased; Gardener, Crane,
    # Raven unregistered.
    assert "Gardener — not open to begin yet" in note
    assert "Firebrand — held, not open yet" in note
    assert "Bear — not open yet" in note
    assert "Crane — not open to begin yet" in note
    assert "Weaver — open now" in note
    assert "Raven — not open to begin yet" in note
    # The note covers the other seats, not the Fox himself.
    assert "Fox —" not in note
    # And it is the computed function, not a pasted string: the
    # builder's note equals the helper's output for this seat.
    assert note == ENC._fellowship_availability_note("maverick").splitlines()[-1]


def test_no_slice_content_in_reference():
    # The Fox's slice is PROPOSED (not decided) and never appears
    # in this reference — neither as a decided mapping nor as
    # slice prose.
    ref = _maverick_definition().fellowship_reference
    assert "System slice" not in ref
    assert "unchosen rules" not in ref
    assert "untried routes" not in ref


def test_blind_spot_never_stated_hinted_or_scaffolded():
    # LAST REVEAL KEYSTONE: no self-diagnosis, no blind-spot
    # language, no shadow label applied to himself.
    ref = _maverick_definition().fellowship_reference
    assert "blind spot" not in ref
    assert "contrarian" not in ref
    assert "my shadow" not in ref.lower()


def test_archetypal_invariance_questioning_stance_kept():
    # He may recognize a structure is useful; he never surrenders
    # questioning constraining assumptions as his principle.
    ref = _maverick_definition().fellowship_reference
    assert "I push at the arrangement first" in ref
    assert "I notice the assumptions nobody remembers agreeing to" in ref


def test_new_material_not_in_capped_frames():
    definition = _maverick_definition()
    for text in (definition.turn_frame, definition.engage_frame):
        assert "where arrangement ends and cage begins" not in text
        assert "You cannot arrange meetings" not in text
        assert "First-meeting openness right now" not in text
        assert "a different kind of experiment" not in text


def test_other_seats_gain_no_reference_and_weaver_untouched():
    guardian = ENC.get_definition(MT.get_script("guardian", 1))
    assert guardian.fellowship_reference == ""
    # The Weaver's builder still uses her inline text, not the
    # shared constant — her shipped reference is byte-stable
    # under this PR (her self-excluding role list stands).
    weaver = ENC.get_definition(MT.get_script("conductor", 1))
    assert ENC._FELLOWSHIP_SHARED_DOCTRINE not in weaver.fellowship_reference
    assert "Gardener, Firebrand, Bear, Fox, Crane, Raven" in weaver.fellowship_reference
    assert weaver.fellowship_reference.splitlines()[-1] == (
        ENC._weaver_availability_note()
    )
