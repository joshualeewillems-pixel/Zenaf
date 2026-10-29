"""Crane recognition as a moment, not a close (six-seat relational
references, 2026-10-29 — Crane PR, mirroring the Weaver
recognition-moment suite). What this pins:

- Decoupling flag: Crane True (Weaver True, unchanged; Guardian
  False as the coupled control).
- A settled verdict never closes a decoupled Crane meeting; it
  still closes a coupled one (Guardian control).
- The recognition moment delivers a live-generated introduction
  exactly once — a second generation on the recognition turn —
  and never as scripted text (no reveal paragraph spoken).
- Direct-question precedence is shared machinery: a direct question
  holds a pending impression for the Crane too, with no per-seat
  paragraph in her reference (see test_crane_fellowship_reference).
- The close chokepoint is silent for a decoupled meeting (no wrap
  line, no reveal paragraphs) while still marking the task Done
  and the meeting complete.
- Filing happens at completion ONLY: no claim exists after
  recognition turns alone; visitor-controlled completion files
  exactly one claim; a second run supersedes the first.

Runtime tests use a fake host (no service, no DB). The _do_reveal
and completion tests use the service fixtures (temp DBs), like the
Weaver suite — with TEST-ONLY activation (script registration +
release + Weaver-first gate satisfied by monkeypatch/seed), because
the production gates are unchanged by this PR: the meeting stays
unregistered and unreleased until Joshua's separate word. No model
calls anywhere.
"""

from __future__ import annotations

import threading

import pytest

from local_ai.agent_intake.store import AgentStore
from local_ai.conversation import encounter as ENC
from local_ai.conversation.meeting import MeetingService, MeetingStore, _seat_keystone_tasks
from local_ai.conversation.store import ConversationStore
from local_ai.council import meetings as MT
from local_ai.vision_execution import keystone_seeding
from local_ai.vision_execution import models as ve_models
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


def _crane_runtime():
    return ENC.EncounterRuntime(
        ENC.get_definition(MT.AMBASSADOR_FIRST_MEETING)
    )


def _guardian_runtime():
    return ENC.EncounterRuntime(
        ENC.get_definition(MT.get_script("guardian", 1))
    )


# ---------------------------------------------------------------- flags


def test_decoupling_flag_crane_true_guardian_false():
    crane = ENC.get_definition(MT.AMBASSADOR_FIRST_MEETING)
    guardian = ENC.get_definition(MT.get_script("guardian", 1))
    weaver = ENC.get_definition(MT.get_script("conductor", 1))
    assert crane.decoupled_recognition is True
    assert weaver.decoupled_recognition is True
    assert guardian.decoupled_recognition is False


def test_introduction_flag_round_trips_and_defaults_false():
    # Shared state machinery, pinned here for the Crane path too.
    state = ENC.EncounterState()
    assert state.introduction_delivered is False
    state.introduction_delivered = True
    assert ENC.EncounterState.from_json(state.to_json()).introduction_delivered is True
    assert (
        ENC.EncounterState.from_json('{"user_turns": 3}').introduction_delivered
        is False
    )


# ------------------------------------------------------- close decision


def test_settled_verdict_does_not_close_decoupled_crane():
    host = FakeHost()
    state = ENC.EncounterState(impression_answered=True)
    _crane_runtime()._close_or_continue(host, state, "Thanks.", "settled")
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
    intro = "I am the Crane, ambassador of this council. Stay a while."
    host = FakeHost(intro=intro)
    state = ENC.EncounterState(
        impression_offered=True, impression_text="a read",
    )
    runtime = _crane_runtime()
    runtime._impression_response_turn(host, state, "Yes, that's right.")
    assert state.impression_answered is True
    assert state.introduction_delivered is True
    assert intro in host.said
    # No scripted reveal text among what was said.
    script = MT.AMBASSADOR_FIRST_MEETING
    for paragraph in script.reveal:
        assert paragraph not in host.said
    # A later turn does not repeat the introduction.
    said_before = list(host.said)
    runtime._post_recognition_turn(host, state, "Tell me more.")
    assert host.said[len(said_before):].count(intro) == 0


def test_recognition_turn_carries_a_second_generation():
    # The introduction is a second generation on the recognition
    # turn (reply first, introduction second), never scripted text.
    intro = "I am the Crane, ambassador of this council."
    host = FakeHost(intro=intro)
    state = ENC.EncounterState(
        impression_offered=True, impression_text="a read",
    )
    _crane_runtime()._impression_response_turn(
        host, state, "Yes, that's right.")
    assert len(host.frames) == 2
    assert "Introduce yourself" in host.frames[1]
    assert host.frames[1] != host.frames[0]


def test_introduction_skipped_when_not_decoupled():
    host = FakeHost(intro="I am the Crane.")
    state = ENC.EncounterState(
        impression_offered=True, impression_text="a read",
    )
    runtime = _guardian_runtime()
    runtime._impression_response_turn(host, state, "Yes, that's right.")
    assert state.introduction_delivered is False
    assert "I am the Crane." not in host.said


# ---------------------------------------------- direct-question precedence


def test_direct_question_holds_pending_impression():
    host = FakeHost()
    state = ENC.EncounterState(impression_pending_text="a held read")
    _crane_runtime().handle_turn(
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
    _crane_runtime().handle_turn(host, state, "Hello.", 0)
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


def _svc(tmp_path, generate_fn=None):
    return MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
        generate_fn=generate_fn,
    )


def _seeded_user(email="crane-recognition@example.com"):
    user = ve.create_user_account(email, "pw", "Crane")
    keystone_seeding.seed_meet_your_council(user["id"])
    return user["id"]


def _activate_test_only(monkeypatch):
    """Test-only activation: script registration + release, gates in
    production code untouched. The Weaver-first entry gate is
    satisfied by marking the Conductor's keystone 1 Done."""
    monkeypatch.setitem(
        MT.SCRIPTS, ("ambassador", 1), MT.AMBASSADOR_FIRST_MEETING)
    monkeypatch.setattr(
        MT, "RELEASED_FIRST_MEETING_SEATS",
        MT.RELEASED_FIRST_MEETING_SEATS | {"ambassador"},
    )


def _ready_user(monkeypatch, email):
    uid = _seeded_user(email=email)
    _activate_test_only(monkeypatch)
    conductor_tasks = _seat_keystone_tasks(uid, "conductor")
    ve.update_task(
        conductor_tasks[0]["id"], ve_models.TaskUpdate(status="Done"), uid)
    return uid


def test_do_reveal_silent_for_decoupled_still_completes(ve_ctx, tmp_path, monkeypatch):
    uid = _ready_user(monkeypatch, "crane-silent@example.com")
    svc = _svc(tmp_path, generate_fn=lambda prompt, **kwargs: "A plain reply.")
    svc.start(uid, "ambassador")
    script = MT.AMBASSADOR_FIRST_MEETING
    said: list[str] = []
    svc._say = lambda user_id, cid, arch_id, body: said.append(body)  # type: ignore[method-assign]
    definition = ENC.get_definition(script)
    assert definition.decoupled_recognition is True
    svc._do_reveal(uid, "ambassador", 1, script, wrap_line="wrap line",
                   silent_close=definition.decoupled_recognition)
    assert said == []
    row = svc.meetings.get(uid, "ambassador", 1)
    assert row["status"] == "complete"


# ------------------------------------------- filing at completion only


class _CompletionFakeGen:
    """Same beats as the ambassador supersede fake: the read-back
    names the Compass and Logic strands, so a run files one
    meeting_impression claim under meeting-ambassador-1 — at
    completion, never before."""

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


def _completion_svc(tmp_path):
    agents_db = tmp_path / "agents.db"
    return MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
        generate_fn=_CompletionFakeGen(),
        agent_store_factory=lambda uid: AgentStore(agents_db, user_id=uid),
    )


def _run_crane_turns(svc, uid, answer, response):
    """Recognition turns only — under decoupling these must NOT
    complete the meeting, however settled the thread reads."""
    svc.start(uid, "ambassador")
    svc.turn(uid, "ambassador", answer)
    svc.turn(uid, "ambassador", response)
    state = svc.turn(uid, "ambassador", "Got it.")
    assert state["status"] != "complete"
    return state


def test_settled_turns_file_nothing_completion_files_once(ve_ctx, tmp_path, monkeypatch):
    uid = _ready_user(monkeypatch, "crane-filing@example.com")
    svc = _completion_svc(tmp_path)
    store = AgentStore(tmp_path / "agents.db", user_id=uid)
    _run_crane_turns(
        svc, uid,
        "I triage by what breaks first if I ignore it.",
        "Mostly right — except I protect mornings first.",
    )
    # Recognition happened, completion did not — nothing filed yet.
    assert store.get_claims("meeting-ambassador-1") == []
    # Visitor-controlled completion: exactly one claim, filed now.
    state = svc.complete(uid, "ambassador")
    assert state["status"] == "complete"
    claims = store.get_claims("meeting-ambassador-1")
    assert len(claims) == 1
    assert claims[0].claim_type == "meeting_impression"
    assert claims[0].evidence == "Mostly right — except I protect mornings first."


def test_second_run_supersedes_prior_claim_via_visitor_completion(ve_ctx, tmp_path, monkeypatch):
    uid = _ready_user(monkeypatch, "crane-supersede@example.com")
    svc = _completion_svc(tmp_path)
    store = AgentStore(tmp_path / "agents.db", user_id=uid)
    _run_crane_turns(
        svc, uid,
        "I triage by what breaks first if I ignore it.",
        "Mostly right — except I protect mornings first.",
    )
    svc.complete(uid, "ambassador")
    first = store.get_claims("meeting-ambassador-1")
    assert len(first) == 1
    first_claim = first[0]
    store.update_claim(first_claim.id, status="accepted")

    svc.restart(uid, "ambassador")
    _run_crane_turns(
        svc, uid,
        "Second time: I start with people, not tasks.",
        "And people first means the message, not the task list.",
    )
    svc.complete(uid, "ambassador")

    claims = store.get_claims("meeting-ambassador-1")
    assert len(claims) == 2  # both rows retained, nothing erased
    by_id = {c.id: c for c in claims}
    old = by_id[first_claim.id]
    assert old.status == "superseded"
    assert "accepted" in old.detail  # prior verdict visible, not silently lost
    assert old.evidence == "Mostly right — except I protect mornings first."
    assert old.inference == first_claim.inference
    new = next(c for c in claims if c.id != first_claim.id)
    assert new.claim_type == "meeting_impression"
    assert new.status == "pending"
    assert new.evidence == "And people first means the message, not the task list."
    standing = [c for c in claims if c.status != "superseded"]
    assert len(standing) == 1
    assert standing[0].id == new.id
