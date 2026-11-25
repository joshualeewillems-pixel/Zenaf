"""V4 obligation-block gate — determination, toggle, recording, seam.

Zero live model calls: pure composition tests over synthetic states,
store-level tests against a temp NarrativeStore, and service turns
driven through the real ``ConversationService.turn`` with an injected
``generate_fn`` (the V1 noting test discipline).

Pins (scoping §3.5):
- Priya-shaped: an arc about capacity attended, no commitment taken
  up ⇒ apparatus OFF, "not relevant" recorded;
- commitment-shaped: a live proposal awaiting the visitor ⇒ ON;
- no-arc fallback over durable records — binary, recorded either way;
- toggle OFF ⇒ apparatus rendered unconditionally, byte-identical
  prompts given identical state;
- the capability awareness slice renders identically in all states;
- the determination is computed (and recorded) independently of the
  gate toggle and of capture rendering.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from local_ai.conversation.service import ConversationService
from local_ai.conversation.store import ConversationStore
from local_ai.narrative.obligation_gate import (
    GateCandidate,
    ObligationGate,
    compose_determination,
    determine_and_record,
    obligation_gate_enabled,
)
from local_ai.narrative.refs import SourceRef
from local_ai.narrative.store import NarrativeStore
from local_ai.vision_execution.obligations import PROPOSAL_INSTRUCTION

USER = "u-gate"
CONVO = "gate-convo"
CHAMPION = "champion"
BRANCH = "seat:champion"

PRIYA_ARC = (
    "responsibility to others versus exhausted capacity",
    "the mother appointment and the school forms keep arriving",
)


# -- flag ------------------------------------------------------------------------


def test_gate_flag_default_off(monkeypatch):
    monkeypatch.delenv("ZENAF_OBLIGATION_GATE", raising=False)
    assert obligation_gate_enabled() is False
    monkeypatch.setenv("ZENAF_OBLIGATION_GATE", "1")
    assert obligation_gate_enabled() is True
    monkeypatch.setenv("ZENAF_OBLIGATION_GATE", "off")
    assert obligation_gate_enabled() is False


# -- pure composition --------------------------------------------------------------


def test_priya_shaped_arc_attended_no_commitment_off():
    det = compose_determination(
        message="The school forms are due and I keep saying yes to everything.",
        arc_subjects=PRIYA_ARC,
        arc_thread_id="arc-1",
        candidates=[
            GateCandidate(
                kind="ve_task",
                text="Renew the gym membership",
                entity_refs=("ve_entity:task-gym-renewal",),
            )
        ],
    )
    assert det.arc_attended is True  # the arc IS what the exchange is about
    assert det.fires is False  # arc attendance alone never fires (§10.2)
    assert det.reasons == ("not_relevant",)


def test_commitment_shaped_live_proposal_on():
    det = compose_determination(
        message="I am not sure about anything today.",
        candidates=[
            GateCandidate(
                kind="proposal",
                text="A proposed reading awaiting the visitor",
                thread_id="thread-proposal",
                awaiting=True,
            )
        ],
    )
    assert det.fires is True
    assert "live_proposal_awaiting" in det.reasons


def test_no_arc_fallback_attended_task_on():
    det = compose_determination(
        message="I need to call the clinic about the referral today.",
        candidates=[
            GateCandidate(
                kind="ve_task",
                text="Call the clinic",
                entity_refs=("ve_entity:call-clinic",),
            )
        ],
    )
    assert det.fires is True


def test_no_arc_fallback_unattended_off():
    det = compose_determination(
        message="Tell me about the weather in the valley.",
        candidates=[
            GateCandidate(
                kind="ve_task",
                text="Call the clinic",
                entity_refs=("ve_entity:call-clinic",),
            )
        ],
    )
    assert det.fires is False
    assert det.reasons == ("not_relevant",)


def test_bounded_recency_followup_on():
    det = compose_determination(
        message="Yes, do it.",
        history_texts=("I need to call the clinic about the referral.",),
        candidates=[
            GateCandidate(
                kind="ve_task",
                text="Call the clinic",
                entity_refs=("ve_entity:call-clinic",),
            )
        ],
    )
    assert det.fires is True
    assert "bounded_recency" in det.reasons


# -- store-level: gathering + recording --------------------------------------------


@pytest.fixture()
def store(tmp_path):
    return NarrativeStore(tmp_path / "narrative.db")


def _evidence(store, user=USER):
    return SourceRef(kind="event", ref_id="evt-seed-1", evidence_kind="quote")


def _make_encounter_arc(store):
    thread = store.create_thread(
        USER,
        origin="steward_proposal",
        title="Encounter — champion — gate-convo",
        evidence_refs=[_evidence(store)],
    )
    store.open_encounter_scope(
        USER,
        thread.id,
        conversation_id=CONVO,
        archetype_id=CHAMPION,
        span_start_message_id="m-1",
    )
    store.propose_reading(
        USER,
        thread.id,
        author=CHAMPION,
        reading={"tensions": list(PRIYA_ARC)},
        evidence_refs=[_evidence(store)],
    )
    return thread


def _make_open_proposal(store):
    thread = store.create_thread(
        USER,
        origin="steward_proposal",
        title="A standing proposal thread",
        evidence_refs=[_evidence(store)],
    )
    store.propose_reading(
        USER,
        thread.id,
        author="steward",
        reading={"tensions": ["whether to take on the clinic referral"]},
        evidence_refs=[_evidence(store)],
    )
    return thread


def test_store_priya_determination_off_and_recorded(store):
    _make_encounter_arc(store)
    det = determine_and_record(
        store,
        USER,
        conversation_id=CONVO,
        message="The school forms are due and I keep saying yes to everything.",
    )
    assert det.arc_attended is True
    assert det.fires is False
    rows = store.assessments_for(USER, branch_id=BRANCH)
    assert len(rows) == 1
    assert rows[0].relevant is False
    assert rows[0].reasons == ["not_relevant"]


def test_store_proposal_determination_on_and_recorded(store):
    _make_open_proposal(store)
    det = determine_and_record(
        store,
        USER,
        conversation_id=CONVO,
        message="I am not sure about anything today.",
    )
    assert det.fires is True
    rows = store.assessments_for(USER, branch_id=BRANCH)
    assert len(rows) == 1
    assert rows[0].relevant is True
    assert "live_proposal_awaiting" in rows[0].reasons


def test_store_no_arc_fallback_recorded_either_way(store):
    det = determine_and_record(
        store,
        USER,
        conversation_id=CONVO,
        message="Tell me about the weather in the valley.",
    )
    assert det.fires is False
    rows = store.assessments_for(USER, branch_id=BRANCH)
    assert len(rows) == 1
    assert rows[0].relevant is False


# -- service seam --------------------------------------------------------------------


class RecordedGen:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.prompts = []

    def __call__(self, prompt, **kw):
        if kw.get("operation") == "conversation-thread-summary":
            return "Rolling summary of the thread."
        self.prompts.append(prompt)
        if self.outputs:
            return self.outputs.pop(0)
        return "Recorded reply."


class FakeSink:
    def __init__(self):
        self.event_ids = {}

    def __call__(self, **kw):
        message_id = kw["payload"]["message_id"]
        event_id = f"evt-{message_id}"
        self.event_ids[message_id] = event_id
        return SimpleNamespace(id=event_id)


@pytest.fixture()
def sink():
    return FakeSink()


def make_service(tmp_path, gen, sink, gate_store, name="conv.db"):
    return ConversationService(
        ConversationStore(db_path=tmp_path / name),
        generate_fn=gen,
        event_sink=sink,
        obligation_gate=ObligationGate(gate_store),
    )


def test_toggle_off_byte_identical_and_unconditional(tmp_path, store, sink, monkeypatch):
    monkeypatch.delenv("ZENAF_OBLIGATION_GATE", raising=False)
    gen_a = RecordedGen(["Plain reply."])
    svc_a = make_service(tmp_path, gen_a, sink, store, "conv-a.db")
    svc_a.turn(USER, CHAMPION, "Hello there.", conversation_id=CONVO)

    monkeypatch.setenv("ZENAF_OBLIGATION_GATE", "0")
    gen_b = RecordedGen(["Plain reply."])
    svc_b = make_service(tmp_path, gen_b, sink, store, "conv-b.db")
    svc_b.turn(USER, CHAMPION, "Hello there.", conversation_id=CONVO)

    assert gen_a.prompts == gen_b.prompts
    # Apparatus rendered unconditionally, exactly as today.
    assert PROPOSAL_INSTRUCTION in gen_a.prompts[0]
    # Slice not live (gate off, capture off): no determination ran.
    assert store.assessments_for(USER, branch_id=BRANCH) == []


def test_gate_on_not_firing_apparatus_absent_and_recorded(
    tmp_path, store, sink, monkeypatch
):
    monkeypatch.setenv("ZENAF_OBLIGATION_GATE", "1")
    gen = RecordedGen(["Plain reply."])
    svc = make_service(tmp_path, gen, sink, store)
    svc.turn(USER, CHAMPION, "Tell me about the weather.", conversation_id=CONVO)
    assert PROPOSAL_INSTRUCTION not in gen.prompts[0]
    rows = store.assessments_for(USER, branch_id=BRANCH)
    assert len(rows) == 1
    assert rows[0].relevant is False


def test_gate_on_firing_apparatus_rendered(tmp_path, store, sink, monkeypatch):
    _make_open_proposal(store)
    monkeypatch.setenv("ZENAF_OBLIGATION_GATE", "1")
    gen = RecordedGen(["Plain reply."])
    svc = make_service(tmp_path, gen, sink, store)
    svc.turn(USER, CHAMPION, "I am not sure today.", conversation_id=CONVO)
    assert PROPOSAL_INSTRUCTION in gen.prompts[0]
    rows = store.assessments_for(USER, branch_id=BRANCH)
    assert len(rows) == 1
    assert rows[0].relevant is True


def test_determination_runs_with_gate_off_when_capture_live(
    tmp_path, store, sink, monkeypatch
):
    """§3.1: the determination is toggle-independent — with capture
    live and the gate OFF it is still computed and recorded, while
    rendering stays unconditional."""
    monkeypatch.delenv("ZENAF_OBLIGATION_GATE", raising=False)
    monkeypatch.setenv("ZENAF_NOTING_CAPTURE_SEATS", "champion")
    gen = RecordedGen(["Plain reply."])
    svc = make_service(tmp_path, gen, sink, store)
    svc.turn(USER, CHAMPION, "Tell me about the weather.", conversation_id=CONVO)
    assert PROPOSAL_INSTRUCTION in gen.prompts[0]  # unconditional render
    rows = store.assessments_for(USER, branch_id=BRANCH)
    assert len(rows) == 1
    assert rows[0].relevant is False


def test_awareness_slice_identical_in_all_states(tmp_path, store, sink, monkeypatch):
    from local_ai.council.capabilities import VisitorState, continuation_block

    awareness = continuation_block(CHAMPION, VisitorState())
    assert awareness  # champion's slice is non-empty at default state

    prompts = {}
    # gate off
    monkeypatch.delenv("ZENAF_OBLIGATION_GATE", raising=False)
    gen = RecordedGen(["Plain reply."])
    make_service(tmp_path, gen, sink, store, "c-off.db").turn(
        USER, CHAMPION, "Hello there.", conversation_id=CONVO
    )
    prompts["off"] = gen.prompts[0]
    # gate on, not firing
    monkeypatch.setenv("ZENAF_OBLIGATION_GATE", "1")
    gen = RecordedGen(["Plain reply."])
    make_service(tmp_path, gen, sink, store, "c-on.db").turn(
        USER, CHAMPION, "Tell me about the weather.", conversation_id=CONVO
    )
    prompts["on_not_firing"] = gen.prompts[0]
    # gate on, firing
    _make_open_proposal(store)
    gen = RecordedGen(["Plain reply."])
    make_service(tmp_path, gen, sink, store, "c-fire.db").turn(
        USER, CHAMPION, "I am not sure today.", conversation_id=CONVO
    )
    prompts["on_firing"] = gen.prompts[0]

    for prompt in prompts.values():
        assert awareness in prompt
    # The awareness slice is byte-identical wherever it appears: the
    # only prompt difference between firing / not-firing is the
    # apparatus itself.
    assert prompts["on_not_firing"].replace(awareness, "<A>") != ""
    core = {
        name: prompt.replace(PROPOSAL_INSTRUCTION, "<APP>")
        for name, prompt in prompts.items()
    }
    assert awareness in core["off"]
    assert awareness in core["on_not_firing"]
    assert awareness in core["on_firing"]
