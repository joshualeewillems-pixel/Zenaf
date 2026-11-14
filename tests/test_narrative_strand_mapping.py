"""Steward strand-vocabulary mapping (founder ruling 2026-11-07 ~17:32 PT).

Defect (narrative-path audit §Q1, defect 1): thread/item strand
weights use lowercase strand keys (``word``/``people``/...) while
archetype strand weights use plain-spoken names
(``Voice``/``Heart``/...). Both ``relevance._cosine`` and
``derivation._cosine`` only lowercased keys, so the key sets were
disjoint and every cross-vocabulary cosine was 0.0 — the
``strand_alignment`` relevance rule (bar 0.30) could never fire, and
the item-seat comparison in ``derivation._has_jurisdiction_candidacy``
was dead the same way.

Fix: both cosines map keys through the canonical PLAIN_TO_KEY
(``local_ai/council/archetypes.py``) before comparing. No second
mapping table, no per-seat keys.

Audit probe (reproduced here): the demo thread's weights
``{"people": 0.8, "self": 0.6}`` against the conductor archetype —
naive lowercase-only cosine 0.0, mapped cosine 0.655 >= 0.30.

Out of scope here: EvidenceItem.strand_weights population (the
second strand defect — still open, founder's decision pending).
No model calls in any test.
"""

from __future__ import annotations

import pytest

from local_ai.council.archetypes import get_archetype
from local_ai.narrative import derivation, relevance
from local_ai.narrative.derivation import Cluster, EvidenceItem, _has_jurisdiction_candidacy, _linked
from local_ai.narrative.refs import SourceRef

# Audit probe vectors: the demo thread's weights (strand keys) and the
# conductor archetype's weights (plain-spoken names).
CANDIDATE_WEIGHTS = {"people": 0.8, "self": 0.6}
CONDUCTOR_WEIGHTS = dict(get_archetype("conductor").strand_weights)
STRAND_BAR = 0.30


def _naive_cosine(a: dict, b: dict) -> float:
    """The pre-fix behavior: lowercase keys only, no PLAIN_TO_KEY."""
    import math

    norm_a = {str(k).lower(): float(v) for k, v in (a or {}).items()}
    norm_b = {str(k).lower(): float(v) for k, v in (b or {}).items()}
    dot = sum(norm_a.get(k, 0.0) * v for k, v in norm_b.items())
    mag_a = math.sqrt(sum(v * v for v in norm_a.values()))
    mag_b = math.sqrt(sum(v * v for v in norm_b.values()))
    if mag_a <= 0 or mag_b <= 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _item(text: str, strand_weights: dict | None) -> EvidenceItem:
    return EvidenceItem(
        ref=SourceRef(kind="claim", ref_id=f"test:{text.split()[0]}"),
        text=text,
        strand_weights=strand_weights,
    )


def test_audit_probe_relevance_cosine():
    """Audit probe: 0.0 without the mapping, 0.655 with it (relevance)."""
    assert _naive_cosine(CANDIDATE_WEIGHTS, CONDUCTOR_WEIGHTS) == pytest.approx(0.0)
    assert relevance._cosine(CANDIDATE_WEIGHTS, CONDUCTOR_WEIGHTS) == pytest.approx(
        0.655, abs=1e-3
    )
    assert relevance._cosine(CANDIDATE_WEIGHTS, CONDUCTOR_WEIGHTS) >= STRAND_BAR


def test_audit_probe_derivation_cosine():
    """Audit probe: 0.0 without the mapping, 0.655 with it (derivation)."""
    assert _naive_cosine(CANDIDATE_WEIGHTS, CONDUCTOR_WEIGHTS) == pytest.approx(0.0)
    assert derivation._cosine(CANDIDATE_WEIGHTS, CONDUCTOR_WEIGHTS) == pytest.approx(
        0.655, abs=1e-3
    )
    assert derivation._cosine(CANDIDATE_WEIGHTS, CONDUCTOR_WEIGHTS) >= STRAND_BAR


def test_assess_relevance_strand_alignment_fires():
    """The relevance gate fires on strand_alignment alone.

    Empty candidate text (no focus overlap) and no entity refs rule
    out the other two rules, so only the strand rule can fire.
    """
    result = relevance.assess_relevance(
        "seat:conductor",
        candidate_text="",
        candidate_strand_weights=dict(CANDIDATE_WEIGHTS),
    )
    assert result.relevant is True
    assert result.reasons == ("strand_alignment",)
    assert result.inputs["strand_similarity"] == pytest.approx(0.655, abs=1e-3)


def test_assess_relevance_below_bar_does_not_fire():
    """A weakly aligned vector stays below the 0.30 bar (conductor).

    {"image": 1.0} vs conductor: 0.10 / sqrt(0.17) ~= 0.243 < 0.30.
    """
    result = relevance.assess_relevance(
        "seat:conductor",
        candidate_text="",
        candidate_strand_weights={"image": 1.0},
    )
    assert result.relevant is False
    assert result.reasons == ()
    assert result.inputs["strand_similarity"] == pytest.approx(0.243, abs=1e-3)


def test_derivation_jurisdiction_candidacy_strand_only():
    """Item-seat strand comparison fires candidacy (derivation.py:781-786).

    Gibberish item text hits no seat's focus corpus, so the focus
    rule cannot fire — only the strand rule can.
    """
    cluster = Cluster(
        items=[_item("zorblax quendrik falmoor", dict(CANDIDATE_WEIGHTS))]
    )
    assert _has_jurisdiction_candidacy(cluster) is True


def test_derivation_jurisdiction_candidacy_no_weights_no_fire():
    """Same cluster with no strand vector: no candidacy either way."""
    cluster = Cluster(items=[_item("zorblax quendrik falmoor", None)])
    assert _has_jurisdiction_candidacy(cluster) is False


@pytest.mark.parametrize("module", [relevance, derivation])
def test_normalize_strand_keys_maps_all_plain_names(module):
    """Every PLAIN_TO_KEY name maps; keyed names pass through."""
    normalized = module._normalize_strand_keys({
        "Voice": 1.0, "Logic": 1.0, "Eye": 1.0, "Ear": 1.0,
        "Hands": 1.0, "Heart": 1.0, "Compass": 1.0,
    })
    assert normalized == {
        "word": 1.0, "number": 1.0, "image": 1.0, "sound": 1.0,
        "body": 1.0, "people": 1.0, "self": 1.0,
    }
    # Keys already in key form pass through unchanged.
    assert module._normalize_strand_keys({"word": 0.5, "self": 0.5}) == {
        "word": 0.5, "self": 0.5,
    }
    # Plain names are matched case-insensitively.
    assert module._normalize_strand_keys({"voice": 1.0}) == {"word": 1.0}
    assert module._normalize_strand_keys({"VOICE": 1.0}) == {"word": 1.0}
    # Unknown keys pass through lowercased; None/empty is empty.
    assert module._normalize_strand_keys({"Mystery": 1.0}) == {"mystery": 1.0}
    assert module._normalize_strand_keys(None) == {}
    assert module._normalize_strand_keys({}) == {}


@pytest.mark.parametrize("module", [relevance, derivation])
def test_cosine_keyed_passthrough_and_disjoint(module):
    """Keyed-vs-keyed is unchanged; plain-vs-key maps; disjoint is 0.0."""
    assert module._cosine({"word": 1.0}, {"word": 1.0}) == pytest.approx(1.0)
    assert module._cosine({"Voice": 1.0}, {"word": 1.0}) == pytest.approx(1.0)
    assert module._cosine({"voice": 1.0}, {"WORD": 1.0}) == pytest.approx(1.0)
    assert module._cosine({"word": 1.0}, {"image": 1.0}) == pytest.approx(0.0)
    assert module._cosine({}, {"word": 1.0}) == pytest.approx(0.0)
    assert module._cosine({"word": 1.0}, {}) == pytest.approx(0.0)


def test_linked_cross_vocabulary_items():
    """Item-item strand link works across vocabularies too.

    Distinct gibberish texts (no shared tokens, no entity) leave the
    strand rule as the only possible link.
    """
    keyed = _item("zorblax quendrik", {"people": 0.8, "self": 0.6})
    plain = _item("falmoor brentok", {"Heart": 0.9, "Compass": 0.5})
    assert _linked(keyed, plain) is not None
    assert _linked(keyed, plain).startswith("strand similarity")
    keyed2 = _item("falmoor brentok", {"people": 0.9, "self": 0.5})
    assert _linked(keyed, keyed2) is not None
    assert _linked(keyed, keyed2).startswith("strand similarity")


def test_linked_disjoint_vectors_no_link():
    """Disjoint strand vectors do not link (and nothing else links)."""
    a = _item("zorblax quendrik", {"word": 1.0})
    b = _item("falmoor brentok", {"image": 1.0})
    assert _linked(a, b) is None
