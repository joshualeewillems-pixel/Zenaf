"""Level 1 canonical instruction tier — deterministic checks (§5.2).

T-L1-1 tier present/positioned/adjacent; T-L1-2 frame clean; T-L1-3
flag off = byte-identical (unit level; end-to-end proof is T-L1-3a/3b);
T-L1-3a Talk end-to-end identity vs the pre-L1 goldens;
T-L1-3b demo end-to-end identity vs the pre-L1 goldens;
T-L1-4 single source; T-L1-5 no truncation; T-L1-6 steward parity;
T-L1-7 meeting control (tier present through the meeting call site).

The pre-L1 goldens (tests/level1_pre_goldens.json) were captured at
5d99063 via the Talk end-to-end path (ConversationService.turn) and
the demo path (POST /voice/chat), all seven seats; two independent
capture runs produced byte-identical output. No model calls here —
every generate_fn is a capturing stub. $0 spend.

CHAMPION EXCEPTION (2026-11-11 #342 correction, founder disposition
2026-11-11 ~06:20 PT, correction 3): the four champion goldens
(talk champion:empty/:seeded, demo champion:skeleton/:inline) were
regenerated from this branch to reflect ONLY the intended Firebrand
S1 behavior — the Q9 sentence, the C1 companion note on the
Commitments line, and the Q6/nature-rule line (delta +354 chars each,
verified identical across all four captures). The other six seats'
goldens are still the 5d99063 pre-L1 capture, byte-identical.
"""
import dataclasses
import json
import logging
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.routes.voice_routes as voice_routes
from api.routes.auth_routes import get_current_user
import local_ai.conversation.reply as reply_mod
from local_ai.agent_intake.store import AgentStore
from local_ai.conversation import encounter as ENC
from local_ai.conversation.canonical_tier import (
    CANONICAL_TIER_L1,
    QUESTION_NOTE,
    SCOPE_LINE,
)
from local_ai.conversation.encounter import EncounterRuntime, EncounterState
from local_ai.conversation.meeting import MeetingService, MeetingStore
from local_ai.conversation.reply import (
    _EXTRA_INSTRUCTIONS_CAP,
    build_voice_prompt,
)
from local_ai.conversation.service import ConversationService
from local_ai.conversation.store import ConversationStore
from local_ai.council import capabilities as CAP
from local_ai.council import meetings as MT
from local_ai.council import steward_records as SR

MSG = "In human communication, words are only about 10% of the communication happening."
# Talk/demo golden messages (must match the capture that produced the fixture).
MSG_A = "I'd like to plan my week."
MSG_B = "What should I focus on next?"
ALICE = {"id": "user-alice", "email": "alice@x", "display_name": "Alice"}
ARCHES = ["mentor", "champion", "guardian", "ambassador", "conductor", "skeptic", "maverick"]
SEATS = [
    ("weaver", "conductor", MT.CONDUCTOR_FIRST_MEETING, ENC.build_weaver_k1_definition),
    ("ambassador", "ambassador", MT.AMBASSADOR_FIRST_MEETING, ENC.build_ambassador_k1_definition),
    ("guardian", "guardian", MT.GUARDIAN_FIRST_MEETING, ENC.build_guardian_k1_definition),
    ("mentor", "mentor", MT.MENTOR_FIRST_MEETING, ENC.build_mentor_k1_definition),
    ("skeptic", "skeptic", MT.SKEPTIC_FIRST_MEETING, ENC.build_skeptic_k1_definition),
    ("maverick", "maverick", MT.MAVERICK_FIRST_MEETING, ENC.build_maverick_k1_definition),
    ("champion", "champion", MT.CHAMPION_FIRST_MEETING, ENC.build_champion_k1_definition),
]
FOUR_LINES = (QUESTION_NOTE, CAP.INTENTION_LINE, SCOPE_LINE, CAP.HONESTY_GUARD)


def _goldens():
    path = os.path.join(os.path.dirname(__file__), "level1_pre_goldens.json")
    with open(path) as f:
        return json.load(f)


def _definition(arch, script, builder):
    return builder(script)


def _frames(seat, arch, script, builder):
    """The corrected post-L1 frames for one seat: (engage, turn)."""
    d = _definition(arch, script, builder)
    runtime = EncounterRuntime(d)
    engage = runtime._engage_frame()
    turn, cue = runtime._turn_frame(EncounterState(), MSG)
    assert cue is None, f"{seat}: unexpected allusion cue"
    return d, engage, turn


def _meeting_prompt(arch, frame, tier, definition):
    lines, _ = build_voice_prompt(
        "level1", arch, MSG, [], mode="base", canonical=False,
        extra_instructions=frame,
        fellowship_reference=definition.fellowship_reference or "",
        canonical_tier=tier,
    )
    return "\n".join(lines)


def _assert_tier_adjacent_to_frame(prompt, frame, seat, where):
    """The tier is present exactly once, immediately before the frame:
    tier + blank line + frame, with no section intervening."""
    assert prompt.count(CANONICAL_TIER_L1) == 1, f"{seat} {where}: tier count"
    assert CANONICAL_TIER_L1 + "\n\n" + frame.strip() in prompt, (
        f"{seat} {where}: tier not immediately before the frame")


# ---------------------------------------------------------------------------
# T-L1-1: tier present, positioned, adjacent.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seat,arch,script,builder", SEATS, ids=[s[0] for s in SEATS])
def test_tier_present_positioned_adjacent(seat, arch, script, builder):
    d, engage, turn = _frames(seat, arch, script, builder)
    for label, frame in (("engage", engage), ("turn", turn)):
        prompt = _meeting_prompt(arch, frame, True, d)
        _assert_tier_adjacent_to_frame(prompt, frame, seat, label)
        # The guard in the tier is byte-identical to the capability constant.
        assert CANONICAL_TIER_L1.endswith(CAP.HONESTY_GUARD)
        assert CAP.HONESTY_GUARD in CANONICAL_TIER_L1


# ---------------------------------------------------------------------------
# T-L1-2: frame clean — none of the four lines in the frame.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seat,arch,script,builder", SEATS, ids=[s[0] for s in SEATS])
def test_frame_clean(seat, arch, script, builder):
    d, engage, turn = _frames(seat, arch, script, builder)
    for label, frame in (("engage", engage), ("turn", turn)):
        for line in FOUR_LINES:
            assert line not in frame, f"{seat} {label}: line in frame: {line[:40]}..."
    # The capability block is lead-in + bullets only.
    block = CAP.first_meeting_block(arch, CAP.VisitorState())
    assert block.split("\n")[0] == "From your scope:"
    for line in FOUR_LINES:
        assert line not in block, f"{seat}: line in block: {line[:40]}..."


# ---------------------------------------------------------------------------
# T-L1-3: flag off = byte-identical (unit level). The tier is absent
# without the flag; T-L1-3a/3b prove end-to-end identity vs pre-L1.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seat,arch,script,builder", SEATS, ids=[s[0] for s in SEATS])
def test_flag_off_tier_absent(seat, arch, script, builder):
    d, engage, turn = _frames(seat, arch, script, builder)
    # Talk prompt (no frame): default flag and explicit False agree.
    default_lines, _ = build_voice_prompt(
        "level1", arch, MSG, [], mode="base", canonical=True)
    explicit_lines, _ = build_voice_prompt(
        "level1", arch, MSG, [], mode="base", canonical=True,
        canonical_tier=False)
    assert "\n".join(default_lines) == "\n".join(explicit_lines)
    assert CANONICAL_TIER_L1 not in "\n".join(default_lines), (
        f"{seat}: tier present with flag off")
    # And a framed prompt with the flag off carries no tier either.
    for label, frame in (("engage", engage), ("turn", turn)):
        off = _meeting_prompt(arch, frame, False, d)
        assert CANONICAL_TIER_L1 not in off, f"{seat} {label}: tier with flag off"


# ---------------------------------------------------------------------------
# T-L1-3a: Talk end-to-end identity vs the pre-L1 goldens.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("arch", ARCHES)
def test_talk_end_to_end_byte_identical(tmp_path, arch):
    goldens = _goldens()["talk"]
    prompts = []

    def _capture(prompt, **kw):
        prompts.append(prompt)
        return "Fake reply."

    store = ConversationStore(db_path=str(tmp_path / f"talk-{arch}.db"))
    svc = ConversationService(store, generate_fn=_capture)
    # Case A: empty history.
    svc.turn("user-alice", arch, MSG_A, conversation_id="skeleton", mode="base")
    assert len(prompts) == 1
    assert prompts[0] == goldens[f"{arch}:empty"], f"{arch}: Talk prompt changed (empty)"
    # Case B: one seeded exchange, then a second turn.
    store.append_message("user-alice", "skeleton", arch, "user", "I protect my mornings fiercely")
    store.append_message("user-alice", "skeleton", arch, "voice", "Noted.", mode="base")
    svc.turn("user-alice", arch, MSG_B, conversation_id="skeleton", mode="base")
    assert len(prompts) == 2
    assert prompts[1] == goldens[f"{arch}:seeded"], f"{arch}: Talk prompt changed (seeded)"
    store.close()


# ---------------------------------------------------------------------------
# T-L1-3b: demo end-to-end identity vs the pre-L1 goldens.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("arch", ARCHES)
def test_demo_end_to_end_byte_identical(tmp_path, monkeypatch, arch):
    goldens = _goldens()["demo"]
    prompts = []

    def _capture_demo(prompt, **kw):
        prompts.append(prompt)
        return "Fake reply."

    monkeypatch.setattr(reply_mod, "_default_generate", _capture_demo)
    app = FastAPI()
    app.include_router(voice_routes.router)
    app.dependency_overrides[get_current_user] = lambda: ALICE
    c = TestClient(app)

    # Skeleton mode: server-side history is the source of truth.
    store = ConversationStore(db_path=str(tmp_path / f"demo-{arch}.db"))
    store.ensure_conversation("user-alice")
    store.append_message("user-alice", "skeleton", arch, "user", "SERVER MARKER ONE")
    store.append_message("user-alice", "skeleton", arch, "voice", "noted", mode="base")
    monkeypatch.setattr(voice_routes, "_conversation_store", lambda s=store: s)
    r = c.post("/voice/chat", json={
        "archetype_id": arch, "message": "continue",
        "history": [{"role": "user", "content": "JUNK CLIENT HISTORY"}],
        "conversation_id": "skeleton",
    })
    assert r.status_code == 200, f"{arch} skeleton: {r.status_code} {r.text}"
    assert prompts[-1] == goldens[f"{arch}:skeleton"], f"{arch}: demo prompt changed (skeleton)"
    assert "SERVER MARKER ONE" in prompts[-1]
    assert "JUNK CLIENT HISTORY" not in prompts[-1]
    store.close()

    # Inline-history mode: no conversation_id, client history is used.
    store2 = ConversationStore(db_path=str(tmp_path / f"demo-inline-{arch}.db"))
    monkeypatch.setattr(voice_routes, "_conversation_store", lambda s=store2: s)
    before = len(prompts)
    r = c.post("/voice/chat", json={
        "archetype_id": arch, "message": "hello",
        "history": [{"role": "user", "content": "CLIENT HISTORY MARKER"}],
    })
    assert r.status_code == 200, f"{arch} inline: {r.status_code} {r.text}"
    assert len(prompts) == before + 1
    assert prompts[-1] == goldens[f"{arch}:inline"], f"{arch}: demo prompt changed (inline)"
    assert "CLIENT HISTORY MARKER" in prompts[-1]
    store2.close()


# ---------------------------------------------------------------------------
# T-L1-4: single source — each line exactly once in the meeting prompt.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seat,arch,script,builder", SEATS, ids=[s[0] for s in SEATS])
def test_single_source(seat, arch, script, builder):
    d, engage, turn = _frames(seat, arch, script, builder)
    for label, frame in (("engage", engage), ("turn", turn)):
        prompt = _meeting_prompt(arch, frame, True, d)
        for line in FOUR_LINES:
            assert prompt.count(line) == 1, (
                f"{seat} {label}: line appears {prompt.count(line)}x: {line[:40]}...")


# ---------------------------------------------------------------------------
# T-L1-5: no truncation — _cap_section never fires for a reachable frame.
# ---------------------------------------------------------------------------

def test_no_truncation_for_any_reachable_frame(caplog):
    caplog.set_level(logging.WARNING, logger="local_ai.conversation.reply")
    for seat, arch, script, builder in SEATS:
        d = _definition(arch, script, builder)
        runtime = EncounterRuntime(d)
        cap_d = CAP.first_meeting_block(arch, CAP.VisitorState())
        cap_w = CAP.first_meeting_block(arch, CAP.VisitorState(signed_in=False))
        others = tuple(a for _, a, _, _ in SEATS if a != arch)
        d_full = dataclasses.replace(d, met_seats=others)
        engage = runtime._engage_frame()
        turn, _ = runtime._turn_frame(EncounterState(), MSG)
        turn_full, _ = EncounterRuntime(d_full)._turn_frame(EncounterState(), MSG)
        # Reachable variants (gate 2): under the cap with >= 300 headroom.
        reachable = {
            "engage": engage,
            "turn": turn,
            "engage_full": (
                d_full.engage_frame + "\n\n" + cap_d + "\n\n" + ENC._naming_note(d_full)),
            "turn_full": turn_full,
        }
        # Bounds (gate 2B): measured and reported separately, never
        # folded into the reachable pass/fail — worst-capability is a
        # bound, not a reachable state.
        bounds = {
            "engage_worst": (
                d.engage_frame + "\n\n" + cap_w + "\n\n" + ENC._naming_note(d)),
            "engage_fully_met_worst": (
                d_full.engage_frame + "\n\n" + cap_w + "\n\n" + ENC._naming_note(d_full)),
        }
        for label, frame in reachable.items():
            assert len(frame) < _EXTRA_INSTRUCTIONS_CAP, (
                f"{seat} {label}: {len(frame)} over cap")
            assert _EXTRA_INSTRUCTIONS_CAP - len(frame) >= 300, (
                f"{seat} {label}: headroom below 300")
            _meeting_prompt(arch, frame, True, d)
        for label, frame in bounds.items():
            assert len(frame) < _EXTRA_INSTRUCTIONS_CAP, (
                f"{seat} {label}: {len(frame)} over cap")
            _meeting_prompt(arch, frame, True, d)
    trunc = [r for r in caplog.records if "truncated" in r.getMessage().lower()]
    assert trunc == [], f"truncation warnings: {[r.getMessage() for r in trunc]}"


# ---------------------------------------------------------------------------
# T-L1-6: steward parity — the steward Weaver path renders the tier
# identically (same tier text, same position) via the shared assemblers.
# ---------------------------------------------------------------------------

def test_steward_weaver_tier_parity(monkeypatch):
    segments = {}
    for flag in (False, True):
        monkeypatch.setattr(SR, "WEAVER_STEWARD_ACTIVE", flag)
        d = ENC.get_definition(MT.CONDUCTOR_FIRST_MEETING)
        runtime = ENC.EncounterRuntime(d)
        frame = runtime._engage_frame()
        prompt = _meeting_prompt("conductor", frame, True, d)
        _assert_tier_adjacent_to_frame(prompt, frame, "weaver", f"steward={flag}")
        # The tier + frame segment is the parity claim: same tier text,
        # same position, same frame under both read paths.
        segments[flag] = prompt[prompt.index(CANONICAL_TIER_L1):]
    assert segments[False] == segments[True]


# ---------------------------------------------------------------------------
# T-L1-7: meeting control — the tier lands through _generate_framed.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seat,arch,script,builder", SEATS, ids=[s[0] for s in SEATS])
def test_meeting_control_tier_present(tmp_path, seat, arch, script, builder):
    d, engage, _turn = _frames(seat, arch, script, builder)
    prompts = []

    def _capture(prompt, **kw):
        prompts.append(prompt)
        return "A plain engaged reply, hearing the work."

    agents_db = tmp_path / "agents.db"
    svc = MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
        generate_fn=_capture,
        agent_store_factory=lambda uid: AgentStore(agents_db, user_id=uid),
    )
    uid = "level1-user"
    cid = f"meeting-{arch}-1"
    store = svc.conversations
    store.ensure_conversation(uid)
    # Non-destructive Meet Again (Slice 1): the seed message is written
    # through the meeting path — the meeting conversation ensured first
    # (which creates the fence), then appended with via_meeting=True,
    # exactly as the meeting engine writes. The strict S1 fence refuses
    # ordinary writes to reserved meeting ids; this test exercises
    # meeting behavior, so the fixture seeds through the authorized
    # path rather than forcing a weaker contract (founder ruling,
    # 2026-11-13: tests adapt to a justified safety invariant).
    store.ensure_conversation(uid, cid, kind="meeting")
    store.append_message(uid, cid, arch, "user", MSG, via_meeting=True)
    reply = svc._generate_framed(uid, arch, 1, engage)
    assert reply == "A plain engaged reply, hearing the work."
    assert len(prompts) == 1
    prompt = prompts[0]
    _assert_tier_adjacent_to_frame(prompt, engage, seat, "meeting")
    # The frame in the prompt equals the corrected frame from §4.1.
    assert engage.strip() in prompt
    store.close()
