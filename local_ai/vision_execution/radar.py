"""
Strategic Radar — read-only summary of what needs attention.
Uses existing data and derived fields only; no new tables or heavy AI.
Bucket rules documented in docs/02_ACTIVE_DESIGN/VISION_EXECUTION_DESIGN.md §12.
Signals come from Layer 1 Signal entity (status not resolved/dismissed).
"""
from __future__ import annotations

import json
from typing import Any

from . import derived as D
from . import storage as S
from local_ai.signals import service as SigS

HIGH_VALUE_THRESHOLD = 70  # weightedScore >= this → "high value" (stricter to avoid cluttering)
LOW_SCORE_KILL_THRESHOLD = 45  # weightedScore < this → kill/watch candidate (Paused not auto-included)


def _initiative_has_next_steps_content(raw: str | None) -> bool:
    """True if next_step_ai holds legacy text, JSON steps payload, or JSON array."""
    t = (raw or "").strip()
    if not t:
        return False
    if t.startswith("{") or t.startswith("["):
        try:
            j = json.loads(t)
            if isinstance(j, dict):
                steps = j.get("steps")
                if isinstance(steps, list):
                    return any(str(x).strip() for x in steps)
                return False
            if isinstance(j, list):
                return any(str(x).strip() for x in j)
        except Exception:
            return False
    return True


def _signal_to_radar_item(s: dict[str, Any]) -> dict[str, Any]:
    """Map Layer 1 Signal dict to radar display shape (backward-compat with RadarSignalItem)."""
    kind = (s.get("kind") or "attention").lower()
    severity = "high" if kind in ("risk", "blocker") else "medium"
    return {
        "id": s.get("id", ""),
        "title": s.get("title", ""),
        "detail": s.get("detail") or "",
        "severity": severity,
        "source": s.get("source", ""),
        "source_excerpt": s.get("source_excerpt"),
        "kind": kind,
        "created_at": s.get("created_at", ""),
        "status": s.get("status"),
    }


def get_radar(user_id: str) -> dict[str, list[dict[str, Any]]]:
    """
    Build radar buckets from current initiatives, projects, tasks, capacity.
    Returns dict with keys: act_now, blocked, overcapacity, unanchored, high_value_stalled, kill_candidates.
    Each value is a list of minimal item dicts (type, id, title/name, and optional context).
    """
    initiatives = S.list_initiatives(user_id)
    for i in initiatives:
        D.add_initiative_derived(i)
    projects = S.list_projects(user_id)
    for p in projects:
        D.add_project_derived(p)
    tasks = S.list_tasks(user_id)
    capacity_list = S.list_capacity_profiles()
    for c in capacity_list:
        D.add_capacity_derived(c, c["person_id"], projects)
    persons = {p["id"]: p for p in S.list_persons()}

    initiative_ids_with_projects = {p["initiative_id"] for p in projects if p.get("initiative_id")}

    act_now: list[dict[str, Any]] = []
    for i in initiatives:
        status = (i.get("status") or "").strip()
        if status not in ("Approved", "Active"):
            continue
        no_owner = not (i.get("owner_id") or "").strip()
        no_next = not _initiative_has_next_steps_content(i.get("next_step_ai"))
        no_projects = i["id"] not in initiative_ids_with_projects
        if not (no_owner or no_next or no_projects):
            continue
        reason = "no_owner" if no_owner else ("no_next_step" if no_next else "no_linked_projects")
        act_now.append({
            "type": "initiative",
            "id": i["id"],
            "title": (i.get("title") or "").strip() or i["id"],
            "status": status,
            "reason": reason,
        })

    blocked: list[dict[str, Any]] = []
    for p in projects:
        if (p.get("status") or "").strip() == "Blocked":
            blocked.append({
                "type": "project",
                "id": p["id"],
                "title": (p.get("title") or "").strip() or p["id"],
                "status": "Blocked",
            })
    for t in tasks:
        if (t.get("status") or "").strip() == "Blocked":
            blocked.append({
                "type": "task",
                "id": t["id"],
                "title": (t.get("title") or "").strip() or t["id"],
                "project_id": t.get("project_id"),
                "status": "Blocked",
            })

    overcapacity: list[dict[str, Any]] = []
    for c in capacity_list:
        if not c.get("overcapacity"):
            continue
        pid = c["person_id"]
        person = persons.get(pid) or {}
        overcapacity.append({
            "type": "person",
            "id": pid,
            "name": (person.get("name") or "").strip() or pid,
            "active_weekly_hours": c.get("activeWeeklyHours"),
            "weekly_capacity_hours": c.get("weekly_capacity_hours"),
        })

    unanchored: list[dict[str, Any]] = []
    for p in projects:
        if not p.get("unanchoredFlag"):
            continue
        unanchored.append({
            "type": "project",
            "id": p["id"],
            "title": (p.get("title") or "").strip() or p["id"],
        })

    high_value_stalled: list[dict[str, Any]] = []
    for i in initiatives:
        status = (i.get("status") or "").strip()
        if status in ("Active", "Complete", "Killed"):
            continue
        ws = i.get("weightedScore")
        if ws is None or ws < HIGH_VALUE_THRESHOLD:
            continue
        high_value_stalled.append({
            "type": "initiative",
            "id": i["id"],
            "title": (i.get("title") or "").strip() or i["id"],
            "weighted_score": ws,
            "status": status,
        })

    kill_candidates: list[dict[str, Any]] = []
    for i in initiatives:
        status = (i.get("status") or "").strip()
        if status in ("Complete", "Killed"):
            continue
        ws = i.get("weightedScore")
        # Only low-score initiatives; Paused is not automatically included
        if ws is not None and ws < LOW_SCORE_KILL_THRESHOLD:
            kill_candidates.append({
                "type": "initiative",
                "id": i["id"],
                "title": (i.get("title") or "").strip() or i["id"],
                "weighted_score": ws,
                "status": status,
            })

    # Signals from canonical Layer 1 entity (exclude resolved/dismissed)
    raw_signals = SigS.list_signals(status_not_in=["resolved", "dismissed"])
    signals = [_signal_to_radar_item(s) for s in raw_signals]

    return {
        "act_now": act_now,
        "blocked": blocked,
        "overcapacity": overcapacity,
        "unanchored": unanchored,
        "high_value_stalled": high_value_stalled,
        "kill_candidates": kill_candidates,
        "signals": signals,
    }
