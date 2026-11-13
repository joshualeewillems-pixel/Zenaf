"""Conversation-skeleton persistence: one ongoing conversation per user.

Own SQLite database (``data/conversations/conversations.db``), following the
per-domain convention (personality, followthrough, provenance). Strict
per-user rows: every read and write is scoped by user_id.

Tables:
  conversations    — one row per (user_id, conversation_id); the skeleton
                     itself. kind='skeleton' for the main thread.
  messages         — every turn, tagged with archetype_id (the seat branch;
                     NULL only for future trunk turns), role, body, the mode
                     used, and a live-context snapshot (JSON).
  thread_state     — per-seat rolling summary + activity: the quiet
                     background continuity each persona carries.
  suggestion_runs  — cached suggestion-engine output, watermarked by the
                     latest message id so GET /conversation/suggestions
                     doesn't re-run the LLM on every call.
  invitations      — Capability C S1: selective-participation records.
                     One pending invitation per (user, conversation,
                     seat); a tap OPENS a conversation but never
                     accepts — only a sent turn to the invited seat
                     accepts (service.turn wires that). Statuses:
                     pending | accepted | expired. No dismiss status
                     in v1: untapped means deferred, not rejected.

Threading: one connection guarded by a lock is enough for user-triggered use.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data" / "conversations"
DEFAULT_DB_PATH = DATA_DIR / "conversations.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
  user_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'skeleton',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, conversation_id)
);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  archetype_id TEXT,
  role TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '',
  mode TEXT NOT NULL DEFAULT 'trained',
  context_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conv_messages_user_conv
  ON messages (user_id, conversation_id, created_at, id);
CREATE TABLE IF NOT EXISTS thread_state (
  user_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  archetype_id TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT '',
  last_active TEXT NOT NULL DEFAULT '',
  messages_since_summary INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, conversation_id, archetype_id)
);
CREATE TABLE IF NOT EXISTS suggestion_runs (
  user_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  up_to_message_id TEXT NOT NULL,
  suggestions_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (user_id, conversation_id)
);
CREATE TABLE IF NOT EXISTS invitations (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  seat TEXT NOT NULL,
  observation_ids TEXT NOT NULL DEFAULT '[]',
  reason TEXT NOT NULL DEFAULT '',
  evidence_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  accepted_message_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_invitations_user_conv_seat
  ON invitations (user_id, conversation_id, seat, status);
CREATE INDEX IF NOT EXISTS idx_invitations_user_expiry
  ON invitations (user_id, status, expires_at);
CREATE TABLE IF NOT EXISTS round_parked_ids (
  user_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  item_id TEXT NOT NULL,
  parked_at TEXT NOT NULL,
  PRIMARY KEY (user_id, conversation_id, kind, item_id)
);
CREATE TABLE IF NOT EXISTS round_reserved_ids (
  user_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  item_id TEXT NOT NULL,
  reserved_at TEXT NOT NULL,
  snooze_until TEXT,
  PRIMARY KEY (user_id, kind, item_id)
);
-- Weaver rapid fire S1 (brief §7.3/§8.4): the per-user decline-
-- cooldown timestamp, beside the parked-ids record. One row per
-- user: the last time the user declined (or ignored) a round offer.
-- While now < declined_at + 24h, no proactive offer is invited in
-- any conversation. The cooldown is a read-time gate, never a sweep.
CREATE TABLE IF NOT EXISTS round_decline_cooldowns (
  user_id TEXT NOT NULL PRIMARY KEY,
  declined_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS strand_threads (
  user_id TEXT NOT NULL,
  strand_key TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, strand_key),
  UNIQUE (user_id, conversation_id)
);
CREATE TABLE IF NOT EXISTS strand_topic_boundaries (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  strand_key TEXT NOT NULL,
  topic TEXT NOT NULL,
  topic_normalized TEXT NOT NULL,
  created_at TEXT NOT NULL,
  created_by_message_id TEXT,
  UNIQUE (user_id, strand_key, topic_normalized)
);
CREATE INDEX IF NOT EXISTS idx_strand_boundaries_user_strand
  ON strand_topic_boundaries (user_id, strand_key, created_at);
CREATE TABLE IF NOT EXISTS strand_sources (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  strand_key TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  ref TEXT NOT NULL,
  label TEXT NOT NULL DEFAULT '',
  excerpt_redacted TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_strand_sources_user_strand
  ON strand_sources (user_id, strand_key, created_at);
-- Upload rapid-fire S1 (§2.1–§2.9): nine ConversationStore tables.
-- The tenth table (upload_outcome_creations) lives in the VE DB
-- (local_ai/vision_execution/storage.py + schema.sql, U-1).
CREATE TABLE IF NOT EXISTS upload_spans (
  span_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  document_id TEXT NOT NULL,
  document_version INTEGER NOT NULL,
  segment_id TEXT NOT NULL,
  span_text TEXT NOT NULL,
  redaction_stage TEXT NOT NULL,
  location TEXT NOT NULL,
  span_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'current',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_upload_spans_user_doc
  ON upload_spans (user_id, document_id, document_version, segment_id);
CREATE INDEX IF NOT EXISTS idx_upload_spans_hash_loc
  ON upload_spans (span_hash, location);
CREATE TABLE IF NOT EXISTS upload_observations (
  observation_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  document_id TEXT NOT NULL,
  document_version INTEGER NOT NULL,
  claim TEXT NOT NULL,
  span_ids TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'current',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_upload_observations_user_doc
  ON upload_observations (user_id, document_id, document_version);
CREATE TABLE IF NOT EXISTS upload_interpretations (
  interpretation_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  document_id TEXT NOT NULL,
  document_version INTEGER NOT NULL,
  lens TEXT NOT NULL,
  lens_kind TEXT NOT NULL,
  text TEXT NOT NULL,
  evidence_ids TEXT NOT NULL DEFAULT '[]',
  observation_ids TEXT NOT NULL DEFAULT '[]',
  origin TEXT NOT NULL,
  is_transformation INTEGER NOT NULL DEFAULT 0,
  proposed_outcome TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  uncertain_match TEXT,
  promotion_turn_id TEXT,
  promotion_message_id TEXT,
  ungrounded INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_upload_interpretations_user_doc
  ON upload_interpretations (user_id, document_id, document_version, lens, status);
CREATE TABLE IF NOT EXISTS upload_outcomes (
  outcome_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  document_id TEXT NOT NULL,
  document_version INTEGER NOT NULL,
  interpretation_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  ve_kind TEXT,
  ve_id TEXT,
  parent_id TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_upload_outcomes_user_interp
  ON upload_outcomes (user_id, interpretation_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_upload_outcomes_interp_kind
  ON upload_outcomes (interpretation_id, kind);
CREATE TABLE IF NOT EXISTS upload_rounds (
  round_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  document_id TEXT NOT NULL,
  document_version INTEGER NOT NULL,
  lens TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'item',
  segment_presented TEXT NOT NULL DEFAULT '[]',
  presented_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_upload_rounds_user_conv
  ON upload_rounds (user_id, conversation_id, created_at);
CREATE TABLE IF NOT EXISTS upload_offers (
  offer_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  document_id TEXT NOT NULL,
  lens TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'offered',
  coverage TEXT NOT NULL DEFAULT '',
  decline_snooze_until TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_upload_offers_user_doc
  ON upload_offers (user_id, document_id, lens, created_at);
CREATE TABLE IF NOT EXISTS upload_extraction_jobs (
  job_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  document_id TEXT NOT NULL,
  document_version INTEGER NOT NULL,
  state TEXT NOT NULL DEFAULT 'queued',
  worker_id TEXT,
  last_heartbeat_at TEXT,
  lease_until TEXT,
  first_interpretation_at TEXT,
  total_calls INTEGER NOT NULL DEFAULT 0,
  completed_calls INTEGER NOT NULL DEFAULT 0,
  failed_calls INTEGER NOT NULL DEFAULT 0,
  failed_chunks TEXT NOT NULL DEFAULT '[]',
  interpreted_chunks TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_upload_jobs_user_doc
  ON upload_extraction_jobs (user_id, document_id, created_at);
CREATE TABLE IF NOT EXISTS upload_extraction_job_calls (
  call_id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL,
  chunk_index INTEGER,
  call_kind TEXT NOT NULL,
  state TEXT NOT NULL,
  code TEXT,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  duration_ms INTEGER,
  rows_written INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_upload_job_calls_job
  ON upload_extraction_job_calls (job_id, started_at);
CREATE TABLE IF NOT EXISTS upload_artifacts (
  artifact_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  document_id TEXT NOT NULL,
  document_version INTEGER NOT NULL,
  interpretation_id TEXT,
  lens TEXT NOT NULL,
  lens_kind TEXT NOT NULL,
  artifact_kind TEXT NOT NULL,
  artifact_text TEXT NOT NULL,
  source_span_ids TEXT NOT NULL DEFAULT '[]',
  framing TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_upload_artifacts_user_doc
  ON upload_artifacts (user_id, document_id, created_at);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


#: Capability C S1 — invitation lifetime backstop (verdict Q2, provisional).
#: Seven days is a cleanup backstop, NOT a relevance claim: an invitation
#: may be invalidated earlier when its evidence is demonstrably
#: superseded or addressed, and expiry never means the underlying
#: concern was resolved. No per-seat TTL in v1 (verdict Q7).
INVITATION_TTL_DAYS = 7


def _invitation_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Invitation row to API dict. Corrupt JSON degrades to empty."""
    try:
        observation_ids = json.loads(row["observation_ids"] or "[]")
    except Exception:
        observation_ids = []
    if not isinstance(observation_ids, list):
        observation_ids = []
    try:
        evidence = json.loads(row["evidence_json"] or "{}")
    except Exception:
        evidence = {}
    if not isinstance(evidence, dict):
        evidence = {}
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "conversation_id": row["conversation_id"],
        "seat": row["seat"],
        "observation_ids": observation_ids,
        "reason": row["reason"],
        "evidence": evidence,
        "status": row["status"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "accepted_message_id": row["accepted_message_id"],
    }


def _message_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    """Message rows to API dicts, oldest-first. Shared by history readers."""
    out: list[dict[str, Any]] = []
    for r in reversed(rows):
        try:
            context = json.loads(r["context_json"] or "{}")
        except Exception:
            context = {}
        out.append(
            {
                "id": r["id"],
                "user_id": r["user_id"],
                "conversation_id": r["conversation_id"],
                "archetype_id": r["archetype_id"],
                "role": r["role"],
                "body": r["body"],
                "mode": r["mode"],
                "context": context,
                "created_at": r["created_at"],
            }
        )
    return out


class ConversationStore:
    """SQLite-backed store for the conversation skeleton."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._migrate_paste_text_columns()
            self._migrate_upload_amendment_columns()
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _migrate_paste_text_columns(self) -> None:
        """Upload S1 §2.11 (U-2): full redacted paste text, COMPRESSED.

        New columns on strand_sources (not a companion table, so the
        U-5 inventory stays ten tables): ``paste_text_blob`` holds the
        zlib-compressed UTF-8 of the full redacted paste text and
        ``paste_text_encoding`` names the codec ('zlib'). Guarded by
        PRAGMA table_info — a no-op when the columns already exist
        (agent_intake precedent). Caller holds the lock.
        """
        cols = [
            r["name"]
            for r in self._conn.execute(
                "PRAGMA table_info(strand_sources)"
            ).fetchall()
        ]
        if "paste_text_blob" not in cols:
            self._conn.execute(
                "ALTER TABLE strand_sources ADD COLUMN paste_text_blob BLOB"
            )
        if "paste_text_encoding" not in cols:
            self._conn.execute(
                "ALTER TABLE strand_sources ADD COLUMN "
                "paste_text_encoding TEXT NOT NULL DEFAULT 'zlib'"
            )

    def _migrate_upload_amendment_columns(self) -> None:
        """Upload S1 amendment A3 (2026-11-07): the re-extraction
        fields the brief's DDL dropped, restored.

        - ``upload_interpretations.uncertain_match`` (TEXT JSON,
          NULL when no uncertain match).
        - ``upload_spans.status`` / ``upload_observations.status``
          (TEXT NOT NULL DEFAULT 'current'; the §5.4 transition
          moves the old set to 'superseded' at re-extraction).
        - ``upload_extraction_jobs.interpreted_chunks`` (TEXT JSON
          list, amendment A1's coverage tracking).
        - Index on ``upload_spans (span_hash, location)`` — the
          §5.2/§5.3 matching lookup compares spans by
          content+location.

        Guarded by PRAGMA table_info / CREATE INDEX IF NOT EXISTS —
        a no-op when the columns already exist (the paste-text
        migration's precedent). Caller holds the lock.
        """
        for table, column, ddl in (
            (
                "upload_interpretations",
                "uncertain_match",
                "ALTER TABLE upload_interpretations ADD COLUMN "
                "uncertain_match TEXT",
            ),
            (
                "upload_spans",
                "status",
                "ALTER TABLE upload_spans ADD COLUMN status "
                "TEXT NOT NULL DEFAULT 'current'",
            ),
            (
                "upload_observations",
                "status",
                "ALTER TABLE upload_observations ADD COLUMN status "
                "TEXT NOT NULL DEFAULT 'current'",
            ),
            (
                "upload_extraction_jobs",
                "interpreted_chunks",
                "ALTER TABLE upload_extraction_jobs ADD COLUMN "
                "interpreted_chunks TEXT NOT NULL DEFAULT '[]'",
            ),
        ):
            cols = [
                r["name"]
                for r in self._conn.execute(
                    f"PRAGMA table_info({table})"
                ).fetchall()
            ]
            if column not in cols:
                self._conn.execute(ddl)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_upload_spans_hash_loc "
            "ON upload_spans (span_hash, location)"
        )

    # -- conversations --------------------------------------------------------

    def ensure_conversation(
        self, user_id: str, conversation_id: str = "skeleton", kind: str = "skeleton"
    ) -> dict[str, Any]:
        now = _utcnow()
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO conversations "
                "(user_id, conversation_id, kind, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, conversation_id, kind, now, now),
            )
            self._conn.execute(
                "UPDATE conversations SET updated_at = ? "
                "WHERE user_id = ? AND conversation_id = ?",
                (now, user_id, conversation_id),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT user_id, conversation_id, kind, created_at, updated_at "
                "FROM conversations WHERE user_id = ? AND conversation_id = ?",
                (user_id, conversation_id),
            ).fetchone()
        return dict(row)

    # -- messages --------------------------------------------------------------

    def append_message(
        self,
        user_id: str,
        conversation_id: str,
        archetype_id: str | None,
        role: str,
        body: str,
        mode: str = "trained",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        msg_id = uuid.uuid4().hex[:16]
        now = _utcnow()
        context_json = json.dumps(context or {}, ensure_ascii=True)
        with self._lock:
            self._conn.execute(
                "INSERT INTO messages (id, user_id, conversation_id, archetype_id, "
                "role, body, mode, context_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    msg_id,
                    user_id,
                    conversation_id,
                    archetype_id,
                    role,
                    body or "",
                    mode or "trained",
                    context_json,
                    now,
                ),
            )
            self._conn.commit()
        return {
            "id": msg_id,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "archetype_id": archetype_id,
            "role": role,
            "body": body or "",
            "mode": mode or "trained",
            "context": context or {},
            "created_at": now,
        }

    def history(
        self, user_id: str, conversation_id: str = "skeleton", limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Oldest-first message history for hydration. Strictly per-user."""
        limit = max(1, min(int(limit or 50), 200))
        offset = max(0, int(offset or 0))
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, user_id, conversation_id, archetype_id, role, body, "
                "mode, context_json, created_at FROM messages "
                "WHERE user_id = ? AND conversation_id = ? "
                "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                (user_id, conversation_id, limit, offset),
            ).fetchall()
        return _message_dicts(rows)

    def get_message(
        self, user_id: str, conversation_id: str, message_id: str
    ) -> dict[str, Any] | None:
        """Single message row, strictly per-user. None when missing or
        foreign — a foreign id is indistinguishable from a missing one,
        so callers cannot probe another user's conversations."""
        with self._lock:
            row = self._conn.execute(
                "SELECT id, user_id, conversation_id, archetype_id, role, body, "
                "mode, context_json, created_at FROM messages "
                "WHERE user_id = ? AND conversation_id = ? AND id = ?",
                (user_id, conversation_id, message_id),
            ).fetchone()
        if row is None:
            return None
        return _message_dicts([row])[0]

    def count_messages(self, user_id: str, conversation_id: str) -> int:
        """Count of live message rows for one user conversation. Read-only."""
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM messages WHERE user_id = ? AND conversation_id = ?",
                (user_id, conversation_id),
            ).fetchone()
        return int(row[0]) if row else 0

    def list_conversations(
        self,
        user_id: str,
        limit: int = 20,
        seat: str | None = None,
        include_meetings: bool = False,
    ) -> list[dict[str, Any]]:
        """Talk conversations for one user, newest message activity first.

        Discovery only: the ``seats`` array is derived from message rows
        (distinct archetype_id values) so the client can resume a talk a
        seat has already spoken in. It is NOT a participation or
        authorization record — no invite, join, or membership state is
        implied by it, and no participant table exists. Every aggregate
        and preview subquery below carries the same user_id predicate
        as the outer query, so another user's rows can never match.

        Ordering uses the latest message time, NOT conversations
        .updated_at: ensure_conversation refreshes updated_at on every
        read and write, so it records last touch, not last message.
        The query is driven by message rows (not the conversations
        table) so a talk with messages is discoverable even if its
        conversation row was never ensured; zero-message rows are
        excluded by construction, since hydration-on-mount creates a
        row before anything is sent and such rows are not
        conversations the user can rediscover.

        When ``seat`` is a non-empty archetype id, the result is
        restricted to conversations that seat has spoken in, via an
        EXISTS membership predicate applied to the outer WHERE
        BEFORE the LIMIT — never a filter applied after a capped
        fetch, and never a row filter on the outer query (which
        would redefine last_message_at as the seat's own latest
        message and drift the recency rule). Ordering, shape, and
        clamping are unchanged; an absent or empty seat means
        today's unfiltered behavior exactly.

        ``include_meetings`` (founder, 2026-11-12: meetings join the
        chat list) additionally admits ``meeting-*`` conversations —
        the seats' first meetings — under the identical shape,
        ordering, and owner scoping; an entry's ``kind`` is
        ``'meeting'`` and its id is ``meeting-{seat}-{keystone}``,
        so clients can tell it apart from a talk and route it to the
        meeting view. It is opt-in because the seat-scoped resume
        lookup deliberately resolves TALKS only: a meeting must never
        become the thread a seat sheet auto-resumes. Callers that
        render a browsable list (the you-node rediscovery list, the
        seat History panel) opt in; the lookup does not, and every
        call without the flag returns exactly what it returned before.
        """
        limit = max(1, min(int(limit or 20), 100))
        id_clause = (
            "(m.conversation_id LIKE 'talk-%' OR m.conversation_id LIKE 'meeting-%')"
            if include_meetings
            else "m.conversation_id LIKE 'talk-%'"
        )
        seat_filter = seat if seat else None
        seat_clause = (
            "AND EXISTS (SELECT 1 FROM messages m2 WHERE m2.user_id = m.user_id "
            "AND m2.conversation_id = m.conversation_id "
            "AND m2.archetype_id = ?) "
            if seat_filter
            else ""
        )
        params: tuple = (
            (user_id, seat_filter, limit) if seat_filter else (user_id, limit)
        )
        with self._lock:
            rows = self._conn.execute(
                "SELECT m.conversation_id, c.kind, c.created_at, c.updated_at, "
                "COUNT(*) AS message_count, "
                "MAX(m.created_at) AS last_message_at, "
                "(SELECT m2.body FROM messages m2 WHERE m2.user_id = m.user_id "
                "AND m2.conversation_id = m.conversation_id "
                "ORDER BY m2.created_at DESC, m2.id DESC LIMIT 1) AS last_message_preview "
                "FROM messages m LEFT JOIN conversations c "
                "ON c.user_id = m.user_id AND c.conversation_id = m.conversation_id "
                "WHERE m.user_id = ? AND "
                + id_clause
                + " "
                + seat_clause
                + "GROUP BY m.conversation_id "
                "ORDER BY last_message_at DESC, m.conversation_id ASC LIMIT ?",
                params,
            ).fetchall()
            seat_rows = self._conn.execute(
                "SELECT m.conversation_id, m.archetype_id, MIN(m.created_at) AS first_seen "
                "FROM messages m WHERE m.user_id = ? AND m.archetype_id IS NOT NULL "
                "AND "
                + id_clause
                + " "
                "GROUP BY m.conversation_id, m.archetype_id "
                "ORDER BY m.conversation_id, first_seen",
                (user_id,),
            ).fetchall()
        seats: dict[str, list[str]] = {}
        for r in seat_rows:
            seats.setdefault(r["conversation_id"], []).append(r["archetype_id"])
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "conversation_id": r["conversation_id"],
                    "kind": r["kind"],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                    "message_count": int(r["message_count"]),
                    "seats": seats.get(r["conversation_id"], []),
                    "last_message_at": r["last_message_at"],
                    "last_message_preview": r["last_message_preview"],
                }
            )
        return out

    def history_before(
        self,
        user_id: str,
        conversation_id: str = "skeleton",
        before_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Messages strictly older than the cursor message, oldest-first.

        Stable snapshot boundary for "load earlier" paging: the cursor
        is the (created_at, id) pair of the oldest message the client
        already shows. Message ids are random hex and carry no
        ordering, so the id alone cannot be the boundary — but the
        pair is unique (ids are unique) and immune to new arrivals:
        appended messages have newer timestamps and can never shift,
        duplicate, or skip rows in earlier pages. An unknown cursor —
        including one from another user or conversation, since the
        lookup is scoped — fails closed to an empty page.
        """
        limit = max(1, min(int(limit or 50), 200))
        if not before_id:
            return []
        with self._lock:
            cur = self._conn.execute(
                "SELECT created_at, id FROM messages WHERE user_id = ? "
                "AND conversation_id = ? AND id = ?",
                (user_id, conversation_id, before_id),
            ).fetchone()
            if cur is None:
                return []
            rows = self._conn.execute(
                "SELECT id, user_id, conversation_id, archetype_id, role, body, "
                "mode, context_json, created_at FROM messages "
                "WHERE user_id = ? AND conversation_id = ? "
                "AND (created_at < ? OR (created_at = ? AND id < ?)) "
                "ORDER BY created_at DESC, id DESC LIMIT ?",
                (
                    user_id,
                    conversation_id,
                    cur["created_at"],
                    cur["created_at"],
                    cur["id"],
                    limit,
                ),
            ).fetchall()
        return _message_dicts(rows)

    def message_ids(self, user_id: str, conversation_id: str) -> list[str]:
        """Live message ids in original order. Read-only, ids only."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM messages WHERE user_id = ? AND conversation_id = ? "
                "ORDER BY created_at ASC, id ASC",
                (user_id, conversation_id),
            ).fetchall()
        return [r["id"] for r in rows]

    def clear_conversation(self, user_id: str, conversation_id: str) -> None:
        """Remove a conversation's messages and derived per-conversation
        state (thread summaries, cached suggestion runs). The conversation
        row itself stays. Used by the meeting restart: the prior run's
        FULL transcript is archived and verified complete in the
        meeting store before this runs; only then is the live
        conversation cleared. Clearing deletes EVERY message row for
        the conversation, including any row not in the archive — never
        call this unless completeness has been verified.

        Capability C S1: pending invitations for the conversation are
        EXPIRED, not deleted — history is preserved, but nothing the
        clear leaves behind stays actionable. Accepted rows are already
        history and stay as-is."""
        with self._lock:
            self._conn.execute(
                "DELETE FROM messages WHERE user_id = ? AND conversation_id = ?",
                (user_id, conversation_id),
            )
            self._conn.execute(
                "DELETE FROM thread_state WHERE user_id = ? AND conversation_id = ?",
                (user_id, conversation_id),
            )
            self._conn.execute(
                "DELETE FROM suggestion_runs WHERE user_id = ? AND conversation_id = ?",
                (user_id, conversation_id),
            )
            self._conn.execute(
                "UPDATE invitations SET status = 'expired' "
                "WHERE user_id = ? AND conversation_id = ? AND status = 'pending'",
                (user_id, conversation_id),
            )
            self._conn.commit()

    def latest_message_id(self, user_id: str, conversation_id: str = "skeleton") -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM messages WHERE user_id = ? AND conversation_id = ? "
                "ORDER BY created_at DESC, id DESC LIMIT 1",
                (user_id, conversation_id),
            ).fetchone()
        return row["id"] if row else None

    # -- thread state -----------------------------------------------------------

    def get_thread_state(
        self, user_id: str, conversation_id: str, archetype_id: str
    ) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT user_id, conversation_id, archetype_id, summary, "
                "last_active, messages_since_summary FROM thread_state "
                "WHERE user_id = ? AND conversation_id = ? AND archetype_id = ?",
                (user_id, conversation_id, archetype_id),
            ).fetchone()
        if row is None:
            return {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "archetype_id": archetype_id,
                "summary": "",
                "last_active": "",
                "messages_since_summary": 0,
            }
        return dict(row)

    def update_thread_state(
        self,
        user_id: str,
        conversation_id: str,
        archetype_id: str,
        *,
        summary: str | None = None,
        increment: int = 0,
        reset_counter: bool = False,
    ) -> dict[str, Any]:
        """Touch a seat's thread: optionally replace the summary, bump the
        since-summary counter, or reset it (after a summarization pass)."""
        now = _utcnow()
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO thread_state "
                "(user_id, conversation_id, archetype_id, summary, last_active, "
                "messages_since_summary) VALUES (?, ?, ?, '', ?, 0)",
                (user_id, conversation_id, archetype_id, now),
            )
            if summary is not None:
                self._conn.execute(
                    "UPDATE thread_state SET summary = ? "
                    "WHERE user_id = ? AND conversation_id = ? AND archetype_id = ?",
                    (summary, user_id, conversation_id, archetype_id),
                )
            if increment:
                self._conn.execute(
                    "UPDATE thread_state SET messages_since_summary = "
                    "messages_since_summary + ? "
                    "WHERE user_id = ? AND conversation_id = ? AND archetype_id = ?",
                    (increment, user_id, conversation_id, archetype_id),
                )
            if reset_counter:
                self._conn.execute(
                    "UPDATE thread_state SET messages_since_summary = 0 "
                    "WHERE user_id = ? AND conversation_id = ? AND archetype_id = ?",
                    (user_id, conversation_id, archetype_id),
                )
            self._conn.execute(
                "UPDATE thread_state SET last_active = ? "
                "WHERE user_id = ? AND conversation_id = ? AND archetype_id = ?",
                (now, user_id, conversation_id, archetype_id),
            )
            self._conn.commit()
        return self.get_thread_state(user_id, conversation_id, archetype_id)

    # -- suggestion runs (cache) --------------------------------------------------

    def get_suggestion_run(
        self, user_id: str, conversation_id: str = "skeleton"
    ) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT user_id, conversation_id, up_to_message_id, "
                "suggestions_json, created_at FROM suggestion_runs "
                "WHERE user_id = ? AND conversation_id = ?",
                (user_id, conversation_id),
            ).fetchone()
        if row is None:
            return None
        try:
            suggestions = json.loads(row["suggestions_json"] or "{}")
        except Exception:
            suggestions = {}
        return {
            "user_id": row["user_id"],
            "conversation_id": row["conversation_id"],
            "up_to_message_id": row["up_to_message_id"],
            "suggestions": suggestions,
            "created_at": row["created_at"],
        }

    def save_suggestion_run(
        self,
        user_id: str,
        conversation_id: str,
        up_to_message_id: str,
        suggestions: dict[str, Any],
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO suggestion_runs "
                "(user_id, conversation_id, up_to_message_id, suggestions_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    user_id,
                    conversation_id,
                    up_to_message_id,
                    json.dumps(suggestions, ensure_ascii=True),
                    _utcnow(),
                ),
            )
            self._conn.commit()

    # -- invitations (Capability C S1) ---------------------------------------

    def create_or_refresh_invitation(
        self,
        user_id: str,
        conversation_id: str,
        seat: str,
        reason: str,
        evidence: dict[str, Any] | None = None,
        observation_ids: list[str] | None = None,
        ttl_days: int = INVITATION_TTL_DAYS,
    ) -> dict[str, Any]:
        """Create or refresh the ONE pending invitation for a triple.

        Refresh-not-stack: if a pending, unexpired row already exists
        for (user_id, conversation_id, seat), it is updated in place
        (same id; new reason / evidence / observation ids; expiry
        extended to now + TTL) and returned. Expired rows are history,
        never revived — a new row is created instead. One pending
        invitation per (conversation, seat) is the invariant; callers
        never stack rows.

        `evidence` is the completed exchange that justified the
        invitation (verbatim user message, responding seat, verbatim
        assistant reply, limited context). The record must carry it:
        selection comes from exchanges, not only observations, so
        observation_ids may be empty. `reason` is the selection's
        short reason, carried as that selection's reading — S5 renders
        it labeled as such; it is never presented as fact.

        The store validates shape only (non-empty user, conversation,
        seat, reason); seat vocabulary is the selection contract's
        job (S2), not this store's. Raises ValueError on empty input.
        """
        user_id = (user_id or "").strip()
        conversation_id = (conversation_id or "").strip()
        seat = (seat or "").strip().lower()
        reason = (reason or "").strip()
        if not user_id or not conversation_id or not seat or not reason:
            raise ValueError("invitation requires user, conversation, seat, reason")
        now = _utcnow()
        expires = (
            datetime.now(timezone.utc) + timedelta(days=ttl_days)
        ).isoformat()
        evidence_json = json.dumps(evidence or {}, ensure_ascii=True)
        observation_json = json.dumps(list(observation_ids or []), ensure_ascii=True)
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM invitations WHERE user_id = ? AND conversation_id = ? "
                "AND seat = ? AND status = 'pending' AND expires_at > ? "
                "ORDER BY created_at DESC, id DESC LIMIT 1",
                (user_id, conversation_id, seat, now),
            ).fetchone()
            if row is not None:
                self._conn.execute(
                    "UPDATE invitations SET reason = ?, evidence_json = ?, "
                    "observation_ids = ?, expires_at = ? WHERE id = ? AND user_id = ?",
                    (reason, evidence_json, observation_json, expires, row["id"], user_id),
                )
                self._conn.commit()
                inv_id = row["id"]
            else:
                inv_id = uuid.uuid4().hex
                self._conn.execute(
                    "INSERT INTO invitations (id, user_id, conversation_id, seat, "
                    "observation_ids, reason, evidence_json, status, created_at, "
                    "expires_at, accepted_message_id) VALUES (?, ?, ?, ?, ?, ?, ?, "
                    "'pending', ?, ?, NULL)",
                    (
                        inv_id,
                        user_id,
                        conversation_id,
                        seat,
                        observation_json,
                        reason,
                        evidence_json,
                        now,
                        expires,
                    ),
                )
                self._conn.commit()
        # Outside the lock: get_invitation takes the same lock (the
        # file's established pattern — never call it while holding it).
        return self.get_invitation(user_id, inv_id)  # type: ignore[return-value]

    def list_pending_invitations(
        self, user_id: str, conversation_id: str | None = None, now: str | None = None
    ) -> list[dict[str, Any]]:
        """Pending invitations for one user: status pending AND unexpired.

        Strictly per-user: another user's rows can never match, and a
        foreign conversation_id simply yields nothing. The time filter
        is the semantic gate (a past-expiry row is not pending even
        before a sweep materializes its status); expire_due_* is
        bookkeeping, not the gate.
        """
        now = now or _utcnow()
        with self._lock:
            if conversation_id:
                rows = self._conn.execute(
                    "SELECT id, user_id, conversation_id, seat, observation_ids, "
                    "reason, evidence_json, status, created_at, expires_at, "
                    "accepted_message_id FROM invitations WHERE user_id = ? "
                    "AND conversation_id = ? AND status = 'pending' AND expires_at > ? "
                    "ORDER BY created_at ASC, id ASC",
                    (user_id, conversation_id, now),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT id, user_id, conversation_id, seat, observation_ids, "
                    "reason, evidence_json, status, created_at, expires_at, "
                    "accepted_message_id FROM invitations WHERE user_id = ? "
                    "AND status = 'pending' AND expires_at > ? "
                    "ORDER BY created_at ASC, id ASC",
                    (user_id, now),
                ).fetchall()
        return [_invitation_dict(r) for r in rows]

    def get_invitation(
        self, user_id: str, invitation_id: str
    ) -> dict[str, Any] | None:
        """One invitation, strictly per-user. A foreign id returns None,
        indistinguishable from a missing one — the same fail-closed
        pattern as get_message, so callers cannot probe another
        user's invitations."""
        with self._lock:
            row = self._conn.execute(
                "SELECT id, user_id, conversation_id, seat, observation_ids, "
                "reason, evidence_json, status, created_at, expires_at, "
                "accepted_message_id FROM invitations "
                "WHERE user_id = ? AND id = ?",
                (user_id, invitation_id),
            ).fetchone()
        if row is None:
            return None
        return _invitation_dict(row)

    def accept_invitation(
        self, user_id: str, invitation_id: str, message_id: str
    ) -> dict[str, Any] | None:
        """Pending + unexpired → accepted, recorded against message_id.

        The ONLY accept semantics: a sent turn to the invited seat
        (service.turn wires this). Tap/opening never calls this —
        opening is a UI action, not a state transition (verdict:
        Pending → Opened → Joined; open-and-leave stays pending).
        Returns None, with no state change, for missing, foreign,
        already-accepted, or expired rows.
        """
        now = _utcnow()
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM invitations WHERE user_id = ? AND id = ? "
                "AND status = 'pending' AND expires_at > ?",
                (user_id, invitation_id, now),
            ).fetchone()
            if row is None:
                return None
            self._conn.execute(
                "UPDATE invitations SET status = 'accepted', "
                "accepted_message_id = ? WHERE id = ? AND user_id = ?",
                (message_id, invitation_id, user_id),
            )
            self._conn.commit()
        return self.get_invitation(user_id, invitation_id)

    def accept_pending_for_seat(
        self, user_id: str, conversation_id: str, seat: str, message_id: str
    ) -> list[dict[str, Any]]:
        """Accept every pending, unexpired invitation for one triple.

        Normally at most one (refresh-not-stack invariant); accept-all
        is defensive, not a second path. Called by the turn path after
        a completed turn — never by tap/open. Returns the accepted rows
        (empty when nothing was pending).

        Atomicity: the UPDATEs and the commit are one unit. On any
        failure the transaction is rolled back before re-raising, so a
        commit failure can never leave a half-accepted row visible to
        later same-connection reads (which would mistake staged,
        uncommitted UPDATEs for a real acceptance). The turn-path guard
        logs the re-raised failure; the invitation stays pending.
        """
        now = _utcnow()
        seat = (seat or "").strip().lower()
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM invitations WHERE user_id = ? AND conversation_id = ? "
                "AND seat = ? AND status = 'pending' AND expires_at > ?",
                (user_id, conversation_id, seat, now),
            ).fetchall()
            try:
                for r in rows:
                    self._conn.execute(
                        "UPDATE invitations SET status = 'accepted', "
                        "accepted_message_id = ? WHERE id = ? AND user_id = ?",
                        (message_id, r["id"], user_id),
                    )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            ids = [r["id"] for r in rows]
        return [self.get_invitation(user_id, i) for i in ids]  # type: ignore[misc]

    def expire_due_invitations(self, user_id: str, now: str | None = None) -> int:
        """Materialize expiry: pending rows with expires_at <= now → expired.

        Bookkeeping only — list_pending already excludes past-expiry
        rows. Returns the number of rows transitioned.
        """
        now = now or _utcnow()
        with self._lock:
            cur = self._conn.execute(
                "UPDATE invitations SET status = 'expired' WHERE user_id = ? "
                "AND status = 'pending' AND expires_at <= ?",
                (user_id, now),
            )
            self._conn.commit()
            return cur.rowcount if cur.rowcount is not None else 0

    # -- lightning-round parking + reserved markers (Firebrand S1) --------
    #
    # The shared mechanisms the Firebrand design §3.4/OQ5 and OQ7 rule:
    # parked-ids (skip until the next round) and reserved markers
    # ("don't remind me about this" — a durable snooze or never).
    # Both live here beside the invitation rows, per the design's
    # recommendation, so the Weaver round reuses them without a second
    # store. The two tables scope differently, deliberately:
    #   * parked: (user, conversation, ROUND kind) — each round's
    #     parked set is its own ('firebrand' vs 'weaver'), and a park
    #     lasts only until the next round in that conversation, when
    #     the round start clears it.
    #   * reserved: (user, ITEM kind) — the marker attaches to the
    #     item itself ('task_proposal'), so a reserved item never
    #     appears in any round that could present it, until its snooze
    #     expires. snooze_until NULL means never.
    # Expiry is a read-time gate (same pattern as
    # list_pending_invitations): a past-expiry row is not active even
    # before any sweep materializes it. No sweep exists in v1.

    def park_round_item(
        self, user_id: str, conversation_id: str, kind: str, item_id: str
    ) -> bool:
        """Park one item for the rest of this round (Firebrand OQ5).

        A park changes no underlying state — the proposal stays
        pending — it only suppresses re-presentation until the next
        round clears it. Idempotent: re-parking returns False.
        """
        now = _utcnow()
        with self._lock:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO round_parked_ids "
                "(user_id, conversation_id, kind, item_id, parked_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, conversation_id, kind, item_id, now),
            )
            self._conn.commit()
            return (cur.rowcount or 0) > 0

    def list_parked_round_items(
        self, user_id: str, conversation_id: str, kind: str
    ) -> list[str]:
        """Parked item ids for one (user, conversation, round kind)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT item_id FROM round_parked_ids WHERE user_id = ? "
                "AND conversation_id = ? AND kind = ? "
                "ORDER BY parked_at ASC, item_id ASC",
                (user_id, conversation_id, kind),
            ).fetchall()
        return [r["item_id"] for r in rows]

    def clear_parked_round_items(
        self, user_id: str, conversation_id: str, kind: str
    ) -> int:
        """Clear one round's parked set — called at round start.

        A park lasts until the next round, so invoking a new round
        lifts every park in that conversation for that round kind.
        Returns the number of rows cleared.
        """
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM round_parked_ids WHERE user_id = ? "
                "AND conversation_id = ? AND kind = ?",
                (user_id, conversation_id, kind),
            )
            self._conn.commit()
            return cur.rowcount if cur.rowcount is not None else 0

    def reserve_round_item(
        self,
        user_id: str,
        kind: str,
        item_id: str,
        snooze_until: str | None = None,
    ) -> dict[str, Any]:
        """Mark one item "don't remind me about this" (Firebrand OQ7).

        Durable, not round-scoped: ``snooze_until`` is an ISO
        timestamp (the item returns to rounds after it) or None
        (never — the item never appears again). Re-reserving the
        same item replaces its snooze. Returns the stored marker.
        """
        now = _utcnow()
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO round_reserved_ids "
                "(user_id, kind, item_id, reserved_at, snooze_until) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, kind, item_id, now, snooze_until),
            )
            self._conn.commit()
        return {
            "user_id": user_id,
            "kind": kind,
            "item_id": item_id,
            "reserved_at": now,
            "snooze_until": snooze_until,
        }

    def list_active_reserved_round_items(
        self, user_id: str, kind: str, now: str | None = None
    ) -> list[str]:
        """Reserved item ids whose marker is still active.

        Never-reserved (snooze_until NULL) and not-yet-expired
        snoozes are active; an expired snooze is not, so the item
        returns to rounds. Read-time gate — no sweep.
        """
        now = now or _utcnow()
        with self._lock:
            rows = self._conn.execute(
                "SELECT item_id FROM round_reserved_ids WHERE user_id = ? "
                "AND kind = ? AND (snooze_until IS NULL OR snooze_until > ?) "
                "ORDER BY reserved_at ASC, item_id ASC",
                (user_id, kind, now),
            ).fetchall()
        return [r["item_id"] for r in rows]

    def get_reserved_round_item(
        self, user_id: str, kind: str, item_id: str, now: str | None = None
    ) -> dict[str, Any] | None:
        """One active reserved marker, or None (never reserved, or
        its snooze expired). The card's hydration read uses this to
        show the snooze date ("back after …") vs never.
        """
        now = now or _utcnow()
        with self._lock:
            row = self._conn.execute(
                "SELECT user_id, kind, item_id, reserved_at, snooze_until "
                "FROM round_reserved_ids WHERE user_id = ? AND kind = ? "
                "AND item_id = ? AND (snooze_until IS NULL OR snooze_until > ?)",
                (user_id, kind, item_id, now),
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def unreserve_round_item(self, user_id: str, kind: str, item_id: str) -> bool:
        """Lift a reserved marker (the card's Undo). Returns True if
        a marker was removed."""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM round_reserved_ids WHERE user_id = ? "
                "AND kind = ? AND item_id = ?",
                (user_id, kind, item_id),
            )
            self._conn.commit()
            return (cur.rowcount or 0) > 0

    # -- Weaver rapid fire S1: decline cooldown (brief §8.4) -----------
    # One timestamp per user, beside the parked-ids record. A decline
    # (or an ignored offer — the user was offered the mode and did not
    # take it) writes declined_at = now; while now < declined_at +
    # 24h no proactive offer is invited in any conversation. The
    # cooldown is a read-time gate, never a sweep.

    def set_round_declined_at(self, user_id: str, declined_at: str | None = None) -> None:
        """Record that the user declined (or ignored) a round offer."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO round_decline_cooldowns (user_id, declined_at) "
                "VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE "
                "SET declined_at = excluded.declined_at",
                (user_id, declined_at or _utcnow()),
            )
            self._conn.commit()

    def get_round_declined_at(self, user_id: str) -> str | None:
        """The last decline timestamp for the user, or None."""
        with self._lock:
            row = self._conn.execute(
                "SELECT declined_at FROM round_decline_cooldowns WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return row["declined_at"] if row is not None else None

    def invalidate_invitation(
        self, user_id: str, invitation_id: str
    ) -> dict[str, Any] | None:
        """Evidence-specific invalidation hook (verdict Q2): a pending
        invitation whose evidence is demonstrably superseded or
        addressed expires early. This is EXPIRY, not a new status —
        v1 has only pending | accepted | expired — and it must never
        be driven by a topic change or by the user talking to another
        seat (neither is evidence of resolution). Returns None for
        missing, foreign, or non-pending rows.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM invitations WHERE user_id = ? AND id = ? "
                "AND status = 'pending'",
                (user_id, invitation_id),
            ).fetchone()
            if row is None:
                return None
            self._conn.execute(
                "UPDATE invitations SET status = 'expired' "
                "WHERE id = ? AND user_id = ?",
                (invitation_id, user_id),
            )
            self._conn.commit()
        return self.get_invitation(user_id, invitation_id)

    # -- Weaver strand interviews (rev2) -------------------------------------
    #
    # One ordinary Weaver (conductor) Talk thread per strand. The mapping
    # is the ONLY new store the strand design requires: one row per
    # (user_id, strand_key) with a conversation_id. Every read and write
    # here is per-user; a foreign strand_key or conversation_id can
    # never resolve. Strand keys are the design keys (heart, hands,
    # logic, voice, ear, compass, eye) — validated, never trusted from
    # the client (see local_ai/strand_interviews/keys.py).

    def get_strand_thread(
        self, user_id: str, strand_key: str
    ) -> dict[str, Any] | None:
        """Mapping row for (user, strand), or None when never resolved."""
        from local_ai.strand_interviews.keys import validate_strand_key

        key = validate_strand_key(strand_key)
        row = self._conn.execute(
            "SELECT user_id, strand_key, conversation_id, created_at, updated_at "
            "FROM strand_threads WHERE user_id = ? AND strand_key = ?",
            (user_id, key),
        ).fetchone()
        return dict(row) if row is not None else None

    def get_strand_key_for_conversation(
        self, user_id: str, conversation_id: str
    ) -> str | None:
        """Reverse lookup: which strand (if any) a conversation belongs to."""
        row = self._conn.execute(
            "SELECT strand_key FROM strand_threads "
            "WHERE user_id = ? AND conversation_id = ?",
            (user_id, conversation_id),
        ).fetchone()
        return str(row["strand_key"]) if row is not None else None

    def resolve_strand_thread(
        self, user_id: str, strand_key: str
    ) -> dict[str, Any]:
        """Get-or-create the strand thread for (user, strand).

        Returns the mapping row plus ``is_fresh`` (True when the thread
        has no messages yet). The mapped conversation row is validated:
        if it is missing (clear keeps the row, so this should not
        happen — but a row deleted by any other path must never leave
        the mapping pointing at a missing thread), a fresh thread is
        created and the mapping is updated. No model call happens here:
        resolution is storage only; the opening orientation is pattern
        copy rendered by the client.
        """
        from local_ai.strand_interviews.keys import validate_strand_key

        key = validate_strand_key(strand_key)
        now = _utcnow()
        with self._lock:
            row = self._conn.execute(
                "SELECT user_id, strand_key, conversation_id, created_at, updated_at "
                "FROM strand_threads WHERE user_id = ? AND strand_key = ?",
                (user_id, key),
            ).fetchone()
            if row is not None:
                conversation_id = str(row["conversation_id"])
                exists = self._conn.execute(
                    "SELECT 1 FROM conversations "
                    "WHERE user_id = ? AND conversation_id = ?",
                    (user_id, conversation_id),
                ).fetchone()
                if exists is None:
                    conversation_id = f"talk-{uuid.uuid4().hex}"
                    self._conn.execute(
                        "UPDATE strand_threads SET conversation_id = ?, updated_at = ? "
                        "WHERE user_id = ? AND strand_key = ?",
                        (conversation_id, now, user_id, key),
                    )
                    self._conn.execute(
                        "INSERT OR IGNORE INTO conversations "
                        "(user_id, conversation_id, kind, created_at, updated_at) "
                        "VALUES (?, ?, 'talk', ?, ?)",
                        (user_id, conversation_id, now, now),
                    )
                    self._conn.commit()
                    return {
                        "user_id": user_id,
                        "strand_key": key,
                        "conversation_id": conversation_id,
                        "is_fresh": True,
                    }
                is_fresh = (
                    self._conn.execute(
                        "SELECT COUNT(*) AS n FROM messages "
                        "WHERE user_id = ? AND conversation_id = ?",
                        (user_id, conversation_id),
                    ).fetchone()["n"]
                    == 0
                )
                return {
                    "user_id": user_id,
                    "strand_key": key,
                    "conversation_id": conversation_id,
                    "is_fresh": bool(is_fresh),
                }
            conversation_id = f"talk-{uuid.uuid4().hex}"
            self._conn.execute(
                "INSERT INTO strand_threads "
                "(user_id, strand_key, conversation_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, key, conversation_id, now, now),
            )
            self._conn.execute(
                "INSERT OR IGNORE INTO conversations "
                "(user_id, conversation_id, kind, created_at, updated_at) "
                "VALUES (?, ?, 'talk', ?, ?)",
                (user_id, conversation_id, now, now),
            )
            self._conn.commit()
            return {
                "user_id": user_id,
                "strand_key": key,
                "conversation_id": conversation_id,
                "is_fresh": True,
            }

    # -- strand topic boundaries (rev2 C2) ------------------------------------
    #
    # "Never ask me about this" is the ONLY decline level that
    # prohibits future questions on a topic, and it requires the user's
    # explicit boundary-setting words. Boundaries persist across
    # sessions; ordinary declines are never recorded here.

    def add_topic_boundary(
        self,
        user_id: str,
        strand_key: str,
        topic: str,
        created_by_message_id: str | None = None,
    ) -> dict[str, Any]:
        """Record an explicit topic boundary (idempotent by normalized topic)."""
        from local_ai.strand_interviews.boundaries import normalize_topic
        from local_ai.strand_interviews.keys import validate_strand_key

        key = validate_strand_key(strand_key)
        display = (topic or "").strip().strip(" .!?,;:\"'()[]")
        if not display:
            raise ValueError("Topic is empty.")
        normalized = normalize_topic(display)
        now = _utcnow()
        with self._lock:
            existing = self._conn.execute(
                "SELECT id, user_id, strand_key, topic, topic_normalized, "
                "created_at, created_by_message_id FROM strand_topic_boundaries "
                "WHERE user_id = ? AND strand_key = ? AND topic_normalized = ?",
                (user_id, key, normalized),
            ).fetchone()
            if existing is not None:
                return dict(existing)
            boundary_id = f"stb-{uuid.uuid4().hex[:16]}"
            self._conn.execute(
                "INSERT INTO strand_topic_boundaries "
                "(id, user_id, strand_key, topic, topic_normalized, "
                "created_at, created_by_message_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    boundary_id,
                    user_id,
                    key,
                    display,
                    normalized,
                    now,
                    created_by_message_id,
                ),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT id, user_id, strand_key, topic, topic_normalized, "
                "created_at, created_by_message_id FROM strand_topic_boundaries "
                "WHERE id = ? AND user_id = ?",
                (boundary_id, user_id),
            ).fetchone()
        return dict(row)

    def list_topic_boundaries(
        self, user_id: str, strand_key: str
    ) -> list[dict[str, Any]]:
        """Active topic boundaries for (user, strand), oldest first."""
        from local_ai.strand_interviews.keys import validate_strand_key

        key = validate_strand_key(strand_key)
        rows = self._conn.execute(
            "SELECT id, user_id, strand_key, topic, topic_normalized, "
            "created_at, created_by_message_id FROM strand_topic_boundaries "
            "WHERE user_id = ? AND strand_key = ? ORDER BY created_at, id",
            (user_id, key),
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_topic_boundary(
        self, user_id: str, boundary_id: str
    ) -> bool:
        """Reopen a bounded topic. False for missing or foreign rows."""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM strand_topic_boundaries WHERE id = ? AND user_id = ?",
                (boundary_id, user_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    # -- strand sources (rev2 §7) ----------------------------------------------
    #
    # Durable source-to-interview linkage: a source is a pasted-text
    # excerpt (redacted at capture, stored here) or an ingest session
    # id (content lives in the presence-ingest store, redacted at
    # capture there). Per-thread, per-strand scoping: a Hands source
    # is never evidence in a Heart conversation. Uploaded content is
    # user DATA, never instructions.

    def add_strand_source(
        self,
        user_id: str,
        strand_key: str,
        conversation_id: str,
        kind: str,
        ref: str,
        label: str = "",
        excerpt_redacted: str = "",
        paste_full_text: str | None = None,
    ) -> dict[str, Any]:
        """Link a source to a strand thread. The caller must already
        have validated that the conversation is the caller's mapped
        thread for the strand, and that a file ``ref`` names an
        existing ingest session.

        Upload S1 §2.11 (U-2): when the source is a paste and
        ``paste_full_text`` (the FULL redacted text, uncapped) is
        given, the zlib-compressed text is stored in the same
        lock/transaction as the source row — the excerpt and the blob
        commit together or neither does. The 2000-char excerpt is
        unchanged.
        """
        from local_ai.strand_interviews.keys import validate_strand_key

        key = validate_strand_key(strand_key)
        kind = (kind or "").strip().lower()
        if kind not in ("paste", "file"):
            raise ValueError(f"Unknown strand source kind: {kind!r}")
        if not (ref or "").strip():
            raise ValueError("Source ref is empty.")
        now = _utcnow()
        source_id = f"sts-{uuid.uuid4().hex[:16]}"
        with self._lock:
            self._conn.execute(
                "INSERT INTO strand_sources "
                "(id, user_id, strand_key, conversation_id, kind, ref, "
                "label, excerpt_redacted, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    source_id,
                    user_id,
                    key,
                    conversation_id,
                    kind,
                    ref.strip(),
                    (label or "").strip(),
                    (excerpt_redacted or "").strip(),
                    now,
                ),
            )
            if kind == "paste" and paste_full_text is not None:
                import zlib

                self._store_paste_full_text_locked(
                    source_id,
                    zlib.compress(paste_full_text.encode("utf-8")),
                    "zlib",
                )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT id, user_id, strand_key, conversation_id, kind, ref, "
                "label, excerpt_redacted, created_at FROM strand_sources "
                "WHERE id = ? AND user_id = ?",
                (source_id, user_id),
            ).fetchone()
        return dict(row)

    def list_strand_sources(
        self, user_id: str, strand_key: str
    ) -> list[dict[str, Any]]:
        """Linked sources for (user, strand), oldest first."""
        from local_ai.strand_interviews.keys import validate_strand_key

        key = validate_strand_key(strand_key)
        rows = self._conn.execute(
            "SELECT id, user_id, strand_key, conversation_id, kind, ref, "
            "label, excerpt_redacted, created_at FROM strand_sources "
            "WHERE user_id = ? AND strand_key = ? ORDER BY created_at, id",
            (user_id, key),
        ).fetchall()
        return [dict(r) for r in rows]

    # -- upload rapid-fire S1 (§2, §4, §5) ------------------------------------
    #
    # Ten-table inventory (U-5): the nine tables above plus the VE
    # carrier (upload_outcome_creations, in the VE DB). Every method
    # is owner-scoped by the authenticated user id; a foreign id
    # returns nothing, never another user's records.

    def _store_paste_full_text_locked(
        self, source_id: str, blob: bytes, encoding: str
    ) -> None:
        """Write the compressed paste blob. Caller holds the lock
        (and, from add_strand_source, the same transaction as the
        source row). No commit here — the caller commits."""
        self._conn.execute(
            "UPDATE strand_sources SET paste_text_blob = ?, "
            "paste_text_encoding = ? WHERE id = ?",
            (blob, encoding, source_id),
        )

    def store_paste_full_text(
        self, source_id: str, blob: bytes, encoding: str = "zlib"
    ) -> bool:
        """Store a compressed paste blob for a source row. Returns
        False when the source does not exist (nothing written)."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE strand_sources SET paste_text_blob = ?, "
                "paste_text_encoding = ? WHERE id = ?",
                (blob, encoding, source_id),
            )
            self._conn.commit()
            return (cur.rowcount or 0) > 0

    def get_paste_full_text(self, source_id: str) -> str | None:
        """Decompress and return the stored redacted paste text, or
        None when absent (a paste captured before U-2 has excerpt
        only). Only the 'zlib' codec is read in S1; an unknown codec
        fails closed with None rather than a misread. Inactive
        pastes are never decompressed by callers — this method is
        the on-demand path (extraction, promotion, display)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT paste_text_blob, paste_text_encoding FROM "
                "strand_sources WHERE id = ?",
                (source_id,),
            ).fetchone()
        if row is None or row["paste_text_blob"] is None:
            return None
        encoding = (row["paste_text_encoding"] or "zlib").strip().lower()
        if encoding != "zlib":
            return None
        import zlib

        try:
            return zlib.decompress(bytes(row["paste_text_blob"])).decode("utf-8")
        except Exception:
            return None

    def get_strand_source(
        self, user_id: str, source_id: str
    ) -> dict[str, Any] | None:
        """One strand source row, owner-scoped. A foreign id reads
        as missing. The blob is NOT carried — use
        get_paste_full_text for the text."""
        with self._lock:
            row = self._conn.execute(
                "SELECT id, user_id, strand_key, conversation_id, kind, ref, "
                "label, excerpt_redacted, paste_text_encoding, created_at "
                "FROM strand_sources WHERE id = ? AND user_id = ?",
                (source_id, user_id),
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def list_sources_for_conversation(
        self, user_id: str, conversation_id: str
    ) -> list[dict[str, Any]]:
        """Sources linked to one conversation, NEWEST first (the
        round resolves its document newest-first)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, user_id, strand_key, conversation_id, kind, ref, "
                "label, excerpt_redacted, paste_text_encoding, created_at "
                "FROM strand_sources WHERE user_id = ? AND conversation_id = ? "
                "ORDER BY created_at DESC, id DESC",
                (user_id, conversation_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def strand_key_for_conversation(
        self, user_id: str, conversation_id: str
    ) -> str | None:
        """The strand key a conversation is the mapped thread for,
        or None (not a strand thread). Reverse of
        resolve_strand_thread."""
        with self._lock:
            row = self._conn.execute(
                "SELECT strand_key FROM strand_threads "
                "WHERE user_id = ? AND conversation_id = ?",
                (user_id, conversation_id),
            ).fetchone()
        if row is None:
            return None
        return str(row["strand_key"])

    # -- upload extraction jobs (§2.7–§2.8, §3) ------------------------------

    def create_upload_job(
        self, user_id: str, document_id: str, document_version: int
    ) -> dict[str, Any]:
        """Create a job row in state 'queued'. One job per
        (document, document_version, lens-set); the caller checks
        for a live job first (the extract route)."""
        job_id = uuid.uuid4().hex
        now = _utcnow()
        with self._lock:
            self._conn.execute(
                "INSERT INTO upload_extraction_jobs (job_id, user_id, "
                "document_id, document_version, state, worker_id, "
                "last_heartbeat_at, lease_until, first_interpretation_at, "
                "total_calls, completed_calls, failed_calls, failed_chunks, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, 'queued', NULL, "
                "NULL, NULL, NULL, 0, 0, 0, '[]', ?, ?)",
                (job_id, user_id, document_id, document_version, now, now),
            )
            self._conn.commit()
        row = self.get_upload_job(user_id, job_id)
        assert row is not None
        return row

    def get_upload_job(
        self, user_id: str, job_id: str
    ) -> dict[str, Any] | None:
        """One job row, owner-scoped. A foreign id reads as missing."""
        with self._lock:
            row = self._conn.execute(
                "SELECT job_id, user_id, document_id, document_version, state, "
                "worker_id, last_heartbeat_at, lease_until, "
                "first_interpretation_at, total_calls, completed_calls, "
                "failed_calls, failed_chunks, interpreted_chunks, created_at, updated_at "
                "FROM upload_extraction_jobs WHERE job_id = ? AND user_id = ?",
                (job_id, user_id),
            ).fetchone()
        if row is None:
            return None
        return _upload_job_dict(row)

    def latest_upload_job(
        self, user_id: str, document_id: str
    ) -> dict[str, Any] | None:
        """The newest job for a document (any state), or None."""
        with self._lock:
            row = self._conn.execute(
                "SELECT job_id, user_id, document_id, document_version, state, "
                "worker_id, last_heartbeat_at, lease_until, "
                "first_interpretation_at, total_calls, completed_calls, "
                "failed_calls, failed_chunks, interpreted_chunks, created_at, updated_at "
                "FROM upload_extraction_jobs WHERE user_id = ? AND document_id = ? "
                "ORDER BY created_at DESC, job_id DESC LIMIT 1",
                (user_id, document_id),
            ).fetchone()
        if row is None:
            return None
        return _upload_job_dict(row)

    def list_upload_jobs(
        self, user_id: str, document_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Jobs for a user (optionally one document), newest first."""
        with self._lock:
            if document_id is not None:
                rows = self._conn.execute(
                    "SELECT job_id, user_id, document_id, document_version, state, "
                    "worker_id, last_heartbeat_at, lease_until, "
                    "first_interpretation_at, total_calls, completed_calls, "
                    "failed_calls, failed_chunks, interpreted_chunks, created_at, updated_at "
                    "FROM upload_extraction_jobs WHERE user_id = ? AND document_id = ? "
                    "ORDER BY created_at DESC, job_id DESC",
                    (user_id, document_id),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT job_id, user_id, document_id, document_version, state, "
                    "worker_id, last_heartbeat_at, lease_until, "
                    "first_interpretation_at, total_calls, completed_calls, "
                    "failed_calls, failed_chunks, interpreted_chunks, created_at, updated_at "
                    "FROM upload_extraction_jobs WHERE user_id = ? "
                    "ORDER BY created_at DESC, job_id DESC",
                    (user_id,),
                ).fetchall()
        return [_upload_job_dict(r) for r in rows]

    def claim_upload_job(
        self, job_id: str, worker_id: str, now: str, lease_until: str
    ) -> bool:
        """Atomic claim (§3.4, C1a record_flip_attempt pattern):
        one UPDATE whose WHERE refuses anything but 'queued'.
        Rowcount 1 → claimed; 0 → another worker holds it (or it
        is not queued), and the caller does nothing."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE upload_extraction_jobs SET state = 'running', "
                "worker_id = ?, last_heartbeat_at = ?, lease_until = ?, "
                "updated_at = ? WHERE job_id = ? AND state = 'queued'",
                (worker_id, now, lease_until, now, job_id),
            )
            self._conn.commit()
            return (cur.rowcount or 0) == 1

    def heartbeat_upload_job(
        self, job_id: str, now: str, lease_until: str
    ) -> bool:
        """Renew a running job's heartbeat + lease (after each
        completed call). False when the job is not running."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE upload_extraction_jobs SET last_heartbeat_at = ?, "
                "lease_until = ?, updated_at = ? "
                "WHERE job_id = ? AND state = 'running'",
                (now, lease_until, now, job_id),
            )
            self._conn.commit()
            return (cur.rowcount or 0) == 1

    def set_upload_job_state(
        self,
        job_id: str,
        state: str,
        *,
        first_interpretation_at: str | None = None,
        total_calls: int | None = None,
        completed_calls: int | None = None,
        failed_calls: int | None = None,
        failed_chunks: list[int] | None = None,
        interpreted_chunks: list[str] | None = None,
    ) -> bool:
        """Set a job's state (+ counters). The worker's terminal
        write and the reconciler's interrupt write both land here.
        ``first_interpretation_at`` is set once, by the worker, and
        is never overwritten by a later call (pass None to leave it).
        ``interpreted_chunks`` (amendment A1) is the job's coverage
        record — the chunk ids whose rows an interpretation call has
        covered; the offer's coverage line reads it.
        """
        now = _utcnow()
        sets = ["state = ?", "updated_at = ?"]
        args: list[Any] = [state, now]
        if first_interpretation_at is not None:
            sets.append("first_interpretation_at = ?")
            args.append(first_interpretation_at)
        if total_calls is not None:
            sets.append("total_calls = ?")
            args.append(total_calls)
        if completed_calls is not None:
            sets.append("completed_calls = ?")
            args.append(completed_calls)
        if failed_calls is not None:
            sets.append("failed_calls = ?")
            args.append(failed_calls)
        if failed_chunks is not None:
            sets.append("failed_chunks = ?")
            args.append(json.dumps([int(c) for c in failed_chunks]))
        if interpreted_chunks is not None:
            sets.append("interpreted_chunks = ?")
            args.append(json.dumps([str(c) for c in interpreted_chunks]))
        args.append(job_id)
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE upload_extraction_jobs SET {', '.join(sets)} "
                "WHERE job_id = ?",
                args,
            )
            self._conn.commit()
            return (cur.rowcount or 0) == 1

    def start_upload_job_call(
        self, job_id: str, chunk_index: int | None, call_kind: str
    ) -> dict[str, Any]:
        """Write a 'started' call row BEFORE the model call (§2.8).
        A crash between the call and the commit leaves it 'started'
        with a stale heartbeat — never presumed complete."""
        call_id = uuid.uuid4().hex
        now = _utcnow()
        with self._lock:
            self._conn.execute(
                "INSERT INTO upload_extraction_job_calls (call_id, job_id, "
                "chunk_index, call_kind, state, code, started_at, ended_at, "
                "duration_ms, rows_written) VALUES (?, ?, ?, ?, 'started', "
                "NULL, ?, NULL, NULL, 0)",
                (call_id, job_id, chunk_index, call_kind, now),
            )
            self._conn.commit()
        return {
            "call_id": call_id,
            "job_id": job_id,
            "chunk_index": chunk_index,
            "call_kind": call_kind,
            "state": "started",
            "code": None,
            "started_at": now,
            "ended_at": None,
            "duration_ms": None,
            "rows_written": 0,
        }

    def complete_upload_call(
        self,
        call_id: str,
        *,
        state: str,
        code: str | None = None,
        rows_written: int = 0,
    ) -> bool:
        """Complete a call row: ended_at + duration_ms from
        started_at, the wash-contract failure code on failure.
        Duration is the per-call latency record (P2)."""
        now = _utcnow()
        with self._lock:
            row = self._conn.execute(
                "SELECT started_at FROM upload_extraction_job_calls "
                "WHERE call_id = ?",
                (call_id,),
            ).fetchone()
            if row is None:
                return False
            started = _parse_upload_iso(row["started_at"])
            ended = _parse_upload_iso(now)
            duration_ms = None
            if started is not None and ended is not None:
                duration_ms = int((ended - started).total_seconds() * 1000)
            cur = self._conn.execute(
                "UPDATE upload_extraction_job_calls SET state = ?, code = ?, "
                "ended_at = ?, duration_ms = ?, rows_written = ? "
                "WHERE call_id = ?",
                (state, code, now, duration_ms, rows_written, call_id),
            )
            self._conn.commit()
            return (cur.rowcount or 0) == 1

    def list_upload_job_calls(self, job_id: str) -> list[dict[str, Any]]:
        """Call rows for a job, oldest first. The source of truth
        per call; the job row's counters are derived summaries."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT call_id, job_id, chunk_index, call_kind, state, code, "
                "started_at, ended_at, duration_ms, rows_written "
                "FROM upload_extraction_job_calls WHERE job_id = ? "
                "ORDER BY started_at ASC, call_id ASC",
                (job_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_stale_upload_jobs(
        self, stale_before: str
    ) -> list[dict[str, Any]]:
        """Jobs the reconciler may interrupt (§3.3): 'running' (or
        'queued' with a stale claim) whose heartbeat is older than
        the stale threshold, or NULL with an age beyond it. Owner
        is carried on the row; the reconciler marks each in its own
        transaction."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT job_id, user_id, document_id, document_version, state, "
                "worker_id, last_heartbeat_at, lease_until, "
                "first_interpretation_at, total_calls, completed_calls, "
                "failed_calls, failed_chunks, interpreted_chunks, created_at, updated_at "
                "FROM upload_extraction_jobs WHERE state IN ('running', 'queued') "
                "AND (last_heartbeat_at IS NULL OR last_heartbeat_at < ?) "
                "AND created_at < ? ORDER BY created_at ASC",
                (stale_before, stale_before),
            ).fetchall()
        return [_upload_job_dict(r) for r in rows]

    # -- upload evidence + interpretation records (§4, §5) --------------------

    def save_upload_span(
        self,
        user_id: str,
        document_id: str,
        document_version: int,
        segment_id: str,
        span_text: str,
        redaction_stage: str,
        location: str,
    ) -> dict[str, Any]:
        """Write one verbatim span (§2.1). ``span_text`` is an exact
        substring of the stored source text at its recorded
        redaction stage. Identity is content + location (§5.1): a
        span with the same (span_hash, location) for this document
        version already on file is returned, never duplicated."""
        span_hash = _upload_span_hash(span_text, location)
        now = _utcnow()
        with self._lock:
            existing = self._conn.execute(
                "SELECT span_id, user_id, document_id, document_version, "
                "segment_id, span_text, redaction_stage, location, span_hash, status, "
                "created_at FROM upload_spans WHERE user_id = ? AND "
                "document_id = ? AND document_version = ? AND span_hash = ? "
                "AND location = ?",
                (user_id, document_id, document_version, span_hash, location),
            ).fetchone()
            if existing is not None:
                return dict(existing)
            span_id = uuid.uuid4().hex
            self._conn.execute(
                "INSERT INTO upload_spans (span_id, user_id, document_id, "
                "document_version, segment_id, span_text, redaction_stage, "
                "location, span_hash, status, created_at) VALUES (?, ?, ?, ?, ?, ?, "
                "?, ?, ?, ?, ?)",
                (
                    span_id,
                    user_id,
                    document_id,
                    document_version,
                    segment_id,
                    span_text,
                    redaction_stage,
                    location,
                    span_hash,
                    "current",
                    now,
                ),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT span_id, user_id, document_id, document_version, "
                "segment_id, span_text, redaction_stage, location, span_hash, status, "
                "created_at FROM upload_spans WHERE span_id = ?",
                (span_id,),
            ).fetchone()
        assert row is not None
        return dict(row)

    def get_upload_span(
        self, user_id: str, span_id: str
    ) -> dict[str, Any] | None:
        """One span row, owner-scoped."""
        with self._lock:
            row = self._conn.execute(
                "SELECT span_id, user_id, document_id, document_version, "
                "segment_id, span_text, redaction_stage, location, span_hash, status, "
                "created_at FROM upload_spans WHERE span_id = ? AND user_id = ?",
                (span_id, user_id),
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def list_upload_spans(
        self,
        user_id: str,
        document_id: str,
        document_version: int,
        segment_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Spans for a document version (optionally one segment),
        in location order."""
        with self._lock:
            if segment_id is not None:
                rows = self._conn.execute(
                    "SELECT span_id, user_id, document_id, document_version, "
                    "segment_id, span_text, redaction_stage, location, span_hash, status, "
                    "created_at FROM upload_spans WHERE user_id = ? AND "
                    "document_id = ? AND document_version = ? AND segment_id = ? "
                    "ORDER BY location, span_id",
                    (user_id, document_id, document_version, segment_id),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT span_id, user_id, document_id, document_version, "
                    "segment_id, span_text, redaction_stage, location, span_hash, status, "
                    "created_at FROM upload_spans WHERE user_id = ? AND "
                    "document_id = ? AND document_version = ? "
                    "ORDER BY location, span_id",
                    (user_id, document_id, document_version),
                ).fetchall()
        return [dict(r) for r in rows]

    def save_upload_observation(
        self,
        user_id: str,
        document_id: str,
        document_version: int,
        claim: str,
        span_ids: list[str],
    ) -> dict[str, Any]:
        """Write one derived claim (§2.2). The never-a-quotation
        rule is enforced here, deterministically (§4.3): a claim
        that is a substring of any cited span is REJECTED — the
        write raises ValueError, the row is not created, and the
        caller records a failed row write (not a model failure).
        Cited span ids must exist for this document version."""
        claim = (claim or "").strip()
        if not claim:
            raise ValueError("Observation claim is empty.")
        span_ids = list(span_ids or [])
        with self._lock:
            spans: list[dict[str, Any]] = []
            for sid in span_ids:
                row = self._conn.execute(
                    "SELECT span_id, span_text FROM upload_spans "
                    "WHERE span_id = ? AND user_id = ? AND document_id = ? "
                    "AND document_version = ?",
                    (sid, user_id, document_id, document_version),
                ).fetchone()
                if row is None:
                    raise ValueError(f"Unknown span id: {sid!r}")
                spans.append(dict(row))
            normalized_claim = _normalize_upload_text(claim)
            for span in spans:
                span_text = span["span_text"] or ""
                if claim and claim in span_text:
                    raise ValueError(
                        "Observation claim is a quotation of its cited span."
                    )
                if normalized_claim and normalized_claim in _normalize_upload_text(
                    span_text
                ):
                    raise ValueError(
                        "Observation claim is a quotation of its cited span."
                    )
            observation_id = uuid.uuid4().hex
            now = _utcnow()
            self._conn.execute(
                "INSERT INTO upload_observations (observation_id, user_id, "
                "document_id, document_version, claim, span_ids, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    observation_id,
                    user_id,
                    document_id,
                    document_version,
                    claim,
                    json.dumps(span_ids),
                    "current",
                    now,
                ),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT observation_id, user_id, document_id, document_version, "
                "claim, span_ids, status, created_at FROM upload_observations "
                "WHERE observation_id = ?",
                (observation_id,),
            ).fetchone()
        assert row is not None
        return _upload_observation_dict(row)

    def get_upload_observation(
        self, user_id: str, observation_id: str
    ) -> dict[str, Any] | None:
        """One observation row, owner-scoped."""
        with self._lock:
            row = self._conn.execute(
                "SELECT observation_id, user_id, document_id, document_version, "
                "claim, span_ids, status, created_at FROM upload_observations "
                "WHERE observation_id = ? AND user_id = ?",
                (observation_id, user_id),
            ).fetchone()
        if row is None:
            return None
        return _upload_observation_dict(row)

    def list_upload_observations(
        self, user_id: str, document_id: str, document_version: int
    ) -> list[dict[str, Any]]:
        """Observations for a document version, oldest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT observation_id, user_id, document_id, document_version, "
                "claim, span_ids, status, created_at FROM upload_observations "
                "WHERE user_id = ? AND document_id = ? AND document_version = ? "
                "ORDER BY created_at ASC, observation_id ASC",
                (user_id, document_id, document_version),
            ).fetchall()
        return [_upload_observation_dict(r) for r in rows]

    def save_upload_interpretation(
        self,
        user_id: str,
        document_id: str,
        document_version: int,
        lens: str,
        lens_kind: str,
        text: str,
        evidence_ids: list[dict[str, Any]] | None = None,
        observation_ids: list[str] | None = None,
        origin: str = "extracted",
        is_transformation: bool = False,
        proposed_outcome: str | None = None,
        promotion_turn_id: str | None = None,
        promotion_message_id: str | None = None,
        ungrounded: bool = False,
    ) -> dict[str, Any]:
        """Write one reading (§2.3). Deterministic checks, in order:

        - lens: a strand key validates as one; a seat validates as
          a stock archetype id. Anything else fails closed.
        - evidence roles coerce (same span in two roles collapses
          to the strongest: primary > supporting > contrast, §4.1).
        - a transformation requires >=1 cited span and carries
          observation_ids empty by design (A2, §4.4).
        - every cited span / observation id must exist for this
          document version.
        - proposed_outcome is None or project | task | idea.
        - auto-link (§5.3, extracted origin only): when the
          normalized text AND the supporting spans (by
          content+location) both match a ruled interpretation for
          the same (document, lens), the new row is written with
          status 'ruled' — it inherits the standing ruling and
          never re-enters the queue. Exactly one condition matching
          writes the uncertain marker on the row (amendment A3:
          ``uncertain_match`` JSON, {"prior_interpretation_id",
          "matched": "text" | "spans"}); the queue reads the column
          and falls back to derivation when it is NULL.
        """
        from local_ai.council.archetypes import get_archetype
        from local_ai.strand_interviews.keys import validate_strand_key

        lens_kind = (lens_kind or "").strip().lower()
        if lens_kind == "strand":
            lens = validate_strand_key(lens)
        elif lens_kind == "seat":
            if get_archetype((lens or "").strip().lower()) is None:
                raise ValueError(f"Unknown seat lens: {lens!r}")
            lens = (lens or "").strip().lower()
        else:
            raise ValueError(f"Unknown lens_kind: {lens_kind!r}")
        text = (text or "").strip()
        if not text:
            raise ValueError("Interpretation text is empty.")
        origin = (origin or "extracted").strip().lower()
        if origin not in ("extracted", "promoted"):
            raise ValueError(f"Unknown origin: {origin!r}")
        if proposed_outcome is not None and proposed_outcome not in (
            "project",
            "task",
            "idea",
        ):
            raise ValueError(f"Unknown proposed_outcome: {proposed_outcome!r}")
        coerced = _coerce_upload_evidence_roles(evidence_ids or [])
        if is_transformation:
            if not coerced:
                raise ValueError(
                    "A transformation requires at least one cited span."
                )
            observation_ids = []
        else:
            observation_ids = list(observation_ids or [])
        with self._lock:
            for entry in coerced:
                row = self._conn.execute(
                    "SELECT 1 FROM upload_spans WHERE span_id = ? AND user_id = ? "
                    "AND document_id = ? AND document_version = ?",
                    (entry["span_id"], user_id, document_id, document_version),
                ).fetchone()
                if row is None:
                    raise ValueError(f"Unknown span id: {entry['span_id']!r}")
            for oid in observation_ids:
                row = self._conn.execute(
                    "SELECT 1 FROM upload_observations WHERE observation_id = ? "
                    "AND user_id = ? AND document_id = ? AND document_version = ?",
                    (oid, user_id, document_id, document_version),
                ).fetchone()
                if row is None:
                    raise ValueError(f"Unknown observation id: {oid!r}")
            status = "pending"
            uncertain_match_json: str | None = None
            if origin == "extracted":
                supporting = self._supporting_span_keys_locked(
                    user_id, document_id, document_version, coerced
                )
                match = self._match_ruled_interpretation_locked(
                    user_id,
                    document_id,
                    lens,
                    _normalize_upload_text(text),
                    supporting,
                )
                if match is not None and match["kind"] == "exact":
                    status = "ruled"
                elif match is not None and match["kind"] in (
                    "text_only",
                    "spans_only",
                ):
                    # Amendment A3: the uncertain case gets its home
                    # on the row — a JSON marker naming the prior
                    # ruled interpretation and which condition
                    # matched. The queue reads it (via
                    # uncertain_match_for, which falls back to
                    # derivation when the column is NULL — e.g. the
                    # prior was ruled after this row was written).
                    uncertain_match_json = json.dumps(
                        {
                            "prior_interpretation_id": match.get(
                                "prior_interpretation_id"
                            ),
                            "matched": (
                                "text"
                                if match["kind"] == "text_only"
                                else "spans"
                            ),
                        }
                    )
            interpretation_id = uuid.uuid4().hex
            now = _utcnow()
            self._conn.execute(
                "INSERT INTO upload_interpretations (interpretation_id, "
                "user_id, document_id, document_version, lens, lens_kind, "
                "text, evidence_ids, observation_ids, origin, "
                "is_transformation, proposed_outcome, status, uncertain_match, "
                "promotion_turn_id, promotion_message_id, ungrounded, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                "?, ?, ?, ?, ?, ?)",
                (
                    interpretation_id,
                    user_id,
                    document_id,
                    document_version,
                    lens,
                    lens_kind,
                    text,
                    json.dumps(coerced),
                    json.dumps(observation_ids),
                    origin,
                    1 if is_transformation else 0,
                    proposed_outcome,
                    status,
                    uncertain_match_json,
                    promotion_turn_id,
                    promotion_message_id,
                    1 if ungrounded else 0,
                    now,
                ),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT interpretation_id, user_id, document_id, "
                "document_version, lens, lens_kind, text, evidence_ids, "
                "observation_ids, origin, is_transformation, "
                "proposed_outcome, status, uncertain_match, promotion_turn_id, "
                "promotion_message_id, ungrounded, created_at "
                "FROM upload_interpretations WHERE interpretation_id = ?",
                (interpretation_id,),
            ).fetchone()
        assert row is not None
        return _upload_interpretation_dict(row)

    def get_upload_interpretation(
        self, user_id: str, interpretation_id: str
    ) -> dict[str, Any] | None:
        """One interpretation row, owner-scoped."""
        with self._lock:
            row = self._conn.execute(
                "SELECT interpretation_id, user_id, document_id, "
                "document_version, lens, lens_kind, text, evidence_ids, "
                "observation_ids, origin, is_transformation, "
                "proposed_outcome, status, uncertain_match, promotion_turn_id, "
                "promotion_message_id, ungrounded, created_at "
                "FROM upload_interpretations WHERE interpretation_id = ? "
                "AND user_id = ?",
                (interpretation_id, user_id),
            ).fetchone()
        if row is None:
            return None
        return _upload_interpretation_dict(row)

    def list_upload_interpretations(
        self,
        user_id: str,
        document_id: str,
        document_version: int | None = None,
        lens: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Interpretations for a document (optionally one version /
        lens / status), oldest first."""
        query = (
            "SELECT interpretation_id, user_id, document_id, "
            "document_version, lens, lens_kind, text, evidence_ids, "
            "observation_ids, origin, is_transformation, "
            "proposed_outcome, status, uncertain_match, promotion_turn_id, "
            "promotion_message_id, ungrounded, created_at "
            "FROM upload_interpretations WHERE user_id = ? AND document_id = ?"
        )
        args: list[Any] = [user_id, document_id]
        if document_version is not None:
            query += " AND document_version = ?"
            args.append(document_version)
        if lens is not None:
            query += " AND lens = ?"
            args.append(lens)
        if status is not None:
            query += " AND status = ?"
            args.append(status)
        query += " ORDER BY created_at ASC, interpretation_id ASC"
        with self._lock:
            rows = self._conn.execute(query, args).fetchall()
        return [_upload_interpretation_dict(r) for r in rows]

    def pending_upload_interpretations(
        self, user_id: str, document_id: str, lens: str
    ) -> list[dict[str, Any]]:
        """Pending interpretations for (document, lens), oldest
        first — the round's raw queue input (§6.2). The queue
        composer applies parked / reserved / auto-link filters."""
        return self.list_upload_interpretations(
            user_id, document_id, lens=lens, status="pending"
        )

    def set_upload_interpretation_status(
        self, user_id: str, interpretation_id: str, status: str
    ) -> bool:
        """Flip an interpretation's status ('pending' | 'ruled' |
        'orphaned'). The ruling paths set 'ruled' when a verdict
        lands; re-extraction sets 'orphaned' on superseded rows
        (§5.4 — a status transition, never a content rewrite)."""
        if status not in ("pending", "ruled", "orphaned"):
            raise ValueError(f"Unknown interpretation status: {status!r}")
        with self._lock:
            cur = self._conn.execute(
                "UPDATE upload_interpretations SET status = ? "
                "WHERE interpretation_id = ? AND user_id = ?",
                (status, interpretation_id, user_id),
            )
            self._conn.commit()
            return (cur.rowcount or 0) == 1

    def match_ruled_interpretation(
        self,
        user_id: str,
        document_id: str,
        lens: str,
        normalized_text: str,
        supporting_keys: list[tuple[str, str]],
    ) -> dict[str, Any] | None:
        """Compare a reading against the ruled interpretations for
        the same (document, lens) (§5.3). Returns the best match:
        ``{"kind": "exact" | "text_only" | "spans_only",
        "prior_interpretation_id": ...}`` — 'exact' when both the
        normalized text and the supporting spans (by
        content+location) match; 'text_only' / 'spans_only' when
        exactly one matches (the UNCERTAIN case: no auto-link, the
        queue names it); None when neither matches. The most
        recently ruled interpretation wins each comparison."""
        with self._lock:
            return self._match_ruled_interpretation_locked(
                user_id, document_id, lens, normalized_text, supporting_keys
            )

    def _match_ruled_interpretation_locked(
        self,
        user_id: str,
        document_id: str,
        lens: str,
        normalized_text: str,
        supporting_keys: list[tuple[str, str]],
    ) -> dict[str, Any] | None:
        """Locked core of match_ruled_interpretation (caller holds
        the lock). Ruled rows only, most recent first."""
        rows = self._conn.execute(
            "SELECT interpretation_id, text, evidence_ids FROM "
            "upload_interpretations WHERE user_id = ? AND document_id = ? "
            "AND lens = ? AND status = 'ruled' "
            "ORDER BY created_at DESC, interpretation_id DESC",
            (user_id, document_id, lens),
        ).fetchall()
        wanted = sorted(supporting_keys)
        best_text: dict[str, Any] | None = None
        best_spans: dict[str, Any] | None = None
        for row in rows:
            prior_text_match = (
                _normalize_upload_text(row["text"] or "") == normalized_text
            )
            prior_evidence = _parse_upload_json_list(row["evidence_ids"])
            prior_keys = self._supporting_span_keys_locked(
                user_id, document_id, None, prior_evidence
            )
            prior_spans_match = sorted(prior_keys) == wanted
            if prior_text_match and prior_spans_match:
                return {
                    "kind": "exact",
                    "prior_interpretation_id": row["interpretation_id"],
                }
            if prior_text_match and best_text is None:
                best_text = {
                    "kind": "text_only",
                    "prior_interpretation_id": row["interpretation_id"],
                }
            if prior_spans_match and best_spans is None:
                best_spans = {
                    "kind": "spans_only",
                    "prior_interpretation_id": row["interpretation_id"],
                }
        # Exactly one condition: the uncertain case. Text match wins
        # the naming when both single-condition matches exist on
        # different priors (deterministic: text first).
        return best_text if best_text is not None else best_spans

    def _supporting_span_keys_locked(
        self,
        user_id: str,
        document_id: str,
        document_version: int | None,
        evidence: list[dict[str, Any]],
    ) -> list[tuple[str, str]]:
        """(span_hash, location) for the SUPPORTING spans of an
        evidence list — roles primary + supporting (contrast argues
        against the reading and is not support, §5.1). Caller holds
        the lock. ``document_version`` may be None to match a span
        across versions (the prior row's version is read from its
        own evidence resolution)."""
        keys: list[tuple[str, str]] = []
        for entry in evidence or []:
            role = (entry.get("role") or "").strip().lower()
            if role not in ("primary", "supporting"):
                continue
            span_id = entry.get("span_id")
            if not span_id:
                continue
            if document_version is not None:
                row = self._conn.execute(
                    "SELECT span_hash, location FROM upload_spans "
                    "WHERE span_id = ? AND user_id = ? AND document_id = ? "
                    "AND document_version = ?",
                    (span_id, user_id, document_id, document_version),
                ).fetchone()
            else:
                row = self._conn.execute(
                    "SELECT span_hash, location FROM upload_spans "
                    "WHERE span_id = ? AND user_id = ? AND document_id = ?",
                    (span_id, user_id, document_id),
                ).fetchone()
            if row is not None:
                keys.append((str(row["span_hash"]), str(row["location"])))
        return keys

    # -- upload outcomes (§2.4, §8) ------------------------------------------

    def create_upload_outcome(
        self,
        user_id: str,
        document_id: str,
        document_version: int,
        interpretation_id: str,
        kind: str,
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a 'pending' outcome row. Idempotent by the UNIQUE
        (interpretation_id, kind) index (§2.4): a second create for
        the same pair returns the existing row, never a duplicate —
        the replay guard (§8.2)."""
        if kind not in ("keep", "explore", "project", "task", "idea"):
            raise ValueError(f"Unknown outcome kind: {kind!r}")
        now = _utcnow()
        with self._lock:
            outcome_id = uuid.uuid4().hex
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO upload_outcomes (outcome_id, user_id, "
                "document_id, document_version, interpretation_id, kind, "
                "status, ve_kind, ve_id, parent_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'pending', NULL, NULL, ?, ?)",
                (
                    outcome_id,
                    user_id,
                    document_id,
                    document_version,
                    interpretation_id,
                    kind,
                    parent_id,
                    now,
                ),
            )
            self._conn.commit()
            if (cur.rowcount or 0) == 1:
                row = self._conn.execute(
                    "SELECT outcome_id, user_id, document_id, document_version, "
                    "interpretation_id, kind, status, ve_kind, ve_id, parent_id, "
                    "created_at FROM upload_outcomes WHERE outcome_id = ?",
                    (outcome_id,),
                ).fetchone()
                assert row is not None
                return dict(row)
            existing = self._conn.execute(
                "SELECT outcome_id, user_id, document_id, document_version, "
                "interpretation_id, kind, status, ve_kind, ve_id, parent_id, "
                "created_at FROM upload_outcomes WHERE interpretation_id = ? "
                "AND kind = ?",
                (interpretation_id, kind),
            ).fetchone()
            assert existing is not None
            return dict(existing)

    def get_upload_outcome(
        self, user_id: str, outcome_id: str
    ) -> dict[str, Any] | None:
        """One outcome row, owner-scoped."""
        with self._lock:
            row = self._conn.execute(
                "SELECT outcome_id, user_id, document_id, document_version, "
                "interpretation_id, kind, status, ve_kind, ve_id, parent_id, "
                "created_at FROM upload_outcomes WHERE outcome_id = ? "
                "AND user_id = ?",
                (outcome_id, user_id),
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def get_upload_outcome_by_interp_kind(
        self, user_id: str, interpretation_id: str, kind: str
    ) -> dict[str, Any] | None:
        """The outcome for one (interpretation, kind), if any —
        the standing-outcome check (§8.2)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT outcome_id, user_id, document_id, document_version, "
                "interpretation_id, kind, status, ve_kind, ve_id, parent_id, "
                "created_at FROM upload_outcomes WHERE user_id = ? "
                "AND interpretation_id = ? AND kind = ?",
                (user_id, interpretation_id, kind),
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def list_upload_outcomes(
        self,
        user_id: str,
        interpretation_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Outcome rows for a user (optionally one interpretation /
        status), oldest first."""
        query = (
            "SELECT outcome_id, user_id, document_id, document_version, "
            "interpretation_id, kind, status, ve_kind, ve_id, parent_id, "
            "created_at FROM upload_outcomes WHERE user_id = ?"
        )
        args: list[Any] = [user_id]
        if interpretation_id is not None:
            query += " AND interpretation_id = ?"
            args.append(interpretation_id)
        if status is not None:
            query += " AND status = ?"
            args.append(status)
        query += " ORDER BY created_at ASC, outcome_id ASC"
        with self._lock:
            rows = self._conn.execute(query, args).fetchall()
        return [dict(r) for r in rows]

    def claim_upload_outcome(self, user_id: str, outcome_id: str) -> bool:
        """The §8.1 step-1 compare-and-swap: only the session whose
        UPDATE matches a 'pending' row proceeds to create. Rowcount
        1 → this session owns the creation; 0 → already decided
        (the caller returns the existing outcome or 409s)."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE upload_outcomes SET status = 'creating' "
                "WHERE outcome_id = ? AND user_id = ? AND status = 'pending'",
                (outcome_id, user_id),
            )
            self._conn.commit()
            return (cur.rowcount or 0) == 1

    def reclaim_upload_outcome(self, user_id: str, outcome_id: str) -> bool:
        """The §8.1 step-1b retry re-claim (brief amendment A4):
        a confirmation for an outcome in status 'creating' with no
        carrier row may re-take the claim — the UPDATE matches a
        'creating' row, rowcount 1 → this session owns the retry;
        rowcount 0 → another session owns it (the caller returns the
        existing outcome or 409s per §8.2). The one-hour staleness
        gate is the CALLER's job (approve_upload_outcome checks the
        outcome's age before calling this); this method is the raw
        compare-and-swap. Setting status to its current value is
        deliberate: the rowcount, not the value change, is the
        ownership signal (SQLite counts matched rows)."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE upload_outcomes SET status = 'creating' "
                "WHERE outcome_id = ? AND user_id = ? AND status = 'creating'",
                (outcome_id, user_id),
            )
            self._conn.commit()
            return (cur.rowcount or 0) == 1

    def supersede_upload_versions_before(
        self, user_id: str, document_id: str, document_version: int
    ) -> dict[str, int]:
        """The §5.4 re-extraction transition (amendment A3): when a
        re-extraction produces a new evidence set, the OLD set
        becomes 'superseded' — preserved, never deleted, never
        presented — and its PENDING interpretations become
        'orphaned' (preserved, never presented). Ruled
        interpretations stay 'ruled': they are the historical record
        of what the user decided, readable in history. Returns the
        counts superseded/orphaned. Idempotent: re-running it
        matches nothing new."""
        with self._lock:
            spans = self._conn.execute(
                "UPDATE upload_spans SET status = 'superseded' "
                "WHERE user_id = ? AND document_id = ? "
                "AND document_version < ? AND status = 'current'",
                (user_id, document_id, document_version),
            )
            observations = self._conn.execute(
                "UPDATE upload_observations SET status = 'superseded' "
                "WHERE user_id = ? AND document_id = ? "
                "AND document_version < ? AND status = 'current'",
                (user_id, document_id, document_version),
            )
            interpretations = self._conn.execute(
                "UPDATE upload_interpretations SET status = 'orphaned' "
                "WHERE user_id = ? AND document_id = ? "
                "AND document_version < ? AND status = 'pending'",
                (user_id, document_id, document_version),
            )
            self._conn.commit()
            return {
                "spans": spans.rowcount or 0,
                "observations": observations.rowcount or 0,
                "interpretations": interpretations.rowcount or 0,
            }

    def set_upload_outcome_status(
        self,
        user_id: str,
        outcome_id: str,
        status: str,
        ve_kind: str | None = None,
        ve_id: str | None = None,
    ) -> bool:
        """Set an outcome's status (optionally its VE link, the
        §8.1 step-3 write). Only the outcome-approval path writes
        'creating' / 'created'; Archive-it writes 'archived'."""
        if status not in ("pending", "creating", "created", "failed", "archived"):
            raise ValueError(f"Unknown outcome status: {status!r}")
        with self._lock:
            if ve_kind is not None or ve_id is not None:
                cur = self._conn.execute(
                    "UPDATE upload_outcomes SET status = ?, ve_kind = ?, "
                    "ve_id = ? WHERE outcome_id = ? AND user_id = ?",
                    (status, ve_kind, ve_id, outcome_id, user_id),
                )
            else:
                cur = self._conn.execute(
                    "UPDATE upload_outcomes SET status = ? "
                    "WHERE outcome_id = ? AND user_id = ?",
                    (status, outcome_id, user_id),
                )
            self._conn.commit()
            return (cur.rowcount or 0) == 1

    # -- upload artifacts (§2.9, §9) ------------------------------------------

    def create_upload_artifact(
        self,
        user_id: str,
        conversation_id: str,
        document_id: str,
        document_version: int,
        interpretation_id: str | None,
        lens: str,
        lens_kind: str,
        artifact_kind: str,
        artifact_text: str,
        source_span_ids: list[str] | None = None,
        framing: str | None = None,
    ) -> dict[str, Any]:
        """File a creative artifact of the conversation (A6.2). An
        artifact is never a VE record, never a node, never a
        commitment — it takes no VE kind and no node kind."""
        if artifact_kind not in (
            "poem",
            "satire",
            "metaphor",
            "story",
            "scene",
            "name",
            "kept-reading",
        ):
            raise ValueError(f"Unknown artifact kind: {artifact_kind!r}")
        artifact_text = (artifact_text or "").strip()
        if not artifact_text:
            raise ValueError("Artifact text is empty.")
        artifact_id = uuid.uuid4().hex
        now = _utcnow()
        with self._lock:
            self._conn.execute(
                "INSERT INTO upload_artifacts (artifact_id, user_id, "
                "conversation_id, document_id, document_version, "
                "interpretation_id, lens, lens_kind, artifact_kind, "
                "artifact_text, source_span_ids, framing, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    artifact_id,
                    user_id,
                    conversation_id,
                    document_id,
                    document_version,
                    interpretation_id,
                    lens,
                    lens_kind,
                    artifact_kind,
                    artifact_text,
                    json.dumps(list(source_span_ids or [])),
                    framing,
                    now,
                ),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT artifact_id, user_id, conversation_id, document_id, "
                "document_version, interpretation_id, lens, lens_kind, "
                "artifact_kind, artifact_text, source_span_ids, framing, "
                "created_at FROM upload_artifacts WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchone()
        assert row is not None
        out = dict(row)
        out["source_span_ids"] = _parse_upload_json_list(out.get("source_span_ids"))
        return out

    def list_upload_artifacts(
        self, user_id: str, document_id: str
    ) -> list[dict[str, Any]]:
        """Artifacts filed under a document, oldest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT artifact_id, user_id, conversation_id, document_id, "
                "document_version, interpretation_id, lens, lens_kind, "
                "artifact_kind, artifact_text, source_span_ids, framing, "
                "created_at FROM upload_artifacts WHERE user_id = ? "
                "AND document_id = ? ORDER BY created_at ASC, artifact_id ASC",
                (user_id, document_id),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            d["source_span_ids"] = _parse_upload_json_list(d.get("source_span_ids"))
            out.append(d)
        return out

    # -- upload rounds + offers (§2.5–§2.6, §6, §11) --------------------------

    def get_upload_round(
        self, user_id: str, conversation_id: str
    ) -> dict[str, Any] | None:
        """The latest durable round record for a conversation, or
        None. The record is a durable trace — round STATE is
        derived per turn from the markers, never read from here."""
        with self._lock:
            row = self._conn.execute(
                "SELECT round_id, user_id, conversation_id, document_id, "
                "document_version, lens, state, segment_presented, "
                "presented_count, created_at, updated_at FROM upload_rounds "
                "WHERE user_id = ? AND conversation_id = ? "
                "ORDER BY updated_at DESC, round_id DESC LIMIT 1",
                (user_id, conversation_id),
            ).fetchone()
        if row is None:
            return None
        return _upload_round_dict(row)

    def save_upload_round(
        self,
        user_id: str,
        round_id: str,
        conversation_id: str,
        document_id: str,
        document_version: int,
        lens: str,
        state: str,
        segment_presented: list[str],
        presented_count: int,
    ) -> dict[str, Any]:
        """Upsert one round record (§2.5), written after generation
        succeeds. ``created_at`` is preserved across upserts."""
        if state not in ("item", "checkpoint", "closing", "ended"):
            raise ValueError(f"Unknown round state: {state!r}")
        now = _utcnow()
        with self._lock:
            self._conn.execute(
                "INSERT INTO upload_rounds (round_id, user_id, "
                "conversation_id, document_id, document_version, lens, state, "
                "segment_presented, presented_count, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(round_id) DO UPDATE SET state = excluded.state, "
                "segment_presented = excluded.segment_presented, "
                "presented_count = excluded.presented_count, "
                "updated_at = excluded.updated_at",
                (
                    round_id,
                    user_id,
                    conversation_id,
                    document_id,
                    document_version,
                    lens,
                    state,
                    json.dumps(list(segment_presented)),
                    presented_count,
                    now,
                    now,
                ),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT round_id, user_id, conversation_id, document_id, "
                "document_version, lens, state, segment_presented, "
                "presented_count, created_at, updated_at FROM upload_rounds "
                "WHERE round_id = ?",
                (round_id,),
            ).fetchone()
        assert row is not None
        return _upload_round_dict(row)

    def get_upload_offer(
        self, user_id: str, document_id: str, lens: str
    ) -> dict[str, Any] | None:
        """The latest offer row for (document, lens), or None."""
        with self._lock:
            row = self._conn.execute(
                "SELECT offer_id, user_id, document_id, lens, state, coverage, "
                "decline_snooze_until, created_at, updated_at FROM upload_offers "
                "WHERE user_id = ? AND document_id = ? AND lens = ? "
                "ORDER BY created_at DESC, offer_id DESC LIMIT 1",
                (user_id, document_id, lens),
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def save_upload_offer(
        self,
        user_id: str,
        document_id: str,
        lens: str,
        state: str,
        coverage: str = "",
        decline_snooze_until: str | None = None,
    ) -> dict[str, Any]:
        """Record an offer state change (§2.6). Each call writes a
        new row; the latest row for (document, lens) is the live
        offer state. 'never' declines carry decline_snooze_until
        NULL and are permanent for the document's round offers."""
        if state not in ("offered", "accepted", "declined", "expired"):
            raise ValueError(f"Unknown offer state: {state!r}")
        offer_id = uuid.uuid4().hex
        now = _utcnow()
        with self._lock:
            self._conn.execute(
                "INSERT INTO upload_offers (offer_id, user_id, document_id, "
                "lens, state, coverage, decline_snooze_until, created_at, "
                "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    offer_id,
                    user_id,
                    document_id,
                    lens,
                    state,
                    coverage or "",
                    decline_snooze_until,
                    now,
                    now,
                ),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT offer_id, user_id, document_id, lens, state, coverage, "
                "decline_snooze_until, created_at, updated_at FROM upload_offers "
                "WHERE offer_id = ?",
                (offer_id,),
            ).fetchone()
        assert row is not None
        return dict(row)

    def set_upload_offer_state(
        self,
        user_id: str,
        offer_id: str,
        state: str,
        decline_snooze_until: str | None = None,
    ) -> bool:
        """Transition one offer row (accept / decline / expire)."""
        if state not in ("offered", "accepted", "declined", "expired"):
            raise ValueError(f"Unknown offer state: {state!r}")
        with self._lock:
            cur = self._conn.execute(
                "UPDATE upload_offers SET state = ?, decline_snooze_until = ?, "
                "updated_at = ? WHERE offer_id = ? AND user_id = ?",
                (state, decline_snooze_until, _utcnow(), offer_id, user_id),
            )
            self._conn.commit()
            return (cur.rowcount or 0) == 1


# -- upload helpers (module-level, pure) --------------------------------------

#: Evidence-role strength for the §4.1 coercion (strongest first).
_UPLOAD_ROLE_STRENGTH = {"primary": 0, "supporting": 1, "contrast": 2}


def _parse_upload_json_list(value: Any) -> list[Any]:
    """Parse a JSON list column, degrading to [] on bad data."""
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value or "[]")
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


def _parse_upload_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _normalize_upload_text(text: str) -> str:
    """Normalization for matching only (noting brief §2.2):
    lowercase, curly quotes straightened, whitespace collapsed.
    Stored text is never normalized — only the comparison is."""
    lowered = (text or "").lower().replace("’", "'").replace("“", '"').replace("”", '"')
    cleaned = re.sub(r"[^\w\s'\"]", " ", lowered)
    return " ".join(cleaned.split())


def _upload_span_hash(span_text: str, location: str) -> str:
    """SHA-256 of normalized span + location (reconciliation §2.4).
    The stable span identity across re-extractions is content +
    location — never the row id (§5.1)."""
    import hashlib

    material = f"{_normalize_upload_text(span_text)}\n{location}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _coerce_upload_evidence_roles(
    evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Collapse duplicate spans to the strongest role (§4.1):
    primary > supporting > contrast. Unknown roles fail closed.
    Order is first-seen order, deterministic."""
    strongest: dict[str, str] = {}
    order: list[str] = []
    for entry in evidence or []:
        span_id = (entry or {}).get("span_id")
        role = ((entry or {}).get("role") or "").strip().lower()
        if not span_id or role not in _UPLOAD_ROLE_STRENGTH:
            raise ValueError(f"Bad evidence entry: {entry!r}")
        if span_id not in strongest:
            strongest[span_id] = role
            order.append(span_id)
        elif (
            _UPLOAD_ROLE_STRENGTH[role] < _UPLOAD_ROLE_STRENGTH[strongest[span_id]]
        ):
            strongest[span_id] = role
    return [{"span_id": sid, "role": strongest[sid]} for sid in order]


def _upload_job_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["failed_chunks"] = _parse_upload_json_list(d.get("failed_chunks"))
    # Amendment A1: the interpreted-chunks coverage record (a JSON
    # list of chunk ids; [] when nothing has been interpreted yet).
    d["interpreted_chunks"] = _parse_upload_json_list(
        d.get("interpreted_chunks")
    )
    return d


def _upload_observation_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["span_ids"] = _parse_upload_json_list(d.get("span_ids"))
    return d


def _upload_interpretation_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["evidence_ids"] = _parse_upload_json_list(d.get("evidence_ids"))
    d["observation_ids"] = _parse_upload_json_list(d.get("observation_ids"))
    d["is_transformation"] = bool(d.get("is_transformation"))
    d["ungrounded"] = bool(d.get("ungrounded"))
    # Amendment A3: the stored uncertain-match marker (JSON, or None).
    # Parsed to a dict when present; the queue translates it to the
    # {kind, prior_interpretation_id} shape via uncertain_match_for.
    raw_match = d.get("uncertain_match")
    if isinstance(raw_match, str) and raw_match.strip():
        try:
            parsed_match = json.loads(raw_match)
        except (ValueError, TypeError):
            parsed_match = None
        d["uncertain_match"] = (
            parsed_match if isinstance(parsed_match, dict) else None
        )
    else:
        d["uncertain_match"] = None
    return d


def _upload_round_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["segment_presented"] = _parse_upload_json_list(d.get("segment_presented"))
    return d
