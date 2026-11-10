"""Meeting restart archives the FULL transcript, verified before delete.

Acceptance tests for the archive correction proposal (base 9dc955d):
restart pages through the whole transcript in 200-row pages, verifies
count + id-sequence equality against the live rows, and only then runs
archive_run -> clear_conversation -> live-row delete. Any pre-clear
failure aborts with the live rows and the live meeting row intact and
the meeting still restartable.

Fixtures seed live message rows directly in a test conversation
store, the same technique existing meeting tests use; expectations
are read back through an independent sqlite3 connection (never
through the helpers under test), so the tests do not assume what
they are proving.
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


def _seeded_user(email="restart-archive@example.com"):
    user = ve.create_user_account(email, "pw", "Restart")
    keystone_seeding.seed_meet_your_council(user["id"])
    return user["id"]


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
    # Non-destructive Meet Again (Slice 1): seeding a meeting
    # transcript goes through the meeting path — the conversation is
    # ensured (which creates its write fence) and the appends carry
    # via_meeting, as the meeting service's own writes do. The
    # restart/archive assertions below are unchanged.
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


def _archive_transcript(svc, uid, arch=ARCH):
    rows = svc.meetings.list_archives(uid, arch, 1)
    assert len(rows) == 1, f"expected exactly one archive row, got {len(rows)}"
    return rows[0]["transcript"]


def _assert_archive_matches_live(archive, live):
    assert [m["id"] for m in archive] == [r["id"] for r in live]
    assert [m["role"] for m in archive] == [r["role"] for r in live]
    assert [m["body"] for m in archive] == [r["body"] for r in live]
    assert [m["created_at"] for m in archive] == [r["created_at"] for r in live]


def _assert_intact(svc, tmp_path, uid, cid, live_before):
    assert svc.meetings.get(uid, ARCH, 1) is not None
    assert svc.meetings.get(uid, ARCH, 1)["status"] == "complete"
    assert _live_rows(tmp_path, uid, cid) == live_before
    assert svc.meetings.list_archives(uid, ARCH, 1) == []


@pytest.mark.parametrize("n", [201, 500, 2500])
def test_restart_archives_full_transcript(ve_ctx, tmp_path, n):
    """E1: meetings past the old bound lose nothing; archive is complete
    and ordered. 500 is the verdict's example (old code lost the first
    300); 2500 shows independence from any particular cap."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    cid = _completed_meeting(svc, uid, n)
    live_before = _live_rows(tmp_path, uid, cid)
    assert len(live_before) == n

    svc.restart(uid, ARCH)

    assert svc.meetings.get(uid, ARCH, 1) is None
    _assert_archive_matches_live(_archive_transcript(svc, uid), live_before)
    assert _live_rows(tmp_path, uid, cid) == []


def test_restart_same_timestamp_tie_order(ve_ctx, tmp_path, monkeypatch):
    """E2: rows sharing one created_at keep deterministic id-ASC order."""
    import local_ai.conversation.store as store_mod

    monkeypatch.setattr(store_mod, "_utcnow", lambda: "2026-11-03T10:00:00+00:00")
    uid = _seeded_user()
    svc = _svc(tmp_path)
    cid = _completed_meeting(svc, uid, 5)
    live_before = _live_rows(tmp_path, uid, cid)
    assert len({r["created_at"] for r in live_before}) == 1
    assert [r["id"] for r in live_before] == sorted(r["id"] for r in live_before)

    svc.restart(uid, ARCH)

    _assert_archive_matches_live(_archive_transcript(svc, uid), live_before)


@pytest.mark.parametrize("n", [1, 3, 199, 200])
def test_short_meetings_unchanged(ve_ctx, tmp_path, n):
    """E4: at or under the old bound, the archive equals today's
    single-read output and the live row is deleted as before."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    cid = _completed_meeting(svc, uid, n)
    single_read = svc.conversations.history(uid, cid, limit=200)
    live_before = _live_rows(tmp_path, uid, cid)

    svc.restart(uid, ARCH)

    archive = _archive_transcript(svc, uid)
    assert [m["id"] for m in archive] == [m["id"] for m in single_read]
    _assert_archive_matches_live(archive, live_before)
    assert svc.meetings.get(uid, ARCH, 1) is None


def test_restart_zero_rows(ve_ctx, tmp_path):
    """Failure-table row 9: a completed meeting with no messages
    archives an empty transcript and deletes the live row."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    cid = _completed_meeting(svc, uid, 0)

    svc.restart(uid, ARCH)

    assert _archive_transcript(svc, uid) == []
    assert svc.meetings.get(uid, ARCH, 1) is None
    assert _live_rows(tmp_path, uid, cid) == []


def test_page_read_failure_aborts_intact(ve_ctx, tmp_path, monkeypatch):
    """E3 / failure row 1: a page read raising mid-loop aborts before
    any archive write; a later clean restart succeeds."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    cid = _completed_meeting(svc, uid, 201)
    live_before = _live_rows(tmp_path, uid, cid)
    real_history = ConversationStore.history

    def failing_history(self, user_id, conversation_id="skeleton", limit=50, offset=0):
        if offset >= 200:
            raise RuntimeError("simulated page read failure")
        return real_history(self, user_id, conversation_id, limit=limit, offset=offset)

    monkeypatch.setattr(ConversationStore, "history", failing_history)
    with pytest.raises(RuntimeError):
        svc.restart(uid, ARCH)
    _assert_intact(svc, tmp_path, uid, cid, live_before)

    monkeypatch.undo()
    svc.restart(uid, ARCH)
    _assert_archive_matches_live(_archive_transcript(svc, uid), live_before)


def test_count_mismatch_aborts_intact(ve_ctx, tmp_path, monkeypatch):
    """E3 / failure row 2: count mismatch aborts before any delete."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    cid = _completed_meeting(svc, uid, 201)
    live_before = _live_rows(tmp_path, uid, cid)
    real_count = svc.conversations.count_messages(uid, cid)

    monkeypatch.setattr(
        ConversationStore, "count_messages",
        lambda self, u, c: real_count + 1,
    )
    with pytest.raises(MeetingError):
        svc.restart(uid, ARCH)
    _assert_intact(svc, tmp_path, uid, cid, live_before)

    monkeypatch.undo()
    svc.restart(uid, ARCH)
    _assert_archive_matches_live(_archive_transcript(svc, uid), live_before)


def test_id_mismatch_aborts_intact(ve_ctx, tmp_path, monkeypatch):
    """E3 / failure row 3: id-sequence mismatch aborts before any delete."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    cid = _completed_meeting(svc, uid, 201)
    live_before = _live_rows(tmp_path, uid, cid)

    monkeypatch.setattr(
        ConversationStore, "message_ids",
        lambda self, u, c: list(reversed([r["id"] for r in live_before])),
    )
    with pytest.raises(MeetingError):
        svc.restart(uid, ARCH)
    _assert_intact(svc, tmp_path, uid, cid, live_before)

    monkeypatch.undo()
    svc.restart(uid, ARCH)
    _assert_archive_matches_live(_archive_transcript(svc, uid), live_before)


def test_archive_write_failure_aborts_before_clear(ve_ctx, tmp_path, monkeypatch):
    """E3 / failure row 4: archive_run raising leaves live rows and the
    live meeting row intact; a later clean restart succeeds."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    cid = _completed_meeting(svc, uid, 201)
    live_before = _live_rows(tmp_path, uid, cid)

    def failing_archive(*args, **kwargs):
        raise RuntimeError("simulated archive write failure")

    monkeypatch.setattr(MeetingStore, "archive_run", failing_archive)
    with pytest.raises(RuntimeError):
        svc.restart(uid, ARCH)
    _assert_intact(svc, tmp_path, uid, cid, live_before)

    monkeypatch.undo()
    svc.restart(uid, ARCH)
    _assert_archive_matches_live(_archive_transcript(svc, uid), live_before)


def test_clear_failure_leaves_complete_archive_and_live_rows(
    ve_ctx, tmp_path, monkeypatch
):
    """E1 ordering proof: when clear fails, the archive row is already
    present and complete while the live rows are untouched."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    cid = _completed_meeting(svc, uid, 201)
    live_before = _live_rows(tmp_path, uid, cid)

    def failing_clear(*args, **kwargs):
        raise RuntimeError("simulated clear failure")

    monkeypatch.setattr(ConversationStore, "clear_conversation", failing_clear)
    with pytest.raises(RuntimeError):
        svc.restart(uid, ARCH)
    _assert_archive_matches_live(_archive_transcript(svc, uid), live_before)
    assert _live_rows(tmp_path, uid, cid) == live_before
    assert svc.meetings.get(uid, ARCH, 1)["status"] == "complete"


def test_history_offset_default_is_byte_identical(ve_ctx, tmp_path):
    """B1 backward compatibility: the defaulted offset changes nothing
    for existing callers, and paging reconstructs a full read."""
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
        rebuilt.extend(page)
    assert rebuilt == default
    assert [m["id"] for m in rebuilt] == svc.conversations.message_ids(uid, cid)
