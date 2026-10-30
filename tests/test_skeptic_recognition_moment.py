"""Raven recognition as a moment, not a close (six-seat Raven build,
2026-10-29). Mirrors tests/test_weaver_recognition_moment.py for
the Skeptic. What this pins:

- Decoupling flag: Skeptic True, Guardian False (coupled control).
- A settled verdict never closes a decoupled meeting; it still
  closes a coupled one (Guardian control).
- The recognition moment delivers a live-generated introduction
  exactly once (flag persists across to_json/from_json; old rows
  hydrate to False), and never as scripted text.
- Direct-question precedence in the move branch (shared machinery,
  not a per-seat paragraph): a direct question holds a pending
  impression (does not deliver it) and carries an explicit
  no-impression line in its frame; a greeting delivers.
- The close chokepoint speaks nothing scripted for a decoupled
  meeting (no wrap line, no reveal paragraphs) while still marking
  the task Done and the meeting complete; a non-silent close speaks
  as before.
- Filing happens at completion only: before the completion
  chokepoint runs, no review claim exists for the run, even with a
  read-back on the row; after it, exactly one meeting_impression
  claim is filed — recognition itself files nothing.

Runtime tests use a fake host (no service, no DB). The _do_reveal
tests create the meeting row directly (the Skeptic meeting is
deliberately unregistered, so svc.start cannot create it — the
gate test pins that separately and is untouched here). No model
calls anywhere.
"""

from __future__ import annotations

import pytest

from local_ai.agent_intake.store import AgentStore
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


def _skeptic_runtime():
    return ENC.EncounterRuntime(
        ENC.get_definition(MT.SKEPTIC_FIRST_MEETING)
    )


def _guardian_runtime():
    return ENC.EncounterRuntime(
        ENC.get_definition(MT.get_script("guardian", 1))
    )


# ---------------------------------------------------------------- flags


def test_decoupling_flag_skeptic_true_guardian_false():
    skeptic = ENC.get_definition(MT.SKEPTIC_FIRST_MEETING)
    guardian = ENC.get_definition(MT.get_script("guardian", 1))
    assert skeptic.decoupled_recognition is True
    assert guardian.decoupled_recognition is False


def test_introduction_flag_round_trips_and_defaults_false():
    state = ENC.EncounterState()
    assert state.introduction_delivered is False
    state.introduction_delivered = True
    assert ENC.EncounterState.from_json(state.to_json()).introduction_delivered is True
    assert (
        ENC.EncounterState.from_json('{"user_turns": 3}').introduction_delivered
        is False
    )


# ------------------------------------------------------- close decision


def test_settled_verdict_does_not_close_decoupled():
    host = FakeHost()
    state = ENC.EncounterState(impression_answered=True)
    _skeptic_runtime()._close_or_continue(host, state, "Thanks.", "settled")
    assert host.close_calls == []
    assert state.closed is False


def test_settled_verdict_still_closes_coupled():
    host = FakeHost()
    state = ENC.EncounterState(impression_answered=True)
    _guardian_runtime()._close_or_continue(host, state, "Thanks.", "settled")
    assert host.close_calls == [""]
    assert state.closed is True


# ------------------------------------------------- recognition moment


def test_introduction_delivered_once_live_generated():
    intro = "I am the Raven, skeptic of this council. Keep talking."
    host = FakeHost(intro=intro)
    state = ENC.EncounterState(
        impression_offered=True, impression_text="a read",
    )
    runtime = _skeptic_runtime()
    runtime._impression_response_turn(host, state, "Yes, that's right.")
    assert state.impression_answered is True
    assert state.introduction_delivered is True
    assert intro in host.said
    # No scripted reveal text among what was said.
    script = MT.SKEPTIC_FIRST_MEETING
    for paragraph in script.reveal:
        assert paragraph not in host.said
    # A later turn does not repeat the introduction.
    said_before = list(host.said)
    runtime._post_recognition_turn(host, state, "Tell me more.")
    assert host.said[len(said_before):].count(intro) == 0


def test_introduction_skipped_when_not_decoupled():
    host = FakeHost(intro="I am the Raven.")
    state = ENC.EncounterState(
        impression_offered=True, impression_text="a read",
    )
    runtime = _guardian_runtime()
    runtime._impression_response_turn(host, state, "Yes, that's right.")
    assert state.introduction_delivered is False
    assert "I am the Raven." not in host.said


# ---------------------------------------------- direct-question precedence


def test_direct_question_holds_pending_impression():
    host = FakeHost()
    state = ENC.EncounterState(impression_pending_text="a held read")
    _skeptic_runtime().handle_turn(
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
    _skeptic_runtime().handle_turn(host, state, "Hello.", 0)
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
    agents_db = tmp_path / "agents.db"
    return MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
        generate_fn=lambda prompt, **kwargs: "A plain reply.",
        agent_store_factory=lambda uid: AgentStore(agents_db, user_id=uid),
    )


def _seeded_user(email="skeptic-recognition@example.com"):
    user = ve.create_user_account(email, "pw", "Recognition")
    keystone_seeding.seed_meet_your_council(user["id"])
    return user["id"]


def test_do_reveal_silent_for_decoupled_still_completes(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    # Row created directly: svc.start cannot create it, because
    # the Skeptic script is deliberately unregistered (gate test).
    svc.meetings.create(uid, "skeptic", 1)
    script = MT.SKEPTIC_FIRST_MEETING
    said: list[str] = []
    svc._say = lambda user_id, cid, arch_id, body: said.append(body)  # type: ignore[method-assign]
    svc._do_reveal(uid, "skeptic", 1, script, wrap_line="wrap line",
                   silent_close=True)
    assert said == []
    row = svc.meetings.get(uid, "skeptic", 1)
    assert row["status"] == "complete"


def test_do_reveal_spoken_when_not_silent(ve_ctx, tmp_path):
    uid = _seeded_user(email="skeptic-recognition-spoken@example.com")
    svc = _svc(tmp_path)
    svc.meetings.create(uid, "skeptic", 1)
    script = MT.SKEPTIC_FIRST_MEETING
    said: list[str] = []
    svc._say = lambda user_id, cid, arch_id, body: said.append(body)  # type: ignore[method-assign]
    svc._do_reveal(uid, "skeptic", 1, script, wrap_line="wrap line",
                   silent_close=False)
    assert said == ["wrap line", *script.reveal]
    row = svc.meetings.get(uid, "skeptic", 1)
    assert row["status"] == "complete"


# -------------------------------------------- filing at completion only


def test_filing_happens_at_completion_not_recognition(ve_ctx, tmp_path):
    uid = _seeded_user(email="skeptic-recognition-filing@example.com")
    svc = _svc(tmp_path)
    svc.meetings.create(uid, "skeptic", 1)
    svc.meetings.update(
        uid, "skeptic", 1,
        readback_claim="A first impression, anchored in your words.",
        readback_response="Yes, that's the shape of it.",
        readback_strands='["Logic", "Compass"]',
    )
    store = AgentStore(tmp_path / "agents.db", user_id=uid)
    # A read-back on the row files nothing on its own: recognition
    # is a moment, not a completion.
    assert store.get_claims("meeting-skeptic-1") == []
    script = MT.SKEPTIC_FIRST_MEETING
    svc._say = lambda user_id, cid, arch_id, body: None  # type: ignore[method-assign]
    svc._do_reveal(uid, "skeptic", 1, script, wrap_line="wrap line",
                   silent_close=True)
    claims = [
        c for c in store.get_claims("meeting-skeptic-1")
        if c.claim_type == "meeting_impression"
    ]
    assert len(claims) == 1
    assert claims[0].evidence == "Yes, that's the shape of it."
