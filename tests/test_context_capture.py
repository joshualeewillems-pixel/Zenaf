"""Context capture: distillation tagging -> review confirm/correct -> seeding.

Covers the PR #42 capture side:
- distill.py extracts decision_context envelopes from LLM output (conservative).
- Review applies user context corrections to pending signals before approval.
- Approved signals are immutable under the capture path.
- End-to-end: distilled decision -> approved with context -> PR #41's
  seed_contextual_fingerprints proposes a candidate (never publishes).
"""
import json

from local_ai.personality.context import (
    get_signal_context,
    parse_decision_context,
)
from local_ai.presence_ingest.distill import _coerce_extraction, distill_events
from local_ai.presence_ingest.schema import PresenceEvent, TrainingSignal
from local_ai.presence_ingest.store import PresenceStore


def _events():
    return [
        PresenceEvent(
            event_id="e1",
            source="chatgpt",
            actor="user",
            kind="message",
            text="I decided to take the startup offer. It's a bet-the-company move for me, and I need to decide by Friday.",
            context={"conversation_title": "Career move"},
            provenance={"adapter": "chatgpt"},
        ),
        PresenceEvent(
            event_id="e2",
            source="chatgpt",
            actor="assistant",
            kind="message",
            text="Let's weigh the tradeoffs.",
            context={"conversation_title": "Career move"},
            provenance={"adapter": "chatgpt"},
        ),
    ]


def _decision_stub(prompt: str) -> str:
    assert "decision_context" in prompt  # prompt asks for the envelope
    return json.dumps(
        [
            {
                "layer": "decision",
                "zone": "strategy",
                "valence": "endorsed",
                "summary": "User took the startup offer, accepting real downside risk.",
                "detail": "Decided to take the startup offer after weighing options; acknowledged the risk.",
                "decision_context": {
                    "stakes": "life-altering",
                    "reversibility": "costly",
                    "time_pressure": "urgent",
                    "information": "thin",
                    "social_field": "solo",
                    "resource_climate": "scarcity",
                },
            }
        ]
    )


# ------------------------------------------------------------ distillation


def test_distill_extracts_decision_context():
    signals = distill_events(_events(), complete_fn=_decision_stub, session_id="s1")
    assert len(signals) == 1
    ctx = get_signal_context(signals[0])
    assert ctx.stakes == "life-altering"
    assert ctx.reversibility == "costly"
    assert ctx.time_pressure == "urgent"
    assert ctx.information == "thin"
    assert ctx.social_field == "solo"
    assert ctx.resource_climate == "scarcity"
    assert not ctx.is_empty()


def test_distill_conservative_unknown_when_absent_or_garbage():
    # No decision_context at all -> all unknown (honest, never guessed).
    coerced = _coerce_extraction(
        {"layer": "decision", "valence": "observed", "summary": "x"}
    )
    assert coerced is not None
    assert parse_decision_context(None).is_empty()
    assert coerced["decision_context"].is_empty()

    # Garbage levels -> unknown, never guessed.
    coerced = _coerce_extraction(
        {
            "layer": "decision",
            "valence": "observed",
            "summary": "x",
            "decision_context": {
                "stakes": "enormous",
                "time_pressure": "whenever-ish",
                "inner_state": "stressed",  # excluded dimension: ignored
            },
        }
    )
    ctx = coerced["decision_context"]
    assert ctx.stakes == "unknown"
    assert ctx.time_pressure == "unknown"
    assert not hasattr(ctx, "inner_state")


def test_distill_context_only_on_decision_layer():
    coerced = _coerce_extraction(
        {
            "layer": "behavior",
            "valence": "observed",
            "summary": "x",
            "decision_context": {"stakes": "high"},
        }
    )
    assert coerced is not None
    assert coerced["decision_context"] is None


def test_distill_signal_carries_envelope_in_context_ref():
    signals = distill_events(_events(), complete_fn=_decision_stub, session_id="s1")
    ref = signals[0].context_ref
    assert ref["decision_context"]["stakes"] == "life-altering"
    # session metadata still present alongside
    assert ref["source_events"] == ["e1", "e2"]


# ------------------------------------------------------- review confirm/correct


def _pending_store(tmp_path) -> PresenceStore:
    from local_ai.presence_ingest.schema import ImportSession

    store = PresenceStore(db_path=tmp_path / "sig.db")
    store.create_session(ImportSession(session_id="s1", source="chatgpt", file_name="c.json"))
    store.save_candidate_signals(
        distill_events(_events(), complete_fn=_decision_stub, session_id="s1")
    )
    return store


def test_review_applies_context_corrections_before_approval(tmp_path):
    from local_ai.presence_ingest import service as svc

    store = _pending_store(tmp_path)
    try:
        (sig,) = store.list_candidates("s1")
        corrected = {
            "stakes": "significant",  # user downgrades the model's "life-altering"
            "time_pressure": "urgent",
        }
        result = svc.review(
            "s1",
            {sig.signal_id: True},
            store=store,
            contexts={sig.signal_id: corrected},
        )
        assert result["approved"] == 1
        assert result["contexts_updated"] == 1
        (approved,) = store.list_signals(status="approved")
        ctx = get_signal_context(approved)
        assert ctx.stakes == "significant"  # user's correction won
        assert ctx.time_pressure == "urgent"
        assert ctx.information == "unknown"  # untouched dims stay as distilled
    finally:
        store.close()


def test_review_context_correction_without_approval_keeps_pending(tmp_path):
    from local_ai.presence_ingest import service as svc

    store = _pending_store(tmp_path)
    try:
        (sig,) = store.list_candidates("s1")
        result = svc.review(
            "s1", {}, store=store, contexts={sig.signal_id: {"stakes": "low"}}
        )
        assert result["contexts_updated"] == 1
        assert result["approved"] == 0
        (still_pending,) = store.list_candidates("s1")
        assert get_signal_context(still_pending).stakes == "low"
    finally:
        store.close()


def test_approved_signals_immutable_under_capture_path(tmp_path):
    from local_ai.presence_ingest import service as svc

    store = _pending_store(tmp_path)
    try:
        (sig,) = store.list_candidates("s1")
        svc.review("s1", {sig.signal_id: True}, store=store)
        before = get_signal_context(store.list_signals(status="approved")[0])

        # Capture-path corrections target the approved signal: must no-op.
        assert store.update_signal_context(sig.signal_id, {"stakes": "low"}) is False
        result = svc.review(
            "s1",
            {sig.signal_id: True},  # re-approving an approved signal: no-op
            store=store,
            contexts={sig.signal_id: {"stakes": "low"}},
        )
        assert result["contexts_updated"] == 0
        assert result["approved"] == 0
        after = get_signal_context(store.list_signals(status="approved")[0])
        assert after.model_dump() == before.model_dump()
    finally:
        store.close()


def test_update_signal_context_rejects_unknown_signal(tmp_path):
    store = _pending_store(tmp_path)
    try:
        assert store.update_signal_context("sig-nope", {"stakes": "low"}) is False
    finally:
        store.close()


# ---------------------------------------------------------------- end-to-end


def test_end_to_end_capture_to_contextual_candidate(tmp_path):
    """Distilled decision -> reviewed with context -> seed proposes a
    contextual-fingerprint candidate. Nothing is published."""
    from local_ai.personality.seed import seed_contextual_fingerprints
    from local_ai.personality.store import PersonalityStore
    from local_ai.presence_ingest import service as svc

    signals_store = _pending_store(tmp_path)
    personality_store = PersonalityStore(
        db_path=tmp_path / "personality.db", user_id="u1"
    )
    try:
        (sig,) = signals_store.list_candidates("s1")
        svc.review("s1", {sig.signal_id: True}, store=signals_store)

        versions_before = personality_store.list_versions()
        candidates = seed_contextual_fingerprints(
            personality_store, signals_store, "u1"
        )
        # The approved decision carried a non-empty envelope + risk cue text,
        # so it seeds exactly one contextual candidate...
        assert len(candidates) == 1
        cand = candidates[0]
        assert cand.strand_key == "self"  # zone "strategy" maps to self
        assert any(
            op.field == "contextual_fingerprints" for op in cand.ops
        )
        # ...and nothing was published: the ask gate holds.
        assert personality_store.list_versions() == versions_before
        assert len(personality_store.list_candidates()) == 1
    finally:
        signals_store.close()
        personality_store.close()
