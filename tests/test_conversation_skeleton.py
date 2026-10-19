"""Conversation skeleton tests: store, service, shared reply builder, routes.

The LLM is faked everywhere (injected generate_fn or monkeypatched module
functions). The ConversationStore uses a tmp SQLite file. No real provider
calls, no training data written.
"""

from __future__ import annotations

import json

import pytest
import local_ai.conversation.reply as reply_mod
import local_ai.conversation.service as service_mod
import local_ai.conversation.suggestions as sugg_mod
from local_ai.conversation.service import ConversationService, context_hint_for
from local_ai.conversation.store import ConversationStore
from local_ai.conversation.suggestions import (
    empty_suggestions,
    generate_suggestions,
    rule_based_suggestions,
)

ALICE = {"id": "user-alice", "email": "alice@x", "display_name": "Alice"}
BOB = {"id": "user-bob", "email": "bob@x", "display_name": "Bob"}


def _fake_generate(prompt: str, **kwargs) -> str:
    return "Fake reply."


def _store(tmp_path) -> ConversationStore:
    return ConversationStore(db_path=tmp_path / "conv.db")


# -- store --------------------------------------------------------------------


def test_ensure_conversation_idempotent(tmp_path):
    s = _store(tmp_path)
    a = s.ensure_conversation("u1")
    b = s.ensure_conversation("u1")
    assert a["conversation_id"] == "skeleton" == b["conversation_id"]
    assert a["created_at"] == b["created_at"]
    s.close()


def test_append_and_history_order(tmp_path):
    s = _store(tmp_path)
    s.ensure_conversation("u1")
    s.append_message("u1", "skeleton", "mentor", "user", "hello")
    s.append_message("u1", "skeleton", "mentor", "voice", "hi there", mode="base")
    s.append_message("u1", "skeleton", "maverick", "user", "new seat")
    hist = s.history("u1", "skeleton")
    assert [m["body"] for m in hist] == ["hello", "hi there", "new seat"]
    assert [m["archetype_id"] for m in hist] == ["mentor", "mentor", "maverick"]
    assert [m["role"] for m in hist] == ["user", "voice", "user"]
    assert hist[1]["mode"] == "base"
    s.close()


def test_history_limit(tmp_path):
    s = _store(tmp_path)
    for i in range(10):
        s.append_message("u1", "skeleton", "mentor", "user", f"m{i}")
    assert len(s.history("u1", "skeleton", limit=4)) == 4
    assert s.history("u1", "skeleton", limit=4)[-1]["body"] == "m9"
    s.close()


def test_per_user_isolation(tmp_path):
    s = _store(tmp_path)
    s.append_message("alice", "skeleton", "mentor", "user", "alice secret")
    assert s.history("bob", "skeleton") == []
    assert s.history("alice", "skeleton")[0]["body"] == "alice secret"
    s.close()


def test_thread_state_lifecycle(tmp_path):
    s = _store(tmp_path)
    st = s.get_thread_state("u1", "skeleton", "mentor")
    assert st["summary"] == "" and st["messages_since_summary"] == 0
    st = s.update_thread_state("u1", "skeleton", "mentor", increment=3)
    assert st["messages_since_summary"] == 3
    st = s.update_thread_state(
        "u1", "skeleton", "mentor", summary="talked about rest", reset_counter=True
    )
    assert st["summary"] == "talked about rest"
    assert st["messages_since_summary"] == 0
    s.close()


# -- service ------------------------------------------------------------------


def _svc(tmp_path, generate_fn=_fake_generate):
    store = _store(tmp_path)
    return ConversationService(store, generate_fn=generate_fn), store


def test_turn_persists_both_sides(tmp_path):
    svc, store = _svc(tmp_path)
    result = svc.turn("u1", "mentor", "I need to plan my week")
    assert result.reply.reply == "Fake reply."
    assert result.conversation_id == "skeleton"
    hist = store.history("u1", "skeleton")
    assert len(hist) == 2
    assert hist[0]["role"] == "user" and hist[0]["body"] == "I need to plan my week"
    assert hist[1]["role"] == "voice" and hist[1]["body"] == "Fake reply."
    assert hist[1]["archetype_id"] == "mentor"
    store.close()


def test_turn_rejects_unknown_seat_and_empty_message(tmp_path):
    svc, store = _svc(tmp_path)
    with pytest.raises(ValueError):
        svc.turn("u1", "nope", "hello")
    with pytest.raises(ValueError):
        svc.turn("u1", "mentor", "   ")
    # question mode allows an empty message
    result = svc.turn("u1", "mentor", "", question=True)
    assert result.reply.reply == "Fake reply."
    store.close()


def test_seat_switch_interleaves_history(tmp_path):
    svc, store = _svc(tmp_path)
    svc.turn("u1", "mentor", "mentor q")
    svc.turn("u1", "maverick", "maverick q")
    svc.turn("u1", "mentor", "mentor again")
    hist = store.history("u1", "skeleton")
    seats = [m["archetype_id"] for m in hist]
    assert seats == ["mentor", "mentor", "maverick", "maverick", "mentor", "mentor"]
    store.close()


def test_context_stored_on_messages(tmp_path):
    svc, store = _svc(tmp_path)
    ctx = {"sheet_type": "today", "entity_type": "task", "entity_id": "t1"}
    svc.turn("u1", "mentor", "hi", context=ctx)
    hist = store.history("u1", "skeleton")
    assert hist[0]["context"]["sheet_type"] == "today"
    assert hist[0]["context"]["entity_id"] == "t1"
    store.close()


def test_context_hint_for():
    assert context_hint_for(None) is None
    assert context_hint_for({}) is None
    hint = context_hint_for({"sheet_type": "today", "entity_type": "task", "entity_id": "t9"})
    assert "today" in hint and "task" in hint and "t9" in hint


def test_thread_summary_refreshes_every_n(tmp_path, monkeypatch):
    summary_calls = []
    reply_calls = []

    def fake_summary(prompt: str, **kwargs) -> str:
        if "ongoing one-on-one thread" in prompt:
            summary_calls.append(prompt)
            return "Rolling summary."
        reply_calls.append(prompt)
        return "Fake reply."

    monkeypatch.setattr(service_mod, "SUMMARY_EVERY_N_TURNS", 2)
    svc, store = _svc(tmp_path, generate_fn=fake_summary)
    svc.turn("u1", "mentor", "one")
    assert summary_calls == []  # only one turn so far — no summary pass yet
    assert len(reply_calls) == 1
    svc.turn("u1", "mentor", "two")
    assert len(summary_calls) == 1
    state = store.get_thread_state("u1", "skeleton", "mentor")
    assert state["summary"] == "Rolling summary."
    assert state["messages_since_summary"] == 0
    store.close()


def test_thread_summary_failure_keeps_old_summary(tmp_path, monkeypatch):
    def boom(prompt: str, **kwargs) -> str:
        if "rolling summary" in prompt.lower() or "ongoing one-on-one" in prompt:
            raise RuntimeError("llm down")
        return "Fake reply."

    monkeypatch.setattr(service_mod, "SUMMARY_EVERY_N_TURNS", 1)
    svc, store = _svc(tmp_path, generate_fn=boom)
    svc.turn("u1", "mentor", "one")
    state = store.get_thread_state("u1", "skeleton", "mentor")
    assert state["summary"] == ""  # old (empty) summary stands
    assert state["messages_since_summary"] == 0  # counter reset, no retry storm
    store.close()


def test_thread_summary_feeds_next_reply(tmp_path, monkeypatch):
    prompts = []

    def capture(prompt: str, **kwargs) -> str:
        prompts.append(prompt)
        return "Fake reply."

    svc, store = _svc(tmp_path, generate_fn=capture)
    store.update_thread_state("u1", "skeleton", "mentor", summary="USER LOVES GARDENING")
    svc.turn("u1", "mentor", "hello again")
    assert any("USER LOVES GARDENING" in p for p in prompts)
    store.close()


# -- shared reply builder ------------------------------------------------------


def test_build_voice_prompt_question_mode_and_extras():
    prompt, meta = reply_mod.build_voice_prompt(
        "u1",
        "mentor",
        "",
        [],
        question=True,
        context_hint="the user currently has the 'today' sheet open.",
        thread_summary="prior thread about rest",
    )
    text = "\n".join(prompt)
    assert "question them" in text
    assert "today" in text
    assert "prior thread about rest" in text
    assert meta["archetype_id"] == "mentor"
    with pytest.raises(ValueError):
        reply_mod.build_voice_prompt("u1", "nope", "hi", [])


def test_generate_voice_reply_meta():
    reply = reply_mod.generate_voice_reply(
        "u1", "maverick", "hi", [], generate_fn=_fake_generate
    )
    assert reply.reply == "Fake reply."
    assert reply.archetype_id == "maverick"
    assert reply.voice_color == "#9a7bc9"
    assert reply.mode_used in ("trained", "base")


def test_trained_sections_scopes_store_to_user(tmp_path, monkeypatch):
    """Regression: PersonalityStore's first positional param is db_path, so
    the user id must be passed as a keyword — otherwise a throwaway DB named
    after the user id is created and training never loads."""
    import local_ai.personality.store as pstore_mod

    seen: dict = {}

    class FakeStore:
        def __init__(self, *a, **k):
            seen["args"] = a
            seen["kwargs"] = k

        def get_current(self):
            return None

        def close(self):
            pass

    monkeypatch.setattr(pstore_mod, "PersonalityStore", FakeStore)
    sections, has_training = reply_mod._trained_sections("user-alice", {"Word": 0.9})
    assert (sections, has_training) == ([], False)
    assert seen["args"] == ()
    assert seen["kwargs"].get("user_id") == "user-alice"


# -- suggestions ---------------------------------------------------------------


def test_suggestions_shapes_and_empty_fallback():
    assert rule_based_suggestions() == empty_suggestions()
    assert generate_suggestions([], None, generate_fn=_fake_generate) == empty_suggestions()
    # unparseable LLM output -> honest empty triple, never raises
    out = generate_suggestions(
        [{"role": "user", "body": "hi", "archetype_id": "mentor"}],
        None,
        generate_fn=lambda prompt, **kw: "not json {{{",
    )
    assert out == empty_suggestions()


def _suggestion_llm(prompt: str, **kwargs) -> str:
    return json.dumps(
        {
            "trainable_moments": [
                {
                    "title": "Values rest",
                    "claim_type": "value_inference",
                    "evidence": "I protect my mornings fiercely",
                    "inference": "Mornings are a protected value.",
                    "question": "Mornings sacred — right?",
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


def test_generate_suggestions_shaped_drafts():
    turns = [{"role": "user", "body": "I protect my mornings fiercely", "archetype_id": "mentor"}]
    out = generate_suggestions(turns, None, generate_fn=_suggestion_llm, user_id="u1")
    tm = out["trainable_moments"][0]
    assert tm["draft"] is True and tm["status"] == "draft"
    assert tm["source"] == "conversation-skeleton"
    assert tm["evidence"] == "I protect my mornings fiercely"
    pp = out["project_proposals"][0]
    assert pp["kind"] == "task" and pp["draft"] is True
    ms = out["mint_suggestions"][0]
    assert ms["suggested_action"] == "mint-standalone"
    assert "How does this piece express this moment to you?" in ms["anchor_question"]
