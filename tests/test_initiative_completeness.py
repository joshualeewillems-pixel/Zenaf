"""Initiative display + completeness block for council inventory questions."""
from __future__ import annotations

from local_ai.vision_execution.initiative_completeness import (
    build_initiative_completeness_block,
    normalize_initiative_display_title,
)


def test_normalize_initiative_display_title_strips_prefix() -> None:
    assert normalize_initiative_display_title("Initiative · initiative: junk drawer") == "junk drawer"
    assert normalize_initiative_display_title("junk drawer") == "junk drawer"


def test_completeness_block_groups_surfaces() -> None:
    row = {
        "id": "i-1",
        "title": "T",
        "brief": "has brief",
        "owner_id": None,
        "source_idea_id": None,
        "dependencies": "",
        "risks": "",
        "kill_criteria": "",
        "required_assets": "[]",
        "seats": [],
    }
    text = build_initiative_completeness_block(row, user_id="u1", execution_step_count=0)
    assert "INITIATIVE COMPLETENESS" in text
    assert "Owner" in text
    assert "Source idea" in text
    assert "Execution steps" in text
    assert "checklist" in text.lower()
    assert "Diagnostics / admin notes" in text
    assert "Mutation truth" in text
