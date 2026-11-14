"""Slice 6 tests: completion recovery at every durable boundary
(AC24) + the safeguard tests' service-level counterparts.

Proposal §3 (the completion-recovery gate): the corrected _do_reveal
order is reveal (1) -> task Done (2) -> emit (3) -> impression (4)
-> fence close (5) -> atomic finalize (6). A crash at each boundary
must heal by re-running _do_reveal (CR-B1…B4) or by the fence-closed
recovery rule (CR-B5), never by speaking twice, filing twice, or
representing the encounter as finished while work is outstanding.
CR-B6: the finalize transaction is atomic — either it commits fully
or it rolls back fully.

- T-CR-1  CR-B1: a partially spoken reveal re-runs insert-if-absent —
  exactly one copy of each reveal paragraph
- T-CR-2  CR-B2: reveal spoken, task not Done — the re-run completes
  (reveal no-op, task Done, one claim)
- T-CR-3  CR-B3: task Done, impression not filed — the re-run files
  exactly once and completes
- T-CR-4  CR-B4: impression filed, fence open — the re-run closes the
  fence and completes with exactly one claim
- T-CR-5  CR-B5: fence closed, finalized_at NULL — the recovery
  finalizes from the recorded artifacts (see also T-S2-10)
- T-CR-6  CR-B6: a forced failure inside the finalize transaction
  rolls back fully — nothing landed
- T-CR-7  Deterministic termination (amendment §A5 pattern): the
  completion is SIGKILLed at each durable boundary (sync points);
  the recovery heals it to complete with no duplicates

The safeguard tests T-S1/T-S2/T-S3 (AC21/AC22/AC23) live in
tests/test_meet_again_slice1_store.py (T-S1-1..T-S1-5,
T-S2-1..T-S2-2, T-S3-1..T-S3-4) — they are the service/store-level
proofs and are not duplicated here.
"""

from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time

import pytest

import local_ai.conversation.meeting as meeting_mod
from local_ai.conversation import encounter as ENC
from local_ai.conversation.meeting import (
    MeetingService,
    MeetingStore,
    _seat_keystone_tasks,
)
from local_ai.conversation.store import ConversationStore
from local_ai.council import meetings as MT
from local_ai.vision_execution import keystone_seeding
from local_ai.vision_execution import service as ve


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    """Isolate the vision-execution SQLite DB per test."""
    import local_ai.vision_execution.storage as ve_store

    monkeypatch.setattr(ve_store, "_DB_PATH", tmp_path / "ve.db")
    monkeypatch.setattr(ve_store, "_DB_DIR", tmp_path)
    monkeypatch.setattr(ve_store, "_init_done_paths", set())
    monkeypatch.setattr(ve_store, "_thread_local", threading.local())
    return {}


def _svc(tmp_path):
    return MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
        generate_fn=lambda prompt, **kwargs: "A plain reply.",
    )


def _seeded_user(email="cr@example.com"):
    user = ve.create_user_account(email, "pw", "CR")
    keystone_seeding.seed_meet_your_council(user["id"])
    return user["id"]


def _start_conductor(svc, uid):
    svc.start(uid, "conductor")
    svc.turn(uid, "conductor", "I work by deadlines first, then everything else follows.")


def _reveal_bodies(svc, uid, cid):
    """The reveal paragraphs in the transcript, by their durable
    message_key (reveal:{run}:{i}) — read through an independent
    connection so the test does not assume what it is proving.
    Ordered by rowid (insertion order): the message `id` is a uuid,
    so ORDER BY id would scramble it."""
    run_id = cid.rsplit("-", 1)[-1]
    conn = sqlite3.connect(svc.conversations.db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT body FROM messages WHERE user_id = ? AND conversation_id = ? "
            "AND message_key LIKE ? ORDER BY rowid ASC",
            (uid, cid, f"reveal:{run_id}:%"),
        ).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]


def _claims(svc, uid):
    # The filing writes to the default-path AgentStore (the same
    # store the intake routes read), as in T-S2-14; the user id is
    # unique per test, so there is no cross-talk.
    from local_ai.agent_intake.store import AgentStore

    return AgentStore(user_id=uid).get_claims("meeting-conductor-1")


def _boundary_state(svc, uid, reveal=True, task_done=False, claim_filed=False):
    """Construct a _do_reveal boundary state by hand: start the
    meeting, speak the reveal paragraphs under their durable
    identities (simulating a crash mid-reveal or after it), mark
    the task Done, and/or file the impression — then return the
    encounter for the re-run under test."""
    _start_conductor(svc, uid)
    enc = svc.meetings.get_latest_encounter(uid, "conductor", 1)
    script = MT.get_script("conductor", 1)
    cid = enc["conversation_id"]
    # The read-back the host recorded when the impression was offered
    # (the filing reads it from the meetings row).
    svc.meetings.update(
        uid, "conductor", 1,
        readback_claim="A first impression, spoken before the crash.",
        readback_response="That's right.",
        readback_strands=json.dumps(["Compass", "Logic"]),
    )
    if reveal:
        # The wrap line is empty for a silent (decoupled) close; the
        # script's reveal paragraphs carry reveal:{run}:1..n.
        for i, paragraph in enumerate(script.reveal):
            svc._say(
                uid, cid, "conductor", paragraph,
                message_key=f"reveal:{enc['run_id']}:{i + 1}",
            )
    if task_done:
        tasks = _seat_keystone_tasks(uid, "conductor")
        from local_ai.vision_execution import models as ve_models

        ve.update_task(tasks[0]["id"], ve_models.TaskUpdate(status="Done"), uid)
    if claim_filed:
        svc._file_impression(uid, "conductor", 1, script)
    return svc.meetings.get_latest_encounter(uid, "conductor", 1)


def test_t_cr_1_partial_reveal_reruns_insert_if_absent(ve_ctx, tmp_path):
    """T-CR-1 (CR-B1): a partially spoken reveal re-runs
    insert-if-absent — exactly one copy of each reveal paragraph."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _start_conductor(svc, uid)
    enc = svc.meetings.get_latest_encounter(uid, "conductor", 1)
    script = MT.get_script("conductor", 1)
    cid = enc["conversation_id"]
    # Only the first reveal paragraph was spoken before the crash.
    svc._say(
        uid, cid, "conductor", script.reveal[0],
        message_key=f"reveal:{enc['run_id']}:1",
    )
    svc._do_reveal(uid, "conductor", 1, script, silent_close=False)
    bodies = _reveal_bodies(svc, uid, cid)
    assert bodies == list(script.reveal)
    enc = svc.meetings.get_latest_encounter(uid, "conductor", 1)
    assert enc["status"] == "complete"


def test_t_cr_2_reveal_spoken_task_not_done(ve_ctx, tmp_path):
    """T-CR-2 (CR-B2): reveal spoken, task not Done — the re-run
    completes (reveal no-op, task Done once, one claim)."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    enc = _boundary_state(svc, uid, reveal=True, task_done=False)
    script = MT.get_script("conductor", 1)
    svc._do_reveal(uid, "conductor", 1, script, silent_close=False)
    bodies = _reveal_bodies(svc, uid, enc["conversation_id"])
    assert bodies == list(script.reveal)
    assert _seat_keystone_tasks(uid, "conductor")[0]["status"] == "Done"
    assert len(_claims(svc, uid)) == 1
    assert svc.meetings.get_latest_encounter(uid, "conductor", 1)["status"] == "complete"


def test_t_cr_3_task_done_impression_not_filed(ve_ctx, tmp_path):
    """T-CR-3 (CR-B3): task Done, impression not filed — the re-run
    files exactly once and completes."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    enc = _boundary_state(svc, uid, reveal=True, task_done=True, claim_filed=False)
    script = MT.get_script("conductor", 1)
    svc._do_reveal(uid, "conductor", 1, script, silent_close=False)
    assert len(_claims(svc, uid)) == 1
    assert _seat_keystone_tasks(uid, "conductor")[0]["status"] == "Done"
    assert svc.meetings.get_latest_encounter(uid, "conductor", 1)["status"] == "complete"


def test_t_cr_4_impression_filed_fence_open(ve_ctx, tmp_path):
    """T-CR-4 (CR-B4): impression filed, fence open — the re-run
    closes the fence and completes with exactly one claim."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    enc = _boundary_state(svc, uid, reveal=True, task_done=True, claim_filed=True)
    assert len(_claims(svc, uid)) == 1
    assert svc.conversations.get_fence_state(uid, enc["conversation_id"]) == "open"
    script = MT.get_script("conductor", 1)
    svc._do_reveal(uid, "conductor", 1, script, silent_close=False)
    assert len(_claims(svc, uid)) == 1
    assert svc.conversations.get_fence_state(uid, enc["conversation_id"]) == "closed"
    assert svc.meetings.get_latest_encounter(uid, "conductor", 1)["status"] == "complete"


def test_t_cr_5_fence_closed_not_finalized_recovers(ve_ctx, tmp_path):
    """T-CR-5 (CR-B5): fence closed, finalized_at NULL — the recovery
    finalizes from the recorded artifacts (no reveal re-spoken, no
    duplicate impression). See also T-S2-10."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    enc = _boundary_state(svc, uid, reveal=True, task_done=True, claim_filed=True)
    svc.conversations.close_fence(uid, enc["conversation_id"], enc["run_id"])
    assert svc.conversations.get_fence_state(uid, enc["conversation_id"]) == "closed"
    records = svc.recover_incomplete_encounters(uid, "conductor", 1)
    assert records and records[0]["action"] == "finalized_cr_b5"
    final = svc.meetings.get_latest_encounter(uid, "conductor", 1)
    assert final["status"] == "complete"
    assert final["finalized_at"]
    assert len(_claims(svc, uid)) == 1
    assert _reveal_bodies(svc, uid, enc["conversation_id"]) == list(
        MT.get_script("conductor", 1).reveal
    )


def test_t_cr_6_finalize_rolls_back_fully(ve_ctx, tmp_path):
    """T-CR-6 (CR-B6): a forced failure inside the finalize
    transaction rolls back fully — nothing landed (no torn
    completion record)."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    enc = _boundary_state(svc, uid, reveal=True, task_done=True, claim_filed=True)
    svc.conversations.close_fence(uid, enc["conversation_id"], enc["run_id"])
    before = dict(svc.meetings.get_encounter(uid, enc["run_id"]))
    mrow_before = dict(svc.meetings.get(uid, "conductor", 1))

    # A proxy connection that fails the meetings-row mirror UPDATE
    # (Connection.execute is read-only, so the fault is injected by
    # wrapping the connection, not by patching it).
    real_conn = svc.meetings._conn

    class _FailingConn:
        def __init__(self, real):
            self._real = real

        def __getattr__(self, name):
            return getattr(self._real, name)

        def execute(self, sql, *args, **kwargs):
            if isinstance(sql, str) and sql.strip().startswith("UPDATE meetings SET status"):
                raise sqlite3.OperationalError("injected mirror failure")
            return self._real.execute(sql, *args, **kwargs)

    svc.meetings._conn = _FailingConn(real_conn)
    try:
        with pytest.raises(sqlite3.OperationalError):
            svc.meetings.finalize_encounter(uid, enc["run_id"], message_count=4)
    finally:
        svc.meetings._conn = real_conn
    after = svc.meetings.get_encounter(uid, enc["run_id"])
    assert after["status"] == before["status"] == "in_progress"
    assert after["finalized_at"] is None
    assert after["message_count"] == before["message_count"]
    assert dict(svc.meetings.get(uid, "conductor", 1))["status"] == mrow_before["status"]
    # The state is CR-B5 (fence closed, not finalized) — the recovery
    # heals it.
    records = svc.recover_incomplete_encounters(uid, "conductor", 1)
    assert records and records[0]["action"] == "finalized_cr_b5"
    assert svc.meetings.get_latest_encounter(uid, "conductor", 1)["status"] == "complete"


_CHILD_SCRIPT = '''\
import sys, time
from pathlib import Path

tmp = Path(sys.argv[1])
uid = sys.argv[2]
boundary = sys.argv[3]
marker = Path(sys.argv[4])
sys.path.insert(0, {worktree!r})
import threading
import local_ai.vision_execution.storage as ve_store
ve_store._DB_PATH = tmp / "ve.db"
ve_store._DB_DIR = tmp
ve_store._init_done_paths = set()
ve_store._thread_local = threading.local()
import local_ai.conversation.meeting as meeting_mod
from local_ai.conversation.meeting import MeetingService, MeetingStore
from local_ai.conversation.store import ConversationStore

def _hook(name):
    if name == boundary:
        marker.write_text(name)
        time.sleep(30)

meeting_mod._COMPLETION_SYNC_HOOK = _hook
svc = MeetingService(
    ConversationStore(tmp / "conv.db"),
    MeetingStore(tmp / "meetings.db"),
    generate_fn=lambda prompt, **kwargs: "A plain reply.",
)
svc.complete(uid, "conductor")
'''


@pytest.mark.parametrize(
    "boundary",
    ["after_reveal", "after_task_done", "after_emit", "after_file", "after_fence_close"],
)
def test_t_cr_7_sigkill_at_boundary_recovers(ve_ctx, tmp_path, boundary):
    """T-CR-7 (AC24, amendment §A5 pattern): the completion is
    SIGKILLed at a durable boundary; the recovery heals it to
    complete with no duplicate reveal and exactly one claim."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _start_conductor(svc, uid)
    enc = svc.meetings.get_latest_encounter(uid, "conductor", 1)
    run_id = enc["run_id"]
    cid = enc["conversation_id"]
    # The read-back fields, so the filing has something to file.
    svc.meetings.update(
        uid, "conductor", 1,
        readback_claim="A first impression, spoken before the kill.",
        readback_response="That's right.",
        readback_strands='["Compass", "Logic"]',
    )
    worktree = str(__import__("pathlib").Path("local_ai").resolve().parent)
    script_path = tmp_path / "cr_child.py"
    script_path.write_text(
        _CHILD_SCRIPT.format(worktree=worktree)
    )
    marker = tmp_path / f"marker-{boundary}"
    proc = subprocess.Popen(
        [sys.executable, str(script_path), str(tmp_path), uid, boundary, str(marker)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 60
        while not marker.exists() and time.time() < deadline:
            if proc.poll() is not None:
                break
            time.sleep(0.2)
        assert marker.exists(), f"child never reached {boundary} (rc={proc.poll()})"
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
    # The encounter is mid-completion (in_progress, fence open or
    # closed depending on the boundary) — the recovery heals the
    # durable states (creating, fence-closed-not-finalized, partial
    # reveal). A kill before the fence closed leaves no durable trace
    # for a silent close (the conductor speaks no reveal), so the
    # meeting is still honestly active — re-running the completion
    # is the healing path there, and it must not duplicate anything.
    records = svc.recover_incomplete_encounters(uid, "conductor", 1)
    final = svc.meetings.get_latest_encounter(uid, "conductor", 1)
    if final["status"] != "complete":
        assert final["status"] == "in_progress", f"records={records}"
        svc.complete(uid, "conductor")
        final = svc.meetings.get_latest_encounter(uid, "conductor", 1)
    assert final["status"] == "complete", f"records={records}"
    assert final["finalized_at"]
    assert final["run_id"] == run_id
    # Exactly one claim, task Done, and the opening spoken once (the
    # re-run never re-speaks it). The conductor's close is silent
    # (decoupled recognition), so no reveal paragraphs are spoken.
    assert len(_claims(svc, uid)) == 1
    assert _seat_keystone_tasks(uid, "conductor")[0]["status"] == "Done"
    opening = list(
        ENC.get_definition(MT.get_script("conductor", 1)).opening
    )
    bodies = [m["body"] for m in svc.conversations.history(uid, cid, limit=200)]
    for paragraph in opening:
        assert bodies.count(paragraph) == 1
    # And a successor is creatable from the healed run.
    out = svc.meet_again(
        uid, "conductor", 1,
        predecessor_run_id=run_id, request_id=f"req-cr7-{boundary}",
    )
    assert out["encounter"]["run_number"] == 2
