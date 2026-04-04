"""
Canonical Vision & Execution integration schema: storage keys, UI labels (match VisionExecutionView),
and trunk-token aliases. User-visible field names must come from here only.
"""
from __future__ import annotations

from typing import Final

# --- Entity type → storage_key → exact UI label (must match DetailField / section copy in the app) ---
_UI_LABEL_BY_ENTITY_AND_KEY: dict[str, dict[str, str]] = {
    "task": {
        "title": "Title",
        "description": "Description",
        "completion_criteria": "Completion criteria",
        "notes": "Notes",
    },
    "idea": {
        "title": "Title",
        "summary": "Short note",
        "description": "Expanded description",
        "desired_outcome": "Intent / what this idea is trying to become",
        "notes": "Notes",
    },
    "initiative": {
        "title": "Title",
        "brief": "Brief",
        "next_step_ai": "Next step (AI)",
        "notes": "Notes",
    },
    "project": {
        "title": "Title",
        "brief": "Brief (scope & outcomes)",
        "next_step_ai": "Next step (AI)",
        "notes": "Notes",
    },
}

# trunk / capture tokens (lowercase) → canonical storage_key per entity
# Task: product default — outcome-like capture maps to Description, not completion criteria.
_ALIASES: dict[str, dict[str, str]] = {
    "task": {
        "title": "title",
        "description": "description",
        "brief": "description",
        "summary": "description",
        "desired_outcome": "description",
        "goal": "description",
        "next_step": "description",
        "acceptance_criteria": "completion_criteria",
        "completion_criteria": "completion_criteria",
        "notes": "notes",
        "constraints": "notes",
        "audience_split": "notes",
        "unknown": "notes",
    },
    "idea": {
        "title": "title",
        "summary": "summary",
        "brief": "description",
        "description": "description",
        "desired_outcome": "desired_outcome",
        "goal": "desired_outcome",
        "notes": "notes",
        "acceptance_criteria": "notes",
        "constraints": "notes",
        "audience_split": "notes",
        "next_step": "notes",
        "unknown": "notes",
    },
    "initiative": {
        "title": "title",
        "brief": "brief",
        "summary": "brief",
        "desired_outcome": "brief",
        "goal": "brief",
        "next_step": "next_step_ai",
        "next_step_ai": "next_step_ai",
        "notes": "notes",
        "acceptance_criteria": "notes",
        "constraints": "notes",
        "audience_split": "notes",
        "description": "notes",
        "unknown": "notes",
    },
    "project": {
        "title": "title",
        "brief": "brief",
        "summary": "brief",
        "desired_outcome": "brief",
        "goal": "brief",
        "next_step": "next_step_ai",
        "next_step_ai": "next_step_ai",
        "notes": "notes",
        "acceptance_criteria": "notes",
        "constraints": "notes",
        "audience_split": "notes",
        "description": "notes",
        "unknown": "notes",
    },
}

_ENTITY_TYPE_UI: Final[dict[str, str]] = {
    "idea": "Idea",
    "initiative": "Initiative",
    "project": "Project",
    "task": "Task",
}


def entity_type_ui_heading(entity_type: str | None) -> str:
    t = (entity_type or "").strip().lower()
    return _ENTITY_TYPE_UI.get(t, (entity_type or "Item").strip().title() or "Item")


def allowed_storage_keys(entity_type: str) -> frozenset[str]:
    et = (entity_type or "").strip().lower()
    row = _UI_LABEL_BY_ENTITY_AND_KEY.get(et)
    return frozenset(row.keys()) if row else frozenset()


def normalize_trunk_token_to_storage_key(entity_type: str, token: str | None) -> str | None:
    """Map internal/trunk capture token to canonical DB/UI storage key, or None if unknown."""
    et = (entity_type or "").strip().lower()
    t = (token or "").strip().lower()
    if not t or not et:
        return None
    aliases = _ALIASES.get(et)
    if not aliases:
        return None
    if t in aliases:
        return aliases[t]
    # Already a canonical storage key
    labels = _UI_LABEL_BY_ENTITY_AND_KEY.get(et)
    if labels and t in labels:
        return t
    return None


def ui_label_for_storage_key(entity_type: str, storage_key: str) -> str | None:
    et = (entity_type or "").strip().lower()
    sk = (storage_key or "").strip().lower()
    row = _UI_LABEL_BY_ENTITY_AND_KEY.get(et)
    if not row:
        return None
    return row.get(sk)


def field_disambiguation_user_message(entity_type: str, entity_display_name: str) -> str:
    """
    When capture cannot be mapped to a single schema field, never imply a save.
    Entity-specific copy uses only schema-backed field names.
    """
    et = (entity_type or "").strip().lower()
    name = (entity_display_name or "").strip() or "this item"
    if et == "task":
        a = ui_label_for_storage_key("task", "description")
        b = ui_label_for_storage_key("task", "notes")
        return (
            f"I don't have a clear field for that on {name} — I can add it to **{a}** or **{b}**. Which do you want?"
        )
    if et == "idea":
        d = ui_label_for_storage_key("idea", "description")
        n = ui_label_for_storage_key("idea", "notes")
        return (
            f"I don't have a clear field for that on {name} — I can add it to **{d}** or **{n}**. Which do you want?"
        )
    if et == "initiative":
        br = ui_label_for_storage_key("initiative", "brief")
        n = ui_label_for_storage_key("initiative", "notes")
        return (
            f"I don't have a clear field for that on {name} — I can add it to **{br}** or **{n}**. Which do you want?"
        )
    if et == "project":
        br = ui_label_for_storage_key("project", "brief")
        n = ui_label_for_storage_key("project", "notes")
        return (
            f"I don't have a clear field for that on {name} — I can add it to **{br}** or **{n}**. Which do you want?"
        )
    return (
        "I don't have a clear Vision & Execution field for that yet — say which part of the item to update, "
        "or open the item in Vision & Execution and we'll align on the next turn."
    )
