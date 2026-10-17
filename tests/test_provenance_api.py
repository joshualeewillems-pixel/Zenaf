"""Provenance API routes via TestClient (auth dependency overridden, tmp db)."""

from __future__ import annotations

import base64
import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

import api.routes.provenance_routes as prov_routes
from api.routes.auth_routes import get_current_user
from local_ai.provenance.store import ProvenanceStore

ALICE = {"id": "user-alice", "email": "alice@x", "display_name": "Alice"}
BOB = {"id": "user-bob", "email": "bob@x", "display_name": "Bob"}


def _img_b64(kind: str = "halves") -> str:
    img = Image.new("RGB", (64, 64), "white")
    d = ImageDraw.Draw(img)
    if kind == "halves":
        d.rectangle([0, 0, 31, 63], fill="black")
    else:
        d.ellipse([12, 12, 52, 52], fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = ProvenanceStore(tmp_path / "prov.db")
    monkeypatch.setattr(prov_routes, "_store", lambda: store)
    app = FastAPI()
    app.include_router(prov_routes.router)
    app.dependency_overrides[get_current_user] = lambda: ALICE
    c = TestClient(app)
    yield c
    store.close()


def _register(client, kind="halves", **kw):
    body = {"image_base64": _img_b64(kind), "title": kw.get("title", kind)}
    if "remix_policy" in kw:
        body["remix_policy"] = kw["remix_policy"]
    r = client.post("/provenance/register", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_register_mint_publish_flow(client):
    a = _register(client)
    assert a["visibility"] == "unlisted"
    r = client.post(f"/provenance/{a['artifact_id']}/mint")
    assert r.json()["visibility"] == "private"
    r = client.post(f"/provenance/{a['artifact_id']}/publish")
    assert r.json()["visibility"] == "public"


def test_register_rejects_bad_image(client):
    r = client.post("/provenance/register", json={"image_base64": "aGVsbG8="})
    assert r.status_code == 422


def test_derive_event_lineage_roundtrip(client):
    parent = _register(client, kind="halves")
    r = client.post(
        "/provenance/derive",
        json={"parent_ids": [parent["artifact_id"]],
              "image_base64": _img_b64("circle"), "title": "remix"},
    )
    assert r.status_code == 200, r.text
    child_id = r.json()["artifact"]["artifact_id"]
    assert r.json()["links"][0]["status"] == "linked"

    r = client.post("/provenance/events", json={
        "artifact_id": child_id, "type": "journal_sparked",
        "context": {"entry_ref": "journal-1"},
    })
    assert r.status_code == 200

    r = client.get(f"/provenance/artifacts/{parent['artifact_id']}/lineage")
    assert r.status_code == 200, r.text
    lineage = r.json()
    assert len(lineage["tree"]["children"]) == 1
    types = [e["type"] for e in lineage["timeline"]]
    assert "minted" in types and "journal_sparked" in types and "remixed" in types
    # reach: remixed 10 + journal_sparked 14*0.6 = 18.4
    r = client.get(f"/provenance/artifacts/{parent['artifact_id']}")
    assert r.json()["reach_cached"] == pytest.approx(18.4)


def test_approval_flow_via_api(client):
    # Deriving from your OWN approval-policy artifact needs no approval.
    parent = _register(client, kind="halves", remix_policy="approval")
    r = client.post(
        "/provenance/derive",
        json={"parent_ids": [parent["artifact_id"]],
              "image_base64": _img_b64("circle")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["links"][0]["status"] == "linked"
    # The pending path (stranger derives) is covered in test_provenance_service.py.


def test_ingest_three_outcomes(client):
    a = _register(client, kind="halves")
    # exact
    r = client.post("/provenance/ingest",
                    json={"image_base64": _img_b64("halves"), "title": "dup"})
    assert r.json()["outcome"] == "exact"
    assert r.json()["artifact"]["artifact_id"] == a["artifact_id"]
    # none
    r = client.post("/provenance/ingest",
                    json={"image_base64": _img_b64("circle"), "title": "new"})
    assert r.json()["outcome"] == "none"
    assert r.json()["artifact"]["imported"] is True


def test_dispute_flow(client):
    a = _register(client, kind="halves")
    # A creator cannot dispute their own artifact.
    r = client.post("/provenance/disputes",
                    json={"artifact_id": a["artifact_id"], "evidence": "mine"})
    assert r.status_code == 422
    # The stranger-challenger flow is covered in test_provenance_service.py.


def test_ledger(client):
    _register(client, kind="halves")
    r = client.get("/provenance/ledger")
    assert r.status_code == 200
    ledger = r.json()
    assert ledger["user_id"] == "user-alice"
    assert len(ledger["artifacts"]) == 1
    assert "perspective_reach" in ledger


def test_recompute(client):
    _register(client, kind="halves")
    r = client.post("/provenance/recompute")
    assert r.json()["recomputed"] == 1
