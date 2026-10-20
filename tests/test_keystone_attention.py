"""Living Tree keystone attention markers ("!").

Covers the marker-state rules (local_ai.vision_execution.keystone_seeding
.keystone_attention) and the read-only GET /vision-execution/keystone-attention
route:

- no initiative seeded → seeded=False, no markers, no error
- fresh account → ONLY the Conductor (entry seat), reason "intro"
- conductor's first keystone Done → the other six light up ("meet"),
  conductor itself becomes "meet" (mid-chain)
- a seat with keystones 1–3 Done and 4 open → reason "recognition"
- a seat with all four Done → no marker
- per-user isolation

Runs against a real temp SQLite DB (same fixture pattern as test_keystones).
"""
from __future__ import annotations

import threading

import pytest

from local_ai.council import keystones as KD
from local_ai.vision_execution import keystone_seeding
from local_ai.vision_execution import models as M
from local_ai.vision_execution import service as ve

SEAT_REFS = [s["seat_ref"] for s in KD.SEATS]
ENTRY = keystone_seeding.ENTRY_SEAT_REF


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    """Isolate the VE SQLite DB per test."""
    import local_ai.vision_execution.storage as ve_store

    ve_db = tmp_path / "ve.db"
    monkeypatch.setattr(ve_store, "_DB_PATH", ve_db)
    monkeypatch.setattr(ve_store, "_DB_DIR", tmp_path)
    monkeypatch.setattr(ve_store, "_init_done_paths", set())
    monkeypatch.setattr(ve_store, "_thread_local", threading.local())
    return {}


def _make_user(email="ally@example.com"):
    return ve.create_user_account(email, "pw-hunter2", "Ally")


def _seed(user_id):
    keystone_seeding.seed_meet_your_council(user_id)


def _seat_tasks(user_id, seat_ref):
    """The seat's 4 keystone tasks, ordered 1→2→3→4."""
    tasks = [t for t in ve.list_tasks(user_id) if t.get("seat_ref") == seat_ref]
    return keystone_seeding._chain_order(tasks)


def _complete(user_id, seat_ref, count):
    """Mark the seat's first `count` keystones Done."""
    for task in _seat_tasks(user_id, seat_ref)[:count]:
        ve.update_task(task["id"], M.TaskUpdate(status="Done"), user_id)


def _lit(state):
    """{seat_ref: reason} for seats whose marker is lit."""
    return {
        ref: m["reason"]
        for ref, m in state["markers"].items()
        if m["attention"]
    }


# ------------------------------------------------------------------ rules


def test_entry_seat_is_conductor():
    assert ENTRY == "conductor"


def test_no_initiative_no_markers(ve_ctx):
    user = _make_user()
    state = keystone_seeding.keystone_attention(user["id"])
    assert state["seeded"] is False
    assert set(state["markers"].keys()) == set(SEAT_REFS)
    assert _lit(state) == {}


def test_fresh_account_only_conductor_intro(ve_ctx):
    user = _make_user()
    _seed(user["id"])
    state = keystone_seeding.keystone_attention(user["id"])
    assert state["seeded"] is True
    assert _lit(state) == {"conductor": "intro"}


def test_conductor_intro_done_lights_the_rest(ve_ctx):
    user = _make_user()
    _seed(user["id"])
    _complete(user["id"], "conductor", 1)
    state = keystone_seeding.keystone_attention(user["id"])
    lit = _lit(state)
    # The other six now carry "meet"; the conductor is mid-chain → "meet".
    for ref in SEAT_REFS:
        assert lit[ref] == "meet", ref
    assert len(lit) == 7


def test_recognition_when_only_keystone_four_remains(ve_ctx):
    user = _make_user()
    _seed(user["id"])
    _complete(user["id"], "conductor", 1)
    _complete(user["id"], "mentor", 3)
    state = keystone_seeding.keystone_attention(user["id"])
    assert state["markers"]["mentor"] == {
        "attention": True,
        "reason": "recognition",
    }


def test_conductor_recognition(ve_ctx):
    user = _make_user()
    _seed(user["id"])
    _complete(user["id"], "conductor", 3)
    state = keystone_seeding.keystone_attention(user["id"])
    assert state["markers"]["conductor"]["reason"] == "recognition"


def test_completed_seat_has_no_marker(ve_ctx):
    user = _make_user()
    _seed(user["id"])
    _complete(user["id"], "conductor", 1)
    _complete(user["id"], "guardian", 4)
    state = keystone_seeding.keystone_attention(user["id"])
    assert state["markers"]["guardian"] == {"attention": False, "reason": None}
    # And everything fully done → nothing lit at all.
    _complete(user["id"], "conductor", 4)
    for ref in ("mentor", "champion", "ambassador", "skeptic", "maverick"):
        _complete(user["id"], ref, 4)
    state = keystone_seeding.keystone_attention(user["id"])
    assert _lit(state) == {}


def test_attention_is_per_user(ve_ctx):
    u1 = _make_user("one@example.com")
    u2 = _make_user("two@example.com")
    _seed(u1["id"])
    state2 = keystone_seeding.keystone_attention(u2["id"])
    assert state2["seeded"] is False
    assert _lit(state2) == {}


# ------------------------------------------------------------------ route


def test_route_returns_state(ve_ctx):
    from api.routes.vision_execution import get_keystone_attention

    user = _make_user()
    out = get_keystone_attention({"id": user["id"]})
    assert out["seeded"] is False
    assert _lit(out) == {}

    _seed(user["id"])
    out = get_keystone_attention({"id": user["id"]})
    assert out["seeded"] is True
    assert _lit(out) == {"conductor": "intro"}
