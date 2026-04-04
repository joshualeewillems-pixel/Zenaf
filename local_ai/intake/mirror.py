"""
Persistent metadata mirror for intake queue and judgment layer.

Data tiers:
- Tier A (operational): metadata, summary, lane, judgment refs, status — default for UI/queue.
- Tier B (sanitized): cleaned body text stored in mirror_item.sanitized_body_text; lower exposure.
- Tier C (raw): placeholder only (raw_content_ref); full raw not stored yet.

Mailbox = external source of truth. Mirror = Atria's durable operational memory.
In-memory queue = working set (Tier A). load_into_memory() loads Tier A only.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

# DB next to repo root (same level as intake_imap_config.json when run from repo root)
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MIRROR_DB_PATH = _REPO_ROOT / "intake_mirror.db"

_MIRROR_BUSY_TIMEOUT_MS = 5000


def _apply_mirror_sqlite_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={_MIRROR_BUSY_TIMEOUT_MS}")


def open_mirror_sqlite(db_path: Path | str) -> sqlite3.Connection:
    """Open SQLite with the same row factory and pragmas as production mirror (tests: use tmp_path only)."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    _apply_mirror_sqlite_pragmas(conn)
    return conn


def _conn() -> sqlite3.Connection:
    return open_mirror_sqlite(MIRROR_DB_PATH)


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS mirror_item (
            id TEXT PRIMARY KEY,
            external_id TEXT NOT NULL,
            thread_id TEXT,
            sender TEXT,
            source_label TEXT,
            subject TEXT,
            created_at TEXT,
            summary TEXT,
            suggested_action TEXT,
            category TEXT,
            priority TEXT,
            lane TEXT,
            confidence REAL,
            confidence_display TEXT,
            has_phi INTEGER,
            source TEXT,
            status TEXT,
            notes TEXT,
            assigned_to TEXT,
            lane_override TEXT,
            judgment_id TEXT,
            archived INTEGER,
            updated_at TEXT,
            synced_at TEXT,
            sanitized_body_text TEXT,
            raw_content_ref TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_mirror_item_external_id ON mirror_item(external_id);

        CREATE TABLE IF NOT EXISTS mirror_judgment (
            id TEXT PRIMARY KEY,
            entity_id TEXT NOT NULL,
            domain TEXT,
            interpretation TEXT,
            proposed_action TEXT,
            confidence REAL,
            signal_codes TEXT,
            interpretation_codes TEXT,
            policy_codes TEXT,
            observation_ref TEXT,
            created_at TEXT,
            superseded_by TEXT,
            correction_note TEXT
        );

        CREATE TABLE IF NOT EXISTS mirror_sync (
            id TEXT PRIMARY KEY,
            last_poll_at TEXT,
            cursor TEXT
        );

        CREATE TABLE IF NOT EXISTS mailbox_action (
            id TEXT PRIMARY KEY,
            item_id TEXT,
            external_id TEXT,
            action_type TEXT,
            payload TEXT,
            created_at TEXT,
            applied_at TEXT,
            mailbox_id TEXT,
            result_status TEXT,
            error_message TEXT
        );
    """)
    conn.commit()
    _migrate_schema(conn)


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Add columns to existing DBs that were created before Tier B/C and mailbox_action audit fields."""
    new_mirror_item_cols = [
        ("sender", "TEXT"),
        ("sanitized_body_text", "TEXT"),
        ("raw_content_ref", "TEXT"),
    ]
    new_mailbox_action_cols = [
        ("mailbox_id", "TEXT"),
        ("result_status", "TEXT"),
        ("error_message", "TEXT"),
    ]
    for col, typ in new_mirror_item_cols:
        try:
            conn.execute(f"ALTER TABLE mirror_item ADD COLUMN {col} {typ}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                raise
    for col, typ in new_mailbox_action_cols:
        try:
            conn.execute(f"ALTER TABLE mailbox_action ADD COLUMN {col} {typ}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                raise
    conn.commit()


def _dict_from_item_row(row: sqlite3.Row, *, include_tier_b: bool = False, include_tier_c: bool = False) -> dict[str, Any]:
    """Build item dict for queue (Tier A). Optionally include sanitized_body (B) or raw_content_ref (C)."""
    d: dict[str, Any] = {
        "id": row["id"],
        "external_id": row["external_id"] or "",
        "subject": row["subject"] or "",
        "source_label": row["source_label"] or "",
        "created_at": row["created_at"] or "",
        "summary": row["summary"] or "",
        "suggested_action": row["suggested_action"] or "",
        "category": row["category"] or "other",
        "priority": row["priority"] or "normal",
        "lane": row["lane"] or "",
        "confidence": float(row["confidence"] or 0),
        "confidence_display": row["confidence_display"] or "low",
        "has_phi": bool(row["has_phi"]),
        "source": row["source"] or "email",
        "status": row["status"] or "new",
        "notes": row["notes"] or "",
        "assigned_to": row["assigned_to"] or "",
        "lane_override": row["lane_override"] or "",
        "judgment_id": row["judgment_id"] or "",
        "archived": bool(row["archived"]),
    }
    if row["thread_id"] is not None:
        d["thread_id"] = row["thread_id"]
    try:
        if row["sender"] is not None:
            d["sender"] = row["sender"]
    except (IndexError, KeyError):
        pass
    if include_tier_b:
        try:
            if row["sanitized_body_text"] is not None:
                d["sanitized_body_text"] = row["sanitized_body_text"]
        except (IndexError, KeyError):
            pass
    if include_tier_c:
        try:
            if row["raw_content_ref"] is not None:
                d["raw_content_ref"] = row["raw_content_ref"]
        except (IndexError, KeyError):
            pass
    return d


def upsert_item(
    item: dict[str, Any],
    *,
    synced_at: str | None = None,
    sanitized_body_text: str | None = None,
    raw_content_ref: str | None = None,
) -> None:
    """
    Persist one queue item to the mirror (Tier A + optional Tier B/C).
    synced_at = when we last saw it from mailbox (default now).
    sanitized_body_text = Tier B cleaned body; stored but not loaded into in-memory queue by default.
    raw_content_ref = Tier C placeholder (e.g. future blob key); not implemented yet.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    ts = synced_at or now
    conn = _conn()
    try:
        init_schema(conn)
        conn.execute(
            """
            INSERT INTO mirror_item (
                id, external_id, thread_id, sender, source_label, subject, created_at, summary,
                suggested_action, category, priority, lane, confidence, confidence_display,
                has_phi, source, status, notes, assigned_to, lane_override, judgment_id,
                archived, updated_at, synced_at, sanitized_body_text, raw_content_ref
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                external_id=excluded.external_id, thread_id=excluded.thread_id, sender=excluded.sender,
                source_label=excluded.source_label, subject=excluded.subject, created_at=excluded.created_at,
                summary=excluded.summary, suggested_action=excluded.suggested_action,
                category=excluded.category, priority=excluded.priority, lane=excluded.lane,
                confidence=excluded.confidence, confidence_display=excluded.confidence_display,
                has_phi=excluded.has_phi, source=excluded.source, status=excluded.status,
                notes=excluded.notes, assigned_to=excluded.assigned_to,
                lane_override=excluded.lane_override, judgment_id=excluded.judgment_id,
                archived=excluded.archived, updated_at=excluded.updated_at, synced_at=excluded.synced_at,
                sanitized_body_text=CASE WHEN excluded.sanitized_body_text IS NOT NULL AND excluded.sanitized_body_text != '' THEN excluded.sanitized_body_text ELSE mirror_item.sanitized_body_text END,
                raw_content_ref=CASE WHEN excluded.raw_content_ref IS NOT NULL AND excluded.raw_content_ref != '' THEN excluded.raw_content_ref ELSE mirror_item.raw_content_ref END
            """,
            (
                item.get("id", ""),
                item.get("external_id", ""),
                item.get("thread_id") or None,
                item.get("sender") or None,
                item.get("source_label", ""),
                item.get("subject", ""),
                item.get("created_at", ""),
                item.get("summary", ""),
                item.get("suggested_action", ""),
                item.get("category", "other"),
                item.get("priority", "normal"),
                item.get("lane", ""),
                float(item.get("confidence", 0)),
                item.get("confidence_display", "low"),
                1 if item.get("has_phi") else 0,
                item.get("source", "email"),
                item.get("status", "new"),
                item.get("notes", ""),
                item.get("assigned_to", ""),
                item.get("lane_override", ""),
                item.get("judgment_id", ""),
                1 if item.get("archived") else 0,
                now,
                ts,
                sanitized_body_text if sanitized_body_text is not None else item.get("sanitized_body_text"),
                raw_content_ref if raw_content_ref is not None else item.get("raw_content_ref"),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def upsert_judgment_record(record: dict[str, Any]) -> None:
    """Persist one judgment record to the mirror."""
    conn = _conn()
    try:
        init_schema(conn)
        conn.execute(
            """
            INSERT INTO mirror_judgment (
                id, entity_id, domain, interpretation, proposed_action, confidence,
                signal_codes, interpretation_codes, policy_codes, observation_ref,
                created_at, superseded_by, correction_note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                entity_id=excluded.entity_id, domain=excluded.domain,
                interpretation=excluded.interpretation, proposed_action=excluded.proposed_action,
                confidence=excluded.confidence, signal_codes=excluded.signal_codes,
                interpretation_codes=excluded.interpretation_codes, policy_codes=excluded.policy_codes,
                observation_ref=excluded.observation_ref, created_at=excluded.created_at,
                superseded_by=excluded.superseded_by, correction_note=excluded.correction_note
            """,
            (
                record.get("id", ""),
                record.get("entity_id", ""),
                record.get("domain", "intake"),
                json.dumps(record.get("interpretation") or {}),
                json.dumps(record.get("proposed_action") or {}),
                float(record.get("confidence", 0)),
                json.dumps(record.get("signal_codes") or []),
                json.dumps(record.get("interpretation_codes") or []),
                json.dumps(record.get("policy_codes") or []),
                json.dumps(record.get("observation_ref")) if record.get("observation_ref") is not None else None,
                record.get("created_at", ""),
                record.get("superseded_by"),
                record.get("correction_note"),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def upsert_judgment_chain_for_entity(entity_id: str) -> None:
    """Load the in-memory judgment chain for this entity and persist all records to the mirror."""
    from local_ai.judgment import get_for_entity, DOMAIN_INTAKE
    records = get_for_entity(DOMAIN_INTAKE, entity_id)
    for r in records:
        upsert_judgment_record(r.to_dict())


def load_into_memory() -> bool:
    """
    Load mirror into in-memory queue and judgment layer. Idempotent; call on startup.
    Returns True if mirror existed and was loaded, False if no DB or empty.
    """
    if not MIRROR_DB_PATH.is_file():
        return False
    from local_ai.judgment import clear_records
    clear_records()
    conn = _conn()
    try:
        init_schema(conn)
        # Load judgments first (items reference judgment_id)
        cur = conn.execute(
            "SELECT id, entity_id, domain, interpretation, proposed_action, confidence,"
            " signal_codes, interpretation_codes, policy_codes, observation_ref,"
            " created_at, superseded_by, correction_note FROM mirror_judgment ORDER BY created_at"
        )
        rows = cur.fetchall()
        if not rows:
            # Maybe no judgments yet; try loading items only
            pass
        else:
            from local_ai.judgment import JudgmentRecord, add_record
            for row in rows:
                interp = json.loads(row["interpretation"] or "{}")
                action = json.loads(row["proposed_action"] or "{}")
                sig = json.loads(row["signal_codes"] or "[]")
                interp_c = json.loads(row["interpretation_codes"] or "[]")
                policy = json.loads(row["policy_codes"] or "[]")
                obs = json.loads(row["observation_ref"]) if row["observation_ref"] else None
                rec = JudgmentRecord(
                    id=row["id"],
                    domain=row["domain"] or "intake",
                    entity_id=row["entity_id"],
                    interpretation=interp,
                    proposed_action=action,
                    confidence=float(row["confidence"] or 0),
                    signal_codes=sig,
                    interpretation_codes=interp_c,
                    policy_codes=policy,
                    observation_ref=obs,
                    created_at=row["created_at"] or "",
                    superseded_by=row["superseded_by"],
                    correction_note=row["correction_note"],
                )
                add_record(rec)

        # Load items into queue_store
        cur = conn.execute(
            "SELECT * FROM mirror_item ORDER BY created_at"
        )
        item_rows = cur.fetchall()
        if not item_rows:
            return bool(rows)
        from .queue_store import replace_with_items
        items = [_dict_from_item_row(r) for r in item_rows]
        replace_with_items(items)
        return True
    finally:
        conn.close()


def set_sync_state(sync_id: str, last_poll_at: str, cursor: str | None = None) -> None:
    """Record last poll time (and optional cursor) for a mailbox config."""
    conn = _conn()
    try:
        init_schema(conn)
        conn.execute(
            "INSERT INTO mirror_sync (id, last_poll_at, cursor) VALUES (?, ?, ?)"
            " ON CONFLICT(id) DO UPDATE SET last_poll_at=excluded.last_poll_at, cursor=excluded.cursor",
            (sync_id, last_poll_at, cursor),
        )
        conn.commit()
    finally:
        conn.close()


def get_sync_state(sync_id: str) -> dict[str, Any] | None:
    """Return last_poll_at and cursor for sync_id, or None."""
    if not MIRROR_DB_PATH.is_file():
        return None
    conn = _conn()
    try:
        cur = conn.execute("SELECT last_poll_at, cursor FROM mirror_sync WHERE id = ?", (sync_id,))
        row = cur.fetchone()
        if not row:
            return None
        return {"last_poll_at": row["last_poll_at"], "cursor": row["cursor"]}
    finally:
        conn.close()


# intake-observability-exempt: mailbox mutations parked for v1 — no STORE/MOVE/mark-read paths yet;
# call sites will appear when mailbox mutations ship (see ACTIVE_VS_PLANNED.md / PLATFORM_PRIMITIVES).
def record_mailbox_action(
    action_id: str,
    item_id: str,
    external_id: str,
    action_type: str,
    payload: dict[str, Any],
    *,
    mailbox_id: str | None = None,
    result_status: str | None = None,
    error_message: str | None = None,
) -> None:
    """
    Append a mailbox action record for audit. Future mailbox edits should log here.
    applied_at left NULL until the action is actually sent to the mailbox (when implemented).
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    conn = _conn()
    try:
        init_schema(conn)
        conn.execute(
            """
            INSERT INTO mailbox_action (id, item_id, external_id, action_type, payload, created_at, applied_at, mailbox_id, result_status, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (action_id, item_id, external_id, action_type, json.dumps(payload), now, None, mailbox_id, result_status, error_message),
        )
        conn.commit()
    finally:
        conn.close()


# --- Tiered access: policy-gated read of Tier B/C content ---

def get_item_with_content(
    item_id: str,
    access_level: str,
    *,
    justification: str | None = None,
) -> dict[str, Any] | None:
    """
    Load one item from the mirror with content tier gated by access_level.
    access_level: metadata_only | sanitized_text | raw_content_required (see data_access policy).
    Tier C requires justification. Returns None if item not in mirror or access denied.
    """
    from local_ai.policy import data_access as ap
    if not ap.request_access(access_level, justification=justification):
        return None
    if not MIRROR_DB_PATH.is_file():
        return None
    conn = _conn()
    try:
        init_schema(conn)
        cur = conn.execute("SELECT * FROM mirror_item WHERE id = ?", (item_id,))
        row = cur.fetchone()
        if not row:
            return None
        include_b = access_level in (ap.SANITIZED_TEXT, ap.RAW_CONTENT_REQUIRED)
        include_c = access_level == ap.RAW_CONTENT_REQUIRED
        return _dict_from_item_row(row, include_tier_b=include_b, include_tier_c=include_c)
    finally:
        conn.close()
