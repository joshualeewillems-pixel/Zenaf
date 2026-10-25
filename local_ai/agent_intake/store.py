"""SQLite store for connected agents (Agent Intake & Sorting).

Layout (under <repo>/data/agent_intake/):
  agents.db             — connected_agents

Design rules:
- Redaction happens at capture (pipeline.py): only redacted text is stored.
- Agents are NOT append-only: status moves pending_review -> active /
  archived as the user reviews. The corrections log (JSONL) keeps the audit
  trail of what the user changed.

Threading: one connection guarded by a lock is enough for user-triggered use.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .schema import ConnectedAgent, SortResult

# Anchor the data dir to the repo root so the location is stable regardless
# of the process working directory.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data" / "agent_intake"
DEFAULT_DB_PATH = DATA_DIR / "agents.db"

_SCHEMA_TABLE = """
CREATE TABLE IF NOT EXISTS connected_agents (
    agent_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_platform TEXT NOT NULL,
    description TEXT NOT NULL,
    instructions TEXT,
    examples TEXT NOT NULL DEFAULT '[]',
    sort_result TEXT,
    status TEXT NOT NULL DEFAULT 'pending_review',
    created_at TEXT NOT NULL,
    user_id TEXT NOT NULL DEFAULT '',
    mining_state TEXT NOT NULL DEFAULT 'pending',
    mined_payload TEXT
);
"""

_SCHEMA_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_agents_status ON connected_agents(status);
CREATE INDEX IF NOT EXISTS idx_agents_user ON connected_agents(user_id, status);
"""

_SCHEMA_CLAIMS = """
CREATE TABLE IF NOT EXISTS review_claims (
    claim_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    claim_type TEXT NOT NULL,
    title TEXT NOT NULL,
    evidence TEXT NOT NULL DEFAULT '',
    inference TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    user_note TEXT NOT NULL DEFAULT '',
    question TEXT NOT NULL DEFAULT '',
    scope TEXT NOT NULL DEFAULT 'moment',
    turn_ref TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    user_id TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_claims_agent ON review_claims(agent_id);
CREATE INDEX IF NOT EXISTS idx_claims_user ON review_claims(user_id, agent_id);
"""


def _json_loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _agent_from_row(row: sqlite3.Row) -> ConnectedAgent:
    sort_raw = _json_loads(row["sort_result"], None)
    return ConnectedAgent(
        id=row["agent_id"],
        name=row["name"],
        source_platform=row["source_platform"],
        description=row["description"],
        instructions=row["instructions"],
        examples=_json_loads(row["examples"], []),
        sort=SortResult.from_dict(sort_raw) if sort_raw else None,
        status=row["status"],
        created_at=row["created_at"],
        user_id=row["user_id"] if "user_id" in row.keys() else "",
        mining_state=row["mining_state"] if "mining_state" in row.keys() else "pending",
        mined_payload=_json_loads(row["mined_payload"], None) if "mined_payload" in row.keys() else None,
    )


def _backfill_single_owner(conn: sqlite3.Connection) -> None:
    """Claim pre-multi-user rows for the single user, if there is exactly one.

    Default-deny: with zero or several users, orphan rows stay unclaimed
    (invisible to everyone) rather than being attributed to the wrong person.
    """
    try:
        cur = conn.execute("SELECT COUNT(*) AS n FROM connected_agents WHERE user_id = ''")
        if cur.fetchone()["n"] == 0:
            return
        from local_ai.vision_execution import storage as St

        users = St.get_connection().execute("SELECT id FROM users").fetchall()
        if len(users) == 1:
            conn.execute(
                "UPDATE connected_agents SET user_id = ? WHERE user_id = ''",
                (users[0]["id"],),
            )
            conn.commit()
    except Exception:
        pass  # never break intake on a best-effort migration


class AgentStore:
    """SQLite-backed store for connected agents."""

    def __init__(self, db_path: Path | str | None = None, user_id: str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # None = unscoped (local single-user mode / tests); otherwise strict per-user filtering.
        self.user_id = user_id
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            cols = [r["name"] for r in self._conn.execute("PRAGMA table_info(connected_agents)").fetchall()]
            self._conn.execute(_SCHEMA_TABLE)
            # Migrations for pre-existing tables: add each missing column
            # BEFORE any index that references it (the old user_id migration
            # created idx_agents_user first, which raised "no such column:
            # user_id" and aborted the migration — see test).
            for col, ddl in (
                ("user_id", "ALTER TABLE connected_agents ADD COLUMN user_id TEXT NOT NULL DEFAULT ''"),
                ("mining_state", "ALTER TABLE connected_agents ADD COLUMN mining_state TEXT NOT NULL DEFAULT 'pending'"),
                ("mined_payload", "ALTER TABLE connected_agents ADD COLUMN mined_payload TEXT"),
            ):
                if cols and col not in cols:
                    self._conn.execute(ddl)
            self._conn.executescript(_SCHEMA_INDEXES)
            self._conn.executescript(_SCHEMA_CLAIMS)
            # review_claims migrations: question / scope / turn_ref for the
            # five-part insight cards. Same best-effort pattern as above.
            claim_cols = [
                r["name"]
                for r in self._conn.execute("PRAGMA table_info(review_claims)").fetchall()
            ]
            for col, ddl in (
                ("question", "ALTER TABLE review_claims ADD COLUMN question TEXT NOT NULL DEFAULT ''"),
                ("scope", "ALTER TABLE review_claims ADD COLUMN scope TEXT NOT NULL DEFAULT 'moment'"),
                ("turn_ref", "ALTER TABLE review_claims ADD COLUMN turn_ref TEXT NOT NULL DEFAULT ''"),
            ):
                if claim_cols and col not in claim_cols:
                    self._conn.execute(ddl)
            _backfill_single_owner(self._conn)
            self._conn.commit()

    def _owner_clause(self) -> tuple[str, tuple]:
        if self.user_id is None:
            return "", ()
        return "user_id = ?", (self.user_id,)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def save(self, agent: ConnectedAgent) -> ConnectedAgent:
        """Create or replace an agent record."""
        owner = agent.user_id or self.user_id or ""
        agent.user_id = owner
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO connected_agents "
                "(agent_id, name, source_platform, description, instructions, "
                " examples, sort_result, status, created_at, user_id, "
                " mining_state, mined_payload) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    agent.id,
                    agent.name,
                    agent.source_platform,
                    agent.description,
                    agent.instructions,
                    json.dumps(agent.examples),
                    json.dumps(agent.sort.to_dict()) if agent.sort else None,
                    agent.status,
                    agent.created_at,
                    owner,
                    agent.mining_state or "pending",
                    json.dumps(agent.mined_payload) if agent.mined_payload else None,
                ),
            )
            self._conn.commit()
        return agent

    def get(self, agent_id: str) -> ConnectedAgent | None:
        clause, params = self._owner_clause()
        q = "SELECT * FROM connected_agents WHERE agent_id = ?"
        if clause:
            q += f" AND {clause}"
        with self._lock:
            row = self._conn.execute(q, (agent_id, *params)).fetchone()
        return _agent_from_row(row) if row else None

    def list_all(self) -> list[ConnectedAgent]:
        clause, params = self._owner_clause()
        q = "SELECT * FROM connected_agents"
        if clause:
            q += f" WHERE {clause}"
        q += " ORDER BY created_at DESC"
        with self._lock:
            rows = self._conn.execute(q, params).fetchall()
        return [_agent_from_row(r) for r in rows]

    def list_pending(self) -> list[ConnectedAgent]:
        """Agents awaiting user review (the review queue)."""
        clause, params = self._owner_clause()
        q = "SELECT * FROM connected_agents WHERE status = 'pending_review'"
        if clause:
            q += f" AND {clause}"
        q += " ORDER BY created_at DESC"
        with self._lock:
            rows = self._conn.execute(q, params).fetchall()
        return [_agent_from_row(r) for r in rows]

    def update_status(self, agent_id: str, status: str) -> bool:
        """Move an agent between pending_review / active / archived."""
        clause, params = self._owner_clause()
        q = "UPDATE connected_agents SET status = ? WHERE agent_id = ?"
        if clause:
            q += f" AND {clause}"
        with self._lock:
            cur = self._conn.execute(q, (status, agent_id, *params))
            self._conn.commit()
            return cur.rowcount > 0

    def set_mining_state(
        self, agent_id: str, state: str, payload: dict | None = None
    ) -> bool:
        """Record the project-mining stage of the review flow.

        state is one of "pending" | "mined" | "skipped". When state is
        "mined", payload carries the raw mining result (initiatives /
        projects / tasks / ideas) so accepted mined claims can be created
        as entities even after the client reloads.
        """
        clause, params = self._owner_clause()
        q = "UPDATE connected_agents SET mining_state = ?, mined_payload = ? WHERE agent_id = ?"
        if clause:
            q += f" AND {clause}"
        with self._lock:
            cur = self._conn.execute(
                q,
                (
                    state,
                    json.dumps(payload) if payload else None,
                    agent_id,
                    *params,
                ),
            )
            self._conn.commit()
            return cur.rowcount > 0

    # -- Review claims ----------------------------------------------------

    def save_claims(self, agent_id: str, claims: list) -> None:
        """Persist review claims for an agent (insert or replace)."""
        from datetime import datetime, timezone

        owner = self.user_id or ""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            for c in claims:
                self._conn.execute(
                    "INSERT OR REPLACE INTO review_claims "
                    "(claim_id, agent_id, claim_type, title, evidence, inference, "
                    " detail, status, user_note, question, scope, turn_ref, "
                    " created_at, updated_at, user_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                    " COALESCE((SELECT created_at FROM review_claims WHERE claim_id = ?), ?),"
                    " ?, ?)",
                    (
                        c.id, agent_id, c.claim_type, c.title, c.evidence,
                        c.inference, c.detail, c.status, c.user_note,
                        c.question, c.scope, c.turn_ref,
                        c.id, now, now, owner,
                    ),
                )
            self._conn.commit()

    def delete_claim_types(self, agent_id: str, types: tuple[str, ...]) -> int:
        """Delete an agent's claims of the given claim types.

        Used by insight regeneration: stale insight/strand/kind/alternative
        rows are removed before the fresh set is saved, so a re-read can't
        leave orphaned claims behind. Mined project claims are untouched.
        """
        if not types:
            return 0
        clause, params = self._owner_clause()
        q = (
            "DELETE FROM review_claims WHERE agent_id = ? AND claim_type IN "
            f"({', '.join('?' * len(types))})"
        )
        args: list = [agent_id, *types]
        if clause:
            q += f" AND {clause}"
            args.extend(params)
        with self._lock:
            cur = self._conn.execute(q, args)
            self._conn.commit()
            return cur.rowcount

    def get_claims(self, agent_id: str) -> list:
        """Return the agent's review claims, oldest first."""
        from .review_claims import ReviewClaim

        clause, params = self._owner_clause()
        q = "SELECT * FROM review_claims WHERE agent_id = ?"
        if clause:
            q += f" AND {clause}"
        q += " ORDER BY created_at ASC"
        with self._lock:
            rows = self._conn.execute(q, (agent_id, *params)).fetchall()
        return [
            ReviewClaim(
                id=r["claim_id"],
                claim_type=r["claim_type"],
                title=r["title"],
                evidence=r["evidence"],
                inference=r["inference"],
                detail=r["detail"],
                status=r["status"],
                user_note=r["user_note"],
                question=r["question"] if "question" in r.keys() else "",
                scope=r["scope"] if "scope" in r.keys() else "moment",
                turn_ref=r["turn_ref"] if "turn_ref" in r.keys() else "",
            )
            for r in rows
        ]

    def claims_for_user(self, user_id: str) -> list[dict]:
        """All review-claim rows owned by the user, oldest first —
        as plain dicts INCLUDING created_at/updated_at (increment
        C's O2 rule compares a correction's verdict time against
        thread rows, and the ReviewClaim model drops both clocks).
        Scoped by the review_claims user_id column, never by agent.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT claim_id, agent_id, claim_type, status, "
                "user_note, created_at, updated_at FROM review_claims "
                "WHERE user_id = ? ORDER BY created_at ASC",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_claim(self, claim_id: str, status: str, user_note: str = "") -> bool:
        """Set a claim's review status and the user's note."""
        from datetime import datetime, timezone

        clause, params = self._owner_clause()
        q = "UPDATE review_claims SET status = ?, user_note = ?, updated_at = ? WHERE claim_id = ?"
        if clause:
            q += f" AND {clause}"
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cur = self._conn.execute(q, (status, user_note, now, claim_id, *params))
            self._conn.commit()
            return cur.rowcount > 0
