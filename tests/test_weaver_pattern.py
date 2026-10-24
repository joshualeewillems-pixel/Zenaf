"""The Weaver pattern — acceptance tests (Joshua, 2026-10-23).

The release after the adaptivity fix, driven by his live test of it.
Six notes, and the shape he chose in answer ("The seventh part"):

  1. The greeting question is REAL: the scripted opening is ONE
     bubble, she waits, and the working-together invitation follows
     from the user's answer (generated), not from a script.
  2. The mover/planner/doubter DILEMMA is retired — too
     philosophical a hypothetical. The encounter is a collaboration
     on a specific task (the instrument's sounding); the user's own
     version of the integration problem is the subject.
  3+4. Register discipline: her dictionary is MUSIC (jurisdictions
     registry), carried as AVAILABLE context under the three-layers
     rule — ordinary speech the default, no layer mandatory, no
     metaphor quota; anything she says must reference the exchange.
  5. The hedge names its claim: the read-back frame instructs the
     exact-point-of-doubt discipline, never a blanket hedge.
  6. MEANINGFUL recognition: the close gate is no longer
     impression-offered ∧ impression-answered. The impression is
     GATED on the shared-work exchange (turn-one impressions are
     structurally impossible), and the close is FLOORED on
     own-material-taken-up ∨ a pursuit exchange. His specimen is
     the canonical play shape below; his live run's two-turn
     anticlimax (dilemma-style answer + affirmation → card) can no
     longer close the meeting. And the closing turn's payload
     always carries her reply AND the reveal (the backend half of
     the missing-lines bug; the frontend half is MeetingView's
     component test).

Latency invariant throughout: ≤1 generation per user turn.
"""

from __future__ import annotations

import re
import threading

import pytest

from local_ai.conversation import encounter as ENC
from local_ai.conversation.meeting import MeetingService, MeetingStore
from local_ai.conversation.store import ConversationStore
from local_ai.council import jurisdictions as JX
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


class PatternGen:
    """Routes on frame markers with per-route queues, like the
    adaptive suite's ScriptedGen."""

    def __init__(self):
        self.prompts: list[str] = []
        self.engage: list[str] = []
        self.turn: list[str] = []
        self.reply: list[str] = []

    @staticmethod
    def _next(queue: list[str], default: str) -> str:
        return queue.pop(0) if queue else default

    def __call__(self, prompt, **kwargs):
        self.prompts.append(prompt)
        if "has just corrected your first impression" in prompt:
            return "A revised read, in her own words.\nStrands: Logic\n[[thread:settled]]"
        if "Whatever its valence" in prompt:
            return self._next(
                self.reply, "A brief engaged reply.\n[[thread:settled]]"
            )
        if "ENCOUNTER" in prompt and "READ-BACK" in prompt:
            return self._next(self.engage, "An engaged reply from the bench.")
        if "READ-BACK" in prompt:
            return "A first impression from the whole exchange.\nStrands: Compass"
        if "mid-conversation in your workshop" in prompt:
            return self._next(
                self.turn, "A conversational reply.\n[[thread:settled]]"
            )
        return "A plain reply."


def _svc(tmp_path, gen=None):
    return MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
        generate_fn=gen or PatternGen(),
    )


def _seeded_user(email="pattern@example.com"):
    user = ve.create_user_account(email, "pw", "Pattern")
    keystone_seeding.seed_meet_your_council(user["id"])
    return user["id"]


def _enc_state(svc, uid):
    row = svc.meetings.get(uid, "conductor", 1)
    return ENC.EncounterState.from_json(row["state_json"])


def _bodies(state):
    return [m["body"] for m in state["messages"]]


# ------------------------------------------------- the greeting is real


def test_greeting_is_one_bubble_and_she_waits(ve_ctx, tmp_path):
    uid = _seeded_user()
    gen = PatternGen()
    svc = _svc(tmp_path, gen)
    script = MT.get_script("conductor", 1)

    state = svc.start(uid, "conductor")
    # ONE scripted bubble — the greeting question — and nothing
    # else: no second scripted bubble exists to be delivered before
    # the user's first turn ends, and starting spent no generation.
    assert _bodies(state) == [script.opening[0]]
    assert "does this look broken to you, or merely unfinished?" in _bodies(state)[0]
    assert gen.prompts == []

    # Her next words are generated from the user's answer — the
    # working-together invitation is not a scripted line.
    gen.engage.append(
        "Unfinished, then — good ears. Hold this end a moment and "
        "tell me what you hear when I sound it."
    )
    state = svc.turn(uid, "conductor", "Unfinished, I'd say — like it's mid-sentence.")
    new_voice = [b for b in _bodies(state) if b != script.opening[0]]
    assert any("Hold this end" in b for b in new_voice)
    # The invitation followed from the answer: it answers what they
    # said (unfinished) rather than reciting a next scripted step.
    assert not any(b in script.reveal for b in new_voice)


# ------------------------------------------- the canonical play shape


def test_specimen_play_shape_pursuit_before_impression(ve_ctx, tmp_path):
    """Joshua's specimen (2026-10-23), the canonical shape: greet →
    the user brings THEIR OWN material with a real question → she
    pursues it (asks for the evidence of their experience) → only
    then may the impression come → recognition closes it."""
    uid = _seeded_user()
    gen = PatternGen()
    svc = _svc(tmp_path, gen)
    script = MT.get_script("conductor", 1)
    svc.start(uid, "conductor")

    # Turn 1 — the greeting answered. The generation offers a read;
    # the gate holds it: NO impression on the first substantive turn.
    gen.engage.append(
        "Mid-sentence is exactly right."
        "\n---\n"
        "A first read offered far too early."
        "\nStrands: Ear"
    )
    state = svc.turn(uid, "conductor", "Unfinished, I think.")
    assert state["stage"] == "encounter"
    row = svc.meetings.get(uid, "conductor", 1)
    assert row["readback_claim"] == ""
    assert not any("far too early" in b for b in _bodies(state))

    # Turn 2 — his own material, with a real question inside it
    # (precision-loving friends vs. free-spirited jazz; "classical
    # jazz"; "can it be reverse engineered?"). Question-shaped, so
    # the conversational frame runs — and it must carry the PURSUIT
    # instruction and her dictionary as available context.
    gen.turn.append(
        "Tell me about one of the times it just happened — when "
        "the precision and the loose playing locked for a moment."
        "\n[[thread:open]]"
    )
    prompts_before = len(gen.prompts)
    state = svc.turn(
        uid, "conductor",
        "It's like my two closest friends — one thrives on rigorous "
        "precision, everything charted, and the other only plays "
        "free, pure jazz instinct. I've been fascinated my whole "
        "life by classical jazz. Can something like that be reverse "
        "engineered?",
    )
    assert len(gen.prompts) - prompts_before == 1  # one generation
    turn_prompt = gen.prompts[-1]
    assert "mid-conversation in your workshop" in turn_prompt
    assert "pursue it BEFORE you read them" in turn_prompt
    assert "the evidence of their experience" in turn_prompt
    assert "Music & Composition" in turn_prompt  # dictionary rides along
    # No impression was smuggled into the pursuit turn either.
    assert svc.meetings.get(uid, "conductor", 1)["readback_claim"] == ""
    # His material is on the record as material: the undertaking
    # objective engaged, and the material turn is tracked.
    enc = _enc_state(svc, uid)
    assert enc.satisfied["own_undertaking_engaged"] is True
    assert enc.material_turn == 2

    # Turn 3 — he gives her the evidence she asked for. The pursuit
    # exchange has now occurred, and the impression may finally land.
    gen.engage.append(
        "A minute of it locking — that's the evidence that matters."
        "\n---\n"
        "A first read, in her own words: you hold precision and "
        "freedom in one hearing, and you keep asking whether the "
        "join can be learned rather than merely witnessed."
        "\nStrands: Ear, Compass"
    )
    state = svc.turn(
        uid, "conductor",
        "Last spring, at a rehearsal — half the band reading charts, "
        "half improvising, and for about a minute it genuinely "
        "locked. Nobody could say afterwards how it happened.",
    )
    assert state["stage"] == "readback"
    enc = _enc_state(svc, uid)
    assert enc.satisfied["pursuit_exchange"] is True
    assert enc.satisfied["impression_offered"] is True

    # Turn 4 — his answer to the read settles it, and the floor is
    # met (his material was taken up AND pursued): the meeting
    # closes, with her reply AND the reveal in the closing state.
    gen.reply.append("Then it can be learned.\n[[thread:settled]]")
    state = svc.turn(
        uid, "conductor",
        "That's uncomfortably close to true. The holding-both part — yes.",
    )
    assert state["status"] == "complete"
    bodies = _bodies(state)
    assert "Then it can be learned." in bodies
    for paragraph in script.reveal:
        assert paragraph in bodies
    # Her reply precedes the reveal in the transcript.
    assert bodies.index("Then it can be learned.") < bodies.index(script.reveal[0])


# --------------------------------- the old two-turn playthrough is dead


def test_two_turn_playthrough_can_no_longer_close(ve_ctx, tmp_path):
    """His live run of #197, replayed: a dilemma-style answer, then
    the affirmation 'I definitely think you're understanding what
    I'm saying' — which met the completion card. Under the pattern
    those two turns produce NO close: the first begins the shared
    work (no impression), and the affirmation — arriving before
    any impression exists — is conversation, not an answer."""
    uid = _seeded_user()
    gen = PatternGen()
    svc = _svc(tmp_path, gen)
    svc.start(uid, "conductor")

    gen.engage.append("Noted at the bench.\n---\nAn early read.\nStrands: Compass")
    state = svc.turn(
        uid, "conductor",
        "I listen to the planner — nothing moves until everything is planned.",
    )
    assert state["status"] == "active"
    assert state["stage"] == "encounter"  # the read was gated

    gen.engage.append("Heard.\n---\nThe read, when it comes.\nStrands: Compass")

    state = svc.turn(
        uid, "conductor",
        "I definitely think you're understanding what I'm saying.",
    )
    # NOT complete — the anticlimax is structurally impossible.
    # (The affirmation was a substantive turn with the gate now
    # satisfied, so the read it was answering finally exists: the
    # meeting is at the read-back, not at the card.)
    assert state["status"] == "active"
    assert state["stage"] == "readback"

    # And the meeting still completes gracefully from here: answer
    # the read, and recognition — meaningful now — closes it.
    gen.reply.append("Good — then we've met.\n[[thread:settled]]")
    state = svc.turn(uid, "conductor", "Yes. That's the shape of it.")
    assert state["status"] == "complete"


# ------------------------------------------ the closing payload is whole


def test_closing_state_carries_reply_and_reveal_together(ve_ctx, tmp_path):
    """The backend half of note 6's missing lines, at the service
    layer: an ack-classified impression answer must produce her
    spoken reply AND every reveal paragraph in the SAME returned
    state (the #197 backend was already sound here — this pins it
    so it stays sound; the actual defect was presentational, in
    MeetingView, and its regression test lives there)."""
    uid = _seeded_user()
    gen = PatternGen()
    svc = _svc(tmp_path, gen)
    script = MT.get_script("conductor", 1)
    svc.start(uid, "conductor")
    gen.engage.append("Heard at the bench.")
    svc.turn(uid, "conductor", "I decide by what breaks first if I ignore it.")
    gen.engage.append(
        "And heard again."
        "\n---\n"
        "A first read, in her own words: triage is your native tempo."
        "\nStrands: Compass"
    )
    svc.turn(uid, "conductor", "Mostly I protect the mornings before anything else.")
    gen.reply.append("A brief engaged reply; the impression stands.\n[[thread:settled]]")
    state = svc.turn(uid, "conductor", "Yes — that's exactly right.")
    assert state["status"] == "complete"
    bodies = _bodies(state)
    reply = "A brief engaged reply; the impression stands."
    assert reply in bodies
    for paragraph in script.reveal:
        assert paragraph in bodies
    assert bodies.index(reply) < bodies.index(script.reveal[0])


# -------------------------------------- dictionary: available, not owed


def test_dictionary_frame_is_available_context_under_three_layers(ve_ctx, tmp_path):
    script = MT.get_script("conductor", 1)
    definition = ENC.get_definition(script)
    frame = definition.dictionary_frame
    record = JX.get_jurisdiction("conductor")
    # The registry's dictionary, framed by the definition.
    assert frame.startswith("Your dictionary is available to you")
    assert record.dictionary.domain in frame
    for word in record.dictionary.lexicon:
        assert word in frame, word
    assert record.dictionary.perspective in frame
    # The three layers, with ordinary speech the default and the
    # no-obligation rule in so many words.
    assert "ordinary speech" in frame
    assert "the default" in frame
    assert "No layer is mandatory" in frame
    assert "never a quota" in frame
    assert "never owed" in frame
    # The frame rides BOTH generation paths (engage + conversational).
    assert frame in definition.engage_frame
    # And no frame on the encounter path instructs per-turn metaphor
    # use — availability wording only, obligation wording nowhere.
    frames = {
        "engage": definition.engage_frame,
        "turn": definition.turn_frame,
        "impression": definition.impression_frame,
        "correction": definition.correction_frame,
        "impression_reply": definition.impression_reply_frame,
        "dictionary": definition.dictionary_frame,
    }
    obligation = re.compile(
        r"(every (reply|turn|response)|each (reply|turn|response)|"
        r"always (use|include|speak)|must (use|include) (a |one )?"
        r"(metaphor|word|term)|one metaphor|a metaphor (in|per|each))",
        re.IGNORECASE,
    )
    for name, text in frames.items():
        assert not obligation.search(text), name


def test_hedge_instruction_names_its_claim(ve_ctx, tmp_path):
    script = MT.get_script("conductor", 1)
    definition = ENC.get_definition(script)
    frame = definition.impression_frame
    # The exact-point-of-doubt discipline, instructed.
    assert "name THAT part as the guess" in frame
    assert "the part I may have wrong is" in frame
    assert "blanket hedge" in frame
    # The old unanchored instruction is gone.
    assert "phrase it as a first impression that may be wrong" not in frame


# ------------------------------- the generic bank machinery survives


class _FakeHost:
    """The encounter host protocol, recorded — for driving the
    runtime directly at the layer where the bank mechanics live."""

    def __init__(self, gen_output=""):
        self.said: list[str] = []
        self.generated_frames: list[str] = []
        self.gen_output = gen_output
        self.impressions: list[tuple[str, list[str]]] = []
        self.closed_with: str | None = None

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


def test_generic_question_bank_machinery_still_works():
    """The Weaver's bank is retired, but the machinery is generic
    and stays for future scripts: a pass advances the bank at no
    generation cost, and exhausting it forms the impression from
    the whole exchange (an ungated definition, as every generic
    definition is)."""
    import dataclasses

    base = MT.get_script("conductor", 1)
    script = dataclasses.replace(
        base,
        archetype_id="mentor",
        questions=(
            "First banked question?",
            "Second banked question?",
            "Third banked question?",
        ),
    )
    definition = ENC.build_definition(script)
    assert definition.question_bank == script.questions
    assert definition.impression_gate_objective == ""
    assert definition.close_floor_objectives == ()

    host = _FakeHost(gen_output="An impression from the exchange.\nStrands: Compass")
    runtime = ENC.EncounterRuntime(definition)
    state = ENC.EncounterState()
    idx = runtime.handle_turn(host, state, "pass", 0)
    assert host.said == ["Second banked question?"]
    assert host.generated_frames == []  # a banked pass spends nothing
    idx = runtime.handle_turn(host, state, "skip", idx)
    assert host.said[-1] == "Third banked question?"
    idx = runtime.handle_turn(host, state, "pass", idx)
    assert host.impressions and host.impressions[0][0].startswith("An impression")
    assert state.impression_offered is True
