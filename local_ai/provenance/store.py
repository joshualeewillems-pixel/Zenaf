"""SQLite registry for minted artifacts, the derivation DAG, engagement events,
creatorship disputes, and per-user reputation.

Layout (under <repo>/data/provenance/):
  provenance.db — provenance_artifacts, provenance_links, provenance_events,
                  provenance_disputes, provenance_reputation

Design rules (from the minting spec):
- The registry is the source of truth. Anything embedded in the file
  (C2PA, QR, EXIF) is a re-identification hint, never the record.
- Derivation links form a DAG in provenance_links (multi-parent mashups
  allowed). Under remix_policy=approval a link stays 'pending' until the
  parent creator approves — no upstream reach flows while pending.
- importer != creator: an import records custodian_user_id (who brought it
  in); creator_user_id is whoever the evidence supports (NULL = unattributed).
- Visibility: unlisted at creation; the mint act flips to private; public
  is always an explicit user action.
- first-seen is the prior, not the verdict: earliest created_at breaks ties
  only when no evidence decides.

Threading: one connection guarded by a lock is enough for user-triggered use.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data" / "provenance"
DEFAULT_DB_PATH = DATA_DIR / "provenance.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS provenance_artifacts (
    artifact_id TEXT PRIMARY KEY,
    creator_user_id TEXT,
    custodian_user_id TEXT,
    created_at TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    archetype_cast TEXT NOT NULL DEFAULT '[]',
    source_hash TEXT,
    modality TEXT NOT NULL DEFAULT 'image',
    phash TEXT,
    sha256 TEXT,
    visibility TEXT NOT NULL DEFAULT 'unlisted',
    remix_policy TEXT NOT NULL DEFAULT 'open',
    minted INTEGER NOT NULL DEFAULT 0,
    imported INTEGER NOT NULL DEFAULT 0,
    disputed INTEGER NOT NULL DEFAULT 0,
    creator_declared INTEGER NOT NULL DEFAULT 0,
    reach_cached REAL NOT NULL DEFAULT 0,
    reach_updated_at TEXT,
    c2pa_manifest BLOB,
    styled_by TEXT,
    variation_of TEXT,
    tier TEXT
);
CREATE INDEX IF NOT EXISTS idx_prov_art_sha ON provenance_artifacts(sha256);
CREATE INDEX IF NOT EXISTS idx_prov_art_phash ON provenance_artifacts(phash);
CREATE INDEX IF NOT EXISTS idx_prov_art_creator ON provenance_artifacts(creator_user_id);
CREATE TABLE IF NOT EXISTS provenance_links (
    child_id TEXT NOT NULL,
    parent_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'linked',
    created_at TEXT NOT NULL,
    PRIMARY KEY (child_id, parent_id)
);
CREATE INDEX IF NOT EXISTS idx_prov_links_parent ON provenance_links(parent_id);
CREATE INDEX IF NOT EXISTS idx_prov_links_child ON provenance_links(child_id);
CREATE TABLE IF NOT EXISTS provenance_events (
    event_id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL,
    type TEXT NOT NULL,
    actor_user_id TEXT,
    at TEXT NOT NULL,
    context TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_prov_events_art ON provenance_events(artifact_id);
CREATE TABLE IF NOT EXISTS provenance_disputes (
    dispute_id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL,
    challenger_user_id TEXT NOT NULL,
    evidence TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    resolution_note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_prov_disputes_art ON provenance_disputes(artifact_id);
CREATE TABLE IF NOT EXISTS provenance_reputation (
    user_id TEXT PRIMARY KEY,
    false_claims INTEGER NOT NULL DEFAULT 0,
    frivolous_challenges INTEGER NOT NULL DEFAULT 0
);
"""

VISIBILITIES = ("private", "unlisted", "public")
REMIX_POLICIES = ("open", "approval")
LINK_STATUSES = ("linked", "pending")
DISPUTE_STATUSES = ("open", "verified", "rejected", "disputed")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


def _row_to_artifact(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "artifact_id": row["artifact_id"],
        "creator_user_id": row["creator_user_id"],
        "custodian_user_id": row["custodian_user_id"],
        "created_at": row["created_at"],
        "title": row["title"],
        "description": row["description"],
        "archetype_cast": json.loads(row["archetype_cast"] or "[]"),
        "source_hash": row["source_hash"],
        "modality": row["modality"],
        "phash": row["phash"],
        "sha256": row["sha256"],
        "visibility": row["visibility"],
        "remix_policy": row["remix_policy"],
        "minted": bool(row["minted"]),
        "imported": bool(row["imported"]),
        "disputed": bool(row["disputed"]),
        "creator_declared": bool(row["creator_declared"]),
        "reach_cached": row["reach_cached"],
        "reach_updated_at": row["reach_updated_at"],
        "has_c2pa_manifest": row["c2pa_manifest"] is not None,
        "styled_by": row["styled_by"] if "styled_by" in row.keys() else None,
        "variation_of": row["variation_of"] if "variation_of" in row.keys() else None,
        # Phase 4 (tier enforcement): NULL = unlabeled (legacy rows and
        # non-pipeline artifacts). Never read as a tier.
        "tier": row["tier"] if "tier" in row.keys() else None,
    }


class ProvenanceStore:
    """SQLite-backed provenance registry."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
            self._migrate()

    def _migrate(self) -> None:
        """Additive migrations for DBs created before a column existed.

        (CREATE TABLE IF NOT EXISTS never alters an existing table, so new
        columns need explicit ALTERs here. Keep this additive-only.)
        """
        cols = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(provenance_artifacts)")
        }
        for name in ("styled_by", "variation_of", "tier"):
            if name not in cols:
                self._conn.execute(
                    f"ALTER TABLE provenance_artifacts ADD COLUMN {name} TEXT"
                )
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- artifacts ------------------------------------------------------

    def create_artifact(
        self,
        *,
        creator_user_id: str | None,
        custodian_user_id: str | None,
        title: str = "",
        description: str = "",
        archetype_cast: list[str] | None = None,
        source_hash: str | None = None,
        modality: str = "image",
        phash: str | None = None,
        sha256: str | None = None,
        visibility: str = "unlisted",
        remix_policy: str = "open",
        imported: bool = False,
        creator_declared: bool = False,
        c2pa_manifest: bytes | None = None,
        styled_by: str | None = None,
        variation_of: str | None = None,
        # Phase 4 (tier enforcement): "evidence" for verbatim user
        # records (journal entries), "dramatization" for tellings
        # shaped for effect (stories, packs, quote cards). None =
        # unlabeled (legacy rows, non-pipeline artifacts) — never
        # interpreted as a tier. Any other value is a programming
        # error and raises.
        tier: str | None = None,
    ) -> dict[str, Any]:
        if visibility not in VISIBILITIES:
            raise ValueError(f"bad visibility: {visibility}")
        if tier not in (None, "evidence", "dramatization"):
            raise ValueError(f"bad provenance tier: {tier!r}")
        if remix_policy not in REMIX_POLICIES:
            raise ValueError(f"bad remix_policy: {remix_policy}")
        artifact_id = _new_id()
        now = _now_iso()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO provenance_artifacts (
                    artifact_id, creator_user_id, custodian_user_id, created_at,
                    title, description, archetype_cast, source_hash, modality,
                    phash, sha256, visibility, remix_policy, minted, imported,
                    disputed, creator_declared, reach_cached, reach_updated_at,
                    c2pa_manifest, styled_by, variation_of, tier
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    artifact_id, creator_user_id, custodian_user_id, now,
                    title, description, json.dumps(archetype_cast or []),
                    source_hash, modality, phash, sha256, visibility,
                    remix_policy, 0, int(imported), 0, int(creator_declared),
                    0.0, None, c2pa_manifest, styled_by, variation_of, tier,
                ),
            )
            self._conn.commit()
        return self.get_artifact(artifact_id)

    def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM provenance_artifacts WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchone()
        return _row_to_artifact(row) if row else None

    def update_artifact(self, artifact_id: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {
            "creator_user_id", "title", "description", "archetype_cast",
            "source_hash", "visibility", "remix_policy", "minted", "imported",
            "disputed", "creator_declared", "reach_cached", "reach_updated_at",
            "c2pa_manifest", "styled_by", "variation_of", "phash", "sha256",
            "tier",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if "visibility" in updates and updates["visibility"] not in VISIBILITIES:
            raise ValueError(f"bad visibility: {updates['visibility']}")
        if "remix_policy" in updates and updates["remix_policy"] not in REMIX_POLICIES:
            raise ValueError(f"bad remix_policy: {updates['remix_policy']}")
        if "archetype_cast" in updates:
            updates["archetype_cast"] = json.dumps(updates["archetype_cast"] or [])
        for bool_field in ("minted", "imported", "disputed", "creator_declared"):
            if bool_field in updates:
                updates[bool_field] = int(bool(updates[bool_field]))
        if not updates:
            return self.get_artifact(artifact_id)
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        with self._lock:
            self._conn.execute(
                f"UPDATE provenance_artifacts SET {set_clause} WHERE artifact_id = ?",
                (*updates.values(), artifact_id),
            )
            self._conn.commit()
        return self.get_artifact(artifact_id)

    def find_by_sha256(self, sha256: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM provenance_artifacts WHERE sha256 = ? ORDER BY created_at ASC LIMIT 1",
                (sha256,),
            ).fetchone()
        return _row_to_artifact(row) if row else None

    def list_artifacts(self) -> list[dict[str, Any]]:
        """All artifacts ordered by creation (used for near-match scans)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM provenance_artifacts ORDER BY created_at ASC"
            ).fetchall()
        return [_row_to_artifact(r) for r in rows]

    def list_user_artifacts(self, user_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT * FROM provenance_artifacts
                   WHERE creator_user_id = ? OR custodian_user_id = ?
                   ORDER BY created_at DESC""",
                (user_id, user_id),
            ).fetchall()
        return [_row_to_artifact(r) for r in rows]

    # -- links (derivation DAG) ------------------------------------------

    def add_link(self, child_id: str, parent_id: str, status: str = "linked") -> dict[str, Any]:
        if status not in LINK_STATUSES:
            raise ValueError(f"bad link status: {status}")
        with self._lock:
            self._conn.execute(
                """INSERT OR IGNORE INTO provenance_links
                   (child_id, parent_id, status, created_at) VALUES (?,?,?,?)""",
                (child_id, parent_id, status, _now_iso()),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM provenance_links WHERE child_id = ? AND parent_id = ?",
                (child_id, parent_id),
            ).fetchone()
        return dict(row)

    def set_link_status(self, child_id: str, parent_id: str, status: str) -> dict[str, Any] | None:
        if status not in LINK_STATUSES:
            raise ValueError(f"bad link status: {status}")
        with self._lock:
            self._conn.execute(
                "UPDATE provenance_links SET status = ? WHERE child_id = ? AND parent_id = ?",
                (status, child_id, parent_id),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM provenance_links WHERE child_id = ? AND parent_id = ?",
                (child_id, parent_id),
            ).fetchone()
        return dict(row) if row else None

    def get_link(self, child_id: str, parent_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM provenance_links WHERE child_id = ? AND parent_id = ?",
                (child_id, parent_id),
            ).fetchone()
        return dict(row) if row else None

    def children_of(self, parent_id: str, *, linked_only: bool = True) -> list[dict[str, Any]]:
        q = "SELECT * FROM provenance_links WHERE parent_id = ?"
        if linked_only:
            q += " AND status = 'linked'"
        with self._lock:
            rows = self._conn.execute(q, (parent_id,)).fetchall()
        return [dict(r) for r in rows]

    def parents_of(self, child_id: str, *, linked_only: bool = True) -> list[dict[str, Any]]:
        q = "SELECT * FROM provenance_links WHERE child_id = ?"
        if linked_only:
            q += " AND status = 'linked'"
        with self._lock:
            rows = self._conn.execute(q, (child_id,)).fetchall()
        return [dict(r) for r in rows]

    # -- events ----------------------------------------------------------

    def log_event(
        self,
        artifact_id: str,
        type: str,
        actor_user_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event_id = _new_id()
        now = _now_iso()
        with self._lock:
            self._conn.execute(
                """INSERT INTO provenance_events
                   (event_id, artifact_id, type, actor_user_id, at, context)
                   VALUES (?,?,?,?,?,?)""",
                (event_id, artifact_id, type, actor_user_id, now, json.dumps(context or {})),
            )
            self._conn.commit()
        return {
            "event_id": event_id, "artifact_id": artifact_id, "type": type,
            "actor_user_id": actor_user_id, "at": now, "context": context or {},
        }

    def events_for(self, artifact_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM provenance_events WHERE artifact_id = ? ORDER BY at ASC",
                (artifact_id,),
            ).fetchall()
        return [
            {
                "event_id": r["event_id"], "artifact_id": r["artifact_id"],
                "type": r["type"], "actor_user_id": r["actor_user_id"],
                "at": r["at"], "context": json.loads(r["context"] or "{}"),
            }
            for r in rows
        ]

    # -- disputes ---------------------------------------------------------

    def file_dispute(
        self, artifact_id: str, challenger_user_id: str, evidence: str = ""
    ) -> dict[str, Any]:
        dispute_id = _new_id()
        now = _now_iso()
        with self._lock:
            self._conn.execute(
                """INSERT INTO provenance_disputes
                   (dispute_id, artifact_id, challenger_user_id, evidence,
                    status, created_at, resolved_at, resolution_note)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (dispute_id, artifact_id, challenger_user_id, evidence,
                 "open", now, None, ""),
            )
            self._conn.execute(
                "UPDATE provenance_artifacts SET disputed = 1 WHERE artifact_id = ?",
                (artifact_id,),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM provenance_disputes WHERE dispute_id = ?",
                (dispute_id,),
            ).fetchone()
        return dict(row)

    def get_dispute(self, dispute_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM provenance_disputes WHERE dispute_id = ?",
                (dispute_id,),
            ).fetchone()
        return dict(row) if row else None

    def resolve_dispute(
        self, dispute_id: str, outcome: str, resolution_note: str = ""
    ) -> dict[str, Any] | None:
        if outcome not in ("verified", "rejected", "disputed"):
            raise ValueError(f"bad dispute outcome: {outcome}")
        now = _now_iso()
        with self._lock:
            self._conn.execute(
                """UPDATE provenance_disputes
                   SET status = ?, resolved_at = ?, resolution_note = ?
                   WHERE dispute_id = ?""",
                (outcome, now, resolution_note, dispute_id),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM provenance_disputes WHERE dispute_id = ?",
                (dispute_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_disputes(self, status: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if status:
                rows = self._conn.execute(
                    "SELECT * FROM provenance_disputes WHERE status = ? ORDER BY created_at DESC",
                    (status,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM provenance_disputes ORDER BY created_at DESC"
                ).fetchall()
        return [dict(r) for r in rows]

    # -- reputation ---------------------------------------------------------

    def get_reputation(self, user_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM provenance_reputation WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row:
            return dict(row)
        return {"user_id": user_id, "false_claims": 0, "frivolous_challenges": 0}

    def bump_reputation(self, user_id: str, field: str) -> dict[str, Any]:
        if field not in ("false_claims", "frivolous_challenges"):
            raise ValueError(f"bad reputation field: {field}")
        with self._lock:
            self._conn.execute(
                """INSERT INTO provenance_reputation (user_id, false_claims, frivolous_challenges)
                   VALUES (?, 0, 0) ON CONFLICT(user_id) DO NOTHING""",
                (user_id,),
            )
            self._conn.execute(
                f"UPDATE provenance_reputation SET {field} = {field} + 1 WHERE user_id = ?",
                (user_id,),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM provenance_reputation WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return dict(row)
