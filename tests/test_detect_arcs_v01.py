"""Unit tests for arc heuristic v0.1 (no DB)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from local_ai.vision_execution.detect_arcs import (
    HEURISTIC_V01,
    FlowReading,
    try_v01_friction_to_done,
)


def _ts(base: datetime, delta_hours: float) -> str:
    return (base + timedelta(hours=delta_hours)).replace(tzinfo=timezone.utc).isoformat()


@pytest.fixture
def t0() -> datetime:
    return datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_v01_happy_path(t0: datetime) -> None:
    readings = [
        FlowReading("a1", _ts(t0, 0), "negative", "friction", 0.6),
        FlowReading("e1", _ts(t0, 2), "positive", "clarity", 0.5),
    ]
    skip, payload = try_v01_friction_to_done(
        readings=readings,
        row_status="Done",
        row_updated_at=_ts(t0, 72),
    )
    assert skip is None
    assert payload is not None
    assert payload["t_avoid_reading_id"] == "a1"
    assert payload["t_eng_reading_id"] == "e1"
    assert payload["notes"]["heuristic"] == HEURISTIC_V01


def test_v01_missing_anchor(t0: datetime) -> None:
    readings = [
        FlowReading("e1", _ts(t0, 1), "positive", "clarity", 0.8),
    ]
    skip, payload = try_v01_friction_to_done(
        readings=readings,
        row_status="Done",
        row_updated_at=_ts(t0, 100),
    )
    assert skip == "missing_friction_anchor"
    assert payload is None


def test_v01_insufficient_span(t0: datetime) -> None:
    readings = [
        FlowReading("a1", _ts(t0, 0), "negative", "friction", 0.6),
        FlowReading("e1", _ts(t0, 1), "positive", "clarity", 0.5),
    ]
    skip, _ = try_v01_friction_to_done(
        readings=readings,
        row_status="complete",
        row_updated_at=_ts(t0, 10),
    )
    assert skip == "insufficient_span"
