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
from datetime import datetime, timezone, timedelta
from typing import Any

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


def _ve_task_status_done(status: str | None) -> bool:
    if not status or not str(status).strip():
        return False
    return bool(_VE_TASK_DONE_STATUS_RE.search(str(status)))


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
          use_in_guidance INTEGER NOT NULL DEFAULT 0 CHECK (use_in_guidance IN (0, 1)),
          allow_inference INTEGER NOT NULL DEFAULT 0 CHECK (allow_inference IN (0, 1)),
          updated_at TEXT NOT NULL,
          FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
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
    Order: user home (typical), then repo data dir next to the SQLite DB (reliable on Windows / OneDrive).
    """
    return [
        Path.home() / ".zenaf" / _SETTINGS_KEY_LOCAL_FILE,
        _DB_DIR / _SETTINGS_KEY_LOCAL_FILE,
    ]


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
              use_in_guidance, allow_inference, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    "experimental_google_model": "gemini-2.5-flash",
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
        conn.commit()
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
    conn.commit()
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
    conn.commit()
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
    # "governance" kept for historical judgments; the Mediator inherits that seat's DNA.
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
        "SELECT id, title, summary, description, status, tags, created_by, desired_outcome, "
        "linked_people, linked_assets, linked_ideas, created_at, updated_at, notes FROM ideas "
        "WHERE user_id = ? ORDER BY updated_at DESC",
        (user_id,),
    )
    return [M.row_to_idea(tuple(r)) for r in cur.fetchall()]


def get_idea(idea_id: str, user_id: str) -> dict[str, Any] | None:
    conn = get_connection()
    cur = conn.execute(
        "SELECT id, title, summary, description, status, tags, created_by, desired_outcome, "
        "linked_people, linked_assets, linked_ideas, created_at, updated_at, notes FROM ideas WHERE id = ? AND user_id = ?",
        (idea_id, user_id),
    )
    row = cur.fetchone()
    return M.row_to_idea(tuple(row)) if row else None


def create_idea(data: M.IdeaCreate, user_id: str) -> dict[str, Any]:
    conn = get_connection()
    iid = M.new_id()
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
    conn.commit()
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
    conn.execute(f"UPDATE ideas SET {', '.join(updates)} WHERE id = ? AND user_id = ?", args + [user_id])
    conn.commit()
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
    conn.execute(
        "UPDATE initiatives SET source_idea_id = NULL WHERE source_idea_id = ? AND user_id = ?",
        (idea_id, user_id),
    )
    conn.execute("DELETE FROM ideas WHERE id = ? AND user_id = ?", (idea_id, user_id))
    conn.commit()
    _log_ve_entity_activity(
        type=ActivityType.IDEA_DELETED.value,
        entity_type=ActivityEntityType.IDEA.value,
        entity_id=idea_id,
        user_id=user_id,
        related_entity_id=None,
        detail="deleted",
    )
    return True


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
            "manual_override, kill_criteria, notes, created_at, updated_at FROM initiatives ORDER BY updated_at DESC"
        )
    else:
        cur = conn.execute(
            "SELECT id, source_idea_id, title, brief, status, owner_id, priority_rank_manual, strategic_value_manual, "
            "energy_impact_manual, evaluation_priority, estimated_cost_ai, estimated_timeframe_ai, philosophical_alignment_ai, next_step_ai, "
            "required_people, required_assets, dependencies, risks, recommendation, counts_toward_capacity, "
            "manual_override, kill_criteria, notes, created_at, updated_at FROM initiatives WHERE user_id = ? ORDER BY updated_at DESC",
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
            "manual_override, kill_criteria, notes, created_at, updated_at FROM initiatives WHERE id = ?",
            (initiative_id,),
        )
    else:
        cur = conn.execute(
            "SELECT id, source_idea_id, title, brief, status, owner_id, priority_rank_manual, strategic_value_manual, "
            "energy_impact_manual, evaluation_priority, estimated_cost_ai, estimated_timeframe_ai, philosophical_alignment_ai, next_step_ai, "
            "required_people, required_assets, dependencies, risks, recommendation, counts_toward_capacity, "
            "manual_override, kill_criteria, notes, created_at, updated_at FROM initiatives WHERE id = ? AND user_id = ?",
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
    conn.execute(
        """INSERT INTO initiatives (
          id, user_id, source_idea_id, title, brief, status, owner_id,
          evaluation_priority, estimated_cost_ai, estimated_timeframe_ai, philosophical_alignment_ai, next_step_ai,
          required_assets, dependencies, risks, recommendation,
          kill_criteria, notes, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            iid, user_id, data.source_idea_id, data.title, data.brief, data.status, data.owner_id,
            data.evaluation_priority,
            data.estimated_cost_ai, data.estimated_timeframe_ai, data.philosophical_alignment_ai, data.next_step_ai,
            M._json_dumps_list(data.required_assets),
            data.dependencies, data.risks, data.recommendation,
            data.kill_criteria, data.notes, now, now,
        ),
    )
    if seats_to_persist:
        _upsert_initiative_seats(conn, iid, seats_to_persist)
    conn.commit()
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

    if seats_to_persist is not None:
        _upsert_initiative_seats(conn, initiative_id, seats_to_persist)

    if not updates:
        return get_initiative(initiative_id, user_id)

    updates.append("updated_at = ?")
    args.append(_now())
    args.append(initiative_id)
    conn.execute(f"UPDATE initiatives SET {', '.join(updates)} WHERE id = ? AND user_id = ?", args + [user_id])
    conn.commit()
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
    if sort_order is None:
        cur = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) FROM execution_steps WHERE user_id = ? AND scope_type = ? AND scope_id = ?",
            (user_id, scope_type, scope_id),
        )
        sort_order = int(cur.fetchone()[0]) + 1
    sid = M.new_id()
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
    conn.commit()
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
    conn.execute(
        f"UPDATE execution_steps SET {', '.join(updates)} WHERE id = ? AND user_id = ?",
        args,
    )
    conn.commit()
    return get_execution_step(step_id, user_id)


def delete_execution_step(step_id: str, user_id: str) -> bool:
    if get_execution_step(step_id, user_id) is None:
        return False
    conn = get_connection()
    conn.execute("DELETE FROM execution_steps WHERE id = ? AND user_id = ?", (step_id, user_id))
    conn.commit()
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
    conn.commit()
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
    for i, sid in enumerate(ordered_ids):
        conn.execute(
            "UPDATE execution_steps SET sort_order = ?, updated_at = ? WHERE id = ? AND user_id = ?",
            (i, now, sid, user_id),
        )
    conn.commit()
    return list_execution_steps(scope_type, scope_id, user_id)


def delete_initiative(initiative_id: str, user_id: str) -> bool:
    before = get_initiative(initiative_id, user_id)
    if before is None:
        return False
    sid_raw = before.get("source_idea_id")
    src = _ve_activity_related_id(str(sid_raw).strip() if sid_raw is not None else None)
    conn = get_connection()
    conn.execute(
        "DELETE FROM execution_steps WHERE user_id = ? AND scope_type = ? AND scope_id = ?",
        (user_id, EXECUTION_STEPS_SCOPE_INITIATIVE, initiative_id),
    )
    conn.execute(
        "UPDATE projects SET initiative_id = NULL WHERE initiative_id = ? AND user_id = ?",
        (initiative_id, user_id),
    )
    conn.execute("DELETE FROM initiatives WHERE id = ? AND user_id = ?", (initiative_id, user_id))
    conn.commit()
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


def create_project(data: M.ProjectCreate, user_id: str) -> dict[str, Any]:
    conn = get_connection()
    pid = M.new_id()
    now = _now()
    _ensure_owned_reference(
        conn,
        table="initiatives",
        ref_id=data.initiative_id,
        user_id=user_id,
        field_name="initiative_id",
    )
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
    conn.commit()
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
    conn.execute(f"UPDATE projects SET {', '.join(updates)} WHERE id = ? AND user_id = ?", args + [user_id])
    conn.commit()
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
    conn.execute(
        "DELETE FROM execution_steps WHERE user_id = ? AND scope_type = ? AND scope_id = ?",
        (user_id, EXECUTION_STEPS_SCOPE_PROJECT, project_id),
    )
    conn.execute("DELETE FROM tasks WHERE project_id = ? AND user_id = ?", (project_id, user_id))
    conn.execute("DELETE FROM projects WHERE id = ? AND user_id = ?", (project_id, user_id))
    conn.commit()
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

def list_tasks(
    user_id: str | None = None,
    project_id: str | None = None,
    initiative_id: str | None = None,
) -> list[dict[str, Any]]:
    conn = get_connection()
    if initiative_id and user_id is not None:
        cur = conn.execute(
            """
            SELECT t.id, t.project_id, t.parent_task_id, t.title, t.description, t.assignee_id, t.status, t.priority,
            t.estimated_hours, t.due_date, t.dependency_ids, t.required_asset_ids, t.completion_criteria, t.notes, t.created_at, t.updated_at
            FROM tasks t
            INNER JOIN projects p ON p.id = t.project_id AND p.user_id = t.user_id
            WHERE p.initiative_id = ? AND t.user_id = ?
            ORDER BY t.updated_at DESC
            """,
            (initiative_id, user_id),
        )
        return [M.row_to_task(tuple(r)) for r in cur.fetchall()]
    if project_id and user_id is not None:
        cur = conn.execute(
            "SELECT id, project_id, parent_task_id, title, description, assignee_id, status, priority, "
            "estimated_hours, due_date, dependency_ids, required_asset_ids, completion_criteria, notes, created_at, updated_at "
            "FROM tasks WHERE project_id = ? AND user_id = ? ORDER BY updated_at DESC",
            (project_id, user_id),
        )
    elif project_id:
        cur = conn.execute(
            "SELECT id, project_id, parent_task_id, title, description, assignee_id, status, priority, "
            "estimated_hours, due_date, dependency_ids, required_asset_ids, completion_criteria, notes, created_at, updated_at "
            "FROM tasks WHERE project_id = ? ORDER BY updated_at DESC",
            (project_id,),
        )
    elif user_id is not None:
        cur = conn.execute(
            "SELECT id, project_id, parent_task_id, title, description, assignee_id, status, priority, "
            "estimated_hours, due_date, dependency_ids, required_asset_ids, completion_criteria, notes, created_at, updated_at "
            "FROM tasks WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        )
    else:
        cur = conn.execute(
            "SELECT id, project_id, parent_task_id, title, description, assignee_id, status, priority, "
            "estimated_hours, due_date, dependency_ids, required_asset_ids, completion_criteria, notes, created_at, updated_at "
            "FROM tasks ORDER BY updated_at DESC"
        )
    return [M.row_to_task(tuple(r)) for r in cur.fetchall()]


def get_task(task_id: str, user_id: str | None = None) -> dict[str, Any] | None:
    conn = get_connection()
    if user_id is None:
        cur = conn.execute(
            "SELECT id, project_id, parent_task_id, title, description, assignee_id, status, priority, "
            "estimated_hours, due_date, dependency_ids, required_asset_ids, completion_criteria, notes, created_at, updated_at "
            "FROM tasks WHERE id = ?",
            (task_id,),
        )
    else:
        cur = conn.execute(
            "SELECT id, project_id, parent_task_id, title, description, assignee_id, status, priority, "
            "estimated_hours, due_date, dependency_ids, required_asset_ids, completion_criteria, notes, created_at, updated_at "
            "FROM tasks WHERE id = ? AND user_id = ?",
            (task_id, user_id),
        )
    row = cur.fetchone()
    return M.row_to_task(tuple(row)) if row else None


def create_task(data: M.TaskCreate, user_id: str) -> dict[str, Any]:
    conn = get_connection()
    tid = M.new_id()
    now = _now()
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
    conn.execute(
        """INSERT INTO tasks (
          id, user_id, project_id, parent_task_id, title, description, assignee_id, status, priority,
          estimated_hours, due_date, dependency_ids, required_asset_ids, completion_criteria, notes, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            tid, user_id, data.project_id, data.parent_task_id, data.title, data.description, data.assignee_id,
            data.status, data.priority, data.estimated_hours, data.due_date,
            M._json_dumps_list(data.dependency_ids), M._json_dumps_list(data.required_asset_ids),
            data.completion_criteria, data.notes, now, now,
        ),
    )
    conn.commit()
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
        if v is not None or (k in nullable_fks):
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
    conn.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id = ? AND user_id = ?", args + [user_id])
    conn.commit()
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


def delete_task(task_id: str, user_id: str) -> bool:
    before = get_task(task_id, user_id)
    if before is None:
        return False
    proj = _ve_activity_related_id(str(before.get("project_id") or "").strip() or None)
    conn = get_connection()
    conn.execute(
        "UPDATE tasks SET parent_task_id = NULL WHERE parent_task_id = ? AND user_id = ?",
        (task_id, user_id),
    )
    conn.execute("DELETE FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id))
    conn.commit()
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

def create_decision(data: M.DecisionCreate) -> dict[str, Any]:
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
    out = get_decision(did) or {}
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


def get_decision(decision_id: str) -> dict[str, Any] | None:
    conn = get_connection()
    cur = conn.execute(
        "SELECT id, user_id, entity_type, entity_id, decision_type, ai_proposal_snapshot, final_values_snapshot, created_at FROM decisions WHERE id = ?",
        (decision_id,),
    )
    row = cur.fetchone()
    return M.row_to_decision(tuple(row)) if row else None


def list_decisions(entity_type: str | None = None, entity_id: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    conn = get_connection()
    if entity_type and entity_id:
        cur = conn.execute(
            "SELECT id, user_id, entity_type, entity_id, decision_type, ai_proposal_snapshot, final_values_snapshot, created_at "
            "FROM decisions WHERE entity_type = ? AND entity_id = ? ORDER BY created_at DESC LIMIT ?",
            (entity_type, entity_id, limit),
        )
    elif entity_type:
        cur = conn.execute(
            "SELECT id, user_id, entity_type, entity_id, decision_type, ai_proposal_snapshot, final_values_snapshot, created_at "
            "FROM decisions WHERE entity_type = ? ORDER BY created_at DESC LIMIT ?",
            (entity_type, limit),
        )
    else:
        cur = conn.execute(
            "SELECT id, user_id, entity_type, entity_id, decision_type, ai_proposal_snapshot, final_values_snapshot, created_at "
            "FROM decisions ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
    return [M.row_to_decision(tuple(r)) for r in cur.fetchall()]


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
