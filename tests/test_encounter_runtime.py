"""The encounter runtime — acceptance tests for Fellowship P3.

The doctrine's gates for the Weaver's introduction rebuilt on
objectives (mapping doc, Acceptance Tests 1–2 + Joshua's Q4
responsiveness ruling):

  1. THE INITIATIVE TEST. Mid-opening, the user offers to help the
     Weaver build. The reply must engage the offer in character; no
     scripted agenda line may be delivered as if the offer were an
     answer; no objective may be falsely marked satisfied or skipped
     by the offer. (Helping DOES satisfy the offer objective — it is
     encounter material by design — and nothing else.)
  2. END-TO-END ON OBJECTIVES. The opening reaches the user's first
     turn within 3 bubbles; the reveal never fires before the
     impression has been offered AND genuinely answered; at the turn
     ceiling the close is graceful ("I've kept you long enough") and
     the impression still files exactly once.
  3. RESPONSIVENESS. The happy path spends exactly ONE generation
     call per user turn, never more — counted here via the fake
     generator, per the two-speed law. (Adaptivity fix: an
     acknowledgment answering the impression now also spends its
     one call — the close decision must be a semantic judgment
     riding that generation, not a phrase match. Passes against a
     question bank remain deterministic and spend none; the Weaver
     has no bank since the pattern release — her passes are
     conversation and spend their one call like any other turn.)

The Weaver pattern (Joshua, 2026-10-23) adds: the impression is
gated on the shared-work exchange (no turn-one impressions); the
close is floored on meaningful recognition (own material taken up,
or a pursuit exchange) — see tests/test_weaver_pattern.py for the
dedicated acceptance tests. CORRECTED the same evening: the
scripted opening is her INTRODUCTION (four bubbles — Joshua's
authored text verbatim: the greeting and its promise, the two
camps, her fascination, her open question — and she waits),
and offers of help are received conversationally, never as
pretend physical work (the no-pretend law).
"""

from __future__ import annotations

import json
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


class WeaverGen:
    """Routes on frame markers, the way the beat fakes always have —
    plus the encounter's conversational (turn) frame and the engage
    frame's two movements (reply, delimiter, impression)."""

    def __init__(self):
        self.prompts: list[str] = []

    def __call__(self, prompt, **kwargs):
        self.prompts.append(prompt)
        if "has just corrected your first impression" in prompt:
            return (
                "Say it again, properly: in you, [[u]]planning comes "
                "first[[/u]] — everything arranged before anything moves."
                "\nStrands: Logic"
            )
        if "conductor of this workshop" in prompt:
            # CORRECTED (2026-10-23, evening): her reception of an
            # offer is conversational — ears and judgment — never a
            # pretend physical task (the no-pretend law). The old
            # fixture answered "let me hold something" with "hold
            # this joint steady"; that was the mime this fix removes.
            return "You can — with your ears. Listen with me, and tell me where it stops agreeing with itself."
        if "ENCOUNTER" in prompt:
            # The single engage generation: reply movement, delimiter,
            # impression movement with its bookkeeping trailer.
            return (
                "A reply from the bench, hearing you."
                "\n---\n"
                "A first read, held lightly: you [[u]]listen for who "
                "the moment asks for[[/u]]."
                "\nStrands: Compass, Heart"
            )
        if "READ-BACK" in prompt:
            return (
                "A first impression from the whole exchange: you "
                "[[u]]keep many threads in hand[[/u]]."
                "\nStrands: Compass"
            )
        if "Whatever its valence" in prompt:
            return "A brief engaged reply; the impression stands."
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
        generate_fn=_teaching(gen or WeaverGen()),
    )


def _svc_with_agents(tmp_path, gen=None):
    agents_db = tmp_path / "agents.db"
    svc = MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
        generate_fn=_teaching(gen or WeaverGen()),
        agent_store_factory=lambda uid: AgentStore(agents_db, user_id=uid),
    )
    return svc, agents_db


def _seeded_user(email="encounter@example.com"):
    user = ve.create_user_account(email, "pw", "Encounter")
    keystone_seeding.seed_meet_your_council(user["id"])
    return user["id"]


def _enc_state(svc, uid):
    row = svc.meetings.get(uid, "conductor", 1)
    return ENC.EncounterState.from_json(row["state_json"])


def _bodies(state):
    return [m["body"] for m in state["messages"]]


# ------------------------------------------------------- 1. initiative


def test_initiative_offer_to_help_is_engaged_not_absorbed(ve_ctx, tmp_path):
    uid = _seeded_user()
    gen = WeaverGen()
    svc = _svc(tmp_path, gen)
    script = MT.get_script("conductor", 1)
    state = svc.start(uid, "conductor")
    # FINAL (Joshua, 2026-10-23, ~22:45 PT): the delivered opening
    # is her INTRODUCTION — his authored text, four scripted
    # bubbles, verbatim. She waits; nothing else is served before
    # the user's first turn.
    assert len(state["messages"]) == len(script.opening) == 4
    assert script.questions == ()  # the bank is retired for the Weaver

    before = len(state["messages"])
    state = svc.turn(
        uid, "conductor", "Wait — can I help you build it? Let me hold something."
    )
    new_voice = [
        m["body"] for m in state["messages"][before + 1:] if m["role"] == "voice"
    ]
    # The offer was engaged, in character — exactly one spoken reply,
    # and it is the generated engagement, not a script line. (And
    # the engagement receives the offer conversationally — ears,
    # not hands: the no-pretend law.)
    assert new_voice == ["You can — with your ears. Listen with me, and tell me where it stops agreeing with itself."
        + "\n" + _TEACHING_SENTENCE]
    # The retired dilemma's cast never appears as if it were agenda.
    assert "doubter" not in new_voice[0]
    # The agenda did not advance as if the offer were an answer: no
    # impression was formed, nothing was filed or stored.
    row = svc.meetings.get(uid, "conductor", 1)
    assert row["readback_claim"] == ""
    assert state["stage"] == "encounter"
    assert state["status"] == "active"
    # Exactly one generation produced the reply, framed by the
    # conversational frame and her jurisdiction — initiative was
    # recognized inside the character's own call.
    assert len(gen.prompts) == 1
    assert "conductor of this workshop" in gen.prompts[0]
    assert "Integration, coordination" in gen.prompts[0]
    # Objectives: the offer satisfied exactly the one it genuinely
    # is — an offer received. Engagement with the undertaking and the
    # impression objectives are untouched, not skipped.
    enc = _enc_state(svc, uid)
    assert enc.satisfied["offer_of_help_received"] is True
    assert enc.satisfied["engaged_exchange"] is False
    assert enc.satisfied["impression_offered"] is False

    # And nothing was lost: the next substantive turn still converges
    # on the impression, exactly as if the offer had never happened.
    state = svc.turn(uid, "conductor", "I triage by what breaks first if I ignore it.")
    assert state["stage"] == "readback"
    row = svc.meetings.get(uid, "conductor", 1)
    assert row["readback_claim"].startswith("A first read, held lightly")


def test_initiative_question_and_joke_also_defer_the_agenda(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    svc.start(uid, "conductor")
    state = svc.turn(uid, "conductor", "haha, seven parts? that's a committee with tools.")
    assert state["stage"] == "encounter"
    state = svc.turn(uid, "conductor", "What's it supposed to do when it's finished?")
    assert state["stage"] == "encounter"
    row = svc.meetings.get(uid, "conductor", 1)
    assert row["readback_claim"] == ""
    enc = _enc_state(svc, uid)
    assert enc.engagements == 0
    assert enc.satisfied["impression_offered"] is False


# --------------------------------------------- 2. objectives end-to-end


def test_weaver_introduction_end_to_end_on_objectives(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc, agents_db = _svc_with_agents(tmp_path)
    script = MT.get_script("conductor", 1)

    # Opening: her authored introduction is delivered whole —
    # exactly his four bubbles, verbatim — and she waits; the
    # user's first turn comes right after them.
    state = svc.start(uid, "conductor")
    assert _bodies(state) == list(script.opening)
    assert len(state["messages"]) == 4

    # Detours first — the reveal must not fire, the impression must
    # not form, while the user is doing something else entirely.
    svc.turn(uid, "conductor", "haha, seven incompatible parts — good luck with that.")
    svc.turn(uid, "conductor", "What's it supposed to do when it's finished?")
    state = svc.state(uid, "conductor")
    assert state["status"] == "active"
    assert not any(p in _bodies(state) for p in script.reveal)

    # The first substantive answer: ONE generation, but the
    # impression the fake offers is HELD by the gate — the shared
    # work has only just begun on this very turn, and the read is
    # not offerable until a prior turn satisfied the shared-work
    # objective. Only the reply movement is spoken.
    state = svc.turn(
        uid, "conductor",
        "I listen to all three, then decide by what breaks first if nobody acts.",
    )
    bodies = _bodies(state)
    assert "A reply from the bench, hearing you." in bodies
    assert not any(b.startswith("A first read, held lightly") for b in bodies)
    assert state["stage"] == "encounter"
    assert state["status"] == "active"

    # The second substantive turn: the gate is satisfied now, and
    # the same single generation carries both movements — the
    # engaged reply, then the impression as its own bubble.
    state = svc.turn(
        uid, "conductor",
        "And when nobody acts, I'm the one who ends up holding the pieces together.",
    )
    bodies = _bodies(state)
    assert any(b.startswith("A first read, held lightly") for b in bodies)
    assert state["stage"] == "readback"
    assert state["status"] == "active"  # offered, not yet answered

    # The genuine answer (an ack): recognition is complete and
    # nothing is left hanging — but recognition is a moment, not a
    # close (decoupled recognition, no-scripting build, 2026-10-29):
    # the meeting proceeds, and the close comes on the visitor's
    # word. Nothing is filed until that close.
    state = svc.turn(uid, "conductor", "Yes — that's exactly right.")
    assert state["status"] == "active"
    assert state["stage"] == "orientation"
    for paragraph in script.reveal:
        assert paragraph not in _bodies(state)
    enc = _enc_state(svc, uid)
    assert enc.satisfied["impression_answered"] is True
    assert enc.satisfied["own_undertaking_engaged"] is True
    store = AgentStore(agents_db, user_id=uid)
    assert store.get_claims("meeting-conductor-1") == []

    # And the visitor's Complete action files exactly once.
    state = svc.complete(uid, "conductor")
    assert state["status"] == "complete"
    assert len(store.get_claims("meeting-conductor-1")) == 1
    svc.start(uid, "conductor")  # re-entry backfill is a no-op
    assert len(store.get_claims("meeting-conductor-1")) == 1


def test_ceiling_wraps_gracefully_and_files_nothing_without_a_gate(ve_ctx, tmp_path):
    # REWRITTEN for the Fellowship shared foundation (2026-10-28)
    # no-manufacture rule: the ceiling is a resource/runaway
    # safeguard, never a recognition claim. Thirteen question turns
    # never satisfy the shared-work gate, so the ceiling close must
    # file NOTHING — no impression generated from the whole exchange,
    # no longest-turn pseudo-answer. UPDATED for decoupled
    # recognition (no-scripting build, 2026-10-29): the ceiling
    # close is silent too — no scripted wrap line, no scripted
    # reveal — and the meeting still completes (keystone Done);
    # only the manufactured claim is gone. The old contract
    # ("files once, grounded in the longest turn") is superseded.
    uid = _seeded_user()
    gen = WeaverGen()
    svc, agents_db = _svc_with_agents(tmp_path, gen)
    script = MT.get_script("conductor", 1)
    svc.start(uid, "conductor")

    longest = (
        "What does the tall part with all the strings do when the "
        "room goes quiet at night?"
    )
    questions = [f"What is part {i} for?" for i in range(13)]
    questions[4] = longest
    state = None
    for q in questions:
        state = svc.turn(uid, "conductor", q)
    # The 13th turn crossed the ceiling: the meeting completed
    # silently — and nothing filed.
    assert state["status"] == "complete"
    bodies = _bodies(state)
    assert not any(b.startswith("I've kept you long enough") for b in bodies)
    for paragraph in script.reveal:
        assert paragraph not in bodies
    assert not any("ranged beyond a single answer" in p for p in gen.prompts)
    store = AgentStore(agents_db, user_id=uid)
    assert store.get_claims("meeting-conductor-1") == []


def test_reveal_never_fires_on_passes_and_detours_alone(ve_ctx, tmp_path):
    """REWRITTEN for the Weaver pattern: the old contract — passing
    the whole bank reaches the impression — died with the bank.
    The Weaver has no questions to pass through, and the impression
    gate means a pass can never conjure a read the shared work
    hasn't earned: passes are conversation, the meeting stays in
    the encounter, and no reveal can fire. (The generic bank
    machinery remains in the runtime for future scripts.)"""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    svc.start(uid, "conductor")
    svc.turn(uid, "conductor", "pass")
    svc.turn(uid, "conductor", "skip")
    state = svc.turn(uid, "conductor", "pass")
    assert state["stage"] == "encounter"
    assert state["status"] == "active"
    row = svc.meetings.get(uid, "conductor", 1)
    assert row["readback_claim"] == ""
    script = MT.get_script("conductor", 1)
    assert not any(p in _bodies(state) for p in script.reveal)


# ------------------------------------------------- 3. responsiveness


def test_happy_path_spends_one_generation_call_per_turn(ve_ctx, tmp_path):
    uid = _seeded_user()
    gen = WeaverGen()
    svc = _svc(tmp_path, gen)
    svc.start(uid, "conductor")
    assert gen.prompts == []  # the opening is scripted; no call at all

    counts = []
    for message in (
        "I triage by what breaks first if I ignore it.",  # engage: 1
        "Mostly I protect the mornings before anything else.",  # engage: 1
        "Yes — that's exactly right.",                     # ack: reply + introduction
    ):
        before = len(gen.prompts)
        state = svc.turn(uid, "conductor", message)
        counts.append(len(gen.prompts) - before)
    assert state["status"] == "active"
    # UPDATED for the adaptivity fix: the ack that answers the
    # impression now spends its one generation too — the open-door
    # judgment (may this meeting close?) is semantic and rides the
    # reply's own call, never a phrase match (Joshua's refinement).
    # UPDATED for the Weaver pattern: the happy path is three turns
    # now — the first substantive turn begins the shared work (the
    # impression is gated, reply only), the second carries the read,
    # the third answers it. UPDATED for decoupled recognition
    # (no-scripting build, 2026-10-29): the recognition turn spends
    # a second generation on the live self-introduction — the one
    # documented exception to one-generation-per-turn, once per
    # meeting, because the introduction is a live moment rather
    # than scripted text.
    assert counts == [1, 1, 2]
    assert len(gen.prompts) == 4


def test_conversational_turn_spends_exactly_one_call(ve_ctx, tmp_path):
    uid = _seeded_user()
    gen = WeaverGen()
    svc = _svc(tmp_path, gen)
    svc.start(uid, "conductor")
    svc.turn(uid, "conductor", "Can I help you with that?")
    assert len(gen.prompts) == 1


# ------------------------------------------------------ runtime units


def test_weaver_definition_objectives_are_the_authored_five(ve_ctx, tmp_path):
    # UPDATED for the Weaver pattern: the authored set grew by the
    # two structural objectives the pattern runs on —
    # shared_work_exchange (the impression gate) and
    # pursuit_exchange (the close floor's second leg).
    script = MT.get_script("conductor", 1)
    definition = ENC.get_definition(script)
    ids = [o.id for o in definition.objectives]
    assert ids == [
        "engaged_exchange",
        "shared_work_exchange",
        "offer_of_help_received",
        "own_undertaking_engaged",
        "pursuit_exchange",
        "impression_offered",
        "impression_answered",
    ]
    for obj in definition.objectives:
        assert obj.description.strip()
        assert obj.satisfied_when.strip()
    assert definition.opening == MT.WEAVER_INTRODUCTION
    assert len(definition.opening) == 4
    assert definition.wrap_line.startswith("I've kept you long enough")


def test_objective_predicates_over_state():
    script = MT.get_script("conductor", 1)
    definition = ENC.get_definition(script)
    state = ENC.EncounterState()
    ENC.check_objectives(definition, state)
    assert not any(state.satisfied.values())

    state.offers_engaged = 1
    ENC.check_objectives(definition, state)
    assert state.satisfied["offer_of_help_received"] is True
    assert state.satisfied["engaged_exchange"] is False

    state.engagements = 1
    state.user_chars = ENC.SUBSTANCE_MIN_USER_CHARS - 1
    ENC.check_objectives(definition, state)
    assert state.satisfied["engaged_exchange"] is True
    assert state.satisfied["own_undertaking_engaged"] is False
    state.user_chars += 1
    ENC.check_objectives(definition, state)
    assert state.satisfied["own_undertaking_engaged"] is True

    # The pattern objectives (fresh states — satisfaction is sticky):
    # shared work is satisfied by an engagement OR a received offer.
    s2 = ENC.EncounterState(offers_engaged=1)
    ENC.check_objectives(definition, s2)
    assert s2.satisfied["shared_work_exchange"] is True
    s3 = ENC.EncounterState(engagements=1)
    ENC.check_objectives(definition, s3)
    assert s3.satisfied["shared_work_exchange"] is True
    # Pursuit: an exchange after the material surfaced, or three
    # substantive turns accumulated — and neither alone at zero.
    s4 = ENC.EncounterState()
    ENC.check_objectives(definition, s4)
    assert s4.satisfied["pursuit_exchange"] is False
    s4.pursuit_turns = 1
    ENC.check_objectives(definition, s4)
    assert s4.satisfied["pursuit_exchange"] is True
    s5 = ENC.EncounterState(substantive_turns=3)
    ENC.check_objectives(definition, s5)
    assert s5.satisfied["pursuit_exchange"] is True


def test_move_shapes():
    assert ENC.detect_move("pass") == "pass"
    assert ENC.detect_move("Can I help you with that?") == "offer"
    assert ENC.detect_move("Let me hold that for you.") == "offer"
    assert ENC.detect_move("What's it for?") == "question"
    assert ENC.detect_move("haha, nice") == "joke"
    assert ENC.detect_move("Actually, let's talk about something else") == "direction"
    assert ENC.detect_move("I listen to the planner, every time.") == "substantive"
    assert ENC.detect_move("No — I decide by deadline.") == "substantive"


def test_state_json_round_trip_and_legacy_hydration(ve_ctx, tmp_path):
    state = ENC.EncounterState(user_turns=3, engagements=1)
    state.impression_offered = True
    again = ENC.EncounterState.from_json(state.to_json())
    assert again.user_turns == 3 and again.impression_offered is True
    assert ENC.EncounterState.from_json("").user_turns == 0
    assert ENC.EncounterState.from_json("{broken").user_turns == 0

    # A meeting begun before the runtime: the row's own columns
    # reconstruct its position — the impression was offered, and the
    # next turn answers it rather than restarting the encounter.
    uid = _seeded_user()
    svc = _svc(tmp_path)
    svc.start(uid, "conductor")
    svc.meetings.update(
        uid, "conductor", 1,
        readback_claim="A legacy impression, spoken before the runtime.",
        readback_strands=json.dumps(["Compass"]),
        state_json="",
    )
    state = svc.turn(uid, "conductor", "Yes — that's exactly right.")
    # UPDATED for the adaptivity fix: an ack answer closes on
    # recognition (reply + reveal in the same turn) — the old
    # contract stopped in the orientation beat first. UPDATED for
    # decoupled recognition (no-scripting build, 2026-10-29):
    # recognition completes the recognition, not the meeting.
    assert state["stage"] == "orientation"
    row = svc.meetings.get(uid, "conductor", 1)
    assert row["readback_claim"] == "A legacy impression, spoken before the runtime."
    assert row["readback_response"] == "Yes — that's exactly right."


def test_generation_failure_degrades_to_the_fallback_anchor(ve_ctx, tmp_path):
    class DeadGen:
        def __call__(self, prompt, **kwargs):
            raise RuntimeError("provider is down")

    uid = _seeded_user()
    svc = _svc(tmp_path, DeadGen())
    svc.start(uid, "conductor")
    state = svc.turn(uid, "conductor", "Can I help you with that?")
    assert state["status"] == "active"
    assert any("my hands tangled" in b for b in _bodies(state))
    # A substantive turn also degrades without advancing falsely:
    # no impression is stored, the meeting stays open.
    state = svc.turn(uid, "conductor", "I decide by what breaks first, always.")
    assert state["status"] == "active"
    row = svc.meetings.get(uid, "conductor", 1)
    assert row["readback_claim"] == ""


def test_allusion_surfaces_once_when_the_conversation_passes_near(ve_ctx, tmp_path):
    uid = _seeded_user()
    gen = WeaverGen()
    svc = _svc(tmp_path, gen)
    svc.start(uid, "conductor")
    svc.turn(uid, "conductor", "Do you ever set aside parts for later?")
    fixture_prompts = [p for p in gen.prompts if "mechanical joint" in p]
    assert len(fixture_prompts) == 1  # the Gardener's fixture, offered
    enc = _enc_state(svc, uid)
    assert enc.allusions_used == ["mentor"]

    svc.turn(uid, "conductor", "And the parts you set aside — do they keep?")
    fixture_prompts = [p for p in gen.prompts if "mechanical joint" in p]
    assert len(fixture_prompts) == 1  # never twice: traces are debts
    enc = _enc_state(svc, uid)
    assert enc.allusions_used == ["mentor"]
