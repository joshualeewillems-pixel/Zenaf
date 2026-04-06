"""Lane A parse layer: phrases → normalized intents."""
from __future__ import annotations

from local_ai.vision_execution.direct_action_parsing import (
    normalize_field_update_value,
    parse_direct_action_intent,
    parse_task_titles,
)


def test_normalize_strips_inner_quotes() -> None:
    assert normalize_field_update_value('this " alpha beta gamma "') == "alpha beta gamma"


def test_parse_text_set_brief() -> None:
    p = parse_direct_action_intent('Change the brief to: "Hello world."')
    assert p is not None
    assert p["kind"] == "text_set"
    assert p["surface_key"] == "brief"
    assert "Hello world" in p["value"]


def test_parse_create_project() -> None:
    p = parse_direct_action_intent("Add a new project: Roadmap refresh")
    assert p is not None
    assert p["kind"] == "child_create_project"
    assert p["title"] == "Roadmap refresh"


def test_parse_batch_tasks_multiline() -> None:
    p = parse_direct_action_intent("Create tasks:\n- First item\n- Second item")
    assert p is not None
    assert p["kind"] == "child_create_tasks"
    assert p["titles"] == ["First item", "Second item"]


def test_parse_task_titles_comma_separated() -> None:
    assert parse_task_titles("Under that create tasks: Alpha, Beta") == ["Alpha", "Beta"]
