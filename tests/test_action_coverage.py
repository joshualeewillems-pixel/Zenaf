"""Registry loader and row resolution for Lane A coverage JSON."""
from __future__ import annotations

from local_ai.vision_execution import action_coverage as ac


def test_load_tier1_has_many_rows() -> None:
    rows = ac.load_tier1_coverage_rows()
    assert len(rows) >= 40


def test_find_text_set_initiative_brief() -> None:
    row = ac.find_text_set_row("initiative", "brief")
    assert row is not None
    assert row.get("handler") == "text_set"
    assert row.get("surface_key") == "brief"


def test_find_workflow_create_project() -> None:
    row = ac.find_workflow_row("workflow:create_project")
    assert row is not None
    assert "Project" in str(row.get("deterministic_confirmation_template") or "")


def test_resolve_text_set_requires_scope() -> None:
    parsed = {"kind": "text_set", "surface_key": "brief", "value": "x"}
    assert (
        ac.resolve_direct_surface_action(
            parsed=parsed,
            entity_id=None,
            entity_type=None,
            context=None,
        )
        is None
    )


def test_iter_rows_filter_handler() -> None:
    rows = list(ac.iter_rows(tier1_only=True, handler="text_set", entity="task"))
    assert rows
    assert all(r.get("entity") == "task" for r in rows)
