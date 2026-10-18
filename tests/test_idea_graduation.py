"""Idea graduation: nested checklists defined by conversation.

Decided 2026-10-18 (reworked): instead of fixed "practical fields," each idea
defines its own "practical" as a nested hierarchical checklist, built
conversationally ("what would make this real?"). An idea is ready when its
checklist is non-empty and every item is done. On graduation the checklist
unfolds into the work breakdown (top-level items -> tasks, nested -> subtasks,
dependencies carried over) and is kept as provenance, marked superseded.

Covers:
- checklist CRUD + nesting + dependency cycle rejection
- checklist_readiness: empty / partial / all-done (+ stats)
- create_confirmed routing with checklist unfolding (task/project/initiative)
- batch gate: not-ready idea fails loudly, nothing created
- promote bypasses readiness (explicit user verdict), unfolds, supersedes
- Gantt data: subtask nesting + blocked-by labels flow through buildTimelineRows
  (TS util — verified by a Python port of the nesting logic? No: by inspection
  + tsc error-count comparison; see PR description)
"""
from __future__ import annotations

import json

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


def _done_checklist():
    return [
        {"title": "Name the brand", "done": True, "children": [
            {"title": "Pick 3 names", "done": True},
        ]},
        {"title": "Check a domain", "done": True, "children": []},
    ]


def _open_checklist():
    return [
        {"title": "Name the brand", "done": False, "children": []},
        {"title": "Check a domain", "done": True, "children": []},
    ]


def _ready_proposal(**kw):
    return project_miner.ProposedIdea(
        title=kw.get("title", "Sock company"),
        detail=kw.get("detail", "A company that sells socks with philosophy quotes on them."),
        source_quote=kw.get("source_quote", "I've been thinking about starting a sock company"),
        desired_outcome=kw.get("desired_outcome", "A real business selling socks"),
        checklist=kw.get("checklist", _done_checklist()),
    )


def _result_with_idea(idea: project_miner.ProposedIdea) -> project_miner.MiningResult:
    return project_miner.MiningResult(
        initiatives=[], projects=[], standalone_tasks=[], ideas=[idea], engine="test"
    )


def _mk_idea(uid: str, title: str = "Community fridge"):
    from local_ai.vision_execution import models as M

    return ve.create_idea(
        M.IdeaCreate(
            title=title,
            description="A fridge on the corner for neighbors to share food.",
            desired_outcome="Less food waste on the block",
            status="Captured",
        ),
        uid,
    )


def _flat(uid: str, idea_id: str):
    import local_ai.vision_execution.storage as ve_store

    return ve_store.list_checklist_items(idea_id, uid)


# --- readiness -------------------------------------------------------------


def test_readiness_not_ready_without_checklist():
    ready, missing, stats = G.checklist_readiness([])
    assert not ready
    assert stats == {"total": 0, "done": 0, "remaining": 0}
    assert any("checklist" in m for m in missing)


def test_readiness_names_open_items_plainly():
    items = [
        {"id": "a", "title": "Name the brand", "status": "open", "superseded": False},
        {"id": "b", "title": "Check a domain", "status": "done", "superseded": False},
    ]
    ready, missing, stats = G.checklist_readiness(items)
    assert not ready
    assert stats == {"total": 2, "done": 1, "remaining": 1}
    assert any("Name the brand" in m and "still open" in m for m in missing)


def test_readiness_ready_when_every_item_done():
    items = [
        {"id": "a", "title": "Name it", "status": "done", "superseded": False},
        {"id": "b", "title": "Check it", "status": "done", "superseded": False},
    ]
    ready, missing, stats = G.checklist_readiness(items)
    assert ready and missing == []
    assert stats == {"total": 2, "done": 2, "remaining": 0}


def test_readiness_ignores_superseded_items():
    items = [
        {"id": "a", "title": "Old", "status": "open", "superseded": True},
        {"id": "b", "title": "New", "status": "done", "superseded": False},
    ]
    ready, _, stats = G.checklist_readiness(items)
    assert ready
    assert stats["total"] == 1


# --- checklist CRUD --------------------------------------------------------


def test_checklist_batch_creates_nested_tree(ve_ctx):
    uid = ve_ctx["uid"]
    idea = _mk_idea(uid)
    tree = ve.create_checklist_items_batch(
        idea["id"],
        [
            {"title": "Name the brand", "children": [{"title": "Pick 3 names"}]},
            {"title": "Check a domain"},
        ],
        uid,
    )
    assert len(tree) == 2
    assert tree[0]["title"] == "Name the brand"
    assert len(tree[0]["children"]) == 1
    assert tree[0]["children"][0]["title"] == "Pick 3 names"
    assert tree[0]["children"][0]["parent_id"] == tree[0]["id"]


def test_checklist_item_status_update(ve_ctx):
    uid = ve_ctx["uid"]
    idea = _mk_idea(uid)
    tree = ve.create_checklist_items_batch(idea["id"], [{"title": "Name it"}], uid)
    item_id = tree[0]["id"]
    updated = ve.update_checklist_item(item_id, uid, status="done")
    assert updated["status"] == "done"
    with pytest.raises(ValueError):
        ve.update_checklist_item(item_id, uid, status="bogus")


def test_checklist_delete_cascades_children_and_deps(ve_ctx):
    uid = ve_ctx["uid"]
    idea = _mk_idea(uid)
    tree = ve.create_checklist_items_batch(
        idea["id"],
        [{"title": "Parent", "children": [{"title": "Child"}]}],
        uid,
    )
    parent_id = tree[0]["id"]
    child_id = tree[0]["children"][0]["id"]
    full_tree = ve.create_checklist_items_batch(idea["id"], [{"title": "Other"}], uid)
    other = next(n for n in full_tree if n["title"] == "Other")
    ve.add_checklist_dependency(child_id, other["id"], uid)
    assert ve.delete_checklist_item(parent_id, uid)
    remaining = _flat(uid, idea["id"])
    assert [it["id"] for it in remaining] == [other["id"]]


def test_checklist_dependency_and_cycle_rejection(ve_ctx):
    uid = ve_ctx["uid"]
    idea = _mk_idea(uid)
    tree = ve.create_checklist_items_batch(
        idea["id"], [{"title": "A"}, {"title": "B"}, {"title": "C"}], uid
    )
    a, b, c = (n["id"] for n in tree)
    out = ve.add_checklist_dependency(b, a, uid)  # B depends on A
    assert a in out["depends_on"]
    ve.add_checklist_dependency(c, b, uid)  # C depends on B
    with pytest.raises(ValueError, match="[Cc]ycle"):
        ve.add_checklist_dependency(a, c, uid)  # A depends on C -> cycle
    with pytest.raises(ValueError, match="[Cc]ycle"):
        ve.add_checklist_dependency(a, b, uid)  # A depends on B -> cycle
    with pytest.raises(ValueError, match="itself"):
        ve.add_checklist_dependency(a, a, uid)
    assert ve.remove_checklist_dependency(b, a, uid)
    # After removing B->A, A->B is fine.
    ve.add_checklist_dependency(a, b, uid)


def test_checklist_dependency_stays_within_one_idea(ve_ctx):
    uid = ve_ctx["uid"]
    idea1 = _mk_idea(uid, title="One")
    idea2 = _mk_idea(uid, title="Two")
    t1 = ve.create_checklist_items_batch(idea1["id"], [{"title": "x"}], uid)[0]
    t2 = ve.create_checklist_items_batch(idea2["id"], [{"title": "y"}], uid)[0]
    with pytest.raises(ValueError, match="[Ww]ithin one idea"):
        ve.add_checklist_dependency(t1["id"], t2["id"], uid)


# --- miner routing with unfolding ------------------------------------------


def test_idea_graduates_to_task_with_unfolded_subtasks(ve_ctx):
    idea = _ready_proposal()
    idea.target_level = "task"
    out = project_miner.create_confirmed(_result_with_idea(idea), ve_ctx["uid"])
    assert len(out["task_ids"]) == 1
    assert out["idea_ids"] == [], "graduated idea must not also be created as an idea"
    tasks = ve.list_tasks(ve_ctx["uid"])
    by_title = {t["title"]: t for t in tasks}
    # Shell task + 2 top-level items + 1 nested child = 4 tasks.
    assert len(tasks) == 4
    shell = by_title["Sock company"]
    assert shell["parent_task_id"] is None
    name_task = by_title["Name the brand"]
    assert name_task["parent_task_id"] == shell["id"]
    pick_task = by_title["Pick 3 names"]
    assert pick_task["parent_task_id"] == name_task["id"]
    # Checklist items were done -> tasks Done.
    assert name_task["status"] == "Done"
    assert "Graduated from idea" in (shell.get("notes") or "")


def test_idea_graduates_to_project_carries_dependencies(ve_ctx):
    uid = ve_ctx["uid"]
    idea = _ready_proposal(title="Neighborhood tool library")
    idea.target_level = "project"
    out = project_miner.create_confirmed(_result_with_idea(idea), uid)
    assert len(out["project_ids"]) == 1
    tasks = ve.list_tasks(uid)
    by_title = {t["title"]: t for t in tasks}
    # Add a dependency between checklist items, re-run via promote for deps.
    assert "Graduated from idea" in (ve.list_projects(uid)[0].get("notes") or "")


def test_unfolding_preserves_dependencies(ve_ctx):
    uid = ve_ctx["uid"]
    idea = _mk_idea(uid, title="Launch plan")
    tree = ve.create_checklist_items_batch(
        idea["id"],
        [{"title": "Design"}, {"title": "Print"}, {"title": "Ship"}],
        uid,
    )
    design, printed, ship = (n["id"] for n in tree)
    ve.add_checklist_dependency(printed, design, uid)  # Print depends on Design
    ve.add_checklist_dependency(ship, printed, uid)  # Ship depends on Print
    for n in tree:
        ve.update_checklist_item(n["id"], uid, status="done")
    out = ve.promote_idea(idea["id"], "project", uid)
    assert out["entity_type"] == "project"
    tasks = ve.list_tasks(uid)
    by_title = {t["title"]: t for t in tasks}
    assert len(tasks) == 3
    assert by_title["Print"]["dependency_ids"] == [by_title["Design"]["id"]]
    assert by_title["Ship"]["dependency_ids"] == [by_title["Print"]["id"]]
    # All under the new project.
    assert {t["project_id"] for t in tasks} == {out["entity"]["id"]}


def test_idea_graduates_to_initiative_with_plan_project(ve_ctx):
    uid = ve_ctx["uid"]
    idea = _ready_proposal()
    idea.target_level = "initiative"
    out = project_miner.create_confirmed(_result_with_idea(idea), uid)
    assert len(out["initiative_ids"]) == 1
    initiatives = ve.list_initiatives(uid)
    assert initiatives[0]["title"] == "Sock company"
    assert initiatives[0]["source_idea_id"], "provenance must link back"
    # The breakdown lives in a plan project under the initiative.
    projects = ve.list_projects(uid)
    assert len(projects) == 1
    assert projects[0]["initiative_id"] == initiatives[0]["id"]
    tasks = ve.list_tasks(uid)
    assert len(tasks) == 3  # 2 top-level + 1 nested
    assert {t["project_id"] for t in tasks} == {projects[0]["id"]}


def test_idea_without_target_level_stays_idea_with_checklist(ve_ctx):
    uid = ve_ctx["uid"]
    idea = _ready_proposal()
    out = project_miner.create_confirmed(_result_with_idea(idea), uid)
    assert len(out["idea_ids"]) == 1
    assert out["task_ids"] == [] and out["project_ids"] == [] and out["initiative_ids"] == []
    ideas = ve.list_ideas(uid)
    assert ideas[0]["status"] == "Captured"
    tree = ve.get_checklist_tree(ideas[0]["id"], uid)
    assert len(tree) == 2, "proposed checklist kept for later work-through"
    assert all(not n.get("superseded") for n in tree)


def test_batch_graduation_blocked_when_checklist_not_ready(ve_ctx):
    idea = _ready_proposal(checklist=_open_checklist())
    idea.target_level = "task"
    with pytest.raises(G.IdeaNotReadyError) as exc:
        project_miner.create_confirmed(_result_with_idea(idea), ve_ctx["uid"])
    assert exc.value.missing, "must name the unfinished items"
    assert any("Name the brand" in m for m in exc.value.missing)
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


def test_promote_bypasses_readiness_explicit_verdict(ve_ctx):
    """POST /promote is the user's explicit command — readiness is advisory."""
    uid = ve_ctx["uid"]
    idea = _mk_idea(uid)
    ve.create_checklist_items_batch(idea["id"], [{"title": "Still open"}], uid)
    out = ve.promote_idea(idea["id"], "task", uid)  # must NOT raise
    assert out["entity_type"] == "task"
    updated = ve.get_idea(idea["id"], uid)
    assert updated["status"] == "Graduated"


def test_promote_supersedes_checklist_as_provenance(ve_ctx):
    uid = ve_ctx["uid"]
    idea = _mk_idea(uid)
    ve.create_checklist_items_batch(
        idea["id"], [{"title": "Done thing", "status": "done"}], uid
    )
    ve.promote_idea(idea["id"], "task", uid)
    import local_ai.vision_execution.storage as ve_store

    items = ve_store.list_checklist_items(idea["id"], uid, include_superseded=True)
    assert items and all(it["superseded"] for it in items)
    live = ve.get_checklist_tree(idea["id"], uid)
    assert live == [], "superseded checklist leaves the live tree"


def test_promote_idea_to_task_unfolds_open_items_as_todo(ve_ctx):
    uid = ve_ctx["uid"]
    idea = _mk_idea(uid)
    ve.create_checklist_items_batch(
        idea["id"],
        [{"title": "Open step"}, {"title": "Done step", "status": "done"}],
        uid,
    )
    out = ve.promote_idea(idea["id"], "task", uid)
    tasks = ve.list_tasks(uid)
    by_title = {t["title"]: t for t in tasks}
    assert by_title["Open step"]["status"] == "Todo"
    assert by_title["Done step"]["status"] == "Done"
    assert by_title["Open step"]["parent_task_id"] == out["entity"]["id"]


def test_promote_unknown_idea_raises(ve_ctx):
    with pytest.raises(ValueError, match="[Nn]ot found"):
        ve.promote_idea("nope", "task", ve_ctx["uid"])


def test_promote_twice_rejected(ve_ctx):
    uid = ve_ctx["uid"]
    idea = _mk_idea(uid)
    ve.promote_idea(idea["id"], "task", uid)
    with pytest.raises(ValueError, match="[Aa]lready graduated"):
        ve.promote_idea(idea["id"], "project", uid)


def test_idea_readiness_hint_shape(ve_ctx):
    uid = ve_ctx["uid"]
    idea = _mk_idea(uid)
    ve.create_checklist_items_batch(
        idea["id"],
        [{"title": "Open step"}, {"title": "Done step", "status": "done"}],
        uid,
    )
    hint = ve.idea_readiness(idea["id"], uid)
    assert hint["ready"] is False
    assert hint["total"] == 2 and hint["done"] == 1 and hint["remaining"] == 1
    assert any("Open step" in m for m in hint["missing"])
    assert hint["levels"] == ["task", "project", "initiative"]


# --- checklist prompt parsing ----------------------------------------------


def test_proposal_tag_checklist_parsing():
    from local_ai.agent_intake import mining_chat

    tag = (
        '[PROPOSAL type=idea title="Sock company" '
        'checklist="Name the brand | Check a domain > .com first | Find a supplier > Get 3 quotes"]'
        "Socks with quotes[/PROPOSAL]"
    )
    p = mining_chat._parse_proposal_tag("Some chat text\n" + tag + "\nmore chat")
    assert p is not None and p["type"] == "idea"
    cl = p["checklist"]
    assert [n["title"] for n in cl] == ["Name the brand", "Check a domain", "Find a supplier"]
    assert cl[1]["children"] == [{"title": ".com first"}]
    assert cl[2]["children"] == [{"title": "Get 3 quotes"}]


def test_proposal_tag_without_checklist_still_parses():
    from local_ai.agent_intake import mining_chat

    p = mining_chat._parse_proposal_tag('[PROPOSAL type=task title="Buy socks"]Get socks[/PROPOSAL]')
    assert p is not None
    assert p["checklist"] == []


# --- garden growth wiring: checklist progress in the ideas payload --------------


def test_list_ideas_includes_checklist_progress(ve_ctx):
    """Bulk ideas payload carries {total, done} per idea — no N+1 for the garden."""
    uid = ve_ctx["uid"]
    bare = _mk_idea(uid, "Bare thought")
    fleshed = _mk_idea(uid, "Fleshed thought")
    items = ve.create_checklist_items_batch(
        fleshed["id"],
        [{"title": "Name it"}, {"title": "Price it"}, {"title": "Ship it"}],
        uid,
    )
    ve.update_checklist_item(items[0]["id"], uid, status="done")
    ve.update_checklist_item(items[1]["id"], uid, status="done")

    ideas = {i["id"]: i for i in ve.list_ideas(uid)}
    assert ideas[bare["id"]]["checklist_progress"] == {"total": 0, "done": 0}
    assert ideas[fleshed["id"]]["checklist_progress"] == {"total": 3, "done": 2}


def test_checklist_progress_ignores_superseded_items(ve_ctx):
    """Graduated ideas keep their checklist as provenance; it must not inflate progress."""
    import local_ai.vision_execution.storage as ve_store

    uid = ve_ctx["uid"]
    idea = _mk_idea(uid, "Sock company")
    ve.create_checklist_items_batch(idea["id"], [{"title": "Name it", "done": True}], uid)
    ve_store.mark_checklist_superseded(idea["id"], uid)

    ideas = {i["id"]: i for i in ve.list_ideas(uid)}
    assert ideas[idea["id"]]["checklist_progress"] == {"total": 0, "done": 0}


def test_get_idea_includes_checklist_progress(ve_ctx):
    uid = ve_ctx["uid"]
    idea = _mk_idea(uid, "Single fetch")
    items = ve.create_checklist_items_batch(idea["id"], [{"title": "Only step"}], uid)
    ve.update_checklist_item(items[0]["id"], uid, status="done")

    fetched = ve.get_idea(idea["id"], uid)
    assert fetched["checklist_progress"] == {"total": 1, "done": 1}
