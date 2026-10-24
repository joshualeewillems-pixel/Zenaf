"""The encounter, made adaptive — acceptance tests for the P3
follow-up (Joshua, 2026-10-23).

The doctrine's distinction, made mechanical: the character's
objectives guide her behavior; the USER's contributions determine
the conversational trajectory. Pinned here:

  - Ordinary cooperative conversation can change direction: the
    impression is discretionary (offered when the exchange earns
    it, grounded in the user's own material when it comes), and
    no banked question is ever forced.
  - Recognition is not agreement: a rejection satisfies it, the
    impression stands as hers, the answer is recorded verbatim,
    and no frame argues the user toward consensus.
  - The close is semantic: the open-door judgment rides each
    turn's single generation as a stripped [[thread:...]] trailer
    (deterministic estimate only when the trailer is missing), so
    an unexpected question after recognition holds the meeting
    open, and no thread is ever closed over.
  - Environmental context is context: allusions and the retired
    pause's paragraphs surface at most one per turn, only when the
    conversation passes near — never as a delivered block.
  - Latency: at most ONE generation per user turn, everywhere.
  - Evidence ≠ expression (the Mad Lib ruling): no frame on this
    path requires quote-weaving, her dialogue and the stored
    claim carry no [[u]] markup even when a model emits it, and
    the evidence chain keeps the user's words verbatim.
"""

from __future__ import annotations

import threading

import pytest

from local_ai.agent_intake.store import AgentStore
from local_ai.conversation import encounter as ENC
from local_ai.conversation.meeting import MeetingService, MeetingStore
from local_ai.conversation.store import ConversationStore
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


class ScriptedGen:
    """Routes on frame markers, with per-route output queues so a
    test scripts exactly what each generation returns — thread
    trailers included. Defaults are compliant, settled replies."""

    def __init__(self):
        self.prompts: list[str] = []
        self.engage: list[str] = []
        self.turn: list[str] = []
        self.correction: list[str] = []
        self.reply: list[str] = []
        self.impression: list[str] = []

    @staticmethod
    def _next(queue: list[str], default: str) -> str:
        return queue.pop(0) if queue else default

    def __call__(self, prompt, **kwargs):
        self.prompts.append(prompt)
        if "has just corrected your first impression" in prompt:
            return self._next(
                self.correction,
                "A revised read, in her own words.\nStrands: Logic\n[[thread:settled]]",
            )
        if "Whatever its valence" in prompt:
            return self._next(
                self.reply, "A brief engaged reply.\n[[thread:settled]]"
            )
        if "ENCOUNTER" in prompt and "READ-BACK" in prompt:
            return self._next(self.engage, "An engaged reply from the bench.")
        if "READ-BACK" in prompt:
            return self._next(
                self.impression,
                "A first impression from the whole exchange.\nStrands: Compass",
            )
        if "mid-conversation in your workshop" in prompt:
            return self._next(
                self.turn, "A conversational reply.\n[[thread:settled]]"
            )
        return "A plain reply."



#: Tutorial-beat mechanism (2026-10-24): these fakes simulate a
#: character that teaches its beats — every generation output
#: carries the three beat trailers, stripped before anything is
#: spoken, so spoken bodies, prompts, and generation counts are
#: unchanged and the tutorial gate opens as it would for a
#: compliant model. The gate itself is pinned by
#: tests/test_encounter_tutorial_beats.py; these suites pin the
#: other behaviors.
_BEAT_SUFFIX = (
    "\n[[beat:conductor:terrain]] [[beat:conductor:involvement]] "
    "[[beat:conductor:why_meet]]"
)


def _teaching(gen):
    def wrapper(prompt, **kwargs):
        return gen(prompt, **kwargs) + _BEAT_SUFFIX
    return wrapper


def _svc(tmp_path, gen=None):
    return MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
        generate_fn=_teaching(gen or ScriptedGen()),
    )


def _svc_with_agents(tmp_path, gen=None):
    agents_db = tmp_path / "agents.db"
    svc = MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
        generate_fn=_teaching(gen or ScriptedGen()),
        agent_store_factory=lambda uid: AgentStore(agents_db, user_id=uid),
    )
    return svc, agents_db


def _seeded_user(email="adaptive@example.com"):
    user = ve.create_user_account(email, "pw", "Adaptive")
    keystone_seeding.seed_meet_your_council(user["id"])
    return user["id"]


def _enc_state(svc, uid):
    row = svc.meetings.get(uid, "conductor", 1)
    return ENC.EncounterState.from_json(row["state_json"])


def _bodies(state):
    return [m["body"] for m in state["messages"]]


class Run:
    """Drives one meeting, asserting the latency invariant on every
    turn (≤1 generation) and reporting the turn's new voice bubbles."""

    def __init__(self, svc, gen, uid):
        self.svc = svc
        self.gen = gen
        self.uid = uid

    def turn(self, message, seat="conductor"):
        before_msgs = len(self.svc.state(self.uid, seat)["messages"])
        before_prompts = len(self.gen.prompts)
        state = self.svc.turn(self.uid, seat, message)
        spent = len(self.gen.prompts) - before_prompts
        assert spent <= 1, f"turn spent {spent} generations: {message!r}"
        new_voice = [
            m["body"] for m in state["messages"][before_msgs:]
            if m["role"] == "voice"
        ]
        return state, new_voice


def _to_readback(run: Run, answer="I decide by what breaks first if I ignore it."):
    """Start and reach the read-back. UPDATED for the Weaver
    pattern: the impression is gated on the shared-work exchange,
    so the drive is two substantive turns — the first begins the
    shared work (her generation offers a read and the gate holds
    it; only the reply is spoken), the second carries the
    impression. Returns the state with the impression on the table."""
    run.gen.engage.append("Heard — the bench takes it in.")
    run.gen.engage.append(
        "Heard, and noted at the bench."
        "\n---\n"
        "A first read, in her own words: you move by triage — what "
        "breaks first gets your hands first."
        "\nStrands: Compass, Heart"
    )
    run.svc.start(run.uid, "conductor")
    state, _ = run.turn(answer)
    assert state["stage"] == "encounter"  # the gate held the read
    state, _ = run.turn(
        "And in my own work it's the same — what breaks first "
        "gets my hands first, every time."
    )
    assert state["stage"] == "readback"
    return state


# ------------------------------------------- cooperative steering


def test_cooperative_conversation_changes_direction(ve_ctx, tmp_path):
    uid = _seeded_user()
    gen = ScriptedGen()
    # First engagement: a reply only — she honestly has no read yet.
    gen.engage.append("A shape before motion. Noted at the bench.")
    # Second engagement: the exchange has earned the impression,
    # and it grounds in the user's own undertaking.
    gen.engage.append(
        "The doubter in your own shop — that's the honest seat."
        "\n---\n"
        "A first read, in her own words: at other people's tables "
        "you plan first, but in your own work — rebuilding your "
        "family's bookkeeping business — you are the doubter, and "
        "that is where you actually live."
        "\nStrands: Compass, Heart"
    )
    run = Run(_svc(tmp_path, gen), gen, uid)
    script = MT.get_script("conductor", 1)
    state = run.svc.start(uid, "conductor")
    # FINAL (Joshua, 2026-10-23, ~22:45 PT): the scripted opening
    # is her INTRODUCTION — his authored text, four bubbles — and
    # she waits.
    assert len(state["messages"]) == len(script.opening) == 4
    assert _bodies(state) == list(script.opening)

    state, voice = run.turn(
        "I listen to the planner first — nothing moves until the shape is clear."
    )
    # No impression was forced out of a thin exchange, and no
    # banked question was served as if nothing had been said (the
    # bank is retired; the retired dilemma's text appears nowhere).
    assert voice == ["A shape before motion. Noted at the bench."]
    assert state["stage"] == "encounter"
    row = run.svc.meetings.get(uid, "conductor", 1)
    assert row["readback_claim"] == ""
    assert not any("Who do you listen to" in b for b in _bodies(state))
    enc = _enc_state(run.svc, uid)
    assert enc.satisfied["impression_offered"] is False

    # The user steers to their own undertaking; the encounter
    # follows, and the impression — when it comes — is built from
    # THEIR material, not from the dilemma's script.
    state, voice = run.turn(
        "Though honestly, in my own work it's messier — I'm rebuilding "
        "my family's bookkeeping business, and there I'm the doubter "
        "half the time."
    )
    assert state["stage"] == "readback"
    row = run.svc.meetings.get(uid, "conductor", 1)
    assert "bookkeeping business" in row["readback_claim"]
    enc = _enc_state(run.svc, uid)
    assert enc.satisfied["own_undertaking_engaged"] is True
    assert enc.satisfied["engaged_exchange"] is True

    state, _ = run.turn("That's fair.")
    assert state["status"] == "complete"


# ------------------------------------------------------- offers


def test_offer_of_help_after_recognition_does_not_force_close(ve_ctx, tmp_path):
    uid = _seeded_user()
    gen = ScriptedGen()
    run = Run(_svc(tmp_path, gen), gen, uid)
    _to_readback(run)

    # The offer arrives AS the answer to her impression — and it
    # opens a thread rather than ending one: no forced close, no
    # snap back to an agenda. (Fixture reply CORRECTED for the
    # no-pretend law: her reception is conversational — ears
    # offered, not a joint held.)
    gen.reply.append("You may — listen with me, then.\n[[thread:open]]")
    state, voice = run.turn(
        "That's a fair read. And — can I help you hold that joint "
        "while you work on it?"
    )
    assert voice == ["You may — listen with me, then."]
    assert state["status"] == "active"
    assert state["stage"] == "orientation"  # post-recognition phase
    script = MT.get_script("conductor", 1)
    assert not any(p in _bodies(state) for p in script.reveal)
    enc = _enc_state(run.svc, uid)
    assert enc.satisfied["offer_of_help_received"] is True
    assert enc.satisfied["impression_answered"] is True

    # The shared work winds down on a settled turn, and only then
    # does the meeting close.
    gen.turn.append("Then we work.\n[[thread:settled]]")
    state, _ = run.turn("There — steady. I've got this end.")
    assert state["status"] == "complete"
    for paragraph in script.reveal:
        assert paragraph in _bodies(state)


# ----------------------------------------------------- rejection


def test_rejection_satisfies_recognition_and_the_impression_stands(ve_ctx, tmp_path):
    uid = _seeded_user()
    gen = ScriptedGen()
    run = Run(_svc(tmp_path, gen), gen, uid)
    _to_readback(run)
    before = run.svc.meetings.get(uid, "conductor", 1)
    claim_before = before["readback_claim"]
    assert claim_before.startswith("A first read")

    rejection = "Honestly? I don't buy that reading of me at all."
    state, _ = run.turn(rejection)
    # Recognition does not require agreement: the rejection
    # completes it, and with nothing left hanging the meeting
    # closes on this turn.
    assert state["status"] == "complete"
    row = run.svc.meetings.get(uid, "conductor", 1)
    # The impression stands as HERS — not revised, not softened —
    # and the user's rejection is the record, verbatim.
    assert row["readback_claim"] == claim_before
    assert row["readback_response"] == rejection
    enc = _enc_state(run.svc, uid)
    assert enc.satisfied["impression_answered"] is True
    assert enc.impression_answer_kind == "other"
    # The frame that produced her reply carried the no-consensus
    # instruction (refinement 2) in so many words.
    assert any(
        "soften a rejection into assent" in p for p in gen.prompts
    )


# ------------------------------------- questions after recognition


def test_unexpected_question_after_recognition(ve_ctx, tmp_path):
    uid = _seeded_user()
    gen = ScriptedGen()
    svc, agents_db = _svc_with_agents(tmp_path, gen)
    run = Run(svc, gen, uid)
    _to_readback(run)

    gen.reply.append("Mm.\n[[thread:open]]")
    state, _ = run.turn("Hmm. Interesting.")
    assert state["status"] == "active"

    # The unexpected question: answered in conversation, and the
    # open thread — not a schedule — decides the meeting stays.
    gen.turn.append(
        "Seven, because each insists on being heard — together "
        "they make the one sound.\n[[thread:open]]"
    )
    state, voice = run.turn(
        "Wait — why seven parts? What is the finished instrument actually for?"
    )
    assert voice == [
        "Seven, because each insists on being heard — together "
        "they make the one sound."
    ]
    assert state["status"] == "active"
    script = MT.get_script("conductor", 1)
    assert not any(p in _bodies(state) for p in script.reveal)

    gen.turn.append("Then we're heard.\n[[thread:settled]]")
    state, _ = run.turn("That makes sense, thank you.")
    assert state["status"] == "complete"
    for paragraph in script.reveal:
        assert paragraph in _bodies(state)
    store = AgentStore(agents_db, user_id=uid)
    assert len(store.get_claims("meeting-conductor-1")) == 1


# ------------------------------------------------------ allusions


def test_allusions_appear_only_when_relevant(ve_ctx, tmp_path):
    # Run A: a full playthrough whose words never pass near any
    # fixture — zero allusions offered, zero surfaced.
    uid = _seeded_user("norelevance@example.com")
    gen = ScriptedGen()
    run = Run(_svc(tmp_path, gen), gen, uid)
    _to_readback(run, answer="I go with whoever has run the job before, twice over.")
    state, _ = run.turn("Yes, that's me.")
    assert state["status"] == "complete"
    assert not any("passes near" in p for p in gen.prompts)
    bodies = _bodies(state)
    for trace in MT.WEAVER_ALLUSIONS:
        assert trace.text not in bodies
    assert not any("workshop as it stands" in b for b in bodies)
    enc = _enc_state(run.svc, uid)
    assert enc.allusions_used == []

    # Run B: the conversation passes near the Bear's fixture —
    # that one surfaces, once, and never again.
    uid = _seeded_user("relevance@example.com")
    gen = ScriptedGen()
    run = Run(_svc(tmp_path, gen), gen, uid)
    run.svc.start(uid, "conductor")
    fixture = MT.SEAT_ENVIRONMENT["guardian"].fixtures[0]
    run.turn("Do you lock the finished pieces away at night, or leave them out?")
    offered = [p for p in gen.prompts if fixture in p]
    assert len(offered) == 1
    enc = _enc_state(run.svc, uid)
    assert enc.allusions_used == ["guardian"]
    run.turn("And the locks themselves — who else keeps a key?")
    offered = [p for p in gen.prompts if fixture in p]
    assert len(offered) == 1  # a debt is paid once
    enc = _enc_state(run.svc, uid)
    assert enc.allusions_used == ["guardian"]


# -------------------------------------------------- bubble budget


def test_no_multi_bubble_exposition_dumps(ve_ctx, tmp_path):
    uid = _seeded_user()
    gen = ScriptedGen()
    run = Run(_svc(tmp_path, gen), gen, uid)
    script = MT.get_script("conductor", 1)
    _to_readback(run)

    # A substantive correction: the revised impression is the
    # turn's only bubble; with no trailer, the deterministic
    # estimate (substantive new material) keeps the thread open.
    gen.correction.append(
        "A revised read, in her own words: the route comes first "
        "for you.\nStrands: Logic"
    )
    state, voice = run.turn(
        "Actually it's the planner in me first — I map the whole "
        "route before anyone moves, every time."
    )
    assert voice == [
        "A revised read, in her own words: the route comes first for you."
    ]
    assert state["status"] == "active"

    # Post-recognition turns: one bubble each.
    gen.turn.append("A bench answer.\n[[thread:open]]")
    state, voice = run.turn("And if the route changes halfway?")
    assert voice == ["A bench answer."]
    assert state["status"] == "active"

    # The closing turn is exactly: her reply + the reveal.
    gen.turn.append("Then we adjust the route together.\n[[thread:settled]]")
    state, voice = run.turn("Alright. I can work with that.")
    assert state["status"] == "complete"
    assert voice[0] == "Then we adjust the route together."
    assert voice[1:] == list(script.reveal)

    # The old pause block can never occur: none of its paragraphs
    # was spoken anywhere in the run, in any turn, let alone five
    # at once.
    bodies = _bodies(state)
    for paragraph in script.orientation:
        assert paragraph not in bodies
    for paragraph in script.orientation_intro:
        assert paragraph not in bodies


# ---------------------------------------------- no forced closure


def test_no_forced_closure_while_a_thread_is_open(ve_ctx, tmp_path):
    uid = _seeded_user()
    gen = ScriptedGen()
    svc, agents_db = _svc_with_agents(tmp_path, gen)
    run = Run(svc, gen, uid)
    _to_readback(run)

    gen.reply.append("Mm — go on.\n[[thread:open]]")
    state, _ = run.turn("Hmm.")
    assert state["status"] == "active"

    # Four consecutive open threads — far past the old contract's
    # single post-pause exchange — and the meeting simply
    # continues, answering each one.
    open_turns = [
        ("What does the tall part do?", "It waits for its moment.\n[[thread:open]]"),
        ("What's the small one for?", "It keeps the time.\n[[thread:open]]"),
        ("Why does that one hum?", "Because it is tuned to the room.\n[[thread:open]]"),
        ("And if it stops humming?", "Then we listen harder.\n[[thread:open]]"),
    ]
    for message, output in open_turns:
        gen.turn.append(output)
        state, voice = run.turn(message)
        assert voice == [output.split("\n")[0]]
        assert state["status"] == "active"
        assert state["stage"] == "orientation"

    # A missing trailer falls back to the deterministic estimate:
    # a question is a thread still open.
    gen.turn.append("It listens back.")  # no trailer at all
    state, _ = run.turn("Does it ever answer?")
    assert state["status"] == "active"

    gen.turn.append("Always.\n[[thread:settled]]")
    state, _ = run.turn("Good. That's enough for today.")
    assert state["status"] == "complete"
    store = AgentStore(agents_db, user_id=uid)
    assert len(store.get_claims("meeting-conductor-1")) == 1


# ------------------------------------------------------- Mad Lib


def test_no_frame_on_the_encounter_path_requires_weaving(ve_ctx, tmp_path):
    script = MT.get_script("conductor", 1)
    definition = ENC.get_definition(script)
    frames = {
        "engage": definition.engage_frame,
        "turn": definition.turn_frame,
        "impression": definition.impression_frame,
        "correction": definition.correction_frame,
        "impression_reply": definition.impression_reply_frame,
    }
    for name, frame in frames.items():
        assert "[[u]]" not in frame, name
        assert "weave markers" not in frame, name
        assert "quote them with" not in frame, name
    # The impression and correction frames carry the own-words
    # synthesis instruction instead — and the correction frame
    # engages the correction's implications, not a summary of it.
    assert "Say it in YOUR OWN words" in frames["impression"]
    assert "never let their first-person words" in frames["impression"]
    assert "your own words" in frames["correction"]
    assert "implications" in frames["correction"]
    assert "do not splice" in frames["correction"]
    # The runtime's own record-quoting machinery is gone.
    assert not hasattr(ENC.EncounterRuntime, "_deliver_pause")
    assert not hasattr(ENC.EncounterRuntime, "_pause_turn")


def test_meeting_generation_is_not_fed_the_weave_instruction(ve_ctx, tmp_path):
    """The generic voice path's weave instruction (reply.py) stays
    the default for chat — but meeting generation opts out, so no
    prompt on the encounter path carries it."""
    from local_ai.conversation.reply import build_voice_prompt

    uid = _seeded_user()
    lines, _ = build_voice_prompt(uid, "conductor", "hello", [])
    assert any("wrap those exact words" in line for line in lines)
    lines, _ = build_voice_prompt(uid, "conductor", "hello", [], weave=False)
    assert not any("wrap those exact words" in line for line in lines)

    gen = ScriptedGen()
    run = Run(_svc(tmp_path, gen), gen, uid)
    _to_readback(run)
    run.turn("That's fair.")
    assert gen.prompts  # generations happened
    for prompt in gen.prompts:
        assert "wrap those exact words" not in prompt
        assert "[[u]]" not in prompt


def test_dialogue_and_claim_carry_no_markers_but_evidence_is_verbatim(ve_ctx, tmp_path):
    """A model that splices anyway — first-person user fragments
    wrapped in markers, the Mad Lib failure exactly — cannot put
    markup (or the splice structure) into her spoken lines or the
    stored claim: the runtime strips markers from everything she
    speaks and stores as her words. The evidence layer is
    untouched: the filed claim's evidence is the user's verbatim
    answer, word for word."""
    uid = _seeded_user()
    gen = ScriptedGen()
    # UPDATED for the Weaver pattern: the first engage generation
    # is a reply only (the gate holds any early read); the spliced
    # impression rides the second substantive turn.
    gen.engage.append("Heard — the bench takes it in.")
    gen.engage.append(
        "Heard."
        "\n---\n"
        "A first read: you [[u]]decide by what breaks first[[/u]], "
        "always."
        "\nStrands: Compass"
    )
    gen.correction.append(
        "Revised, plainly: you [[u]]protect mornings first[[/u]] "
        "before all else."
        "\nStrands: Heart"
    )
    svc, agents_db = _svc_with_agents(tmp_path, gen)
    run = Run(svc, gen, uid)
    svc.start(uid, "conductor")

    run.turn("I decide by what breaks first if I ignore it.")
    state, _ = run.turn(
        "And in my own work it's the same — what breaks first "
        "gets my hands first, every time."
    )
    assert state["stage"] == "readback"
    correction = "Mostly right — except I protect mornings first."
    state, _ = run.turn(correction)
    state, _ = run.turn("Got it.")
    assert state["status"] == "complete"

    bodies = _bodies(state)
    assert not any("[[u]]" in b or "[[/u]]" in b for b in bodies)
    # Her claim is her synthesized words — markers stripped, text kept.
    row = svc.meetings.get(uid, "conductor", 1)
    assert row["readback_claim"] == (
        "Revised, plainly: you protect mornings first before all else."
    )
    # The user's verbatim answer appears exactly once in the whole
    # transcript: in their own bubble. She never quotes it back.
    assert bodies.count(correction) == 1
    # The filed claim: her interpretation as inference, his words
    # as evidence — the separation, end to end.
    store = AgentStore(agents_db, user_id=uid)
    (claim,) = store.get_claims("meeting-conductor-1")
    assert claim.inference == row["readback_claim"]
    assert "[[" not in claim.inference
    assert claim.evidence == correction
