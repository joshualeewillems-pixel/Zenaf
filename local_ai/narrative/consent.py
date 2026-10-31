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

#: permissions-v1 flag key for Narrative Steward cross-branch
#: coordination (Phase 1, addendum §4.5 / §7(c)). Distinct from
#: derivation by design: a visitor may want patterns recognized
#: within individual conversations without distributing those
#: observations to other branches. Default ``False`` like the
#: derivation flag; missing, malformed, or unavailable state fails
#: closed. This flag never expands the derivation flag's meaning,
#: and neither flag overrides aspiration permissions or evidence
#: restrictions — those are enforced by their own paths, not here.
STEWARD_COORDINATION_KEY = "steward_coordination"


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


def _flag_allowed(
    user_id: str | None,
    flag_key: str,
    *,
    connection=None,
) -> bool:
    """Shared fail-closed flag read (derivation + coordination).

    Same discipline as ``steward_consent_allowed``: a direct
    read-only SELECT on the permissions row, never the settings
    helper (which INSERTs). Any failure, missing row, or non-``True``
    value resolves to ``False``.
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
        return parsed.get(flag_key) is True
    except Exception:
        logger.exception(
            "narrative: steward consent check failed for user %r; "
            "failing closed",
            user_id,
        )
        return False


def steward_coordination_allowed(
    user_id: str | None,
    *,
    connection=None,
) -> bool:
    """Does this visitor hold the coordination flag?

    Default-off ``steward_coordination`` in ``permissions_json``.
    Fail-closed exactly like the derivation flag. This flag
    authorizes eligible narrative context to cross branch
    boundaries; it does not authorize derivation, and derivation
    does not authorize coordination.
    """
    return _flag_allowed(user_id, STEWARD_COORDINATION_KEY, connection=connection)


def coordination_allowed(
    user_id: str | None,
    *,
    connection=None,
) -> bool:
    """Are BOTH coordination prerequisites satisfied?

    Derived cross-branch coordination requires the derivation flag
    AND the coordination flag, alongside relevance assessment
    (which this function does not perform — see relevance.py and
    coordination.py). Either flag off, missing, malformed, or
    unreadable closes coordination. The check is re-run at every
    context preparation; prior eligibility never permanently
    authorizes subsequent disclosure.
    """
    return steward_consent_allowed(
        user_id, connection=connection
    ) and steward_coordination_allowed(user_id, connection=connection)
