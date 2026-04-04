"""
Vision Execution commit-alignment and workflow hardening tests.

Covers:
- Migration: required_assets (projects), required_asset_ids (tasks), linked_asset_ids (signals)
- Model: ProjectCreate and TaskCreate accept new asset fields
- Commit preview and payload behavior are documented in docs/03_IMPLEMENTATION_PLANS/WORKFLOW_HARDENING.md

Run from repo root: python -m pytest tests/test_vision_execution_commit_align.py -v
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _migrate_asset_columns(conn: sqlite3.Connection) -> None:
    """Same logic as local_ai.vision_execution.storage._migrate_asset_columns."""
    for table, column, default in [
        ("projects", "required_assets", "'[]'"),
        ("tasks", "required_asset_ids", "'[]'"),
        ("signals", "linked_asset_ids", "'[]'"),
    ]:
        cur = conn.execute(f"PRAGMA table_info({table})")
        if not any(r[1] == column for r in cur.fetchall()):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT NOT NULL DEFAULT {default}")
    conn.commit()


def test_migration_adds_asset_columns():
    """Migration adds required_assets, required_asset_ids, linked_asset_ids when missing."""
    conn = sqlite3.connect(":memory:")
    # Old schema: projects without required_assets, tasks without required_asset_ids, signals without linked_asset_ids
    conn.executescript("""
        CREATE TABLE projects (id TEXT PRIMARY KEY, initiative_id TEXT, title TEXT NOT NULL DEFAULT '', brief TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'Draft', owner_id TEXT, supporting_owner_ids TEXT NOT NULL DEFAULT '[]', priority TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE tasks (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '', assignee_id TEXT, status TEXT NOT NULL DEFAULT 'Todo', dependency_ids TEXT NOT NULL DEFAULT '[]', completion_criteria TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE signals (id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', detail TEXT, source TEXT NOT NULL DEFAULT '', linked_initiative_id TEXT, linked_project_id TEXT, linked_task_id TEXT, status TEXT NOT NULL DEFAULT 'new', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    """)
    conn.commit()
    _migrate_asset_columns(conn)
    for table, column in [("projects", "required_assets"), ("tasks", "required_asset_ids"), ("signals", "linked_asset_ids")]:
        cur = conn.execute(f"PRAGMA table_info({table})")
        names = [r[1] for r in cur.fetchall()]
        assert column in names, f"Migration should add {column} to {table}, got {names}"
    conn.close()


def test_project_create_model_accepts_required_assets():
    """ProjectCreate model includes required_assets."""
    from local_ai.vision_execution.models import ProjectCreate

    p = ProjectCreate(title="T", brief="B", status="Draft", required_assets=["asset-1", "asset-2"])
    assert p.required_assets == ["asset-1", "asset-2"]
    p2 = ProjectCreate(title="T", brief="B", status="Draft")
    assert getattr(p2, "required_assets", None) is not None
    assert p2.required_assets == []


def test_task_create_model_accepts_required_asset_ids():
    """TaskCreate model includes required_asset_ids."""
    from local_ai.vision_execution.models import TaskCreate

    t = TaskCreate(project_id="proj-1", title="T", required_asset_ids=["a1", "a2"])
    assert t.required_asset_ids == ["a1", "a2"]
    t2 = TaskCreate(project_id="proj-1", title="T")
    assert getattr(t2, "required_asset_ids", None) is not None
    assert t2.required_asset_ids == []

    t3 = TaskCreate(title="Standalone")
    assert t3.project_id is None


def test_signal_create_model_accepts_linked_asset_ids():
    """SignalCreate model includes linked_asset_ids."""
    from local_ai.signals.models import SignalCreate

    s = SignalCreate(kind="attention", title="T", source="meeting", linked_asset_ids=["x", "y"])
    assert s.linked_asset_ids == ["x", "y"]
    s2 = SignalCreate(kind="risk", title="R", source="meeting")
    assert getattr(s2, "linked_asset_ids", None) is not None
    assert s2.linked_asset_ids == []
