"""
Vision Execution Engine — derived (computed) fields.
Computed on read only; not stored in the DB.
Formulas and decision rules are documented here and in docs/02_ACTIVE_DESIGN/VISION_EXECUTION_DESIGN.md.
"""
from __future__ import annotations

from typing import Any
import re

# -----------------------------------------------------------------------------
# INITIATIVE DERIVED FIELDS
# -----------------------------------------------------------------------------
# weightedScore:
#   Formula: weighted average of three 0–5 scores, scaled to 0–100.
#   Weights: priority_rank_manual 0.4, strategic_value_manual 0.4, energy_impact_manual 0.2.
#   priority_rank_manual is the user-visible effective priority; strategic_value_manual and
#   energy_impact_manual are evaluation-derived (set on Apply, not user-editable in UI).
#   evaluation_priority (model suggestion) is stored separately for human–model delta signals.
#   If any of the three is null/missing, weightedScore is null (we do not partial-score).
#
# approvalReady:
#   True when: (1) weightedScore is not null and >= APPROVAL_READY_THRESHOLD (60),
#   (2) brief is non-empty, (3) status is Draft or Evaluating.
#   Rationale: initiative has enough signal and is still in evaluation phase.
#
# returnOnTime:
#   0–1 score indicating whether we have time/cost estimates from AI.
#   1.0 = both estimated_cost_ai and estimated_timeframe_ai non-empty;
#   0.5 = exactly one non-empty; 0.0 = neither.
#   Rationale: "return on time" readiness = having feasibility estimates.
# -----------------------------------------------------------------------------

APPROVAL_READY_THRESHOLD = 60
MANUAL_SCORE_WEIGHTS = (0.4, 0.4, 0.2)  # priority, strategic, energy


def _norm_score(v: Any) -> float | None:
    """Normalize a manual score to 0–5. Accepts int/float; returns None if missing or invalid."""
    if v is None:
        return None
    try:
        x = float(v)
        if x < 0 or x > 10:  # allow 0–10 scale and clamp to 0–5 for formula
            x = max(0, min(5, x))
        elif x > 5:
            x = 5
        return x
    except (TypeError, ValueError):
        return None


def add_initiative_derived(initiative: dict[str, Any]) -> dict[str, Any]:
    """Attach weightedScore, approvalReady, returnOnTime. Mutates and returns the same dict."""
    p = _norm_score(initiative.get("priority_rank_manual"))
    s = _norm_score(initiative.get("strategic_value_manual"))
    e = _norm_score(initiative.get("energy_impact_manual"))
    if p is not None and s is not None and e is not None:
        weighted = (p * MANUAL_SCORE_WEIGHTS[0] + s * MANUAL_SCORE_WEIGHTS[1] + e * MANUAL_SCORE_WEIGHTS[2]) * (100 / 5)
        initiative["weightedScore"] = round(weighted, 1)
    else:
        initiative["weightedScore"] = None

    ws = initiative.get("weightedScore")
    brief_ok = bool((initiative.get("brief") or "").strip())
    status = (initiative.get("status") or "").strip()
    initiative["approvalReady"] = (
        ws is not None
        and ws >= APPROVAL_READY_THRESHOLD
        and brief_ok
        and status in ("Draft", "Evaluating")
    )

    cost_ok = bool((initiative.get("estimated_cost_ai") or "").strip())
    time_ok = bool((initiative.get("estimated_timeframe_ai") or "").strip())
    if cost_ok and time_ok:
        initiative["returnOnTime"] = 1.0
    elif cost_ok or time_ok:
        initiative["returnOnTime"] = 0.5
    else:
        initiative["returnOnTime"] = 0.0

    return initiative


# -----------------------------------------------------------------------------
# PROJECT DERIVED FIELDS
# -----------------------------------------------------------------------------
# duration:
#   Calendar days between start_date and end_date (inclusive of end day).
#   If either start_date or end_date is null/empty, duration is null.
#   Dates parsed as ISO date (YYYY-MM-DD) or best-effort; invalid format → null.
#
# completionReadiness:
#   0–1 score. Rules: +0.4 if status is Ready or Active; +0.3 if deliverables
#   non-empty; +0.3 if next_step_ai non-empty. Capped at 1.0.
#   Rationale: ready to execute when status is ready/active and we have
#   deliverables and a next step.
#
# unanchoredFlag:
#   True when initiative_id is null. "Unanchored" = not linked to an initiative.
# -----------------------------------------------------------------------------


def _parse_date(s: Any) -> int | None:
    """Return date as ordinal (days since epoch) for difference calc; None if invalid."""
    if s is None or not isinstance(s, str) or not s.strip():
        return None
    s = s.strip()[:10]
    if not re.match(r"\d{4}-\d{2}-\d{2}", s):
        return None
    try:
        from datetime import datetime
        dt = datetime.strptime(s, "%Y-%m-%d")
        return dt.toordinal()
    except ValueError:
        return None


def add_project_derived(project: dict[str, Any]) -> dict[str, Any]:
    """Attach duration, completionReadiness, unanchoredFlag. Mutates and returns the same dict."""
    start = _parse_date(project.get("start_date"))
    end = _parse_date(project.get("end_date"))
    if start is not None and end is not None and end >= start:
        project["duration"] = end - start + 1  # inclusive
    else:
        project["duration"] = None

    readiness = 0.0
    if (project.get("status") or "").strip() in ("Ready", "Active"):
        readiness += 0.4
    if (project.get("deliverables") or "").strip():
        readiness += 0.3
    if (project.get("next_step_ai") or "").strip():
        readiness += 0.3
    project["completionReadiness"] = round(min(1.0, readiness), 2)

    project["unanchoredFlag"] = project.get("initiative_id") is None or (project.get("initiative_id") or "").strip() == ""

    return project


# -----------------------------------------------------------------------------
# CAPACITY DERIVED FIELDS
# -----------------------------------------------------------------------------
# activeWeeklyHours:
#   Sum of project.estimated_weekly_hours for all projects where this person is
#   owner_id OR in supporting_owner_ids. Only projects with status in
#   (Ready, Active) are counted. If estimated_weekly_hours is null, treat as 0.
#   Rationale: reflects committed time from active/ready projects.
#
# capacityDelta:
#   activeWeeklyHours - weekly_capacity_hours. Positive = over-committed.
#
# overcapacity:
#   True when capacityDelta > 0 (person is allocated more hours than their
#   stated capacity).
# -----------------------------------------------------------------------------


def add_capacity_derived(
    capacity: dict[str, Any],
    person_id: str,
    projects: list[dict[str, Any]],
) -> dict[str, Any]:
    """Attach activeWeeklyHours, capacityDelta, overcapacity. Mutates and returns capacity dict."""
    active = 0.0
    for p in projects:
        status = (p.get("status") or "").strip()
        if status not in ("Ready", "Active"):
            continue
        if p.get("owner_id") == person_id:
            h = p.get("estimated_weekly_hours")
            active += float(h) if h is not None else 0.0
            continue
        supporting = p.get("supporting_owner_ids") or []
        if isinstance(supporting, str):
            supporting = []
        if person_id in supporting:
            h = p.get("estimated_weekly_hours")
            active += float(h) if h is not None else 0.0
    capacity["activeWeeklyHours"] = round(active, 1)

    cap_hours = capacity.get("weekly_capacity_hours")
    cap_hours = float(cap_hours) if cap_hours is not None else 0.0
    delta = active - cap_hours
    capacity["capacityDelta"] = round(delta, 1)
    capacity["overcapacity"] = delta > 0

    return capacity
