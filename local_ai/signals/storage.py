"""
Signal persistence. Uses vision_execution SQLite (same DB, signals table).
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
    # row (new): id, kind, title, detail, source, source_excerpt, source_ref, confidence,
    #            linked_initiative_id, linked_project_id, linked_task_id, linked_asset_ids, status, created_at, updated_at (15 cols)
    # row (legacy): same without linked_asset_ids (14 cols)
    n = len(row)
    has_assets = n >= 15
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
        "created_at": row[13] if has_assets else row[12],
        "updated_at": row[14] if has_assets else row[13],
    }


def create_signal(data: dict[str, Any]) -> dict[str, Any]:
    """Insert one signal. Caller must provide id or we generate one."""
    conn = _get_conn()
    sid = data.get("id") or M.new_id()
    now = _now()
    source_ref = data.get("source_ref")
    source_ref_str = json.dumps(source_ref) if source_ref else None
    linked_asset_ids = data.get("linked_asset_ids") or []
    linked_asset_ids_str = json.dumps(linked_asset_ids) if isinstance(linked_asset_ids, list) else "[]"
    conn.execute(
        """INSERT INTO signals (
          id, kind, title, detail, source, source_excerpt, source_ref, confidence,
          linked_initiative_id, linked_project_id, linked_task_id, linked_asset_ids, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
            now,
            now,
        ),
    )
    conn.commit()
    out = row_to_signal(
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
            now,
            now,
        )
    )
    try:
        from local_ai.activity import log_activity_simple, ActivityType, ActivityEntityType
        log_activity_simple(
            type=ActivityType.SIGNAL_CREATED.value,
            entity_type=ActivityEntityType.SIGNAL.value,
            entity_id=sid,
            source=data.get("source", ""),
            detail=f"kind={data.get('kind', 'attention')} title={data.get('title', '')}",
        )
    except Exception:
        pass
    return out


def create_signals_bulk(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bulk insert signals. Returns list of created signal dicts."""
    out = []
    for data in items:
        out.append(create_signal(data))
    return out


def list_signals(
    *,
    status_in: list[str] | None = None,
    status_not_in: list[str] | None = None,
    source: str | None = None,
) -> list[dict[str, Any]]:
    """List signals with optional filters. status_not_in typically ['resolved','dismissed'] for Radar."""
    conn = _get_conn()
    sql = (
        "SELECT id, kind, title, detail, source, source_excerpt, source_ref, confidence, "
        "linked_initiative_id, linked_project_id, linked_task_id, linked_asset_ids, status, created_at, updated_at "
        "FROM signals"
    )
    params: list[Any] = []
    conditions = []
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
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY created_at DESC"
    cur = conn.execute(sql, params)
    return [row_to_signal(tuple(r)) for r in cur.fetchall()]


def get_signal(signal_id: str) -> dict[str, Any] | None:
    conn = _get_conn()
    cur = conn.execute(
        "SELECT id, kind, title, detail, source, source_excerpt, source_ref, confidence, "
        "linked_initiative_id, linked_project_id, linked_task_id, linked_asset_ids, status, created_at, updated_at "
        "FROM signals WHERE id = ?",
        (signal_id,),
    )
    row = cur.fetchone()
    return row_to_signal(tuple(row)) if row else None


def update_signal(signal_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    """Update status and/or linked_* fields. Returns updated signal or None if not found."""
    existing = get_signal(signal_id)
    if not existing:
        return None
    conn = _get_conn()
    now = _now()
    old_status = existing["status"]
    status = patch.get("status") if "status" in patch else old_status
    linked_initiative_id = patch.get("linked_initiative_id") if "linked_initiative_id" in patch else existing["linked_initiative_id"]
    linked_project_id = patch.get("linked_project_id") if "linked_project_id" in patch else existing["linked_project_id"]
    linked_task_id = patch.get("linked_task_id") if "linked_task_id" in patch else existing["linked_task_id"]
    conn.execute(
        """UPDATE signals SET status = ?, linked_initiative_id = ?, linked_project_id = ?, linked_task_id = ?, updated_at = ?
        WHERE id = ?""",
        (status, linked_initiative_id, linked_project_id, linked_task_id, now, signal_id),
    )
    conn.commit()
    updated = get_signal(signal_id)
    if updated:
        _log_signal_lifecycle_activity(signal_id, old_status, status, updated)
    return updated


def _log_signal_lifecycle_activity(signal_id: str, old_status: str, new_status: str, signal: dict[str, Any]) -> None:
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
            related_entity_id=related,
            source=signal.get("source", ""),
            detail=f"title={signal.get('title', '')}",
        )
    except Exception:
        pass
