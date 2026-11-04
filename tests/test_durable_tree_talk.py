"""Durable Tree Talk Slice A tests (TestClient; run in CI).

Route/store-level coverage for GET /conversation/list, the extended
GET /conversation (total + before cursor), and talk- identity rules.
The LLM is faked; the store uses a tmp SQLite file. No real provider
calls, no training data written.

Plan tests: T1 identity isolation, T2 persistence across instances,
T3 skeleton/meetings untouched, T4 no silent shared default, T5 list
contents + scoping, T6 reopening round-trip, T7 windowing + cursor
stability. T8/T10 are frontend vitest tests; T9 is manual staging
acceptance (separately authorized, not automated here).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.routes.conversation_routes as conv_routes
from api.routes.auth_routes import get_current_user
import local_ai.conversation.reply as reply_mod
from local_ai.conversation.service import ConversationService
from local_ai.conversation.store import ConversationStore

ALICE = {"id": "user-alice", "email": "alice@x", "display_name": "Alice"}
BOB = {"id": "user-bob", "email": "bob@x", "display_name": "Bob"}

TALK_A = "talk-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
TALK_B = "talk-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def _fake_generate(prompt: str, **kwargs) -> str:
    return "Fake reply."


def _store(tmp_path) -> ConversationStore:
    return ConversationStore(db_path=tmp_path / "conv.db")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = _store(tmp_path)
    svc = ConversationService(store, generate_fn=_fake_generate)
    monkeypatch.setattr(conv_routes, "_store", lambda: store)
    monkeypatch.setattr(conv_routes, "_service", lambda: svc)
    monkeypatch.setattr(reply_mod, "_default_generate", _fake_generate)
    app = FastAPI()
    app.include_router(conv_routes.router)
    app.dependency_overrides[get_current_user] = lambda: ALICE
    c = TestClient(app)
    yield c, store
    store.close()


def _turn(c, cid, seat, text):
    r = c.post(
        "/conversation/turn",
        json={"conversation_id": cid, "archetype_id": seat, "message": text},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _hydrate(c, cid, **params):
    r = c.get("/conversation", params={"conversation_id": cid, **params})
    assert r.status_code == 200, r.text
    return r.json()


def test_t1_identity_isolation(client):
    """Two talk- threads, interleaved sends: neither leaks into the other."""
    c, _ = client
    _turn(c, TALK_A, "mentor", "A one")
    _turn(c, TALK_B, "champion", "B one")
    _turn(c, TALK_A, "mentor", "A two")
    _turn(c, TALK_B, "champion", "B two")
    a = _hydrate(c, TALK_A)
    b = _hydrate(c, TALK_B)
    assert [m["body"] for m in a["messages"]] == [
        "A one", "Fake reply.", "A two", "Fake reply.",
    ]
    assert [m["body"] for m in b["messages"]] == [
        "B one", "Fake reply.", "B two", "Fake reply.",
    ]
    assert a["total"] == 4 and b["total"] == 4
    assert all(m["conversation_id"] == TALK_A for m in a["messages"])
    assert all(m["conversation_id"] == TALK_B for m in b["messages"])


def test_t2_persistence_across_instances(tmp_path):
    """Messages survive closing and reopening the store on the same file."""
    path = tmp_path / "conv.db"
    s = ConversationStore(db_path=path)
    svc = ConversationService(s, generate_fn=_fake_generate)
    svc.turn("u1", "mentor", "remember this", conversation_id=TALK_A)
    before = s.history("u1", TALK_A)
    s.close()
    s2 = ConversationStore(db_path=path)
    after = s2.history("u1", TALK_A)
    assert [(m["body"], m["role"]) for m in after] == [
        (m["body"], m["role"]) for m in before
    ]
    assert len(after) == 2
    s2.close()


def test_t3_skeleton_and_meetings_untouched(client):
    """Talk sends leave the skeleton thread and meeting rows alone."""
    c, store = client
    _turn(c, "skeleton", "mentor", "skeleton msg")
    before = _hydrate(c, "skeleton")
    _turn(c, TALK_A, "mentor", "talk msg")
    _turn(c, "meeting-mentor-1", "mentor", "meeting msg")
    after = _hydrate(c, "skeleton")
    assert [m["body"] for m in after["messages"]] == [
        m["body"] for m in before["messages"]
    ]
    assert after["total"] == before["total"] == 2
    # Talk sends created no meeting-* rows beyond the one meeting turn.
    rows = store._conn.execute(
        "SELECT DISTINCT conversation_id FROM messages "
        "WHERE conversation_id LIKE 'meeting-%'"
    ).fetchall()
    assert [r[0] for r in rows] == ["meeting-mentor-1"]


def test_t4_no_silent_shared_default(client):
    """A talk- send never lands in skeleton; blank ids keep old behavior."""
    c, store = client
    _turn(c, TALK_A, "mentor", "talk msg")
    assert store.count_messages("user-alice", "skeleton") == 0
    r = c.post(
        "/conversation/turn",
        json={"conversation_id": "", "archetype_id": "mentor", "message": "blank"},
    )
    assert r.status_code == 200
    assert r.json()["conversation_id"] == "skeleton"
    assert store.count_messages("user-alice", "skeleton") == 2


def test_t5_list_contents_and_scoping(client):
    """List returns only the caller's talks with messages, newest first."""
    c, store = client
    store.append_message("user-alice", TALK_A, "mentor", "user", "a1")
    store.append_message("user-alice", TALK_A, "mentor", "voice", "a2")
    store.append_message("user-alice", TALK_A, "champion", "user", "a3")
    store.append_message("user-alice", TALK_B, "champion", "user", "b1")
    store.append_message("user-alice", "skeleton", "mentor", "user", "sk")
    store.append_message("user-alice", "meeting-mentor-1", "mentor", "user", "mt")
    store.append_message("user-bob", "talk-cccccccccccccccccccccccccccccccc", "mentor", "user", "bob")
    store.ensure_conversation("user-alice", "talk-eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee")
    r = c.get("/conversation/list")
    assert r.status_code == 200, r.text
    convs = r.json()["conversations"]
    ids = [x["conversation_id"] for x in convs]
    assert set(ids) == {TALK_A, TALK_B}
    # Ordered by latest message time, never increasing down the list.
    times = [x["last_message_at"] for x in convs]
    assert times == sorted(times, reverse=True)
    by_id = {x["conversation_id"]: x for x in convs}
    assert by_id[TALK_A]["message_count"] == 3
    assert by_id[TALK_A]["seats"] == ["mentor", "champion"]
    assert by_id[TALK_A]["last_message_preview"] == "a3"
    assert by_id[TALK_B]["message_count"] == 1
    r = c.get("/conversation/list", params={"limit": 1})
    assert len(r.json()["conversations"]) == 1


def test_t5_list_ordering_uses_message_time_not_updated_at(client):
    """Hydrating an older talk must not promote it above a newer talk.

    conversations.updated_at is refreshed by ensure_conversation on
    every read, so it records last touch, not last message. List
    ordering must follow latest message time instead.
    """
    c, store = client
    store.append_message("user-alice", TALK_A, "mentor", "user", "older talk")
    store.append_message("user-alice", TALK_B, "mentor", "user", "newer talk")
    # Touch the older talk last (a hydration read bumps updated_at).
    _hydrate(c, TALK_A)
    r = c.get("/conversation/list")
    ids = [x["conversation_id"] for x in r.json()["conversations"]]
    assert ids == [TALK_B, TALK_A]


def test_t5_list_requires_auth(tmp_path, monkeypatch):
    store = _store(tmp_path)
    monkeypatch.setattr(conv_routes, "_store", lambda: store)
    app = FastAPI()
    app.include_router(conv_routes.router)
    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/conversation/list")
    assert r.status_code == 401
    store.close()


def test_t6_reopening_round_trip(client):
    """List -> hydrate returns the same thread, bodies, order, seat tags."""
    c, _ = client
    _turn(c, TALK_A, "mentor", "round trip")
    _turn(c, TALK_A, "champion", "second seat")
    r = c.get("/conversation/list")
    cid = r.json()["conversations"][0]["conversation_id"]
    assert cid == TALK_A
    data = _hydrate(c, cid)
    assert [m["body"] for m in data["messages"]] == [
        "round trip", "Fake reply.", "second seat", "Fake reply.",
    ]
    assert [m["archetype_id"] for m in data["messages"]] == [
        "mentor", "mentor", "champion", "champion",
    ]


def test_t7_windowing_and_cursor_stability(client):
    """250-message thread: latest 200 + total, cursor page of earlier 50,
    and new arrivals never shift, duplicate, or skip cursor pages."""
    c, store = client
    for i in range(250):
        store.append_message("user-alice", TALK_A, "mentor", "user", f"m{i}")
    page1 = _hydrate(c, TALK_A, limit=200)
    assert page1["total"] == 250
    assert len(page1["messages"]) == 200
    assert page1["messages"][0]["body"] == "m50"
    assert page1["messages"][-1]["body"] == "m249"
    cursor = page1["messages"][0]["id"]
    page2 = _hydrate(c, TALK_A, limit=200, before=cursor)
    assert [m["body"] for m in page2["messages"]] == [f"m{i}" for i in range(50)]
    assert page2["total"] == 250
    combined = [m["body"] for m in page2["messages"]] + [
        m["body"] for m in page1["messages"]
    ]
    assert combined == [f"m{i}" for i in range(250)]
    # New arrivals after the snapshot leave the cursor page unchanged.
    for i in range(250, 255):
        store.append_message("user-alice", TALK_A, "mentor", "user", f"m{i}")
    page2b = _hydrate(c, TALK_A, limit=200, before=cursor)
    assert [m["body"] for m in page2b["messages"]] == [f"m{i}" for i in range(50)]
    assert page2b["total"] == 255
    # Unknown and cross-user cursors fail closed to an empty page.
    assert _hydrate(c, TALK_A, before="no-such-id")["messages"] == []
    store.append_message("user-bob", TALK_B, "mentor", "user", "bob msg")
    bob_id = store.history("user-bob", TALK_B)[0]["id"]
    assert _hydrate(c, TALK_A, before=bob_id)["messages"] == []


def test_t7_unknown_conversation_hydrates_empty_and_keeps_ensure(client):
    """Unknown IDs still ensure-on-read (unchanged behavior, C1b)."""
    c, store = client
    data = _hydrate(c, "talk-ffffffffffffffffffffffffffffffff")
    assert data["messages"] == [] and data["total"] == 0
    row = store._conn.execute(
        "SELECT conversation_id FROM conversations "
        "WHERE user_id = ? AND conversation_id = ?",
        ("user-alice", "talk-ffffffffffffffffffffffffffffffff"),
    ).fetchone()
    assert row is not None
