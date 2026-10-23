"""Keystone meetings — the first-meeting stage machine.

Semantics under test (Joshua's design, 2026-10-19 + corrections 2026-10-22):
  - A first meeting runs opening (scripted) → encounter (one question,
    live reply) → read-back (one tentative, correctable impression) →
    reveal (scripted), and completing it marks keystone 1 Done.
  - The Conductor is met first; no other seat's first meeting begins until
    the Weaver's keystone 1 is complete. Nobody is introduced by proxy.
  - A seat with no written script has no meeting yet — refused honestly.
  - Passing is participation: it offers the next banked question; passing
    the whole bank still reaches the read-back.
  - The read-back claim and the user's response are stored verbatim on the
    meeting record as an UNFILED first impression. Nothing here files
    training.
  - Meetings resume: re-starting never repeats the opening.
"""

from __future__ import annotations

import dataclasses
import threading

import pytest
from fastapi import HTTPException

from local_ai.council import meetings as MT
from local_ai.conversation.meeting import MeetingError, MeetingService, MeetingStore
from local_ai.conversation.store import ConversationStore
from local_ai.vision_execution import keystone_seeding
from local_ai.vision_execution import service as ve


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    """Isolate the vision-execution SQLite DB per test (test_you_profile pattern)."""
    import local_ai.vision_execution.storage as ve_store

    monkeypatch.setattr(ve_store, "_DB_PATH", tmp_path / "ve.db")
    monkeypatch.setattr(ve_store, "_DB_DIR", tmp_path)
    monkeypatch.setattr(ve_store, "_init_done_paths", set())
    monkeypatch.setattr(ve_store, "_thread_local", threading.local())
    return {}


class FakeGen:
    """Records prompts; answers by beat so tests can see which frame ran."""

    def __init__(self):
        self.prompts: list[str] = []

    def __call__(self, prompt, **kwargs):
        self.prompts.append(prompt)
        if "READ-BACK beat" in prompt:
            return "A first impression, anchored in [[u]]your words[[/u]] — correct me."
        if "ENCOUNTER beat" in prompt:
            return "An engaged reply that hears two tensions together."
        return "A plain reply."


def _svc(tmp_path, gen=None):
    return MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
        generate_fn=gen or FakeGen(),
    )


def _seeded_user(email="meet@example.com"):
    user = ve.create_user_account(email, "pw", "Meet")
    keystone_seeding.seed_meet_your_council(user["id"])
    return user["id"]


def _conductor_k1_status(uid):
    from local_ai.conversation.meeting import _seat_keystone_tasks

    tasks = _seat_keystone_tasks(uid, "conductor")
    return tasks[0]["status"] if tasks else None


# ------------------------------------------------------------------ start


def test_start_delivers_opening_and_first_question(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    state = svc.start(uid, "conductor")

    assert state["status"] == "active"
    assert state["stage"] == "encounter"
    assert state["conversation_id"] == "meeting-conductor-1"
    script = MT.get_script("conductor", 1)
    bodies = [m["body"] for m in state["messages"]]
    assert bodies[: len(script.opening)] == list(script.opening)
    assert bodies[len(script.opening)] == script.questions[0]
    assert all(m["role"] == "voice" for m in state["messages"])
    assert _conductor_k1_status(uid) != "Done"


def test_resume_never_repeats_opening(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    first = svc.start(uid, "conductor")
    second = svc.start(uid, "conductor")
    assert len(second["messages"]) == len(first["messages"])


def test_start_refusals(ve_ctx, tmp_path):
    svc = _svc(tmp_path)
    user = ve.create_user_account("unseeded@example.com", "pw", "U")
    with pytest.raises(MeetingError, match="hasn't been seeded"):
        svc.start(user["id"], "conductor")
    with pytest.raises(ValueError, match="Unknown seat"):
        svc.start(user["id"], "not-a-seat")

    uid = _seeded_user("seeded@example.com")
    # Mentor's meeting is not written yet — refused honestly, not improvised.
    with pytest.raises(MeetingError, match="isn't written yet"):
        svc.start(uid, "mentor")
    # Keystone 2 has no meeting in this build either.
    with pytest.raises(MeetingError, match="isn't written yet"):
        svc.start(uid, "conductor", keystone_index=2)


def test_conductor_first_guard(ve_ctx, tmp_path, monkeypatch):
    """Even with a script registered, another seat's first meeting waits
    for the Weaver's — the entry order is a rule, not a default."""
    uid = _seeded_user()
    fake = dataclasses.replace(MT.get_script("conductor", 1), archetype_id="mentor")
    monkeypatch.setitem(MT.SCRIPTS, ("mentor", 1), fake)
    svc = _svc(tmp_path)
    with pytest.raises(MeetingError, match="Weaver opens the council"):
        svc.start(uid, "mentor")


# -------------------------------------------------------------- the beats


def test_full_meeting_arc_completes_keystone(ve_ctx, tmp_path):
    uid = _seeded_user()
    gen = FakeGen()
    svc = _svc(tmp_path, gen)
    svc.start(uid, "conductor")

    state = svc.turn(uid, "conductor", "I triage by what breaks first if I ignore it.")
    assert state["stage"] == "readback"
    bodies = [m["body"] for m in state["messages"]]
    assert "An engaged reply that hears two tensions together." in bodies
    assert "A first impression, anchored in [[u]]your words[[/u]] — correct me." in bodies
    # Both live beats ran through the shared voice builder with their frames.
    assert any("ENCOUNTER beat" in p for p in gen.prompts)
    assert any("READ-BACK beat" in p for p in gen.prompts)

    state = svc.turn(uid, "conductor", "Mostly right — except I protect mornings first.")
    assert state["status"] == "complete"
    assert state["stage"] == "complete"
    script = MT.get_script("conductor", 1)
    bodies = [m["body"] for m in state["messages"]]
    for paragraph in script.reveal:
        assert paragraph in bodies
    # The reveal names the Weaver and his demeanor — and no motto, no flaw.
    assert any("I'm the Weaver." in b for b in bodies)

    # Keystone 1 flipped; the record kept both sides of the read-back verbatim.
    assert _conductor_k1_status(uid) == "Done"
    row = svc.meetings.get(uid, "conductor", 1)
    assert row["readback_claim"].startswith("A first impression")
    assert row["readback_response"] == "Mostly right — except I protect mornings first."

    # Attention moves on: every seat now invites a meeting.
    attention = keystone_seeding.keystone_attention(uid)
    assert attention["markers"]["conductor"]["reason"] == "meet"  # K2 next in its chain
    assert attention["markers"]["mentor"] == {"attention": True, "reason": "meet"}


def test_pass_offers_next_question_without_llm(ve_ctx, tmp_path):
    uid = _seeded_user()
    gen = FakeGen()
    svc = _svc(tmp_path, gen)
    svc.start(uid, "conductor")
    script = MT.get_script("conductor", 1)

    state = svc.turn(uid, "conductor", "pass")
    assert state["stage"] == "encounter"
    assert state["messages"][-1]["body"] == script.questions[1]
    assert gen.prompts == []  # a pass never reaches the model

    state = svc.turn(uid, "conductor", "next question")
    assert state["messages"][-1]["body"] == script.questions[2]
    assert gen.prompts == []


def test_passing_the_whole_bank_still_reaches_readback(ve_ctx, tmp_path):
    uid = _seeded_user()
    gen = FakeGen()
    svc = _svc(tmp_path, gen)
    svc.start(uid, "conductor")
    svc.turn(uid, "conductor", "pass")
    svc.turn(uid, "conductor", "skip")
    state = svc.turn(uid, "conductor", "pass")
    assert state["stage"] == "readback"
    assert state["messages"][-1]["body"].startswith("A first impression")
    # Only the read-back frame ran — there was nothing to engage with.
    assert len(gen.prompts) == 1 and "READ-BACK beat" in gen.prompts[0]


def test_substantive_no_is_an_answer_not_a_pass(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    svc.start(uid, "conductor")
    state = svc.turn(uid, "conductor", "No — I decide by deadline, every time.")
    assert state["stage"] == "readback"


# ------------------------------------------------------------------ pause


def test_pause_and_resume(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    svc.start(uid, "conductor")
    state = svc.pause(uid, "conductor")
    assert state["status"] == "paused"
    count = len(state["messages"])
    state = svc.start(uid, "conductor")
    assert state["status"] == "active"
    assert len(state["messages"]) == count  # resumed, not restarted


def test_turn_without_a_meeting_is_refused(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    with pytest.raises(MeetingError, match="No meeting is in progress"):
        svc.turn(uid, "conductor", "hello?")


def test_completed_meeting_cannot_be_replayed(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    svc.start(uid, "conductor")
    svc.turn(uid, "conductor", "Deadlines first, then everything else.")
    svc.turn(uid, "conductor", "That's right.")
    state = svc.start(uid, "conductor")
    assert state["status"] == "complete"
    with pytest.raises(MeetingError, match="No meeting is in progress"):
        svc.turn(uid, "conductor", "again?")


# -------------------------------------------------------------------- API


def test_api_flow_and_conflict_mapping(ve_ctx, tmp_path, monkeypatch):
    import api.routes.conversation_routes as routes

    uid = _seeded_user("api@example.com")
    svc = _svc(tmp_path)
    monkeypatch.setattr(routes, "_meeting_service", lambda: svc)
    user = {"id": uid}

    state = routes.meeting_start(routes.MeetingStartBody(archetype_id="conductor"), user)
    assert state["status"] == "active"

    # A meeting that isn't written maps the design refusal to 409.
    with pytest.raises(HTTPException) as exc:
        routes.meeting_start(routes.MeetingStartBody(archetype_id="mentor"), user)
    assert exc.value.status_code == 409

    state = routes.meeting_turn(
        routes.MeetingTurnBody(archetype_id="conductor", message="I plan, then improvise."),
        user,
    )
    assert state["stage"] == "readback"

    fetched = routes.meeting_state("conductor", 1, user)
    assert fetched["stage"] == "readback"
    assert fetched["has_script"] is True
