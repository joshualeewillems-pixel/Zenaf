"""Idea graduation: ideas sprout to task/project/initiative by scope.

Decided 2026-10-18: an idea graduates when enough *practical* fields are
filled in (thought experiment -> work in progress). The miner may suggest a
level; the user decides at review time. Covers:

- graduation_readiness: ready vs missing fields (named in plain language)
- create_confirmed routing: idea->task, idea->project, idea->initiative
- graduation blocked when practical fields are missing (nothing created)
- idea with no target_level stays an idea
- promote op on a confirmed idea (incl. provenance linkage)
- invalid target_level rejected
"""
from __future__ import annotations

import pytest

from local_ai.agent_intake import project_miner
from local_ai.vision_execution import graduation as G
from local_ai.vision_execution import service as ve


_uid_counter = [0]


def _next_uid() -> str:
    _uid_counter[0] += 1
    return f"grad-user-{_uid_counter[0]}"


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    """Isolate the VE SQLite DB per test."""
    import local_ai.vision_execution.storage as ve_store

    ve_db = tmp_path / "ve.db"
    monkeypatch.setattr(ve_store, "_DB_PATH", ve_db)
    monkeypatch.setattr(ve_store, "_DB_DIR", tmp_path)
    monkeypatch.setattr(ve_store, "_init_done_paths", set())
    monkeypatch.setattr(ve_store, "_thread_local", __import__("threading").local())
    return {"uid": _next_uid()}


def _ready_proposal(**kw):
    return project_miner.ProposedIdea(
        title=kw.get("title", "Sock company"),
        detail=kw.get("detail", "A company that sells socks with philosophy quotes on them."),
        source_quote=kw.get("source_quote", "I've been thinking about starting a sock company"),
        desired_outcome=kw.get("desired_outcome", "A real business selling socks"),
    )


def _result_with_idea(idea: project_miner.ProposedIdea) -> project_miner.MiningResult:
    return project_miner.MiningResult(
        initiatives=[], projects=[], standalone_tasks=[], ideas=[idea], engine="test"
    )


# --- readiness -------------------------------------------------------------


def test_readiness_ready_when_practical_fields_filled():
    ready, missing = G.graduation_readiness(
        {
            "title": "Sock company",
            "description": "Sell socks with quotes.",
            "desired_outcome": "A real business",
            "tags": [],
            "linked_people": [],
            "linked_assets": [],
            "notes": "",
        }
    )
    assert ready and missing == []


def test_readiness_names_missing_fields_plainly():
    ready, missing = G.graduation_readiness({"title": "  ", "description": ""})
    assert not ready
    assert any("title" in m for m in missing)
    assert any("description" in m for m in missing)
    assert any("grounding" in m for m in missing)


def test_readiness_grounding_can_be_note_tag_person_or_asset():
    base = {"title": "T", "description": "D"}
    for grounding in (
        {"notes": "some note"},
        {"tags": ["x"]},
        {"linked_people": ["p1"]},
        {"linked_assets": ["a1"]},
        {"desired_outcome": "intent"},
    ):
        ready, _ = G.graduation_readiness({**base, **grounding})
        assert ready, f"expected ready with grounding {grounding}"


# --- miner routing ---------------------------------------------------------


def test_idea_graduates_to_task(ve_ctx):
    idea = _ready_proposal()
    idea.target_level = "task"
    out = project_miner.create_confirmed(_result_with_idea(idea), ve_ctx["uid"])
    assert len(out["task_ids"]) == 1
    assert out["idea_ids"] == [], "graduated idea must not also be created as an idea"
    tasks = ve.list_tasks(ve_ctx["uid"])
    assert tasks[0]["title"] == "Sock company"
    assert "Graduated from idea" in (tasks[0].get("notes") or "")


def test_idea_graduates_to_project(ve_ctx):
    idea = _ready_proposal(title="Neighborhood tool library")
    idea.target_level = "project"
    out = project_miner.create_confirmed(_result_with_idea(idea), ve_ctx["uid"])
    assert len(out["project_ids"]) == 1
    assert out["idea_ids"] == []
    projects = ve.list_projects(ve_ctx["uid"])
    assert "Graduated from idea" in (projects[0].get("notes") or "")


def test_idea_graduates_to_initiative(ve_ctx):
    idea = _ready_proposal()
    idea.target_level = "initiative"
    out = project_miner.create_confirmed(_result_with_idea(idea), ve_ctx["uid"])
    assert len(out["initiative_ids"]) == 1
    initiatives = ve.list_initiatives(ve_ctx["uid"])
    assert initiatives[0]["title"] == "Sock company"


def test_idea_without_target_level_stays_idea(ve_ctx):
    idea = _ready_proposal()
    out = project_miner.create_confirmed(_result_with_idea(idea), ve_ctx["uid"])
    assert len(out["idea_ids"]) == 1
    assert out["task_ids"] == [] and out["project_ids"] == [] and out["initiative_ids"] == []
    ideas = ve.list_ideas(ve_ctx["uid"])
    assert ideas[0]["desired_outcome"] == "A real business selling socks"


def test_graduation_blocked_when_practical_fields_missing(ve_ctx):
    idea = project_miner.ProposedIdea(title="Vague notion", detail="", source_quote="")
    idea.target_level = "task"
    with pytest.raises(G.IdeaNotReadyError) as exc:
        project_miner.create_confirmed(_result_with_idea(idea), ve_ctx["uid"])
    assert exc.value.missing, "must name the missing fields"
    # Two-pass validation: nothing was created before the failure.
    assert ve.list_tasks(ve_ctx["uid"]) == []
    assert ve.list_ideas(ve_ctx["uid"]) == []


def test_invalid_target_level_rejected(ve_ctx):
    idea = _ready_proposal()
    idea.target_level = "empire"
    with pytest.raises(ValueError, match="target_level"):
        project_miner.create_confirmed(_result_with_idea(idea), ve_ctx["uid"])
    assert ve.list_tasks(ve_ctx["uid"]) == []


def test_miner_suggested_level_is_informational_only(ve_ctx):
    """suggested_level never graduates on its own — the user decides."""
    idea = _ready_proposal()
    idea.suggested_level = "task"
    out = project_miner.create_confirmed(_result_with_idea(idea), ve_ctx["uid"])
    assert len(out["idea_ids"]) == 1
    assert out["task_ids"] == []


# --- promote op ------------------------------------------------------------


def _confirmed_idea(uid: str, **kw):
    from local_ai.vision_execution import models as M

    data = {
        "title": kw.get("title", "Community fridge"),
        "description": kw.get("description", "A fridge on the corner for neighbors to share food."),
        "desired_outcome": kw.get("desired_outcome", "Less food waste on the block"),
        "status": "Captured",
    }
    return ve.create_idea(M.IdeaCreate(**data), uid)


def test_promote_idea_to_task(ve_ctx):
    uid = ve_ctx["uid"]
    idea = _confirmed_idea(uid)
    out = ve.promote_idea(idea["id"], "task", uid)
    assert out["entity_type"] == "task"
    assert out["entity"]["title"] == "Community fridge"
    assert "Graduated from idea" in (out["entity"].get("notes") or "")
    updated = ve.get_idea(idea["id"], uid)
    assert updated["status"] == "Graduated"
    assert "Graduated to task" in (updated.get("notes") or "")


def test_promote_idea_to_initiative_links_source(ve_ctx):
    uid = ve_ctx["uid"]
    idea = _confirmed_idea(uid, title="Start a sock company")
    out = ve.promote_idea(idea["id"], "initiative", uid)
    assert out["entity_type"] == "initiative"
    initiative = ve.get_initiative(out["entity"]["id"], uid)
    assert initiative["source_idea_id"] == idea["id"], "provenance must link back"


def test_promote_not_ready_names_missing_fields(ve_ctx):
    uid = ve_ctx["uid"]
    from local_ai.vision_execution import models as M

    idea = ve.create_idea(M.IdeaCreate(title="Half thought"), uid)
    with pytest.raises(G.IdeaNotReadyError) as exc:
        ve.promote_idea(idea["id"], "task", uid)
    assert exc.value.missing
    assert ve.get_idea(idea["id"], uid)["status"] == "Captured"


def test_promote_unknown_idea_raises(ve_ctx):
    with pytest.raises(ValueError, match="[Nn]ot found"):
        ve.promote_idea("nope", "task", ve_ctx["uid"])


def test_promote_twice_rejected(ve_ctx):
    uid = ve_ctx["uid"]
    idea = _confirmed_idea(uid)
    ve.promote_idea(idea["id"], "task", uid)
    with pytest.raises(ValueError, match="[Aa]lready graduated"):
        ve.promote_idea(idea["id"], "project", uid)
