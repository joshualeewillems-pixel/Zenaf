"""Tests for the anonymous landing demo routes: question-mode toggle,
SQLite-backed claim codes, and the anti-presumption rule + per-seat warmth
registers."""

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


# --- Question-tennis fix: anti-narration + new-substance rules ----------------


def _question_tennis_transcript():
    # Mirrors the observed 10-turn failure: the last voice rephrased the
    # previous voice's question instead of bringing anything new.
    return [
        {"role": "visitor", "content": "Part of me wants the rocket ship, part wants to keep it mine."},
        {"role": "skeptic", "content": "What are you assuming makes YC different?"},
        {"role": "guardian", "content": "What must be protected if the rocket ship means you don't keep it yours?"},
        {"role": "skeptic", "content": "What are you assuming lets the rocket ship still let you keep it yours?"},
    ]


def test_speak_turn_question_mode_bans_narration():
    from api.routes import demo_routes as dr

    prompt = dr._build_demo_prompt(
        "ambassador", _question_tennis_transcript(), speak=True, question_mode=True
    )
    assert "never about the other voices" in prompt
    assert "do not narrate" in prompt


def test_speak_turn_respond_mode_bans_narration():
    from api.routes import demo_routes as dr

    prompt = dr._build_demo_prompt(
        "ambassador", _question_tennis_transcript(), speak=True, question_mode=False
    )
    assert "never about the other voices" in prompt
    assert "do not narrate" in prompt


def test_speak_turn_question_mode_requires_new_substance():
    from api.routes import demo_routes as dr

    prompt = dr._build_demo_prompt(
        "skeptic", _question_tennis_transcript(), speak=True, question_mode=True
    )
    assert "open a door that is still closed" in prompt
    assert "Never rephrase the previous voice's question" in prompt
    # The instruction targets the LAST voice turn (the rephrase), not the
    # earlier one — the prompt must name what it is responding to.
    assert "What are you assuming lets the rocket ship still let you keep it yours?" in prompt


def test_speak_turn_respond_mode_requires_new_substance():
    from api.routes import demo_routes as dr

    prompt = dr._build_demo_prompt(
        "champion", _question_tennis_transcript(), speak=True, question_mode=False
    )
    assert "Bring something new" in prompt
    assert "Do not restate the previous voice's point" in prompt


def test_speak_turn_addresses_visitor_directly():
    from api.routes import demo_routes as dr

    for mode in (True, False):
        prompt = dr._build_demo_prompt(
            "mentor", _question_tennis_transcript(), speak=True, question_mode=mode
        )
        assert "address the visitor directly" in prompt


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


# --- Issue 4: anti-presumption rule + per-seat warmth registers -----------------


def test_anti_presumption_rule_present_for_all_seats():
    from local_ai.council import archetypes as arch

    for vid in arch.stock_archetype_ids():
        text = "\n".join(arch.build_archetype_prompt_lines(vid))
        assert "never presume" in text.lower(), vid
        assert "own words" in text.lower(), vid


def test_anti_presumption_names_banned_patterns():
    from local_ai.council import archetypes as arch

    text = "\n".join(arch.build_archetype_prompt_lines("guardian"))
    # Presumption is steered against by name ...
    assert "That sounds lonely" in text
    # ... while validation with the user's own words is explicitly allowed.
    assert "reflect the speaker's own words" in text.lower()


def test_warmth_registers_differ_per_seat():
    from local_ai.council import archetypes as arch

    warm = {
        "guardian": "warm-protective",
        "ambassador": "warm-understanding",
        "mentor": "warm-patient",
    }
    for vid, marker in warm.items():
        text = "\n".join(arch.build_archetype_prompt_lines(vid))
        assert marker in text, vid

    for vid in ("champion", "maverick", "conductor"):
        text = "\n".join(arch.build_archetype_prompt_lines(vid))
        assert "sparing and direct" in text, vid

    skeptic = "\n".join(arch.build_archetype_prompt_lines("skeptic"))
    assert "warmth register: none" in skeptic
    assert "hard question" in skeptic

    # The warm seats' registers are genuinely different lines, not one
    # shared string — no flattening into seven Skeptics.
    registers = {
        next(
            line for line in arch.build_archetype_prompt_lines(vid)
            if line.startswith("Your warmth register:")
        )
        for vid in arch.stock_archetype_ids()
    }
    assert len(registers) == len(arch.stock_archetype_ids())


def test_warmth_register_covers_every_stock_seat():
    from local_ai.council import archetypes as arch

    assert set(arch.WARMTH_REGISTERS) == set(arch.stock_archetype_ids())


def test_anti_presumption_leaves_card_content_untouched():
    from local_ai.council import archetypes as arch

    # Card content assertions from the existing suite still hold: philosophy
    # block is exactly 4 lines, defining questions intact.
    for vid in arch.stock_archetype_ids():
        assert len(arch.philosophy_prompt_lines(vid)) == 4, vid
    assert "What are we assuming?" in "\n".join(arch.build_archetype_prompt_lines("skeptic"))


def test_demo_prompt_matches_two_layer_framing():
    from api.routes import demo_routes as dr

    prompt = dr._build_demo_prompt("guardian", [], speak=False, question_mode=False)
    assert "That sounds lonely" in prompt  # the presumption pattern is named
    assert "warmth register" in prompt
    # The per-seat register flows into the demo prompt via the archetype lines.
    assert "warm-protective" in prompt


# --- Conductor orchestration v1: dissent-preserving synthesis ----------------


def test_conductor_speak_turn_carries_orchestration_block():
    from api.routes import demo_routes as dr

    prompt = dr._build_demo_prompt(
        "conductor", _two_voice_transcript(), speak=True, question_mode=False
    )
    # Name the standing disagreements and let them stand — no false consensus.
    assert "standing disagreements" in prompt
    assert "never a consensus the thread hasn't reached" in prompt
    # A moved position must be owned out loud, with what changed it.
    assert "say what changed it" in prompt


def test_orchestration_block_is_conductor_only():
    from api.routes import demo_routes as dr

    for vid in ("mentor", "champion", "guardian", "maverick", "ambassador", "skeptic"):
        prompt = dr._build_demo_prompt(
            vid, _two_voice_transcript(), speak=True, question_mode=False
        )
        assert "standing disagreements" not in prompt, vid


def test_conductor_question_mode_untouched_by_orchestration():
    from api.routes import demo_routes as dr

    # Hard constraint: question mode stays exactly as-is.
    prompt = dr._build_demo_prompt(
        "conductor", _two_voice_transcript(), speak=True, question_mode=True
    )
    assert "standing disagreements" not in prompt
    assert "ONE penetrating question about Mentor's last response" in prompt


# --- Conductor orchestration v1: seat recusal --------------------------------


def test_recusal_offered_to_every_seat_but_skeptic():
    from api.routes import demo_routes as dr
    from local_ai.council.archetypes import stock_archetype_ids

    for vid in stock_archetype_ids():
        prompt = dr._build_demo_prompt(
            vid, _two_voice_transcript(), speak=True, question_mode=False
        )
        if vid == "skeptic":
            # The Skeptic never recuses — examining is always its ground.
            assert "recuse" not in prompt, vid
        else:
            assert "recuse" in prompt, vid
            # The seat's own home ground is named, so the boundary is legible.
            assert dr._SEAT_TERRITORY[vid] in prompt, vid


def test_recusal_is_rare_and_complete():
    from api.routes import demo_routes as dr

    prompt = dr._build_demo_prompt(
        "ambassador", _two_voice_transcript(), speak=True, question_mode=False
    )
    # Rare/literal: plainly another seat's ground only, never a dodge.
    assert "Recuse rarely" in prompt
    assert "never to dodge a hard question" in prompt
    # A recusal is the whole reply for the turn — one generation, no extra call.
    assert "a recusal is a complete reply" in prompt


def test_recusal_not_offered_in_question_mode():
    from api.routes import demo_routes as dr

    # Hard constraint: question mode stays exactly as-is — no recusal there.
    for vid in ("mentor", "guardian", "conductor"):
        prompt = dr._build_demo_prompt(
            vid, _two_voice_transcript(), speak=True, question_mode=True
        )
        assert "recuse" not in prompt, vid


# --- Register flag: "!" over the seat whose register a reply entered -------


def test_register_flag_instruction_on_speak_turns_all_seats():
    from api.routes import demo_routes as dr
    from local_ai.council.archetypes import stock_archetype_ids

    for vid in stock_archetype_ids():
        prompt = dr._build_demo_prompt(
            vid, _two_voice_transcript(), speak=True, question_mode=False
        )
        assert "[[register:" in prompt, vid


def test_register_flag_instruction_lists_other_seats_only():
    from api.routes import demo_routes as dr
    from local_ai.council.archetypes import stock_archetype_ids

    for vid in stock_archetype_ids():
        instruction = dr._register_flag_instruction(vid)
        # Every other seat is a named flag target, with its register text —
        # including the Skeptic, whose register a reply can enter even
        # though the Skeptic itself never recuses.
        for other in stock_archetype_ids():
            if other == vid:
                assert f"({other})" not in instruction, vid
            else:
                assert f"({other})" in instruction, (vid, other)
                assert dr._SEAT_REGISTERS[other] in instruction, (vid, other)
        # Rare, singular, never its own seat — the recusal spirit. (The
        # hand-off wording avoids "recuse" so the Skeptic's prompt keeps
        # #171's invariant: no recusal language is ever addressed to it.)
        assert "At most one marker" in instruction
        assert "never your own seat" in instruction
        assert "add no marker" in instruction
        assert "hand-off already names the seat" in instruction


def test_register_flag_absent_in_question_mode():
    from api.routes import demo_routes as dr

    # Hard constraint: question mode stays exactly as-is — no flag there.
    for vid in ("mentor", "guardian", "conductor", "skeptic"):
        prompt = dr._build_demo_prompt(
            vid, _two_voice_transcript(), speak=True, question_mode=True
        )
        assert "[[register:" not in prompt, vid


def test_register_flag_absent_for_typed_messages():
    from api.routes import demo_routes as dr

    # Speak turns only: a typed message in respond mode gets no instruction.
    prompt = dr._build_demo_prompt(
        "mentor",
        [{"role": "visitor", "content": "I'm at a crossroads."}],
        speak=False,
        question_mode=False,
    )
    assert "[[register:" not in prompt


def test_register_flag_parsed_and_stripped():
    from api.routes import demo_routes as dr

    text, flag = dr._extract_register_flag(
        "Watch what this costs the people around you.\n[[register:guardian]]",
        "mentor",
    )
    assert flag == "guardian"
    assert text == "Watch what this costs the people around you."


def test_register_flag_none_without_marker():
    from api.routes import demo_routes as dr

    text, flag = dr._extract_register_flag("A plain answer in my own voice.", "mentor")
    assert flag is None
    assert text == "A plain answer in my own voice."


def test_register_flag_with_trailing_whitespace():
    from api.routes import demo_routes as dr

    text, flag = dr._extract_register_flag(
        "An answer.\n[[register:guardian]]  \n", "mentor"
    )
    assert flag == "guardian"
    assert text == "An answer."


def test_register_flag_recusal_carries_no_flag():
    from api.routes import demo_routes as dr

    # The recusal already names the seat — a marker on top of it is ignored.
    text, flag = dr._extract_register_flag(
        "This is the Guardian's ground — protection, not translation.\n"
        "[[register:guardian]]",
        "ambassador",
    )
    assert flag is None
    assert text == "This is the Guardian's ground — protection, not translation."


def test_register_flag_malformed_never_leaks():
    from api.routes import demo_routes as dr

    cases = [
        # Unknown seat: no flag, marker gone.
        "An answer.\n[[register:bogus]]",
        # Empty seat id.
        "An answer.\n[[register:]]",
        # Missing a closing bracket: not flag-bearing, still stripped.
        "An answer.\n[[register:guardian]",
        # A seat never flags itself.
        "An answer.\n[[register:mentor]]",
    ]
    for raw in cases:
        text, flag = dr._extract_register_flag(raw, "mentor")
        assert flag is None, raw
        assert "register" not in text, raw
        assert text == "An answer.", raw
    # Turns that may not flag (typed / question mode) strip but never flag.
    text, flag = dr._extract_register_flag(
        "An answer.\n[[register:guardian]]", "mentor", enabled=False
    )
    assert flag is None
    assert "register" not in text


def test_register_flag_first_valid_marker_wins():
    from api.routes import demo_routes as dr

    text, flag = dr._extract_register_flag(
        "An answer.\n[[register:guardian]]\n[[register:skeptic]]", "mentor"
    )
    assert flag == "guardian"
    assert "register" not in text
    assert text == "An answer."


def test_stream_safe_split_holds_split_marker():
    from api.routes import demo_routes as dr

    # A marker arriving split across chunks is never emitted in pieces.
    safe, held = dr._split_stream_safe("An answer.\n[[reg")
    assert safe == "An answer.\n"
    assert held == "[[reg"
    safe, held = dr._split_stream_safe(held + "ister:guard")
    assert safe == ""
    assert held == "[[register:guard"
    safe, held = dr._split_stream_safe(held + "ian]]")
    assert safe == ""
    assert held == "[[register:guardian]]"
    # Plain text with no marker shape passes straight through.
    safe, held = dr._split_stream_safe("Just prose, nothing held.")
    assert safe == "Just prose, nothing held."
    assert held == ""


def test_register_flag_response_field_defaults_none():
    from api.routes.demo_routes import DemoChatResponse

    resp = DemoChatResponse(
        reply="hi",
        session_id="s",
        voice="mentor",
        voice_color="#c9a86a",
        exchanges_used=1,
        exchanges_left=11,
    )
    assert resp.register_flag is None
