"""Phase 5: temporal modeling — signal decay, snapshots, era addressing.

Covers local_ai/personality/temporal.py, the snapshot methods on
PersonalityStore, and api/routes/personality_temporal_routes.py.

Standing rules under test: decay never deletes; snapshots are insert-only
(no update/delete path exists); no silent mutation (only the three
sanctioned triggers create snapshots); per-user scoping everywhere.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from local_ai.personality.store import PersonalityStore
from local_ai.personality.temporal import (
    ANNUAL_SNAPSHOT_DAYS,
    CORROBORATION_WEIGHT,
    SIGNAL_HALF_LIFE_DAYS,
    SNAPSHOT_TRIGGER_ANNUAL,
    SNAPSHOT_TRIGGER_MANUAL,
    SNAPSHOT_TRIGGER_VOLUME,
    VOLUME_TRIGGER_VERSIONS,
    find_parallels,
    rank_signals_by_relevance,
    run_temporal_maintenance,
    signal_relevance,
)
from local_ai.presence_ingest.schema import TrainingSignal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _store(tmp_path, user_id="u1"):
    return PersonalityStore(db_path=tmp_path / f"{user_id or 'anon'}_{uuid.uuid4().hex[:6]}.db",
                            user_id=user_id)


def _publish_version(store, tag):
    from local_ai.personality.schema import CandidateOp, ProfileCandidate

    op = CandidateOp(op="add", field="heuristics", value=tag)
    cand = ProfileCandidate(
        candidate_id=f"pc_{uuid.uuid4().hex[:8]}",
        user_id=store.user_id or "",
        strand_key="self",
        ops=[op],
        source="manual",
    )
    store.propose(cand)
    return store.publish([cand.candidate_id])


def _signal(sid, age_days=0.0, layer="decision", zone="self", now=None):
    now = now or datetime.now(timezone.utc)
    ts = int((now - timedelta(days=age_days)).timestamp() * 1000)
    return TrainingSignal(
        signal_id=sid, ts_ms=ts, layer=layer, zone=zone, actor="u1", summary="s",
        valence="observed",
    )


# ---------------------------------------------------------------------------
# Signal decay
# ---------------------------------------------------------------------------


def test_fresh_signal_has_full_relevance():
    s = _signal("a", age_days=0)
    assert signal_relevance(s) == pytest.approx(1.0)


def test_fresh_beats_old():
    now = datetime.now(timezone.utc)
    fresh = _signal("a", age_days=1, now=now)
    old = _signal("b", age_days=400, now=now)
    assert signal_relevance(fresh, now=now) > signal_relevance(old, now=now)
    # Half-life math: ~180d -> 0.5; 360d -> 0.25
    assert signal_relevance(_signal("c", age_days=SIGNAL_HALF_LIFE_DAYS, now=now), now=now) == pytest.approx(0.5, rel=0.01)


def test_corroborated_beats_lonely():
    now = datetime.now(timezone.utc)
    lonely = _signal("a", age_days=200, now=now)
    supported = _signal("b", age_days=200, now=now)
    fresh_parallel = _signal("p", age_days=2, now=now)
    assert find_parallels(supported, [fresh_parallel]) == [fresh_parallel]
    r_lonely = signal_relevance(lonely, [], now=now)
    r_supported = signal_relevance(supported, [fresh_parallel], now=now)
    assert r_supported > r_lonely
    # A fresh parallel recharges close to CORROBORATION_WEIGHT on top of base.
    assert r_supported == pytest.approx(min(1.0, r_lonely + CORROBORATION_WEIGHT * 0.5 ** (2 / SIGNAL_HALF_LIFE_DAYS)), rel=0.01)


def test_stale_parallel_boosts_less_than_fresh():
    now = datetime.now(timezone.utc)
    old = _signal("a", age_days=200, now=now)
    fresh_p = _signal("pf", age_days=1, now=now)
    stale_p = _signal("ps", age_days=300, now=now)
    assert signal_relevance(old, [fresh_p], now=now) > signal_relevance(old, [stale_p], now=now)


def test_parallels_require_same_layer_and_zone():
    now = datetime.now(timezone.utc)
    s = _signal("a", age_days=100, layer="decision", zone="self", now=now)
    other_zone = _signal("b", age_days=1, layer="decision", zone="word", now=now)
    other_layer = _signal("c", age_days=1, layer="behavior", zone="self", now=now)
    same = _signal("d", age_days=1, layer="decision", zone="self", now=now)
    assert find_parallels(s, [other_zone, other_layer, same]) == [same]
    base = signal_relevance(s, [], now=now)
    # signal_relevance takes pre-filtered parallels; non-parallels add nothing.
    assert signal_relevance(s, find_parallels(s, [other_zone, other_layer]), now=now) == pytest.approx(base)


def test_relevance_bounded_and_positive():
    now = datetime.now(timezone.utc)
    for age in (0, 30, 365, 3650):
        r = signal_relevance(_signal("a", age_days=age, now=now), now=now)
        assert 0.0 < r <= 1.0
    # Even many parallels can't push past 1.0.
    s = _signal("a", age_days=0, now=now)
    pals = [_signal(f"p{i}", age_days=0, now=now) for i in range(10)]
    assert signal_relevance(s, pals, now=now) == pytest.approx(1.0)


def test_decay_never_deletes_or_reorders_input():
    now = datetime.now(timezone.utc)
    signals = [_signal(f"s{i}", age_days=i * 60, now=now) for i in range(5)]
    before = [s.signal_id for s in signals]
    ranked = rank_signals_by_relevance(signals, now=now)
    # Nothing dropped, input untouched.
    assert len(ranked) == 5
    assert [s.signal_id for s in signals] == before
    # Ranked highest-relevance first.
    rels = [r for _, r in ranked]
    assert rels == sorted(rels, reverse=True)
    assert ranked[0][0].signal_id == "s0"  # freshest first


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------


def test_manual_snapshot_archives_current_version(tmp_path):
    s = _store(tmp_path)
    _publish_version(s, "h1")
    snap = s.create_snapshot(trigger=SNAPSHOT_TRIGGER_MANUAL, era_name="early Zenaf era", note="n")
    assert snap.version == 1
    assert snap.trigger == "manual"
    assert snap.era_name == "early Zenaf era"
    assert snap.note == "n"
    assert "v1" in snap.auto_label and "manual" in snap.auto_label
    assert snap.user_id == "u1"
    # Full immutable payload archived.
    import json

    payload = json.loads(snap.profile_json)
    assert payload["version"] == 1
    assert "h1" in payload["strands"]["self"]["heuristics"]


def test_snapshot_is_frozen(tmp_path):
    s = _store(tmp_path)
    _publish_version(s, "h1")
    snap = s.create_snapshot(trigger=SNAPSHOT_TRIGGER_MANUAL)
    with pytest.raises(Exception):
        snap.version = 99  # type: ignore[misc]


def test_no_update_or_delete_path_for_snapshots(tmp_path):
    s = _store(tmp_path)
    assert not hasattr(s, "update_snapshot")
    assert not hasattr(s, "delete_snapshot")
    assert not hasattr(s, "remove_snapshot")


def test_create_snapshot_needs_published_profile(tmp_path):
    s = _store(tmp_path)
    with pytest.raises(ValueError, match="no published profile version"):
        s.create_snapshot(trigger=SNAPSHOT_TRIGGER_MANUAL)


def test_create_snapshot_rejects_bad_trigger(tmp_path):
    s = _store(tmp_path)
    _publish_version(s, "h1")
    with pytest.raises(ValueError, match="unknown snapshot trigger"):
        s.create_snapshot(trigger="whenever")


def test_duplicate_era_name_raises(tmp_path):
    s = _store(tmp_path)
    _publish_version(s, "h1")
    s.create_snapshot(trigger=SNAPSHOT_TRIGGER_MANUAL, era_name="era one")
    with pytest.raises(ValueError, match="already used"):
        s.create_snapshot(trigger=SNAPSHOT_TRIGGER_MANUAL, era_name="era one")
    # ...but the same era name is fine for a different user.
    s2 = _store(tmp_path, "u2")
    _publish_version(s2, "h1")
    s2.create_snapshot(trigger=SNAPSHOT_TRIGGER_MANUAL, era_name="era one")


def test_era_retrieval_by_id_and_name(tmp_path):
    s = _store(tmp_path)
    _publish_version(s, "h1")
    snap = s.create_snapshot(trigger=SNAPSHOT_TRIGGER_MANUAL, era_name="early Zenaf era")
    assert s.get_snapshot(snap.snapshot_id).snapshot_id == snap.snapshot_id
    assert s.get_snapshot_by_era("early Zenaf era").snapshot_id == snap.snapshot_id
    assert s.get_snapshot("nope") is None
    assert s.get_snapshot_by_era("nope") is None
    assert s.get_snapshot_by_era("") is None


def test_list_snapshots_metadata(tmp_path):
    s = _store(tmp_path)
    _publish_version(s, "h1")
    _publish_version(s, "h2")
    s.create_snapshot(trigger=SNAPSHOT_TRIGGER_MANUAL, era_name="one")
    s.create_snapshot(trigger=SNAPSHOT_TRIGGER_MANUAL)
    metas = s.list_snapshots()
    assert len(metas) == 2
    assert metas[0]["era_name"] == "one"
    assert metas[1]["era_name"] is None
    # Metadata only — no full payloads.
    assert "profile_json" not in metas[0]


def test_volume_trigger_threshold(tmp_path):
    s = _store(tmp_path)
    for i in range(VOLUME_TRIGGER_VERSIONS - 1):
        _publish_version(s, f"h{i}")
    assert s.check_volume_trigger() is False
    _publish_version(s, "h-final")
    assert s.check_volume_trigger() is True
    snap, created = s.ensure_snapshot(SNAPSHOT_TRIGGER_VOLUME)
    assert created is True
    assert snap.trigger == "volume"
    assert snap.version == VOLUME_TRIGGER_VERSIONS
    # After archiving, the counter resets — no immediate re-fire.
    assert s.check_volume_trigger() is False


def test_ensure_snapshot_idempotent(tmp_path):
    s = _store(tmp_path)
    for i in range(VOLUME_TRIGGER_VERSIONS):
        _publish_version(s, f"h{i}")
    snap1, c1 = s.ensure_snapshot(SNAPSHOT_TRIGGER_VOLUME)
    snap2, c2 = s.ensure_snapshot(SNAPSHOT_TRIGGER_VOLUME)
    assert c1 is True and c2 is False
    assert snap1.snapshot_id == snap2.snapshot_id
    assert len(s.list_snapshots()) == 1


def test_ensure_rejects_manual_trigger(tmp_path):
    s = _store(tmp_path)
    _publish_version(s, "h1")
    with pytest.raises(ValueError, match="auto triggers"):
        s.ensure_snapshot(SNAPSHOT_TRIGGER_MANUAL)


def test_annual_snapshot_due_and_ensure(tmp_path):
    s = _store(tmp_path)
    _publish_version(s, "h1")
    # No annual snapshot ever -> due.
    assert s.annual_snapshot_due() is True
    snap, created = s.ensure_snapshot(SNAPSHOT_TRIGGER_ANNUAL)
    assert created is True and snap.trigger == "annual"
    assert s.annual_snapshot_due() is False
    # Simulate a year passing: backdate the annual snapshot row (test-only SQL).
    old = (datetime.now(timezone.utc) - timedelta(days=ANNUAL_SNAPSHOT_DAYS + 5)).isoformat()
    with s._lock:
        s._conn.execute(
            "UPDATE profile_snapshots SET created_at = ? WHERE snapshot_id = ?",
            (old, snap.snapshot_id),
        )
        s._conn.commit()
    assert s.annual_snapshot_due() is True


def test_run_temporal_maintenance(tmp_path):
    s = _store(tmp_path)
    for i in range(VOLUME_TRIGGER_VERSIONS):
        _publish_version(s, f"h{i}")
    report = run_temporal_maintenance(s)
    assert report["volume"]["due"] is True and report["volume"]["created"] is True
    assert report["annual"]["due"] is True and report["annual"]["created"] is True
    assert len(s.list_snapshots()) == 2
    # Second run: nothing new -> nothing created.
    report2 = run_temporal_maintenance(s)
    assert report2["volume"]["created"] is False
    assert report2["annual"]["created"] is False
    assert len(s.list_snapshots()) == 2


def test_per_user_isolation(tmp_path):
    a = _store(tmp_path, "alice")
    b = _store(tmp_path, "bob")
    _publish_version(a, "h1")
    snap = a.create_snapshot(trigger=SNAPSHOT_TRIGGER_MANUAL, era_name="alice era")
    assert b.list_snapshots() == []
    assert b.get_snapshot(snap.snapshot_id) is None
    assert b.get_snapshot_by_era("alice era") is None
    assert b.check_volume_trigger() is False
    assert b.annual_snapshot_due() is True  # bob has no snapshots at all


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------


def test_snapshot_write_routes_require_train_self(monkeypatch):
    """Without train:self, snapshot writes -> 403."""
    from fastapi import HTTPException

    from api.routes import personality_temporal_routes as ptr
    from local_ai.identity import ScopeDenied

    def deny(scope, **kwargs):
        raise ScopeDenied(scope)

    monkeypatch.setattr("local_ai.identity.scopes.require_scope", deny)
    user = {"id": "u1"}
    with pytest.raises(HTTPException) as ei:
        ptr.create_snapshot(ptr.SnapshotBody(era_name="x"), user)
    assert ei.value.status_code == 403
    with pytest.raises(HTTPException) as ei2:
        ptr.check_snapshot_triggers(user)
    assert ei2.value.status_code == 403


def test_snapshot_route_flow(monkeypatch, tmp_path):
    from api.routes import personality_temporal_routes as ptr

    monkeypatch.setattr(
        "local_ai.identity.scopes.require_scope", lambda scope, **kw: None
    )
    monkeypatch.setattr(
        ptr, "_store", lambda user_id: PersonalityStore(db_path=tmp_path / "t.db", user_id=user_id)
    )
    user = {"id": "u1"}

    # No published profile yet -> 404 on manual snapshot.
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as ei:
        ptr.create_snapshot(ptr.SnapshotBody(), user)
    assert ei.value.status_code == 404

    # Publish, then snapshot.
    store = ptr._store("u1")
    _publish_version(store, "h1")
    store.close()
    snap = ptr.create_snapshot(ptr.SnapshotBody(era_name="early era", note="n"), user)
    assert snap.era_name == "early era"
    assert snap.version == 1

    listed = ptr.list_snapshots(user)
    assert len(listed["snapshots"]) == 1
    assert listed["snapshots"][0]["era_name"] == "early era"

    # Era addressing: by id and by era name.
    assert ptr.get_snapshot(snap.snapshot_id, user).snapshot_id == snap.snapshot_id
    assert ptr.get_snapshot("early era", user).snapshot_id == snap.snapshot_id
    with pytest.raises(HTTPException) as ei2:
        ptr.get_snapshot("nope", user)
    assert ei2.value.status_code == 404

    # Duplicate era name -> 422.
    with pytest.raises(HTTPException) as ei3:
        ptr.create_snapshot(ptr.SnapshotBody(era_name="early era"), user)
    assert ei3.value.status_code == 422

    # check-triggers: annual is due on a fresh archive history.
    report = ptr.check_snapshot_triggers(user)
    assert report["annual"]["due"] is True
    assert report["annual"]["created"] is True
    assert report["volume"]["due"] is False
    assert len(report["snapshots"]) == 1
