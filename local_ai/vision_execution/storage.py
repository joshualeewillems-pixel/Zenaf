"""
Vision Execution Engine — SQLite persistence. Init on first use; CRUD per entity.
"""
from pathlib import Path
import logging
import re
import sqlite3
import json
import os
import threading
import hashlib
import hmac
import secrets
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from typing import Any, NamedTuple

from . import models as M
from local_ai.hosted_config import is_prod as _is_prod
from local_ai.activity import (
    ActivityEntityType,
    ActivityType,
    COORDINATION_ACTIVITY_SOURCE_SERVER_EXECUTION,
)

_PKG_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _PKG_DIR.parent.parent
_DB_DIR = _REPO_ROOT / "data" / "vision_execution"
_DB_PATH = _DB_DIR / "vision_execution.db"
_SCHEMA_PATH = _PKG_DIR / "schema.sql"
_DEFAULT_OWNER_EMAIL = "owner@local.zenaf"
_DEFAULT_OWNER_DISPLAY_NAME = "Local Owner"
_DEFAULT_OWNER_PASSWORD_FALLBACK = "local-dev-owner"
_SESSION_TTL_DAYS = 30

# One SQLite connection per thread: FastAPI runs sync route handlers on a thread pool; a single
# shared connection is not safe for concurrent execute() and triggers InterfaceError (e.g. Python 3.14).
_thread_local = threading.local()
_init_lock = threading.Lock()
_init_done_paths: set[str] = set()

_logger = logging.getLogger(__name__)

_VE_ACTIVITY_SOURCE = "vision_execution"
# Aligned with frontend/src/vision-map/mapGrowthMetrics.ts statusDone()
_VE_TASK_DONE_STATUS_RE = re.compile(r"\b(done|complete|completed|shipped|closed|won)\b", re.IGNORECASE)
_VE_VITALITY_ENTITY_TYPES = frozenset(
    {
        ActivityEntityType.IDEA.value,
        ActivityEntityType.INITIATIVE.value,
        ActivityEntityType.PROJECT.value,
        ActivityEntityType.TASK.value,
    }
)


def _ve_activity_related_id(raw: str | None) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    return s or None


def _emit_fellowship_event(*, kind: str, user_id: str, entity_type: str,
                           entity_id: str, evidence_text: str = "",
                           summary: str = "",
                           payload: dict | None = None) -> None:
    """Fellowship Runtime P1 (local_ai/fellowship/events.py): record a
    runtime event at this chokepoint, for the off-path derivation.
    Lazy import + fully guarded, exactly like _log_ve_entity_activity
    — an event can never break the write that produced it."""
    try:
        from local_ai.fellowship.events import emit_event

        emit_event(
            kind=kind,
            user_id=user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            evidence_text=evidence_text,
            summary=summary,
            payload=payload,
        )
    except Exception:
        pass


def _ve_task_status_done(status: str | None) -> bool:
    if not status or not str(status).strip():
        return False
    return bool(_VE_TASK_DONE_STATUS_RE.search(str(status)))


# W1 (Refinement 1, founder verdict 2026-11-05): terminal-parent
# interpretation for the parent-availability check. The single
# existing authoritative "done" interpretation is
# _ve_task_status_done (shared with task-completion events). Dropped
# is terminal for parenting but NOT "done" — extending the shared
# regex would fire task_completed events for dropped tasks — so W1's
# parent check is that helper OR an exact normalized "dropped".
# No stored status is ever rewritten; no lifecycle machinery.
def _is_terminal_parent_status(status: str | None) -> bool:
    """True when a task's status makes it unavailable as a parent."""
    if status is None:
        return False
    if _ve_task_status_done(status):
        return True
    return str(status).strip().lower() == "dropped"


def _log_ve_entity_activity(
    *,
    type: str,
    entity_type: str,
    entity_id: str,
    user_id: str,
    related_entity_id: str | None = None,
    detail: str | None = None,
) -> None:
    event_id: str | None = None
    now_iso = _now()
    try:
        from local_ai.activity import log_activity_simple  # lazy: keeps optional deps clear

        event_id = log_activity_simple(
            type=type,
            entity_type=entity_type,
            entity_id=entity_id,
            related_entity_id=related_entity_id,
            actor=str(user_id),
            source=_VE_ACTIVITY_SOURCE,
            detail=detail,
        )
    except Exception:
        pass
    if event_id and entity_type in _VE_VITALITY_ENTITY_TYPES:
        _maybe_touch_node_vitality_from_activity(
            user_id, entity_type, entity_id, event_id, now_iso
        )


def _log_coordination_ve_activity(
    *,
    type: str,
    entity_type: str,
    entity_id: str,
    user_id: str,
    related_entity_id: str | None = None,
    detail: str | None = None,
) -> str | None:
    """Append ActivityEvent with coordination server source (not generic vision_execution)."""
    event_id: str | None = None
    now_iso = _now()
    try:
        from local_ai.activity import log_activity_simple

        event_id = log_activity_simple(
            type=type,
            entity_type=entity_type,
            entity_id=entity_id,
            related_entity_id=related_entity_id,
            actor=str(user_id),
            source=COORDINATION_ACTIVITY_SOURCE_SERVER_EXECUTION,
            detail=detail,
        )
    except Exception:
        pass
    if event_id and entity_type in _VE_VITALITY_ENTITY_TYPES:
        _maybe_touch_node_vitality_from_activity(
            user_id, entity_type, entity_id, event_id, now_iso
        )
    return event_id


def log_coordination_client_checkpoint(
    user_id: str,
    checkpoint: str,
    entity_type: str,
    entity_id: str,
    *,
    user_outcome: str | None = None,
    action_intent: str | None = None,
    trace_id: str | None = None,
    detail: str | None = None,
) -> str:
    """Append ActivityEvent with coordination client-trace source; verifies entity ownership."""
    from local_ai.activity import (
        ActivityType,
        COORDINATION_ACTIVITY_SOURCE_CLIENT_TRACE,
        log_activity_simple,
    )

    uid = (user_id or "").strip()
    if not uid:
        raise ValueError("user_id required")
    et = (entity_type or "").strip().lower()
    eid = (entity_id or "").strip()
    if not et or not eid:
        raise ValueError("entity_type and entity_id required")
    if et == ActivityEntityType.INITIATIVE.value:
        if get_initiative(eid, uid) is None:
            raise ValueError("entity not found or not owned")
    elif et == ActivityEntityType.PROJECT.value:
        if get_project(eid, uid) is None:
            raise ValueError("entity not found or not owned")
    elif et == ActivityEntityType.IDEA.value:
        if get_idea(eid, uid) is None:
            raise ValueError("entity not found or not owned")
    else:
        raise ValueError("unsupported entity_type for coordination checkpoint")
    cp = (checkpoint or "").strip()
    if cp == "ai_action_user_trace":
        atype = ActivityType.AI_ACTION_USER_TRACE.value
    elif cp == "ai_suggestion_applied":
        atype = ActivityType.AI_SUGGESTION_APPLIED.value
    else:
        raise ValueError("invalid checkpoint")
    parts: dict[str, Any] = {}
    if user_outcome:
        parts["user_outcome"] = str(user_outcome).strip()[:200]
    if action_intent:
        parts["action_intent"] = str(action_intent).strip()[:512]
    if trace_id:
        parts["trace_id"] = str(trace_id).strip()[:256]
    if detail:
        parts["note"] = str(detail).strip()[:2000]
    d = json.dumps(parts, ensure_ascii=False) if parts else None
    if d and len(d) > 2000:
        d = d[:2000]
    now_iso = _now()
    event_id = log_activity_simple(
        type=atype,
        entity_type=et,
        entity_id=eid,
        actor=uid,
        source=COORDINATION_ACTIVITY_SOURCE_CLIENT_TRACE,
        detail=d,
    )
    if event_id and et in _VE_VITALITY_ENTITY_TYPES:
        _maybe_touch_node_vitality_from_activity(uid, et, eid, event_id, now_iso)
    if event_id:
        try:
            from local_ai.vision_execution.coordination_signals import (
                append_execution_flow_reading,
            )

            uo = str(user_outcome or "").strip().lower()
            applied_suggestion = cp == "ai_suggestion_applied" and uo == "applied"
            friction_checkpoint = cp == "ai_suggestion_applied" and uo in ("stuck", "dismissed")
            if applied_suggestion:
                append_execution_flow_reading(
                    user_id=uid,
                    entity_type=et,
                    entity_id=eid,
                    pointer=event_id,
                    pointer_kind="activity_event",
                    evidence_source="zenaf-client-trace",
                    impact="positive",
                    dimension="capacity",
                    confidence=0.6,
                )
            elif friction_checkpoint:
                append_execution_flow_reading(
                    user_id=uid,
                    entity_type=et,
                    entity_id=eid,
                    pointer=event_id,
                    pointer_kind="activity_event",
                    evidence_source="zenaf-client-trace",
                    impact="negative",
                    dimension="friction",
                    confidence=0.6,
                )
            else:
                append_execution_flow_reading(
                    user_id=uid,
                    entity_type=et,
                    entity_id=eid,
                    pointer=event_id,
                    pointer_kind="activity_event",
                    evidence_source="zenaf-client-trace",
                    impact="neutral",
                    dimension="capacity",
                    confidence=0.5,
                )
        except Exception as exc:
            # TODO/coordination: checkpoint still succeeds; we degrade to activity-only evidence
            # (no execution_flow_reading row) if append fails—HTTP/client still get activity_event_id.
            _logger.warning(
                "coordination client-checkpoint: execution_flow_reading append failed: %s",
                exc,
                exc_info=True,
            )
    return event_id


# Concurrent API + council: WAL reduces writer blocking; busy_timeout avoids immediate SQLITE_BUSY.
_SQLITE_BUSY_TIMEOUT_MS = 5000


def _apply_sqlite_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")


def open_sqlite_with_ve_pragmas(
    db_path: Path | str, *, check_same_thread: bool = False
) -> sqlite3.Connection:
    """Open SQLite with the same row factory and pragmas as production VE (tests: use tmp_path only)."""
    conn = sqlite3.connect(str(db_path), check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    _apply_sqlite_pragmas(conn)
    return conn


def resolved_vision_execution_db_path() -> Path:
    """Absolute path to the Vision Execution SQLite file (ops logging / diagnostics)."""
    return _DB_PATH.resolve()


def _migrate_asset_columns(conn: sqlite3.Connection) -> None:
    """Add required_assets / required_asset_ids / linked_asset_ids if missing (existing DBs)."""
    for table, column, default in [
        ("projects", "required_assets", "'[]'"),
        ("tasks", "required_asset_ids", "'[]'"),
        ("signals", "linked_asset_ids", "'[]'"),
    ]:
        cur = conn.execute(f"PRAGMA table_info({table})")
        if not any(r[1] == column for r in cur.fetchall()):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT NOT NULL DEFAULT {default}")
    conn.commit()


def _migrate_keystone_columns(conn: sqlite3.Connection) -> None:
    """Add seed_key to initiatives and seat_ref to tasks if missing (existing DBs)."""
    for table, column in [
        ("initiatives", "seed_key"),
        ("tasks", "seat_ref"),
    ]:
        cur = conn.execute(f"PRAGMA table_info({table})")
        if not any(r[1] == column for r in cur.fetchall()):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
    conn.commit()


def _migrate_tasks_timeframe_commitment(conn: sqlite3.Connection) -> None:
    """Add timeframe_commitment to tasks if missing (existing DBs).

    NULL = unspecified (the default for every pre-existing row — nothing
    is retroactively tentative). The only other accepted value is
    "tentative"; enforcement lives in create_task / update_task, not
    in the column, so the migration stays a plain nullable TEXT column
    in the repo's PRAGMA-checked ALTER TABLE pattern.
    """
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'")
    if cur.fetchone() is None:
        return
    info = conn.execute("PRAGMA table_info(tasks)")
    if not any(r[1] == "timeframe_commitment" for r in info.fetchall()):
        conn.execute("ALTER TABLE tasks ADD COLUMN timeframe_commitment TEXT")
    conn.commit()


def _migrate_tasks_provenance_columns(conn: sqlite3.Connection) -> None:
    """W0B: add weave provenance columns to tasks if missing (existing DBs).

    Additive schema only — NO behavior change. All six columns are
    nullable TEXT with no default, so every pre-existing row reads NULL
    (absent = absent). NO backfill: legacy origins are unknowable, and
    copying any existing value into an origin column would fabricate
    provenance. Nothing writes these columns yet; the W1 producer will
    populate them at task creation, and the population rule is:

    - origin_seat: the proposing seat's archetype id (required for
      producer-created tasks). It is NOT stewardship.
    - origin_conversation_id / origin_message_id / origin_claim_id:
      the conversation, turn, and (nullable) review claim the proposal
      came from.
    - origin_decision_id: the user decision that authorized creation.
      Under the W0B anchor decision this is the approving PROPOSAL ROW
      itself (proposal id + decided_at + user_id); the column is a
      generic nullable TEXT reference with no foreign key, so a future
      authoritative transition record could anchor it instead WITHOUT
      a schema change — repointing the anchor convention is a
      separately authorized lifecycle-slice decision, not a migration.
      W0B implements no transition record of any kind.
    - responsible_seat: the seat currently stewarding execution, if
      assigned. Set ONLY by the user via task PATCH, NEVER by the
      producer, NEVER defaulted from origin_seat.

    seat_ref is deliberately UNTOUCHED by this migration: it stays
    keystone-scoped (written only by keystone seeding and, until W1
    removes it, the Capability B approve path) and is never the
    provenance field. The producer never writes seat_ref.
    """
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'")
    if cur.fetchone() is None:
        return
    for column in (
        "origin_seat",
        "origin_conversation_id",
        "origin_message_id",
        "origin_claim_id",
        "origin_decision_id",
        "responsible_seat",
    ):
        info = conn.execute("PRAGMA table_info(tasks)")
        if not any(r[1] == column for r in info.fetchall()):
            conn.execute(f"ALTER TABLE tasks ADD COLUMN {column} TEXT")
    conn.commit()


def _migrate_checklist_person_asset_columns(conn: sqlite3.Connection) -> None:
    """Add person_id / asset_id to checklist_items if missing (existing DBs)."""
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='checklist_items'")
    if cur.fetchone() is None:
        return
    for column in ("person_id", "asset_id"):
        cur = conn.execute("PRAGMA table_info(checklist_items)")
        if not any(r[1] == column for r in cur.fetchall()):
            conn.execute(f"ALTER TABLE checklist_items ADD COLUMN {column} TEXT")
    conn.commit()


def _migrate_execution_steps_table(conn: sqlite3.Connection) -> None:
    """Create execution_steps for DBs that predate schema.sql update."""
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='execution_steps'")
    if cur.fetchone() is not None:
        return
    conn.execute("""
        CREATE TABLE execution_steps (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          scope_type TEXT NOT NULL CHECK (scope_type IN ('initiative', 'project')),
          scope_id TEXT NOT NULL,
          title TEXT NOT NULL DEFAULT '',
          sort_order INTEGER NOT NULL DEFAULT 0,
          is_done INTEGER NOT NULL DEFAULT 0 CHECK (is_done IN (0, 1)),
          completed_at TEXT,
          source TEXT NOT NULL DEFAULT 'user' CHECK (source IN ('ai', 'user', 'import')),
          source_evaluation_id TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_execution_steps_scope_list ON execution_steps (user_id, scope_type, scope_id, sort_order)"
    )
    conn.commit()


def _migrate_initiative_evaluation_priority(conn: sqlite3.Connection) -> None:
    """Add evaluation_priority (model-suggested priority 0–5) if missing."""
    cur = conn.execute("PRAGMA table_info(initiatives)")
    if any(r[1] == "evaluation_priority" for r in cur.fetchall()):
        return
    conn.execute("ALTER TABLE initiatives ADD COLUMN evaluation_priority INTEGER")
    conn.commit()


def _migrate_core_profile_raw_notes(conn: sqlite3.Connection) -> None:
    """Add raw_notes to core_profiles if missing (existing DBs)."""
    cur = conn.execute("PRAGMA table_info(core_profiles)")
    if not any(r[1] == "raw_notes" for r in cur.fetchall()):
        conn.execute("ALTER TABLE core_profiles ADD COLUMN raw_notes TEXT NOT NULL DEFAULT ''")
    conn.commit()


def _migrate_core_profile_is_primary(conn: sqlite3.Connection) -> None:
    """Add is_primary to core_profiles; backfill when a user has exactly one profile."""
    cur = conn.execute("PRAGMA table_info(core_profiles)")
    if any(r[1] == "is_primary" for r in cur.fetchall()):
        return
    conn.execute("ALTER TABLE core_profiles ADD COLUMN is_primary INTEGER NOT NULL DEFAULT 0")
    for row in conn.execute(
        "SELECT user_id FROM core_profiles GROUP BY user_id HAVING COUNT(*) = 1"
    ).fetchall():
        uid = row[0]
        if uid:
            conn.execute("UPDATE core_profiles SET is_primary = 1 WHERE user_id = ?", (uid,))
    conn.commit()


def _migrate_content_briefs(conn: sqlite3.Connection) -> None:
    """Create content_briefs table if missing (existing DBs)."""
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='content_briefs'")
    if cur.fetchone() is not None:
        return
    conn.execute("""
        CREATE TABLE content_briefs (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'draft',
          payload TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
    """)
    conn.commit()


def _migrate_auth_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
          id TEXT PRIMARY KEY,
          email TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL,
          display_name TEXT NOT NULL DEFAULT '',
          is_admin INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          token_hash TEXT NOT NULL UNIQUE,
          created_at TEXT NOT NULL,
          expires_at TEXT NOT NULL,
          revoked_at TEXT,
          FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at)")
    conn.commit()


def _migrate_upload_outcome_creations(conn: sqlite3.Connection) -> None:
    """Upload rapid-fire S1 §2.10 (U-1): the VE idempotency carrier.

    One row per outcome whose VE record was created, written in the
    SAME VE transaction as the VE record it records (the insert and
    the create_* insert commit together, or neither does).
    ``outcome_id`` as PRIMARY KEY is the idempotency guarantee — a
    replay for the same outcome hits the existing row and returns
    the existing VE record. ``node_id`` stays NULL in S1 (S-NODE
    fills it at flip time; U-10 deferred to C1b).
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS upload_outcome_creations (
          outcome_id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          ve_kind TEXT NOT NULL,
          ve_id TEXT NOT NULL,
          node_id TEXT,
          created_at TEXT NOT NULL
        )
    """)
    conn.commit()


def _migrate_user_admin_column(conn: sqlite3.Connection) -> None:
    cur = conn.execute("PRAGMA table_info(users)")
    cols = {r[1] for r in cur.fetchall()}
    if "is_admin" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
        conn.commit()


def _migrate_users_avatar_data_url(conn: sqlite3.Connection) -> None:
    cur = conn.execute("PRAGMA table_info(users)")
    cols = {r[1] for r in cur.fetchall()}
    if "avatar_data_url" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN avatar_data_url TEXT")
        conn.commit()


def _migrate_user_permissions_settings(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_permissions_settings (
          user_id TEXT PRIMARY KEY,
          consent_given INTEGER NOT NULL DEFAULT 0 CHECK (consent_given IN (0, 1)),
          consent_version TEXT NOT NULL DEFAULT '',
          consent_at TEXT,
          permissions_json TEXT NOT NULL DEFAULT '{}',
          updated_at TEXT NOT NULL,
          FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )
    # Permission Slice 1 (foundation): extend the SAME row with the
    # stance store (stances_json + pause_json columns) and the
    # append-only stance-history table. Imported lazily so this
    # module never depends on the permissions package at import
    # time. Existing rows read the '{}' defaults — no stances, no
    # pause — exactly as if the user had never set one.
    from local_ai.permissions.store import ensure_permission_framework_schema

    ensure_permission_framework_schema(conn)
    conn.commit()


def _migrate_workspace_messages(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS workspace_messages (
          id TEXT PRIMARY KEY,
          from_user_id TEXT NOT NULL,
          to_user_id TEXT NOT NULL,
          title TEXT NOT NULL,
          body_json TEXT NOT NULL,
          read_at TEXT,
          created_at TEXT NOT NULL,
          FOREIGN KEY (from_user_id) REFERENCES users(id),
          FOREIGN KEY (to_user_id) REFERENCES users(id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_workspace_messages_to_created ON workspace_messages(to_user_id, created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_workspace_messages_from_created ON workspace_messages(from_user_id, created_at DESC)"
    )
    conn.commit()


def _migrate_tasks_nullable_project_id(conn: sqlite3.Connection) -> None:
    """Allow tasks without a project (project_id NULL). Rebuilds table when project_id was NOT NULL."""
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'")
    if cur.fetchone() is None:
        return
    info = conn.execute("PRAGMA table_info(tasks)").fetchall()
    proj = next((r for r in info if r[1] == "project_id"), None)
    if proj is None or proj[3] == 0:
        return
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.executescript(
        """
        CREATE TABLE tasks_new (
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
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          FOREIGN KEY (project_id) REFERENCES projects(id),
          FOREIGN KEY (parent_task_id) REFERENCES tasks(id),
          FOREIGN KEY (assignee_id) REFERENCES persons(id)
        );
        INSERT INTO tasks_new SELECT * FROM tasks;
        DROP TABLE tasks;
        ALTER TABLE tasks_new RENAME TO tasks;
        CREATE INDEX IF NOT EXISTS idx_tasks_user_id ON tasks(user_id);
        """
    )
    conn.execute("PRAGMA foreign_keys=ON")
    conn.commit()


def _migrate_studio_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS studio_system_settings (
          key TEXT PRIMARY KEY,
          value_json TEXT NOT NULL DEFAULT '{}',
          updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS council_teacher_runs (
          id TEXT PRIMARY KEY,
          created_at TEXT NOT NULL,
          user_id TEXT,
          execution_scope TEXT,
          execution_principal_ref TEXT,
          capability_name TEXT NOT NULL DEFAULT 'council',
          teacher_mode TEXT NOT NULL,
          final_selection_policy TEXT,
          prompt_version TEXT,
          native_provider TEXT,
          native_model TEXT,
          teacher_provider_requested TEXT,
          teacher_model_requested TEXT,
          teacher_provider_effective TEXT,
          teacher_model_effective TEXT,
          teacher_succeeded INTEGER NOT NULL DEFAULT 0,
          native_text TEXT,
          teacher_text TEXT,
          native_artifact_json TEXT,
          teacher_artifact_json TEXT,
          native_run_debug_json TEXT,
          teacher_run_debug_json TEXT,
          comparison_json TEXT,
          error TEXT
        )
        """
    )
    cur = conn.execute("PRAGMA table_info(council_teacher_runs)")
    cols = {r[1] for r in cur.fetchall()}
    if "native_run_debug_json" not in cols:
        conn.execute("ALTER TABLE council_teacher_runs ADD COLUMN native_run_debug_json TEXT")
    if "teacher_run_debug_json" not in cols:
        conn.execute("ALTER TABLE council_teacher_runs ADD COLUMN teacher_run_debug_json TEXT")
    for col, decl in (
        ("teacher_enforcement_mode", "TEXT"),
        ("teacher_vetoed", "INTEGER NOT NULL DEFAULT 0"),
        ("teacher_warning", "INTEGER NOT NULL DEFAULT 0"),
        ("teacher_final_source", "TEXT"),
        ("teacher_reason_codes_json", "TEXT"),
        ("teacher_notes", "TEXT"),
    ):
        if col not in cols:
            conn.execute(f"ALTER TABLE council_teacher_runs ADD COLUMN {col} {decl}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_council_teacher_runs_created_at ON council_teacher_runs(created_at DESC)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS council_stream_runs (
          id TEXT PRIMARY KEY,
          created_at TEXT NOT NULL,
          user_id TEXT,
          integrity_run_id TEXT,
          artifact_json TEXT NOT NULL,
          full_text TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_council_stream_runs_integrity ON council_stream_runs(integrity_run_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_council_stream_runs_user_created ON council_stream_runs(user_id, created_at)")
    conn.commit()


def _migrate_node_memory_tables(conn: sqlite3.Connection) -> None:
    """node_vitality + node_judgment_history (SubjectRef-keyed memory index)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS node_vitality (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            water REAL DEFAULT 0.0,
            soil REAL DEFAULT 0.0,
            fruit REAL DEFAULT 0.0,
            staleness_days REAL DEFAULT 0.0,
            last_activity_at TEXT,
            last_assessed_at TEXT NOT NULL,
            triggered_by_event_id TEXT,
            rules_version TEXT DEFAULT 'v1',
            payload_json TEXT,
            UNIQUE(user_id, entity_type, entity_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_node_vitality_user_entity ON node_vitality(user_id, entity_type)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS node_judgment_history (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            verdict_kind TEXT NOT NULL,
            effect TEXT NOT NULL,
            state TEXT NOT NULL,
            mechanism_mode TEXT NOT NULL,
            observation_pointer TEXT,
            council_stream_run_id TEXT,
            decision_id TEXT,
            intake_judgment_id TEXT,
            trunk_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_njh_subject
        ON node_judgment_history(user_id, entity_type, entity_id, created_at)
        """
    )
    conn.commit()


def _migrate_aspiration_tables(conn: sqlite3.Connection) -> None:
    """Aspiration profile, inference log, and proposal rows (CREATE IF NOT EXISTS for existing DBs)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS aspiration_profile (
          user_id TEXT PRIMARY KEY,
          core_aim TEXT NOT NULL DEFAULT '',
          growth_domains TEXT NOT NULL DEFAULT '[]',
          current_edge TEXT NOT NULL DEFAULT '',
          current_obstacles TEXT NOT NULL DEFAULT '',
          near_term_aspirations TEXT NOT NULL DEFAULT '',
          long_term_aspirations TEXT NOT NULL DEFAULT '',
          guidance_preferences TEXT NOT NULL DEFAULT '{}',
          anti_goals TEXT NOT NULL DEFAULT '',
          heart_loves TEXT NOT NULL DEFAULT '',
          heart_meaning TEXT NOT NULL DEFAULT '',
          heart_commitments TEXT NOT NULL DEFAULT '',
          use_in_guidance INTEGER NOT NULL DEFAULT 0 CHECK (use_in_guidance IN (0, 1)),
          allow_inference INTEGER NOT NULL DEFAULT 0 CHECK (allow_inference IN (0, 1)),
          updated_at TEXT NOT NULL,
          FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )
    # Phase 2 (Narrative Steward, Part IX dependency): Heart fields
    # for loves, sources of meaning, and commitments. Databases
    # created before Phase 2 have no such columns (CREATE TABLE IF
    # NOT EXISTS does not add them). Additive only; a missing
    # column reads back as "not stated" for older rows. The fields
    # hold user-stated text only — nothing in this codebase infers
    # or invents Heart values; the Phase 2 aspiration bridge
    # renders them verbatim when the guidance gates allow.
    _heart_columns = {
        row[1]
        for row in conn.execute(
            "PRAGMA table_info(aspiration_profile)"
        ).fetchall()
    }
    for _heart_col in ("heart_loves", "heart_meaning", "heart_commitments"):
        if _heart_col not in _heart_columns:
            conn.execute(
                f"ALTER TABLE aspiration_profile ADD COLUMN {_heart_col} "
                "TEXT NOT NULL DEFAULT ''"
            )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS aspiration_inference_log (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          snapshot_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_aspiration_inference_log_user ON aspiration_inference_log(user_id, created_at DESC)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS aspiration_proposals (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          theme TEXT NOT NULL DEFAULT '',
          detail TEXT NOT NULL DEFAULT '',
          basis_json TEXT NOT NULL DEFAULT '[]',
          status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'dismissed')),
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_aspiration_proposals_user_status ON aspiration_proposals(user_id, status)"
    )
    conn.commit()


def _migrate_strand_weightings_table(conn: sqlite3.Connection) -> None:
    """Standalone strand_weightings table (CREATE IF NOT EXISTS for existing DBs).

    Keyed by (user_id, entity_type, entity_id). Sparse by design: entities
    without a row are treated as never-weighed (unknown) by
    local_ai.entity_strands — no backfilling of defaults.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS strand_weightings (
          user_id TEXT NOT NULL,
          entity_type TEXT NOT NULL CHECK (entity_type IN ('person','project','task','asset','job')),
          entity_id TEXT NOT NULL,
          weights_json TEXT NOT NULL DEFAULT '{}',
          source TEXT NOT NULL DEFAULT '' CHECK (source IN ('','user_stated','inferred','mined')),
          updated_at TEXT NOT NULL,
          PRIMARY KEY (user_id, entity_type, entity_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_strand_weightings_entity ON strand_weightings(entity_type, entity_id)"
    )
    conn.commit()


def _ensure_user_id_column(conn: sqlite3.Connection, table: str) -> None:
    cur = conn.execute(f"PRAGMA table_info({table})")
    if not any(r[1] == "user_id" for r in cur.fetchall()):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN user_id TEXT")


def _migrate_llm_provider_prefs_json(conn: sqlite3.Connection) -> None:
    cur = conn.execute("PRAGMA table_info(user_llm_profile)")
    if any(r[1] == "llm_provider_prefs_json" for r in cur.fetchall()):
        return
    conn.execute(
        "ALTER TABLE user_llm_profile ADD COLUMN llm_provider_prefs_json TEXT NOT NULL DEFAULT '{}'"
    )
    conn.commit()


def _migrate_idea_notes_column(conn: sqlite3.Connection) -> None:
    cur = conn.execute("PRAGMA table_info(ideas)")
    cols = {r[1] for r in cur.fetchall()}
    if "notes" not in cols:
        conn.execute("ALTER TABLE ideas ADD COLUMN notes TEXT NOT NULL DEFAULT ''")


def _migrate_user_ownership_columns(conn: sqlite3.Connection) -> None:
    _ensure_user_id_column(conn, "core_profiles")
    _ensure_user_id_column(conn, "content_briefs")
    _ensure_user_id_column(conn, "ideas")
    _ensure_user_id_column(conn, "initiatives")
    _ensure_user_id_column(conn, "projects")
    _ensure_user_id_column(conn, "tasks")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_core_profiles_user_id ON core_profiles(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_content_briefs_user_id ON content_briefs(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ideas_user_id ON ideas(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_initiatives_user_id ON initiatives(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_projects_user_id ON projects(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_user_id ON tasks(user_id)")
    conn.commit()


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _hash_password(password: str, *, salt: str | None = None) -> str:
    salt_hex = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), 150000)
    return f"pbkdf2_sha256${salt_hex}${digest.hex()}"


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        algo, salt_hex, _ = password_hash.split("$", 2)
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    candidate = _hash_password(password, salt=salt_hex)
    return hmac.compare_digest(candidate, password_hash)


def _hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _llm_credential_row_count(conn: sqlite3.Connection, user_id: str) -> int:
    r = conn.execute(
        "SELECT COUNT(*) AS c FROM user_llm_provider_credentials WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    return int(r["c"] or 0) if r else 0


def _copy_user_llm_stack(conn: sqlite3.Connection, source_user_id: str, dest_user_id: str) -> None:
    """Copy LLM profile row + all provider credentials from source to dest (dest ciphertext reused as-is)."""
    if source_user_id == dest_user_id:
        return
    now = _now()
    for uid in (source_user_id, dest_user_id):
        conn.execute(
            "INSERT OR IGNORE INTO user_llm_profile (user_id, default_provider, default_model, ollama_base_url, "
            "ollama_model, llm_provider_prefs_json, updated_at) VALUES (?, 'ollama', NULL, NULL, NULL, '{}', ?)",
            (uid, now),
        )
    src = conn.execute(
        "SELECT default_provider, default_model, ollama_base_url, ollama_model, llm_provider_prefs_json "
        "FROM user_llm_profile WHERE user_id = ?",
        (source_user_id,),
    ).fetchone()
    if not src:
        return
    conn.execute(
        "UPDATE user_llm_profile SET default_provider = ?, default_model = ?, ollama_base_url = ?, "
        "ollama_model = ?, llm_provider_prefs_json = ?, updated_at = ? WHERE user_id = ?",
        (
            src["default_provider"],
            src["default_model"],
            src["ollama_base_url"],
            src["ollama_model"],
            src["llm_provider_prefs_json"] or "{}",
            now,
            dest_user_id,
        ),
    )
    conn.execute("DELETE FROM user_llm_provider_credentials WHERE user_id = ?", (dest_user_id,))
    cred_rows = conn.execute(
        "SELECT provider, api_key_ciphertext, extra_json, updated_at FROM user_llm_provider_credentials WHERE user_id = ?",
        (source_user_id,),
    ).fetchall()
    for cr in cred_rows:
        ex = cr["extra_json"] if cr["extra_json"] is not None else "{}"
        if not isinstance(ex, str):
            ex = "{}"
        conn.execute(
            "INSERT INTO user_llm_provider_credentials (id, user_id, provider, api_key_ciphertext, extra_json, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (M.new_id(), dest_user_id, cr["provider"], cr["api_key_ciphertext"], ex, cr["updated_at"] or now),
        )


def _ensure_default_owner_and_backfill(conn: sqlite3.Connection) -> None:
    now = _now()
    owner = conn.execute(
        "SELECT id FROM users WHERE email = ?",
        (_DEFAULT_OWNER_EMAIL,),
    ).fetchone()
    if owner is None:
        bootstrap_password = os.environ.get("ZENAF_BOOTSTRAP_PASSWORD", "").strip()
        if not bootstrap_password:
            if _is_prod():
                raise RuntimeError(
                    "ZENAF_BOOTSTRAP_PASSWORD must be set in production (ZENAF_PROD=1); "
                    "refusing to create the owner account with a dev fallback password."
                )
            print(
                "WARNING: ZENAF_BOOTSTRAP_PASSWORD is not set. "
                "Using local-dev fallback bootstrap password for owner@local.zenaf. "
                "This is DEV ONLY and not production-safe."
            )
            bootstrap_password = _DEFAULT_OWNER_PASSWORD_FALLBACK
        uid = M.new_id()
        conn.execute(
            "INSERT INTO users (id, email, password_hash, display_name, is_admin, created_at, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?)",
            (uid, _DEFAULT_OWNER_EMAIL, _hash_password(bootstrap_password), _DEFAULT_OWNER_DISPLAY_NAME, now, now),
        )
        owner_id = uid
    else:
        owner_id = owner[0]
    conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (owner_id,))

    conn.execute("UPDATE core_profiles SET user_id = ? WHERE user_id IS NULL", (owner_id,))
    conn.execute("UPDATE content_briefs SET user_id = ? WHERE user_id IS NULL", (owner_id,))
    conn.execute("UPDATE ideas SET user_id = ? WHERE user_id IS NULL", (owner_id,))
    conn.execute("UPDATE initiatives SET user_id = ? WHERE user_id IS NULL", (owner_id,))
    conn.execute("UPDATE projects SET user_id = ? WHERE user_id IS NULL", (owner_id,))
    conn.execute("UPDATE tasks SET user_id = ? WHERE user_id IS NULL", (owner_id,))
    conn.commit()


def init_db(conn: sqlite3.Connection) -> None:
    if _SCHEMA_PATH.exists():
        conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    _migrate_asset_columns(conn)
    _migrate_checklist_person_asset_columns(conn)
    _migrate_execution_steps_table(conn)
    _migrate_initiative_evaluation_priority(conn)
    _migrate_core_profile_raw_notes(conn)
    _migrate_core_profile_is_primary(conn)
    _migrate_content_briefs(conn)
    _migrate_auth_tables(conn)
    _migrate_user_admin_column(conn)
    _migrate_users_avatar_data_url(conn)
    _migrate_user_permissions_settings(conn)
    _migrate_studio_tables(conn)
    _migrate_user_ownership_columns(conn)
    _migrate_llm_provider_prefs_json(conn)
    _migrate_workspace_messages(conn)
    _migrate_tasks_nullable_project_id(conn)
    _migrate_idea_notes_column(conn)
    _migrate_node_memory_tables(conn)
    _migrate_aspiration_tables(conn)
    _migrate_strand_weightings_table(conn)
    _migrate_keystone_columns(conn)
    _migrate_tasks_timeframe_commitment(conn)
    _migrate_tasks_provenance_columns(conn)
    _migrate_task_proposals(conn)
    _migrate_migration_ledger(conn)
    _migrate_node_store(conn)
    _migrate_upload_outcome_creations(conn)
    _ensure_default_owner_and_backfill(conn)
    conn.commit()


def get_connection() -> sqlite3.Connection:
    resolved = str(_DB_PATH.resolve())
    cached = getattr(_thread_local, "conn", None)
    cached_path = getattr(_thread_local, "db_path_resolved", None)
    if cached is not None and cached_path == resolved:
        return cached
    if cached is not None:
        try:
            cached.close()
        except sqlite3.Error:
            pass
        _thread_local.conn = None
        _thread_local.db_path_resolved = None

    _DB_DIR.mkdir(parents=True, exist_ok=True)
    # Serialize first-time init: do not hand out thread connections until init_db has committed on
    # this file. Otherwise another thread can sqlite3.connect the same path before DDL finishes and
    # later skip init — breaking reads (e.g. login) on a half-initialized or empty schema.
    with _init_lock:
        if resolved not in _init_done_paths:
            bootstrap = open_sqlite_with_ve_pragmas(_DB_PATH, check_same_thread=True)
            try:
                init_db(bootstrap)
                _init_done_paths.add(resolved)
            finally:
                bootstrap.close()

    conn = open_sqlite_with_ve_pragmas(_DB_PATH, check_same_thread=True)
    _thread_local.conn = conn
    _thread_local.db_path_resolved = resolved
    return conn


def _now() -> str:
    return M._now_iso()


# ======================================================================
# C1a — Write-authority infrastructure (unified-node cutover, C1a).
#
# Governing design: ~/workspace/your_files/zenaf-ve-unified-node-
# c1a-design-brief-2026-11-06.md (§§2-17), accepted 2026-11-06.
# This section builds ONLY the C1a mechanisms: the migration ledger
# (§2), the node-store tables (§3), the shared write-transaction
# helper (§4), the writer guards (§5), the delete_project cascade
# guard (§6), the durable pause + operator controls (§7), the
# flip-attempt tracking + recovery procedure (§§8-9), the write
# freeze (§10), the in-transaction fingerprint (§11), and the
# contention behavior (§12). It builds NO flip, NO read shim, NO
# node-write CRUD, and NO migrated-node deletion (C1b/C2 scope).
# With zero flipped subtrees the guard never refuses and no read
# changes: the guard is dormant in production behavior in C1a.
# ======================================================================

# --- C1a §5.2: named refusal errors ------------------------------------
# Following the existing precedent (ProposalNotFound, ProposalConflict
# at storage.py:5056,5060). A refused flip or write is an expected,
# named outcome — mapped by _migration_error in
# api/routes/vision_execution.py, never a 500.


class MigratedNodeWriteRefused(Exception):
    """A legacy write targets a flipped subtree. API mapping: 409."""

    def __init__(self, message: str, *, subtree_id: str | None = None,
                 target_id: str | None = None) -> None:
        super().__init__(message)
        self.subtree_id = subtree_id
        self.target_id = target_id


class SubtreeWriteFrozen(Exception):
    """Any write targets a subtree with an unresolved failed_after_commit
    attempt (§10). API mapping: 423."""

    def __init__(self, message: str, *, subtree_id: str | None = None,
                 target_id: str | None = None,
                 attempt_id: str | None = None) -> None:
        super().__init__(message)
        self.subtree_id = subtree_id
        self.target_id = target_id
        self.attempt_id = attempt_id


class MigrationPaused(Exception):
    """A flip is attempted while the pause is engaged (or while no
    release exists for the subtree). API mapping: 409."""

    def __init__(self, message: str, *, subtree_id: str | None = None) -> None:
        super().__init__(message)
        self.subtree_id = subtree_id


class UnresolvedFlipAttempt(Exception):
    """A flip is attempted while an unresolved attempt exists (a
    `recorded` attempt blocks ALL subtrees; a `failed_*` attempt
    blocks its own subtree). API mapping: 409."""

    def __init__(self, message: str, *, subtree_id: str | None = None,
                 attempt_id: str | None = None,
                 attempt_state: str | None = None) -> None:
        super().__init__(message)
        self.subtree_id = subtree_id
        self.attempt_id = attempt_id
        self.attempt_state = attempt_state


class ProjectHasTasks(Exception):
    """§6: delete_project refused while the project has tasks.
    API mapping: 409. Detail names the count."""

    def __init__(self, message: str, *, project_id: str | None = None,
                 task_count: int | None = None) -> None:
        super().__init__(message)
        self.project_id = project_id
        self.task_count = task_count


# --- C1a §4.1: the shared write-transaction helper -----------------------
# Owner token, not SAVEPOINT (record §3.7): savepoints silently change
# failure semantics. The token is thread-local (the connection is
# thread-local); it holds token_id, purpose, depth, and the connection
# object itself (holding the conn prevents id-reuse confusion).


class _WriteTransactionHandle(NamedTuple):
    """Yielded by ve_write_transaction: `.is_owner` (bool), `.depth` (int)."""

    is_owner: bool
    depth: int


def _write_tokens() -> dict[int, dict[str, Any]]:
    """The thread's active helper-transaction tokens, keyed by id(conn).

    Lazily created: test fixtures replace `_thread_local` with a fresh
    threading.local(), so the attribute must never be assumed present.
    """
    tokens = getattr(_thread_local, "ve_write_tokens", None)
    if tokens is None:
        tokens = {}
        _thread_local.ve_write_tokens = tokens
    return tokens


def _active_write_token(conn: sqlite3.Connection) -> dict[str, Any] | None:
    """The helper token for this connection on this thread, if any."""
    token = _write_tokens().get(id(conn))
    if token is not None and token.get("conn") is conn:
        return token
    return None


@contextmanager
def ve_write_transaction(conn: sqlite3.Connection, purpose: str):
    """Open a helper transaction (BEGIN IMMEDIATE) if the thread does not
    already own one on this connection; otherwise join the existing one.
    On clean exit the OWNER commits; on exception the OWNER rolls back.
    Yields a handle with `.is_owner` (bool) and `.depth` (int).

    Rules (§4.2): BEGIN IMMEDIATE before any authority read; one owner
    per connection per thread; re-entrant nesting, never a second BEGIN;
    only the owner commits or rolls back. A nested commit is a no-op; a
    nested rollback raises (see _rollback_if_owner).

    Ambient-transaction adoption (brief-ambiguity resolution, §4.1):
    the brief does not name the case where no token exists but the
    connection already has an implicit transaction open (e.g. a prior
    uncommitted write on the thread-local connection). The helper
    ADOPTS that transaction as the owner's — mirroring the approve
    path's pre-existing `if not conn.in_transaction` guard — rather
    than raising or issuing a second BEGIN (SQLite would raise).
    """
    tokens = _write_tokens()
    key = id(conn)
    token = tokens.get(key)
    if token is not None and token.get("conn") is conn:
        token["depth"] += 1
        handle = _WriteTransactionHandle(is_owner=False, depth=token["depth"])
        try:
            yield handle
        except BaseException:
            token["depth"] -= 1
            raise
        else:
            token["depth"] -= 1
        return
    adopted = bool(conn.in_transaction)
    if not adopted:
        conn.execute("BEGIN IMMEDIATE")
    token = {
        "token_id": M.new_id(),
        "purpose": purpose,
        "depth": 1,
        "conn": conn,
        "adopted": adopted,
    }
    tokens[key] = token
    try:
        yield _WriteTransactionHandle(is_owner=True, depth=1)
    except BaseException as exc:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        tokens.pop(key, None)
        _maybe_record_write_refusal(conn, exc)
        raise
    else:
        try:
            conn.commit()
        finally:
            tokens.pop(key, None)


def _commit_if_owner(conn: sqlite3.Connection) -> None:
    """Commit only if the caller owns the helper transaction on this
    connection. A nested call is a no-op.

    No-token case (brief-ambiguity resolution, §4.1): the brief's
    docstring does not cover a call with no helper transaction active.
    The class-B requirement forces it — the signals functions call
    `_commit_if_owner` without entering a helper — so with no token
    the caller owns the ambient transaction and the call commits.

    Caller contract (pinned finding, T-O1–T-O3): this must only be
    called from inside a helper the CALLER owns (a class-A function
    inside its own `with`, or a standalone writer with no token).
    "Depth == 1" means the OUTERMOST helper is at depth 1 — it does
    NOT mean the caller owns it. A writer that never opens a helper
    (upsert_node_vitality, append_node_judgment) called while an
    outer helper is open would commit that outer transaction; such
    writers use `_commit_if_standalone` instead.
    """
    token = _active_write_token(conn)
    if token is None:
        conn.commit()
        return
    if token["depth"] == 1:
        conn.commit()
    # Nested (depth > 1): no-op — only the owner commits.


def _commit_if_standalone(conn: sqlite3.Connection) -> None:
    """Commit only if NO helper transaction is active on this
    connection. For writers that never open a helper (class-D
    upsert_node_vitality / append_node_judgment, reached via the
    post-commit log path): if a helper token exists, the transaction
    belongs to someone else — an outer helper — and this call must
    not commit it; the owner commits (the write joins that
    transaction). With no token the caller owns the ambient
    transaction and the call commits (the pre-C1a behavior).

    Pinned finding (T-O1–T-O3): `_commit_if_owner` is wrong here —
    its depth==1 branch commits the OUTERMOST helper, which the
    class-D writer does not own. The log path runs after the inner
    `with` exits but inside an outer `with` when a class-A function
    is called nested, so the depth==1 commit fired and the outer
    transaction became visible before the owner committed.
    """
    if _active_write_token(conn) is None:
        conn.commit()
    # A helper token exists: no-op — the helper owner commits.


def _rollback_if_owner(conn: sqlite3.Connection) -> None:
    """Roll back only if the caller owns the helper transaction.
    A nested call RAISES (it does not roll back) — the error propagates
    to the owner, which rolls back the whole transaction.

    No-token case: mirror of _commit_if_owner — with no token the
    caller owns the ambient transaction, so the call rolls it back.
    """
    token = _active_write_token(conn)
    if token is None:
        conn.rollback()
        return
    if token["depth"] == 1:
        conn.rollback()
        return
    raise RuntimeError(
        "nested _rollback_if_owner refused: an inner function cannot roll "
        "back its caller's helper transaction; the error propagates to "
        "the owner, which rolls back the whole transaction"
    )


def _require_helper_transaction(conn: sqlite3.Connection) -> None:
    """Rule 1 (§4.2): a guarded write that finds itself outside a helper
    transaction raises rather than proceeding — the helper is the only
    entry point. The brief names no error type for this; RuntimeError
    with a precise message (pinned finding)."""
    if _active_write_token(conn) is None:
        raise RuntimeError(
            "write-authority guard called outside a helper transaction: "
            "guarded writes must enter through ve_write_transaction"
        )


def _maybe_record_write_refusal(
    conn: sqlite3.Connection, exc: BaseException
) -> None:
    """Record a guard refusal in ledger_history (§2.3 `write_refused` /
    `write_frozen_refusal`) after the owner's rollback, in its own
    short transaction. Called only from the helper owner's exception
    path, so a refusal is recorded exactly once, regardless of caller.

    The record must never mask the original exception: any failure
    here is logged and swallowed. T-D1 pins that a delete_project
    refusal is recorded; T-FZ1/T-G1 pin the refusal errors themselves.
    """
    event: str | None = None
    if isinstance(exc, SubtreeWriteFrozen):
        event = "write_frozen_refusal"
    elif isinstance(exc, (MigratedNodeWriteRefused, ProjectHasTasks)):
        event = "write_refused"
    if event is None:
        return
    try:
        detail: dict[str, Any] = {
            "error": type(exc).__name__,
            "reason": str(exc),
        }
        subtree_id = getattr(exc, "subtree_id", None)
        target_id = getattr(exc, "target_id", None)
        if subtree_id is not None:
            detail["subtree_id"] = subtree_id
        if target_id is not None:
            detail["target_id"] = target_id
        attempt_id = getattr(exc, "attempt_id", None)
        if attempt_id is not None:
            detail["attempt_id"] = attempt_id
        if isinstance(exc, ProjectHasTasks):
            if getattr(exc, "project_id", None) is not None:
                detail["project_id"] = exc.project_id
            if getattr(exc, "task_count", None) is not None:
                detail["task_count"] = exc.task_count
        _append_ledger_history(
            conn,
            subtree_id=str(subtree_id) if subtree_id is not None else None,
            event=event,
            actor="system",
            detail=detail,
        )
        conn.commit()
    except Exception:
        _logger.exception("failed to record write refusal in ledger_history")


# --- C1a §2/§3: ledger + node-store migrations (class C) --------------
# New migration functions in the class-C pattern: CREATE TABLE IF NOT
# EXISTS (+ indexes), then conn.commit(). They run from init_db under
# _init_lock, before any authority exists. The class grows by these
# two functions; T-O4c covers them like the other migrations.

_LEDGER_EVENTS = frozenset(
    {
        "attempt_recorded",
        "flip_committed",
        "flip_failed_before_commit",
        "flip_failed_after_commit",
        "verification_passed",
        "verification_failed",
        "pause_engaged",
        "pause_released",
        "attempt_reconciled",
        "write_refused",
        "write_frozen_refusal",
        "rollback_committed",
        # §9.2 requires a `recovery_blocked` history entry for the
        # inconsistent-ledger case; §2.3's list omits it. The §9.2
        # instruction governs (pinned finding): the set includes it.
        "recovery_blocked",
    }
)

_LEDGER_EXCEPTION_NAMES = frozenset(
    {
        "LEGACY_TASK_DELETE_ORPHANS_CHILDREN",
        "LEGACY_INITIATIVE_DELETE_UNANCHORS_PROJECTS",
    }
)


def _migrate_migration_ledger(conn: sqlite3.Connection) -> None:
    """§2: migration_ledger, flip_attempts, ledger_history,
    ledger_exceptions, migration_pause, pause_releases.

    Fresh databases start PAUSED: the migration_pause row is created
    `paused`, and no startup code ever releases it (§7.3). The
    ledger_history append-only rule (§2.3) is enforced twice: no
    UPDATE/DELETE statement against the table exists in the code
    (static test T-L4), AND two BEFORE triggers make a runtime
    attempt fail (T-L4 requires the runtime attempt to raise; a
    trigger is the mechanism — §2.3 names only the static half).
    """
    conn.execute(
        """CREATE TABLE IF NOT EXISTS migration_ledger (
          subtree_id TEXT PRIMARY KEY,
          authority TEXT NOT NULL,
          version INTEGER NOT NULL,
          fingerprint_sha256 TEXT,
          fingerprint_canonical_json TEXT,
          flipped_at TEXT,
          flip_authorization_ref TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS flip_attempts (
          attempt_id TEXT PRIMARY KEY,
          subtree_id TEXT NOT NULL,
          state TEXT NOT NULL,
          authorization_ref TEXT NOT NULL,
          release_id TEXT,
          operator TEXT,
          started_at TEXT NOT NULL,
          ended_at TEXT,
          failure_detail TEXT,
          verification_entry TEXT,
          resolution TEXT,
          ledger_ref TEXT
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_flip_attempts_subtree "
        "ON flip_attempts(subtree_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_flip_attempts_state "
        "ON flip_attempts(state)"
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS ledger_history (
          history_id TEXT PRIMARY KEY,
          subtree_id TEXT,
          event TEXT NOT NULL,
          actor TEXT NOT NULL,
          at TEXT NOT NULL,
          detail_json TEXT
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ledger_history_subtree "
        "ON ledger_history(subtree_id)"
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS ledger_exceptions (
          exception_id TEXT PRIMARY KEY,
          subtree_id TEXT NOT NULL,
          name TEXT NOT NULL,
          recorded_at TEXT NOT NULL,
          expires_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS migration_pause (
          id TEXT PRIMARY KEY,
          state TEXT NOT NULL,
          engaged_at TEXT,
          engaged_by TEXT,
          engaged_reason TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS pause_releases (
          release_id TEXT PRIMARY KEY,
          subtree_id TEXT NOT NULL,
          authorization_ref TEXT NOT NULL,
          operator TEXT NOT NULL,
          released_at TEXT NOT NULL,
          consumed_by_attempt_id TEXT
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pause_releases_subtree "
        "ON pause_releases(subtree_id)"
    )
    # Append-only enforcement (runtime half of T-L4). Corrections are
    # new history entries, never edits (§2.3).
    conn.execute(
        """CREATE TRIGGER IF NOT EXISTS trg_ledger_history_no_update
           BEFORE UPDATE ON ledger_history
           BEGIN
             SELECT RAISE(ABORT, 'ledger_history is append-only');
           END"""
    )
    conn.execute(
        """CREATE TRIGGER IF NOT EXISTS trg_ledger_history_no_delete
           BEFORE DELETE ON ledger_history
           BEGIN
             SELECT RAISE(ABORT, 'ledger_history is append-only');
           END"""
    )
    now = _now()
    conn.execute(
        "INSERT OR IGNORE INTO migration_pause "
        "(id, state, engaged_at, engaged_by, engaged_reason) "
        "VALUES ('global', 'paused', ?, 'system', 'fresh database: paused by default')",
        (now,),
    )
    conn.commit()


def _migrate_node_store(conn: sqlite3.Connection) -> None:
    """§3: nodes, node_bullets, node_seats. Created empty; the guard
    refuses node writes to unflipped subtrees, and with zero flipped
    subtrees there is no authorized node write (T-L1 pins the
    empty-store invariant). Kind-specific fields are nullable columns;
    a field meaningless for a kind stays NULL, never a backfilled
    default. No delete_node exists (§1.2, §5.5)."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS nodes (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          parent_id TEXT,
          status TEXT NOT NULL,
          original_status TEXT NOT NULL,
          title TEXT NOT NULL,
          description TEXT,
          notes TEXT,
          priority TEXT,
          estimated_hours REAL,
          due_date TEXT,
          timeframe_commitment TEXT,
          dependency_ids TEXT NOT NULL DEFAULT '[]',
          origin_seat TEXT,
          origin_conversation_id TEXT,
          origin_message_id TEXT,
          origin_claim_id TEXT,
          origin_decision_id TEXT,
          seat_ref TEXT,
          responsible_seat TEXT,
          position INTEGER,
          source_table TEXT NOT NULL,
          visibility TEXT NOT NULL DEFAULT 'visible',
          completion_criteria TEXT,
          deliverables TEXT,
          brief TEXT,
          current_focus TEXT,
          next_step_ai TEXT,
          seed_key TEXT,
          tags TEXT,
          evaluation_priority TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_nodes_parent ON nodes(parent_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_nodes_user ON nodes(user_id)"
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS node_bullets (
          id TEXT PRIMARY KEY,
          node_id TEXT NOT NULL,
          content TEXT NOT NULL,
          standing TEXT NOT NULL,
          position INTEGER NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_node_bullets_node "
        "ON node_bullets(node_id)"
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS node_seats (
          id TEXT PRIMARY KEY,
          node_id TEXT NOT NULL,
          role TEXT NOT NULL,
          assigned_person_id TEXT,
          estimated_effort TEXT,
          notes TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_node_seats_node "
        "ON node_seats(node_id)"
    )
    conn.commit()


# --- C1a §2: ledger read/write helpers (conn-passing) --------------------

def _append_ledger_history(
    conn: sqlite3.Connection,
    subtree_id: str | None,
    event: str,
    actor: str,
    detail: dict[str, Any] | None = None,
) -> str:
    """Append one ledger_history row. No commit — the caller commits.
    The event must be in the closed set (§2.3 + `recovery_blocked`
    per §9.2); a new event kind needs a design review, not a code
    change, so an unknown event raises here. Detail never carries
    subtree content — events, not rows."""
    if event not in _LEDGER_EVENTS:
        raise ValueError(f"unknown ledger_history event: {event!r}")
    history_id = M.new_id()
    conn.execute(
        "INSERT INTO ledger_history "
        "(history_id, subtree_id, event, actor, at, detail_json) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            history_id,
            subtree_id,
            event,
            actor,
            _now(),
            json.dumps(detail or {}, ensure_ascii=False, sort_keys=True),
        ),
    )
    return history_id


def _ledger_authority(conn: sqlite3.Connection, subtree_id: str) -> str | None:
    """The authority for a subtree: 'legacy', 'node', or None (no row —
    legacy by default, §2.1)."""
    row = conn.execute(
        "SELECT authority FROM migration_ledger WHERE subtree_id = ?",
        (subtree_id,),
    ).fetchone()
    return str(row[0]) if row is not None else None


def _ledger_row(conn: sqlite3.Connection, subtree_id: str) -> dict[str, Any] | None:
    """The full migration_ledger row for a subtree, or None."""
    row = conn.execute(
        "SELECT subtree_id, authority, version, fingerprint_sha256, "
        "fingerprint_canonical_json, flipped_at, flip_authorization_ref, "
        "created_at, updated_at FROM migration_ledger WHERE subtree_id = ?",
        (subtree_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "subtree_id": row[0],
        "authority": row[1],
        "version": row[2],
        "fingerprint_sha256": row[3],
        "fingerprint_canonical_json": row[4],
        "flipped_at": row[5],
        "flip_authorization_ref": row[6],
        "created_at": row[7],
        "updated_at": row[8],
    }


def _unresolved_failed_after_commit(
    conn: sqlite3.Connection, subtree_id: str
) -> dict[str, Any] | None:
    """The unresolved `failed_after_commit` attempt for a subtree, if
    any — the freeze (§10). Returns the attempt dict or None."""
    row = conn.execute(
        "SELECT attempt_id, subtree_id, state, authorization_ref, "
        "release_id, operator, started_at, ended_at, failure_detail, "
        "verification_entry, resolution, ledger_ref FROM flip_attempts "
        "WHERE subtree_id = ? AND state = 'failed_after_commit'",
        (subtree_id,),
    ).fetchone()
    return _attempt_row_to_dict(row) if row is not None else None


def _read_pause_row(conn: sqlite3.Connection) -> dict[str, Any]:
    """The single migration_pause row (id='global')."""
    row = conn.execute(
        "SELECT id, state, engaged_at, engaged_by, engaged_reason "
        "FROM migration_pause WHERE id = 'global'",
    ).fetchone()
    if row is None:
        return {
            "id": "global",
            "state": "paused",
            "engaged_at": None,
            "engaged_by": None,
            "engaged_reason": None,
        }
    return {
        "id": row[0],
        "state": row[1],
        "engaged_at": row[2],
        "engaged_by": row[3],
        "engaged_reason": row[4],
    }


def _live_release_for_subtree(
    conn: sqlite3.Connection, subtree_id: str
) -> dict[str, Any] | None:
    """The oldest live (unconsumed) pause release for a subtree, if any."""
    row = conn.execute(
        "SELECT release_id, subtree_id, authorization_ref, operator, "
        "released_at, consumed_by_attempt_id FROM pause_releases "
        "WHERE subtree_id = ? AND consumed_by_attempt_id IS NULL "
        "ORDER BY released_at ASC LIMIT 1",
        (subtree_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "release_id": row[0],
        "subtree_id": row[1],
        "authorization_ref": row[2],
        "operator": row[3],
        "released_at": row[4],
        "consumed_by_attempt_id": row[5],
    }


def _attempt_row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "attempt_id": row[0],
        "subtree_id": row[1],
        "state": row[2],
        "authorization_ref": row[3],
        "release_id": row[4],
        "operator": row[5],
        "started_at": row[6],
        "ended_at": row[7],
        "failure_detail": row[8],
        "verification_entry": row[9],
        "resolution": row[10],
        "ledger_ref": row[11],
    }


def _get_attempt_row(
    conn: sqlite3.Connection, attempt_id: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT attempt_id, subtree_id, state, authorization_ref, "
        "release_id, operator, started_at, ended_at, failure_detail, "
        "verification_entry, resolution, ledger_ref FROM flip_attempts "
        "WHERE attempt_id = ?",
        (attempt_id,),
    ).fetchone()
    return _attempt_row_to_dict(row) if row is not None else None


def _list_unresolved_attempt_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT attempt_id, subtree_id, state, authorization_ref, "
        "release_id, operator, started_at, ended_at, failure_detail, "
        "verification_entry, resolution, ledger_ref FROM flip_attempts "
        "WHERE state IN ('recorded', 'failed_before_commit', "
        "'failed_after_commit') ORDER BY started_at ASC",
    ).fetchall()
    return [_attempt_row_to_dict(r) for r in rows]


# --- C1a §5: subtree resolution + the writer guards ---------------------
# The guard resolves a write's subtree, then checks in the fixed
# order (§5.1, §10.3): (1) freeze first — an unresolved
# failed_after_commit attempt refuses with SubtreeWriteFrozen (423);
# (2) authority — a legacy write to a 'node' subtree refuses with
# MigratedNodeWriteRefused (409); no row or 'legacy' proceeds.
# All resolution reads are owner-scoped and run inside the caller's
# helper transaction (the guard raises if called outside one).

_MAX_PARENT_CHAIN = 100


def _resolve_task_subtree(
    conn: sqlite3.Connection, task_id: str | None, user_id: str
) -> str | None:
    """A task's subtree: walk the parent_task_id chain (the immediate
    parent wins, §3.2) to the root task, then its project_id's
    initiative. A dangling parent (missing, or another user's) falls
    back to the task's own project_id; a cycle falls back the same
    way. A root task with no project belongs to no subtree yet (§5.1
    step 1: root creates are legacy writes)."""
    if not task_id:
        return None
    seen: set[str] = set()
    current_id: str | None = task_id
    own_project_id: str | None = None
    depth = 0
    while current_id and depth < _MAX_PARENT_CHAIN:
        if current_id in seen:
            break
        seen.add(current_id)
        row = conn.execute(
            "SELECT parent_task_id, project_id FROM tasks "
            "WHERE id = ? AND user_id = ?",
            (current_id, user_id),
        ).fetchone()
        if row is None:
            break
        if own_project_id is None:
            own_project_id = row[1]
        parent_id = row[0]
        if not parent_id:
            # Root of the chain: its project decides the subtree.
            return _resolve_project_subtree(conn, row[1], user_id)
        current_id = parent_id
        depth += 1
    # Dangling parent, cycle, or depth cap: fall back to the task's own
    # project (the most local available anchor).
    return _resolve_project_subtree(conn, own_project_id, user_id)


def _resolve_project_subtree(
    conn: sqlite3.Connection, project_id: str | None, user_id: str
) -> str | None:
    """A project's subtree is its initiative_id (None → no subtree)."""
    if not project_id:
        return None
    row = conn.execute(
        "SELECT initiative_id FROM projects WHERE id = ? AND user_id = ?",
        (project_id, user_id),
    ).fetchone()
    if row is None or not row[0]:
        return None
    return str(row[0])


def _resolve_task_payload_subtree(
    conn: sqlite3.Connection,
    parent_task_id: str | None,
    project_id: str | None,
    user_id: str,
) -> str | None:
    """Resolve the subtree a task CREATE belongs to, from the create
    payload's parent fields (§5.1 step 1): the immediate parent task
    wins; otherwise the project. No parent and no project → None
    (root create; the T-G3 refusal half is an open question)."""
    if parent_task_id:
        return _resolve_task_subtree(conn, parent_task_id, user_id)
    if project_id:
        return _resolve_project_subtree(conn, project_id, user_id)
    return None


def _resolve_idea_subtrees(
    conn: sqlite3.Connection, idea_id: str | None, user_id: str
) -> list[str]:
    """The subtrees an idea resolves to: the initiatives claiming it
    via source_idea_id (the only idea↔initiative link in the schema;
    Slice A treats it as an origin edge, not parentage — the guard
    treats it as the idea's subtree membership, because an idea's
    checklist children flip with the claiming initiative's subtree).
    A write to the idea refuses if ANY claiming subtree is
    flipped/frozen (fail-closed). No claim → no subtree → legacy
    write proceeds. The flip's census (C1b) is the authority on
    row→subtree assignment at flip time and must confirm this rule
    (open question, pinned in the build report)."""
    if not idea_id:
        return []
    rows = conn.execute(
        "SELECT id FROM initiatives WHERE source_idea_id = ? AND user_id = ?",
        (idea_id, user_id),
    ).fetchall()
    return [str(r[0]) for r in rows]


def _resolve_checklist_subtree(
    conn: sqlite3.Connection, item_id: str | None, user_id: str
) -> list[str]:
    """A checklist item resolves via its idea (§5.1 step 1)."""
    if not item_id:
        return []
    row = conn.execute(
        "SELECT idea_id FROM checklist_items WHERE id = ? AND user_id = ?",
        (item_id, user_id),
    ).fetchone()
    if row is None:
        return []
    return _resolve_idea_subtrees(conn, row[0], user_id)


def _resolve_step_subtree(
    conn: sqlite3.Connection,
    scope_type: str | None,
    scope_id: str | None,
    user_id: str,
) -> str | None:
    """An execution step resolves via its scope (§5.1 step 1)."""
    if not scope_id:
        return None
    if scope_type == EXECUTION_STEPS_SCOPE_INITIATIVE:
        return str(scope_id)
    if scope_type == EXECUTION_STEPS_SCOPE_PROJECT:
        return _resolve_project_subtree(conn, scope_id, user_id)
    return None


def _resolve_proposal_subtree(
    conn: sqlite3.Connection, proposal_id: str | None, user_id: str
) -> str | None:
    """A proposal resolves via its parent task (§5.1 step 1).
    Parentless → no subtree → legacy write proceeds."""
    if not proposal_id:
        return None
    row = conn.execute(
        "SELECT parent_task_id FROM task_proposals "
        "WHERE id = ? AND user_id = ?",
        (proposal_id, user_id),
    ).fetchone()
    if row is None:
        return None
    return _resolve_task_subtree(conn, row[0], user_id)


def _guard_legacy_write(
    conn: sqlite3.Connection,
    subtree_id: str | None,
    *,
    target_id: str | None = None,
    target_kind: str = "node",
) -> None:
    """§5.1: the legacy-write guard. No subtree → proceed (a root
    create/write has no subtree until the flip assigns it one).
    Otherwise, inside the caller's helper transaction: freeze first,
    then authority. Raises the named refusal errors (§5.2)."""
    _require_helper_transaction(conn)
    if subtree_id is None:
        return
    frozen = _unresolved_failed_after_commit(conn, subtree_id)
    if frozen is not None:
        raise SubtreeWriteFrozen(
            f"subtree {subtree_id} is write-frozen: flip attempt "
            f"{frozen['attempt_id']} failed after commit; recovery "
            f"review required; see attempt {frozen['attempt_id']}",
            subtree_id=subtree_id,
            target_id=target_id,
            attempt_id=frozen["attempt_id"],
        )
    authority = _ledger_authority(conn, subtree_id)
    if authority == "node":
        raise MigratedNodeWriteRefused(
            f"subtree {subtree_id} has flipped to node authority; "
            f"legacy writes are refused (target {target_kind} "
            f"{target_id or '?'})",
            subtree_id=subtree_id,
            target_id=target_id,
        )
    # No row or 'legacy': proceed with the mutation.


def _guard_node_write(
    conn: sqlite3.Connection,
    subtree_id: str | None,
    *,
    target_id: str | None = None,
    target_kind: str = "node",
) -> None:
    """§5.5: the node-write branch of the guard. Used by the flip's
    conn-passing test helpers in C1a (no production node-write CRUD
    exists yet — the C2 interface is specified below). A node write to
    a subtree whose authority is 'legacy' (or has no row) is refused;
    a node write to a frozen subtree refuses with SubtreeWriteFrozen;
    a node write to a flipped subtree proceeds (the version bump
    happens in the same transaction as the write). The legacy-refusal
    error type is not named in the brief; ValueError with a precise
    message (pinned finding)."""
    _require_helper_transaction(conn)
    if subtree_id is None:
        raise ValueError(
            "node write refused: target has no subtree (node writes "
            "require a flipped subtree)"
        )
    frozen = _unresolved_failed_after_commit(conn, subtree_id)
    if frozen is not None:
        raise SubtreeWriteFrozen(
            f"subtree {subtree_id} is write-frozen: flip attempt "
            f"{frozen['attempt_id']} failed after commit; recovery "
            f"review required; see attempt {frozen['attempt_id']}",
            subtree_id=subtree_id,
            target_id=target_id,
            attempt_id=frozen["attempt_id"],
        )
    authority = _ledger_authority(conn, subtree_id)
    if authority != "node":
        raise ValueError(
            f"node write refused: subtree {subtree_id} is legacy "
            f"authority; the node store is not authoritative there "
            f"(target {target_kind} {target_id or '?'})"
        )


def _guard_idea_write(
    conn: sqlite3.Connection,
    idea_id: str | None,
    user_id: str,
    *,
    target_id: str | None = None,
    target_kind: str = "idea",
) -> None:
    """The idea guard: an idea resolves to every subtree claiming it
    (§5.1 step 1 via _resolve_idea_subtrees). Refuse if ANY claiming
    subtree is frozen or flipped. Two passes, so the freeze check
    comes first for every claiming subtree before any authority
    check (§10.3's fixed order, applied across subtrees). No claim
    → proceed."""
    _require_helper_transaction(conn)
    subtree_ids = _resolve_idea_subtrees(conn, idea_id, user_id)
    for subtree_id in subtree_ids:
        frozen = _unresolved_failed_after_commit(conn, subtree_id)
        if frozen is not None:
            raise SubtreeWriteFrozen(
                f"subtree {subtree_id} is write-frozen: flip attempt "
                f"{frozen['attempt_id']} failed after commit; recovery "
                f"review required; see attempt {frozen['attempt_id']}",
                subtree_id=subtree_id,
                target_id=target_id,
                attempt_id=frozen["attempt_id"],
            )
    for subtree_id in subtree_ids:
        _guard_legacy_write(
            conn, subtree_id, target_id=target_id, target_kind=target_kind
        )


def _guard_checklist_write(
    conn: sqlite3.Connection,
    item_id: str | None,
    user_id: str,
    *,
    target_id: str | None = None,
    target_kind: str = "checklist_item",
) -> None:
    """Guard for a checklist-item write: read the item's idea inside
    the helper transaction, then apply the idea guard (two-pass:
    freeze first, then authority, across all claiming subtrees)."""
    if not item_id:
        return
    row = conn.execute(
        "SELECT idea_id FROM checklist_items WHERE id = ? AND user_id = ?",
        (item_id, user_id),
    ).fetchone()
    idea_id = row[0] if row is not None else None
    _guard_idea_write(
        conn, idea_id, user_id,
        target_id=target_id if target_id is not None else item_id,
        target_kind=target_kind,
    )


def _guard_step_write(
    conn: sqlite3.Connection,
    step_id: str | None,
    user_id: str,
    *,
    target_id: str | None = None,
    target_kind: str = "execution_step",
) -> None:
    """Guard for an execution-step write: read the step's scope inside
    the helper transaction, then apply the legacy guard on the
    resolved subtree."""
    if not step_id:
        return
    row = conn.execute(
        "SELECT scope_type, scope_id FROM execution_steps "
        "WHERE id = ? AND user_id = ?",
        (step_id, user_id),
    ).fetchone()
    if row is None:
        return
    subtree_id = _resolve_step_subtree(conn, row[0], row[1], user_id)
    _guard_legacy_write(
        conn,
        subtree_id,
        target_id=target_id if target_id is not None else step_id,
        target_kind=target_kind,
    )


# --- C1a §5.5: node-write CRUD — interface specified, NOT implemented ----
# C2 builds these against this interface; C1a specifies it only.
#   create_node(conn, data, user_id) / update_node(conn, node_id, patch,
#   user_id) — conn-passing helpers (following the _insert_task
#   precedent), called only inside a helper transaction, only for a
#   target whose subtree authority is 'node' (guarded by
#   _guard_node_write above). They increment the subtree version in
#   the same transaction as the write (record §7.2(1)).
#   delete_node does NOT exist: migrated-node deletion remains refused
#   fail-closed until the descendant-disposition workflow is
#   separately authorized (§1.2). When that workflow is authorized,
#   its design specifies the delete path; until then there is no
#   node-delete function to call.
# The route wiring (which API endpoints call the node-write functions
# after a flip) is C2/Slice B scope, not C1a. C1a's tests exercise
# node writes only through the flip's conn-passing helpers in
# fixture databases.


# --- C1a §7: the durable migration pause + operator controls -----------
# Surface chosen (R-D2): storage functions + the established
# flyctl machine-exec operator channel. NO API endpoint, NO manual-SQL
# path, NO env flag, NO in-app UI (§7.2). The global state stays
# 'paused'; a release is the scoped, single-use exception to it.
# These functions take no conn (brief §7.1 signatures): they open
# their own connection via get_connection(), which the test fixtures
# point at an isolated database by monkeypatching _DB_PATH.


def _pause_status_dict(conn: sqlite3.Connection) -> dict[str, Any]:
    """The operator's status read: global state, live releases, and
    unresolved attempts (§7.1). Read-only."""
    pause = _read_pause_row(conn)
    live = conn.execute(
        "SELECT release_id, subtree_id, authorization_ref, operator, "
        "released_at, consumed_by_attempt_id FROM pause_releases "
        "WHERE consumed_by_attempt_id IS NULL ORDER BY released_at ASC",
    ).fetchall()
    return {
        "state": pause["state"],
        "engaged_at": pause["engaged_at"],
        "engaged_by": pause["engaged_by"],
        "engaged_reason": pause["engaged_reason"],
        "live_releases": [
            {
                "release_id": r[0],
                "subtree_id": r[1],
                "authorization_ref": r[2],
                "operator": r[3],
                "released_at": r[4],
                "consumed_by_attempt_id": r[5],
            }
            for r in live
        ],
        "unresolved_attempts": _list_unresolved_attempt_rows(conn),
    }


def migration_pause_status() -> dict[str, Any]:
    """Read-only: global state, the list of live releases, the list of
    unresolved attempts. The operator's status read (and the read
    C1b's diagnostics formalize under R-D3)."""
    return _pause_status_dict(get_connection())


def engage_migration_pause(operator: str, reason: str) -> dict[str, Any]:
    """Set migration_pause.state = 'paused' (own short transaction),
    writing a `pause_engaged` history entry (operator, time, reason).
    Idempotent: engaging an already-engaged pause records the
    (redundant) engagement in history but changes nothing."""
    conn = get_connection()
    with ve_write_transaction(conn, purpose="engage_migration_pause"):
        now = _now()
        conn.execute(
            "UPDATE migration_pause SET state = 'paused', engaged_at = ?, "
            "engaged_by = ?, engaged_reason = ? WHERE id = 'global'",
            (now, operator, reason),
        )
        _append_ledger_history(
            conn,
            subtree_id=None,
            event="pause_engaged",
            actor=operator,
            detail={"reason": reason},
        )
        _commit_if_owner(conn)
    return _pause_status_dict(conn)


def release_migration_pause_for_subtree(
    subtree_id: str, authorization_ref: str, operator: str
) -> dict[str, Any]:
    """Append a pause_releases row (single-use, §2.5) and write a
    `pause_released` history entry. Does NOT flip the global pause
    state — the global state stays 'paused'; the release is the
    scoped exception to it. The flip path checks: global pause
    engaged AND a live (unconsumed) release exists for this subtree,
    else refuse with MigrationPaused."""
    conn = get_connection()
    release_id = M.new_id()
    with ve_write_transaction(conn, purpose="release_migration_pause_for_subtree"):
        now = _now()
        conn.execute(
            "INSERT INTO pause_releases (release_id, subtree_id, "
            "authorization_ref, operator, released_at, "
            "consumed_by_attempt_id) VALUES (?, ?, ?, ?, ?, NULL)",
            (release_id, subtree_id, authorization_ref, operator, now),
        )
        _append_ledger_history(
            conn,
            subtree_id=subtree_id,
            event="pause_released",
            actor=operator,
            detail={
                "release_id": release_id,
                "authorization_ref": authorization_ref,
            },
        )
        _commit_if_owner(conn)
    return {
        "release_id": release_id,
        "subtree_id": subtree_id,
        "authorization_ref": authorization_ref,
        "operator": operator,
        "released_at": now,
        "consumed_by_attempt_id": None,
    }


def _engage_pause_in_transaction(
    conn: sqlite3.Connection, operator: str, reason: str
) -> None:
    """Engage the pause inside an already-open helper transaction
    (used by the attempt-marking functions, §8.1: the flip path
    records the failure in a post-rollback transaction and engages
    the pause). Idempotent; records the engagement in history."""
    now = _now()
    conn.execute(
        "UPDATE migration_pause SET state = 'paused', engaged_at = ?, "
        "engaged_by = ?, engaged_reason = ? WHERE id = 'global'",
        (now, operator, reason),
    )
    _append_ledger_history(
        conn,
        subtree_id=None,
        event="pause_engaged",
        actor=operator,
        detail={"reason": reason},
    )


# --- C1a §§8-9: flip-attempt tracking + the recovery procedure --------
# The attempt row is committed in its own transaction BEFORE the
# migration transaction begins (§2.2). The flip PATH itself (the C2
# migration transaction that moves rows) is NOT built in C1a — only
# the attempt record, the states, the enforcement, and the recovery
# procedure's storage functions. No flip may run in C1a.
# A `recorded` attempt blocks ALL flips globally (§8.2); a
# `failed_before_commit` / `failed_after_commit` attempt blocks flips
# for its own subtree only. Only `failed_after_commit` freezes writes
# (§10).


def record_flip_attempt(
    subtree_id: str, authorization_ref: str, operator: str
) -> dict[str, Any]:
    """Record a flip attempt (own transaction, committed) BEFORE the
    migration transaction begins. Check-then-record atomically in one
    transaction: (1) a live (unconsumed) release must exist for this
    subtree — else MigrationPaused; (2) no unresolved attempt may
    exist — a `recorded` attempt anywhere blocks ALL flips, a
    `failed_*` attempt for this subtree blocks this subtree — else
    UnresolvedFlipAttempt. The release is consumed by the recording
    (consumed_by_attempt_id set); a refused flip consumes no release
    and records no attempt (§11.3 step order is loose; §8 + §14
    window (a) govern — pinned finding)."""
    conn = get_connection()
    attempt_id = M.new_id()
    with ve_write_transaction(conn, purpose="record_flip_attempt"):
        release = _live_release_for_subtree(conn, subtree_id)
        if release is None:
            raise MigrationPaused(
                f"flip of subtree {subtree_id} refused: the migration "
                f"pause is engaged and no live release exists for this "
                f"subtree",
                subtree_id=subtree_id,
            )
        unresolved = _list_unresolved_attempt_rows(conn)
        for other in unresolved:
            if other["state"] == "recorded":
                raise UnresolvedFlipAttempt(
                    f"flip of subtree {subtree_id} refused: attempt "
                    f"{other['attempt_id']} (subtree "
                    f"{other['subtree_id']}) is recorded and unresolved; "
                    f"a recorded attempt blocks all flips globally",
                    subtree_id=subtree_id,
                    attempt_id=other["attempt_id"],
                    attempt_state="recorded",
                )
            if other["subtree_id"] == subtree_id:
                raise UnresolvedFlipAttempt(
                    f"flip of subtree {subtree_id} refused: attempt "
                    f"{other['attempt_id']} is {other['state']} and "
                    f"unresolved for this subtree",
                    subtree_id=subtree_id,
                    attempt_id=other["attempt_id"],
                    attempt_state=other["state"],
                )
        now = _now()
        conn.execute(
            "INSERT INTO flip_attempts (attempt_id, subtree_id, state, "
            "authorization_ref, release_id, operator, started_at, "
            "ended_at, failure_detail, verification_entry, resolution, "
            "ledger_ref) VALUES (?, ?, 'recorded', ?, ?, ?, ?, NULL, "
            "NULL, NULL, NULL, NULL)",
            (
                attempt_id,
                subtree_id,
                authorization_ref,
                release["release_id"],
                operator,
                now,
            ),
        )
        conn.execute(
            "UPDATE pause_releases SET consumed_by_attempt_id = ? "
            "WHERE release_id = ?",
            (attempt_id, release["release_id"]),
        )
        _append_ledger_history(
            conn,
            subtree_id=subtree_id,
            event="attempt_recorded",
            actor=operator,
            detail={
                "attempt_id": attempt_id,
                "authorization_ref": authorization_ref,
                "release_id": release["release_id"],
            },
        )
        _commit_if_owner(conn)
    row = _get_attempt_row(conn, attempt_id)
    return row if row is not None else {}


def _mark_attempt_failed(
    conn: sqlite3.Connection,
    attempt_id: str,
    state: str,
    failure_detail: str,
    operator: str,
) -> dict[str, Any]:
    """Shared marking path for failed_before_commit /
    failed_after_commit (§8.1): the attempt must be `recorded`; the
    marking + pause engagement happen in one post-rollback
    transaction; the failure is recorded in history. The freeze (§10)
    engages automatically via the guard reading the attempt state —
    no separate flag."""
    row = _get_attempt_row(conn, attempt_id)
    if row is None:
        raise ValueError(f"flip attempt not found: {attempt_id}")
    if row["state"] != "recorded":
        raise ValueError(
            f"flip attempt {attempt_id} is {row['state']}, not recorded; "
            f"only a recorded attempt can be marked failed"
        )
    now = _now()
    event = (
        "flip_failed_before_commit"
        if state == "failed_before_commit"
        else "flip_failed_after_commit"
    )
    conn.execute(
        "UPDATE flip_attempts SET state = ?, ended_at = ?, "
        "failure_detail = ? WHERE attempt_id = ?",
        (state, now, failure_detail, attempt_id),
    )
    _engage_pause_in_transaction(
        conn, operator, f"flip attempt {attempt_id} marked {state}"
    )
    _append_ledger_history(
        conn,
        subtree_id=row["subtree_id"],
        event=event,
        actor=operator,
        detail={"attempt_id": attempt_id, "failure_detail": failure_detail},
    )
    updated = _get_attempt_row(conn, attempt_id)
    return updated if updated is not None else {}


def mark_attempt_failed_before_commit(
    attempt_id: str, failure_detail: str, operator: str = "system"
) -> dict[str, Any]:
    """§8.1: the migration transaction rolled back while the process
    was alive; the flip path records the failure in a post-rollback
    transaction and engages the pause. The subtree is unchanged
    (legacy authority). Blocks flips for that subtree only."""
    conn = get_connection()
    with ve_write_transaction(conn, purpose="mark_attempt_failed_before_commit"):
        out = _mark_attempt_failed(
            conn, attempt_id, "failed_before_commit", failure_detail, operator
        )
        _commit_if_owner(conn)
    return out


def mark_attempt_failed_after_commit(
    attempt_id: str, failure_detail: str, operator: str = "system"
) -> dict[str, Any]:
    """§8.1: the migration transaction committed, but a post-commit
    verification failed. Node authority is preserved; the pause is
    engaged; the subtree is write-frozen (§10). The flip is NOT
    reversed automatically."""
    conn = get_connection()
    with ve_write_transaction(conn, purpose="mark_attempt_failed_after_commit"):
        out = _mark_attempt_failed(
            conn, attempt_id, "failed_after_commit", failure_detail, operator
        )
        _commit_if_owner(conn)
    return out


def determine_recorded_attempt(
    attempt_id: str, operator: str = "system"
) -> dict[str, Any]:
    """§9 Steps 1–4: the operator recovery procedure's determination,
    for a `recorded` attempt whose flip invocation is no longer
    running. Reads the attempt row, the ledger authority row, and the
    ledger history — the ONLY determinant — and marks the attempt:
    authority 'node' + a `flip_committed` event for this attempt →
    failed_after_commit (the flip committed; the subtree is now
    write-frozen); authority 'legacy' + no event → failed_before_commit
    (the flip did not commit; the subtree is unchanged). Disagreement
    (node without event, or legacy with event) → INCONSISTENT: stop,
    mark nothing, engage nothing; record a `recovery_blocked` history
    entry and return the inconsistency. Never auto-retries, never
    reverses authority, never assumes failure (§9.4)."""
    conn = get_connection()
    attempt = _get_attempt_row(conn, attempt_id)
    if attempt is None:
        raise ValueError(f"flip attempt not found: {attempt_id}")
    if attempt["state"] != "recorded":
        raise ValueError(
            f"flip attempt {attempt_id} is {attempt['state']}, not "
            f"recorded; the recovery procedure does not apply"
        )
    subtree_id = attempt["subtree_id"]
    ledger = _ledger_row(conn, subtree_id)
    authority = ledger["authority"] if ledger is not None else "legacy"
    history = conn.execute(
        "SELECT event, detail_json FROM ledger_history "
        "WHERE subtree_id = ? ORDER BY at ASC",
        (subtree_id,),
    ).fetchall()
    flip_event = False
    for event, detail_json in history:
        if event != "flip_committed":
            continue
        try:
            detail = json.loads(detail_json or "{}")
        except (TypeError, ValueError):
            detail = {}
        if detail.get("attempt_id") == attempt_id:
            flip_event = True
            break
    if authority == "node" and flip_event:
        out = mark_attempt_failed_after_commit(
            attempt_id,
            "flip committed; outcome determined by recovery review of "
            "a recorded attempt; post-commit verification status: "
            f"{attempt.get('verification_entry') or 'never ran'}",
            operator,
        )
        return {
            "attempt_id": attempt_id,
            "subtree_id": subtree_id,
            "determination": "failed_after_commit",
            "attempt": out,
        }
    if authority == "legacy" and not flip_event:
        out = mark_attempt_failed_before_commit(
            attempt_id,
            "flip did not commit; determined by recovery review of "
            "a recorded attempt",
            operator,
        )
        return {
            "attempt_id": attempt_id,
            "subtree_id": subtree_id,
            "determination": "failed_before_commit",
            "attempt": out,
        }
    # INCONSISTENT — stop. Record the inconsistency; change nothing.
    with ve_write_transaction(conn, purpose="determine_recorded_attempt_blocked"):
        _append_ledger_history(
            conn,
            subtree_id=subtree_id,
            event="recovery_blocked",
            actor=operator,
            detail={
                "attempt_id": attempt_id,
                "authority": authority,
                "flip_committed_event": flip_event,
            },
        )
        _commit_if_owner(conn)
    return {
        "attempt_id": attempt_id,
        "subtree_id": subtree_id,
        "determination": "inconsistent",
        "authority": authority,
        "flip_committed_event": flip_event,
        "attempt": attempt,
    }


def close_attempt_reconciled(
    attempt_id: str, resolution: str, operator: str = "system"
) -> dict[str, Any]:
    """§9 Step 6: close the attempt to `reconciled` with the recorded
    resolution. Allowed from `flipped`, `failed_before_commit`, and
    `failed_after_commit` (NOT from `recorded` — the outcome must be
    determined first — and not twice). The attempt row is never
    deleted. Closing lifts the freeze (the guard keys the freeze to
    an UNRESOLVED failed_after_commit attempt) but NEVER releases
    the pause (§10.4)."""
    conn = get_connection()
    with ve_write_transaction(conn, purpose="close_attempt_reconciled"):
        row = _get_attempt_row(conn, attempt_id)
        if row is None:
            raise ValueError(f"flip attempt not found: {attempt_id}")
        if row["state"] == "recorded":
            raise ValueError(
                f"flip attempt {attempt_id} is still recorded; determine "
                f"its outcome before closing it"
            )
        if row["state"] == "reconciled":
            raise ValueError(
                f"flip attempt {attempt_id} is already reconciled"
            )
        now = _now()
        conn.execute(
            "UPDATE flip_attempts SET state = 'reconciled', ended_at = ?, "
            "resolution = ? WHERE attempt_id = ?",
            (now, resolution, attempt_id),
        )
        _append_ledger_history(
            conn,
            subtree_id=row["subtree_id"],
            event="attempt_reconciled",
            actor=operator,
            detail={"attempt_id": attempt_id, "resolution": resolution},
        )
        _commit_if_owner(conn)
    updated = _get_attempt_row(conn, attempt_id)
    return updated if updated is not None else {}


def record_verification_result(
    attempt_id: str, passed: bool, summary: str, operator: str = "system"
) -> dict[str, Any]:
    """§11.3 step 13 / §14 windows (d)–(e): record a post-commit
    verification result on the attempt (`verification_entry`) plus a
    `verification_passed` / `verification_failed` history event. A
    failure on a `flipped` attempt transitions it to
    `failed_after_commit` (pause engaged, subtree frozen — the flip
    is NOT reversed). A pass on a `flipped` attempt records the
    entry and leaves the attempt flipped. On a `failed_after_commit`
    attempt a re-run pass records the entry; the freeze lifts only
    when the attempt is closed to `reconciled` (§10.5)."""
    conn = get_connection()
    with ve_write_transaction(conn, purpose="record_verification_result"):
        row = _get_attempt_row(conn, attempt_id)
        if row is None:
            raise ValueError(f"flip attempt not found: {attempt_id}")
        if row["state"] not in ("flipped", "failed_after_commit"):
            raise ValueError(
                f"cannot record a verification result for attempt "
                f"{attempt_id} in state {row['state']}"
            )
        entry = ("passed: " if passed else "failed: ") + summary
        now = _now()
        if row["state"] == "flipped" and not passed:
            conn.execute(
                "UPDATE flip_attempts SET state = 'failed_after_commit', "
                "ended_at = ?, failure_detail = ?, verification_entry = ? "
                "WHERE attempt_id = ?",
                (now, entry, entry, attempt_id),
            )
            _engage_pause_in_transaction(
                conn, operator,
                f"post-commit verification failed for attempt {attempt_id}",
            )
            _append_ledger_history(
                conn,
                subtree_id=row["subtree_id"],
                event="flip_failed_after_commit",
                actor=operator,
                detail={"attempt_id": attempt_id, "failure_detail": entry},
            )
        else:
            conn.execute(
                "UPDATE flip_attempts SET verification_entry = ? "
                "WHERE attempt_id = ?",
                (entry, attempt_id),
            )
        _append_ledger_history(
            conn,
            subtree_id=row["subtree_id"],
            event="verification_passed" if passed else "verification_failed",
            actor=operator,
            detail={"attempt_id": attempt_id, "summary": summary},
        )
        _commit_if_owner(conn)
    updated = _get_attempt_row(conn, attempt_id)
    return updated if updated is not None else {}


def get_flip_attempt(attempt_id: str) -> dict[str, Any] | None:
    """Read one flip attempt row, or None."""
    return _get_attempt_row(get_connection(), attempt_id)


def list_unresolved_attempts() -> list[dict[str, Any]]:
    """Attempts in `recorded` / `failed_before_commit` /
    `failed_after_commit` — the flip path's block set (§8.2)."""
    return _list_unresolved_attempt_rows(get_connection())


# --- C1a §11: the fingerprint, computed inside the transaction ---------
# Compute-inside adopted (§11.2): the canonical document is assembled
# from rows read AFTER BEGIN IMMEDIATE, so no concurrent writer can
# interleave a change between the hash and the flip. The validation
# alternative stays a paragraph in the brief, not code.
#
# The canonical document (§11.4) is one JSON object per subtree:
# records sorted deterministically; within a record, keys sorted;
# dependency_ids sorted; compact separators; strings as UTF-8. The
# fingerprint is SHA-256 of the canonical bytes, stored as hex.
# Included: every authoritative stored content field per node (§3.1)
# + bullets + seats + the ledger authority row (subtree id, version,
# flip time). Excluded: ONLY created_at / updated_at (R-D9).
#
# Two sources, one form: at flip time the document is built from the
# LEGACY rows projected into node form (canonicalize_legacy_subtree);
# at rollback time it is rebuilt from the NODE rows
# (canonicalize_subtree). Both produce identical node-form dicts, so
# the hashes agree exactly when the content agrees. The node-form
# field set is the §11.4 list; the mapper is shared by both paths.
#
# Fields the §3.1 node columns do NOT carry (pinned finding, not a
# C1a deviation): an idea's summary / desired_outcome / linked_people
# / linked_assets / linked_ideas / created_by; a checklist item's
# person_id / asset_id; an execution step's source /
# source_evaluation_id; a project's estimated_weekly_hours (not the
# node's estimated_hours). Those legacy fields are not in the node
# store and therefore not in the fingerprint; the legacy rows retain
# them (the rollback path). The C1b reverse projection cannot
# round-trip them — a design question for C1b/C2.

_NODE_FORM_FIELDS = (
    "id", "kind", "parent_id", "status", "original_status", "title",
    "description", "notes", "priority", "estimated_hours", "due_date",
    "timeframe_commitment", "dependency_ids", "origin_seat",
    "origin_conversation_id", "origin_message_id", "origin_claim_id",
    "origin_decision_id", "seat_ref", "responsible_seat", "position",
    "source_table", "visibility", "completion_criteria", "deliverables",
    "brief", "current_focus", "next_step_ai", "seed_key", "tags",
    "evaluation_priority",
)


def _json_list_or_none(raw: Any) -> list[str] | None:
    """Parse a stored JSON array column (dependency_ids, tags) to a
    sorted list, or None when the column is NULL/empty. A malformed
    stored value raises — the fingerprint must not silently normalize
    corrupt content (the census refuses such rows before a flip)."""
    if raw is None:
        return None
    if isinstance(raw, list):
        return sorted(str(v) for v in raw)
    text = str(raw).strip()
    if not text:
        return None
    parsed = json.loads(text)
    if not isinstance(parsed, list):
        raise ValueError(f"expected a JSON array, got: {text[:80]!r}")
    return sorted(str(v) for v in parsed)


def _node_form_base() -> dict[str, Any]:
    """A node-form dict with every §11.4 field present (None/[] until
    the mapper fills it). Both sources build the same keys, so a
    missing key can never make two equal contents hash differently."""
    form: dict[str, Any] = {key: None for key in _NODE_FORM_FIELDS}
    form["dependency_ids"] = []
    return form


def _node_form_from_legacy(kind: str, row: dict[str, Any]) -> dict[str, Any]:
    """Project one legacy row (as a plain dict of its stored columns)
    into node form (§3.1 columns, §11.4 field list). Status and
    visibility follow Slice A's mapping (node_projection.map_status);
    parentage follows the corrected §3.2 rule (immediate task parent
    wins; an initiative's source idea is an origin edge, not a
    parent). `row` must already carry the parentage inputs the kind
    needs (parent_task_id / project_id / idea_id / scope_* /
    depends_on); the caller supplies them from the stored row."""
    # Lazy import: node_projection imports this module at ITS top
    # level, so a module-level import here would be circular.
    from local_ai.vision_execution import node_projection as _NP

    form = _node_form_base()
    form["id"] = row["id"]
    form["kind"] = kind
    form["source_table"] = {
        "idea": "ideas",
        "initiative": "initiatives",
        "project": "projects",
        "task": "tasks",
        "checklist_item": "checklist_items",
        "execution_step": "execution_steps",
    }[kind]
    form["title"] = row.get("title") or ""
    if kind == "idea":
        status, visibility = _NP.map_status("ideas", row["status"])
        form.update(
            parent_id=None,
            status=status,
            original_status=row["status"],
            visibility=visibility,
            description=row.get("description"),
            notes=row.get("notes"),
            tags=_json_list_or_none(row.get("tags")),
        )
    elif kind == "initiative":
        status, visibility = _NP.map_status("initiatives", row["status"])
        form.update(
            parent_id=None,
            status=status,
            original_status=row["status"],
            visibility=visibility,
            brief=row.get("brief"),
            notes=row.get("notes"),
            next_step_ai=row.get("next_step_ai"),
            seed_key=row.get("seed_key"),
            evaluation_priority=row.get("evaluation_priority"),
        )
    elif kind == "project":
        status, visibility = _NP.map_status("projects", row["status"])
        form.update(
            parent_id=row.get("initiative_id") or None,
            status=status,
            original_status=row["status"],
            visibility=visibility,
            brief=row.get("brief"),
            notes=row.get("notes"),
            priority=row.get("priority"),
            current_focus=row.get("current_focus"),
            next_step_ai=row.get("next_step_ai"),
        )
    elif kind == "task":
        status, visibility = _NP.map_status("tasks", row["status"])
        parent_id = row.get("parent_task_id") or row.get("project_id") or None
        form.update(
            parent_id=parent_id,
            status=status,
            original_status=row["status"],
            visibility=visibility,
            description=row.get("description"),
            notes=row.get("notes"),
            priority=row.get("priority"),
            estimated_hours=row.get("estimated_hours"),
            due_date=row.get("due_date"),
            timeframe_commitment=row.get("timeframe_commitment"),
            dependency_ids=_json_list_or_none(row.get("dependency_ids")) or [],
            origin_seat=row.get("origin_seat"),
            origin_conversation_id=row.get("origin_conversation_id"),
            origin_message_id=row.get("origin_message_id"),
            origin_claim_id=row.get("origin_claim_id"),
            origin_decision_id=row.get("origin_decision_id"),
            seat_ref=row.get("seat_ref"),
            responsible_seat=row.get("responsible_seat"),
            completion_criteria=row.get("completion_criteria"),
        )
    elif kind == "checklist_item":
        original = str(row.get("status") or "")
        mapped = {"open": "Open", "done": "Done"}.get(original.strip().lower())
        if mapped is None:
            raise ValueError(
                f"unmapped checklist item status {original!r}"
            )
        form.update(
            parent_id=row.get("parent_id") or row.get("idea_id") or None,
            status=mapped,
            original_status=original,
            visibility="archived" if row.get("superseded") else "visible",
            dependency_ids=sorted(str(v) for v in (row.get("depends_on") or [])),
            position=row.get("position"),
        )
    elif kind == "execution_step":
        is_done = bool(row.get("is_done"))
        form.update(
            parent_id=row.get("scope_id") or None,
            status="Done" if is_done else "Open",
            original_status="done" if is_done else "open",
            visibility="visible",
            position=row.get("sort_order"),
        )
    return form


def _node_form_from_node_row(row: Any) -> dict[str, Any]:
    """A node-table row (sqlite3.Row) into the same node-form dict.
    The stored dependency_ids / tags JSON is parsed back to sorted
    lists, so the form matches the legacy projection exactly."""
    form = _node_form_base()
    for key in _NODE_FORM_FIELDS:
        value = row[key]
        if key == "dependency_ids":
            form[key] = _json_list_or_none(value) or []
        elif key == "tags":
            form[key] = _json_list_or_none(value)
        else:
            form[key] = value
    return form


def _canonical_json(doc: dict[str, Any]) -> str:
    """The canonical serialization (§11.4): keys sorted, compact
    separators, strings as UTF-8, no trailing newline."""
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical_doc(
    node_forms: list[dict[str, Any]],
    bullets: list[dict[str, Any]],
    seats: list[dict[str, Any]],
    *,
    subtree_id: str,
    version: int,
    flipped_at: str | None,
) -> dict[str, Any]:
    """Assemble the canonical document (§11.4) from node forms +
    bullets + seats + the authority row. Nodes sort by
    (parent_id, position, id); bullets by (node_id, position, id);
    seats by id — deterministic, so the sort cannot mask a content
    change."""
    nodes = sorted(
        node_forms,
        key=lambda n: (n.get("parent_id") or "", n.get("position") or 0, n["id"]),
    )
    ordered_bullets = sorted(
        bullets,
        key=lambda b: (b["node_id"], b["position"], b["id"]),
    )
    ordered_seats = sorted(seats, key=lambda s: s["id"])
    return {
        "authority": {
            "subtree_id": subtree_id,
            "version": version,
            "flipped_at": flipped_at,
        },
        "nodes": nodes,
        "node_bullets": ordered_bullets,
        "node_seats": ordered_seats,
    }


def _subtree_node_ids_from_rows(
    conn: sqlite3.Connection, subtree_id: str, user_id: str
) -> list[str]:
    """The node ids in a subtree, by walking parent_id links down
    from the root node (id = subtree_id) over the nodes table. Nodes
    whose parent chain is broken or belongs to another subtree are
    not included.

    The walk is seeded with TWO roots: the initiative node AND the
    initiative's claimed idea node. The idea is a separate root in
    the node store (its parent_id is None — the source idea is an
    origin edge, not parentage, per Slice A §3.2), and its checklist
    items hang off it; yet the idea + its checklist are IN the
    subtree (the flip-time side, _legacy_subtree_rows, includes
    them). Seeding only the initiative would silently drop the idea
    and its checklist from the rollback-time recompute, so the
    fingerprint could never round-trip for a subtree with a claimed
    idea (caught by T-F3/T-F4). The link is the legacy
    initiatives.source_idea_id — the node store carries no
    source-idea link, and the legacy row is stable post-flip (the
    guard refuses updates to a flipped initiative's source idea
    and deletes of its claimed idea)."""
    rows = conn.execute(
        "SELECT id, parent_id FROM nodes WHERE user_id = ?", (user_id,)
    ).fetchall()
    children: dict[str | None, list[str]] = {}
    all_ids: set[str] = set()
    for node_id, parent_id in rows:
        all_ids.add(str(node_id))
        children.setdefault(parent_id, []).append(str(node_id))
    if subtree_id not in all_ids:
        return []
    seeds = [subtree_id]
    idea_row = conn.execute(
        "SELECT source_idea_id FROM initiatives WHERE id = ?",
        (subtree_id,),
    ).fetchone()
    idea_id = (
        str(idea_row[0])
        if idea_row is not None and idea_row[0]
        else None
    )
    if idea_id is not None and idea_id in all_ids and idea_id != subtree_id:
        seeds.append(idea_id)
    found: list[str] = []
    stack = list(seeds)
    seen: set[str] = set()
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        found.append(current)
        stack.extend(children.get(current, []))
    return found


def canonicalize_subtree(conn: sqlite3.Connection, subtree_id: str) -> dict[str, Any]:
    """The canonical document (§11.4) rebuilt from the NODE rows —
    the rollback-time recompute (§11.5). Reads the authority row for
    the version + flip time, walks the subtree's node rows, and
    assembles the document. Raises ValueError when the subtree has
    no authority row (nothing to recompute against). Callers must
    hold the rollback transaction (BEGIN IMMEDIATE) before calling,
    so the recompute cannot miss a concurrent node write."""
    ledger = _ledger_row(conn, subtree_id)
    if ledger is None:
        raise ValueError(
            f"cannot canonicalize subtree {subtree_id}: no authority row"
        )
    initiative = conn.execute(
        "SELECT user_id FROM initiatives WHERE id = ?", (subtree_id,)
    ).fetchone()
    if initiative is None:
        raise ValueError(
            f"cannot canonicalize subtree {subtree_id}: no initiative row"
        )
    user_id = str(initiative[0])
    node_ids = _subtree_node_ids_from_rows(conn, subtree_id, user_id)
    forms: list[dict[str, Any]] = []
    if node_ids:
        placeholders = ",".join("?" for _ in node_ids)
        rows = conn.execute(
            f"SELECT * FROM nodes WHERE id IN ({placeholders})",
            tuple(node_ids),
        ).fetchall()
        forms = [_node_form_from_node_row(r) for r in rows]
        bullet_rows = conn.execute(
            f"SELECT id, node_id, content, standing, position "
            f"FROM node_bullets WHERE node_id IN ({placeholders})",
            tuple(node_ids),
        ).fetchall()
        seat_rows = conn.execute(
            f"SELECT id, node_id, role, assigned_person_id, "
            f"estimated_effort, notes FROM node_seats "
            f"WHERE node_id IN ({placeholders})",
            tuple(node_ids),
        ).fetchall()
    else:
        bullet_rows = []
        seat_rows = []
    bullets = [
        {
            "id": r[0],
            "node_id": r[1],
            "content": r[2],
            "standing": r[3],
            "position": r[4],
        }
        for r in bullet_rows
    ]
    seats = [
        {
            "id": r[0],
            "node_id": r[1],
            "role": r[2],
            "assigned_person_id": r[3],
            "estimated_effort": r[4],
            "notes": r[5],
        }
        for r in seat_rows
    ]
    return _canonical_doc(
        forms,
        bullets,
        seats,
        subtree_id=subtree_id,
        version=int(ledger["version"]),
        flipped_at=ledger["flipped_at"],
    )


def compute_subtree_fingerprint(
    conn: sqlite3.Connection, subtree_id: str
) -> dict[str, str]:
    """The rollback-time fingerprint: canonicalize from the node rows
    (§11.5) and SHA-256 the canonical bytes. Returns
    {"canonical_json", "sha256"}."""
    doc = canonicalize_subtree(conn, subtree_id)
    text = _canonical_json(doc)
    return {"canonical_json": text, "sha256": _sha256_hex(text)}


def _task_dict_in_subtree(
    task: dict[str, Any],
    tasks_by_id: dict[str, dict[str, Any]],
    project_ids: set[str],
) -> bool:
    """In-memory version of _resolve_task_subtree for the fingerprint:
    walk the parent chain (immediate parent wins); the root task's
    project decides membership. A dangling parent or a cycle falls
    back to the task's own project; depth exhaustion does the same."""
    seen: set[str] = set()
    current: dict[str, Any] | None = task
    own_project = task.get("project_id")
    depth = 0
    while current is not None and depth < _MAX_PARENT_CHAIN:
        current_id = str(current["id"])
        if current_id in seen:
            return str(own_project or "") in project_ids
        seen.add(current_id)
        parent_id = current.get("parent_task_id")
        if not parent_id:
            return str(current.get("project_id") or "") in project_ids
        parent = tasks_by_id.get(str(parent_id))
        if parent is None:
            return str(own_project or "") in project_ids
        current = parent
        depth += 1
    return str(own_project or "") in project_ids


def _legacy_subtree_rows(
    conn: sqlite3.Connection, subtree_id: str
) -> dict[str, Any]:
    """The legacy rows in a subtree, read on the passed connection
    (callers hold the flip transaction). The subtree is the
    initiative + its projects + tasks whose parent chain leads to it
    + the claimed idea + that idea's checklist items + execution
    steps scoped to it or its projects + its initiative seats. The
    §11.3 step-6 parenthetical omits projects and the claimed idea,
    but both are in the subtree by the §5.1 parentage rules (pinned
    note). An idea claimed by several initiatives contributes its
    checklist items to each claiming subtree's fingerprint; the C1b
    census is the authority on row→subtree assignment and must
    confirm the rule."""
    initiative = conn.execute(
        "SELECT * FROM initiatives WHERE id = ?", (subtree_id,)
    ).fetchone()
    if initiative is None:
        raise ValueError(f"cannot fingerprint subtree {subtree_id}: no initiative row")
    init = dict(initiative)
    user_id = str(init["user_id"])
    projects = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM projects WHERE initiative_id = ? AND user_id = ?",
            (subtree_id, user_id),
        ).fetchall()
    ]
    project_ids = {str(p["id"]) for p in projects}
    all_tasks = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM tasks WHERE user_id = ?", (user_id,)
        ).fetchall()
    ]
    tasks_by_id = {str(t["id"]): t for t in all_tasks}
    tasks = [
        task
        for task in all_tasks
        if _task_dict_in_subtree(task, tasks_by_id, project_ids)
    ]
    idea: dict[str, Any] | None = None
    items: list[dict[str, Any]] = []
    source_idea_id = init.get("source_idea_id")
    if source_idea_id:
        idea_row = conn.execute(
            "SELECT * FROM ideas WHERE id = ? AND user_id = ?",
            (source_idea_id, user_id),
        ).fetchone()
        if idea_row is not None:
            idea = dict(idea_row)
            items = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM checklist_items "
                    "WHERE idea_id = ? AND user_id = ?",
                    (source_idea_id, user_id),
                ).fetchall()
            ]
            # Attach each item's dependency edges (the mapper reads
            # them as `depends_on`).
            dep_rows = conn.execute(
                "SELECT d.item_id, d.depends_on_item_id "
                "FROM checklist_item_dependencies d "
                "JOIN checklist_items i ON i.id = d.item_id "
                "WHERE i.idea_id = ? AND i.user_id = ?",
                (source_idea_id, user_id),
            ).fetchall()
            deps: dict[str, list[str]] = {}
            for item_id, depends_on in dep_rows:
                deps.setdefault(str(item_id), []).append(str(depends_on))
            for item in items:
                item["depends_on"] = deps.get(str(item["id"]), [])
    step_placeholders = ",".join("?" for _ in project_ids) if project_ids else ""
    step_params: list[Any] = [user_id, subtree_id]
    step_sql = (
        "SELECT * FROM execution_steps WHERE user_id = ? AND "
        "(scope_type = 'initiative' AND scope_id = ?)"
    )
    if project_ids:
        step_sql += (
            f" OR (scope_type = 'project' AND scope_id IN ({step_placeholders}))"
        )
        step_params.extend(sorted(project_ids))
    steps = [dict(r) for r in conn.execute(step_sql, tuple(step_params)).fetchall()]
    seats = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM initiative_seats WHERE initiative_id = ?",
            (subtree_id,),
        ).fetchall()
    ]
    return {
        "user_id": user_id,
        "initiative": init,
        "idea": idea,
        "projects": projects,
        "tasks": tasks,
        "checklist_items": items,
        "execution_steps": steps,
        "seats": seats,
    }


def canonicalize_legacy_subtree(
    conn: sqlite3.Connection, subtree_id: str, *, flipped_at: str | None = None
) -> dict[str, Any]:
    """The canonical document (§11.4) built from the LEGACY rows —
    the flip-time computation (§11.3 steps 6–7). The version is 1
    (the flip sets it) and flipped_at defaults to now (the flip
    stores the same value on the authority row). Callers must hold
    the flip transaction (BEGIN IMMEDIATE) before calling."""
    content = _legacy_subtree_rows(conn, subtree_id)
    forms: list[dict[str, Any]] = []
    forms.append(_node_form_from_legacy("initiative", content["initiative"]))
    if content["idea"] is not None:
        forms.append(_node_form_from_legacy("idea", content["idea"]))
    for project in content["projects"]:
        forms.append(_node_form_from_legacy("project", project))
    for task in content["tasks"]:
        forms.append(_node_form_from_legacy("task", task))
    for item in content["checklist_items"]:
        forms.append(_node_form_from_legacy("checklist_item", item))
    for step in content["execution_steps"]:
        forms.append(_node_form_from_legacy("execution_step", step))
    # No bullets exist at flip time (the legacy tables hold no
    # progressive needs); seats re-key from initiative_id to node_id.
    seats = [
        {
            "id": s["id"],
            "node_id": subtree_id,
            "role": s.get("role") or "",
            "assigned_person_id": s.get("assigned_person_id"),
            "estimated_effort": s.get("estimated_effort"),
            "notes": s.get("notes") or "",
        }
        for s in content["seats"]
    ]
    return _canonical_doc(
        forms,
        [],
        seats,
        subtree_id=subtree_id,
        version=1,
        flipped_at=flipped_at if flipped_at is not None else _now(),
    )


def compute_legacy_subtree_fingerprint(
    conn: sqlite3.Connection, subtree_id: str, *, flipped_at: str | None = None
) -> dict[str, str]:
    """The flip-time fingerprint: canonicalize from the legacy rows
    and SHA-256 the canonical bytes. Returns {"canonical_json",
    "sha256"}. The flip stores both on the authority row (§11.3
    step 9)."""
    doc = canonicalize_legacy_subtree(conn, subtree_id, flipped_at=flipped_at)
    text = _canonical_json(doc)
    return {"canonical_json": text, "sha256": _sha256_hex(text)}


# --- Auth (Phase 1A) ---

def get_user_by_email(email: str) -> dict[str, Any] | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT id, email, password_hash, display_name, is_admin, avatar_data_url, created_at, updated_at "
        "FROM users WHERE email = ?",
        (email.strip().lower(),),
    ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "email": row["email"],
        "password_hash": row["password_hash"],
        "display_name": row["display_name"],
        "is_admin": bool(row["is_admin"]),
        "avatar_data_url": row["avatar_data_url"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_users() -> list[dict[str, Any]]:
    """All login accounts (admin use: backfill, seeding). No password hashes."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, email, display_name, is_admin FROM users ORDER BY created_at"
    ).fetchall()
    return [
        {
            "id": row["id"],
            "email": row["email"],
            "display_name": row["display_name"],
            "is_admin": bool(row["is_admin"]),
        }
        for row in rows
    ]


def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT id, email, password_hash, display_name, is_admin, avatar_data_url, created_at, updated_at "
        "FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "email": row["email"],
        "password_hash": row["password_hash"],
        "display_name": row["display_name"],
        "is_admin": bool(row["is_admin"]),
        "avatar_data_url": row["avatar_data_url"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def authenticate_user(email: str, password: str) -> dict[str, Any] | None:
    user = get_user_by_email(email)
    if not user:
        return None
    if not _verify_password(password, user["password_hash"]):
        return None
    return user


def set_user_password_by_email(email: str, new_password: str) -> dict[str, Any]:
    """
    Replace password hash for a user (local dev / recovery). Email is normalized like login.
    """
    raw = (email or "").strip().lower()
    if not raw or not new_password:
        return {"ok": False, "reason": "email_and_password_required"}
    conn = get_connection()
    row = conn.execute("SELECT id FROM users WHERE email = ?", (raw,)).fetchone()
    if not row:
        return {"ok": False, "reason": "user_not_found", "email": raw}
    uid = row[0]
    conn.execute(
        "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
        (_hash_password(new_password), _now(), uid),
    )
    conn.commit()
    return {"ok": True, "user_id": uid, "email": raw}


def port_user_llm_stack_between_users(source_user_id: str, dest_user_id: str) -> dict[str, Any]:
    """
    Copy ``user_llm_profile`` + ``user_llm_provider_credentials`` from source to dest.
    Replaces dest credential rows. Ciphertext is reused; decryption must use the same Fernet key as when keys were saved.
    """
    su = (source_user_id or "").strip()
    du = (dest_user_id or "").strip()
    if not su or not du or su == du:
        return {"ok": False, "reason": "invalid_ids"}
    conn = get_connection()
    if get_user_by_id(su) is None or get_user_by_id(du) is None:
        return {"ok": False, "reason": "user_not_found"}
    n_before = _llm_credential_row_count(conn, du)
    n_src = _llm_credential_row_count(conn, su)
    _copy_user_llm_stack(conn, su, du)
    conn.commit()
    return {
        "ok": True,
        "dest_credentials_before": n_before,
        "dest_credentials_after": _llm_credential_row_count(conn, du),
        "source_credentials": n_src,
    }


def create_session(user_id: str, *, ttl_days: int = _SESSION_TTL_DAYS) -> str:
    conn = get_connection()
    sid = M.new_id()
    token = secrets.token_urlsafe(32)
    now = _now_dt()
    expires_at = now + timedelta(days=ttl_days)
    conn.execute(
        "INSERT INTO sessions (id, user_id, token_hash, created_at, expires_at, revoked_at) VALUES (?, ?, ?, ?, ?, NULL)",
        (sid, user_id, _hash_session_token(token), now.isoformat(), expires_at.isoformat()),
    )
    conn.commit()
    return token


def get_session_user(session_token: str) -> dict[str, Any] | None:
    if not session_token:
        return None
    conn = get_connection()
    row = conn.execute(
        """
        SELECT s.user_id, s.expires_at, s.revoked_at, u.id, u.email, u.display_name, u.is_admin, u.avatar_data_url
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token_hash = ?
        """,
        (_hash_session_token(session_token),),
    ).fetchone()
    if not row:
        return None
    if row["revoked_at"] is not None:
        return None
    try:
        if datetime.fromisoformat(row["expires_at"]) <= _now_dt():
            return None
    except Exception:
        return None
    return {
        "id": row["id"],
        "email": row["email"],
        "display_name": row["display_name"],
        "is_admin": bool(row["is_admin"]),
        "avatar_data_url": row["avatar_data_url"],
    }


def is_admin_user(user_id: str) -> bool:
    if not user_id:
        return False
    conn = get_connection()
    row = conn.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
    return bool(row and row["is_admin"])


def get_owner_user_id() -> str | None:
    """Id of the bootstrapped owner account, or None if absent.

    The owner is the user created by _ensure_default_owner_and_backfill
    (owner@local.zenaf). The build-room runner gates on this id so only
    the account whose OpenAI credit is spent can invoke a meeting.
    """
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM users WHERE email = ?",
        (_DEFAULT_OWNER_EMAIL,),
    ).fetchone()
    return str(row["id"]) if row else None


def revoke_session(session_token: str) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
        (_now(), _hash_session_token(session_token)),
    )
    conn.commit()


def create_user_account(
    email: str,
    password: str,
    display_name: str,
    *,
    is_admin: bool = False,
) -> dict[str, Any]:
    """
    Create a new login account. Raises ValueError("user_exists") if email is taken.
    Returns public user fields only (no password hash).
    """
    conn = get_connection()
    email_l = email.strip().lower()
    if not email_l or "@" not in email_l:
        raise ValueError("invalid_email")
    if conn.execute("SELECT id FROM users WHERE email = ?", (email_l,)).fetchone():
        raise ValueError("user_exists")
    uid = M.new_id()
    now = _now()
    dn = (display_name or "").strip() or email_l.split("@", 1)[0]
    conn.execute(
        "INSERT INTO users (id, email, password_hash, display_name, is_admin, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (uid, email_l, _hash_password(password), dn, 1 if is_admin else 0, now, now),
    )
    conn.commit()
    return {
        "id": uid,
        "email": email_l,
        "display_name": dn,
        "is_admin": bool(is_admin),
        "avatar_data_url": None,
    }


# --- User settings (LLM + notifications) ---
_SETTINGS_KEY_ENV = "ZENAF_SETTINGS_ENCRYPTION_KEY"
_SETTINGS_KEY_LOCAL_FILE = "settings_encryption.key"
_LLM_PROVIDERS_WITH_KEY = frozenset({"openai", "anthropic", "google", "xai", "meta", "openrouter"})
_LLM_DEFAULT_PROVIDERS = frozenset({"ollama", "openai", "anthropic", "google", "xai", "meta", "openrouter"})
_settings_key_cache: str | None = None


def _validate_fernet_key_string(raw: str) -> bool:
    if not raw:
        return False
    try:
        from cryptography.fernet import Fernet

        Fernet(raw.encode("utf-8"))
        return True
    except Exception:
        return False


def _local_settings_encryption_key_path() -> Path:
    """Primary path for UI messages (first candidate)."""
    return _settings_encryption_key_paths()[0]


def _settings_encryption_key_paths() -> list[Path]:
    """
    Order: on server deployments the persistent data dir comes first; local dev keeps the
    historical home-first order.

    Why: on Fly the persistent volume IS the repo data dir (WORKDIR /app + volume at
    /app/data, so ``_DB_DIR`` survives redeploys), while home is ephemeral. A key file
    created under home is lost on redeploy, a new key is generated, and every
    previously saved credential becomes undecryptable — while the rows (and the
    "Configured" display, which checks row presence only) survive. NOTE: this prevents
    future orphans only; rows orphaned by an already-lost key cannot be recovered
    without that key and must be re-saved in Settings.
    """
    home_path = Path.home() / ".zenaf" / _SETTINGS_KEY_LOCAL_FILE
    data_path = _DB_DIR / _SETTINGS_KEY_LOCAL_FILE
    if (
        _is_prod()
        or os.environ.get("ZENAF_DATA_DIR")
        or os.environ.get("ZENAF_DB_DIR")
    ):
        return [data_path, home_path]
    return [home_path, data_path]


def _get_settings_encryption_key_raw() -> str | None:
    """
    Prefer ``ZENAF_SETTINGS_ENCRYPTION_KEY`` when valid.
    Otherwise read or create a Fernet key file (see ``_settings_encryption_key_paths``).
    """
    global _settings_key_cache
    env_raw = os.environ.get(_SETTINGS_KEY_ENV, "").strip()
    if env_raw:
        if _validate_fernet_key_string(env_raw):
            return env_raw
        _logger.warning(
            "%s is set but invalid; trying local key files under %s",
            _SETTINGS_KEY_ENV,
            [str(p) for p in _settings_encryption_key_paths()],
        )
    if _settings_key_cache and _validate_fernet_key_string(_settings_key_cache):
        return _settings_key_cache

    for p in _settings_encryption_key_paths():
        try:
            if p.is_file():
                k = p.read_text(encoding="utf-8").strip()
                if _validate_fernet_key_string(k):
                    _settings_key_cache = k
                    _logger.info("Loaded settings encryption key from %s", p)
                    return k
        except OSError as e:
            _logger.warning("Could not read settings key from %s: %s", p, e)

    try:
        from cryptography.fernet import Fernet
    except ImportError as e:
        _logger.error(
            "cryptography is not installed; cannot store API keys in Settings. "
            "Install with: pip install cryptography (%s)",
            e,
        )
        return None

    k = Fernet.generate_key().decode()
    for p in _settings_encryption_key_paths():
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(k, encoding="utf-8")
            try:
                os.chmod(p, 0o600)
            except OSError:
                pass
            _settings_key_cache = k
            _logger.info(
                "Created local settings encryption key at %s (set %s to override).",
                p,
                _SETTINGS_KEY_ENV,
            )
            return k
        except OSError as e:
            _logger.warning("Could not write settings encryption key to %s: %s", p, e)
            continue

    _logger.error(
        "Could not create settings encryption key in any location (tried %s)",
        [str(p) for p in _settings_encryption_key_paths()],
    )
    return None


def settings_encryption_available() -> bool:
    return _get_settings_encryption_key_raw() is not None


def settings_encryption_key_paths_for_diagnostics() -> list[str]:
    """Public strings for startup logs / support (no secrets)."""
    return [str(p) for p in _settings_encryption_key_paths()]


def _fernet_cipher():
    raw = _get_settings_encryption_key_raw()
    if not raw:
        return None
    try:
        from cryptography.fernet import Fernet

        return Fernet(raw.encode("utf-8"))
    except Exception:
        return None


def encrypt_credential_secret(plaintext: str) -> str:
    """Return urlsafe-b64-encoded Fernet token for SQLite TEXT storage."""
    import base64

    f = _fernet_cipher()
    if f is None:
        raise ValueError(
            "Cannot encrypt API keys: install the cryptography package (pip install cryptography), "
            f"set {_SETTINGS_KEY_ENV} to a valid Fernet key, or ensure a writable key file at one of: "
            f"{', '.join(str(p) for p in _settings_encryption_key_paths())}."
        )
    tok = f.encrypt(plaintext.encode("utf-8"))
    return base64.urlsafe_b64encode(tok).decode("ascii")


def decrypt_credential_secret(stored: str) -> str:
    import base64

    f = _fernet_cipher()
    if f is None:
        raise ValueError(
            f"Cannot decrypt credentials: set {_SETTINGS_KEY_ENV} or restore a key file at "
            f"{', '.join(str(p) for p in _settings_encryption_key_paths())}."
        )
    raw = base64.urlsafe_b64decode(stored.encode("ascii"))
    return f.decrypt(raw).decode("utf-8")


_MAX_AVATAR_DATA_URL_LEN = 320_000
_ALLOWED_AVATAR_PREFIXES = (
    "data:image/jpeg;base64,",
    "data:image/jpg;base64,",
    "data:image/png;base64,",
    "data:image/webp;base64,",
    "data:image/gif;base64,",
)

_USER_PERMISSION_DEFAULTS: dict[str, bool] = {
    "behavioral_tracking": False,
    "personalization": False,
    "interaction_pattern_storage": False,
    "profile_learning": False,
    "analytics_product_improvement": False,
    "aspiration_store_explicit": False,
    "aspiration_infer_suggestions": False,
    "aspiration_use_in_guidance": False,
    # Increment A: Narrative Steward derivation (proposal §1.8).
    # Default off; existing rows read False for it until the
    # visitor turns it on — nobody is opted in by the addition.
    # NOTE: the upsert needs no logic change, but this key-list
    # entry IS required — normalize_user_permission_prefs filters
    # to these keys and would otherwise drop the flag on write.
    "steward_derivation": False,
    # Permission Slice 1 (foundation) — R3 DEAD-FLAG REPAIR
    # (inventory §1.4): steward_coordination existed in
    # narrative/consent.py and was consumed by coordination.py,
    # but was absent from this key list AND the frontend defaults,
    # so normalize_user_permission_prefs dropped it on every read
    # and write and coordination_allowed was always False in
    # production. Adding the key here (and to
    # USER_PERMISSION_DEFAULTS in frontend/src/settings/api.ts)
    # makes the flag persist at all. Default off; existing rows
    # read False for it until the visitor turns it on — nobody is
    # opted in by the repair, and no forced re-acknowledgement.
    # No Settings UI row is added in Slice 1 (bounds): the flag
    # persists via the API + defaults, and its row lands with the
    # Slice 2 Settings surface.
    "steward_coordination": False,
    # Phase 0 consent correction — fellowship derivation gate.
    # Dedicated default-off flag, distinct from steward_derivation
    # by design (a visitor may want steward threads without
    # fellowship readings, and vice versa). Default off; existing
    # rows read False for it until the visitor turns it on —
    # nobody is opted in by the addition. NOTE: this key-list
    # entry IS required — normalize_user_permission_prefs filters
    # to these keys and would otherwise drop the flag on write.
    # The toggle wording is a founder decision; no Settings UI row
    # is added here (bounds) — the flag persists via the API +
    # defaults, and its row lands once the wording is ruled.
    "fellowship_derivation": False,
}

_USER_PERMISSION_KEYS = tuple(_USER_PERMISSION_DEFAULTS.keys())


def _validate_avatar_data_url(v: str) -> str:
    s = v.strip()
    if not s:
        raise ValueError("invalid_avatar")
    if len(s) > _MAX_AVATAR_DATA_URL_LEN:
        raise ValueError("avatar_too_large")
    if not any(s.startswith(p) for p in _ALLOWED_AVATAR_PREFIXES):
        raise ValueError("invalid_avatar")
    return s


def update_user_display_name(user_id: str, display_name: str) -> dict[str, Any] | None:
    return patch_user_profile(user_id, {"display_name": display_name.strip()})


def patch_user_profile(user_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
    """Update allowed public user fields. Values for avatar_data_url: set str, or None/'' to clear."""
    if get_user_by_id(user_id) is None:
        return None
    sets: list[str] = []
    vals: list[Any] = []
    if "display_name" in fields:
        dn = fields["display_name"]
        if dn is None:
            raise ValueError("display_name_invalid")
        dns = str(dn).strip()
        if not dns:
            raise ValueError("display_name_invalid")
        sets.append("display_name = ?")
        vals.append(dns)
    if "avatar_data_url" in fields:
        raw = fields["avatar_data_url"]
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            sets.append("avatar_data_url = ?")
            vals.append(None)
        else:
            sets.append("avatar_data_url = ?")
            vals.append(_validate_avatar_data_url(str(raw)))
    if not sets:
        return get_user_by_id(user_id)
    now = _now()
    vals.append(now)
    vals.append(user_id)
    conn = get_connection()
    conn.execute(
        f"UPDATE users SET {', '.join(sets)}, updated_at = ? WHERE id = ?",
        vals,
    )
    conn.commit()
    return get_user_by_id(user_id)


def normalize_user_permission_prefs(raw: Any) -> dict[str, bool]:
    out = dict(_USER_PERMISSION_DEFAULTS)
    if not isinstance(raw, dict):
        return out
    for key in _USER_PERMISSION_KEYS:
        if isinstance(raw.get(key), bool):
            out[key] = bool(raw[key])
    return out


def get_user_permissions_settings(user_id: str) -> dict[str, Any]:
    conn = get_connection()
    row = conn.execute(
        "SELECT consent_given, consent_version, consent_at, permissions_json, updated_at "
        "FROM user_permissions_settings WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row:
        try:
            parsed = json.loads(row["permissions_json"] or "{}")
        except Exception:
            parsed = {}
        perms = normalize_user_permission_prefs(parsed)
        consent_given = bool(row["consent_given"])
        consent_version = str(row["consent_version"] or "")
        consent_at = row["consent_at"]
        updated_at = row["updated_at"]
        normalized_blob = json.dumps(perms, sort_keys=True)
        if normalized_blob != json.dumps(parsed if isinstance(parsed, dict) else {}, sort_keys=True):
            now = _now()
            conn.execute(
                "UPDATE user_permissions_settings SET permissions_json = ?, updated_at = ? WHERE user_id = ?",
                (normalized_blob, now, user_id),
            )
            conn.commit()
            updated_at = now
        return {
            "consent_given": consent_given,
            "consent_version": consent_version,
            "consent_at": consent_at,
            "updated_at": updated_at,
            "permissions": perms,
        }
    now = _now()
    conn.execute(
        """
        INSERT INTO user_permissions_settings (user_id, consent_given, consent_version, consent_at, permissions_json, updated_at)
        VALUES (?, 0, '', NULL, ?, ?)
        """,
        (user_id, json.dumps(_USER_PERMISSION_DEFAULTS), now),
    )
    conn.commit()
    return {
        "consent_given": False,
        "consent_version": "",
        "consent_at": None,
        "updated_at": now,
        "permissions": dict(_USER_PERMISSION_DEFAULTS),
    }


def upsert_user_permissions_settings(
    user_id: str,
    *,
    permissions: dict[str, Any],
    consent_acknowledged: bool,
    consent_version: str,
) -> dict[str, Any]:
    conn = get_connection()
    now = _now()
    canonical = normalize_user_permission_prefs(permissions or {})
    consent_version_s = (consent_version or "").strip()
    if consent_acknowledged and not consent_version_s:
        raise ValueError("consent_version is required when consent_acknowledged is true")
    row = conn.execute(
        "SELECT user_id, consent_given, consent_at FROM user_permissions_settings WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row:
        prior_consent_at = row["consent_at"]
        next_consent_at = prior_consent_at
        if consent_acknowledged and not prior_consent_at:
            next_consent_at = now
        conn.execute(
            """
            UPDATE user_permissions_settings
            SET consent_given = ?, consent_version = ?, consent_at = ?, permissions_json = ?, updated_at = ?
            WHERE user_id = ?
            """,
            (1 if consent_acknowledged else 0, consent_version_s, next_consent_at, json.dumps(canonical), now, user_id),
        )
    else:
        conn.execute(
            """
            INSERT INTO user_permissions_settings (user_id, consent_given, consent_version, consent_at, permissions_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                1 if consent_acknowledged else 0,
                consent_version_s,
                now if consent_acknowledged else None,
                json.dumps(canonical),
                now,
            ),
        )
    conn.commit()
    return get_user_permissions_settings(user_id)


def user_permission_enabled(user_id: str, permission_key: str) -> bool:
    settings = get_user_permissions_settings(user_id)
    if not settings.get("consent_given"):
        return False
    perms = settings.get("permissions")
    if not isinstance(perms, dict):
        return False
    return bool(perms.get(permission_key, False))


def _parse_json_array(raw: str | None, *, max_len: int = 64) -> list[str]:
    if not raw or not str(raw).strip():
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out: list[str] = []
    for x in data[:max_len]:
        if isinstance(x, str) and x.strip():
            out.append(x.strip()[:400])
    return out


def _parse_json_obj(raw: str | None) -> dict[str, Any]:
    if not raw or not str(raw).strip():
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _aspiration_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    keys = set(row.keys()) if hasattr(row, "keys") else set()
    return {
        "user_id": row["user_id"],
        "core_aim": row["core_aim"] or "",
        "growth_domains": _parse_json_array(row["growth_domains"]),
        "current_edge": row["current_edge"] or "",
        "current_obstacles": row["current_obstacles"] or "",
        "near_term_aspirations": row["near_term_aspirations"] or "",
        "long_term_aspirations": row["long_term_aspirations"] or "",
        "guidance_preferences": _parse_json_obj(row["guidance_preferences"]),
        "anti_goals": row["anti_goals"] or "",
        # Heart fields (Phase 2): absent on pre-Phase 2 rows, where
        # the migration above has not run — read as "not stated",
        # never inferred.
        "heart_loves": row["heart_loves"] if "heart_loves" in keys else "",
        "heart_meaning": row["heart_meaning"] if "heart_meaning" in keys else "",
        "heart_commitments": (
            row["heart_commitments"] if "heart_commitments" in keys else ""
        ),
        "use_in_guidance": bool(row["use_in_guidance"]),
        "allow_inference": bool(row["allow_inference"]),
        "updated_at": row["updated_at"],
    }


def get_aspiration_profile(user_id: str) -> dict[str, Any] | None:
    uid = (user_id or "").strip()
    if not uid:
        return None
    conn = get_connection()
    row = conn.execute("SELECT * FROM aspiration_profile WHERE user_id = ?", (uid,)).fetchone()
    if not row:
        return None
    return _aspiration_row_to_dict(row)


def _validate_aspiration_text_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Clamp and normalize writable aspiration fields."""
    out: dict[str, Any] = {}
    for key in (
        "core_aim",
        "current_edge",
        "current_obstacles",
        "near_term_aspirations",
        "long_term_aspirations",
        "anti_goals",
        "heart_loves",
        "heart_meaning",
        "heart_commitments",
    ):
        if key not in data:
            continue
        v = data.get(key)
        s = "" if v is None else str(v)
        if len(s) > 12000:
            s = s[:12000]
        out[key] = s
    if "growth_domains" in data:
        gd = data.get("growth_domains")
        if isinstance(gd, list):
            out["growth_domains"] = json.dumps([str(x).strip()[:400] for x in gd[:48] if str(x).strip()])
        elif isinstance(gd, str):
            try:
                parsed = json.loads(gd)
                if isinstance(parsed, list):
                    out["growth_domains"] = json.dumps([str(x).strip()[:400] for x in parsed[:48] if str(x).strip()])
                else:
                    out["growth_domains"] = "[]"
            except Exception:
                out["growth_domains"] = "[]"
    if "guidance_preferences" in data:
        gp = data.get("guidance_preferences")
        if isinstance(gp, dict):
            out["guidance_preferences"] = json.dumps({str(k)[:80]: v for k, v in list(gp.items())[:32]})
        elif isinstance(gp, str):
            try:
                parsed = json.loads(gp)
                out["guidance_preferences"] = json.dumps(parsed) if isinstance(parsed, dict) else "{}"
            except Exception:
                out["guidance_preferences"] = "{}"
    if "use_in_guidance" in data:
        out["use_in_guidance"] = 1 if bool(data.get("use_in_guidance")) else 0
    if "allow_inference" in data:
        out["allow_inference"] = 1 if bool(data.get("allow_inference")) else 0
    return out


def upsert_aspiration_profile(user_id: str, data: dict[str, Any]) -> dict[str, Any]:
    uid = (user_id or "").strip()
    if not uid:
        raise ValueError("user_id_required")
    if get_user_by_id(uid) is None:
        raise ValueError("user_not_found")
    fields = _validate_aspiration_text_fields(data)
    now = _now()
    conn = get_connection()
    row = conn.execute("SELECT user_id FROM aspiration_profile WHERE user_id = ?", (uid,)).fetchone()
    if row:
        if not fields:
            conn.commit()
            return get_aspiration_profile(uid) or {}
        sets = [f"{k} = ?" for k in fields.keys()]
        vals = list(fields.values())
        vals.append(now)
        vals.append(uid)
        conn.execute(
            f"UPDATE aspiration_profile SET {', '.join(sets)}, updated_at = ? WHERE user_id = ?",
            vals,
        )
    else:
        defaults = {
            "core_aim": "",
            "growth_domains": "[]",
            "current_edge": "",
            "current_obstacles": "",
            "near_term_aspirations": "",
            "long_term_aspirations": "",
            "guidance_preferences": "{}",
            "anti_goals": "",
            "heart_loves": "",
            "heart_meaning": "",
            "heart_commitments": "",
            "use_in_guidance": 0,
            "allow_inference": 0,
        }
        for k, v in fields.items():
            defaults[k] = v
        conn.execute(
            """
            INSERT INTO aspiration_profile (
              user_id, core_aim, growth_domains, current_edge, current_obstacles,
              near_term_aspirations, long_term_aspirations, guidance_preferences, anti_goals,
              heart_loves, heart_meaning, heart_commitments,
              use_in_guidance, allow_inference, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uid,
                defaults["core_aim"],
                defaults["growth_domains"],
                defaults["current_edge"],
                defaults["current_obstacles"],
                defaults["near_term_aspirations"],
                defaults["long_term_aspirations"],
                defaults["guidance_preferences"],
                defaults["anti_goals"],
                defaults["heart_loves"],
                defaults["heart_meaning"],
                defaults["heart_commitments"],
                int(defaults["use_in_guidance"]),
                int(defaults["allow_inference"]),
                now,
            ),
        )
    conn.commit()
    return get_aspiration_profile(uid) or {}


def patch_aspiration_profile(user_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
    uid = (user_id or "").strip()
    if not uid:
        return None
    if get_aspiration_profile(uid) is None:
        return upsert_aspiration_profile(uid, fields)
    validated = _validate_aspiration_text_fields(fields)
    if not validated:
        return get_aspiration_profile(uid)
    now = _now()
    conn = get_connection()
    sets = [f"{k} = ?" for k in validated.keys()]
    vals = list(validated.values())
    vals.append(now)
    vals.append(uid)
    conn.execute(
        f"UPDATE aspiration_profile SET {', '.join(sets)}, updated_at = ? WHERE user_id = ?",
        vals,
    )
    conn.commit()
    return get_aspiration_profile(uid)


def append_aspiration_inference_log(user_id: str, snapshot: dict[str, Any]) -> None:
    uid = (user_id or "").strip()
    if not uid:
        return
    now = _now()
    conn = get_connection()
    conn.execute(
        "INSERT INTO aspiration_inference_log (id, user_id, snapshot_json, created_at) VALUES (?, ?, ?, ?)",
        (M.new_id(), uid, json.dumps(snapshot, default=str)[:200_000], now),
    )
    conn.commit()


def list_aspiration_proposals(user_id: str, *, status: str | None = "pending") -> list[dict[str, Any]]:
    uid = (user_id or "").strip()
    if not uid:
        return []
    conn = get_connection()
    if status:
        rows = conn.execute(
            "SELECT * FROM aspiration_proposals WHERE user_id = ? AND status = ? ORDER BY created_at DESC LIMIT 50",
            (uid, status),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM aspiration_proposals WHERE user_id = ? ORDER BY created_at DESC LIMIT 50",
            (uid,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        basis: list[str] = []
        try:
            bj = json.loads(r["basis_json"] or "[]")
            if isinstance(bj, list):
                basis = [str(x) for x in bj[:12] if str(x).strip()]
        except Exception:
            pass
        out.append(
            {
                "id": r["id"],
                "user_id": r["user_id"],
                "theme": r["theme"] or "",
                "detail": r["detail"] or "",
                "basis": basis,
                "status": r["status"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
        )
    return out


def create_aspiration_proposal(
    user_id: str,
    *,
    theme: str,
    detail: str,
    basis: list[str],
) -> dict[str, Any]:
    uid = (user_id or "").strip()
    if not uid:
        raise ValueError("user_id_required")
    now = _now()
    pid = M.new_id()
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO aspiration_proposals (id, user_id, theme, detail, basis_json, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
        """,
        (
            pid,
            uid,
            theme.strip()[:240],
            detail.strip()[:1200],
            json.dumps([b[:400] for b in basis[:12]]),
            now,
            now,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM aspiration_proposals WHERE id = ?", (pid,)).fetchone()
    if not row:
        return {}
    return {
        "id": row["id"],
        "theme": row["theme"],
        "detail": row["detail"],
        "basis": basis,
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def set_aspiration_proposal_status(
    user_id: str,
    proposal_id: str,
    status: str,
) -> dict[str, Any] | None:
    uid = (user_id or "").strip()
    pid = (proposal_id or "").strip()
    if not uid or not pid:
        return None
    if status not in ("pending", "accepted", "dismissed"):
        raise ValueError("invalid_status")
    now = _now()
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM aspiration_proposals WHERE user_id = ? AND id = ?",
        (uid, pid),
    ).fetchone()
    if not row:
        return None
    conn.execute(
        "UPDATE aspiration_proposals SET status = ?, updated_at = ? WHERE user_id = ? AND id = ?",
        (status, now, uid, pid),
    )
    conn.commit()
    return {
        "id": pid,
        "status": status,
        "updated_at": now,
    }


def _parse_llm_provider_prefs(raw: str | None) -> dict[str, Any]:
    if not raw or not str(raw).strip():
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def get_user_llm_profile(user_id: str) -> dict[str, Any]:
    conn = get_connection()
    row = conn.execute(
        "SELECT user_id, default_provider, default_model, ollama_base_url, ollama_model, "
        "llm_provider_prefs_json, updated_at "
        "FROM user_llm_profile WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row:
        d = dict(row)
        prefs_raw = d.get("llm_provider_prefs_json") or "{}"
        d["provider_prefs"] = _parse_llm_provider_prefs(prefs_raw if isinstance(prefs_raw, str) else "{}")
        return d
    now = _now()
    conn.execute(
        "INSERT INTO user_llm_profile (user_id, default_provider, default_model, ollama_base_url, ollama_model, "
        "llm_provider_prefs_json, updated_at) "
        "VALUES (?, 'ollama', NULL, NULL, NULL, '{}', ?)",
        (user_id, now),
    )
    conn.commit()
    return {
        "user_id": user_id,
        "default_provider": "meta",
        "default_model": None,
        "ollama_base_url": None,
        "ollama_model": None,
        "llm_provider_prefs_json": "{}",
        "provider_prefs": {},
        "updated_at": now,
    }


_LLM_EXECUTION_PROVIDER_IDS = frozenset({"ollama", "openai", "anthropic", "google", "xai", "meta", "openrouter"})


def set_llm_provider_enabled(user_id: str, provider: str, enabled: bool) -> dict[str, Any]:
    pv = (provider or "").strip().lower()
    if pv not in _LLM_EXECUTION_PROVIDER_IDS:
        raise ValueError(f"Invalid provider: {provider}")
    get_user_llm_profile(user_id)
    conn = get_connection()
    row = conn.execute(
        "SELECT llm_provider_prefs_json FROM user_llm_profile WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    prefs = _parse_llm_provider_prefs(row["llm_provider_prefs_json"] if row else None)
    block = dict(prefs.get(pv) or {})
    block["enabled"] = bool(enabled)
    prefs[pv] = block
    now = _now()
    conn.execute(
        "UPDATE user_llm_profile SET llm_provider_prefs_json = ?, updated_at = ? WHERE user_id = ?",
        (json.dumps(prefs), now, user_id),
    )
    conn.commit()
    return get_user_llm_profile(user_id)


def record_llm_provider_test_result(
    user_id: str,
    provider: str,
    *,
    ok: bool,
    error: str | None = None,
) -> dict[str, Any]:
    pv = (provider or "").strip().lower()
    if pv not in _LLM_EXECUTION_PROVIDER_IDS:
        raise ValueError(f"Invalid provider: {provider}")
    get_user_llm_profile(user_id)
    conn = get_connection()
    row = conn.execute(
        "SELECT llm_provider_prefs_json FROM user_llm_profile WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    prefs = _parse_llm_provider_prefs(row["llm_provider_prefs_json"] if row else None)
    block = dict(prefs.get(pv) or {})
    block["last_test"] = {
        "ok": bool(ok),
        "at": _now(),
        "error": (error or None) if not ok else None,
    }
    prefs[pv] = block
    now = _now()
    conn.execute(
        "UPDATE user_llm_profile SET llm_provider_prefs_json = ?, updated_at = ? WHERE user_id = ?",
        (json.dumps(prefs), now, user_id),
    )
    conn.commit()
    return get_user_llm_profile(user_id)


_COUNCIL_SEATS_PREFS_KEY = "__council_seats"


def get_council_seat_providers(user_id: str) -> dict[str, str]:
    """Map perspective/seat id → provider id (excludes 'auto' / unset)."""
    prof = get_user_llm_profile(user_id)
    pp = prof.get("provider_prefs") or {}
    raw = pp.get(_COUNCIL_SEATS_PREFS_KEY)
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        if not isinstance(k, str) or not isinstance(v, str):
            continue
        pv = v.strip().lower()
        if pv and pv not in ("auto", "default"):
            out[k.strip()] = pv
    return out


def set_council_seat_llm_provider(user_id: str, seat_id: str, llm_provider: str) -> dict[str, str]:
    """Persist seat → provider. Use ``auto`` / empty to clear."""
    sid = (seat_id or "").strip()
    if not sid:
        raise ValueError("seat_id is required")
    pv_in = (llm_provider or "").strip().lower()
    if pv_in in ("", "auto", "default"):
        pv_in = "auto"
    elif pv_in not in _LLM_EXECUTION_PROVIDER_IDS:
        raise ValueError(f"Invalid llm_provider: {llm_provider}")
    get_user_llm_profile(user_id)
    conn = get_connection()
    row = conn.execute(
        "SELECT llm_provider_prefs_json FROM user_llm_profile WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    prefs = _parse_llm_provider_prefs(row["llm_provider_prefs_json"] if row else None)
    seats = dict(prefs.get(_COUNCIL_SEATS_PREFS_KEY) or {}) if isinstance(prefs.get(_COUNCIL_SEATS_PREFS_KEY), dict) else {}
    if pv_in == "auto":
        seats.pop(sid, None)
    else:
        seats[sid] = pv_in
    prefs[_COUNCIL_SEATS_PREFS_KEY] = seats
    now = _now()
    conn.execute(
        "UPDATE user_llm_profile SET llm_provider_prefs_json = ?, updated_at = ? WHERE user_id = ?",
        (json.dumps(prefs), now, user_id),
    )
    conn.commit()
    return get_council_seat_providers(user_id)


_MAX_COUNCIL_WORKSPACE_JSON_BYTES = 1_250_000


def get_user_council_workspace(user_id: str) -> dict[str, Any] | None:
    """Return persisted perspective agents JSON, or None if the user has no row yet."""
    conn = get_connection()
    row = conn.execute(
        "SELECT perspectives_json, updated_at FROM user_council_workspace WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if not row:
        return None
    return {"perspectives_json": row["perspectives_json"], "updated_at": row["updated_at"]}


def upsert_user_council_workspace(user_id: str, perspectives: list[Any]) -> dict[str, Any]:
    blob = json.dumps(perspectives, ensure_ascii=False)
    if len(blob.encode("utf-8")) > _MAX_COUNCIL_WORKSPACE_JSON_BYTES:
        raise ValueError("council_workspace_perspectives_payload_too_large")
    conn = get_connection()
    now = _now()
    exists = conn.execute(
        "SELECT 1 FROM user_council_workspace WHERE user_id = ? LIMIT 1",
        (user_id,),
    ).fetchone()
    if exists:
        conn.execute(
            "UPDATE user_council_workspace SET perspectives_json = ?, updated_at = ? WHERE user_id = ?",
            (blob, now, user_id),
        )
    else:
        conn.execute(
            "INSERT INTO user_council_workspace (user_id, perspectives_json, updated_at) VALUES (?, ?, ?)",
            (user_id, blob, now),
        )
    conn.commit()
    return {"updated_at": now}


def upsert_user_llm_profile(
    user_id: str,
    *,
    default_provider: str,
    default_model: str | None,
    ollama_base_url: str | None,
    ollama_model: str | None,
) -> dict[str, Any]:
    dp = (default_provider or "meta").strip().lower()
    if dp not in _LLM_DEFAULT_PROVIDERS:
        raise ValueError(f"Invalid default_provider: {default_provider}")
    get_user_llm_profile(user_id)  # ensure row
    conn = get_connection()
    now = _now()
    conn.execute(
        "UPDATE user_llm_profile SET default_provider = ?, default_model = ?, ollama_base_url = ?, "
        "ollama_model = ?, updated_at = ? WHERE user_id = ?",
        (dp, default_model, ollama_base_url, ollama_model, now, user_id),
    )
    conn.commit()
    return get_user_llm_profile(user_id)


def llm_credential_row_exists(user_id: str, provider: str) -> bool:
    conn = get_connection()
    row = conn.execute(
        "SELECT 1 FROM user_llm_provider_credentials WHERE user_id = ? AND provider = ? LIMIT 1",
        (user_id, provider),
    ).fetchone()
    return row is not None


def upsert_llm_provider_credential(user_id: str, provider: str, api_key_plain: str) -> None:
    pv = (provider or "").strip().lower()
    if pv not in _LLM_PROVIDERS_WITH_KEY:
        raise ValueError("Provider does not use stored API keys in this build.")
    ct = encrypt_credential_secret(api_key_plain.strip())
    conn = get_connection()
    now = _now()
    row_id = conn.execute(
        "SELECT id FROM user_llm_provider_credentials WHERE user_id = ? AND provider = ?",
        (user_id, pv),
    ).fetchone()
    if row_id:
        conn.execute(
            "UPDATE user_llm_provider_credentials SET api_key_ciphertext = ?, updated_at = ? WHERE user_id = ? AND provider = ?",
            (ct, now, user_id, pv),
        )
    else:
        conn.execute(
            "INSERT INTO user_llm_provider_credentials (id, user_id, provider, api_key_ciphertext, extra_json, updated_at) "
            "VALUES (?, ?, ?, ?, '{}', ?)",
            (M.new_id(), user_id, pv, ct, now),
        )
    conn.commit()


def get_decrypted_llm_api_key(user_id: str, provider: str) -> str | None:
    pv = (provider or "").strip().lower()
    if pv not in _LLM_PROVIDERS_WITH_KEY:
        return None
    conn = get_connection()
    row = conn.execute(
        "SELECT api_key_ciphertext FROM user_llm_provider_credentials WHERE user_id = ? AND provider = ?",
        (user_id, pv),
    ).fetchone()
    if not row:
        return None
    try:
        return decrypt_credential_secret(row["api_key_ciphertext"])
    except Exception:
        return None


def list_llm_credentials_mask(user_id: str) -> dict[str, bool]:
    conn = get_connection()
    cur = conn.execute(
        "SELECT provider FROM user_llm_provider_credentials WHERE user_id = ?",
        (user_id,),
    )
    present = {r[0] for r in cur.fetchall()}
    return {p: (p in present) for p in sorted(_LLM_PROVIDERS_WITH_KEY)}


# Canonical notification prefs (nested only). Legacy flat {in_app: bool, email: bool} is normalized on read/write.
_NOTIFICATION_DEFAULTS: dict[str, Any] = {
    "in_app": {
        "task_activity": True,
        "matching": True,
        "share_revoke": True,
        "sync_system": True,
    },
    "email": {
        "enabled": False,
        "task_activity": False,
        "matching": False,
        "share_revoke": False,
        "sync_system": False,
    },
}
_IN_APP_KEYS = ("task_activity", "matching", "share_revoke", "sync_system")
_EMAIL_KEYS = ("enabled", "task_activity", "matching", "share_revoke", "sync_system")


def normalize_notification_prefs(raw: Any) -> dict[str, Any]:
    """Return canonical nested notification prefs. Merges known keys; tolerates legacy top-level booleans."""
    out = json.loads(json.dumps(_NOTIFICATION_DEFAULTS))
    if not isinstance(raw, dict):
        return out
    in_app = raw.get("in_app")
    if isinstance(in_app, bool):
        for k in _IN_APP_KEYS:
            out["in_app"][k] = in_app
    elif isinstance(in_app, dict):
        for k in _IN_APP_KEYS:
            if k in in_app and isinstance(in_app[k], bool):
                out["in_app"][k] = in_app[k]
    email = raw.get("email")
    if isinstance(email, bool):
        out["email"]["enabled"] = email
    elif isinstance(email, dict):
        for k in _EMAIL_KEYS:
            if k in email and isinstance(email[k], bool):
                out["email"][k] = email[k]
    return out


def get_user_notification_settings(user_id: str) -> dict[str, Any]:
    conn = get_connection()
    row = conn.execute(
        "SELECT prefs_json, updated_at FROM user_notification_settings WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row:
        try:
            data = json.loads(row["prefs_json"] or "{}")
        except Exception:
            data = {}
        normalized = normalize_notification_prefs(data)
        if json.dumps(normalized, sort_keys=True) != json.dumps(data, sort_keys=True):
            now = _now()
            conn.execute(
                "UPDATE user_notification_settings SET prefs_json = ?, updated_at = ? WHERE user_id = ?",
                (json.dumps(normalized), now, user_id),
            )
            conn.commit()
            return {"prefs": normalized, "updated_at": now}
        return {"prefs": normalized, "updated_at": row["updated_at"]}
    now = _now()
    conn.execute(
        "INSERT INTO user_notification_settings (user_id, prefs_json, updated_at) VALUES (?, ?, ?)",
        (user_id, json.dumps(_NOTIFICATION_DEFAULTS), now),
    )
    conn.commit()
    return {"prefs": json.loads(json.dumps(_NOTIFICATION_DEFAULTS)), "updated_at": now}


def upsert_user_notification_settings(user_id: str, prefs: dict[str, Any]) -> dict[str, Any]:
    conn = get_connection()
    now = _now()
    canonical = normalize_notification_prefs(prefs or {})
    row = conn.execute(
        "SELECT user_id FROM user_notification_settings WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    blob = json.dumps(canonical)
    if row:
        conn.execute(
            "UPDATE user_notification_settings SET prefs_json = ?, updated_at = ? WHERE user_id = ?",
            (blob, now, user_id),
        )
    else:
        conn.execute(
            "INSERT INTO user_notification_settings (user_id, prefs_json, updated_at) VALUES (?, ?, ?)",
            (user_id, blob, now),
        )
    conn.commit()
    return get_user_notification_settings(user_id)


# --- Studio / admin teacher controls ---

_STUDIO_COUNCIL_TEACHER_KEY = "council_teacher"
_TEACHER_MODE_VALUES = frozenset({"off", "shadow", "warn", "veto", "replace"})
_TEACHER_PROVIDER_VALUES = frozenset({"ollama", "openai", "anthropic", "google", "xai"})

_STUDIO_COUNCIL_TEACHER_DEFAULTS: dict[str, Any] = {
    "teacher_mode": "shadow",
    "teacher_provider": "ollama",
    "teacher_model": "qwen3:8b",
    "teacher_prompt_version": "council_teacher_v1",
    "teacher_prompt_overlay": None,
    "main_attachment_provider": "ollama",
    "main_attachment_model": "qwen3:8b",
    "local_attachment_provider": "ollama",
    "local_attachment_model": "qwen3:8b",
    "experimental_google_provider": "google",
    "experimental_google_model": "gemini-3.8-flash",
    "experimental_xai_provider": "xai",
    "experimental_xai_model": "grok-4-1-fast-reasoning",
    "capability_teacher_modes": {},
}


def _normalize_attachment_provider(v: Any) -> str | None:
    if v is None:
        return None
    p = str(v).strip().lower() or None
    if p is not None and p not in _TEACHER_PROVIDER_VALUES:
        return None
    return p


def get_studio_council_teacher_settings() -> dict[str, Any]:
    conn = get_connection()
    row = conn.execute(
        "SELECT value_json FROM studio_system_settings WHERE key = ?",
        (_STUDIO_COUNCIL_TEACHER_KEY,),
    ).fetchone()
    defaults = dict(_STUDIO_COUNCIL_TEACHER_DEFAULTS)
    defaults["updated_at"] = None
    if not row:
        return defaults
    raw = row["value_json"] if isinstance(row["value_json"], str) else "{}"
    try:
        d = json.loads(raw)
    except Exception:
        d = {}
    if not isinstance(d, dict):
        d = {}
    mode = str(d.get("teacher_mode") or defaults["teacher_mode"]).strip().lower()
    ver = str(d.get("teacher_prompt_version") or "council_teacher_v1").strip() or "council_teacher_v1"
    ov = d.get("teacher_prompt_overlay")
    overlay = str(ov).strip() if isinstance(ov, str) and ov.strip() else None
    out = dict(defaults)
    if "teacher_provider" in d and d.get("teacher_provider") is not None:
        tp = _normalize_attachment_provider(d.get("teacher_provider"))
        teacher_provider_eff = tp or defaults["teacher_provider"]
    else:
        teacher_provider_eff = defaults["teacher_provider"]
    if "teacher_model" in d and d.get("teacher_model") is not None:
        teacher_model_eff = str(d["teacher_model"]).strip() or defaults["teacher_model"]
    else:
        teacher_model_eff = defaults["teacher_model"]
    out.update(
        {
            "teacher_mode": mode if mode in _TEACHER_MODE_VALUES else "shadow",
            "teacher_provider": teacher_provider_eff,
            "teacher_model": teacher_model_eff,
            "teacher_prompt_version": ver,
            "teacher_prompt_overlay": overlay,
            "updated_at": d.get("updated_at"),
        }
    )
    for key in (
        "main_attachment_provider",
        "local_attachment_provider",
        "experimental_google_provider",
        "experimental_xai_provider",
    ):
        pv = _normalize_attachment_provider(d.get(key))
        out[key] = pv if pv is not None else defaults[key]
    for key in (
        "main_attachment_model",
        "local_attachment_model",
        "experimental_google_model",
        "experimental_xai_model",
    ):
        m = d.get(key)
        out[key] = str(m).strip() if m is not None and str(m).strip() else defaults[key]
    cm = d.get("capability_teacher_modes")
    if isinstance(cm, dict):
        cleaned: dict[str, str] = {}
        for cap, md in cm.items():
            c = str(cap or "").strip().lower()
            mo = str(md or "").strip().lower()
            if c and mo in _TEACHER_MODE_VALUES:
                cleaned[c] = mo
        out["capability_teacher_modes"] = cleaned
    else:
        out["capability_teacher_modes"] = {}
    return out


def upsert_studio_council_teacher_settings(
    *,
    teacher_mode: str,
    teacher_provider: str | None,
    teacher_model: str | None,
    teacher_prompt_version: str | None,
    teacher_prompt_overlay: str | None,
    main_attachment_provider: str | None = None,
    main_attachment_model: str | None = None,
    local_attachment_provider: str | None = None,
    local_attachment_model: str | None = None,
    experimental_google_provider: str | None = None,
    experimental_google_model: str | None = None,
    experimental_xai_provider: str | None = None,
    experimental_xai_model: str | None = None,
    capability_teacher_modes: dict[str, str] | None = None,
) -> dict[str, Any]:
    mode = (teacher_mode or "shadow").strip().lower()
    if mode not in _TEACHER_MODE_VALUES:
        raise ValueError("Invalid teacher_mode")
    pv = (teacher_provider or "").strip().lower() or None
    if pv is not None and pv not in _TEACHER_PROVIDER_VALUES:
        raise ValueError("Invalid teacher_provider")
    model = (teacher_model or "").strip() or None
    prompt_version = (teacher_prompt_version or "council_teacher_v1").strip() or "council_teacher_v1"
    overlay = (teacher_prompt_overlay or "").strip() or None
    now = _now()
    cur = get_studio_council_teacher_settings()
    payload = {
        "teacher_mode": mode,
        "teacher_provider": pv,
        "teacher_model": model,
        "teacher_prompt_version": prompt_version,
        "teacher_prompt_overlay": overlay,
        "main_attachment_provider": _normalize_attachment_provider(main_attachment_provider)
        if main_attachment_provider is not None
        else cur["main_attachment_provider"],
        "main_attachment_model": (str(main_attachment_model).strip() if main_attachment_model is not None else cur["main_attachment_model"]),
        "local_attachment_provider": _normalize_attachment_provider(local_attachment_provider)
        if local_attachment_provider is not None
        else cur["local_attachment_provider"],
        "local_attachment_model": (str(local_attachment_model).strip() if local_attachment_model is not None else cur["local_attachment_model"]),
        "experimental_google_provider": _normalize_attachment_provider(experimental_google_provider)
        if experimental_google_provider is not None
        else cur["experimental_google_provider"],
        "experimental_google_model": (
            str(experimental_google_model).strip() if experimental_google_model is not None else cur["experimental_google_model"]
        ),
        "experimental_xai_provider": _normalize_attachment_provider(experimental_xai_provider)
        if experimental_xai_provider is not None
        else cur["experimental_xai_provider"],
        "experimental_xai_model": (str(experimental_xai_model).strip() if experimental_xai_model is not None else cur["experimental_xai_model"]),
        "capability_teacher_modes": cur["capability_teacher_modes"],
        "updated_at": now,
    }
    if capability_teacher_modes is not None:
        if not isinstance(capability_teacher_modes, dict):
            raise ValueError("capability_teacher_modes must be an object")
        cleaned: dict[str, str] = {}
        for cap, md in capability_teacher_modes.items():
            c = str(cap or "").strip().lower()
            mo = str(md or "").strip().lower()
            if not c:
                continue
            if mo not in _TEACHER_MODE_VALUES:
                raise ValueError(f"Invalid teacher_mode for capability {c!r}")
            cleaned[c] = mo
        payload["capability_teacher_modes"] = cleaned
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO studio_system_settings (key, value_json, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at
        """,
        (_STUDIO_COUNCIL_TEACHER_KEY, json.dumps(payload, ensure_ascii=False), now),
    )
    conn.commit()
    return get_studio_council_teacher_settings()


def _decode_council_teacher_run_row(d: dict[str, Any]) -> None:
    """Mutates row dict from SQLite into API shape (JSON blobs + booleans)."""
    for k in (
        "native_artifact_json",
        "teacher_artifact_json",
        "native_run_debug_json",
        "teacher_run_debug_json",
        "comparison_json",
    ):
        raw = d.get(k)
        try:
            d[k.replace("_json", "")] = json.loads(raw) if isinstance(raw, str) and raw.strip() else {}
        except Exception:
            d[k.replace("_json", "")] = {}
        d.pop(k, None)
    trc_raw = d.pop("teacher_reason_codes_json", None)
    try:
        trc = json.loads(trc_raw) if isinstance(trc_raw, str) and trc_raw.strip() else []
    except Exception:
        trc = []
    d["teacher_reason_codes"] = trc if isinstance(trc, list) else []
    d["teacher_succeeded"] = bool(d.get("teacher_succeeded"))
    d["teacher_vetoed"] = bool(d.get("teacher_vetoed"))
    d["teacher_warning"] = bool(d.get("teacher_warning"))
    if d.get("teacher_enforcement_mode") is None:
        d["teacher_enforcement_mode"] = d.get("teacher_mode")


def append_council_teacher_run(row: dict[str, Any]) -> str:
    conn = get_connection()
    rid = M.new_id()
    now = _now()
    t_codes = row.get("teacher_reason_codes") or []
    if not isinstance(t_codes, list):
        t_codes = []
    conn.execute(
        """
        INSERT INTO council_teacher_runs (
          id, created_at, user_id, execution_scope, execution_principal_ref, capability_name,
          teacher_mode, final_selection_policy, prompt_version,
          native_provider, native_model, teacher_provider_requested, teacher_model_requested,
          teacher_provider_effective, teacher_model_effective, teacher_succeeded,
          native_text, teacher_text, native_artifact_json, teacher_artifact_json,
          native_run_debug_json, teacher_run_debug_json, comparison_json, error,
          teacher_enforcement_mode, teacher_vetoed, teacher_warning, teacher_final_source,
          teacher_reason_codes_json, teacher_notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            rid,
            now,
            row.get("user_id"),
            row.get("execution_scope"),
            row.get("execution_principal_ref"),
            str(row.get("capability_name") or "council"),
            str(row.get("teacher_mode") or "off"),
            row.get("final_selection_policy"),
            row.get("prompt_version"),
            row.get("native_provider"),
            row.get("native_model"),
            row.get("teacher_provider_requested"),
            row.get("teacher_model_requested"),
            row.get("teacher_provider_effective"),
            row.get("teacher_model_effective"),
            1 if row.get("teacher_succeeded") else 0,
            row.get("native_text"),
            row.get("teacher_text"),
            json.dumps(row.get("native_artifact") or {}, ensure_ascii=False, default=str),
            json.dumps(row.get("teacher_artifact") or {}, ensure_ascii=False, default=str),
            json.dumps(row.get("native_run_debug") or {}, ensure_ascii=False, default=str),
            json.dumps(row.get("teacher_run_debug") or {}, ensure_ascii=False, default=str),
            json.dumps(row.get("comparison") or {}, ensure_ascii=False, default=str),
            row.get("error"),
            row.get("teacher_enforcement_mode") or row.get("teacher_mode"),
            1 if row.get("teacher_vetoed") else 0,
            1 if row.get("teacher_warning") else 0,
            row.get("teacher_final_source"),
            json.dumps(t_codes, ensure_ascii=False),
            row.get("teacher_notes"),
        ),
    )
    conn.commit()
    return rid


def append_council_stream_run(row: dict[str, Any]) -> str:
    conn = get_connection()
    rid = M.new_id()
    now = _now()
    art = row.get("artifact")
    if art is None:
        art = {}
    if not isinstance(art, dict):
        art = {}
    conn.execute(
        """
        INSERT INTO council_stream_runs (id, created_at, user_id, integrity_run_id, artifact_json, full_text)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            rid,
            now,
            row.get("user_id"),
            row.get("integrity_run_id"),
            json.dumps(art, ensure_ascii=False, default=str),
            row.get("full_text"),
        ),
    )
    conn.commit()
    return rid


def get_council_stream_run_for_user(run_id: str, user_id: str) -> dict[str, Any] | None:
    """
    Lookup by primary key ``council_stream_runs.id``.

    ``execution_flow_reading`` rows with ``pointer_kind=council_stream_run`` must point at this
    id (the return value of ``append_council_stream_run``), **not** ``integrity_run_id``.
    When ``user_id`` is set on the row, it must match ``user_id`` (normalized strip).
    Rows with NULL ``user_id`` (legacy) are visible to any caller — prefer always persisting user_id.
    """
    rid = (run_id or "").strip()
    uid = (user_id or "").strip() or "anonymous"
    if not rid:
        return None
    conn = get_connection()
    r = conn.execute(
        "SELECT id, created_at, user_id, integrity_run_id FROM council_stream_runs WHERE id = ?",
        (rid,),
    ).fetchone()
    if r is None:
        return None
    d = dict(r)
    row_uid = (d.get("user_id") or "").strip()
    if row_uid and row_uid != uid:
        return None
    return d


def get_council_stream_artifact(integrity_run_id: str) -> dict[str, Any] | None:
    iid = (integrity_run_id or "").strip()
    if not iid:
        return None
    conn = get_connection()
    r = conn.execute(
        """
        SELECT id, created_at, user_id, integrity_run_id, artifact_json, full_text
        FROM council_stream_runs
        WHERE integrity_run_id = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (iid,),
    ).fetchone()
    if r is None:
        return None
    d = dict(r)
    raw = d.get("artifact_json")
    try:
        d["artifact"] = json.loads(raw) if isinstance(raw, str) and raw.strip() else {}
    except Exception:
        d["artifact"] = {}
    del d["artifact_json"]
    return d


def list_recent_council_stream_runs(user_id: str, limit: int = 5) -> list[dict[str, Any]]:
    uid = (user_id or "").strip()
    lim = max(1, min(int(limit), 200))
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT id, created_at, user_id, integrity_run_id, artifact_json, full_text
        FROM council_stream_runs
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (uid, lim),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        raw = d.get("artifact_json")
        try:
            d["artifact"] = json.loads(raw) if isinstance(raw, str) and raw.strip() else {}
        except Exception:
            d["artifact"] = {}
        del d["artifact_json"]
        out.append(d)
    return out


def _row_to_node_vitality(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    raw = d.pop("payload_json", None)
    if isinstance(raw, str) and raw.strip():
        try:
            d["payload"] = json.loads(raw)
        except Exception:
            d["payload"] = {}
    else:
        d["payload"] = {}
    return d


def upsert_node_vitality(
    user_id: str,
    entity_type: str,
    entity_id: str,
    scores: dict[str, Any],
) -> str:
    """Insert or update node_vitality for SubjectRef key; returns row id."""
    uid = (user_id or "").strip() or "anonymous"
    et = (entity_type or "").strip()
    eid = (entity_id or "").strip()
    if not et or not eid:
        raise ValueError("entity_type and entity_id are required")
    conn = get_connection()
    now = _now()
    cur = conn.execute(
        "SELECT id, water, soil, fruit, staleness_days, last_activity_at, last_assessed_at, "
        "triggered_by_event_id, rules_version, payload_json FROM node_vitality "
        "WHERE user_id = ? AND entity_type = ? AND entity_id = ?",
        (uid, et, eid),
    )
    existing = cur.fetchone()

    def _f(key: str, default: float | str | None) -> Any:
        if key not in scores:
            return default
        return scores[key]

    payload_out: str | None = None
    if "payload_json" in scores:
        pj = scores["payload_json"]
        if isinstance(pj, dict):
            payload_out = json.dumps(pj, ensure_ascii=False, default=str)
        elif isinstance(pj, str):
            payload_out = pj
    if existing:
        vid = existing["id"]
        w = float(scores["water"]) if "water" in scores else existing["water"]
        s = float(scores["soil"]) if "soil" in scores else existing["soil"]
        fr = float(scores["fruit"]) if "fruit" in scores else existing["fruit"]
        sd = float(scores["staleness_days"]) if "staleness_days" in scores else existing["staleness_days"]
        laa = scores.get("last_activity_at", existing["last_activity_at"])
        las = scores.get("last_assessed_at", existing["last_assessed_at"] or now)
        tev = scores.get("triggered_by_event_id", existing["triggered_by_event_id"])
        rv = scores.get("rules_version", existing["rules_version"] or "v1")
        pjson = payload_out if payload_out is not None else existing["payload_json"]
        conn.execute(
            """
            UPDATE node_vitality SET water=?, soil=?, fruit=?, staleness_days=?,
              last_activity_at=?, last_assessed_at=?, triggered_by_event_id=?, rules_version=?, payload_json=?
            WHERE id=?
            """,
            (w, s, fr, sd, laa, las, tev, rv, pjson, vid),
        )
        _commit_if_standalone(conn)
        return str(vid)

    vid = M.new_id()
    las = scores.get("last_assessed_at", now)
    conn.execute(
        """
        INSERT INTO node_vitality (
          id, user_id, entity_type, entity_id, water, soil, fruit, staleness_days,
          last_activity_at, last_assessed_at, triggered_by_event_id, rules_version, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            vid,
            uid,
            et,
            eid,
            float(_f("water", 0.0)),
            float(_f("soil", 0.0)),
            float(_f("fruit", 0.0)),
            float(_f("staleness_days", 0.0)),
            scores.get("last_activity_at"),
            las,
            scores.get("triggered_by_event_id"),
            str(scores.get("rules_version") or "v1"),
            payload_out,
        ),
    )
    _commit_if_standalone(conn)
    return vid


def get_node_vitality(user_id: str, entity_type: str, entity_id: str) -> dict[str, Any] | None:
    uid = (user_id or "").strip() or "anonymous"
    et = (entity_type or "").strip()
    eid = (entity_id or "").strip()
    conn = get_connection()
    r = conn.execute(
        "SELECT * FROM node_vitality WHERE user_id = ? AND entity_type = ? AND entity_id = ?",
        (uid, et, eid),
    ).fetchone()
    return _row_to_node_vitality(r) if r else None


def list_node_vitality_for_user(
    user_id: str, entity_type: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    uid = (user_id or "").strip() or "anonymous"
    lim = max(1, min(int(limit), 500))
    conn = get_connection()
    if entity_type and str(entity_type).strip():
        rows = conn.execute(
            """
            SELECT * FROM node_vitality WHERE user_id = ? AND entity_type = ?
            ORDER BY last_assessed_at DESC LIMIT ?
            """,
            (uid, str(entity_type).strip(), lim),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM node_vitality WHERE user_id = ?
            ORDER BY last_assessed_at DESC LIMIT ?
            """,
            (uid, lim),
        ).fetchall()
    return [_row_to_node_vitality(r) for r in rows]


def append_node_judgment(
    user_id: str,
    entity_type: str,
    entity_id: str,
    trunk: Any,
    refs: dict[str, Any] | None = None,
) -> str:
    """Persist JudgmentTrunk JSON + optional provenance refs; returns history row id."""
    from local_ai.judgment_substrate import JudgmentTrunk

    if not isinstance(trunk, JudgmentTrunk):
        raise TypeError("trunk must be a JudgmentTrunk")
    uid = (user_id or "").strip() or "anonymous"
    et = (entity_type or "").strip()
    eid = (entity_id or "").strip()
    if not et or not eid:
        raise ValueError("entity_type and entity_id are required")
    refs = refs or {}
    conn = get_connection()
    jid = M.new_id()
    now = _now()
    trunk_json = json.dumps(trunk.model_dump(mode="json"), ensure_ascii=False, default=str)
    conn.execute(
        """
        INSERT INTO node_judgment_history (
          id, user_id, entity_type, entity_id, created_at, verdict_kind, effect, state, mechanism_mode,
          observation_pointer, council_stream_run_id, decision_id, intake_judgment_id, trunk_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            jid,
            uid,
            et,
            eid,
            now,
            trunk.verdict.kind,
            trunk.effect,
            trunk.state,
            trunk.mechanism.mode,
            trunk.observation.pointer,
            refs.get("council_stream_run_id"),
            refs.get("decision_id"),
            refs.get("intake_judgment_id"),
            trunk_json,
        ),
    )
    _commit_if_standalone(conn)
    return jid


def append_resonance_rating(
    user_id: str,
    entity_type: str,
    entity_id: str,
    score: float,
    response_id: str,
    seat_id: str | None,
    context_kind: str,
    subject_perspective_id: str | None = None,
) -> str:
    """
    Store a resonance rating as a node_judgment_history entry.
    verdict_kind='resonance_rating', effect='persist_decision', state='applied'.
    Returns the judgment id.
    """
    from local_ai.judgment_substrate import (
        JudgmentMechanism,
        JudgmentObservation,
        JudgmentTrunk,
        JudgmentVerdict,
        SubjectRef,
    )

    sc = float(score)
    if sc < 0.0 or sc > 1.0:
        raise ValueError("score must be between 0.0 and 1.0")
    rid = (response_id or "").strip()
    if not rid:
        raise ValueError("response_id is required")
    ck = (context_kind or "").strip()
    if not ck:
        raise ValueError("context_kind is required")
    et = (entity_type or "").strip()
    eid = (entity_id or "").strip()
    if not et or not eid:
        raise ValueError("entity_type and entity_id are required")
    payload: dict[str, Any] = {
        "score": sc,
        "response_id": rid,
        "seat_id": seat_id,
        "context_kind": ck,
        "subject_perspective_id": subject_perspective_id,
    }
    trunk = JudgmentTrunk(
        subject=SubjectRef(entity_type=et, entity_id=eid),
        observation=JudgmentObservation(pointer=rid, context={"resonance_rating": True}),
        verdict=JudgmentVerdict(kind="resonance_rating", payload=payload),
        mechanism=JudgmentMechanism(mode="human_override"),
        effect="persist_decision",
        state="applied",
    )
    return append_node_judgment(user_id, et, eid, trunk, refs={})


def _is_challenge_accountability_seat(seat_id: str) -> bool:
    s = (seat_id or "").strip().lower()
    # "governance" kept for historical judgments; the Heart inherits that seat's DNA.
    return s in ("governance", "mediator") or s == "skeptic" or "skeptic" in s


def _session_day(created_at: str | None) -> str:
    ca = (created_at or "").strip()
    return ca[:10] if len(ca) >= 10 else (ca or "")


def _derive_escalation_signal(records: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Map resonance rows to Core Profile interaction ladder (1–5).
    Each record: score, seat_id, context_kind, session_day (YYYY-MM-DD).
    """
    n = len(records)
    if n == 0:
        return {
            "current_level": 1,
            "confidence": 0.0,
            "basis": "No resonance ratings yet.",
            "recommended_approach": "exploration",
        }

    scores = [float(r["score"]) for r in records]
    avg_all = sum(scores) / n
    sessions: set[str] = set()
    for r in records:
        d = _session_day(r.get("created_at")) or _session_day(r.get("session_day"))
        if d:
            sessions.add(d)
    n_sessions = len(sessions)

    def _level2_match() -> bool:
        if n < 5 or n_sessions < 2:
            return False
        by_seat_mid: dict[str, int] = {}
        for r in records:
            s = float(r["score"])
            sk = (r.get("seat_id") or "").strip() or "__none__"
            if 0.4 <= s <= 0.7:
                by_seat_mid[sk] = by_seat_mid.get(sk, 0) + 1
        return any(c >= 3 for c in by_seat_mid.values())

    def _level3_match() -> bool:
        if n < 10:
            return False
        zen = [float(r["score"]) for r in records if (r.get("context_kind") or "") == "zenaf_training"]
        cou = [float(r["score"]) for r in records if (r.get("context_kind") or "") == "council_seat"]
        if len(zen) < 3 or len(cou) < 3:
            return False
        az = sum(zen) / len(zen)
        ac = sum(cou) / len(cou)
        return az >= 0.65 and ac < az - 0.12

    def _level4_metrics() -> tuple[bool, float, float]:
        challenge: list[float] = []
        baseline: list[float] = []
        for r in records:
            s = float(r["score"])
            ck = (r.get("context_kind") or "") == "council_seat"
            ch = _is_challenge_accountability_seat(str(r.get("seat_id") or ""))
            if ck and ch:
                challenge.append(s)
            else:
                baseline.append(s)
        if len(challenge) < 2 or len(baseline) < 2:
            return False, 0.0, 0.0
        bc = sum(baseline) / len(baseline)
        cc = sum(challenge) / len(challenge)
        return (bc - cc) > 0.2, bc, cc

    l4_ok, avg_base, avg_ch = _level4_metrics()
    gap = avg_base - avg_ch if l4_ok else 0.0

    def _level5_confidence() -> float:
        if not l4_ok or n < 20 or n_sessions < 3:
            return 0.0
        return min(
            0.95,
            0.52 + min(0.28, gap * 1.15) + min(0.12, (n - 20) / 120) + min(0.1, (n_sessions - 3) * 0.03),
        )

    level = 1
    conf = 0.45
    basis = "No strong split or avoidance pattern; stay exploratory."

    if l4_ok and n >= 20 and n_sessions >= 3:
        c5 = _level5_confidence()
        if c5 > 0.75:
            level = 5
            conf = c5
            basis = (
                f"Sustained lower ratings on governance/skeptic council seats vs other contexts "
                f"(gap {gap:.2f}; {n} ratings, {n_sessions} sessions)."
            )
        else:
            level = 4
            conf = min(0.88, 0.52 + min(0.22, gap) + min(0.14, n / 100))
            basis = (
                f"Clear drop vs baseline on challenge/accountability council seats (governance/skeptic); "
                f"mean gap {gap:.2f}."
            )
    elif l4_ok:
        level = 4
        conf = min(0.85, 0.5 + min(0.25, gap) + min(0.12, n / 90))
        basis = (
            f"Lower resonance on governance/skeptic council seats than elsewhere (mean gap {gap:.2f})."
        )
    elif _level3_match():
        level = 3
        zen = [float(r["score"]) for r in records if (r.get("context_kind") or "") == "zenaf_training"]
        cou = [float(r["score"]) for r in records if (r.get("context_kind") or "") == "council_seat"]
        az = sum(zen) / len(zen)
        ac = sum(cou) / len(cou)
        conf = min(0.88, 0.52 + min(0.22, (az - ac) * 1.8) + min(0.14, n / 75))
        basis = (
            f"Higher ratings in zenaf_training ({az:.2f}) than council_seat responses ({ac:.2f}); "
            "may favor reflection over direct challenge."
        )
    elif _level2_match():
        level = 2
        conf = min(0.84, 0.48 + min(0.2, n / 55) + min(0.16, n_sessions / 20))
        basis = (
            "Several sessions with repeated mid-range scores on the same seat; pattern is visible enough to name."
        )
    else:
        if n < 5:
            conf = min(0.42, 0.12 + n * 0.07)
            basis = "Sparse ratings; remain exploratory."
        elif avg_all > 0.7:
            conf = min(0.82, 0.56 + min(0.22, n / 90))
            basis = f"Strong average resonance ({avg_all:.2f}); user appears engaged — keep a light, curious stance."
        else:
            conf = min(0.68, 0.4 + min(0.22, n / 85))
            basis = "Insufficient signal for loop or avoidance; default exploration."

    approach_names = ("exploration", "recognition", "loop", "avoidance", "confrontation")
    return {
        "current_level": level,
        "confidence": float(conf),
        "basis": basis,
        "recommended_approach": approach_names[level - 1] if 1 <= level <= 5 else "exploration",
    }


def get_resonance_pattern(
    user_id: str,
    context_kind: str | None = None,
    seat_id: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """
    Returns aggregated resonance patterns from node_judgment_history (verdict_kind='resonance_rating').
    """
    uid = (user_id or "").strip() or "anonymous"
    lim = max(1, min(int(limit), 500))
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT trunk_json, created_at FROM node_judgment_history
        WHERE user_id = ? AND verdict_kind = ?
        ORDER BY created_at DESC LIMIT ?
        """,
        (uid, "resonance_rating", lim),
    ).fetchall()

    scores: list[float] = []
    by_seat: dict[str, list[float]] = {}
    by_ctx: dict[str, list[float]] = {}
    high = 0
    low = 0
    ck_f = context_kind.strip() if isinstance(context_kind, str) and context_kind.strip() else None
    seat_f = seat_id.strip() if isinstance(seat_id, str) and seat_id.strip() else None
    esc_records: list[dict[str, Any]] = []

    for r in rows:
        raw = r["trunk_json"]
        created_s = str(r["created_at"]) if r["created_at"] is not None else ""
        if not isinstance(raw, str) or not raw.strip():
            continue
        try:
            trunk = json.loads(raw)
        except Exception:
            continue
        ver = trunk.get("verdict") if isinstance(trunk, dict) else None
        pl = ver.get("payload") if isinstance(ver, dict) else None
        if not isinstance(pl, dict):
            continue
        try:
            s = float(pl.get("score"))
        except (TypeError, ValueError):
            continue
        sk_raw = pl.get("seat_id")
        sk = sk_raw if isinstance(sk_raw, str) else (str(sk_raw) if sk_raw is not None else "")
        ck_row = pl.get("context_kind")
        ck_s = ck_row if isinstance(ck_row, str) else (str(ck_row) if ck_row is not None else "")
        if ck_f is not None and ck_s != ck_f:
            continue
        if seat_f is not None and sk != seat_f:
            continue
        scores.append(s)
        if s >= 0.75:
            high += 1
        if s <= 0.25:
            low += 1
        seat_key = sk if sk else "__none__"
        by_seat.setdefault(seat_key, []).append(s)
        ctx_key = ck_s if ck_s else "__none__"
        by_ctx.setdefault(ctx_key, []).append(s)
        esc_records.append(
            {
                "score": s,
                "seat_id": sk,
                "context_kind": ck_s,
                "session_day": _session_day(created_s),
                "created_at": created_s,
            }
        )

    def _avg(vals: list[float]) -> float:
        return sum(vals) / len(vals) if vals else 0.0

    escalation_signal = _derive_escalation_signal(esc_records)

    return {
        "average_score": _avg(scores) if scores else None,
        "average_by_seat_id": {k: _avg(v) for k, v in by_seat.items()},
        "average_by_context_kind": {k: _avg(v) for k, v in by_ctx.items()},
        "high_resonance_count": high,
        "low_resonance_count": low,
        "total_ratings": len(scores),
        "escalation_signal": escalation_signal,
    }


def list_node_judgments(
    user_id: str, entity_type: str, entity_id: str, limit: int = 20
) -> list[dict[str, Any]]:
    uid = (user_id or "").strip() or "anonymous"
    et = (entity_type or "").strip()
    eid = (entity_id or "").strip()
    lim = max(1, min(int(limit), 200))
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT * FROM node_judgment_history
        WHERE user_id = ? AND entity_type = ? AND entity_id = ?
        ORDER BY created_at DESC LIMIT ?
        """,
        (uid, et, eid, lim),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        raw = d.get("trunk_json")
        try:
            d["trunk"] = json.loads(raw) if isinstance(raw, str) and raw.strip() else {}
        except Exception:
            d["trunk"] = {}
        del d["trunk_json"]
        out.append(d)
    return out


def list_node_judgments_chronological(
    user_id: str, entity_type: str, entity_id: str, limit: int = 1000
) -> list[dict[str, Any]]:
    """Oldest-first judgments for arc/heuristic scans (contrast list_node_judgments DESC)."""
    uid = (user_id or "").strip() or "anonymous"
    et = (entity_type or "").strip()
    eid = (entity_id or "").strip()
    lim = max(1, min(int(limit), 5000))
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT * FROM node_judgment_history
        WHERE user_id = ? AND entity_type = ? AND entity_id = ?
        ORDER BY created_at ASC LIMIT ?
        """,
        (uid, et, eid, lim),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        raw = d.get("trunk_json")
        try:
            d["trunk"] = json.loads(raw) if isinstance(raw, str) and raw.strip() else {}
        except Exception:
            d["trunk"] = {}
        del d["trunk_json"]
        out.append(d)
    return out


def try_insert_arc_detection_candidate(
    *,
    user_id: str,
    source_entity_type: str,
    source_entity_id: str,
    heuristic_version: str,
    t_avoid_reading_id: str,
    t_eng_reading_id: str,
    t_complete_at: str,
    detector_confidence: float,
    notes_json: str,
) -> str | None:
    """
    Insert status=proposed. Returns new row id, or None if UNIQUE conflict (same user/entity/heuristic)
    or DB error.
    """
    from local_ai.vision_execution import models as M

    uid = (user_id or "").strip()
    if not uid:
        return None
    et = (source_entity_type or "").strip().lower()
    eid = (source_entity_id or "").strip()
    hv = (heuristic_version or "").strip()
    if not et or not eid or not hv:
        return None
    cid = M.new_id()
    now = _now()
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO arc_detection_candidates (
              id, user_id, source_entity_type, source_entity_id, heuristic_version,
              t_avoid_reading_id, t_eng_reading_id, t_complete_at,
              detector_confidence, status, notes_json, reviewed_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'proposed', ?, NULL, ?)
            """,
            (
                cid,
                uid,
                et,
                eid,
                hv,
                t_avoid_reading_id,
                t_eng_reading_id,
                t_complete_at,
                float(detector_confidence),
                notes_json,
                now,
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        return None
    except Exception:
        conn.rollback()
        return None
    return cid


def get_node_judgment_summary(user_id: str, entity_type: str, entity_id: str) -> dict[str, Any]:
    uid = (user_id or "").strip() or "anonymous"
    et = (entity_type or "").strip()
    eid = (entity_id or "").strip()
    conn = get_connection()
    cnt_row = conn.execute(
        """
        SELECT COUNT(*) FROM node_judgment_history
        WHERE user_id = ? AND entity_type = ? AND entity_id = ?
        """,
        (uid, et, eid),
    ).fetchone()
    count = int(cnt_row[0]) if cnt_row else 0
    latest = conn.execute(
        """
        SELECT state, verdict_kind, created_at FROM node_judgment_history
        WHERE user_id = ? AND entity_type = ? AND entity_id = ?
        ORDER BY created_at DESC LIMIT 1
        """,
        (uid, et, eid),
    ).fetchone()
    if latest is None:
        return {
            "count": count,
            "latest_state": None,
            "latest_verdict_kind": None,
            "latest_created_at": None,
        }
    return {
        "count": count,
        "latest_state": latest["state"],
        "latest_verdict_kind": latest["verdict_kind"],
        "latest_created_at": latest["created_at"],
    }


def _propagate_vitality_upward(
    user_id: str,
    entity_type: str,
    entity_id: str,
    triggered_by_event_id: str,
    now_iso: str,
    depth: int = 0,
) -> None:
    """
    Recompute vitality for a parent entity after a child changed.
    Max depth 2: task→project→initiative. Never propagates past initiative.
    Fire and forget — errors logged, never raised.
    """
    if depth > 2:
        return
    try:
        from local_ai.vision_execution.node_vitality_scores import (
            RULES_VERSION,
            compute_vitality_scores,
            staleness_days_for_row,
        )

        row: dict[str, Any] | None = None
        tasks: list[dict[str, Any]] | None = None
        et = entity_type.lower()

        if et == "project":
            row = get_project(entity_id, user_id)
            tasks = list_tasks(user_id=user_id, project_id=entity_id)
        elif et == "initiative":
            row = get_initiative(entity_id, user_id)
            tasks = list_tasks(user_id=user_id, initiative_id=entity_id)

        if not row:
            return

        scores = compute_vitality_scores(et, row, tasks)
        staleness = staleness_days_for_row(row)

        upsert_node_vitality(
            user_id,
            entity_type,
            entity_id,
            {
                **scores,
                "staleness_days": staleness,
                "last_activity_at": now_iso,
                "last_assessed_at": now_iso,
                "triggered_by_event_id": triggered_by_event_id,
                "rules_version": RULES_VERSION,
                "payload_json": {
                    "vitality_source": "upward_propagation",
                    "vitality_rules": RULES_VERSION,
                    "propagation_depth": depth,
                },
            },
        )

        if et == "project" and row.get("initiative_id"):
            _propagate_vitality_upward(
                user_id=user_id,
                entity_type="initiative",
                entity_id=row["initiative_id"],
                triggered_by_event_id=triggered_by_event_id,
                now_iso=now_iso,
                depth=depth + 1,
            )

    except Exception:
        _logger.warning(
            "upward vitality propagation failed for %s/%s depth=%d",
            entity_type,
            entity_id,
            depth,
            exc_info=True,
        )


def _maybe_touch_node_vitality_from_activity(
    user_id: str,
    entity_type: str,
    entity_id: str,
    event_id: str,
    now_iso: str,
) -> None:
    """Called after ActivityEvent fires. Fetches row, computes scores, upserts vitality."""
    try:
        from local_ai.vision_execution.node_vitality_scores import (
            RULES_VERSION,
            compute_vitality_scores,
        )

        row: dict[str, Any] | None = None
        tasks: list[dict[str, Any]] | None = None
        et = entity_type.lower()

        if et == "idea":
            row = get_idea(entity_id, user_id)
        elif et == "initiative":
            row = get_initiative(entity_id, user_id)
            tasks = list_tasks(user_id=user_id, initiative_id=entity_id)
        elif et == "project":
            row = get_project(entity_id, user_id)
            tasks = list_tasks(user_id=user_id, project_id=entity_id)
        elif et == "task":
            row = get_task(entity_id, user_id)

        if not row:
            return

        scores = compute_vitality_scores(et, row, tasks)

        upsert_node_vitality(
            user_id,
            entity_type,
            entity_id,
            {
                **scores,
                "last_activity_at": now_iso,
                "last_assessed_at": now_iso,
                "staleness_days": 0.0,
                "triggered_by_event_id": event_id,
                "rules_version": RULES_VERSION,
            },
        )

        if et == "task" and row.get("project_id"):
            _propagate_vitality_upward(
                user_id=user_id,
                entity_type="project",
                entity_id=row["project_id"],
                triggered_by_event_id=event_id,
                now_iso=now_iso,
                depth=1,
            )
        elif et == "project" and row.get("initiative_id"):
            _propagate_vitality_upward(
                user_id=user_id,
                entity_type="initiative",
                entity_id=row["initiative_id"],
                triggered_by_event_id=event_id,
                now_iso=now_iso,
                depth=1,
            )
    except Exception:
        _logger.warning(
            "node vitality score update failed for %s/%s",
            entity_type,
            entity_id,
            exc_info=True,
        )


def list_recent_council_teacher_runs(limit: int = 20) -> list[dict[str, Any]]:
    lim = max(1, min(int(limit), 200))
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT id, created_at, user_id, execution_scope, execution_principal_ref, capability_name,
               teacher_mode, final_selection_policy, prompt_version,
               native_provider, native_model, teacher_provider_requested, teacher_model_requested,
               teacher_provider_effective, teacher_model_effective, teacher_succeeded,
               native_text, teacher_text, native_artifact_json, teacher_artifact_json,
               native_run_debug_json, teacher_run_debug_json, comparison_json, error,
               teacher_enforcement_mode, teacher_vetoed, teacher_warning, teacher_final_source,
               teacher_reason_codes_json, teacher_notes
        FROM council_teacher_runs
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (lim,),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        _decode_council_teacher_run_row(d)
        out.append(d)
    return out


def get_council_teacher_run(run_id: str) -> dict[str, Any] | None:
    rid = (run_id or "").strip()
    if not rid:
        return None
    conn = get_connection()
    r = conn.execute(
        """
        SELECT id, created_at, user_id, execution_scope, execution_principal_ref, capability_name,
               teacher_mode, final_selection_policy, prompt_version,
               native_provider, native_model, teacher_provider_requested, teacher_model_requested,
               teacher_provider_effective, teacher_model_effective, teacher_succeeded,
               native_text, teacher_text, native_artifact_json, teacher_artifact_json,
               native_run_debug_json, teacher_run_debug_json, comparison_json, error,
               teacher_enforcement_mode, teacher_vetoed, teacher_warning, teacher_final_source,
               teacher_reason_codes_json, teacher_notes
        FROM council_teacher_runs
        WHERE id = ?
        """,
        (rid,),
    ).fetchone()
    if r is None:
        return None
    d = dict(r)
    _decode_council_teacher_run_row(d)
    return d


# --- Core profiles ---

def list_core_profiles(user_id: str) -> list[dict[str, Any]]:
    conn = get_connection()
    cur = conn.execute(
        "SELECT id, name, core_definition, current_goals, growth_focus_12_months, economic_engine, "
        "non_negotiables, strategic_filter, current_constraints, capacity_limit, kill_philosophy, "
        "strength_positioning, raw_notes, is_primary, created_at, updated_at FROM core_profiles WHERE user_id = ? "
        "ORDER BY is_primary DESC, updated_at DESC",
        (user_id,),
    )
    return [M.row_to_core_profile(tuple(r)) for r in cur.fetchall()]


def get_core_profile(profile_id: str, user_id: str) -> dict[str, Any] | None:
    conn = get_connection()
    cur = conn.execute(
        "SELECT id, name, core_definition, current_goals, growth_focus_12_months, economic_engine, "
        "non_negotiables, strategic_filter, current_constraints, capacity_limit, kill_philosophy, "
        "strength_positioning, raw_notes, is_primary, created_at, updated_at FROM core_profiles WHERE id = ? AND user_id = ?",
        (profile_id, user_id),
    )
    row = cur.fetchone()
    return M.row_to_core_profile(tuple(row)) if row else None


def create_core_profile(data: M.CoreProfileCreate, user_id: str) -> dict[str, Any]:
    conn = get_connection()
    pid = M.new_id()
    now = _now()
    prior_n = conn.execute(
        "SELECT COUNT(*) FROM core_profiles WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    is_primary_val = 1 if int(prior_n or 0) == 0 else 0
    conn.execute(
        """INSERT INTO core_profiles (
          id, user_id, name, core_definition, current_goals, growth_focus_12_months, economic_engine,
          non_negotiables, strategic_filter, current_constraints, capacity_limit, kill_philosophy,
          strength_positioning, raw_notes, is_primary, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            pid, user_id, data.name, data.core_definition, data.current_goals, data.growth_focus_12_months,
            data.economic_engine, data.non_negotiables, data.strategic_filter, data.current_constraints,
            data.capacity_limit, data.kill_philosophy, data.strength_positioning,
            data.raw_notes, is_primary_val, now, now,
        ),
    )
    conn.commit()
    return get_core_profile(pid, user_id) or {}


def update_core_profile(profile_id: str, data: M.CoreProfileUpdate, user_id: str) -> dict[str, Any] | None:
    if get_core_profile(profile_id, user_id) is None:
        return None
    conn = get_connection()
    updates: list[str] = []
    args: list[Any] = []
    for k, v in data.model_dump(exclude_unset=True).items():
        if v is not None:
            updates.append(f"{k} = ?")
            args.append(v)
    if not updates:
        return get_core_profile(profile_id, user_id)
    updates.append("updated_at = ?")
    args.append(_now())
    args.append(profile_id)
    conn.execute(f"UPDATE core_profiles SET {', '.join(updates)} WHERE id = ? AND user_id = ?", args + [user_id])
    conn.commit()
    return get_core_profile(profile_id, user_id)


def set_core_profile_primary(profile_id: str, user_id: str) -> dict[str, Any] | None:
    if get_core_profile(profile_id, user_id) is None:
        return None
    conn = get_connection()
    now = _now()
    conn.execute("UPDATE core_profiles SET is_primary = 0, updated_at = ? WHERE user_id = ?", (now, user_id))
    conn.execute(
        "UPDATE core_profiles SET is_primary = 1, updated_at = ? WHERE id = ? AND user_id = ?",
        (now, profile_id, user_id),
    )
    conn.commit()
    return get_core_profile(profile_id, user_id)


# --- Ideas ---

def _ensure_owned_reference(
    conn: sqlite3.Connection,
    *,
    table: str,
    ref_id: str | None,
    user_id: str,
    field_name: str,
) -> None:
    if not ref_id:
        return
    row = conn.execute(
        f"SELECT 1 FROM {table} WHERE id = ? AND user_id = ?",
        (ref_id, user_id),
    ).fetchone()
    if row is None:
        raise ValueError(f"{field_name} is invalid or not owned by the current user")


def list_ideas(user_id: str) -> list[dict[str, Any]]:
    conn = get_connection()
    cur = conn.execute(
        "SELECT i.id, i.title, i.summary, i.description, i.status, i.tags, i.created_by, i.desired_outcome, "
        "i.linked_people, i.linked_assets, i.linked_ideas, i.created_at, i.updated_at, i.notes, "
        "COALESCE(cp.total, 0) AS checklist_total, COALESCE(cp.done, 0) AS checklist_done "
        "FROM ideas i LEFT JOIN ("
        "SELECT idea_id, COUNT(*) AS total, SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done "
        "FROM checklist_items WHERE user_id = ? AND superseded = 0 GROUP BY idea_id"
        ") cp ON cp.idea_id = i.id "
        "WHERE i.user_id = ? ORDER BY i.updated_at DESC",
        (user_id, user_id),
    )
    return [M.row_to_idea(tuple(r)) for r in cur.fetchall()]


def get_idea(idea_id: str, user_id: str) -> dict[str, Any] | None:
    conn = get_connection()
    cur = conn.execute(
        "SELECT i.id, i.title, i.summary, i.description, i.status, i.tags, i.created_by, i.desired_outcome, "
        "i.linked_people, i.linked_assets, i.linked_ideas, i.created_at, i.updated_at, i.notes, "
        "COALESCE(cp.total, 0) AS checklist_total, COALESCE(cp.done, 0) AS checklist_done "
        "FROM ideas i LEFT JOIN ("
        "SELECT idea_id, COUNT(*) AS total, SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done "
        "FROM checklist_items WHERE user_id = ? AND superseded = 0 GROUP BY idea_id"
        ") cp ON cp.idea_id = i.id "
        "WHERE i.id = ? AND i.user_id = ?",
        (user_id, idea_id, user_id),
    )
    row = cur.fetchone()
    return M.row_to_idea(tuple(row)) if row else None


def _insert_idea(
    conn: sqlite3.Connection,
    data: M.IdeaCreate,
    user_id: str,
    *,
    iid: str | None = None,
) -> str:
    """Validate + INSERT one idea row. No commit, no read-back, no log.

    Shared by create_idea and approve_upload_outcome so the approve
    path reuses the exact write path instead of duplicating
    validation or SQL (the _insert_task precedent). Callers commit
    (or roll back) and do read-back + logging.
    """
    iid = iid or M.new_id()
    now = _now()
    conn.execute(
        """INSERT INTO ideas (
          id, user_id, title, summary, description, status, tags, created_by, desired_outcome,
          linked_people, linked_assets, linked_ideas, created_at, updated_at, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            iid, user_id, data.title, data.summary, data.description, data.status, M._json_dumps_list(data.tags),
            data.created_by, data.desired_outcome, M._json_dumps_list(data.linked_people),
            M._json_dumps_list(data.linked_assets), M._json_dumps_list(data.linked_ideas), now, now,
            data.notes or "",
        ),
    )
    return iid


def create_idea(data: M.IdeaCreate, user_id: str) -> dict[str, Any]:
    conn = get_connection()
    iid = M.new_id()
    with ve_write_transaction(conn, purpose="create_idea"):
        _guard_idea_write(conn, iid, user_id, target_id=iid, target_kind="idea")
        _insert_idea(conn, data, user_id, iid=iid)
        _commit_if_owner(conn)
    out = get_idea(iid, user_id) or {}
    _log_ve_entity_activity(
        type=ActivityType.IDEA_CREATED.value,
        entity_type=ActivityEntityType.IDEA.value,
        entity_id=iid,
        user_id=user_id,
        related_entity_id=None,
        detail=f"title={(data.title or '')[:120]!r}",
    )
    return out


def update_idea(idea_id: str, data: M.IdeaUpdate, user_id: str) -> dict[str, Any] | None:
    if get_idea(idea_id, user_id) is None:
        return None
    conn = get_connection()
    updates: list[str] = []
    args: list[Any] = []
    patch_keys = list(data.model_dump(exclude_unset=True).keys())
    for k, v in data.model_dump(exclude_unset=True).items():
        if v is not None:
            if k in ("tags", "linked_people", "linked_assets", "linked_ideas"):
                updates.append(f"{k} = ?")
                args.append(M._json_dumps_list(v))
            else:
                updates.append(f"{k} = ?")
                args.append(v)
    if not updates:
        return get_idea(idea_id, user_id)
    updates.append("updated_at = ?")
    args.append(_now())
    args.append(idea_id)
    with ve_write_transaction(conn, purpose="update_idea"):
        _guard_idea_write(conn, idea_id, user_id, target_id=idea_id, target_kind="idea")
        conn.execute(f"UPDATE ideas SET {', '.join(updates)} WHERE id = ? AND user_id = ?", args + [user_id])
        _commit_if_owner(conn)
    out = get_idea(idea_id, user_id)
    _log_ve_entity_activity(
        type=ActivityType.IDEA_UPDATED.value,
        entity_type=ActivityEntityType.IDEA.value,
        entity_id=idea_id,
        user_id=user_id,
        related_entity_id=None,
        detail=f"fields={','.join(patch_keys)[:200]}",
    )
    return out


def delete_idea(idea_id: str, user_id: str) -> bool:
    if get_idea(idea_id, user_id) is None:
        return False
    conn = get_connection()
    with ve_write_transaction(conn, purpose="delete_idea"):
        _guard_idea_write(conn, idea_id, user_id, target_id=idea_id, target_kind="idea")
        conn.execute(
            "UPDATE initiatives SET source_idea_id = NULL WHERE source_idea_id = ? AND user_id = ?",
            (idea_id, user_id),
        )
        conn.execute("DELETE FROM ideas WHERE id = ? AND user_id = ?", (idea_id, user_id))
        _commit_if_owner(conn)
    _log_ve_entity_activity(
        type=ActivityType.IDEA_DELETED.value,
        entity_type=ActivityEntityType.IDEA.value,
        entity_id=idea_id,
        user_id=user_id,
        related_entity_id=None,
        detail="deleted",
    )
    return True


# --- Idea checklists ---
# Nested hierarchical checklists, defined by conversation: each idea's own
# definition of "practical." On graduation the checklist unfolds into the
# work breakdown and is kept as provenance, marked superseded.

CHECKLIST_STATUSES = ("open", "done")


def _checklist_row_to_dict(row) -> dict[str, Any]:
    return {
        "id": row[0],
        "idea_id": row[1],
        "parent_id": row[2],
        "title": row[3],
        "status": row[4],
        "position": row[5],
        "superseded": bool(row[6]),
        "person_id": row[7] if len(row) > 9 else None,
        "asset_id": row[8] if len(row) > 9 else None,
        "created_at": row[9] if len(row) > 9 else row[7],
        "updated_at": row[10] if len(row) > 9 else row[8],
    }


_CHECKLIST_COLS = (
    "id, idea_id, parent_id, title, status, position, superseded, person_id, asset_id, created_at, updated_at"
)


def _get_checklist_item_any(item_id: str, user_id: str) -> dict[str, Any] | None:
    """Fetch a checklist item only if its idea belongs to the user."""
    conn = get_connection()
    cur = conn.execute(
        f"SELECT {_CHECKLIST_COLS} FROM checklist_items "
        "WHERE id = ? AND user_id = ?",
        (item_id, user_id),
    )
    row = cur.fetchone()
    return _checklist_row_to_dict(row) if row else None


def create_checklist_item(
    user_id: str,
    idea_id: str,
    title: str,
    parent_id: str | None = None,
    position: int = 0,
    status: str = "open",
    person_id: str | None = None,
    asset_id: str | None = None,
) -> dict[str, Any]:
    if get_idea(idea_id, user_id) is None:
        raise ValueError("Idea not found")
    if status not in CHECKLIST_STATUSES:
        raise ValueError(f"unknown checklist status: {status!r}")
    if parent_id is not None:
        parent = _get_checklist_item_any(parent_id, user_id)
        if parent is None or parent["idea_id"] != idea_id:
            raise ValueError("parent item not found on this idea")
    if person_id is not None and get_person(person_id) is None:
        raise ValueError("person not found")
    if asset_id is not None and get_asset(asset_id) is None:
        raise ValueError("asset not found")
    conn = get_connection()
    iid = M.new_id()
    now = _now()
    with ve_write_transaction(conn, purpose="create_checklist_item"):
        _guard_idea_write(conn, idea_id, user_id, target_id=iid, target_kind="checklist_item")
        conn.execute(
            "INSERT INTO checklist_items (id, user_id, idea_id, parent_id, title, status, "
            "position, superseded, person_id, asset_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)",
            (iid, user_id, idea_id, parent_id, title, status, position, person_id, asset_id, now, now),
        )
        _commit_if_owner(conn)
    return _get_checklist_item_any(iid, user_id) or {}


def list_checklist_items(
    idea_id: str, user_id: str, include_superseded: bool = False
) -> list[dict[str, Any]]:
    if get_idea(idea_id, user_id) is None:
        raise ValueError("Idea not found")
    conn = get_connection()
    q = (
        f"SELECT {_CHECKLIST_COLS} FROM checklist_items "
        "WHERE idea_id = ? AND user_id = ?"
    )
    if not include_superseded:
        q += " AND superseded = 0"
    q += " ORDER BY position ASC, created_at ASC"
    cur = conn.execute(q, (idea_id, user_id))
    items = [_checklist_row_to_dict(r) for r in cur.fetchall()]
    # Attach dependency edges (item_id -> [depends_on ids]).
    dep_cur = conn.execute(
        "SELECT d.item_id, d.depends_on_item_id FROM checklist_item_dependencies d "
        "JOIN checklist_items i ON i.id = d.item_id "
        "WHERE i.idea_id = ? AND i.user_id = ?",
        (idea_id, user_id),
    )
    deps: dict[str, list[str]] = {}
    for item_id, depends_on in dep_cur.fetchall():
        deps.setdefault(item_id, []).append(depends_on)
    for it in items:
        it["depends_on"] = deps.get(it["id"], [])
    return items


def list_all_checklist_items(user_id: str) -> list[dict[str, Any]]:
    """All checklist items for a user, any idea, including superseded rows.

    Read-only helper for the unified-node projection (Slice A): reading
    per idea would silently miss items whose idea was removed
    (delete_idea leaves checklist items in place). Same dicts as
    list_checklist_items, with dependency edges attached.
    """
    conn = get_connection()
    cur = conn.execute(
        f"SELECT {_CHECKLIST_COLS} FROM checklist_items "
        "WHERE user_id = ? ORDER BY idea_id ASC, position ASC, created_at ASC",
        (user_id,),
    )
    items = [_checklist_row_to_dict(r) for r in cur.fetchall()]
    dep_cur = conn.execute(
        "SELECT d.item_id, d.depends_on_item_id FROM checklist_item_dependencies d "
        "JOIN checklist_items i ON i.id = d.item_id "
        "WHERE i.user_id = ?",
        (user_id,),
    )
    deps: dict[str, list[str]] = {}
    for item_id, depends_on in dep_cur.fetchall():
        deps.setdefault(item_id, []).append(depends_on)
    for it in items:
        it["depends_on"] = deps.get(it["id"], [])
    return items


def get_checklist_item(item_id: str, user_id: str) -> dict[str, Any] | None:
    it = _get_checklist_item_any(item_id, user_id)
    if it is None:
        return None
    conn = get_connection()
    cur = conn.execute(
        "SELECT depends_on_item_id FROM checklist_item_dependencies WHERE item_id = ?",
        (item_id,),
    )
    it["depends_on"] = [r[0] for r in cur.fetchall()]
    return it


def update_checklist_item(
    item_id: str,
    user_id: str,
    title: str | None = None,
    status: str | None = None,
    position: int | None = None,
    person_id: str | None = None,
    asset_id: str | None = None,
    _clear_person: bool = False,
    _clear_asset: bool = False,
) -> dict[str, Any] | None:
    if _get_checklist_item_any(item_id, user_id) is None:
        return None
    if status is not None and status not in CHECKLIST_STATUSES:
        raise ValueError(f"unknown checklist status: {status!r}")
    if person_id is not None and get_person(person_id) is None:
        raise ValueError("person not found")
    if asset_id is not None and get_asset(asset_id) is None:
        raise ValueError("asset not found")
    updates: list[str] = []
    args: list[Any] = []
    if title is not None:
        updates.append("title = ?")
        args.append(title)
    if status is not None:
        updates.append("status = ?")
        args.append(status)
    if position is not None:
        updates.append("position = ?")
        args.append(position)
    if person_id is not None or _clear_person:
        updates.append("person_id = ?")
        args.append(person_id)
    if asset_id is not None or _clear_asset:
        updates.append("asset_id = ?")
        args.append(asset_id)
    if not updates:
        return get_checklist_item(item_id, user_id)
    updates.append("updated_at = ?")
    args.append(_now())
    args.append(item_id)
    args.append(user_id)
    conn = get_connection()
    with ve_write_transaction(conn, purpose="update_checklist_item"):
        _guard_checklist_write(conn, item_id, user_id, target_id=item_id)
        conn.execute(
            f"UPDATE checklist_items SET {', '.join(updates)} WHERE id = ? AND user_id = ?",
            tuple(args),
        )
        _commit_if_owner(conn)
    return get_checklist_item(item_id, user_id)


def _checklist_descendant_ids(
    conn, item_id: str, user_id: str
) -> list[str]:
    """All descendant ids (recursive) of a checklist item."""
    seen: list[str] = []
    stack = [item_id]
    while stack:
        cur_id = stack.pop()
        cur = conn.execute(
            "SELECT id FROM checklist_items WHERE parent_id = ? AND user_id = ?",
            (cur_id, user_id),
        )
        for (child_id,) in cur.fetchall():
            if child_id not in seen:
                seen.append(child_id)
                stack.append(child_id)
    return seen


def delete_checklist_item(item_id: str, user_id: str) -> bool:
    """Delete an item and its descendants (cascade), plus their dependency edges."""
    if _get_checklist_item_any(item_id, user_id) is None:
        return False
    conn = get_connection()
    with ve_write_transaction(conn, purpose="delete_checklist_item"):
        _guard_checklist_write(conn, item_id, user_id, target_id=item_id)
        doomed = [item_id] + _checklist_descendant_ids(conn, item_id, user_id)
        placeholders = ",".join("?" for _ in doomed)
        conn.execute(
            f"DELETE FROM checklist_item_dependencies WHERE item_id IN ({placeholders}) "
            f"OR depends_on_item_id IN ({placeholders})",
            tuple(doomed) + tuple(doomed),
        )
        conn.execute(
            f"DELETE FROM checklist_items WHERE id IN ({placeholders}) AND user_id = ?",
            tuple(doomed) + (user_id,),
        )
        _commit_if_owner(conn)
    return True


def _checklist_depends_on(conn, idea_id: str, user_id: str) -> dict[str, list[str]]:
    """Adjacency: item_id -> [ids it depends on], for one idea's checklist."""
    cur = conn.execute(
        "SELECT d.item_id, d.depends_on_item_id FROM checklist_item_dependencies d "
        "JOIN checklist_items i ON i.id = d.item_id "
        "WHERE i.idea_id = ? AND i.user_id = ? AND i.superseded = 0",
        (idea_id, user_id),
    )
    adj: dict[str, list[str]] = {}
    for item_id, depends_on in cur.fetchall():
        adj.setdefault(item_id, []).append(depends_on)
    return adj


def _would_create_cycle(
    adj: dict[str, list[str]], item_id: str, depends_on_id: str
) -> bool:
    """Adding edge (item_id depends on depends_on_id) cycles iff depends_on_id
    can already reach item_id via depends-on edges."""
    stack = [depends_on_id]
    seen = set()
    while stack:
        cur = stack.pop()
        if cur == item_id:
            return True
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(adj.get(cur, []))
    return False


def add_checklist_dependency(
    item_id: str, depends_on_id: str, user_id: str
) -> dict[str, Any]:
    item = _get_checklist_item_any(item_id, user_id)
    other = _get_checklist_item_any(depends_on_id, user_id)
    if item is None or other is None:
        raise ValueError("checklist item not found")
    if item["idea_id"] != other["idea_id"]:
        raise ValueError("dependencies must stay within one idea's checklist")
    if item_id == depends_on_id:
        raise ValueError("an item cannot depend on itself")
    conn = get_connection()
    with ve_write_transaction(conn, purpose="add_checklist_dependency"):
        _guard_checklist_write(conn, item_id, user_id, target_id=item_id)
        adj = _checklist_depends_on(conn, item["idea_id"], user_id)
        if _would_create_cycle(adj, item_id, depends_on_id):
            raise ValueError("that dependency would create a cycle")
        conn.execute(
            "INSERT OR IGNORE INTO checklist_item_dependencies "
            "(item_id, depends_on_item_id, created_at) VALUES (?, ?, ?)",
            (item_id, depends_on_id, _now()),
        )
        _commit_if_owner(conn)
    return get_checklist_item(item_id, user_id) or {}


def remove_checklist_dependency(
    item_id: str, depends_on_id: str, user_id: str
) -> bool:
    if _get_checklist_item_any(item_id, user_id) is None:
        return False
    conn = get_connection()
    with ve_write_transaction(conn, purpose="remove_checklist_dependency"):
        _guard_checklist_write(conn, item_id, user_id, target_id=item_id)
        cur = conn.execute(
            "DELETE FROM checklist_item_dependencies WHERE item_id = ? AND depends_on_item_id = ?",
            (item_id, depends_on_id),
        )
        _commit_if_owner(conn)
    return cur.rowcount > 0


def mark_checklist_superseded(idea_id: str, user_id: str) -> int:
    """Keep the graduated checklist as provenance; mark it superseded by the work."""
    conn = get_connection()
    with ve_write_transaction(conn, purpose="mark_checklist_superseded"):
        _guard_idea_write(conn, idea_id, user_id, target_id=idea_id, target_kind="idea")
        cur = conn.execute(
            "UPDATE checklist_items SET superseded = 1, updated_at = ? "
            "WHERE idea_id = ? AND user_id = ? AND superseded = 0",
            (_now(), idea_id, user_id),
        )
        _commit_if_owner(conn)
    return cur.rowcount


# --- Initiatives ---

def _decode_legacy_required_people_as_seats(required_people: list[str]) -> list[dict[str, Any]]:
    """
    Backward compatibility for older initiatives that used `initiatives.required_people`
    as a seat transport:

    - Either a list of JSON strings like:
        {"role":"...","person_id":"...","effort":"...","notes":"..."}
    - Or a list of plain person IDs.
    """
    out: list[dict[str, Any]] = []
    for raw in required_people:
        if raw is None:
            continue
        s = str(raw).strip()
        if not s:
            continue

        if s.startswith("{") and s.endswith("}"):
            try:
                parsed = json.loads(s)
                role = str(parsed.get("role") or "").strip()
                assigned_person_id = parsed.get("person_id") or parsed.get("personId") or None
                assigned_person_id = str(assigned_person_id).strip() if assigned_person_id else None
                estimated_effort = parsed.get("effort") or parsed.get("estimated_effort") or None
                estimated_effort = str(estimated_effort).strip() if estimated_effort else None
                notes = str(parsed.get("notes") or "").strip()
                if role or assigned_person_id or estimated_effort or notes:
                    out.append({
                        "role": role,
                        "assigned_person_id": assigned_person_id,
                        "estimated_effort": estimated_effort,
                        "notes": notes,
                    })
                    continue
            except Exception:
                # Not parseable; fall back to plain id handling.
                pass

        # Legacy plain person id.
        out.append({
            "role": "",
            "assigned_person_id": s,
            "estimated_effort": None,
            "notes": "",
        })

    return out


def _list_seats_for_initiative(conn: sqlite3.Connection, initiative_id: str) -> list[dict[str, Any]]:
    cur = conn.execute(
        "SELECT role, assigned_person_id, estimated_effort, notes FROM initiative_seats WHERE initiative_id = ? ORDER BY created_at ASC, id ASC",
        (initiative_id,),
    )
    rows = cur.fetchall()
    return [{
        "role": r["role"],
        "assigned_person_id": r["assigned_person_id"],
        "estimated_effort": r["estimated_effort"],
        "notes": r["notes"],
    } for r in rows]


def _upsert_initiative_seats(conn: sqlite3.Connection, initiative_id: str, seats: list[M.InitiativeSeat]) -> None:
    # Replace entire set (simple + consistent MVP behavior).
    conn.execute("DELETE FROM initiative_seats WHERE initiative_id = ?", (initiative_id,))
    if not seats:
        return
    now = _now()
    for seat in seats:
        conn.execute(
            """INSERT INTO initiative_seats (
              id, initiative_id, role, assigned_person_id, estimated_effort, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                M.new_id(),
                initiative_id,
                seat.role or "",
                seat.assigned_person_id,
                seat.estimated_effort,
                seat.notes or "",
                now,
                now,
            ),
        )


def list_initiatives(user_id: str | None = None) -> list[dict[str, Any]]:
    conn = get_connection()
    if user_id is None:
        cur = conn.execute(
            "SELECT id, source_idea_id, title, brief, status, owner_id, priority_rank_manual, strategic_value_manual, "
            "energy_impact_manual, evaluation_priority, estimated_cost_ai, estimated_timeframe_ai, philosophical_alignment_ai, next_step_ai, "
            "required_people, required_assets, dependencies, risks, recommendation, counts_toward_capacity, "
            "manual_override, kill_criteria, notes, created_at, updated_at, seed_key FROM initiatives ORDER BY updated_at DESC"
        )
    else:
        cur = conn.execute(
            "SELECT id, source_idea_id, title, brief, status, owner_id, priority_rank_manual, strategic_value_manual, "
            "energy_impact_manual, evaluation_priority, estimated_cost_ai, estimated_timeframe_ai, philosophical_alignment_ai, next_step_ai, "
            "required_people, required_assets, dependencies, risks, recommendation, counts_toward_capacity, "
            "manual_override, kill_criteria, notes, created_at, updated_at, seed_key FROM initiatives WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        )
    initiatives = [M.row_to_initiative(tuple(r)) for r in cur.fetchall()]
    for init in initiatives:
        init["seats"] = _list_seats_for_initiative(conn, init["id"])
    return initiatives


def get_initiative(initiative_id: str, user_id: str | None = None) -> dict[str, Any] | None:
    conn = get_connection()
    if user_id is None:
        cur = conn.execute(
            "SELECT id, source_idea_id, title, brief, status, owner_id, priority_rank_manual, strategic_value_manual, "
            "energy_impact_manual, evaluation_priority, estimated_cost_ai, estimated_timeframe_ai, philosophical_alignment_ai, next_step_ai, "
            "required_people, required_assets, dependencies, risks, recommendation, counts_toward_capacity, "
            "manual_override, kill_criteria, notes, created_at, updated_at, seed_key FROM initiatives WHERE id = ?",
            (initiative_id,),
        )
    else:
        cur = conn.execute(
            "SELECT id, source_idea_id, title, brief, status, owner_id, priority_rank_manual, strategic_value_manual, "
            "energy_impact_manual, evaluation_priority, estimated_cost_ai, estimated_timeframe_ai, philosophical_alignment_ai, next_step_ai, "
            "required_people, required_assets, dependencies, risks, recommendation, counts_toward_capacity, "
            "manual_override, kill_criteria, notes, created_at, updated_at, seed_key FROM initiatives WHERE id = ? AND user_id = ?",
            (initiative_id, user_id),
        )
    row = cur.fetchone()
    if not row:
        return None
    out = M.row_to_initiative(tuple(row))
    out["seats"] = _list_seats_for_initiative(conn, out["id"])
    return out


def create_initiative(data: M.InitiativeCreate, user_id: str) -> dict[str, Any]:
    conn = get_connection()
    iid = M.new_id()
    now = _now()
    _ensure_owned_reference(
        conn,
        table="ideas",
        ref_id=data.source_idea_id,
        user_id=user_id,
        field_name="source_idea_id",
    )
    seats_to_persist: list[M.InitiativeSeat] = list(data.seats or [])
    with ve_write_transaction(conn, purpose="create_initiative"):
        _guard_legacy_write(conn, iid, target_id=iid, target_kind="initiative")
        conn.execute(
            """INSERT INTO initiatives (
              id, user_id, source_idea_id, title, brief, status, owner_id,
              evaluation_priority, estimated_cost_ai, estimated_timeframe_ai, philosophical_alignment_ai, next_step_ai,
              required_assets, dependencies, risks, recommendation,
              kill_criteria, notes, seed_key, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                iid, user_id, data.source_idea_id, data.title, data.brief, data.status, data.owner_id,
                data.evaluation_priority,
                data.estimated_cost_ai, data.estimated_timeframe_ai, data.philosophical_alignment_ai, data.next_step_ai,
                M._json_dumps_list(data.required_assets),
                data.dependencies, data.risks, data.recommendation,
                data.kill_criteria, data.notes, data.seed_key, now, now,
            ),
        )
        if seats_to_persist:
            _upsert_initiative_seats(conn, iid, seats_to_persist)
        _commit_if_owner(conn)
    out = get_initiative(iid, user_id) or {}
    _log_ve_entity_activity(
        type=ActivityType.INITIATIVE_CREATED.value,
        entity_type=ActivityEntityType.INITIATIVE.value,
        entity_id=iid,
        user_id=user_id,
        related_entity_id=_ve_activity_related_id(data.source_idea_id),
        detail=f"title={(data.title or '')[:120]!r}",
    )
    return out


def update_initiative(initiative_id: str, data: M.InitiativeUpdate, user_id: str) -> dict[str, Any] | None:
    if get_initiative(initiative_id, user_id) is None:
        return None
    conn = get_connection()
    model_items = data.model_dump(exclude_unset=True)
    if "source_idea_id" in model_items:
        _ensure_owned_reference(
            conn,
            table="ideas",
            ref_id=model_items.get("source_idea_id"),
            user_id=user_id,
            field_name="source_idea_id",
        )

    seats_to_persist: list[M.InitiativeSeat] | None = None
    if "seats" in model_items and model_items["seats"] is not None:
        seats_to_persist = list(model_items["seats"])

    updates: list[str] = []
    args: list[Any] = []
    nullable_fks = ("source_idea_id", "owner_id")

    # Seats are stored in `initiative_seats`.
    for k, v in model_items.items():
        if k in ("seats",):
            continue
        if v is not None or (k in nullable_fks):
            if k in ("required_assets",):
                updates.append(f"{k} = ?")
                args.append(M._json_dumps_list(v) if v is not None else "[]")
            else:
                updates.append(f"{k} = ?")
                args.append(v)

    if not updates and seats_to_persist is None:
        return get_initiative(initiative_id, user_id)
    updates.append("updated_at = ?")
    args.append(_now())
    args.append(initiative_id)
    with ve_write_transaction(conn, purpose="update_initiative"):
        _guard_legacy_write(conn, initiative_id, target_id=initiative_id, target_kind="initiative")
        if seats_to_persist is not None:
            _upsert_initiative_seats(conn, initiative_id, seats_to_persist)
        if not updates:
            # Seats-only update: the upsert above IS the write. The
            # owner's clean exit commits it. Previously this path
            # returned WITHOUT committing (the seat upserts sat in an
            # open implicit transaction until the next commit on the
            # connection) — a latent quirk the helper conversion
            # corrects in the direction of the evident intent (the
            # caller is returned the updated initiative). Pinned
            # finding; no test covers the uncommitted behavior.
            return get_initiative(initiative_id, user_id)
        conn.execute(f"UPDATE initiatives SET {', '.join(updates)} WHERE id = ? AND user_id = ?", args + [user_id])
        _commit_if_owner(conn)
    out = get_initiative(initiative_id, user_id)
    patch_keys = list(model_items.keys())
    detail = (
        "seats_updated"
        if ("seats" in model_items or "required_people" in model_items) and len(patch_keys) <= 2
        else f"fields={','.join(patch_keys)[:200]}"
    )
    src_id = (out or {}).get("source_idea_id") if isinstance(out, dict) else None
    _log_ve_entity_activity(
        type=ActivityType.INITIATIVE_UPDATED.value,
        entity_type=ActivityEntityType.INITIATIVE.value,
        entity_id=initiative_id,
        user_id=user_id,
        related_entity_id=_ve_activity_related_id(str(src_id) if src_id else None),
        detail=detail,
    )
    return out


# --- Execution steps (Phase 1 checklist; rows canonical) ---

EXECUTION_STEPS_SCOPE_INITIATIVE = "initiative"
EXECUTION_STEPS_SCOPE_PROJECT = "project"


def _assert_execution_scope_owned(
    conn: sqlite3.Connection, user_id: str, scope_type: str, scope_id: str
) -> None:
    if scope_type == EXECUTION_STEPS_SCOPE_INITIATIVE:
        row = conn.execute(
            "SELECT 1 FROM initiatives WHERE id = ? AND user_id = ?",
            (scope_id, user_id),
        ).fetchone()
        if not row:
            raise ValueError("Initiative not found")
    elif scope_type == EXECUTION_STEPS_SCOPE_PROJECT:
        row = conn.execute(
            "SELECT 1 FROM projects WHERE id = ? AND user_id = ?",
            (scope_id, user_id),
        ).fetchone()
        if not row:
            raise ValueError("Project not found")
    else:
        raise ValueError("Invalid scope_type")


def list_execution_steps(scope_type: str, scope_id: str, user_id: str) -> list[dict[str, Any]]:
    conn = get_connection()
    cur = conn.execute(
        """SELECT id, user_id, scope_type, scope_id, title, sort_order, is_done, completed_at,
           source, source_evaluation_id, created_at, updated_at
           FROM execution_steps
           WHERE user_id = ? AND scope_type = ? AND scope_id = ?
           ORDER BY sort_order ASC, id ASC""",
        (user_id, scope_type, scope_id),
    )
    return [M.row_to_execution_step(tuple(r)) for r in cur.fetchall()]


def list_all_execution_steps(user_id: str) -> list[dict[str, Any]]:
    """All execution steps for a user, any scope.

    Read-only helper for the unified-node projection (Slice A): reading
    per scope would silently miss a step whose scope row is gone.
    """
    conn = get_connection()
    cur = conn.execute(
        """SELECT id, user_id, scope_type, scope_id, title, sort_order, is_done, completed_at,
           source, source_evaluation_id, created_at, updated_at
           FROM execution_steps
           WHERE user_id = ?
           ORDER BY scope_type ASC, scope_id ASC, sort_order ASC, id ASC""",
        (user_id,),
    )
    return [M.row_to_execution_step(tuple(r)) for r in cur.fetchall()]


def count_execution_steps(scope_type: str, scope_id: str, user_id: str) -> int:
    conn = get_connection()
    cur = conn.execute(
        "SELECT COUNT(*) FROM execution_steps WHERE user_id = ? AND scope_type = ? AND scope_id = ?",
        (user_id, scope_type, scope_id),
    )
    return int(cur.fetchone()[0])


def get_execution_step(step_id: str, user_id: str) -> dict[str, Any] | None:
    conn = get_connection()
    cur = conn.execute(
        """SELECT id, user_id, scope_type, scope_id, title, sort_order, is_done, completed_at,
           source, source_evaluation_id, created_at, updated_at
           FROM execution_steps WHERE id = ? AND user_id = ?""",
        (step_id, user_id),
    )
    row = cur.fetchone()
    return M.row_to_execution_step(tuple(row)) if row else None


def create_execution_step(
    user_id: str,
    scope_type: str,
    scope_id: str,
    title: str,
    sort_order: int | None,
    source: str = "user",
    source_evaluation_id: str | None = None,
) -> dict[str, Any]:
    conn = get_connection()
    _assert_execution_scope_owned(conn, user_id, scope_type, scope_id)
    title = (title or "").strip()
    if not title:
        raise ValueError("title is required")
    now = _now()
    sid = M.new_id()
    with ve_write_transaction(conn, purpose="create_execution_step"):
        _guard_legacy_write(
            conn,
            _resolve_step_subtree(conn, scope_type, scope_id, user_id),
            target_id=sid,
            target_kind="execution_step",
        )
        if sort_order is None:
            cur = conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) FROM execution_steps WHERE user_id = ? AND scope_type = ? AND scope_id = ?",
                (user_id, scope_type, scope_id),
            )
            sort_order = int(cur.fetchone()[0]) + 1
        conn.execute(
            """INSERT INTO execution_steps (
              id, user_id, scope_type, scope_id, title, sort_order, is_done, completed_at,
              source, source_evaluation_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 0, NULL, ?, ?, ?, ?)""",
            (
                sid,
                user_id,
                scope_type,
                scope_id,
                title,
                sort_order,
                source,
                source_evaluation_id,
                now,
                now,
            ),
        )
        _commit_if_owner(conn)
    return get_execution_step(sid, user_id) or {}


def update_execution_step(step_id: str, user_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    if get_execution_step(step_id, user_id) is None:
        return None
    conn = get_connection()
    updates: list[str] = []
    args: list[Any] = []
    if "title" in patch:
        t = (patch.get("title") or "").strip()
        if not t:
            raise ValueError("title cannot be empty")
        updates.append("title = ?")
        args.append(t)
    if "sort_order" in patch and patch["sort_order"] is not None:
        updates.append("sort_order = ?")
        args.append(int(patch["sort_order"]))
    if "is_done" in patch:
        done = bool(patch["is_done"])
        updates.append("is_done = ?")
        args.append(1 if done else 0)
        updates.append("completed_at = ?")
        args.append(_now() if done else None)
    if not updates:
        return get_execution_step(step_id, user_id)
    updates.append("updated_at = ?")
    args.append(_now())
    args.append(step_id)
    args.append(user_id)
    with ve_write_transaction(conn, purpose="update_execution_step"):
        _guard_step_write(conn, step_id, user_id, target_id=step_id)
        conn.execute(
            f"UPDATE execution_steps SET {', '.join(updates)} WHERE id = ? AND user_id = ?",
            args,
        )
        _commit_if_owner(conn)
    return get_execution_step(step_id, user_id)


def delete_execution_step(step_id: str, user_id: str) -> bool:
    if get_execution_step(step_id, user_id) is None:
        return False
    conn = get_connection()
    with ve_write_transaction(conn, purpose="delete_execution_step"):
        _guard_step_write(conn, step_id, user_id, target_id=step_id)
        conn.execute("DELETE FROM execution_steps WHERE id = ? AND user_id = ?", (step_id, user_id))
        _commit_if_owner(conn)
    return True


def materialize_execution_steps(
    user_id: str,
    scope_type: str,
    scope_id: str,
    titles: list[str],
    source: str,
    *,
    replace: bool,
) -> list[dict[str, Any]]:
    """
    Insert titles as new rows. If any row already exists for this scope and replace is False,
    raises ValueError('EXECUTION_STEPS_EXIST'). If replace is True, deletes existing rows first.
    """
    conn = get_connection()
    _assert_execution_scope_owned(conn, user_id, scope_type, scope_id)
    cleaned = [t.strip() for t in titles if isinstance(t, str) and t.strip()]
    if not cleaned or len(cleaned) > 20:
        raise ValueError("titles must be 1 to 20 non-empty strings")
    if source not in ("ai", "user", "import"):
        source = "user"
    n = count_execution_steps(scope_type, scope_id, user_id)
    if n > 0 and not replace:
        raise ValueError("EXECUTION_STEPS_EXIST")
    now = _now()
    with ve_write_transaction(conn, purpose="materialize_execution_steps"):
        _guard_legacy_write(
            conn,
            _resolve_step_subtree(conn, scope_type, scope_id, user_id),
            target_id=scope_id,
            target_kind="execution_step",
        )
        if replace:
            conn.execute(
                "DELETE FROM execution_steps WHERE user_id = ? AND scope_type = ? AND scope_id = ?",
                (user_id, scope_type, scope_id),
            )
        for i, title in enumerate(cleaned):
            sid = M.new_id()
            conn.execute(
                """INSERT INTO execution_steps (
                  id, user_id, scope_type, scope_id, title, sort_order, is_done, completed_at,
                  source, source_evaluation_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, NULL, ?, NULL, ?, ?)""",
                (sid, user_id, scope_type, scope_id, title, i, source, now, now),
            )
        _commit_if_owner(conn)
    if scope_type == EXECUTION_STEPS_SCOPE_INITIATIVE:
        et = ActivityEntityType.INITIATIVE.value
        eid = scope_id
    elif scope_type == EXECUTION_STEPS_SCOPE_PROJECT:
        et = ActivityEntityType.PROJECT.value
        eid = scope_id
    else:
        et, eid = "", ""
    if et and eid:
        d = f"count={len(cleaned)};replace={replace};source={source}"
        if len(d) > 2000:
            d = d[:2000]
        _log_coordination_ve_activity(
            type=ActivityType.EXECUTION_STEP_MATERIALIZED.value,
            entity_type=et,
            entity_id=eid,
            user_id=user_id,
            detail=d,
        )
    return list_execution_steps(scope_type, scope_id, user_id)


def reorder_execution_steps(
    user_id: str, scope_type: str, scope_id: str, ordered_ids: list[str]
) -> list[dict[str, Any]]:
    conn = get_connection()
    _assert_execution_scope_owned(conn, user_id, scope_type, scope_id)
    existing = list_execution_steps(scope_type, scope_id, user_id)
    existing_ids = {r["id"] for r in existing}
    if set(ordered_ids) != existing_ids or len(ordered_ids) != len(existing_ids):
        raise ValueError("ordered_ids must be a permutation of existing step ids")
    now = _now()
    with ve_write_transaction(conn, purpose="reorder_execution_steps"):
        _guard_legacy_write(
            conn,
            _resolve_step_subtree(conn, scope_type, scope_id, user_id),
            target_id=scope_id,
            target_kind="execution_step",
        )
        for i, sid in enumerate(ordered_ids):
            conn.execute(
                "UPDATE execution_steps SET sort_order = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                (i, now, sid, user_id),
            )
        _commit_if_owner(conn)
    return list_execution_steps(scope_type, scope_id, user_id)


def delete_initiative(initiative_id: str, user_id: str) -> bool:
    before = get_initiative(initiative_id, user_id)
    if before is None:
        return False
    sid_raw = before.get("source_idea_id")
    src = _ve_activity_related_id(str(sid_raw).strip() if sid_raw is not None else None)
    conn = get_connection()
    with ve_write_transaction(conn, purpose="delete_initiative"):
        _guard_legacy_write(conn, initiative_id, target_id=initiative_id, target_kind="initiative")
        conn.execute(
            "DELETE FROM execution_steps WHERE user_id = ? AND scope_type = ? AND scope_id = ?",
            (user_id, EXECUTION_STEPS_SCOPE_INITIATIVE, initiative_id),
        )
        conn.execute(
            "UPDATE projects SET initiative_id = NULL WHERE initiative_id = ? AND user_id = ?",
            (initiative_id, user_id),
        )
        conn.execute("DELETE FROM initiatives WHERE id = ? AND user_id = ?", (initiative_id, user_id))
        _commit_if_owner(conn)
    _log_ve_entity_activity(
        type=ActivityType.INITIATIVE_DELETED.value,
        entity_type=ActivityEntityType.INITIATIVE.value,
        entity_id=initiative_id,
        user_id=user_id,
        related_entity_id=src,
        detail="deleted",
    )
    return True


# --- Projects ---

def list_projects(user_id: str | None = None) -> list[dict[str, Any]]:
    conn = get_connection()
    if user_id is None:
        cur = conn.execute(
            "SELECT id, initiative_id, title, brief, status, owner_id, supporting_owner_ids, required_assets, priority, "
            "start_date, end_date, estimated_weekly_hours, deliverables, complexity, current_focus, next_step_ai, "
            "notes, created_at, updated_at FROM projects ORDER BY updated_at DESC"
        )
    else:
        cur = conn.execute(
            "SELECT id, initiative_id, title, brief, status, owner_id, supporting_owner_ids, required_assets, priority, "
            "start_date, end_date, estimated_weekly_hours, deliverables, complexity, current_focus, next_step_ai, "
            "notes, created_at, updated_at FROM projects WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        )
    return [M.row_to_project(tuple(r)) for r in cur.fetchall()]


def get_project(project_id: str, user_id: str | None = None) -> dict[str, Any] | None:
    conn = get_connection()
    if user_id is None:
        cur = conn.execute(
            "SELECT id, initiative_id, title, brief, status, owner_id, supporting_owner_ids, required_assets, priority, "
            "start_date, end_date, estimated_weekly_hours, deliverables, complexity, current_focus, next_step_ai, "
            "notes, created_at, updated_at FROM projects WHERE id = ?",
            (project_id,),
        )
    else:
        cur = conn.execute(
            "SELECT id, initiative_id, title, brief, status, owner_id, supporting_owner_ids, required_assets, priority, "
            "start_date, end_date, estimated_weekly_hours, deliverables, complexity, current_focus, next_step_ai, "
            "notes, created_at, updated_at FROM projects WHERE id = ? AND user_id = ?",
            (project_id, user_id),
        )
    row = cur.fetchone()
    return M.row_to_project(tuple(row)) if row else None


def _insert_project(
    conn: sqlite3.Connection,
    data: M.ProjectCreate,
    user_id: str,
    *,
    pid: str | None = None,
) -> str:
    """INSERT one project row. No commit, no read-back, no log, no
    guard — the caller runs _ensure_owned_reference and
    _guard_legacy_write inside its transaction first (the
    _insert_task precedent). Shared by create_project and
    approve_upload_outcome so the approve path reuses the exact
    write path instead of duplicating validation or SQL.
    """
    pid = pid or M.new_id()
    now = _now()
    conn.execute(
        """INSERT INTO projects (
          id, user_id, initiative_id, title, brief, status, owner_id, supporting_owner_ids, required_assets, priority,
          start_date, end_date, estimated_weekly_hours, next_step_ai,
          notes, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            pid, user_id, data.initiative_id, data.title, data.brief, data.status, data.owner_id,
            M._json_dumps_list(data.supporting_owner_ids), M._json_dumps_list(data.required_assets),
            data.priority, data.start_date, data.end_date,
            data.estimated_weekly_hours, data.next_step_ai,
            data.notes, now, now,
        ),
    )
    return pid


def create_project(data: M.ProjectCreate, user_id: str) -> dict[str, Any]:
    conn = get_connection()
    pid = M.new_id()
    _ensure_owned_reference(
        conn,
        table="initiatives",
        ref_id=data.initiative_id,
        user_id=user_id,
        field_name="initiative_id",
    )
    with ve_write_transaction(conn, purpose="create_project"):
        # The create payload's parent field IS the subtree: the
        # initiative_id names the subtree root directly. (Do NOT
        # route it through _resolve_project_subtree — that takes a
        # PROJECT id; passing an initiative id there looks up a
        # nonexistent project, returns None, and silently bypasses
        # the guard. Caught by T-G1.)
        _guard_legacy_write(
            conn,
            data.initiative_id,
            target_id=pid,
            target_kind="project",
        )
        _insert_project(conn, data, user_id, pid=pid)
        _commit_if_owner(conn)
    out = get_project(pid, user_id) or {}
    _log_ve_entity_activity(
        type=ActivityType.PROJECT_CREATED.value,
        entity_type=ActivityEntityType.PROJECT.value,
        entity_id=pid,
        user_id=user_id,
        related_entity_id=_ve_activity_related_id(data.initiative_id),
        detail=f"title={(data.title or '')[:120]!r}",
    )
    return out


def update_project(project_id: str, data: M.ProjectUpdate, user_id: str) -> dict[str, Any] | None:
    if get_project(project_id, user_id) is None:
        return None
    conn = get_connection()
    updates = []
    args = []
    nullable_fks = ("initiative_id", "owner_id")
    model_items = data.model_dump(exclude_unset=True)
    if "initiative_id" in model_items:
        _ensure_owned_reference(
            conn,
            table="initiatives",
            ref_id=model_items.get("initiative_id"),
            user_id=user_id,
            field_name="initiative_id",
        )
    for k, v in model_items.items():
        if v is not None or (k in nullable_fks):
            if k == "supporting_owner_ids":
                updates.append("supporting_owner_ids = ?")
                args.append(M._json_dumps_list(v) if v is not None else "[]")
            elif k == "required_assets":
                updates.append("required_assets = ?")
                args.append(M._json_dumps_list(v) if v is not None else "[]")
            else:
                updates.append(f"{k} = ?")
                args.append(v)
    if not updates:
        return get_project(project_id, user_id)
    updates.append("updated_at = ?")
    args.append(_now())
    args.append(project_id)
    with ve_write_transaction(conn, purpose="update_project"):
        _guard_legacy_write(
            conn,
            _resolve_project_subtree(conn, project_id, user_id),
            target_id=project_id,
            target_kind="project",
        )
        conn.execute(f"UPDATE projects SET {', '.join(updates)} WHERE id = ? AND user_id = ?", args + [user_id])
        _commit_if_owner(conn)
    out = get_project(project_id, user_id)
    ini = (out or {}).get("initiative_id") if isinstance(out, dict) else None
    _log_ve_entity_activity(
        type=ActivityType.PROJECT_UPDATED.value,
        entity_type=ActivityEntityType.PROJECT.value,
        entity_id=project_id,
        user_id=user_id,
        related_entity_id=_ve_activity_related_id(str(ini) if ini else None),
        detail=f"fields={','.join(list(model_items.keys()))[:200]}",
    )
    return out


def delete_project(project_id: str, user_id: str) -> bool:
    before = get_project(project_id, user_id)
    if before is None:
        return False
    ini = _ve_activity_related_id(str(before.get("initiative_id") or "").strip() or None)
    conn = get_connection()
    with ve_write_transaction(conn, purpose="delete_project"):
        _guard_legacy_write(
            conn,
            _resolve_project_subtree(conn, project_id, user_id),
            target_id=project_id,
            target_kind="project",
        )
        task_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE project_id = ? AND user_id = ?",
                (project_id, user_id),
            ).fetchone()[0]
        )
        if task_count > 0:
            # §6: a project with tasks cannot be deleted while the
            # unified-node migration is in flight — deleting the
            # project would orphan its tasks' node counterparts.
            raise ProjectHasTasks(
                f"project {project_id} cannot be deleted: it still has "
                f"{task_count} task(s); delete or move the tasks first",
                project_id=project_id,
                task_count=task_count,
            )
        conn.execute(
            "DELETE FROM execution_steps WHERE user_id = ? AND scope_type = ? AND scope_id = ?",
            (user_id, EXECUTION_STEPS_SCOPE_PROJECT, project_id),
        )
        conn.execute("DELETE FROM tasks WHERE project_id = ? AND user_id = ?", (project_id, user_id))
        conn.execute("DELETE FROM projects WHERE id = ? AND user_id = ?", (project_id, user_id))
        _commit_if_owner(conn)
    _log_ve_entity_activity(
        type=ActivityType.PROJECT_DELETED.value,
        entity_type=ActivityEntityType.PROJECT.value,
        entity_id=project_id,
        user_id=user_id,
        related_entity_id=ini,
        detail="deleted",
    )
    return True


# --- Tasks ---

def _timeframe_filter_clause(column: str, value: str | None) -> tuple[str, tuple]:
    """SQL fragment + params for the timeframe_commitment list filter.

    None = no filter (all tasks). "tentative" = tentative only.
    "unspecified" = NULL rows only. Anything else is a caller error:
    absent and "unspecified" are different filters and must not be
    conflated, and no other value exists in the closed value set.
    """
    if value is None:
        return "", ()
    if value == "tentative":
        return f" AND {column} = ?", ("tentative",)
    if value == "unspecified":
        return f" AND {column} IS NULL", ()
    raise ValueError(f"Invalid timeframe_commitment filter: {value!r}")


def list_tasks(
    user_id: str | None = None,
    project_id: str | None = None,
    initiative_id: str | None = None,
    timeframe_commitment: str | None = None,
) -> list[dict[str, Any]]:
    conn = get_connection()
    if initiative_id and user_id is not None:
        frag, fparams = _timeframe_filter_clause("t.timeframe_commitment", timeframe_commitment)
        cur = conn.execute(
            """
            SELECT t.id, t.project_id, t.parent_task_id, t.title, t.description, t.assignee_id, t.status, t.priority,
            t.estimated_hours, t.due_date, t.dependency_ids, t.required_asset_ids, t.completion_criteria, t.notes, t.created_at, t.updated_at, t.seat_ref, t.timeframe_commitment, t.origin_seat, t.origin_conversation_id, t.origin_message_id, t.origin_claim_id, t.origin_decision_id, t.responsible_seat
            FROM tasks t
            INNER JOIN projects p ON p.id = t.project_id AND p.user_id = t.user_id
            WHERE p.initiative_id = ? AND t.user_id = ?""" + frag + """
            ORDER BY t.updated_at DESC
            """,
            (initiative_id, user_id) + fparams,
        )
        return [M.row_to_task(tuple(r)) for r in cur.fetchall()]
    if project_id and user_id is not None:
        frag, fparams = _timeframe_filter_clause("timeframe_commitment", timeframe_commitment)
        cur = conn.execute(
            "SELECT id, project_id, parent_task_id, title, description, assignee_id, status, priority, "
            "estimated_hours, due_date, dependency_ids, required_asset_ids, completion_criteria, notes, created_at, updated_at, seat_ref, timeframe_commitment, origin_seat, origin_conversation_id, origin_message_id, origin_claim_id, origin_decision_id, responsible_seat "
            "FROM tasks WHERE project_id = ? AND user_id = ?" + frag + " ORDER BY updated_at DESC",
            (project_id, user_id) + fparams,
        )
    elif project_id:
        frag, fparams = _timeframe_filter_clause("timeframe_commitment", timeframe_commitment)
        cur = conn.execute(
            "SELECT id, project_id, parent_task_id, title, description, assignee_id, status, priority, "
            "estimated_hours, due_date, dependency_ids, required_asset_ids, completion_criteria, notes, created_at, updated_at, seat_ref, timeframe_commitment, origin_seat, origin_conversation_id, origin_message_id, origin_claim_id, origin_decision_id, responsible_seat "
            "FROM tasks WHERE project_id = ?" + frag + " ORDER BY updated_at DESC",
            (project_id,) + fparams,
        )
    elif user_id is not None:
        frag, fparams = _timeframe_filter_clause("timeframe_commitment", timeframe_commitment)
        cur = conn.execute(
            "SELECT id, project_id, parent_task_id, title, description, assignee_id, status, priority, "
            "estimated_hours, due_date, dependency_ids, required_asset_ids, completion_criteria, notes, created_at, updated_at, seat_ref, timeframe_commitment, origin_seat, origin_conversation_id, origin_message_id, origin_claim_id, origin_decision_id, responsible_seat "
            "FROM tasks WHERE user_id = ?" + frag + " ORDER BY updated_at DESC",
            (user_id,) + fparams,
        )
    else:
        frag, fparams = _timeframe_filter_clause("timeframe_commitment", timeframe_commitment)
        where = (" WHERE " + frag[5:]) if frag else ""
        cur = conn.execute(
            "SELECT id, project_id, parent_task_id, title, description, assignee_id, status, priority, "
            "estimated_hours, due_date, dependency_ids, required_asset_ids, completion_criteria, notes, created_at, updated_at, seat_ref, timeframe_commitment, origin_seat, origin_conversation_id, origin_message_id, origin_claim_id, origin_decision_id, responsible_seat "
            "FROM tasks" + where + " ORDER BY updated_at DESC",
            fparams,
        )
    return [M.row_to_task(tuple(r)) for r in cur.fetchall()]


def get_task(task_id: str, user_id: str | None = None) -> dict[str, Any] | None:
    conn = get_connection()
    if user_id is None:
        cur = conn.execute(
            "SELECT id, project_id, parent_task_id, title, description, assignee_id, status, priority, "
            "estimated_hours, due_date, dependency_ids, required_asset_ids, completion_criteria, notes, created_at, updated_at, seat_ref, timeframe_commitment, origin_seat, origin_conversation_id, origin_message_id, origin_claim_id, origin_decision_id, responsible_seat "
            "FROM tasks WHERE id = ?",
            (task_id,),
        )
    else:
        cur = conn.execute(
            "SELECT id, project_id, parent_task_id, title, description, assignee_id, status, priority, "
            "estimated_hours, due_date, dependency_ids, required_asset_ids, completion_criteria, notes, created_at, updated_at, seat_ref, timeframe_commitment, origin_seat, origin_conversation_id, origin_message_id, origin_claim_id, origin_decision_id, responsible_seat "
            "FROM tasks WHERE id = ? AND user_id = ?",
            (task_id, user_id),
        )
    row = cur.fetchone()
    return M.row_to_task(tuple(row)) if row else None


def list_tasks_by_origin_conversation(
    user_id: str, conversation_id: str, limit: int = 11
) -> list[dict[str, Any]]:
    """W2 seed query: tasks whose origin is this conversation.

    Owner-scoped, same 24-column SELECT list and ``row_to_task``
    mapping as ``list_tasks`` so no second mapping can drift.
    ``ORDER BY updated_at DESC, id ASC`` (most recently touched
    first, id as the deterministic tiebreak) with ``LIMIT 11``: the
    eleventh row is read only to detect seed overflow and is never
    rendered. Legacy/manual rows carry NULL origins and never seed.
    ``user_id`` is required (no default); an empty owner raises.
    """
    _require_owner_id(user_id)
    conn = get_connection()
    cur = conn.execute(
        "SELECT id, project_id, parent_task_id, title, description, assignee_id, status, priority, "
        "estimated_hours, due_date, dependency_ids, required_asset_ids, completion_criteria, notes, created_at, updated_at, seat_ref, timeframe_commitment, origin_seat, origin_conversation_id, origin_message_id, origin_claim_id, origin_decision_id, responsible_seat "
        "FROM tasks WHERE user_id = ? AND origin_conversation_id = ? "
        "ORDER BY updated_at DESC, id ASC LIMIT ?",
        (user_id, conversation_id, max(1, int(limit))),
    )
    return [M.row_to_task(tuple(r)) for r in cur.fetchall()]


def _validate_timeframe_commitment(value: str | None) -> None:
    """Closed value set for the timeframe dimension: None (unspecified)
    or "tentative". Anything else is rejected, never stored — a new
    dimension stays a dimension only if its value set stays closed."""
    if value is not None and value != "tentative":
        raise ValueError(
            f"Invalid timeframe_commitment: {value!r} (expected null or 'tentative')"
        )


def _insert_task(
    conn: sqlite3.Connection,
    data: M.TaskCreate,
    user_id: str,
    *,
    origin_seat: str | None = None,
    origin_conversation_id: str | None = None,
    origin_message_id: str | None = None,
    origin_claim_id: str | None = None,
    origin_decision_id: str | None = None,
    responsible_seat: str | None = None,
) -> str:
    """Validate + INSERT one task row. No commit, no read-back, no log.

    Shared by create_task and approve_task_proposal so the approve path
    reuses the exact write path instead of duplicating validation or
    SQL. Callers commit (or roll back) and do read-back + logging.
    The origin_* keyword args are W1 provenance (approve only): the
    manual create_task path leaves them NULL, as before.
    """
    _validate_timeframe_commitment(data.timeframe_commitment)
    if data.project_id:
        _ensure_owned_reference(
            conn,
            table="projects",
            ref_id=data.project_id,
            user_id=user_id,
            field_name="project_id",
        )
    _ensure_owned_reference(
        conn,
        table="tasks",
        ref_id=data.parent_task_id,
        user_id=user_id,
        field_name="parent_task_id",
    )
    tid = M.new_id()
    now = _now()
    conn.execute(
        """INSERT INTO tasks (
          id, user_id, project_id, parent_task_id, title, description, assignee_id, status, priority,
          estimated_hours, due_date, dependency_ids, required_asset_ids, completion_criteria, notes, seat_ref, timeframe_commitment, created_at, updated_at,
          origin_seat, origin_conversation_id, origin_message_id, origin_claim_id, origin_decision_id, responsible_seat
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            tid, user_id, data.project_id, data.parent_task_id, data.title, data.description, data.assignee_id,
            data.status, data.priority, data.estimated_hours, data.due_date,
            M._json_dumps_list(data.dependency_ids), M._json_dumps_list(data.required_asset_ids),
            data.completion_criteria, data.notes, data.seat_ref, data.timeframe_commitment, now, now,
            origin_seat, origin_conversation_id, origin_message_id,
            origin_claim_id, origin_decision_id, responsible_seat,
        ),
    )
    return tid


def create_task(data: M.TaskCreate, user_id: str) -> dict[str, Any]:
    conn = get_connection()
    with ve_write_transaction(conn, purpose="create_task"):
        _guard_legacy_write(
            conn,
            _resolve_task_payload_subtree(conn, data.parent_task_id, data.project_id, user_id),
            target_id=None,
            target_kind="task",
        )
        tid = _insert_task(conn, data, user_id)
        _commit_if_owner(conn)
    out = get_task(tid, user_id) or {}
    _log_ve_entity_activity(
        type=ActivityType.TASK_CREATED.value,
        entity_type=ActivityEntityType.TASK.value,
        entity_id=tid,
        user_id=user_id,
        related_entity_id=_ve_activity_related_id(data.project_id),
        detail=f"title={(data.title or '')[:120]!r}",
    )
    return out


# --- Seat task proposals (Firebrand task-context, server-owned) -----------
#
# A model proposes; a user authorizes; the application executes. The
# proposal record is the durable transaction record — never the reply
# text, never mutable task notes. C1 provenance (revision review
# 2026-11-03): recording verifies the source message belongs to the
# caller's conversation, is an assistant message attributed to
# champion, and contains the identified block, and the submitted
# proposal must match that block. C3: PATCH / decline / approve are
# conditional on state='pending' under the same transactional
# discipline, so no transition can silently race another.


class ProposalNotFound(Exception):
    """Proposal missing or foreign. Routes map this to 404, never a leak."""


class ProposalConflict(Exception):
    """Proposal in a terminal state for the requested transition. Routes
    map this to 409; nothing changes."""


_PROPOSAL_FENCE_RE = re.compile(r"```task-proposal\s*\n(.*?)```", re.DOTALL)
_PROPOSAL_STATES = ("pending", "approved", "declined")

# W1 (Q1): the only seats whose assistant messages may carry
# proposals. The seat is read from the message itself, never from
# client claims. Firebrand (champion) is the first proposer; other
# seats join only when their own producer slice authorizes them.
ENABLED_PROPOSER_SEATS = frozenset({"champion"})
_PROPOSAL_COLUMNS = (
    "id, user_id, conversation_id, source_message_id, block_index, proposal_index, "
    "seat, title, parent_task_id, timeframe_commitment, due_date, notes, state, "
    "created_task_id, created_at, updated_at, decided_at, "
    "evidence_quote, original_title, original_parent_task_id, "
    "original_timeframe_commitment, original_due_date, original_notes"
)


def _migrate_task_proposals(conn: sqlite3.Connection) -> None:
    """Create the task_proposals table if missing (fresh and existing DBs).

    The UNIQUE triple is the re-attachment identity: re-recording the
    same triple is idempotent and must never overwrite stored contents
    (an edit or terminal decision survives re-recording).

    W0B adds six nullable columns (evidence_quote + the original_*
    snapshot columns). Fresh DBs get them from the CREATE TABLE below;
    existing DBs get them from the PRAGMA-checked ALTERs after it.
    Columns are NULLABLE with no default and are NEVER backfilled:
    legacy originals are unknowable (live values may already have been
    edited in place), so copying live values into original_* would
    fabricate an original. The W1 record path copies submitted values
    into original_* in the SAME INSERT as the live values, and the
    server verifies the evidence_quote against the source message.
    Until then they read NULL (absent = absent).
    """
    conn.execute(
        """CREATE TABLE IF NOT EXISTS task_proposals (
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
          evidence_quote TEXT,
          original_title TEXT,
          original_parent_task_id TEXT,
          original_timeframe_commitment TEXT,
          original_due_date TEXT,
          original_notes TEXT,
          UNIQUE(user_id, source_message_id, block_index, proposal_index)
        )"""
    )
    # S3 (verdict OQ5): node-scoped proposal lookup by exact parent.
    # The table is created here, not in schema.sql, so its index lives
    # here too — CREATE INDEX IF NOT EXISTS is idempotent on existing DBs.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_proposals_user_parent "
        "ON task_proposals (user_id, parent_task_id, state)"
    )
    # W2: owner-scoped proposal reverse lookup by created task (the
    # execution block's provenance read). No (user_id, created_task_id)
    # index existed at 8761278; the lookup is bounded (one per rendered
    # task, at most 10 per block) but the index keeps it a seek, not a
    # scan.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_proposals_user_created_task "
        "ON task_proposals (user_id, created_task_id)"
    )
    for column in (
        "evidence_quote",
        "original_title",
        "original_parent_task_id",
        "original_timeframe_commitment",
        "original_due_date",
        "original_notes",
    ):
        info = conn.execute("PRAGMA table_info(task_proposals)")
        if not any(r[1] == column for r in info.fetchall()):
            conn.execute(f"ALTER TABLE task_proposals ADD COLUMN {column} TEXT")
    conn.commit()


def _parse_task_proposal_blocks(body: str | None) -> list[list[dict[str, Any]] | None]:
    """Parse fenced ```task-proposal blocks from reply text, in order.

    One entry per block: a list of raw proposal objects, or None when
    the block's JSON is malformed or lacks a proposals list. Malformed
    blocks can never record — provenance fails on them.
    """
    blocks: list[list[dict[str, Any]] | None] = []
    for m in _PROPOSAL_FENCE_RE.finditer(body or ""):
        try:
            data = json.loads(m.group(1))
        except Exception:
            blocks.append(None)
            continue
        proposals = data.get("proposals") if isinstance(data, dict) else None
        if not isinstance(proposals, list):
            blocks.append(None)
            continue
        blocks.append([p for p in proposals if isinstance(p, dict)])
    return blocks


def _strict_due_date(value: Any) -> str | None:
    """Normalize a due-date value: None or strict %Y-%m-%d, else ValueError."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        raise ValueError(f"Invalid due_date: {value!r} (expected YYYY-MM-DD or null)")
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"Invalid due_date: {value!r} (expected YYYY-MM-DD or null)")
    return s


def _normalize_proposal(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize one proposal to stored shape, validating as we go.
    Unknown fields are ignored (forward-compatible)."""
    if not isinstance(raw, dict):
        raise ValueError("Proposal must be an object")
    title = str(raw.get("title") or "").strip()
    if not title:
        raise ValueError("Proposal title must be non-empty")
    timeframe = raw.get("timeframe_commitment")
    if timeframe is not None and timeframe != "tentative":
        raise ValueError(
            f"Invalid timeframe_commitment: {timeframe!r} (expected null or 'tentative')"
        )
    parent = raw.get("parent_task_id")
    parent = str(parent).strip() if parent else None
    return {
        "title": title,
        "parent_task_id": parent,
        "timeframe_commitment": timeframe,
        "due_date": _strict_due_date(raw.get("due_date")),
        "notes": str(raw.get("notes") or ""),
    }


def _proposal_row_to_dict(row: tuple) -> dict[str, Any]:
    return {
        "id": row[0],
        "user_id": row[1],
        "conversation_id": row[2],
        "source_message_id": row[3],
        "block_index": row[4],
        "proposal_index": row[5],
        "seat": row[6],
        "title": row[7],
        "parent_task_id": row[8],
        "timeframe_commitment": row[9],
        "due_date": row[10],
        "notes": row[11],
        "state": row[12],
        "created_task_id": row[13],
        "created_at": row[14],
        "updated_at": row[15],
        "decided_at": row[16],
        # W1: evidence_quote + original_* are populated by the record
        # path in the SAME INSERT as the live values (never editable
        # after); NULL on legacy rows, which predate the snapshot.
        "evidence_quote": row[17],
        "original_title": row[18],
        "original_parent_task_id": row[19],
        "original_timeframe_commitment": row[20],
        "original_due_date": row[21],
        "original_notes": row[22],
        # W1 (C-2): grounding flag, computed on read from the live
        # title and the stored quote — lexical correspondence only,
        # never verified meaning. None on legacy rows with no quote.
        "grounding_flag": _grounding_flag(row[7], row[17]),
    }


def _get_proposal_row(
    conn: sqlite3.Connection, proposal_id: str, user_id: str
) -> tuple | None:
    return conn.execute(
        f"SELECT {_PROPOSAL_COLUMNS} FROM task_proposals WHERE id = ? AND user_id = ?",
        (proposal_id, user_id),
    ).fetchone()


# -- W1 producer helpers ------------------------------------------------------

_EVIDENCE_QUOTE_MAX_CHARS = 500


def _normalize_whitespace(value: Any) -> str:
    """Collapse every whitespace run to one space and strip. None (or
    a whitespace-only value) normalizes to the empty string."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def _strip_proposal_blocks(text: str | None) -> str:
    """The proposing turn's prose: the message body with every fenced
    ```task-proposal block removed. The block itself never counts as
    evidence — only the prose around it does."""
    return _PROPOSAL_FENCE_RE.sub("", text or "")


# W1 (C-2, founder verdict Refinement 3): grounding is lexical
# correspondence, never verified meaning. "words_matched" = every
# significant title word appears in the quote; "summarized" = the
# title uses wording beyond the quote. The card always shows the
# exact quote beside the label, so the user sees what the label
# actually rests on. Known limit, pinned by test: negation is
# invisible to this check — "not"/"no" and contraction fragments
# are stopwords, so "Call the clinic" against "don't call the
# clinic" reads words_matched. That is the documented limit of a
# lexical check, not a claim about meaning.
_GROUNDING_STOPWORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "of", "to", "for", "in", "on",
        "at", "by", "with", "from", "is", "are", "was", "were", "be",
        "been", "it", "its", "this", "that", "these", "those", "i",
        "you", "he", "she", "we", "they", "my", "our", "your", "his",
        "her", "their", "me", "him", "us", "them", "please", "let",
        "lets", "do", "does", "did", "can", "could", "should",
        "would", "will", "shall", "may", "might", "must", "have",
        "has", "had", "am", "as", "so", "if", "then", "than", "but",
        "when", "while", "about", "into", "over", "under", "up",
        "down", "out", "off", "again", "further", "once", "here",
        "there", "all", "any", "both", "each", "few", "more", "most",
        "other", "some", "such", "only", "own", "same", "too",
        "very", "just", "also", "now", "how", "what", "which",
        "who", "whom", "why", "where", "not", "no", "nor",
        # Contraction fragments left by splitting on the apostrophe
        # ("don't" -> "don", "t"): stopwords so a contraction never
        # counts as a significant word on either side.
        "don", "t", "ll", "re", "ve", "s", "d", "m",
    }
)


def _content_tokens(text: str | None) -> set[str]:
    """Lowercased alphanumeric tokens minus the stopword list."""
    return {
        tok
        for tok in re.split(r"[^a-z0-9]+", (text or "").lower())
        if tok and tok not in _GROUNDING_STOPWORDS
    }


def _grounding_flag(title: str | None, evidence_quote: str | None) -> str | None:
    """Lexical correspondence between a live title and its stored
    quote: "words_matched" when every significant title word appears
    in the quote, "summarized" otherwise; None when there is no
    quote (legacy rows). Computed on read, so an edited title
    recomputes. A title with no significant words is vacuously
    words_matched."""
    if not evidence_quote:
        return None
    title_tokens = _content_tokens(title)
    if not title_tokens:
        return "words_matched"
    return (
        "words_matched"
        if title_tokens <= _content_tokens(evidence_quote)
        else "summarized"
    )


def check_parent_available(
    conn: sqlite3.Connection, parent_task_id: str | None, user_id: str
) -> str | None:
    """None when the parent may be used; else the reason it may not.

    Owner-scoped: a parent that does not exist under this user reads
    as unavailable — the same copy as a terminal parent, never "not
    yours". Terminal parents (Done/Dropped/completed/Closed — W1
    Refinement 1) block. Callers decide the error shape: PATCH raises
    ValueError (400), approval raises ProposalConflict (409).
    """
    if parent_task_id is None:
        return None
    row = conn.execute(
        "SELECT status FROM tasks WHERE id = ? AND user_id = ?",
        (parent_task_id, user_id),
    ).fetchone()
    if row is None:
        return "Parent task is no longer available."
    if _is_terminal_parent_status(row[0]):
        return "Parent task is no longer available."
    return None


def _reject_keystone_project(project_id: str | None, user_id: str) -> None:
    """Guard B (W1): a W1-created task must never land in a keystone
    project. Raises ValueError when the project belongs to the user's
    keystone initiative; passes (including project_id=None) otherwise.
    Called from approve only — NOT from shared _insert_task, so the
    keystone seeder's own writes are untouched. Vacuous in W1 (the
    approve path passes no project_id) but wired so the guard exists
    if the path ever gains one."""
    if project_id is None:
        return
    from local_ai.vision_execution import keystone_seeding

    initiative = keystone_seeding.find_keystone_initiative(user_id)
    if initiative is None:
        return
    project = get_project(project_id, user_id)
    if project is not None and project.get("initiative_id") == initiative["id"]:
        raise ValueError("W1 tasks may not be created in a keystone project")


def record_task_proposal(
    user_id: str,
    payload: dict[str, Any],
    conversation_store: Any = None,
) -> dict[str, Any]:
    """Validate + provenance-verify + record a pending proposal.

    Order matters: field validation, then the triple lookup (an
    existing triple returns the STORED record untouched — re-recording
    never undoes an edit or terminal decision, and is not re-checked
    against the quote), then C1 provenance verification against the
    source message, then C-1 evidence-quote verification against the
    turn's prose, then parent ownership, then insert. A fabricated
    source id reads as 404; a real message that is not a champion
    assistant message, a block that does not match the submission, or
    a quote that is missing, empty, over-long, or not verbatim reads
    as 400.
    """
    try:
        block_index = int(payload.get("block_index"))
        proposal_index = int(payload.get("proposal_index"))
    except (TypeError, ValueError):
        raise ValueError("block_index and proposal_index must be integers")
    if block_index < 0 or proposal_index < 0:
        raise ValueError("block_index and proposal_index must be non-negative")
    conversation_id = str(payload.get("conversation_id") or "").strip()
    source_message_id = str(payload.get("source_message_id") or "").strip()
    if not conversation_id or not source_message_id:
        raise ValueError("conversation_id and source_message_id are required")
    submitted = _normalize_proposal(payload)

    conn = get_connection()
    existing = conn.execute(
        "SELECT " + _PROPOSAL_COLUMNS + " FROM task_proposals "
        "WHERE user_id = ? AND source_message_id = ? AND block_index = ? AND proposal_index = ?",
        (user_id, source_message_id, block_index, proposal_index),
    ).fetchone()
    if existing is not None:
        # Idempotent re-record: return stored contents, never overwrite.
        return _proposal_row_to_dict(tuple(existing))

    if conversation_store is None:
        from local_ai.conversation.store import ConversationStore

        conversation_store = ConversationStore()
    msg = conversation_store.get_message(user_id, conversation_id, source_message_id)
    if msg is None:
        raise ProposalNotFound("Source message not found")
    if msg.get("role") != "voice":
        raise ValueError("Source message is not an assistant message")
    if msg.get("archetype_id") not in ENABLED_PROPOSER_SEATS:
        raise ValueError("Source message is not attributed to an enabled proposer")
    blocks = _parse_task_proposal_blocks(msg.get("body"))
    if block_index >= len(blocks) or blocks[block_index] is None:
        raise ValueError("Source message does not contain the identified proposal block")
    block = blocks[block_index]
    if proposal_index >= len(block):
        raise ValueError("Proposal index out of range in the source block")
    if _normalize_proposal(block[proposal_index]) != submitted:
        raise ValueError("Submitted proposal does not match the source block")

    # W1 (C-1): the evidence quote must be a verbatim span of the
    # proposing turn's PROSE — the structured block itself does not
    # count. The client-supplied quote is a candidate, not trusted
    # evidence: the server checks it against the source message's
    # actual prose. Missing, empty, over-long, or non-verbatim
    # quotes are rejected with 400 and no row is written. The
    # stored quote is the NORMALIZED form.
    evidence_quote = _normalize_whitespace(payload.get("evidence_quote"))
    if not evidence_quote:
        raise ValueError("evidence_quote is required")
    if len(evidence_quote) > _EVIDENCE_QUOTE_MAX_CHARS:
        raise ValueError("evidence_quote exceeds 500 characters")
    prose = _normalize_whitespace(_strip_proposal_blocks(msg.get("body")))
    if evidence_quote not in prose:
        raise ValueError("evidence_quote is not a verbatim span of the proposing turn's prose")

    _ensure_owned_reference(
        conn,
        table="tasks",
        ref_id=submitted["parent_task_id"],
        user_id=user_id,
        field_name="parent_task_id",
    )
    now = _now()
    pid = M.new_id()
    with ve_write_transaction(conn, purpose="record_task_proposal"):
        # Race re-check: a concurrent record of the same triple may
        # have committed between the pre-check above and the helper
        # enter. Re-checking inside the transaction makes the
        # idempotent re-record race-safe (return the stored row
        # instead of an IntegrityError on the triple).
        existing = conn.execute(
            "SELECT " + _PROPOSAL_COLUMNS + " FROM task_proposals "
            "WHERE user_id = ? AND source_message_id = ? AND block_index = ? AND proposal_index = ?",
            (user_id, source_message_id, block_index, proposal_index),
        ).fetchone()
        if existing is not None:
            return _proposal_row_to_dict(tuple(existing))
        _guard_legacy_write(
            conn,
            _resolve_task_subtree(conn, submitted["parent_task_id"], user_id)
            if submitted["parent_task_id"]
            else None,
            target_id=pid,
            target_kind="task_proposal",
        )
        conn.execute(
            """INSERT INTO task_proposals (
              id, user_id, conversation_id, source_message_id, block_index, proposal_index,
              seat, title, parent_task_id, timeframe_commitment, due_date, notes, state,
              created_task_id, created_at, updated_at, decided_at,
              evidence_quote, original_title, original_parent_task_id,
              original_timeframe_commitment, original_due_date, original_notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL, ?, ?, NULL,
              ?, ?, ?, ?, ?, ?)""",
            (
                pid, user_id, conversation_id, source_message_id, block_index, proposal_index,
                msg.get("archetype_id"), submitted["title"], submitted["parent_task_id"],
                submitted["timeframe_commitment"], submitted["due_date"], submitted["notes"],
                now, now,
                # W1: the quote + the originals are copied in this SAME
                # INSERT, never editable after. The originals are the
                # submitted values as recorded, not the live values.
                evidence_quote, submitted["title"], submitted["parent_task_id"],
                submitted["timeframe_commitment"], submitted["due_date"], submitted["notes"],
            ),
        )
        _commit_if_owner(conn)
    row = _get_proposal_row(conn, pid, user_id)
    return _proposal_row_to_dict(tuple(row)) if row else {}


def list_task_proposals(
    user_id: str,
    conversation_id: str,
    state: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Proposals for one user conversation, oldest first. Card hydration
    reads this — never client memory. Every row is predicated on the
    caller's id, so another user's rows can never match."""
    if state is not None and state not in _PROPOSAL_STATES:
        raise ValueError(f"Invalid proposal state filter: {state!r}")
    try:
        limit = max(1, min(int(limit), 500))
    except (TypeError, ValueError):
        limit = 100
    conn = get_connection()
    if state is None:
        cur = conn.execute(
            "SELECT " + _PROPOSAL_COLUMNS + " FROM task_proposals "
            "WHERE user_id = ? AND conversation_id = ? ORDER BY created_at ASC, rowid ASC LIMIT ?",
            (user_id, conversation_id, limit),
        )
    else:
        cur = conn.execute(
            "SELECT " + _PROPOSAL_COLUMNS + " FROM task_proposals "
            "WHERE user_id = ? AND conversation_id = ? AND state = ? ORDER BY created_at ASC, rowid ASC LIMIT ?",
            (user_id, conversation_id, state, limit),
        )
    return [_proposal_row_to_dict(tuple(r)) for r in cur.fetchall()]


def count_pending_task_proposals(
    user_id: str, connection: sqlite3.Connection | None = None
) -> int:
    """User-wide count of pending task proposals (Slice 2 retained count).

    ``list_task_proposals`` is per-conversation only; the framework
    surface needs the user-wide pending count (Rev2 §4.2 retained
    information for R5). Count-only, owner-scoped, no rows returned.
    ``connection`` is injectable for tests; otherwise the default
    vision-execution connection is used.
    """
    conn = connection if connection is not None else get_connection()
    cur = conn.execute(
        "SELECT COUNT(*) FROM task_proposals "
        "WHERE user_id = ? AND state = 'pending'",
        (user_id,),
    )
    row = cur.fetchone()
    return int(row[0]) if row is not None else 0


def list_pending_task_proposals(
    user_id: str, connection: sqlite3.Connection | None = None
) -> list[dict[str, Any]]:
    """User-wide pending task proposals, oldest first (Firebrand S1).

    ``list_task_proposals`` is per-conversation only; the lightning
    round's queue is user-wide (OQ3: any conversation). Owner-scoped,
    full rows — the same dicts the card hydrates from. ``connection``
    is injectable for tests; otherwise the default vision-execution
    connection is used.
    """
    conn = connection if connection is not None else get_connection()
    cur = conn.execute(
        "SELECT " + _PROPOSAL_COLUMNS + " FROM task_proposals "
        "WHERE user_id = ? AND state = 'pending' "
        "ORDER BY created_at ASC, rowid ASC",
        (user_id,),
    )
    return [_proposal_row_to_dict(tuple(r)) for r in cur.fetchall()]


def get_task_proposal(
    user_id: str, proposal_id: str, connection: sqlite3.Connection | None = None
) -> dict[str, Any] | None:
    """One task proposal, strictly per-user (Firebrand S1).

    A foreign id returns None, indistinguishable from a missing one —
    the same fail-closed pattern as the conversation store's
    get_message, so callers cannot probe another user's proposals.
    ``connection`` is injectable for tests.
    """
    conn = connection if connection is not None else get_connection()
    row = conn.execute(
        "SELECT " + _PROPOSAL_COLUMNS + " FROM task_proposals "
        "WHERE user_id = ? AND id = ?",
        (user_id, proposal_id),
    ).fetchone()
    if row is None:
        return None
    return _proposal_row_to_dict(tuple(row))


def list_task_proposals_by_parent(
    user_id: str,
    parent_task_id: str,
    state: str | None = "pending",
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Proposals for one parent task, oldest first (S3, verdict OQ5).

    Exact parent match only: ``parent_task_id`` must equal the focused
    task id. A proposal with ``parent_task_id IS NULL`` or a different
    parent is omitted, even if it belongs to the same conversation —
    conversation membership does not establish node relevance. No
    descendant traversal. ``user_id`` is required (no default); an
    invalid state raises ValueError, same as ``list_task_proposals``.
    """
    if state is not None and state not in _PROPOSAL_STATES:
        raise ValueError(f"Invalid proposal state filter: {state!r}")
    try:
        limit = max(1, min(int(limit), 500))
    except (TypeError, ValueError):
        limit = 100
    conn = get_connection()
    if state is None:
        cur = conn.execute(
            "SELECT " + _PROPOSAL_COLUMNS + " FROM task_proposals "
            "WHERE user_id = ? AND parent_task_id = ? "
            "ORDER BY created_at ASC, rowid ASC LIMIT ?",
            (user_id, parent_task_id, limit),
        )
    else:
        cur = conn.execute(
            "SELECT " + _PROPOSAL_COLUMNS + " FROM task_proposals "
            "WHERE user_id = ? AND parent_task_id = ? AND state = ? "
            "ORDER BY created_at ASC, rowid ASC LIMIT ?",
            (user_id, parent_task_id, state, limit),
        )
    return [_proposal_row_to_dict(tuple(r)) for r in cur.fetchall()]


def get_proposals_by_created_task(
    user_id: str, created_task_id: str
) -> list[dict[str, Any]]:
    """W2 provenance read: proposals that created one task.

    Owner-scoped reverse lookup by ``created_task_id``. Returns every
    matching row (normally zero or one); the caller must never choose
    between multiple matches — ambiguity degrades to weaker wording.
    ``user_id`` is required (no default); an empty owner raises.
    ``created_task_id`` empty returns [] (no row can match it).
    """
    _require_owner_id(user_id)
    if not created_task_id:
        return []
    conn = get_connection()
    cur = conn.execute(
        "SELECT " + _PROPOSAL_COLUMNS + " FROM task_proposals "
        "WHERE user_id = ? AND created_task_id = ? "
        "ORDER BY created_at ASC, rowid ASC",
        (user_id, created_task_id),
    )
    return [_proposal_row_to_dict(tuple(r)) for r in cur.fetchall()]


def update_task_proposal(
    user_id: str, proposal_id: str, patch: dict[str, Any]
) -> dict[str, Any]:
    """Edit a PENDING proposal in place, fully re-validated.

    Conditional update: succeeds only while state='pending'. A
    terminal record yields 409 (via ProposalConflict) and changes
    nothing; a missing or foreign id yields 404.
    """
    allowed = ("title", "parent_task_id", "timeframe_commitment", "due_date", "notes")
    values: dict[str, Any] = {}
    for key in allowed:
        if key in patch:
            values[key] = patch[key]
    if "title" in values:
        values["title"] = str(values["title"] or "").strip()
        if not values["title"]:
            raise ValueError("Proposal title must be non-empty")
    if "timeframe_commitment" in values:
        _validate_timeframe_commitment(values["timeframe_commitment"])
    if "due_date" in values:
        values["due_date"] = _strict_due_date(values["due_date"])
    if "parent_task_id" in values:
        parent = values["parent_task_id"]
        values["parent_task_id"] = str(parent).strip() if parent else None
    if "notes" in values:
        values["notes"] = str(values["notes"] or "")
    if not values:
        row = _get_proposal_row(get_connection(), proposal_id, user_id)
        if row is None:
            raise ProposalNotFound("Proposal not found")
        return _proposal_row_to_dict(tuple(row))

    conn = get_connection()
    _ensure_owned_reference(
        conn,
        table="tasks",
        ref_id=values.get("parent_task_id"),
        user_id=user_id,
        field_name="parent_task_id",
    )
    if "parent_task_id" in values:
        # W1 (Q1/Q5): a terminal parent blocks the edit. Ownership
        # (400) is already validated above; this adds terminal status
        # only. A null parent always passes.
        if check_parent_available(conn, values["parent_task_id"], user_id) is not None:
            raise ValueError("Parent task is unavailable")
    sets = ", ".join(f"{k} = ?" for k in values) + ", updated_at = ?"
    args = list(values.values()) + [_now(), proposal_id, user_id]
    with ve_write_transaction(conn, purpose="update_task_proposal"):
        prow = conn.execute(
            "SELECT parent_task_id FROM task_proposals WHERE id = ? AND user_id = ?",
            (proposal_id, user_id),
        ).fetchone()
        _guard_legacy_write(
            conn,
            _resolve_task_subtree(conn, prow[0], user_id)
            if prow is not None and prow[0]
            else None,
            target_id=proposal_id,
            target_kind="task_proposal",
        )
        cur = conn.execute(
            f"UPDATE task_proposals SET {sets} WHERE id = ? AND user_id = ? AND state = 'pending'",
            args,
        )
        _commit_if_owner(conn)
    if cur.rowcount == 0:
        row = _get_proposal_row(conn, proposal_id, user_id)
        if row is None:
            raise ProposalNotFound("Proposal not found")
        raise ProposalConflict(f"Proposal is already {row[12]}")
    row = _get_proposal_row(conn, proposal_id, user_id)
    return _proposal_row_to_dict(tuple(row)) if row else {}


def decline_task_proposal(user_id: str, proposal_id: str) -> dict[str, Any]:
    """Decline a proposal. Conditional on pending, but idempotent:
    re-declining an already-declined proposal returns the same record
    with 200, not an error. Declining an approved proposal is a 409."""
    conn = get_connection()
    cur = conn.execute(
        "UPDATE task_proposals SET state = 'declined', decided_at = ? "
        "WHERE id = ? AND user_id = ? AND state = 'pending'",
        (_now(), proposal_id, user_id),
    )
    conn.commit()
    if cur.rowcount == 0:
        row = _get_proposal_row(conn, proposal_id, user_id)
        if row is None:
            raise ProposalNotFound("Proposal not found")
        d = _proposal_row_to_dict(tuple(row))
        if d["state"] == "declined":
            return d
        raise ProposalConflict(f"Proposal is already {d['state']}")
    row = _get_proposal_row(conn, proposal_id, user_id)
    return _proposal_row_to_dict(tuple(row)) if row else {}


def approve_task_proposal(user_id: str, proposal_id: str) -> dict[str, Any]:
    """Atomically approve a proposal: create the task and record the
    outcome in ONE transaction. Returns {"task": ..., "proposal": ...}.

    BEGIN IMMEDIATE + compare-and-swap claim: only the session whose
    UPDATE matches a pending row proceeds to insert; the loser rolls
    back, re-reads, and returns the winner's task. Approval reads the
    FINAL edited values inside its transaction, so a concurrent edit
    cannot silently race approval: either the edit lands first (and
    approval writes the edited values) or it lands after the claim
    (and sees a terminal record → 409). Validation failure rolls
    back the claim too, leaving the proposal pending so the user can
    edit and retry; nothing is written.

    C2 — approval outcome vs activity log: the durable approval
    outcome is the proposal row + task row committed together. The
    task activity log is NOT part of that transaction: it is a
    file-backed append (activity.log via local_ai.activity), not a
    database write, so it cannot participate in this SQLite
    transaction. It stays a post-commit effect exactly as create_task
    does today, and its failure — already swallowed inside
    _log_ve_entity_activity — never rolls back or retries the
    creation. One approved proposal → one created task → one durable
    approval outcome, independent of the log.
    """
    conn = get_connection()
    now = _now()
    with ve_write_transaction(conn, purpose="approve_task_proposal"):
        # Pre-read the proposal inside the helper; guard only while
        # state is 'pending'. A re-approval of an already-decided
        # proposal writes nothing, so it skips the guard and follows
        # the existing rowcount==0 return-winner/raise-conflict path
        # below — the documented idempotent re-approval, preserved
        # exactly.
        _prow = conn.execute(
            "SELECT " + _PROPOSAL_COLUMNS + " FROM task_proposals WHERE id = ? AND user_id = ?",
            (proposal_id, user_id),
        ).fetchone()
        if _prow is not None:
            _pd = _proposal_row_to_dict(tuple(_prow))
            if _pd["state"] == "pending":
                _guard_legacy_write(
                    conn,
                    _resolve_task_subtree(conn, _pd["parent_task_id"], user_id)
                    if _pd["parent_task_id"]
                    else None,
                    target_id=proposal_id,
                    target_kind="task_proposal",
                )
        try:
            cur = conn.execute(
                "UPDATE task_proposals SET state = 'approved', decided_at = ? "
                "WHERE id = ? AND user_id = ? AND state = 'pending'",
                (now, proposal_id, user_id),
            )
            if cur.rowcount == 0:
                _rollback_if_owner(conn)
                row = _get_proposal_row(conn, proposal_id, user_id)
                if row is None:
                    raise ProposalNotFound("Proposal not found")
                d = _proposal_row_to_dict(tuple(row))
                if d["state"] == "approved":
                    task = get_task(d["created_task_id"], user_id) if d["created_task_id"] else None
                    return {"task": task or {}, "proposal": d}
                raise ProposalConflict(f"Proposal is already {d['state']}")
            row = conn.execute(
                "SELECT " + _PROPOSAL_COLUMNS + " FROM task_proposals WHERE id = ? AND user_id = ?",
                (proposal_id, user_id),
            ).fetchone()
            proposal = _proposal_row_to_dict(tuple(row))
            # Re-validate the final edited values inside the transaction.
            if not str(proposal["title"] or "").strip():
                raise ValueError("Proposal title must be non-empty")
            _validate_timeframe_commitment(proposal["timeframe_commitment"])
            _strict_due_date(proposal["due_date"])
            _ensure_owned_reference(
                conn,
                table="tasks",
                ref_id=proposal["parent_task_id"],
                user_id=user_id,
                field_name="parent_task_id",
            )
            # W1 (Q1/Q5): the parent-availability check, revalidated
            # inside the approval transaction. Ownership (400) is already
            # re-validated above, so reaching here with a reason means
            # the parent exists but is terminal. 409 with guidance; the
            # claim rolls back, the proposal stays pending, and the
            # system never re-parents, never declines, never creates
            # parentless.
            if check_parent_available(conn, proposal["parent_task_id"], user_id) is not None:
                raise ProposalConflict(
                    "Parent task is no longer available. Edit the proposal to "
                    "choose a different parent (or no parent), or decline it."
                )
            data = M.TaskCreate(
                title=proposal["title"],
                parent_task_id=proposal["parent_task_id"],
                status="Todo",
                timeframe_commitment=proposal["timeframe_commitment"],
                due_date=proposal["due_date"],
                notes=proposal["notes"],
                # W1 Guard A: the deliberation-path write to seat_ref is
                # REMOVED. Keystone seeding is the only seat_ref writer;
                # a W1-created task carries no seat_ref.
                seat_ref="",
            )
            # W1 Guard B: a W1-created task never lands in a keystone
            # project. Vacuous today (approve passes no project_id) but
            # wired so the guard exists if the path ever gains one.
            _reject_keystone_project(data.project_id, user_id)
            tid = _insert_task(
                conn,
                data,
                user_id,
                origin_seat=proposal["seat"],
                origin_conversation_id=proposal["conversation_id"],
                origin_message_id=proposal["source_message_id"],
                # W1 Refinement 2 (Q4): origin_decision_id stays NULL.
                # There is no proposal-specific column on tasks, and
                # storing the proposal row's id in the decision field
                # would make it polymorphic. The proposal row itself is
                # the anchor: proposal.created_task_id -> created task,
                # and the task's origin_conversation_id +
                # origin_message_id -> source message, all owner-scoped.
                origin_claim_id=None,
                origin_decision_id=None,
                responsible_seat=None,
            )
            conn.execute(
                # W3 §0 correction 1: the state guard closes the one
                # unguarded UPDATE on task_proposals. Vacuous today — this
                # runs immediately after the compare-and-swap claim inside
                # the approval transaction — but a future refactor must not
                # be able to overwrite created_task_id on an approved row.
                "UPDATE task_proposals SET created_task_id = ? WHERE id = ? AND state = 'approved'",
                (tid, proposal_id),
            )
            _commit_if_owner(conn)
        except Exception:
            _rollback_if_owner(conn)
            raise
    task = get_task(tid, user_id) or {}
    _log_ve_entity_activity(
        type=ActivityType.TASK_CREATED.value,
        entity_type=ActivityEntityType.TASK.value,
        entity_id=tid,
        user_id=user_id,
        related_entity_id=_ve_activity_related_id(None),
        detail=f"title={(proposal['title'] or '')[:120]!r}",
    )
    row = _get_proposal_row(conn, proposal_id, user_id)
    proposal = _proposal_row_to_dict(tuple(row)) if row else {}
    return {"task": task, "proposal": proposal}


class UploadOutcomeStuckError(Exception):
    """An upload outcome is stuck in 'creating' with no carrier row
    (reconciliation §6.3 R2: crash before the VE commit). The
    diagnostic surfaces it. A retry is refused while the outcome is
    younger than one hour ('Still creating — check back shortly');
    an older one may be re-claimed (amendment A4 step 1b). Routes
    map this to 409 with the diagnostic copy."""


#: Amendment A4: the re-claim staleness gate — a 'creating' outcome
#: younger than this is presumed live, not dead. One hour, the
#: diagnostic's threshold (reconciliation §6.3).
_UPLOAD_RECLAIM_STALE_S = 3600


def _upload_outcome_age_s(outcome: dict[str, Any]) -> float | None:
    """An outcome row's age in seconds from its created_at, or None
    when the timestamp is missing / unparseable. The age is the
    re-claim gate's input (amendment A4); an unknown age refuses
    the retry (the safe default — the outcome might be live)."""
    try:
        created = datetime.fromisoformat(
            str(outcome.get("created_at") or "").replace("Z", "+00:00")
        )
    except ValueError:
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - created).total_seconds()


def get_upload_outcome_creation(
    user_id: str, outcome_id: str
) -> dict[str, Any] | None:
    """The carrier row for one outcome (U-1), owner-scoped — the
    durable idempotency record for replay / R1 recovery. None when
    no VE record was ever committed for this outcome."""
    conn = get_connection()
    row = conn.execute(
        "SELECT outcome_id, user_id, ve_kind, ve_id, node_id, created_at "
        "FROM upload_outcome_creations WHERE outcome_id = ? AND user_id = ?",
        (outcome_id, user_id),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def approve_upload_outcome(
    user_id: str,
    outcome_id: str,
    *,
    kind: str,
    title: str,
    detail: str,
    parent_id: str | None = None,
    conversation_id: str | None = None,
    lens_seat: str | None = None,
    store: Any | None = None,
) -> dict[str, Any]:
    """Approve one upload outcome: create the VE record and record
    the creation in ONE VE transaction (§8.1, U-1).

    Follows approve_task_proposal's contract shape, adapted to the
    two-DB reality (W3: the VE and ConversationStore DBs are
    SEPARATE — no shared transaction; read-time exclusion is the
    mandatory guarantee):

    1. Claim the outcome (ConversationStore, BEGIN IMMEDIATE via
       claim_upload_outcome): only the session whose UPDATE matches
       a 'pending' row proceeds. Rowcount 0 → the outcome was
       already decided: a 'created' outcome replays (the carrier
       row returns the existing VE record); a 'creating' outcome
       WITH a carrier row is R1 (the retry tap heals it to
       'created', reconciliation §6.3 R3 — no other read heals it);
       a 'creating' outcome WITHOUT a carrier row is R2 — the
       retry re-claim (amendment A4 step 1b) when the outcome is
       older than one hour, else refused ('Still creating').
    2. Create the VE record + carrier row (VE DB, one
       ve_write_transaction): the _insert_* helper + the
       upload_outcome_creations insert commit together, or neither
       does. A validation failure rolls back the claim too (the
       outcome returns to 'pending' so the user can edit and
       retry); nothing is written. A carrier-insert PRIMARY KEY
       failure (a concurrent creation committed first) re-reads
       the carrier row and returns the existing VE record (case
       (iii)) instead of surfacing an error.
    3. Mark the outcome 'created' (ConversationStore) with its
       ve_kind / ve_id, and flip the interpretation to 'ruled' —
       the verdict has landed, so the reading leaves the queue.

    R-label mapping footnote (amendment A4): the brief's R1–R4 do
    not map onto reconciliation §6.3's R1–R4. Brief R1 =
    reconciliation R3 (crash after VE commit, before outcome
    'created'); brief R2 = reconciliation R2 (crash before VE
    commit); brief R3 = reconciliation R4 (duplicate tap during
    creation); brief R4 is new (the §8.1 step-1 CAS loser).

    Parentage (U-4; the VE mapping is the brief's open point — the
    chooser lists recent PROJECTS): a task nests under the chosen
    project (project_id); a project sits alongside it under the
    same initiative (initiative_id inherited); an idea takes no VE
    parent (the choice is recorded on the outcome row only).
    Default root (parent_id None): top-level task / root project.

    Returns {"outcome": ..., "record": ..., "replayed": bool}.
    The activity log is a post-commit effect, exactly as
    create_task does (its failure never rolls back the creation).
    """
    from local_ai.conversation.store import ConversationStore

    if kind not in ("project", "task", "idea"):
        raise ValueError(f"Unknown outcome kind: {kind!r}")
    title = (title or "").strip()
    if not title:
        raise ValueError("Outcome title must be non-empty")
    store = store if store is not None else ConversationStore()
    outcome = store.get_upload_outcome(user_id, outcome_id)
    if outcome is None:
        raise ValueError(f"Outcome not found: {outcome_id!r}")
    status = outcome.get("status")
    if status == "created":
        carrier = get_upload_outcome_creation(user_id, outcome_id)
        record = _upload_outcome_ve_record(user_id, outcome) if carrier else {}
        return {"outcome": outcome, "record": record, "replayed": True}
    reclaimed = False
    if status == "creating":
        carrier = get_upload_outcome_creation(user_id, outcome_id)
        if carrier is not None:
            # R1 healing — the RETRY TAP (reconciliation §6.3 R3):
            # the VE record + carrier committed, the outcome never
            # flipped to 'created'. Complete it now. No other read
            # heals it.
            store.set_upload_outcome_status(
                user_id,
                outcome_id,
                "created",
                ve_kind=carrier["ve_kind"],
                ve_id=carrier["ve_id"],
            )
            store.set_upload_interpretation_status(
                user_id, outcome["interpretation_id"], "ruled"
            )
            outcome = store.get_upload_outcome(user_id, outcome_id) or outcome
            record = _upload_outcome_ve_record(user_id, outcome)
            return {"outcome": outcome, "record": record, "replayed": True}
        # Step 1b (amendment A4): no carrier row — the retry may
        # re-take the claim, but only when the outcome is older
        # than one hour. A younger 'creating' outcome is presumed
        # live, not dead, and the retry is refused with a plain
        # message. The age is the outcome row's age (created_at —
        # the claim to 'creating' follows creation in the same
        # approve call, so creation age approximates claim age).
        # An unparseable timestamp refuses the retry (safe default).
        age_s = _upload_outcome_age_s(outcome)
        if age_s is None or age_s < _UPLOAD_RECLAIM_STALE_S:
            raise UploadOutcomeStuckError("Still creating — check back shortly.")
        if not store.reclaim_upload_outcome(user_id, outcome_id):
            # Another session owns the retry — return the existing
            # outcome / 409 per §8.2.
            raise ProposalConflict(
                "Already decided — refresh to see its state."
            )
        # Re-claimed: this session owns the retry. Fall through to
        # step 2 (carrier lookup first — already done above, no
        # carrier) and create the VE record + carrier below.
        reclaimed = True
    elif status != "pending":
        raise ProposalConflict(
            f"Outcome is already {status} — refresh to see its state."
        )
    if not reclaimed and not store.claim_upload_outcome(user_id, outcome_id):
        # Lost the race after the read: re-read and replay, or 409.
        fresh = store.get_upload_outcome(user_id, outcome_id) or outcome
        if fresh.get("status") == "created":
            record = _upload_outcome_ve_record(user_id, fresh)
            return {"outcome": fresh, "record": record, "replayed": True}
        raise ProposalConflict("Already decided — refresh to see its state.")

    conn = get_connection()
    ve_kind = kind
    ve_id: str | None = None
    try:
        with ve_write_transaction(conn, purpose="approve_upload_outcome"):
            if kind == "task":
                project_id = parent_id
                data = M.TaskCreate(
                    project_id=project_id,
                    title=title,
                    description=detail or "",
                    status="Todo",
                    seat_ref="",
                )
                _reject_keystone_project(data.project_id, user_id)
                _guard_legacy_write(
                    conn,
                    _resolve_task_payload_subtree(
                        conn, data.parent_task_id, data.project_id, user_id
                    ),
                    target_id=None,
                    target_kind="task",
                )
                ve_id = _insert_task(
                    conn,
                    data,
                    user_id,
                    origin_seat=lens_seat or "conductor",
                    origin_conversation_id=conversation_id,
                    origin_message_id=None,
                    origin_claim_id=None,
                    origin_decision_id=None,
                    responsible_seat=None,
                )
            elif kind == "project":
                initiative_id = None
                if parent_id:
                    parent = get_project(parent_id, user_id)
                    if parent is None:
                        raise ValueError(
                            f"Parent project not found: {parent_id!r}"
                        )
                    initiative_id = parent.get("initiative_id")
                pid = M.new_id()
                data = M.ProjectCreate(
                    initiative_id=initiative_id,
                    title=title,
                    brief=detail or "",
                    status="Draft",
                    owner_id=user_id,
                )
                _ensure_owned_reference(
                    conn,
                    table="initiatives",
                    ref_id=data.initiative_id,
                    user_id=user_id,
                    field_name="initiative_id",
                )
                _guard_legacy_write(
                    conn,
                    data.initiative_id,
                    target_id=pid,
                    target_kind="project",
                )
                ve_id = _insert_project(conn, data, user_id, pid=pid)
            else:  # idea: no VE parent; the choice stays on the outcome row.
                iid = M.new_id()
                data = M.IdeaCreate(
                    title=title,
                    description=detail or "",
                    status="Captured",
                    created_by=user_id,
                )
                _guard_idea_write(conn, iid, user_id, target_id=iid, target_kind="idea")
                ve_id = _insert_idea(conn, data, user_id, iid=iid)
            assert ve_id is not None
            conn.execute(
                "INSERT INTO upload_outcome_creations (outcome_id, user_id, "
                "ve_kind, ve_id, node_id, created_at) VALUES (?, ?, ?, ?, NULL, ?)",
                (outcome_id, user_id, ve_kind, ve_id, _now()),
            )
            _commit_if_owner(conn)
    except sqlite3.IntegrityError:
        # Amendment A4, case (iii): the carrier insert failed on
        # PRIMARY KEY — a concurrent creation committed its carrier
        # first. Re-read the carrier row and return the existing VE
        # record instead of surfacing an error. (The
        # ve_write_transaction owner already rolled this session's
        # partial VE insert back on the exception exit.)
        carrier = get_upload_outcome_creation(user_id, outcome_id)
        if carrier is not None:
            store.set_upload_outcome_status(
                user_id,
                outcome_id,
                "created",
                ve_kind=carrier["ve_kind"],
                ve_id=carrier["ve_id"],
            )
            store.set_upload_interpretation_status(
                user_id, outcome["interpretation_id"], "ruled"
            )
            done = store.get_upload_outcome(user_id, outcome_id) or outcome
            record = _upload_outcome_ve_record(user_id, done)
            return {"outcome": done, "record": record, "replayed": True}
        # Not a carrier conflict (or the carrier vanished): fall
        # through to the generic failure handling below.
        _rollback_if_owner(conn)
        try:
            store.set_upload_outcome_status(user_id, outcome_id, "pending")
        except Exception:
            pass
        raise
    except Exception:
        _rollback_if_owner(conn)
        # Step-4 contract: a validation failure rolls back the claim
        # too — the outcome returns to 'pending' so the user can edit
        # and retry; nothing is written.
        try:
            store.set_upload_outcome_status(user_id, outcome_id, "pending")
        except Exception:
            pass
        raise
    record = _upload_outcome_ve_record(
        user_id, {"ve_kind": ve_kind, "ve_id": ve_id}
    )
    activity_type = {
        "project": ActivityType.PROJECT_CREATED.value,
        "task": ActivityType.TASK_CREATED.value,
        "idea": ActivityType.IDEA_CREATED.value,
    }[ve_kind]
    entity_type = {
        "project": ActivityEntityType.PROJECT.value,
        "task": ActivityEntityType.TASK.value,
        "idea": ActivityEntityType.IDEA.value,
    }[ve_kind]
    _log_ve_entity_activity(
        type=activity_type,
        entity_type=entity_type,
        entity_id=ve_id,
        user_id=user_id,
        related_entity_id=_ve_activity_related_id(
            parent_id if ve_kind == "task" else None
        ),
        detail=f"title={title[:120]!r}",
    )
    store.set_upload_outcome_status(
        user_id, outcome_id, "created", ve_kind=ve_kind, ve_id=ve_id
    )
    store.set_upload_interpretation_status(
        user_id, outcome["interpretation_id"], "ruled"
    )
    outcome = store.get_upload_outcome(user_id, outcome_id) or outcome
    return {"outcome": outcome, "record": record, "replayed": False}


def _upload_outcome_ve_record(
    user_id: str, outcome: dict[str, Any]
) -> dict[str, Any]:
    """Read back the VE record an outcome created (or replayed)."""
    ve_kind = outcome.get("ve_kind")
    ve_id = outcome.get("ve_id")
    if not ve_kind or not ve_id:
        return {}
    if ve_kind == "project":
        return get_project(ve_id, user_id) or {}
    if ve_kind == "task":
        return get_task(ve_id, user_id) or {}
    if ve_kind == "idea":
        return get_idea(ve_id, user_id) or {}
    return {}


def update_task(task_id: str, data: M.TaskUpdate, user_id: str) -> dict[str, Any] | None:
    before = get_task(task_id, user_id)
    if before is None:
        return None
    old_status = str(before.get("status") or "")
    conn = get_connection()
    updates = []
    args = []
    nullable_fks = ("assignee_id", "parent_task_id", "project_id")
    model_items = data.model_dump(exclude_unset=True)
    if "timeframe_commitment" in model_items:
        _validate_timeframe_commitment(model_items.get("timeframe_commitment"))
    if "project_id" in model_items and model_items.get("project_id") is not None:
        _ensure_owned_reference(
            conn,
            table="projects",
            ref_id=model_items.get("project_id"),
            user_id=user_id,
            field_name="project_id",
        )
    if "parent_task_id" in model_items:
        _ensure_owned_reference(
            conn,
            table="tasks",
            ref_id=model_items.get("parent_task_id"),
            user_id=user_id,
            field_name="parent_task_id",
        )
    for k, v in model_items.items():
        # Explicit None clears a nullable field (timeframe_commitment is
        # set AND cleared via PATCH; absent fields never reach here
        # because model_dump(exclude_unset=True) omits them).
        if v is not None or (k in nullable_fks) or k == "timeframe_commitment":
            if k == "dependency_ids":
                updates.append("dependency_ids = ?")
                args.append(M._json_dumps_list(v) if v is not None else "[]")
            elif k == "required_asset_ids":
                updates.append("required_asset_ids = ?")
                args.append(M._json_dumps_list(v) if v is not None else "[]")
            else:
                updates.append(f"{k} = ?")
                args.append(v)
    if not updates:
        return get_task(task_id, user_id)
    updates.append("updated_at = ?")
    args.append(_now())
    args.append(task_id)
    with ve_write_transaction(conn, purpose="update_task"):
        _guard_legacy_write(
            conn,
            _resolve_task_subtree(conn, task_id, user_id),
            target_id=task_id,
            target_kind="task",
        )
        conn.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id = ? AND user_id = ?", args + [user_id])
        _commit_if_owner(conn)
    after = get_task(task_id, user_id)
    new_status = str((after or {}).get("status") or "")
    rel_pid = after.get("project_id") if isinstance(after, dict) else None
    related = _ve_activity_related_id(str(rel_pid).strip() if rel_pid else None)
    patch_keys = list(model_items.keys())
    if _ve_task_status_done(new_status) and not _ve_task_status_done(old_status):
        _log_ve_entity_activity(
            type=ActivityType.TASK_COMPLETED.value,
            entity_type=ActivityEntityType.TASK.value,
            entity_id=task_id,
            user_id=user_id,
            related_entity_id=related,
            detail=f"status={new_status[:80]!r}",
        )
        _emit_fellowship_event(
            kind="task_completed",
            user_id=user_id,
            entity_type="task",
            entity_id=task_id,
            summary=f"Task completed: {str((after or {}).get('title') or '')[:160]}",
            payload={
                "title": str((after or {}).get("title") or "")[:300],
                "status": new_status,
                "project_id": str(rel_pid) if rel_pid else "",
            },
        )
        # Sticky seat unlock (Joshua's rule, 2026-10-30: "Once it's
        # open it should stay open"). If this flip completed the entry
        # seat's keystone 1, the other seats' begin doors light — and
        # they must survive a later Weaver restart or Reopen toggle,
        # both of which funnel through this same update path. The
        # recording is guarded like the fellowship event above: it
        # must never break the task update itself (the task commit
        # already succeeded by this point).
        try:
            from local_ai.vision_execution import keystone_seeding

            keystone_seeding.maybe_record_entry_unlock(user_id, after or {})
        except Exception:
            _logger.exception("seat unlock recording failed")
    else:
        det = f"fields={','.join(patch_keys)[:200]}"
        if _ve_task_status_done(old_status) and not _ve_task_status_done(new_status):
            det = f"reopened; {det}"
        _log_ve_entity_activity(
            type=ActivityType.TASK_UPDATED.value,
            entity_type=ActivityEntityType.TASK.value,
            entity_id=task_id,
            user_id=user_id,
            related_entity_id=related,
            detail=det,
        )
    return after


# --- Sticky seat unlocks ---
# One row per (user, non-entry seat) whose begin door has become
# available (see keystone_seeding.maybe_record_entry_unlock). Rows are
# append-only in practice: nothing deletes them — not a Weaver restart,
# not a Reopen toggle, not a server restart. Reads degrade to "not
# unlocked" on any error (fail closed: the pre-sticky behavior).


def record_seat_unlocks(user_id: str, seat_refs: list[str]) -> None:
    """Idempotently record begin-door availability for seats."""
    refs = sorted({(r or "").strip() for r in seat_refs if (r or "").strip()})
    if not refs:
        return
    conn = get_connection()
    now = _now()
    conn.executemany(
        "INSERT OR IGNORE INTO seat_unlocks (user_id, seat_ref, unlocked_at)"
        " VALUES (?, ?, ?)",
        [(user_id, ref, now) for ref in refs],
    )
    conn.commit()


def get_seat_unlocks(user_id: str) -> set[str]:
    """Seat refs whose begin door has become available for the user."""
    conn = get_connection()
    cur = conn.execute(
        "SELECT seat_ref FROM seat_unlocks WHERE user_id = ?", (user_id,)
    )
    return {(r[0] or "").strip() for r in cur.fetchall() if r and r[0]}


def delete_task(task_id: str, user_id: str) -> bool:
    before = get_task(task_id, user_id)
    if before is None:
        return False
    proj = _ve_activity_related_id(str(before.get("project_id") or "").strip() or None)
    conn = get_connection()
    with ve_write_transaction(conn, purpose="delete_task"):
        _guard_legacy_write(
            conn,
            _resolve_task_subtree(conn, task_id, user_id),
            target_id=task_id,
            target_kind="task",
        )
        conn.execute(
            "UPDATE tasks SET parent_task_id = NULL WHERE parent_task_id = ? AND user_id = ?",
            (task_id, user_id),
        )
        conn.execute("DELETE FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id))
        _commit_if_owner(conn)
    _log_ve_entity_activity(
        type=ActivityType.TASK_DELETED.value,
        entity_type=ActivityEntityType.TASK.value,
        entity_id=task_id,
        user_id=user_id,
        related_entity_id=proj,
        detail="deleted",
    )
    return True


# --- Persons ---

def list_persons() -> list[dict[str, Any]]:
    conn = get_connection()
    cur = conn.execute(
        "SELECT id, name, role, relationship_type, contact_info, strengths, needs, wants, availability, "
        "notes, created_at, updated_at FROM persons ORDER BY name"
    )
    return [M.row_to_person(tuple(r)) for r in cur.fetchall()]


def get_person(person_id: str) -> dict[str, Any] | None:
    conn = get_connection()
    cur = conn.execute(
        "SELECT id, name, role, relationship_type, contact_info, strengths, needs, wants, availability, "
        "notes, created_at, updated_at FROM persons WHERE id = ?",
        (person_id,),
    )
    row = cur.fetchone()
    return M.row_to_person(tuple(row)) if row else None


def create_person(data: M.PersonCreate) -> dict[str, Any]:
    conn = get_connection()
    pid = M.new_id()
    now = _now()
    conn.execute(
        """INSERT INTO persons (
          id, name, role, relationship_type, contact_info, strengths, needs, wants, availability,
          notes, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            pid, data.name, data.role, data.relationship_type, data.contact_info,
            data.strengths, data.needs, data.wants, data.availability, data.notes, now, now,
        ),
    )
    conn.commit()
    return get_person(pid) or {}


def update_person(person_id: str, data: M.PersonUpdate) -> dict[str, Any] | None:
    if get_person(person_id) is None:
        return None
    conn = get_connection()
    updates = []
    args = []
    for k, v in data.model_dump(exclude_unset=True).items():
        if v is not None:
            updates.append(f"{k} = ?")
            args.append(v)
    if not updates:
        return get_person(person_id)
    updates.append("updated_at = ?")
    args.append(_now())
    args.append(person_id)
    conn.execute(f"UPDATE persons SET {', '.join(updates)} WHERE id = ?", args)
    conn.commit()
    return get_person(person_id)


def delete_person(person_id: str) -> bool:
    if get_person(person_id) is None:
        return False
    conn = get_connection()
    conn.execute("UPDATE initiatives SET owner_id = NULL WHERE owner_id = ?", (person_id,))
    conn.execute("UPDATE projects SET owner_id = NULL WHERE owner_id = ?", (person_id,))
    conn.execute("UPDATE tasks SET assignee_id = NULL WHERE assignee_id = ?", (person_id,))
    conn.execute("UPDATE assets SET owner_id = NULL WHERE owner_id = ?", (person_id,))
    conn.execute("DELETE FROM capacity_profiles WHERE person_id = ?", (person_id,))
    conn.execute("DELETE FROM persons WHERE id = ?", (person_id,))
    conn.commit()
    return True


# --- Capacity profiles ---

def list_capacity_profiles() -> list[dict[str, Any]]:
    conn = get_connection()
    cur = conn.execute(
        "SELECT person_id, weekly_capacity_hours, created_at, updated_at FROM capacity_profiles"
    )
    return [M.row_to_capacity(tuple(r)) for r in cur.fetchall()]


def get_capacity_profile(person_id: str) -> dict[str, Any] | None:
    conn = get_connection()
    cur = conn.execute(
        "SELECT person_id, weekly_capacity_hours, created_at, updated_at FROM capacity_profiles WHERE person_id = ?",
        (person_id,),
    )
    row = cur.fetchone()
    return M.row_to_capacity(tuple(row)) if row else None


def upsert_capacity_profile(data: M.CapacityProfileUpsert) -> dict[str, Any]:
    conn = get_connection()
    now = _now()
    conn.execute(
        """INSERT INTO capacity_profiles (person_id, weekly_capacity_hours, created_at, updated_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(person_id) DO UPDATE SET weekly_capacity_hours = ?, updated_at = ?""",
        (data.person_id, data.weekly_capacity_hours, now, now, data.weekly_capacity_hours, now),
    )
    conn.commit()
    return get_capacity_profile(data.person_id) or {}


# --- Assets ---

def list_assets() -> list[dict[str, Any]]:
    conn = get_connection()
    cur = conn.execute(
        "SELECT id, name, asset_type, owner_id, status, availability, cost, time_availability, "
        "linked_idea_ids, linked_initiative_ids, linked_project_ids, notes, created_at, updated_at "
        "FROM assets ORDER BY name"
    )
    return [M.row_to_asset(tuple(r)) for r in cur.fetchall()]


def get_asset(asset_id: str) -> dict[str, Any] | None:
    conn = get_connection()
    cur = conn.execute(
        "SELECT id, name, asset_type, owner_id, status, availability, cost, time_availability, "
        "linked_idea_ids, linked_initiative_ids, linked_project_ids, notes, created_at, updated_at "
        "FROM assets WHERE id = ?",
        (asset_id,),
    )
    row = cur.fetchone()
    return M.row_to_asset(tuple(row)) if row else None


def create_asset(data: M.AssetCreate) -> dict[str, Any]:
    conn = get_connection()
    aid = M.new_id()
    now = _now()
    conn.execute(
        """INSERT INTO assets (
          id, name, asset_type, owner_id, status, availability, cost, time_availability,
          linked_idea_ids, linked_initiative_ids, linked_project_ids, notes, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            aid, data.name, data.asset_type, data.owner_id, data.status, data.availability,
            data.cost, data.time_availability, M._json_dumps_list(data.linked_idea_ids),
            M._json_dumps_list(data.linked_initiative_ids), M._json_dumps_list(data.linked_project_ids),
            data.notes, now, now,
        ),
    )
    conn.commit()
    return get_asset(aid) or {}


def update_asset(asset_id: str, data: M.AssetUpdate) -> dict[str, Any] | None:
    if get_asset(asset_id) is None:
        return None
    conn = get_connection()
    updates = []
    args = []
    for k, v in data.model_dump(exclude_unset=True).items():
        if v is not None:
            if k in ("linked_idea_ids", "linked_initiative_ids", "linked_project_ids"):
                updates.append(f"{k} = ?")
                args.append(M._json_dumps_list(v))
            else:
                updates.append(f"{k} = ?")
                args.append(v)
    if not updates:
        return get_asset(asset_id)
    updates.append("updated_at = ?")
    args.append(_now())
    args.append(asset_id)
    conn.execute(f"UPDATE assets SET {', '.join(updates)} WHERE id = ?", args)
    conn.commit()
    return get_asset(asset_id)


def delete_asset(asset_id: str) -> bool:
    if get_asset(asset_id) is None:
        return False
    conn = get_connection()
    conn.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
    conn.commit()
    return True


# --- Decisions (append-only; for personality learning / decision analysis) ---

def _require_owner_id(user_id: str | None) -> str:
    """Validate an owner identity at the data-access boundary.

    A required parameter is not a valid identity: empty strings and
    ``None`` are rejected here, never trusted. Ownership is enforced
    by the SQL predicate in the caller, never by a downstream filter.
    """
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("user_id must be a non-empty string")
    return user_id


def create_decision(data: M.DecisionCreate) -> dict[str, Any]:
    _require_owner_id(data.user_id)
    conn = get_connection()
    did = M.new_id()
    now = _now()
    conn.execute(
        """INSERT INTO decisions (
          id, user_id, entity_type, entity_id, decision_type, ai_proposal_snapshot, final_values_snapshot, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            did, data.user_id, data.entity_type, data.entity_id, data.decision_type,
            M._json_dumps_obj(data.ai_proposal_snapshot), M._json_dumps_obj(data.final_values_snapshot), now,
        ),
    )
    conn.commit()
    out = get_decision(did, data.user_id) or {}
    # Fellowship Runtime P1: the append-only decision record is adopted
    # as an event source — the event references this decision by id
    # and never duplicates the record.
    _emit_fellowship_event(
        kind="decision_recorded",
        user_id=str(data.user_id or ""),
        entity_type="decision",
        entity_id=did,
        summary=(
            f"Decision recorded: {data.decision_type} on "
            f"{data.entity_type} {data.entity_id}"
        ),
        payload={
            "decision_type": data.decision_type,
            "about_entity_type": data.entity_type,
            "about_entity_id": data.entity_id,
        },
    )
    if data.decision_type == "evaluation_applied" and str(data.entity_type or "").strip().lower() in (
        "initiative",
        "idea",
    ):
        uid = str(data.user_id or "").strip() or "anonymous"
        eid = str(data.entity_id or "").strip()
        et = str(data.entity_type or "").strip().lower()
        if eid and et:
            d = json.dumps({"decision_id": did}, ensure_ascii=False)
            if len(d) > 2000:
                d = d[:2000]
            _log_coordination_ve_activity(
                type=ActivityType.VE_EVALUATE_APPLIED.value,
                entity_type=et,
                entity_id=eid,
                user_id=uid,
                detail=d,
            )
    return out


def get_decision(decision_id: str, user_id: str) -> dict[str, Any] | None:
    """Return one decision row owned by ``user_id``, else None.

    A foreign id is indistinguishable from a missing one (404, not 403):
    existence is never confirmed to a non-owner. ``user_id`` is required
    and must be a non-empty string — see ``_require_owner_id``.
    """
    _require_owner_id(user_id)
    conn = get_connection()
    cur = conn.execute(
        "SELECT id, user_id, entity_type, entity_id, decision_type, ai_proposal_snapshot, final_values_snapshot, created_at FROM decisions WHERE id = ? AND user_id = ?",
        (decision_id, user_id),
    )
    row = cur.fetchone()
    return M.row_to_decision(tuple(row)) if row else None


def list_decisions(user_id: str, entity_type: str | None = None, entity_id: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    """List decision rows owned by ``user_id`` (all filter branches).

    Ownership is enforced by the SQL predicate, so filtering happens
    BEFORE the LIMIT — a post-query filter could not make that guarantee.
    ``user_id`` is required and must be a non-empty string.
    """
    _require_owner_id(user_id)
    conn = get_connection()
    if entity_type and entity_id:
        cur = conn.execute(
            "SELECT id, user_id, entity_type, entity_id, decision_type, ai_proposal_snapshot, final_values_snapshot, created_at "
            "FROM decisions WHERE user_id = ? AND entity_type = ? AND entity_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, entity_type, entity_id, limit),
        )
    elif entity_type:
        cur = conn.execute(
            "SELECT id, user_id, entity_type, entity_id, decision_type, ai_proposal_snapshot, final_values_snapshot, created_at "
            "FROM decisions WHERE user_id = ? AND entity_type = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, entity_type, limit),
        )
    else:
        cur = conn.execute(
            "SELECT id, user_id, entity_type, entity_id, decision_type, ai_proposal_snapshot, final_values_snapshot, created_at "
            "FROM decisions WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        )
    return [M.row_to_decision(tuple(r)) for r in cur.fetchall()]


def migrate_decisions_user_created_index(connection: sqlite3.Connection | None = None) -> None:
    """Explicit-call migration: index the scoped decision-list query.

    Adds ``idx_decisions_user_created`` on ``decisions (user_id, created_at)``.
    Idempotent (``CREATE INDEX IF NOT EXISTS``). Explicit-call only — this
    function is never invoked by ``init_db`` or any import path, and it
    must never be executed against staging without its own authorization.
    Pass a connection to apply it to a specific database (tests); otherwise
    the module's default connection is used.
    """
    conn = connection if connection is not None else get_connection()
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_decisions_user_created "
        "ON decisions (user_id, created_at)"
    )
    conn.commit()


# --- Radar feed (meeting signals, etc.) ---

def create_radar_item(data: M.RadarFeedCreate) -> dict[str, Any]:
    from local_ai.activity import log_activity_simple

    conn = get_connection()
    pid = M.new_id()
    now = _now()
    conn.execute(
        """INSERT INTO radar_feed (id, title, detail, severity, source, source_excerpt, kind, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            pid,
            data.title or "",
            data.detail or "",
            data.severity or "medium",
            data.source or "meeting-extraction",
            data.source_excerpt or "",
            data.kind or "attention",
            now,
        ),
    )
    conn.commit()
    out = M.row_to_radar_feed(
        (pid, data.title or "", data.detail or "", data.severity or "medium", data.source or "meeting-extraction", data.source_excerpt or "", data.kind or "attention", now)
    )
    # Log a simple activity event for signal creation (using radar feed as proxy for now).
    try:
        from local_ai.activity import ActivityType, ActivityEntityType
        log_activity_simple(
            type=ActivityType.SIGNAL_CREATED.value,
            entity_type=ActivityEntityType.SIGNAL.value,
            entity_id=pid,
            source=data.source or "meeting-extraction",
            detail=f"kind={data.kind or 'attention'} title={data.title or ''}",
        )
    except Exception:
        pass
    return out


def list_radar_feed() -> list[dict[str, Any]]:
    conn = get_connection()
    cur = conn.execute(
        "SELECT id, title, detail, severity, source, source_excerpt, kind, created_at FROM radar_feed ORDER BY created_at DESC"
    )
    return [M.row_to_radar_feed(tuple(r)) for r in cur.fetchall()]


# --- Content briefs ---

def list_content_briefs(user_id: str) -> list[dict[str, Any]]:
    conn = get_connection()
    cur = conn.execute(
        "SELECT id, title, status, payload, created_at, updated_at FROM content_briefs WHERE user_id = ? ORDER BY updated_at DESC",
        (user_id,),
    )
    return [_row_to_content_brief(tuple(r)) for r in cur.fetchall()]


def get_content_brief(brief_id: str, user_id: str) -> dict[str, Any] | None:
    conn = get_connection()
    cur = conn.execute(
        "SELECT id, title, status, payload, created_at, updated_at FROM content_briefs WHERE id = ? AND user_id = ?",
        (brief_id, user_id),
    )
    row = cur.fetchone()
    return _row_to_content_brief(tuple(row)) if row else None


def _row_to_content_brief(row: tuple) -> dict[str, Any]:
    rid, title, status, payload, created_at, updated_at = row
    out = {"id": rid, "title": title or "", "status": status or "draft", "created_at": created_at, "updated_at": updated_at}
    try:
        out["payload"] = json.loads(payload) if payload else {}
    except Exception:
        out["payload"] = {}
    return out


def create_content_brief(data: dict[str, Any], user_id: str) -> dict[str, Any]:
    conn = get_connection()
    bid = M.new_id()
    now = _now()
    payload = data.get("payload")
    if payload is None:
        payload = {k: v for k, v in data.items() if k not in ("id", "title", "status", "created_at", "updated_at")}
    title = (data.get("title") or (payload.get("title") if isinstance(payload, dict) else None)) or "Untitled brief"
    status = (data.get("status") or (payload.get("status") if isinstance(payload, dict) else None)) or "draft"
    if isinstance(payload, dict):
        payload = {k: v for k, v in payload.items() if k not in ("id", "created_at", "updated_at")}
    else:
        payload = {}
    payload_json = json.dumps(payload)
    conn.execute(
        "INSERT INTO content_briefs (id, user_id, title, status, payload, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (bid, user_id, title, status, payload_json, now, now),
    )
    conn.commit()
    return get_content_brief(bid, user_id) or {}


def update_content_brief(brief_id: str, data: dict[str, Any], user_id: str) -> dict[str, Any] | None:
    if get_content_brief(brief_id, user_id) is None:
        return None
    conn = get_connection()
    now = _now()
    updates = []
    args = []
    if "title" in data and data["title"] is not None:
        updates.append("title = ?")
        args.append(data["title"])
    if "status" in data and data["status"] is not None:
        updates.append("status = ?")
        args.append(data["status"])
    if "payload" in data and data["payload"] is not None:
        payload = data["payload"]
        if isinstance(payload, dict):
            payload = json.dumps(payload)
        updates.append("payload = ?")
        args.append(payload)
    if not updates:
        return get_content_brief(brief_id, user_id)
    updates.append("updated_at = ?")
    args.append(now)
    args.extend([brief_id, user_id])
    conn.execute(f"UPDATE content_briefs SET {', '.join(updates)} WHERE id = ? AND user_id = ?", args)
    conn.commit()
    return get_content_brief(brief_id, user_id)


# --- Shareability + matching source objects (S2/S3/S4-lite) ---

_SHARE_STATES = {"private", "shared_unindexed", "shared_indexed", "revoked", "inactive", "deleted"}
_ALLOWED_SHARE_TRANSITIONS: dict[str, set[str]] = {
    "private": {"private", "shared_unindexed", "inactive", "deleted"},
    "shared_unindexed": {"private", "shared_unindexed", "shared_indexed", "revoked", "inactive", "deleted"},
    "shared_indexed": {"private", "shared_unindexed", "shared_indexed", "revoked", "inactive", "deleted"},
    # Explicit re-share path: revoked -> shared_unindexed first, never direct -> shared_indexed.
    "revoked": {"private", "shared_unindexed", "revoked", "inactive", "deleted"},
    # Inactive cannot jump directly to indexed visibility.
    "inactive": {"private", "shared_unindexed", "inactive", "deleted"},
    # Deleted is terminal.
    "deleted": {"deleted"},
}

_QUANTITY_UNIT_ALIASES: dict[str, str] = {
    "item": "item",
    "items": "item",
    "unit": "unit",
    "units": "unit",
    "set": "set",
    "sets": "set",
    "pack": "pack",
    "packs": "pack",
    "box": "box",
    "boxes": "box",
    "kg": "kg",
    "kilogram": "kg",
    "kilograms": "kg",
    "g": "g",
    "gram": "g",
    "grams": "g",
    "lb": "lb",
    "lbs": "lb",
    "l": "l",
    "liter": "l",
    "liters": "l",
    "ml": "ml",
    "milliliter": "ml",
    "milliliters": "ml",
    "hour": "hour",
    "hours": "hour",
    "day": "day",
    "days": "day",
    "week": "week",
    "weeks": "week",
    "month": "month",
    "months": "month",
    "seat": "seat",
    "seats": "seat",
    "license": "license",
    "licenses": "license",
}
_RESOURCE_NATURE_VALUES = {"consumable", "reusable", "reservable", "transferable", "access_based"}
_CONDITION_ORDER = ["any", "poor", "fair", "good", "very_good", "excellent", "new"]
_CONDITION_INDEX = {v: i for i, v in enumerate(_CONDITION_ORDER)}
_COST_BAND_ORDER = ["free", "low", "medium", "high", "premium", "enterprise"]
_COST_BAND_INDEX = {v: i for i, v in enumerate(_COST_BAND_ORDER)}


def _normalize_share_until(share_until: str | None) -> str | None:
    if share_until is None:
        return None
    raw = str(share_until).strip()
    if not raw:
        return None

    # Accepted formats:
    # - YYYY-MM-DD (normalized to end-of-day UTC)
    # - ISO datetime with timezone, e.g. 2026-03-11T15:30:00Z or +00:00
    if len(raw) == 10:
        try:
            day = datetime.strptime(raw, "%Y-%m-%d")
            dt = day.replace(hour=23, minute=59, second=59, microsecond=0, tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError as exc:
            raise ValueError("Invalid share_until date; expected YYYY-MM-DD") from exc

    iso = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError as exc:
        raise ValueError("Invalid share_until datetime; expected ISO-8601 with timezone") from exc
    if dt.tzinfo is None:
        raise ValueError("Invalid share_until datetime; timezone is required")
    return dt.astimezone(timezone.utc).isoformat()


def _is_share_until_active(share_until: str | None, now_dt: datetime) -> bool:
    normalized = _normalize_share_until(share_until)
    if normalized is None:
        return True
    dt = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    return dt >= now_dt


def _validate_share_state(visibility: str, index_state: str) -> None:
    if visibility not in _SHARE_STATES:
        raise ValueError(f"Invalid visibility state: {visibility}")
    if index_state not in _SHARE_STATES:
        raise ValueError(f"Invalid index_state: {index_state}")
    if index_state == "shared_indexed" and visibility != "shared_indexed":
        raise ValueError("index_state=shared_indexed requires visibility=shared_indexed")
    if visibility == "private" and index_state != "private":
        raise ValueError("private visibility requires private index_state")
    if visibility == "shared_unindexed" and index_state not in {"shared_unindexed", "private"}:
        raise ValueError("shared_unindexed visibility requires shared_unindexed or private index_state")
    if visibility in {"revoked", "inactive", "deleted"} and index_state not in {"revoked", "inactive", "deleted"}:
        raise ValueError("revoked/inactive/deleted visibility requires matching non-indexable index_state")


def _validate_share_transition(current_visibility: str, next_visibility: str) -> None:
    allowed = _ALLOWED_SHARE_TRANSITIONS.get(current_visibility, {current_visibility})
    if next_visibility not in allowed:
        raise ValueError(f"Illegal lifecycle transition: {current_visibility} -> {next_visibility}")


def _normalize_nonempty_key(label: str, value: str) -> str:
    out = str(value or "").strip().lower()
    if not out:
        raise ValueError(f"{label} is required")
    return out


def _normalize_quantity_unit(value: str) -> str:
    key = _normalize_nonempty_key("quantity_unit", value)
    out = _QUANTITY_UNIT_ALIASES.get(key)
    if out is None:
        raise ValueError(f"Invalid quantity_unit: {value}")
    return out


def _normalize_resource_nature(value: str) -> str:
    key = _normalize_nonempty_key("resource_nature", value)
    if key not in _RESOURCE_NATURE_VALUES:
        raise ValueError(f"Invalid resource_nature: {value}")
    return key


def _normalize_condition_value(value: str, *, field_name: str) -> str:
    key = _normalize_nonempty_key(field_name, value)
    if key not in _CONDITION_INDEX:
        raise ValueError(f"Invalid {field_name}: {value}")
    return key


def _normalize_cost_band(value: str | None, *, field_name: str) -> str:
    if value is None:
        return ""
    key = str(value).strip().lower()
    if not key:
        return ""
    if key not in _COST_BAND_INDEX:
        raise ValueError(f"Invalid {field_name}: {value}")
    return key


def _normalize_iso_datetime(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    iso = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError as exc:
        raise ValueError(f"Invalid {field_name}; expected ISO-8601 with timezone") from exc
    if dt.tzinfo is None:
        raise ValueError(f"Invalid {field_name}; timezone is required")
    return dt.astimezone(timezone.utc).isoformat()


def _normalize_tags(values: list[str] | None) -> list[str]:
    if not values:
        return []
    return sorted({str(v).strip().lower() for v in values if str(v).strip()})


def _normalize_positive_quantity(value: float | int | None, *, field_name: str) -> float:
    try:
        out = float(value if value is not None else 0)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {field_name}; expected a positive number") from exc
    if out <= 0:
        raise ValueError(f"{field_name} must be > 0")
    return out


def _seat_request_select_sql() -> str:
    return (
        "SELECT id, user_id, title, summary, context_type, context_id, role_tags, capability_tags, "
        "availability_window, commitment_type, collaboration_mode, timezone_pref, visibility, index_state, "
        "consent_version, consent_at, share_until, share_revoked_at, state_changed_at, is_active, created_at, updated_at "
        "FROM seat_requests"
    )


def _capability_offer_select_sql() -> str:
    return (
        "SELECT id, user_id, title, summary, capability_tags, role_tags, availability_window, commitment_type, "
        "collaboration_mode, timezone_pref, visibility, index_state, consent_version, consent_at, share_until, "
        "share_revoked_at, state_changed_at, is_active, created_at, updated_at FROM capability_offers"
    )


def list_seat_requests(user_id: str) -> list[dict[str, Any]]:
    conn = get_connection()
    cur = conn.execute(f"{_seat_request_select_sql()} WHERE user_id = ? ORDER BY updated_at DESC", (user_id,))
    return [M.row_to_seat_request(tuple(r)) for r in cur.fetchall()]


def get_seat_request(seat_request_id: str, user_id: str) -> dict[str, Any] | None:
    conn = get_connection()
    row = conn.execute(
        f"{_seat_request_select_sql()} WHERE id = ? AND user_id = ?",
        (seat_request_id, user_id),
    ).fetchone()
    return M.row_to_seat_request(tuple(row)) if row else None


def create_seat_request(data: M.SeatRequestCreate, user_id: str) -> dict[str, Any]:
    conn = get_connection()
    rid = M.new_id()
    now = _now()
    conn.execute(
        """INSERT INTO seat_requests (
          id, user_id, title, summary, context_type, context_id, role_tags, capability_tags,
          availability_window, commitment_type, collaboration_mode, timezone_pref,
          visibility, index_state, consent_version, consent_at, share_until, share_revoked_at,
          state_changed_at, is_active, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'private', 'private', '', NULL, ?, NULL, ?, 1, ?, ?)""",
        (
            rid,
            user_id,
            data.title or "",
            data.summary or "",
            data.context_type or "",
            data.context_id,
            M._json_dumps_list(data.role_tags),
            M._json_dumps_list(data.capability_tags),
            data.availability_window,
            data.commitment_type or "",
            data.collaboration_mode or "",
            data.timezone_pref or "",
            _normalize_share_until(data.share_until),
            now,
            now,
            now,
        ),
    )
    conn.commit()
    return get_seat_request(rid, user_id) or {}


def update_seat_request(seat_request_id: str, data: M.SeatRequestUpdate, user_id: str) -> dict[str, Any] | None:
    if get_seat_request(seat_request_id, user_id) is None:
        return None
    patch = data.model_dump(exclude_unset=True)
    if not patch:
        return get_seat_request(seat_request_id, user_id)
    conn = get_connection()
    updates: list[str] = []
    args: list[Any] = []
    for key in ("title", "summary", "context_type", "context_id", "availability_window", "commitment_type", "collaboration_mode", "timezone_pref", "share_until"):
        if key in patch:
            updates.append(f"{key} = ?")
            if key == "share_until":
                args.append(_normalize_share_until(patch[key]))
            else:
                args.append(patch[key])
    if "role_tags" in patch:
        updates.append("role_tags = ?")
        args.append(M._json_dumps_list(patch["role_tags"] or []))
    if "capability_tags" in patch:
        updates.append("capability_tags = ?")
        args.append(M._json_dumps_list(patch["capability_tags"] or []))
    if "is_active" in patch:
        updates.append("is_active = ?")
        args.append(1 if patch["is_active"] else 0)
    updates.append("updated_at = ?")
    args.append(_now())
    args.extend([seat_request_id, user_id])
    conn.execute(f"UPDATE seat_requests SET {', '.join(updates)} WHERE id = ? AND user_id = ?", args)
    conn.commit()
    return get_seat_request(seat_request_id, user_id)


def delete_seat_request(seat_request_id: str, user_id: str) -> bool:
    conn = get_connection()
    cur = conn.execute("DELETE FROM seat_requests WHERE id = ? AND user_id = ?", (seat_request_id, user_id))
    conn.commit()
    return cur.rowcount > 0


def set_seat_request_share_state(seat_request_id: str, data: M.ShareStateUpdate, user_id: str) -> dict[str, Any] | None:
    existing = get_seat_request(seat_request_id, user_id)
    if existing is None:
        return None
    _validate_share_transition(existing.get("visibility") or "private", data.visibility)
    _validate_share_state(data.visibility, data.index_state)
    normalized_share_until = _normalize_share_until(data.share_until)
    if data.visibility in {"shared_unindexed", "shared_indexed"} and not (data.consent_version or "").strip():
        raise ValueError("consent_version is required when entering shared states")
    now = _now()
    revoked_at = now if data.visibility == "revoked" else None
    consent_at = now if data.visibility in {"shared_unindexed", "shared_indexed"} else existing.get("consent_at")
    if data.visibility in {"private", "inactive", "deleted"}:
        consent_at = existing.get("consent_at")
    conn = get_connection()
    conn.execute(
        """UPDATE seat_requests
           SET visibility = ?, index_state = ?, consent_version = ?, consent_at = ?, share_until = ?,
               share_revoked_at = ?, state_changed_at = ?, updated_at = ?
           WHERE id = ? AND user_id = ?""",
        (
            data.visibility,
            data.index_state,
            data.consent_version or "",
            consent_at,
            normalized_share_until,
            revoked_at,
            now,
            now,
            seat_request_id,
            user_id,
        ),
    )
    conn.commit()
    return get_seat_request(seat_request_id, user_id)


def list_capability_offers(user_id: str) -> list[dict[str, Any]]:
    conn = get_connection()
    cur = conn.execute(f"{_capability_offer_select_sql()} WHERE user_id = ? ORDER BY updated_at DESC", (user_id,))
    return [M.row_to_capability_offer(tuple(r)) for r in cur.fetchall()]


def get_capability_offer(offer_id: str, user_id: str) -> dict[str, Any] | None:
    conn = get_connection()
    row = conn.execute(
        f"{_capability_offer_select_sql()} WHERE id = ? AND user_id = ?",
        (offer_id, user_id),
    ).fetchone()
    return M.row_to_capability_offer(tuple(row)) if row else None


def create_capability_offer(data: M.CapabilityOfferCreate, user_id: str) -> dict[str, Any]:
    conn = get_connection()
    oid = M.new_id()
    now = _now()
    conn.execute(
        """INSERT INTO capability_offers (
          id, user_id, title, summary, capability_tags, role_tags, availability_window, commitment_type,
          collaboration_mode, timezone_pref, visibility, index_state, consent_version, consent_at, share_until,
          share_revoked_at, state_changed_at, is_active, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'private', 'private', '', NULL, ?, NULL, ?, 1, ?, ?)""",
        (
            oid,
            user_id,
            data.title or "",
            data.summary or "",
            M._json_dumps_list(data.capability_tags),
            M._json_dumps_list(data.role_tags),
            data.availability_window,
            data.commitment_type or "",
            data.collaboration_mode or "",
            data.timezone_pref or "",
            _normalize_share_until(data.share_until),
            now,
            now,
            now,
        ),
    )
    conn.commit()
    return get_capability_offer(oid, user_id) or {}


def update_capability_offer(offer_id: str, data: M.CapabilityOfferUpdate, user_id: str) -> dict[str, Any] | None:
    if get_capability_offer(offer_id, user_id) is None:
        return None
    patch = data.model_dump(exclude_unset=True)
    if not patch:
        return get_capability_offer(offer_id, user_id)
    conn = get_connection()
    updates: list[str] = []
    args: list[Any] = []
    for key in ("title", "summary", "availability_window", "commitment_type", "collaboration_mode", "timezone_pref", "share_until"):
        if key in patch:
            updates.append(f"{key} = ?")
            if key == "share_until":
                args.append(_normalize_share_until(patch[key]))
            else:
                args.append(patch[key])
    if "role_tags" in patch:
        updates.append("role_tags = ?")
        args.append(M._json_dumps_list(patch["role_tags"] or []))
    if "capability_tags" in patch:
        updates.append("capability_tags = ?")
        args.append(M._json_dumps_list(patch["capability_tags"] or []))
    if "is_active" in patch:
        updates.append("is_active = ?")
        args.append(1 if patch["is_active"] else 0)
    updates.append("updated_at = ?")
    args.append(_now())
    args.extend([offer_id, user_id])
    conn.execute(f"UPDATE capability_offers SET {', '.join(updates)} WHERE id = ? AND user_id = ?", args)
    conn.commit()
    return get_capability_offer(offer_id, user_id)


def delete_capability_offer(offer_id: str, user_id: str) -> bool:
    conn = get_connection()
    cur = conn.execute("DELETE FROM capability_offers WHERE id = ? AND user_id = ?", (offer_id, user_id))
    conn.commit()
    return cur.rowcount > 0


def set_capability_offer_share_state(offer_id: str, data: M.ShareStateUpdate, user_id: str) -> dict[str, Any] | None:
    existing = get_capability_offer(offer_id, user_id)
    if existing is None:
        return None
    _validate_share_transition(existing.get("visibility") or "private", data.visibility)
    _validate_share_state(data.visibility, data.index_state)
    normalized_share_until = _normalize_share_until(data.share_until)
    if data.visibility in {"shared_unindexed", "shared_indexed"} and not (data.consent_version or "").strip():
        raise ValueError("consent_version is required when entering shared states")
    now = _now()
    revoked_at = now if data.visibility == "revoked" else None
    consent_at = now if data.visibility in {"shared_unindexed", "shared_indexed"} else existing.get("consent_at")
    if data.visibility in {"private", "inactive", "deleted"}:
        consent_at = existing.get("consent_at")
    conn = get_connection()
    conn.execute(
        """UPDATE capability_offers
           SET visibility = ?, index_state = ?, consent_version = ?, consent_at = ?, share_until = ?,
               share_revoked_at = ?, state_changed_at = ?, updated_at = ?
           WHERE id = ? AND user_id = ?""",
        (
            data.visibility,
            data.index_state,
            data.consent_version or "",
            consent_at,
            normalized_share_until,
            revoked_at,
            now,
            now,
            offer_id,
            user_id,
        ),
    )
    conn.commit()
    return get_capability_offer(offer_id, user_id)


def list_matchable_seat_requests() -> list[dict[str, Any]]:
    conn = get_connection()
    now_dt = _now_dt()
    cur = conn.execute(
        f"""{_seat_request_select_sql()}
            WHERE visibility = 'shared_indexed'
              AND index_state = 'shared_indexed'
              AND is_active = 1""",
    )
    out = [M.row_to_seat_request(tuple(r)) for r in cur.fetchall()]
    return [row for row in out if _is_share_until_active(row.get("share_until"), now_dt)]


def list_matchable_capability_offers() -> list[dict[str, Any]]:
    conn = get_connection()
    now_dt = _now_dt()
    cur = conn.execute(
        f"""{_capability_offer_select_sql()}
            WHERE visibility = 'shared_indexed'
              AND index_state = 'shared_indexed'
              AND is_active = 1""",
    )
    out = [M.row_to_capability_offer(tuple(r)) for r in cur.fetchall()]
    return [row for row in out if _is_share_until_active(row.get("share_until"), now_dt)]


def _material_request_select_sql() -> str:
    return (
        "SELECT id, user_id, title, summary, material_type, resource_nature, category_tags, quantity_needed, quantity_unit, "
        "availability_start, availability_end, condition_min, access_mode, location_region, max_distance_km, usage_constraints, "
        "cost_band_max, visibility, index_state, consent_version, consent_at, share_until, share_revoked_at, state_changed_at, "
        "is_active, created_at, updated_at FROM material_requests"
    )


def _material_offer_select_sql() -> str:
    return (
        "SELECT id, user_id, title, summary, material_type, resource_nature, category_tags, quantity_available, quantity_unit, "
        "availability_start, availability_end, condition_state, access_mode, location_region, service_area_km, usage_constraints, "
        "cost_band, visibility, index_state, consent_version, consent_at, share_until, share_revoked_at, state_changed_at, "
        "is_active, created_at, updated_at FROM material_offers"
    )


def list_material_requests(user_id: str) -> list[dict[str, Any]]:
    conn = get_connection()
    cur = conn.execute(f"{_material_request_select_sql()} WHERE user_id = ? ORDER BY updated_at DESC", (user_id,))
    return [M.row_to_material_request(tuple(r)) for r in cur.fetchall()]


def get_material_request(request_id: str, user_id: str) -> dict[str, Any] | None:
    conn = get_connection()
    row = conn.execute(
        f"{_material_request_select_sql()} WHERE id = ? AND user_id = ?",
        (request_id, user_id),
    ).fetchone()
    return M.row_to_material_request(tuple(row)) if row else None


def create_material_request(data: M.MaterialRequestCreate, user_id: str) -> dict[str, Any]:
    conn = get_connection()
    rid = M.new_id()
    now = _now()
    availability_start = _normalize_iso_datetime(data.availability_start, field_name="availability_start")
    availability_end = _normalize_iso_datetime(data.availability_end, field_name="availability_end")
    if availability_start and availability_end and availability_start > availability_end:
        raise ValueError("availability_start must be <= availability_end")
    conn.execute(
        """INSERT INTO material_requests (
          id, user_id, title, summary, material_type, resource_nature, category_tags, quantity_needed, quantity_unit,
          availability_start, availability_end, condition_min, access_mode, location_region, max_distance_km, usage_constraints,
          cost_band_max, visibility, index_state, consent_version, consent_at, share_until, share_revoked_at, state_changed_at,
          is_active, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'private', 'private', '', NULL, ?, NULL, ?, 1, ?, ?)""",
        (
            rid,
            user_id,
            data.title or "",
            data.summary or "",
            _normalize_nonempty_key("material_type", data.material_type),
            _normalize_resource_nature(data.resource_nature),
            M._json_dumps_list(_normalize_tags(data.category_tags)),
            _normalize_positive_quantity(data.quantity_needed, field_name="quantity_needed"),
            _normalize_quantity_unit(data.quantity_unit),
            availability_start,
            availability_end,
            _normalize_condition_value(data.condition_min, field_name="condition_min"),
            (data.access_mode or "").strip().lower(),
            (data.location_region or "").strip().lower(),
            data.max_distance_km,
            M._json_dumps_list(_normalize_tags(data.usage_constraints)),
            _normalize_cost_band(data.cost_band_max, field_name="cost_band_max"),
            _normalize_share_until(data.share_until),
            now,
            now,
            now,
        ),
    )
    conn.commit()
    return get_material_request(rid, user_id) or {}


def update_material_request(request_id: str, data: M.MaterialRequestUpdate, user_id: str) -> dict[str, Any] | None:
    if get_material_request(request_id, user_id) is None:
        return None
    patch = data.model_dump(exclude_unset=True)
    if not patch:
        return get_material_request(request_id, user_id)
    conn = get_connection()
    updates: list[str] = []
    args: list[Any] = []
    if "title" in patch:
        updates.append("title = ?")
        args.append(patch["title"] or "")
    if "summary" in patch:
        updates.append("summary = ?")
        args.append(patch["summary"] or "")
    if "material_type" in patch:
        updates.append("material_type = ?")
        args.append(_normalize_nonempty_key("material_type", patch["material_type"]))
    if "resource_nature" in patch:
        updates.append("resource_nature = ?")
        args.append(_normalize_resource_nature(patch["resource_nature"]))
    if "category_tags" in patch:
        updates.append("category_tags = ?")
        args.append(M._json_dumps_list(_normalize_tags(patch["category_tags"])))
    if "quantity_needed" in patch:
        updates.append("quantity_needed = ?")
        args.append(_normalize_positive_quantity(patch["quantity_needed"], field_name="quantity_needed"))
    if "quantity_unit" in patch:
        updates.append("quantity_unit = ?")
        args.append(_normalize_quantity_unit(patch["quantity_unit"]))
    if "availability_start" in patch:
        updates.append("availability_start = ?")
        args.append(_normalize_iso_datetime(patch["availability_start"], field_name="availability_start"))
    if "availability_end" in patch:
        updates.append("availability_end = ?")
        args.append(_normalize_iso_datetime(patch["availability_end"], field_name="availability_end"))
    if "condition_min" in patch:
        updates.append("condition_min = ?")
        args.append(_normalize_condition_value(patch["condition_min"], field_name="condition_min"))
    if "access_mode" in patch:
        updates.append("access_mode = ?")
        args.append((patch["access_mode"] or "").strip().lower())
    if "location_region" in patch:
        updates.append("location_region = ?")
        args.append((patch["location_region"] or "").strip().lower())
    if "max_distance_km" in patch:
        updates.append("max_distance_km = ?")
        args.append(patch["max_distance_km"])
    if "usage_constraints" in patch:
        updates.append("usage_constraints = ?")
        args.append(M._json_dumps_list(_normalize_tags(patch["usage_constraints"])))
    if "cost_band_max" in patch:
        updates.append("cost_band_max = ?")
        args.append(_normalize_cost_band(patch["cost_band_max"], field_name="cost_band_max"))
    if "share_until" in patch:
        updates.append("share_until = ?")
        args.append(_normalize_share_until(patch["share_until"]))
    if "is_active" in patch:
        updates.append("is_active = ?")
        args.append(1 if patch["is_active"] else 0)
    # Validate final availability range after potential updates.
    existing = get_material_request(request_id, user_id) or {}
    start = args[updates.index("availability_start = ?")] if "availability_start = ?" in updates else existing.get("availability_start")
    end = args[updates.index("availability_end = ?")] if "availability_end = ?" in updates else existing.get("availability_end")
    if start and end and str(start) > str(end):
        raise ValueError("availability_start must be <= availability_end")
    updates.append("updated_at = ?")
    args.append(_now())
    args.extend([request_id, user_id])
    conn.execute(f"UPDATE material_requests SET {', '.join(updates)} WHERE id = ? AND user_id = ?", args)
    conn.commit()
    return get_material_request(request_id, user_id)


def delete_material_request(request_id: str, user_id: str) -> bool:
    conn = get_connection()
    cur = conn.execute("DELETE FROM material_requests WHERE id = ? AND user_id = ?", (request_id, user_id))
    conn.commit()
    return cur.rowcount > 0


def set_material_request_share_state(request_id: str, data: M.ShareStateUpdate, user_id: str) -> dict[str, Any] | None:
    existing = get_material_request(request_id, user_id)
    if existing is None:
        return None
    _validate_share_transition(existing.get("visibility") or "private", data.visibility)
    _validate_share_state(data.visibility, data.index_state)
    normalized_share_until = _normalize_share_until(data.share_until)
    if data.visibility in {"shared_unindexed", "shared_indexed"} and not (data.consent_version or "").strip():
        raise ValueError("consent_version is required when entering shared states")
    now = _now()
    revoked_at = now if data.visibility == "revoked" else None
    consent_at = now if data.visibility in {"shared_unindexed", "shared_indexed"} else existing.get("consent_at")
    if data.visibility in {"private", "inactive", "deleted"}:
        consent_at = existing.get("consent_at")
    conn = get_connection()
    conn.execute(
        """UPDATE material_requests
           SET visibility = ?, index_state = ?, consent_version = ?, consent_at = ?, share_until = ?,
               share_revoked_at = ?, state_changed_at = ?, updated_at = ?
           WHERE id = ? AND user_id = ?""",
        (
            data.visibility,
            data.index_state,
            data.consent_version or "",
            consent_at,
            normalized_share_until,
            revoked_at,
            now,
            now,
            request_id,
            user_id,
        ),
    )
    conn.commit()
    return get_material_request(request_id, user_id)


def list_material_offers(user_id: str) -> list[dict[str, Any]]:
    conn = get_connection()
    cur = conn.execute(f"{_material_offer_select_sql()} WHERE user_id = ? ORDER BY updated_at DESC", (user_id,))
    return [M.row_to_material_offer(tuple(r)) for r in cur.fetchall()]


def get_material_offer(offer_id: str, user_id: str) -> dict[str, Any] | None:
    conn = get_connection()
    row = conn.execute(
        f"{_material_offer_select_sql()} WHERE id = ? AND user_id = ?",
        (offer_id, user_id),
    ).fetchone()
    return M.row_to_material_offer(tuple(row)) if row else None


def create_material_offer(data: M.MaterialOfferCreate, user_id: str) -> dict[str, Any]:
    conn = get_connection()
    oid = M.new_id()
    now = _now()
    availability_start = _normalize_iso_datetime(data.availability_start, field_name="availability_start")
    availability_end = _normalize_iso_datetime(data.availability_end, field_name="availability_end")
    if availability_start and availability_end and availability_start > availability_end:
        raise ValueError("availability_start must be <= availability_end")
    conn.execute(
        """INSERT INTO material_offers (
          id, user_id, title, summary, material_type, resource_nature, category_tags, quantity_available, quantity_unit,
          availability_start, availability_end, condition_state, access_mode, location_region, service_area_km, usage_constraints,
          cost_band, visibility, index_state, consent_version, consent_at, share_until, share_revoked_at, state_changed_at,
          is_active, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'private', 'private', '', NULL, ?, NULL, ?, 1, ?, ?)""",
        (
            oid,
            user_id,
            data.title or "",
            data.summary or "",
            _normalize_nonempty_key("material_type", data.material_type),
            _normalize_resource_nature(data.resource_nature),
            M._json_dumps_list(_normalize_tags(data.category_tags)),
            _normalize_positive_quantity(data.quantity_available, field_name="quantity_available"),
            _normalize_quantity_unit(data.quantity_unit),
            availability_start,
            availability_end,
            _normalize_condition_value(data.condition_state, field_name="condition_state"),
            (data.access_mode or "").strip().lower(),
            (data.location_region or "").strip().lower(),
            data.service_area_km,
            M._json_dumps_list(_normalize_tags(data.usage_constraints)),
            _normalize_cost_band(data.cost_band, field_name="cost_band"),
            _normalize_share_until(data.share_until),
            now,
            now,
            now,
        ),
    )
    conn.commit()
    return get_material_offer(oid, user_id) or {}


def update_material_offer(offer_id: str, data: M.MaterialOfferUpdate, user_id: str) -> dict[str, Any] | None:
    if get_material_offer(offer_id, user_id) is None:
        return None
    patch = data.model_dump(exclude_unset=True)
    if not patch:
        return get_material_offer(offer_id, user_id)
    conn = get_connection()
    updates: list[str] = []
    args: list[Any] = []
    if "title" in patch:
        updates.append("title = ?")
        args.append(patch["title"] or "")
    if "summary" in patch:
        updates.append("summary = ?")
        args.append(patch["summary"] or "")
    if "material_type" in patch:
        updates.append("material_type = ?")
        args.append(_normalize_nonempty_key("material_type", patch["material_type"]))
    if "resource_nature" in patch:
        updates.append("resource_nature = ?")
        args.append(_normalize_resource_nature(patch["resource_nature"]))
    if "category_tags" in patch:
        updates.append("category_tags = ?")
        args.append(M._json_dumps_list(_normalize_tags(patch["category_tags"])))
    if "quantity_available" in patch:
        updates.append("quantity_available = ?")
        args.append(_normalize_positive_quantity(patch["quantity_available"], field_name="quantity_available"))
    if "quantity_unit" in patch:
        updates.append("quantity_unit = ?")
        args.append(_normalize_quantity_unit(patch["quantity_unit"]))
    if "availability_start" in patch:
        updates.append("availability_start = ?")
        args.append(_normalize_iso_datetime(patch["availability_start"], field_name="availability_start"))
    if "availability_end" in patch:
        updates.append("availability_end = ?")
        args.append(_normalize_iso_datetime(patch["availability_end"], field_name="availability_end"))
    if "condition_state" in patch:
        updates.append("condition_state = ?")
        args.append(_normalize_condition_value(patch["condition_state"], field_name="condition_state"))
    if "access_mode" in patch:
        updates.append("access_mode = ?")
        args.append((patch["access_mode"] or "").strip().lower())
    if "location_region" in patch:
        updates.append("location_region = ?")
        args.append((patch["location_region"] or "").strip().lower())
    if "service_area_km" in patch:
        updates.append("service_area_km = ?")
        args.append(patch["service_area_km"])
    if "usage_constraints" in patch:
        updates.append("usage_constraints = ?")
        args.append(M._json_dumps_list(_normalize_tags(patch["usage_constraints"])))
    if "cost_band" in patch:
        updates.append("cost_band = ?")
        args.append(_normalize_cost_band(patch["cost_band"], field_name="cost_band"))
    if "share_until" in patch:
        updates.append("share_until = ?")
        args.append(_normalize_share_until(patch["share_until"]))
    if "is_active" in patch:
        updates.append("is_active = ?")
        args.append(1 if patch["is_active"] else 0)
    existing = get_material_offer(offer_id, user_id) or {}
    start = args[updates.index("availability_start = ?")] if "availability_start = ?" in updates else existing.get("availability_start")
    end = args[updates.index("availability_end = ?")] if "availability_end = ?" in updates else existing.get("availability_end")
    if start and end and str(start) > str(end):
        raise ValueError("availability_start must be <= availability_end")
    updates.append("updated_at = ?")
    args.append(_now())
    args.extend([offer_id, user_id])
    conn.execute(f"UPDATE material_offers SET {', '.join(updates)} WHERE id = ? AND user_id = ?", args)
    conn.commit()
    return get_material_offer(offer_id, user_id)


def delete_material_offer(offer_id: str, user_id: str) -> bool:
    conn = get_connection()
    cur = conn.execute("DELETE FROM material_offers WHERE id = ? AND user_id = ?", (offer_id, user_id))
    conn.commit()
    return cur.rowcount > 0


def set_material_offer_share_state(offer_id: str, data: M.ShareStateUpdate, user_id: str) -> dict[str, Any] | None:
    existing = get_material_offer(offer_id, user_id)
    if existing is None:
        return None
    _validate_share_transition(existing.get("visibility") or "private", data.visibility)
    _validate_share_state(data.visibility, data.index_state)
    normalized_share_until = _normalize_share_until(data.share_until)
    if data.visibility in {"shared_unindexed", "shared_indexed"} and not (data.consent_version or "").strip():
        raise ValueError("consent_version is required when entering shared states")
    now = _now()
    revoked_at = now if data.visibility == "revoked" else None
    consent_at = now if data.visibility in {"shared_unindexed", "shared_indexed"} else existing.get("consent_at")
    if data.visibility in {"private", "inactive", "deleted"}:
        consent_at = existing.get("consent_at")
    conn = get_connection()
    conn.execute(
        """UPDATE material_offers
           SET visibility = ?, index_state = ?, consent_version = ?, consent_at = ?, share_until = ?,
               share_revoked_at = ?, state_changed_at = ?, updated_at = ?
           WHERE id = ? AND user_id = ?""",
        (
            data.visibility,
            data.index_state,
            data.consent_version or "",
            consent_at,
            normalized_share_until,
            revoked_at,
            now,
            now,
            offer_id,
            user_id,
        ),
    )
    conn.commit()
    return get_material_offer(offer_id, user_id)


def list_matchable_material_requests() -> list[dict[str, Any]]:
    conn = get_connection()
    now_dt = _now_dt()
    cur = conn.execute(
        f"""{_material_request_select_sql()}
            WHERE visibility = 'shared_indexed'
              AND index_state = 'shared_indexed'
              AND is_active = 1""",
    )
    out = [M.row_to_material_request(tuple(r)) for r in cur.fetchall()]
    return [row for row in out if _is_share_until_active(row.get("share_until"), now_dt)]


def list_matchable_material_offers() -> list[dict[str, Any]]:
    conn = get_connection()
    now_dt = _now_dt()
    cur = conn.execute(
        f"""{_material_offer_select_sql()}
            WHERE visibility = 'shared_indexed'
              AND index_state = 'shared_indexed'
              AND is_active = 1""",
    )
    out = [M.row_to_material_offer(tuple(r)) for r in cur.fetchall()]
    return [row for row in out if _is_share_until_active(row.get("share_until"), now_dt)]


# --- Prompt signals (lightweight user responses to system prompts) ---

_MAX_DEFERRED_PROMPTS_IN_UI = 7


def _parse_iso_utc_optional(value: str | None) -> datetime | None:
    if not value or not str(value).strip():
        return None
    t = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def insert_prompt_signal(
    user_id: str,
    *,
    prompt_id: str,
    action: str,
    entity_type: str | None,
    entity_id: str | None,
    prompt_summary: str = "",
    deferred_until: str | None = None,
) -> dict[str, Any]:
    """
    Append-only user stance on one prompt instance.

    * engaged — user chose to discuss; does not mean the issue is resolved.
    * deferred — user asked to revisit later; not an endorsement of the prompt.
    * dismissed — suppress reinjection for the default window; not a permanent rejection.
    """
    pid = (prompt_id or "").strip()
    if not pid:
        raise ValueError("prompt_id is required")
    act = (action or "").strip().lower()
    if act not in ("engaged", "dismissed", "deferred"):
        raise ValueError("action must be engaged, dismissed, or deferred")
    if act == "deferred" and not (deferred_until or "").strip():
        raise ValueError("deferred_until is required for deferred action")
    et = (entity_type or "").strip() or None
    eid = (entity_id or "").strip() or None
    if et and not eid:
        raise ValueError("entity_id is required when entity_type is set")
    if eid and not et:
        raise ValueError("entity_type is required when entity_id is set")
    rid = secrets.token_urlsafe(16)
    now = _now()
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO prompt_signals (
          id, user_id, prompt_id, action, entity_type, entity_id, prompt_summary, deferred_until, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (rid, user_id, pid, act, et, eid, (prompt_summary or "")[:4000], (deferred_until or "").strip() or None, now),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM prompt_signals WHERE id = ?", (rid,)).fetchone()
    return dict(row) if row else {"id": rid}


def recently_dismissed_prompt(user_id: str, prompt_id: str, *, within_days: int = 7) -> bool:
    """True if this exact ``prompt_id`` was dismissed within ``within_days`` (entity not part of match)."""
    pid = (prompt_id or "").strip()
    if not pid:
        return False
    days = max(1, min(int(within_days), 366))
    conn = get_connection()
    r = conn.execute(
        f"""
        SELECT 1 FROM prompt_signals
        WHERE user_id = ? AND prompt_id = ? AND action = 'dismissed'
          AND datetime(created_at) > datetime('now', '-{days} days')
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (user_id, pid),
    ).fetchone()
    return r is not None


def active_future_defer_blocks_prompt(user_id: str, prompt_id: str) -> bool:
    """
    True when the user has a deferred row for this ``prompt_id`` with ``deferred_until`` still in the future,
    and no later dismiss supersedes that defer (global dismiss with NULL entity counts).
    """
    pid = (prompt_id or "").strip()
    if not pid:
        return False
    conn = get_connection()
    r = conn.execute(
        """
        SELECT 1 FROM prompt_signals p
        WHERE p.user_id = ? AND p.prompt_id = ? AND p.action = 'deferred'
          AND p.deferred_until IS NOT NULL
          AND datetime(p.deferred_until) > datetime('now')
          AND NOT EXISTS (
            SELECT 1 FROM prompt_signals d
            WHERE d.user_id = p.user_id
              AND d.prompt_id = p.prompt_id
              AND d.action = 'dismissed'
              AND d.created_at > p.created_at
              AND (
                (IFNULL(d.entity_type, '') = IFNULL(p.entity_type, '')
                 AND IFNULL(d.entity_id, '') = IFNULL(p.entity_id, ''))
                OR (d.entity_type IS NULL AND d.entity_id IS NULL)
              )
          )
        ORDER BY p.created_at DESC
        LIMIT 1
        """,
        (user_id, pid),
    ).fetchone()
    return r is not None


def list_active_deferred_prompts_for_entity(
    user_id: str, entity_type: str, entity_id: str
) -> list[dict[str, Any]]:
    """
    Deferred rows for one entity scope, excluding those superseded by a later dismiss.

    A dismiss with NULL entity (global for that ``prompt_id``) also clears the reminder so the
    list stays aligned with chat reinjection suppression. Results: one row per ``prompt_id`` (latest
    defer), sorted due-first then soonest upcoming, capped for a small UI surface.
    """
    et = (entity_type or "").strip()
    eid = (entity_id or "").strip()
    if not et or not eid:
        return []
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT p.id, p.prompt_id, p.prompt_summary, p.deferred_until, p.created_at
        FROM prompt_signals p
        WHERE p.user_id = ?
          AND p.entity_type = ?
          AND p.entity_id = ?
          AND p.action = 'deferred'
          AND NOT EXISTS (
            SELECT 1 FROM prompt_signals d
            WHERE d.user_id = p.user_id
              AND d.prompt_id = p.prompt_id
              AND d.action = 'dismissed'
              AND d.created_at > p.created_at
              AND (
                (IFNULL(d.entity_type, '') = IFNULL(p.entity_type, '')
                 AND IFNULL(d.entity_id, '') = IFNULL(p.entity_id, ''))
                OR (d.entity_type IS NULL AND d.entity_id IS NULL)
              )
          )
        ORDER BY p.created_at DESC
        """,
        (user_id, et, eid),
    ).fetchall()
    raw = [dict(x) for x in rows]
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for r in raw:
        pid = (r.get("prompt_id") or "").strip()
        if not pid or pid in seen:
            continue
        seen.add(pid)
        deduped.append(r)
    now = _now_dt()

    def _sort_key(rec: dict[str, Any]) -> tuple[int, float, float]:
        du = _parse_iso_utc_optional(rec.get("deferred_until"))
        ca = _parse_iso_utc_optional(rec.get("created_at"))
        ca_ts = ca.timestamp() if ca else 0.0
        if du is not None and du <= now:
            return (0, du.timestamp(), -ca_ts)
        sec = du.timestamp() if du is not None else float("inf")
        return (1, sec, -ca_ts)

    deduped.sort(key=_sort_key)
    return deduped[:_MAX_DEFERRED_PROMPTS_IN_UI]


# --- Workspace messages (user-to-user inbox; extraction handoff + matching context) ---


def list_workspace_users_directory(exclude_user_id: str) -> list[dict[str, Any]]:
    conn = get_connection()
    cur = conn.execute(
        "SELECT id, email, display_name FROM users WHERE id != ? ORDER BY display_name COLLATE NOCASE, email COLLATE NOCASE",
        (exclude_user_id,),
    )
    return [{"id": r["id"], "email": r["email"], "display_name": r["display_name"] or r["email"]} for r in cur.fetchall()]


def _workspace_message_row_dict(row: sqlite3.Row) -> dict[str, Any]:
    body = json.loads(row["body_json"] or "{}")
    if not isinstance(body, dict):
        body = {}
    return {
        "id": row["id"],
        "from_user_id": row["from_user_id"],
        "to_user_id": row["to_user_id"],
        "from_display_name": row["from_display_name"] or row["from_email"],
        "to_display_name": row["to_display_name"] or row["to_email"],
        "title": row["title"] or "",
        "body": body,
        "read_at": row["read_at"],
        "created_at": row["created_at"],
    }


def list_workspace_messages(user_id: str, box: str) -> list[dict[str, Any]]:
    conn = get_connection()
    if box == "inbox":
        cur = conn.execute(
            """
            SELECT m.id, m.from_user_id, m.to_user_id, m.title, m.body_json, m.read_at, m.created_at,
                   uf.display_name AS from_display_name, uf.email AS from_email,
                   ut.display_name AS to_display_name, ut.email AS to_email
            FROM workspace_messages m
            JOIN users uf ON uf.id = m.from_user_id
            JOIN users ut ON ut.id = m.to_user_id
            WHERE m.to_user_id = ?
            ORDER BY m.created_at DESC
            """,
            (user_id,),
        )
    elif box == "sent":
        cur = conn.execute(
            """
            SELECT m.id, m.from_user_id, m.to_user_id, m.title, m.body_json, m.read_at, m.created_at,
                   uf.display_name AS from_display_name, uf.email AS from_email,
                   ut.display_name AS to_display_name, ut.email AS to_email
            FROM workspace_messages m
            JOIN users uf ON uf.id = m.from_user_id
            JOIN users ut ON ut.id = m.to_user_id
            WHERE m.from_user_id = ?
            ORDER BY m.created_at DESC
            """,
            (user_id,),
        )
    else:
        return []
    return [_workspace_message_row_dict(r) for r in cur.fetchall()]


def create_workspace_message(from_user_id: str, to_user_id: str, title: str, body: dict[str, Any]) -> dict[str, Any]:
    if from_user_id == to_user_id:
        raise ValueError("Cannot send a message to yourself")
    if get_user_by_id(to_user_id) is None:
        raise ValueError("Recipient user not found")
    mid = M.new_id()
    now = _now()
    conn = get_connection()
    conn.execute(
        """INSERT INTO workspace_messages (id, from_user_id, to_user_id, title, body_json, read_at, created_at)
           VALUES (?, ?, ?, ?, ?, NULL, ?)""",
        (mid, from_user_id, to_user_id, title or "", json.dumps(body), now),
    )
    conn.commit()
    rows = conn.execute(
        """
        SELECT m.id, m.from_user_id, m.to_user_id, m.title, m.body_json, m.read_at, m.created_at,
               uf.display_name AS from_display_name, uf.email AS from_email,
               ut.display_name AS to_display_name, ut.email AS to_email
        FROM workspace_messages m
        JOIN users uf ON uf.id = m.from_user_id
        JOIN users ut ON ut.id = m.to_user_id
        WHERE m.id = ?
        """,
        (mid,),
    ).fetchall()
    if not rows:
        return {"id": mid, "from_user_id": from_user_id, "to_user_id": to_user_id, "title": title, "body": body, "read_at": None, "created_at": now}
    return _workspace_message_row_dict(rows[0])


def mark_workspace_message_read(message_id: str, user_id: str) -> bool:
    """Returns True if the message exists for this recipient (marks read or was already read)."""
    conn = get_connection()
    row = conn.execute(
        "SELECT read_at FROM workspace_messages WHERE id = ? AND to_user_id = ?",
        (message_id, user_id),
    ).fetchone()
    if row is None:
        return False
    if row["read_at"]:
        return True
    now = _now()
    conn.execute(
        "UPDATE workspace_messages SET read_at = ? WHERE id = ? AND to_user_id = ?",
        (now, message_id, user_id),
    )
    conn.commit()
    return True


def count_unread_workspace_messages(user_id: str) -> int:
    conn = get_connection()
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM workspace_messages WHERE to_user_id = ? AND read_at IS NULL",
        (user_id,),
    ).fetchone()
    return int(row["n"] or 0) if row else 0
