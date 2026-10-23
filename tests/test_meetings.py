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
            return (
                "A first impression, anchored in [[u]]your words[[/u]] — correct me."
                "\nStrands: Compass, Logic"
            )
        if "ORIENTATION beat" in prompt:
            return "A factual orientation answer from the notes."
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

    # The Conductor's meeting is unique: the orientation beat comes
    # between the read-back response and the reveal.
    state = svc.turn(uid, "conductor", "Mostly right — except I protect mornings first.")
    assert state["stage"] == "orientation"
    assert state["status"] == "active"  # not complete yet
    assert _conductor_k1_status(uid) != "Done"
    bodies = [m["body"] for m in state["messages"]]
    # The pulled-item accounting quotes BOTH sides verbatim, names the
    # strands the impression was filed under, and the bookkeeping line
    # itself never reaches the user.
    assert any("A first impression, anchored in" in b and "word for word" in b for b in bodies)
    assert any("Mostly right — except I protect mornings first." in b for b in bodies)
    assert any("the Compass and Logic strands" in b for b in bodies)
    assert not any(b.strip().startswith("Strands:") for b in bodies)

    state = svc.turn(uid, "conductor", "Got it.")
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
    svc.turn(uid, "conductor", "Got it.")
    state = svc.start(uid, "conductor")
    assert state["status"] == "complete"
    with pytest.raises(MeetingError, match="No meeting is in progress"):
        svc.turn(uid, "conductor", "again?")


def test_orientation_question_is_answered_then_reveal(ve_ctx, tmp_path):
    uid = _seeded_user()
    gen = FakeGen()
    svc = _svc(tmp_path, gen)
    svc.start(uid, "conductor")
    svc.turn(uid, "conductor", "I plan in pencil and improvise in ink.")
    svc.turn(uid, "conductor", "Close enough.")
    state = svc.turn(uid, "conductor", "Where does that impression actually live?")
    assert state["status"] == "complete"
    bodies = [m["body"] for m in state["messages"]]
    assert "A factual orientation answer from the notes." in bodies
    # The answer was framed by the orientation facts, not improvised.
    orientation_prompts = [p for p in gen.prompts if "ORIENTATION beat" in p]
    assert orientation_prompts and "seven seats" in orientation_prompts[0]


def test_script_without_orientation_goes_straight_to_reveal(ve_ctx, tmp_path, monkeypatch):
    """The orientation is the Conductor's distinction, not the engine's
    shape: a script without one keeps the four-beat meeting."""
    uid = _seeded_user()
    base = MT.get_script("conductor", 1)
    plain = dataclasses.replace(
        base, archetype_id="mentor", character="Gardener",
        orientation_intro=(), pulled_item_template="", pulled_where_template="",
        orientation=(), orientation_frame="", orientation_facts="",
    )
    monkeypatch.setitem(MT.SCRIPTS, ("mentor", 1), plain)
    svc = _svc(tmp_path)
    # Conductor first (full five-beat flow), then the mentor's four.
    svc.start(uid, "conductor")
    svc.turn(uid, "conductor", "Slow is smooth.")
    svc.turn(uid, "conductor", "Yes.")
    svc.turn(uid, "conductor", "Got it.")
    assert _conductor_k1_status(uid) == "Done"

    svc.start(uid, "mentor")
    svc.turn(uid, "mentor", "I learned patience the hard way.")
    state = svc.turn(uid, "mentor", "That's fair.")
    assert state["status"] == "complete"  # no orientation stop


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

    state = routes.meeting_turn(
        routes.MeetingTurnBody(archetype_id="conductor", message="Right."),
        user,
    )
    assert state["stage"] == "orientation"
    assert state["demeanor"] is None  # the reveal hasn't happened yet

    state = routes.meeting_turn(
        routes.MeetingTurnBody(archetype_id="conductor", message="ok"),
        user,
    )
    assert state["status"] == "complete"
    assert state["character"] == "Weaver"
    assert state["demeanor"] and "loose thread" in state["demeanor"]


# ----------------------------------------------------------------- restart


def _run_conductor_to_completion(svc, uid, answer="Deadlines first.", response="That's right."):
    svc.start(uid, "conductor")
    svc.turn(uid, "conductor", answer)
    svc.turn(uid, "conductor", response)
    return svc.turn(uid, "conductor", "Got it.")


def test_restart_refusals(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)

    # No meeting on record at all.
    with pytest.raises(MeetingError, match="hasn't been met yet"):
        svc.restart(uid, "conductor")
    # A seat whose meeting isn't written yet — same honest gate as start.
    with pytest.raises(MeetingError, match="isn't written yet"):
        svc.restart(uid, "mentor")
    with pytest.raises(ValueError, match="Unknown seat"):
        svc.restart(uid, "not-a-seat")

    # In progress (active or paused) is resumable, never restartable.
    svc.start(uid, "conductor")
    with pytest.raises(MeetingError, match="still in progress"):
        svc.restart(uid, "conductor")
    svc.pause(uid, "conductor")
    with pytest.raises(MeetingError, match="still in progress"):
        svc.restart(uid, "conductor")


def test_restart_archives_run_resets_state_and_reverts_keystone(ve_ctx, tmp_path):
    from local_ai.council import naming

    uid = _seeded_user()
    svc = _svc(tmp_path)
    done = _run_conductor_to_completion(
        svc, uid,
        answer="I triage by what breaks first if I ignore it.",
        response="Mostly right — except I protect mornings first.",
    )
    assert done["status"] == "complete"
    assert _conductor_k1_status(uid) == "Done"
    assert naming.keystone_one_done(uid, "conductor") is True
    first_bodies = [m["body"] for m in done["messages"]]
    row = svc.meetings.get(uid, "conductor", 1)
    assert row is not None

    state = svc.restart(uid, "conductor")

    # Fresh not-started state: no live row, no messages, keystone task
    # back to the exact status it was seeded with ("Todo"), and the face
    # the meeting revealed is locked again behind the new run.
    assert state["status"] == "not_started"
    assert state["messages"] == []
    assert svc.meetings.get(uid, "conductor", 1) is None
    assert _conductor_k1_status(uid) == "Todo"
    assert naming.keystone_one_done(uid, "conductor") is False

    # The prior run survives verbatim in the archive: full transcript and
    # the unfiled read-back impression, both sides.
    archives = svc.meetings.list_archives(uid, "conductor", 1)
    assert len(archives) == 1
    archive = archives[0]
    assert [m["body"] for m in archive["transcript"]] == first_bodies
    assert archive["readback_claim"] == row["readback_claim"]
    assert archive["readback_response"] == "Mostly right — except I protect mornings first."
    assert archive["readback_strands"] == ["Compass", "Logic"]


def test_restarted_meeting_reruns_and_recompletes(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _run_conductor_to_completion(svc, uid)
    svc.restart(uid, "conductor")

    # A fresh run delivers the opening again and runs the whole arc;
    # completing it flips keystone 1 back to Done.
    state = svc.start(uid, "conductor")
    assert state["status"] == "active"
    script = MT.get_script("conductor", 1)
    bodies = [m["body"] for m in state["messages"]]
    assert bodies[: len(script.opening)] == list(script.opening)

    svc.turn(uid, "conductor", "Second time: I start with people, not tasks.")
    svc.turn(uid, "conductor", "Yes, that's the shape of it.")
    state = svc.turn(uid, "conductor", "Ok sounds good")
    assert state["status"] == "complete"
    assert _conductor_k1_status(uid) == "Done"

    # A second restart archives the second run alongside the first.
    svc.restart(uid, "conductor")
    archives = svc.meetings.list_archives(uid, "conductor", 1)
    assert len(archives) == 2
    assert any(
        "Second time: I start with people, not tasks." in [m["body"] for m in a["transcript"]]
        for a in archives
    )


def test_restart_api_mapping(ve_ctx, tmp_path, monkeypatch):
    import api.routes.conversation_routes as routes

    uid = _seeded_user("restart-api@example.com")
    svc = _svc(tmp_path)
    monkeypatch.setattr(routes, "_meeting_service", lambda: svc)
    user = {"id": uid}

    # Nothing to restart yet → the refusal maps to 409.
    with pytest.raises(HTTPException) as exc:
        routes.meeting_restart(routes.MeetingRestartBody(archetype_id="conductor"), user)
    assert exc.value.status_code == 409

    _run_conductor_to_completion(svc, uid)
    state = routes.meeting_restart(routes.MeetingRestartBody(archetype_id="conductor"), user)
    assert state["status"] == "not_started"
    assert _conductor_k1_status(uid) == "Todo"


# -- The feel fixes (Joshua's first live run, 2026-10-23) ---------------------

def test_acknowledgment_detection_is_human_shaped():
    """'Ok sounds good' must proceed to the reveal, not be answered as if
    it were a question (the live run's worst break). Contrast words and
    real questions still route to the framed answer."""
    from local_ai.conversation.meeting import _is_acknowledgment

    assert _is_acknowledgment("Ok sounds good")
    assert _is_acknowledgment("ok")
    assert _is_acknowledgment("Yeah, that's right")
    assert _is_acknowledgment("Perfect, thanks")
    assert not _is_acknowledgment("Yes, but what about the review queue?")
    assert not _is_acknowledgment("Where does that impression live?")
    assert not _is_acknowledgment("Ok but actually I disagree with the strands")
    assert not _is_acknowledgment(
        "I mostly agree and the second strand feels right to me overall"
    )


def test_orientation_shows_excerpts_not_the_full_dump(ve_ctx, tmp_path):
    """The pulled-item accounting excerpts the claim and the answer —
    the full verbatim texts live on the record and in review. In the
    first live run the full dump read as parroting."""
    uid = _seeded_user()
    long_answer = (
        "I decide by writing the whole tangle down first, then I sleep on "
        "it, then I ask the one person who will tell me the truth even "
        "when it stings, and only then do I actually choose anything."
    )
    svc = _svc(tmp_path, FakeGen())
    svc.start(uid, "conductor")
    svc.turn(uid, "conductor", long_answer)
    state = svc.turn(uid, "conductor", "Close enough.")
    assert state["stage"] == "orientation"
    bodies = [m["body"] for m in state["messages"]]
    pulled = next(b for b in bodies if "the heart of my first impression" in b)
    assert "the full text of both waits in your review" in pulled.lower() or \
        "waits in your review" in pulled
    # The user's full answer is NOT dumped back inline.
    assert long_answer not in pulled


def test_ok_sounds_good_proceeds_straight_to_reveal(ve_ctx, tmp_path):
    """The exact live-run break: 'Ok sounds good' after the orientation
    was treated as a question and got an improvised second introduction.
    It must now proceed directly — no orientation generation at all."""
    uid = _seeded_user()
    gen = FakeGen()
    svc = _svc(tmp_path, gen)
    svc.start(uid, "conductor")
    svc.turn(uid, "conductor", "I plan in pencil and improvise in ink.")
    svc.turn(uid, "conductor", "Close enough.")
    prompts_before = len(gen.prompts)
    state = svc.turn(uid, "conductor", "Ok sounds good")
    assert state["status"] == "complete"
    new_prompts = gen.prompts[prompts_before:]
    assert not any("ORIENTATION beat" in p for p in new_prompts)
