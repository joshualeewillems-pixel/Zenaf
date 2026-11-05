"""Weave W0B provenance schema tests: additive nullable columns, no behavior change.

W0B adds origin/provenance columns to tasks and evidence/snapshot columns
to task_proposals. Nothing writes them yet (W1 will); this file proves:

- The migration applies on a fresh DB and on a legacy DB (old schema,
  pre-W0B tables), and is idempotent.
- Legacy rows read with NULL origins and NULL originals — NO backfill
  (copying live values into original_* would fabricate an original).
- The task and proposal positional mappings read the right fields
  (fixture rows with distinct sentinels per position).
- New-column values round-trip through the storage read paths
  (SELECT lists + mappings agree).
- seat_ref is untouched: its column definition, its stored values, and
  its write path are exactly as before (keystone-scoped, never the
  provenance field).

No model calls. No behavior code is exercised beyond the storage reads.
"""

from __future__ import annotations

import sqlite3

import pytest

import local_ai.vision_execution.models as M
import local_ai.vision_execution.storage as S

TASK_ORIGIN_COLUMNS = (
    "origin_seat",
    "origin_conversation_id",
    "origin_message_id",
    "origin_claim_id",
    "origin_decision_id",
    "responsible_seat",
)

PROPOSAL_W0B_COLUMNS = (
    "evidence_quote",
    "original_title",
    "original_parent_task_id",
    "original_timeframe_commitment",
    "original_due_date",
    "original_notes",
)

# Legacy DDL: the pre-W0B tables (current schema minus the W0B columns).
LEGACY_TASKS_DDL = """
CREATE TABLE tasks (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  project_id TEXT,
  parent_task_id TEXT,
  title TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  assignee_id TEXT,
  status TEXT NOT NULL DEFAULT 'Todo',
  priority TEXT NOT NULL DEFAULT '',
  estimated_hours REAL,
  due_date TEXT,
  dependency_ids TEXT NOT NULL DEFAULT '[]',
  required_asset_ids TEXT NOT NULL DEFAULT '[]',
  completion_criteria TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  seat_ref TEXT NOT NULL DEFAULT '',
  timeframe_commitment TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
)
"""

LEGACY_PROPOSALS_DDL = """
CREATE TABLE task_proposals (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  source_message_id TEXT NOT NULL,
  block_index INTEGER NOT NULL,
  proposal_index INTEGER NOT NULL,
  seat TEXT NOT NULL,
  title TEXT NOT NULL,
  parent_task_id TEXT,
  timeframe_commitment TEXT,
  due_date TEXT,
  notes TEXT NOT NULL DEFAULT '',
  state TEXT NOT NULL DEFAULT 'pending',
  created_task_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  decided_at TEXT,
  UNIQUE(user_id, source_message_id, block_index, proposal_index)
)
"""


@pytest.fixture()
def ve_conn(tmp_path, monkeypatch):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    S.init_db(conn)
    monkeypatch.setattr(S, "get_connection", lambda: conn)
    yield conn
    conn.close()


def _pragma_columns(conn, table):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1]: r for r in rows}


def _legacy_conn():
    """A connection holding pre-W0B tables + one legacy row each."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(LEGACY_TASKS_DDL + ";" + LEGACY_PROPOSALS_DDL)
    conn.execute(
        "INSERT INTO tasks (id, user_id, title, seat_ref, timeframe_commitment,"
        " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("task-legacy", "u1", "Legacy task", "champion", "tentative", "2026-01-01", "2026-01-02"),
    )
    conn.execute(
        "INSERT INTO task_proposals (id, user_id, conversation_id, source_message_id,"
        " block_index, proposal_index, seat, title, notes, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("prop-legacy", "u1", "conv-1", "msg-1", 0, 0, "champion",
         "Legacy proposal", "Do the thing", "2026-01-01", "2026-01-02"),
    )
    conn.commit()
    return conn


# -- Fresh DB -------------------------------------------------------------------


def test_fresh_db_has_w0b_columns_nullable_no_default(ve_conn):
    task_cols = _pragma_columns(ve_conn, "tasks")
    for col in TASK_ORIGIN_COLUMNS:
        assert col in task_cols, f"tasks missing {col}"
        assert task_cols[col][3] == 0, f"{col} must be nullable"
        assert task_cols[col][4] is None, f"{col} must have no default"
    prop_cols = _pragma_columns(ve_conn, "task_proposals")
    for col in PROPOSAL_W0B_COLUMNS:
        assert col in prop_cols, f"task_proposals missing {col}"
        assert prop_cols[col][3] == 0, f"{col} must be nullable"
        assert prop_cols[col][4] is None, f"{col} must have no default"


def test_fresh_task_reads_null_origins_and_seat_ref_path_unchanged(ve_conn):
    task = S.create_task(M.TaskCreate(title="Fresh task", seat_ref="mentor"), "u1")
    assert task["seat_ref"] == "mentor"
    for col in TASK_ORIGIN_COLUMNS:
        assert task[col] is None, f"fresh task {col} must be None"
    fetched = S.get_task(task["id"], "u1")
    assert fetched is not None
    for col in TASK_ORIGIN_COLUMNS:
        assert fetched[col] is None


def test_fresh_proposal_reads_null_w0b_columns(ve_conn):
    ve_conn.execute(
        "INSERT INTO task_proposals (id, user_id, conversation_id, source_message_id,"
        " block_index, proposal_index, seat, title, notes, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("prop-fresh", "u1", "conv-1", "msg-1", 0, 0, "champion",
         "Fresh proposal", "Do it", "2026-01-01", "2026-01-02"),
    )
    ve_conn.commit()
    rows = S.list_task_proposals("u1", "conv-1")
    assert len(rows) == 1
    for col in PROPOSAL_W0B_COLUMNS:
        assert rows[0][col] is None, f"fresh proposal {col} must be None"


# -- Legacy DB: migration, no backfill, idempotency ------------------------------


def test_legacy_db_migrates_with_null_origins_no_backfill(monkeypatch):
    conn = _legacy_conn()
    monkeypatch.setattr(S, "get_connection", lambda: conn)
    S.init_db(conn)
    task = S.get_task("task-legacy", "u1")
    assert task is not None
    assert task["title"] == "Legacy task"
    assert task["seat_ref"] == "champion", "migration must preserve seat_ref"
    assert task["timeframe_commitment"] == "tentative"
    for col in TASK_ORIGIN_COLUMNS:
        assert task[col] is None, f"legacy task {col} must be None, not backfilled"
    rows = S.list_task_proposals("u1", "conv-1")
    assert len(rows) == 1
    assert rows[0]["title"] == "Legacy proposal"
    for col in PROPOSAL_W0B_COLUMNS:
        assert rows[0][col] is None, f"legacy proposal {col} must be None, not backfilled"
    # The original is honestly unrecorded: live title must NOT be copied.
    assert rows[0]["original_title"] is None
    conn.close()


def test_legacy_migration_is_idempotent(monkeypatch):
    conn = _legacy_conn()
    monkeypatch.setattr(S, "get_connection", lambda: conn)
    S.init_db(conn)
    S.init_db(conn)
    task = S.get_task("task-legacy", "u1")
    assert task is not None
    assert task["seat_ref"] == "champion"
    for col in TASK_ORIGIN_COLUMNS:
        assert task[col] is None
    cols = _pragma_columns(conn, "tasks")
    assert sum(1 for c in cols if c in TASK_ORIGIN_COLUMNS) == len(TASK_ORIGIN_COLUMNS)
    conn.close()


def test_seat_ref_column_definition_unchanged(ve_conn):
    col = _pragma_columns(ve_conn, "tasks")["seat_ref"]
    assert col[2] == "TEXT"
    assert col[3] == 1, "seat_ref must stay NOT NULL"
    assert col[4] == "''", "seat_ref default must stay ''"


def test_provenance_migration_noops_without_tasks_table():
    conn = sqlite3.connect(":memory:")
    # Must not raise when the tasks table does not exist (early return).
    S._migrate_tasks_provenance_columns(conn)
    conn.close()


# -- Positional mapping pins ------------------------------------------------------


def test_row_to_task_positional_pin():
    row = (
        "t-1", "p-1", "pt-1", "Title", "Desc", "a-1", "Todo", "high",
        2.5, "2026-12-01", '["d1"]', '["r1"]', "Done when x", "Notes",
        "2026-01-01", "2026-01-02", "mentor", "tentative",
        "champion", "conv-9", "msg-9", "claim-9", "dec-9", "guardian",
    )
    assert len(row) == 24
    task = M.row_to_task(row)
    assert task["id"] == "t-1"
    assert task["project_id"] == "p-1"
    assert task["parent_task_id"] == "pt-1"
    assert task["title"] == "Title"
    assert task["description"] == "Desc"
    assert task["assignee_id"] == "a-1"
    assert task["status"] == "Todo"
    assert task["priority"] == "high"
    assert task["estimated_hours"] == 2.5
    assert task["due_date"] == "2026-12-01"
    assert task["dependency_ids"] == ["d1"]
    assert task["required_asset_ids"] == ["r1"]
    assert task["completion_criteria"] == "Done when x"
    assert task["notes"] == "Notes"
    assert task["created_at"] == "2026-01-01"
    assert task["updated_at"] == "2026-01-02"
    assert task["seat_ref"] == "mentor"
    assert task["timeframe_commitment"] == "tentative"
    assert task["origin_seat"] == "champion"
    assert task["origin_conversation_id"] == "conv-9"
    assert task["origin_message_id"] == "msg-9"
    assert task["origin_claim_id"] == "claim-9"
    assert task["origin_decision_id"] == "dec-9"
    assert task["responsible_seat"] == "guardian"


def test_row_to_task_short_rows_default_new_columns_to_none():
    # Pre-W0B 18-column rows (no provenance) must still map, with Nones.
    row = (
        "t-1", "p-1", "pt-1", "Title", "Desc", "a-1", "Todo", "high",
        2.5, "2026-12-01", "[]", "[]", "", "", "2026-01-01", "2026-01-02",
        "", None,
    )
    task = M.row_to_task(row)
    for col in TASK_ORIGIN_COLUMNS:
        assert task[col] is None


def test_proposal_row_to_dict_positional_pin():
    row = (
        "pr-1", "u1", "conv-9", "msg-9", 0, 1, "champion", "Call it",
        "pt-1", "tentative", "2026-12-01", "Notes", "pending", None,
        "2026-01-01", "2026-01-02", None,
        "We should call it", "Call it", "pt-1", "tentative", "2026-12-01", "Notes",
    )
    assert len(row) == 23
    d = S._proposal_row_to_dict(row)
    assert d["id"] == "pr-1"
    assert d["user_id"] == "u1"
    assert d["conversation_id"] == "conv-9"
    assert d["source_message_id"] == "msg-9"
    assert d["block_index"] == 0
    assert d["proposal_index"] == 1
    assert d["seat"] == "champion"
    assert d["title"] == "Call it"
    assert d["parent_task_id"] == "pt-1"
    assert d["timeframe_commitment"] == "tentative"
    assert d["due_date"] == "2026-12-01"
    assert d["notes"] == "Notes"
    assert d["state"] == "pending"
    assert d["created_task_id"] is None
    assert d["created_at"] == "2026-01-01"
    assert d["updated_at"] == "2026-01-02"
    assert d["decided_at"] is None
    assert d["evidence_quote"] == "We should call it"
    assert d["original_title"] == "Call it"
    assert d["original_parent_task_id"] == "pt-1"
    assert d["original_timeframe_commitment"] == "tentative"
    assert d["original_due_date"] == "2026-12-01"
    assert d["original_notes"] == "Notes"


# -- Round-trip through the storage read paths --------------------------------------


def test_task_origin_columns_round_trip_through_read_paths(ve_conn):
    task = S.create_task(M.TaskCreate(title="Round trip"), "u1")
    ve_conn.execute(
        "UPDATE tasks SET origin_seat = ?, origin_conversation_id = ?,"
        " origin_message_id = ?, origin_claim_id = ?, origin_decision_id = ?,"
        " responsible_seat = ? WHERE id = ?",
        ("champion", "conv-9", "msg-9", "claim-9", "dec-9", "guardian", task["id"]),
    )
    ve_conn.commit()
    fetched = S.get_task(task["id"], "u1")
    assert fetched is not None
    assert fetched["origin_seat"] == "champion"
    assert fetched["origin_conversation_id"] == "conv-9"
    assert fetched["origin_message_id"] == "msg-9"
    assert fetched["origin_claim_id"] == "claim-9"
    assert fetched["origin_decision_id"] == "dec-9"
    assert fetched["responsible_seat"] == "guardian"
    listed = S.list_tasks(user_id="u1")
    assert len(listed) == 1
    assert listed[0]["origin_seat"] == "champion"
    assert listed[0]["responsible_seat"] == "guardian"


def test_proposal_w0b_columns_round_trip_through_read_paths(ve_conn):
    ve_conn.execute(
        "INSERT INTO task_proposals (id, user_id, conversation_id, source_message_id,"
        " block_index, proposal_index, seat, title, notes, created_at, updated_at,"
        " evidence_quote, original_title, original_parent_task_id,"
        " original_timeframe_commitment, original_due_date, original_notes)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("prop-rt", "u1", "conv-1", "msg-1", 0, 0, "champion", "RT",
         "Notes", "2026-01-01", "2026-01-02",
         "We should RT", "RT", "pt-1", "tentative", "2026-12-01", "Notes"),
    )
    ve_conn.commit()
    rows = S.list_task_proposals("u1", "conv-1")
    assert len(rows) == 1
    assert rows[0]["evidence_quote"] == "We should RT"
    assert rows[0]["original_title"] == "RT"
    assert rows[0]["original_parent_task_id"] == "pt-1"
    assert rows[0]["original_timeframe_commitment"] == "tentative"
    assert rows[0]["original_due_date"] == "2026-12-01"
    assert rows[0]["original_notes"] == "Notes"
