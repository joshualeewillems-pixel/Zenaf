"""Permission diagnostics — read-only derivation of *why* a
capability is or is not available (Permission Simplification P-1).

This module changes nothing. It reads the same stored inputs the
enforcement checks read and classifies the outcome so a surface can
say, in plain language, which protection fired — instead of every
gate failing silently closed. Enforcement is untouched and never
consults this module: the diagnostics *mirror* enforcement, they do
not participate in it.

Capabilities covered, and the enforcement check each mirrors:

- ``derivation`` — ``local_ai.narrative.consent``
  ``steward_consent_allowed`` (the ``steward_derivation`` flag).
- ``coordination`` — ``steward_coordination_allowed`` (the
  ``steward_coordination`` flag). Cross-branch context preparation
  additionally requires the derivation flag via the composite
  ``coordination_allowed``; that is a gate over two capabilities,
  and this module reports each capability's own standing.
- ``candidate_capture`` — ``candidate_capture_disclosed`` (the D1
  gate: derivation flag AND stored ``consent_version`` equal to
  ``DISCLOSURE_CONSENT_VERSION``).

States:

- ``available`` — returned **exactly** when the mirrored
  enforcement check returns True for the same stored state.
- ``consent_absent`` — enforcement is closed and the account has no
  recorded consent (no permissions row, or ``consent_given``
  false). ``consent_given`` is the foundation
  ``user_permission_enabled`` requires before any flag functions.
- ``intentionally_off`` — consent is recorded, but the capability's
  own flag is off.
- ``scope_version_stale`` — ``candidate_capture`` only: consent
  recorded, derivation flag on, but the stored ``consent_version``
  predates the current disclosure version.
- ``operationally_off`` — part of the vocabulary for capabilities
  governed by an operational switch. None of these three
  capabilities has one, so this state is never returned here; it is
  declared so consumers can handle the full vocabulary uniformly.
- ``error`` — the diagnostic read itself failed; ``detail`` names
  the exception class. A diagnostic never raises into a caller.

One mirror-fidelity note: the steward leaf readers do not consult
``consent_given`` — they read the flags alone. So a row whose flag
is on diagnoses ``available`` even if ``consent_given`` is false,
because that is what enforcement will do. ``consent_absent`` is
therefore only assigned when enforcement is closed; the diagnostic
never contradicts the gate it explains.

Read discipline matches the consent leaf exactly: direct read-only
SELECTs on ``user_permissions_settings``, never the settings helper
(``get_user_permissions_settings`` INSERTs a row for unknown users —
a write that does not belong in a diagnostic). Malformed stored
JSON resolves to flags-off, exactly as the leaf readers resolve it.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger("zenaf.permissions.diagnostics")

#: Capability names, in surface order.
DERIVATION = "derivation"
COORDINATION = "coordination"
CANDIDATE_CAPTURE = "candidate_capture"
CAPABILITIES = (DERIVATION, COORDINATION, CANDIDATE_CAPTURE)

#: Diagnostic states (the full vocabulary; see module docstring).
AVAILABLE = "available"
INTENTIONALLY_OFF = "intentionally_off"
CONSENT_ABSENT = "consent_absent"
SCOPE_VERSION_STALE = "scope_version_stale"
OPERATIONALLY_OFF = "operationally_off"
ERROR = "error"
STATES = (
    AVAILABLE,
    INTENTIONALLY_OFF,
    CONSENT_ABSENT,
    SCOPE_VERSION_STALE,
    OPERATIONALLY_OFF,
    ERROR,
)

_DETAILS = {
    (DERIVATION, AVAILABLE): "the steward derivation flag is on",
    (DERIVATION, INTENTIONALLY_OFF): (
        "consent is recorded, but the steward derivation flag is off"
    ),
    (COORDINATION, AVAILABLE): "the steward coordination flag is on",
    (COORDINATION, INTENTIONALLY_OFF): (
        "consent is recorded, but the steward coordination flag is off"
    ),
    (CANDIDATE_CAPTURE, AVAILABLE): (
        "the derivation flag is on and the recorded consent carries "
        "the current disclosure version"
    ),
    (CANDIDATE_CAPTURE, INTENTIONALLY_OFF): (
        "consent is recorded, but the steward derivation flag is off"
    ),
    (CANDIDATE_CAPTURE, SCOPE_VERSION_STALE): (
        "the derivation flag is on, but the recorded consent "
        "predates the current disclosure version"
    ),
}

_CONSENT_ABSENT_DETAIL = "no consent is recorded for this account"


def _diagnostic(capability: str, state: str) -> dict[str, str]:
    if state == CONSENT_ABSENT:
        detail = _CONSENT_ABSENT_DETAIL
    else:
        detail = _DETAILS[(capability, state)]
    return {"state": state, "detail": detail}


def _error_diagnostics(exc: Exception) -> dict[str, dict[str, str]]:
    detail = f"diagnostic read failed ({type(exc).__name__})"
    return {
        capability: {"state": ERROR, "detail": detail}
        for capability in CAPABILITIES
    }


def permission_diagnostics(
    user_id: str | None,
    *,
    connection=None,
) -> dict[str, dict[str, str]]:
    """Diagnose the three steward capabilities for ``user_id``.

    Returns ``{capability: {"state": ..., "detail": ...}}`` for
    ``derivation``, ``coordination``, and ``candidate_capture``.
    Read-only and total: any store-read failure resolves to the
    ``error`` state rather than raising. ``connection`` is an
    injectable SQLite connection (tests pass a connection to a tmp
    permissions database); when omitted, the vision-execution
    storage connection is used, exactly as the consent leaf readers
    resolve it.
    """
    if not user_id:
        return {
            capability: _diagnostic(capability, CONSENT_ABSENT)
            for capability in CAPABILITIES
        }
    try:
        return _diagnose(user_id, connection=connection)
    except Exception as exc:  # a diagnostic never raises into a caller
        logger.exception(
            "permissions diagnostics: read failed for user %r", user_id
        )
        return _error_diagnostics(exc)


def _diagnose(
    user_id: str,
    *,
    connection=None,
) -> dict[str, dict[str, str]]:
    from local_ai.narrative.consent import (
        DISCLOSURE_CONSENT_VERSION,
        STEWARD_COORDINATION_KEY,
        STEWARD_PERMISSION_KEY,
    )

    if connection is None:
        from local_ai.vision_execution.storage import get_connection

        connection = get_connection()

    # One read of the stored inputs every mirrored check reads.
    # The fallback (permissions_json alone) mirrors the consent
    # leaf's tolerance of a minimal permissions table: the leaf
    # readers need only that column, so a table missing the consent
    # columns still diagnoses the flag capabilities; the unreadable
    # consent fields then resolve as absent, fail-closed, exactly
    # as enforcement resolves unreadable state.
    try:
        row = connection.execute(
            "SELECT consent_given, consent_version, permissions_json "
            "FROM user_permissions_settings WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            consent_given: bool | None = None
            consent_version: str | None = None
            permissions_json = None
        else:
            consent_given = bool(row[0])
            consent_version = row[1]
            permissions_json = row[2]
    except Exception:
        row = connection.execute(
            "SELECT permissions_json FROM user_permissions_settings "
            "WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        consent_given = None
        consent_version = None
        permissions_json = None if row is None else row[0]

    # Flag resolution identical to the leaf readers: malformed or
    # non-dict JSON, and any value that is not literal True, is off.
    try:
        parsed = json.loads(permissions_json or "{}")
    except (json.JSONDecodeError, TypeError):
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    derivation_on = parsed.get(STEWARD_PERMISSION_KEY) is True
    coordination_on = parsed.get(STEWARD_COORDINATION_KEY) is True

    # ``available`` is decided by the mirrored enforcement semantics
    # alone (the flags, plus the version for capture) — never by
    # consent_given, which the leaf readers do not consult.
    capture_available = (
        derivation_on and consent_version == DISCLOSURE_CONSENT_VERSION
    )

    out: dict[str, dict[str, str]] = {}

    if derivation_on:
        out[DERIVATION] = _diagnostic(DERIVATION, AVAILABLE)
    elif not consent_given:
        out[DERIVATION] = _diagnostic(DERIVATION, CONSENT_ABSENT)
    else:
        out[DERIVATION] = _diagnostic(DERIVATION, INTENTIONALLY_OFF)

    if coordination_on:
        out[COORDINATION] = _diagnostic(COORDINATION, AVAILABLE)
    elif not consent_given:
        out[COORDINATION] = _diagnostic(COORDINATION, CONSENT_ABSENT)
    else:
        out[COORDINATION] = _diagnostic(COORDINATION, INTENTIONALLY_OFF)

    if capture_available:
        out[CANDIDATE_CAPTURE] = _diagnostic(CANDIDATE_CAPTURE, AVAILABLE)
    elif not consent_given:
        out[CANDIDATE_CAPTURE] = _diagnostic(
            CANDIDATE_CAPTURE, CONSENT_ABSENT
        )
    elif not derivation_on:
        out[CANDIDATE_CAPTURE] = _diagnostic(
            CANDIDATE_CAPTURE, INTENTIONALLY_OFF
        )
    else:
        out[CANDIDATE_CAPTURE] = _diagnostic(
            CANDIDATE_CAPTURE, SCOPE_VERSION_STALE
        )

    return out
