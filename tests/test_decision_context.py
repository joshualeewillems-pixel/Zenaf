"""Tests for context-conditioned decision modeling.

Covers:
  * DecisionContext schema — six canonical dimensions, three levels each,
    every dimension defaulting to unknown; normalization of sloppy input;
    no internal states anywhere;
  * signal attachment — context_ref["decision_context"] round-trip, and
    old records without the key reading as all-unknown (migration-safe);
  * similarity — exact/partial/unknown handling;
  * conservative derivation from text — explicit cues only, vague text stays
    unknown;
  * aggregation — approved decision signals grouped by envelope propose
    contextual-fingerprint candidates; never publishes; dedup on re-run;
    non-decision layers and contextless signals skipped;
  * publish flow — contextual entries land on the strand, global fingerprint
    untouched, old profile JSON still parses;
  * council rendering — similar envelopes surface labeled; dissimilar ones
    trigger the honest-extrapolation note; no envelope means today's
    behavior, byte-identical;
  * the ask-gate invariant — no silent mutation through the new paths.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from local_ai.personality import (
    DecisionContext,
    context_similarity,
    derive_decision_context,
    get_signal_context,
    parse_decision_context,
    set_signal_context,
)
from local_ai.personality.blend import (
    CONTEXT_SIMILARITY_THRESHOLD,
    apply_council_personality,
    resolve_council_personality,
)
from local_ai.personality.context import DIMENSIONS, LEVELS, normalize_level
from local_ai.personality.schema import (
    CandidateOp,
    ContextualFingerprint,
    PersonalityProfile,
    ProfileCandidate,
)
from local_ai.personality.seed import seed_contextual_fingerprints
from local_ai.personality.store import PersonalityStore
from local_ai.presence_ingest.schema import TrainingSignal
from local_ai.zenaf_tools import (
    BUILT_IN_PERSONA_DEFINITIONS,
    _build_council_persona_block,
    _resolve_decision_context,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


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


def _ctx_value(context: dict, n: int = 1) -> dict:
    return {
        "context": context,
        "fingerprint": {"risk_bias": "Observed: took the reversible bet"},
        "evidence": f"{n} decision signal(s)",
        "decision_count": n,
    }


def _rich_self_ops() -> dict:
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
            ("contextual_fingerprints", "add", _ctx_value({"stakes": "significant", "time_pressure": "urgent"}, n=3)),
            ("contextual_fingerprints", "add", _ctx_value({"stakes": "low", "time_pressure": "open-ended"}, n=2)),
        ],
        None: [
            ("voice.description", "set", "terse, dry, allergic to fluff"),
            ("voice.tags", "add", "concise"),
        ],
    }


def _signal(signal_id: str, layer: str = "decision", context: dict | None = None) -> TrainingSignal:
    sig = TrainingSignal(
        signal_id=signal_id,
        ts_ms=1_700_000_000_000,
        layer=layer,
        zone="strategy",
        actor="u1",
        summary="Chose the reversible option despite the risk involved in the bet.",
        context_ref={},
        payload_redacted="",
        valence="observed",
        status="approved",
        session_id="sess1",
    )
    if context is not None:
        set_signal_context(sig, DecisionContext(**context))
    return sig


class _FakeSignals:
    def __init__(self, signals):
        self._signals = signals

    def list_signals(self, status: str = "approved"):
        return [s for s in self._signals if s.status == status]


# ---------------------------------------------------------------------------
# schema: the six dimensions, unknown defaults, normalization
# ---------------------------------------------------------------------------


def test_six_dimensions_three_levels_each():
    assert DIMENSIONS == (
        "stakes",
        "reversibility",
        "time_pressure",
        "information",
        "social_field",
        "resource_climate",
    )
    assert LEVELS["stakes"] == ("low", "significant", "life-altering")
    assert LEVELS["reversibility"] == ("easily", "costly", "irreversible")
    assert LEVELS["time_pressure"] == ("urgent", "deliberative", "open-ended")
    assert LEVELS["information"] == ("thin", "adequate", "rich")
    assert LEVELS["social_field"] == ("solo", "interpersonal", "publicly_accountable")
    assert LEVELS["resource_climate"] == ("scarcity", "sufficiency", "abundance")


def test_defaults_all_unknown():
    ctx = DecisionContext()
    assert ctx.is_empty()
    assert ctx.known() == {}
    assert ctx.signature() == ""
    assert ctx.summarize() == "unspecified context"
    for dim in DIMENSIONS:
        assert getattr(ctx, dim) == "unknown"


def test_no_internal_states():
    # tired / grieving / stressed must have no home in the envelope.
    ctx = DecisionContext.model_validate(
        {"stakes": "low", "mood": "tired", "stress": "high", "grieving": True}
    )
    assert ctx.stakes == "low"
    assert not hasattr(ctx, "mood")
    assert ctx.is_empty() is False  # only via the legitimate dimension


def test_normalization_is_tolerant_but_never_guesses():
    assert normalize_level("stakes", "Life-Altering") == "life-altering"
    assert normalize_level("social_field", "publicly accountable") == "publicly_accountable"
    assert normalize_level("time_pressure", "URGENT") == "urgent"
    assert normalize_level("stakes", "cosmic") == "unknown"
    assert normalize_level("stakes", None) == "unknown"
    assert normalize_level("stakes", 42) == "unknown"
    assert normalize_level("stakes", "") == "unknown"


def test_parse_is_total():
    assert parse_decision_context(None).is_empty()
    assert parse_decision_context("garbage").is_empty()
    assert parse_decision_context(42).is_empty()
    assert parse_decision_context({"stakes": "bogus"}).is_empty()
    ctx = parse_decision_context({"stakes": "significant", "bogus_dim": "x"})
    assert ctx.stakes == "significant"
    assert ctx.time_pressure == "unknown"
    # idempotent on instances
    assert parse_decision_context(ctx) is ctx


def test_summarize_names_known_dimensions():
    ctx = DecisionContext(stakes="significant", time_pressure="urgent", information="thin")
    s = ctx.summarize()
    assert "significant stakes" in s
    assert "urgent" in s
    assert "thin information" in s


# ---------------------------------------------------------------------------
# signal attachment (migration-safe)
# ---------------------------------------------------------------------------


def test_signal_context_round_trip():
    sig = _signal("s1")
    assert get_signal_context(sig).is_empty()  # old record: no key -> all unknown
    set_signal_context(sig, DecisionContext(stakes="significant", information="thin"))
    back = get_signal_context(sig)
    assert back.stakes == "significant"
    assert back.information == "thin"
    assert back.time_pressure == "unknown"
    # stored as a plain dict under context_ref
    assert sig.context_ref["decision_context"]["stakes"] == "significant"


def test_plain_dict_signals_supported():
    raw: dict = {"context_ref": {}}
    assert get_signal_context(raw).is_empty()
    set_signal_context(raw, DecisionContext(reversibility="irreversible"))
    assert get_signal_context(raw).reversibility == "irreversible"


# ---------------------------------------------------------------------------
# similarity
# ---------------------------------------------------------------------------


def test_similarity_exact_partial_and_unknown():
    a = DecisionContext(stakes="significant", time_pressure="urgent")
    b = DecisionContext(stakes="significant", time_pressure="urgent", information="thin")
    assert context_similarity(a, b) == 1.0

    c = DecisionContext(stakes="significant", time_pressure="open-ended", information="thin")
    # compared: stakes + time_pressure (information unknown on a) -> 1/2
    assert context_similarity(a, c) == pytest.approx(0.5)

    d = DecisionContext(stakes="low")
    # compared: stakes only -> 0/1
    assert context_similarity(a, d) == 0.0

    # unknown dimensions neither help nor hurt
    assert context_similarity(DecisionContext(), DecisionContext()) == 0.0
    assert context_similarity(a, DecisionContext()) == 0.0


def test_similarity_threshold_constant_sane():
    assert 0.0 < CONTEXT_SIMILARITY_THRESHOLD <= 1.0


# ---------------------------------------------------------------------------
# conservative derivation
# ---------------------------------------------------------------------------


def test_derive_sets_only_explicit_cues():
    ctx = derive_decision_context(
        "This is urgent — the deadline is tomorrow and we're flying blind with no data."
    )
    assert ctx.time_pressure == "urgent"
    assert ctx.information == "thin"
    assert ctx.stakes == "unknown"  # not stated -> stays unknown


def test_derive_vague_text_stays_unknown():
    assert derive_decision_context("What should we do about lunch?").is_empty()
    assert derive_decision_context("").is_empty()
    assert derive_decision_context(None).is_empty()


def test_derive_explicit_envelope():
    ctx = derive_decision_context(
        "A life-altering, irreversible call and it's just me deciding alone with no budget."
    )
    assert ctx.stakes == "life-altering"
    assert ctx.reversibility == "irreversible"
    assert ctx.social_field == "solo"
    assert ctx.resource_climate == "scarcity"


# ---------------------------------------------------------------------------
# aggregation: decision signals -> proposed candidates (never published)
# ---------------------------------------------------------------------------


def test_seed_contextual_proposes_but_never_publishes(tmp_path):
    store = _store(tmp_path)
    try:
        sigs = _FakeSignals(
            [
                _signal("s1", context={"stakes": "significant", "time_pressure": "urgent"}),
                _signal("s2", context={"stakes": "significant", "time_pressure": "urgent"}),
                _signal("s3", context={"stakes": "low"}),
                _signal("s4"),  # no context -> skipped
                _signal("s5", layer="behavior", context={"stakes": "significant"}),  # wrong layer
            ]
        )
        made = seed_contextual_fingerprints(store, sigs, "u1")
        # two envelopes -> two candidates
        assert len(made) == 2
        assert store.version_count() == 0  # nothing published
        assert all(c.status == "proposed" for c in made)
        ops = [c.ops[0] for c in made]
        assert all(o.field == "contextual_fingerprints" and o.op == "add" for o in ops)
        sig_group = next(c for c in made if c.ops[0].value["decision_count"] == 2)
        assert sig_group.strand_key == "self"  # "strategy"/decision cues -> self
        assert sig_group.ops[0].value["context"]["stakes"] == "significant"
        assert "risk_bias" in sig_group.ops[0].value["fingerprint"]
        assert sig_group.confidence == pytest.approx(0.30)
        # dedup: re-running proposes nothing new
        assert seed_contextual_fingerprints(store, sigs, "u1") == []
        assert store.version_count() == 0
    finally:
        store.close()


def test_seed_contextual_skips_groups_without_fingerprint_cues(tmp_path):
    store = _store(tmp_path)
    try:
        sig = _signal("s9", context={"stakes": "low"})
        sig.summary = "Had a pleasant conversation about the weather today."
        made = seed_contextual_fingerprints(store, _FakeSignals([sig]), "u1")
        assert made == []
    finally:
        store.close()


# ---------------------------------------------------------------------------
# publish flow: contextual entries land, globals untouched
# ---------------------------------------------------------------------------


def test_publish_carries_contextual_fingerprints(tmp_path):
    store = _store(tmp_path)
    try:
        profile = _publish(store, "u1", _rich_self_ops())
        sp = profile.strands["self"]
        assert sp.fingerprint.risk_bias == "reversible first"  # global untouched
        assert len(sp.contextual_fingerprints) == 2
        entry = next(e for e in sp.contextual_fingerprints if e.context.stakes == "significant")
        assert isinstance(entry, ContextualFingerprint)
        assert entry.context.time_pressure == "urgent"
        assert entry.fingerprint.risk_bias == "Observed: took the reversible bet"
        assert entry.decision_count == 3
        # old profile JSON without the field still parses (migration-safe)
        raw = profile.model_dump()
        del raw["strands"]["self"]["contextual_fingerprints"]
        reparsed = PersonalityProfile(**raw)
        assert reparsed.strands["self"].contextual_fingerprints == []
    finally:
        store.close()


def test_candidate_op_validation_for_contextual_field():
    ok = CandidateOp(op="add", field="contextual_fingerprints", value=_ctx_value({}))
    assert ok.field == "contextual_fingerprints"
    with pytest.raises(Exception):
        CandidateOp(op="set", field="contextual_fingerprints", value=[])
    with pytest.raises(Exception):
        CandidateOp(op="add", field="fingerprint.risk_bias", value="x")


# ---------------------------------------------------------------------------
# council rendering: similarity-ranked, honest extrapolation
# ---------------------------------------------------------------------------


def _blend_personality(store, mode, decision_context):
    return resolve_council_personality(store, mode, decision_context)


def test_similar_envelope_surfaces_labeled(tmp_path):
    store = _store(tmp_path)
    try:
        _publish(store, "u1", _rich_self_ops())
        personality = _blend_personality(
            store, "blend", {"stakes": "significant", "time_pressure": "urgent"}
        )
        assert personality.decision_context is not None
        defn = dict(BUILT_IN_PERSONA_DEFINITIONS["guide"])
        base = _build_council_persona_block(defn)
        rendered = apply_council_personality(base, defn, personality, strand_key="self")
        assert rendered != base
        # the matching envelope surfaces with its envelope labeled
        assert "Under significant stakes, urgent" in rendered
        assert "context match" in rendered
        assert "100% context match" in rendered
        # the dissimilar envelope does not surface as a match
        assert "low stakes" not in rendered
        # no extrapolation note: we HAVE a similar observation
        assert "no observed decisions" not in rendered
    finally:
        store.close()


def test_dissimilar_envelope_triggers_honest_note(tmp_path):
    store = _store(tmp_path)
    try:
        _publish(store, "u1", _rich_self_ops())
        personality = _blend_personality(
            store, "blend", {"stakes": "life-altering", "reversibility": "irreversible"}
        )
        defn = dict(BUILT_IN_PERSONA_DEFINITIONS["guide"])
        base = _build_council_persona_block(defn)
        rendered = apply_council_personality(base, defn, personality, strand_key="self")
        assert "no observed decisions under these conditions" in rendered
        assert "life-altering stakes" in rendered
        # the global fingerprint still renders below the note (fallback intact)
        assert "reversible first" in rendered
    finally:
        store.close()


def test_no_envelope_means_todays_behavior(tmp_path):
    store = _store(tmp_path)
    try:
        _publish(store, "u1", _rich_self_ops())
        personality = _blend_personality(store, "blend", None)
        assert personality.decision_context is None
        defn = dict(BUILT_IN_PERSONA_DEFINITIONS["guide"])
        base = _build_council_persona_block(defn)
        rendered = apply_council_personality(base, defn, personality, strand_key="self")
        # trained envelopes named compactly, no similarity claims, no note
        assert "Decisions observed under:" in rendered
        assert "context match" not in rendered
        assert "no observed decisions" not in rendered
    finally:
        store.close()


def test_garbage_context_normalizes_to_none(tmp_path):
    store = _store(tmp_path)
    try:
        personality = _blend_personality(store, "blend", {"stakes": "cosmic", "x": 1})
        assert personality.decision_context is None
        personality = _blend_personality(store, "blend", "not a dict")
        assert personality.decision_context is None
    finally:
        store.close()


def test_mirror_mode_conditions_on_context(tmp_path):
    store = _store(tmp_path)
    try:
        _publish(store, "u1", _rich_self_ops())
        personality = _blend_personality(
            store, "mirror", {"stakes": "significant", "time_pressure": "urgent"}
        )
        defn = dict(BUILT_IN_PERSONA_DEFINITIONS["guide"])
        base = _build_council_persona_block(defn)
        rendered = apply_council_personality(base, defn, personality, strand_key="self")
        assert "The mirror" in rendered
        assert "Under significant stakes, urgent" in rendered
    finally:
        store.close()


def test_base_mode_ignores_context(tmp_path):
    store = _store(tmp_path)
    try:
        _publish(store, "u1", _rich_self_ops())
        personality = _blend_personality(
            store, "base", {"stakes": "significant", "time_pressure": "urgent"}
        )
        defn = dict(BUILT_IN_PERSONA_DEFINITIONS["guide"])
        base = _build_council_persona_block(defn)
        assert apply_council_personality(base, defn, personality, strand_key="self") == base
    finally:
        store.close()


def test_resolve_decision_context_precedence_and_safety():
    # explicit wins over derivation
    ctx = _resolve_decision_context({"stakes": "low"}, "urgent deadline, no data")
    assert ctx is not None and ctx.stakes == "low"
    # derivation fallback
    ctx = _resolve_decision_context(None, "urgent deadline, no data, flying blind")
    assert ctx is not None and ctx.time_pressure == "urgent" and ctx.information == "thin"
    # all-unknown -> None
    assert _resolve_decision_context(None, "what's for lunch") is None
    assert _resolve_decision_context(None, None) is None
    # never raises
    assert _resolve_decision_context(object(), object()) is None


# ---------------------------------------------------------------------------
# ask-gate invariant: the new paths create no versions silently
# ---------------------------------------------------------------------------


def test_no_silent_mutation_through_context_paths(tmp_path):
    store = _store(tmp_path)
    try:
        sigs = _FakeSignals([_signal("s1", context={"stakes": "significant"})])
        seed_contextual_fingerprints(store, sigs, "u1")
        assert store.version_count() == 0
        # proposing a contextual candidate directly also creates no version
        cand = ProfileCandidate(
            candidate_id="pc_ctx_direct",
            user_id="u1",
            strand_key="self",
            ops=[CandidateOp(op="add", field="contextual_fingerprints", value=_ctx_value({"stakes": "low"}))],
            source="manual",
            confidence=0.9,
            rationale="test",
            created_at=datetime.now(timezone.utc),
        )
        store.propose(cand)
        assert store.version_count() == 0
        profile = store.publish(["pc_ctx_direct"], source_summary="test")
        assert store.version_count() == 1
        assert len(profile.strands["self"].contextual_fingerprints) == 1
    finally:
        store.close()
