"""Handler helpers and dispatch guards (persistence covered in test_direct_ve_action)."""
from __future__ import annotations

from local_ai.vision_execution.direct_action_handlers import (
    execute_direct_surface_action,
    format_confirmation_template,
    handler_name_for_row,
)


def test_format_confirmation_template() -> None:
    s = format_confirmation_template(
        "Created {task_count} {task_noun} under Project → {project_title}",
        task_count=2,
        task_noun="tasks",
        project_title="P",
    )
    assert "2" in s and "tasks" in s and "P" in s


def test_handler_name_maps_workflow_router_to_child_create() -> None:
    row = {"handler": "workflow_router", "surface_key": "workflow:create_project"}
    assert handler_name_for_row(row) == "child_create"


def test_execute_declines_when_handler_not_registered() -> None:
    row = {"handler": "date_set", "surface_key": "due_date"}
    out = execute_direct_surface_action(
        row,
        {"kind": "text_set", "surface_key": "brief", "value": "x"},
        context={},
        user_id="u",
        entity_id="e1",
        entity_type="initiative",
    )
    assert out["status"] == "declined"
