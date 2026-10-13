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

_SCHEMA = """
CREATE TABLE IF NOT EXISTS connected_agents (
    agent_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_platform TEXT NOT NULL,
    description TEXT NOT NULL,
    instructions TEXT,
    examples TEXT NOT NULL DEFAULT '[]',
    sort_result TEXT,
    status TEXT NOT NULL DEFAULT 'pending_review',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agents_status ON connected_agents(status);
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
    )


class AgentStore:
    """SQLite-backed store for connected agents."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def save(self, agent: ConnectedAgent) -> ConnectedAgent:
        """Create or replace an agent record."""
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO connected_agents "
                "(agent_id, name, source_platform, description, instructions, "
                " examples, sort_result, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                ),
            )
            self._conn.commit()
        return agent

    def get(self, agent_id: str) -> ConnectedAgent | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM connected_agents WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
        return _agent_from_row(row) if row else None

    def list_all(self) -> list[ConnectedAgent]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM connected_agents ORDER BY created_at DESC"
            ).fetchall()
        return [_agent_from_row(r) for r in rows]

    def list_pending(self) -> list[ConnectedAgent]:
        """Agents awaiting user review (the review queue)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM connected_agents WHERE status = 'pending_review' "
                "ORDER BY created_at DESC"
            ).fetchall()
        return [_agent_from_row(r) for r in rows]

    def update_status(self, agent_id: str, status: str) -> bool:
        """Move an agent between pending_review / active / archived."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE connected_agents SET status = ? WHERE agent_id = ?",
                (status, agent_id),
            )
            self._conn.commit()
            return cur.rowcount > 0
