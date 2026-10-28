"""Migration dry-run inventory tests (design: Joshua).

The inventory route reports what the stage-4 migration *would* do
without doing it. These tests pin the load-bearing guarantee: the
inventory path never writes. File bytes are hashed before and
after every inventory call (unit and route level) and must be
identical. No live API calls, no live store.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI

from api.routes import build_room_routes as br_routes
from api.routes.auth_routes import get_current_user
from local_ai.build_room.migration import inventory_store_dir

OWNER = {"id": "owner-id", "email": "owner@local.zenaf"}
OTHER = {"id": "someone-else"}


def _small_artifact():
    return {
        "status": "DRAFT_EXPERIMENTAL",
        "meeting_id": "test123",
        "claim_registry": [
            {"id": "C1", "participant": "GPT", "phase": "opening",
             "status": "Observed", "text": "Authority confusion is a risk.",
             "supersedes": None, "withdraws": None,
             "epistemic_assessment": "unresolved", "assessment_sources": []},
        ],
        "interactions": [],
    }


def _write(path: Path, payload) -> None:
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")


def _hash_store(store: Path) -> dict[str, str]:
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(store.iterdir()) if p.is_file()
    }


def _fake_store(store: Path) -> None:
    store.mkdir(parents=True, exist_ok=True)
    migratable = _small_artifact()
    already = _small_artifact()
    already["meeting_id"] = "already1"
    already["claim_standing"] = {"version": 1, "entries": []}
    _write(store / "meeting_aaa.draft_artifact.json", migratable)
    _write(store / "meeting_bbb.draft_artifact.json", already)
    _write(store / "meeting_ccc.draft_artifact.json", "{not json")
    _write(store / "meeting_ddd.draft_artifact.json", {"meeting_id": "no-registry"})
    _write(store / "meeting_eee.draft_artifact.json", ["not", "an", "object"])
    _write(store / "meeting_fff.transcript.json", {"entries": []})
    _write(store / "usage.jsonl", "{}\n")


def test_inventory_reports_verdicts_and_totals(tmp_path):
    store = tmp_path / "store"
    _fake_store(store)
    before = _hash_store(store)
    report = inventory_store_dir(store)
    # The guarantee: nothing in the store changed.
    assert _hash_store(store) == before
    assert report["totals"] == {
        "files": 5,  # transcript + usage files are not artifacts
        "would_migrate": 1,
        "already_present": 1,
        "unmigrated": 2,  # no-registry + non-object JSON
        "failed": 1,  # corrupt JSON
    }
    by_file = {f["file"]: f for f in report["files"]}
    assert by_file["meeting_aaa.draft_artifact.json"]["verdict"] == "would_migrate"
    assert by_file["meeting_aaa.draft_artifact.json"]["claims"] == 1
    assert by_file["meeting_aaa.draft_artifact.json"]["has_claim_standing"] is False
    assert by_file["meeting_aaa.draft_artifact.json"]["meeting_id"] == "test123"
    assert by_file["meeting_bbb.draft_artifact.json"]["verdict"] == "already_present"
    assert by_file["meeting_bbb.draft_artifact.json"]["has_claim_standing"] is True
    assert by_file["meeting_ccc.draft_artifact.json"]["verdict"] == "failed"
    assert by_file["meeting_ddd.draft_artifact.json"]["verdict"] == "unmigrated"
    assert by_file["meeting_ddd.draft_artifact.json"]["meeting_id"] == "no-registry"
    assert by_file["meeting_eee.draft_artifact.json"]["verdict"] == "unmigrated"
    # No contents leak: no claim texts, registries, or tables.
    assert "Authority confusion" not in json.dumps(report)
    assert "claim_registry" not in json.dumps(report)
    assert "entries" not in json.dumps(report)


def test_inventory_missing_meeting_id_falls_back_to_filename(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    artifact = _small_artifact()
    del artifact["meeting_id"]
    _write(store / "meeting_zzz.draft_artifact.json", artifact)
    report = inventory_store_dir(store)
    assert report["files"][0]["meeting_id"] == "zzz"


def test_inventory_missing_directory_reports_without_raising():
    report = inventory_store_dir("/nonexistent/store/dir")
    assert report["totals"]["files"] == 0
    assert report["files"] == []
    assert "error" in report


# --- Endpoint: GET /build-room/artifacts/inventory ---


def _call_get(app, path: str) -> tuple[int, dict]:
    scope = {
        "type": "http", "http_version": "1.1", "method": "GET", "scheme": "http",
        "path": path, "raw_path": path.encode(), "query_string": b"",
        "headers": [],
        "client": ("testclient", 50000), "server": ("testserver", 80),
    }
    messages: list[dict] = []
    sent = False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(m for m in messages if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in messages
                    if m["type"] == "http.response.body")
    return start["status"], json.loads(body.decode() or "{}")


@pytest.fixture()
def app(tmp_path, monkeypatch):
    import local_ai.vision_execution.storage as ve_store_mod

    monkeypatch.setattr(br_routes, "get_build_room_store_dir", lambda: tmp_path / "store")
    monkeypatch.setattr(ve_store_mod, "get_owner_user_id", lambda: OWNER["id"])
    application = FastAPI()
    application.include_router(br_routes.router)
    return application


def test_inventory_route_unauthenticated_is_401(app):
    status, _ = _call_get(app, "/build-room/artifacts/inventory")
    assert status == 401


def test_inventory_route_non_owner_is_403(app):
    app.dependency_overrides[get_current_user] = lambda: OTHER
    status, _ = _call_get(app, "/build-room/artifacts/inventory")
    assert status == 403


def test_inventory_route_owner_reports_and_writes_nothing(app, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    store = tmp_path / "store"
    _fake_store(store)
    before = _hash_store(store)
    status, body = _call_get(app, "/build-room/artifacts/inventory")
    assert status == 200, body
    assert body["totals"]["files"] == 5
    assert body["totals"]["would_migrate"] == 1
    assert body["totals"]["already_present"] == 1
    assert body["totals"]["unmigrated"] == 2
    assert body["totals"]["failed"] == 1
    # The route wrote nothing either.
    assert _hash_store(store) == before
