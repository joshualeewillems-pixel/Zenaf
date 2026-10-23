"""Recurrence pass tests (Joshua, 2026-10-23).

What a person returns to across a conversation is first-class evidence.
These tests pin the grounding discipline: quotes must be verbatim from
the transcript, from at least two DIFFERENT turns; ungrounded or
single-turn "patterns" are dropped; no LLM means an honest empty list.
"""

from __future__ import annotations

import json

import pytest

from local_ai.agent_intake import recurrence, review_claims

TURNS = [
    "I keep thinking about my dad's workshop behind the house.",
    "Work was fine. The standup ran long again.",
    "Honestly the workshop is where I actually feel like myself.",
    "Lunch was a sandwich, nothing to report.",
    "If I could spend every weekend in that workshop I would.",
]


def _fake_llm(monkeypatch, payload, key="test-key"):
    monkeypatch.setattr(recurrence, "_api_key", lambda user_id=None: key)
    monkeypatch.setattr(
        recurrence, "_generate", lambda prompt, user_id=None: json.dumps(payload)
    )


def test_recurrence_grounded_in_distinct_turns(monkeypatch):
    _fake_llm(monkeypatch, {"patterns": [{
        "topic": "his father's workshop",
        "strand": "Heart",
        "inference": "You keep coming back to the workshop — it reads like the place you feel most yourself.",
        "quotes": [
            "I keep thinking about my dad's workshop behind the house.",
            "If I could spend every weekend in that workshop I would.",
        ],
    }]})
    patterns, engine = recurrence.mine_recurrences(TURNS, user_id="u1")
    assert engine == "anthropic"
    assert len(patterns) == 1
    p = patterns[0]
    assert p.strand == "Heart"
    assert p.turns == [1, 5]


def test_single_turn_pattern_is_dropped(monkeypatch):
    _fake_llm(monkeypatch, {"patterns": [{
        "topic": "standup meetings",
        "strand": "Logic",
        "inference": "You keep coming back to standups.",
        "quotes": ["Work was fine. The standup ran long again.",
                   "The standup ran long"],
    }]})
    patterns, _ = recurrence.mine_recurrences(TURNS, user_id="u1")
    assert patterns == []  # both quotes live in turn 2 — not a recurrence


def test_invented_quote_is_dropped(monkeypatch):
    _fake_llm(monkeypatch, {"patterns": [{
        "topic": "the workshop",
        "strand": "Heart",
        "inference": "You keep coming back to the workshop.",
        "quotes": ["I keep thinking about my dad's workshop behind the house.",
                   "The workshop is my favorite place in the whole world."],
    }]})
    patterns, _ = recurrence.mine_recurrences(TURNS, user_id="u1")
    assert patterns == []  # second quote is not in the transcript


def test_no_llm_means_honest_empty(monkeypatch):
    monkeypatch.setattr(recurrence, "_api_key", lambda user_id=None: None)
    patterns, engine = recurrence.mine_recurrences(TURNS, user_id="u1")
    assert patterns == [] and engine == "rule_based"


def test_single_chunk_cannot_recur():
    patterns, engine = recurrence.mine_recurrences(["just one turn"], user_id="u1")
    assert patterns == [] and engine == "rule_based"


def test_recurrence_claims_shape():
    p = recurrence.RecurrencePattern(
        topic="his father's workshop", strand="Heart",
        inference="You keep coming back to the workshop.",
        quotes=["quote one", "quote two"], turns=[1, 5],
    )
    claims = review_claims.build_recurrence_claims([p], "agent-1")
    assert len(claims) == 1
    c = claims[0]
    assert c.id == "agent-1:recurrence:0"
    assert c.claim_type == "recurrence"
    assert c.scope == "pattern"
    assert c.title == "Keeps coming back to: his father's workshop"
    assert c.evidence == "quote one"
    assert "Heart" in c.detail and "quote two" in c.detail
    assert "Turn 1" in c.turn_ref and "Turn 5" in c.turn_ref
