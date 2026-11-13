"""Sticky seat unlock (Joshua's rule, 2026-10-30: "Once it's open it
should stay open") — sticky ACCESS, not sticky markers (entry-seat
correction, disposition point 1).

Once a seat's begin door has become available — when the Guardian's
(the entry seat's) keystone 1 completed — it stays available even if
the Guardian's task later returns to Todo (Guardian restart or Reopen
toggle): the door sticks via seat_unlocks, which the begin guard
consults. The MARKERS follow current keystone state instead: a
reopened entry keystone re-lights "intro" on the Guardian and the
"meet" marker goes dark, while every previously unlocked door stays
beginnable. What stays unchanged: the Guardian's OWN restart
semantics (its door/face revert until its new run completes),
never-opened seats (locked behind Guardian-first ordering until the
Guardian completes), and the availability sets (released / held /
unreleased).

Fixture pattern copied from tests/test_meetings.py (temp SQLite DBs,
fake generation) and tests/test_keystone_attention.py (temp VE DB).
"""
from __future__ import annotations

import threading

import pytest

from local_ai.council import meetings as MT
from local_ai.conversation.meeting import MeetingError, MeetingService, MeetingStore
from local_ai.conversation.store import ConversationStore
from local_ai.council import naming
from local_ai import activity as activity_mod
from local_ai.vision_execution import keystone_seeding
from local_ai.vision_execution import models as M
from local_ai.vision_execution import service as ve

SEAT_REFS = [s["seat_ref"] for s in keystone_seeding.KD.SEATS]
SIX = [r for r in SEAT_REFS if r != keystone_seeding.ENTRY_SEAT_REF]


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    """Isolate the vision-execution SQLite DB per test."""
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


_TEACHING_SENTENCE = (
    "My ground is the council and the tree, where parts of your "
    "life need hearing together; bring me the competing priorities "
    "that will not sit together; every new voice changes what the "
    "whole orchestra can play, and I keep the whole of it in ear."
)


def _teaching(gen):
    def wrapper(prompt, **kwargs):
        out = gen(prompt, **kwargs)
        lines = out.split("\n")
        for i, line in enumerate(lines):
            if line.strip().lower().startswith("strands:"):
                lines.insert(i, _TEACHING_SENTENCE)
                break
        else:
            lines.append(_TEACHING_SENTENCE)
        return "\n".join(lines)

    return wrapper


def _svc(tmp_path):
    return MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
        generate_fn=_teaching(FakeGen()),
    )


def _seeded_user(email="sticky@example.com"):
    user = ve.create_user_account(email, "pw", "Sticky")
    keystone_seeding.seed_meet_your_council(user["id"])
    return user["id"]


def _seat_tasks(user_id, seat_ref):
    tasks = [t for t in ve.list_tasks(user_id) if t.get("seat_ref") == seat_ref]
    return keystone_seeding._chain_order(tasks)


def _set_task(user_id, seat_ref, index, status):
    task = _seat_tasks(user_id, seat_ref)[index]
    ve.update_task(task["id"], M.TaskUpdate(status=status), user_id)


def _lit(user_id):
    state = keystone_seeding.keystone_attention(user_id)
    return {
        ref: m["reason"] for ref, m in state["markers"].items() if m["attention"]
    }


def _run_guardian_to_completion(svc, uid):
    """Drive the Guardian's (entry seat's) meeting to its close
    (test_meetings pattern)."""
    svc.start(uid, "guardian")
    svc.turn(uid, "guardian", "I work by deadlines first, then everything else follows.")
    svc.turn(
        uid,
        "guardian",
        "And in my own work it's the same — what breaks first gets my hands first.",
    )
    state = svc.turn(uid, "guardian", "That's right.")
    if state["status"] != "complete":
        state = svc.turn(uid, "guardian", "Got it.")
    if state["status"] != "complete":
        state = svc.complete(uid, "guardian")
    assert state["status"] == "complete"
    return state


# ------------------------------------------------------------------ (a)


def test_restart_keeps_six_doors_open(ve_ctx, tmp_path):
    """Guardian Done → "meet" offered on the Conductor only, six doors
    open → Guardian restart → doors STILL open, markers follow state."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _run_guardian_to_completion(svc, uid)
    # One-at-a-time offering: only the next seat in JOURNEY_ORDER.
    assert _lit(uid) == {"conductor": "meet"}
    for ref in SIX:
        assert keystone_seeding.seat_unlocked(uid, ref) is True

    svc.restart(uid, "guardian")

    # Sticky access: every previously opened door stays open...
    for ref in SIX:
        assert keystone_seeding.seat_unlocked(uid, ref) is True
    # ...while markers follow current state: "intro" re-lights on the
    # Guardian and "meet" goes dark.
    assert _lit(uid) == {"guardian": "intro"}
    # Guardian's own state reverts (its restart semantics unchanged):
    # face locked again.
    assert naming.keystone_one_done(uid, "guardian") is False


# ------------------------------------------------------------------ (b)


def test_reopen_toggle_keeps_six_doors_open(ve_ctx):
    """Guardian Done (bare toggle) → doors open → Reopen toggle →
    doors STILL open; markers follow current state.

    The toggle path is the critical one: it emits no meeting event,
    so a derivation from meeting_completed events alone would miss
    it. The recording hook lives on the task update itself, so the
    toggle records exactly like a genuine completion.
    """
    uid = _seeded_user()
    _set_task(uid, "guardian", 0, "Done")
    assert _lit(uid) == {"conductor": "meet"}
    for ref in SIX:
        assert keystone_seeding.seat_unlocked(uid, ref) is True

    _set_task(uid, "guardian", 0, "Todo")

    for ref in SIX:
        assert keystone_seeding.seat_unlocked(uid, ref) is True
    assert _lit(uid) == {"guardian": "intro"}


# ------------------------------------------------------------------ (c)


def test_in_progress_six_meeting_keeps_door_after_guardian_reset(ve_ctx, tmp_path):
    """A begun six meeting keeps its door after the Guardian resets."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _set_task(uid, "guardian", 0, "Done")
    started = svc.start(uid, "mentor")
    assert started["status"] == "active"

    _set_task(uid, "guardian", 0, "Todo")

    # Door still open (the begin guard consults the sticky record)
    # and the row still active (resume needs no begin check, so the
    # overlay reopens it). The "meet" marker follows current state:
    # it is dark while the Guardian's intro is outstanding again.
    assert keystone_seeding.seat_unlocked(uid, "mentor") is True
    assert _lit(uid) == {"guardian": "intro"}
    row = svc.meetings.get(uid, "mentor", 1)
    assert row is not None and row["status"] == "active"
    assert svc.state(uid, "mentor")["status"] == "active"


# ------------------------------------------------------------------ (d)


def test_never_opened_stays_locked_before_guardian_completes(ve_ctx):
    """Fresh account: no six doors, and the begin guard refuses."""
    uid = _seeded_user()
    assert _lit(uid) == {"guardian": "intro"}
    for ref in SIX:
        assert keystone_seeding.seat_unlocked(uid, ref) is False


def test_begin_guard_refuses_never_opened(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    with pytest.raises(MeetingError, match="meet her first"):
        svc._check_beginnable(uid, "mentor", 1)


# ------------------------------------------------------------------ (e)


def test_guardian_own_door_reverts_on_restart(ve_ctx, tmp_path):
    """The Guardian's own restart semantics are unchanged by stickiness.

    After its own restart, the Guardian's door returns to the
    pre-completion Begin-fresh state (intro marker, face locked) — it
    does NOT keep a revisit door — while the six doors stay open. The
    entry seat is never recorded as unlocked.
    """
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _run_guardian_to_completion(svc, uid)
    assert naming.keystone_one_done(uid, "guardian") is True

    svc.restart(uid, "guardian")

    assert keystone_seeding.seat_unlocked(uid, "guardian") is False
    assert _lit(uid)["guardian"] == "intro"
    assert naming.keystone_one_done(uid, "guardian") is False
    for ref in SIX:
        assert keystone_seeding.seat_unlocked(uid, ref) is True


# ------------------------------------------------------------------ guard


def test_begin_guard_allows_previously_unlocked_after_reset(ve_ctx, tmp_path):
    """A lit door must actually begin: the guard consults the record.

    Without this, the sticky door would lead to a refusal — a door
    that cannot begin is not "open". The availability sets are
    untouched; only the entry condition gains the sticky exception.
    """
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _set_task(uid, "guardian", 0, "Done")
    _set_task(uid, "guardian", 0, "Todo")

    script = svc._check_beginnable(uid, "mentor", 1)
    assert script is not None
    assert MT.get_script("mentor", 1) is not None


# ------------------------------------------------------------------ misc


def test_toggle_only_completion_records_unlock(ve_ctx):
    """A Done flip on a NON-entry task records nothing."""
    uid = _seeded_user()
    _set_task(uid, "mentor", 0, "Done")
    for ref in SIX:
        assert keystone_seeding.seat_unlocked(uid, ref) is False
    assert _lit(uid) == {"guardian": "intro"}


def test_unlock_is_per_user(ve_ctx):
    """One user's unlock never leaks to another user's tree."""
    u1 = _seeded_user("one@example.com")
    u2 = _seeded_user("two@example.com")
    _set_task(u1, "guardian", 0, "Done")
    assert _lit(u1) == {"conductor": "meet"}
    for ref in SIX:
        assert keystone_seeding.seat_unlocked(u1, ref) is True
    assert _lit(u2) == {"guardian": "intro"}
    for ref in SIX:
        assert keystone_seeding.seat_unlocked(u2, ref) is False


def test_rerecord_is_idempotent_and_recompletion_reopens(ve_ctx):
    """Done → Todo → Done re-records harmlessly; doors never flicker."""
    uid = _seeded_user()
    _set_task(uid, "guardian", 0, "Done")
    assert _lit(uid) == {"conductor": "meet"}
    _set_task(uid, "guardian", 0, "Todo")
    # Doors stay open via the record; the marker follows state.
    for ref in SIX:
        assert keystone_seeding.seat_unlocked(uid, ref) is True
    assert _lit(uid) == {"guardian": "intro"}
    _set_task(uid, "guardian", 0, "Done")
    assert _lit(uid) == {"conductor": "meet"}
    # The guardian is mid-chain after recompletion ([Done, Todo, Todo,
    # Todo]) and carries no marker — "meet" lights only while a seat's
    # first keystone is undone (deliberate semantics change, 2026-11-05).
    assert "guardian" not in _lit(uid)


# ------------------------------------------------------------------ waivers
# C-3 + addendum §1: a waiver is recorded at the waiver operation —
# the explicit "I already know" marker carried into the task update —
# never inferred from a bare toggle. The record is a task_waived entry
# in the VE entity-activity log, distinguishable by query (its type)
# from the task_completed entry a genuine meeting close produces.


@pytest.fixture()
def activity_records(monkeypatch):
    """Intercept the activity log: record calls instead of writing
    (test_fellowship_observations pattern)."""
    records: list[dict] = []

    def _fake_log(**kwargs):
        records.append(kwargs)
        return f"evt-{len(records)}"

    monkeypatch.setattr(activity_mod, "log_activity_simple", _fake_log)
    return records


def _waive(uid, seat_ref):
    """The waiver operation: "I already know" + the Done flip."""
    task = _seat_tasks(uid, seat_ref)[0]
    ve.update_task(task["id"], M.TaskUpdate(status="Done", waiver=True), uid)
    return task


def _waiver_records(records, task_id):
    return [
        r for r in records
        if r.get("type") == "task_waived" and r.get("entity_id") == task_id
    ]


def test_waiver_records_event_and_done(ve_ctx, activity_records):
    uid = _seeded_user()
    task = _waive(uid, "champion")
    assert _seat_tasks(uid, "champion")[0]["status"] == "Done"
    hits = _waiver_records(activity_records, task["id"])
    assert len(hits) == 1
    assert hits[0]["actor"] == uid
    assert hits[0]["source"] == "vision_execution"
    assert "champion" in hits[0]["detail"]
    assert "I already know" in hits[0]["detail"]


def test_waiver_out_of_order_changes_only_that_seat(ve_ctx, activity_records):
    """Waiving a later seat while the Guardian's K1 is Todo succeeds;
    only that seat's K1 changes; no unlock rows (non-entry waiver)."""
    uid = _seeded_user()
    _waive(uid, "champion")
    for ref in SEAT_REFS:
        expected = "Done" if ref == "champion" else "Todo"
        assert _seat_tasks(uid, ref)[0]["status"] == expected, ref
    for ref in SIX:
        assert keystone_seeding.seat_unlocked(uid, ref) is False
    # No marker beyond the Guardian's own intro.
    assert _lit(uid) == {"guardian": "intro"}


def test_waiver_distinguishable_from_meeting_close(ve_ctx, activity_records):
    """The waiver entry's type separates it by query from the
    task_completed entry logged for the same flip."""
    uid = _seeded_user()
    task = _waive(uid, "mentor")
    types = [r.get("type") for r in activity_records if r.get("entity_id") == task["id"]]
    assert "task_waived" in types
    assert "task_completed" in types  # the flip itself is still logged


def test_generic_toggle_is_not_a_waiver(ve_ctx, activity_records):
    """Negative (addendum §1.3): a K1 Done via the bare toggle, with
    no waiver marker, records NO waiver event — provenance unknown,
    never inferred."""
    uid = _seeded_user()
    task = _seat_tasks(uid, "guardian")[0]
    ve.update_task(task["id"], M.TaskUpdate(status="Done"), uid)
    assert _seat_tasks(uid, "guardian")[0]["status"] == "Done"
    assert _waiver_records(activity_records, task["id"]) == []


def test_genuine_completion_is_not_a_waiver(ve_ctx, tmp_path, activity_records):
    """_do_reveal calls update_task without the waiver marker, so a
    genuine meeting close records no waiver event."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _run_guardian_to_completion(svc, uid)
    task = _seat_tasks(uid, "guardian")[0]
    assert task["status"] == "Done"
    assert _waiver_records(activity_records, task["id"]) == []


def test_waiving_entry_seat_records_unlocks_only(ve_ctx, activity_records):
    """Waiving the Guardian's K1 opens the six doors (sticky access)
    and marks no other seat's K1 Done."""
    uid = _seeded_user()
    _waive(uid, "guardian")
    for ref in SIX:
        assert keystone_seeding.seat_unlocked(uid, ref) is True
        assert _seat_tasks(uid, ref)[0]["status"] == "Todo", ref
    # The marker moves to the next unfinished seat in JOURNEY_ORDER.
    assert _lit(uid) == {"conductor": "meet"}


def test_waived_entry_k1_counts_as_done_for_the_gate(ve_ctx, tmp_path, activity_records):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _waive(uid, "guardian")
    script = svc._check_beginnable(uid, "mentor", 1)
    assert script is not None
