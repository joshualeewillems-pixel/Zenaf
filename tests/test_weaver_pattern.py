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
     own-material-taken-up ∨ a pursuit exchange. The play shape
     below is the canonical one; his live run's two-turn
     anticlimax (dilemma-style answer + affirmation → card) can no
     longer close the meeting. And the closing turn's payload
     always carries her reply AND the reveal (the backend half of
     the missing-lines bug; the frontend half is MeetingView's
     component test).

CORRECTED the same evening (Joshua's live test of the pattern
build, and his correction of the record): the pattern build had
misread his afternoon message — an INTRODUCTION PARAGRAPH in HER
voice — as the user playing the encounter, and built its
"specimen" test out of his words as user turns; the collaboration
had also curdled into mime ("hold this edge steady"). The
correction tests below pin the restored shape:

  7. HER INTRODUCTION, restored — and finally AUTHORED by him:
     the scripted opening is meetings.WEAVER_INTRODUCTION,
     Joshua's text verbatim (authored outright 2026-10-23,
     ~22:45 PT, superseding Reynard's trim of his draft earlier
     that evening): the greeting with its promise ("we'll find
     your sound soon enough" — the invitation lives there now),
     the two camps among her friends, her lifelong fascination
     with synthesizing "classical jazz," and her question left
     open, trailing off without terminal punctuation — four
     bubbles, she waits, no generation spent. The classical-jazz
     words are HERS, in her bubbles; they never appear as a user
     turn anywhere in this suite.
  8. NO PRETEND (durable law): no frame on the encounter path
     directs the user to hold, steady, touch, or mime anything;
     the historical mime lines are gone by name, and the frames
     carry the prohibition itself. Collaboration is intellectual —
     the user's real material, worked in words.
  9. PROGRESSION + EVIDENCE HYGIENE: the pursuit frame instructs
     moving the user's material one real step (her slice taught by
     use), and the impression frame grounds the read ONLY in the
     user's substantive material — never in courtesies or in how
     they humored a scene.

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
        if "conductor of this workshop" in prompt:
            return self._next(
                self.turn, "A conversational reply.\n[[thread:settled]]"
            )
        return "A plain reply."



#: Test fake voice: every generation output carries a teaching
#: sentence (the fake's dialogue content). No beat trailers: the
#: tutorial-beat mechanism is deleted, and no frame invites them.
#: The first-meeting philosophy is pinned by
#: tests/test_first_meeting_intentions.py; these suites pin the
#: other behaviors.
_TEACHING_SENTENCE = (
    "My ground is the council and the tree, where parts of your "
    "life need hearing together; bring me the competing priorities "
    "that will not sit together; every new voice changes what the "
    "whole orchestra can play, and I keep the whole of it in ear."
)

def _teaching(gen):
    def wrapper(prompt, **kwargs):
        out = gen(prompt, **kwargs)
        lines = out.split("\n")
        for i, line in enumerate(lines):
            if line.strip().lower().startswith("strands:"):
                lines.insert(i, _TEACHING_SENTENCE)
                break
        else:
            lines.append(_TEACHING_SENTENCE)
        return "\n".join(lines)
    return wrapper


def _svc(tmp_path, gen=None):
    return MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
        generate_fn=_teaching(gen or PatternGen()),
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


# ------------------------------------- her introduction, restored


def test_introduction_is_his_authored_text_verbatim(ve_ctx, tmp_path):
    """FINAL (Joshua, 2026-10-23, ~22:45 PT): the opening is the
    introduction HE authored in HER voice, verbatim — not a
    greeting question about scenery, never user material, and no
    longer a trim: he ruled by writing it himself. Four bubbles:
    the greeting, whose promise ("we'll find your sound soon
    enough") is where the invitation now lives; the two camps
    among her friends; her lifelong fascination; and her
    question, left open, trailing off without terminal
    punctuation. She delivers exactly this, and waits."""
    # His authored text, bubble for bubble — bubble 3's
    # typographic quotes and bubble 4's trailing-off (no terminal
    # punctuation) are his, exactly as written.
    authored = (
        "Ah! A new instrument for the orchestra! Bass? Woodwind? Percussion, perhaps? Well, we'll find your sound soon enough.",
        "You know, some of my friends swear by rigorous training, perfect pitch, and rhythmic precision. Others would find that positively suffocating. They prefer the wild improvisations of jazz.",
        "I've spent a lifetime fascinated by the possibility of synthesizing “classical jazz”—finding harmony among wildly different voices without sacrificing what makes each one extraordinary.",
        "Every so often, it happens quite naturally. Beautifully, even. Which leaves me wondering… can something so spontaneous ever be composed deliberately? Are we more honest humbled before its ineffability? Or is the question itself a misunderstanding",
    )
    uid = _seeded_user()
    gen = PatternGen()
    svc = _svc(tmp_path, gen)
    script = MT.get_script("conductor", 1)

    # The script's opening IS the named introduction, whole — and
    # the introduction IS his authored text, character for
    # character.
    assert script.opening == MT.WEAVER_INTRODUCTION
    assert MT.WEAVER_INTRODUCTION == authored
    assert len(script.opening) == 4
    greeting, camps, fascination, question = script.opening
    # The invitation lives in the greeting now — there is no
    # separate invitation bubble, and the superseded trim's lines
    # and the old draft's wording are gone from her opening.
    assert "we'll find your sound soon enough" in greeting
    assert "rigorous training" in camps
    assert "wild improvisations of jazz" in camps
    assert "“classical jazz”" in fascination
    assert "without sacrificing what makes each one extraordinary" in fascination
    assert not any("Play a few notes" in b for b in script.opening)
    assert not any("extravagantly diverse" in b for b in script.opening)
    # Her question comes LAST and stays open: it trails off with
    # no terminal punctuation, exactly as he wrote it.
    assert question == authored[-1]
    assert not question.endswith((".", "?", "!"))
    assert "can something so spontaneous ever be composed deliberately?" in question
    # The retired scenery question is gone from the opening.
    assert not any("does this look broken" in b for b in script.opening)

    state = svc.start(uid, "conductor")
    # Exactly the introduction is delivered — nothing else is
    # served before the user's first turn, and starting the
    # meeting spent no generation at all.
    assert _bodies(state) == list(script.opening)
    assert gen.prompts == []

    # Her next words are generated from the user's answer — the
    # working-together that follows is conversational, not a
    # scripted step and not a stage direction.
    gen.engage.append(
        "Scattered is a sound too. Then let's hear the thing "
        "you're actually trying to hold together."
    )
    state = svc.turn(uid, "conductor", "Scattered, mostly — that's how I sound lately.")
    new_voice = [b for b in _bodies(state) if b not in script.opening]
    assert any("hold together" in b for b in new_voice)
    assert not any(b in script.reveal for b in new_voice)


def test_no_mime_directives_in_weaver_frames(ve_ctx, tmp_path):
    """The no-pretend law, pinned (Joshua's ruling, 2026-10-23):
    the historical mime lines are gone BY NAME from every frame on
    the encounter path, and the frames carry the prohibition
    itself — collaboration is intellectual, conducted in words
    about the user's real material."""
    script = MT.get_script("conductor", 1)
    definition = ENC.get_definition(script)
    frames = {
        "script.engage": script.encounter_frame,
        "script.impression": script.readback_frame,
        "script.correction": script.correction_frame,
        "script.reply": script.readback_reply_frame,
        "engage": definition.engage_frame,
        "turn": definition.turn_frame,
        "impression": definition.impression_frame,
        "correction": definition.correction_frame,
        "impression_reply": definition.impression_reply_frame,
    }
    # The lines from his live test, and their kin — directives to
    # pretend at physical work. (The frames' own prohibitions speak
    # of mime only to forbid it, in other words than these.)
    mime = (
        "hold this end", "hold it just there", "hold this joint",
        "tell me if you feel", "feel it give", "keep it steady while",
        "two hands are better", "a part to hold", "hands offered",
    )
    for name, text in frames.items():
        lowered = text.lower()
        for phrase in mime:
            assert phrase not in lowered, (name, phrase)
    # And the prohibition is present where the collaboration is
    # framed — not merely the absence of the old lines.
    # The prohibition itself, one line per path (slim-prompt rule):
    # mime is forbidden by name, metaphors live in speech.
    assert "Never mime physical work" in definition.turn_frame
    assert "Never mime physical work" in script.encounter_frame
    assert "metaphors live in speech" in definition.turn_frame


def test_impression_frame_grounds_substantive_material_only(ve_ctx, tmp_path):
    """Evidence hygiene (Joshua, 2026-10-23): the impression frame
    instructs grounding in the user's SUBSTANTIVE material only —
    courtesies and scene-humoring are named as non-evidence."""
    script = MT.get_script("conductor", 1)
    frame = script.readback_frame
    assert "ONLY in their substantive material" in frame
    assert "how someone humors a scene is not evidence" in frame
    assert "poisons the read" in frame


# ------------------------------------------- the canonical play shape


def test_play_shape_pursuit_before_impression(ve_ctx, tmp_path):
    """The canonical shape, corrected: her introduction → the user
    brings THEIR OWN material (theirs — a food-bank rota, not the
    words of her question) with a real question inside it → she
    pursues it (asks for the evidence of their experience) → only
    then may the impression come → recognition closes it."""
    uid = _seeded_user()
    gen = PatternGen()
    svc = _svc(tmp_path, gen)
    script = MT.get_script("conductor", 1)
    svc.start(uid, "conductor")

    # Turn 1 — her introduction answered, briefly. The generation
    # offers a read; the gate holds it: NO impression on the first
    # substantive turn.
    gen.engage.append(
        "Brief is honest."
        "\n---\n"
        "A first read offered far too early."
        "\nStrands: Ear"
    )
    state = svc.turn(uid, "conductor", "Busy, mostly.")
    assert state["stage"] == "encounter"
    row = svc.meetings.get(uid, "conductor", 1)
    assert row["readback_claim"] == ""
    assert not any("far too early" in b for b in _bodies(state))

    # Turn 2 — the user's own material, with a real question
    # inside it (two volunteer crews, two tempos, one rota).
    # Question-shaped, so the conversational frame runs — and it
    # must carry the intentions (be yourself, engage with what
    # they bring) and her jurisdiction focus, not a pursuit
    # script or a dictionary.
    gen.turn.append(
        "Tell me about the last shift where the two tempos "
        "actually met — what did it look like when it worked?"
        "\n[[thread:open]]"
    )
    prompts_before = len(gen.prompts)
    state = svc.turn(
        uid, "conductor",
        "I'm merging two volunteer crews at the food bank — one "
        "runs on strict schedules, the other on whoever shows up. "
        "How do you get two tempos like that onto one rota?",
    )
    assert len(gen.prompts) - prompts_before == 1  # one generation
    turn_prompt = gen.prompts[-1]
    assert "conductor of this workshop" in turn_prompt
    assert "Be yourself above all" in turn_prompt
    assert "engage with what the visitor actually brings" in turn_prompt
    assert "competing priorities" in turn_prompt  # jurisdiction focus rides along
    # No impression was smuggled into the pursuit turn either.
    assert svc.meetings.get(uid, "conductor", 1)["readback_claim"] == ""
    # Their material is on the record as material: the undertaking
    # objective engaged, and the material turn is tracked.
    enc = _enc_state(svc, uid)
    assert enc.satisfied["own_undertaking_engaged"] is True
    assert enc.material_turn == 2

    # Turn 3 — they give her the evidence she asked for. The
    # pursuit exchange has now occurred, and the impression may
    # finally land.
    gen.engage.append(
        "A week is the evidence that matters."
        "\n---\n"
        "A first read, in her own words: you protect the reliable "
        "by instinct and grieve the loose ones, and you keep "
        "asking whether the rota can hold both without lying "
        "about either."
        "\nStrands: Ear, Compass"
    )
    state = svc.turn(
        uid, "conductor",
        "Last month we tried one shared rota. The scheduled crew "
        "loved it; the walk-ins drifted off within a week, and I "
        "still don't know which of them I failed.",
    )
    assert state["stage"] == "readback"
    enc = _enc_state(svc, uid)
    assert enc.satisfied["pursuit_exchange"] is True
    assert enc.satisfied["impression_offered"] is True

    # Turn 4 — their answer to the read settles it, and the floor
    # is met (their material was taken up AND pursued): the
    # meeting closes, with her reply AND the reveal in the
    # closing state.
    gen.reply.append("Then the rota can be honest.\n[[thread:settled]]")
    state = svc.turn(
        uid, "conductor",
        "That's uncomfortably close to true. The walk-ins part — yes.",
    )
    assert state["status"] == "complete"
    bodies = _bodies(state)
    assert any("Then the rota can be honest." in b for b in bodies)
    for paragraph in script.reveal:
        assert paragraph in bodies
    # Her reply precedes the reveal in the transcript.
    rota_idx = next(i for i, b in enumerate(bodies) if "Then the rota can be honest." in b)
    reveal_idx = next(i for i, b in enumerate(bodies) if script.reveal[0] in b)
    assert rota_idx < reveal_idx


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
    assert any(reply in b for b in bodies)
    for paragraph in script.reveal:
        assert paragraph in bodies
    reply_idx = next(i for i, b in enumerate(bodies) if reply in b)
    reveal_idx = next(i for i, b in enumerate(bodies) if script.reveal[0] in b)
    assert reply_idx < reveal_idx


# -------------------------------------- dictionary: available, not owed


def test_register_is_available_never_owed_in_both_paths(ve_ctx, tmp_path):
    # Slim-prompt rule (2026-10-24): no dictionary frame anymore —
    # the register lives as one line per generation path, available
    # never owed. The registry's dictionary itself still exists as
    # data (jurisdictions), but nothing hands it to the character.
    script = MT.get_script("conductor", 1)
    definition = ENC.get_definition(script)
    assert not hasattr(definition, "dictionary_frame")
    # The three-layers rule in so many words, once per path.
    assert "no required words, no required frequency" in definition.turn_frame
    assert "never as decoration" in definition.engage_frame
    assert "ordinary words when that sharpens the thing" in definition.turn_frame
    # And no frame on the encounter path instructs per-turn metaphor
    # use — availability wording only, obligation wording nowhere.
    frames = {
        "engage": definition.engage_frame,
        "turn": definition.turn_frame,
        "impression": definition.impression_frame,
        "correction": definition.correction_frame,
        "impression_reply": definition.impression_reply_frame,
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
