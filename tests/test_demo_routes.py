"""Tests for the anonymous landing demo routes: question-mode toggle,
SQLite-backed claim codes, and the therapy-speak style guard."""

from __future__ import annotations

import time

import pytest
from fastapi import HTTPException


def _body(**kwargs):
    from api.routes.demo_routes import DemoChatBody

    return DemoChatBody(**kwargs)


def _sess(transcript=({"role": "visitor", "content": "hi"},)):
    return {"transcript": list(transcript)}


# --- Issue 1: question mode honored for typed messages ----------------------


def test_question_mode_applies_to_typed_message():
    from api.routes import demo_routes as dr

    speak, question = dr._speak_turn_params(
        _body(message="Should I quit my job?", mode="question"), _sess()
    )
    assert speak is False
    assert question is True


def test_respond_mode_typed_message_unchanged():
    from api.routes import demo_routes as dr

    speak, question = dr._speak_turn_params(
        _body(message="Should I quit my job?", mode="respond"), _sess()
    )
    assert (speak, question) == (False, False)


def test_question_mode_chip_tap_unchanged():
    from api.routes import demo_routes as dr

    # Empty message = voice-chip tap; question toggle still works there.
    speak, question = dr._speak_turn_params(_body(message="", mode="question"), _sess())
    assert (speak, question) == (True, True)
    speak, question = dr._speak_turn_params(_body(message="  ", mode="respond"), _sess())
    assert (speak, question) == (True, False)


def test_question_mode_case_insensitive():
    from api.routes import demo_routes as dr

    _, question = dr._speak_turn_params(_body(message="hi", mode="Question"), _sess())
    assert question is True


def test_speak_turn_with_no_conversation_still_422():
    from api.routes import demo_routes as dr

    with pytest.raises(HTTPException) as exc:
        dr._speak_turn_params(_body(message="", mode="question"), {"transcript": []})
    assert exc.value.status_code == 422


def test_demo_prompt_question_mode_typed_message():
    from api.routes import demo_routes as dr

    prompt = dr._build_demo_prompt(
        "skeptic",
        [{"role": "visitor", "content": "Am I being brave or reckless?"}],
        speak=False,
        question_mode=True,
    )
    assert "do not answer it" in prompt
    assert "penetrating question" in prompt
    assert "no advice" in prompt


def test_demo_prompt_question_mode_chip_tap_unchanged():
    from api.routes import demo_routes as dr

    prompt = dr._build_demo_prompt("mentor", [], speak=True, question_mode=True)
    assert "tapped you to question them" in prompt


def test_demo_prompt_default_has_no_question_language():
    from api.routes import demo_routes as dr

    prompt = dr._build_demo_prompt("mentor", [], speak=False, question_mode=False)
    assert "do not answer it" not in prompt
    assert "penetrating question" not in prompt


# --- Speak turn targets the last voice response ----------------------------


def _two_voice_transcript():
    return [
        {"role": "visitor", "content": "I'm at a crossroads."},
        {"role": "skeptic", "content": "What are we assuming here? Who outside this loop has paid?"},
        {"role": "visitor", "content": "Nobody yet."},
        {"role": "mentor", "content": "Thirty years holds a pattern. What can it teach you?"},
    ]


def test_speak_turn_targets_last_voice_response():
    from api.routes import demo_routes as dr

    prompt = dr._build_demo_prompt("champion", _two_voice_transcript(), speak=True, question_mode=False)
    assert "Respond to Mentor's last response specifically" in prompt
    assert "Thirty years holds a pattern" in prompt


def test_speak_turn_question_mode_targets_last_response_as_question():
    from api.routes import demo_routes as dr

    prompt = dr._build_demo_prompt("skeptic", _two_voice_transcript(), speak=True, question_mode=True)
    assert "ONE penetrating question about Mentor's last response" in prompt
    assert "Thirty years holds a pattern" in prompt
    assert "no advice, no preamble" in prompt


def test_speak_turn_same_voice_targets_own_response():
    from api.routes import demo_routes as dr

    transcript = [
        {"role": "visitor", "content": "hi"},
        {"role": "skeptic", "content": "What proof would change your mind?"},
    ]
    prompt = dr._build_demo_prompt("skeptic", transcript, speak=True, question_mode=False)
    assert "your own last response" in prompt
    assert "What proof would change your mind?" in prompt


def test_speak_turn_no_voice_turn_yet_falls_back():
    from api.routes import demo_routes as dr

    prompt = dr._build_demo_prompt(
        "mentor", [{"role": "visitor", "content": "hi"}], speak=True, question_mode=False
    )
    assert "Respond to the" in prompt
    assert "conversation so far" in prompt
    assert "last response specifically" not in prompt


def test_speak_turn_quote_truncated():
    from api.routes import demo_routes as dr

    long_reply = "word " * 100
    transcript = [
        {"role": "visitor", "content": "hi"},
        {"role": "mentor", "content": long_reply},
    ]
    prompt = dr._build_demo_prompt("champion", transcript, speak=True, question_mode=False)
    head = prompt.split("Conversation so far:")[0]
    assert "…" in head
    # The instruction quote is truncated — the full 500-char reply must not
    # be inlined into the targeting instruction (it still appears verbatim
    # in the "Conversation so far" transcript dump below, which is fine).
    assert long_reply not in head


# --- Issue 3a: SQLite claim store -------------------------------------------


def _store(tmp_path):
    from api.routes.demo_routes import DemoClaimStore

    return DemoClaimStore(db_path=tmp_path / "claims.db")


def test_claim_issue_consume_roundtrip(tmp_path):
    store = _store(tmp_path)
    try:
        store.issue("ABC123", "You: hello")
        assert store.consume("ABC123") == "You: hello"
    finally:
        store.close()


def test_claim_single_use(tmp_path):
    store = _store(tmp_path)
    try:
        store.issue("ABC123", "You: hello")
        assert store.consume("ABC123") == "You: hello"
        assert store.consume("ABC123") is None
    finally:
        store.close()


def test_claim_unknown_code(tmp_path):
    store = _store(tmp_path)
    try:
        assert store.consume("NOPE99") is None
    finally:
        store.close()


def test_claim_expired(tmp_path):
    from api.routes.demo_routes import CLAIM_TTL_S

    store = _store(tmp_path)
    try:
        store.issue("OLD999", "stale", now=time.time() - CLAIM_TTL_S - 10)
        assert store.consume("OLD999") is None
        # Consumed (deleted) even though expired — no second chances.
        assert store.exists("OLD999") is False
    finally:
        store.close()


def test_claim_sweep_expired(tmp_path):
    from api.routes.demo_routes import CLAIM_TTL_S

    store = _store(tmp_path)
    try:
        now = time.time()
        store.issue("FRESH1", "new", now=now)
        store.issue("STALE1", "old", now=now - CLAIM_TTL_S - 10)
        removed = store.sweep_expired(now=now)
        assert removed == 1
        assert store.exists("FRESH1") is True
        assert store.exists("STALE1") is False
    finally:
        store.close()


def test_claim_codes_survive_reopen(tmp_path):
    """The deploy-wipe bug: codes must persist across store instances."""
    from api.routes.demo_routes import DemoClaimStore

    db = tmp_path / "claims.db"
    s1 = DemoClaimStore(db_path=db)
    s1.issue("KEEP01", "You: hello")
    s1.close()
    s2 = DemoClaimStore(db_path=db)
    try:
        assert s2.consume("KEEP01") == "You: hello"
    finally:
        s2.close()


# --- Issue 4: therapy-speak style guard --------------------------------------


def test_direct_voice_style_in_archetype_prompt():
    from local_ai.council import archetypes as arch

    for vid in arch.stock_archetype_ids():
        text = "\n".join(arch.build_archetype_prompt_lines(vid))
        assert "no therapy-speak" in text.lower() or "therapy-speak" in text, vid


def test_direct_voice_style_leaves_card_content_untouched():
    from local_ai.council import archetypes as arch

    # Card content assertions from the existing suite still hold: philosophy
    # block is exactly 4 lines, defining questions intact.
    for vid in arch.stock_archetype_ids():
        assert len(arch.philosophy_prompt_lines(vid)) == 4, vid
    assert "What are we assuming?" in "\n".join(arch.build_archetype_prompt_lines("skeptic"))


def test_demo_prompt_bans_therapy_openers():
    from api.routes import demo_routes as dr

    prompt = dr._build_demo_prompt("guardian", [], speak=False, question_mode=False)
    assert "therapy-speak" in prompt
    assert "That sounds" in prompt  # the banned opener pattern is named
