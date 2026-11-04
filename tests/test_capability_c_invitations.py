"""Capability C S1 tests: invitation records + lifecycle.

Rules pinned here (verdict Q2/Q3/Q8 + lifecycle corrections):
  - one pending invitation per (conversation, seat): refresh-not-stack;
  - per-user scoping on EVERY read (foreign ids return nothing);
  - TTL 7 days provisional, as a cleanup BACKSTOP, not relevance;
  - evidence-specific invalidation expires early (never on topic
    change or on talking to another seat — that rule lives in the
    caller, but the hook here is expiry, not a new status);
  - NO dismiss status in v1: untapped = pending/deferred;
  - accepted ONLY via a sent turn to the invited seat (the turn path
    records it); tap/opening alone NEVER accepts — there is no store
    method that accepts on open, and reads never transition;
  - invitation and observation lifecycles are INDEPENDENT: nothing
    here touches observation state (no observation store is even
    imported by these tests).

No model calls, no network: ConversationStore on tmp_path, and the
service tests use a fake generate_fn.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from local_ai.conversation.service import ConversationService
from local_ai.conversation.store import ConversationStore


def _fake_generate(prompt: str, **kwargs) -> str:
    return "Fake reply."


def _store(tmp_path) -> ConversationStore:
    return ConversationStore(db_path=tmp_path / "inv.db")


def _evidence() -> dict:
    return {
        "user_message": "Staging trial test.",
        "responding_seat": "champion",
        "assistant_reply": "That's no hill.",
        "context": [],
    }


def _future(days: float = 8.0) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _create(store, user="u1", conv="talk-1", seat="guardian", reason="hand to offer"):
    return store.create_or_refresh_invitation(
        user, conv, seat, reason, evidence=_evidence()
    )


# -- create / list / get -------------------------------------------------------


def test_create_fields_and_backstop_ttl(tmp_path):
    store = _store(tmp_path)
    inv = _create(store)
    assert inv["status"] == "pending"
    assert inv["seat"] == "guardian"
    assert inv["reason"] == "hand to offer"
    assert inv["evidence"] == _evidence()
    assert inv["observation_ids"] == []
    assert inv["accepted_message_id"] is None
    created = datetime.fromisoformat(inv["created_at"])
    expires = datetime.fromisoformat(inv["expires_at"])
    delta = expires - created
    assert timedelta(days=6, hours=23) < delta < timedelta(days=7, hours=1)
    store.close()


def test_list_pending_scoped_by_user_and_conversation(tmp_path):
    store = _store(tmp_path)
    _create(store, user="u1", conv="talk-1", seat="guardian")
    _create(store, user="u1", conv="talk-1", seat="conductor")
    _create(store, user="u1", conv="talk-2", seat="guardian")
    _create(store, user="u2", conv="talk-1", seat="guardian")
    assert len(store.list_pending_invitations("u1")) == 3
    assert len(store.list_pending_invitations("u1", "talk-1")) == 2
    assert len(store.list_pending_invitations("u2")) == 1
    assert store.list_pending_invitations("u1", "talk-unknown") == []
    store.close()


def test_get_is_per_user(tmp_path):
    store = _store(tmp_path)
    inv = _create(store)
    assert store.get_invitation("u1", inv["id"])["id"] == inv["id"]
    assert store.get_invitation("u2", inv["id"]) is None
    assert store.get_invitation("u1", "missing-id") is None
    store.close()


def test_create_rejects_empty_fields(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        store.create_or_refresh_invitation("", "talk-1", "guardian", "r")
    with pytest.raises(ValueError):
        store.create_or_refresh_invitation("u1", "talk-1", "guardian", "   ")
    store.close()


# -- refresh-not-stack ----------------------------------------------------------


def test_refresh_does_not_stack(tmp_path):
    store = _store(tmp_path)
    first = _create(store, reason="first reason")
    second = store.create_or_refresh_invitation(
        "u1", "talk-1", "guardian", "stronger reason", evidence=_evidence()
    )
    assert second["id"] == first["id"]
    assert second["reason"] == "stronger reason"
    assert len(store.list_pending_invitations("u1", "talk-1")) == 1
    store.close()


def test_expired_row_is_not_revived(tmp_path):
    store = _store(tmp_path)
    first = _create(store)
    assert store.expire_due_invitations("u1", now=_future()) == 1
    second = _create(store, reason="fresh reason")
    assert second["id"] != first["id"]
    assert store.get_invitation("u1", first["id"])["status"] == "expired"
    assert len(store.list_pending_invitations("u1", "talk-1")) == 1
    store.close()


# -- accept ---------------------------------------------------------------------


def test_accept_flow_and_no_overwrite(tmp_path):
    store = _store(tmp_path)
    inv = _create(store)
    accepted = store.accept_invitation("u1", inv["id"], "msg-1")
    assert accepted is not None
    assert accepted["status"] == "accepted"
    assert accepted["accepted_message_id"] == "msg-1"
    # A second accept is a no-op, not an overwrite.
    assert store.accept_invitation("u1", inv["id"], "msg-2") is None
    assert store.get_invitation("u1", inv["id"])["accepted_message_id"] == "msg-1"
    store.close()


def test_accept_rejects_foreign_missing_expired(tmp_path):
    store = _store(tmp_path)
    inv = _create(store)
    assert store.accept_invitation("u2", inv["id"], "msg-1") is None
    assert store.accept_invitation("u1", "missing-id", "msg-1") is None
    assert store.expire_due_invitations("u1", now=_future()) == 1
    assert store.accept_invitation("u1", inv["id"], "msg-1") is None
    store.close()


# -- expiry + invalidation ------------------------------------------------------


def test_expire_sweep(tmp_path):
    store = _store(tmp_path)
    _create(store, seat="guardian")
    _create(store, seat="conductor")
    assert store.expire_due_invitations("u1") == 0
    assert len(store.list_pending_invitations("u1")) == 2
    assert store.expire_due_invitations("u1", now=_future()) == 2
    assert store.list_pending_invitations("u1") == []
    store.close()


def test_list_hides_unswept_past_expiry_rows(tmp_path):
    """The time filter is the semantic gate; the sweep is bookkeeping.
    A past-expiry row is not pending even before any sweep runs."""
    store = _store(tmp_path)
    inv = _create(store)
    assert store.list_pending_invitations("u1", now=_future()) == []
    # ...while the stored status is still 'pending' until swept.
    assert store.get_invitation("u1", inv["id"])["status"] == "pending"
    store.close()


def test_invalidate_is_expiry_not_a_new_status(tmp_path):
    store = _store(tmp_path)
    inv = _create(store)
    out = store.invalidate_invitation("u1", inv["id"])
    assert out is not None
    assert out["status"] == "expired"
    assert store.list_pending_invitations("u1") == []
    # Non-pending and foreign rows: no-op.
    assert store.invalidate_invitation("u1", inv["id"]) is None
    other = _create(store, seat="conductor")
    assert store.invalidate_invitation("u2", other["id"]) is None
    store.close()


# -- accept is a sent turn, never a tap ------------------------------------------


def test_open_does_not_accept(tmp_path):
    """Opening is a UI action with no transition in this layer: there
    is no store method that accepts on open, and reads never
    transition. An invitation left alone stays pending."""
    store = _store(tmp_path)
    inv = _create(store)
    # Read it repeatedly, as an open conversation view would.
    assert store.get_invitation("u1", inv["id"])["status"] == "pending"
    assert len(store.list_pending_invitations("u1", "talk-1")) == 1
    assert store.get_invitation("u1", inv["id"])["status"] == "pending"
    store.close()


def test_turn_to_invited_seat_accepts(tmp_path):
    store = _store(tmp_path)
    inv = _create(store)
    svc = ConversationService(store, generate_fn=_fake_generate)
    result = svc.turn("u1", "guardian", "hello there", conversation_id="talk-1")
    after = store.get_invitation("u1", inv["id"])
    assert after["status"] == "accepted"
    assert after["accepted_message_id"] == result.user_message["id"]
    store.close()


def test_turn_to_other_seat_leaves_invitation_pending(tmp_path):
    store = _store(tmp_path)
    inv = _create(store)
    svc = ConversationService(store, generate_fn=_fake_generate)
    svc.turn("u1", "mentor", "hello there", conversation_id="talk-1")
    assert store.get_invitation("u1", inv["id"])["status"] == "pending"
    store.close()


def test_turn_does_not_accept_expired_invitation(tmp_path):
    store = _store(tmp_path)
    inv = _create(store)
    assert store.expire_due_invitations("u1", now=_future()) == 1
    svc = ConversationService(store, generate_fn=_fake_generate)
    svc.turn("u1", "guardian", "hello there", conversation_id="talk-1")
    after = store.get_invitation("u1", inv["id"])
    assert after["status"] == "expired"
    assert after["accepted_message_id"] is None
    store.close()
