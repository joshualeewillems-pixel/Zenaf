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
    user_id TEXT NOT NULL DEFAULT ''
);
"""

_SCHEMA_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_agents_status ON connected_agents(status);
CREATE INDEX IF NOT EXISTS idx_agents_user ON connected_agents(user_id, status);
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
            if cols and "user_id" not in cols:
                # Pre-multi-user table: add the column BEFORE any index that
                # references it (the old code created idx_agents_user first,
                # which raised "no such column: user_id" and aborted the migration).
                self._conn.execute("ALTER TABLE connected_agents ADD COLUMN user_id TEXT NOT NULL DEFAULT ''")
            self._conn.executescript(_SCHEMA_INDEXES)
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
                " examples, sort_result, status, created_at, user_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
