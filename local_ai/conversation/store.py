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
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

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
        self, user_id: str, limit: int = 20, seat: str | None = None
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
        """
        limit = max(1, min(int(limit or 20), 100))
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
                "WHERE m.user_id = ? AND m.conversation_id LIKE 'talk-%' "
                + seat_clause
                + "GROUP BY m.conversation_id "
                "ORDER BY last_message_at DESC, m.conversation_id ASC LIMIT ?",
                params,
            ).fetchall()
            seat_rows = self._conn.execute(
                "SELECT m.conversation_id, m.archetype_id, MIN(m.created_at) AS first_seen "
                "FROM messages m WHERE m.user_id = ? AND m.archetype_id IS NOT NULL "
                "AND m.conversation_id LIKE 'talk-%' "
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
    ) -> dict[str, Any]:
        """Link a source to a strand thread. The caller must already
        have validated that the conversation is the caller's mapped
        thread for the strand, and that a file ``ref`` names an
        existing ingest session."""
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
