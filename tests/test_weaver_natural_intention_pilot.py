"""Track A pilot — prompt-only Weaver natural intention (weave rev2 §4.1).

Founder-authorized 2026-11-05: the founder's shared prompt (§3.3,
verbatim, 989 chars) + Weaver's per-seat line (§3.3, verbatim, 180
chars), combined 1,170 chars. Weaver (conductor) only, first meeting
+ ordinary Talk turns. No records, no new model calls, no evidence
changes, no other seat touched, no other prompt text changed.

What this pins:
- The two constants are the founder's verbatim text (lengths +
  start/end anchors for the shared prompt; the 180-char line in full).
- Meeting path: the pilot rides the uncapped fellowship-reference
  section of the Weaver K1 definition — NOT the capped turn/engage
  frames (engage frame stays 7,967 chars, 33 headroom, MIN_HEADROOM 30).
- Talk path: a Weaver Talk turn carries the pilot in
  extra_instructions; other seats' turns do not.
- No model calls anywhere: generation functions are capturing stubs.
"""

from __future__ import annotations

from local_ai.conversation import encounter as ENC
from local_ai.conversation.encounter import (
    _WEAVER_NATURAL_INTENTION,
    _WEAVER_NATURAL_INTENTION_LINE,
    _WEAVER_NATURAL_INTENTION_SHARED,
)
from local_ai.conversation.reply import (
    _EXTRA_INSTRUCTIONS_CAP,
    build_voice_prompt,
)
from local_ai.conversation.service import ConversationService
from local_ai.conversation.store import ConversationStore
from local_ai.council import meetings as MT

SHARED_START = "You have interests, convictions, and fascinations of your own."
SHARED_END = "not something you must accomplish in every conversation."

WEAVER_LINE = (
    "What excites you is how parts fit — the moment a thread, "
    "followed, composes something. Name the connection: what the "
    "arrangement makes possible that the ingredients alone couldn't."
)


def test_pilot_text_is_the_founders_verbatim():
    """The two insertions are the rev2 §3.3 text, copied not paraphrased."""
    assert len(_WEAVER_NATURAL_INTENTION_SHARED) == 989
    assert _WEAVER_NATURAL_INTENTION_SHARED.startswith(SHARED_START)
    assert _WEAVER_NATURAL_INTENTION_SHARED.endswith(SHARED_END)
    assert _WEAVER_NATURAL_INTENTION_LINE == WEAVER_LINE
    assert len(_WEAVER_NATURAL_INTENTION_LINE) == 180
    assert len(_WEAVER_NATURAL_INTENTION) == 1170
    assert _WEAVER_NATURAL_INTENTION == (
        _WEAVER_NATURAL_INTENTION_SHARED + "\n" + _WEAVER_NATURAL_INTENTION_LINE
    )


def _weaver_definition():
    return ENC.get_definition(MT.get_script("conductor", 1))


def test_meeting_path_pilot_rides_the_uncapped_reference():
    """Weaver K1: pilot inside fellowship_reference, frames untouched."""
    definition = _weaver_definition()
    reference = definition.fellowship_reference
    assert _WEAVER_NATURAL_INTENTION in reference
    # The old reference is intact ahead of it (prefix, not rewritten),
    # and the availability note stays the section's last line.
    assert reference.startswith(
        "Fellowship reference — how you know the other seats."
    )
    assert "First-meeting openness right now" in reference
    assert reference.splitlines()[-1].startswith("First-meeting openness right now")
    # Capped frames: byte-identical budget to before the pilot.
    # Engage frame 8,347 chars, 653 headroom vs the 9,000 cap
    # (MIN_HEADROOM 30, test_conductor_agency_refinement.py).
    # Re-measured 2026-11-06: the read-back frames lengthened the
    # engage frame (was 7,967) and the cap rose 8000 -> 9000.
    # Re-measured 2026-11-07 (Gardener S1, G4/D1): the engage frame
    # is 28 chars shorter — the "Shadow: forcing resolution." slice
    # line was removed (27 chars + newline); the four pronoun swaps
    # in the frame net to zero. Not a pilot change: the pilot text
    # still rides only the uncapped reference.
    runtime = ENC.EncounterRuntime(definition)
    turn_frame, _cue = runtime._turn_frame(ENC.EncounterState(), "Hello.")
    engage_frame = definition.engage_frame
    engage_frame += "\n\n" + ENC._ZENAF_QUESTION_NOTE
    engage_frame += "\n\n" + ENC._naming_note(definition)
    if definition.capability_context:
        engage_frame += "\n\n" + definition.capability_context
    assert len(engage_frame) == 8347
    assert _EXTRA_INSTRUCTIONS_CAP - len(engage_frame) >= 30
    assert _EXTRA_INSTRUCTIONS_CAP - len(turn_frame) >= 30
    assert _WEAVER_NATURAL_INTENTION not in turn_frame
    assert _WEAVER_NATURAL_INTENTION not in engage_frame
    # Pinned render: the assembled meeting prompt carries it verbatim.
    lines, _ = build_voice_prompt(
        "u1", "conductor", "hello", [],
        extra_instructions=turn_frame, fellowship_reference=reference,
    )
    assert _WEAVER_NATURAL_INTENTION in "\n".join(lines)


def test_other_seats_meeting_definitions_carry_no_pilot():
    """No other seat's first meeting gets the pilot."""
    for arch_id in ("mentor", "ambassador", "guardian", "skeptic", "maverick", "champion"):
        definition = ENC.get_definition(MT.get_script(arch_id, 1))
        assert _WEAVER_NATURAL_INTENTION not in definition.fellowship_reference, arch_id


def test_talk_path_weaver_carries_pilot_other_seats_do_not(tmp_path):
    """ConversationService.turn: Weaver Talk turns carry the pilot; others don't."""
    seen: list[str] = []

    def _capture(prompt: str, **kwargs) -> str:
        seen.append(prompt)
        return "Fake reply."

    store = ConversationStore(db_path=tmp_path / "conv.db")
    try:
        svc = ConversationService(store, generate_fn=_capture)
        svc.turn(
            "u1", "conductor", "I built a filtration device.",
            conversation_id="talk-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
        assert len(seen) == 1
        assert _WEAVER_NATURAL_INTENTION in seen[0]
        svc.turn(
            "u1", "mentor", "I built a filtration device.",
            conversation_id="talk-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        )
        assert len(seen) == 2
        assert _WEAVER_NATURAL_INTENTION not in seen[1]
    finally:
        store.close()


def test_talk_pilot_fits_the_extra_instructions_cap():
    """Pilot alone: 1,170 chars, headroom under the extra-instructions cap."""
    lines, _ = build_voice_prompt(
        "u1", "conductor", "hello", [], extra_instructions=_WEAVER_NATURAL_INTENTION,
    )
    assert _WEAVER_NATURAL_INTENTION in "\n".join(lines)
    assert len(_WEAVER_NATURAL_INTENTION) == 1170
    assert _EXTRA_INSTRUCTIONS_CAP - len(_WEAVER_NATURAL_INTENTION) == 7830
