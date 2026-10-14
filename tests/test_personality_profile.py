"""Tests for PersonalityProfile Phase 1 (the user-defined side).

Covers: schema validation, per-strand structure, versioning/supersession,
propose->review->publish flow, the no-silent-write guarantee, license-scope
gating on writes, seeding from approved signals, and the architectural
invariant that the aspirational defaults are never touched here.
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path

import pytest

from local_ai.personality.schema import (
    CandidateOp,
    DecisionFingerprint,
    PersonalityProfile,
    ProfileCandidate,
    StrandProfile,
)
from local_ai.personality.seed import seed_from_signals
from local_ai.personality.store import PersonalityStore
from local_ai.strands import strand_keys


def _store(tmp_path: Path, user_id: str = "u1") -> PersonalityStore:
    return PersonalityStore(db_path=tmp_path / "profiles.db", user_id=user_id)


def _cand(
    strand_key="self",
    ops=None,
    user_id="u1",
    source="manual",
    confidence=0.8,
) -> ProfileCandidate:
    return ProfileCandidate(
        candidate_id=f"pc_{strand_key}_{abs(hash((strand_key, source))) % 999999:06d}",
        user_id=user_id,
        strand_key=strand_key,
        ops=ops or [CandidateOp(op="add", field="heuristics", value="prefer reversible decisions")],
        source=source,
        confidence=confidence,
        rationale="test",
        created_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_profile_has_exactly_seven_canonical_strands():
    p = PersonalityProfile(profile_id="p1", user_id="u1", version=1)
    assert set(p.strands.keys()) == set(strand_keys())
    assert len(p.strands) == 7


def test_profile_rejects_wrong_strand_set():
    with pytest.raises(Exception):
        PersonalityProfile(
            profile_id="p1",
            user_id="u1",
            version=1,
            strands={"word": StrandProfile()},
        )


def test_candidate_rejects_unknown_strand_key():
    with pytest.raises(Exception):
        ProfileCandidate(
            candidate_id="c1",
            user_id="u1",
            strand_key="telepathy",
            ops=[CandidateOp(op="add", field="heuristics", value="x")],
        )


def test_candidate_rejects_unknown_field():
    with pytest.raises(Exception):
        CandidateOp(op="add", field="fingerprint.mood", value="x")


def test_candidate_rejects_add_on_scalar_field():
    with pytest.raises(Exception):
        CandidateOp(op="add", field="fingerprint.risk_bias", value="x")


def test_candidate_rejects_set_on_list_field():
    with pytest.raises(Exception):
        CandidateOp(op="set", field="heuristics", value=["x"])


def test_voice_fields_need_global_strand():
    with pytest.raises(Exception):
        ProfileCandidate(
            candidate_id="c1",
            user_id="u1",
            strand_key="word",
            ops=[CandidateOp(op="add", field="voice.tags", value="concise")],
        )


def test_fingerprint_fields_optional():
    fp = DecisionFingerprint(risk_bias="reversible first")
    assert fp.conflict_style == ""
    assert fp.risk_bias == "reversible first"


# ---------------------------------------------------------------------------
# Propose -> review -> publish
# ---------------------------------------------------------------------------


def test_propose_creates_no_version(tmp_path):
    s = _store(tmp_path)
    s.propose(_cand())
    s.propose(_cand(strand_key="word", source="manual-2"))
    assert s.get_current() is None
    assert s.version_count() == 0
    assert len(s.list_candidates(status="proposed")) == 2


def test_no_silent_write_after_any_non_publish_path(tmp_path):
    """Propose/reject/list must never create a profile version."""
    s = _store(tmp_path)
    c1, c2 = _cand(source="a"), _cand(strand_key="number", source="b")
    s.propose(c1)
    s.propose(c2)
    s.reject([c1.candidate_id])
    _ = s.list_candidates()
    _ = s.list_candidates(status="rejected")
    _ = s.get_current()
    _ = s.list_versions()
    assert s.version_count() == 0
    assert s.get_current() is None


def test_publish_applies_ops_and_versions(tmp_path):
    s = _store(tmp_path)
    c = _cand(
        strand_key="self",
        ops=[
            CandidateOp(op="add", field="heuristics", value="kill criteria before scale"),
            CandidateOp(op="set", field="fingerprint.risk_bias", value="reversible first"),
            CandidateOp(op="set", field="reasoning.notes", value="trade-offs first"),
        ],
    )
    s.propose(c)
    p1 = s.publish([c.candidate_id], source_summary="test")
    assert p1.version == 1
    assert p1.supersedes is None
    assert "kill criteria before scale" in p1.strands["self"].heuristics
    assert p1.strands["self"].fingerprint.risk_bias == "reversible first"

    c2 = ProfileCandidate(
        candidate_id="pc_voice_1", user_id="u1", strand_key=None,
        ops=[CandidateOp(op="add", field="voice.tags", value="concise")],
        source="m2", confidence=0.9, rationale="t",
        created_at=datetime.now(timezone.utc),
    )
    s.propose(c2)
    p2 = s.publish([c2.candidate_id])
    assert p2.version == 2
    assert p2.supersedes == 1
    assert "concise" in p2.voice.tags
    # v1 content carried forward
    assert "kill criteria before scale" in p2.strands["self"].heuristics
    # v1 retrievable and unchanged
    v1 = s.get_version(1)
    assert v1.version == 1 and "concise" not in v1.voice.tags
    assert s.get_current().version == 2


def test_publish_rejects_non_proposed_candidates(tmp_path):
    s = _store(tmp_path)
    c = _cand()
    s.propose(c)
    s.reject([c.candidate_id])
    with pytest.raises(ValueError, match="not proposed"):
        s.publish([c.candidate_id])
    assert s.version_count() == 0


def test_publish_rejects_unknown_candidate(tmp_path):
    s = _store(tmp_path)
    with pytest.raises(ValueError, match="not found"):
        s.publish(["nope"])


def test_rejected_candidates_never_applied(tmp_path):
    s = _store(tmp_path)
    keep = _cand(source="keep", ops=[CandidateOp(op="add", field="heuristics", value="kept")])
    drop = _cand(source="drop", ops=[CandidateOp(op="add", field="heuristics", value="dropped")])
    s.propose(keep)
    s.propose(drop)
    assert s.reject([drop.candidate_id]) == 1
    p = s.publish([keep.candidate_id])
    assert "kept" in p.strands["self"].heuristics
    assert "dropped" not in p.strands["self"].heuristics


def test_add_dedupes_exact_duplicates(tmp_path):
    s = _store(tmp_path)
    op = CandidateOp(op="add", field="heuristics", value="same")
    s.propose(_cand(source="a", ops=[op]))
    s.propose(_cand(source="b", ops=[op]))
    p = s.publish([c.candidate_id for c in s.list_candidates(status="proposed")])
    assert p.strands["self"].heuristics.count("same") == 1


def test_per_user_isolation(tmp_path):
    s1 = _store(tmp_path, "alice")
    s2 = _store(tmp_path, "bob")
    s1.propose(_cand(user_id="alice"))
    assert s1.publish([c.candidate_id for c in s1.list_candidates()]).version == 1
    assert s2.get_current() is None
    assert s2.list_candidates() == []
    # bob cannot publish alice's candidate
    with pytest.raises(ValueError, match="not found"):
        s2.publish([s1.list_candidates()[0].candidate_id])


# ---------------------------------------------------------------------------
# License-scope gating (route level)
# ---------------------------------------------------------------------------


def test_write_routes_require_train_self(monkeypatch):
    """Without the train:self scope, propose/publish/reject/seed -> 403."""
    from fastapi import HTTPException

    from api.routes import personality_routes as pr
    from local_ai.identity import ScopeDenied

    def deny(scope, **kwargs):
        raise ScopeDenied(scope)

    monkeypatch.setattr("local_ai.identity.scopes.require_scope", deny)
    user = {"id": "u1"}
    with pytest.raises(HTTPException) as ei:
        pr._require_train_self("u1")
    assert ei.value.status_code == 403

    # And the route handlers enforce it too (propose path).
    body = pr.ProposeBody(
        strand_key="self",
        ops=[CandidateOp(op="add", field="heuristics", value="x")],
    )
    with pytest.raises(HTTPException) as ei2:
        pr.propose_candidate(body, user)
    assert ei2.value.status_code == 403


def test_write_routes_pass_with_scope(monkeypatch, tmp_path):
    from api.routes import personality_routes as pr

    monkeypatch.setattr(
        "local_ai.identity.scopes.require_scope", lambda scope, **kw: None
    )
    # Route the store at a temp db via monkeypatched _store.
    monkeypatch.setattr(
        pr, "_store", lambda user_id: PersonalityStore(db_path=tmp_path / "p.db", user_id=user_id)
    )
    user = {"id": "u1"}
    body = pr.ProposeBody(
        strand_key="self",
        ops=[CandidateOp(op="add", field="heuristics", value="x")],
        source="t",
    )
    cand = pr.propose_candidate(body, user)
    assert cand.status == "proposed"
    pub = pr.publish_profile(pr.PublishBody(candidate_ids=[cand.candidate_id]), user)
    assert pub.version == 1
    assert pr.get_current_profile(user).version == 1


# ---------------------------------------------------------------------------
# Seeding from approved signals
# ---------------------------------------------------------------------------


def _seed_presence_store(tmp_path: Path, license_id: str):
    from local_ai.presence_ingest.schema import ImportSession, TrainingSignal
    from local_ai.presence_ingest.store import PresenceStore

    ps = PresenceStore(db_path=tmp_path / "signals.db")
    sess = ImportSession(
        session_id="imp-1",
        source="chatgpt",
        file_name="conversations.json",
        status="distilled",
        provenance={"license_id": license_id},
    )
    ps.create_session(sess)
    sigs = [
        TrainingSignal(
            signal_id="sig-1",
            ts_ms=1,
            layer="decision",
            zone="strategy",
            actor="user",
            summary="User killed the project early. Values revealed: reversibility over sunk cost.",
            payload_redacted="Communication style: terse, direct.",
            valence="observed",
            session_id="imp-1",
        ),
        TrainingSignal(
            signal_id="sig-2",
            ts_ms=2,
            layer="guidance",
            zone="zzz-no-match",
            actor="user",
            summary="A plain logistical note about Tuesday timing.",
            valence="observed",
            session_id="imp-1",
        ),
    ]
    ps.save_candidate_signals(sigs)
    ps.review_signals(["sig-1", "sig-2"], approve=True)
    return ps


def test_seed_proposes_but_never_publishes(tmp_path):
    ps = _seed_presence_store(tmp_path, "lic-1")
    store = _store(tmp_path)
    made = seed_from_signals(store, ps, "u1")
    # sig-1: values cue -> heuristic + style cue -> example
    assert len(made) == 2
    assert all(c.source == "seed:signal:sig-1" for c in made)
    assert all(c.status == "proposed" for c in made)
    assert all(c.confidence <= 0.5 for c in made)  # heuristic parse: modest confidence
    # sig-2 had no strand match and no values cues -> skipped
    assert store.version_count() == 0
    assert store.get_current() is None


def test_seed_is_idempotent(tmp_path):
    ps = _seed_presence_store(tmp_path, "lic-1")
    store = _store(tmp_path)
    first = seed_from_signals(store, ps, "u1")
    second = seed_from_signals(store, ps, "u1")
    assert len(first) == 2
    assert second == []


def test_seed_does_not_fabricate_fields(tmp_path):
    """Seeded candidates only carry observed text; fingerprint stays empty."""
    ps = _seed_presence_store(tmp_path, "lic-1")
    store = _store(tmp_path)
    made = seed_from_signals(store, ps, "u1")
    for c in made:
        for op in c.ops:
            assert not op.field.startswith("fingerprint.")
        assert "signal sig-1" in c.rationale


# ---------------------------------------------------------------------------
# Architectural invariant: aspirational defaults never touched here
# ---------------------------------------------------------------------------


def test_personality_package_never_references_builtin_personas():
    """AST check: no import of zenaf_tools and no live code reference to the
    builtin persona definitions. (Docstrings may *name* them in warnings.)"""
    pkg = Path(__file__).resolve().parent.parent / "local_ai" / "personality"
    for path in pkg.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "zenaf_tools" not in node.module, f"{path.name} imports zenaf_tools"
            elif isinstance(node, ast.Import):
                assert not any("zenaf_tools" in a.name for a in node.names)
            elif isinstance(node, ast.Name):
                assert node.id != "BUILT_IN_PERSONA_DEFINITIONS", (
                    f"{path.name} references BUILT_IN_PERSONA_DEFINITIONS in code"
                )
