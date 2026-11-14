"""Slice 1 tests: the fenced conversation store (non-destructive Meet Again).

Proposal §2 safeguards and §1.3 G2, tested at the store boundary:

- T-S1-1  the (b) gate: ordinary writes to a ``meeting-*`` id are refused
- T-S1-2  the fence: a missing fence on a meeting id is an integrity
  error (502), never permission to write
- T-S1-3  a closed fence refuses writes (``encounter_finalized``)
- T-S1-4  fence creation in ``ensure_conversation`` + ``close_fence``
  outcomes (closed / already-closed-by-same-run / closed-by-other-run
  / missing); a closed fence is never re-opened by ``ensure_conversation``
- T-S2-1  transaction ownership: an append that finds a transaction it
  did not open fails closed and never rolls back unrelated work
- T-S3-1  the conflict handler: same key + matching body/context
  returns the existing message (``inserted: False``), no duplicate
- T-S3-2  same key + different body/context -> OpeningIntegrityConflict
- T-S3-3  an unkeyed write to a fenced meeting conversation keeps
  today's return shape; the partial unique index ignores NULL keys
- T-S1-MIG  opening a pre-existing database adds ``messages.message_key``
  and creates the fence table (guarded ALTER + _SCHEMA IF NOT EXISTS)

AC21 (safeguard 1), AC22 (safeguard 2), AC23 (safeguard 3).
"""

import sqlite3

import pytest

from local_ai.conversation.store import (
    ConversationIntegrityError,
    ConversationStore,
    ConversationWriteRefused,
    OpeningIntegrityConflict,
    TransactionStateError,
)

MEETING_CID = "meeting-mentor-1"
OTHER_MEETING_CID = "meeting-champion-2"


@pytest.fixture
def store(tmp_path):
    return ConversationStore(db_path=tmp_path / "conversations.db")


def test_t_s1_1_ordinary_write_to_meeting_id_refused(store):
    """T-S1-1 (AC22-adjacent, §1.3 G2): the (b) gate refuses an ordinary
    writer's append to a reserved meeting conversation id — even when a
    fence row exists and is open."""
    store.ensure_conversation("u1", MEETING_CID, kind="meeting")
    assert store.get_fence_state("u1", MEETING_CID) == "open"
    with pytest.raises(ConversationWriteRefused) as excinfo:
        store.append_message("u1", MEETING_CID, "mentor", "user", "hello")
    assert excinfo.value.code == "reserved_meeting_id"
    assert store.count_messages("u1", MEETING_CID) == 0


def test_t_s1_2_meeting_write_without_fence_is_integrity_error(store):
    """T-S1-2 (AC21, safeguard 1): a meeting write with no fence row at
    all is an integrity error (502), never permission to write. The
    fence row is the write-admission record; its absence means the
    encounter was never created or the migration missed it."""
    with pytest.raises(ConversationIntegrityError):
        store.append_message("u1", MEETING_CID, "mentor", "voice", "hello",
                             via_meeting=True)
    assert store.count_messages("u1", MEETING_CID) == 0


def test_t_s1_3_closed_fence_refuses_writes(store):
    """T-S1-3 (AC14/AC21): once the fence is closed, a meeting write is
    refused with ``encounter_finalized`` and names the run that closed
    it; the message is never written."""
    store.ensure_conversation("u1", MEETING_CID, kind="meeting")
    assert store.close_fence("u1", MEETING_CID, "run-abc") == "closed"
    with pytest.raises(ConversationWriteRefused) as excinfo:
        store.append_message("u1", MEETING_CID, "mentor", "voice", "hello",
                             via_meeting=True)
    assert excinfo.value.code == "encounter_finalized"
    assert excinfo.value.run_id == "run-abc"
    assert store.count_messages("u1", MEETING_CID) == 0


def test_t_s1_4_fence_lifecycle(store):
    """T-S1-4: fence creation, the close_fence outcome vocabulary, and
    the guarantee that ``ensure_conversation`` never re-opens a closed
    fence (a finalized encounter stays finalized)."""
    # A non-meeting conversation gets no fence row.
    store.ensure_conversation("u1", "talk-aaaa", kind="talk")
    assert store.get_fence_state("u1", "talk-aaaa") is None

    # Closing a conversation that was never fenced reports missing.
    assert store.close_fence("u1", OTHER_MEETING_CID, "run-x") == "missing"

    # ensure_conversation creates the fence open; ensure_fence is
    # idempotent and also never re-opens.
    store.ensure_conversation("u1", MEETING_CID, kind="meeting")
    assert store.get_fence_state("u1", MEETING_CID) == "open"
    store.ensure_fence("u1", MEETING_CID)
    assert store.get_fence_state("u1", MEETING_CID) == "open"

    assert store.close_fence("u1", MEETING_CID, "run-abc") == "closed"
    assert store.close_fence("u1", MEETING_CID, "run-abc") == "already-closed-by-same-run"
    assert store.close_fence("u1", MEETING_CID, "run-other") == "closed-by-other-run"
    assert store.get_fence_state("u1", MEETING_CID) == "closed"

    store.ensure_conversation("u1", MEETING_CID, kind="meeting")
    assert store.get_fence_state("u1", MEETING_CID) == "closed"
    store.ensure_fence("u1", MEETING_CID)
    assert store.get_fence_state("u1", MEETING_CID) == "closed"


def test_t_s1_5_meeting_write_with_open_fence_succeeds(store):
    """T-S1-5: the happy path — a meeting write with an open fence
    commits, and an ordinary write to an ordinary conversation is
    unaffected by the gate and the fence."""
    store.ensure_conversation("u1", MEETING_CID, kind="meeting")
    msg = store.append_message("u1", MEETING_CID, "mentor", "voice", "hello",
                               via_meeting=True)
    assert msg["body"] == "hello"
    assert "inserted" not in msg  # unkeyed writes keep today's shape
    assert store.count_messages("u1", MEETING_CID) == 1

    plain = store.append_message("u1", "talk-aaaa", "mentor", "user", "hi")
    assert plain["body"] == "hi"
    assert store.count_messages("u1", "talk-aaaa") == 1


def test_t_s2_1_append_with_unrelated_transaction_fails_closed(store):
    """T-S2-1 (AC22, safeguard 2): when the connection already holds a
    transaction this append did not open, the append fails closed with
    TransactionStateError — and the unrelated transaction's work is
    still there afterwards (nothing was rolled back)."""
    store.ensure_conversation("u1", MEETING_CID, kind="meeting")
    # Open an unrelated transaction on the same connection and put
    # work in it.
    store._conn.execute("BEGIN")
    store._conn.execute(
        "INSERT INTO messages (id, user_id, conversation_id, archetype_id, "
        "role, body, mode, context_json, created_at) "
        "VALUES ('unrelated-1', 'u1', 'talk-aaaa', 'mentor', 'user', "
        "'unrelated work', 'trained', '{}', '2026-11-09T00:00:00Z')"
    )
    with pytest.raises(TransactionStateError):
        store.append_message("u1", MEETING_CID, "mentor", "voice", "hello",
                             via_meeting=True)
    # The unrelated transaction is untouched: commit it and its row
    # is still there; the refused append wrote nothing.
    store._conn.execute("COMMIT")
    assert store.count_messages("u1", "talk-aaaa") == 1
    assert store.count_messages("u1", MEETING_CID) == 0


def test_t_s2_2_close_fence_with_unrelated_transaction_fails_closed(store):
    """T-S2-2 (AC22): the same ownership rule for ``close_fence`` — a
    close that finds a foreign transaction fails closed instead of
    rolling it back."""
    store.ensure_conversation("u1", MEETING_CID, kind="meeting")
    store._conn.execute("BEGIN")
    with pytest.raises(TransactionStateError):
        store.close_fence("u1", MEETING_CID, "run-abc")
    store._conn.execute("ROLLBACK")
    assert store.get_fence_state("u1", MEETING_CID) == "open"


def test_t_s3_1_keyed_duplicate_returns_existing(store):
    """T-S3-1 (AC23, safeguard 3): the same message identity with
    matching body and context returns the existing message with
    ``inserted: False`` — one row, never a duplicate."""
    store.ensure_conversation("u1", MEETING_CID, kind="meeting")
    first = store.append_message(
        "u1", MEETING_CID, "mentor", "voice", "Welcome.",
        context={"meeting": True, "opening_index": 0, "opening_total": 2},
        message_key="opening:run-abc:0", via_meeting=True,
    )
    assert first["inserted"] is True
    second = store.append_message(
        "u1", MEETING_CID, "mentor", "voice", "Welcome.",
        context={"meeting": True, "opening_index": 0, "opening_total": 2},
        message_key="opening:run-abc:0", via_meeting=True,
    )
    assert second["id"] == first["id"]
    assert second["inserted"] is False
    assert second["body"] == "Welcome."
    assert store.count_messages("u1", MEETING_CID) == 1


def test_t_s3_2_keyed_mismatch_is_conflict(store):
    """T-S3-2 (AC23): the same message identity with a different body
    is a contradiction — 409 ``opening_integrity_conflict``, and no
    row is added or overwritten."""
    store.ensure_conversation("u1", MEETING_CID, kind="meeting")
    store.append_message(
        "u1", MEETING_CID, "mentor", "voice", "Welcome.",
        context={"meeting": True, "opening_index": 0, "opening_total": 2},
        message_key="opening:run-abc:0", via_meeting=True,
    )
    with pytest.raises(OpeningIntegrityConflict) as excinfo:
        store.append_message(
            "u1", MEETING_CID, "mentor", "voice", "A different welcome.",
            context={"meeting": True, "opening_index": 0, "opening_total": 2},
            message_key="opening:run-abc:0", via_meeting=True,
        )
    assert excinfo.value.code == "opening_integrity_conflict"
    assert excinfo.value.run_id == "run-abc"
    assert store.count_messages("u1", MEETING_CID) == 1


def test_t_s3_3_keyed_context_mismatch_is_conflict(store):
    """T-S3-3 (AC23): the same key with the same body but a different
    context is also a contradiction — context is part of the identity."""
    store.ensure_conversation("u1", MEETING_CID, kind="meeting")
    store.append_message(
        "u1", MEETING_CID, "mentor", "voice", "Welcome.",
        context={"meeting": True, "opening_index": 0, "opening_total": 2},
        message_key="opening:run-abc:0", via_meeting=True,
    )
    with pytest.raises(OpeningIntegrityConflict):
        store.append_message(
            "u1", MEETING_CID, "mentor", "voice", "Welcome.",
            context={"meeting": True, "opening_index": 1, "opening_total": 2},
            message_key="opening:run-abc:0", via_meeting=True,
        )
    assert store.count_messages("u1", MEETING_CID) == 1


def test_t_s3_4_unkeyed_writes_unaffected_by_partial_index(store):
    """T-S3-4: the partial unique index only constrains keyed rows —
    any number of unkeyed messages may share a conversation, and the
    same key may recur across conversations (the index is scoped by
    user + conversation)."""
    store.ensure_conversation("u1", MEETING_CID, kind="meeting")
    store.ensure_conversation("u1", OTHER_MEETING_CID, kind="meeting")
    store.append_message("u1", MEETING_CID, "mentor", "voice", "a", via_meeting=True)
    store.append_message("u1", MEETING_CID, "mentor", "voice", "b", via_meeting=True)
    store.append_message("u1", MEETING_CID, "mentor", "voice", "c",
                         message_key="opening:run-abc:0", via_meeting=True)
    # Same key in a different conversation is a different row.
    store.append_message("u1", OTHER_MEETING_CID, "champion", "voice", "c",
                         message_key="opening:run-abc:0", via_meeting=True)
    assert store.count_messages("u1", MEETING_CID) == 3
    assert store.count_messages("u1", OTHER_MEETING_CID) == 1


def test_t_s1_mig_old_database_gains_message_key_and_fence(tmp_path):
    """T-S1-MIG: opening a database created before this slice adds
    ``messages.message_key`` (guarded ALTER) and creates the fence
    table plus the partial unique index — a no-op on a second open."""
    old_db = tmp_path / "old-conversations.db"
    raw = sqlite3.connect(str(old_db))
    raw.execute(
        "CREATE TABLE messages (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, "
        "conversation_id TEXT NOT NULL, archetype_id TEXT, role TEXT NOT NULL, "
        "body TEXT NOT NULL DEFAULT '', mode TEXT NOT NULL DEFAULT 'trained', "
        "context_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL)"
    )
    raw.execute(
        "INSERT INTO messages (id, user_id, conversation_id, role, body, "
        "created_at) VALUES ('m1', 'u1', 'talk-aaaa', 'user', 'kept', "
        "'2026-11-09T00:00:00Z')"
    )
    raw.commit()
    raw.close()

    opened = ConversationStore(db_path=old_db)
    cols = [r["name"] for r in opened._conn.execute("PRAGMA table_info(messages)")]
    assert "message_key" in cols
    tables = [
        r["name"]
        for r in opened._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    ]
    assert "conversation_write_fence" in tables
    assert opened.count_messages("u1", "talk-aaaa") == 1

    # Second open is a no-op (the migration is guarded).
    reopened = ConversationStore(db_path=old_db)
    assert reopened.count_messages("u1", "talk-aaaa") == 1
    reopened.close()
    opened.close()
