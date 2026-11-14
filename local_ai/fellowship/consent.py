"""Fellowship derivation consent gate (Phase 0 consent correction).

One rule, enforced the same way as the steward gate: fellowship
derivation runs for a visitor only when that visitor holds the
dedicated, default-off fellowship permission flag.

The flag is a permissions-v1 flag, not a scope:
``fellowship_derivation`` in ``permissions_json``, default
``False``, added to the frontend defaults and the backend key list
so existing rows read ``False`` for it until the visitor turns it
on. The toggle wording is a founder decision; this module does
not draft user-facing consent copy.

This module is deliberately a leaf: it imports nothing from
fellowship derivation or the observations store, so derivation
can import it without a cycle and the turn path never touches
it. The read mirrors the capability registry's
``resolve_visitor_state``: a direct read-only SELECT on the
permissions row. It must NEVER use the settings helper
(``get_user_permissions_settings``) — that helper INSERTs a row
for unknown users, a write that does not belong on a derivation
gate. Any failure, any missing row, any missing or non-boolean
flag resolves to ``False``: unknown fails closed, and no
derivation runs.

Consequence (intended, fail-closed): with the flag off for
everyone by default, fellowship derivation stops for everyone —
including the founder — until each visitor turns the flag on.
There is no auto-on, no migration that turns it on, and no
bypass. The installed pipeline always gates (see
``local_ai.fellowship.derivation.install_default_pipeline``); a
pipeline built directly without a reader derives ungated only as
the documented test/tool direct-drive mode, same as steward.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

#: permissions-v1 flag key for fellowship derivation.
#: Distinct from ``steward_derivation`` by design: a visitor may
#: want patterns recognized within individual conversations
#: (steward) without distributing observations to other seats'
#: readings (fellowship), and vice versa. Default ``False`` like
#: the steward flag; missing, malformed, or unavailable state
#: fails closed. This flag never expands the steward flag's
#: meaning, and neither flag overrides aspiration permissions or
#: evidence restrictions — those are enforced by their own paths,
#: not here.
FELLOWSHIP_PERMISSION_KEY = "fellowship_derivation"


def fellowship_consent_allowed(
    user_id: str | None,
    *,
    connection=None,
) -> bool:
    """Does this visitor hold the fellowship derivation flag?

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
        return parsed.get(FELLOWSHIP_PERMISSION_KEY) is True
    except Exception:
        logger.exception(
            "fellowship: consent check failed for user %r; "
            "failing closed",
            user_id,
        )
        return False
