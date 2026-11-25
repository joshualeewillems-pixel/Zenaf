"""Verdict Slice 1 — the Palace door into the steward review
mechanism (founder ruling 2026-11-25 10:07 PT).

Two backend pieces:

* The reconsideration-request endpoint,
  ``POST /steward/review/reading/{id}/reconsider`` — the first
  production writer of candidacies through
  ``store.propose_reading_reconsideration``. The visitor's cause
  is preserved verbatim; the candidacy is born ``proposed`` and
  is itself verdicted through the existing routes; an empty
  cause is refused without writing; foreign and unknown readings
  are indistinguishable (404).

* The attributed read's ``pending`` section — the review layer's
  pending set filtered to the items whose thread names the
  subject, under the same mirrored steward gates as the read's
  other steward material. Seat-authored readings never appear
  (they are not steward proposals); another user's items never
  appear; a correspondence is attributed when ANY thread it
  cites names the subject.

Conventions mirror tests/test_attributed_read.py:
ALICE = "u1", BOB = "u2".
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from local_ai.conversation import attributed_read as AR
from local_ai.conversation.store import ConversationStore
from local_ai.followthrough.store import FollowthroughStore
from local_ai.narrative import correspondence as corr_mod
from local_ai.narrative.store import NarrativeStore
from local_ai.narrative.refs import SourceRef
from local_ai.vision_execution import models as M
from local_ai.vision_execution import service as ve_service
from local_ai.vision_execution import storage as S

ALICE = "u1"
BOB = "u2"

FLAGS_ON = {"steward_derivation": True, "steward_coordination": True}

CAUSE = "The yard changed its terms —  see Tuesday's note, not the old one."


# ---------------------------------------------------------------------------
# fixtures + seed helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def ve_conn(monkeypatch: pytest.MonkeyPatch):
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
def conv_store(tmp_path: Path):
    store = ConversationStore(db_path=tmp_path / "conv.db")
    yield store
    store.close()


@pytest.fixture()
def ft_store(tmp_path: Path):
    return FollowthroughStore(db_path=tmp_path / "ft.db")


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


def _read(store, conv, ft, user, entity_type, entity_id, conn=None):
    return AR.attributed_read_for_subject(
        user,
        entity_type,
        entity_id,
        narrative_store=store,
        conversation_store=conv,
        followthrough_store=ft,
        consent_connection=conn if conn is not None else _perm_conn({user: FLAGS_ON}),
    )


def _thread_naming_task(
    narrative_store,
    user,
    task_id,
    *,
    author="steward",
    origin="user_declared",
    status="active",
    accept=False,
):
    """A thread whose evidence names the task, carrying one reading."""
    thread = narrative_store.create_thread(
        user, origin=origin, title="The boundary thread",
        evidence_refs=(SourceRef(kind="event", ref_id="evt-1", evidence_kind="entity_ref"),),
    )
    narrative_store.annotate_evidence_entities(
        user, thread.id, {("event", "evt-1"): f"task:{task_id}"}
    )
    if status != "nascent":
        narrative_store.set_thread_status(user, thread.id, status)
    reading = narrative_store.propose_reading(
        user, thread.id, author=author,
        reading={"tensions": ["Sundays keep colliding with deliveries"],
                 "open_questions": ["Where does the weekend actually sit?"]},
        evidence_refs=(SourceRef(kind="event", ref_id="evt-1", evidence_kind="entity_ref"),),
    )
    if accept:
        narrative_store.accept_reading(user, reading.id)
    return narrative_store.get_thread(user, thread.id), reading


def _route_client(tmp_path: Path, monkeypatch, user=ALICE):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import api.routes.steward_review_routes as review_routes
    from api.routes.auth_routes import get_current_user

    monkeypatch.setattr(
        review_routes,
        "get_narrative_store",
        lambda: NarrativeStore(db_path=tmp_path / "narrative.db"),
    )
    app = FastAPI()
    app.include_router(review_routes.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": user}
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# the reconsideration-request endpoint
# ---------------------------------------------------------------------------


def test_reconsider_opens_candidacy_with_verbatim_cause(
    narrative_store, tmp_path, monkeypatch
):
    _thread, reading = _thread_naming_task(
        narrative_store, ALICE, "task-x", accept=True
    )
    client = _route_client(tmp_path, monkeypatch)
    resp = client.post(
        f"/steward/review/reading/{reading.id}/reconsider",
        json={"reason": CAUSE},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["item_kind"] == "reconsideration"
    candidacy = body["reconsideration"]
    # The cause rides verbatim — double space and all.
    assert candidacy["reason"] == CAUSE
    assert candidacy["status"] == "proposed"
    assert candidacy["reading_id"] == reading.id

    rows = narrative_store.reconsiderations_for(ALICE)
    assert len(rows) == 1
    assert rows[0].reason == CAUSE
    assert rows[0].status == "proposed"
    # The reading itself is untouched: still accepted.
    readings = narrative_store.readings_for(ALICE, _thread.id)
    assert readings[0].status == "accepted"

    # The candidacy is a review item, verdicted through the
    # existing routes: affirm it and it leaves the pending set.
    listed = client.get("/steward/review").json()["items"]
    items = [i for i in listed if i["item_kind"] == "reconsideration"]
    assert len(items) == 1
    assert items[0]["payload"]["reason"] == CAUSE
    assert items[0]["payload"]["reading_id"] == reading.id
    decided = client.post(
        f"/steward/review/reconsideration/{candidacy['id']}/accept"
    )
    assert decided.status_code == 200
    assert decided.json()["status"] == "affirmed"
    assert narrative_store.reconsiderations_for(ALICE)[0].status == "affirmed"


def test_reconsider_foreign_and_unknown_reading_are_identical_404(
    narrative_store, tmp_path, monkeypatch
):
    _thread, bob_reading = _thread_naming_task(
        narrative_store, BOB, "task-x", accept=True
    )
    client = _route_client(tmp_path, monkeypatch)  # acts as ALICE
    foreign = client.post(
        f"/steward/review/reading/{bob_reading.id}/reconsider",
        json={"reason": CAUSE},
    )
    unknown = client.post(
        "/steward/review/reading/rdg-nope/reconsider",
        json={"reason": CAUSE},
    )
    assert foreign.status_code == 404
    assert unknown.status_code == 404
    assert foreign.json() == unknown.json()
    # Nothing was written for either user.
    assert narrative_store.reconsiderations_for(ALICE) == []
    assert narrative_store.reconsiderations_for(BOB) == []


def test_reconsider_empty_cause_rejected_without_writing(
    narrative_store, tmp_path, monkeypatch
):
    _thread, reading = _thread_naming_task(
        narrative_store, ALICE, "task-x", accept=True
    )
    client = _route_client(tmp_path, monkeypatch)
    for bad in ("", "   ", "\n\t "):
        resp = client.post(
            f"/steward/review/reading/{reading.id}/reconsider",
            json={"reason": bad},
        )
        assert resp.status_code == 400
    assert narrative_store.reconsiderations_for(ALICE) == []


def test_reconsider_non_accepted_reading_refused(
    narrative_store, tmp_path, monkeypatch
):
    _thread, reading = _thread_naming_task(
        narrative_store, ALICE, "task-x", accept=False
    )
    client = _route_client(tmp_path, monkeypatch)
    resp = client.post(
        f"/steward/review/reading/{reading.id}/reconsider",
        json={"reason": CAUSE},
    )
    assert resp.status_code == 400
    assert narrative_store.reconsiderations_for(ALICE) == []


def test_reconsider_repeat_request_returns_standing_candidacy(
    narrative_store, tmp_path, monkeypatch
):
    _thread, reading = _thread_naming_task(
        narrative_store, ALICE, "task-x", accept=True
    )
    client = _route_client(tmp_path, monkeypatch)
    first = client.post(
        f"/steward/review/reading/{reading.id}/reconsider",
        json={"reason": CAUSE},
    )
    second = client.post(
        f"/steward/review/reading/{reading.id}/reconsider",
        json={"reason": "a second phrasing of the same ask"},
    )
    assert first.status_code == second.status_code == 200
    assert (
        first.json()["reconsideration"]["id"]
        == second.json()["reconsideration"]["id"]
    )
    assert len(narrative_store.reconsiderations_for(ALICE)) == 1


# ---------------------------------------------------------------------------
# the attributed read's pending section
# ---------------------------------------------------------------------------


def test_pending_reading_item_for_subject(
    ve_conn, narrative_store, conv_store, ft_store, pencil_on
):
    task = _make_task(ALICE, "Order timber", status="Todo")
    other = _make_task(ALICE, "Unrelated errand", status="Todo")
    _thread, reading = _thread_naming_task(narrative_store, ALICE, task["id"])

    result = _read(narrative_store, conv_store, ft_store, ALICE, "task", task["id"])
    assert result["steward_gate_open"] is True
    pending = result["pending"]
    assert len(pending) == 1
    item = pending[0]
    assert item["item_kind"] == "reading"
    assert item["item_id"] == f"reading:{reading.id}"
    assert item["status"] == "proposed"
    # Evidence composition rides with the item (DE-1).
    assert item["payload"]["evidence_refs"]
    assert item["payload"]["currency"]["placement"] == "current"

    # A subject the thread does not name carries none of it.
    result_other = _read(
        narrative_store, conv_store, ft_store, ALICE, "task", other["id"]
    )
    assert result_other["pending"] == []


def test_pending_gate_closed_reads_empty(
    ve_conn, narrative_store, conv_store, ft_store
):
    # No ZENAF_STEWARD_PENCIL: the mirrored gate is closed and the
    # pending steward material does not reach the door.
    task = _make_task(ALICE, "Order timber", status="Todo")
    _thread_naming_task(narrative_store, ALICE, task["id"])
    result = _read(narrative_store, conv_store, ft_store, ALICE, "task", task["id"])
    assert result["steward_gate_open"] is False
    assert result["pending"] == []


def test_pending_excludes_seat_authored_and_foreign(
    ve_conn, narrative_store, conv_store, ft_store, pencil_on
):
    task = _make_task(ALICE, "Order timber", status="Todo")
    # A seat-authored proposed reading is NOT a steward proposal:
    # it is answered conversationally, never verdicted at a door.
    _thread_naming_task(narrative_store, ALICE, task["id"], author="skeptic")
    # BOB's steward proposal on BOB's own thread naming the task id
    # is BOB's material; it never enters ALICE's read.
    _thread_naming_task(narrative_store, BOB, task["id"], author="steward")
    result = _read(narrative_store, conv_store, ft_store, ALICE, "task", task["id"])
    assert result["pending"] == []
    # …and BOB's own read of a subject BOB owns does carry it —
    # isolation is by owner, not by suppression.
    bob_task = _make_task(BOB, "Order timber", status="Todo")
    _thread_naming_task(narrative_store, BOB, bob_task["id"], author="steward")
    result_bob = _read(
        narrative_store, conv_store, ft_store, BOB, "task", bob_task["id"]
    )
    assert len(result_bob["pending"]) == 1


def test_pending_birth_item_on_nascent_thread(
    ve_conn, narrative_store, conv_store, ft_store, pencil_on
):
    task = _make_task(ALICE, "Order timber", status="Todo")
    thread, _reading = _thread_naming_task(
        narrative_store, ALICE, task["id"],
        origin="steward_proposal", status="nascent",
    )
    result = _read(narrative_store, conv_store, ft_store, ALICE, "task", task["id"])
    kinds = {item["item_kind"] for item in result["pending"]}
    assert "birth" in kinds
    birth = next(i for i in result["pending"] if i["item_kind"] == "birth")
    assert birth["item_id"] == f"birth:{thread.id}"
    assert birth["status"] == "nascent"


def test_pending_reconsideration_item_for_subject(
    ve_conn, narrative_store, conv_store, ft_store, pencil_on
):
    task = _make_task(ALICE, "Order timber", status="Todo")
    _thread, reading = _thread_naming_task(
        narrative_store, ALICE, task["id"], accept=True
    )
    narrative_store.propose_reading_reconsideration(ALICE, reading.id, CAUSE)
    result = _read(narrative_store, conv_store, ft_store, ALICE, "task", task["id"])
    items = [i for i in result["pending"] if i["item_kind"] == "reconsideration"]
    assert len(items) == 1
    assert items[0]["payload"]["reading_id"] == reading.id
    assert items[0]["payload"]["reason"] == CAUSE


def test_pending_correspondence_via_any_cited_thread(
    ve_conn, narrative_store, conv_store, ft_store, pencil_on
):
    task = _make_task(ALICE, "Order timber", status="Todo")
    claim_a = SourceRef(kind="claim", ref_id="claim-a", evidence_kind="quote")
    claim_b = SourceRef(kind="claim", ref_id="claim-b", evidence_kind="quote")

    def _standing(title, ref, author, text, *, name_task=False):
        thread = narrative_store.create_thread(
            ALICE, origin="user_declared", title=title, evidence_refs=(ref,)
        )
        if name_task:
            narrative_store.annotate_evidence_entities(
                ALICE, thread.id, {(ref.kind, ref.ref_id): f"task:{task['id']}"}
            )
        narrative_store.set_thread_status(ALICE, thread.id, "active")
        reading = narrative_store.propose_reading(
            ALICE, thread.id, author=author,
            reading={"tensions": [text], "open_questions": [], "milestones": []},
            evidence_refs=(ref,),
        )
        narrative_store.accept_reading(ALICE, reading.id)
        return narrative_store.get_thread(ALICE, thread.id)

    # The FIRST cited thread does not name the subject; the second does.
    t1 = _standing("Loft ledger", claim_a, "mentor", "one")
    t2 = _standing("Harbor notes", claim_b, "champion", "two", name_task=True)
    ev1 = narrative_store.evidence_for(ALICE, t1.id)[0].id
    ev2 = narrative_store.evidence_for(ALICE, t2.id)[0].id
    outcome = corr_mod.propose_correspondence(
        narrative_store, ALICE,
        evidence_refs=[ev1, ev2],
        structural_tension="patience vs avoidance",
        proposed_relationship="restraint that is simultaneously protective and limiting",
        candidate_metaphor="Odysseus bound to the mast",
        mapping={"patience": "the ropes", "avoidance": "the mast"},
        limitations="the myth does not say whether the restraint is wisdom or fear",
    )
    assert outcome.abstained is False
    result = _read(narrative_store, conv_store, ft_store, ALICE, "task", task["id"])
    kinds = {item["item_kind"] for item in result["pending"]}
    assert "correspondence" in kinds
