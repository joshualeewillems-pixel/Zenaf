"""Subject-interaction counts (the Living Palace's ivy read).

The endpoint GET /conversation/subject-interactions serves, for the
caller only, per-subject counts of the visitor turns sent with that
subject selected, split by the seat they were sent to — the linkage
context_preparation.py documents (a user message's own live-context
snapshot names its subject; the message's archetype_id is its seat).

Coverage: the aggregation itself (user turns only, subject-naming
snapshots only), the route's shape, structural owner isolation
(another user's subjects are absent, and their turns never move the
caller's counts), the 401 gate, and failure isolation (a failed
read degrades to an empty result, never a 500).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.routes.conversation_routes as conv_routes
from api.routes.auth_routes import get_current_user
from local_ai.conversation.store import ConversationStore
from local_ai.conversation.subject_interactions import (
    aggregate_subject_interactions,
    subject_interactions_for_user,
)

ALICE = {"id": "user-alice", "email": "alice@x", "display_name": "Alice"}
BOB = {"id": "user-bob", "email": "bob@x", "display_name": "Bob"}


def _store(tmp_path) -> ConversationStore:
    return ConversationStore(db_path=tmp_path / "conv.db")


def _turn(store, user, conv, seat, entity_type=None, entity_id=None, role="user"):
    context = {"sheet_type": "living_palace"}
    if entity_type is not None:
        context["entity_type"] = entity_type
    if entity_id is not None:
        context["entity_id"] = entity_id
    store.append_message(user, conv, seat, role, "words", context=context)


def _seed_alice(store):
    # Three turns to Rumi and two to Maeve about project p1, one to
    # Maeve about initiative i1 — across two conversations.
    for _ in range(3):
        _turn(store, ALICE["id"], "living-palace:project:p1", "mentor", "project", "p1")
    for _ in range(2):
        _turn(store, ALICE["id"], "campaign-board:project:p1", "guardian", "project", "p1")
    _turn(store, ALICE["id"], "living-palace:initiative:i1", "guardian", "initiative", "i1")
    # A seat reply echoing the same snapshot is not a visitor turn.
    _turn(store, ALICE["id"], "living-palace:project:p1", "mentor", "project", "p1", role="assistant")
    # Turns naming no subject, or a type outside the vocabulary,
    # are not interactions about a subject.
    _turn(store, ALICE["id"], "skeleton", "mentor")
    _turn(store, ALICE["id"], "skeleton", "mentor", "planet", "x1")


def test_aggregation_counts_visitor_turns_per_subject_and_seat(tmp_path):
    store = _store(tmp_path)
    _seed_alice(store)
    result = subject_interactions_for_user(store, ALICE["id"])
    store.close()
    subjects = {(s["entity_type"], s["entity_id"]): s for s in result["subjects"]}
    assert set(subjects) == {("project", "p1"), ("initiative", "i1")}
    assert subjects[("project", "p1")]["total"] == 5
    assert subjects[("project", "p1")]["per_seat"] == {"guardian": 2, "mentor": 3}
    assert subjects[("initiative", "i1")]["total"] == 1
    assert subjects[("initiative", "i1")]["per_seat"] == {"guardian": 1}


def test_aggregation_ignores_malformed_snapshots():
    messages = [
        {"role": "user", "archetype_id": "mentor", "context": "not-a-dict"},
        {"role": "user", "archetype_id": "mentor", "context": {"entity_type": "project"}},
        {"role": "user", "archetype_id": "mentor", "context": {"entity_id": "p1"}},
        {"role": "user", "archetype_id": None, "context": {"entity_type": "task", "entity_id": "t1"}},
    ]
    result = aggregate_subject_interactions(messages)
    # Only the well-formed snapshot counts; a seatless turn still
    # counts toward the total, with no seat attribution.
    assert result["subjects"] == [
        {"entity_type": "task", "entity_id": "t1", "total": 1, "per_seat": {}}
    ]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = _store(tmp_path)
    monkeypatch.setattr(conv_routes, "_store", lambda: store)
    holder = {"user": ALICE}
    app = FastAPI()
    app.include_router(conv_routes.router)
    app.dependency_overrides[get_current_user] = lambda: holder["user"]
    c = TestClient(app)
    yield c, store, holder
    store.close()


def test_endpoint_serves_the_caller_counts(client):
    c, store, _holder = client
    _seed_alice(store)
    r = c.get("/conversation/subject-interactions")
    assert r.status_code == 200, r.text
    subjects = {(s["entity_type"], s["entity_id"]): s for s in r.json()["subjects"]}
    assert subjects[("project", "p1")]["total"] == 5
    assert subjects[("project", "p1")]["per_seat"] == {"guardian": 2, "mentor": 3}


def test_endpoint_owner_isolation(client):
    c, store, holder = client
    _seed_alice(store)
    # Bob discusses his own project — and, pointedly, a subject id
    # that collides with Alice's project id.
    for _ in range(4):
        _turn(store, BOB["id"], "living-palace:project:p9", "maverick", "project", "p9")
    _turn(store, BOB["id"], "living-palace:project:p1", "maverick", "project", "p1")

    holder["user"] = BOB
    r = c.get("/conversation/subject-interactions")
    assert r.status_code == 200, r.text
    bob_subjects = {(s["entity_type"], s["entity_id"]): s for s in r.json()["subjects"]}
    assert set(bob_subjects) == {("project", "p9"), ("project", "p1")}
    # Bob's p1 count is his own single turn — Alice's five never leak.
    assert bob_subjects[("project", "p1")]["total"] == 1
    assert bob_subjects[("project", "p9")]["total"] == 4

    holder["user"] = ALICE
    r = c.get("/conversation/subject-interactions")
    alice_subjects = {(s["entity_type"], s["entity_id"]): s for s in r.json()["subjects"]}
    # Alice never sees Bob's project, and her p1 count is unmoved.
    assert ("project", "p9") not in alice_subjects
    assert alice_subjects[("project", "p1")]["total"] == 5


def test_endpoint_empty_for_a_fresh_owner(client):
    c, _store_, _holder = client
    r = c.get("/conversation/subject-interactions")
    assert r.status_code == 200, r.text
    assert r.json() == {"subjects": []}


def test_endpoint_requires_sign_in(tmp_path, monkeypatch):
    store = _store(tmp_path)
    monkeypatch.setattr(conv_routes, "_store", lambda: store)
    app = FastAPI()
    app.include_router(conv_routes.router)
    app.dependency_overrides[get_current_user] = lambda: {}
    c = TestClient(app)
    r = c.get("/conversation/subject-interactions")
    store.close()
    assert r.status_code == 401


def test_endpoint_failure_degrades_to_empty(client, monkeypatch):
    c, _store_, _holder = client

    def _boom():
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(conv_routes, "_store", _boom)
    r = c.get("/conversation/subject-interactions")
    assert r.status_code == 200, r.text
    assert r.json() == {"subjects": []}
