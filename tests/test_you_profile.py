"""Per-seat "You" profiles — the Zenaf/You switch's durable record + QC read.

Semantics under test (Joshua's correction, 2026-10-19): keystone 4 gates
exactly two things — (a) the identity REVEAL (the character card's
name/face/presentation) and (b) rentability. The switch, the QC surface,
and this record are open from day one; training runs continuously per user
approval.

Covers:
- store CRUD: upsert/get/partial-update/clear/delete, per-user isolation,
  idempotent re-upsert, input validation
- recognition is DERIVED from keystone tasks (never stored): unseeded ->
  unmet; 1-3 keystones Done -> meeting; "The echo" Done -> recognized +
  rentable (rentability is the one hard gate alongside the reveal)
- writes are NOT gated: the echo can be named/pinned before keystone 4;
  GET reports revealed=False while unmet, revealed=True after
- reference-not-duplicate: the you_profiles table carries only identity
  fields + pointers; depth/signals/persona/snapshot data is composed live
  from its ground-truth store on read (a read performs no writes, and a
  later publish is visible without touching the you store)
- API: route functions return the composed payload shape; PUT succeeds
  before and after keystone 4; 404 on unknown archetype
"""

from __future__ import annotations

import threading

import pytest
from fastapi import HTTPException

from local_ai.council import archetypes, keystones as KD
from local_ai.vision_execution import keystone_seeding
from local_ai.vision_execution import models as M
from local_ai.vision_execution import service as ve
from local_ai.you_profile import service as ysvc  # noqa: F401  (import sanity)
from local_ai.you_profile.service import YouProfileService, keystone_progress
from local_ai.you_profile.store import YouProfileStore

ALL_KEYSTONES = ["First meeting", "Strengths", "Weaknesses", "The echo"]


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    """Isolate the vision-execution SQLite DB per test (test_keystones pattern)."""
    import local_ai.vision_execution.storage as ve_store

    monkeypatch.setattr(ve_store, "_DB_PATH", tmp_path / "ve.db")
    monkeypatch.setattr(ve_store, "_DB_DIR", tmp_path)
    monkeypatch.setattr(ve_store, "_init_done_paths", set())
    monkeypatch.setattr(ve_store, "_thread_local", threading.local())
    return {}


@pytest.fixture()
def api_ctx(tmp_path, monkeypatch):
    """Isolate every store the default service touches (API-level tests)."""
    monkeypatch.setattr(
        "local_ai.you_profile.store.DEFAULT_DB_PATH", tmp_path / "you.db"
    )
    monkeypatch.setattr(
        "local_ai.personality.store.DEFAULT_DB_PATH", tmp_path / "personality.db"
    )
    monkeypatch.setattr(
        "local_ai.council.naming._load_approved_signals", lambda: []
    )
    return {}


def _svc(tmp_path, signals=None):
    from local_ai.personality.store import PersonalityStore

    return YouProfileService(
        you_store=YouProfileStore(tmp_path / "you.db"),
        personality_store_factory=lambda uid: PersonalityStore(
            db_path=tmp_path / "personality.db", user_id=uid
        ),
        signals_provider=(lambda: signals if signals is not None else []),
    )


def _make_signal(signal_id, zone="values", valence="endorsed", status="approved"):
    from local_ai.presence_ingest.schema import TrainingSignal

    return TrainingSignal(
        signal_id=signal_id,
        ts_ms=1_700_000_000_000,
        layer="guidance",
        zone=zone,
        actor="u1",
        summary="Holds two truths lightly instead of rushing to decide.",
        payload_redacted="Said: I can see why both sides need this.",
        valence=valence,
        kind="distilled",
        provenance={"source": "import"},
        status=status,
    )


def _complete_task_by_title(user_id, archetype_id, title):
    for project in ve.list_projects(user_id):
        for task in ve.list_tasks(user_id, project_id=project["id"]):
            if task.get("seat_ref") == archetype_id and task.get("title") == title:
                return ve.update_task(
                    task["id"], M.TaskUpdate(status="Done"), user_id
                )
    raise AssertionError(f"task {title!r} not found for {archetype_id}")


def _complete_all_keystones(user_id, archetype_id):
    for title in ALL_KEYSTONES:
        _complete_task_by_title(user_id, archetype_id, title)


# ------------------------------------------------------------ store CRUD


def test_store_upsert_get_roundtrip(tmp_path):
    store = YouProfileStore(tmp_path / "you.db")
    assert store.get("u1", "conductor") is None
    row = store.upsert("u1", "conductor", personal_name="Arranger", avatar_ref="asset-9")
    assert row["user_id"] == "u1"
    assert row["archetype_id"] == "conductor"
    assert row["personal_name"] == "Arranger"
    assert row["avatar_ref"] == "asset-9"
    assert store.get("u1", "conductor") == row
    store.close()


def test_store_partial_update_and_clear(tmp_path):
    store = YouProfileStore(tmp_path / "you.db")
    store.upsert("u1", "mentor", personal_name="Tender", avatar_ref="asset-1")
    row = store.upsert("u1", "mentor", avatar_ref="asset-2")
    # Untouched field preserved.
    assert row["personal_name"] == "Tender"
    assert row["avatar_ref"] == "asset-2"
    # Explicit None clears.
    row = store.upsert("u1", "mentor", avatar_ref=None)
    assert row["avatar_ref"] is None
    assert row["personal_name"] == "Tender"
    store.close()


def test_store_idempotent_and_isolated(tmp_path):
    store = YouProfileStore(tmp_path / "you.db")
    first = store.upsert("u1", "mentor", personal_name="Tender")
    second = store.upsert("u1", "mentor", personal_name="Tender")
    assert first["created_at"] == second["created_at"]
    assert store.get("u2", "mentor") is None  # per-user isolation
    assert len(store.list_for_user("u1")) == 1
    assert store.delete("u1", "mentor") is True
    assert store.delete("u1", "mentor") is False  # second delete is a no-op
    store.close()


def test_store_validation(tmp_path):
    store = YouProfileStore(tmp_path / "you.db")
    with pytest.raises(ValueError):
        store.upsert("u1", "mentor", personal_name="x" * 61)
    with pytest.raises(ValueError):
        store.upsert("u1", "mentor", personal_name=123)
    store.close()


# ----------------------------------------------- recognition from keystones


def test_recognition_unseeded(ve_ctx):
    progress = keystone_progress("nobody", "conductor")
    assert progress["seeded"] is False
    assert progress["status"] == "unmet"
    assert progress["rentable"] is False
    assert progress["completed"] == 0


def test_recognition_progresses_with_tasks(ve_ctx):
    user = ve.create_user_account("ally@example.com", "pw", "Ally")
    uid = user["id"]
    keystone_seeding.seed_meet_your_council(uid)

    progress = keystone_progress(uid, "conductor")
    assert progress["seeded"] is True
    assert progress["status"] == "unmet"
    assert [k["title"] for k in progress["keystones"]] == ALL_KEYSTONES

    _complete_task_by_title(uid, "conductor", "First meeting")
    _complete_task_by_title(uid, "conductor", "Strengths")
    progress = keystone_progress(uid, "conductor")
    assert progress["status"] == "meeting"
    assert progress["completed"] == 2
    assert progress["rentable"] is False

    _complete_task_by_title(uid, "conductor", "Weaknesses")
    _complete_task_by_title(uid, "conductor", "The echo")
    progress = keystone_progress(uid, "conductor")
    assert progress["status"] == "recognized"
    assert progress["completed"] == 4
    assert progress["echo_complete"] is True
    assert progress["rentable"] is True


def test_recognition_is_per_seat(ve_ctx):
    user = ve.create_user_account("solo@example.com", "pw", "Solo")
    uid = user["id"]
    keystone_seeding.seed_meet_your_council(uid)
    _complete_all_keystones(uid, "mentor")
    assert keystone_progress(uid, "mentor")["status"] == "recognized"
    assert keystone_progress(uid, "conductor")["status"] == "unmet"


# -------------------------------------- writes open; reveal is the only gate


def test_writes_open_before_keystone4(ve_ctx, tmp_path):
    """The record is writable from day one. What keystone 4 withholds is the
    REVEAL (revealed=False) and rentability — not the data."""
    user = ve.create_user_account("new@example.com", "pw", "New")
    uid = user["id"]
    keystone_seeding.seed_meet_your_council(uid)
    svc = _svc(tmp_path)

    record = svc.update_profile(uid, "conductor", personal_name="Arranger")
    assert record["personal_name"] == "Arranger"

    profile = svc.get_profile(uid, "conductor")
    assert profile["you"]["revealed"] is False
    assert profile["you"]["state"] == "unmet"
    # The user's own record reads back — the gate is presentational.
    assert profile["you"]["personal_name"] == "Arranger"
    assert profile["recognition"]["rentable"] is False


def test_reveal_after_keystone4(ve_ctx, tmp_path):
    user = ve.create_user_account("met@example.com", "pw", "Met")
    uid = user["id"]
    keystone_seeding.seed_meet_your_council(uid)
    svc = _svc(tmp_path)
    svc.update_profile(uid, "conductor", personal_name="Arranger")
    _complete_all_keystones(uid, "conductor")

    profile = svc.get_profile(uid, "conductor")
    assert profile["you"]["revealed"] is True
    assert profile["you"]["state"] == "recognized"
    assert profile["you"]["personal_name"] == "Arranger"
    assert profile["you"]["mode"] == "trained"
    assert profile["zenaf"]["mode"] == "base"
    assert profile["zenaf"]["character"] == "Weaver"
    assert profile["recognition"]["rentable"] is True


def test_snapshot_pin_must_resolve(ve_ctx, tmp_path):
    user = ve.create_user_account("pin@example.com", "pw", "Pin")
    uid = user["id"]
    keystone_seeding.seed_meet_your_council(uid)
    svc = _svc(tmp_path)
    with pytest.raises(ValueError):
        svc.update_profile(uid, "conductor", current_snapshot_id="ps_does-not-exist")


# -------------------------------------------- reference, never duplication


def test_you_db_holds_no_payload_data(tmp_path):
    """The you_profiles table must stay a pointer/index table — any
    signal/snapshot/persona payload column here is a design violation."""
    store = YouProfileStore(tmp_path / "you.db")
    store.upsert("u1", "conductor", personal_name="Arranger")
    cols = {
        r[1]
        for r in store._conn.execute("PRAGMA table_info(you_profiles)").fetchall()
    }
    assert cols <= {
        "user_id",
        "archetype_id",
        "personal_name",
        "avatar_ref",
        "current_snapshot_id",
        "created_at",
        "updated_at",
    }, cols
    store.close()


def test_read_performs_no_writes(tmp_path):
    svc = _svc(tmp_path)
    svc.get_profile("ghost", "skeptic")
    # A read composes from other stores; the you store stays untouched.
    you_store = YouProfileStore(tmp_path / "you.db")
    assert you_store.list_for_user("ghost") == []
    you_store.close()


def test_persona_version_reflects_live_without_write(ve_ctx, tmp_path):
    """Publish a profile version AFTER the last you-store write; GET must
    reflect it — proof the version is a live reference, not a copied value."""
    from local_ai.personality.schema import CandidateOp, ProfileCandidate
    from local_ai.personality.store import PersonalityStore

    user = ve.create_user_account("pub@example.com", "pw", "Pub")
    uid = user["id"]
    keystone_seeding.seed_meet_your_council(uid)
    _complete_all_keystones(uid, "conductor")

    pers_db = tmp_path / "personality.db"
    pstore = PersonalityStore(db_path=pers_db, user_id=uid)
    pstore.propose(
        ProfileCandidate(
            candidate_id="pc_1",
            user_id=uid,
            ops=[
                CandidateOp(
                    field="voice.description", op="set", value="calm and direct"
                )
            ],
            source="manual",
            rationale="first version",
        )
    )
    pstore.publish(["pc_1"], source_summary="first version")
    snap = pstore.create_snapshot(trigger="manual", note="era one")
    pstore.close()

    svc = YouProfileService(
        you_store=YouProfileStore(tmp_path / "you.db"),
        personality_store_factory=lambda u: PersonalityStore(
            db_path=pers_db, user_id=u
        ),
        signals_provider=lambda: [],
    )
    profile = svc.get_profile(uid, "conductor")
    assert profile["fashioning"]["persona_version"] == 1
    assert profile["fashioning"]["persona_version_count"] == 1
    assert (
        profile["fashioning"]["snapshots"][0]["snapshot_id"] == snap.snapshot_id
    )
    # The version number was never copied into the you store.
    assert svc._you_store.get(uid, "conductor") is None

    # Pinning the snapshot stores only the id (a pointer).
    svc.update_profile(uid, "conductor", current_snapshot_id=snap.snapshot_id)
    profile = svc.get_profile(uid, "conductor")
    assert profile["you"]["current_snapshot_id"] == snap.snapshot_id
    assert profile["you"]["pinned_snapshot"]["snapshot_id"] == snap.snapshot_id
    assert "profile_json" not in profile["you"]["pinned_snapshot"]


# --------------------------------------------------- signal QC composition


def test_seat_signals_map_by_contribution(ve_ctx, tmp_path):
    compass_sig = _make_signal("s1", zone="values")  # -> 'self'/Compass strand
    body_sig = _make_signal("s2", zone="craft bench")  # -> 'body'/Hands strand
    rejected_sig = _make_signal("s3", zone="my values", valence="rejected")
    svc = _svc(tmp_path, signals=[compass_sig, body_sig, rejected_sig])

    user = ve.create_user_account("qc@example.com", "pw", "QC")
    profile = svc.get_profile(user["id"], "conductor")
    signals = profile["fashioning"]["approved_signals"]

    by_id = {s["signal_id"]: s for s in signals}
    # Conductor: Compass 0.25 > Hands 0.10 — Compass-backed signals rank first.
    assert list(by_id) == ["s1", "s3", "s2"]
    assert by_id["s1"]["contribution"] == 0.25
    assert by_id["s3"]["is_divergence"] is True
    assert by_id["s1"]["is_divergence"] is False
    # The anchor is the redacted text the reading rests on.
    assert by_id["s1"]["anchor"] == "Said: I can see why both sides need this."
    assert profile["fashioning"]["signal_total"] == 3


def test_seat_signals_honest_zero(tmp_path):
    svc = _svc(tmp_path, signals=[])
    profile = svc.get_profile("ghost", "maverick")
    assert profile["fashioning"]["approved_signals"] == []
    assert profile["fashioning"]["signal_total"] == 0


# ------------------------------------------------------------------ API


def test_api_get_shape_and_unknown_seat(ve_ctx, api_ctx):
    import api.routes.you_profile_routes as routes

    user = ve.create_user_account("api@example.com", "pw", "API")
    with pytest.raises(HTTPException) as exc_info:
        routes.get_you_profile("not-a-seat", user={"id": user["id"]})
    assert exc_info.value.status_code == 404

    payload = routes.get_you_profile("conductor", user={"id": user["id"]})
    assert set(payload) == {
        "archetype_id",
        "zenaf",
        "you",
        "recognition",
        "fashioning",
    }
    assert payload["zenaf"]["mode"] == "base"
    assert payload["you"]["mode"] == "trained"
    assert payload["you"]["revealed"] is False


def test_api_put_open_and_roundtrip(ve_ctx, api_ctx):
    import api.routes.you_profile_routes as routes

    user = ve.create_user_account("api2@example.com", "pw", "API2")
    uid = user["id"]
    keystone_seeding.seed_meet_your_council(uid)

    # PUT before keystone 4 succeeds — the record is not gated.
    result = routes.update_you_profile(
        "conductor",
        routes.YouProfileUpdate(personal_name="Arranger"),
        user={"id": uid},
    )
    assert result["ok"] is True
    assert result["record"]["personal_name"] == "Arranger"

    payload = routes.get_you_profile("conductor", user={"id": uid})
    assert payload["you"]["revealed"] is False
    assert payload["you"]["personal_name"] == "Arranger"
    assert payload["recognition"]["rentable"] is False

    # After the recognition keystone, the reveal flips; rentability too.
    _complete_all_keystones(uid, "conductor")
    payload = routes.get_you_profile("conductor", user={"id": uid})
    assert payload["you"]["revealed"] is True
    assert payload["you"]["personal_name"] == "Arranger"
    assert payload["recognition"]["rentable"] is True


def test_unknown_archetype_service_errors(tmp_path):
    svc = _svc(tmp_path)
    with pytest.raises(ValueError):
        svc.get_profile("u1", "not-a-seat")
    with pytest.raises(ValueError):
        svc.update_profile("u1", "not-a-seat", personal_name="X")
