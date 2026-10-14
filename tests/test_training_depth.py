"""Tests for Phase 6: visible training-depth metrics.

Covers: honest zeros on empty stores, depth rising with real evidence,
recency (old-only evidence scores lower), context diversity, per-user
isolation, unmapped signals counting nowhere, band boundaries, and the
read-only guarantee (the metric never mutates any store).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from local_ai.personality.context import DecisionContext, set_signal_context
from local_ai.personality.depth import (
    band_for_score,
    compute_training_depth,
    map_signal_to_strand,
)
from local_ai.personality.schema import CandidateOp, ProfileCandidate
from local_ai.personality.store import PersonalityStore
from local_ai.presence_ingest.schema import TrainingSignal
from local_ai.strands import strand_keys


def _store(tmp_path: Path, user_id: str = "u1") -> PersonalityStore:
    return PersonalityStore(db_path=tmp_path / f"profiles_{user_id}.db", user_id=user_id)


def _now_ms(now: datetime) -> int:
    return int(now.timestamp() * 1000)


def _sig(
    signal_id: str,
    zone: str,
    summary: str,
    *,
    now: datetime,
    age_days: float = 0.0,
    layer: str = "decision",
    context: DecisionContext | None = None,
) -> TrainingSignal:
    ts = now - timedelta(days=age_days)
    sig = TrainingSignal(
        signal_id=signal_id,
        ts_ms=_now_ms(ts),
        layer=layer,
        zone=zone,
        actor="user",
        summary=summary,
        valence="observed",
        status="approved",
        session_id="sess1",
    )
    if context is not None:
        set_signal_context(sig, context)
    return sig


def _self_signal(signal_id: str, now: datetime, **kw) -> TrainingSignal:
    # zone/text chosen to map to the "self" strand via seed keywords.
    return _sig(
        signal_id,
        "strategy",
        "Made a decision about strategy and direction.",
        now=now,
        **kw,
    )


def _publish_heuristics(store: PersonalityStore, strand_key: str, n: int = 1) -> None:
    for i in range(n):
        cand = ProfileCandidate(
            candidate_id=f"pc_{strand_key}_{i}_{store.user_id}",
            user_id=store.user_id or "u1",
            strand_key=strand_key,
            ops=[CandidateOp(op="add", field="heuristics", value=f"heuristic {i}")],
            source="manual",
            confidence=0.9,
            rationale="test",
            created_at=datetime.now(timezone.utc),
        )
        store.propose(cand)
        store.publish([cand.candidate_id], source_summary="test")


def _versions(store: PersonalityStore):
    out = []
    for meta in store.list_versions():
        v = store.get_version(meta["version"])
        assert v is not None
        out.append((meta["version"], v))
    return out


# ---------------------------------------------------------------------------
# Honest empty states
# ---------------------------------------------------------------------------


def test_empty_everything_honest_zeros(tmp_path):
    depths = compute_training_depth(signals=[], profile=None, versions=[])
    assert set(depths.keys()) == set(strand_keys())
    for key, d in depths.items():
        assert d.score == 0, key
        assert d.trained is False, key
        assert d.band == "not yet trained", key
        assert d.approved_signals == 0
        assert d.profile_versions_touching == 0
        assert d.distinct_contexts == 0
        assert d.last_evidence_at is None
        assert all(v == 0.0 for v in d.components.values())


def test_unmapped_signals_count_nowhere():
    now = datetime.now(timezone.utc)
    sig = _sig("s1", "misc", "Some neutral observation about things.", now=now)
    assert map_signal_to_strand(sig) is None
    depths = compute_training_depth(signals=[sig], profile=None, versions=[])
    for d in depths.values():
        assert d.score == 0
        assert d.trained is False


# ---------------------------------------------------------------------------
# Evidence moves the needle
# ---------------------------------------------------------------------------


def test_signals_raise_depth():
    now = datetime.now(timezone.utc)
    sigs = [_self_signal(f"s{i}", now) for i in range(5)]
    depths = compute_training_depth(signals=sigs, profile=None, versions=[])
    d = depths["self"]
    assert d.approved_signals == 5
    assert d.components["signal_breadth"] == pytest.approx(0.25)
    assert d.components["recency"] > 0.99
    assert d.trained is True
    assert d.score > 0
    assert d.last_evidence_at is not None
    # Untouched strands stay honestly at zero.
    assert depths["word"].score == 0
    assert depths["word"].trained is False


def test_profile_content_counts(tmp_path):
    now = datetime.now(timezone.utc)
    store = _store(tmp_path)
    _publish_heuristics(store, "self", n=1)
    profile = store.get_current()
    assert profile is not None
    depths = compute_training_depth(
        signals=[], profile=profile, versions=_versions(store), now=now
    )
    d = depths["self"]
    assert d.profile_versions_touching == 1
    assert d.components["profile_depth"] == pytest.approx(round(1 / 13, 4))
    assert d.trained is True
    assert d.score > 0
    assert depths["word"].score == 0


def test_old_evidence_scores_lower_than_fresh():
    now = datetime.now(timezone.utc)
    fresh = [_self_signal(f"f{i}", now, age_days=2) for i in range(5)]
    stale = [_self_signal(f"s{i}", now, age_days=400) for i in range(5)]
    d_fresh = compute_training_depth(signals=fresh, profile=None, versions=[], now=now)["self"]
    d_stale = compute_training_depth(signals=stale, profile=None, versions=[], now=now)["self"]
    assert d_stale.components["recency"] == 0.0
    assert d_fresh.components["recency"] > 0.9
    assert d_stale.score < d_fresh.score
    # Stale evidence still counts as evidence — just weaker.
    assert d_stale.trained is True
    assert d_stale.approved_signals == 5


def test_context_diversity_matters():
    now = datetime.now(timezone.utc)
    ctx_a = DecisionContext(stakes="high", time_pressure="urgent")
    ctx_b = DecisionContext(stakes="low", time_pressure="open-ended")
    varied = [
        _self_signal("a1", now, context=ctx_a),
        _self_signal("a2", now, context=ctx_a),
        _self_signal("b1", now, context=ctx_b),
        _self_signal("b2", now, context=ctx_b),
    ]
    uniform = [_self_signal(f"u{i}", now, context=ctx_a) for i in range(4)]
    d_varied = compute_training_depth(signals=varied, profile=None, versions=[], now=now)["self"]
    d_uniform = compute_training_depth(signals=uniform, profile=None, versions=[], now=now)["self"]
    assert d_varied.distinct_contexts == 2
    assert d_uniform.distinct_contexts == 1
    assert d_varied.components["context_diversity"] == pytest.approx(0.5)
    assert d_uniform.components["context_diversity"] == pytest.approx(0.25)
    assert d_varied.score > d_uniform.score


def test_non_decision_signals_skip_diversity_but_count_breadth():
    now = datetime.now(timezone.utc)
    ctx = DecisionContext(stakes="high")
    sigs = [_self_signal(f"b{i}", now, layer="behavior", context=ctx) for i in range(4)]
    d = compute_training_depth(signals=sigs, profile=None, versions=[], now=now)["self"]
    assert d.approved_signals == 4
    assert d.distinct_contexts == 0
    assert d.components["context_diversity"] == 0.0
    assert d.score > 0  # breadth + recency still count


# ---------------------------------------------------------------------------
# Bands
# ---------------------------------------------------------------------------


def test_band_boundaries():
    assert band_for_score(0) == "not yet trained"
    assert band_for_score(1) == "early"
    assert band_for_score(24) == "early"
    assert band_for_score(25) == "developing"
    assert band_for_score(49) == "developing"
    assert band_for_score(50) == "trained"
    assert band_for_score(74) == "trained"
    assert band_for_score(75) == "deeply trained"
    assert band_for_score(100) == "deeply trained"


# ---------------------------------------------------------------------------
# Isolation + read-only
# ---------------------------------------------------------------------------


def test_per_user_isolation(tmp_path):
    now = datetime.now(timezone.utc)
    s1, s2 = _store(tmp_path, "u1"), _store(tmp_path, "u2")
    _publish_heuristics(s1, "self", n=2)
    sigs = [_self_signal("x1", now)]
    d1 = compute_training_depth(signals=sigs, profile=s1.get_current(), versions=_versions(s1), now=now)
    d2 = compute_training_depth(signals=[], profile=s2.get_current(), versions=_versions(s2), now=now)
    assert d1["self"].trained is True
    for d in d2.values():
        assert d.trained is False
        assert d.score == 0
    s1.close()
    s2.close()


def test_compute_is_read_only(tmp_path):
    now = datetime.now(timezone.utc)
    store = _store(tmp_path)
    _publish_heuristics(store, "self", n=1)
    sigs = [_self_signal("r1", now)]
    before_versions = store.version_count()
    before_cands = len(store.list_candidates())
    compute_training_depth(
        signals=sigs, profile=store.get_current(), versions=_versions(store), now=now
    )
    assert store.version_count() == before_versions
    assert len(store.list_candidates()) == before_cands
    store.close()


def test_route_training_depth_read_only(tmp_path, monkeypatch):
    from api.routes import personality_routes as routes

    store = _store(tmp_path, "u1")
    _publish_heuristics(store, "self", n=1)
    monkeypatch.setattr(routes, "_store", lambda uid: store)
    monkeypatch.setattr(routes, "_user_approved_signals", lambda: [])

    before_versions = store.version_count()
    before_cands = len(store.list_candidates())

    resp = routes.get_training_depth(current_user={"id": "u1"})

    assert set(resp["strands"].keys()) == set(strand_keys())
    self_d = resp["strands"]["self"]
    assert self_d["trained"] is True
    assert self_d["score"] > 0
    assert self_d["profile_versions_touching"] == 1
    assert resp["strands"]["word"]["score"] == 0
    assert resp["voice_published"] is False
    assert resp["version_count"] == 1
    assert resp["profile_version"] == 1
    assert "computed_at" in resp
    # Read-only: the route closed the store; re-open and confirm no
    # version or candidate rows were added.
    check = PersonalityStore(db_path=tmp_path / "profiles_u1.db", user_id="u1")
    try:
        assert check.version_count() == before_versions
        assert len(check.list_candidates(status="proposed")) == 0
        assert len(check.list_candidates()) == before_cands
    finally:
        check.close()
    store.close()


def test_route_empty_store_honest_zeros(tmp_path, monkeypatch):
    from api.routes import personality_routes as routes

    store = _store(tmp_path, "u9")
    monkeypatch.setattr(routes, "_store", lambda uid: store)
    monkeypatch.setattr(routes, "_user_approved_signals", lambda: [])

    resp = routes.get_training_depth(current_user={"id": "u9"})
    for d in resp["strands"].values():
        assert d["score"] == 0
        assert d["band"] == "not yet trained"
    assert resp["profile_version"] is None
    assert resp["version_count"] == 0
    store.close()
