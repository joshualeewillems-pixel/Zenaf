"""Regression test: mined projects confirmed from review actually land in
Vision Execution and appear in the map/Gantt list endpoints.

Covers the bug Joshua hit 2026-10-14: tapping "Create N confirmed" on mined
project claims silently created nothing (client title-matching fragility),
so the Vision map showed "0 nodes" and the timeline was empty.

The fix: POST /agents/mined-projects/confirm accepts agent_id and resolves
proposals from the agent's stored mined_payload server-side; empty requests
return 422 instead of a silent 201.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from api.routes import agent_routes
from local_ai.agent_intake.store import AgentStore
from local_ai.agent_intake.schema import ConnectedAgent
from local_ai.vision_execution import service as ve


_uid_counter = [0]


def _next_uid() -> str:
    _uid_counter[0] += 1
    return f"regression-user-{_uid_counter[0]}"


PAYLOAD = {
    "engine": "test",
    "initiatives": [
        {"title": "Reg Initiative", "brief": "brief", "source_quote": "q", "project_titles": []}
    ],
    "projects": [
        {
            "title": "Reg Project",
            "goal": "goal",
            "status_hint": "ongoing",
            "source_quote": "q",
            "initiative_title": None,
            "tasks": [{"title": "Reg Task", "detail": "d", "source_quote": "q"}],
        }
    ],
    "standalone_tasks": [],
    "ideas": [
        {"title": "Reg Idea", "detail": "d", "source_quote": "q"}
    ],
}


def _agent_with_payload(store: AgentStore) -> ConnectedAgent:
    agent = ConnectedAgent(
        id="reg-agent-1",
        name="Reg chat",
        source_platform="chatgpt_share",
        description="Shared chat",
        instructions=None,
        examples=["USER: hello"],
        sort=None,
        status="pending_review",
        created_at="2026-10-14T00:00:00Z",
    )
    store.save(agent)
    store.set_mining_state(agent.id, "mined", payload=PAYLOAD)
    return agent


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    # Isolate the agent store DB and the VE DB per test (both are file-backed).
    import local_ai.vision_execution.storage as ve_store

    ve_db = tmp_path / "ve.db"
    monkeypatch.setattr(ve_store, "_DB_PATH", ve_db)
    monkeypatch.setattr(ve_store, "_DB_DIR", tmp_path)
    # Reset the module's init bookkeeping so the new path gets initialized.
    monkeypatch.setattr(ve_store, "_init_done_paths", set())
    monkeypatch.setattr(ve_store, "_thread_local", __import__("threading").local())

    uid = _next_uid()
    db_path = tmp_path / "agents.db"
    store = AgentStore(db_path=db_path, user_id=uid)
    _agent_with_payload(store)
    # Route handlers build their own store via _store(uid); point it at ours.
    monkeypatch.setattr(
        agent_routes, "_store", lambda u: store if u == uid else AgentStore(user_id=u)
    )
    return {"agent_id": "reg-agent-1", "uid": uid, "user": {"id": uid}}


def test_confirm_resolves_from_stored_payload(ctx):
    """Empty arrays + agent_id -> server resolves from mined_payload, entities created."""
    body = agent_routes.ConfirmMinedBody(agent_id=ctx["agent_id"])
    out = agent_routes.confirm_mined_projects(body, ctx["user"])
    assert out["project_ids"], "expected a project to be created"
    assert out["idea_ids"], "expected an idea to be created"
    assert out["task_ids"], "expected a task to be created"
    assert out["initiative_ids"], "expected an initiative to be created"


def test_created_entities_visible_in_ve_lists(ctx):
    """What the Vision map and Gantt read must include the confirmed entities."""
    body = agent_routes.ConfirmMinedBody(agent_id=ctx["agent_id"])
    agent_routes.confirm_mined_projects(body, ctx["user"])
    uid = ctx["uid"]
    assert [p["title"] for p in ve.list_projects(uid)] == ["Reg Project"]
    assert [i["title"] for i in ve.list_ideas(uid)] == ["Reg Idea"]
    assert [i["title"] for i in ve.list_initiatives(uid)] == ["Reg Initiative"]
    assert [t["title"] for t in ve.list_tasks(uid)] == ["Reg Task"]


def test_confirm_with_selected_titles_filters(ctx):
    body = agent_routes.ConfirmMinedBody(agent_id=ctx["agent_id"], selected_titles=["Reg Project"])
    out = agent_routes.confirm_mined_projects(body, ctx["user"])
    assert out["project_ids"]
    assert not out["idea_ids"], "unselected idea must not be created"


def test_confirm_empty_without_agent_id_is_422(ctx):
    """Silent 201 with zero entities was the bug — now it's a loud 422."""
    body = agent_routes.ConfirmMinedBody()
    with pytest.raises(HTTPException) as exc:
        agent_routes.confirm_mined_projects(body, ctx["user"])
    assert exc.value.status_code == 422


def test_confirm_unknown_agent_id_is_404(ctx):
    body = agent_routes.ConfirmMinedBody(agent_id="nope")
    with pytest.raises(HTTPException) as exc:
        agent_routes.confirm_mined_projects(body, ctx["user"])
    assert exc.value.status_code == 404
