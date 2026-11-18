"""SQLite store for the identity license, consent ledger, and receipts.

Layout (under <data>/identity/):
  identity.db   — license (single row), scope_events (append-only),
                  deletion_receipts (audit)

Threading: one connection guarded by a lock is enough for user-triggered use.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import identity_data_dir
from .boundary import BoundaryState, register_boundary_state, unregister_boundary_state
from .models import DeletionReceipt, IdentityLicense, ScopeEvent

_SCHEMA = """
CREATE TABLE IF NOT EXISTS license (
    license_id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    rights TEXT NOT NULL DEFAULT '',
    terms_json TEXT NOT NULL DEFAULT '{}',
    signature TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    terminated_at TEXT
);
CREATE TABLE IF NOT EXISTS scope_events (
    event_id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    action TEXT NOT NULL,
    ts TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    user_id TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_scope_events_scope ON scope_events(scope);
CREATE TABLE IF NOT EXISTS deletion_receipts (
    receipt_id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    license_id TEXT NOT NULL,
    summary_json TEXT NOT NULL DEFAULT '{}',
    signature TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS erasure_operation_work (
    operation_id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL DEFAULT '{}',
    classification_sha256 TEXT NOT NULL DEFAULT '',
    signature TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    sealed_at TEXT
);
"""


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _json_loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _license_from_row(row: sqlite3.Row) -> IdentityLicense:
    return IdentityLicense(
        license_id=row["license_id"],
        owner_id=row["owner_id"],
        issued_at=_parse_dt(row["issued_at"]) or datetime.now(timezone.utc),
        version=row["version"],
        rights=row["rights"] or "",
        terms=_json_loads(row["terms_json"], {}),
        signature=row["signature"] or "",
        status=row["status"] or "active",
        terminated_at=_parse_dt(row["terminated_at"]),
    )


def _event_from_row(row: sqlite3.Row) -> ScopeEvent:
    return ScopeEvent(
        event_id=row["event_id"],
        scope=row["scope"],
        action=row["action"],
        ts=_parse_dt(row["ts"]) or datetime.now(timezone.utc),
        note=row["note"] or "",
        user_id=row["user_id"] if "user_id" in row.keys() else "",
    )


def _resolve_installation_owner_id() -> str | None:
    """The bootstrapped installation owner's user id, or None.

    Resolved through the vision-execution users table — the same
    §9.1 source the erasure flow uses (erasure._default_owner_resolver).
    Called through this module attribute so tests can monkeypatch it.
    Any failure resolves to None (fail closed: the legacy global tier
    then folds for no specific account).
    """
    try:
        from local_ai.vision_execution import storage as ve_storage

        return ve_storage.get_owner_user_id()
    except Exception:
        return None


def _receipt_from_row(row: sqlite3.Row) -> DeletionReceipt:
    return DeletionReceipt(
        receipt_id=row["receipt_id"],
        ts=_parse_dt(row["ts"]) or datetime.now(timezone.utc),
        license_id=row["license_id"],
        summary=_json_loads(row["summary_json"], {}),
        signature=row["signature"] or "",
    )


class IdentityStore:
    """SQLite-backed store for the license, consent ledger, and receipts."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        # NOTE: db_path default is resolved at call time (not import time) so
        # ZENAF_DATA_DIR honored by tests stays effective.
        self.db_path = Path(db_path) if db_path else identity_data_dir() / "identity.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # Gate B Increment 1: the boundary participation state
        # (four-gap §1(c)). Every commit site in this store routes
        # through it; with no boundary standing it passes through.
        self.boundary_state = BoundaryState("identity")
        register_boundary_state(self._conn, self.boundary_state)
        with self._lock:
            cols = [r["name"] for r in self._conn.execute("PRAGMA table_info(scope_events)").fetchall()]
            self._conn.executescript(_SCHEMA)
            if cols and "user_id" not in cols:
                self._conn.execute("ALTER TABLE scope_events ADD COLUMN user_id TEXT NOT NULL DEFAULT ''")
            self.boundary_state.commit(self._conn)

    def close(self) -> None:
        with self._lock:
            unregister_boundary_state(self._conn)
            self._conn.close()

    # -- license -------------------------------------------------------

    def save_license(self, lic: IdentityLicense) -> IdentityLicense:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO license "
                "(license_id, owner_id, issued_at, version, rights, terms_json, "
                " signature, status, terminated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    lic.license_id,
                    lic.owner_id,
                    _iso(lic.issued_at),
                    lic.version,
                    lic.rights,
                    json.dumps(lic.terms),
                    lic.signature,
                    lic.status,
                    _iso(lic.terminated_at),
                ),
            )
            self.boundary_state.commit(self._conn)
        return lic

    def get_license(self) -> IdentityLicense | None:
        """The single license row (latest wins; there should only be one)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM license ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        return _license_from_row(row) if row else None

    def terminate_license(self) -> None:
        """Tombstone the license: it stays as proof it existed, marked ended."""
        with self._lock:
            self._conn.execute(
                "UPDATE license SET status = 'terminated', terminated_at = ?",
                (_iso(datetime.now(timezone.utc)),),
            )
            self.boundary_state.commit(self._conn)

    # -- consent ledger ------------------------------------------------

    def append_scope_event(self, event: ScopeEvent) -> ScopeEvent:
        with self._lock:
            self._conn.execute(
                "INSERT INTO scope_events (event_id, scope, action, ts, note, user_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    event.event_id,
                    event.scope,
                    event.action,
                    _iso(event.ts),
                    event.note,
                    event.user_id or "",
                ),
            )
            self.boundary_state.commit(self._conn)
        return event

    def list_scope_events(self) -> list[ScopeEvent]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM scope_events ORDER BY rowid"
            ).fetchall()
        return [_event_from_row(r) for r in rows]

    @staticmethod
    def _fold_scope_events(
        events: list[ScopeEvent], uid: str | None, *, include_global: bool
    ) -> set[str]:
        """Fold an event sequence: grant adds, revoke removes, in order.

        With a user id, events belonging to another user are skipped
        and global (user_id="") events fold only when include_global
        is set. With uid=None (the installation read), every event
        folds — the pre-correction union semantics the service-level
        gates consult.
        """
        active: set[str] = set()
        for e in events:
            if uid is not None:
                if e.user_id:
                    if e.user_id != uid:
                        continue
                elif not include_global:
                    continue
            if e.action == "grant":
                active.add(e.scope)
            elif e.action == "revoke":
                active.discard(e.scope)
        return active

    def active_scopes(self, user_id: str | None = None) -> set[str]:
        """Fold the append-only ledger: grant adds, revoke removes.

        Three reads, by caller:

        - No user_id (the installation read): every event folds —
          the union the service-level gates behind owner-gated routes
          have always consulted.
        - The installation owner: their own events plus the legacy
          global (user_id="") tier. Historical global grants were
          written by the previously unauthenticated scopes route, so
          their provenance is unattributable; they are preserved as
          the owner's effective permissions (never silently dropped)
          but are NOT verified owner consent — see
          legacy_global_scopes() for the distinct representation.
        - Any other account: only its own events. The legacy global
          tier must never confer installation-owner grants on another
          account (security correction D-6, founder amendment §2).
        """
        uid = (user_id or "").strip()
        if not uid:
            return self._fold_scope_events(
                self.list_scope_events(), None, include_global=True
            )
        owner_id = _resolve_installation_owner_id()
        include_global = owner_id is not None and uid == owner_id
        return self._fold_scope_events(
            self.list_scope_events(), uid, include_global=include_global
        )

    def legacy_global_scopes(self, user_id: str) -> set[str]:
        """Scopes effective for `user_id` ONLY via the legacy global tier.

        The difference between the user's fold with the global tier
        and without it: permissions whose entire provenance is the
        historical (user_id="") events written before the scopes
        route required the installation owner. Empty for non-owners
        (the global tier no longer folds for them at all).
        """
        uid = (user_id or "").strip()
        if not uid:
            return set()
        events = self.list_scope_events()
        with_global = self._fold_scope_events(events, uid, include_global=True)
        own_only = self._fold_scope_events(events, uid, include_global=False)
        owner_id = _resolve_installation_owner_id()
        if owner_id is None or uid != owner_id:
            return set()
        return with_global - own_only

    def clear_scope_events(self) -> int:
        """Remove the consent ledger (used only by full deletion)."""
        with self._lock:
            cur = self._conn.execute("DELETE FROM scope_events")
            self.boundary_state.commit(self._conn)
            return cur.rowcount

    # -- deletion receipts ---------------------------------------------

    def save_receipt(self, receipt: DeletionReceipt) -> DeletionReceipt:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO deletion_receipts "
                "(receipt_id, ts, license_id, summary_json, signature) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    receipt.receipt_id,
                    _iso(receipt.ts),
                    receipt.license_id,
                    json.dumps(receipt.summary),
                    receipt.signature,
                ),
            )
            self.boundary_state.commit(self._conn)
        return receipt

    def list_receipts(self) -> list[DeletionReceipt]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM deletion_receipts ORDER BY rowid DESC"
            ).fetchall()
        return [_receipt_from_row(r) for r in rows]

    # -- erasure operation work (Gate B Increment 1) ----------------
    #
    # The temporary classification persistence of the joint erasure
    # protocol (amendment §1.2; FPC §§1–2): one signed row per open
    # operation, holding the captured classification while the
    # operation is open and destroyed in the sealing transaction.
    # Sensitive temporary material: readable only by the erasure
    # flow, never exposed by any route, never written to a receipt.

    def save_operation_work(
        self, operation_id: str, payload: dict[str, Any], signature: str
    ) -> None:
        """Persist (or replace) the operation's signed work row."""
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO erasure_operation_work "
                "(operation_id, payload_json, classification_sha256, "
                " signature, created_at, sealed_at) "
                "VALUES (?, ?, ?, ?, ?, NULL)",
                (
                    operation_id,
                    json.dumps(payload, sort_keys=True),
                    str(payload.get("classification_sha256", "")),
                    signature,
                    str(payload.get("created_at", "")),
                ),
            )
            self.boundary_state.commit(self._conn)

    def load_operation_work(
        self, operation_id: str
    ) -> tuple[dict[str, Any] | None, bool]:
        """Load a work row and verify it.

        Returns ``(payload, verified)``: ``(None, False)`` when no
        row stands; ``(payload, False)`` when the row exists but
        its HMAC signature fails, its stored classification hash
        disagrees with the payload's, or it binds a different
        operation — every one of those is a conflict to the caller,
        never a recompute invitation (FPC §1).
        """
        from .signing import verify_mapping

        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM erasure_operation_work "
                "WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
        if row is None:
            return None, False
        payload = _json_loads(row["payload_json"], {})
        if not isinstance(payload, dict):
            return None, False
        verified = (
            payload.get("operation_id") == operation_id
            and payload.get("classification_sha256")
            == row["classification_sha256"]
            and verify_mapping(payload, row["signature"])
        )
        return payload, verified

    def has_operation_work(self, operation_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM erasure_operation_work "
                "WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
        return row is not None

    def delete_operation_work(self, operation_id: str) -> bool:
        """Destroy the work row (sealing / abandonment cleanup)."""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM erasure_operation_work "
                "WHERE operation_id = ?",
                (operation_id,),
            )
            self.boundary_state.commit(self._conn)
            return cur.rowcount == 1
