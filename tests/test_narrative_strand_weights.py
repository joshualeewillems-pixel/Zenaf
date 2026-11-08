"""Steward strand weights — bounded correction (proposal §8 + founder rulings Q1–Q5).

Pins:
- §8.1: entity lookup in event_to_item (T1–T4).
- §8.2: birth aggregate in both derivation birth paths (T7–T8) and the
  discovery birth path (T12 — gap-fill: proposal §3 names
  discovery.py:214 as a birth caller, but §8.2 wires only the two
  derivation paths; the discovery thread carries the mean of its
  parents' weights).
- Q3: recompute on extension, records-first and generation paths (T10).
- Q4: weights settable at creation for declared threads (T11).
- T5/T6: the derivation-internal strand rules fire on populated weights.
- T9: no invented weights.
- T13: the store's strand-weights setter (validation + clearing).

No relevance-gate outcomes are asserted: the strand rule's thread-side
comparison depends on the separate strand-fix (PLAIN_TO_KEY in the
cosines), so these tests pass with or without it.
"""

from __future__ import annotations

import json

import pytest

from local_ai.entity_strands import StrandWeighting
from local_ai.fellowship.events import FellowshipEvent
from local_ai.narrative import NarrativeStore, SourceRef
from local_ai.narrative.derivation import (
    Cluster,
    EvidenceItem,
    _cluster_strand_weights,
    _has_jurisdiction_candidacy,
    _linked,
    _recompute_thread_weights,
    derive_batch,
    event_to_item,
)
from local_ai.narrative.discovery import discover, propose
from local_ai.narrative.models import NarrativeThread

USER = "user-1"

#: Plain-name vectors (entity_strands' vocabulary). Each sums to 1.0.
COMPASS_ONLY: dict[str, float] = {
    "Voice": 0.0, "Logic": 0.0, "Eye": 0.0, "Ear": 0.0,
    "Hands": 0.0, "Heart": 0.0, "Compass": 1.0,
}
LOGIC_ONLY: dict[str, float] = {
    "Voice": 0.0, "Logic": 1.0, "Eye": 0.0, "Ear": 0.0,
    "Hands": 0.0, "Heart": 0.0, "Compass": 0.0,
}
MIXED: dict[str, float] = {
    "Voice": 0.1, "Logic": 0.2, "Eye": 0.0, "Ear": 0.0,
    "Hands": 0.0, "Heart": 0.1, "Compass": 0.6,
}

#: Nonsense wording: no focus term, no shared token with anything else.
NONSENSE_A = "quuxor flibberty wobble"
NONSENSE_B = "zibblenaut morptastic dremmel"
NONSENSE_C = "yarpish flendle snorvax"

#: Focus-anchored wording (S1's FOCUS_TEXT): "cultivation" is a
#: Gardener focus term, so clusters using it clear the jurisdiction
#: gate deterministically even with no strand vector.
FOCUS_TEXT = "cultivation in the orchard, learning what ripens"

#: Extension fixture, copied from tests/test_narrative_steward_s1.py
#: (same shape its extension tests use).
EXTENSION_JSON = json.dumps(
    {
        "tensions": ["roots vs. road, revisited"],
        "open_questions": ["what endures now?"],
        "milestones": ["pruned the old row"],
        "scales": ["personal"],
        "primary_scale": "personal",
        "change_kind": "extended",
    }
)


def _store(tmp_path):
    return NarrativeStore(db_path=tmp_path / "narrative.db")


def _event(event_id, text, entity="task:orchard-1"):
    entity_type, _, entity_id = entity.partition(":")
    return FellowshipEvent(
        id=event_id,
        kind="conversation_turn",
        user_id=USER,
        entity_type=entity_type,
        entity_id=entity_id,
        evidence_text=text,
        summary="orchard turn",
    )


def _item(ref_id, text, weights, entity_ref="task:orchard-1"):
    return EvidenceItem(
        ref=SourceRef(kind="event", ref_id=ref_id, evidence_kind="quote"),
        text=text,
        entity_ref=entity_ref,
        strand_weights=weights,
    )


def _lookup_stub(monkeypatch, weights, calls=None):
    """Stub get_entity_strands to return `weights` for any entity."""

    def stub(user_id, entity_type, entity_id):
        if calls is not None:
            calls.append((user_id, entity_type, entity_id))
        return StrandWeighting(
            entity_id=entity_id,
            entity_type=entity_type,
            strand_weights=weights,
            source="inferred",
            updated_at="2026-11-07T00:00:00+00:00",
        )

    monkeypatch.setattr(
        "local_ai.entity_strands.get_entity_strands", stub
    )
    return stub


def _counting_gen(payload, calls):
    def gen(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return payload

    return gen


def _seed_thread(store, weights, evidence_ref_id="evt-1"):
    """A live thread whose evidence derivation knows is about
    task:orchard-1 — seeded through the store + the annotation
    derivation itself would have written at attach time (S1's
    _seed_thread, extended with strand weights)."""
    thread = store.create_thread(
        USER,
        origin="user_declared",
        title="The orchard",
        strand_weights=weights,
        evidence_refs=[
            SourceRef(kind="event", ref_id=evidence_ref_id, evidence_kind="quote")
        ],
    )
    store.annotate_evidence_entities(
        USER, thread.id, {("event", evidence_ref_id): "task:orchard-1"}
    )
    return thread


# -- §8.1: entity lookup in event_to_item (T1–T4) ---------------------------


def test_t1_weighed_entity_populates_item(monkeypatch):
    """A weighed entity's stored vector lands on the item, plain
    names, unchanged values."""
    calls: list = []
    _lookup_stub(monkeypatch, MIXED, calls)
    item = event_to_item(_event("evt-1", NONSENSE_A))
    assert item.strand_weights == MIXED
    assert calls == [(USER, "task", "orchard-1")]


def test_t2_unweighed_entity_stays_none(monkeypatch):
    """An entity with no stored weighting stays honest unknown."""
    _lookup_stub(monkeypatch, None)
    item = event_to_item(_event("evt-1", NONSENSE_A))
    assert item.strand_weights is None


def test_t3_out_of_vocabulary_entity_type_skips_lookup(monkeypatch):
    """Entity types the table does not accept never reach the lookup."""

    def boom(user_id, entity_type, entity_id):
        raise AssertionError("lookup must not run for %r" % entity_type)

    monkeypatch.setattr("local_ai.entity_strands.get_entity_strands", boom)
    for entity in ("meeting:m1", "claim:c1", "conversation:cv1"):
        item = event_to_item(_event("evt-1", NONSENSE_A, entity=entity))
        assert item.strand_weights is None


def test_t4_lookup_failure_is_honest_unknown(monkeypatch):
    """A raising lookup degrades to None; no exception propagates."""

    def boom(user_id, entity_type, entity_id):
        raise RuntimeError("strand store down")

    monkeypatch.setattr("local_ai.entity_strands.get_entity_strands", boom)
    item = event_to_item(_event("evt-1", NONSENSE_A))
    assert item.strand_weights is None


# -- T5/T6: derivation-internal strand rules --------------------------------


def test_t5_item_item_link_fires_on_strands():
    """Two items with similar vectors link on strands alone — zero
    shared tokens, no shared entity — and do not link when either
    vector is missing."""
    a = _item("evt-a", NONSENSE_A, MIXED, entity_ref=None)
    b = _item("evt-b", NONSENSE_B, MIXED, entity_ref=None)
    assert _linked(a, b) == "strand similarity 1.00"
    c = _item("evt-c", NONSENSE_C, None, entity_ref=None)
    assert _linked(a, c) is None


def test_t6_jurisdiction_candidacy_fires_on_strands():
    """A Compass-heavy item clears the jurisdiction gate on strands
    alone (nonsense text: no focus-term hit); the same item without
    weights does not."""
    weighed = Cluster(items=[_item("evt-a", NONSENSE_A, MIXED)])
    assert _has_jurisdiction_candidacy(weighed) is True
    bare = Cluster(items=[_item("evt-a", NONSENSE_A, None)])
    assert _has_jurisdiction_candidacy(bare) is False


# -- §8.2: birth aggregate (T7–T8) + T9: no invented weights ---------------


def test_t7_birth_carries_aggregate(tmp_path):
    """A records-first birth passes the cluster aggregate (mean of
    the founding items, mapped to strand keys) to the store."""
    store = _store(tmp_path)
    items = [
        _item("evt-1", NONSENSE_A, COMPASS_ONLY),
        _item("evt-2", NONSENSE_B, LOGIC_ONLY),
    ]
    result = derive_batch(USER, items, store, generate_fn=None)
    assert len(result.births) == 1
    thread = store.get_thread(USER, result.births[0])
    assert thread is not None
    # Mean of {Compass: 1.0} and {Logic: 1.0}, key-mapped
    # (zero-weight strands omitted).
    assert thread.strand_weights == {"number": 0.5, "self": 0.5}
    assert thread.strand_weights == _cluster_strand_weights(items)


def test_t8_records_first_birth_signature_covers_weights(tmp_path):
    """create_thread_with_deferred_prose takes the optional weights
    parameter (and defaults to {} without it); unknown keys refuse."""
    store = _store(tmp_path)
    thread = store.create_thread_with_deferred_prose(
        USER,
        origin="steward_proposal",
        title="T",
        evidence_refs=[
            SourceRef(kind="event", ref_id="evt-1", evidence_kind="quote")
        ],
        deferred_kind="birth",
        evidence_signature="sig-1",
        evidence_texts=[],
        strand_weights={"self": 0.7, "number": 0.3},
    )
    assert thread.strand_weights == {"self": 0.7, "number": 0.3}
    plain = store.create_thread_with_deferred_prose(
        USER,
        origin="steward_proposal",
        title="U",
        evidence_refs=[],
        deferred_kind="birth",
        evidence_signature="sig-2",
        evidence_texts=[],
    )
    assert plain.strand_weights == {}
    with pytest.raises(ValueError):
        store.create_thread_with_deferred_prose(
            USER,
            origin="steward_proposal",
            title="V",
            evidence_refs=[],
            deferred_kind="birth",
            evidence_signature="sig-3",
            evidence_texts=[],
            strand_weights={"bogus": 1.0},
        )


def test_t9_no_invented_weights(tmp_path, monkeypatch):
    """A cluster of unweighed items produces None item weights and
    {} thread weights — the fix never synthesizes a vector."""
    _lookup_stub(monkeypatch, None)
    store = _store(tmp_path)
    items = [
        event_to_item(_event("evt-1", FOCUS_TEXT)),
        event_to_item(_event("evt-2", FOCUS_TEXT)),
    ]
    assert all(item.strand_weights is None for item in items)
    result = derive_batch(USER, items, store, generate_fn=None)
    assert len(result.births) == 1
    thread = store.get_thread(USER, result.births[0])
    assert thread is not None
    assert thread.strand_weights == {}


# -- Q3: recompute on extension (T10) ----------------------------------------


def test_t10a_recompute_unit():
    """The recompute is the count-weighted mean: the thread's current
    weights re-enter weighted by the number of previously attached
    evidence rows; each new weighed item enters once."""
    thread = NarrativeThread(
        id="thr-1", user_id=USER, strand_weights={"self": 0.6, "number": 0.4}
    )
    out = _recompute_thread_weights(
        thread, [_item("evt-9", NONSENSE_C, LOGIC_ONLY)], prior_attached_count=2
    )
    # (2 * {self: 0.6, number: 0.4} + {number: 1.0}) / 3
    assert out["self"] == pytest.approx(0.4)
    assert out["number"] == pytest.approx(0.6)
    # Nothing weighed on either side: weightless, not invented.
    bare = NarrativeThread(id="thr-2", user_id=USER, strand_weights={})
    assert (
        _recompute_thread_weights(bare, [_item("evt-9", NONSENSE_C, None)], 2)
        == {}
    )
    # Weightless thread + weighed extension: the mean of the new only.
    assert _recompute_thread_weights(
        bare, [_item("evt-9", NONSENSE_C, LOGIC_ONLY)], 1
    ) == {"number": 1.0}


def test_t10b_extension_records_first_recomputes(tmp_path, monkeypatch):
    """Records-first extension recomputes the thread's weights from
    all attached evidence (old aggregate weighted by the prior
    attached-row count, new items once each)."""
    _lookup_stub(monkeypatch, LOGIC_ONLY)
    store = _store(tmp_path)
    thread = _seed_thread(store, {"self": 1.0})
    result = derive_batch(
        USER, [event_to_item(_event("evt-2", NONSENSE_B))], store, generate_fn=None
    )
    assert result.births == []
    assert thread.id in result.deferred
    after = store.get_thread(USER, thread.id)
    assert after is not None
    # (1 * {self: 1.0} + {number: 1.0}) / 2
    assert after.strand_weights == {"self": 0.5, "number": 0.5}


def test_t10c_extension_generation_path_recomputes(tmp_path, monkeypatch):
    """The generation extension path recomputes too (one generation,
    change + reading proposed, weights refreshed)."""
    _lookup_stub(monkeypatch, LOGIC_ONLY)
    store = _store(tmp_path)
    thread = _seed_thread(store, {"self": 1.0})
    calls: list = []
    result = derive_batch(
        USER,
        [event_to_item(_event("evt-2", NONSENSE_B))],
        store,
        generate_fn=_counting_gen(EXTENSION_JSON, calls),
    )
    assert result.calls == 1
    assert len(result.changes) == 1 and len(result.readings) == 1
    after = store.get_thread(USER, thread.id)
    assert after is not None
    assert after.strand_weights == {"self": 0.5, "number": 0.5}


def test_t10d_extension_without_weighed_items_keeps_weights(tmp_path, monkeypatch):
    """Extending with unweighed evidence leaves the thread's weights
    exactly as they were (the extension still lands)."""
    _lookup_stub(monkeypatch, None)
    store = _store(tmp_path)
    thread = _seed_thread(store, {"self": 1.0})
    result = derive_batch(
        USER, [event_to_item(_event("evt-2", NONSENSE_B))], store, generate_fn=None
    )
    assert thread.id in result.deferred
    after = store.get_thread(USER, thread.id)
    assert after is not None
    assert after.strand_weights == {"self": 1.0}


def test_t10e_extension_onto_weightless_thread(tmp_path, monkeypatch):
    """Extending a weightless thread with weighed evidence gives the
    thread the new items' mean (the old side contributes nothing)."""
    _lookup_stub(monkeypatch, LOGIC_ONLY)
    store = _store(tmp_path)
    thread = _seed_thread(store, {})
    result = derive_batch(
        USER, [event_to_item(_event("evt-2", NONSENSE_B))], store, generate_fn=None
    )
    assert thread.id in result.deferred
    after = store.get_thread(USER, thread.id)
    assert after is not None
    assert after.strand_weights == {"number": 1.0}


# -- Q4: weights settable at creation for declared threads (T11) -------------


def test_t11_declared_thread_weights_settable_at_creation(tmp_path):
    """create_thread already accepts strand_weights, and its default
    origin is user_declared — a declared thread carries the weights
    it is given, and defaults to {} without them."""
    store = _store(tmp_path)
    thread = store.create_thread(
        USER,
        origin="user_declared",
        title="Declared",
        strand_weights={"self": 0.7, "number": 0.3},
    )
    assert thread.strand_weights == {"self": 0.7, "number": 0.3}
    assert store.get_thread(USER, thread.id).strand_weights == {
        "self": 0.7,
        "number": 0.3,
    }
    plain = store.create_thread(USER, origin="user_declared", title="Plain")
    assert plain.strand_weights == {}
    with pytest.raises(ValueError):
        store.create_thread(
            USER,
            origin="user_declared",
            title="Bad",
            strand_weights={"bogus": 1.0},
        )


# -- Discovery birth (T12) ----------------------------------------------------


def _pair_with_shared_entity_ref(store, weights_a, weights_b):
    """Two ACTIVE threads sharing one annotated entity ref
    (mirrors tests/test_steward_phase3.py::_pair_with_shared_ref):
    discovery only pairs active/dormant threads, and only on
    annotated entity refs — sharing an evidence ref_id alone does
    not pair. The shared ref is carried by exactly the pair, so it
    scores 2/2 = 1.0, the default gate."""
    ref_a = SourceRef(kind="event", ref_id="evt-a", evidence_kind="entity_ref")
    ref_b = SourceRef(kind="event", ref_id="evt-b", evidence_kind="entity_ref")
    thread_a = store.create_thread(
        USER,
        origin="user_declared",
        title="A",
        strand_weights=weights_a,
        evidence_refs=[ref_a],
    )
    thread_b = store.create_thread(
        USER,
        origin="user_declared",
        title="B",
        strand_weights=weights_b,
        evidence_refs=[ref_b],
    )
    store.set_thread_status(USER, thread_a.id, "active")
    store.set_thread_status(USER, thread_b.id, "active")
    store.annotate_evidence_entities(
        USER, thread_a.id, {("event", "evt-a"): "project:alpha"}
    )
    store.annotate_evidence_entities(
        USER, thread_b.id, {("event", "evt-b"): "project:alpha"}
    )
    return thread_a, thread_b


def test_t12_discovery_birth_carries_parent_mean(tmp_path):
    """A discovery thread carries the mean of its parents' weights;
    two weightless parents yield a weightless discovery."""
    store = _store(tmp_path)
    _pair_with_shared_entity_ref(store, {"self": 1.0}, {"number": 1.0})
    found = discover(store, USER)
    assert len(found.candidates) == 1
    made = propose(store, USER, found.candidates)
    assert len(made) == 1
    assert made[0].strand_weights == {"self": 0.5, "number": 0.5}


def test_t12b_discovery_birth_weightless_parents(tmp_path):
    """Two weightless parents yield a weightless discovery thread."""
    store = _store(tmp_path)
    _pair_with_shared_entity_ref(store, None, None)
    found = discover(store, USER)
    assert len(found.candidates) == 1
    made = propose(store, USER, found.candidates)
    assert len(made) == 1
    assert made[0].strand_weights == {}


# -- T13: the store's strand-weights setter -----------------------------------


def test_t13_set_thread_strand_weights(tmp_path):
    """The setter replaces the weights (validated), None clears them
    back to {}, unknown keys and unknown threads refuse."""
    store = _store(tmp_path)
    thread = store.create_thread(USER, origin="user_declared", title="T")
    assert thread.strand_weights == {}
    updated = store.set_thread_strand_weights(
        USER, thread.id, {"self": 0.4, "number": 0.6}
    )
    assert updated.strand_weights == {"self": 0.4, "number": 0.6}
    assert store.get_thread(USER, thread.id).strand_weights == {
        "self": 0.4,
        "number": 0.6,
    }
    cleared = store.set_thread_strand_weights(USER, thread.id, None)
    assert cleared.strand_weights == {}
    with pytest.raises(ValueError):
        store.set_thread_strand_weights(USER, thread.id, {"bogus": 1.0})
    with pytest.raises(ValueError):
        store.set_thread_strand_weights(USER, "thr-nope", {"self": 1.0})
