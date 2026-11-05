"""Standing-permission stance store (Slice 1, foundation).

EXTENDS the existing ``user_permissions_settings`` store; it does not
rebuild it and does not create a new permission store (Rev2 OQ2,
inventory §3 Slice 1):

- The boolean-flag blob (``permissions_json``) and the consent fields
  are untouched by every function here. The existing Settings toggles
  keep working against the migrated store: flag reads/writes go
  through ``normalize_user_permission_prefs`` /
  ``get_user_permissions_settings`` /
  ``upsert_user_permissions_settings`` exactly as before, and stance
  reads/writes never touch those columns.
- Stance records live in two new columns on the SAME row
  (``stances_json``, ``pause_json``), added by
  ``ensure_permission_framework_schema`` (PRAGMA + ALTER for existing
  databases, same pattern as the avatar-data-url migration) and by
  ``_migrate_user_permissions_settings`` in vision-execution storage
  for production databases.
- Stance history is append-only in spirit (Rev2 §2.1): every stance
  change appends one row to ``user_permission_stance_history`` in the
  same store and connection. A stance change never rewrites the fact
  that an earlier stance was held.

Pause (corrections C4, clarification I.1) is an INDEPENDENT record
(``pause_json``), checked BEFORE the stance by the framework check,
never by rewriting stances. ``set_pause`` / ``clear_pause`` write
only ``pause_json``: a pause cycle leaves ``stances_json`` and the
history table byte-identical (C4-T4).

Layering (Rev2 §2.6, inventory G26): stance storage is NOT scopes.
Nothing here reads or writes the identity-scope ledger, and no stance
write grants a scope.

No model calls anywhere on this path: every function here is a
lookup or a row write.

All functions accept an injectable ``connection`` (tests pass a tmp
SQLite connection, mirroring the steward-gate pattern). When omitted,
the vision-execution storage connection is used — imported lazily so
this module stays importable without the storage module.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from .registry import (
    ASK_ME,
    DONT_DO_IT,
    JUST_DO_IT,
    get_capability,
    is_registered,
    is_valid_row,
)

#: Surface label recorded when a stance record comes from the flag
#: migration (inventory §3 Slice 1(d), Rev2 OQ3).
SURFACE_FLAG_MIGRATION = "flag_migration"

#: Surface label for a stance record set through Settings. Slice 1
#: records the surface; the Slice 2 Settings surface writes it.
SURFACE_SETTINGS = "settings"

_STANCES_COLUMNS = {
    "stances_json": "TEXT NOT NULL DEFAULT '{}'",
    "pause_json": "TEXT NOT NULL DEFAULT '{}'",
}

_HISTORY_DDL = """
CREATE TABLE IF NOT EXISTS user_permission_stance_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  capability TEXT NOT NULL,
  row_key TEXT NOT NULL,
  old_stance TEXT,
  new_stance TEXT NOT NULL,
  surface TEXT NOT NULL DEFAULT '',
  changed_at TEXT NOT NULL
)
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_connection() -> sqlite3.Connection:
    from local_ai.vision_execution.storage import get_connection

    return get_connection()


def ensure_permission_framework_schema(conn: sqlite3.Connection) -> None:
    """Create the Slice 1 stance-store schema on ``conn`` if missing.

    Idempotent: safe to call on every stance-store access. Adds the
    two columns to an existing ``user_permissions_settings`` table
    (PRAGMA check + ALTER, no backfill — existing rows read the
    ``'{}'`` default, i.e. no stances and no pause, exactly as if
    the user had never set one) and creates the append-only history
    table. Does nothing when the base table does not exist yet
    (callers that need a row create it via ``_ensure_user_row``).
    """
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    if "user_permissions_settings" in tables:
        cols = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(user_permissions_settings)"
            ).fetchall()
        }
        for column, ddl in _STANCES_COLUMNS.items():
            if column not in cols:
                conn.execute(
                    f"ALTER TABLE user_permissions_settings ADD COLUMN "
                    f"{column} {ddl}"
                )
    conn.execute(_HISTORY_DDL)
    conn.commit()


def _conn(connection: sqlite3.Connection | None) -> sqlite3.Connection:
    conn = connection if connection is not None else _default_connection()
    ensure_permission_framework_schema(conn)
    return conn


def _ensure_user_row(conn: sqlite3.Connection, user_id: str) -> None:
    """Insert a minimal permissions row for a write path, if absent.

    Write paths only (``set_stance``, ``set_pause``). Read paths
    never insert — mirroring the steward gate's discipline, a stance
    read for an unknown user returns defaults without creating state.
    The minimal row carries consent_given=0 and an empty flag blob,
    so creating it opts nobody into anything.
    """
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    if "user_permissions_settings" not in tables:
        conn.execute(
            "CREATE TABLE user_permissions_settings ("
            "user_id TEXT PRIMARY KEY, permissions_json TEXT, "
            "updated_at TEXT)"
        )
        conn.commit()
        ensure_permission_framework_schema(conn)
    row = conn.execute(
        "SELECT user_id FROM user_permissions_settings WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row is not None:
        return
    cols = {
        r[1]
        for r in conn.execute(
            "PRAGMA table_info(user_permissions_settings)"
        ).fetchall()
    }
    # Minimal tmp tables in older tests have only (user_id,
    # permissions_json, updated_at); production rows have the consent
    # columns too. Insert only columns the table actually has.
    values: dict[str, Any] = {"user_id": user_id}
    if "permissions_json" in cols:
        values["permissions_json"] = "{}"
    if "updated_at" in cols:
        values["updated_at"] = _now()
    if "consent_given" in cols:
        values["consent_given"] = 0
    if "consent_version" in cols:
        values["consent_version"] = ""
    if "consent_at" in cols:
        values["consent_at"] = None
    if "stances_json" in cols:
        values["stances_json"] = "{}"
    if "pause_json" in cols:
        values["pause_json"] = json.dumps(_default_pause())
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    conn.execute(
        f"INSERT INTO user_permissions_settings ({columns}) "
        f"VALUES ({placeholders})",
        tuple(values.values()),
    )
    conn.commit()


def _default_pause() -> dict[str, Any]:
    return {"paused": False, "paused_at": None, "surface": None}


def _read_framework_blobs(
    conn: sqlite3.Connection, user_id: str
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """Return (stances, pause, row_exists) for the user, never inserting."""
    cols = {
        r[1]
        for r in conn.execute(
            "PRAGMA table_info(user_permissions_settings)"
        ).fetchall()
    }
    if "stances_json" not in cols or "pause_json" not in cols:
        return {}, _default_pause(), False
    row = conn.execute(
        "SELECT stances_json, pause_json FROM user_permissions_settings "
        "WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        return {}, _default_pause(), False
    try:
        stances = json.loads(row[0] or "{}")
    except (json.JSONDecodeError, TypeError):
        stances = {}
    try:
        pause = json.loads(row[1] or "{}")
    except (json.JSONDecodeError, TypeError):
        pause = {}
    if not isinstance(stances, dict):
        stances = {}
    if not isinstance(pause, dict):
        pause = _default_pause()
    pause = {
        "paused": bool(pause.get("paused", False)),
        "paused_at": pause.get("paused_at"),
        "surface": pause.get("surface"),
    }
    return stances, pause, True


def _write_stances(
    conn: sqlite3.Connection, user_id: str, stances: dict[str, Any]
) -> None:
    conn.execute(
        "UPDATE user_permissions_settings SET stances_json = ? "
        "WHERE user_id = ?",
        (json.dumps(stances, sort_keys=True), user_id),
    )
    conn.commit()


def get_stances(
    user_id: str, *, connection: sqlite3.Connection | None = None
) -> dict[str, dict[str, dict[str, Any]]]:
    """All stance records for the user, grouped by capability and row.

    Read-only: unknown users return {} without creating a row. Each
    record carries capability, row_key, stance, stated limits +
    "does NOT allow" text, granted_at / last_changed_at, and surface
    of change (Rev2 §2.1 record shape).
    """
    conn = _conn(connection)
    stances, _pause, _exists = _read_framework_blobs(conn, user_id)
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for capability, rows in stances.items():
        if not isinstance(rows, dict):
            continue
        for row_key, record in rows.items():
            if not isinstance(record, dict):
                continue
            out.setdefault(capability, {})[row_key] = dict(record)
    return out


def get_stance(
    user_id: str,
    capability: str,
    row_key: str | None,
    *,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any] | None:
    """One stance record, or None if the user never set that row."""
    conn = _conn(connection)
    stances, _pause, _exists = _read_framework_blobs(conn, user_id)
    rows = stances.get(capability)
    if not isinstance(rows, dict):
        return None
    record = rows.get("all" if row_key is None else row_key)
    return dict(record) if isinstance(record, dict) else None


def set_stance(
    user_id: str,
    capability: str,
    row_key: str | None,
    stance: str,
    *,
    surface: str,
    limits_text: str = "",
    does_not_allow: str = "",
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Write one stance record. Validates against the registry.

    Rejects (ValueError): unregistered capabilities (including R7),
    stances the capability does not support (e.g. Ask me for R4/R5),
    and row keys that are not rows of the capability. A write that
    repeats the current stance is a no-op returning the existing
    record (no history row: idempotent writes are not changes).

    A stance write succeeds even while the global pause override is
    set (clarification I.1 rule 2): the write is durable, visible,
    and revocable, but it takes no effect for new operations until
    un-pause — the pause record is independent and untouched here.
    Never touches ``permissions_json`` or any consent field.
    """
    entry = get_capability(capability)
    if entry is None:
        raise ValueError(f"unregistered capability: {capability!r}")
    if stance not in entry.supported_stances:
        raise ValueError(
            f"capability {capability} does not support stance {stance!r}"
        )
    key = "all" if row_key is None else row_key
    if not is_valid_row(capability, key):
        raise ValueError(f"capability {capability} has no row {key!r}")
    conn = _conn(connection)
    _ensure_user_row(conn, user_id)
    stances, _pause, _exists = _read_framework_blobs(conn, user_id)
    rows = stances.setdefault(capability, {})
    if not isinstance(rows, dict):
        rows = stances[capability] = {}
    now = _now()
    existing = rows.get(key)
    if isinstance(existing, dict) and existing.get("stance") == stance:
        return dict(existing)
    old_stance = existing.get("stance") if isinstance(existing, dict) else None
    granted_at = (
        existing.get("granted_at")
        if isinstance(existing, dict) and existing.get("granted_at")
        else now
    )
    record = {
        "capability": capability,
        "row_key": key,
        "stance": stance,
        "limits_text": limits_text,
        "does_not_allow": does_not_allow
        or entry.does_not_allow,
        "granted_at": granted_at,
        "last_changed_at": now,
        "surface": surface,
    }
    rows[key] = record
    _write_stances(conn, user_id, stances)
    conn.execute(
        "INSERT INTO user_permission_stance_history "
        "(user_id, capability, row_key, old_stance, new_stance, surface, changed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, capability, key, old_stance, stance, surface, now),
    )
    conn.commit()
    return dict(record)


def get_pause(
    user_id: str, *, connection: sqlite3.Connection | None = None
) -> dict[str, Any]:
    """The global pause override record (C4.3: independent of stances).

    Read-only: unknown users return ``{"paused": False, ...}`` without
    creating a row.
    """
    conn = _conn(connection)
    _stances, pause, _exists = _read_framework_blobs(conn, user_id)
    return pause


def set_pause(
    user_id: str,
    paused: bool,
    *,
    surface: str,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Set or clear the global pause override. Writes ONLY pause_json.

    Pausing never rewrites a stance, never writes permission history,
    and never changes a disposition (C4.2(d), C4-T4). Un-pausing
    restores exactly the stances held before pausing, because they
    were never touched.
    """
    conn = _conn(connection)
    _ensure_user_row(conn, user_id)
    record = {
        "paused": bool(paused),
        "paused_at": _now() if paused else None,
        "surface": surface,
    }
    conn.execute(
        "UPDATE user_permissions_settings SET pause_json = ? WHERE user_id = ?",
        (json.dumps(record, sort_keys=True), user_id),
    )
    conn.commit()
    return dict(record)


def stance_history(
    user_id: str, *, connection: sqlite3.Connection | None = None
) -> list[dict[str, Any]]:
    """Append-only stance-change history for the user, oldest first."""
    conn = _conn(connection)
    rows = conn.execute(
        "SELECT capability, row_key, old_stance, new_stance, surface, changed_at "
        "FROM user_permission_stance_history WHERE user_id = ? ORDER BY id ASC",
        (user_id,),
    ).fetchall()
    return [
        {
            "capability": row[0],
            "row_key": row[1],
            "old_stance": row[2],
            "new_stance": row[3],
            "surface": row[4],
            "changed_at": row[5],
        }
        for row in rows
    ]


def migrate_flags_to_stances(
    user_id: str, *, connection: sqlite3.Connection | None = None
) -> dict[str, str]:
    """Map legacy boolean steward flags to R2/R3 stance records (OQ3).

    - ``steward_derivation`` ON → R2 Just do it; OFF → R2 Don't do it.
    - ``steward_coordination`` ON → R3 Just do it; OFF → R3 Don't do it.

    Only rows with NO existing stance record are written: migration
    never overwrites a user-set stance, and re-running it is a no-op
    for already-migrated rows. Existing users are NOT opted in by
    this migration (OFF maps to Don't do it, the R2/R3 default), and
    no forced re-acknowledgement happens: ``consent_given``,
    ``consent_version``, and ``consent_at`` are never touched, and
    ``permissions_json`` is never rewritten here.

    This function is deliberately NOT auto-run on any read or gate
    path (no subsystem wiring in Slice 1): it runs when a caller
    explicitly migrates a user. Returns the stances it wrote.
    """
    conn = _conn(connection)
    row = conn.execute(
        "SELECT permissions_json FROM user_permissions_settings "
        "WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        return {}
    try:
        flags = json.loads(row[0] or "{}")
    except (json.JSONDecodeError, TypeError):
        flags = {}
    if not isinstance(flags, dict):
        flags = {}
    written: dict[str, str] = {}
    for flag_key, capability in (
        ("steward_derivation", "R2"),
        ("steward_coordination", "R3"),
    ):
        if get_stance(user_id, capability, "all", connection=conn) is not None:
            continue
        stance = JUST_DO_IT if flags.get(flag_key) is True else DONT_DO_IT
        set_stance(
            user_id,
            capability,
            "all",
            stance,
            surface=SURFACE_FLAG_MIGRATION,
            connection=conn,
        )
        written[capability] = stance
    return written
