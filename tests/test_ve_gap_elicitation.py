"""Structured VE gap elicitation (one prompt at a time + inventory ladder)."""
from __future__ import annotations

from pathlib import Path

import pytest

from local_ai.vision_execution import models as M
from local_ai.vision_execution import storage as ve_storage
from local_ai.vision_execution.ve_gap_elicitation import (
    attach_ve_gap_to_preflight,
    next_missing_field_prompt,
    top_missing_field_prompts,
)
from local_ai.vision_execution.storage import init_db, open_sqlite_with_ve_pragmas


@pytest.fixture
def ve_conn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "gap_elicit.db"
    conn = open_sqlite_with_ve_pragmas(db_path)
    init_db(conn)
    monkeypatch.setattr(ve_storage, "get_connection", lambda: conn)
    yield conn
    conn.close()


def test_initiative_owner_first() -> None:
    row = {"owner_id": None, "brief": "", "source_idea_id": None}
    p = next_missing_field_prompt("initiative", row, execution_step_count=0)
    assert p and p["field_key"] == "owner_id"
    assert "owner" in p["question"].lower()


def test_initiative_brief_after_owner() -> None:
    row = {"owner_id": "p1", "brief": "", "source_idea_id": None}
    p = next_missing_field_prompt("initiative", row, execution_step_count=0)
    assert p and p["field_key"] == "brief"


def test_project_tasks_last_in_chain() -> None:
    row = {
        "owner_id": "o",
        "brief": "b",
        "status": "Active",
        "supporting_owner_ids": ["x"],
        "start_date": "2026-01-01",
        "end_date": None,
        "estimated_weekly_hours": 2.0,
    }
    p = next_missing_field_prompt("project", row, task_count=0)
    assert p and p["field_key"] == "tasks"


def test_task_assignee_first() -> None:
    row = {"assignee_id": None, "status": "Todo", "due_date": "2026-02-01"}
    p = next_missing_field_prompt("task", row)
    assert p and p["field_key"] == "assignee_id"


def test_top_missing_limits_and_orders() -> None:
    row = {"owner_id": None, "brief": "", "source_idea_id": None}
    tops = top_missing_field_prompts("initiative", row, execution_step_count=0, limit=3)
    assert len(tops) == 3
    assert tops[0]["field_key"] == "owner_id"
    assert tops[1]["field_key"] == "brief"
    assert tops[2]["field_key"] == "source_idea_id"


def test_attach_inventory_missing_fields_kind(ve_conn) -> None:
    uid = "u-gap-inv"
    ini = ve_storage.create_initiative(M.InitiativeCreate(title="Gap", brief=""), uid)
    iid = str(ini["id"])
    cp: dict = {"ve_focus": {"entity_type": "initiative", "entity_id": iid}}
    attach_ve_gap_to_preflight(
        cp,
        conversation_subject_dict=None,
        user_id=uid,
        question_kind="missing_fields",
    )
    assert cp.get("ve_gap_mode") == "inventory"
    assert isinstance(cp.get("ve_gap_inventory"), list)
    assert len(cp["ve_gap_inventory"]) >= 1


def test_attach_decline_pivot(ve_conn) -> None:
    uid = "u-gap-dec"
    ini = ve_storage.create_initiative(M.InitiativeCreate(title="D", brief="b"), uid)
    iid = str(ini["id"])
    cp: dict = {
        "ve_focus": {"entity_type": "initiative", "entity_id": iid},
        "lane_a_mutation_intent_parsed": True,
        "lane_a_direct_action_declined": True,
        "lane_a_last_intent": {"kind": "person_assign"},
    }
    attach_ve_gap_to_preflight(
        cp,
        conversation_subject_dict=None,
        user_id=uid,
        question_kind="next_step",
    )
    assert cp.get("ve_gap_mode") == "decline_pivot"
    assert "could not apply" in str(cp.get("ve_gap_primary", {}).get("question", "")).lower()


def test_next_missing_field_prompt_alias() -> None:
    assert next_missing_field_prompt(
        "initiative", {"owner_id": None, "brief": "x", "source_idea_id": "i"}, execution_step_count=1
    ) is not None


def test_trunk_includes_decline_elicitation_block() -> None:
    from local_ai.conversation_trunk import conversational_partner_trunk_instructions, derive_mediation_profile

    kind = "next_step"
    contract = "three_options_then_lean"
    profile = derive_mediation_profile("q", kind, contract)
    block = conversational_partner_trunk_instructions(
        question_kind=kind,
        output_contract=contract,
        mediation_profile=profile,
        user_question="q",
        council_preflight_dict={
            "ve_gap_mode": "decline_pivot",
            "ve_gap_primary": {
                "question": "Who should own this?",
            },
        },
    )
    assert "LANE A + ELICITATION" in block
    assert "Who should own this?" in block
