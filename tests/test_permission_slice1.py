"""Permission Slice 1 (foundation) tests.

Covers, per inventory §3 Slice 1:
- S7: unregistered capability produces nothing; registered with
  default Don't do it still produces nothing until a stance is set.
- Framework-check unit tests per step: unregistered fails closed;
  pause blocks new starts regardless of stance; boundary crossing
  requires the neighbor.
- Migration tests: existing flag rows map to stances without
  re-acknowledgement; coordination flag survives a write/read
  round-trip (REGRESSION TEST for the §1.4 dead-flag defect).
- Most-restrictive-join tests across rows of one capability.

Bounds honored by these tests: no Settings UI, no noting record,
no circle, no pause UI, no C1 contract records (only the check's
step-4 shape), no subsystem wiring, no training/publication gate
changes, no model calls, no scope-ledger changes.

Two connection styles, mirroring existing test patterns:
- Injected in-memory connections with minimal permissions tables
  (steward-gate pattern): the stance store must work on any
  connection, adding its own columns + history table.
- The real vision-execution storage path (ve_ctx pattern): the
  coordination round-trip runs through the actual upsert/get
  functions, which is where the dead-flag defect lived.
"""

from __future__ import annotations

import json
import sqlite3
import threading

import pytest

from local_ai.permissions import framework as F
from local_ai.permissions import registry as R
from local_ai.permissions import store as S


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _perm_conn(flags_by_user=None):
    """In-memory permissions DB in the minimal steward-test shape."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE user_permissions_settings ("
        "user_id TEXT, permissions_json TEXT, updated_at TEXT)"
    )
    for user_id, flags in (flags_by_user or {}).items():
        conn.execute(
            "INSERT INTO user_permissions_settings VALUES (?, ?, ?)",
            (user_id, json.dumps(flags), "2026-11-04T00:00:00+00:00"),
        )
    conn.commit()
    return conn


def _full_conn(flags_by_user=None, consent=None):
    """In-memory permissions DB in the full production-column shape."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE user_permissions_settings ("
        "user_id TEXT PRIMARY KEY,"
        "consent_given INTEGER NOT NULL DEFAULT 0,"
        "consent_version TEXT NOT NULL DEFAULT '',"
        "consent_at TEXT,"
        "permissions_json TEXT NOT NULL DEFAULT '{}',"
        "updated_at TEXT NOT NULL)"
    )
    for user_id, flags in (flags_by_user or {}).items():
        given, version, at = (consent or {}).get(
            user_id, (0, "", None)
        )
        conn.execute(
            "INSERT INTO user_permissions_settings VALUES (?, ?, ?, ?, ?, ?)",
            (
                user_id,
                given,
                version,
                at,
                json.dumps(flags),
                "2026-11-04T00:00:00+00:00",
            ),
        )
    conn.commit()
    return conn


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    """Isolate the vision-execution SQLite DB per test (real path)."""
    import local_ai.vision_execution.storage as ve_store

    monkeypatch.setattr(ve_store, "_DB_PATH", tmp_path / "ve.db")
    monkeypatch.setattr(ve_store, "_DB_DIR", tmp_path)
    monkeypatch.setattr(ve_store, "_init_done_paths", set())
    monkeypatch.setattr(ve_store, "_thread_local", threading.local())
    return ve_store


def _set(conn, user, capability, row, stance, surface="settings"):
    return S.set_stance(
        user, capability, row, stance, surface=surface, connection=conn
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_contains_exactly_r1_to_r6_and_not_r7():
    assert set(R.CAPABILITIES) == {"R1", "R2", "R3", "R4", "R5", "R6"}
    assert R.get_capability("R7") is None
    assert R.is_registered("R7") is False
    assert "R7" in R.RETIRED_CAPABILITY_IDS
    assert R.get_capability("R99") is None
    assert R.get_capability(None) is None
    # R8: the registry is immutable by construction — runtime
    # self-declaration raises instead of registering.
    with pytest.raises(TypeError):
        R.CAPABILITIES["R9"] = None  # type: ignore[index]
    R.validate_registry()
    for entry in R.CAPABILITIES.values():
        assert entry.covers.strip()
        assert entry.does_not_allow.strip()
        assert entry.default_stance in entry.supported_stances
        assert entry.never_authorizes


def test_registry_row_schemes_and_defaults():
    r1 = R.get_capability("R1")
    assert len(r1.rows) == 9  # 7 strands + 2 sources
    assert r1.default_stance == R.ASK_ME
    assert set(r1.supported_stances) == set(R.STANCES)
    r2 = R.get_capability("R2")
    assert [row.key for row in r2.rows] == ["all"]
    assert r2.default_stance == R.DONT_DO_IT
    r3 = R.get_capability("R3")
    assert r3.default_stance == R.DONT_DO_IT
    r4 = R.get_capability("R4")
    assert len(r4.rows) == 7
    assert r4.supported_stances == (R.JUST_DO_IT, R.DONT_DO_IT)
    assert r4.default_stance == R.JUST_DO_IT
    r5 = R.get_capability("R5")
    assert r5.supported_stances == (R.JUST_DO_IT, R.DONT_DO_IT)
    assert r5.default_stance == R.JUST_DO_IT
    r6 = R.get_capability("R6")
    assert r6.row_scheme == "per_commitment"
    assert r6.rows == ()
    assert r6.default_stance == R.DONT_DO_IT


# ---------------------------------------------------------------------------
# S7: registration gate
# ---------------------------------------------------------------------------


def test_s7_unregistered_capability_produces_nothing():
    conn = _perm_conn()
    decision = F.framework_check("u1", "R99", connection=conn)
    assert decision.outcome == "deny"
    assert decision.reason == "unregistered_capability"
    assert decision.allowed is False
    # The hypothetical new subsystem from Rev2 S7, unregistered:
    decision = F.framework_check(
        "u1", "mood_inference", connection=conn
    )
    assert decision.outcome == "deny"
    # No shadow record: nothing was written for the user.
    assert S.get_stances("u1", connection=conn) == {}
    assert S.stance_history("u1", connection=conn) == []
    rows = conn.execute(
        "SELECT COUNT(*) FROM user_permissions_settings WHERE user_id = 'u1'"
    ).fetchone()[0]
    assert rows == 0


def test_s7_registered_default_dont_produces_nothing_until_stance_set():
    conn = _perm_conn()
    # R2 default is Don't do it: produces nothing with no stance set.
    decision = F.framework_check("u1", "R2", connection=conn)
    assert decision.outcome == "deny"
    assert decision.stance == R.DONT_DO_IT
    # After registration with default Don't do it, still nothing
    # until the user sets a stance (R6, per-commitment default).
    decision = F.framework_check(
        "u1", "R6", scope_rows=["commitment-1"], connection=conn
    )
    assert decision.outcome == "deny"
    # Setting the stance is what unlocks it.
    _set(conn, "u1", "R2", "all", R.JUST_DO_IT)
    decision = F.framework_check("u1", "R2", connection=conn)
    assert decision.outcome == "proceed"
    # R1's stated Ask-me default is the exception: asking is not
    # capturing, so the default asks rather than denying.
    decision = F.framework_check(
        "u1", "R1", scope_rows=["strand:heart"], connection=conn
    )
    assert decision.outcome == "ask"
    assert decision.stance == R.ASK_ME


# ---------------------------------------------------------------------------
# Framework check, per step
# ---------------------------------------------------------------------------


def test_step1_unregistered_fails_closed_even_with_rows():
    conn = _perm_conn()
    decision = F.framework_check(
        "u1", "R7", scope_rows=["strand:heart"], connection=conn
    )
    assert decision.outcome == "deny"
    assert decision.reason == "unregistered_capability"


def test_step2_pause_blocks_new_starts_regardless_of_stance():
    conn = _perm_conn()
    _set(conn, "u1", "R2", "all", R.JUST_DO_IT)
    assert F.framework_check("u1", "R2", connection=conn).outcome == "proceed"
    S.set_pause("u1", True, surface="settings", connection=conn)
    decision = F.framework_check("u1", "R2", connection=conn)
    assert decision.outcome == "deny"
    assert decision.reason == "paused"
    # The underlying stance was not rewritten by pausing.
    assert S.get_stance("u1", "R2", "all", connection=conn)["stance"] == (
        R.JUST_DO_IT
    )
    S.set_pause("u1", False, surface="settings", connection=conn)
    assert F.framework_check("u1", "R2", connection=conn).outcome == "proceed"


def test_step2_pause_cycle_writes_no_stance_history_c4_t4():
    conn = _perm_conn()
    _set(conn, "u1", "R2", "all", R.JUST_DO_IT)
    before_blob = conn.execute(
        "SELECT stances_json FROM user_permissions_settings WHERE user_id = 'u1'"
    ).fetchone()[0]
    before_history = S.stance_history("u1", connection=conn)
    S.set_pause("u1", True, surface="settings", connection=conn)
    S.set_pause("u1", False, surface="settings", connection=conn)
    after_blob = conn.execute(
        "SELECT stances_json FROM user_permissions_settings WHERE user_id = 'u1'"
    ).fetchone()[0]
    assert after_blob == before_blob
    assert S.stance_history("u1", connection=conn) == before_history


def test_pause_existing_instance_and_stance_write_i1():
    conn = _perm_conn()
    _set(conn, "u1", "R1", "strand:heart", R.ASK_ME)
    S.set_pause("u1", True, surface="settings", connection=conn)
    # I.1 rule 1: an already-surfaced ask may be answered while
    # paused, for that instance only.
    decision = F.framework_check(
        "u1",
        "R1",
        scope_rows=["strand:heart"],
        is_existing_instance=True,
        connection=conn,
    )
    assert decision.outcome == "proceed"
    assert decision.instance_only is True
    # I.1 rule 2: a stance write during pause succeeds and is
    # visible — but starts nothing until un-pause.
    _set(conn, "u1", "R1", "strand:heart", R.JUST_DO_IT)
    assert S.get_stance("u1", "R1", "strand:heart", connection=conn)[
        "stance"
    ] == R.JUST_DO_IT
    assert F.framework_check(
        "u1", "R1", scope_rows=["strand:heart"], connection=conn
    ).outcome == "deny"
    S.set_pause("u1", False, surface="settings", connection=conn)
    assert F.framework_check(
        "u1", "R1", scope_rows=["strand:heart"], connection=conn
    ).outcome == "proceed"


def test_step3_most_restrictive_join_across_rows():
    # Pure join.
    assert F.most_restrictive_join([R.JUST_DO_IT, R.DONT_DO_IT]) == (
        R.DONT_DO_IT
    )
    assert F.most_restrictive_join([R.JUST_DO_IT, R.ASK_ME]) == R.ASK_ME
    assert F.most_restrictive_join([R.JUST_DO_IT, R.JUST_DO_IT]) == (
        R.JUST_DO_IT
    )
    assert F.most_restrictive_join([]) == R.DONT_DO_IT
    assert F.most_restrictive_join(["bogus"]) == R.DONT_DO_IT
    # Via the check: one restrictive row constrains the instance.
    conn = _perm_conn()
    _set(conn, "u1", "R1", "strand:heart", R.JUST_DO_IT)
    _set(conn, "u1", "R1", "strand:compass", R.DONT_DO_IT)
    decision = F.framework_check(
        "u1",
        "R1",
        scope_rows=["strand:heart", "strand:compass"],
        connection=conn,
    )
    assert decision.outcome == "deny"
    _set(conn, "u1", "R1", "strand:compass", R.ASK_ME)
    decision = F.framework_check(
        "u1",
        "R1",
        scope_rows=["strand:heart", "strand:compass"],
        connection=conn,
    )
    assert decision.outcome == "ask"
    # An unknown row key fails closed for that row.
    decision = F.framework_check(
        "u1", "R1", scope_rows=["strand:nope"], connection=conn
    )
    assert decision.outcome == "deny"
    # C3: there is no R1/R7 cross-authority join — R7 is not an
    # authority at all, so a strand stance lives in exactly one
    # record (R1), shown once here.
    assert S.get_stance("u1", "R1", "strand:heart", connection=conn)[
        "stance"
    ] == R.JUST_DO_IT


def test_step4_contract_shape_covered_exceeding_never_coverable():
    conn = _perm_conn()
    _set(conn, "u1", "R5", "all", R.JUST_DO_IT)
    contract = F.AuthorizationContract(
        capability="R5",
        recipients=("alice", "bob", "carol"),
        schedule="friday",
    )
    # Covered instance proceeds WITHOUT per-transaction confirmation.
    decision = F.framework_check(
        "u1",
        "R5",
        consequential_class="bounded_send",
        contract=contract,
        instance={"recipients": ["alice", "bob"], "schedule": "friday"},
        connection=conn,
    )
    assert decision.outcome == "proceed"
    assert decision.reason == "contract_covered"
    # Fourth recipient: outside the contract → confirm.
    decision = F.framework_check(
        "u1",
        "R5",
        consequential_class="bounded_send",
        contract=contract,
        instance={"recipients": ["alice", "dave"], "schedule": "friday"},
        connection=conn,
    )
    assert decision.outcome == "confirm"
    assert decision.reason == "consequential_not_covered"
    # No contract at all → confirm.
    decision = F.framework_check(
        "u1",
        "R5",
        consequential_class="bounded_send",
        connection=conn,
    )
    assert decision.outcome == "confirm"
    # A contract with no bounds covers nothing (fail closed).
    decision = F.framework_check(
        "u1",
        "R5",
        consequential_class="bounded_send",
        contract=F.AuthorizationContract(capability="R5"),
        instance={"recipients": ["alice"]},
        connection=conn,
    )
    assert decision.outcome == "confirm"
    # C1.6: a never-coverable class confirms even under Just do it,
    # even with a contract that claims to cover it.
    decision = F.framework_check(
        "u1",
        "R5",
        consequential_class="new_third_party_grant",
        contract=contract,
        instance={"recipients": ["alice"]},
        connection=conn,
    )
    assert decision.outcome == "confirm"
    assert decision.reason == "consequential_never_coverable"
    # Spend cap shape: at cap proceeds, over cap confirms.
    spend = F.AuthorizationContract(
        capability="R5", amount_cap=10.0, period="month"
    )
    assert spend.covers({"amount": 9.0}) is True
    assert spend.covers({"amount": 11.0}) is False


def test_step4_ask_me_still_asks_for_consequential():
    conn = _perm_conn()
    decision = F.framework_check(
        "u1",
        "R1",
        scope_rows=["strand:heart"],
        consequential_class="bounded_send",
        connection=conn,
    )
    assert decision.outcome == "ask"


def test_step5_boundary_crossing_requires_neighbor():
    conn = _perm_conn()
    _set(conn, "u1", "R1", "strand:hands", R.JUST_DO_IT)
    # Neighbor R2 is Don't do it (default) → the act is denied.
    decision = F.framework_check(
        "u1",
        "R1",
        scope_rows=["strand:hands"],
        neighbor_checks=[("R2", None)],
        connection=conn,
    )
    assert decision.outcome == "deny"
    assert decision.reason == "boundary_neighbor_denied"
    # Neighbor authorized → proceeds.
    _set(conn, "u1", "R2", "all", R.JUST_DO_IT)
    decision = F.framework_check(
        "u1",
        "R1",
        scope_rows=["strand:hands"],
        neighbor_checks=[("R2", None)],
        connection=conn,
    )
    assert decision.outcome == "proceed"
    # Neighbor in Ask me → the act asks (its authorization is pending).
    _set(conn, "u1", "R2", "all", R.ASK_ME)
    decision = F.framework_check(
        "u1",
        "R1",
        scope_rows=["strand:hands"],
        neighbor_checks=[("R2", None)],
        connection=conn,
    )
    assert decision.outcome == "ask"
    # Unregistered neighbor fails closed.
    decision = F.framework_check(
        "u1",
        "R1",
        scope_rows=["strand:hands"],
        neighbor_checks=[("R99", None)],
        connection=conn,
    )
    assert decision.outcome == "deny"


# ---------------------------------------------------------------------------
# Stance store: validation, record shape, pause independence
# ---------------------------------------------------------------------------


def test_set_stance_validates_against_registry():
    conn = _perm_conn()
    with pytest.raises(ValueError):
        _set(conn, "u1", "R7", "all", R.JUST_DO_IT)
    with pytest.raises(ValueError):
        _set(conn, "u1", "R4", "mentor", R.ASK_ME)  # R4: no Ask me
    with pytest.raises(ValueError):
        _set(conn, "u1", "R1", "strand:nope", R.ASK_ME)
    # R6 rows are per commitment: any non-empty key is a row.
    record = _set(conn, "u1", "R6", "commitment-42", R.JUST_DO_IT)
    assert record["capability"] == "R6"
    assert record["row_key"] == "commitment-42"
    assert record["stance"] == R.JUST_DO_IT
    assert record["granted_at"] == record["last_changed_at"]
    assert record["surface"] == "settings"
    assert record["does_not_allow"]  # registry text fills the default


def test_set_stance_record_shape_and_idempotent_rewrite():
    conn = _perm_conn()
    first = _set(
        conn,
        "u1",
        "R2",
        "all",
        R.JUST_DO_IT,
        surface="settings",
    )
    # granted_at is set once; a later change keeps it.
    second = _set(conn, "u1", "R2", "all", R.DONT_DO_IT)
    assert second["granted_at"] == first["granted_at"]
    history = S.stance_history("u1", connection=conn)
    assert [(h["old_stance"], h["new_stance"]) for h in history] == [
        (None, R.JUST_DO_IT),
        (R.JUST_DO_IT, R.DONT_DO_IT),
    ]
    # Repeating the current stance is a no-op: no history row.
    _set(conn, "u1", "R2", "all", R.DONT_DO_IT)
    assert len(S.stance_history("u1", connection=conn)) == 2


def test_pause_record_is_independent_of_stances():
    conn = _perm_conn()
    _set(conn, "u1", "R2", "all", R.JUST_DO_IT)
    before_blob = conn.execute(
        "SELECT stances_json FROM user_permissions_settings WHERE user_id = 'u1'"
    ).fetchone()[0]
    before_history = S.stance_history("u1", connection=conn)
    pause = S.set_pause("u1", True, surface="settings", connection=conn)
    assert pause["paused"] is True
    assert pause["paused_at"]
    after_blob = conn.execute(
        "SELECT stances_json FROM user_permissions_settings WHERE user_id = 'u1'"
    ).fetchone()[0]
    assert after_blob == before_blob
    assert S.stance_history("u1", connection=conn) == before_history
    assert S.get_pause("u1", connection=conn)["paused"] is True
    # Reads for unknown users do not create rows.
    assert S.get_pause("ghost", connection=conn)["paused"] is False
    assert S.get_stances("ghost", connection=conn) == {}


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def test_migration_maps_flags_without_reacknowledgement():
    conn = _full_conn(
        {"u1": {"steward_derivation": True, "steward_coordination": False}},
        consent={"u1": (1, "v1", "2026-11-01T00:00:00+00:00")},
    )
    before_flags = conn.execute(
        "SELECT permissions_json FROM user_permissions_settings WHERE user_id = 'u1'"
    ).fetchone()[0]
    written = S.migrate_flags_to_stances("u1", connection=conn)
    assert written == {"R2": R.JUST_DO_IT, "R3": R.DONT_DO_IT}
    assert S.get_stance("u1", "R2", "all", connection=conn)["stance"] == (
        R.JUST_DO_IT
    )
    assert S.get_stance("u1", "R3", "all", connection=conn)["stance"] == (
        R.DONT_DO_IT
    )
    assert S.get_stance("u1", "R2", "all", connection=conn)[
        "surface"
    ] == S.SURFACE_FLAG_MIGRATION
    # No forced re-acknowledgement: consent fields untouched, and the
    # flag blob itself is not rewritten by migration.
    row = conn.execute(
        "SELECT consent_given, consent_version, consent_at, permissions_json "
        "FROM user_permissions_settings WHERE user_id = 'u1'"
    ).fetchone()
    assert (row[0], row[1], row[2]) == (1, "v1", "2026-11-01T00:00:00+00:00")
    assert row[3] == before_flags
    # Re-running is a no-op for already-migrated rows.
    assert S.migrate_flags_to_stances("u1", connection=conn) == {}
    assert len(S.stance_history("u1", connection=conn)) == 2


def test_migration_never_overwrites_a_user_set_stance():
    conn = _full_conn({"u1": {"steward_derivation": True}})
    _set(conn, "u1", "R2", "all", R.ASK_ME)
    written = S.migrate_flags_to_stances("u1", connection=conn)
    assert written == {"R3": R.DONT_DO_IT}
    assert S.get_stance("u1", "R2", "all", connection=conn)["stance"] == (
        R.ASK_ME
    )


def test_migration_unknown_user_is_noop():
    conn = _full_conn()
    assert S.migrate_flags_to_stances("ghost", connection=conn) == {}
    assert conn.execute(
        "SELECT COUNT(*) FROM user_permissions_settings"
    ).fetchone()[0] == 0


def test_migration_existing_users_not_opted_in():
    # All flags off → every migrated stance is Don't do it: nobody
    # gains a Just-do-it authorization from the framework's arrival.
    conn = _full_conn(
        {"u1": {"steward_derivation": False, "steward_coordination": False}}
    )
    written = S.migrate_flags_to_stances("u1", connection=conn)
    assert set(written.values()) == {R.DONT_DO_IT}


# ---------------------------------------------------------------------------
# R3 dead-flag repair: round-trip through the REAL production path
# ---------------------------------------------------------------------------


def test_coordination_flag_survives_write_read_roundtrip(ve_ctx):
    """REGRESSION TEST for the inventory §1.4 dead-flag defect.

    Pre-fix, ``normalize_user_permission_prefs`` filtered to the
    nine-key list, which had no ``steward_coordination`` entry: the
    flag was dropped on write (upsert canonicalizes) AND on read
    (get rewrites the stored blob without it), so the round-trip
    below returned False and ``coordination_allowed`` was always
    False in production. Verified against the pre-fix code path by
    running the pre-fix ``normalize_user_permission_prefs`` from
    the clean 3e5c92f checkout: it drops ``steward_coordination``
    (see the Slice 1 report). Post-fix, the flag round-trips and
    the steward gate reads True through the production row.
    """
    import local_ai.vision_execution.storage as ve_store
    from local_ai.narrative.consent import (
        coordination_allowed,
        steward_coordination_allowed,
    )

    user_id = "u-coord"
    # Direct normalize check: the key survives normalization now.
    assert ve_store.normalize_user_permission_prefs(
        {"steward_coordination": True}
    )["steward_coordination"] is True
    # Full round-trip through upsert → get (the production path).
    ve_store.upsert_user_permissions_settings(
        user_id,
        permissions={
            "steward_derivation": True,
            "steward_coordination": True,
        },
        consent_acknowledged=False,
        consent_version="",
    )
    settings = ve_store.get_user_permissions_settings(user_id)
    assert settings["permissions"]["steward_coordination"] is True
    assert settings["permissions"]["steward_derivation"] is True
    # And the steward gate — which reads the raw blob — now sees it.
    raw = sqlite3.connect(str(ve_ctx._DB_PATH))
    try:
        assert steward_coordination_allowed(user_id, connection=raw) is True
        assert coordination_allowed(user_id, connection=raw) is True
    finally:
        raw.close()


def test_boolean_toggles_keep_working_against_migrated_store(ve_ctx):
    """Slice 1 bound: existing boolean toggles are unaffected."""
    import local_ai.vision_execution.storage as ve_store

    user_id = "u-toggles"
    ve_store.upsert_user_permissions_settings(
        user_id,
        permissions={"behavioral_tracking": True, "steward_derivation": True},
        consent_acknowledged=True,
        consent_version="v1",
    )
    # A stance write must not disturb the flag blob or consent.
    S.set_stance(
        user_id, "R2", "all", R.JUST_DO_IT, surface="settings"
    )
    settings = ve_store.get_user_permissions_settings(user_id)
    assert settings["permissions"]["behavioral_tracking"] is True
    assert settings["permissions"]["steward_derivation"] is True
    assert settings["consent_given"] is True
    assert settings["consent_version"] == "v1"
    # And a flag write must not disturb the stance record.
    ve_store.upsert_user_permissions_settings(
        user_id,
        permissions={"behavioral_tracking": False, "steward_derivation": True},
        consent_acknowledged=True,
        consent_version="v1",
    )
    assert S.get_stance(user_id, "R2", "all")["stance"] == R.JUST_DO_IT
    settings = ve_store.get_user_permissions_settings(user_id)
    assert settings["permissions"]["behavioral_tracking"] is False
