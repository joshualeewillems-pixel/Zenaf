"""
Contract-backed initiative completeness for council inventory questions.

Used when the user asks what is empty, missing, or still needs filling — answers must not
flatten scalar fields, structured sections, evaluation outputs, and admin notes into one list.
"""
from __future__ import annotations

import json
import re
from typing import Any

_INITIATIVE_TITLE_NOISE = re.compile(
    r"(?i)^\s*Initiative\s*[·•]\s*initiative\s*:\s*(.+)\s*$",
)


def normalize_initiative_display_title(title: str | None) -> str:
    """Strip redundant 'Initiative · initiative: …' prefix from client/thread labels."""
    t = (title or "").strip()
    if not t:
        return t
    m = _INITIATIVE_TITLE_NOISE.match(t)
    return m.group(1).strip() if m else t


def _blank_text(v: Any) -> bool:
    return not str(v if v is not None else "").strip()


def _assets_empty(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, list):
        return len(v) == 0
    if isinstance(v, str):
        s = v.strip()
        if not s or s == "[]":
            return True
        try:
            p = json.loads(s)
            return not (isinstance(p, list) and len(p) > 0)
        except Exception:
            return False
    return False


def build_initiative_completeness_block(
    row: dict[str, Any],
    *,
    user_id: str,
    execution_step_count: int,
) -> str:
    """
    Markdown block appended to council context for ``missing_fields`` / ``state_inventory`` questions.

    ``row`` should be a full ``get_initiative`` dict (includes ``seats``).
    """
    iid = str(row.get("id") or "").strip()
    title = normalize_initiative_display_title(str(row.get("title") or "").strip() or None) or "(untitled)"

    core_empty: list[str] = []
    if _blank_text(row.get("owner_id")):
        core_empty.append("Owner")
    if _blank_text(row.get("source_idea_id")):
        core_empty.append("Source idea")
    if _blank_text(row.get("brief")):
        core_empty.append("Brief")

    structured_lines: list[str] = []
    if execution_step_count <= 0:
        structured_lines.append(
            "- **Execution steps:** no checklist rows yet — in the app this is a **step list**, not one free-text field."
        )
    seats = row.get("seats")
    seat_list = seats if isinstance(seats, list) else []
    if not seat_list:
        structured_lines.append("- **Required seats / roles:** none defined yet.")
    else:
        unassigned = sum(1 for s in seat_list if isinstance(s, dict) and _blank_text(s.get("assigned_person_id")))
        if unassigned == len(seat_list) and len(seat_list) > 0:
            structured_lines.append(
                f"- **Required seats / roles:** {len(seat_list)} row(s) — none have an assignee yet."
            )
    if _blank_text(row.get("dependencies")):
        structured_lines.append("- **Dependencies (text):** empty.")
    if _blank_text(row.get("risks")):
        structured_lines.append("- **Risks (text):** empty.")
    if _blank_text(row.get("kill_criteria")):
        structured_lines.append("- **Kill criteria:** empty.")
    if _assets_empty(row.get("required_assets")):
        structured_lines.append("- **Required assets:** none linked.")

    derived_bits: list[str] = [
        "Priority (0–5), Strategic value, Energy impact (often set after **Run evaluation**).",
        "Estimated cost, Estimated timeframe, Strategic alignment (AI), Recommendation — evaluation / decision lane.",
        "Legacy **Next step (AI)** text is transitional; canonical actionable work is **Execution steps**.",
    ]

    lines = [
        "**INITIATIVE COMPLETENESS (authoritative grouping — follow this shape in your answer):**",
        f"- Record: **{title}** (`initiative` id `{iid}`).",
        "",
        "**A) Core form fields that are still empty or unset:**",
        ("- " + ", ".join(core_empty)) if core_empty else "- (none of: Owner, Source idea, Brief — all have values)",
        "",
        "**B) Structured sections (extend in-app; do not describe as one scalar “field”):**",
        *(structured_lines if structured_lines else ["- (all listed sections have some content)"]),
        "",
        "**C) Evaluation / derived — not the same as “empty form fields”:**",
        *[f"- {b}" for b in derived_bits],
        "",
        "**D) Admin / diagnostics — do not foreground in a casual “what’s empty?” answer:**",
        "- **Diagnostics / admin notes** exists on the record; only discuss it if the user asked about notes, admin, or diagnostics.",
        "",
        "**Mutation truth:** Do **not** claim an Owner/Brief/etc. change **succeeded** unless this request includes an "
        "authoritative **INTEGRATION COMMITTED** overlay or a deterministic line like **Recorded →** / **Created →** from "
        "the server. Otherwise say you cannot confirm a save and suggest the user verify in Vision & Execution.",
    ]
    return "\n".join(lines)
