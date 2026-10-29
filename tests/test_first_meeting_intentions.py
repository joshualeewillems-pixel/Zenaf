"""The first-meeting philosophy (Joshua, 2026-10-24): three
intentions, not a tutorial.

A first meeting is organized by:
1. Be yourself. Converse naturally from the established
   character, philosophy, and jurisdiction. Engage with what the
   visitor actually brings.
2. Tell us about yourself. Let the visitor discover who you are,
   what matters to you, why you wanted to meet, and what
   distinguishes your perspective.
3. Tell us something about Zenaf within your scope. Introduce at
   least one real, useful aspect of the system you understand and
   can help the visitor engage with. Explain it concretely when
   relevant.

These are not three scripted speeches, three mandatory turns, or
an ordered checklist. They overlap, emerge in any order, and are
expressed naturally. "Something" is intentional: the first meeting
is not responsible for teaching every feature or facet. Be
yourself is the governing principle; the other two are
conversational intentions, not permission to interrupt a
meaningful exchange.

This file pins the philosophy in the Weaver's frames and the
runtime: the intentions are stated once, as intentions; no
tutorial machinery (beats, guidance, pivot, gate) remains anywhere
on the path; safety, consent, provenance, naming, and recognition
constraints stay in the system layer. The desired outcome is a
visitor who feels they met someone distinctive, learned something
about that character, and discovered something meaningful they can
do in Zenaf.

Supersedes the tutorial-beat mechanism (2026-10-24, amendments
A-F), which this PR removes: its module, its wiring, its close
gate, and its tests are gone, not dormant.
"""

from __future__ import annotations

from local_ai.conversation import encounter as ENC
from local_ai.council import meetings as MT


# ---------------------------------------------------------------------------
# The authored introduction and the scope map survive unchanged.
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


def test_feature_focus_states_primary_ux_and_shared_creation():
    focus = MT.SEAT_FEATURE_FOCUS["conductor"]
    assert "relationship genuinely heard" in focus
    assert "primary" in focus
    assert "shared creative system" in focus
    assert "Narrative Steward" in focus
    assert "one real step forward" not in focus
    assert "genuinely advanced" not in focus


# ---------------------------------------------------------------------------
# The intentions, stated once — never as a checklist.
# ---------------------------------------------------------------------------

def test_turn_frame_states_the_three_intentions():
    frame = ENC.WEAVER_TURN_FRAME
    # 1. Be yourself, governing.
    assert "Be yourself above all" in frame
    assert "engage with what the visitor actually brings" in frame
    # P1 rewrite (Conductor agency refinement, 2026-10-28): the
    # initiative bans are superseded by permission + judgment-based
    # yielding — never a prescribed yield procedure. The old ban
    # wording must not survive as a separate prohibition.
    assert "never resume an agenda of your own" not in frame
    assert "may volunteer a topic" in frame
    assert "you yield when the visitor redirects" in frame
    assert "judgment about rhythm, not a procedure" in frame
    # 2. Discover who you are.
    assert "discover who you are" in frame
    assert "why you wanted to meet" in frame
    assert "what distinguishes your hearing" in frame
    # 3. Something within scope, concretely.
    assert "one real thing they can do here" in frame
    assert "explain it concretely" in frame
    assert "not responsible for teaching every feature" in frame
    # The governing rule, in so many words — and the anti-checklist
    # line, so no future edit can re-encode these as steps.
    assert "intentions, not speeches" in frame
    assert "being yourself governs" in frame
    assert "never interrupt a meaningful exchange" in frame


def test_turn_frame_is_conductor_not_coach():
    frame = ENC.WEAVER_TURN_FRAME
    assert "conductor of this workshop" in frame
    assert "no required words, no required frequency" in frame
    assert "move their material one real step" not in frame
    assert "Progress they can use" not in frame
    assert "Never name or describe the other council members" not in frame
    # The authored opening is not a template for later dialogue:
    # no intro recap in the conversational frame.
    assert "we'll find your sound soon enough" not in frame
    assert "new instrument for the orchestra" not in frame


def test_encounter_frame_carries_the_intentions_on_the_engage_path():
    # The engage path never sees the turn frame, so the encounter
    # frame must carry the philosophy itself — in miniature, not as
    # a second checklist.
    frame = MT.get_script("conductor", 1).encounter_frame
    assert "Answer what they actually said — genuinely" in frame
    assert "take up THEIR material as the shared work" in frame
    assert "discover who you are" in frame
    assert "show one real thing concretely" in frame
    assert "not a tour" in frame
    assert "intentions, not a checklist" in frame
    assert "never interrupt a meaningful exchange" in frame


def test_no_per_generation_duplicates():
    # Repeated behavioral prescriptions are gone: each rule appears
    # exactly once per generation path.
    definition = ENC.get_definition(MT.get_script("conductor", 1))
    for name, text in (("turn", definition.turn_frame),
                       ("engage", definition.engage_frame)):
        low = text.lower()
        assert low.count("reveal your name yet") == 1, name
        assert low.count("think in music") == 1, name
        assert low.count("mime") == 1, name


def test_no_tutorial_machinery_remains():
    # The mechanism is deleted, not unwired: no module, no
    # definition field, no state ledger, no coverage reader.
    import local_ai.conversation as conv

    assert not hasattr(conv, "tutorial_beats")
    definition = ENC.get_definition(MT.get_script("conductor", 1))
    assert not hasattr(definition, "tutorial_beats")
    assert not hasattr(ENC, "_apply_tutorial_coverage")
    state = ENC.EncounterState()
    assert not hasattr(state, "tutorial_covered")
    assert not hasattr(state, "tutorial_facets")
    assert not hasattr(state, "tutorial_pivot_delivered")


# ---------------------------------------------------------------------------
# System layer: naming + Zenaf one-liners, recognition close.
# ---------------------------------------------------------------------------

def test_turn_frame_carries_zenaf_note_and_naming_note():
    # Both standing notes are one line each.
    runtime = ENC.EncounterRuntime(
        ENC.get_definition(MT.get_script("conductor", 1)))
    frame, _cue = runtime._turn_frame(
        ENC.EncounterState(), "What is this app?")
    assert "answer plainly first" in frame
    assert "planned rather than available" in frame
    assert "Other seats: roles until met." in frame
    # No detector reinforcement, no long naming paragraph.
    assert "Note: this message asks directly about Zenaf" not in frame
    assert "Meeting a character is not developing" not in frame
    assert "refer to every other seat by its seat role" not in frame


def test_zenaf_note_is_standing_not_detector_triggered():
    # No detector exists anymore: the one-line note rides the frame
    # for an unmistakable question AND for an oblique one — a
    # visitor may ask in words no small vocabulary knows.
    assert not hasattr(ENC, "_asks_about_zenaf")
    runtime = ENC.EncounterRuntime(
        ENC.get_definition(MT.get_script("conductor", 1)))
    for question in ("What is this app?",
                     "So what actually is all of this?"):
        frame, _cue = runtime._turn_frame(
            ENC.EncounterState(), question)
        assert "answer plainly first" in frame


def test_naming_note_is_two_tier_and_per_seat():
    base = ENC.get_definition(MT.get_script("conductor", 1))
    note = ENC._naming_note(base)
    assert note == "Other seats: roles until met. None met yet."

    import dataclasses
    met = dataclasses.replace(base, met_seats=("champion",))
    note = ENC._naming_note(met)
    assert note == "Other seats: roles until met. Met: Firebrand (champion)."
    assert "\n" not in note


def _settled_state(floor=True):
    state = ENC.EncounterState()
    state.impression_answered = True
    if floor:
        state.satisfied = {"own_undertaking_engaged": True}
    return state


def test_close_is_on_recognition_not_coverage():
    # No coverage exists to gate on: a settled verdict with the
    # recognition floor satisfied closes, full stop.
    runtime = ENC.EncounterRuntime(
        ENC.get_definition(MT.get_script("conductor", 1)))
    host = _FakeHost()
    state = _settled_state()
    runtime._close_or_continue(host, state, "Yes, that's right.", "settled")
    assert state.closed is True
    assert host.close_calls == 1


def test_close_still_requires_the_recognition_floor():
    runtime = ENC.EncounterRuntime(
        ENC.get_definition(MT.get_script("conductor", 1)))
    host = _FakeHost()
    state = _settled_state(floor=False)
    runtime._close_or_continue(host, state, "Yes, that's right.", "settled")
    assert state.closed is False


def test_generic_definitions_close_on_recognition():
    definition = ENC.build_definition(MT.get_script("conductor", 1))
    runtime = ENC.EncounterRuntime(definition)
    host = _FakeHost()
    state = ENC.EncounterState()
    state.impression_answered = True
    runtime._close_or_continue(host, state, "Yes, that's right.", "settled")
    assert state.closed is True


def test_state_round_trips_through_json():
    state = ENC.EncounterState()
    state.impression_pending_text = "A held read."
    state.impression_pending_strands = ["Logic"]
    restored = ENC.EncounterState.from_json(state.to_json())
    assert restored.impression_pending_text == "A held read."
    assert restored.impression_pending_strands == ["Logic"]
    # Rows written before this mechanism load with clean defaults.
    legacy = ENC.EncounterState.from_json('{"user_turns": 3}')
    assert legacy.impression_pending_text == ""
    assert legacy.impression_pending_strands == []


# ---------------------------------------------------------------------------
# Sequencing: one question per breath (2026-10-24 screenshot fix).
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


def _gated_runtime():
    definition = ENC.get_definition(MT.get_script("conductor", 1))
    return ENC.EncounterRuntime(definition), definition


def _gate_open_state():
    # The impression gate reads the prior turn's snapshot: the
    # shared work must already have happened.
    state = ENC.EncounterState()
    state.satisfied = {"shared_work_exchange": True}
    return state


_SUBSTANTIVE = (
    "I sold cable door to door for $200 a month, and the house "
    "had soggy diapers everywhere on my last day."
)


def test_reply_question_holds_impression():
    # The screenshot shape: a reply ending in a question must not
    # share its breath with an impression ending in another
    # question — the reply's question gets orphaned. Speak the
    # reply only; hold the impression.
    runtime, _ = _gated_runtime()
    host = _FakeHost(
        gen_output="What does your own part still refuse to give up "
        "to it?\n---\nA first read of you.\nStrands: Logic")
    state = _gate_open_state()
    runtime.handle_turn(host, state, _SUBSTANTIVE, 0)
    assert host.said == [
        "What does your own part still refuse to give up to it?"]
    assert state.impression_pending_text == "A first read of you."
    assert state.impression_pending_strands == ["Logic"]
    assert state.impression_offered is False
    assert state.impression_text == ""


def test_pending_delivered_after_non_question_reply():
    # Held impression rides the first later reply that does not
    # end in a question; a fresh impression the same turn is
    # discarded — the held read speaks, never two reads.
    runtime, _ = _gated_runtime()
    host = _FakeHost(
        gen_output="What does your own part still refuse to give up "
        "to it?\n---\nA first read of you.\nStrands: Logic")
    state = _gate_open_state()
    runtime.handle_turn(host, state, _SUBSTANTIVE, 0)
    assert state.impression_pending_text == "A first read of you."

    host.gen_output = (
        "That tracks — the work held together.\n---\nA fresh read.\n"
        "Strands: Logic")
    runtime.handle_turn(host, state, "It held together, barely.", 0)
    assert host.said[-2:] == [
        "That tracks — the work held together.",
        "A first read of you.",
    ]
    assert state.impression_pending_text == ""
    assert state.impression_offered is True
    assert state.impression_text == "A first read of you."
    assert host.impressions == [("A first read of you.", ["Logic"])]


def test_pending_held_across_question_replies():
    # A reply ending in another question keeps the hold: one
    # question per breath, and the reply's question keeps its turn.
    runtime, _ = _gated_runtime()
    host = _FakeHost(
        gen_output="What does your own part still refuse to give up "
        "to it?\n---\nA first read of you.\nStrands: Logic")
    state = _gate_open_state()
    runtime.handle_turn(host, state, _SUBSTANTIVE, 0)

    host.gen_output = (
        "And where did that leave you?\n---\nA fresh read.\n"
        "Strands: Logic")
    runtime.handle_turn(host, state, "It left me tired.", 0)
    assert host.said[-1] == "And where did that leave you?"
    assert "A first read of you." not in host.said
    assert "A fresh read." not in host.said
    assert state.impression_pending_text == "A first read of you."
    assert state.impression_offered is False


def test_statement_reply_and_impression_share_one_question():
    # The acceptable shape: a reply that does NOT end in a question
    # may share its turn with the impression — the user has exactly
    # one question to answer, the impression's.
    runtime, _ = _gated_runtime()
    host = _FakeHost(
        gen_output="That tracks.\n---\nA first read of you.\nStrands: Logic")
    state = _gate_open_state()
    runtime.handle_turn(host, state, _SUBSTANTIVE, 0)
    assert host.said == ["That tracks.", "A first read of you."]
    assert state.impression_offered is True
    assert state.impression_pending_text == ""


def test_pending_spoken_at_wrap():
    # A held read is the read: at the ceiling wrap it speaks
    # rather than a freshly generated one.
    runtime, _ = _gated_runtime()
    host = _FakeHost()
    state = _gate_open_state()
    state.impression_pending_text = "A held read."
    state.impression_pending_strands = ["Logic"]
    state.longest_user_turn = _SUBSTANTIVE
    runtime._wrap_turn(host, state)
    assert "A held read." in host.said
    assert state.impression_offered is True
    assert state.impression_pending_text == ""
    assert state.closed is True
