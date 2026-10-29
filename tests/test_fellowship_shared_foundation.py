"""Fellowship shared foundation (2026-10-28) — mechanics built once,
not seven times.

Covers: the completion-intent signal and its ordering; the
confirmation action that actually completes (the loop fix) with NO
deterministic second-utterance auto-close rule; the pending-impression
EXPLICIT DISCARD on voluntary end (audit §6.1.2's deliver-or-discard
is SUPERSEDED — discard only, auditable); recognition/completion
separation and the ceiling no-manufacture rule; the continuity honesty
floor as shared machinery; the budget/cap machinery (uncapped
meeting-scoped reference section + guarded engage frame); and the
frontend affordance/hint. Layer B is ESTIMATE ONLY (see
docs/fellowship-layer-b-estimate.md) and is deliberately NOT built,
so it has no tests here.

Service-level tests reuse the MeetingService harness pattern from
tests/test_encounter_runtime.py (seeded VE user, tmp stores, fake
generator). No model is called and no provider key is used.
"""

from __future__ import annotations

import dataclasses
import threading
from pathlib import Path

import pytest

from local_ai.agent_intake.store import AgentStore
from local_ai.conversation import encounter as ENC
from local_ai.conversation.meeting import MeetingService, MeetingStore
from local_ai.conversation.reply import build_voice_prompt
from local_ai.conversation.store import ConversationStore
from local_ai.council import capabilities as CAP
from local_ai.council import meetings as MT
from local_ai.vision_execution import keystone_seeding
from local_ai.vision_execution import service as ve


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    import local_ai.vision_execution.storage as ve_store

    monkeypatch.setattr(ve_store, "_DB_PATH", tmp_path / "ve.db")
    monkeypatch.setattr(ve_store, "_DB_DIR", tmp_path)
    monkeypatch.setattr(ve_store, "_init_done_paths", set())
    monkeypatch.setattr(ve_store, "_thread_local", threading.local())
    return {}


class _Gen:
    """Fake generator: plain replies for turn frames, and a canned
    acknowledgement whenever the completion-path instruction is in
    the frame (the character naming the Complete action)."""

    def __init__(self):
        self.prompts: list[str] = []

    def __call__(self, prompt, **kwargs):
        self.prompts.append(prompt)
        if "tap 'Complete this meeting'" in prompt:
            return "Of course — tap 'Complete this meeting' below when you're ready."
        return "A plain reply."


def _svc(tmp_path, gen=None):
    return MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
        generate_fn=gen or _Gen(),
    )


def _svc_with_agents(tmp_path, gen=None):
    agents_db = tmp_path / "agents.db"
    svc = MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
        generate_fn=gen or _Gen(),
        agent_store_factory=lambda uid: AgentStore(agents_db, user_id=uid),
    )
    return svc, agents_db


def _seeded_user(email="shared-foundation@example.com"):
    user = ve.create_user_account(email, "pw", "SharedFoundation")
    keystone_seeding.seed_meet_your_council(user["id"])
    return user["id"]


def _enc_state(svc, uid):
    row = svc.meetings.get(uid, "conductor", 1)
    return ENC.EncounterState.from_json(row["state_json"])


def _bodies(state):
    return [m["body"] for m in state["messages"]]


def _set_pending(svc, uid, text="A held read."):
    row = svc.meetings.get(uid, "conductor", 1)
    state = ENC.EncounterState.from_json(row["state_json"])
    state.impression_pending_text = text
    state.impression_pending_strands = ["Logic"]
    svc.meetings.update(uid, "conductor", 1, state_json=state.to_json())


class _FakeHost:
    def __init__(self, gen_output=""):
        self.said: list[str] = []
        self.stored: list[str] = []
        self.responses: list[str] = []
        self.closed_with: list[str] = []
        self.gen_output = gen_output

    def say(self, body):
        self.said.append(body)

    def generate(self, frame):
        return self.gen_output

    def store_impression(self, claim, strands):
        self.stored.append(claim)

    def store_response(self, text):
        self.responses.append(text)

    def close(self, wrap_line):
        self.closed_with.append(wrap_line)


def _weaver_definition():
    script = MT.get_script("conductor", 1)
    definition = ENC.get_definition(script)
    return dataclasses.replace(
        definition,
        capability_context=CAP.first_meeting_block(
            "conductor", CAP.VisitorState(signed_in=True, consent_acknowledged=None)),
    )


# ------------------------------------------------------- 1. completion signal


def test_detect_move_completion_checked_before_question_rule():
    assert ENC.detect_move("we're done here?") == "completion"
    assert ENC.detect_move("we're done") == "completion"
    assert ENC.detect_move("I have to go") == "completion"
    assert ENC.detect_move("that's all") == "completion"
    assert ENC.detect_move("That's all for now, thanks") == "completion"
    # Unchanged neighbors: a real question still routes as one, and a
    # bare goodbye is NOT swept into completion (narrow list).
    assert ENC.detect_move("What is this supposed to do?") == "question"
    assert ENC.detect_move("ok, bye") != "completion"
    assert ENC.detect_move("I am done with this topic, let's move on") != "completion"


def test_single_completion_utterance_never_auto_closes(ve_ctx, tmp_path):
    uid = _seeded_user()
    gen = _Gen()
    svc = _svc(tmp_path, gen)
    script = MT.get_script("conductor", 1)
    svc.start(uid, "conductor")
    state = svc.turn(uid, "conductor", "Ok great so we're done here?")
    assert state["status"] == "active"
    assert state["completion_offered"] is True
    assert not any(p in _bodies(state) for p in script.reveal)
    # The offer turn names the Complete action; the record stays
    # honestly active (words and state agree).
    assert any("Complete this meeting" in b for b in _bodies(state))
    assert any("tap 'Complete this meeting'" in p for p in gen.prompts)


def test_no_auto_close_on_ambiguous_utterances(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    svc.start(uid, "conductor")
    svc.turn(uid, "conductor", "ok")
    state = svc.turn(uid, "conductor", "ok, sounds good")
    assert state["status"] == "active"
    assert state["completion_offered"] is False


# ------------------------------------------------------- 2. confirmation action


def test_loop_case_reaches_confirmation_on_restated_intent(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    script = MT.get_script("conductor", 1)
    svc.start(uid, "conductor")
    # Intent stated → path offered (not closed).
    state = svc.turn(uid, "conductor", "I think we're done")
    assert state["status"] == "active"
    assert state["completion_offered"] is True
    # Intent restated → the confirmation action, NOT another
    # "You can click Complete" loop: the meeting completes.
    state = svc.turn(uid, "conductor", "Yes, I'm saying we're done")
    assert state["status"] == "complete"
    assert state["stage"] == "complete"
    for paragraph in script.reveal:
        assert paragraph in _bodies(state)


def test_affirmation_after_offered_path_completes(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    script = MT.get_script("conductor", 1)
    svc.start(uid, "conductor")
    svc.turn(uid, "conductor", "I have to go")
    state = svc.turn(uid, "conductor", "yes")
    assert state["status"] == "complete"
    for paragraph in script.reveal:
        assert paragraph in _bodies(state)


def test_new_topic_after_offer_lapses_it_without_closing(ve_ctx, tmp_path):
    # This is what makes the rule NOT a blind second-utterance rule:
    # a second utterance that is neither an affirmation nor a
    # restated intent lapses the offer and continues normally.
    uid = _seeded_user()
    svc = _svc(tmp_path)
    svc.start(uid, "conductor")
    svc.turn(uid, "conductor", "that's all")
    state = svc.turn(uid, "conductor", "Actually, tell me more about the tree")
    assert state["status"] == "active"
    assert state["completion_offered"] is False


# ------------------------------------------------------- 4. explicit discard


def test_manual_complete_discards_pending_with_auditable_reason(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc, agents_db = _svc_with_agents(tmp_path)
    script = MT.get_script("conductor", 1)
    svc.start(uid, "conductor")
    _set_pending(svc, uid)
    state = svc.complete(uid, "conductor")
    assert state["status"] == "complete"
    enc = _enc_state(svc, uid)
    assert enc.impression_pending_text == ""
    assert enc.impression_pending_strands == []
    assert "manually" in enc.pending_impression_discarded
    assert state["pending_impression_discarded"] != ""
    # Never spoken, never filed, never an accepted claim.
    assert "A held read." not in _bodies(state)
    store = AgentStore(agents_db, user_id=uid)
    assert store.get_claims("meeting-conductor-1") == []
    for paragraph in script.reveal:
        assert paragraph in _bodies(state)


def test_confirmed_completion_discards_pending(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc, agents_db = _svc_with_agents(tmp_path)
    svc.start(uid, "conductor")
    _set_pending(svc, uid)
    state = svc.turn(uid, "conductor", "we're done")
    # The offer turn does NOT deliver the pending read: leaving
    # must not wait on a delivery.
    assert "A held read." not in _bodies(state)
    assert state["status"] == "active"
    state = svc.turn(uid, "conductor", "yes")
    assert state["status"] == "complete"
    enc = _enc_state(svc, uid)
    assert enc.impression_pending_text == ""
    assert "confirmed" in enc.pending_impression_discarded
    assert "A held read." not in _bodies(state)
    store = AgentStore(agents_db, user_id=uid)
    assert store.get_claims("meeting-conductor-1") == []


def test_complete_with_nothing_pending_is_unchanged(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc, agents_db = _svc_with_agents(tmp_path)
    svc.start(uid, "conductor")
    svc.turn(uid, "conductor", "What is this place for?")
    state = svc.complete(uid, "conductor")
    assert state["status"] == "complete"
    assert state["pending_impression_discarded"] == ""
    store = AgentStore(agents_db, user_id=uid)
    assert store.get_claims("meeting-conductor-1") == []


# ------------------------------------------------------- 5. separation + ceiling


def test_ceiling_files_nothing_when_gate_unsatisfied():
    definition = _weaver_definition()
    runtime = ENC.EncounterRuntime(definition)
    host = _FakeHost()
    state = ENC.EncounterState(user_turns=13, longest_user_turn="A long turn.")
    assert definition.impression_gate_objective != ""
    assert state.satisfied.get(definition.impression_gate_objective, False) is False
    runtime._wrap_turn(host, state)
    assert state.closed is True
    assert host.closed_with == [definition.wrap_line]
    assert host.stored == []
    assert host.responses == []


def test_ceiling_with_gate_satisfied_still_offers():
    definition = _weaver_definition()
    runtime = ENC.EncounterRuntime(definition)
    host = _FakeHost(
        gen_output="A first impression from the whole exchange.\nStrands: Compass")
    state = ENC.EncounterState(user_turns=13, longest_user_turn="A long turn.")
    state.satisfied[definition.impression_gate_objective] = True
    runtime._wrap_turn(host, state)
    assert state.closed is True
    assert state.impression_offered is True
    assert host.stored == ["A first impression from the whole exchange."]
    # And the filing is grounded in the visitor's own words.
    assert host.responses == ["A long turn."]


def test_settled_close_floor_retained_and_close_without_impression():
    # Separation, stated as two facts: (a) the semantic settled
    # close still requires the meaningful-recognition floor — the
    # floor is retained, not silently dropped; (b) a settled close
    # completes without any filed impression when no impression
    # stands (filing reads the stored claim; none exists here).
    definition = _weaver_definition()
    runtime = ENC.EncounterRuntime(definition)
    host = _FakeHost()
    state = ENC.EncounterState(impression_answered=True)
    runtime._close_or_continue(host, state, "Yes, that's right.", "settled")
    assert state.closed is False
    assert host.closed_with == []
    for floor_id in definition.close_floor_objectives:
        state.satisfied[floor_id] = True
    runtime._close_or_continue(host, state, "Yes, that's right.", "settled")
    assert state.closed is True
    assert host.closed_with == [""]
    assert host.stored == []


def test_state_json_round_trip_for_new_fields():
    state = ENC.EncounterState(
        completion_offered=True,
        pending_impression_discarded="visitor completed manually",
    )
    restored = ENC.EncounterState.from_json(state.to_json())
    assert restored.completion_offered is True
    assert restored.pending_impression_discarded == "visitor completed manually"
    # Old rows without the fields still hydrate (forward compat).
    legacy = ENC.EncounterState.from_json('{"user_turns": 3}')
    assert legacy.completion_offered is False
    assert legacy.pending_impression_discarded == ""


# ------------------------------------------------------- 7 + 8. budget machinery


def test_engage_frame_guarded_honesty_guard_position():
    # Weaver's current frames, composed for real: the engage frame
    # fits the 8,000-char cap with headroom, and the honesty guard
    # is no longer the last content — the variable-length naming
    # note sits after the capability block, so truncation would eat
    # the naming note first, never the guard.
    definition = _weaver_definition()
    runtime = ENC.EncounterRuntime(definition)
    frame = runtime._engage_frame()
    assert len(frame) <= 8000
    assert len(frame) >= 300  # sanity: a real frame, not an empty one
    assert CAP.HONESTY_GUARD in frame
    guard_at = frame.index(CAP.HONESTY_GUARD)
    naming_at = frame.index("Other seats: roles until met.")
    assert guard_at < naming_at
    # Budget (measured here, reported in the PR description):
    # engage frame must leave >= 300 chars of headroom.
    assert 8000 - len(frame) >= 300


def test_fellowship_reference_is_an_uncapped_section():
    long_reference = "Fellowship knowledge. " * 1000  # 21,000 chars
    lines, _ = build_voice_prompt(
        "u1", "conductor", "hello", [],
        extra_instructions="x" * 9000,
        fellowship_reference=long_reference,
    )
    joined = "\n".join(lines)
    assert long_reference.strip() in joined  # NOT truncated
    assert ("x" * 9000) not in joined  # the frame cap still applies
    assert any(len(line) == 8000 for line in lines)
    # Empty reference = section absent (byte-identical prompt shape).
    lines2, _ = build_voice_prompt("u1", "conductor", "hello", [])
    assert not any("Fellowship reference" in line for line in lines2)


def test_continuity_honesty_floor_is_shared_machinery():
    short_history = [{"role": "user", "content": f"turn {i}"} for i in range(10)]
    lines, _ = build_voice_prompt("u1", "conductor", "hello", short_history)
    assert not any("don't remember" in line for line in lines)
    long_history = [{"role": "user", "content": f"turn {i}"} for i in range(12)]
    lines, _ = build_voice_prompt("u1", "conductor", "hello", long_history)
    assert any("don't remember" in line for line in lines)
    # Shared, not per-seat: the same builder line fires for any seat.
    lines, _ = build_voice_prompt("u1", "guardian", "hello", long_history)
    assert any("don't remember" in line for line in lines)


def test_parser_contract_delimiter_intact():
    definition = _weaver_definition()
    runtime = ENC.EncounterRuntime(definition)
    reply, impression, had_delim = runtime._split_reply_and_impression(
        "A reply.\n---\nA first read.\nStrands: Logic")
    assert had_delim is True
    assert reply == "A reply."
    assert impression == "A first read.\nStrands: Logic"
    reply2, _, had_delim2 = runtime._split_reply_and_impression("No delimiter here.")
    assert had_delim2 is False
    assert reply2 == ""


# ------------------------------------------------------- 3. frontend affordance


def test_frontend_complete_promoted_and_hint_rendered():
    # Structural test in the repo's frame-content-assertion pattern:
    # the active footer's Complete action is a primary bordered
    # button (the paused pattern), not small grey underlined text,
    # and the conversation-visible hint renders from the
    # controller-visible `completion_offered` signal.
    src = (Path(__file__).resolve().parent.parent
           / "frontend" / "src" / "living-tree" / "MeetingView.tsx").read_text()
    assert "completion_offered" in src
    assert "She heard you want to finish" in src
    label_at = src.index("Complete this meeting — we’re done here")
    button_at = src.rfind("<button", 0, label_at)
    active_complete = src[button_at:label_at]
    assert "rounded-full" in active_complete
    assert "border" in active_complete
    assert "text-stone-400 underline" not in active_complete
    # The route is untouched: the button still calls completeMeeting.
    assert "completeMeeting" in src
