"""Champion recognition as a moment, not a close (six-seat
references, 2026-10-29) — mirrors
tests/test_weaver_recognition_moment.py for the Firebrand.

Decoupled like all seven (F1): her decisiveness is how she thinks
and acts, not a reason for the application to end a conversation.
What this pins:

- Decoupling flag: Champion True, Guardian True.
- A settled verdict never closes a decoupled meeting; it still
  closes a coupled one (coupled twin — no real seat remains
  coupled).
- The recognition moment delivers a live-generated introduction
  exactly once — a second generation on the recognition turn,
  after the reply generation — and never as scripted text.
- Direct-question precedence in the move branch: a direct question
  holds a pending impression (does not deliver it) and carries an
  explicit no-impression line in its frame; a greeting delivers.
- The close chokepoint speaks nothing scripted for a decoupled
  meeting (no wrap line, no reveal paragraphs) while still marking
  the task Done and the meeting complete — including through the
  visitor's own Complete action; coupled closes speak as before.
- Filing happens at completion only: a completed recognition arc
  files nothing while still active, and files exactly one claim
  when the visitor completes it.

Runtime tests use a fake host (no service, no DB). The _do_reveal
and filing tests use the service fixtures (temp DBs), like the
encounter runtime suite. The meeting itself stays HELD for
visitors and unreleased: these tests create the meeting row
directly (a fixture — turn/complete/_do_reveal need only the row
and the script) rather than beginning it, so they exercise
close/filing behavior without touching begin policy or patching
any gate set. Begin policy stays pinned by the held test in
tests/test_champion_first_meeting.py. No model calls anywhere.
"""

from __future__ import annotations

import dataclasses
import threading

import pytest

from local_ai.conversation import encounter as ENC
from local_ai.conversation.meeting import (
    MeetingService,
    MeetingStore,
)
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


def _champion_runtime():
    return ENC.EncounterRuntime(
        ENC.get_definition(MT.get_script("champion", 1))
    )


def _coupled_runtime():
    # No real seat remains coupled (F1: all seven decoupled after
    # the six-seat build), so the coupled path is exercised via a
    # synthetic coupled twin: this seat's own definition with only
    # the flag flipped. Same script, same gates — only the coupled
    # branch under test changes.
    return ENC.EncounterRuntime(
        dataclasses.replace(
            ENC.get_definition(MT.get_script("champion", 1)),
            decoupled_recognition=False,
        )
    )


# ---------------------------------------------------------------- flags


def test_decoupling_flag_champion_true_guardian_true():
    champion = ENC.get_definition(MT.get_script("champion", 1))
    guardian = ENC.get_definition(MT.get_script("guardian", 1))
    assert champion.decoupled_recognition is True
    assert guardian.decoupled_recognition is True


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
    _champion_runtime()._close_or_continue(host, state, "Thanks.", "settled")
    assert host.close_calls == []
    assert state.closed is False


def test_settled_verdict_still_closes_coupled():
    host = FakeHost()
    state = ENC.EncounterState(impression_answered=True)
    _coupled_runtime()._close_or_continue(host, state, "Thanks.", "settled")
    assert host.close_calls == [""]
    assert state.closed is True


# ------------------------------------------------- recognition moment


def test_introduction_delivered_once_live_generated():
    intro = "I am the Firebrand, champion of this forge. Name your hill."
    host = FakeHost(intro=intro)
    state = ENC.EncounterState(
        impression_offered=True, impression_text="a read",
    )
    runtime = _champion_runtime()
    runtime._impression_response_turn(host, state, "Yes, that's right.")
    assert state.impression_answered is True
    assert state.introduction_delivered is True
    assert intro in host.said
    # The recognition turn carries a second generation: the reply
    # generation, then the live introduction generation.
    assert any("Introduce yourself" in frame for frame in host.frames)
    assert len(host.frames) >= 2
    # No scripted reveal text among what was said.
    script = MT.get_script("champion", 1)
    for paragraph in script.reveal:
        assert paragraph not in host.said
    # A later turn does not repeat the introduction.
    said_before = list(host.said)
    runtime._post_recognition_turn(host, state, "Tell me more.")
    assert host.said[len(said_before):].count(intro) == 0


def test_introduction_skipped_when_not_decoupled():
    host = FakeHost(intro="I am the Firebrand.")
    state = ENC.EncounterState(
        impression_offered=True, impression_text="a read",
    )
    runtime = _coupled_runtime()
    runtime._impression_response_turn(host, state, "Yes, that's right.")
    assert state.introduction_delivered is False
    assert "I am the Firebrand." not in host.said


# ---------------------------------------------- direct-question precedence


def test_direct_question_holds_pending_impression():
    host = FakeHost()
    state = ENC.EncounterState(impression_pending_text="a held read")
    _champion_runtime().handle_turn(
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
    _champion_runtime().handle_turn(host, state, "Hello.", 0)
    assert state.impression_pending_text == ""
    assert state.impression_offered is True
    assert "a held read" in host.said


# ------------------------------------------------------------- silent close


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    """Isolate the vision-execution SQLite DB per test (test_meetings pattern)."""
    import local_ai.vision_execution.storage as ve_store

    monkeypatch.setattr(ve_store, "_DB_PATH", tmp_path / "ve.db")
    monkeypatch.setattr(ve_store, "_DB_DIR", tmp_path)
    monkeypatch.setattr(ve_store, "_init_done_paths", set())
    monkeypatch.setattr(ve_store, "_thread_local", threading.local())
    return {}


class _ArcGen:
    """Fake voice: read-back names Compass + Logic, as in
    tests/test_meetings.py and tests/test_meeting_impressions.py."""

    def __call__(self, prompt, **kwargs):
        if "has just corrected your first impression" in prompt:
            return (
                "A first impression, anchored in [[u]]your words[[/u]] — correct me."
                "\nStrands: Compass, Logic"
            )
        if "READ-BACK" in prompt:
            return (
                "A first impression, anchored in [[u]]your words[[/u]] — correct me."
                "\nStrands: Compass, Logic"
            )
        if "ENCOUNTER" in prompt:
            return "An engaged reply that hears two tensions together."
        return "A plain reply."


def _svc_with_agents(tmp_path):
    from local_ai.agent_intake.store import AgentStore

    agents_db = tmp_path / "agents.db"
    return MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
        generate_fn=_ArcGen(),
        agent_store_factory=lambda uid: AgentStore(agents_db, user_id=uid),
    )


def _svc(tmp_path):
    return MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
        generate_fn=lambda prompt, **kwargs: "A plain reply.",
    )


def _seeded_user(email="recognition-champ@example.com"):
    user = ve.create_user_account(email, "pw", "Recognition")
    keystone_seeding.seed_meet_your_council(user["id"])
    return user["id"]


def _champion_row(tmp_path, email, svc_factory):
    """Seeded user + a live champion meeting row, created
    directly (see module docstring): no begin, no gate touched."""
    uid = _seeded_user(email)
    svc = svc_factory(tmp_path)
    svc.meetings.create(uid, "champion", 1)
    return svc, uid


def test_do_reveal_silent_for_decoupled_still_completes(
    ve_ctx, tmp_path
):
    svc, uid = _champion_row(
        tmp_path, "recognition-champ@example.com", _svc
    )
    script = MT.get_script("champion", 1)
    said: list[str] = []
    svc._say = lambda user_id, cid, arch_id, body: said.append(body)  # type: ignore[method-assign]
    svc._do_reveal(uid, "champion", 1, script, wrap_line="wrap line",
                   silent_close=True)
    assert said == []
    row = svc.meetings.get(uid, "champion", 1)
    assert row["status"] == "complete"


def test_do_reveal_spoken_for_coupled(ve_ctx, tmp_path):
    svc, uid = _champion_row(
        tmp_path, "recognition-coupled-champ@example.com", _svc
    )
    script = MT.get_script("champion", 1)
    said: list[str] = []
    svc._say = lambda user_id, cid, arch_id, body: said.append(body)  # type: ignore[method-assign]
    svc._do_reveal(uid, "champion", 1, script, wrap_line="wrap line",
                   silent_close=False)
    assert said == ["wrap line", *script.reveal]
    row = svc.meetings.get(uid, "champion", 1)
    assert row["status"] == "complete"


def test_filing_at_completion_only_via_visitor_complete(
    ve_ctx, tmp_path
):
    """A full recognition arc files nothing while still active;
    the visitor's Complete action files exactly one claim — and
    speaks nothing scripted (silent close on the real path, not
    just the direct _do_reveal argument)."""
    from local_ai.agent_intake.store import AgentStore

    svc, uid = _champion_row(
        tmp_path, "recognition-filing-champ@example.com", _svc_with_agents
    )
    state = svc.state(uid, "champion")
    assert state["status"] == "active"
    svc.turn(uid, "champion", "I keep circling whether to quit my job and start the thing.")
    svc.turn(uid, "champion", "Mostly right — except the price is my savings, not my pride.")
    state = svc.turn(uid, "champion", "Got it.")
    # Decoupled: recognition did not close the meeting.
    assert state["status"] == "active"
    store = AgentStore(tmp_path / "agents.db", user_id=uid)
    assert store.get_claims("meeting-champion-1") == []
    # The visitor's own Complete action: silent, completing, filing.
    said: list[str] = []
    svc._say = lambda user_id, cid, arch_id, body: said.append(body)  # type: ignore[method-assign]
    state = svc.complete(uid, "champion")
    assert state["status"] == "complete"
    assert said == []
    claims = store.get_claims("meeting-champion-1")
    assert len(claims) == 1
    assert claims[0].claim_type == "meeting_impression"
    assert claims[0].status == "pending"
