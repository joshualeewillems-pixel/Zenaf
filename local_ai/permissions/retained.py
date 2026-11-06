"""Retained-information counts per capability (Slice 2).

Rev2 §4.2: revocation decides nothing about previously retained
information; the surface must show counts where retained items exist
(the standing "retained items" line per row, and the contextual
choice line on a Don't-do-it change). Counts come ONLY from stores
that already exist — no new store, no invented counting (Slice 2
bounds):

- R1 NOTE: 0 — no noting record exists until Slice 3.
- R2 INTERPRET: derived narrative threads (``narrative_threads``).
  Every thread status is retained (readings supersede, never delete),
  so the count is all threads for the user.
- R3 COORDINATE: 0 — coordination writes no persisted distribution
  record.
- R4 INVITE: pending invitations, user-wide
  (``list_pending_invitations`` with no conversation filter returns
  the user's pending, unexpired invitations).
- R5 PROPOSE: pending task proposals, user-wide
  (``count_pending_task_proposals``).
- R6 REMIND: live follow-through nudges (``list_feed_nudges``:
  not acked, not resolved, snooze expired or absent).

All counts are owner-scoped. A store whose database file does not
exist yet contributes 0 WITHOUT creating it — a GET must not create
state. A read failure on an existing store also contributes 0: the
surface shows a count, never an error, for retained items. (The
framework check, not this module, is the fail-closed path; a count
of 0 never authorizes anything.)

Store instances are injectable for tests; otherwise the default
stores are constructed lazily (and only when their database file
already exists).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

def _safe_count(fn) -> int:
    try:
        value = fn()
    except (sqlite3.Error, OSError, ImportError, AttributeError, ValueError):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _db_exists(default_path: Path | str | None) -> bool:
    if default_path is None:
        return False
    try:
        return Path(default_path).exists()
    except (OSError, ValueError):
        return False


def retained_counts(
    user_id: str,
    *,
    narrative_store: Any | None = None,
    conversation_store: Any | None = None,
    followthrough_store: Any | None = None,
    ve_connection: sqlite3.Connection | None = None,
) -> dict[str, int]:
    """Retained-item counts per capability for the user.

    Always returns all six capabilities (missing/zero counts are 0,
    never absent), so the surface can render a standing line per row
    without special-casing capabilities.
    """
    counts: dict[str, int] = {cap: 0 for cap in ("R1", "R2", "R3", "R4", "R5", "R6")}

    # R2: derived narrative threads.
    if narrative_store is not None:
        counts["R2"] = _safe_count(
            lambda: len(narrative_store.threads_for(user_id, limit=None))
        )
    else:
        from local_ai.narrative.store import DEFAULT_DB_PATH, NarrativeStore

        if _db_exists(DEFAULT_DB_PATH):
            store = NarrativeStore()
            counts["R2"] = _safe_count(
                lambda: len(store.threads_for(user_id, limit=None))
            )
            store.close()

    # R4: pending invitations, user-wide.
    if conversation_store is not None:
        counts["R4"] = _safe_count(
            lambda: len(conversation_store.list_pending_invitations(user_id))
        )
    else:
        from local_ai.conversation.store import (
            DEFAULT_DB_PATH,
            ConversationStore,
        )

        if _db_exists(DEFAULT_DB_PATH):
            store = ConversationStore()
            counts["R4"] = _safe_count(
                lambda: len(store.list_pending_invitations(user_id))
            )
            store.close()

    # R5: pending task proposals, user-wide.
    from local_ai.vision_execution import storage as _ve_storage

    if ve_connection is not None:
        counts["R5"] = _safe_count(
            lambda: _ve_storage.count_pending_task_proposals(
                user_id, connection=ve_connection
            )
        )
    else:
        counts["R5"] = _safe_count(
            lambda: _ve_storage.count_pending_task_proposals(user_id)
        )

    # R6: live follow-through nudges.
    if followthrough_store is not None:
        counts["R6"] = _safe_count(
            lambda: len(followthrough_store.list_feed_nudges(user_id))
        )
    else:
        from local_ai.followthrough.store import (
            DEFAULT_DB_PATH,
            FollowthroughStore,
        )

        if _db_exists(DEFAULT_DB_PATH):
            store = FollowthroughStore()
            counts["R6"] = _safe_count(
                lambda: len(store.list_feed_nudges(user_id))
            )
            store.close()

    return counts
