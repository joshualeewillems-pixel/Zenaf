"""The encounter tutorial-beat mechanism (Joshua, 2026-10-24).

Ratified design: a seat's first meeting must leave the user knowing
what that seat is FOR — its terrain, what the visitor does with it,
and why it wanted to meet — drawn from its feature-focus slice.
The beats ride the conversational frame as standing hopes (never a
lecture block); steering pressure grows with the turns; after the
seat's own patience of exchanges the frame instructs an honest pivot
("let's set that aside for now, why I wanted to talk was…") that
OWNS the direction change; and the close requires every beat
COVERED — covered meaning the beat's essential information was
actually communicated in a spoken turn. The pivot NEVER satisfies
the gate on its own: it redirects toward uncovered beats, and a
pivot response satisfies the gate only by covering beats with
content, under the same rule as any other turn. Beat markers are
the model's own claims, so a claim counts only with content: the
stripped spoken body must hit one of the beat's content anchors.
The Weaver playtest of 2026-10-24 closed tutorial-less after ~3
user turns; under this mechanism it extends with the pivot instead
— and still does not close until the teaching is actually done.

Constraints pinned here alongside the mechanism: no new LLM call
per turn (the gradient is frame instruction; beat recognition rides
the generation call the meeting already makes, via stripped
bookkeeping trailers); the Weaver's authored introduction stays
byte-identical; everything the #200 correction protected
(recognition floor, semantic close, dictionaries, Mad Lib law,
hedge-names-its-claim, queueDrained gating, one generation/turn,
no-pretend) keeps passing in the existing suites.
"""

from __future__ import annotations

import pytest

from local_ai.conversation import encounter as ENC
from local_ai.conversation import tutorial_beats as TB
from local_ai.council import meetings as MT


# ---------------------------------------------------------------------------
# The data: seven checklists, one patience table, no gaps or overlaps.
# ---------------------------------------------------------------------------

SEAT_IDS = (
    "conductor", "mentor", "champion", "guardian",
    "ambassador", "skeptic", "maverick",
)

EXPECTED_PATIENCE = {
    "champion": 2,    # Firebrand
    "ambassador": 7,  # Crane
    "conductor": 5,   # Weaver
    "mentor": 6,      # Gardener
    "guardian": 4,    # Bear
    "skeptic": 6,     # Raven
    "maverick": 3,    # Fox
}


def test_every_seat_has_exactly_three_beats():
    for seat in SEAT_IDS:
        beats = TB.beats_for(seat)
        assert len(beats) == 3, seat
        assert [b.kind for b in beats] == [
            "terrain", "involvement", "why_meet",
        ], seat
        assert [b.id for b in beats] == [
            f"{seat}:terrain", f"{seat}:involvement", f"{seat}:why_meet",
        ], seat
        for beat in beats:
            assert beat.title and beat.teaching, (seat, beat.id)


def test_patience_table_is_exact_and_lives_with_the_seat():
    assert TB.SEAT_PATIENCE == EXPECTED_PATIENCE
    for seat in SEAT_IDS:
        assert TB.patience_for(seat) == EXPECTED_PATIENCE[seat]
    assert TB.patience_for("unknown-seat") == 0
    assert TB.beats_for("unknown-seat") == ()


def test_checklists_tile_the_system_without_overlap():
    teachings = []
    for seat in SEAT_IDS:
        for beat in TB.beats_for(seat):
            teachings.append(beat.teaching)
    # No two seats teach the same slice in the same words.
    assert len(set(teachings)) == len(teachings)
    # Every seat's terrain names its own ground, not another's.
    terrains = {
        seat: TB.beats_for(seat)[0].teaching for seat in SEAT_IDS
    }
    assert "council and the tree" in terrains["conductor"]
    assert "follow-through" in terrains["champion"]
    assert "consent scopes" in terrains["guardian"]
    assert "echo rentals" in terrains["ambassador"]
    assert "review queue" in terrains["skeptic"]
    assert "bring-your-own key" in terrains["maverick"]
    assert "snapshots and eras" in terrains["mentor"]


# ---------------------------------------------------------------------------
# The gradient: pressure scales with turn count against patience.
# ---------------------------------------------------------------------------

def _weaver_beats():
    return TB.beats_for("conductor")


def test_guidance_tiers_scale_with_turn_count():
    beats = _weaver_beats()
    light = TB.tutorial_guidance(beats, set(), 1, 5, False)
    light2 = TB.tutorial_guidance(beats, set(), 2, 5, False)
    gentle = TB.tutorial_guidance(beats, set(), 3, 5, False)
    gentle2 = TB.tutorial_guidance(beats, set(), 4, 5, False)
    pivot = TB.tutorial_guidance(beats, set(), 5, 5, False)
    assert "will find its moment" in light
    assert "will find its moment" in light2
    assert "set that aside" not in light
    assert "natural opening" in gentle
    assert "natural opening" in gentle2
    assert "set that aside" not in gentle
    assert "set that aside" in pivot
    assert "why I wanted to talk" in pivot
    assert "never fake a natural segue" in pivot
    assert light != gentle != pivot


def test_guidance_is_empty_when_there_is_nothing_to_teach():
    beats = _weaver_beats()
    covered = {b.id for b in beats}
    assert TB.tutorial_guidance(beats, covered, 9, 5, False) == ""
    assert TB.tutorial_guidance(beats, covered, 9, 5, True) == ""
    assert TB.tutorial_guidance((), set(), 9, 5, False) == ""
    assert TB.tutorial_guidance(beats, set(), 9, 0, False) == ""


def test_guidance_stays_at_maximum_after_a_pivot():
    # Correction 2026-10-24: a pivot redirects, it does not satisfy.
    # Steering must NOT relax once the pivot is delivered — it stays
    # at maximum until the beats are covered, and it must not
    # re-instruct a set-aside that already happened.
    beats = _weaver_beats()
    guide = TB.tutorial_guidance(beats, set(), 6, 5, True)
    assert guide != ""
    assert "deliver what is still untaught" in guide
    assert "set that aside" not in guide


@pytest.mark.parametrize("seat,patience", sorted(EXPECTED_PATIENCE.items()))
def test_fallback_fires_at_exactly_each_seats_threshold(seat, patience):
    beats = TB.beats_for(seat)
    for turn in range(1, patience):
        guide = TB.tutorial_guidance(beats, set(), turn, patience, False)
        assert "set that aside" not in guide, (seat, turn)
    at = TB.tutorial_guidance(beats, set(), patience, patience, False)
    assert "set that aside" in at, seat
    assert "why I wanted to talk" in at, seat


def test_pivot_honesty_markers():
    assert TB.pivot_delivered_in(
        "Let's set that aside for now, why I wanted to talk was "
        "the orchestra itself.")
    assert not TB.pivot_delivered_in(
        "Speaking of which, let me tell you about the council.")
    assert not TB.pivot_delivered_in("A plain reply.")
    assert TB.PIVOT_SET_ASIDE_MARKER == "set that aside"


# ---------------------------------------------------------------------------
# The Weaver's definition: beats wired, introduction untouched.
# ---------------------------------------------------------------------------

WEAVER_INTRODUCTION_VERBATIM = (
    "Ah! A new instrument for the orchestra! Bass? Woodwind? Percussion, perhaps? Well, we'll find your sound soon enough.",
    "You know, some of my friends swear by rigorous training, perfect pitch, and rhythmic precision. Others would find that positively suffocating. They prefer the wild improvisations of jazz.",
    "I've spent a lifetime fascinated by the possibility of synthesizing “classical jazz”—finding harmony among wildly different voices without sacrificing what makes each one extraordinary.",
    "Every so often, it happens quite naturally. Beautifully, even. Which leaves me wondering… can something so spontaneous ever be composed deliberately? Are we more honest humbled before its ineffability? Or is the question itself a misunderstanding",
)


def test_weaver_introduction_is_byte_identical():
    # Joshua's authored text, verbatim — including the curly quotes
    # around classical jazz, the unspaced em dash, the ellipsis, the
    # "more honest humbled" phrasing, and bubble 4's missing terminal
    # punctuation. Any change here is a change to his words.
    assert MT.WEAVER_INTRODUCTION == WEAVER_INTRODUCTION_VERBATIM
    script = MT.get_script("conductor", 1)
    definition = ENC.get_definition(script)
    assert definition.opening == WEAVER_INTRODUCTION_VERBATIM


def test_weaver_definition_carries_beats_and_patience():
    definition = ENC.get_definition(MT.get_script("conductor", 1))
    assert definition.tutorial_beats == TB.beats_for("conductor")
    assert definition.tutorial_patience == 5
    # The generic shape carries no tutorial gate.
    generic = ENC.build_definition(MT.get_script("conductor", 1))
    assert generic.tutorial_beats == ()
    assert generic.tutorial_patience == 0


# ---------------------------------------------------------------------------
# The runtime: frames, markers, pivot, and the close gate.
# ---------------------------------------------------------------------------

class _FakeHost:
    """The encounter host protocol, recorded — for driving the
    runtime directly."""

    def __init__(self, gen_output=""):
        self.said: list[str] = []
        self.generated_frames: list[str] = []
        self.gen_output = gen_output
        self.impressions: list[tuple[str, list[str]]] = []
        self.closed_with: str | None = None
        self.close_calls = 0

    def say(self, body: str) -> None:
        self.said.append(body)

    def generate(self, frame: str) -> str:
        self.generated_frames.append(frame)
        return self.gen_output

    def store_impression(self, claim: str, strands: list[str]) -> None:
        self.impressions.append((claim, strands))

    def store_response(self, text: str) -> None:
        pass

    def close(self, wrap_line: str) -> None:
        self.closed_with = wrap_line
        self.close_calls += 1


def _weaver_runtime():
    definition = ENC.get_definition(MT.get_script("conductor", 1))
    return ENC.EncounterRuntime(definition), definition


def test_gradient_rides_the_turn_frame_and_adds_no_generation():
    runtime, _ = _weaver_runtime()
    host = _FakeHost(gen_output="A plain reply.")
    state = ENC.EncounterState()
    frames = []
    for _ in range(5):
        runtime.handle_turn(host, state, "What is this place?", 0)
        frames.append(host.generated_frames[-1])
    # One generation per turn — the gradient is frame instruction,
    # never a new call.
    assert len(host.generated_frames) == 5
    assert "will find its moment" in frames[0]
    assert "natural opening" in frames[2]
    assert "set that aside" in frames[4]
    # The frame's pivot instruction must not self-trigger delivery:
    # detection runs on spoken replies, never on frames.
    assert state.tutorial_pivot_delivered is False


def test_beat_markers_cover_beats_and_never_reach_the_user():
    runtime, _ = _weaver_runtime()
    host = _FakeHost(
        gen_output="My ground is the council and the tree. "
        "[[beat:conductor:terrain]]")
    state = ENC.EncounterState()
    runtime.handle_turn(host, state, "What is this place?", 0)
    assert state.tutorial_covered == ["conductor:terrain"]
    assert host.said == ["My ground is the council and the tree."]
    assert all("[[beat:" not in said for said in host.said)


def test_unknown_beat_ids_never_satisfy_anything():
    runtime, _ = _weaver_runtime()
    host = _FakeHost(gen_output="Something taught. [[beat:conductor:nope]]")
    state = ENC.EncounterState()
    runtime.handle_turn(host, state, "What is this place?", 0)
    assert state.tutorial_covered == []


def test_spoken_pivot_marks_the_pivot_delivered():
    runtime, _ = _weaver_runtime()
    host = _FakeHost(
        gen_output="Let's set that aside for now, why I wanted to "
        "talk was the orchestra itself.")
    state = ENC.EncounterState()
    runtime.handle_turn(host, state, "What is this place?", 0)
    assert state.tutorial_pivot_delivered is True


def _settled_state(definition, covered=(), pivot=False, floor=True):
    state = ENC.EncounterState()
    state.impression_answered = True
    if floor:
        state.satisfied = {"own_undertaking_engaged": True}
    state.tutorial_covered = list(covered)
    state.tutorial_pivot_delivered = pivot
    return state


def test_close_refused_when_beats_uncovered_and_no_pivot():
    runtime, definition = _weaver_runtime()
    host = _FakeHost()
    state = _settled_state(definition)
    runtime._close_or_continue(host, state, "Yes, that's right.", "settled")
    assert state.closed is False
    assert host.close_calls == 0


def test_close_permitted_once_beats_covered():
    runtime, definition = _weaver_runtime()
    host = _FakeHost()
    covered = {b.id for b in definition.tutorial_beats}
    state = _settled_state(definition, covered=covered)
    runtime._close_or_continue(host, state, "Yes, that's right.", "settled")
    assert state.closed is True
    assert host.close_calls == 1


def test_close_refused_on_pivot_alone():
    # Correction 2026-10-24: the pivot NEVER satisfies the gate on
    # its own. Pivot delivered, beats uncovered, no covering content
    # in any body — the gate stays shut.
    runtime, definition = _weaver_runtime()
    host = _FakeHost()
    state = _settled_state(definition, pivot=True)
    runtime._close_or_continue(host, state, "Yes, that's right.", "settled")
    assert state.closed is False
    assert host.close_calls == 0


def test_close_permitted_when_pivot_response_communicates_essentials():
    # The pivot response CAN satisfy the gate — but only by covering
    # beats with content, under the same rule as any other turn.
    runtime, _ = _weaver_runtime()
    host = _FakeHost(
        gen_output="Let's set that aside for now, why I wanted to "
        "talk was this: my ground is the council and the tree — "
        "anywhere parts of your life need hearing together. Bring "
        "me the competing priorities that will not sit together, "
        "whenever they need hearing together. And every new voice "
        "changes what the whole orchestra can play — I keep the "
        "whole of it in ear. "
        "[[beat:conductor:terrain]] [[beat:conductor:involvement]] "
        "[[beat:conductor:why_meet]]")
    state = ENC.EncounterState()
    runtime.handle_turn(host, state, "What is this place?", 0)
    assert state.tutorial_pivot_delivered is True
    assert set(state.tutorial_covered) == {
        "conductor:terrain", "conductor:involvement", "conductor:why_meet",
    }
    state.impression_answered = True
    state.satisfied = {"own_undertaking_engaged": True}
    runtime._close_or_continue(host, state, "Yes, that's right.", "settled")
    assert state.closed is True
    assert host.close_calls == 1


def test_close_refused_when_pivot_response_covers_only_some_beats():
    # Pivot + partial content is still not the gate: every beat
    # must be communicated, not just the pivoted-to one.
    runtime, _ = _weaver_runtime()
    host = _FakeHost(
        gen_output="Let's set that aside for now, why I wanted to "
        "talk was this: my ground is the council and the tree. "
        "[[beat:conductor:terrain]]")
    state = ENC.EncounterState()
    runtime.handle_turn(host, state, "What is this place?", 0)
    assert state.tutorial_pivot_delivered is True
    assert state.tutorial_covered == ["conductor:terrain"]
    state.impression_answered = True
    state.satisfied = {"own_undertaking_engaged": True}
    runtime._close_or_continue(host, state, "Yes, that's right.", "settled")
    assert state.closed is False
    assert host.close_calls == 0


def test_tutorial_gate_does_not_weaken_the_recognition_floor():
    runtime, definition = _weaver_runtime()
    host = _FakeHost()
    covered = {b.id for b in definition.tutorial_beats}
    state = _settled_state(definition, covered=covered, floor=False)
    runtime._close_or_continue(host, state, "Yes, that's right.", "settled")
    assert state.closed is False


def test_generic_definitions_close_without_a_tutorial_gate():
    definition = ENC.build_definition(MT.get_script("conductor", 1))
    runtime = ENC.EncounterRuntime(definition)
    host = _FakeHost()
    state = ENC.EncounterState()
    state.impression_answered = True
    runtime._close_or_continue(host, state, "Yes, that's right.", "settled")
    assert state.closed is True


def test_tutorial_state_round_trips_through_json():
    state = ENC.EncounterState()
    state.tutorial_covered = ["conductor:terrain"]
    state.tutorial_pivot_delivered = True
    restored = ENC.EncounterState.from_json(state.to_json())
    assert restored.tutorial_covered == ["conductor:terrain"]
    assert restored.tutorial_pivot_delivered is True
    # Rows written before this mechanism load with clean defaults.
    legacy = ENC.EncounterState.from_json('{"user_turns": 3}')
    assert legacy.tutorial_covered == []
    assert legacy.tutorial_pivot_delivered is False


# ---------------------------------------------------------------------------
# Correction 2026-10-24: markers are self-reported, so a claim counts
# only with content. Anchors are the guard; the floor is a backstop.
# ---------------------------------------------------------------------------

_GENERIC_ANCHOR_WORDS = {"terrain", "involvement", "why_meet", "meet"}


def test_every_beat_carries_real_content_anchors():
    for seat in SEAT_IDS:
        for beat in TB.beats_for(seat):
            assert len(beat.anchors) >= 2, beat.id
            for anchor in beat.anchors:
                assert beat.id not in anchor, beat.id
                assert anchor.lower() not in _GENERIC_ANCHOR_WORDS, beat.id
            # The frame's own teaching substance passes its own guard:
            # anchors and teaching cannot drift apart unnoticed.
            assert TB.beat_content_covered(beat, beat.teaching), beat.id


def test_anchor_matching_is_word_bounded_and_case_insensitive():
    beat = TB.beats_for("conductor")[0]  # terrain: council, tree, ...
    assert TB.beat_content_covered(beat, "MY GROUND IS THE COUNCIL.")
    assert not TB.beat_content_covered(beat, "Back to the street.")
    assert not TB.beat_content_covered(beat, "The council")
    assert not TB.beat_content_covered(beat, "")


def test_announced_but_unexplained_beat_is_not_counted():
    # Realistic dialogue, not a toy: over three turns the character
    # first announces the terrain beat, then mentions it generically,
    # then actually explains it. Only the third turn counts — and
    # the close stays shut throughout on the uncovered beats.
    # (The announcement-only turns are exactly the failure the
    # self-reported-marker design allowed before this correction.)
    runtime, definition = _weaver_runtime()
    host = _FakeHost()
    state = ENC.EncounterState()

    host.gen_output = (
        "Let me tell you about my terrain now — it's very important. "
        "[[beat:conductor:terrain]]")
    runtime.handle_turn(host, state, "What is this place?", 0)
    assert state.tutorial_covered == []

    host.gen_output = (
        "My terrain is important to me, it matters a lot, really. "
        "[[beat:conductor:terrain]]")
    runtime.handle_turn(host, state, "So what is your terrain?", 0)
    assert state.tutorial_covered == []

    host.gen_output = (
        "My ground is the council and the tree — anywhere parts of "
        "your life need hearing together. "
        "[[beat:conductor:terrain]]")
    runtime.handle_turn(host, state, "Say more about that.", 0)
    assert state.tutorial_covered == ["conductor:terrain"]

    # Positive control in the same script: the explained beat counts.
    # But one beat is not the gate — involvement and why-meet are
    # still uncovered, so a settled verdict must not close.
    state.impression_answered = True
    state.satisfied = {"own_undertaking_engaged": True}
    runtime._close_or_continue(host, state, "Yes, that's right.", "settled")
    assert state.closed is False
    assert host.close_calls == 0
