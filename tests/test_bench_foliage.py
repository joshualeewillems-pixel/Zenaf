"""Bench foliage from steward readings (rapid fire item 5, 2026-11-25).

The Bench's §7 foliage gains its second source: the seats whose
steward readings touch a task. The linkage is context preparation's
(PR #425) — a thread touches a record when its evidence names it,
through the derivation index (entity_ref) or a ve_entity evidence
row. Attribution is the reading record's own ``author`` field:
a seat archetype foliates; ``"steward"`` does NOT map to Maeve
(the record does not support it — the Steward is not a seat);
the skeptic never foliates her own tree (§7).

The gate mirrors context preparation's steward source exactly:
ZENAF_STEWARD_PENCIL master switch, BOTH steward consent flags,
standing threads only — fail-closed to empty foliage, never an
error. The read writes nothing (in particular it records no
relevance assessments: prepare_context's write path is not used).

Conventions: ALICE = "u1" (owner), BOB = "u2" (other user).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from local_ai.conversation import bench_foliage as BF
from local_ai.narrative import NarrativeStore
from local_ai.narrative.refs import SourceRef
from local_ai.vision_execution import models as M
from local_ai.vision_execution import service as ve_service
from local_ai.vision_execution import storage as S

ALICE = "u1"
BOB = "u2"

FLAGS_ON = {"steward_derivation": True, "steward_coordination": True}
FLAGS_OFF = {"steward_derivation": False, "steward_coordination": False}


# ---------------------------------------------------------------------------
# fixtures + seed helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def ve_conn(monkeypatch: pytest.MonkeyPatch):
    # Same pattern as test_context_preparation: a shared in-memory
    # VE connection.
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    S.init_db(conn)
    monkeypatch.setattr(S, "get_connection", lambda: conn)
    yield conn
    conn.close()


@pytest.fixture()
def narrative_store(tmp_path: Path):
    return NarrativeStore(db_path=tmp_path / "narrative.db")


@pytest.fixture()
def pencil_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ZENAF_STEWARD_PENCIL", "1")


def _perm_conn(flags_by_user: dict) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE user_permissions_settings ("
        "user_id TEXT, permissions_json TEXT, updated_at TEXT)"
    )
    for user_id, flags in flags_by_user.items():
        conn.execute(
            "INSERT INTO user_permissions_settings VALUES (?, ?, ?)",
            (user_id, json.dumps(flags), "2026-11-24T00:00:00Z"),
        )
    conn.commit()
    return conn


def _make_task(user: str, title: str, **kw) -> dict:
    return ve_service.create_task(M.TaskCreate(title=title, **kw), user)


def _make_project(user: str, title: str, **kw) -> dict:
    return ve_service.create_project(M.ProjectCreate(title=title, **kw), user)


def _make_initiative(user: str, title: str, **kw) -> dict:
    return ve_service.create_initiative(M.InitiativeCreate(title=title, **kw), user)


def _thread_naming_task(
    narrative_store,
    user,
    task_id,
    *,
    author="guardian",
    status="active",
    via="entity_ref",
    accept=False,
):
    """A standing thread whose evidence names the task, carrying
    one reading by ``author`` (proposed, or accepted when asked)."""
    if via == "entity_ref":
        thread = narrative_store.create_thread(
            user, origin="user_declared", title="The timber thread",
            evidence_refs=(SourceRef(kind="event", ref_id="evt-1", evidence_kind="entity_ref"),),
        )
        narrative_store.annotate_evidence_entities(
            user, thread.id, {("event", "evt-1"): f"task:{task_id}"}
        )
    else:  # via == "ve_entity"
        thread = narrative_store.create_thread(
            user, origin="user_declared", title="The timber thread",
            evidence_refs=(SourceRef(kind="ve_entity", ref_id=task_id, evidence_kind="entity_ref"),),
        )
    if status != "nascent":
        narrative_store.set_thread_status(user, thread.id, status)
    reading = narrative_store.propose_reading(
        user, thread.id, author=author,
        reading={"tensions": ["a tension"], "open_questions": ["a question"]},
        evidence_refs=(SourceRef(kind="event", ref_id="evt-1", evidence_kind="entity_ref"),)
        if via == "entity_ref"
        else (SourceRef(kind="ve_entity", ref_id=task_id, evidence_kind="entity_ref"),),
    )
    if accept:
        narrative_store.accept_reading(user, reading.id)
    return narrative_store.get_thread(user, thread.id)


def _foliage(store, user, parent_type, parent_id, conn=None):
    return BF.foliage_for_parent(
        user, parent_type, parent_id,
        narrative_store=store,
        consent_connection=conn if conn is not None else _perm_conn({user: FLAGS_ON}),
    )


# ---------------------------------------------------------------------------
# the gates — fail-closed to empty, never an error
# ---------------------------------------------------------------------------


def test_gate_off_by_default(ve_conn, narrative_store):
    task = _make_task(ALICE, "Order timber", status="Todo")
    _thread_naming_task(narrative_store, ALICE, task["id"])
    # No ZENAF_STEWARD_PENCIL: even with consent open, nothing.
    assert _foliage(narrative_store, ALICE, "task", task["id"]) == {}


def test_consent_closed_serves_nothing(ve_conn, narrative_store, pencil_on):
    task = _make_task(ALICE, "Order timber", status="Todo")
    _thread_naming_task(narrative_store, ALICE, task["id"])
    result = BF.foliage_for_parent(
        ALICE, "task", task["id"],
        narrative_store=narrative_store,
        consent_connection=_perm_conn({ALICE: FLAGS_OFF}),
    )
    assert result == {}


def test_one_consent_flag_closed_serves_nothing(ve_conn, narrative_store, pencil_on):
    task = _make_task(ALICE, "Order timber", status="Todo")
    _thread_naming_task(narrative_store, ALICE, task["id"])
    half = {"steward_derivation": True, "steward_coordination": False}
    result = BF.foliage_for_parent(
        ALICE, "task", task["id"],
        narrative_store=narrative_store,
        consent_connection=_perm_conn({ALICE: half}),
    )
    assert result == {}


def test_nascent_thread_never_contributes(ve_conn, narrative_store, pencil_on):
    task = _make_task(ALICE, "Order timber", status="Todo")
    _thread_naming_task(narrative_store, ALICE, task["id"], status="nascent")
    assert _foliage(narrative_store, ALICE, "task", task["id"]) == {}


def test_broken_store_degrades_to_empty(ve_conn, pencil_on):
    task = _make_task(ALICE, "Order timber", status="Todo")

    class ExplodingStore:
        def threads_for(self, *a, **kw):
            raise RuntimeError("store is down")

    result = BF.foliage_for_parent(
        ALICE, "task", task["id"],
        narrative_store=ExplodingStore(),
        consent_connection=_perm_conn({ALICE: FLAGS_ON}),
    )
    assert result == {}


# ---------------------------------------------------------------------------
# the foliage itself — linkage, attribution, currency
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("via", ["entity_ref", "ve_entity"])
def test_seat_reading_foliates_the_task_it_names(
    ve_conn, narrative_store, pencil_on, via
):
    task = _make_task(ALICE, "Order timber", status="Todo")
    _thread_naming_task(narrative_store, ALICE, task["id"], author="guardian", via=via)
    assert _foliage(narrative_store, ALICE, "task", task["id"]) == {
        task["id"]: ["guardian"]
    }


def test_accepted_reading_foliates(ve_conn, narrative_store, pencil_on):
    task = _make_task(ALICE, "Order timber", status="Todo")
    _thread_naming_task(narrative_store, ALICE, task["id"], author="mentor", accept=True)
    assert _foliage(narrative_store, ALICE, "task", task["id"]) == {
        task["id"]: ["mentor"]
    }


def test_steward_authored_reading_does_not_foliate(
    ve_conn, narrative_store, pencil_on
):
    """The honest bound: derivation readings are authored by the
    Steward, who is not a seat and is not Maeve. No colour is
    borrowed for them."""
    task = _make_task(ALICE, "Order timber", status="Todo")
    _thread_naming_task(narrative_store, ALICE, task["id"], author="steward")
    assert _foliage(narrative_store, ALICE, "task", task["id"]) == {}


def test_skeptic_authored_reading_never_foliates(
    ve_conn, narrative_store, pencil_on
):
    """§7: Severine's own colour never foliates her tree — she is
    the examiner."""
    task = _make_task(ALICE, "Order timber", status="Todo")
    _thread_naming_task(narrative_store, ALICE, task["id"], author="skeptic")
    assert _foliage(narrative_store, ALICE, "task", task["id"]) == {}


def test_displaced_proposed_reading_authors_nothing(
    ve_conn, narrative_store, pencil_on
):
    """Currency: a proposed reading displaced through change
    lineage is history; only the current reading's seat foliates."""
    task = _make_task(ALICE, "Order timber", status="Todo")
    thread = _thread_naming_task(narrative_store, ALICE, task["id"], author="champion")
    first = narrative_store.readings_for(ALICE, thread.id, status="proposed")[0]
    second = narrative_store.propose_reading(
        ALICE, thread.id, author="mentor",
        reading={"tensions": ["a newer tension"]},
        evidence_refs=(SourceRef(kind="event", ref_id="evt-1", evidence_kind="entity_ref"),),
    )
    narrative_store.record_change(
        ALICE, thread.id, kind="extended",
        evidence_refs=(SourceRef(kind="event", ref_id="evt-2", evidence_kind="entity_ref"),),
        prior_reading_id=first.id, new_reading_id=second.id,
    )
    assert _foliage(narrative_store, ALICE, "task", task["id"]) == {
        task["id"]: ["mentor"]
    }


def test_multiple_seats_merge_sorted(ve_conn, narrative_store, pencil_on):
    task = _make_task(ALICE, "Order timber", status="Todo")
    _thread_naming_task(narrative_store, ALICE, task["id"], author="maverick")
    _thread_naming_task(narrative_store, ALICE, task["id"], author="champion")
    assert _foliage(narrative_store, ALICE, "task", task["id"]) == {
        task["id"]: ["champion", "maverick"]
    }


def test_thread_naming_another_task_does_not_foliate(
    ve_conn, narrative_store, pencil_on
):
    project = _make_project(ALICE, "Season prep", status="Active")
    named = _make_task(
        ALICE, "Order timber", status="Todo", project_id=project["id"]
    )
    _make_task(ALICE, "Book the yard", status="Todo", project_id=project["id"])
    _thread_naming_task(narrative_store, ALICE, named["id"], author="guardian")
    result = _foliage(narrative_store, ALICE, "project", project["id"])
    assert result == {named["id"]: ["guardian"]}


# ---------------------------------------------------------------------------
# scope — parent kinds
# ---------------------------------------------------------------------------


def test_project_scope_covers_its_tasks(ve_conn, narrative_store, pencil_on):
    project = _make_project(ALICE, "Season prep", status="Active")
    task = _make_task(ALICE, "Order timber", status="Todo", project_id=project["id"])
    _thread_naming_task(narrative_store, ALICE, task["id"], author="guardian")
    assert _foliage(narrative_store, ALICE, "project", project["id"]) == {
        task["id"]: ["guardian"]
    }


def test_initiative_scope_covers_nested_tasks(ve_conn, narrative_store, pencil_on):
    initiative = _make_initiative(ALICE, "Winter season", status="Active")
    project = _make_project(
        ALICE, "Season prep", status="Active", initiative_id=initiative["id"]
    )
    task = _make_task(ALICE, "Order timber", status="Todo", project_id=project["id"])
    _thread_naming_task(narrative_store, ALICE, task["id"], author="conductor")
    assert _foliage(narrative_store, ALICE, "initiative", initiative["id"]) == {
        task["id"]: ["conductor"]
    }


def test_task_scope_includes_subtasks(ve_conn, narrative_store, pencil_on):
    parent = _make_task(ALICE, "Rebuild the fence", status="Todo")
    sub = _make_task(ALICE, "Buy posts", status="Todo", parent_task_id=parent["id"])
    _thread_naming_task(narrative_store, ALICE, sub["id"], author="ambassador")
    assert _foliage(narrative_store, ALICE, "task", parent["id"]) == {
        sub["id"]: ["ambassador"]
    }


def test_unknown_parent_type_is_empty(ve_conn, narrative_store, pencil_on):
    task = _make_task(ALICE, "Order timber", status="Todo")
    _thread_naming_task(narrative_store, ALICE, task["id"])
    assert _foliage(narrative_store, ALICE, "idea", task["id"]) == {}
    assert _foliage(narrative_store, ALICE, "nonsense", task["id"]) == {}


# ---------------------------------------------------------------------------
# owner isolation
# ---------------------------------------------------------------------------


def test_foreign_parent_resolves_to_nothing(ve_conn, narrative_store, pencil_on):
    task = _make_task(ALICE, "Order timber", status="Todo")
    _thread_naming_task(narrative_store, ALICE, task["id"], author="guardian")
    # BOB asks for ALICE's task: the parent does not resolve as his.
    assert _foliage(narrative_store, BOB, "task", task["id"]) == {}


def test_foreign_thread_never_leaks(ve_conn, narrative_store, pencil_on):
    task = _make_task(ALICE, "Order timber", status="Todo")
    # BOB's own thread names ALICE's task id — BOB's material is
    # his; ALICE's read is scoped to ALICE's threads and stays bare.
    _thread_naming_task(narrative_store, BOB, task["id"], author="guardian")
    assert _foliage(narrative_store, ALICE, "task", task["id"]) == {}


# ---------------------------------------------------------------------------
# read-only — the read writes nothing
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# the route — thin, authenticated, fail-closed
# ---------------------------------------------------------------------------


def _route_client(user_id: str):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.routes import vision_execution as ve_routes
    from api.routes.auth_routes import get_current_user

    app = FastAPI()
    app.include_router(ve_routes.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": user_id}
    return TestClient(app)


def test_route_serves_empty_foliage_when_gate_closed(ve_conn):
    task = _make_task(ALICE, "Order timber", status="Todo")
    client = _route_client(ALICE)
    res = client.get(
        f"/vision-execution/bench-foliage/by-parent/task/{task['id']}"
    )
    assert res.status_code == 200
    assert res.json() == {"foliage": {}}


def test_route_unknown_parent_type_reads_as_empty(ve_conn):
    client = _route_client(ALICE)
    res = client.get("/vision-execution/bench-foliage/by-parent/nonsense/abc")
    assert res.status_code == 200
    assert res.json() == {"foliage": {}}


def test_route_requires_authentication(ve_conn):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.routes import vision_execution as ve_routes

    app = FastAPI()
    app.include_router(ve_routes.router)
    client = TestClient(app, raise_server_exceptions=False)
    res = client.get("/vision-execution/bench-foliage/by-parent/task/abc")
    assert res.status_code == 401


def test_read_writes_nothing(ve_conn, narrative_store, pencil_on):
    task = _make_task(ALICE, "Order timber", status="Todo")
    _thread_naming_task(narrative_store, ALICE, task["id"], author="guardian")
    conn = narrative_store._conn

    def counts() -> dict[str, int]:
        out = {}
        for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall():
            out[name] = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        return out

    before = counts()
    result = _foliage(narrative_store, ALICE, "task", task["id"])
    assert result == {task["id"]: ["guardian"]}
    after = counts()
    assert before == after
    # Specifically: no relevance assessments were recorded — the
    # prepare_context write path is not part of this read.
    assert after.get("relevance_assessments", 0) == before.get(
        "relevance_assessments", 0
    )
