"""The Guardian's (Bear's) first meeting — script, frames, and release gate.

Guardian K1 is the second written first meeting (the Weaver's is the
template) and the first written under the Fellowship conversational-
agency build: prompt-control cleanup in the Weaver pattern, the
orientation draft's reference slice embedded prompt-locally (Weaver
#252 pattern — NOT the shared uncapped section, which is unmerged
PR #255), and a release gate proving BUILDING IS NOT AVAILABILITY:
the script exists, the meeting is still not visitor-accessible.

What this file pins, and why each pin exists:
  - The script exists with the right seat / character / demeanor
    (character and demeanor verbatim from keystones.py seed data),
    a four-bubble opening that does NOT reveal the name, an empty
    question bank (the Weaver pattern: the authored opening is
    delivered whole), and exactly ONE reveal — no reveal variants
    (removed by the approved corrections).
  - Every integrity invariant, verbatim, somewhere on the generation
    path: naming by role until met, direct-answer-first, the honesty
    guard, grounding only in substantive material, reveal timing
    ("Do not reveal your name yet"), no invented training, the
    recognition note (a first impression is a proposal, never a
    filed claim), and the parser contract (the --- delimiter in the
    engage frame, the Strands bookkeeping line in the read-back).
  - The prompt-control cleanup: permission plus judgment-based
    yielding (never a prescribed yield procedure), the no-checklist
    principle in its exact sentence, and the read-back unmandated
    (the engage glue permits, never demands, an impression).
  - The reference slice present on BOTH live generation paths
    (turn frame and engage frame), in all three dimensions, and
    absent from the Weaver's definition (no cross-seat leakage).
  - The release gate: a seeded visitor whose Weaver K1 is complete
    — the exact visitor for whom script existence alone WOULD have
    opened the meeting under the old rules — is still refused, and
    no meeting row, transcript, or generation can result.
  - The frame budget, measured, not claimed: the composed engage
    and turn frames fit the live 8,000-char frame cap (reply.py)
    with at least 300 chars headroom, in the default, worst-case
    capability, and fully-met naming variants — so the honesty
    guard (the capability block's last line) is never truncated.
  - No steward wiring: the Guardian definition reads nothing from
    the steward module (steward consolidation was Weaver-only).
"""

from __future__ import annotations

import dataclasses
import threading

import pytest

from local_ai.conversation import encounter as ENC
from local_ai.conversation.encounter import (
    EncounterRuntime,
    EncounterState,
    _naming_note,
    _ZENAF_QUESTION_NOTE,
    split_strands_trailer,
)
from local_ai.conversation.meeting import (
    MeetingError,
    MeetingService,
    MeetingStore,
)
from local_ai.conversation.store import ConversationStore
from local_ai.council import capabilities as CAP
from local_ai.council import meetings as MT
from local_ai.vision_execution import keystone_seeding
from local_ai.vision_execution import service as ve
from local_ai.vision_execution.models import TaskUpdate


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    """Isolate the vision-execution SQLite DB per test (test_meetings pattern)."""
    import local_ai.vision_execution.storage as ve_store

    monkeypatch.setattr(ve_store, "_DB_PATH", tmp_path / "ve.db")
    monkeypatch.setattr(ve_store, "_DB_DIR", tmp_path)
    monkeypatch.setattr(ve_store, "_init_done_paths", set())
    monkeypatch.setattr(ve_store, "_thread_local", threading.local())
    return {}


def _svc(tmp_path):
    return MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
    )


def _seeded_user(email="guardian@example.com"):
    user = ve.create_user_account(email, "pw", "Guard")
    keystone_seeding.seed_meet_your_council(user["id"])
    return user["id"]


def _complete_conductor_k1(uid):
    from local_ai.conversation.meeting import _seat_keystone_tasks

    tasks = _seat_keystone_tasks(uid, "conductor")
    assert tasks, "seeded user has no conductor keystone tasks"
    ve.update_task(tasks[0]["id"], TaskUpdate(status="Done"), uid)
    assert _seat_keystone_tasks(uid, "conductor")[0]["status"] == "Done"


# ------------------------------------------------------------------ script


def test_guardian_script_exists_with_canonical_identity():
    script = MT.get_script("guardian", 1)
    assert script is not None
    assert MT.has_script("guardian", 1)
    assert script.archetype_id == "guardian"
    assert script.character == "Bear"
    # Demeanor verbatim from the keystones.py seed data.
    assert script.demeanor == (
        "Steady, sheltering; slow to move, impossible to move once moved."
    )
    assert script.keystone_index == 1


def test_guardian_opening_is_four_bubbles_and_names_nobody():
    script = MT.get_script("guardian", 1)
    assert len(script.opening) == 4
    opening_text = "\n".join(script.opening)
    # Introductions are earned, not announced: the opening carries
    # the door, the winter stores, and his standing question — never
    # the name or the role.
    assert "Bear" not in opening_text
    assert "Guardian" not in opening_text
    assert "What must be protected" in opening_text or "what must be protected" in opening_text
    # The Weaver pattern in kind: no question bank to work through.
    assert script.questions == ()


def test_guardian_reveal_is_single_and_names_him():
    script = MT.get_script("guardian", 1)
    # ONE reveal, the existing ceremony — no variants, no variant fields.
    assert len(script.reveal) == 3
    reveal_text = "\n".join(script.reveal)
    assert "I'm the Bear" in reveal_text
    assert "steady and sheltering" in reveal_text
    # The reveal closes with an invitation, not a completion declaration.
    assert "come back" in reveal_text
    # No motto, no flaw in the reveal (those ride elsewhere / later).
    assert "smothering" not in reveal_text.lower()


def test_guardian_orientation_settles_the_weaver_debt():
    """The Weaver's guardian allusion (locks she didn't put there, a
    kept door) is honored from the Bear's side: his keeping, shown
    as his own — and the orientation frame disciplines answers to
    the place notes only."""
    script = MT.get_script("guardian", 1)
    assert script.orientation, "orientation context paragraphs required"
    orientation_text = "\n".join(script.orientation)
    assert "kept, not hidden" in orientation_text
    assert "locks I put there" in orientation_text
    assert "say so plainly rather than inventing" in script.orientation_frame
    assert "locks you put there" in script.orientation_facts
    assert "checked twice" in script.orientation_facts


# ------------------------------------------------------- integrity invariants


# Invariants verbatim, and where each must appear on the path.
INVARIANTS = [
    # Naming: roles until met (guidance; the runtime's naming note
    # carries the per-visitor met list beside it).
    ("Refer to seats not yet met by role", "guidance"),
    # Direct-answer-first.
    ("Answer a direct question first, in plain words, before any interpretation of it.", "guidance"),
    # Reveal timing (every generation frame).
    ("Do not reveal your name yet.", "frames"),
    # Grounding: substantive material only.
    ("Ground the impression ONLY in their substantive material", "readback"),
    # No invented training.
    ("Never invent training they don't have", "readback"),
    # Recognition note: proposal, never a filed claim.
    ("A first impression is a proposal, never a filed claim", "readback"),
    # No-checklist principle, exact sentence.
    ("Don't reduce your friends to a feature checklist.", "guidance"),
]


def test_integrity_invariants_present_verbatim():
    script = MT.get_script("guardian", 1)
    definition = ENC.get_definition(script)
    frames = definition.turn_frame + "\n" + definition.engage_frame
    for text, where in INVARIANTS:
        if where == "guidance":
            assert text in ENC._GUARDIAN_FIRST_MEETING_GUIDANCE, text
        elif where == "readback":
            assert text in script.readback_frame, text
        else:
            assert text in frames, text
    # The honesty guard rides the capability block (last line), which
    # the runtime appends to both composed frames — asserted with the
    # budget test below, where the composed frames are built.
    assert CAP.HONESTY_GUARD in CAP.first_meeting_block(
        "guardian", CAP.VisitorState()
    )


def test_prompt_control_cleanup_is_permission_not_procedure():
    """Yielding is judgment-based: the guidance permits volunteering
    and requires yielding, and prescribes NO yield procedure — no
    step list, no counting, no scripted yield move anywhere in the
    guidance or the frames."""
    guidance = ENC._GUARDIAN_FIRST_MEETING_GUIDANCE
    assert "You may volunteer a topic from your own interests" in guidance
    assert "yield by judgment, in the moment" in guidance
    assert "never by a prescribed procedure" in guidance
    for forbidden in ("step 1", "first, yield", "yield in three", "counting"):
        assert forbidden not in guidance.lower(), forbidden
    # The read-back is unmandated: the engage glue permits it ("only
    # if"), it never demands it — and the definition's engage frame
    # carries that glue verbatim.
    definition = ENC.get_definition(MT.get_script("guardian", 1))
    assert "only if this exchange has genuinely shown you how they orient" in definition.engage_frame


def test_parser_contract_delimiter_and_strands_survive():
    """The delimiter + Strands line are the parser contract: the
    engage frame must carry the --- movement split, the read-back
    frame must demand the Strands line, and the runtime splitter
    must still parse both."""
    script = MT.get_script("guardian", 1)
    definition = ENC.get_definition(script)
    assert "containing only ---" in definition.engage_frame
    assert "Strands: <names>" in script.readback_frame
    assert "Strands: <names>" in script.correction_frame
    claim, strands = split_strands_trailer(
        "A first impression, held at its doubt.\nStrands: Compass, Logic"
    )
    assert "first impression" in claim
    assert strands == ["Compass", "Logic"]


# ------------------------------------------------------------ reference slice


SLICE_MARKERS = [
    # Ideal + question + shadow.
    "Love through stewardship",
    "What must be protected?",
    "smothering",
    # Relational perspective, one line per pair, with pair numbers.
    "growth-pressure is a loosening decision, not a threat. (Pair 2.)",
    "must not call a priced choice irresponsibility. (Pair 7.)",
    "tells a kept door from a cage. (Pair 12.)",
    "connection is not automatically access granted. (Pair 13.)",
    "not an abandoned vital thing. (Pair 14.)",
    "I yield the evidentiary challenge and keep the stewardship decision. (Pair 15.)",
    # Conversational agency.
    "pursue floors, thresholds, and slow leaks",
    "answer direct questions directly, in quantities",
]


def test_reference_slice_on_both_live_paths_and_nowhere_else():
    """Prompt-local slice (Weaver #252 pattern): present on the turn
    frame AND the engage frame, in all three dimensions — and absent
    from the Weaver's definition, so no seat leaks into another."""
    definition = ENC.get_definition(MT.get_script("guardian", 1))
    for marker in SLICE_MARKERS:
        assert marker in definition.turn_frame, marker
        assert marker in definition.engage_frame, marker
    weaver = ENC.get_definition(MT.get_script("conductor", 1))
    for marker in SLICE_MARKERS:
        assert marker not in weaver.turn_frame, marker
        assert marker not in weaver.engage_frame, marker
    # The slice is prompt-local, not the shared uncapped section:
    # this checkout's definition has no fellowship_reference field
    # (that mechanism is unmerged PR #255) and the slice lives in
    # the frames themselves.
    assert not hasattr(definition, "fellowship_reference")


def test_no_steward_wiring_for_guardian():
    """Steward consolidation was Weaver-only. The Guardian builder
    must not consult the steward module: its definition's frames
    come from meetings.py alone."""
    import local_ai.council.steward_records as sr

    definition = ENC.get_definition(MT.get_script("guardian", 1))
    # The Weaver's steward-sourced turn frame must not appear here.
    assert definition.turn_frame != sr.TURN_FRAME
    assert "Bear" in definition.character or definition.character == "Bear"


# ---------------------------------------------------------------- release gate


def test_guardian_meeting_is_not_visitor_accessible(ve_ctx, tmp_path):
    """BUILDING IS NOT AVAILABILITY. A seeded visitor with Weaver K1
    complete satisfies every old rule (seeded, scripted, entry done)
    — the exact visitor script existence alone would have opened
    the meeting to — and is still refused by the release gate, with
    no row, no transcript, and no generation possible."""
    uid = _seeded_user()
    _complete_conductor_k1(uid)
    svc = _svc(tmp_path)
    # The script genuinely exists — this is not the unwritten-seat path.
    assert MT.get_script("guardian", 1) is not None
    with pytest.raises(MeetingError, match="isn't open to visitors yet"):
        svc.start(uid, "guardian")
    assert svc.meetings.get(uid, "guardian", 1) is None
    with pytest.raises(MeetingError, match="No meeting is in progress"):
        svc.turn(uid, "guardian", "Hello?")
    # And the release gate changes nothing for the released seat.
    assert "conductor" in MT.RELEASED_FIRST_MEETING_SEATS
    assert "guardian" not in MT.RELEASED_FIRST_MEETING_SEATS


def test_unwritten_seats_keep_their_original_refusal(ve_ctx, tmp_path):
    """Gate ordering: unwritten seats still hit the script check
    first, with the original message — the release check never
    shadows it."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    with pytest.raises(MeetingError, match="isn't written yet"):
        svc.start(uid, "mentor")


# ---------------------------------------------------------------- frame budget


def _composed_engage(definition, capability_block):
    frame = (
        definition.engage_frame
        + "\n\n" + _ZENAF_QUESTION_NOTE
        + "\n\n" + _naming_note(definition)
    )
    if capability_block:
        frame += "\n\n" + capability_block
    return frame


def test_frame_sizes_measured_with_headroom():
    """Measured, not claimed (see PR description for the table).
    The composed engage frame — exactly as handle_turn builds it —
    fits the live 8,000-char frame cap (reply.py) with >= 300 chars
    headroom in the default, worst-case capability (signed-out),
    and fully-met naming variants; the composed turn frame fits
    with room for an allusion cue (~300 chars). The honesty guard,
    the capability block's last line, is therefore never the first
    content lost to truncation."""
    definition = ENC.get_definition(MT.get_script("guardian", 1))
    cap_default = CAP.first_meeting_block("guardian", CAP.VisitorState())
    cap_worst = CAP.first_meeting_block(
        "guardian", CAP.VisitorState(signed_in=False)
    )
    variants = {
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
    for name, frame in variants.items():
        assert len(frame) <= 8000, (name, len(frame))
        assert 8000 - len(frame) >= 300, (name, len(frame))
        assert CAP.HONESTY_GUARD in frame, name
        assert len(frame) <= 12500, (name, len(frame))
    runtime = EncounterRuntime(definition)
    turn_frame, _cue = runtime._turn_frame(EncounterState(), "test message")
    assert len(turn_frame) <= 8000
    assert 8000 - len(turn_frame) >= 300
    assert CAP.HONESTY_GUARD in turn_frame
