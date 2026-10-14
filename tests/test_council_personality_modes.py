"""Tests for user-chosen council personality modes (base / mirror / blend).

Covers:
  * mode behaviors — base renders pure aspirational (byte-identical to the
    unweighted seat block); mirror renders the profile-only seat; blend is
    the Phase 4 weighted behavior, unchanged;
  * graceful mirror fallback — strands with no published content fall back
    to aspirational and are recorded in mirror_empty_strands;
  * mode resolution precedence — per-run override > stored default >
    system default ("blend");
  * default-mode get/set round-trip + validation;
  * the ask-gate invariant — no code path from insight to a published
    version except explicit publish(); propose requires a source;
  * synthesis seats and non-strand custom seats pass through untouched in
    every mode.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from local_ai.personality.blend import (
    CouncilPersonality,
    apply_council_personality,
    mirror_notice_text,
    normalize_council_mode,
    render_mirror_block,
    resolve_council_personality,
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
    _resolve_council_personality,
    _resolve_seat_strand,
)


def _store(tmp_path: Path, user_id: str = "u1") -> PersonalityStore:
    return PersonalityStore(db_path=tmp_path / "profiles.db", user_id=user_id)


def _publish(store: PersonalityStore, user_id: str, ops_by_strand: dict) -> PersonalityProfile:
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


def _rich_self_ops() -> dict:
    return {
        "self": [
            ("reasoning.descriptors", "add", "prefer trade-off framing"),
            ("reasoning.notes", "set", "thinks out loud before deciding"),
            ("fingerprint.risk_bias", "set", "reversible first"),
            ("fingerprint.decision_style", "set", "decide fast, iterate"),
            ("heuristics", "add", "never optimize what you don't measure"),
            ("red_lines", "add", {"rule": "no dark patterns", "rationale": "trust"}),
            ("examples", "add", {"context": "planning", "fragment": "cut scope, ship it", "tag": "voice"}),
        ],
        None: [
            ("voice.description", "set", "terse, dry, allergic to fluff"),
        ],
    }


# ---------------------------------------------------------------------------
# Mode normalization
# ---------------------------------------------------------------------------


def test_normalize_council_mode():
    assert normalize_council_mode("base") == "base"
    assert normalize_council_mode("mirror") == "mirror"
    assert normalize_council_mode("blend") == "blend"
    assert normalize_council_mode("  MIRROR ") == "mirror"
    assert normalize_council_mode(None) == "blend"
    assert normalize_council_mode("") == "blend"
    assert normalize_council_mode("bogus") == "blend"


# ---------------------------------------------------------------------------
# Default-mode get/set
# ---------------------------------------------------------------------------


def test_council_mode_default_is_blend(tmp_path):
    s = _store(tmp_path)
    try:
        assert s.get_council_mode() == "blend"
    finally:
        s.close()


def test_council_mode_round_trip(tmp_path):
    s = _store(tmp_path)
    try:
        assert s.set_council_mode("mirror") == "mirror"
        assert s.get_council_mode() == "mirror"
        assert s.set_council_mode("base") == "base"
        assert s.get_council_mode() == "base"
    finally:
        s.close()


def test_council_mode_rejects_unknown(tmp_path):
    s = _store(tmp_path)
    try:
        with pytest.raises(ValueError):
            s.set_council_mode("bogus")
        # unchanged after the failed write
        assert s.get_council_mode() == "blend"
    finally:
        s.close()


def test_council_mode_is_per_user(tmp_path):
    a = _store(tmp_path, "alice")
    b = _store(tmp_path, "bob")
    try:
        a.set_council_mode("mirror")
        assert a.get_council_mode() == "mirror"
        assert b.get_council_mode() == "blend"
    finally:
        a.close()
        b.close()


# ---------------------------------------------------------------------------
# Mode resolution precedence
# ---------------------------------------------------------------------------


def test_mode_resolution_precedence(tmp_path):
    s = _store(tmp_path)
    try:
        # no override, no stored default -> system default
        assert resolve_council_personality(s, None).mode == "blend"
        # stored default wins over system default
        s.set_council_mode("base")
        assert resolve_council_personality(s, None).mode == "base"
        # explicit per-run override wins over stored default
        assert resolve_council_personality(s, "mirror").mode == "mirror"
        # invalid override coerces to system default, not to stored
        assert resolve_council_personality(s, "bogus").mode == "blend"
    finally:
        s.close()


def test_resolve_never_raises_without_user():
    p = _resolve_council_personality(None, "mirror")
    assert isinstance(p, CouncilPersonality)
    assert p.mode == "mirror"
    assert p.mirror_profile is None
    p2 = _resolve_council_personality(None, None)
    assert p2.mode == "blend"


# ---------------------------------------------------------------------------
# Mode behaviors on seat blocks
# ---------------------------------------------------------------------------


def _base_and_defn():
    defn = dict(BUILT_IN_PERSONA_DEFINITIONS["guide"])
    return _build_council_persona_block(defn), defn


def test_base_mode_is_pure_aspirational(tmp_path):
    base, defn = _base_and_defn()
    s = _store(tmp_path)
    try:
        _publish(s, "u1", _rich_self_ops())  # profile exists, but base ignores it
        p = resolve_council_personality(s, "base")
        assert p.mode == "base"
        out = _build_weighted_council_persona_block(defn, personality=p)
        assert out == base
    finally:
        s.close()


def test_blend_mode_unchanged_from_phase4(tmp_path):
    from local_ai.personality.blend import apply_personality_blend

    base, defn = _base_and_defn()
    s = _store(tmp_path)
    try:
        _publish(s, "u1", _rich_self_ops())
        p = resolve_council_personality(s, "blend")
        assert p.mode == "blend"
        via_mode = _build_weighted_council_persona_block(defn, personality=p)
        via_legacy = apply_personality_blend(base, defn, p.blend_ctx)
        assert via_mode == via_legacy
        assert "How this user wields this faculty" in via_mode
    finally:
        s.close()


def test_mirror_mode_renders_profile_only(tmp_path):
    base, defn = _base_and_defn()
    s = _store(tmp_path)
    try:
        _publish(s, "u1", _rich_self_ops())
        p = resolve_council_personality(s, "mirror")
        assert p.mode == "mirror"
        out = _build_weighted_council_persona_block(defn, personality=p)
        # mirror-only: profile content present, aspirational base absent
        assert "The mirror" in out
        assert "terse, dry, allergic to fluff" in out
        assert "no dark patterns" in out
        assert out != base
        assert "Hold the question of where this is going" not in out
        assert p.mirror_empty_strands == []
    finally:
        s.close()


def test_mirror_falls_back_gracefully_when_strand_empty(tmp_path):
    base, defn = _base_and_defn()
    word_defn = dict(BUILT_IN_PERSONA_DEFINITIONS["storyteller"])
    s = _store(tmp_path)
    try:
        # profile has content for self only; word strand is empty
        _publish(s, "u1", _rich_self_ops())
        p = resolve_council_personality(s, "mirror")
        guide_out = _build_weighted_council_persona_block(defn, personality=p)
        assert "The mirror" in guide_out
        word_base = _build_council_persona_block(word_defn)
        word_out = _build_weighted_council_persona_block(word_defn, personality=p)
        assert word_out == word_base  # graceful fallback, no crash, no empty seat
        assert p.mirror_empty_strands == ["word"]
        notice = mirror_notice_text(p.mirror_empty_strands)
        assert notice is not None and "Storyteller" in notice
    finally:
        s.close()


def test_mirror_with_no_profile_falls_back_everywhere(tmp_path):
    base, defn = _base_and_defn()
    s = _store(tmp_path)
    try:
        p = resolve_council_personality(s, "mirror")
        assert p.mirror_profile is None
        out = _build_weighted_council_persona_block(defn, personality=p)
        assert out == base
        assert p.mirror_empty_strands == ["self"]
        assert mirror_notice_text([]) is None
    finally:
        s.close()


def test_synthesis_and_custom_seats_untouched_in_every_mode(tmp_path):
    s = _store(tmp_path)
    try:
        _publish(s, "u1", _rich_self_ops())
        for mode in ("base", "mirror", "blend"):
            p = resolve_council_personality(s, mode)
            for defn in (
                dict(BUILT_IN_PERSONA_DEFINITIONS["thinking_partner"]),
                dict(BUILT_IN_PERSONA_DEFINITIONS["zenaf"]),
                {"id": "custom", "name": "Custom", "purpose": "do things"},
            ):
                base = _build_council_persona_block(defn)
                out = _build_weighted_council_persona_block(defn, personality=p)
                assert out == base, f"{mode} touched a non-strand seat"
    finally:
        s.close()


def test_render_mirror_block_none_when_empty(tmp_path):
    s = _store(tmp_path)
    try:
        profile = _publish(s, "u1", _rich_self_ops())
        assert render_mirror_block(profile, "word", 1) is None
        assert render_mirror_block(profile, "self", 1) is not None
    finally:
        s.close()


# ---------------------------------------------------------------------------
# Seat strand resolution (incl. client-supplied definitions)
# ---------------------------------------------------------------------------


def test_resolve_seat_strand_direct_and_fallback():
    assert _resolve_seat_strand({"strand": "self"}) == "self"
    assert _resolve_seat_strand({"strand": " SELF "}) == "self"
    # GUI-style definition: no strand, but a built-in agent id
    assert _resolve_seat_strand({"perspective_agent_id": "guide", "name": "Guide"}) == "self"
    assert _resolve_seat_strand({"id": "songwriter"}) == "sound"
    assert _resolve_seat_strand({"id": "custom-thing"}) == ""
    assert _resolve_seat_strand({}) == ""


def test_gui_style_defn_gets_blend_and_mirror(tmp_path):
    """Definitions as the GUI sends them (no strand key) still resolve."""
    s = _store(tmp_path)
    try:
        _publish(s, "u1", _rich_self_ops())
        gui_defn = {
            "id": "slot-1",
            "perspective_agent_id": "guide",
            "name": "Guide",
            "purpose": "hold direction",
        }
        base = _build_council_persona_block(gui_defn)
        p = resolve_council_personality(s, "blend")
        blended = _build_weighted_council_persona_block(gui_defn, personality=p)
        assert blended != base
        assert "How this user wields this faculty" in blended
        p2 = resolve_council_personality(s, "mirror")
        mirrored = _build_weighted_council_persona_block(gui_defn, personality=p2)
        assert "The mirror" in mirrored
    finally:
        s.close()


# ---------------------------------------------------------------------------
# Ask-gate invariant: insights -> candidates -> explicit publish only
# ---------------------------------------------------------------------------


def test_only_publish_writes_profile_versions():
    """Static invariant: the ONLY version-row insert in the repo lives inside
    PersonalityStore.publish. No insight pipeline can mint a profile version
    without the user's explicit publish."""
    repo = Path(__file__).resolve().parents[1]
    # Built via concatenation so this test file itself never literally
    # contains the scanned statement.
    needle = "INSERT INTO " + "profile_versions"
    hits: list[str] = []
    for path in list(repo.rglob("*.py")):
        if "__pycache__" in path.parts or ".venv" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        if needle in text:
            hits.append(str(path.relative_to(repo)))
    assert hits == ["local_ai/personality/store.py"], hits


def test_propose_and_seed_never_create_versions(tmp_path):
    s = _store(tmp_path)
    try:
        cand = ProfileCandidate(
            candidate_id="pc_x",
            user_id="u1",
            strand_key="self",
            ops=[CandidateOp(op="add", field="heuristics", value="x")],
            source="council_interaction",
            confidence=0.7,
            rationale="r",
            created_at=datetime.now(timezone.utc),
        )
        s.propose(cand)
        assert s.get_current() is None
        assert s.version_count() == 0
        # publish with no ids is rejected; publish of the candidate works
        with pytest.raises(ValueError):
            s.publish(["nope"])
        assert s.version_count() == 0
        s.publish([cand.candidate_id], source_summary="user approved")
        assert s.version_count() == 1
    finally:
        s.close()


def test_propose_requires_source():
    """The ask only works if the user sees where the insight came from."""
    from pydantic import ValidationError

    from api.routes.personality_routes import ProposeBody

    with pytest.raises(ValidationError):
        ProposeBody(
            strand_key="self",
            ops=[CandidateOp(op="add", field="heuristics", value="x")],
        )
    ok = ProposeBody(
        strand_key="self",
        ops=[CandidateOp(op="add", field="heuristics", value="x")],
        source="council_interaction",
    )
    assert ok.source == "council_interaction"


def test_candidate_source_vocab_documented():
    from local_ai.personality.blend import CANDIDATE_SOURCES

    for expected in ("distillation", "council_interaction", "correction", "manual"):
        assert expected in CANDIDATE_SOURCES


# ---------------------------------------------------------------------------
# Council-mode API routes
# ---------------------------------------------------------------------------


def test_council_mode_routes(tmp_path, monkeypatch):
    from fastapi import HTTPException

    from api.routes import personality_routes as pr
    from local_ai.identity import ScopeDenied

    monkeypatch.setattr(
        pr, "_store", lambda user_id: PersonalityStore(db_path=tmp_path / "p.db", user_id=user_id)
    )
    user = {"id": "u1"}

    # GET: read needs session auth only; default blend.
    assert pr.get_council_mode(user) == {"council_mode": "blend"}

    # PUT needs session auth only (display preference, not training):
    # it works even when train:self is denied.
    def deny(scope, **kwargs):
        raise ScopeDenied(scope)

    monkeypatch.setattr("local_ai.identity.scopes.require_scope", deny)
    assert pr.set_council_mode(pr.CouncilModeBody(council_mode="mirror"), user) == {
        "council_mode": "mirror"
    }
    assert pr.get_council_mode(user) == {"council_mode": "mirror"}

    # PUT validates the mode value.
    monkeypatch.setattr("local_ai.identity.scopes.require_scope", lambda scope, **kw: None)
    with pytest.raises(HTTPException) as ei2:
        pr.set_council_mode(pr.CouncilModeBody(council_mode="bogus"), user)
    assert ei2.value.status_code == 422
