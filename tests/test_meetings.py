"""Keystone meetings — the first-meeting encounter and its host service.

Semantics under test (Joshua's design, 2026-10-19 + corrections 2026-10-22;
the encounter runtime, Fellowship P3, 2026-10-23; the Weaver pattern,
2026-10-23):
  - A first meeting is an encounter with objectives, not a stage walk:
    ONE scripted opening bubble (her greeting question, asked for
    real) → collaboration → one tentative, correctable read-back
    impression (gated on the shared-work exchange) → reveal
    (scripted), and completing it marks keystone 1 Done. The stage
    values asserted below are the derived position labels the API
    has always surfaced, not the engine's mechanism.
  - The Conductor is met first; no other seat's first meeting begins until
    the Weaver's keystone 1 is complete. Nobody is introduced by proxy.
  - A seat with no written script has no meeting yet — refused honestly.
  - Passing is participation. For the Weaver there is no bank to
    pass through (retired with the dilemma): a pass is conversation.
    The generic bank machinery remains for future scripts.
  - The read-back claim and the user's response are stored verbatim on the
    meeting record as the first impression. Nothing here files training.
  - The redesign's correction semantics (2026-10-23) — a correction
    replaces the stored impression, an acknowledgment leaves it standing,
    and the dialogue carries no system explanation — are covered in
    tests/test_weaver_rewrite.py; filing the impression into the review
    queue is covered by tests/test_meeting_impressions.py.
  - Meetings resume: re-starting never repeats the opening.
"""

from __future__ import annotations

import dataclasses
import json
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
    """UPDATED for the Weaver pattern (2026-10-23): the delivered
    opening is ONE bubble — the script's first paragraph IS the
    first question: her greeting, asked for real, and she waits for
    the answer. (P3 delivered the greeting plus the scripted dilemma
    in one breath, so the question was scenery — Joshua's first
    live-test note. The dilemma is retired; there is no second
    scripted bubble to serve.)"""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    state = svc.start(uid, "conductor")

    assert state["status"] == "active"
    assert state["stage"] == "encounter"
    assert state["conversation_id"] == "meeting-conductor-1"
    script = MT.get_script("conductor", 1)
    bodies = [m["body"] for m in state["messages"]]
    assert bodies == [script.opening[0]]
    assert len(bodies) == 1
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

    # UPDATED for the Weaver pattern: the first substantive turn
    # begins the shared work — the fake's read is offered in the
    # generation and HELD by the impression gate (only the reply
    # movement, or the honest fallback, is spoken). The prompt
    # accounting is the P3 invariant, unchanged: ONE generation
    # carrying both frames (the two-speed responsiveness gate).
    state = svc.turn(uid, "conductor", "I triage by what breaks first if I ignore it.")
    assert state["stage"] == "encounter"
    assert len(gen.prompts) == 1
    assert "ENCOUNTER" in gen.prompts[0]
    assert "READ-BACK" in gen.prompts[0]

    # The second substantive turn: the gate is satisfied, and the
    # impression lands.
    state = svc.turn(
        uid, "conductor",
        "Mostly I protect the mornings before anything else gets a vote.",
    )
    assert state["stage"] == "readback"
    bodies = [m["body"] for m in state["messages"]]
    # The fake's claim text carries weave markers; the spoken claim
    # does not (evidence/expression separation, 2026-10-23): the
    # words survive, the markup does not — dialogue is hers now.
    assert "A first impression, anchored in your words — correct me." in bodies
    assert not any("[[u]]" in b for b in bodies)

    # UPDATED for the adaptivity fix: no orientation beat follows the
    # read-back response. The correction is answered (the revised
    # impression is spoken), and because the fake gives no thread
    # trailer and the correction is substantive new material, the
    # deterministic estimate keeps the encounter open in the
    # post-recognition phase — derived stage label "orientation",
    # as the API has always named that position.
    state = svc.turn(uid, "conductor", "Mostly right — except I protect mornings first.")
    assert state["stage"] == "orientation"
    assert state["status"] == "active"  # not complete yet
    assert _conductor_k1_status(uid) != "Done"
    bodies = [m["body"] for m in state["messages"]]
    # Nothing quotes the record back — no pulled-item excerpt, no
    # "waits in your review" — and the bookkeeping line itself never
    # reaches the user. The strands live on the record.
    assert any("Mostly right — except I protect mornings first." in b for b in bodies)
    assert not any("the heart of my first impression" in b for b in bodies)
    assert not any("waits in your review" in b for b in bodies)
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

    # Keystone 1 flipped; the record kept both sides of the read-back
    # verbatim, and the strand attribution lives on the record (the
    # intelligence layer), not in anything the Weaver said.
    assert _conductor_k1_status(uid) == "Done"
    row = svc.meetings.get(uid, "conductor", 1)
    assert row["readback_claim"].startswith("A first impression")
    assert row["readback_response"] == "Mostly right — except I protect mornings first."
    assert json.loads(row["readback_strands"]) == ["Compass", "Logic"]

    # Attention moves on: every seat now invites a meeting.
    attention = keystone_seeding.keystone_attention(uid)
    assert attention["markers"]["conductor"]["reason"] == "meet"  # K2 next in its chain
    assert attention["markers"]["mentor"] == {"attention": True, "reason": "meet"}


def test_pass_is_conversation_for_the_weaver(ve_ctx, tmp_path):
    """REWRITES test_pass_offers_next_question_without_llm and
    test_passing_the_whole_bank_still_reaches_readback (Weaver
    pattern, 2026-10-23): both pinned bank mechanics — a pass
    serving the next scripted question at no generation cost, and
    bank exhaustion forming the impression. The Weaver's bank is
    retired, so neither contract exists for her: a pass is answered
    in character (one conversational generation), no scripted
    question is served (there are none), and no impression can be
    conjured by passing — the gate requires the shared work. The
    generic bank machinery remains in the runtime for future
    scripts; it is unit-tested there (test_weaver_pattern)."""
    uid = _seeded_user()
    gen = FakeGen()
    svc = _svc(tmp_path, gen)
    svc.start(uid, "conductor")
    script = MT.get_script("conductor", 1)
    assert script.questions == ()

    state = svc.turn(uid, "conductor", "pass")
    assert state["stage"] == "encounter"
    # One conversational generation under the turn frame — the pass
    # reached the model because there is no bank to answer it.
    assert len(gen.prompts) == 1
    assert "mid-conversation in your workshop" in gen.prompts[0]
    row = svc.meetings.get(uid, "conductor", 1)
    assert row["readback_claim"] == ""

    state = svc.turn(uid, "conductor", "next question")
    assert state["stage"] == "encounter"
    assert len(gen.prompts) == 2
    row = svc.meetings.get(uid, "conductor", 1)
    assert row["readback_claim"] == ""


def test_substantive_no_is_an_answer_not_a_pass(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    svc.start(uid, "conductor")
    # A substantive "no" engages the encounter (it is not routed as
    # navigation): the shared work begins, and the read follows on
    # the next substantive turn — never on this one (the gate).
    state = svc.turn(uid, "conductor", "No — I decide by deadline, every time.")
    assert state["stage"] == "encounter"
    state = svc.turn(
        uid, "conductor", "Deadlines first, then everything else gets scheduled."
    )
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
    svc.turn(uid, "conductor", "Deadlines first, then everything else, every time.")
    # UPDATED for the adaptivity fix + the Weaver pattern: the
    # answering turn completes the meeting on recognition — but the
    # read itself took the shared-work exchange first.
    state = svc.turn(uid, "conductor", "That's right.")
    assert state["status"] == "complete"
    state = svc.start(uid, "conductor")
    assert state["status"] == "complete"
    with pytest.raises(MeetingError, match="No meeting is in progress"):
        svc.turn(uid, "conductor", "again?")


def test_question_after_recognition_is_answered_in_conversation(ve_ctx, tmp_path):
    """REWRITTEN for the adaptivity fix (was: the orientation beat's
    one Q&A exchange, then the reveal). There is no orientation beat:
    after recognition, a question is ordinary conversation — one
    generation under the conversational frame, with the workshop
    facts riding as prepared context — and the meeting closes only
    when a later turn settles."""

    class ThreadGen:
        def __init__(self):
            self.prompts: list[str] = []

        def __call__(self, prompt, **kwargs):
            self.prompts.append(prompt)
            if "READ-BACK" in prompt:
                return (
                    "A first impression, anchored in plain words — correct me."
                    "\nStrands: Compass, Logic"
                )
            if "Whatever its valence" in prompt:
                # The answer to the impression leaves a thread open.
                return "Fair enough.\n[[thread:open]]"
            if "mid-conversation in your workshop" in prompt:
                if "settled now" in prompt:
                    return "Then we're heard.\n[[thread:settled]]"
                return "It lives on the bench, same as everything here.\n[[thread:open]]"
            return "A plain reply."

    uid = _seeded_user()
    gen = ThreadGen()
    svc = _svc(tmp_path, gen)
    svc.start(uid, "conductor")
    # UPDATED for the Weaver pattern: two substantive turns to the
    # read (the gate), then an answer that leaves the thread open.
    svc.turn(uid, "conductor", "I plan in pencil and improvise in ink.")
    svc.turn(uid, "conductor", "And I keep the pencil sharp — plans are drafts, not promises.")
    svc.turn(uid, "conductor", "Close enough.")
    state = svc.turn(uid, "conductor", "Where does that impression actually live?")
    assert state["status"] == "active"  # the open question holds it open
    bodies = [m["body"] for m in state["messages"]]
    assert "It lives on the bench, same as everything here." in bodies
    # The answer was framed by the workshop facts, not improvised:
    # the facts block rides the conversational frame as context.
    assert "mid-conversation in your workshop" in gen.prompts[-1]
    assert "seven rather incompatible parts" in gen.prompts[-1]

    state = svc.turn(uid, "conductor", "Alright — settled now, thank you.")
    assert state["status"] == "complete"
    script = MT.get_script("conductor", 1)
    bodies = [m["body"] for m in state["messages"]]
    for paragraph in script.reveal:
        assert paragraph in bodies


def test_script_without_orientation_goes_straight_to_reveal(ve_ctx, tmp_path, monkeypatch):
    """UPDATED for the adaptivity fix: there is no orientation beat
    for ANY script now — recognition closes the meeting. A script
    stripped of orientation content behaves exactly like one that
    carries it: answer the impression, and the reveal follows."""
    uid = _seeded_user()
    base = MT.get_script("conductor", 1)
    plain = dataclasses.replace(
        base, archetype_id="mentor", character="Gardener",
        orientation_intro=(), pulled_item_template="", pulled_where_template="",
        orientation=(), orientation_frame="", orientation_facts="",
    )
    monkeypatch.setitem(MT.SCRIPTS, ("mentor", 1), plain)
    svc = _svc(tmp_path)
    # Conductor first, then the mentor — both close on recognition.
    # (The Weaver's drive carries the pattern's shape: shared work,
    # the read, then the answer. The generic mentor definition has
    # no gate or floor — its two-turn drive is unchanged.)
    svc.start(uid, "conductor")
    svc.turn(uid, "conductor", "Slow is smooth, and smooth is fast in the end.")
    svc.turn(uid, "conductor", "That's how I approach my own work, too.")
    state = svc.turn(uid, "conductor", "Yes.")
    assert state["status"] == "complete"
    assert _conductor_k1_status(uid) == "Done"

    svc.start(uid, "mentor")
    svc.turn(uid, "mentor", "I learned patience the hard way.")
    state = svc.turn(uid, "mentor", "That's fair.")
    assert state["status"] == "complete"  # no orientation stop anywhere


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

    # UPDATED for the Weaver pattern: the first turn begins the
    # shared work (stage encounter); the read lands on the second.
    state = routes.meeting_turn(
        routes.MeetingTurnBody(archetype_id="conductor", message="I plan, then improvise."),
        user,
    )
    assert state["stage"] == "encounter"

    state = routes.meeting_turn(
        routes.MeetingTurnBody(
            archetype_id="conductor",
            message="I plan in pencil, then improvise in ink, most days.",
        ),
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
    # UPDATED for the adaptivity fix: the answering turn completes
    # the meeting on recognition — the reveal (and its demeanor)
    # arrives with that same turn; there is no orientation stop
    # where the demeanor is still locked.
    assert state["status"] == "complete"
    assert state["stage"] == "complete"
    assert state["character"] == "Weaver"
    assert state["demeanor"] and "loose thread" in state["demeanor"]


# ----------------------------------------------------------------- restart


def _run_conductor_to_completion(
    svc, uid,
    answer="I work by deadlines first, then everything else follows.",
    response="That's right.",
):
    """Drive the Weaver's meeting to its close under the pattern's
    shape: a first substantive turn (the shared work begins), a
    second (the read lands), then the response to the impression."""
    svc.start(uid, "conductor")
    svc.turn(uid, "conductor", answer)
    svc.turn(
        uid, "conductor",
        "And in my own work it's the same — what breaks first gets my hands first.",
    )
    state = svc.turn(uid, "conductor", response)
    if state["status"] != "complete":
        # The answer left a thread open (a substantive correction,
        # under the deterministic estimate): one settled turn ends it.
        state = svc.turn(uid, "conductor", "Got it.")
    return state


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
    # the read-back impression, both sides.
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
    # completing it flips keystone 1 back to Done. (Opening shape as
    # in test_start_delivers_opening_and_first_question — the single
    # greeting bubble, the Weaver pattern.)
    state = svc.start(uid, "conductor")
    assert state["status"] == "active"
    script = MT.get_script("conductor", 1)
    bodies = [m["body"] for m in state["messages"]]
    assert bodies == [script.opening[0]]

    svc.turn(uid, "conductor", "Second time: I start with people, not tasks.")
    svc.turn(uid, "conductor", "Second time: people first, whatever the deadline says.")
    # UPDATED for the adaptivity fix: the answering turn completes
    # the rerun on recognition.
    state = svc.turn(uid, "conductor", "Yes, that's the shape of it.")
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


def test_the_record_is_never_quoted_back_in_dialogue(ve_ctx, tmp_path):
    """Redesign (2026-10-23), strengthened by the adaptivity fix: the
    dialogue never quotes the read-back or the user's answer back at
    them — the self-quoting audit log was purged from the Weaver's
    dialogue entirely, and the pause that once carried it is retired.
    The full verbatim texts live on the record and in review
    (interface layer); in the room, each is spoken exactly once: the
    claim by the Weaver, the answer by the user."""
    uid = _seeded_user()
    long_answer = (
        "I decide by writing the whole tangle down first, then I sleep on "
        "it, then I ask the one person who will tell me the truth even "
        "when it stings, and only then do I actually choose anything."
    )
    svc = _svc(tmp_path, FakeGen())
    svc.start(uid, "conductor")
    svc.turn(uid, "conductor", long_answer)
    # UPDATED for the Weaver pattern: a second substantive turn
    # carries the read (the gate), then the answer closes it.
    svc.turn(uid, "conductor", "And honestly, the sleeping on it is the part I never skip.")
    state = svc.turn(uid, "conductor", "Close enough.")
    assert state["stage"] == "complete"  # recognition closed it
    bodies = [m["body"] for m in state["messages"]]
    assert bodies.count(long_answer) == 1  # the user's own bubble only
    claim = svc.meetings.get(uid, "conductor", 1)["readback_claim"]
    assert bodies.count(claim) == 1  # the read-back bubble only
    assert not any("the heart of my first impression" in b for b in bodies)
    assert not any("waits in your review" in b for b in bodies)


def test_weave_markers_never_reach_dialogue_or_the_record(ve_ctx, tmp_path, monkeypatch):
    """REWRITTEN for the Mad Lib ruling (Joshua, 2026-10-23): the old
    contract kept [[u]] markers in the spoken claim and on the record
    (for the client's amber rendering) and stripped them only where
    the record was quoted back. That structure is gone. Evidence and
    expression are separate layers now: no frame asks for weaving,
    and when a model emits markers anyway — splicing the user's
    first-person phrases into her sentences, exactly the failure
    this guards — the runtime strips the markup from everything she
    speaks AND from the stored claim. The words survive; the splice
    markup does not. (The user's own verbatim texts, stored as
    evidence, are never touched by this.) The pulled-item templates
    are retired from dialogue entirely: even a template-bearing
    script produces no quoted-record bubble.
    """

    class WovenGen:
        def __init__(self):
            self.prompts: list[str] = []

        def __call__(self, prompt, **kwargs):
            self.prompts.append(prompt)
            if "READ-BACK" in prompt:
                return (
                    "A first impression, plainly put: you lead from "
                    "[[u]]intuition based usually[[/u]], and you only shift "
                    "tracks when [[u]]there's something practical pressing "
                    "hard on the day, the kind of tangle that has to be "
                    "written down in full before it can be slept on[[/u]] "
                    "— tell me where that reading is wrong."
                    "\nStrands: Compass, Logic"
                )
            if "ENCOUNTER" in prompt:
                return "An engaged reply that hears two tensions together."
            return "A plain reply."

    # A template-bearing script (the pre-redesign shape): the runtime
    # must never format it into dialogue now.
    quoting_script = dataclasses.replace(
        MT.CONDUCTOR_FIRST_MEETING,
        pulled_item_template=(
            "Here is the one thing I pulled from it \u2014 the heart of "
            "my first impression: \u201c{claim}\u201d And the heart of "
            "your answer: \u201c{response}\u201d"
        ),
    )
    monkeypatch.setitem(MT.SCRIPTS, ("conductor", 1), quoting_script)

    uid = _seeded_user()
    svc = _svc(tmp_path, WovenGen())
    svc.start(uid, "conductor")
    svc.turn(
        uid, "conductor",
        "Intuition based usually, unless something practical is pressing.",
    )
    # UPDATED for the Weaver pattern: the woven impression rides
    # the second substantive turn (the gate holds the first), and
    # the answer turn closes the meeting.
    svc.turn(uid, "conductor", "Close enough.")
    state = svc.turn(uid, "conductor", "Close enough.")
    assert state["stage"] == "complete"
    bodies = [m["body"] for m in state["messages"]]
    # No marker — whole, severed, or malformed — in anything spoken.
    assert not any("[[" in b or "[/u" in b for b in bodies)
    # No pulled-item bubble exists to leak through.
    assert not any("the heart of my first impression" in b for b in bodies)
    # The woven words themselves survive in her claim; only the
    # markup is gone — in the bubble and on the record alike.
    assert any("intuition based usually" in b for b in bodies)
    row = svc.meetings.get(uid, "conductor", 1)
    assert "[[" not in row["readback_claim"]
    assert "intuition based usually" in row["readback_claim"]
    assert "there's something practical pressing" in row["readback_claim"]


def test_strip_weave_markers_keeps_words_drops_markup():
    """Unit coverage for the stripper: canonical pairs, the malformed
    closings sanitize_weave tolerates, and plain text passthrough."""
    from local_ai.conversation.weave import strip_weave_markers as _strip_weave_markers

    assert _strip_weave_markers("lead from [[u]]your words[[/u]] here") == \
        "lead from your words here"
    assert _strip_weave_markers("a [[u]]span[/u]] b") == "a span b"
    assert _strip_weave_markers("a [[u]]span[/[/u]] b") == "a span b"
    assert _strip_weave_markers("no markers at all") == "no markers at all"
    assert _strip_weave_markers("") == ""


def test_ok_sounds_good_closes_on_recognition(ve_ctx, tmp_path):
    """REWRITTEN for the adaptivity fix (the live-run break, in its
    new form): 'Ok sounds good' answering the impression must be
    received as the acknowledgment it is — one brief generated
    reply, then the reveal — never answered as if it were a
    question, and never with an improvised second introduction.
    (The orientation beat it once stumbled into no longer exists;
    and acks now generate precisely so the close decision is the
    model's semantic judgment, not a phrase match.)"""
    uid = _seeded_user()
    gen = FakeGen()
    svc = _svc(tmp_path, gen)
    svc.start(uid, "conductor")
    svc.turn(uid, "conductor", "I plan in pencil and improvise in ink.")
    # UPDATED for the Weaver pattern: a second substantive turn
    # carries the read before the acknowledgment can answer it.
    svc.turn(uid, "conductor", "I plan in pencil and improvise in ink — the ink is where it gets real.")
    prompts_before = len(gen.prompts)
    state = svc.turn(uid, "conductor", "Ok sounds good")
    assert state["status"] == "complete"
    new_prompts = gen.prompts[prompts_before:]
    assert len(new_prompts) == 1  # exactly one generation: her reply
    assert not any("ORIENTATION" in p for p in new_prompts)
    bodies = [m["body"] for m in state["messages"]]
    script = MT.get_script("conductor", 1)
    for paragraph in script.reveal:
        assert paragraph in bodies
