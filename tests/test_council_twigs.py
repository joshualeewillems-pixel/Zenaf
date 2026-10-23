"""Tests for specialization twigs (local_ai/council/twigs.py).

Covers:
  * domain slug/label normalization;
  * weight blending math (50/50 default, 70/30 council nudge, normalization);
  * closest-parent selection and divergence thresholding;
  * sprout_twig proposal shape (never auto-approved);
  * TwigStore CRUD + status transitions;
  * apply_twig_overrides — approved twigs nudge matching seats; proposed
    twigs and non-matching domains leave seats untouched; caller dicts are
    never mutated.
"""
from __future__ import annotations

import pytest

from local_ai.council.archetypes import PLAIN_TO_KEY, get_archetype
from local_ai.council.twigs import (
    TwigRecord,
    TwigStore,
    apply_twig_overrides,
    blend_weights,
    closest_parent,
    domain_label_for,
    domain_matches_twig,
    domain_slug,
    sprout_twig,
)

STRANDS = tuple(PLAIN_TO_KEY.keys())


def _twig(
    twig_id="guardian-cooking",
    parent_id="guardian",
    domain="cooking",
    status="approved",
    signal_count=25,
) -> TwigRecord:
    parent = get_archetype(parent_id)
    assert parent is not None and parent.strand_weights is not None
    return TwigRecord(
        twig_id=twig_id,
        user_id="u1",
        parent_id=parent_id,
        domain=domain,
        domain_label="Cooking",
        display_name="Guardian of Cooking",
        strand_weights=dict(parent.strand_weights),
        prompt_frame="frame",
        status=status,
        signal_count=signal_count,
    )


# --- slug / label -----------------------------------------------------------

def test_domain_slug():
    assert domain_slug("Meal Planning") == "meal-planning"
    assert domain_slug("  cooking!! ") == "cooking"
    assert domain_slug("") == "general"


def test_domain_label():
    assert domain_label_for("meal planning") == "Meal Planning"
    assert domain_label_for("") == "General"


# --- blending ---------------------------------------------------------------

def test_blend_weights_halfway():
    parent = {"Compass": 1.0}
    cluster = {"Hands": 1.0}
    out = blend_weights(parent, cluster, cluster_share=0.5)
    assert out["Compass"] == pytest.approx(0.5)
    assert out["Hands"] == pytest.approx(0.5)
    assert abs(sum(out.values()) - 1.0) < 1e-9
    assert set(out) == set(STRANDS)


def test_blend_weights_council_nudge():
    parent = get_archetype("guardian")
    assert parent is not None and parent.strand_weights is not None
    twig_w = {"Heart": 1.0}
    out = blend_weights(parent.strand_weights, twig_w, cluster_share=0.30)
    # parent keeps 70%: guardian Heart 0.35 -> 0.245 + 0.30 = 0.545 before norm
    assert out["Heart"] > parent.strand_weights["Heart"]
    assert abs(sum(out.values()) - 1.0) < 1e-9


# --- closest parent / divergence --------------------------------------------

def test_closest_parent_picks_guardian_for_heart_cluster():
    parent_id, sim, max_sim = closest_parent({"Heart": 0.6, "Hands": 0.4})
    assert parent_id == "guardian"
    assert sim == pytest.approx(max_sim)
    assert sim > 0.85


def test_divergent_cluster_has_low_max_similarity():
    # An Ear-dominant cluster is far from every peaked stock vector
    # (no stock archetype weights Ear above 5%).
    pid, sim, max_sim = closest_parent({"Ear": 0.7, "Eye": 0.3})
    assert pid  # still picks the least-bad parent
    assert (1.0 - max_sim) > 0.25  # divergent per DIVERGENCE_THRESHOLD


def test_balanced_cluster_is_not_divergent():
    # A near-uniform distribution is well covered by the Conductor
    # (the most balanced stock archetype) — no twig needed.
    n = len(STRANDS)
    uniform = {s: 1.0 / n for s in STRANDS}
    _, _, max_sim = closest_parent(uniform)
    assert (1.0 - max_sim) <= 0.25


def test_stock_vector_is_not_divergent():
    mentor = get_archetype("mentor")
    assert mentor is not None and mentor.strand_weights is not None
    _, _, max_sim = closest_parent(mentor.strand_weights)
    assert (1.0 - max_sim) <= 0.25  # a stock vector matches itself


# --- domain matching ---------------------------------------------------------

def test_domain_matches_twig():
    assert domain_matches_twig("cooking", "Cooking", "What should I cook tonight?")
    assert domain_matches_twig("meal-planning", "Meal Planning", "meal planning for the week")
    assert not domain_matches_twig("cooking", "Cooking", "Q3 revenue forecast")
    assert not domain_matches_twig("cooking", "Cooking", "")


# --- sprouting (proposal-first) ----------------------------------------------

def test_sprout_twig_is_proposal(tmp_path):
    store = TwigStore(tmp_path / "twigs.db")
    try:
        cluster = {"Heart": 0.5, "Hands": 0.3, "Compass": 0.2}
        twig = sprout_twig("u1", "guardian", "Cooking", cluster, signal_count=22, store=store)
        assert twig.twig_id == "guardian-cooking"
        assert twig.display_name == "Guardian of Cooking"
        assert twig.status == "proposed"  # never auto-approved
        assert twig.parent_id == "guardian"
        assert abs(sum(twig.strand_weights.values()) - 1.0) < 1e-9
        # 50/50 blend: Heart = 0.5*0.35 + 0.5*0.5 = 0.425 before normalization
        assert twig.strand_weights["Heart"] == pytest.approx(0.425, rel=0.05)
        assert "cooking" in twig.prompt_frame.lower()
        # persisted
        assert store.get("u1", "guardian-cooking") is not None
    finally:
        store.close()


def test_sprout_twig_rejects_unknown_parent(tmp_path):
    store = TwigStore(tmp_path / "twigs.db")
    try:
        with pytest.raises(ValueError):
            sprout_twig("u1", "nope", "cooking", {"Heart": 1.0}, store=store)
    finally:
        store.close()


# --- store -------------------------------------------------------------------

def test_twig_store_crud(tmp_path):
    store = TwigStore(tmp_path / "twigs.db")
    try:
        store.save(_twig())
        assert store.has_domain("u1", "cooking")
        assert not store.has_domain("u1", "gardening")
        assert not store.has_domain("u2", "cooking")

        twigs = store.list("u1")
        assert len(twigs) == 1
        assert store.list("u1", status="proposed") == []
        assert len(store.list("u1", status="approved")) == 1
        assert len(store.list("u1", parent_id="guardian")) == 1
        assert store.list("u1", parent_id="mentor") == []

        assert store.set_status("u1", "guardian-cooking", "proposed") is True
        assert store.get("u1", "guardian-cooking").status == "proposed"
        assert store.set_status("u1", "missing", "approved") is False

        assert store.delete("u1", "guardian-cooking") is True
        assert store.get("u1", "guardian-cooking") is None
        assert store.delete("u1", "guardian-cooking") is False
    finally:
        store.close()


# --- apply_twig_overrides ----------------------------------------------------

def test_overrides_nudge_matching_seat(tmp_path):
    store = TwigStore(tmp_path / "twigs.db")
    try:
        store.save(_twig(status="approved"))
        seat = {"name": "Guardian", "archetype": "guardian"}
        out = apply_twig_overrides(
            [seat], "u1", "What should I cook for the family dinner?", None, store=store
        )
        assert out is not seat and out[0] is not seat  # no mutation of caller dicts
        assert seat.get("archetype_weights") is None  # original untouched
        nudged = out[0]
        assert nudged["archetype_name"] == "Guardian of Cooking"
        weights = nudged["archetype_weights"]
        assert abs(sum(weights.values()) - 1.0) < 1e-9
        # 70/30 nudge: twig == parent here, so weights match parent vector
        parent = get_archetype("guardian")
        assert parent is not None and parent.strand_weights is not None
        for s in STRANDS:
            assert weights[s] == pytest.approx(parent.strand_weights[s])
    finally:
        store.close()


def test_overrides_ignore_proposed_twigs(tmp_path):
    store = TwigStore(tmp_path / "twigs.db")
    try:
        store.save(_twig(status="proposed"))
        seat = {"name": "Guardian", "archetype": "guardian"}
        out = apply_twig_overrides(
            [seat], "u1", "What should I cook tonight?", None, store=store
        )
        assert out == [seat]
        assert "archetype_weights" not in out[0]
    finally:
        store.close()


def test_overrides_ignore_nonmatching_domain(tmp_path):
    store = TwigStore(tmp_path / "twigs.db")
    try:
        store.save(_twig(status="approved"))
        seat = {"name": "Guardian", "archetype": "guardian"}
        out = apply_twig_overrides(
            [seat], "u1", "Q3 revenue forecast review", None, store=store
        )
        assert "archetype_weights" not in out[0]
    finally:
        store.close()


def test_overrides_noop_without_archetype_seats(tmp_path):
    store = TwigStore(tmp_path / "twigs.db")
    try:
        store.save(_twig(status="approved"))
        seats = [{"name": "Plain seat"}]
        out = apply_twig_overrides([seats[0]], "u1", "cooking dinner", None, store=store)
        assert out == seats
    finally:
        store.close()


def test_overrides_noop_without_user(tmp_path):
    store = TwigStore(tmp_path / "twigs.db")
    try:
        seat = {"name": "Guardian", "archetype": "guardian"}
        assert apply_twig_overrides([seat], None, "cooking", None, store=store) == [seat]
        assert apply_twig_overrides(None, "u1", "cooking", None, store=store) is None
    finally:
        store.close()
