"""Maverick recognition as a moment, not a close (six-seat
references, 2026-10-29). Mirrors the Weaver recognition-moment
suite, for the Fox — F1 decoupling applied to a second seat:

- Decoupling flag: Maverick True (Guardian stays False).
- A settled verdict never closes a decoupled meeting, and the
  settled turn files nothing — filing happens only at the
  completion chokepoint (see the restart-supersede suite, which
  drives complete()).
- The recognition moment delivers a live-generated introduction
  exactly once (never scripted reveal text), on the recognition
  turn's second generation; a later turn does not repeat it.
- Direct-question precedence in the move branch: a direct question
  holds a pending impression (does not deliver it); a greeting
  delivers.
- The close chokepoint speaks nothing scripted for a decoupled
  meeting (no wrap line, no reveal paragraphs) while still marking
  the task Done and the meeting complete; the coupled path speaks
  as before. The Maverick's begin is gated, so the service-level
  close tests fabricate the meeting row exactly as the
  restart-supersede suite does — start is never driven.

Runtime tests use a fake host (no service, no DB). The _do_reveal
tests use the service fixtures (temp DBs), like the Weaver suite.
No model calls anywhere.
"""

from __future__ import annotations

import pytest

from local_ai.conversation import encounter as ENC
from local_ai.conversation.meeting import MeetingService, MeetingStore, _seat_keystone_tasks
from local_ai.conversation.store import ConversationStore
from local_ai.council import meetings as MT
from local_ai.vision_execution import keystone_seeding
from local_ai.vision_execution import service as ve


class FakeHost:
    """Minimal EncounterHost: records everything, generates canned."""

    def __init__(self, reply="A plain reply.", intro=None):
        self.said: list[str] = []
        self.frames: list[str] = []
        self.close_calls: list[str] = []
        self.stored_impressions: list[str] = []
        self.stored_responses: list[str] = []
        self.reply = reply
        self.intro = intro

    def say(self, body: str) -> None:
        self.said.append(body)

    def generate(self, frame: str) -> str:
        self.frames.append(frame)
        if self.intro is not None and "Introduce yourself" in frame:
            return self.intro
        return self.reply

    def store_impression(self, claim: str, strands: list[str]) -> None:
        self.stored_impressions.append(claim)

    def store_response(self, text: str) -> None:
        self.stored_responses.append(text)

    def close(self, wrap_line: str) -> None:
        self.close_calls.append(wrap_line)


def _maverick_runtime():
    return ENC.EncounterRuntime(
        ENC.get_definition(MT.get_script("maverick", 1))
    )


def _guardian_runtime():
    return ENC.EncounterRuntime(
        ENC.get_definition(MT.get_script("guardian", 1))
    )


# ---------------------------------------------------------------- flags


def test_decoupling_flag_maverick_true_guardian_false():
    maverick = ENC.get_definition(MT.get_script("maverick", 1))
    guardian = ENC.get_definition(MT.get_script("guardian", 1))
    assert maverick.decoupled_recognition is True
    assert guardian.decoupled_recognition is False
    # No authored gate or floor rides with decoupling: the generic
    # path stands (the audit-carried gate/floor was never code).
    assert maverick.impression_gate_objective == ""
    assert maverick.close_floor_objectives == ()


# ------------------------------------------------------- close decision


def test_settled_verdict_does_not_close_decoupled_and_files_nothing():
    host = FakeHost()
    state = ENC.EncounterState(impression_answered=True)
    _maverick_runtime()._close_or_continue(host, state, "Thanks.", "settled")
    assert host.close_calls == []
    assert state.closed is False
    # The settled turn is not a filing: nothing stored, no close.
    assert host.stored_impressions == []


# ------------------------------------------------- recognition moment


def test_introduction_delivered_once_live_generated():
    intro = "I am the Fox, maverick of this council. Stay a while."
    host = FakeHost(intro=intro)
    state = ENC.EncounterState(
        impression_offered=True, impression_text="a read",
    )
    runtime = _maverick_runtime()
    runtime._impression_response_turn(host, state, "Yes, that's right.")
    assert state.impression_answered is True
    assert state.introduction_delivered is True
    assert intro in host.said
    # No scripted reveal text among what was said.
    script = MT.get_script("maverick", 1)
    for paragraph in script.reveal:
        assert paragraph not in host.said
    # A later turn does not repeat the introduction.
    said_before = list(host.said)
    runtime._post_recognition_turn(host, state, "Tell me more.")
    assert host.said[len(said_before):].count(intro) == 0


def test_introduction_skipped_when_not_decoupled():
    host = FakeHost(intro="I am the Fox.")
    state = ENC.EncounterState(
        impression_offered=True, impression_text="a read",
    )
    runtime = _guardian_runtime()
    runtime._impression_response_turn(host, state, "Yes, that's right.")
    assert state.introduction_delivered is False
    assert "I am the Fox." not in host.said


# ---------------------------------------------- direct-question precedence


def test_direct_question_holds_pending_impression():
    host = FakeHost()
    state = ENC.EncounterState(impression_pending_text="a held read")
    _maverick_runtime().handle_turn(
        host, state, "What's their label? Their name?", 0
    )
    # The pending read was NOT delivered, and the reply spoken was
    # the generated answer, not the held read.
    assert state.impression_pending_text == "a held read"
    assert state.impression_offered is False
    assert "a held read" not in host.said
    assert any(
        "Do not offer a first impression on this turn" in frame
        for frame in host.frames
    )


def test_greeting_delivers_pending_impression():
    host = FakeHost()
    state = ENC.EncounterState(impression_pending_text="a held read")
    _maverick_runtime().handle_turn(host, state, "Hello.", 0)
    assert state.impression_pending_text == ""
    assert state.impression_offered is True
    assert "a held read" in host.said


# ------------------------------------------------------------- silent close


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    import local_ai.vision_execution.storage as ve_store

    monkeypatch.setattr(ve_store, "_DB_PATH", tmp_path / "ve.db")
    yield


def _svc(tmp_path):
    return MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
        generate_fn=lambda prompt, **kwargs: "A plain reply.",
    )


def _seeded_user(email="maverick-recognition@example.com"):
    user = ve.create_user_account(email, "pw", "Mav")
    keystone_seeding.seed_meet_your_council(user["id"])
    return user["id"]


def test_do_reveal_silent_for_decoupled_still_completes(ve_ctx, tmp_path):
    # Begin is gated, so the row is fabricated exactly as the
    # restart-supersede suite fabricates it; _do_reveal itself is
    # the real completion chokepoint under test.
    uid = _seeded_user()
    svc = _svc(tmp_path)
    svc.meetings.create(uid, "maverick", 1)
    script = MT.get_script("maverick", 1)
    said: list[str] = []
    svc._say = lambda user_id, cid, arch_id, body: said.append(body)  # type: ignore[method-assign]
    svc._do_reveal(uid, "maverick", 1, script, wrap_line="wrap line",
                   silent_close=True)
    assert said == []
    row = svc.meetings.get(uid, "maverick", 1)
    assert row["status"] == "complete"
    assert _seat_keystone_tasks(uid, "maverick")[0]["status"] == "Done"


def test_do_reveal_spoken_for_coupled(ve_ctx, tmp_path):
    uid = _seeded_user(email="maverick-recognition-coupled@example.com")
    svc = _svc(tmp_path)
    svc.meetings.create(uid, "maverick", 1)
    script = MT.get_script("maverick", 1)
    said: list[str] = []
    svc._say = lambda user_id, cid, arch_id, body: said.append(body)  # type: ignore[method-assign]
    svc._do_reveal(uid, "maverick", 1, script, wrap_line="wrap line",
                   silent_close=False)
    assert said == ["wrap line", *script.reveal]
    row = svc.meetings.get(uid, "maverick", 1)
    assert row["status"] == "complete"
