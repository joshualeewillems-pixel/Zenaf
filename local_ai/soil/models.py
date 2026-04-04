"""Soil type to category mapping and capture-source rules."""

from __future__ import annotations

from typing import Literal

SOIL_TYPE_TO_CATEGORY: dict[str, str] = {
    "inbox": "inbox",
    "recurring_pattern": "recurring_patterns",
    "tension": "tensions",
    "hypothesis": "hypotheses",
    "excerpt": "excerpts",
    "mediation": "mediations",
    "entity_shadow": "entity_shadows",
    "route_observation": "route_observations",
    "candidate_truth": "candidate_truth",
}

CaptureSource = Literal["user_action", "named_system_capture", "manual_import"]

CAPTURE_SOURCES: frozenset[str] = frozenset(
    {"user_action", "named_system_capture", "manual_import"}
)

MATURATION_STATUSES: frozenset[str] = frozenset(
    {"seed", "sprout", "cluster", "candidate", "canonicalized"}
)


def category_for_soil_type(soil_type: str) -> str:
    cat = SOIL_TYPE_TO_CATEGORY.get((soil_type or "").strip())
    if not cat:
        raise ValueError(f"unknown soil_type: {soil_type!r}")
    return cat
