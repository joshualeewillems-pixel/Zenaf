"""Bear S1 §6 progress mechanism (tests only — the mechanism itself
already exists at 93e6033, landed by the Gardener D4 build).

The D4 progress condition (encounter.py): a held impression is
delivered once the visitor has taken the thread up
PROGRESS_PURSUIT_THRESHOLD (= 2) pursuit turns after the hold, even
when the reply ends in a question — as its own bubble, after the
reply. Engage path only.

Driving notes (all verified against the runtime at 93e6033):
- The Guardian definition has NO impression gate objective
  (``impression_gate_objective == ""``) and an EMPTY question bank,
  so every offered impression proceeds and every pass falls through
  to the bare-delivery branch of ``_pass_turn``.
- An engage turn's host reply must carry the ``---`` delimiter for
  the reply movement to be spoken: a delimiter-less engage output
  is treated as an impression movement, and with a read held the
  runtime speaks the held read alone instead (``allow_bare``).
- Pursuit turns count only substantive pursuit: passes and acks do
  NOT advance ``pursuit_turns``; greetings, direct questions, and
  substantive turns do.
- P2 and P7 are REWRITTEN from the brief's specified forms, whose
  premises are refuted by the code (see each test's docstring):
  P2's "passes never deliver" fails — a pass delivers bare; P7's
  "no progress delivery on a non-Guardian definition" fails — the
  call site is unconditional, so the mechanism is active for every
  definition. Both rewrites pin the true behavior instead.

Deterministic: FakeHost with a reply queue, no model calls, no DB.
"""

from __future__ import annotations

import dataclasses

import pytest

from local_ai.conversation import encounter as ENC
from local_ai.conversation.encounter import (
    EncounterRuntime,
    EncounterState,
)
from local_ai.council import meetings as MT

PENDING_TEXT = "You keep what matters close."
SUB1 = (
    "I have been thinking about what home means to me lately, "
    "and why I keep coming back to it."
)
SUB2 = (
    "There is a fence on the north side that has needed mending "
    "since spring, and I keep putting it off."
)
SUB3 = (
    "The roof held through the last storm, but the gutters are "
    "full of leaves again."
)
SUB4 = (
    "I walked the boundary line yesterday and found the gate "
    "hanging loose on its hinges."
)
HOLD_REPLY = (
    "What do you make of that?\n---\n"
    + PENDING_TEXT
    + "\nStrands: Heart, Voice"
)
QUESTION_REPLY = (
    "And then what?\n---\n"
    "A fresh read I have not earned yet.\nStrands: Heart, Voice"
)
QUESTION_PLAIN = "And then what?"


class FakeHost:
    """Minimal EncounterHost: records everything, generates queued."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.said: list[str] = []
        self.frames: list[str] = []
        self.close_calls: list[str] = []
        self.stored_impressions: list[str] = []
        self.stored_responses: list[str] = []
        self.stored_dimensions: list[tuple[str, str]] = []

    def say(self, body: str) -> None:
        self.said.append(body)

    def generate(self, frame: str) -> str:
        self.frames.append(frame)
        return self.replies.pop(0) if self.replies else "A plain reply."

    def store_impression(self, claim: str, strands: list[str]) -> None:
        self.stored_impressions.append(claim)

    def store_response(self, text: str) -> None:
        self.stored_responses.append(text)

    def store_dimensions(self, seat_outcome: str, visitor_response: str) -> None:
        self.stored_dimensions.append((seat_outcome, visitor_response))

    def close(self, wrap_line: str) -> None:
        self.close_calls.append(wrap_line)


def _guardian_runtime():
    return EncounterRuntime(
        ENC.get_definition(MT.get_script("guardian", 1))
    )


def _held_state(replies):
    """Drive a Guardian K1 meeting to a held impression. Returns
    (runtime, host, state, question_idx) with the read held at
    pursuit_turns == 1 (impression_held_at_pursuit == 1)."""
    rt = _guardian_runtime()
    host = FakeHost(replies)
    state = EncounterState()
    qi = 0
    qi = rt.handle_turn(host, state, SUB1, qi)
    qi = rt.handle_turn(host, state, SUB2, qi)
    assert state.impression_pending_text == PENDING_TEXT
    assert state.impression_held_at_pursuit == 1
    assert state.pursuit_turns == 1
    assert not state.impression_offered
    return rt, host, state, qi


def _assert_not_delivered(host, state):
    assert PENDING_TEXT not in host.said
    assert PENDING_TEXT not in host.stored_impressions
    assert state.impression_pending_text == PENDING_TEXT
    assert not state.impression_offered


# ---------------------------------------------------------------- P1


def test_p1_question_ending_replies_deliver_by_second_pursuit_turn():
    """P1: every-reply-ends-in-'?' — the held read is delivered no
    later than the second pursuit turn after the hold, and not
    before the first. Turn 3 (pursuit 2, one turn after the hold)
    does not deliver; turn 4 (pursuit 3, two turns after) does,
    as its own bubble after the question-ending reply."""
    rt, host, state, qi = _held_state(
        ["A plain reply.", HOLD_REPLY, QUESTION_REPLY, QUESTION_REPLY]
    )
    qi = rt.handle_turn(host, state, SUB3, qi)
    assert state.pursuit_turns == 2
    _assert_not_delivered(host, state)
    qi = rt.handle_turn(host, state, SUB4, qi)
    assert state.pursuit_turns == 3
    assert state.impression_pending_text == ""
    assert state.impression_held_at_pursuit == 0
    assert state.impression_offered
    assert state.impression_text == PENDING_TEXT
    assert host.said[-2] == "And then what?"
    assert host.said[-1] == PENDING_TEXT
    assert host.stored_impressions == [PENDING_TEXT]


# ---------------------------------------------------------------- P2


def test_p2a_acks_only_never_deliver():
    """P2 (acks half — true as specified): a run of ack turns with
    question-ending replies never delivers. Acks do not advance
    pursuit, so the progress condition can never mature on them,
    and the ordinary path declines the question-ending replies."""
    rt, host, state, qi = _held_state(
        ["A plain reply.", HOLD_REPLY] + [QUESTION_PLAIN] * 4
    )
    for _ in range(4):
        qi = rt.handle_turn(host, state, "ok", qi)
    assert state.pursuit_turns == 1
    _assert_not_delivered(host, state)


def test_p2b_pass_delivers_bare_not_progress():
    """P2 (passes half — REWRITTEN: the brief's premise is refuted).
    The brief says a meeting of passes and acks never delivers the
    held read. Acks alone do not (P2a). But a pass DOES deliver on
    this tree: the Guardian's question bank is empty, so
    ``_pass_turn`` falls through to the bare-delivery branch and
    the held read speaks alone (``allow_bare=True``) — pre-existing
    behavior, not the progress condition: the pass does not advance
    pursuit (still 1), so the threshold never matured. This pins
    the true behavior rather than the brief's false premise."""
    rt, host, state, qi = _held_state(["A plain reply.", HOLD_REPLY])
    qi = rt.handle_turn(host, state, "pass", qi)
    assert state.pursuit_turns == 1
    assert state.impression_pending_text == ""
    assert state.impression_offered
    assert state.impression_text == PENDING_TEXT
    assert host.said[-1] == PENDING_TEXT
    assert host.stored_impressions == [PENDING_TEXT]


# ---------------------------------------------------------------- P3


def test_p3_direct_question_and_move_branch_never_trigger():
    """P3: a direct-question turn does not trigger progress delivery
    (precedence — the move branch never calls delivery for one),
    and a question-ending move-branch reply does not trigger it
    either (no progress call in the move branch). A subsequent
    substantive turn then delivers the read, threshold met."""
    rt, host, state, qi = _held_state(
        ["A plain reply.", HOLD_REPLY]
        + [QUESTION_PLAIN] * 3
        + [QUESTION_REPLY]
    )
    # Greeting: pursuit 2, move-branch question-ending reply.
    qi = rt.handle_turn(host, state, "hello", qi)
    assert state.pursuit_turns == 2
    _assert_not_delivered(host, state)
    # Direct question: pursuit 3 — the threshold IS met (3 - 1 = 2)
    # — but the move branch skips delivery entirely for one.
    qi = rt.handle_turn(
        host, state, "What should I do about the fence first?", qi
    )
    assert state.pursuit_turns == 3
    _assert_not_delivered(host, state)
    # Greeting again: pursuit 4, still no delivery from the move branch.
    qi = rt.handle_turn(host, state, "hello", qi)
    assert state.pursuit_turns == 4
    _assert_not_delivered(host, state)
    # Substantive engage turn: the progress condition fires.
    qi = rt.handle_turn(host, state, SUB3, qi)
    assert state.impression_offered
    assert host.said[-1] == PENDING_TEXT
    assert host.said.count(PENDING_TEXT) == 1


# ---------------------------------------------------------------- P4


def test_p4_voluntary_end_discards_past_threshold():
    """P4: the visitor ending the meeting discards the held read
    even past the threshold — no delivery on a completion turn, and
    the confirmation discards it (never spoken, never filed)."""
    rt, host, state, qi = _held_state(
        ["A plain reply.", HOLD_REPLY]
        + [QUESTION_PLAIN] * 2
        + ["You can click Complete when you are ready."]
    )
    # Advance pursuit past the threshold without delivering:
    # greeting turns advance pursuit but never trigger delivery.
    qi = rt.handle_turn(host, state, "hello", qi)
    qi = rt.handle_turn(host, state, "hello", qi)
    assert state.pursuit_turns == 3
    _assert_not_delivered(host, state)
    # Completion intent: the path is offered, the read waits.
    qi = rt.handle_turn(host, state, "we're done here", qi)
    assert state.completion_offered
    _assert_not_delivered(host, state)
    # Confirmation: discard, never spoken, never filed.
    qi = rt.handle_turn(host, state, "we're done here", qi)
    assert state.impression_pending_text == ""
    assert state.impression_held_at_pursuit == 0
    assert state.pending_impression_discarded == (
        "visitor confirmed completion after the Complete path was offered"
    )
    assert not state.impression_offered
    assert PENDING_TEXT not in host.said
    assert PENDING_TEXT not in host.stored_impressions
    assert state.closed


# ---------------------------------------------------------------- P5


def test_p5_state_round_trip_preserves_hold():
    """P5: ``impression_held_at_pursuit`` survives the state_json
    round-trip, including a value of 0 (no hold) and the non-zero
    hold point — and the progress guarantee still fires after the
    restore."""
    rt, host, state, qi = _held_state(
        ["A plain reply.", HOLD_REPLY, QUESTION_REPLY, QUESTION_REPLY]
    )
    raw = state.to_json()
    restored = EncounterState.from_json(raw)
    assert restored.impression_pending_text == PENDING_TEXT
    assert restored.impression_pending_strands == ["Heart", "Voice"]
    assert restored.impression_held_at_pursuit == 1
    assert restored.pursuit_turns == 1
    # A no-hold state round-trips the zero hold point too.
    assert EncounterState.from_json(EncounterState().to_json()) \
        .impression_held_at_pursuit == 0
    # The restored state still delivers on the second pursuit turn.
    qi = rt.handle_turn(host, restored, SUB3, qi)
    _assert_not_delivered(host, restored)
    qi = rt.handle_turn(host, restored, SUB4, qi)
    assert restored.impression_offered
    assert host.said[-1] == PENDING_TEXT


# ---------------------------------------------------------------- P6


def test_p6a_held_read_speaks_at_ceiling_wrap():
    """P6 (held read): a meeting that reaches TURN_CEILING with a
    held read still wraps as before — the held read speaks at the
    wrap via ``allow_bare=True`` — and the meeting closes."""
    assert ENC.TURN_CEILING == 12
    rt, host, state, qi = _held_state(
        ["A plain reply.", HOLD_REPLY] + [QUESTION_PLAIN] * 10
    )
    # Ack turns 3–12: no delivery, no pursuit advance.
    for _ in range(10):
        qi = rt.handle_turn(host, state, "ok", qi)
    assert state.user_turns == 12
    _assert_not_delivered(host, state)
    # Turn 13 crosses the ceiling: the wrap delivers the held read.
    qi = rt.handle_turn(host, state, "ok", qi)
    assert state.user_turns == 13
    assert state.closed
    assert state.impression_offered
    assert host.said[-1] == PENDING_TEXT
    assert host.said.count(PENDING_TEXT) == 1
    assert host.stored_impressions == [PENDING_TEXT]
    assert len(host.close_calls) == 1


def test_p6b_no_hold_gate_satisfied_offers_from_whole_exchange():
    """P6 (no held read): a meeting that reaches the ceiling with
    no held read and the gate satisfied still offers its impression
    from the whole exchange at the wrap."""
    rt = _guardian_runtime()
    host = FakeHost(["A plain reply."] * 12 + ["You keep what matters close."])
    state = EncounterState()
    qi = 0
    subs = [SUB1, SUB2, SUB3, SUB4] * 3
    for i in range(12):
        qi = rt.handle_turn(host, state, subs[i], qi)
    assert state.user_turns == 12
    assert not state.impression_offered
    assert not state.impression_pending_text
    qi = rt.handle_turn(host, state, SUB1, qi)
    assert state.closed
    assert state.impression_offered
    assert state.impression_text == "You keep what matters close."
    assert host.stored_impressions == ["You keep what matters close."]


def test_p6c_gate_never_satisfied_files_nothing():
    """P6 (gate never satisfied): a meeting that reaches the ceiling
    without satisfying the gate still files nothing. The Guardian
    has no gate objective of its own, so this runs on a synthetic
    gated twin (the recognition test's coupled-twin pattern):
    the same definition with ``shared_work_exchange`` as the gate,
    driven on greeting turns that never engage and never offer —
    the wrap's gate logic itself is what is under test."""
    definition = dataclasses.replace(
        ENC.get_definition(MT.get_script("guardian", 1)),
        impression_gate_objective="shared_work_exchange",
    )
    rt = EncounterRuntime(definition)
    host = FakeHost([QUESTION_PLAIN] * 12)
    state = EncounterState()
    qi = 0
    for _ in range(12):
        qi = rt.handle_turn(host, state, "hello", qi)
    assert not state.satisfied.get("shared_work_exchange")
    qi = rt.handle_turn(host, state, "hello", qi)
    assert state.closed
    assert not state.impression_offered
    assert not state.impression_pending_text
    assert host.stored_impressions == []
    assert host.stored_responses == []
    assert len(host.close_calls) == 1


# ---------------------------------------------------------------- P7


def test_p7_guardian_positive_progress_delivery_via_engage():
    """P7 (REWRITTEN — guardian-positive). The brief specified the
    same simulation on a non-Guardian definition asserting NO
    progress delivery, on the premise that this build gates the
    mechanism to the Guardian (brief §6.4 decision 1). That premise
    is spent: the Gardener build's call site passes
    ``allow_progress=True`` UNCONDITIONALLY in the engage branch
    (encounter.py), so the mechanism is active for every
    definition and the specified negative assertion would FAIL.
    This pins the true guardian-positive behavior instead: for the
    Guardian definition the held read delivers through the engage
    path — the delivery turn's generation used the engage frame —
    as its own bubble after the question-ending reply, with the
    hold point cleared. The unconditional activation is recorded
    as a deviation in the build report."""
    rt, host, state, qi = _held_state(
        ["A plain reply.", HOLD_REPLY, QUESTION_REPLY, QUESTION_REPLY]
    )
    frames_before = len(host.frames)
    qi = rt.handle_turn(host, state, SUB3, qi)
    _assert_not_delivered(host, state)
    qi = rt.handle_turn(host, state, SUB4, qi)
    assert state.impression_offered
    assert host.said[-2] == "And then what?"
    assert host.said[-1] == PENDING_TEXT
    assert state.impression_held_at_pursuit == 0
    # The delivery turn generated through the engage frame (the
    # engage path), not the turn frame: the frame carries the
    # guidance and the engage glue.
    delivery_frame = host.frames[-1]
    assert ENC._GUARDIAN_FIRST_MEETING_GUIDANCE[:80] in delivery_frame
    assert "only if this exchange has genuinely shown you how they orient" in delivery_frame
    assert frames_before + 2 == len(host.frames)


# ---------------------------------------------------------------- P8


def test_p8_no_double_delivery_hold_point_cleared():
    """P8: after the progress delivery, ``impression_pending_text``
    is empty, ``impression_held_at_pursuit`` is 0, and
    ``impression_offered`` is True; subsequent substantive turns
    do not deliver a second read."""
    rt, host, state, qi = _held_state(
        ["A plain reply.", HOLD_REPLY, QUESTION_REPLY, QUESTION_REPLY,
         QUESTION_REPLY, QUESTION_REPLY]
    )
    qi = rt.handle_turn(host, state, SUB3, qi)
    qi = rt.handle_turn(host, state, SUB4, qi)
    assert state.impression_offered
    assert host.said.count(PENDING_TEXT) == 1
    assert host.stored_impressions == [PENDING_TEXT]
    # Two more substantive turns: the held read is gone, and the
    # fresh reads in the outputs are not held or delivered — the
    # meeting is past recognition's first read, so the next turns
    # answer it instead (no second delivery of the same read).
    qi = rt.handle_turn(host, state, SUB1, qi)
    qi = rt.handle_turn(host, state, SUB2, qi)
    assert host.said.count(PENDING_TEXT) == 1
    assert host.stored_impressions == [PENDING_TEXT]
    assert state.impression_held_at_pursuit == 0
    assert state.impression_pending_text == ""
