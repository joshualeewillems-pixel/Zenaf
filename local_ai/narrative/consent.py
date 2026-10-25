"""Narrative Steward consent gate (increment A).

One rule, enforced the same way on the install path and the sweep
path: steward derivation runs for a visitor only when that visitor
holds the dedicated, default-off steward permission flag.

The flag is a permissions-v1 flag, not a scope (proposal §1.8):
``steward_derivation`` in ``permissions_json``, default ``False``,
added to the frontend defaults and the backend key list so existing
rows read ``False`` for it until the visitor turns it on. The
approved wording for the toggle is: "Can Zenaf connect our talks
into ongoing threads, note what they might mean, and keep those
notes where you can review/delete them?"

This module is deliberately a leaf: it imports nothing from
narrative derivation or the narrative store, so derivation can
import it without a cycle and the turn path never touches it. The
read mirrors the capability registry's ``resolve_visitor_state``:
a direct read-only SELECT on the permissions row. It must NEVER
use the settings helper (``get_user_permissions_settings``) — that
helper INSERTs a row for unknown users, a write that does not
belong on a derivation gate. Any failure, any missing row, any
missing or non-boolean flag resolves to ``False``: unknown fails
closed, and no derivation runs.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

#: permissions-v1 flag key for Narrative Steward derivation.
STEWARD_PERMISSION_KEY = "steward_derivation"


def steward_consent_allowed(
    user_id: str | None,
    *,
    connection=None,
) -> bool:
    """Does this visitor hold the steward derivation flag?

    Read-only: a single SELECT of ``permissions_json`` for the user.
    ``connection`` is an injectable SQLite connection (tests pass a
    connection to a tmp permissions database); when omitted, the
    vision-execution storage connection is used, exactly as
    ``resolve_visitor_state`` does. Never inserts, never updates,
    never calls the settings helper.
    """
    if not user_id:
        return False
    try:
        if connection is None:
            from local_ai.vision_execution.storage import get_connection

            connection = get_connection()
        row = connection.execute(
            "SELECT permissions_json FROM user_permissions_settings "
            "WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return False
        try:
            parsed = json.loads(row[0] or "{}")
        except (json.JSONDecodeError, TypeError):
            return False
        if not isinstance(parsed, dict):
            return False
        return parsed.get(STEWARD_PERMISSION_KEY) is True
    except Exception:
        logger.exception(
            "narrative: steward consent check failed for user %r; "
            "failing closed",
            user_id,
        )
        return False
