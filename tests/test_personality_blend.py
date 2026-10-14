"""Tests for Phase 4: the runtime weighting layer (personality mirror in seats).

Covers: byte-identical fallback when there is no published profile (or the
profile is too thin), labeled two-lens blend structure when evidence is
rich, weight scaling with evidence depth, per-strand overrides, the
invariant that built-in definitions are never mutated, and that synthesis
seats (no strand) are untouched.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from local_ai.personality.blend import (
    MIN_EVIDENCE,
    apply_personality_blend,
    default_weight_for_strand,
    resolve_blend_context,
    resolve_weights,
    strand_evidence_depth,
)
from local_ai.personality.schema import (
    CandidateOp,
    PersonalityProfile,
    ProfileCandidate,
)
from local_ai.personality.store import PersonalityStore
from local_ai.strands import strand_keys
from local_ai.zenaf_tools import (
    BUILT_IN_PERSONA_DEFINITIONS,
    _build_council_persona_block,
    _build_weighted_council_persona_block,
)


def _store(tmp_path: Path, user_id: str = "u1") -> PersonalityStore:
    return PersonalityStore(db_path=tmp_path / "profiles.db", user_id=user_id)


def _publish_profile(store: PersonalityStore, user_id: str, ops_by_strand: dict) -> PersonalityProfile:
    """Propose + publish candidates; ops_by_strand maps strand_key (or None
    for voice) -> list of (field, op, value)."""
    ids = []
    for strand_key, ops in ops_by_strand.items():
        cand = ProfileCandidate(
            candidate_id=f"pc_{strand_key}_{abs(hash(str(ops))) % 999999:06d}",
            user_id=user_id,
            strand_key=strand_key,
            ops=[CandidateOp(field=f, op=o, value=v) for f, o, v in ops],
            source="test",
            confidence=0.8,
            rationale="test",
            created_at=datetime.now(timezone.utc),
        )
        store.propose(cand)
        ids.append(cand.candidate_id)
    return store.publish(ids, source_summary="test")


def _rich_ops() -> dict:
    return {
        "self": [
            ("reasoning.descriptors", "add", "prefer trade-off framing"),
            ("reasoning.notes", "set", "thinks out loud before deciding"),
            ("fingerprint.risk_bias", "set", "reversible first"),
            ("fingerprint.decision_style", "set", "decide fast, iterate"),
            ("fingerprint.conflict_style", "set", "explicit trade-off"),
            ("heuristics", "add", "never optimize what you don't measure"),
            ("red_lines", "add", {"rule": "no dark patterns", "rationale": "trust"}),
            ("examples", "add", {"context": "planning", "fragment": "cut scope, ship it", "tag": "voice"}),
        ],
        None: [
            ("voice.description", "set", "terse, dry, allergic to fluff"),
            ("voice.tags", "add", "concise"),
        ],
    }


def _thin_ops() -> dict:
    return {"self": [("heuristics", "add", "measure twice")]}


# ---------------------------------------------------------------------------
# Byte-identical fallback
# ---------------------------------------------------------------------------


def test_no_profile_byte_identical(tmp_path):
    defn = dict(BUILT_IN_PERSONA_DEFINITIONS["guide"])
    base = _build_council_persona_block(defn)
    store = _store(tmp_path)
    try:
        ctx = resolve_blend_context(store)
        assert ctx is None
        assert apply_personality_blend(base, defn, ctx) == base
        assert apply_personality_blend(base, defn, None) == base
        # through the council wrapper too
        assert _build_weighted_council_persona_block(defn, blend_ctx=None) == base
    finally:
        store.close()


def test_thin_profile_byte_identical(tmp_path):
    store = _store(tmp_path)
    try:
        _publish_profile(store, "u1", _thin_ops())
        profile = store.get_current()
        depth = strand_evidence_depth(profile, "self")
        assert depth < MIN_EVIDENCE
        assert default_weight_for_strand(profile, "self") == 0.0
        assert resolve_blend_context(store) is None  # all weights 0 -> no blend
        defn = dict(BUILT_IN_PERSONA_DEFINITIONS["guide"])
        base = _build_council_persona_block(defn)
        assert apply_personality_blend(base, defn, None) == base
    finally:
        store.close()


def test_synthesis_seats_untouched(tmp_path):
    store = _store(tmp_path)
    try:
        _publish_profile(store, "u1", _rich_ops())
        ctx = resolve_blend_context(store)
        assert ctx is not None
        for key in ("thinking_partner", "zenaf"):
            defn = dict(BUILT_IN_PERSONA_DEFINITIONS[key])
            base = _build_council_persona_block(defn)
            assert apply_personality_blend(base, defn, ctx) == base
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Blend structure with rich evidence
# ---------------------------------------------------------------------------


def test_rich_profile_blends_with_labeled_sections(tmp_path):
    store = _store(tmp_path)
    try:
        _publish_profile(store, "u1", _rich_ops())
        profile = store.get_current()
        depth = strand_evidence_depth(profile, "self")
        assert depth >= MIN_EVIDENCE
        weight = default_weight_for_strand(profile, "self")
        assert 0.0 < weight <= 1.0
        assert weight == pytest.approx(depth, abs=1e-3)

        ctx = resolve_blend_context(store)
        assert ctx is not None
        assert ctx.weights["self"] == pytest.approx(weight)

        defn = dict(BUILT_IN_PERSONA_DEFINITIONS["guide"])
        base = _build_council_persona_block(defn)
        blended = apply_personality_blend(base, defn, ctx)

        assert blended != base
        # both lenses labeled and legible
        assert "two lenses" in blended
        assert "How this user wields this faculty" in blended
        assert f"user-side weight {weight:.2f}" in blended
        # aspirational side intact
        assert base in blended
        # user content present
        assert "reversible first" in blended
        assert "never optimize what you don't measure" in blended
        assert "no dark patterns" in blended
        assert "terse, dry, allergic to fluff" in blended
        # blend instruction names the delta
        assert "delta is the point" in blended
        # strands with no strand-specific evidence still get the global voice
        # (2/15 slots) — enough to tint the seat toward how the user sounds
        assert ctx.weights["word"] == pytest.approx(2 / 15, abs=1e-3)
        word_defn = dict(BUILT_IN_PERSONA_DEFINITIONS["storyteller"])
        word_base = _build_council_persona_block(word_defn)
        word_blended = apply_personality_blend(word_base, word_defn, ctx)
        assert "terse, dry, allergic to fluff" in word_blended
        assert "reversible first" not in word_blended  # self-strand content stays put
    finally:
        store.close()


def test_blend_never_mutates_builtins(tmp_path):
    before = copy.deepcopy(BUILT_IN_PERSONA_DEFINITIONS)
    store = _store(tmp_path)
    try:
        _publish_profile(store, "u1", _rich_ops())
        ctx = resolve_blend_context(store)
        for key in ("seer", "guide", "songwriter", "storyteller", "patternist", "maker", "mediator"):
            defn = BUILT_IN_PERSONA_DEFINITIONS[key]  # the real object, not a copy
            base = _build_council_persona_block(defn)
            apply_personality_blend(base, defn, ctx)
            _build_weighted_council_persona_block(defn, blend_ctx=ctx)
        assert BUILT_IN_PERSONA_DEFINITIONS == before
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Weight scaling + overrides
# ---------------------------------------------------------------------------


def test_evidence_depth_scales_with_filled_fields(tmp_path):
    store = _store(tmp_path)
    try:
        _publish_profile(store, "u1", _thin_ops())
        thin = strand_evidence_depth(store.get_current(), "self")
        store2 = PersonalityStore(db_path=tmp_path / "p2.db", user_id="u1")
        try:
            _publish_profile(store2, "u1", _rich_ops())
            rich = strand_evidence_depth(store2.get_current(), "self")
        finally:
            store2.close()
        assert rich > thin
        assert 0.0 <= thin <= 1.0 and 0.0 <= rich <= 1.0
    finally:
        store.close()


def test_manual_override_wins_over_auto(tmp_path):
    store = _store(tmp_path)
    try:
        _publish_profile(store, "u1", _rich_ops())
        profile = store.get_current()
        auto = default_weight_for_strand(profile, "self")
        assert auto > 0

        # override to 0 -> byte-identical even with rich evidence
        store.set_weight_overrides({"self": 0.0})
        effective, overrides = resolve_weights(store, profile)
        assert overrides["self"] == 0.0
        assert effective["self"] == 0.0
        assert resolve_blend_context(store) is None or resolve_blend_context(store).weights["self"] == 0.0
        defn = dict(BUILT_IN_PERSONA_DEFINITIONS["guide"])
        base = _build_council_persona_block(defn)
        ctx = resolve_blend_context(store)
        assert apply_personality_blend(base, defn, ctx) == base

        # override to a fixed value
        store.set_weight_overrides({"self": 0.7})
        effective, _ = resolve_weights(store, profile)
        assert effective["self"] == 0.7

        # None clears back to auto
        store.set_weight_overrides({"self": None})
        effective, overrides = resolve_weights(store, profile)
        assert "self" not in overrides
        assert effective["self"] == pytest.approx(auto)
    finally:
        store.close()


def test_weight_override_validation(tmp_path):
    store = _store(tmp_path)
    try:
        with pytest.raises(ValueError):
            store.set_weight_overrides({"nonsense": 0.5})
        with pytest.raises(ValueError):
            store.set_weight_overrides({"self": 1.5})
        with pytest.raises(ValueError):
            store.set_weight_overrides({"self": -0.1})
        # valid keys for all seven strands accepted
        store.set_weight_overrides({k: 0.25 for k in strand_keys()})
        assert store.get_weight_overrides()["word"] == 0.25
    finally:
        store.close()


def test_all_strands_have_weight_entries(tmp_path):
    store = _store(tmp_path)
    try:
        _publish_profile(store, "u1", _rich_ops())
        effective, _ = resolve_weights(store, store.get_current())
        assert set(effective.keys()) == set(strand_keys())
        assert all(0.0 <= w <= 1.0 for w in effective.values())
    finally:
        store.close()
