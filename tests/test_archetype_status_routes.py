"""Shadowed-route regression: GET /council/archetypes/status shape.

Two routers once claimed the same path with the same function name:
- api/routes/council_archetype_routes.py GET /status returned the RENAME
  shape (rename_status(): unlock states, avatars, milestones);
- api/routes/council_routes.py GET /archetypes/status returns the FULL
  shape (ArchetypeStatusResponse) the Living Tree consumes.

The naming router registers first in api/main.py, so the rename shape
deterministically won the path and the tree handler was unreachable over
HTTP — while the frontend's fetchArchetypeStatus only checks that the
response has an ``archetypes`` array and casts unchecked, so the wrong
shape passed validation silently.

The fix separates the paths: the naming GET moved to
GET /council/archetypes/naming-status. These tests mount BOTH routers in
api/main.py's registration order and assert, through the real ASGI app,
that each path serves its own shape — and that the two shapes differ.

Transport note: this environment has no httpx, so starlette's TestClient
is unavailable (its import fails at collection in 15 pre-existing test
files). Instead of skipping, the tests below drive the app through its
ASGI interface directly — the same routing, dependency injection, and
response-model serialization TestClient would exercise, minus the socket.
No test is faked: a wrong handler or a wrong shape fails the assertions.

Stores are redirected to tmp_path (personality profiles, twigs, VE task
store), so a fresh user has no approved signals and no twigs: the full
handler returns 0-depth entries and the rename handler returns locked
unlock states. No LLM is involved anywhere in this file.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import FastAPI

from api.routes.auth_routes import get_current_user
from api.routes import council_archetype_routes as arch_routes
from api.routes import council_routes

USER = {"id": "route-test-user"}


def _call_app(app, path: str) -> tuple[int, dict]:
    """Drive a GET through the app's ASGI interface; return (status, json)."""
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    messages: list[dict] = []
    sent_request = False

    async def receive():
        nonlocal sent_request
        if not sent_request:
            sent_request = True
            return {"type": "http.request", "body": b"", "more_body": False}
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
    """Both routers, mounted in api/main.py's registration order.

    The naming router registers BEFORE the council router — that order
    is the bug's mechanism, so the fixture preserves it deliberately.
    Store paths are redirected to tmp_path so no real data is read or
    written.
    """
    import local_ai.council.twigs as twigs_mod
    import local_ai.personality.store as profile_store_mod
    import local_ai.vision_execution.storage as ve_store_mod

    monkeypatch.setattr(profile_store_mod, "DEFAULT_DB_PATH", tmp_path / "profiles.db")
    monkeypatch.setattr(twigs_mod, "DEFAULT_DB_PATH", tmp_path / "twigs.db")
    monkeypatch.setattr(ve_store_mod, "_DB_PATH", tmp_path / "ve.db")
    monkeypatch.setattr(ve_store_mod, "_DB_DIR", tmp_path)

    application = FastAPI()
    application.include_router(arch_routes.router)
    application.include_router(council_routes.router)
    application.dependency_overrides[get_current_user] = lambda: USER
    return application


def test_status_returns_full_tree_shape(app):
    status, body = _call_app(app, "/council/archetypes/status")
    assert status == 200, body
    assert "computed_at" in body
    entries = body["archetypes"]
    assert len(entries) == 7
    for entry in entries:
        # The full tree shape — and NOT the rename shape.
        assert isinstance(entry["strand_weights"], dict)
        assert isinstance(entry["band"], str) and entry["band"]
        assert isinstance(entry["prompt_frame"], str) and entry["prompt_frame"]
        assert isinstance(entry["twigs"], list)
        assert isinstance(entry["is_skeptic"], bool)
        # int, not float: the rename shape reports depth as a float.
        assert type(entry["depth"]) is int
        assert 0 <= entry["depth"] <= 100
        assert "rename_unlocked" not in entry
        assert "signals_to_unlock" not in entry


def test_naming_status_returns_rename_shape(app):
    status, body = _call_app(app, "/council/archetypes/naming-status")
    assert status == 200, body
    entries = body["archetypes"]
    assert len(entries) == 7
    for entry in entries:
        # The rename shape — and NOT the full tree shape.
        assert isinstance(entry["rename_unlocked"], bool)
        assert isinstance(entry["signals_to_unlock"], int)
        assert type(entry["depth"]) is float
        assert "twigs" not in entry
        assert "strand_weights" not in entry
        assert "prompt_frame" not in entry
    assert isinstance(body["all_rename_unlocked"], bool)
    assert isinstance(body["custom_archetype"], dict)


def test_paths_return_different_shapes(app):
    """Regression: the two paths must not serve each other's shape."""
    _, status_body = _call_app(app, "/council/archetypes/status")
    _, naming_body = _call_app(app, "/council/archetypes/naming-status")
    status_keys = set(status_body["archetypes"][0])
    naming_keys = set(naming_body["archetypes"][0])
    assert "twigs" in status_keys and "twigs" not in naming_keys
    assert "rename_unlocked" in naming_keys and "rename_unlocked" not in status_keys
    assert status_keys != naming_keys
