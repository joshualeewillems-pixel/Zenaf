"""Conversation skeleton API tests (TestClient; run in CI).

Route-level coverage for POST /conversation/turn, GET /conversation,
GET /conversation/suggestions, and POST /voice/chat with conversation_id.
The LLM is faked; the store uses a tmp SQLite file.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.routes.conversation_routes as conv_routes
import api.routes.voice_routes as voice_routes
from api.routes.auth_routes import get_current_user
import local_ai.conversation.reply as reply_mod
import local_ai.conversation.suggestions as sugg_mod
from local_ai.conversation.service import ConversationService
from local_ai.conversation.store import ConversationStore
from local_ai.conversation.suggestions import generate_suggestions

ALICE = {"id": "user-alice", "email": "alice@x", "display_name": "Alice"}


def _fake_generate(prompt: str, **kwargs) -> str:
    return "Fake reply."


def _store(tmp_path) -> ConversationStore:
    return ConversationStore(db_path=tmp_path / "conv.db")


def _suggestion_llm(prompt: str, **kwargs) -> str:
    import json

    return json.dumps(
        {
            "trainable_moments": [
                {
                    "title": "Values rest",
                    "claim_type": "value_inference",
                    "evidence": "I protect my mornings fiercely",
                    "inference": "Mornings are a protected value.",
                    "question": "Mornings sacred \u2014 right?",
                }
            ],
            "project_proposals": [
                {
                    "kind": "task",
                    "title": "Fix the fence",
                    "source_quote": "I need to fix the fence",
                    "detail": "backyard fence is leaning",
                }
            ],
            "mint_suggestions": [
                {
                    "title": "The leaning fence",
                    "moment": "noticing the fence at dawn",
                    "source_quote": "the light hit it just so",
                    "why": "a whole story in one image",
                }
            ],
        }
    )

# -- routes --------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = _store(tmp_path)
    svc = ConversationService(store, generate_fn=_fake_generate)
    monkeypatch.setattr(conv_routes, "_store", lambda: store)
    monkeypatch.setattr(conv_routes, "_service", lambda: svc)
    monkeypatch.setattr(voice_routes, "_conversation_store", lambda: store)
    monkeypatch.setattr(reply_mod, "_default_generate", _fake_generate)
    monkeypatch.setattr(
        sugg_mod,
        "generate_suggestions",
        lambda turns, live_context=None, **kw: generate_suggestions(
            [{"role": "user", "body": "I protect my mornings fiercely",
              "archetype_id": "mentor"}],
            live_context,
            generate_fn=_suggestion_llm,
            user_id="user-alice",
        ),
    )
    app = FastAPI()
    app.include_router(conv_routes.router)
    app.include_router(voice_routes.router)
    app.dependency_overrides[get_current_user] = lambda: ALICE
    c = TestClient(app)
    yield c, store
    store.close()


def test_turn_and_hydrate(client):
    c, store = client
    r = c.post(
        "/conversation/turn",
        json={"archetype_id": "mentor", "message": "plan my week",
              "context": {"sheet_type": "today"}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reply"] == "Fake reply."
    assert body["archetype_id"] == "mentor"
    assert body["conversation_id"] == "skeleton"

    r = c.get("/conversation", params={"limit": 10})
    assert r.status_code == 200
    msgs = r.json()["messages"]
    assert len(msgs) == 2
    assert msgs[0]["body"] == "plan my week"
    assert msgs[0]["context"]["sheet_type"] == "today"
    assert msgs[1]["body"] == "Fake reply."


def test_turn_rejects_bad_input(client):
    c, _ = client
    r = c.post("/conversation/turn", json={"archetype_id": "nope", "message": "hi"})
    assert r.status_code == 422
    r = c.post("/conversation/turn", json={"archetype_id": "mentor", "message": "  "})
    assert r.status_code == 422
    # question mode allows empty message
    r = c.post("/conversation/turn",
               json={"archetype_id": "mentor", "message": "", "question": True})
    assert r.status_code == 200


def test_voice_chat_conversation_id_uses_server_history(client, monkeypatch):
    c, store = client
    # seed server-side history directly
    store.ensure_conversation("user-alice")
    store.append_message("user-alice", "skeleton", "mentor", "user", "SERVER MARKER ONE")
    store.append_message("user-alice", "skeleton", "mentor", "voice", "noted", mode="base")

    prompts = []
    monkeypatch.setattr(
        reply_mod, "_default_generate",
        lambda prompt, **kw: prompts.append(prompt) or "Fake reply.",
    )
    r = c.post(
        "/voice/chat",
        json={
            "archetype_id": "mentor",
            "message": "continue",
            "history": [{"role": "user", "content": "JUNK CLIENT HISTORY"}],
            "conversation_id": "skeleton",
        },
    )
    assert r.status_code == 200, r.text
    assert prompts, "expected the reply builder to run"
    assert "SERVER MARKER ONE" in prompts[-1]
    assert "JUNK CLIENT HISTORY" not in prompts[-1]
    # both turns persisted to the skeleton
    msgs = c.get("/conversation").json()["messages"]
    assert [m["body"] for m in msgs[-2:]] == ["continue", "Fake reply."]


def test_voice_chat_without_conversation_id_unchanged(client, monkeypatch):
    c, store = client
    prompts = []
    monkeypatch.setattr(
        reply_mod, "_default_generate",
        lambda prompt, **kw: prompts.append(prompt) or "Fake reply.",
    )
    r = c.post(
        "/voice/chat",
        json={
            "archetype_id": "mentor",
            "message": "hello",
            "history": [{"role": "user", "content": "CLIENT HISTORY MARKER"}],
        },
    )
    assert r.status_code == 200, r.text
    assert "CLIENT HISTORY MARKER" in prompts[-1]
    # nothing persisted to the skeleton
    assert c.get("/conversation").json()["messages"] == []


def test_suggestions_endpoint_cached_and_read_only(client):
    c, store = client
    c.post("/conversation/turn", json={"archetype_id": "mentor", "message": "I protect my mornings"})
    before = len(store.history("user-alice", "skeleton"))

    r1 = c.get("/conversation/suggestions")
    assert r1.status_code == 200, r1.text
    b1 = r1.json()
    assert b1["cached"] is False
    assert b1["trainable_moments"] and b1["project_proposals"] and b1["mint_suggestions"]
    assert all(m["draft"] is True for m in b1["trainable_moments"])

    r2 = c.get("/conversation/suggestions")
    assert r2.json()["cached"] is True
    assert r2.json()["trainable_moments"] == b1["trainable_moments"]

    # read-only: no messages added, nothing filed
    assert len(store.history("user-alice", "skeleton")) == before
