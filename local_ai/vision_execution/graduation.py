"""Idea graduation: an idea becomes work when its practical fields are filled in.

The decided rule (2026-10-18): an idea graduates when enough *practical*
fields are filled in — the transition from thought experiment to work in
progress. The hierarchy is levels of importance/scope ("buy socks" is a task,
"start a sock company" is an initiative), never a rigid pipeline.

The miner may *suggest* a level, but the user decides at review time
(proposal -> user verdict, per the review philosophy).
"""
from __future__ import annotations

import json
from typing import Any

#: Every level an idea can land on. None (stays an idea) is the default.
TARGET_LEVELS = ("idea", "task", "project", "initiative")

#: Levels that count as graduation (leaving idea-hood behind).
GRADUATE_LEVELS = ("task", "project", "initiative")


class IdeaNotReadyError(Exception):
    """Graduation attempted before the idea's practical fields are filled."""

    def __init__(self, missing: list[str], idea_title: str = ""):
        self.missing = missing
        self.idea_title = idea_title
        where = f" '{idea_title}'" if idea_title else ""
        super().__init__(
            f"This idea{where} isn't ready to graduate yet — it's still a thought "
            f"experiment. Fill in: {', '.join(missing)}."
        )


def _as_list(v: Any) -> list:
    if not v:
        return []
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return list(v)


def graduation_readiness(idea: dict[str, Any]) -> tuple[bool, list[str]]:
    """Check whether an idea has enough practical fields to graduate.

    Uses only existing idea-schema fields (no new required columns in v1):
    a clear title, an expanded description, and at least one actionable /
    grounding field (intent, note, tag, person, or asset).

    Returns (ready, missing) with missing named in plain language.
    """
    missing: list[str] = []
    if not (idea.get("title") or "").strip():
        missing.append("a clear title")
    if not (idea.get("description") or "").strip():
        missing.append("an expanded description")
    grounded = any(
        [
            (idea.get("desired_outcome") or "").strip(),
            _as_list(idea.get("tags")),
            _as_list(idea.get("linked_people")),
            _as_list(idea.get("linked_assets")),
            (idea.get("notes") or "").strip(),
        ]
    )
    if not grounded:
        missing.append("a grounding detail — an intent, note, tag, person, or asset")
    return (not missing, missing)


def assert_ready(idea: dict[str, Any], idea_title: str = "") -> None:
    """Raise IdeaNotReadyError naming the missing fields when not ready."""
    ready, missing = graduation_readiness(idea)
    if not ready:
        raise IdeaNotReadyError(missing, idea_title or str(idea.get("title") or ""))


def build_graduated_payload(
    idea: dict[str, Any],
    target_level: str,
    source_idea_id: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Build a VE Create payload for the graduated entity.

    Preserves the idea's content (title, description, intent) and links
    provenance back to the source idea: initiatives carry source_idea_id
    (schema-native); projects/tasks carry it in notes.
    Returns (entity_type, payload_dict).
    """
    if target_level not in GRADUATE_LEVELS:
        raise ValueError(
            f"unknown target_level: {target_level!r} (expected one of {GRADUATE_LEVELS})"
        )
    title = (idea.get("title") or "").strip()
    description = (idea.get("description") or "").strip()
    summary = (idea.get("summary") or "").strip()
    desired_outcome = (idea.get("desired_outcome") or "").strip()
    notes = (idea.get("notes") or "").strip()

    detail = description or summary
    if desired_outcome:
        detail = (detail + "\n\nIntent: " + desired_outcome).strip()

    provenance = f"Graduated from idea '{title}'"
    if source_idea_id:
        provenance += f" ({source_idea_id})"
    full_notes = (provenance + ("\n\n" + notes if notes else "")).strip()

    if target_level == "task":
        return ("task", {
            "title": title,
            "description": detail,
            "notes": full_notes,
            "status": "Todo",
        })
    if target_level == "project":
        return ("project", {
            "title": title,
            "brief": detail,
            "notes": full_notes,
            "status": "Draft",
            "current_focus": desired_outcome,
        })
    payload: dict[str, Any] = {
        "title": title,
        "brief": detail,
        "notes": full_notes,
        "status": "Draft",
    }
    if source_idea_id:
        payload["source_idea_id"] = source_idea_id
    return ("initiative", payload)
