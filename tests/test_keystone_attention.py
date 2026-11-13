"""Living Tree keystone attention markers ("!").

Covers the marker-state rules (local_ai.vision_execution.keystone_seeding
.keystone_attention) and the read-only GET /vision-execution/keystone-attention
route:

- no initiative seeded → seeded=False, no markers, no error
- fresh account → ONLY the Guardian (entry seat), reason "intro"
- guardian's first keystone Done → the journey offers ONE seat at a
  time in JOURNEY_ORDER ("meet" on the next unfinished seat only);
  later seats stay dark until their predecessor's first keystone is
  Done (a mid-chain seat carries no marker — "meet" lights only
  while a seat's first keystone is undone)
- a seat with keystones 1–3 Done and 4 open → reason "recognition",
  independent of journey position and of the entry intro
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


def test_entry_seat_is_guardian():
    assert ENTRY == "guardian"


def test_exactly_one_entry_seat_flagged():
    flagged = [s["seat_ref"] for s in KD.SEATS if s.get("entry") == "true"]
    assert flagged == ["guardian"]


def test_entry_derivation_raises_on_zero_flags(monkeypatch):
    stripped = tuple({**s, "entry": "false"} if s.get("entry") else s for s in KD.SEATS)
    monkeypatch.setattr(KD, "SEATS", stripped)
    with pytest.raises(ValueError, match="no entry seat configured"):
        keystone_seeding._assert_single_entry_seat()


def test_entry_derivation_raises_on_two_flags(monkeypatch):
    doubled = tuple(
        {**s, "entry": "true"} if s["seat_ref"] in ("guardian", "conductor") else s
        for s in KD.SEATS
    )
    monkeypatch.setattr(KD, "SEATS", doubled)
    with pytest.raises(ValueError, match="multiple entry seats configured"):
        keystone_seeding._assert_single_entry_seat()


def test_no_initiative_no_markers(ve_ctx):
    user = _make_user()
    state = keystone_seeding.keystone_attention(user["id"])
    assert state["seeded"] is False
    assert set(state["markers"].keys()) == set(SEAT_REFS)
    assert _lit(state) == {}


def test_fresh_account_only_guardian_intro(ve_ctx):
    user = _make_user()
    _seed(user["id"])
    state = keystone_seeding.keystone_attention(user["id"])
    assert state["seeded"] is True
    assert _lit(state) == {"guardian": "intro"}


def test_guardian_intro_done_offers_one_at_a_time(ve_ctx):
    """One-at-a-time journey offering (O-I-6): after the Guardian's
    first keystone, ONLY the next seat in JOURNEY_ORDER lights
    ("meet"); completing each first keystone moves the marker to the
    next seat; later seats stay dark until then."""
    user = _make_user()
    _seed(user["id"])
    journey = list(KD.JOURNEY_ORDER)
    assert journey[0] == "guardian"
    for i, ref in enumerate(journey):
        _complete(user["id"], ref, 1)
        state = keystone_seeding.keystone_attention(user["id"])
        lit = _lit(state)
        if i + 1 < len(journey):
            assert lit == {journey[i + 1]: "meet"}, (ref, lit)
        else:
            # Every first keystone Done: no "meet" left to offer; each
            # seat is mid-chain and dark until its recognition stage.
            assert lit == {}, lit


def test_recognition_when_only_keystone_four_remains(ve_ctx):
    user = _make_user()
    _seed(user["id"])
    _complete(user["id"], "guardian", 1)
    _complete(user["id"], "mentor", 3)
    state = keystone_seeding.keystone_attention(user["id"])
    assert state["markers"]["mentor"] == {
        "attention": True,
        "reason": "recognition",
    }


def test_recognition_lights_while_entry_intro_undone(ve_ctx):
    """Recognition is independent of the entry intro (addendum §3.2):
    a recognition-stage seat lights even before the Guardian's first
    keystone is Done — the entry gate governs "meet" offering only."""
    user = _make_user()
    _seed(user["id"])
    _complete(user["id"], "mentor", 3)
    state = keystone_seeding.keystone_attention(user["id"])
    assert state["markers"]["mentor"]["reason"] == "recognition"
    assert state["markers"]["guardian"]["reason"] == "intro"


def test_guardian_recognition(ve_ctx):
    user = _make_user()
    _seed(user["id"])
    _complete(user["id"], "guardian", 3)
    state = keystone_seeding.keystone_attention(user["id"])
    assert state["markers"]["guardian"]["reason"] == "recognition"


def test_conductor_recognition_after_entry_done(ve_ctx):
    """The recognition rule itself, on the Conductor's chain: with the
    entry keystone Done and the conductor's 1–3 Done, the conductor
    carries "recognition" while the journey's "meet" offer has moved
    on to the champion."""
    user = _make_user()
    _seed(user["id"])
    _complete(user["id"], "guardian", 1)
    _complete(user["id"], "conductor", 3)
    state = keystone_seeding.keystone_attention(user["id"])
    assert state["markers"]["conductor"]["reason"] == "recognition"
    assert state["markers"]["champion"]["reason"] == "meet"


def test_completed_seat_has_no_marker(ve_ctx):
    user = _make_user()
    _seed(user["id"])
    _complete(user["id"], "guardian", 4)
    state = keystone_seeding.keystone_attention(user["id"])
    assert state["markers"]["guardian"] == {"attention": False, "reason": None}
    # And everything fully done → nothing lit at all.
    for ref in SEAT_REFS:
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
    assert _lit(out) == {"guardian": "intro"}


# ------------------------------------------------------------------ invitations
# (Capability C visible-UX slice: additive invitation fields on the
# keystone-attention route. The route must not disturb any pre-existing
# marker field, must not flip attention or reason for invitations, and
# must omit (not zero) the new fields when the invitation read fails.)

_NEW_FIELDS = ("invitation_count", "invitation_conversation_ids")


def _inv_store(tmp_path, monkeypatch):
    """Conversation store on an isolated DB, patched in as the class the
    route lazily imports (so the route's in-function import resolves it)."""
    import local_ai.conversation.store as store_mod
    from local_ai.conversation.store import ConversationStore

    store = ConversationStore(db_path=tmp_path / "inv.db")
    monkeypatch.setattr(store_mod, "ConversationStore", lambda *a, **k: store)
    return store


def _create_inv(store, user_id, conv, seat, reason="a reason"):
    return store.create_or_refresh_invitation(
        user_id,
        conv,
        seat,
        reason,
        evidence={"user_message": "hello", "assistant_reply": "hi"},
    )


def _strip_new(marker):
    return {k: v for k, v in marker.items() if k not in _NEW_FIELDS}


def test_invitation_fields_do_not_disturb_existing_markers(ve_ctx, tmp_path, monkeypatch):
    from api.routes.vision_execution import get_keystone_attention

    user = _make_user()
    store = _inv_store(tmp_path, monkeypatch)
    baseline = get_keystone_attention({"id": user["id"]})
    assert baseline["markers"]["guardian"]["invitation_count"] == 0
    assert baseline["markers"]["guardian"]["invitation_conversation_ids"] == []

    _create_inv(store, user["id"], "talk-1", "guardian")
    _create_inv(store, user["id"], "talk-2", "guardian")
    _create_inv(store, user["id"], "talk-1", "mentor")
    out = get_keystone_attention({"id": user["id"]})
    # Every pre-existing field, for every seat, byte-identical to baseline.
    for ref in SEAT_REFS:
        assert _strip_new(out["markers"][ref]) == _strip_new(baseline["markers"][ref]), ref
    assert out["seeded"] == baseline["seeded"]
    # New fields: count is invitations, ids most-recent-first, deduped.
    assert out["markers"]["guardian"]["invitation_count"] == 2
    assert out["markers"]["guardian"]["invitation_conversation_ids"] == ["talk-2", "talk-1"]
    assert out["markers"]["mentor"]["invitation_count"] == 1
    assert out["markers"]["mentor"]["invitation_conversation_ids"] == ["talk-1"]
    assert out["markers"]["conductor"]["invitation_count"] == 0
    assert out["markers"]["conductor"]["invitation_conversation_ids"] == []
    store.close()


def test_invitation_fields_dedup_duplicate_rows(ve_ctx, tmp_path, monkeypatch):
    """Defensive dedup: even if duplicate rows ever appear (contrary to
    refresh-not-stack), one entry per conversation is returned."""
    import json

    from api.routes.vision_execution import get_keystone_attention

    user = _make_user()
    store = _inv_store(tmp_path, monkeypatch)
    _create_inv(store, user["id"], "talk-1", "guardian")
    # Direct duplicate row (same user/conversation/seat, new id).
    store._conn.execute(
        "INSERT INTO invitations (id, user_id, conversation_id, seat, observation_ids,"
        " reason, evidence_json, status, created_at, expires_at, accepted_message_id)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, NULL)",
        (
            "dup-row-id",
            user["id"],
            "talk-1",
            "guardian",
            json.dumps([]),
            "dup reason",
            json.dumps({}),
            "2026-01-01T00:00:00+00:00",
            "2999-01-01T00:00:00+00:00",
        ),
    )
    store._conn.commit()
    out = get_keystone_attention({"id": user["id"]})
    assert out["markers"]["guardian"]["invitation_count"] == 2
    assert out["markers"]["guardian"]["invitation_conversation_ids"] == ["talk-1"]
    store.close()


def test_invitation_fields_are_per_user(ve_ctx, tmp_path, monkeypatch):
    from api.routes.vision_execution import get_keystone_attention

    u1 = _make_user("one@example.com")
    u2 = _make_user("two@example.com")
    store = _inv_store(tmp_path, monkeypatch)
    _create_inv(store, u1["id"], "talk-1", "guardian")
    out = get_keystone_attention({"id": u2["id"]})
    assert out["markers"]["guardian"]["invitation_count"] == 0
    assert out["markers"]["guardian"]["invitation_conversation_ids"] == []
    store.close()


def test_invitation_unknown_seat_creates_no_marker(ve_ctx, tmp_path, monkeypatch):
    from api.routes.vision_execution import get_keystone_attention

    user = _make_user()
    store = _inv_store(tmp_path, monkeypatch)
    _create_inv(store, user["id"], "talk-1", "not-a-seat")
    out = get_keystone_attention({"id": user["id"]})
    assert set(out["markers"].keys()) == set(SEAT_REFS)
    for ref in SEAT_REFS:
        assert out["markers"][ref]["invitation_count"] == 0
        assert out["markers"][ref]["invitation_conversation_ids"] == []
    store.close()


def test_invitation_read_failure_omits_fields(ve_ctx, tmp_path, monkeypatch):
    import local_ai.conversation.store as store_mod
    from api.routes.vision_execution import get_keystone_attention

    user = _make_user()
    _seed(user["id"])

    def _boom(*a, **k):
        raise RuntimeError("invitation read down")

    monkeypatch.setattr(store_mod, "ConversationStore", _boom)
    out = get_keystone_attention({"id": user["id"]})
    # Unavailable data is never rendered as authoritative empty: the
    # fields are absent, while everything else is intact.
    for ref in SEAT_REFS:
        assert "invitation_count" not in out["markers"][ref]
        assert "invitation_conversation_ids" not in out["markers"][ref]
    assert _lit(out) == {"guardian": "intro"}


def test_obligation_merge_unchanged_with_invitations(ve_ctx, tmp_path, monkeypatch):
    import local_ai.vision_execution.obligations as obligations_mod
    from api.routes.vision_execution import get_keystone_attention

    user = _make_user()
    store = _inv_store(tmp_path, monkeypatch)
    _create_inv(store, user["id"], "talk-1", "guardian")
    monkeypatch.setattr(
        obligations_mod,
        "obligation_attention",
        lambda user_id: {
            "obligation_status": "ok",
            "overdue_count": 1,
            "due_soon_count": 2,
            "next_due": "2026-11-20",
        },
    )
    out = get_keystone_attention({"id": user["id"]})
    champ = out["markers"]["champion"]
    # Obligation merge behaves exactly as before (counts, reason
    # fallback only when reason empty), alongside invitation fields.
    assert champ["obligation_status"] == "ok"
    assert champ["overdue_count"] == 1
    assert champ["due_soon_count"] == 2
    assert champ["next_due"] == "2026-11-20"
    assert champ["attention"] is True
    assert champ["reason"] == "obligation"
    assert out["markers"]["guardian"]["invitation_count"] == 1
    store.close()


def test_obligation_unknown_still_omits_with_invitations(ve_ctx, tmp_path, monkeypatch):
    import local_ai.vision_execution.obligations as obligations_mod
    from api.routes.vision_execution import get_keystone_attention

    user = _make_user()
    store = _inv_store(tmp_path, monkeypatch)
    _create_inv(store, user["id"], "talk-1", "guardian")

    def _boom(user_id):
        raise RuntimeError("obligation read down")

    monkeypatch.setattr(obligations_mod, "obligation_attention", _boom)
    out = get_keystone_attention({"id": user["id"]})
    champ = out["markers"]["champion"]
    assert champ["obligation_status"] == "unknown"
    assert "overdue_count" not in champ
    assert "due_soon_count" not in champ
    assert "next_due" not in champ
    assert out["markers"]["guardian"]["invitation_count"] == 1
    store.close()
