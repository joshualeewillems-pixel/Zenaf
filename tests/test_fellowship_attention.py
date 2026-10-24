"""Fellowship Runtime P2 — attention service.

Covers the merged per-seat attention read model
(local_ai/fellowship/attention.py) and the extended
GET /vision-execution/keystone-attention route:

- reason classification is deterministic display logic (question →
  clarify, contrast → challenge, proposal → offer, else discuss),
  with word boundaries (a word merely containing "not" is not a
  challenge);
- relevance scoring is P1's deterministic pre-filter under the
  attention layer's name: same inputs → same scores, no model call,
  and an event in nobody's focus scores nobody;
- the read model merges keystone markers (unchanged semantics) with
  pending/surfaced observations: one marker per seat, keystone reason
  wins ``reason`` when both are lit (the tree's Begin door keys off
  "intro"), observation detail preserved separately;
- markers clear when observations are discussed or dismissed, and
  serving attention writes nothing (no auto-surface on fetch);
- the turn path is untouched: the attention module imports no LLM
  machinery, and no conversation module imports the attention module
  (P2 adds zero turn-path cost — the scoring already runs inside
  P1's async derivation);
- acceptance shape (mapping test 4, P2 half): a task-completion
  observation for the Weaver lights her marker only, and discussing
  it clears the marker while keystone markers keep their meanings.

Stores are tmp SQLite files; the VE DB is isolated with the ve_ctx
pattern. No LLM is involved anywhere in this file.
"""

from __future__ import annotations

import ast
import threading
from pathlib import Path

import pytest

from local_ai.council import keystones as KD
from local_ai.council.jurisdictions import get_jurisdiction
from local_ai.fellowship import attention
from local_ai.fellowship.attention import (
    SeatRelevance,
    attention_for_user,
    reason_for_observation,
    score_relevance,
)
from local_ai.fellowship.events import FellowshipEvent
from local_ai.fellowship.observations import Observation, ObservationStore
from local_ai.vision_execution import keystone_seeding
from local_ai.vision_execution import models as M
from local_ai.vision_execution import service as ve

USER = "user-1"
OTHER = "user-2"

SEAT_REFS = [s["seat_ref"] for s in KD.SEATS]

# A message in the Weaver's (Conductor's) focus: competing priorities
# that do not fit together — the same fixture shape P1's tests use.
WEAVER_MESSAGE = (
    "I keep juggling three projects and nothing fits together — the "
    "priorities keep competing and the whole plan feels like it is detuning."
)
NEUTRAL_MESSAGE = "ok thanks, sounds good, see you tomorrow."


@pytest.fixture()
def store(tmp_path):
    return ObservationStore(db_path=tmp_path / "observations.db")


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    """Isolate the VE SQLite DB per test (test_keystones pattern)."""
    import local_ai.vision_execution.storage as ve_store

    monkeypatch.setattr(ve_store, "_DB_PATH", tmp_path / "ve.db")
    monkeypatch.setattr(ve_store, "_DB_DIR", tmp_path)
    monkeypatch.setattr(ve_store, "_init_done_paths", set())
    monkeypatch.setattr(ve_store, "_thread_local", threading.local())
    return {}


def _obs(store, seat="conductor", interpretation="Noted.", **kwargs):
    kwargs.setdefault("user_id", USER)
    kwargs.setdefault("event_ref", "evt-1")
    kwargs.setdefault("event_kind", "conversation_turn")
    kwargs.setdefault("evidence", "user words")
    kwargs.setdefault("evidence_kind", "quote")
    return store.add(seat=seat, interpretation=interpretation, **kwargs)


def _keystone_dark():
    """An unseeded keystone state: no markers lit, seeded False."""
    return {
        "seeded": False,
        "markers": {
            ref: {"attention": False, "reason": None} for ref in SEAT_REFS
        },
    }


def _lit(state):
    """{seat: reason} for lit markers."""
    return {
        ref: m["reason"] for ref, m in state["markers"].items() if m["attention"]
    }


# -- reason classification ----------------------------------------------------


def test_reason_question_is_clarify():
    obs = Observation(
        id="x", user_id=USER, seat="conductor", event_ref="e",
        event_kind="conversation_turn", evidence="w", evidence_kind="quote",
        interpretation="What does dependable mean here?",
    )
    assert reason_for_observation(obs) == "clarify"


def test_reason_contrast_is_challenge():
    obs = Observation(
        id="x", user_id=USER, seat="skeptic", event_ref="e",
        event_kind="conversation_turn", evidence="w", evidence_kind="quote",
        interpretation="This holds, but the evidence is thinner than it looks.",
    )
    assert reason_for_observation(obs) == "challenge"


def test_reason_proposal_is_offer():
    obs = Observation(
        id="x", user_id=USER, seat="mentor", event_ref="e",
        event_kind="conversation_turn", evidence="w", evidence_kind="quote",
        interpretation="Consider letting it rest for a season before deciding.",
    )
    assert reason_for_observation(obs) == "offer"


def test_reason_plain_is_discuss_and_empty_is_discuss():
    plain = Observation(
        id="x", user_id=USER, seat="conductor", event_ref="e",
        event_kind="conversation_turn", evidence="w", evidence_kind="quote",
        interpretation="The parts are pulling in different directions.",
    )
    assert reason_for_observation(plain) == "discuss"
    empty = Observation(
        id="x", user_id=USER, seat="conductor", event_ref="e",
        event_kind="conversation_turn", evidence="w", evidence_kind="quote",
        interpretation="",
    )
    assert reason_for_observation(empty) == "discuss"


def test_reason_word_boundaries_not_substrings():
    # "another" contains "not" as a substring; it is not a challenge.
    obs = Observation(
        id="x", user_id=USER, seat="conductor", event_ref="e",
        event_kind="conversation_turn", evidence="w", evidence_kind="quote",
        interpretation="Another thread worth following.",
    )
    assert reason_for_observation(obs) == "discuss"


def test_reason_precedence_question_beats_challenge_beats_offer():
    obs = Observation(
        id="x", user_id=USER, seat="conductor", event_ref="e",
        event_kind="conversation_turn", evidence="w", evidence_kind="quote",
        interpretation="This holds, but should we consider another way?",
    )
    assert reason_for_observation(obs) == "clarify"
    obs2 = Observation(
        id="x", user_id=USER, seat="conductor", event_ref="e",
        event_kind="conversation_turn", evidence="w", evidence_kind="quote",
        interpretation="This holds, but consider another way.",
    )
    assert reason_for_observation(obs2) == "challenge"


# -- relevance scoring --------------------------------------------------------


def _event(text):
    return FellowshipEvent(
        id="evt-1", kind="conversation_turn", user_id=USER,
        entity_type="", entity_id="", evidence_text=text, summary=text,
    )


def test_score_relevance_is_deterministic_and_pure():
    event = _event(WEAVER_MESSAGE)
    first = score_relevance(event)
    second = score_relevance(event)
    assert [r.to_dict() for r in first] == [r.to_dict() for r in second]
    assert first  # the Weaver-focus message scores at least one seat
    assert all(isinstance(r, SeatRelevance) for r in first)
    assert all(r.score > 0 for r in first)
    # Scores descend; ties break by seat id (candidate_seats' order).
    scores = [r.score for r in first]
    assert scores == sorted(scores, reverse=True)


def test_score_relevance_uses_jurisdiction_corpus():
    # An event written from the Mentor's own focus text scores the
    # Mentor on focus terms — the score comes from jurisdiction data,
    # not from a model.
    focus_text = get_jurisdiction("mentor").focus
    scored = {r.seat: r for r in score_relevance(_event(focus_text))}
    assert "mentor" in scored
    assert scored["mentor"].focus_terms


def test_score_relevance_neutral_event_scores_nobody():
    assert score_relevance(_event(NEUTRAL_MESSAGE)) == []


# -- read model: observations → markers --------------------------------------


def test_no_observations_no_markers(store):
    state = attention_for_user(USER, observation_store=store,
                                keystone_state=_keystone_dark())
    assert state["seeded"] is False
    assert _lit(state) == {}
    for ref in SEAT_REFS:
        marker = state["markers"][ref]
        assert marker["attention"] is False
        assert marker["reason"] is None
        assert marker["observation_count"] == 0
        assert marker["observation_ids"] == []


def test_pending_observation_lights_only_its_seat(store):
    obs = _obs(store, interpretation="What does dependable mean here?")
    state = attention_for_user(USER, observation_store=store,
                                keystone_state=_keystone_dark())
    assert _lit(state) == {"conductor": "clarify"}
    marker = state["markers"]["conductor"]
    assert marker["observation_reason"] == "clarify"
    assert marker["observation_ids"] == [obs.id]
    assert marker["observation_count"] == 1
    assert marker["keystone_reason"] is None


def test_multiple_observations_one_marker_reason_from_most_recent(store):
    _obs(store, interpretation="The parts are pulling apart.")
    latest = _obs(store, interpretation="Consider letting it rest.")
    state = attention_for_user(USER, observation_store=store,
                                keystone_state=_keystone_dark())
    marker = state["markers"]["conductor"]
    assert marker["attention"] is True
    assert marker["observation_count"] == 2
    assert len(marker["observation_ids"]) == 2
    assert marker["observation_reason"] == "offer"  # most recent wins
    assert marker["reason"] == "offer"


def test_surfaced_observations_still_light_markers(store):
    obs = _obs(store)
    store.set_status(USER, obs.id, "surfaced")
    state = attention_for_user(USER, observation_store=store,
                                keystone_state=_keystone_dark())
    assert _lit(state) == {"conductor": "discuss"}


def test_discussed_and_dismissed_clear_markers(store):
    discussed = _obs(store, interpretation="First.")
    store.set_status(USER, discussed.id, "surfaced")
    store.set_status(USER, discussed.id, "discussed")
    dismissed = _obs(store, interpretation="Second.")
    store.set_status(USER, dismissed.id, "dismissed")
    state = attention_for_user(USER, observation_store=store,
                                keystone_state=_keystone_dark())
    assert _lit(state) == {}


def test_serving_attention_writes_nothing(store):
    obs = _obs(store)
    attention_for_user(USER, observation_store=store,
                       keystone_state=_keystone_dark())
    assert store.get(USER, obs.id).status == "pending"  # no auto-surface


def test_attention_is_per_user(store):
    _obs(store, user_id=OTHER)
    state = attention_for_user(USER, observation_store=store,
                                keystone_state=_keystone_dark())
    assert _lit(state) == {}


def test_unknown_seat_observation_is_not_dropped(store):
    _obs(store, seat="not-a-seat")
    state = attention_for_user(USER, observation_store=store,
                                keystone_state=_keystone_dark())
    assert state["markers"]["not-a-seat"]["attention"] is True


# -- read model: keystone merge ----------------------------------------------


def _make_user(email="ally@example.com"):
    return ve.create_user_account(email, "pw-hunter2", "Ally")


def test_keystone_markers_unchanged_without_observations(store, ve_ctx):
    user = _make_user()
    keystone_state = keystone_seeding.keystone_attention(user["id"])
    state = attention_for_user(user["id"], observation_store=store,
                                keystone_state=keystone_state)
    assert state["seeded"] is False
    assert _lit(state) == {}


def test_keystone_reason_wins_reason_when_both_lit(store, ve_ctx):
    user = _make_user()
    keystone_seeding.seed_meet_your_council(user["id"])
    _obs(store, user_id=user["id"],
         interpretation="What does dependable mean here?")
    state = attention_for_user(user["id"], observation_store=store)
    marker = state["markers"]["conductor"]
    # The Begin door keys off reason == "intro": an observation must
    # never mask it. The observation reason survives separately.
    assert marker["reason"] == "intro"
    assert marker["keystone_reason"] == "intro"
    assert marker["observation_reason"] == "clarify"
    assert marker["attention"] is True


def test_observation_only_seat_uses_observation_reason(store, ve_ctx):
    user = _make_user()
    keystone_seeding.seed_meet_your_council(user["id"])
    # Fresh seed: only the Conductor carries a keystone marker; the
    # other seats wait for her intro. The Mentor's marker here comes
    # purely from its observation.
    _obs(store, user_id=user["id"], seat="mentor",
         interpretation="Consider letting it rest for a season.")
    state = attention_for_user(user["id"], observation_store=store)
    assert state["markers"]["mentor"]["reason"] == "offer"
    assert state["markers"]["mentor"]["keystone_reason"] is None


# -- acceptance shape: task observation → "!" → discuss clears ---------------


def test_task_observation_lights_weaver_only_and_discuss_clears(store):
    _obs(store, event_kind="task_completed",
         interpretation="Three priorities are competing for the same week.")
    state = attention_for_user(USER, observation_store=store,
                                keystone_state=_keystone_dark())
    assert _lit(state) == {"conductor": "discuss"}
    obs_id = state["markers"]["conductor"]["observation_ids"][0]
    store.set_status(USER, obs_id, "surfaced")
    store.set_status(USER, obs_id, "discussed")
    state = attention_for_user(USER, observation_store=store,
                                keystone_state=_keystone_dark())
    assert _lit(state) == {}


# -- no turn-path cost: import discipline ------------------------------------


def test_attention_module_imports_no_llm_machinery():
    package_file = Path(attention.__file__)
    banned_modules = {"openai", "anthropic", "ollama", "httpx", "requests"}
    banned_prefixes = (
        "local_ai.llm",
        "local_ai.providers",
        "local_ai.conversation",
    )
    tree = ast.parse(package_file.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        for name in names:
            root = name.split(".")[0]
            if root in banned_modules or name.startswith(banned_prefixes):
                offenders.append(name)
    assert offenders == []


def test_conversation_package_never_imports_attention():
    conv_dir = Path(attention.__file__).resolve().parent.parent / "conversation"
    offenders: list[str] = []
    for path in sorted(conv_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "local_ai.fellowship.attention" or (
                    module == "local_ai.fellowship"
                    and any(a.name == "attention" for a in node.names)
                ):
                    offenders.append(f"{path.name}: {module}")
            elif isinstance(node, ast.Import):
                if any(a.name == "local_ai.fellowship.attention"
                       for a in node.names):
                    offenders.append(path.name)
    assert offenders == []


# -- route --------------------------------------------------------------------


def test_route_returns_merged_model(store, ve_ctx, monkeypatch):
    from api.routes.vision_execution import get_keystone_attention

    monkeypatch.setattr(attention, "ObservationStore", lambda: store)
    user = _make_user()
    out = get_keystone_attention({"id": user["id"]})
    assert out["seeded"] is False
    assert _lit(out) == {}

    keystone_seeding.seed_meet_your_council(user["id"])
    _obs(store, user_id=user["id"],
         interpretation="What does dependable mean here?")
    out = get_keystone_attention({"id": user["id"]})
    assert out["seeded"] is True
    marker = out["markers"]["conductor"]
    assert marker["reason"] == "intro"  # keystone wins, door preserved
    assert marker["observation_reason"] == "clarify"
    assert marker["observation_count"] == 1
