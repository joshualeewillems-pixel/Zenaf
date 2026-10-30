"""Gardener recognition as a moment, not a close (six-seat references
build, 2026-10-29) — the Weaver recognition-moment suite, in kind,
for the Mentor.

What this pins:

- Decoupling flag: Mentor True (Guardian True).
- A settled verdict never closes a decoupled meeting.
- The recognition moment delivers a live-generated introduction
  exactly once (never scripted reveal text), and the meeting stays
  active after it — completion comes only from the visitor-confirmed
  path, the ceiling wrap, or manual Complete.
- The GATELESS recognition moment (the Gardener's own question):
  the Mentor builder has NO impression gate and NO close floor, yet
  the moment still fires — the impression still exists via
  base.impression_frame, and _deliver_introduction_if_due fires on
  impression-answered alone. Before the impression is answered, no
  introduction delivers.
- The close chokepoint speaks nothing scripted for a decoupled
  meeting (silent close) while still marking the task Done and the
  meeting complete.

Runtime tests use a fake host (no service, no DB). The _do_reveal
test uses the service fixtures (temp DBs), like the encounter
runtime suite, with the Mentor's gates monkeypatched open for the
test only — the production gates are unchanged (script
unregistered, meeting refused at the gate; see
test_mentor_first_meeting). No model calls anywhere.
"""

from __future__ import annotations

import dataclasses

import pytest

from local_ai.conversation import encounter as ENC
from local_ai.conversation.meeting import MeetingService, MeetingStore
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


def _mentor_runtime():
    return ENC.EncounterRuntime(
        ENC.get_definition(MT.MENTOR_FIRST_MEETING)
    )


def _coupled_runtime():
    # No real seat remains coupled (F1: all seven decoupled after
    # the six-seat build), so the coupled path is exercised via a
    # synthetic coupled twin: this seat's own definition with only
    # the flag flipped. Same script, same gates — only the coupled
    # branch under test changes.
    return ENC.EncounterRuntime(
        dataclasses.replace(
            ENC.get_definition(MT.MENTOR_FIRST_MEETING),
            decoupled_recognition=False,
        )
    )


# ---------------------------------------------------------------- flags


def test_decoupling_flag_mentor_true_guardian_true():
    mentor = ENC.get_definition(MT.MENTOR_FIRST_MEETING)
    guardian = ENC.get_definition(MT.get_script("guardian", 1))
    assert mentor.decoupled_recognition is True
    assert guardian.decoupled_recognition is True


# ------------------------------------------------------- close decision


def test_settled_verdict_does_not_close_decoupled_mentor():
    host = FakeHost()
    state = ENC.EncounterState(impression_answered=True)
    _mentor_runtime()._close_or_continue(host, state, "Thanks.", "settled")
    assert host.close_calls == []
    assert state.closed is False


# ------------------------------------------------- recognition moment


def test_introduction_delivered_once_live_generated_meeting_stays_active():
    intro = "I am the Gardener, mentor of this council. Stay a while."
    host = FakeHost(intro=intro)
    state = ENC.EncounterState(
        impression_offered=True, impression_text="a read",
    )
    runtime = _mentor_runtime()
    runtime._impression_response_turn(host, state, "Yes, that's right.")
    assert state.impression_answered is True
    assert state.introduction_delivered is True
    assert intro in host.said
    # No scripted reveal text among what was said.
    for paragraph in MT.MENTOR_FIRST_MEETING.reveal:
        assert paragraph not in host.said
    # The meeting did NOT close on recognition.
    assert state.closed is False
    assert host.close_calls == []
    # A later turn does not repeat the introduction.
    said_before = list(host.said)
    runtime._post_recognition_turn(host, state, "Tell me more.")
    assert host.said[len(said_before):].count(intro) == 0


def test_introduction_skipped_when_not_decoupled():
    host = FakeHost(intro="I am the Bear.")
    state = ENC.EncounterState(
        impression_offered=True, impression_text="a read",
    )
    runtime = _coupled_runtime()
    runtime._impression_response_turn(host, state, "Yes, that's right.")
    assert state.introduction_delivered is False
    assert "I am the Bear." not in host.said


# ------------------------------------------- gateless recognition moment


def test_gateless_seat_has_no_gate_and_no_floor():
    definition = ENC.get_definition(MT.MENTOR_FIRST_MEETING)
    assert definition.impression_gate_objective == ""
    assert definition.close_floor_objectives == ()
    # Yet the impression itself still exists via the generic frame.
    assert definition.impression_frame.strip() != ""


def test_gateless_recognition_fires_on_impression_answered_alone():
    """The Gardener's own question, pinned: with no gate and no
    floor, the recognition moment fires exactly when the impression
    is answered — introduction delivered once, meeting stays active."""
    intro = "I am the Gardener, mentor of this council. Stay a while."
    host = FakeHost(intro=intro)
    state = ENC.EncounterState(
        impression_offered=True, impression_text="a read",
    )
    _mentor_runtime()._impression_response_turn(
        host, state, "Yes, that's right."
    )
    assert state.impression_answered is True
    assert state.introduction_delivered is True
    assert intro in host.said
    assert state.closed is False
    assert host.close_calls == []


def test_no_introduction_before_impression_answered():
    host = FakeHost(intro="I am the Gardener.")
    state = ENC.EncounterState(impression_offered=True)
    _mentor_runtime()._post_recognition_turn(host, state, "Hello.")
    assert state.introduction_delivered is False
    assert "I am the Gardener." not in host.said


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


def _seeded_user(email="mentor-recognition@example.com"):
    user = ve.create_user_account(email, "pw", "Recognition")
    keystone_seeding.seed_meet_your_council(user["id"])
    return user["id"]


def test_do_reveal_silent_for_decoupled_mentor_still_completes(
    ve_ctx, tmp_path, monkeypatch,
):
    # Test-only gate opening: the production gates are unchanged.
    monkeypatch.setitem(MT.SCRIPTS, ("mentor", 1), MT.MENTOR_FIRST_MEETING)
    monkeypatch.setattr(
        MT, "RELEASED_FIRST_MEETING_SEATS", frozenset({"conductor", "mentor"})
    )
    uid = _seeded_user()
    svc = _svc(tmp_path)
    # Entry gate: the Weaver opens the council — complete her first
    # meeting before the mentor can begin (same drive as
    # test_meetings' orientation test).
    svc.start(uid, "conductor")
    svc.turn(uid, "conductor", "Slow is smooth, and smooth is fast in the end.")
    svc.turn(uid, "conductor", "That's how I approach my own work, too.")
    svc.turn(uid, "conductor", "Yes.")
    svc.complete(uid, "conductor")
    svc.start(uid, "mentor")
    said: list[str] = []
    svc._say = lambda user_id, cid, arch_id, body: said.append(body)  # type: ignore[method-assign]
    svc._do_reveal(uid, "mentor", 1, MT.MENTOR_FIRST_MEETING,
                   wrap_line="wrap line", silent_close=True)
    assert said == []
    row = svc.meetings.get(uid, "mentor", 1)
    assert row["status"] == "complete"
