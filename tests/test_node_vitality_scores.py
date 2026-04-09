"""Pure vitality score helpers (node_vitality_scores) — no DB."""
from __future__ import annotations

from local_ai.vision_execution.node_vitality_scores import (
    RULES_VERSION,
    compute_vitality_scores,
    staleness_days_for_row,
)


def test_rules_version_v2() -> None:
    assert RULES_VERSION == "v2"


def test_task_done_fruit_and_soil() -> None:
    row = {
        "title": "x",
        "description": "y" * 30,
        "completion_criteria": "z" * 20,
        "status": "Done",
        "updated_at": "2099-01-01T00:00:00+00:00",
    }
    m = compute_vitality_scores("task", row, None)
    assert m["fruit"] == 1.0
    assert m["water"] == 1.0
    assert m["soil"] > 0.0


def test_idea_fruit_status_not_done() -> None:
    row = {"status": "Captured", "updated_at": "2099-01-01T00:00:00+00:00", "title": "t"}
    m = compute_vitality_scores("idea", row, None)
    assert m["fruit"] == 0.3


def test_project_fruit_with_tasks_ratio() -> None:
    proj = {"status": "Active", "updated_at": "2099-01-01T00:00:00+00:00", "title": "p"}
    tasks = [{"status": "Done"}, {"status": "Open"}]
    m = compute_vitality_scores("project", proj, tasks)
    assert m["fruit"] == round(0.1 + 0.5 * 0.8, 4)


def test_staleness_days_for_row() -> None:
    assert staleness_days_for_row({"updated_at": None}) == 999.0
