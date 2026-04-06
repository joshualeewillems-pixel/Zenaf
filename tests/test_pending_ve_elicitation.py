"""Elicitation bridge: capture value → yes → Lane A person_assign / text_set."""
from __future__ import annotations

from pathlib import Path

import pytest

from local_ai.vision_execution import models as M
from local_ai.vision_execution import storage as ve_storage
from local_ai.vision_execution.direct_action_executor import evaluate_direct_ve_action
from local_ai.vision_execution.storage import init_db, open_sqlite_with_ve_pragmas


@pytest.fixture
def ve_conn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "pend_ve.db"
    conn = open_sqlite_with_ve_pragmas(db_path)
    init_db(conn)
    monkeypatch.setattr(ve_storage, "get_connection", lambda: conn)
    yield conn
    conn.close()


def _pending_initiative_owner(iid: str, *, phase: str, name: str | None = None) -> dict:
    p: dict = {
        "version": 1,
        "phase": phase,
        "elicitation_kind": "person_assign",
        "entity_type": "initiative",
        "entity_id": iid,
        "field_key": "owner_id",
    }
    if name:
        p["proposed_person_name"] = name
    return p


def test_pending_value_then_confirm_assigns_owner(ve_conn) -> None:
    uid = "u-pend-1"
    ini = ve_storage.create_initiative(M.InitiativeCreate(title="P", brief="b"), uid)
    iid = str(ini["id"])
    ve_storage.create_person(M.PersonCreate(name="Phil Tester", role=""))
    ctx: dict = {
        "council_preflight": {"ve_focus": {"entity_type": "initiative", "entity_id": iid}},
        "pending_ve_elicitation": _pending_initiative_owner(iid, phase="awaiting_value"),
    }
    r1 = evaluate_direct_ve_action(question="Phil Tester", context=ctx, user_id=uid)
    assert r1["status"] == "handled"
    assert r1.get("pending_ve_elicitation", {}).get("phase") == "awaiting_confirm"
    assert r1.get("pending_ve_elicitation", {}).get("proposed_person_name") == "Phil Tester"

    ctx["pending_ve_elicitation"] = r1["pending_ve_elicitation"]
    r2 = evaluate_direct_ve_action(question="yes", context=ctx, user_id=uid)
    assert r2["status"] == "handled"
    assert r2.get("pending_ve_elicitation") is None
    row = ve_storage.get_initiative(iid, uid)
    people = ve_storage.list_persons()
    phil = next(p for p in people if p.get("name") == "Phil Tester")
    assert row and row.get("owner_id") == phil["id"]


def _pending_initiative_brief(iid: str, *, phase: str, value: str | None = None) -> dict:
    p: dict = {
        "version": 1,
        "phase": phase,
        "elicitation_kind": "text_set",
        "entity_type": "initiative",
        "entity_id": iid,
        "field_key": "brief",
        "surface_key": "brief",
    }
    if value is not None:
        p["proposed_value"] = value
    return p


def _pending_initiative_dependencies(iid: str, *, phase: str, items: list[str] | None = None) -> dict:
    p: dict = {
        "version": 1,
        "phase": phase,
        "elicitation_kind": "collection_add",
        "entity_type": "initiative",
        "entity_id": iid,
        "field_key": "dependencies",
        "surface_key": "dependencies",
    }
    if items is not None:
        p["proposed_items"] = items
    return p


def test_pending_collection_add_then_confirm_appends_dependencies(ve_conn) -> None:
    uid = "u-pend-coll"
    ini = ve_storage.create_initiative(M.InitiativeCreate(title="Living", brief="b"), uid)
    iid = str(ini["id"])
    ve_storage.update_initiative(iid, M.InitiativeUpdate(dependencies="Existing dep."), uid)
    ctx: dict = {
        "council_preflight": {"ve_focus": {"entity_type": "initiative", "entity_id": iid}},
        "pending_ve_elicitation": _pending_initiative_dependencies(iid, phase="awaiting_value"),
    }
    paste = "Partnerships with schools\nResources for materials\nFeedback mechanisms"
    r1 = evaluate_direct_ve_action(question=paste, context=ctx, user_id=uid)
    assert r1["status"] == "handled"
    assert r1.get("pending_ve_elicitation", {}).get("phase") == "awaiting_confirm"
    assert len(r1.get("pending_ve_elicitation", {}).get("proposed_items") or []) == 3

    ctx["pending_ve_elicitation"] = r1["pending_ve_elicitation"]
    r2 = evaluate_direct_ve_action(question="those are good! add those!", context=ctx, user_id=uid)
    assert r2["status"] == "handled"
    assert r2.get("pending_ve_elicitation") is None
    row = ve_storage.get_initiative(iid, uid)
    deps = (row or {}).get("dependencies") or ""
    assert "Existing dep." in deps
    assert "Partnerships with schools" in deps
    assert "Feedback mechanisms" in deps


def test_pending_text_value_then_confirm_sets_brief(ve_conn) -> None:
    uid = "u-pend-brief"
    ini = ve_storage.create_initiative(M.InitiativeCreate(title="T", brief=""), uid)
    iid = str(ini["id"])
    ctx: dict = {
        "council_preflight": {"ve_focus": {"entity_type": "initiative", "entity_id": iid}},
        "pending_ve_elicitation": _pending_initiative_brief(iid, phase="awaiting_value"),
    }
    body = "Ship the dashboard by Q2 with weekly reviews."
    r1 = evaluate_direct_ve_action(question=body, context=ctx, user_id=uid)
    assert r1["status"] == "handled"
    assert r1.get("pending_ve_elicitation", {}).get("phase") == "awaiting_confirm"
    assert r1.get("pending_ve_elicitation", {}).get("proposed_value") == body

    ctx["pending_ve_elicitation"] = r1["pending_ve_elicitation"]
    r2 = evaluate_direct_ve_action(question="yes", context=ctx, user_id=uid)
    assert r2["status"] == "handled"
    assert r2.get("pending_ve_elicitation") is None
    row = ve_storage.get_initiative(iid, uid)
    assert row and row.get("brief") == body


def test_pending_confirm_without_value_still_needs_name(ve_conn) -> None:
    uid = "u-pend-2"
    ini = ve_storage.create_initiative(M.InitiativeCreate(title="Q", brief="b"), uid)
    iid = str(ini["id"])
    ctx: dict = {
        "council_preflight": {"ve_focus": {"entity_type": "initiative", "entity_id": iid}},
        "pending_ve_elicitation": _pending_initiative_owner(iid, phase="awaiting_value"),
    }
    r = evaluate_direct_ve_action(question="yes", context=ctx, user_id=uid)
    assert r["status"] == "handled"
    assert "name" in r["message"].lower()
