"""
Signal persistence. Uses vision_execution SQLite (same DB, signals table).

Owner-scoped (Track C, Option A): every read and mutation carries a
required, validated ``user_id`` enforced by a SQL predicate — never by a
downstream filter. Legacy rows with ``user_id IS NULL`` (quarantine)
never match an owner predicate, for any caller including the owner.
Linked initiative/project/task references are validated against the
authenticated owner before any write (founder correction 1, 2026-11-11).
"""
from __future__ import annotations

import json
from typing import Any

from local_ai.vision_execution import models as M
from local_ai.vision_execution import storage as V


def _get_conn():
    return V.get_connection()


def _now() -> str:
    return M._now_iso()


def _json_loads(s: str | None) -> dict[str, str] | None:
    if not s:
        return None
    try:
        return json.loads(s)
    except (TypeError, json.JSONDecodeError):
        return None


def _json_loads_list(s: str | None) -> list:
    if not s:
        return []
    try:
        out = json.loads(s)
        return out if isinstance(out, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


def row_to_signal(row: tuple) -> dict[str, Any]:
    # row (current): id, kind, title, detail, source, source_excerpt, source_ref, confidence,
    #            linked_initiative_id, linked_project_id, linked_task_id, linked_asset_ids, status,
    #            created_at, updated_at, user_id (16 cols — SELECT lists request user_id last)
    # row (pre-migration): same without user_id (15 cols)
    # row (legacy): same without linked_asset_ids and user_id (14 cols)
    n = len(row)
    has_assets = n >= 15
    has_user = n >= 16
    return {
        "id": row[0],
        "kind": row[1],
        "title": row[2] or "",
        "detail": row[3],
        "source": row[4] or "",
        "source_excerpt": row[5],
        "source_ref": _json_loads(row[6]),
        "confidence": row[7],
        "linked_initiative_id": row[8],
        "linked_project_id": row[9],
        "linked_task_id": row[10],
        "linked_asset_ids": _json_loads_list(row[11]) if has_assets else [],
        "status": (row[12] if has_assets else row[11]) or "new",
        "user_id": row[15] if has_user else None,
        "created_at": row[13] if has_assets else row[12],
        "updated_at": row[14] if has_assets else row[13],
    }


# SELECT list shared by list/get: the stored column order, user_id last,
# so row_to_signal's positional mapping holds for all three shapes.
_SIGNAL_COLUMNS = (
    "id, kind, title, detail, source, source_excerpt, source_ref, confidence, "
    "linked_initiative_id, linked_project_id, linked_task_id, linked_asset_ids, status, created_at, updated_at, user_id"
)


def _validate_linked_refs(
    conn,
    user_id: str,
    linked_initiative_id: str | None,
    linked_project_id: str | None,
    linked_task_id: str | None,
) -> None:
    """Founder correction 1 (linked ownership): every supplied
    initiative/project/task reference must resolve to a record owned by
    the caller. Foreign or nonexistent references raise ValueError
    before any mutation. ``None`` (absent/cleared) needs no check.
    ``linked_asset_ids`` is not validated here: the assets table carries
    no user_id yet (Track B's work), so no owner check exists for it."""
    V._ensure_owned_reference(
        conn, table="initiatives", ref_id=linked_initiative_id,
        user_id=user_id, field_name="linked_initiative_id",
    )
    V._ensure_owned_reference(
        conn, table="projects", ref_id=linked_project_id,
        user_id=user_id, field_name="linked_project_id",
    )
    V._ensure_owned_reference(
        conn, table="tasks", ref_id=linked_task_id,
        user_id=user_id, field_name="linked_task_id",
    )


def create_signal(data: dict[str, Any], user_id: str) -> dict[str, Any]:
    """Insert one signal owned by ``user_id`` (required, validated).
    Any ``user_id`` key in ``data`` is ignored — ownership is stamped
    from the argument, never trusted from the payload."""
    user_id = V._require_owner_id(user_id)
    conn = _get_conn()
    _validate_linked_refs(
        conn,
        user_id,
        data.get("linked_initiative_id"),
        data.get("linked_project_id"),
        data.get("linked_task_id"),
    )
    sid = data.get("id") or M.new_id()
    now = _now()
    source_ref = data.get("source_ref")
    source_ref_str = json.dumps(source_ref) if source_ref else None
    linked_asset_ids = data.get("linked_asset_ids") or []
    linked_asset_ids_str = json.dumps(linked_asset_ids) if isinstance(linked_asset_ids, list) else "[]"
    conn.execute(
        """INSERT INTO signals (
          id, kind, title, detail, source, source_excerpt, source_ref, confidence,
          linked_initiative_id, linked_project_id, linked_task_id, linked_asset_ids, status, user_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            sid,
            data.get("kind", "attention"),
            data.get("title", ""),
            data.get("detail"),
            data.get("source", ""),
            data.get("source_excerpt"),
            source_ref_str,
            data.get("confidence"),
            data.get("linked_initiative_id"),
            data.get("linked_project_id"),
            data.get("linked_task_id"),
            linked_asset_ids_str,
            data.get("status", "new"),
            user_id,
            now,
            now,
        ),
    )
    V._commit_if_owner(conn)
    # Re-read instead of hand-building the return tuple: row_to_signal
    # is positional, and a hand-built tuple is exactly the hazard that
    # drifts. The re-read also proves the row is readable by its owner.
    out = get_signal(sid, user_id)
    try:
        from local_ai.activity import log_activity_simple, ActivityType, ActivityEntityType
        log_activity_simple(
            type=ActivityType.SIGNAL_CREATED.value,
            entity_type=ActivityEntityType.SIGNAL.value,
            entity_id=sid,
            actor=user_id,
            source=data.get("source", ""),
            detail=f"kind={data.get('kind', 'attention')} title={data.get('title', '')}",
        )
    except Exception:
        pass
    return out


def create_signals_bulk(items: list[dict[str, Any]], user_id: str) -> list[dict[str, Any]]:
    """Bulk insert signals owned by ``user_id``. All items' linked
    references are validated BEFORE any insert, so one foreign reference
    rejects the whole bulk with no partial mutation."""
    user_id = V._require_owner_id(user_id)
    conn = _get_conn()
    for data in items:
        _validate_linked_refs(
            conn,
            user_id,
            data.get("linked_initiative_id"),
            data.get("linked_project_id"),
            data.get("linked_task_id"),
        )
    out = []
    for data in items:
        out.append(create_signal(data, user_id))
    return out


def list_signals(
    user_id: str,
    *,
    status_in: list[str] | None = None,
    status_not_in: list[str] | None = None,
    source: str | None = None,
) -> list[dict[str, Any]]:
    """List the caller's signals only. The ownership predicate is the
    FIRST condition, ahead of the status/source filters, so ownership is
    enforced before any other filtering — the list_decisions shape.
    Quarantined rows (user_id IS NULL) never match."""
    user_id = V._require_owner_id(user_id)
    conn = _get_conn()
    sql = f"SELECT {_SIGNAL_COLUMNS} FROM signals"
    params: list[Any] = [user_id]
    conditions = ["user_id = ?"]
    if status_in:
        placeholders = ",".join("?" * len(status_in))
        conditions.append(f"status IN ({placeholders})")
        params.extend(status_in)
    if status_not_in:
        placeholders = ",".join("?" * len(status_not_in))
        conditions.append(f"status NOT IN ({placeholders})")
        params.extend(status_not_in)
    if source:
        conditions.append("source = ?")
        params.append(source)
    sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY created_at DESC"
    cur = conn.execute(sql, params)
    return [row_to_signal(tuple(r)) for r in cur.fetchall()]


def get_signal(signal_id: str, user_id: str) -> dict[str, Any] | None:
    """Owner-scoped read. A foreign id returns None (route 404), never
    a 403 that confirms the row exists."""
    user_id = V._require_owner_id(user_id)
    conn = _get_conn()
    cur = conn.execute(
        f"SELECT {_SIGNAL_COLUMNS} FROM signals WHERE id = ? AND user_id = ?",
        (signal_id, user_id),
    )
    row = cur.fetchone()
    return row_to_signal(tuple(row)) if row else None


def update_signal(signal_id: str, patch: dict[str, Any], user_id: str) -> dict[str, Any] | None:
    """Update status and/or linked_* fields. Returns updated signal or
    None if not found (missing and foreign are identical). The ownership
    predicate is on the UPDATE itself — a predicate on the pre-read
    alone is not enforcement. Zero rows affected returns None; no
    fall-through to a re-read that could return a stale row."""
    user_id = V._require_owner_id(user_id)
    existing = get_signal(signal_id, user_id)
    if not existing:
        return None
    conn = _get_conn()
    now = _now()
    old_status = existing["status"]
    status = patch.get("status") if "status" in patch else old_status
    linked_initiative_id = patch.get("linked_initiative_id") if "linked_initiative_id" in patch else existing["linked_initiative_id"]
    linked_project_id = patch.get("linked_project_id") if "linked_project_id" in patch else existing["linked_project_id"]
    linked_task_id = patch.get("linked_task_id") if "linked_task_id" in patch else existing["linked_task_id"]
    # Validate only the links this patch SUPPLIES. Untouched links keep
    # their persisted values without re-validation (legacy rows may carry
    # links written before validation existed).
    _validate_linked_refs(
        conn,
        user_id,
        patch.get("linked_initiative_id") if "linked_initiative_id" in patch else None,
        patch.get("linked_project_id") if "linked_project_id" in patch else None,
        patch.get("linked_task_id") if "linked_task_id" in patch else None,
    )
    cur = conn.execute(
        """UPDATE signals SET status = ?, linked_initiative_id = ?, linked_project_id = ?, linked_task_id = ?, updated_at = ?
        WHERE id = ? AND user_id = ?""",
        (status, linked_initiative_id, linked_project_id, linked_task_id, now, signal_id, user_id),
    )
    if cur.rowcount == 0:
        return None
    V._commit_if_owner(conn)
    updated = get_signal(signal_id, user_id)
    if updated:
        _log_signal_lifecycle_activity(signal_id, old_status, status, updated, user_id)
    return updated


def _log_signal_lifecycle_activity(signal_id: str, old_status: str, new_status: str, signal: dict[str, Any], actor: str) -> None:
    """Emit activity event when signal status changes (acknowledged/linked/resolved/dismissed)."""
    if old_status == new_status:
        return
    try:
        from local_ai.activity import log_activity_simple, ActivityType, ActivityEntityType
        event_type = None
        if new_status == "acknowledged":
            event_type = ActivityType.SIGNAL_ACKNOWLEDGED
        elif new_status == "linked":
            event_type = ActivityType.SIGNAL_LINKED
        elif new_status == "resolved":
            event_type = ActivityType.SIGNAL_RESOLVED
        elif new_status == "dismissed":
            event_type = ActivityType.SIGNAL_DISMISSED
        if event_type is None:
            return
        related = signal.get("linked_project_id") or signal.get("linked_initiative_id") or signal.get("linked_task_id")
        log_activity_simple(
            type=event_type.value,
            entity_type=ActivityEntityType.SIGNAL.value,
            entity_id=signal_id,
            actor=actor,
            related_entity_id=related,
            source=signal.get("source", ""),
            detail=f"title={signal.get('title', '')}",
        )
    except Exception:
        pass
