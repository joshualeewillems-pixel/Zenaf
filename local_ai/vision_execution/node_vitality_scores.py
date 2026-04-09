"""
Server-side water/soil/fruit scoring for node_vitality (VE row dicts).

Pure functions over row dicts — no DB calls, no side effects.
Rules version: v2 — soil weights align with structural field depth (notes, alignment, etc.).

Convergence note: keep numerically consistent with the frontend orchestrator
``assessNodeFlowAndChannels`` (see ``frontend/src/flow/assessNodeFlowAndChannels.ts`` and
``UNIFIED_NODE_ASSESSMENT_RULES_VERSION``). Extend ``tests/test_node_vitality_scores.py`` with
shared-input vectors when changing either side.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

RULES_VERSION = "v2"

_DONE_RE = re.compile(
    r"\b(done|complete|completed|shipped|closed|won)\b",
    re.IGNORECASE,
)


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def _days_since(iso: str | None) -> float:
    if not iso:
        return 999.0
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return max(0.0, (now - dt).total_seconds() / 86400.0)
    except Exception:
        return 999.0


def staleness_days_for_row(row: dict[str, Any]) -> float:
    """Calendar days since row's updated_at; aligns with water_from_row."""
    return _days_since(row.get("updated_at"))


def _text_depth(*fields: str | None) -> float:
    total = sum(len((f or "").strip()) for f in fields if f)
    if total == 0:
        return 0.0
    if total < 100:
        return 0.2
    if total < 500:
        return 0.5
    if total < 1500:
        return 0.75
    return 1.0


def _is_done(status: str | None) -> bool:
    return bool(_DONE_RE.search(status or ""))


# --- Soil (text depth / completeness) ---


def soil_from_idea(row: dict[str, Any]) -> float:
    return _clamp(
        _text_depth(
            row.get("title"),
            row.get("summary"),
            row.get("description"),
            row.get("desired_outcome"),
            row.get("notes"),
        )
    )


def soil_from_initiative(row: dict[str, Any]) -> float:
    return _clamp(
        _text_depth(
            row.get("title"),
            row.get("brief"),
            row.get("notes"),
            row.get("next_step_ai"),
            row.get("risks"),
            row.get("dependencies"),
            row.get("kill_criteria"),
            row.get("recommendation"),
            row.get("philosophical_alignment_ai"),
        )
    )


def soil_from_project(row: dict[str, Any]) -> float:
    return _clamp(
        _text_depth(
            row.get("title"),
            row.get("brief"),
            row.get("next_step_ai"),
            row.get("deliverables"),
            row.get("notes"),
            row.get("current_focus"),
        )
    )


def soil_from_task(row: dict[str, Any]) -> float:
    return _clamp(
        _text_depth(
            row.get("title"),
            row.get("description"),
            row.get("completion_criteria"),
            row.get("notes"),
        )
    )


# --- Fruit (completion / progress) ---


def fruit_from_idea(row: dict[str, Any]) -> float:
    status = row.get("status") or ""
    if _is_done(status):
        return 1.0
    if status:
        return 0.3
    return 0.0


def fruit_from_initiative(row: dict[str, Any], tasks: list[dict] | None = None) -> float:
    if _is_done(row.get("status")):
        return 1.0
    if tasks:
        done = sum(1 for t in tasks if _is_done(t.get("status")))
        ratio = done / len(tasks)
        return _clamp(0.1 + ratio * 0.8)
    return 0.1 if row.get("status") else 0.0


def fruit_from_project(row: dict[str, Any], tasks: list[dict] | None = None) -> float:
    if _is_done(row.get("status")):
        return 1.0
    if tasks:
        done = sum(1 for t in tasks if _is_done(t.get("status")))
        ratio = done / len(tasks)
        return _clamp(0.1 + ratio * 0.8)
    return 0.1 if row.get("status") else 0.0


def fruit_from_task(row: dict[str, Any]) -> float:
    return 1.0 if _is_done(row.get("status")) else 0.0


# --- Water (recency / activity) ---


def water_from_row(row: dict[str, Any]) -> float:
    days = _days_since(row.get("updated_at"))
    if days < 1:
        return 1.0
    if days < 3:
        return 0.85
    if days < 7:
        return 0.65
    if days < 14:
        return 0.45
    if days < 30:
        return 0.25
    if days < 60:
        return 0.1
    return 0.0


# --- Dispatch ---


def compute_vitality_scores(
    entity_type: str,
    row: dict[str, Any],
    tasks: list[dict] | None = None,
) -> dict[str, float]:
    """
    Returns {"water": float, "soil": float, "fruit": float}
    for any of the core four entity types.
    """
    et = entity_type.lower()
    water = water_from_row(row)

    if et == "idea":
        soil = soil_from_idea(row)
        fruit = fruit_from_idea(row)
    elif et == "initiative":
        soil = soil_from_initiative(row)
        fruit = fruit_from_initiative(row, tasks)
    elif et == "project":
        soil = soil_from_project(row)
        fruit = fruit_from_project(row, tasks)
    elif et == "task":
        soil = soil_from_task(row)
        fruit = fruit_from_task(row)
    else:
        soil = 0.0
        fruit = 0.0

    return {
        "water": round(water, 4),
        "soil": round(soil, 4),
        "fruit": round(fruit, 4),
    }
