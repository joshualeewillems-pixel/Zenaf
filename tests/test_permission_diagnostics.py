"""Permission Simplification P-1 — read-only permission diagnostics.

The diagnostics in ``local_ai.permissions.diagnostics`` mirror the
steward enforcement checks without participating in them. These
tests pin the mirror against the REAL enforcement functions
(``steward_consent_allowed``, ``steward_coordination_allowed``,
``candidate_capture_disclosed`` — imported and called, never
reimplemented) over the full matrix of stored permission states,
pin the exact scope of the ``scope_version_stale`` state, and prove
the diagnostic path writes nothing.

Fixture pattern copied from tests/test_steward_d1_candidates.py: a
tmp vision-execution database created by the real storage layer
(``init_db``) behind the storage module's ``get_connection`` seam.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from local_ai.narrative.consent import (
    DISCLOSURE_CONSENT_VERSION,
    candidate_capture_disclosed,
    steward_consent_allowed,
    steward_coordination_allowed,
)
from local_ai.permissions.diagnostics import (
    AVAILABLE,
    CANDIDATE_CAPTURE,
    CONSENT_ABSENT,
    COORDINATION,
    DERIVATION,
    ERROR,
    INTENTIONALLY_OFF,
    SCOPE_VERSION_STALE,
    permission_diagnostics,
)
from local_ai.vision_execution import storage as ve_storage
from local_ai.vision_execution.storage import init_db, open_sqlite_with_ve_pragmas

CURRENT = DISCLOSURE_CONSENT_VERSION
STALE = "permissions-v1"  # the pre-disclosure version (consent.py)
EMPTY = ""


def _state_specs():
    """The stored-state matrix: consent absent/off/on x derivation
    flag x coordination flag x stored consent_version
    current/stale/empty. (For an absent row neither flags nor a
    version exist; it is enumerated once.)"""
    specs = []
    # An absent row stores no flags at all, so the flag dimensions
    # collapse: one absent state, not four fictitious ones.
    specs.append(
        {"consent": "absent", "deriv": False, "coord": False,
         "version": None}
    )
    for consent in (0, 1):
        for deriv in (False, True):
            for coord in (False, True):
                for version in (CURRENT, STALE, EMPTY):
                    specs.append(
                        {"consent": consent, "deriv": deriv,
                         "coord": coord, "version": version}
                    )
    return specs


@pytest.fixture()
def matrix(tmp_path, monkeypatch):
    """A real-schema VE database holding one user per matrix state.

    Returns ``(conn, [(user_id, spec), ...])``."""
    conn = open_sqlite_with_ve_pragmas(tmp_path / "ve.db")
    init_db(conn)
    monkeypatch.setattr(ve_storage, "get_connection", lambda: conn)
    users = []
    for idx, spec in enumerate(_state_specs()):
        user_id = f"matrix-{idx}"
        users.append((user_id, spec))
        if spec["consent"] == "absent":
            continue
        conn.execute(
            "INSERT INTO user_permissions_settings "
            "(user_id, consent_given, consent_version, consent_at, "
            "permissions_json, updated_at) VALUES (?, ?, ?, NULL, ?, '')",
            (
                user_id,
                spec["consent"],
                spec["version"],
                json.dumps(
                    {
                        "steward_derivation": spec["deriv"],
                        "steward_coordination": spec["coord"],
                    }
                ),
            ),
        )
    conn.commit()
    yield conn, users
    conn.close()


def _expected_states(spec):
    """The brief's classification semantics for one stored state."""
    consent_given = spec["consent"] == 1

    def flag_state(on):
        if on:
            return AVAILABLE
        if not consent_given:
            return CONSENT_ABSENT
        return INTENTIONALLY_OFF

    if spec["deriv"] and spec["version"] == CURRENT:
        capture = AVAILABLE
    elif not consent_given:
        capture = CONSENT_ABSENT
    elif not spec["deriv"]:
        capture = INTENTIONALLY_OFF
    else:
        capture = SCOPE_VERSION_STALE

    return {
        DERIVATION: flag_state(spec["deriv"]),
        COORDINATION: flag_state(spec["coord"]),
        CANDIDATE_CAPTURE: capture,
    }


# ---------------------------------------------------------------------
# 1. Property: "available" exactly when real enforcement returns True
# ---------------------------------------------------------------------


def test_available_iff_real_enforcement(matrix):
    conn, users = matrix
    assert len(users) == 25  # 1 absent-row + 24 stored-row states
    for user_id, spec in users:
        diag = permission_diagnostics(user_id, connection=conn)
        enforcement = {
            DERIVATION: steward_consent_allowed(user_id, connection=conn),
            COORDINATION: steward_coordination_allowed(
                user_id, connection=conn
            ),
            CANDIDATE_CAPTURE: candidate_capture_disclosed(
                user_id, connection=conn
            ),
        }
        for capability, allowed in enforcement.items():
            assert (diag[capability]["state"] == AVAILABLE) == allowed, (
                f"{capability} for {spec}: diagnostic "
                f"{diag[capability]['state']!r} vs enforcement {allowed}"
            )
        # And the full classification matches the specified semantics.
        assert {
            cap: diag[cap]["state"] for cap in diag
        } == _expected_states(spec), f"full classification for {spec}"


# ---------------------------------------------------------------------
# 2. Stale exactness
# ---------------------------------------------------------------------


def test_scope_version_stale_exactness(matrix):
    conn, users = matrix
    for user_id, spec in users:
        diag = permission_diagnostics(user_id, connection=conn)
        expected_stale = (
            spec["consent"] == 1
            and spec["deriv"]
            and spec["version"] != CURRENT
        )
        assert (
            diag[CANDIDATE_CAPTURE]["state"] == SCOPE_VERSION_STALE
        ) == expected_stale, f"capture stale for {spec}"
        # No other capability ever reports the stale state.
        assert diag[DERIVATION]["state"] != SCOPE_VERSION_STALE
        assert diag[COORDINATION]["state"] != SCOPE_VERSION_STALE


# ---------------------------------------------------------------------
# 3. No writes, on either the injected- or default-connection path
# ---------------------------------------------------------------------


def _snapshot(conn):
    rows = conn.execute(
        "SELECT user_id, consent_given, consent_version, consent_at, "
        "permissions_json, updated_at FROM user_permissions_settings "
        "ORDER BY user_id"
    ).fetchall()
    return repr([tuple(row) for row in rows])


def test_diagnostics_write_nothing(matrix):
    conn, users = matrix
    before = _snapshot(conn)
    for user_id, _spec in users:
        permission_diagnostics(user_id, connection=conn)
    # Default-connection path (the monkeypatched storage seam),
    # including an unknown user — the settings helper would INSERT
    # a row for them; the diagnostic must not.
    known = users[-1][0]
    permission_diagnostics(known)
    unknown = permission_diagnostics("matrix-unknown-user")
    assert all(
        d["state"] == CONSENT_ABSENT for d in unknown.values()
    )
    assert _snapshot(conn) == before


# ---------------------------------------------------------------------
# Failure and edge behavior
# ---------------------------------------------------------------------


def test_missing_table_is_error_state_not_exception():
    conn = sqlite3.connect(":memory:")  # no user_permissions_settings
    diag = permission_diagnostics("anyone", connection=conn)
    for capability in (DERIVATION, COORDINATION, CANDIDATE_CAPTURE):
        assert diag[capability]["state"] == ERROR
        assert "OperationalError" in diag[capability]["detail"]
    conn.close()


def test_no_user_is_consent_absent():
    for user_id in (None, ""):
        diag = permission_diagnostics(user_id)
        assert all(d["state"] == CONSENT_ABSENT for d in diag.values())
        # Consistent with enforcement, which is closed for no user.
        assert steward_consent_allowed(user_id) is False
        assert steward_coordination_allowed(user_id) is False
        assert candidate_capture_disclosed(user_id) is False


def test_malformed_and_nonboolean_flags_resolve_off(matrix):
    conn, _users = matrix
    cases = {
        "bad-json": "not json",
        "int-flag": json.dumps({"steward_derivation": 1}),
    }
    for user_id, blob in cases.items():
        conn.execute(
            "INSERT INTO user_permissions_settings "
            "(user_id, consent_given, consent_version, consent_at, "
            "permissions_json, updated_at) VALUES (?, 1, ?, NULL, ?, '')",
            (user_id, CURRENT, blob),
        )
    conn.commit()
    for user_id in cases:
        # Enforcement (literal-True-only) is closed...
        assert steward_consent_allowed(user_id, connection=conn) is False
        assert candidate_capture_disclosed(user_id, connection=conn) is False
        # ...and the diagnostic agrees, as intentionally_off: consent
        # is recorded, the flag does not read as on.
        diag = permission_diagnostics(user_id, connection=conn)
        assert diag[DERIVATION]["state"] == INTENTIONALLY_OFF
        assert diag[CANDIDATE_CAPTURE]["state"] == INTENTIONALLY_OFF
