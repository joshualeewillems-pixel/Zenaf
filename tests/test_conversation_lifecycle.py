"""Talk conversation lifecycle tests (founder, 2026-11-12).

Route/store coverage for the "+" flow's backend: the conversations
row's archived/symbol/color fields, list exclusion + the
include_archived opt-in, the disposition endpoint, the real delete's
cascade, owner isolation, and the meeting refusal. The LLM is faked;
the store uses a tmp SQLite file. #368's tests
(test_durable_tree_talk.py) are untouched and must keep passing.
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
MEETING_MENTOR = "meeting-mentor-1"


def _fake_generate(prompt: str, **kwargs) -> str:
    return "Fake reply."


def _make_client(tmp_path, monkeypatch, user):
    store = ConversationStore(db_path=tmp_path / "conv.db")
    svc = ConversationService(store, generate_fn=_fake_generate)
    monkeypatch.setattr(conv_routes, "_store", lambda: store)
    monkeypatch.setattr(conv_routes, "_service", lambda: svc)
    monkeypatch.setattr(reply_mod, "_default_generate", _fake_generate)
    app = FastAPI()
    app.include_router(conv_routes.router)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), store


@pytest.fixture()
def client(tmp_path, monkeypatch):
    c, store = _make_client(tmp_path, monkeypatch, ALICE)
    yield c, store
    store.close()


def _turn(c, cid, seat, text):
    r = c.post(
        "/conversation/turn",
        json={"conversation_id": cid, "archetype_id": seat, "message": text},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _list(c, **params):
    r = c.get("/conversation/list", params=params)
    assert r.status_code == 200, r.text
    return r.json()["conversations"]


def _disposition(c, cid, action, symbol=None, color=None):
    body = {"conversation_id": cid, "action": action}
    if symbol is not None:
        body["symbol"] = symbol
    if color is not None:
        body["color"] = color
    return c.post("/conversation/disposition", json=body)


def _seed_meeting(store, user_id, cid=MEETING_MENTOR, seat="mentor"):
    """A meeting conversation the way MeetingService leaves it: the
    conversation row ensured with kind='meeting', messages from both
    roles carrying the seat's archetype id.

    Non-destructive Meet Again (Slice 1): the messages are written
    through the meeting path — ensured first (which creates the
    fence), then appended with via_meeting=True, exactly as the
    meeting engine writes. The strict S1 fence refuses ordinary
    writes to reserved meeting ids; the tests using this helper
    exercise meeting behavior, so the fixture seeds through the
    authorized path rather than forcing a weaker contract (founder
    ruling, 2026-11-13: tests adapt to a justified safety
    invariant)."""
    store.ensure_conversation(user_id, cid, kind="meeting")
    store.append_message(user_id, cid, seat, "user", "meeting hello",
                         via_meeting=True)
    store.append_message(user_id, cid, seat, "voice", "meeting reply",
                         via_meeting=True)


def test_archive_excludes_by_default_and_surfaces_with_opt_in(client):
    """Archive for data: out of every default list (general + seat),
    still stored, and listed — flagged — when include_archived=true."""
    c, store = client
    _turn(c, TALK_A, "mentor", "A one")
    _turn(c, TALK_B, "mentor", "B one")

    r = _disposition(c, TALK_A, "archive", symbol=7, color="#b5533c")
    assert r.status_code == 200, r.text
    row = r.json()["conversation"]
    assert row["archived"] is True
    assert row["symbol"] == 7 and row["color"] == "#b5533c"

    # Default lists: the archived talk is gone everywhere.
    assert [x["conversation_id"] for x in _list(c)] == [TALK_B]
    assert [x["conversation_id"] for x in _list(c, seat="mentor")] == [TALK_B]
    # The seat resume lookup resolves the remaining talk.
    assert [
        x["conversation_id"] for x in _list(c, seat="mentor", limit=1)
    ] == [TALK_B]

    # Opt-in: both appear; the archived one is flagged, with identity.
    convs = _list(c, include_archived=True)
    by_id = {x["conversation_id"]: x for x in convs}
    assert set(by_id) == {TALK_A, TALK_B}
    assert by_id[TALK_A]["archived"] is True
    assert by_id[TALK_A]["symbol"] == 7 and by_id[TALK_A]["color"] == "#b5533c"
    assert by_id[TALK_B]["archived"] is False
    # Nothing was deleted: the archived thread still hydrates.
    r = c.get("/conversation", params={"conversation_id": TALK_A})
    assert r.json()["total"] == 2


def test_identity_round_trip_and_defaults(client):
    """Keep open writes symbol+color only; an untouched conversation
    lists with the lifecycle fields at their defaults."""
    c, _ = client
    _turn(c, TALK_A, "mentor", "A one")
    _turn(c, TALK_B, "champion", "B one")

    plain = {x["conversation_id"]: x for x in _list(c)}
    assert plain[TALK_B]["archived"] is False
    assert plain[TALK_B]["symbol"] is None and plain[TALK_B]["color"] is None

    r = _disposition(c, TALK_A, "keep_open", symbol=3, color="#4a7fb5")
    assert r.status_code == 200, r.text
    assert r.json()["conversation"]["archived"] is False

    after = {x["conversation_id"]: x for x in _list(c)}
    assert after[TALK_A]["symbol"] == 3 and after[TALK_A]["color"] == "#4a7fb5"
    assert after[TALK_A]["archived"] is False
    # Keep open changes nothing about queue membership.
    assert set(after) == {TALK_A, TALK_B}


def test_disposition_and_delete_are_owner_scoped(tmp_path, monkeypatch):
    """Another user cannot disposition or delete the owner's talk:
    delete 404s under their id, and a disposition under their id
    writes only their own (empty) row — the owner's data is intact."""
    alice, store = _make_client(tmp_path, monkeypatch, ALICE)
    _turn(alice, TALK_A, "mentor", "A one")
    bob, _ = _make_client(tmp_path, monkeypatch, BOB)

    r = bob.delete(f"/conversation/{TALK_A}")
    assert r.status_code == 404, r.text

    r = _disposition(bob, TALK_A, "archive", symbol=9, color="#000000")
    assert r.status_code == 200, r.text  # writes Bob's own row only
    # Alice's conversation is untouched: unarchived, no identity, listed.
    convs = _list(alice)
    assert [x["conversation_id"] for x in convs] == [TALK_A]
    assert convs[0]["archived"] is False and convs[0]["symbol"] is None
    assert store.count_messages("user-alice", TALK_A) == 2
    # And Bob's phantom row lists nothing (he has no messages there).
    assert _list(bob, include_archived=True) == []
    store.close()


def test_delete_cascades_conversation_store(client):
    """Delete all system references: row, messages, thread state,
    suggestion runs, invitations (deleted, not expired), and parked
    round items are all gone; a second delete 404s."""
    c, store = client
    _turn(c, TALK_A, "mentor", "A one")
    store.update_thread_state("user-alice", TALK_A, "mentor", summary="seeded")
    store.save_suggestion_run(
        "user-alice", TALK_A, "m-any", {"suggestions": []}
    )
    store.create_or_refresh_invitation(
        "user-alice", TALK_A, "champion", "a reason"
    )
    store.park_round_item("user-alice", TALK_A, "weave", "item-1")

    r = c.delete(f"/conversation/{TALK_A}")
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] is True

    assert store.get_conversation("user-alice", TALK_A) is None
    assert store.count_messages("user-alice", TALK_A) == 0
    assert store.history("user-alice", TALK_A) == []
    state = store.get_thread_state("user-alice", TALK_A, "mentor")
    assert state["summary"] == "" and state["last_active"] == ""
    assert store.get_suggestion_run("user-alice", TALK_A) is None
    assert store.list_pending_invitations("user-alice", TALK_A) == []
    assert store.list_parked_round_items("user-alice", TALK_A, "weave") == []
    with store._lock:
        inv_count = store._conn.execute(
            "SELECT COUNT(*) FROM invitations WHERE user_id = ? AND conversation_id = ?",
            ("user-alice", TALK_A),
        ).fetchone()[0]
    assert inv_count == 0  # deleted outright, not expired
    assert _list(c, include_archived=True, include_meetings=True) == []

    r = c.delete(f"/conversation/{TALK_A}")
    assert r.status_code == 404, r.text


def test_meetings_refuse_disposition_and_delete(client):
    """Meetings are not dispositionable: disposition and delete both
    refuse cleanly (422), and the meeting is entirely untouched."""
    c, store = client
    _seed_meeting(store, "user-alice")

    r = _disposition(c, MEETING_MENTOR, "archive", symbol=1, color="#ffffff")
    assert r.status_code == 422, r.text
    r = _disposition(c, MEETING_MENTOR, "keep_open", symbol=1, color="#ffffff")
    assert r.status_code == 422, r.text
    r = c.delete(f"/conversation/{MEETING_MENTOR}")
    assert r.status_code == 422, r.text

    convs = _list(c, include_meetings=True)
    assert [x["conversation_id"] for x in convs] == [MEETING_MENTOR]
    assert convs[0]["archived"] is False and convs[0]["symbol"] is None
    assert store.count_messages("user-alice", MEETING_MENTOR) == 2


def test_disposition_rejects_unknown_action_and_bad_symbol(client):
    c, _ = client
    _turn(c, TALK_A, "mentor", "A one")
    r = _disposition(c, TALK_A, "shred")
    assert r.status_code == 422, r.text
    r = _disposition(c, TALK_A, "archive", symbol=25)
    assert r.status_code == 422, r.text
    # Neither attempt wrote anything.
    convs = _list(c)
    assert convs[0]["archived"] is False and convs[0]["symbol"] is None
