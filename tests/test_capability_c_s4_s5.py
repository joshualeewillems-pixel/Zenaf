"""Capability C S4 + S5 tests: read surfaces and tap-to-open / join turns.

S4 — pending invitations for a conversation must be readable:
per-user scoped, reads never consume (tapping OPENS, it does not
accept), and a cleared conversation yields nothing actionable
(clear-expire landed in S1; this pins the read side of it).

S5 — the first joining turn carries the invitation's bounded
evidence + attributed reason; later turns are normal continuity;
the 10-turn window is NOT enlarged. Acceptance still happens only
via a sent turn (S1 accept-on-turn, reused, not duplicated).

No model calls: the reply builder is called directly, service
tests use a fake generate_fn, route tests call the route function
directly with a monkeypatched store (no TestClient, no real DB).
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

import api.routes.conversation_routes as routes_mod
import local_ai.conversation.reply as reply_mod
from local_ai.conversation.service import (
    ConversationService,
    build_invitation_context,
)
from local_ai.conversation.store import ConversationStore


def _fake_generate(prompt: str, **kwargs) -> str:
    return "Fake reply."


def _evidence() -> dict:
    return {
        "user_message": "Staging trial test.",
        "responding_seat": "champion",
        "assistant_reply": "That's no hill.",
        "context": [],
    }


def _create(store, user="u1", conv="talk-1", seat="guardian", reason="hand to offer"):
    return store.create_or_refresh_invitation(
        user, conv, seat, reason, evidence=_evidence()
    )


def _history_section(prompt_lines: list[str], final_user_line: str) -> list[str]:
    start = prompt_lines.index("Conversation so far:")
    end = prompt_lines.index(final_user_line)
    return prompt_lines[start + 1 : end]


# -- S4: read surface ----------------------------------------------------------


def test_invitations_route_is_registered():
    paths = [getattr(r, "path", "") for r in routes_mod.router.routes]
    assert "/conversation/invitations" in paths


def test_api_item_labels_reason_and_carries_verbatim_evidence():
    inv = {
        "id": "abc",
        "user_id": "u1",
        "conversation_id": "talk-1",
        "seat": "guardian",
        "reason": "hand to offer",
        "evidence": _evidence(),
        "status": "pending",
        "created_at": "2026-11-04T00:00:00",
        "expires_at": "2026-11-11T00:00:00",
    }
    item = routes_mod._invitation_api_item(inv)
    # Q5: the reason travels with its attribution, never as fact.
    assert item["reason"] == "hand to offer"
    assert "not an established fact" in item["reason_attribution"]
    assert "interpretation" in item["reason_attribution"]
    # Evidence travels verbatim; the caller's id is not echoed.
    assert item["evidence"] == _evidence()
    assert "user_id" not in item
    assert item["seat"] == "guardian"
    assert item["status"] == "pending"


def test_route_lists_pending_scoped_and_reads_do_not_consume(tmp_path, monkeypatch):
    store = ConversationStore(db_path=tmp_path / "inv.db")
    monkeypatch.setattr(routes_mod, "_store", lambda: store)
    _create(store, user="u1", conv="talk-1", seat="guardian")
    _create(store, user="u1", conv="talk-1", seat="conductor")
    _create(store, user="u1", conv="talk-2", seat="guardian")
    _create(store, user="u2", conv="talk-1", seat="guardian")

    first = routes_mod.list_invitations(
        conversation_id="talk-1", current_user={"id": "u1"}
    )
    assert first["conversation_id"] == "talk-1"
    assert {i["seat"] for i in first["invitations"]} == {"guardian", "conductor"}
    # Tap/open is a read: a second listing is identical, and the
    # store rows are still pending — nothing was consumed.
    second = routes_mod.list_invitations(
        conversation_id="talk-1", current_user={"id": "u1"}
    )
    assert second == first
    assert len(store.list_pending_invitations("u1", "talk-1")) == 2
    store.close()


def test_route_foreign_conversation_yields_nothing(tmp_path, monkeypatch):
    store = ConversationStore(db_path=tmp_path / "inv.db")
    monkeypatch.setattr(routes_mod, "_store", lambda: store)
    _create(store, user="u2", conv="talk-1", seat="guardian")
    result = routes_mod.list_invitations(
        conversation_id="talk-1", current_user={"id": "u1"}
    )
    assert result["invitations"] == []
    store.close()


def test_route_requires_sign_in():
    with pytest.raises(HTTPException) as exc_info:
        routes_mod.list_invitations(conversation_id="talk-1", current_user={})
    assert exc_info.value.status_code == 401


def test_cleared_conversation_yields_nothing_actionable(tmp_path, monkeypatch):
    store = ConversationStore(db_path=tmp_path / "inv.db")
    monkeypatch.setattr(routes_mod, "_store", lambda: store)
    _create(store, user="u1", conv="talk-1", seat="guardian")
    assert len(store.list_pending_invitations("u1", "talk-1")) == 1
    store.clear_conversation("u1", "talk-1")
    # Clear expired the pending row (S1); the read side sees nothing.
    assert store.list_pending_invitations("u1", "talk-1") == []
    result = routes_mod.list_invitations(
        conversation_id="talk-1", current_user={"id": "u1"}
    )
    assert result["invitations"] == []
    store.close()


def test_expired_invitation_is_not_listed(tmp_path, monkeypatch):
    store = ConversationStore(db_path=tmp_path / "inv.db")
    monkeypatch.setattr(routes_mod, "_store", lambda: store)
    inv = _create(store)
    store.invalidate_invitation("u1", inv["id"])
    result = routes_mod.list_invitations(
        conversation_id="talk-1", current_user={"id": "u1"}
    )
    assert result["invitations"] == []
    store.close()


# -- S5: join-context builder ---------------------------------------------------


def test_join_block_renders_verbatim_evidence_and_labeled_reason():
    block = build_invitation_context(
        {
            "reason": "hand to offer",
            "evidence": _evidence(),
        }
    )
    assert block is not None
    assert "hand to offer" in block
    # Q5: attribution is part of the block, not an optional garnish.
    assert "not an established fact" in block
    assert "interpretation" in block
    # Verbatim exchange, responding seat by stock display name.
    assert "User: Staging trial test." in block
    assert "Champion: That's no hill." in block


def test_join_block_empty_evidence_is_reason_only_and_honest():
    block = build_invitation_context({"reason": "hand to offer", "evidence": {}})
    assert block is not None
    assert "hand to offer" in block
    assert "No justifying exchange was stored" in block
    assert "User:" not in block


def test_join_block_missing_or_empty_reason_is_none():
    assert build_invitation_context(None) is None
    assert build_invitation_context({"reason": "  ", "evidence": _evidence()}) is None


def test_join_block_renders_context_entries_bounded_and_skips_junk():
    evidence = _evidence()
    evidence["context"] = [
        "Prior note.",
        {"role": "user", "content": "Earlier words."},
        42,
        {"nope": True},
    ]
    block = build_invitation_context({"reason": "hand to offer", "evidence": evidence})
    assert block is not None
    assert "Prior note." in block
    assert "user: Earlier words." in block
    assert "42" not in block
    assert "nope" not in block


def test_join_block_caps_oversized_evidence():
    evidence = _evidence()
    evidence["assistant_reply"] = "x" * 5000
    block = build_invitation_context({"reason": "hand to offer", "evidence": evidence})
    assert block is not None
    reply_line = [ln for ln in block.split("\n") if ln.startswith("Champion:")][0]
    assert len(reply_line) <= len("Champion: ") + 2000


def test_reply_builder_invitation_section_absent_when_none():
    prompt, _meta = reply_mod.build_voice_prompt(
        "u1", "guardian", "Hello.", [], mode="base", canonical=True
    )
    assert not any("Invitation context" in line for line in prompt)
    prompt2, _meta2 = reply_mod.build_voice_prompt(
        "u1",
        "guardian",
        "Hello.",
        [],
        mode="base",
        canonical=True,
        invitation_context="Invitation context — test block.",
    )
    assert "Invitation context — test block." in prompt2


# -- S5: service turn behavior ---------------------------------------------------


def _svc_with_capture(tmp_path):
    prompts: list[str] = []

    def _capture(prompt: str, **kwargs) -> str:
        prompts.append(prompt)
        return "Fake reply."

    store = ConversationStore(db_path=tmp_path / "conv.db")
    svc = ConversationService(store, generate_fn=_capture)
    return svc, store, prompts


def test_first_joining_turn_carries_block_later_turns_do_not(tmp_path):
    svc, store, prompts = _svc_with_capture(tmp_path)
    _create(store)
    svc.turn("u1", "guardian", "Hello, Bear.", conversation_id="talk-1")
    first = prompts[-1]
    assert "Invitation context" in first
    assert "hand to offer" in first
    assert "Staging trial test." in first
    # The turn accepted the invitation (S1 wiring, reused).
    assert store.list_pending_invitations("u1", "talk-1") == []
    svc.turn("u1", "guardian", "And one more thing.", conversation_id="talk-1")
    assert "Invitation context" not in prompts[-1]
    store.close()


def test_turn_to_other_seat_gets_no_block_and_leaves_pending(tmp_path):
    svc, store, prompts = _svc_with_capture(tmp_path)
    _create(store)
    svc.turn("u1", "conductor", "Hello, Weaver.", conversation_id="talk-1")
    assert "Invitation context" not in prompts[-1]
    assert len(store.list_pending_invitations("u1", "talk-1")) == 1
    store.close()


def test_untapped_invitation_survives_another_seats_join(tmp_path):
    svc, store, prompts = _svc_with_capture(tmp_path)
    _create(store, seat="guardian", reason="hand to offer")
    _create(store, seat="conductor", reason="second reason")
    svc.turn("u1", "guardian", "Hello, Bear.", conversation_id="talk-1")
    remaining = store.list_pending_invitations("u1", "talk-1")
    assert [i["seat"] for i in remaining] == ["conductor"]
    # The untapped seat's own first joining turn still gets its block.
    svc.turn("u1", "conductor", "Hello, Weaver.", conversation_id="talk-1")
    assert "second reason" in prompts[-1]
    assert store.list_pending_invitations("u1", "talk-1") == []
    store.close()


def test_expired_invitation_gets_no_block(tmp_path):
    svc, store, prompts = _svc_with_capture(tmp_path)
    inv = _create(store)
    store.invalidate_invitation("u1", inv["id"])
    svc.turn("u1", "guardian", "Hello, Bear.", conversation_id="talk-1")
    assert "Invitation context" not in prompts[-1]
    store.close()


def test_join_lookup_failure_does_not_break_turn(tmp_path, monkeypatch):
    svc, store, prompts = _svc_with_capture(tmp_path)
    _create(store)

    def _raise(*args, **kwargs):
        raise RuntimeError("store down")

    monkeypatch.setattr(store, "list_pending_invitations", _raise)
    result = svc.turn("u1", "guardian", "Hello, Bear.", conversation_id="talk-1")
    assert result.reply.reply == "Fake reply."
    assert "Invitation context" not in prompts[-1]
    store.close()


def test_window_not_enlarged_on_join_turn(tmp_path):
    svc, store, prompts = _svc_with_capture(tmp_path)
    _create(store)
    for i in range(7):
        svc.turn("u1", "mentor", f"turn {i}", conversation_id="talk-1")
    svc.turn("u1", "guardian", "Hello, Bear.", conversation_id="talk-1")
    lines = prompts[-1].split("\n")
    section = _history_section(lines, "User: Hello, Bear.")
    # Still exactly the last 10 prior turns — the join block is a
    # separate section, not window enlargement.
    assert len(section) == 10
    assert "Invitation context" in prompts[-1]
    assert lines.index(next(ln for ln in lines if "Invitation context" in ln)) < lines.index(
        "Conversation so far:"
    )
    store.close()
