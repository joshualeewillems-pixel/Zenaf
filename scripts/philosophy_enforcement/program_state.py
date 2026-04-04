"""
Program execution state for the convergence plan.

Source of truth: docs/01_TRUTH/convergence_program_state.json

The philosophy enforcement runner loads only this JSON — never the Markdown plan.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

STATE_RELATIVE = Path("docs/01_TRUTH/convergence_program_state.json")


class ProgramStateError(ValueError):
    """Invalid or missing convergence_program_state.json."""


def program_state_path(repo: Path) -> Path:
    return repo / STATE_RELATIVE


def load_program_state(repo: Path) -> dict[str, Any]:
    path = program_state_path(repo)
    if not path.is_file():
        raise ProgramStateError(
            f"Missing program state file: {path}. "
            "Create docs/01_TRUTH/convergence_program_state.json (see ATRIA_CONVERGENCE_PROGRAM_PLAN.md)."
        )
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ProgramStateError(f"Invalid JSON in {path}: {e}") from e
    if not isinstance(data, dict):
        raise ProgramStateError(f"{path}: root must be a JSON object")
    _validate_program_state(data, path)
    return data


def _validate_program_state(data: dict[str, Any], path: Path) -> None:
    required_top = (
        "active_phase",
        "active_objectives",
        "blocked",
        "notes",
        "operating_loop",
    )
    for key in required_top:
        if key not in data:
            raise ProgramStateError(f"{path}: missing required key {key!r}")

    phase = data["active_phase"]
    if not isinstance(phase, str) or not phase.strip():
        raise ProgramStateError(f"{path}: active_phase must be a non-empty string")

    objectives = data["active_objectives"]
    if not isinstance(objectives, list):
        raise ProgramStateError(f"{path}: active_objectives must be an array")
    if len(objectives) > 3:
        raise ProgramStateError(
            f"{path}: active_objectives must have at most 3 items, got {len(objectives)}"
        )
    for i, obj in enumerate(objectives):
        if not isinstance(obj, dict):
            raise ProgramStateError(f"{path}: active_objectives[{i}] must be an object")
        for fk in ("id", "title", "track"):
            if fk not in obj:
                raise ProgramStateError(
                    f"{path}: active_objectives[{i}] missing required key {fk!r}"
                )
            if not isinstance(obj[fk], str) or not str(obj[fk]).strip():
                raise ProgramStateError(
                    f"{path}: active_objectives[{i}].{fk} must be a non-empty string"
                )

    blocked = data["blocked"]
    if not isinstance(blocked, list):
        raise ProgramStateError(f"{path}: blocked must be an array")
    for i, item in enumerate(blocked):
        if not isinstance(item, str):
            raise ProgramStateError(f"{path}: blocked[{i}] must be a string")

    notes = data["notes"]
    if not isinstance(notes, str):
        raise ProgramStateError(f"{path}: notes must be a string")

    loop = data["operating_loop"]
    if not isinstance(loop, str) or not loop.strip():
        raise ProgramStateError(f"{path}: operating_loop must be a non-empty string")

    label = data.get("active_phase_label")
    if label is not None and not isinstance(label, str):
        raise ProgramStateError(f"{path}: active_phase_label must be a string when present")

    updated = data.get("updated_at")
    if updated is not None and not isinstance(updated, str):
        raise ProgramStateError(f"{path}: updated_at must be a string when present")
