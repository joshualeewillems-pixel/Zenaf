"""D4 progress condition (Gardener correction, 2026-11-07): a held
read-back must not stall indefinitely on question-ending replies.

After PROGRESS_PURSUIT_THRESHOLD (2) pursuit turns, the held read
speaks as its own bubble even when the turn's reply ends in a question.
Below the threshold the sequencing hold stands; without the progress
flag the ordinary delivery rule is unchanged. No quota on questions
or turns — the count is pursuit only.
"""

from __future__ import annotations

from local_ai.conversation import encounter as ENC
from local_ai.council import meetings as MT


class FakeHost:
    """Minimal EncounterHost: records everything, generates canned."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.said: list[str] = []
        self.frames: list[str] = []
        self.stored_impressions: list[str] = []

    def say(self, body: str) -> None:
        self.said.append(body)

    def generate(self, frame: str) -> str:
        self.frames.append(frame)
        return self.replies.pop(0) if self.replies else "A plain reply."

    def store_impression(self, claim: str, strands: list[str]) -> None:
        self.stored_impressions.append(claim)

    def store_response(self, text: str) -> None:
        pass

    def store_dimensions(self, seat_outcome: str, visitor_response: str) -> None:
        pass

    def close(self, wrap_line: str) -> None:
        pass


def _mentor_runtime():
    return ENC.EncounterRuntime(
        ENC.build_mentor_k1_definition(MT.MENTOR_FIRST_MEETING)
    )


def _held_state(**overrides):
    kwargs = dict(
        impression_pending_text="a held read",
        impression_pending_strands=["self"],
        impression_held_at_pursuit=0,
        pursuit_turns=0,
    )
    kwargs.update(overrides)
    return ENC.EncounterState(**kwargs)


# ------------------------------------------------------- unit: the delivery rule


def test_progress_threshold_is_two():
    assert ENC.PROGRESS_PURSUIT_THRESHOLD == 2


def test_progress_delivers_after_two_pursuit_turns():
    host = FakeHost([])
    state = _held_state(pursuit_turns=2)
    rt = _mentor_runtime()
    assert rt._deliver_pending_if_clear(
        host, state, "A question for you?", allow_progress=True
    ) is True
    assert state.impression_pending_text == ""
    assert state.impression_held_at_pursuit == 0
    assert state.impression_offered is True
    assert "a held read" in host.said
    assert "a held read" in host.stored_impressions


def test_progress_holds_below_threshold():
    host = FakeHost([])
    state = _held_state(pursuit_turns=1)
    rt = _mentor_runtime()
    assert rt._deliver_pending_if_clear(
        host, state, "A question for you?", allow_progress=True
    ) is False
    assert state.impression_pending_text == "a held read"
    assert state.impression_offered is False
    assert "a held read" not in host.said


def test_progress_does_not_fire_without_the_flag():
    # The ordinary call never delivers on a question-ending reply,
    # however many pursuit turns have passed.
    host = FakeHost([])
    state = _held_state(pursuit_turns=5)
    rt = _mentor_runtime()
    assert rt._deliver_pending_if_clear(host, state, "A question?") is False
    assert state.impression_pending_text == "a held read"


def test_progress_counts_from_the_hold_not_from_zero():
    # Held at pursuit 3, now at 4: one pursuit turn since the hold.
    host = FakeHost([])
    state = _held_state(pursuit_turns=4, impression_held_at_pursuit=3)
    rt = _mentor_runtime()
    assert rt._deliver_pending_if_clear(
        host, state, "A question?", allow_progress=True
    ) is False
    state.pursuit_turns = 5
    assert rt._deliver_pending_if_clear(
        host, state, "A question?", allow_progress=True
    ) is True


def test_hold_point_round_trips_in_state_json():
    state = _held_state(pursuit_turns=3, impression_held_at_pursuit=1)
    restored = ENC.EncounterState.from_json(state.to_json())
    assert restored.impression_held_at_pursuit == 1
    assert restored.impression_pending_text == "a held read"
    assert restored.pursuit_turns == 3


# ------------------------------------------------------- integration: the engage path


def test_engage_holds_impression_and_records_the_hold_point():
    host = FakeHost(["What would you do with it?\n---\nYou tend patiently.\nStrands: self"])
    state = ENC.EncounterState()
    _mentor_runtime().handle_turn(
        host, state,
        "I feel like I have a lot of talent but none of it is serving towards a viable life.",
        0,
    )
    assert state.impression_pending_text == "You tend patiently."
    assert state.impression_held_at_pursuit == state.pursuit_turns == 0
    assert state.impression_offered is False
    assert "You tend patiently." not in host.said


def test_engage_delivers_held_impression_after_two_pursuit_turns():
    host = FakeHost([
        "What do you make of that?\n---\nA fresh read.\nStrands: self",
        "And what then?\n---\nAnother fresh read.\nStrands: self",
    ])
    state = _held_state(material_turn=1, user_turns=2)
    rt = _mentor_runtime()
    # First pursuit turn: one turn since the hold — still held.
    rt.handle_turn(
        host, state,
        "I have been thinking about what to protect in my work lately.",
        0,
    )
    assert state.pursuit_turns == 1
    assert state.impression_pending_text == "a held read"
    assert state.impression_offered is False
    assert "a held read" not in host.said
    # Second pursuit turn: the threshold is met — the held read speaks
    # as its own bubble, after the question-ending reply.
    rt.handle_turn(
        host, state,
        "The same question keeps coming back to me in different forms.",
        0,
    )
    assert state.pursuit_turns == 2
    assert state.impression_pending_text == ""
    assert state.impression_held_at_pursuit == 0
    assert state.impression_offered is True
    assert "a held read" in host.said
    assert host.said[-1] == "a held read"
