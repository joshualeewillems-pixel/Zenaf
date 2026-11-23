"""Permission Simplification P-2 — the permission home.

Pins the Phase P-2 acceptance criteria and the founder's contract
corrections against the aggregation/write-through layer in
``local_ai.permissions.home`` and the separated write primitives in
vision-execution storage:

1. Consistency contract: a simulated partial-write failure yields
   Custom — out of sync naming the failed control, and Repair (an
   absolute-set re-application) converges; the displayed state at
   every step equals the read-back.
2. No-regression parity: every control reachable in the two legacy
   surfaces is reachable in the home (row inventory diffed
   mechanically — backend flag keys, registry rows, and the legacy
   frontend surface's row keys read from its source).
3. Stored-choice preservation: representative stored states render
   as the stored truth, and a no-op visit writes nothing
   (store-diff assertion).
4. Outside Zenaf: the grouping carries the always-asks classes and
   no standing consents yet; no disclosure control appears inside
   an unrelated intent.
5. Correction 1: critical-subset write ordering (opt-out writes
   critical first, opt-in last) and incomplete-revocation
   reporting — a failed critical opt-out is never reported as a
   completed revocation.
6. Correction 2: a consent-only write leaves permissions_json
   byte-identical; a capability (flags) write never touches the
   consent fields.

Fixture pattern follows tests/test_permission_diagnostics.py: a
real-schema VE database (``init_db``) behind the storage module's
``get_connection`` seam, with connections injected directly.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi import HTTPException

import api.routes.settings_routes as settings_mod
from local_ai.permissions import home, registry, store as stance_store
from local_ai.vision_execution import storage as ve_storage
from local_ai.vision_execution.models import (
    PermissionHomeControlUpdate,
    PermissionHomeGroupUpdate,
)
from local_ai.vision_execution.storage import (
    _USER_PERMISSION_KEYS,
    init_db,
    open_sqlite_with_ve_pragmas,
    record_user_consent,
    update_user_permission_flags,
)

USER = "home-user"


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    c = open_sqlite_with_ve_pragmas(tmp_path / "ve.db")
    init_db(c)
    monkeypatch.setattr(ve_storage, "get_connection", lambda: c)
    yield c
    c.close()


def _seed_row(conn, user_id, *, consent=1, version="permissions-v2", flags=None):
    conn.execute(
        "INSERT INTO user_permissions_settings "
        "(user_id, consent_given, consent_version, consent_at, "
        "permissions_json, updated_at) VALUES (?, ?, ?, NULL, ?, '')",
        (user_id, consent, version, json.dumps(flags or {})),
    )
    conn.commit()


def _raw_row(conn, user_id):
    return conn.execute(
        "SELECT consent_given, consent_version, consent_at, permissions_json "
        "FROM user_permissions_settings WHERE user_id = ?",
        (user_id,),
    ).fetchone()


def _group(state, intent_id, group_id):
    for intent in state["intents"]:
        if intent["id"] == intent_id:
            for group in intent["groups"]:
                if group["id"] == group_id:
                    return group
    raise AssertionError(f"group {intent_id}/{group_id} missing")


def _all_controls(state):
    out = []
    for intent in state["intents"]:
        for group in intent["groups"]:
            out.extend(group["controls"])
        out.extend(intent["granular"])
    return out


# ---------------------------------------------------------------------
# 2. Parity inventory (mechanical diff)
# ---------------------------------------------------------------------


def test_every_flag_reachable_exactly_once(conn):
    state = home.permission_home_state(USER, connection=conn)
    flag_ids = [c["id"] for c in _all_controls(state) if c["kind"] == "flag"]
    assert sorted(flag_ids) == sorted(f"flag:{k}" for k in _USER_PERMISSION_KEYS)
    assert len(flag_ids) == len(set(flag_ids)) == 11


def test_every_registry_row_reachable(conn):
    # An R6 record makes the dynamic Follow Through rows appear.
    stance_store.set_stance(
        USER, "R6", "commitment-1", registry.JUST_DO_IT,
        surface="settings", connection=conn,
    )
    state = home.permission_home_state(USER, connection=conn)
    stance_ids = {
        c["id"] for c in _all_controls(state) if c["kind"] == "stance"
    }
    expected = set()
    for capability_id, entry in registry.CAPABILITIES.items():
        if entry.row_scheme == "enumerated":
            for row in entry.rows:
                expected.add(f"stance:{capability_id}:{row.key}")
        elif capability_id == "R6":
            expected.add("stance:R6:commitment-1")
    assert expected <= stance_ids


def test_legacy_frontend_rows_all_present_in_home(conn):
    """The legacy PermissionsSection's row keys, read from its
    source, are a subset of the home's flag controls."""
    source = Path(
        "frontend/src/settings/sections/PermissionsSection.tsx"
    ).read_text()
    legacy_keys = set(re.findall(r"key: '([a-z_]+)'", source))
    assert len(legacy_keys) == 10  # the legacy surface's flag rows
    state = home.permission_home_state(USER, connection=conn)
    home_keys = {
        c["key"] for c in _all_controls(state) if c["kind"] == "flag"
    }
    assert legacy_keys <= home_keys
    # The one addition the program makes: fellowship_derivation.
    assert home_keys - legacy_keys == {"fellowship_derivation"}


# ---------------------------------------------------------------------
# 3. Stored-choice preservation + no-op visit writes nothing
# ---------------------------------------------------------------------


def _snapshot(conn):
    rows = conn.execute(
        "SELECT * FROM user_permissions_settings ORDER BY user_id"
    ).fetchall()
    history = conn.execute(
        "SELECT COUNT(*) FROM user_permission_stance_history"
    ).fetchone()[0]
    return repr([tuple(r) for r in rows]), history


def test_noop_visit_writes_nothing(conn):
    _seed_row(conn, USER, flags={"steward_derivation": True})
    stance_store.set_stance(
        USER, "R2", "all", registry.JUST_DO_IT,
        surface="settings", connection=conn,
    )
    before = _snapshot(conn)
    home.permission_home_state(USER, connection=conn)
    home.permission_home_state("never-seen-user", connection=conn)
    assert _snapshot(conn) == before


def test_initial_render_equals_stored_truth(conn):
    state = home.permission_home_state("fresh-user", connection=conn)
    # R1's registry default is Ask me; the storage flags are off:
    # the retention layer is truthfully mixed, not tidied.
    retention = _group(state, "remember", "retention")
    assert retention["state"] == "custom"
    assert retention["sync"] == "granularity"
    assert _group(state, "remember", "story")["state"] == "off"
    assert _group(state, "connect", "connect")["state"] == "off"
    # R4/R5 default to Just do it: surfacing is on by default today.
    assert _group(state, "suggest", "suggest")["state"] == "on"
    ft = _group(state, "follow_through", "follow_through")
    assert ft["state"] == "off" and ft["has_rows"] is False

    _seed_row(
        conn,
        "mixed-user",
        flags={
            "personalization": True,
            "interaction_pattern_storage": True,
            "profile_learning": True,
            "steward_derivation": True,
            "fellowship_derivation": True,
            "steward_coordination": True,
        },
    )
    for capability in ("R1", "R2", "R3"):
        rows = (
            [r.key for r in registry.CAPABILITIES[capability].rows]
            if registry.CAPABILITIES[capability].row_scheme == "enumerated"
            else ["all"]
        )
        for row_key in rows:
            stance_store.set_stance(
                "mixed-user", capability, row_key, registry.JUST_DO_IT,
                surface="settings", connection=conn,
            )
    state = home.permission_home_state("mixed-user", connection=conn)
    assert _group(state, "remember", "retention")["state"] == "on"
    assert _group(state, "remember", "story")["state"] == "on"
    assert _group(state, "connect", "connect")["state"] == "on"
    assert state["consent"]["given"] is True


# ---------------------------------------------------------------------
# Write-through: absolute sets, read-back, conjunction (design §3)
# ---------------------------------------------------------------------


def test_group_write_round_trip_and_readback(conn):
    report = home.apply_group_write(USER, "story", "on", connection=conn)
    assert report["read_back_state"] == "on"
    assert report["complete"] is True
    assert report["sync"] == "in_sync"
    assert report["failed_controls"] == []
    # Independent reads agree with the report (not the request).
    _cg, _cv, _ca, blob = _raw_row(conn, USER)
    flags = json.loads(blob)
    assert flags["steward_derivation"] is True
    assert flags["fellowship_derivation"] is True
    record = stance_store.get_stance(USER, "R2", "all", connection=conn)
    assert record["stance"] == registry.JUST_DO_IT

    # Idempotent: re-applying the same absolute set changes nothing.
    again = home.apply_group_write(USER, "story", "on", connection=conn)
    assert again["read_back_state"] == "on" and again["complete"] is True

    report = home.apply_group_write(USER, "story", "off", connection=conn)
    assert report["read_back_state"] == "off"
    assert report["revocation"] == "complete"
    flags = json.loads(_raw_row(conn, USER)[3])
    assert flags["steward_derivation"] is False


def test_connect_writes_flag_and_stance_together(conn):
    home.apply_group_write(USER, "connect", "on", connection=conn)
    flags = json.loads(_raw_row(conn, USER)[3])
    assert flags["steward_coordination"] is True
    record = stance_store.get_stance(USER, "R3", "all", connection=conn)
    assert record["stance"] == registry.JUST_DO_IT


def test_ask_me_target_rejected_where_flags_are_mapped(conn):
    with pytest.raises(ValueError):
        home.apply_group_write(USER, "story", "ask_me", connection=conn)
    with pytest.raises(ValueError):
        home.apply_group_write(USER, "nope", "on", connection=conn)


def test_follow_through_dynamic_rows(conn):
    with pytest.raises(ValueError):
        home.apply_group_write(USER, "follow_through", "on", connection=conn)
    stance_store.set_stance(
        USER, "R6", "commitment-1", registry.DONT_DO_IT,
        surface="settings", connection=conn,
    )
    state = home.permission_home_state(USER, connection=conn)
    ft = _group(state, "follow_through", "follow_through")
    assert ft["has_rows"] is True and ft["state"] == "off"
    report = home.apply_group_write(
        USER, "follow_through", "ask_me", connection=conn
    )
    assert report["read_back_state"] == "ask_me" and report["complete"] is True


# ---------------------------------------------------------------------
# 1 + 5. Partial failure, ordering, incomplete revocation
# ---------------------------------------------------------------------


def _fail_flag(monkeypatch, failing_key):
    original = home._apply_flag

    def flaky(user_id, key, on, *, connection=None):
        if key == failing_key:
            raise RuntimeError("forced failure")
        return original(user_id, key, on, connection=connection)

    monkeypatch.setattr(home, "_apply_flag", flaky)
    return original


def test_partial_failure_out_of_sync_and_repair_converges(conn, monkeypatch):
    _fail_flag(monkeypatch, "steward_derivation")
    report = home.apply_group_write(USER, "story", "on", connection=conn)
    assert report["read_back_state"] == "custom"
    assert report["sync"] == "out_of_sync"
    assert report["failed_controls"] == ["flag:steward_derivation"]
    assert report["write_errors"] == {
        "flag:steward_derivation": "RuntimeError"
    }
    assert report["complete"] is False
    assert report["repair"] == {"group": "story", "state": "on"}
    # The controls that could write, did (read-back truth).
    flags = json.loads(_raw_row(conn, USER)[3])
    assert flags["fellowship_derivation"] is True
    assert flags["steward_derivation"] is False

    # Repair: re-apply the declared target; absolute sets converge.
    monkeypatch.undo()
    repaired = home.apply_group_write(USER, "story", "on", connection=conn)
    assert repaired["read_back_state"] == "on"
    assert repaired["sync"] == "in_sync" and repaired["complete"] is True


def test_failed_critical_optout_is_an_incomplete_revocation(conn, monkeypatch):
    home.apply_group_write(USER, "story", "on", connection=conn)
    _fail_flag(monkeypatch, "steward_derivation")
    report = home.apply_group_write(USER, "story", "off", connection=conn)
    # Never reported as withdrawn: the critical flag is still on.
    assert report["revocation"] == "incomplete"
    assert report["complete"] is False
    assert report["still_on"] == ["flag:steward_derivation"]
    assert report["sync"] == "out_of_sync"


def test_critical_subset_write_ordering(conn, monkeypatch):
    calls: list[tuple[str, str]] = []
    original_flag = home._apply_flag
    original_stance = home._apply_stance

    def rec_flag(user_id, key, on, *, connection=None):
        calls.append(("flag", key))
        return original_flag(user_id, key, on, connection=connection)

    def rec_stance(user_id, capability, row_key, stance, *, connection=None):
        calls.append(("stance", capability))
        return original_stance(
            user_id, capability, row_key, stance, connection=connection
        )

    monkeypatch.setattr(home, "_apply_flag", rec_flag)
    monkeypatch.setattr(home, "_apply_stance", rec_stance)

    home.apply_group_write(USER, "story", "on", connection=conn)
    # Opt-in: presentational (stance) first, critical (flags) last.
    assert calls.index(("stance", "R2")) < calls.index(
        ("flag", "steward_derivation")
    )
    calls.clear()
    home.apply_group_write(USER, "story", "off", connection=conn)
    # Opt-out: critical (flags) first, presentational last.
    assert calls.index(("flag", "steward_derivation")) < calls.index(
        ("stance", "R2")
    )


# ---------------------------------------------------------------------
# 6. Correction 2: separated writes
# ---------------------------------------------------------------------


def test_consent_only_write_preserves_permissions_json_byte_identical(conn):
    # A deliberately non-normalized stored blob: partial, compact,
    # unsorted — any normalization rewrite would change the bytes.
    blob = '{"steward_derivation": true}'
    _seed_row(conn, USER, consent=0, version="", flags=None)
    conn.execute(
        "UPDATE user_permissions_settings SET permissions_json = ? WHERE user_id = ?",
        (blob, USER),
    )
    conn.commit()
    result = record_user_consent(
        USER, consent_given=True, consent_version="permissions-v2",
        connection=conn,
    )
    row = _raw_row(conn, USER)
    assert row[3] == blob  # byte-identical
    assert row[0] == 1 and row[1] == "permissions-v2" and row[2] is not None
    assert result["permissions"]["steward_derivation"] is True


def test_consent_only_write_requires_version_when_acknowledging(conn):
    with pytest.raises(ValueError):
        record_user_consent(USER, consent_given=True, consent_version="",
                            connection=conn)


def test_capability_write_never_touches_consent_fields(conn):
    _seed_row(conn, USER, consent=1, version="permissions-v2")
    before = _raw_row(conn, USER)
    update_user_permission_flags(
        USER, {"personalization": True}, connection=conn
    )
    after = _raw_row(conn, USER)
    assert after[:3] == before[:3]  # consent_given/version/at unchanged
    assert json.loads(after[3])["personalization"] is True
    # And through the home's group write path as well.
    home.apply_group_write(USER, "connect", "on", connection=conn)
    assert _raw_row(conn, USER)[:3] == before[:3]


# ---------------------------------------------------------------------
# Granular control writes + the fellowship row
# ---------------------------------------------------------------------


def test_control_write_round_trips(conn):
    control = home.apply_control_write(
        USER, "flag:aspiration_use_in_guidance", True, connection=conn
    )
    assert control["state"] == "on"
    control = home.apply_control_write(
        USER, "stance:R4:mentor", registry.DONT_DO_IT, connection=conn
    )
    assert control["stance"] == registry.DONT_DO_IT
    with pytest.raises(ValueError):
        home.apply_control_write(USER, "flag:nope", True, connection=conn)
    with pytest.raises(ValueError):
        home.apply_control_write(
            USER, "flag:personalization", "yes", connection=conn
        )
    with pytest.raises(ValueError):
        home.apply_control_write(USER, "widget:x", True, connection=conn)


def test_fellowship_row_present_and_writes(conn):
    # The row's wording was founder-ruled 2026-11-22 and lives with
    # the surface copy; no control is wording-pending anymore.
    state = home.permission_home_state(USER, connection=conn)
    story = _group(state, "remember", "story")
    fellowship = next(
        c for c in story["controls"] if c["id"] == "flag:fellowship_derivation"
    )
    assert fellowship["wording_pending"] is False
    assert all(
        c["wording_pending"] is False for c in _all_controls(state)
    )
    control = home.apply_control_write(
        USER, "flag:fellowship_derivation", True, connection=conn
    )
    assert control["state"] == "on"


# ---------------------------------------------------------------------
# 4. Outside Zenaf + diagnostics adoption
# ---------------------------------------------------------------------


def test_outside_zenaf_grouping(conn):
    state = home.permission_home_state(USER, connection=conn)
    outside = state["outside_zenaf"]
    assert outside["always_asks"] == ["train", "publish", "share", "spend", "execute"]
    assert outside["standing_consents"] == []
    # No disclosure-shaped control hides inside an intent: the only
    # controls are the mapped flags and stances of the inventory.
    kinds = {c["kind"] for c in _all_controls(state)}
    assert kinds == {"flag", "stance"}


def test_story_group_carries_p1_diagnostics(conn):
    _seed_row(
        conn, USER, consent=1, version="permissions-v2",
        flags={"steward_derivation": True},
    )
    state = home.permission_home_state(USER, connection=conn)
    story = _group(state, "remember", "story")
    assert story["diagnostics"]["derivation"]["state"] == "available"
    assert story["diagnostics"]["candidate_capture"]["state"] == "available"


# ---------------------------------------------------------------------
# Rollout control + routes
# ---------------------------------------------------------------------


def test_rollout_flag_disables_home(conn, monkeypatch):
    monkeypatch.setenv("ZENAF_PERMISSION_HOME", "0")
    assert home.permission_home_state(USER, connection=conn) == {"enabled": False}
    with pytest.raises(HTTPException) as excinfo:
        settings_mod.put_permission_home_group(
            PermissionHomeGroupUpdate(group="story", state="on"),
            current_user={"id": USER},
        )
    assert excinfo.value.status_code == 404


def test_routes_round_trip(conn, monkeypatch):
    monkeypatch.delenv("ZENAF_PERMISSION_HOME", raising=False)
    state = settings_mod.get_permission_home(current_user={"id": USER})
    assert state["enabled"] is True
    response = settings_mod.put_permission_home_group(
        PermissionHomeGroupUpdate(group="connect", state="on"),
        current_user={"id": USER},
    )
    assert response["write"]["read_back_state"] == "on"
    assert _group(response["state"], "connect", "connect")["state"] == "on"
    response = settings_mod.put_permission_home_control(
        PermissionHomeControlUpdate(
            control="flag:behavioral_tracking", value=True
        ),
        current_user={"id": USER},
    )
    assert response["write"]["control"]["state"] == "on"
    with pytest.raises(HTTPException) as excinfo:
        settings_mod.put_permission_home_group(
            PermissionHomeGroupUpdate(group="bogus", state="on"),
            current_user={"id": USER},
        )
    assert excinfo.value.status_code == 400
    with pytest.raises(HTTPException) as excinfo:
        settings_mod.get_permission_home(current_user={"id": "  "})
    assert excinfo.value.status_code == 404
