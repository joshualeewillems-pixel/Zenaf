"""Per-response feedback API tests (TestClient; run in CI).

Route-level coverage for POST /feedback and GET /feedback. The store uses
a tmp SQLite file. No training writes exist in v1, so these tests assert
the inert-record contract: untouched stores nothing, an explicit submit
stores exactly the submitted values, and rows are strictly per-user.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.routes.feedback_routes as fb_routes
from api.routes.auth_routes import get_current_user
from local_ai.feedback.store import FeedbackStore

ALICE = {"id": "user-alice", "email": "alice@x", "display_name": "Alice"}
BOB = {"id": "user-bob", "email": "bob@x", "display_name": "Bob"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = FeedbackStore(db_path=tmp_path / "fb.db")
    monkeypatch.setattr(fb_routes, "_store", lambda: store)
    app = FastAPI()
    app.include_router(fb_routes.router)
    app.dependency_overrides[get_current_user] = lambda: ALICE
    c = TestClient(app)
    yield c, store, app
    store.close()


def _submit(c, **overrides):
    body = {
        "response_ref": "msg-abc123",
        "conversation_id": "skeleton",
        "seat": "mentor",
        "slider": 6,
        "checks": ["Helpful", "Want more of this"],
        "note": "This landed well.",
    }
    body.update(overrides)
    return c.post("/feedback", json=body)


def test_untouched_stores_nothing(client):
    """No POST at all → zero records. The inert default, asserted."""
    c, _store, _app = client
    r = c.get("/feedback")
    assert r.status_code == 200, r.text
    assert r.json()["records"] == []


def test_submit_round_trips_exact_values(client):
    c, _store, _app = client
    r = _submit(c)
    assert r.status_code == 200, r.text
    created = r.json()
    assert created["response_ref"] == "msg-abc123"
    assert created["conversation_id"] == "skeleton"
    assert created["seat"] == "mentor"
    assert created["slider"] == 6
    assert created["checks"] == ["Helpful", "Want more of this"]
    assert created["note"] == "This landed well."
    assert created["review_status"] == "unreviewed"
    assert created["id"]

    r = c.get("/feedback")
    assert r.status_code == 200
    records = r.json()["records"]
    assert len(records) == 1
    assert records[0] == created


def test_explicit_neutral_submit_records(client):
    """An explicit submit of all defaults still records: deliberate
    interaction creates a record (doc's explicit-neutral proposal)."""
    c, _store, _app = client
    r = _submit(c, slider=4, checks=[], note="")
    assert r.status_code == 200, r.text
    assert r.json()["slider"] == 4
    assert r.json()["checks"] == []
    assert r.json()["note"] == ""
    assert len(c.get("/feedback").json()["records"]) == 1


def test_submit_rejects_bad_input(client):
    c, _store, _app = client
    assert c.post("/feedback", json={
        "response_ref": "x", "seat": "mentor", "slider": 0}).status_code == 422
    assert c.post("/feedback", json={
        "response_ref": "x", "seat": "mentor", "slider": 8}).status_code == 422
    assert c.post("/feedback", json={
        "response_ref": "x", "seat": "nope", "slider": 4}).status_code == 422
    assert c.post("/feedback", json={
        "response_ref": "x", "seat": "mentor", "slider": 4,
        "checks": ["Not a preset"]}).status_code == 422
    assert c.post("/feedback", json={
        "response_ref": "", "seat": "mentor", "slider": 4}).status_code == 422
    assert c.post("/feedback", json={
        "response_ref": "   ", "seat": "mentor", "slider": 4}).status_code == 422
    assert c.get("/feedback").json()["records"] == []


def test_records_are_strictly_per_user(client):
    c, store, app = client
    assert _submit(c).status_code == 200
    app.dependency_overrides[get_current_user] = lambda: BOB
    assert c.get("/feedback").json()["records"] == []
    r = _submit(c, response_ref="msg-bob1", seat="guardian")
    assert r.status_code == 200
    assert len(c.get("/feedback").json()["records"]) == 1
    app.dependency_overrides[get_current_user] = lambda: ALICE
    records = c.get("/feedback").json()["records"]
    assert len(records) == 1
    assert records[0]["response_ref"] == "msg-abc123"


def test_list_filters_by_conversation_and_newest_first(client):
    c, _store, _app = client
    assert _submit(c, response_ref="m1", conversation_id="skeleton").status_code == 200
    assert _submit(c, response_ref="m2", conversation_id="other").status_code == 200
    all_records = c.get("/feedback").json()["records"]
    assert [r["response_ref"] for r in all_records] == ["m2", "m1"]
    only = c.get("/feedback", params={"conversation_id": "skeleton"}).json()["records"]
    assert [r["response_ref"] for r in only] == ["m1"]
