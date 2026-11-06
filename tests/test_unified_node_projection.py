"""Unified-node read-only projection (Slice A, rev2 §5/§8).

Covers the Slice A authorization request exactly:
- projection fidelity: every live row projects to exactly one node with
  the mapped parent/kind/status (4 ideas, 5 initiatives, 27 projects,
  85 tasks at the rev1 inventory counts, plus checklist nodes);
- the motivating case: the 23 Direction tasks project as root nodes and
  the "Zenaf build directions" initiative projects as a root with zero
  children;
- parentage: the corrected §3.2 mapping (immediate task parent wins
  over the project; no live row carries both, verified 2026-11-05);
- read-only proof: the six tables are byte-identical before and after
  projection reads, and the projection module contains no write
  statement;
- fail-closed: unresolvable parents and unmapped statuses are reported,
  never guessed.

Runs against a real temp SQLite DB (same fixture pattern as
test_keystone_attention).
"""

from __future__ import annotations

import ast
import sqlite3
import threading
from dataclasses import FrozenInstanceError

import pytest

from local_ai.vision_execution import models as M
from local_ai.vision_execution import node_projection as NP
from local_ai.vision_execution import service as ve

TABLES = (
    "ideas",
    "initiatives",
    "projects",
    "tasks",
    "checklist_items",
    "execution_steps",
)


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    """Isolate the VE SQLite DB per test."""
    import local_ai.vision_execution.storage as ve_store

    ve_db = tmp_path / "ve.db"
    monkeypatch.setattr(ve_store, "_DB_PATH", ve_db)
    monkeypatch.setattr(ve_store, "_DB_DIR", tmp_path)
    monkeypatch.setattr(ve_store, "_init_done_paths", set())
    monkeypatch.setattr(ve_store, "_thread_local", threading.local())
    return {"db_path": ve_db}


def _make_user(email="ally@example.com"):
    return ve.create_user_account(email, "pw-hunter2", "Ally")


def _raw(db_path):
    return sqlite3.connect(str(db_path))


def _dump(db_path):
    """Full ordered dump of the six projection source tables."""
    conn = _raw(db_path)
    try:
        return {
            table: conn.execute(
                f"SELECT * FROM {table} ORDER BY id"
            ).fetchall()
            for table in TABLES
        }
    finally:
        conn.close()


def _by_id(nodes):
    return {n.id: n for n in nodes}


def _children(nodes, parent_id):
    return [n for n in nodes if n.parent_id == parent_id]


def _seed_inventory(user_id):
    """Seed the rev1 inventory shape: 4 ideas, 5 initiatives, 27 projects,
    85 tasks — mirroring the live staging shape of 2026-11-04/05."""
    idea_ids = {}
    for title, status in [
        ("Direction: permission implementation", "Captured"),
        ("Direction: flow state", "Advanced"),
        ("Direction: living council", "Parked"),
        ("An old archived thought", "Archived"),
    ]:
        idea = ve.create_idea(M.IdeaCreate(title=title, status=status), user_id)
        idea_ids[title] = idea["id"]

    build_dirs = ve.create_initiative(
        M.InitiativeCreate(title="Zenaf build directions", status="Draft"),
        user_id,
    )
    initiatives = {"Zenaf build directions": build_dirs}
    for title, status, source in [
        ("Meet your council", "Evaluating", "Direction: permission implementation"),
        ("Vision execution", "Approved", None),
        ("Characterization", "Active", None),
        ("Fellowship", "Paused", None),
    ]:
        init = ve.create_initiative(
            M.InitiativeCreate(
                title=title,
                status=status,
                source_idea_id=idea_ids[source] if source else None,
            ),
            user_id,
        )
        initiatives[title] = init

    project_statuses = ["Draft", "Ready", "Active", "Blocked", "Complete", "Parked"]
    projects = []
    owners = [t for t in initiatives if t != "Zenaf build directions"]
    for i in range(27):
        owner = owners[i % len(owners)]
        proj = ve.create_project(
            M.ProjectCreate(
                title=f"Project {i + 1}",
                initiative_id=initiatives[owner]["id"],
                status=project_statuses[i % len(project_statuses)],
            ),
            user_id,
        )
        projects.append(proj)

    task_statuses = ["Todo", "In Progress", "Blocked", "Done", "Dropped"]
    tasks = []
    # 23 Direction tasks: project-less roots (the motivating case).
    for i in range(23):
        tasks.append(
            ve.create_task(
                M.TaskCreate(
                    title=f"Direction: work item {i + 1}",
                    status=task_statuses[i % len(task_statuses)],
                ),
                user_id,
            )
        )
    # The single parented task (live shape: 76778801 "Confirm dentist
    # slot" has parent_task_id only).
    parented = ve.create_task(
        M.TaskCreate(
            title="Confirm dentist slot",
            parent_task_id=tasks[0]["id"],
            status="Todo",
        ),
        user_id,
    )
    tasks.append(parented)
    # A task with BOTH project_id and parent_task_id: the corrected
    # §3.2 rule keeps the immediate task parent (live: 0 such rows,
    # the rule is preventive). The parent task itself sits under the
    # project, so the project is reached through the ancestor chain.
    dual_parent = ve.create_task(
        M.TaskCreate(
            title="Dual-parent anchor",
            project_id=projects[0]["id"],
            status="Todo",
        ),
        user_id,
    )
    tasks.append(dual_parent)
    dual = ve.create_task(
        M.TaskCreate(
            title="Dual-parented task",
            project_id=projects[0]["id"],
            parent_task_id=dual_parent["id"],
            status="In Progress",
        ),
        user_id,
    )
    tasks.append(dual)
    # One dated task, one tentative task, one dependency-carrying task.
    dated = ve.create_task(
        M.TaskCreate(
            title="Dated task",
            project_id=projects[1]["id"],
            status="Todo",
            due_date="2026-12-01",
        ),
        user_id,
    )
    tasks.append(dated)
    tentative = ve.create_task(
        M.TaskCreate(
            title="Tentative task",
            project_id=projects[1]["id"],
            status="Todo",
            timeframe_commitment="tentative",
        ),
        user_id,
    )
    tasks.append(tentative)
    dependent = ve.create_task(
        M.TaskCreate(
            title="Dependent task",
            project_id=projects[2]["id"],
            status="Todo",
            dependency_ids=[dated["id"]],
        ),
        user_id,
    )
    tasks.append(dependent)
    # The rest under projects, rotating statuses.
    remaining = 85 - len(tasks)
    for i in range(remaining):
        tasks.append(
            ve.create_task(
                M.TaskCreate(
                    title=f"Project task {i + 1}",
                    project_id=projects[i % len(projects)]["id"],
                    status=task_statuses[i % len(task_statuses)],
                ),
                user_id,
            )
        )
    assert len(tasks) == 85
    return {
        "idea_ids": idea_ids,
        "initiatives": initiatives,
        "projects": projects,
        "tasks": tasks,
        "parented": parented,
        "dual_parent": dual_parent,
        "dual": dual,
        "dated": dated,
        "tentative": tentative,
        "dependent": dependent,
    }


# ------------------------------------------------------------------ fidelity


def test_projection_fidelity_full_inventory(ve_ctx):
    user = _make_user()
    seed = _seed_inventory(user["id"])
    nodes = NP.project_nodes(user["id"])
    by_id = _by_id(nodes)

    # Every live row projects to exactly one node.
    assert len(nodes) == 4 + 5 + 27 + 85
    assert len(by_id) == len(nodes)
    kinds = [n.kind for n in nodes]
    assert kinds.count("idea") == 4
    assert kinds.count("initiative") == 5
    assert kinds.count("project") == 27
    assert kinds.count("task") == 85

    # Kind comes from the source table; every node carries provenance.
    for n in nodes:
        assert n.kind in NP.NODE_KINDS
        assert n.status in NP.NODE_STATUSES
        assert n.user_id == user["id"]
        assert n.source_table in TABLES[:4]

    # The motivating case: the 23 Direction tasks are roots.
    direction = [n for n in nodes if n.title.startswith("Direction: work item")]
    assert len(direction) == 23
    assert all(n.parent_id is None for n in direction)
    assert all(n.kind == "task" for n in direction)

    # "Zenaf build directions" is a root with zero children.
    build_dirs = by_id[seed["initiatives"]["Zenaf build directions"]["id"]]
    assert build_dirs.parent_id is None
    assert build_dirs.kind == "initiative"
    assert _children(nodes, build_dirs.id) == []

    # The single parented task sits under its parent task.
    parented = by_id[seed["parented"]["id"]]
    assert parented.parent_id == seed["tasks"][0]["id"]
    assert by_id[parented.parent_id].kind == "task"

    # The dual-parented task keeps its immediate task parent, not the
    # project; the project is reached through the ancestor chain.
    dual = by_id[seed["dual"]["id"]]
    assert dual.parent_id == seed["dual_parent"]["id"]
    assert by_id[dual.parent_id].parent_id == seed["projects"][0]["id"]

    # Typed attributes and carried fields (§3.2).
    dated = by_id[seed["dated"]["id"]]
    assert dated.due_date == "2026-12-01"
    tentative = by_id[seed["tentative"]["id"]]
    assert tentative.timeframe_commitment == "tentative"
    dependent = by_id[seed["dependent"]["id"]]
    assert dependent.dependency_ids == (seed["dated"]["id"],)

    # Origin edge: the initiative sourced from an idea carries the
    # origin, not a parent.
    council = by_id[seed["initiatives"]["Meet your council"]["id"]]
    assert council.parent_id is None
    assert council.origin_id == seed["idea_ids"]["Direction: permission implementation"]

    # Archived idea: Parked work state, archived visibility.
    archived = [n for n in nodes if n.title == "An old archived thought"][0]
    assert archived.status == "Parked"
    assert archived.visibility == "archived"


# ------------------------------------------------------------------ status map


@pytest.mark.parametrize(
    "table,old,new,visibility",
    [
        ("ideas", "Captured", "Open", "visible"),
        ("ideas", "Clarifying", "Open", "visible"),
        ("ideas", "Contextualized", "Open", "visible"),
        ("ideas", "Evaluated", "Open", "visible"),
        ("ideas", "Advanced", "Active", "visible"),
        ("ideas", "Parked", "Parked", "visible"),
        ("ideas", "Archived", "Parked", "archived"),
        ("ideas", "Graduated", "Done", "visible"),
        ("initiatives", "Draft", "Open", "visible"),
        ("initiatives", "Evaluating", "Open", "visible"),
        ("initiatives", "Approved", "Open", "visible"),
        ("initiatives", "Active", "Active", "visible"),
        ("initiatives", "Paused", "Parked", "visible"),
        ("initiatives", "Complete", "Done", "visible"),
        ("initiatives", "Killed", "Dropped", "visible"),
        ("projects", "Draft", "Open", "visible"),
        ("projects", "Ready", "Open", "visible"),
        ("projects", "Active", "Active", "visible"),
        ("projects", "Blocked", "Blocked", "visible"),
        ("projects", "Complete", "Done", "visible"),
        ("projects", "Parked", "Parked", "visible"),
        ("tasks", "Todo", "Open", "visible"),
        ("tasks", "In Progress", "Active", "visible"),
        ("tasks", "Blocked", "Blocked", "visible"),
        ("tasks", "Done", "Done", "visible"),
        ("tasks", "Dropped", "Dropped", "visible"),
    ],
)
def test_status_mapping_covers_every_legacy_status(table, old, new, visibility):
    assert NP.map_status(table, old) == (new, visibility)


def test_status_mapping_rejects_unknown_status():
    with pytest.raises(ValueError, match="unmapped"):
        NP.map_status("tasks", "Weird")
    with pytest.raises(ValueError, match="no status mapping"):
        NP.map_status("nope", "Open")


# ------------------------------------------------------------------ checklist + steps


def test_checklist_and_execution_step_nodes(ve_ctx):
    user = _make_user()
    idea = ve.create_idea(M.IdeaCreate(title="An idea with a checklist"), user["id"])
    ve.create_checklist_items_batch(
        idea["id"],
        [
            {
                "title": "Make it real",
                "status": "open",
                "children": [{"title": "Sketch it", "status": "done"}],
            },
            {"title": "Find a friend", "status": "open"},
        ],
        user["id"],
    )
    import local_ai.vision_execution.storage as ve_store

    items = ve_store.list_checklist_items(idea["id"], user["id"], include_superseded=True)
    by_title = {it["title"]: it for it in items}
    # Supersede one item and hang a dependency on another (raw writes:
    # there is no service call that supersedes an item).
    conn = _raw(ve_ctx["db_path"])
    conn.execute(
        "UPDATE checklist_items SET superseded = 1 WHERE id = ?",
        (by_title["Find a friend"]["id"],),
    )
    conn.commit()
    conn.close()
    ve.add_checklist_dependency(
        by_title["Sketch it"]["id"], by_title["Make it real"]["id"], user["id"]
    )

    init = ve.create_initiative(
        M.InitiativeCreate(title="An initiative with steps"), user["id"]
    )
    step1 = ve.create_execution_step_for_initiative(
        init["id"], M.ExecutionStepCreate(title="First step"), user["id"]
    )
    step2 = ve.create_execution_step_for_initiative(
        init["id"], M.ExecutionStepCreate(title="Second step"), user["id"]
    )
    ve.update_execution_step(
        step1["id"], M.ExecutionStepUpdate(is_done=True), user["id"]
    )
    proj = ve.create_project(
        M.ProjectCreate(title="A project with a step", initiative_id=init["id"]),
        user["id"],
    )
    ve.create_execution_step_for_project(
        proj["id"], M.ExecutionStepCreate(title="Project step"), user["id"]
    )

    nodes = NP.project_nodes(user["id"])
    by_id = _by_id(nodes)

    # Checklist items are task-kind child nodes of the idea / parent item.
    make_it_real = by_id[by_title["Make it real"]["id"]]
    assert make_it_real.kind == "task"
    assert make_it_real.source_table == "checklist_items"
    assert make_it_real.parent_id == idea["id"]
    assert make_it_real.status == "Open"
    assert make_it_real.position == 0
    sketch_it = by_id[by_title["Sketch it"]["id"]]
    assert sketch_it.parent_id == make_it_real.id
    assert sketch_it.status == "Done"
    assert sketch_it.dependency_ids == (make_it_real.id,)
    # Superseded items project as archived, never silently dropped.
    friend = by_id[by_title["Find a friend"]["id"]]
    assert friend.visibility == "archived"
    assert friend.status == "Open"

    # Execution steps are task-kind child nodes of their scope node.
    first = by_id[step1["id"]]
    assert first.kind == "task"
    assert first.source_table == "execution_steps"
    assert first.parent_id == init["id"]
    assert first.status == "Done"
    assert first.position == 0
    second = by_id[step2["id"]]
    assert second.status == "Open"
    assert second.parent_id == init["id"]
    assert second.position == 1


def test_task_provenance_fields_carried_unchanged(ve_ctx):
    # Rev2 §3.2: task origin_*, seat_ref, timeframe_commitment are
    # carried unchanged. (Service create has no origin fields — the
    # approve path writes them — so set them directly.)
    user = _make_user()
    task = ve.create_task(
        M.TaskCreate(title="A task with provenance", status="Todo"), user["id"]
    )
    conn = _raw(ve_ctx["db_path"])
    conn.execute(
        "UPDATE tasks SET seat_ref = ?, origin_seat = ?, "
        "origin_conversation_id = ?, origin_message_id = ?, "
        "origin_claim_id = ?, origin_decision_id = ?, "
        "responsible_seat = ? WHERE id = ?",
        (
            "champion",
            "champion",
            "conv-1",
            "msg-1",
            "claim-1",
            "decision-1",
            "guardian",
            task["id"],
        ),
    )
    conn.commit()
    conn.close()
    nodes = NP.project_nodes(user["id"])
    assert len(nodes) == 1
    node = nodes[0]
    assert node.seat_ref == "champion"
    assert node.origin_seat == "champion"
    assert node.origin_conversation_id == "conv-1"
    assert node.origin_message_id == "msg-1"
    assert node.origin_claim_id == "claim-1"
    assert node.origin_decision_id == "decision-1"
    assert node.responsible_seat == "guardian"
    # An empty seat_ref normalizes to None.
    plain = ve.create_task(M.TaskCreate(title="A plain task"), user["id"])
    nodes = NP.project_nodes(user["id"])
    assert _by_id(nodes)[plain["id"]].seat_ref is None


# ------------------------------------------------------------------ read-only proof


def test_projection_is_read_only(ve_ctx):
    user = _make_user()
    _seed_inventory(user["id"])
    before = _dump(ve_ctx["db_path"])
    first = NP.project_nodes(user["id"])
    second = NP.project_nodes(user["id"])
    after = _dump(ve_ctx["db_path"])
    assert before == after
    assert first == second

    # The projection module contains no write statement: scan its
    # string literals for SQL write verbs at statement start (word
    # boundary, so a data value like "Dropped" does not match "DROP").
    import re

    import local_ai.vision_execution.node_projection as mod

    source = open(mod.__file__, encoding="utf-8").read()
    tree = ast.parse(source)
    write_stmt = re.compile(
        r"^(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|PRAGMA)\b"
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert not write_stmt.match(node.value.strip().upper()), (
                "write statement in projection string literal: "
                f"{node.value[:60]!r}"
            )

    # Projected nodes are immutable.
    node = first[0]
    with pytest.raises(FrozenInstanceError):
        node.title = "changed"


# ------------------------------------------------------------------ fail-closed


def test_unresolvable_parent_is_reported_not_guessed(ve_ctx):
    user = _make_user()
    conn = _raw(ve_ctx["db_path"])
    conn.execute(
        "INSERT INTO tasks (id, user_id, title, status, parent_task_id, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("orphan-task", user["id"], "Orphan", "Todo", "missing-parent",
         "2026-11-05T00:00:00", "2026-11-05T00:00:00"),
    )
    conn.commit()
    conn.close()
    with pytest.raises(ValueError, match="does not resolve"):
        NP.project_nodes(user["id"])


def test_unresolvable_project_parent_is_reported(ve_ctx):
    user = _make_user()
    conn = _raw(ve_ctx["db_path"])
    conn.execute(
        "INSERT INTO projects (id, user_id, title, status, initiative_id, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("orphan-project", user["id"], "Orphan", "Draft", "missing-initiative",
         "2026-11-05T00:00:00", "2026-11-05T00:00:00"),
    )
    conn.commit()
    conn.close()
    with pytest.raises(ValueError, match="does not resolve"):
        NP.project_nodes(user["id"])


def test_wrong_kind_parent_is_reported(ve_ctx):
    user = _make_user()
    init = ve.create_initiative(M.InitiativeCreate(title="An initiative"), user["id"])
    conn = _raw(ve_ctx["db_path"])
    conn.execute(
        "INSERT INTO tasks (id, user_id, title, status, parent_task_id, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("bad-parent-task", user["id"], "Bad parent", "Todo", init["id"],
         "2026-11-05T00:00:00", "2026-11-05T00:00:00"),
    )
    conn.commit()
    conn.close()
    with pytest.raises(ValueError, match="expected"):
        NP.project_nodes(user["id"])


# ------------------------------------------------------------------ scoping


def test_empty_user_projects_to_nothing(ve_ctx):
    user = _make_user()
    assert NP.project_nodes(user["id"]) == []


def test_other_users_rows_are_not_projected(ve_ctx):
    user = _make_user()
    other = ve.create_user_account("other@example.com", "pw-hunter2", "Other")
    ve.create_idea(M.IdeaCreate(title="Other user's idea"), other["id"])
    ve.create_task(M.TaskCreate(title="Other user's task"), other["id"])
    ve.create_idea(M.IdeaCreate(title="My idea"), user["id"])
    nodes = NP.project_nodes(user["id"])
    assert len(nodes) == 1
    assert nodes[0].title == "My idea"
    assert all(n.user_id == user["id"] for n in nodes)
