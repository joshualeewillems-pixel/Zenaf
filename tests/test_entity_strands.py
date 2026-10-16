"""Tests for local_ai.entity_strands — multi-strand entity weighting."""

import pytest

from local_ai.entity_strands import (
    ENTITY_TYPES,
    StrandWeighting,
    clear_entity_strands,
    get_entity_strands,
    set_entity_strands,
    suggest_weights,
    uniform_weights,
    validate_weights,
)


FULL = {
    "Voice": 0.3, "Logic": 0.25, "Eye": 0.15, "Ear": 0.05,
    "Hands": 0.1, "Heart": 0.1, "Compass": 0.05,
}


def test_validate_accepts_full_vector():
    out = validate_weights(dict(FULL))
    assert abs(sum(out.values()) - 1.0) < 1e-9
    assert set(out) == set(FULL)


def test_validate_fills_missing_with_zero():
    out = validate_weights({"Logic": 0.6, "Hands": 0.4})
    assert len(out) == 7
    assert out["Eye"] == 0.0


def test_validate_rejects_bad_input():
    for bad in (
        {},
        {"Voice": 0.5},                      # doesn't sum to 1
        {"Bogus": 1.0},                      # unknown strand
        {"Voice": -0.1, "Logic": 1.1},       # negative
        {"Voice": "lots"},                   # not a number
        "not a dict",
    ):
        with pytest.raises(ValueError):
            validate_weights(bad)


def test_entity_types_covered():
    assert set(ENTITY_TYPES) == {"person", "project", "task", "asset", "job"}


def test_strand_weighting_rejects_bad_type():
    with pytest.raises(ValueError):
        StrandWeighting("x", "bogus", None, None, "now")


def test_uniform_weights_sum_to_one():
    u = uniform_weights()
    assert len(u) == 7 and abs(sum(u.values()) - 1.0) < 1e-9


def test_suggest_weights_none_when_empty():
    assert suggest_weights({}) is None
    assert suggest_weights(None) is None  # type: ignore[arg-type]


def test_storage_round_trip_isolated_user():
    # Unknown entity -> null weights (honest, never zero).
    got = get_entity_strands("test-u-1", "project", "nope")
    assert got.strand_weights is None
    assert got.source is None

    saved = set_entity_strands("test-u-1", "project", "p1", dict(FULL), "user_stated")
    assert saved.dominant(1)[0][0] == "Voice"

    reread = get_entity_strands("test-u-1", "project", "p1")
    assert reread.source == "user_stated"
    assert abs(reread.strand_weights["Voice"] - 0.3) < 1e-9

    # Another user sees nothing (isolation).
    assert get_entity_strands("test-u-2", "project", "p1").strand_weights is None

    # Clear restores unknown.
    assert clear_entity_strands("test-u-1", "project", "p1") is True
    assert get_entity_strands("test-u-1", "project", "p1").strand_weights is None
    assert clear_entity_strands("test-u-1", "project", "p1") is False
