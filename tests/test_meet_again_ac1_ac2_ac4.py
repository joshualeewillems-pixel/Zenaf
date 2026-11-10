"""AC1 / AC2 / AC4 — the replacement for the PR #308 restart suite.

PR #308 (tests/test_meeting_restart_archive.py, 15 tests) verified the
delete-based restart: archive the full transcript, verified complete,
then clear + delete. That implementation is SUPERSEDED by the
non-destructive Meet Again (founder decision 2026-11-09 ~17:30 PT):
there is no delete to verify, because nothing is ever deleted. These
tests replace that suite (AC10): they prove the same preservation
properties in the non-destructive model — the successor leaves the
predecessor byte-identical (AC1), runs have distinct conversation ids
with disjoint message sets (AC2), and the run chain walks 3 -> 2 -> 1
(AC4) — plus the history-paging test carried over unchanged (it is not
a restart-behavior test).

Replacement record (PR #308 test -> replacement):
- test_restart_archives_full_transcript (201/500/2500) ->
  test_ac1_successor_leaves_predecessor_byte_identical (the full
  transcript is preserved because nothing is ever deleted, not
  because it was archived-then-cleared)
- test_restart_same_timestamp_tie_order -> test_ac1 (the predecessor
  keeps its own identity and order; the successor is a new run)
- test_short_meetings_unchanged -> test_ac1 (a short predecessor is
  equally untouched)
- test_restart_zero_rows -> test_ac1_failed_meet_again_leaves_predecessor_intact
  (a refused Meet Again creates nothing)
- test_page_read_failure_aborts_intact, test_count_mismatch_aborts_intact,
  test_id_mismatch_aborts_intact -> test_ac1_failed_meet_again_leaves_predecessor_intact
  (the abort-intact property is now: a refused Meet Again creates
  nothing and the predecessor is untouched; the read-consistency
  check's failure mode is covered by T-MIG-6)
- test_archive_write_failure_aborts_before_clear,
  test_clear_failure_leaves_complete_archive_and_live_rows -> (no
  counterpart: there is no archive-then-clear step to fail; the
  atomic finalize + the fence are covered by T-S2-8 and T-S1)
- test_history_offset_default_is_byte_identical -> carried over
  verbatim below.
"""

from __future__ import annotations

import json
import sqlite3
import threading

import pytest

from local_ai.conversation.meeting import (
    MeetingError,
    MeetingService,
    MeetingStore,
    MeetingValidationError,
    conversation_id_for,
)
from local_ai.conversation.store import ConversationStore
from local_ai.vision_execution import keystone_seeding
from local_ai.vision_execution import service as ve

ARCH = "maverick"


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


def _seeded_user(email="ac1-ac2-ac4@example.com"):
    user = ve.create_user_account(email, "pw", "AC")
    keystone_seeding.seed_meet_your_council(user["id"])
    return user["id"]


def _complete_conductor(svc, uid):
    """Drive the Weaver's meeting to its close."""
    svc.start(uid, "conductor")
    svc.turn(uid, "conductor", "I work by deadlines first, then everything else follows.")
    svc.turn(
        uid, "conductor",
        "And in my own work it's the same — what breaks first gets my hands first.",
    )
    state = svc.turn(uid, "conductor", "That's right.")
    if state["status"] != "complete":
        state = svc.turn(uid, "conductor", "Got it.")
    if state["status"] != "complete":
        state = svc.complete(uid, "conductor")
    assert state["status"] == "complete"
    return state


def _completed_meeting(svc, uid, n, arch=ARCH):
    """A completed meeting row plus n live message rows. Returns the cid."""
    svc.meetings.create(uid, arch, 1)
    svc.meetings.update(
        uid, arch, 1,
        status="complete",
        stage="complete",
        readback_claim="Run read-back.",
        readback_response="That's right.",
        readback_strands=json.dumps(["Compass"]),
    )
    cid = conversation_id_for(arch, 1)
    svc.conversations.ensure_conversation(uid, cid, kind="meeting")
    for i in range(n):
        role = "user" if i % 2 == 0 else "voice"
        svc.conversations.append_message(uid, cid, arch, role, f"message {i}",
                                         via_meeting=True)
    return cid


def _live_rows(tmp_path, uid, cid):
    """Live rows via an independent connection, in original order."""
    conn = sqlite3.connect(tmp_path / "conv.db")
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, role, body, created_at FROM messages "
            "WHERE user_id = ? AND conversation_id = ? "
            "ORDER BY created_at ASC, id ASC",
            (uid, cid),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def _messages(svc, uid, cid):
    return svc.conversations.history(uid, cid, limit=500)


def test_ac1_successor_leaves_predecessor_byte_identical(ve_ctx, tmp_path):
    """AC1: the successor leaves the predecessor byte-identical — its
    encounter row, its transcript, and the archive rows are untouched,
    before and after the successor itself completes."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _complete_conductor(svc, uid)
    run1 = svc.meetings.get_latest_encounter(uid, "conductor", 1)
    pred_row_before = dict(run1)
    pred_msgs_before = _messages(svc, uid, run1["conversation_id"])
    pred_live_before = _live_rows(tmp_path, uid, run1["conversation_id"])
    archives_before = svc.meetings.list_archives(uid, "conductor", 1)

    out = svc.meet_again(
        uid, "conductor", 1,
        predecessor_run_id=run1["run_id"], request_id="req-ac1",
    )
    run2 = out["encounter"]
    assert dict(svc.meetings.get_encounter(uid, run1["run_id"])) == pred_row_before
    assert _messages(svc, uid, run1["conversation_id"]) == pred_msgs_before
    assert _live_rows(tmp_path, uid, run1["conversation_id"]) == pred_live_before
    assert svc.meetings.list_archives(uid, "conductor", 1) == archives_before

    # The successor runs to completion — the predecessor is still identical.
    _complete_conductor(svc, uid)
    assert svc.meetings.get_latest_encounter(uid, "conductor", 1)["run_id"] == run2["run_id"]
    assert dict(svc.meetings.get_encounter(uid, run1["run_id"])) == pred_row_before
    assert _messages(svc, uid, run1["conversation_id"]) == pred_msgs_before
    assert _live_rows(tmp_path, uid, run1["conversation_id"]) == pred_live_before


def test_ac1_failed_meet_again_leaves_predecessor_intact(ve_ctx, tmp_path):
    """AC1 (abort-intact, the non-destructive form): a refused Meet
    Again creates nothing and the predecessor is untouched."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _complete_conductor(svc, uid)
    run1 = svc.meetings.get_latest_encounter(uid, "conductor", 1)
    pred_row_before = dict(run1)
    pred_msgs_before = _messages(svc, uid, run1["conversation_id"])

    # An unknown predecessor refuses (422) and creates nothing.
    with pytest.raises(MeetingValidationError):
        svc.meet_again(
            uid, "conductor", 1,
            predecessor_run_id="no-such-run", request_id="req-fail-1",
        )
    assert len(svc.list_encounters(uid, "conductor", 1)) == 1
    assert dict(svc.meetings.get_encounter(uid, run1["run_id"])) == pred_row_before
    assert _messages(svc, uid, run1["conversation_id"]) == pred_msgs_before

    # An in-progress predecessor refuses (409) and creates nothing.
    svc.meet_again(
        uid, "conductor", 1,
        predecessor_run_id=run1["run_id"], request_id="req-ok-2",
    )
    run2 = svc.meetings.get_latest_encounter(uid, "conductor", 1)
    run2_row_before = dict(run2)
    with pytest.raises(MeetingError) as exc_info:
        svc.meet_again(
            uid, "conductor", 1,
            predecessor_run_id=run2["run_id"], request_id="req-fail-2",
        )
    assert exc_info.value.code == "encounter_in_progress"
    assert len(svc.list_encounters(uid, "conductor", 1)) == 2
    assert dict(svc.meetings.get_encounter(uid, run1["run_id"])) == pred_row_before
    assert dict(svc.meetings.get_encounter(uid, run2["run_id"])) == run2_row_before
    assert _messages(svc, uid, run1["conversation_id"]) == pred_msgs_before


def test_ac2_distinct_conversation_ids_disjoint_messages(ve_ctx, tmp_path):
    """AC2: each run has a distinct conversation id and the message
    sets are disjoint (by message id)."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _complete_conductor(svc, uid)
    run1 = svc.meetings.get_latest_encounter(uid, "conductor", 1)
    svc.meet_again(
        uid, "conductor", 1,
        predecessor_run_id=run1["run_id"], request_id="req-ac2-2",
    )
    _complete_conductor(svc, uid)
    run2 = svc.meetings.get_latest_encounter(uid, "conductor", 1)
    svc.meet_again(
        uid, "conductor", 1,
        predecessor_run_id=run2["run_id"], request_id="req-ac2-3",
    )
    run3 = svc.meetings.get_latest_encounter(uid, "conductor", 1)

    cids = [run1["conversation_id"], run2["conversation_id"], run3["conversation_id"]]
    assert len(set(cids)) == 3
    assert all(c.startswith("meeting-conductor-1-") for c in cids)
    id_sets = [
        {m["id"] for m in _messages(svc, uid, cid)} for cid in cids
    ]
    assert not (id_sets[0] & id_sets[1])
    assert not (id_sets[1] & id_sets[2])
    assert not (id_sets[0] & id_sets[2])
    # Every message belongs to exactly one run's conversation.
    assert len(id_sets[0]) > 0 and len(id_sets[1]) > 0 and len(id_sets[2]) > 0


def test_ac4_three_runs_chain_walks(ve_ctx, tmp_path):
    """AC4: run_number / predecessor linkage across three encounters;
    the chain walks 3 -> 2 -> 1."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _complete_conductor(svc, uid)
    run1 = svc.meetings.get_latest_encounter(uid, "conductor", 1)
    svc.meet_again(
        uid, "conductor", 1,
        predecessor_run_id=run1["run_id"], request_id="req-ac4-2",
    )
    _complete_conductor(svc, uid)
    run2 = svc.meetings.get_latest_encounter(uid, "conductor", 1)
    svc.meet_again(
        uid, "conductor", 1,
        predecessor_run_id=run2["run_id"], request_id="req-ac4-3",
    )
    run3 = svc.meetings.get_latest_encounter(uid, "conductor", 1)

    assert [r["run_number"] for r in (run1, run2, run3)] == [1, 2, 3]
    assert run2["predecessor_run_id"] == run1["run_id"]
    assert run3["predecessor_run_id"] == run2["run_id"]
    assert run1["predecessor_run_id"] is None
    chain = svc.list_encounters(uid, "conductor", 1)
    assert [e["run_number"] for e in chain] == [1, 2, 3]
    by_id = {e["run_id"]: e for e in chain}
    walk = [run3["run_id"]]
    while by_id[walk[-1]]["predecessor_run_id"]:
        walk.append(by_id[walk[-1]]["predecessor_run_id"])
    assert walk == [run3["run_id"], run2["run_id"], run1["run_id"]]


def test_history_offset_default_is_byte_identical(ve_ctx, tmp_path):
    """Carried over verbatim from the PR #308 suite (not a
    restart-behavior test): the defaulted offset changes nothing for
    existing callers, and paging reconstructs a full read."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    cid = _completed_meeting(svc, uid, 150)

    default = svc.conversations.history(uid, cid, limit=200)
    explicit = svc.conversations.history(uid, cid, limit=200, offset=0)
    assert default == explicit

    pages = []
    offset = 0
    while True:
        page = svc.conversations.history(uid, cid, limit=200, offset=offset)
        pages.append(page)
        if len(page) < 200:
            break
        offset += 200
    rebuilt = []
    for page in reversed(pages):
        rebuilt = page + rebuilt
    assert rebuilt == default
    assert len(rebuilt) == 150
