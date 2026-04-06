"""Direct Vision Execution Lane A: evaluate_direct_ve_action and _run_council early exit."""
from __future__ import annotations

from pathlib import Path

import pytest

from local_ai.llm.execution_principal import authenticated_account_principal
from local_ai.vision_execution import models as M
from local_ai.vision_execution import storage as ve_storage
from local_ai.vision_execution.direct_action_executor import evaluate_direct_ve_action
from local_ai.vision_execution.storage import init_db, open_sqlite_with_ve_pragmas


@pytest.fixture
def ve_conn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "direct_ve.db"
    conn = open_sqlite_with_ve_pragmas(db_path)
    init_db(conn)
    monkeypatch.setattr(ve_storage, "get_connection", lambda: conn)
    yield conn
    conn.close()


def _ctx_initiative(init_id: str) -> dict:
    return {
        "council_preflight": {
            "ve_focus": {"entity_type": "initiative", "entity_id": init_id},
        }
    }


def _ctx_project(proj_id: str) -> dict:
    return {
        "council_preflight": {
            "ve_focus": {"entity_type": "project", "entity_id": proj_id},
        }
    }


def test_change_brief_commits(ve_conn) -> None:
    uid = "u-direct-1"
    ini = ve_storage.create_initiative(M.InitiativeCreate(title="Init A", brief="old"), uid)
    iid = str(ini["id"])
    ctx = _ctx_initiative(iid)
    r = evaluate_direct_ve_action(
        question='Change the brief to: "New brief body for tests."',
        context=ctx,
        user_id=uid,
    )
    assert r["status"] == "handled"
    assert "brief" in r["message"].lower()
    row = ve_storage.get_initiative(iid, uid)
    assert "New brief body for tests." in (row or {}).get("brief", "")


def test_change_brief_uses_last_imperative_after_filler(ve_conn) -> None:
    uid = "u-filler"
    ini = ve_storage.create_initiative(M.InitiativeCreate(title="J", brief="todos"), uid)
    iid = str(ini["id"])
    q = (
        'ok, well, if it moves things along, change the brief to '
        '"serves as a collection of miscellaneous tasks."'
    )
    r = evaluate_direct_ve_action(question=q, context=_ctx_initiative(iid), user_id=uid)
    assert r["status"] == "handled"
    row = ve_storage.get_initiative(iid, uid)
    assert "miscellaneous tasks" in (row or {}).get("brief", "")


def test_change_brief_strips_leading_colon(ve_conn) -> None:
    uid = "u-colon"
    ini = ve_storage.create_initiative(M.InitiativeCreate(title="J", brief="old"), uid)
    iid = str(ini["id"])
    r = evaluate_direct_ve_action(
        question='change the brief to ": leading colon artifact"',
        context=_ctx_initiative(iid),
        user_id=uid,
    )
    assert r["status"] == "handled"
    assert (ve_storage.get_initiative(iid, uid) or {}).get("brief") == "leading colon artifact"


def test_change_brief_to_this_extracts_inner_quotes(ve_conn) -> None:
    uid = "u-this"
    ini = ve_storage.create_initiative(M.InitiativeCreate(title="J", brief="old"), uid)
    iid = str(ini["id"])
    q = 'change the brief to this " alpha beta gamma "'
    r = evaluate_direct_ve_action(question=q, context=_ctx_initiative(iid), user_id=uid)
    assert r["status"] == "handled"
    row = ve_storage.get_initiative(iid, uid)
    assert (row or {}).get("brief", "").strip() == "alpha beta gamma"


def test_add_project_under_initiative(ve_conn) -> None:
    uid = "u-direct-2"
    ini = ve_storage.create_initiative(M.InitiativeCreate(title="Parent", brief="x"), uid)
    iid = str(ini["id"])
    r = evaluate_direct_ve_action(
        question="Add a project: Inventory all my offerings",
        context=_ctx_initiative(iid),
        user_id=uid,
    )
    assert r["status"] == "handled"
    assert r["created_entities"]
    pid = r["created_entities"][0]["entity_id"]
    proj = ve_storage.get_project(pid, uid)
    assert proj and proj.get("title") == "Inventory all my offerings"
    assert proj.get("initiative_id") == iid


def test_batch_tasks_scoped_project(ve_conn) -> None:
    uid = "u-direct-3"
    ini = ve_storage.create_initiative(M.InitiativeCreate(title="I", brief="b"), uid)
    iid = str(ini["id"])
    proj = ve_storage.create_project(
        M.ProjectCreate(initiative_id=iid, title="Task bucket"),
        uid,
    )
    pid = str(proj["id"])
    r = evaluate_direct_ve_action(
        question="Create tasks:\n- First item\n- Second item",
        context=_ctx_project(pid),
        user_id=uid,
    )
    assert r["status"] == "handled"
    assert len(r["created_entities"]) == 2
    tasks = ve_storage.list_tasks(user_id=uid, project_id=pid)
    titles = sorted(t.get("title") for t in tasks)
    assert titles == ["First item", "Second item"]


def test_batch_tasks_last_created_project_session(ve_conn) -> None:
    uid = "u-direct-4"
    ini = ve_storage.create_initiative(M.InitiativeCreate(title="I2", brief="b"), uid)
    iid = str(ini["id"])
    proj = ve_storage.create_project(
        M.ProjectCreate(initiative_id=iid, title="Session proj"),
        uid,
    )
    pid = str(proj["id"])
    ctx = {
        "council_preflight": {"ve_focus": {"entity_type": "initiative", "entity_id": iid}},
        "ve_direct_session": {"last_created_project_id": pid},
    }
    r = evaluate_direct_ve_action(
        question="Under that create tasks: Alpha, Beta",
        context=ctx,
        user_id=uid,
    )
    assert r["status"] == "handled"
    tasks = ve_storage.list_tasks(user_id=uid, project_id=pid)
    assert len(tasks) == 2


def test_assign_owner_requires_exact_person_name(ve_conn) -> None:
    uid = "u-owner"
    ini = ve_storage.create_initiative(M.InitiativeCreate(title="Own", brief="b"), uid)
    iid = str(ini["id"])
    ve_storage.create_person(M.PersonCreate(name="Alice Example", role=""))
    r = evaluate_direct_ve_action(
        question="Set owner to Bob Nobody",
        context=_ctx_initiative(iid),
        user_id=uid,
    )
    assert r["status"] == "declined"


def test_assign_owner_exact_name(ve_conn) -> None:
    uid = "u-owner2"
    ini = ve_storage.create_initiative(M.InitiativeCreate(title="Own2", brief="b"), uid)
    iid = str(ini["id"])
    ve_storage.create_person(M.PersonCreate(name="Alice Example", role=""))
    r = evaluate_direct_ve_action(
        question="Set owner to Alice Example",
        context=_ctx_initiative(iid),
        user_id=uid,
    )
    assert r["status"] == "handled"
    assert "Owner" in r["message"] and "Alice" in r["message"]
    row = ve_storage.get_initiative(iid, uid)
    people = ve_storage.list_persons()
    alice = next(p for p in people if p.get("name") == "Alice Example")
    assert row and row.get("owner_id") == alice["id"]


def test_set_initiative_status_lane_a(ve_conn) -> None:
    uid = "u-st"
    ini = ve_storage.create_initiative(M.InitiativeCreate(title="S", brief="b"), uid)
    iid = str(ini["id"])
    r = evaluate_direct_ve_action(
        question="Set status to Active",
        context=_ctx_initiative(iid),
        user_id=uid,
    )
    assert r["status"] == "handled"
    assert (ve_storage.get_initiative(iid, uid) or {}).get("status") == "Active"


def test_add_risk_append(ve_conn) -> None:
    uid = "u-risk"
    ini = ve_storage.create_initiative(M.InitiativeCreate(title="R", brief="b"), uid)
    iid = str(ini["id"])
    r = evaluate_direct_ve_action(
        question="Add risk: Budget overrun in Q2",
        context=_ctx_initiative(iid),
        user_id=uid,
    )
    assert r["status"] == "handled"
    risks = str((ve_storage.get_initiative(iid, uid) or {}).get("risks") or "")
    assert "Budget overrun" in risks


def test_set_kill_criteria_lane_a(ve_conn) -> None:
    uid = "u-kill"
    ini = ve_storage.create_initiative(M.InitiativeCreate(title="K", brief="b"), uid)
    iid = str(ini["id"])
    r = evaluate_direct_ve_action(
        question="Set kill criteria to Pause if no sponsor by June 1",
        context=_ctx_initiative(iid),
        user_id=uid,
    )
    assert r["status"] == "handled"
    row = ve_storage.get_initiative(iid, uid) or {}
    assert "June 1" in str(row.get("kill_criteria") or "")


def test_append_to_admin_notes_lane_a(ve_conn) -> None:
    uid = "u-nappend"
    ini = ve_storage.create_initiative(M.InitiativeCreate(title="N", brief="b"), uid)
    iid = str(ini["id"])
    ve_storage.update_initiative(iid, M.InitiativeUpdate(notes="First line."), uid)
    r = evaluate_direct_ve_action(
        question="Append to admin notes: Check compliance folder.",
        context=_ctx_initiative(iid),
        user_id=uid,
    )
    assert r["status"] == "handled"
    notes = str((ve_storage.get_initiative(iid, uid) or {}).get("notes") or "")
    assert "First line." in notes and "compliance" in notes.lower()


def test_add_execution_step(ve_conn) -> None:
    uid = "u-step"
    ini = ve_storage.create_initiative(M.InitiativeCreate(title="E", brief="b"), uid)
    iid = str(ini["id"])
    r = evaluate_direct_ve_action(
        question="Add execution step: Ship the beta",
        context=_ctx_initiative(iid),
        user_id=uid,
    )
    assert r["status"] == "handled"
    steps = ve_storage.list_execution_steps("initiative", iid, uid)
    assert any("Ship the beta" in str(s.get("title") or "") for s in steps)


def test_lane_a_guard_sets_preflight_on_decline(ve_conn) -> None:
    uid = "u-guard"
    ini = ve_storage.create_initiative(M.InitiativeCreate(title="G", brief="b"), uid)
    iid = str(ini["id"])
    ctx = _ctx_initiative(iid)
    r = evaluate_direct_ve_action(
        question="Set owner to Missing Person XYZ",
        context=ctx,
        user_id=uid,
    )
    assert r["status"] == "declined"
    cp = ctx.get("council_preflight")
    assert isinstance(cp, dict)
    assert cp.get("lane_a_mutation_intent_parsed") is True
    assert cp.get("lane_a_direct_action_declined") is True


def test_ambiguous_no_scope_declines(ve_conn) -> None:
    uid = "u-direct-5"
    r = evaluate_direct_ve_action(
        question="Change the brief to something vague",
        context={},
        user_id=uid,
    )
    assert r["status"] == "declined"


def test_ve_selected_entity_wins_over_conversation_subject_and_ve_focus(ve_conn) -> None:
    """Open panel selection must not lose to stale field focus or Zenaf conversation_subject."""
    uid = "u-scope-sel"
    a = ve_storage.create_initiative(M.InitiativeCreate(title="A", brief="a"), uid)
    b = ve_storage.create_initiative(M.InitiativeCreate(title="B", brief="b"), uid)
    c = ve_storage.create_initiative(M.InitiativeCreate(title="C", brief="c"), uid)
    aid, bid, cid = str(a["id"]), str(b["id"]), str(c["id"])
    ctx = {
        "conversation_subject": {"entity_type": "initiative", "entity_id": aid},
        "council_preflight": {
            "ve_focus": {"entity_type": "initiative", "entity_id": bid},
            "ve_selected_entity": {"entity_type": "initiative", "entity_id": cid, "title": "C"},
        },
    }
    r = evaluate_direct_ve_action(
        question='Change the brief to: "target is C"',
        context=ctx,
        user_id=uid,
    )
    assert r["status"] == "handled"
    assert "target is C" in (ve_storage.get_initiative(cid, uid) or {}).get("brief", "")
    assert (ve_storage.get_initiative(aid, uid) or {}).get("brief") == "a"
    assert (ve_storage.get_initiative(bid, uid) or {}).get("brief") == "b"


def test_scoped_digression_ve_focus_wins_over_ve_selected_entity(ve_conn) -> None:
    uid = "u-scope-dig"
    a = ve_storage.create_initiative(M.InitiativeCreate(title="A", brief="a"), uid)
    b = ve_storage.create_initiative(M.InitiativeCreate(title="B", brief="b"), uid)
    aid, bid = str(a["id"]), str(b["id"])
    ctx = {
        "is_scoped_digression": True,
        "council_preflight": {
            "ve_focus": {"entity_type": "initiative", "entity_id": aid},
            "ve_selected_entity": {"entity_type": "initiative", "entity_id": bid, "title": "B"},
        },
    }
    r = evaluate_direct_ve_action(
        question='Change the brief to: "dig thread"',
        context=ctx,
        user_id=uid,
    )
    assert r["status"] == "handled"
    assert "dig thread" in (ve_storage.get_initiative(aid, uid) or {}).get("brief", "")
    assert (ve_storage.get_initiative(bid, uid) or {}).get("brief") == "b"


def test_ve_selection_blob_resolves_scope_without_ve_selected_entity(ve_conn) -> None:
    uid = "u-scope-vsel"
    ini = ve_storage.create_initiative(M.InitiativeCreate(title="S", brief="old"), uid)
    iid = str(ini["id"])
    ctx = {
        "council_preflight": {
            "ve_selection": {"tab": "execution", "initiativeId": iid},
        },
    }
    r = evaluate_direct_ve_action(
        question='Change the brief to: "from selection only"',
        context=ctx,
        user_id=uid,
    )
    assert r["status"] == "handled"
    assert "from selection only" in (ve_storage.get_initiative(iid, uid) or {}).get("brief", "")


def test_run_council_skips_llm_when_direct_handles(monkeypatch, ve_conn) -> None:
    from api.main import RunParams, _run_council

    uid = "u-direct-6"
    ini = ve_storage.create_initiative(M.InitiativeCreate(title="Z", brief="z"), uid)
    iid = str(ini["id"])

    def boom(*_a, **_kw):
        raise AssertionError("run_council LLM path should not run when Lane A handles")

    monkeypatch.setattr("local_ai.atria_tools.run_council", boom)
    monkeypatch.setattr(
        "local_ai.vision_execution.storage.get_studio_council_teacher_settings",
        lambda: {"teacher_mode": "off"},
    )

    params = RunParams(question="Add a project: LLM Skip Test")
    ctx = _ctx_initiative(iid)
    principal = authenticated_account_principal(uid)
    out = _run_council(params, ctx, None, execution_principal=principal)
    assert "Created → Project" in out
    assert getattr(_run_council, "_last_direct_ve_action", None)["status"] == "handled"
