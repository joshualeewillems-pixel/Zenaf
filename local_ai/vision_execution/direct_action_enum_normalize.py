"""Map free-text phrases to canonical status/priority strings for Lane A enum_set."""
from __future__ import annotations

from typing import get_args

from local_ai.vision_execution.models import (
    IDEA_STATUS,
    INITIATIVE_STATUS,
    PROJECT_STATUS,
    TASK_STATUS,
)

_STATUS_ALLOWED: dict[str, frozenset[str]] = {
    "idea": frozenset(get_args(IDEA_STATUS)),
    "initiative": frozenset(get_args(INITIATIVE_STATUS)),
    "project": frozenset(get_args(PROJECT_STATUS)),
    "task": frozenset(get_args(TASK_STATUS)),
}

# Minimal synonyms — expand cautiously (wrong status is worse than decline).
_STATUS_SYNONYMS: dict[str, dict[str, str]] = {
    "idea": {
        "parked": "Parked",
        "archived": "Archived",
        "captured": "Captured",
        "clarifying": "Clarifying",
        "evaluated": "Evaluated",
    },
    "initiative": {
        "active": "Active",
        "live": "Active",
        "running": "Active",
        "paused": "Paused",
        "stopped": "Paused",
        "done": "Complete",
        "complete": "Complete",
        "finished": "Complete",
        "killed": "Killed",
        "dead": "Killed",
        "draft": "Draft",
        "evaluating": "Evaluating",
        "evaluation": "Evaluating",
        "approved": "Approved",
    },
    "project": {
        "active": "Active",
        "live": "Active",
        "ready": "Ready",
        "draft": "Draft",
        "blocked": "Blocked",
        "complete": "Complete",
        "done": "Complete",
        "finished": "Complete",
        "parked": "Parked",
        "paused": "Parked",
    },
    "task": {
        "todo": "Todo",
        "to do": "Todo",
        "pending": "Todo",
        "progress": "In Progress",
        "in progress": "In Progress",
        "working": "In Progress",
        "blocked": "Blocked",
        "stuck": "Blocked",
        "done": "Done",
        "complete": "Done",
        "finished": "Done",
        "dropped": "Dropped",
        "cancelled": "Dropped",
        "canceled": "Dropped",
    },
}


def normalize_status_value(entity_type: str, raw: str) -> str | None:
    et = (entity_type or "").strip().lower()
    s = (raw or "").strip()
    if not s or et not in _STATUS_ALLOWED:
        return None
    allowed = _STATUS_ALLOWED[et]
    for a in allowed:
        if a.casefold() == s.casefold():
            return a
    key = s.casefold().replace("-", " ").strip()
    syn = _STATUS_SYNONYMS.get(et, {}).get(key)
    if syn and syn in allowed:
        return syn
    return None


def normalize_priority_value(entity_type: str, raw: str) -> str | None:
    et = (entity_type or "").strip().lower()
    s = (raw or "").strip()
    if not s or et not in ("project", "task"):
        return None
    t = s.casefold()
    if t.isdigit():
        if et == "project" and t in "12345":
            return t
        if et == "task" and t in "12345":
            return t
    mp = {
        "lowest": "1",
        "low": "2",
        "medium": "3",
        "normal": "3",
        "med": "3",
        "mid": "3",
        "high": "4",
        "highest": "5",
        "critical": "5",
        "urgent": "5",
    }
    if t in mp:
        return mp[t]
    if et == "task":
        # Allow short labels if they match common words (stored as plain string in DB).
        for label in ("Low", "Medium", "High", "Urgent"):
            if t == label.casefold():
                return label
    return None
