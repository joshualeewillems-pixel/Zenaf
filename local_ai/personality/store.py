"""SQLite store for PersonalityProfiles (Phase 1: the user-defined side).

Layout (under <repo>/data/personality/):
  profiles.db  — profile_versions (immutable), profile_candidates (review queue)

Design rules (from docs/PERSONALITY_PROFILE.md + Joshua's directive):
- Versions are IMMUTABLE. publish() is the ONLY write path to
  profile_versions; it creates version = max+1 with a `supersedes` pointer.
- Candidates are inert proposals. propose() NEVER creates or mutates a
  version. Nothing becomes part of a profile without an explicit publish.
- The aspirational defaults (BUILT_IN_PERSONA_DEFINITIONS) are never read,
  written, or referenced here. This store holds the user-defined side only.
- Per-user scoping: every row carries user_id; the store filters strictly.

Threading: one connection guarded by a lock is enough for user-triggered use.
"""
from __future__ import annotations

import copy
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from local_ai.strands import strand_keys

from .schema import (
    CandidateStatus,
    DomainEntry,
    ExampleFragment,
    PersonalityProfile,
    ProfileCandidate,
    RedLine,
    StrandProfile,
    VoiceProfile,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data" / "personality"
DEFAULT_DB_PATH = DATA_DIR / "profiles.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS profile_versions (
    profile_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    supersedes INTEGER,
    created_at TEXT NOT NULL,
    source_summary TEXT NOT NULL DEFAULT '',
    approved_by TEXT NOT NULL DEFAULT 'user',
    profile_json TEXT NOT NULL,
    PRIMARY KEY (profile_id, version)
);
CREATE INDEX IF NOT EXISTS idx_versions_user ON profile_versions(user_id, version);
CREATE TABLE IF NOT EXISTS profile_candidates (
    candidate_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    strand_key TEXT,
    ops_json TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0.5,
    rationale TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'proposed',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_candidates_user ON profile_candidates(user_id, status);
CREATE TABLE IF NOT EXISTS seat_weights (
    user_id TEXT NOT NULL DEFAULT '',
    strand_key TEXT NOT NULL,
    weight REAL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, strand_key)
);
CREATE TABLE IF NOT EXISTS personality_settings (
    user_id TEXT NOT NULL DEFAULT '',
    key TEXT NOT NULL,
    value TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);
"""

_VALID_STATUSES: tuple[str, ...] = ("proposed", "accepted", "rejected", "published")


def _json_loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _profile_to_row(p: PersonalityProfile) -> dict:
    return {
        "profile_id": p.profile_id,
        "user_id": p.user_id,
        "version": p.version,
        "supersedes": p.supersedes,
        "created_at": p.created_at.isoformat(),
        "source_summary": p.source_summary,
        "approved_by": p.approved_by,
        "profile_json": p.model_dump_json(),
    }


def _row_to_profile(row: sqlite3.Row) -> PersonalityProfile:
    data = json.loads(row["profile_json"])
    # created_at etc. come from the JSON snapshot (immutable); row columns
    # carry the queryable metadata.
    return PersonalityProfile(**data)


def _row_to_candidate(row: sqlite3.Row) -> ProfileCandidate:
    return ProfileCandidate(
        candidate_id=row["candidate_id"],
        user_id=row["user_id"],
        strand_key=row["strand_key"],
        ops=_json_loads(row["ops_json"], []),
        source=row["source"],
        confidence=row["confidence"],
        rationale=row["rationale"],
        status=row["status"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _apply_ops(base: dict, candidate: ProfileCandidate) -> dict:
    """Apply a candidate's ops to a profile dict (in-memory only)."""
    for op in candidate.ops:
        if op.field.startswith("voice."):
            target = base["voice"]
            leaf = op.field.split(".", 1)[1]
            if op.op == "add":
                _add_unique(target[leaf], op.value)
            else:
                target[leaf] = op.value
            continue
        strands = base["strands"]
        sp = strands[candidate.strand_key]
        head, _, rest = op.field.partition(".")
        if rest:  # nested, e.g. fingerprint.risk_bias / reasoning.notes
            if op.op == "add":
                _add_unique(sp[head][rest], _coerce(head, rest, op.value))
            else:
                sp[head][rest] = op.value
        else:  # top-level strand list field
            _add_unique(sp[head], _coerce(head, "", op.value))
    return base


def _add_unique(lst: list, value: Any) -> None:
    marker = json.dumps(value, sort_keys=True, default=str)
    if all(json.dumps(v, sort_keys=True, default=str) != marker for v in lst):
        lst.append(value)


def _coerce(head: str, rest: str, value: Any) -> Any:
    """Validate structured values against their sub-models; pass scalars through."""
    if head == "domain_map":
        return DomainEntry(**value).model_dump() if isinstance(value, dict) else value
    if head == "red_lines":
        return RedLine(**value).model_dump() if isinstance(value, dict) else value
    if head == "examples":
        return ExampleFragment(**value).model_dump() if isinstance(value, dict) else value
    return value


class PersonalityStore:
    """Versioned, per-user personality profile store.

    The no-silent-write guarantee: `publish()` is the sole method that
    inserts into `profile_versions`. `propose()` only writes to the
    candidates table. There is no update path for published rows.
    """

    def __init__(self, db_path: Path | str | None = None, user_id: str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # None = unscoped (tests / local single-user); otherwise strict filter.
        self.user_id = user_id
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _owner(self) -> tuple[str, tuple]:
        if self.user_id is None:
            return "", ()
        return "user_id = ?", (self.user_id,)

    # -- candidates (propose / review) ------------------------------------

    def propose(self, candidate: ProfileCandidate) -> ProfileCandidate:
        """Queue a candidate diff. NEVER creates or mutates a profile version."""
        owner = candidate.user_id or self.user_id or ""
        candidate.user_id = owner
        if candidate.status != "proposed":
            candidate.status = "proposed"
        with self._lock:
            self._conn.execute(
                "INSERT INTO profile_candidates "
                "(candidate_id, user_id, strand_key, ops_json, source, confidence,"
                " rationale, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    candidate.candidate_id,
                    candidate.user_id,
                    candidate.strand_key,
                    json.dumps([o.model_dump() for o in candidate.ops]),
                    candidate.source,
                    candidate.confidence,
                    candidate.rationale,
                    candidate.status,
                    candidate.created_at.isoformat(),
                ),
            )
            self._conn.commit()
        return candidate

    def list_candidates(self, status: CandidateStatus | None = None) -> list[ProfileCandidate]:
        clause, params = self._owner()
        q = "SELECT * FROM profile_candidates"
        filters, args = [], list(params)
        if clause:
            filters.append(clause)
        if status:
            filters.append("status = ?")
            args.append(status)
        if filters:
            q += " WHERE " + " AND ".join(filters)
        q += " ORDER BY created_at ASC"
        with self._lock:
            rows = self._conn.execute(q, args).fetchall()
        return [_row_to_candidate(r) for r in rows]

    def reject(self, candidate_ids: list[str]) -> int:
        """Mark candidates rejected. Rejected candidates are never published."""
        clause, params = self._owner()
        with self._lock:
            cur = self._conn.executemany(
                "UPDATE profile_candidates SET status = 'rejected' "
                f"WHERE candidate_id = ? AND status = 'proposed'{(' AND ' + clause) if clause else ''}",
                [(cid, *params) for cid in candidate_ids],
            )
            self._conn.commit()
            return cur.rowcount

    # -- publish (the ONLY version write path) -----------------------------

    def publish(
        self,
        candidate_ids: list[str],
        *,
        approved_by: str = "user",
        source_summary: str = "",
    ) -> PersonalityProfile:
        """Apply proposed candidates as a NEW immutable profile version.

        Raises ValueError if any candidate is missing, not proposed, or
        belongs to another user. Published candidates flip to 'published'.
        """
        clause, params = self._owner()
        with self._lock:
            cands: list[ProfileCandidate] = []
            for cid in candidate_ids:
                q = "SELECT * FROM profile_candidates WHERE candidate_id = ?"
                args: list[Any] = [cid]
                if clause:
                    q += f" AND {clause}"
                    args.extend(params)
                row = self._conn.execute(q, args).fetchone()
                if row is None:
                    raise ValueError(f"candidate {cid!r} not found")
                cand = _row_to_candidate(row)
                if cand.status != "proposed":
                    raise ValueError(f"candidate {cid!r} is {cand.status}, not proposed")
                cands.append(cand)

            current = self._latest_locked()
            if current is None:
                base: dict[str, Any] = PersonalityProfile(
                    profile_id=f"pp_{uuid.uuid4().hex[:12]}",
                    user_id=self.user_id or "",
                    version=1,
                    strands={k: StrandProfile() for k in strand_keys()},
                    voice=VoiceProfile(),
                ).model_dump(mode="json")
                new_version = 1
                supersedes = None
                profile_id = base["profile_id"]
            else:
                base = json.loads(current.model_dump_json())
                new_version = current.version + 1
                supersedes = current.version
                profile_id = current.profile_id

            for cand in cands:
                base = _apply_ops(base, cand)

            profile = PersonalityProfile(
                **{
                    **base,
                    "version": new_version,
                    "supersedes": supersedes,
                    "created_at": datetime.now(timezone.utc),
                    "source_summary": source_summary,
                    "approved_by": approved_by,
                }
            )
            row = _profile_to_row(profile)
            self._conn.execute(
                "INSERT INTO profile_versions "
                "(profile_id, user_id, version, supersedes, created_at,"
                " source_summary, approved_by, profile_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row["profile_id"],
                    row["user_id"],
                    row["version"],
                    row["supersedes"],
                    row["created_at"],
                    row["source_summary"],
                    row["approved_by"],
                    row["profile_json"],
                ),
            )
            self._conn.executemany(
                "UPDATE profile_candidates SET status = 'published' WHERE candidate_id = ?",
                [(c.candidate_id,) for c in cands],
            )
            self._conn.commit()
            return profile

    # -- reads --------------------------------------------------------------

    def _latest_locked(self) -> PersonalityProfile | None:
        clause, params = self._owner()
        q = "SELECT * FROM profile_versions"
        if clause:
            q += f" WHERE {clause}"
        q += " ORDER BY version DESC LIMIT 1"
        row = self._conn.execute(q, params).fetchone()
        return _row_to_profile(row) if row else None

    def get_current(self) -> PersonalityProfile | None:
        """Latest published version, or None if the user never published."""
        with self._lock:
            return self._latest_locked()

    def get_version(self, version: int) -> PersonalityProfile | None:
        clause, params = self._owner()
        q = "SELECT * FROM profile_versions WHERE version = ?"
        args: list[Any] = [version]
        if clause:
            q += f" AND {clause}"
            args.extend(params)
        with self._lock:
            row = self._conn.execute(q, args).fetchone()
        return _row_to_profile(row) if row else None

    def list_versions(self) -> list[dict[str, Any]]:
        """Version metadata (no full payloads) for the review UI."""
        clause, params = self._owner()
        q = (
            "SELECT version, supersedes, created_at, source_summary, approved_by"
            " FROM profile_versions"
        )
        if clause:
            q += f" WHERE {clause}"
        q += " ORDER BY version ASC"
        with self._lock:
            rows = self._conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]

    def version_count(self) -> int:
        clause, params = self._owner()
        q = "SELECT COUNT(*) AS n FROM profile_versions"
        if clause:
            q += f" WHERE {clause}"
        with self._lock:
            return int(self._conn.execute(q, params).fetchone()["n"])

    # -- seat weights (Phase 4: per-strand user-side blend weight) ----------

    def _weight_owner(self) -> str:
        """Owner key for the seat_weights table ('' = unscoped single-user)."""
        return self.user_id or ""

    def get_weight_overrides(self) -> dict[str, float | None]:
        """Manual per-strand weight overrides. Missing key = auto (None)."""
        owner = self._weight_owner()
        with self._lock:
            rows = self._conn.execute(
                "SELECT strand_key, weight FROM seat_weights WHERE user_id = ?",
                (owner,),
            ).fetchall()
        return {r["strand_key"]: (None if r["weight"] is None else float(r["weight"])) for r in rows}

    def set_weight_overrides(self, mapping: dict[str, float | None]) -> dict[str, float | None]:
        """Set per-strand weight overrides. None clears back to auto.

        Validates strand keys against the 7 canonical strands and weights
        against [0.0, 1.0]. Returns the full override map afterwards.
        """
        from local_ai.strands import strand_keys

        valid = set(strand_keys())
        owner = self._weight_owner()
        with self._lock:
            for key, weight in mapping.items():
                if key not in valid:
                    raise ValueError(f"unknown strand_key: {key!r} (expected one of {sorted(valid)})")
                if weight is None:
                    self._conn.execute(
                        "DELETE FROM seat_weights WHERE user_id = ? AND strand_key = ?",
                        (owner, key),
                    )
                else:
                    w = float(weight)
                    if not (0.0 <= w <= 1.0):
                        raise ValueError(f"weight for {key!r} must be in [0.0, 1.0]; got {weight!r}")
                    self._conn.execute(
                        "INSERT INTO seat_weights (user_id, strand_key, weight, updated_at)"
                        " VALUES (?, ?, ?, ?)"
                        " ON CONFLICT(user_id, strand_key) DO UPDATE SET weight = excluded.weight,"
                        " updated_at = excluded.updated_at",
                        (owner, key, w, _iso_now()),
                    )
            self._conn.commit()
        return self.get_weight_overrides()

    # -- council personality mode (user-chosen seat version) -----------------

    _COUNCIL_MODE_KEY = "council_mode"
    _COUNCIL_MODES = ("base", "mirror", "blend")

    def get_council_mode(self) -> str:
        """The user's default council personality mode. System default: blend."""
        owner = self._weight_owner()
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM personality_settings WHERE user_id = ? AND key = ?",
                (owner, self._COUNCIL_MODE_KEY),
            ).fetchone()
        v = (row["value"] if row else "").strip().lower()
        return v if v in self._COUNCIL_MODES else "blend"

    def set_council_mode(self, mode: str) -> str:
        """Set the user's default council personality mode. Validates input."""
        v = (mode or "").strip().lower()
        if v not in self._COUNCIL_MODES:
            raise ValueError(
                f"unknown council mode {mode!r} (expected one of {list(self._COUNCIL_MODES)})"
            )
        owner = self._weight_owner()
        with self._lock:
            self._conn.execute(
                "INSERT INTO personality_settings (user_id, key, value, updated_at)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value,"
                " updated_at = excluded.updated_at",
                (owner, self._COUNCIL_MODE_KEY, v, _iso_now()),
            )
            self._conn.commit()
        return v
