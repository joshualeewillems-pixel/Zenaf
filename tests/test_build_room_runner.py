"""Runner endpoint tests: owner gate + R1 invocation through HTTP.

No httpx here, so starlette's TestClient is unavailable; like the
archetype-status tests, these drive a minimal FastAPI app through
its ASGI interface directly. Generation is mocked — no live API
calls, no real key values anywhere. A fake key value is used to
prove it never leaks into responses.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import FastAPI

from api.routes import build_room_routes as br_routes
from api.routes.auth_routes import get_current_user
from local_ai.build_room import participants as part_mod
from local_ai.build_room.meeting import MeetingResult, Transcript

FAKE_KEY = "FAKE-KEY-VALUE-67890"
OWNER = {"id": "owner-id", "email": "owner@local.zenaf"}
OTHER = {"id": "someone-else"}


def _call_post(app, path: str, payload: dict) -> tuple[int, dict]:
    """Drive a POST with a JSON body through the ASGI interface."""
    raw = json.dumps(payload).encode()
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(raw)).encode()),
        ],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    messages: list[dict] = []
    sent_request = False

    async def receive():
        nonlocal sent_request
        if not sent_request:
            sent_request = True
            return {"type": "http.request", "body": raw, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(m for m in messages if m["type"] == "http.response.start")
    body = b"".join(
        m.get("body", b"") for m in messages if m["type"] == "http.response.body"
    )
    return start["status"], json.loads(body.decode() or "{}")


@pytest.fixture()
def app(tmp_path, monkeypatch):
    """Minimal app with only the build-room router.

    Store dir redirected to tmp_path; owner id stubbed so no real
    database is touched. Auth is overridden per test.
    """
    import local_ai.vision_execution.storage as ve_store_mod

    monkeypatch.setattr(
        br_routes, "get_build_room_store_dir", lambda: tmp_path / "store"
    )
    monkeypatch.setattr(ve_store_mod, "get_owner_user_id", lambda: OWNER["id"])
    application = FastAPI()
    application.include_router(br_routes.router)
    return application


def _mock_generation_ok(monkeypatch):
    def fake_generate(api_key, prompt, *, model=None, timeout=120):
        assert api_key == FAKE_KEY
        assert "Test work item" in prompt and "Is this sound?" in prompt
        return "Canned deliberation: observed X, proposed Y."

    monkeypatch.setattr(
        part_mod, "resolve_cloud_api_key", lambda p, pid: (FAKE_KEY, "settings")
    )
    monkeypatch.setattr(part_mod._openai, "generate", fake_generate)


def _body() -> dict:
    return {
        "work_item": "Test work item",
        "question": "Is this sound?",
        "excerpts": ["excerpt one"],
        "constraints": ["keep it small"],
        "source_refs": ["local_ai/build_room/meeting.py"],
    }


def test_unauthenticated_is_401(app):
    status, _ = _call_post(app, "/build-room/meetings", _body())
    assert status == 401


def test_non_owner_is_403(app):
    app.dependency_overrides[get_current_user] = lambda: OTHER
    status, _ = _call_post(app, "/build-room/meetings", _body())
    assert status == 403


def test_owner_runs_meeting_persists_files(app, tmp_path, monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    _mock_generation_ok(monkeypatch)
    status, body = _call_post(app, "/build-room/meetings", _body())
    assert status == 200, body
    assert body["meeting_id"]
    assert body["ok"] is True
    kinds = [e["kind"] for e in body["transcript"]["entries"]]
    assert kinds == ["convene", "contribution"]
    assert (
        body["transcript"]["entries"][1]["text"]
        == "Canned deliberation: observed X, proposed Y."
    )
    artifact = body["artifact"]
    assert artifact["status"] == "DRAFT_EXPERIMENTAL"
    assert artifact["is_review_item"] is False
    assert artifact["experimental_area"] is True
    assert "RECOMMENDS ONLY" in artifact["authorization"]
    assert artifact["recommendation"] == "Canned deliberation: observed X, proposed Y."
    assert artifact["provenance"]["key_source"] == "settings"
    assert FAKE_KEY not in json.dumps(body)
    store = tmp_path / "store"
    assert list(store.glob("meeting_*.transcript.json"))
    assert list(store.glob("meeting_*.draft_artifact.json"))


def test_absence_is_recorded_not_raised(app, monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    monkeypatch.setattr(
        part_mod, "resolve_cloud_api_key", lambda p, pid: (None, "none")
    )
    status, body = _call_post(app, "/build-room/meetings", _body())
    assert status == 200, body
    assert body["ok"] is False
    kinds = [e["kind"] for e in body["transcript"]["entries"]]
    assert kinds == ["convene", "absence"]
    assert body["artifact"]["provenance"]["status"] == "absent"


def test_blank_work_item_is_422(app):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    payload = _body()
    payload["work_item"] = "   "
    status, _ = _call_post(app, "/build-room/meetings", payload)
    assert status == 422


def test_caller_account_principal_is_used(app, tmp_path, monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    seen: dict = {}

    def fake_run(packet, *, store_dir, budget=None, principal=None, participant=None):
        seen["principal"] = principal
        seen["store_dir"] = str(store_dir)
        seen["work_item"] = packet.work_item
        return MeetingResult(
            meeting_id="m1",
            transcript=Transcript(),
            artifact={"status": "DRAFT_EXPERIMENTAL"},
            ok=True,
            transcript_path=tmp_path / "t.json",
            artifact_path=tmp_path / "a.json",
        )

    monkeypatch.setattr(br_routes, "run_single_model_meeting", fake_run)
    status, body = _call_post(app, "/build-room/meetings", _body())
    assert status == 200, body
    assert body["meeting_id"] == "m1"
    principal = seen["principal"]
    assert principal.account_user_id == OWNER["id"]
    assert principal.scope == "account"
    assert seen["store_dir"] == str(tmp_path / "store")
    assert seen["work_item"] == "Test work item"
