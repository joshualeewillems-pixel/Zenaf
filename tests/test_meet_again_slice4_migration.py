"""Slice 4 tests: verification + migration (non-destructive Meet Again).

Proposal §4 (migration Steps 2–5, §4.1 I6 identity evidence), §3
(read-consistency check), AC5/AC6/AC16/AC17.

- T-MIG-1  migration on a fixture with archives + a live row: archive
  encounters (legacy-unverified, legacy_group_key, reconstructed
  links), the live encounter (unverified, live, the grandfathered
  shared id, run k+1), the meetings row re-pointed, fences created
  (open for in_progress, closed for complete), Step 5 verified (AC6)
- T-MIG-2  the I6 identity rule: a duplicate archive group yields
  'legacy-record' + legacy_possible_duplicate=1; a unique group
  yields 'generated-migration' (AC17)
- T-MIG-3  idempotency: running the migration twice creates nothing
  new and still verifies (AC6)
- T-MIG-4  a pre-existing materialized live row is ADOPTED (its
  run_number moves to k+1, its predecessor binds to the last archive
  encounter), never duplicated (AC6)
- T-MIG-5  the read-consistency check at completion: a normal
  completion yields read_consistency_verified with an append-only
  detail entry carrying the normative paragraph (AC16)
- T-MIG-6  AC5: a forced partial-read failure yields
  read_consistency_failed; the encounter is still complete and a
  successor is still creatable
- T-MIG-7  AC16: a failed check preserves the prior passing record
  (append-only detail history)
- T-MIG-8  AC17: the listing carries identity_kind 'legacy-record'
  for duplicate-group rows, predecessor_link_kind 'reconstructed',
  and the lineage label "follows (archive order)"
"""

from __future__ import annotations

import json
import threading

import pytest

from local_ai.conversation.meeting import (
    READ_CONSISTENCY_NORMATIVE,
    MeetingService,
    MeetingStore,
    _seat_keystone_tasks,
)
from local_ai.conversation.store import ConversationStore
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


def _seeded_user(email="s4@example.com"):
    user = ve.create_user_account(email, "pw", "S4")
    keystone_seeding.seed_meet_your_council(user["id"])
    return user["id"]


def _task_id_for(uid, arch, key):
    tasks = _seat_keystone_tasks(uid, arch)
    return tasks[key - 1]["id"] if len(tasks) >= key else None


def _archive_fixture(svc, uid):
    """A conductor key with 3 archive rows (2 in a duplicate group
    sharing one meeting_created_at, 1 in a unique group) and a live
    complete row with 3 messages under the shared conversation id.
    Returns (archive_rows, live_messages)."""
    svc.meetings.create(uid, "conductor", 1)
    mrow = svc.meetings.get(uid, "conductor", 1)
    t1 = [{"id": "a1", "role": "user", "body": "first run, first turn"}]
    t2 = [{"id": "a2", "role": "user", "body": "first run, second turn"}]
    svc.meetings.archive_run(uid, "conductor", 1, mrow, t1)
    svc.meetings.archive_run(uid, "conductor", 1, mrow, t2)
    # A second group: move the meetings row's created_at, then archive.
    svc.meetings._conn.execute(
        "UPDATE meetings SET created_at = '2026-01-02T00:00:00+00:00' "
        "WHERE user_id = ? AND archetype_id = 'conductor' AND keystone_index = 1",
        (uid,),
    )
    svc.meetings._conn.commit()
    mrow2 = svc.meetings.get(uid, "conductor", 1)
    t3 = [{"id": "a3", "role": "user", "body": "second run"}]
    svc.meetings.archive_run(uid, "conductor", 1, mrow2, t3)
    # The live row: complete, with 3 messages under the shared id.
    svc.meetings.update(uid, "conductor", 1, status="complete", stage="complete")
    svc.conversations.ensure_conversation(uid, "meeting-conductor-1", kind="meeting")
    for body in ("live one", "live two", "live three"):
        svc.conversations.append_message(
            uid, "meeting-conductor-1", "conductor", "user", body,
            mode="base", context={"meeting": True}, via_meeting=True,
        )
    archives = svc.meetings.list_archives(uid, "conductor", 1)
    live = svc.conversations.history(uid, "meeting-conductor-1", limit=100)
    return archives, live


def test_t_mig_1_migration_steps_2_to_5(ve_ctx, tmp_path):
    """T-MIG-1 (AC6): the migration creates archive + live encounters,
    re-points the meetings row, creates the fences, and Step 5 verifies."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    archives, live = _archive_fixture(svc, uid)
    assert len(archives) == 3
    assert len(live) == 3

    report = svc.meetings.migrate_to_encounters(svc.conversations, _task_id_for)
    assert report["verified"] is True
    assert report["failures"] == []
    key = report["keys"][0]
    assert key["archives_migrated"] == 3
    assert key["live"] == "created"
    assert key["fences"] == 4  # 3 archive + 1 live

    encounters = svc.list_encounters(uid, "conductor", 1)
    assert len(encounters) == 4
    assert [e["run_number"] for e in encounters] == [1, 2, 3, 4]
    # The three archive encounters (in archived_at order).
    for e in encounters[:3]:
        assert e["transcript_source"] == "archive"
        assert e["verification_status"] == "legacy-unverified"
        assert e["status"] == "complete"
        assert e["predecessor_link_kind"] == "reconstructed" or e["run_number"] == 1
        assert e["conversation_id"] == f"meeting-conductor-1-{e['run_id']}"
    # The transcripts carried over (not empty): one message each.
    assert [e["message_count"] for e in encounters[:3]] == [1, 1, 1]
    assert json.loads(encounters[0]["transcript_json"])[0]["body"] == "first run, first turn"
    assert json.loads(encounters[1]["transcript_json"])[0]["body"] == "first run, second turn"
    assert json.loads(encounters[2]["transcript_json"])[0]["body"] == "second run"
    assert encounters[0]["predecessor_run_id"] is None
    assert encounters[1]["predecessor_run_id"] == encounters[0]["run_id"]
    assert encounters[2]["predecessor_run_id"] == encounters[1]["run_id"]
    # The live encounter (run 4 = k+1).
    live_enc = encounters[3]
    assert live_enc["transcript_source"] == "live"
    assert live_enc["verification_status"] == "unverified"
    assert live_enc["run_id_provenance"] == "generated-migration"
    assert live_enc["conversation_id"] == "meeting-conductor-1"
    assert live_enc["predecessor_run_id"] == encounters[2]["run_id"]
    assert live_enc["predecessor_link_kind"] == "reconstructed"
    assert live_enc["message_count"] == 3
    assert live_enc["status"] == "complete"
    # The meetings row points at the live encounter.
    assert svc.meetings.get(uid, "conductor", 1)["run_id"] == live_enc["run_id"]
    # The fences: closed for the (complete) archive + live runs.
    for e in encounters:
        assert svc.conversations.get_fence_state(uid, e["conversation_id"]) == "closed"
    # The live messages are untouched (Step 6).
    assert [m["body"] for m in svc.conversations.history(uid, "meeting-conductor-1", limit=100)] == [
        "live one", "live two", "live three",
    ]
    # meeting_archives is retained as-is.
    assert len(svc.meetings.list_archives(uid, "conductor", 1)) == 3


def test_t_mig_2_identity_evidence_rule(ve_ctx, tmp_path):
    """T-MIG-2 (AC17): the I6 rule — a duplicate archive group yields
    'legacy-record' + legacy_possible_duplicate=1; a unique group
    yields 'generated-migration'."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _archive_fixture(svc, uid)
    svc.meetings.migrate_to_encounters(svc.conversations, _task_id_for)
    encounters = svc.list_encounters(uid, "conductor", 1)
    archive_encs = [e for e in encounters if e["transcript_source"] == "archive"]
    assert len(archive_encs) == 3
    # The first two share a meeting_created_at (the duplicate group).
    assert archive_encs[0]["legacy_group_key"] == archive_encs[1]["legacy_group_key"]
    assert archive_encs[0]["run_id_provenance"] == "legacy-record"
    assert archive_encs[1]["run_id_provenance"] == "legacy-record"
    assert archive_encs[0]["legacy_possible_duplicate"] == 1
    assert archive_encs[1]["legacy_possible_duplicate"] == 1
    # The third is a unique group.
    assert archive_encs[2]["legacy_group_key"] != archive_encs[0]["legacy_group_key"]
    assert archive_encs[2]["run_id_provenance"] == "generated-migration"
    assert archive_encs[2]["legacy_possible_duplicate"] == 0


def test_t_mig_3_migration_is_idempotent(ve_ctx, tmp_path):
    """T-MIG-3 (AC6): running the migration twice creates nothing new
    and still verifies."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _archive_fixture(svc, uid)
    first = svc.meetings.migrate_to_encounters(svc.conversations, _task_id_for)
    assert first["verified"] is True
    second = svc.meetings.migrate_to_encounters(svc.conversations, _task_id_for)
    assert second["verified"] is True
    assert second["failures"] == []
    assert len(svc.list_encounters(uid, "conductor", 1)) == 4
    assert second["keys"][0]["archives_migrated"] == 0
    assert second["keys"][0]["archives_adopted"] == 3
    assert second["keys"][0]["live"] == "adopted"


def test_t_mig_4_adopt_materialized_live_row(ve_ctx, tmp_path):
    """T-MIG-4 (AC6): a pre-existing materialized live row is ADOPTED
    (its run_number moves to k+1, its predecessor binds to the last
    archive encounter), never duplicated."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    archives, _ = _archive_fixture(svc, uid)
    # Materialize the live row first (the S2 lazy path): the service
    # creates a run-1 encounter from the meetings row.
    svc.start(uid, "conductor")
    materialized = svc.meetings.get_latest_encounter(uid, "conductor", 1)
    assert materialized["run_number"] == 1
    assert materialized["run_id_provenance"] == "generated-migration"

    report = svc.meetings.migrate_to_encounters(svc.conversations, _task_id_for)
    assert report["verified"] is True
    encounters = svc.list_encounters(uid, "conductor", 1)
    assert len(encounters) == 4
    # The materialized row is now run 4 (k+1), bound to the last archive.
    adopted = svc.meetings.get_encounter(uid, materialized["run_id"])
    assert adopted["run_number"] == 4
    assert adopted["predecessor_run_id"] == encounters[2]["run_id"]
    assert adopted["transcript_source"] == "live"
    assert adopted["conversation_id"] == "meeting-conductor-1"


def test_t_mig_5_completion_check_verifies(ve_ctx, tmp_path):
    """T-MIG-5 (AC16): a normal completion yields
    read_consistency_verified with an append-only detail entry
    carrying the normative paragraph."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    svc.start(uid, "conductor")
    svc.turn(uid, "conductor", "I work by deadlines first.")
    state = svc.complete(uid, "conductor")
    assert state["status"] == "complete"
    enc = svc.meetings.get_latest_encounter(uid, "conductor", 1)
    assert enc["verification_status"] == "read_consistency_verified"
    assert enc["verification_checked_at"]
    detail = enc["verification_detail"]
    assert len(detail) == 1
    assert detail[0]["result"] == "read_consistency_verified"
    assert detail[0]["count"] == enc["message_count"]
    assert detail[0]["failures"] == []
    assert detail[0]["note"] == READ_CONSISTENCY_NORMATIVE
    # The encounter detail serves the paragraph as user-facing copy.
    served = svc.get_encounter_detail(uid, enc["run_id"])
    assert served["verification_note"] == READ_CONSISTENCY_NORMATIVE


def test_t_mig_6_forced_partial_read_fails_but_completes(ve_ctx, tmp_path, monkeypatch):
    """T-MIG-6 (AC5): a forced partial-read failure yields
    read_consistency_failed; the encounter is still complete and a
    successor is still creatable."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    svc.start(uid, "conductor")
    svc.turn(uid, "conductor", "I work by deadlines first.")
    # Force the second paged read to return a truncated transcript.
    real_history = svc.conversations.history
    calls = {"n": 0}

    def _flaky_history(user_id, cid, limit=50, offset=0):
        rows = real_history(user_id, cid, limit=limit, offset=offset)
        calls["n"] += 1
        # The check reads the transcript twice (two full passes); the
        # second pass returns one fewer row.
        if calls["n"] > 1 and rows:
            return rows[:-1]
        return rows

    monkeypatch.setattr(svc.conversations, "history", _flaky_history)
    state = svc.complete(uid, "conductor")
    assert state["status"] == "complete"
    enc = svc.meetings.get_latest_encounter(uid, "conductor", 1)
    assert enc["verification_status"] == "read_consistency_failed"
    detail = enc["verification_detail"]
    assert len(detail) == 1
    assert detail[0]["result"] == "read_consistency_failed"
    assert any("count_mismatch" in f for f in detail[0]["failures"])
    # A successor is still creatable from the failed-but-complete run.
    out = svc.meet_again(
        uid, "conductor", 1,
        predecessor_run_id=enc["run_id"], request_id="req-after-fail",
    )
    assert out["encounter"]["run_number"] == 2
    assert out["encounter"]["status"] == "in_progress"


def test_t_mig_7_failed_check_preserves_prior_record(ve_ctx, tmp_path):
    """T-MIG-7 (AC16): a failed check appends to the detail history —
    the prior passing record is preserved, never overwritten."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    svc.start(uid, "conductor")
    enc = svc.meetings.get_latest_encounter(uid, "conductor", 1)
    # Seed a prior passing record, then finalize with a failing one
    # (the store-level append-only rule).
    passing = {
        "checked_at": "2026-11-09T00:00:00+00:00",
        "result": "read_consistency_verified",
        "count": 4,
        "id_range": [1, 4],
        "failures": [],
        "note": READ_CONSISTENCY_NORMATIVE,
    }
    svc.meetings.update_encounter(
        uid, enc["run_id"], verification_detail=[passing]
    )
    failing = dict(passing, result="read_consistency_failed",
                   failures=["count_mismatch: first=4 second=3"])
    finalized = svc.meetings.finalize_encounter(
        uid, enc["run_id"], message_count=4,
        verification_status="read_consistency_failed",
        verification_detail=failing,
        verification_checked_at="2026-11-09T00:01:00+00:00",
    )
    assert finalized["verification_status"] == "read_consistency_failed"
    detail = finalized["verification_detail"]
    assert len(detail) == 2
    assert detail[0]["result"] == "read_consistency_verified"
    assert detail[1]["result"] == "read_consistency_failed"


def test_t_mig_8_legacy_identity_in_listing(ve_ctx, tmp_path):
    """T-MIG-8 (AC17): the listing carries identity_kind
    'legacy-record' for duplicate-group rows, predecessor_link_kind
    'reconstructed', and the lineage label 'follows (archive order)'."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _archive_fixture(svc, uid)
    svc.meetings.migrate_to_encounters(svc.conversations, _task_id_for)
    listed = svc.list_encounters(uid, "conductor", 1)
    archive_encs = [e for e in listed if e["transcript_source"] == "archive"]
    assert archive_encs[0]["identity_kind"] == "legacy-record"
    assert archive_encs[1]["identity_kind"] == "legacy-record"
    assert archive_encs[2]["identity_kind"] == "generated-migration"
    assert archive_encs[1]["predecessor_link_kind"] == "reconstructed"
    assert archive_encs[1]["lineage_label"] == "follows (archive order)"
    assert archive_encs[2]["lineage_label"] == "follows (archive order)"
    # The first run has no predecessor and no lineage label.
    assert archive_encs[0]["lineage_label"] is None
    # The live run follows the last archive run (reconstructed).
    live_enc = [e for e in listed if e["transcript_source"] == "live"][0]
    assert live_enc["lineage_label"] == "follows (archive order)"
