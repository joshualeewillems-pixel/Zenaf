"""
Core Profile context helpers.

Purpose: build a controlled, readable context block for evaluation prompts.
Intentionally excludes raw_notes (too noisy for evaluation prompts).
"""
from __future__ import annotations

from typing import Any


def _s(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, str):
        return val.strip()
    return str(val).strip()


def build_core_profile_summary(profile: dict[str, Any]) -> str:
    """
    Compose a structured summary used as evaluation context.

    Format (no header; evaluators wrap with 'Core Profile Context:'):
    - Definition: ...
    - Goals: ...
    - Growth Focus: ...
    - Economic Engine: ...
    - Non-Negotiables: ...
    - Strategic Filter: ...
    - Constraints: ...
    - Capacity: ...
    - Strengths: ...

    Empty fields are omitted to reduce prompt noise.
    """
    if not isinstance(profile, dict):
        return ""

    fields = [
        ("Definition", _s(profile.get("core_definition"))),
        ("Goals", _s(profile.get("current_goals"))),
        ("Growth Focus", _s(profile.get("growth_focus_12_months"))),
        ("Economic Engine", _s(profile.get("economic_engine"))),
        ("Non-Negotiables", _s(profile.get("non_negotiables"))),
        ("Strategic Filter", _s(profile.get("strategic_filter"))),
        ("Constraints", _s(profile.get("current_constraints"))),
        ("Capacity", _s(profile.get("capacity_limit"))),
        ("Strengths", _s(profile.get("strength_positioning"))),
    ]

    lines = [f"- {label}: {value}" for (label, value) in fields if value]
    return "\n".join(lines).rstrip()

