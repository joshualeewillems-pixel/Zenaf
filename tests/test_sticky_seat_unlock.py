"""Sticky seat unlock (Joshua's rule, 2026-10-30: "Once it's open it
should stay open").

Once a seat's begin door has become available — its "meet" marker lit
when the Conductor's keystone 1 completed — it stays available even if
the Conductor's task later returns to Todo (Weaver restart or Reopen
toggle). Likewise a begun six-seat meeting keeps its tree path. What
stays unchanged: Weaver's OWN restart semantics (its door/face revert
until its new run completes), never-opened seats (locked behind
Weaver-first ordering until Weaver completes), and the availability
sets (released / held / unreleased).

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


def _run_conductor_to_completion(svc, uid):
    """Drive the Weaver's meeting to its close (test_meetings pattern)."""
    svc.start(uid, "conductor")
    svc.turn(uid, "conductor", "I work by deadlines first, then everything else follows.")
    svc.turn(
        uid,
        "conductor",
        "And in my own work it's the same — what breaks first gets my hands first.",
    )
    state = svc.turn(uid, "conductor", "That's right.")
    if state["status"] != "complete":
        state = svc.turn(uid, "conductor", "Got it.")
    if state["status"] != "complete":
        state = svc.complete(uid, "conductor")
    assert state["status"] == "complete"
    return state


# ------------------------------------------------------------------ (a)


def test_restart_keeps_six_doors_lit(ve_ctx, tmp_path):
    """Weaver Done → six doors lit → Weaver restart → six STILL lit."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _run_conductor_to_completion(svc, uid)
    assert all(_lit(uid)[ref] == "meet" for ref in SIX)

    svc.restart(uid, "conductor")

    lit = _lit(uid)
    for ref in SIX:
        assert lit[ref] == "meet", ref
    # Weaver's own state reverts (its restart semantics unchanged):
    # back to the intro marker, face locked again.
    assert lit["conductor"] == "intro"
    assert naming.keystone_one_done(uid, "conductor") is False


# ------------------------------------------------------------------ (b)


def test_reopen_toggle_keeps_six_doors_lit(ve_ctx):
    """Weaver Done (bare toggle) → lit → Reopen toggle → STILL lit.

    The toggle path is the critical one: it emits no meeting event,
    so a derivation from meeting_completed events alone would miss
    it. The recording hook lives on the task update itself, so the
    toggle records exactly like a genuine completion.
    """
    uid = _seeded_user()
    _set_task(uid, "conductor", 0, "Done")
    assert all(_lit(uid)[ref] == "meet" for ref in SIX)
    for ref in SIX:
        assert keystone_seeding.seat_unlocked(uid, ref) is True

    _set_task(uid, "conductor", 0, "Todo")

    lit = _lit(uid)
    for ref in SIX:
        assert lit[ref] == "meet", ref
    assert lit["conductor"] == "intro"


# ------------------------------------------------------------------ (c)


def test_in_progress_six_meeting_keeps_door_after_weaver_reset(ve_ctx, tmp_path):
    """A begun six meeting keeps its tree path after Weaver resets."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _set_task(uid, "conductor", 0, "Done")
    started = svc.start(uid, "mentor")
    assert started["status"] == "active"

    _set_task(uid, "conductor", 0, "Todo")

    # Door still lit (the tree path back in) and the row still active
    # (resume needs no begin check, so the overlay reopens it).
    assert _lit(uid)["mentor"] == "meet"
    row = svc.meetings.get(uid, "mentor", 1)
    assert row is not None and row["status"] == "active"
    assert svc.state(uid, "mentor")["status"] == "active"


# ------------------------------------------------------------------ (d)


def test_never_opened_stays_locked_before_weaver_completes(ve_ctx):
    """Fresh account: no six doors, and the begin guard refuses."""
    uid = _seeded_user()
    assert _lit(uid) == {"conductor": "intro"}
    for ref in SIX:
        assert keystone_seeding.seat_unlocked(uid, ref) is False


def test_begin_guard_refuses_never_opened(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    with pytest.raises(MeetingError, match="meet them first"):
        svc._check_beginnable(uid, "mentor", 1)


# ------------------------------------------------------------------ (e)


def test_weaver_own_door_reverts_on_restart(ve_ctx, tmp_path):
    """Weaver's own restart semantics are unchanged by stickiness.

    After its own restart, Weaver's door returns to the pre-completion
    Begin-fresh state (intro marker, face locked) — it does NOT keep
    a revisit door — while the six stay lit. Weaver's seat is never
    recorded as unlocked.
    """
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _run_conductor_to_completion(svc, uid)
    assert naming.keystone_one_done(uid, "conductor") is True

    svc.restart(uid, "conductor")

    assert keystone_seeding.seat_unlocked(uid, "conductor") is False
    assert _lit(uid)["conductor"] == "intro"
    assert naming.keystone_one_done(uid, "conductor") is False
    for ref in SIX:
        assert _lit(uid)[ref] == "meet", ref


# ------------------------------------------------------------------ guard


def test_begin_guard_allows_previously_unlocked_after_reset(ve_ctx, tmp_path):
    """A lit door must actually begin: the guard consults the record.

    Without this, the sticky door would lead to a refusal — a door
    that cannot begin is not "open". The availability sets are
    untouched; only the entry condition gains the sticky exception.
    """
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _set_task(uid, "conductor", 0, "Done")
    _set_task(uid, "conductor", 0, "Todo")

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
    assert _lit(uid) == {"conductor": "intro"}


def test_unlock_is_per_user(ve_ctx):
    """One user's unlock never leaks to another user's tree."""
    u1 = _seeded_user("one@example.com")
    u2 = _seeded_user("two@example.com")
    _set_task(u1, "conductor", 0, "Done")
    assert all(_lit(u1)[ref] == "meet" for ref in SIX)
    assert _lit(u2) == {"conductor": "intro"}
    for ref in SIX:
        assert keystone_seeding.seat_unlocked(u2, ref) is False


def test_rerecord_is_idempotent_and_recompletion_reopens(ve_ctx):
    """Done → Todo → Done re-records harmlessly; doors never flicker."""
    uid = _seeded_user()
    _set_task(uid, "conductor", 0, "Done")
    _set_task(uid, "conductor", 0, "Todo")
    assert all(_lit(uid)[ref] == "meet" for ref in SIX)
    _set_task(uid, "conductor", 0, "Done")
    assert all(_lit(uid)[ref] == "meet" for ref in SIX)
    assert _lit(uid)["conductor"] == "meet"
