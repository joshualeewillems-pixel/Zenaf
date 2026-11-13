"""Permissions Slice 1 — consumption-boundary enforcement.

Implements the consumption half of the permissions framework: the
derivation and consent gates already stop new material from being
*created* without permission; this module is the one shared check
consulted where already-derived material is *consumed* — read into a
response, a read model, a prompt context, or a proactive surface —
per the approved proposal
(~/workspace/your_files/zenaf-permissions-slice-1-consumption-boundary-proposal-2026-11-10.md
§4, founder decision record 2026-11-12).

``consumption_allowed(user_id, permission) -> bool`` is the single
entry point. Callers name the permission that governs the material
they are about to consume; the helper resolves it through the
machinery that already exists:

- Flag-governed permissions (``fellowship_derivation``,
  ``steward_derivation``, ``steward_coordination``) dispatch to the
  existing fail-closed leaf readers in ``local_ai.fellowship.consent``
  and ``local_ai.narrative.consent``. No new flag readers: the leaf
  readers' literal-``True``-only semantics, and their own distinction
  between an explicit denial (silent ``False``) and a resolution
  failure (an exception log, still ``False``), are preserved by
  dispatching rather than re-reading the settings row here.
- Stance-governed permissions (``R4``, ``R6``) resolve through the
  existing stance read — ``effective_stance`` (the store read joined
  with registry defaults) — NOT the five-step ``framework_check``:
  consumption involves no new action instance to preserve, no scope
  beyond the surface's own rows, and no conversation to pause-check,
  so steps 1/2/4/5 do not apply. A stance permission is allowed only
  when the resolved stance is ``just_do_it``.

Semantics (proposal §4, founder requirements O-S1-1..O-S1-6):

- **Fail closed.** Any error, missing row, malformed value, or
  unknown permission resolves to ``False``. A resolution *failure*
  additionally logs an exception here (stance path) or in the leaf
  reader (flag path), so failure remains distinguishable from an
  explicit denial, which returns ``False`` with no failure log.
- **Read-only.** A check never writes: no row inserted, no flag
  flipped, no history appended. Unknown users resolve through
  defaults (flags off; registry stance defaults) without any row
  being created for them.
- **Checked at each consumption.** Callers consult the helper at the
  moment of consumption, every time — never cached from generation
  time — so a revocation takes effect at the next consumption
  boundary, including when previously computed material (a cached
  run, stored markers) is reused. Material already served into an
  in-flight context is not recalled.
- **Narrow overrides stay narrow (O-S1-3).** Boundaries that serve
  explicitly user-initiated interactions (joining an invitation,
  opening a conversation) are not gated here; invocation overrides
  restrictions on unsolicited *initiation* for that interaction only
  and never overrides derivation, coordination, retention, or
  disclosure permissions — which is why the derivation gates in this
  slice apply regardless of how the surface was reached.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("zenaf.permissions.consumption")

# The permission names a caller may pass. Flag names match the
# settings-row keys the leaf readers consult; stance names are the
# registry capability ids.
FELLOWSHIP_DERIVATION = "fellowship_derivation"
STEWARD_DERIVATION = "steward_derivation"
STEWARD_COORDINATION = "steward_coordination"
R4 = "R4"
R6 = "R6"

# R6's standing scheme carries a single standing row: the "all" row
# the Settings surface writes (standing "follow through on my behalf"
# choice). Per-commitment rows, if a user ever sets them, do not
# widen consumption beyond the standing row.
_R6_STANDING_ROW = "all"


def consumption_allowed(
    user_id: str | None,
    permission: str,
    *,
    scope_row: str | None = None,
    connection=None,
) -> bool:
    """Whether ``user_id`` may consume material governed by ``permission``.

    ``permission`` is one of the module constants above. For ``R4``
    (the enumerated per-seat scheme), ``scope_row`` names the seat row
    being consumed (e.g. ``"guardian"``); a missing row fails closed.
    For ``R6`` the standing ``"all"`` row is always consulted and
    ``scope_row`` is ignored. ``connection`` is forwarded to the
    underlying readers (tests, alternate stores); production callers
    omit it.

    Returns a plain bool and never raises: resolution failures fail
    closed and are logged as failures (here or in the leaf readers),
    distinguishable from an explicit denial's silent ``False``.
    """
    if not user_id or not permission:
        return False

    if permission == FELLOWSHIP_DERIVATION:
        from local_ai.fellowship.consent import fellowship_consent_allowed

        return fellowship_consent_allowed(user_id, connection=connection)

    if permission == STEWARD_DERIVATION:
        from local_ai.narrative.consent import steward_consent_allowed

        return steward_consent_allowed(user_id, connection=connection)

    if permission == STEWARD_COORDINATION:
        from local_ai.narrative.consent import steward_coordination_allowed

        return steward_coordination_allowed(user_id, connection=connection)

    if permission in (R4, R6):
        if permission == R4:
            if not scope_row:
                logger.warning(
                    "consumption: R4 check for user %r without a seat "
                    "row; failing closed",
                    user_id,
                )
                return False
            rows = [scope_row]
        else:
            rows = [_R6_STANDING_ROW]
        try:
            from local_ai.permissions.framework import effective_stance
            from local_ai.permissions.registry import JUST_DO_IT

            # effective_stance returns (joined stance, per-row map);
            # consumption is governed by the joined stance alone.
            stance, _per_row = effective_stance(
                user_id, permission, rows, connection=connection
            )
        except Exception:
            logger.exception(
                "consumption: stance resolution failed for user %r, "
                "permission %s; failing closed",
                user_id,
                permission,
            )
            return False
        return stance == JUST_DO_IT

    logger.warning(
        "consumption: unknown permission %r for user %r; failing closed",
        permission,
        user_id,
    )
    return False
