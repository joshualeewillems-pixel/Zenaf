"""Fellowship Runtime P1 — events, observations, derivation.

Covers the event → evidence → interpretation layer
(local_ai/fellowship/):

- events are emitted at the wired chokepoints (conversation turn,
  claim verdict, task completion, meeting completion, decision
  record) onto the activity log, and nowhere else changes behavior;
- the deterministic pre-filter: an event in the Weaver's focus makes
  her a candidate and does not make an unrelated seat one; an event in
  nobody's focus/periphery makes zero LLM calls;
- observations persist with verbatim evidence and the status
  lifecycle;
- the two-speed law's fault isolation: a raising generate_fn (or a
  raising sink) can never break a conversation turn;
- the control invariant: derivation writes no training signals.

The LLM is faked everywhere (injected generate_fn). Stores are tmp
SQLite files; the VE DB is isolated with the usual ve_ctx pattern.
"""

from __future__ import annotations

import json
import threading
import time

import pytest

import local_ai.activity as activity_mod
from local_ai.agent_intake import pipeline as intake_pipeline
from local_ai.conversation.meeting import MeetingService, MeetingStore
from local_ai.conversation.service import ConversationService
from local_ai.conversation.store import ConversationStore
from local_ai.council import meetings as MT
from local_ai.entity_strands import set_entity_strands
from local_ai.fellowship import derivation, events
from local_ai.fellowship.events import FellowshipEvent
from local_ai.fellowship.observations import ObservationStore
from local_ai.presence_ingest.store import PresenceStore
from local_ai.vision_execution import keystone_seeding
from local_ai.vision_execution import models as ve_models
from local_ai.vision_execution import service as ve

WEAVER_MESSAGE = (
    "I keep juggling three projects and nothing fits together — the "
    "priorities keep competing and the whole plan feels like it is detuning."
)
NEUTRAL_MESSAGE = "ok thanks, sounds good, see you tomorrow."


# -- fixtures / helpers -------------------------------------------------------


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    """Isolate the VE SQLite DB per test (test_keystones pattern)."""
    import local_ai.vision_execution.storage as ve_store

    monkeypatch.setattr(ve_store, "_DB_PATH", tmp_path / "ve.db")
    monkeypatch.setattr(ve_store, "_DB_DIR", tmp_path)
    monkeypatch.setattr(ve_store, "_init_done_paths", set())
    monkeypatch.setattr(ve_store, "_thread_local", threading.local())
    return {}


@pytest.fixture()
def activity_records(monkeypatch):
    """Intercept the activity log: record calls instead of writing.

    Returns the list of captured log_activity_simple kwargs; the fake
    returns sequential event ids so emit_event's return value (and any
    observation's event_ref) is assertable.
    """
    records: list[dict] = []

    def _fake_log(**kwargs):
        records.append(kwargs)
        return f"evt-{len(records)}"

    monkeypatch.setattr(activity_mod, "log_activity_simple", _fake_log)
    return records


@pytest.fixture(autouse=True)
def _no_background_derivation():
    """Keep emit_event from scheduling real derivation in this module:
    install a pipeline whose scheduler never runs its callback, and
    restore whatever was installed (api.main installs one at import in
    the full suite) afterwards. Pipeline-specific tests install their
    own inside the test body."""
    old = derivation._PIPELINE
    derivation.install_default_pipeline(
        store=None, generate_fn=None, scheduler=lambda fn: None
    )
    yield
    derivation._PIPELINE = old


def _fellowship_records(records: list[dict]) -> list[dict]:
    return [r for r in records if r.get("source") == events.FELLOWSHIP_ACTIVITY_SOURCE]


def _obs_store(tmp_path) -> ObservationStore:
    return ObservationStore(tmp_path / "observations.db")


def _gen_returning(text: str):
    def _gen(prompt: str, **kwargs) -> str:
        return text

    return _gen


def _gen_raising(prompt: str, **kwargs) -> str:
    raise RuntimeError("model unavailable")


class _CountingGen:
    def __init__(self, text: str = "A reading."):
        self.text = text
        self.prompts: list[str] = []

    def __call__(self, prompt: str, **kwargs) -> str:
        self.prompts.append(prompt)
        return self.text


def _event(text: str = "", **overrides) -> FellowshipEvent:
    base = dict(
        id="evt-test",
        kind=events.CONVERSATION_TURN,
        user_id="user-1",
        entity_type="conversation",
        entity_id="skeleton",
        evidence_text=text,
        summary="",
        payload={},
    )
    base.update(overrides)
    return FellowshipEvent(**base)


# -- events: recording + vocabulary -------------------------------------------


def test_emit_event_records_on_activity_log(activity_records):
    event = events.emit_event(
        kind=events.CONVERSATION_TURN,
        user_id="user-1",
        entity_type="conversation",
        entity_id="skeleton",
        evidence_text="the user's exact words",
        summary="Conversation turn with the conductor voice.",
        payload={"archetype_id": "conductor"},
    )
    assert event.id == "evt-1"
    (record,) = _fellowship_records(activity_records)
    assert record["type"] == "conversation_turn"
    assert record["entity_type"] == "conversation"
    assert record["entity_id"] == "skeleton"
    assert record["actor"] == "user-1"
    detail = json.loads(record["detail"])
    assert detail["evidence"] == "the user's exact words"
    assert detail["summary"] == "Conversation turn with the conductor voice."
    assert detail["payload"] == {"archetype_id": "conductor"}


def test_emit_event_rejects_unknown_kind(activity_records):
    with pytest.raises(ValueError, match="unknown fellowship event kind"):
        events.emit_event(
            kind="conversaton_turn",  # typo must fail loudly
            user_id="user-1",
            entity_type="conversation",
            entity_id="skeleton",
        )
    assert _fellowship_records(activity_records) == []


def test_emit_event_without_pipeline_still_records(activity_records, monkeypatch):
    monkeypatch.setattr(derivation, "_PIPELINE", None)
    event = events.emit_event(
        kind=events.TASK_COMPLETED,
        user_id="user-1",
        entity_type="task",
        entity_id="task-9",
        summary="Task completed: anything",
    )
    assert event.id == "evt-1"
    assert len(_fellowship_records(activity_records)) == 1


# -- chokepoint: conversation turn ----------------------------------------------


def _conv_service(tmp_path, sink=None, gen=None) -> ConversationService:
    return ConversationService(
        ConversationStore(tmp_path / "conv.db"),
        generate_fn=gen or _gen_returning("Fake reply."),
        event_sink=sink,
    )


def test_turn_emits_conversation_turn_event(tmp_path):
    captured: list[dict] = []
    svc = _conv_service(tmp_path, sink=lambda **kw: captured.append(kw))
    result = svc.turn("user-1", "conductor", WEAVER_MESSAGE)

    assert result.reply.reply == "Fake reply."
    (call,) = captured
    assert call["kind"] == events.CONVERSATION_TURN
    assert call["user_id"] == "user-1"
    assert call["entity_type"] == "conversation"
    assert call["entity_id"] == "skeleton"
    # Evidence is the user's message, verbatim.
    assert call["evidence_text"] == WEAVER_MESSAGE
    assert call["payload"]["archetype_id"] == "conductor"
    assert call["payload"]["message_id"] == result.user_message["id"]


def test_turn_without_sink_emits_nothing(tmp_path, activity_records):
    svc = _conv_service(tmp_path)  # no sink wired
    svc.turn("user-1", "conductor", WEAVER_MESSAGE)
    assert _fellowship_records(activity_records) == []


def test_turn_with_raising_sink_still_succeeds(tmp_path):
    def _bad_sink(**kwargs):
        raise RuntimeError("event layer down")

    svc = _conv_service(tmp_path, sink=_bad_sink)
    result = svc.turn("user-1", "conductor", WEAVER_MESSAGE)
    assert result.reply.reply == "Fake reply."
    assert result.assistant_message["body"] == "Fake reply."


def test_turn_empty_message_emits_nothing(tmp_path):
    captured: list[dict] = []
    svc = _conv_service(tmp_path, sink=lambda **kw: captured.append(kw))
    svc.turn("user-1", "conductor", "Question me.", question=False)
    assert len(captured) == 1  # control: a real message does emit
    captured.clear()
    # question-mode turn: the seat speaks first; no user words, no event.
    svc.turn("user-1", "conductor", "", question=True)
    assert captured == []


# -- chokepoint: claim verdict ----------------------------------------------------


def test_claim_verdict_emits_claim_decided(tmp_path, activity_records):
    presence = PresenceStore(tmp_path / "presence.db")
    intake_pipeline.log_claim_feedback(
        "agent-1",
        "claim-1",
        "value_inference",
        "accepted",
        evidence="I protect my mornings fiercely",
        inference="Mornings are a protected value.",
        claim_title="Mornings are protected",
        user_id="user-1",
        presence_store=presence,
    )
    (record,) = _fellowship_records(activity_records)
    assert record["type"] == "claim_decided"
    assert record["entity_type"] == "claim"
    assert record["entity_id"] == "claim-1"
    detail = json.loads(record["detail"])
    # The claim's anchored evidence rides verbatim.
    assert detail["evidence"] == "I protect my mornings fiercely"
    assert detail["payload"]["action"] == "accepted"
    assert detail["payload"]["claim_type"] == "value_inference"


def test_claim_verdict_multi_strand_path_also_emits(tmp_path, activity_records):
    """Meeting-impression claims fan out one signal per strand; the
    event must fire on that path too (it is the same verdict)."""
    presence = PresenceStore(tmp_path / "presence.db")
    intake_pipeline.log_claim_feedback(
        "meeting-conductor-1",
        "meeting-conductor-1:impression:self+people:run1",
        "meeting_impression",
        "corrected",
        note="Except I protect mornings first.",
        evidence="I triage by what breaks first",
        inference="Triage-first orientation.",
        claim_title="Meeting impression",
        user_id="user-1",
        presence_store=presence,
    )
    (record,) = _fellowship_records(activity_records)
    assert record["type"] == "claim_decided"
    assert detail_payload(record)["action"] == "corrected"


def detail_payload(record: dict) -> dict:
    return json.loads(record["detail"])["payload"]


# -- chokepoints: VE task completion + decision records ---------------------------


def test_task_completion_emits_event(ve_ctx, activity_records):
    user = ve.create_user_account("tasky@example.com", "pw", "Tasky")
    uid = user["id"]
    task = ve.create_task(ve_models.TaskCreate(title="Write the plan"), uid)
    # A non-completion update emits no task_completed event.
    ve.update_task(task["id"], ve_models.TaskUpdate(title="Write the plan v2"), uid)
    assert [r for r in _fellowship_records(activity_records)
            if r["type"] == "task_completed"] == []

    ve.update_task(task["id"], ve_models.TaskUpdate(status="Done"), uid)
    (record,) = [r for r in _fellowship_records(activity_records)
                 if r["type"] == "task_completed"]
    assert record["entity_type"] == "task"
    assert record["entity_id"] == task["id"]
    assert record["actor"] == uid
    detail = json.loads(record["detail"])
    assert detail["payload"]["title"] == "Write the plan v2"
    assert detail["payload"]["status"] == "Done"


def test_decision_record_adopted_as_event_source(ve_ctx, activity_records):
    user = ve.create_user_account("deci@example.com", "pw", "Deci")
    uid = user["id"]
    out = ve.create_decision(
        ve_models.DecisionCreate(
            user_id=uid,
            entity_type="project",
            entity_id="project-1",
            decision_type="priority_change",
            final_values_snapshot={"priority": "high"},
        )
    )
    (record,) = [r for r in _fellowship_records(activity_records)
                 if r["type"] == "decision_recorded"]
    # The event references the decision record itself — adoption of the
    # existing append-only record, not a parallel decision object.
    assert record["entity_id"] == out["id"]
    assert record["entity_type"] == "decision"
    detail = json.loads(record["detail"])
    assert detail["payload"]["decision_type"] == "priority_change"
    assert detail["payload"]["about_entity_id"] == "project-1"
    # The canonical record is still the VE one, readable as before.
    assert ve.list_decisions("project", "project-1")[0]["id"] == out["id"]


# -- chokepoint: meeting completion ------------------------------------------------



#: Tutorial-beat mechanism (2026-10-24, corrected the same day):
#: this fake simulates a character that teaches its beats WITH
#: CONTENT — every generation output carries a teaching sentence
#: with all three beats' anchors plus the three beat trailers
#: (trailers stripped before anything is spoken). Trailers alone
#: no longer count under the content guard. Prompts and
#: generation counts are unchanged; spoken bodies gain the
#: teaching sentence. The gate itself is pinned by
#: tests/test_encounter_tutorial_beats.py; this suite pins the
#: other behaviors.
#: Teaching sentence the fakes speak (correction 2026-10-24):
#: beat trailers alone no longer count — coverage requires
#: content, so a fake that teaches its beats must speak them.
#: One sentence carrying all three conductor beats' anchors
#: (council/tree/hearing-together, competing priorities/sit
#: together, new voice/whole orchestra/in ear). Inserted BEFORE
#: any Strands: bookkeeping line (strands parsing reads from the
#: end) and before the beat trailers, so every trailer parse in
#: the runtime sees the same trailing structure as the original
#: output; thread trailers are position-tolerant.
_TEACHING_SENTENCE = (
    "My ground is the council and the tree, where parts of your "
    "life need hearing together; bring me the competing priorities "
    "that will not sit together; every new voice changes what the "
    "whole orchestra can play, and I keep the whole of it in ear."
)

_BEAT_SUFFIX = (
    "\n[[beat:conductor:terrain]] [[beat:conductor:involvement]] "
    "[[beat:conductor:why_meet]]"
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
        return "\n".join(lines) + _BEAT_SUFFIX
    return wrapper


class _MeetingGen:
    """FakeGen in the test_meetings.py shape: answers by beat."""

    def __init__(self):
        self.prompts: list[str] = []

    def __call__(self, prompt, **kwargs):
        self.prompts.append(prompt)
        if "READ-BACK" in prompt:
            return (
                "A first impression, anchored in [[u]]your words[[/u]] — correct me."
                "\nStrands: Compass, Logic"
            )
        if "ENCOUNTER" in prompt:
            return "An engaged reply that hears two tensions together."
        return "A plain reply."


def test_meeting_completion_emits_event(ve_ctx, tmp_path, activity_records):
    user = ve.create_user_account("meet@example.com", "pw", "Meet")
    uid = user["id"]
    keystone_seeding.seed_meet_your_council(uid)
    svc = MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
        generate_fn=_teaching(_MeetingGen()),
    )
    svc.start(uid, "conductor")
    svc.turn(uid, "conductor", "I triage by what breaks first if I ignore it.")
    # UPDATED for the Weaver pattern: a second substantive turn
    # carries the read (the first begins the shared work; the
    # impression is gated), so the correction below is genuinely
    # the read-back ANSWER the event evidence must carry.
    svc.turn(uid, "conductor", "Mostly I protect the mornings before anything else.")
    readback_answer = "Mostly right — except I protect mornings first."
    svc.turn(uid, "conductor", readback_answer)
    state = svc.turn(uid, "conductor", "Got it.")
    assert state["status"] == "complete"

    (record,) = [r for r in _fellowship_records(activity_records)
                 if r["type"] == "meeting_completed"]
    assert record["entity_type"] == "meeting"
    assert record["entity_id"] == "meeting-conductor-1"
    detail = json.loads(record["detail"])
    # Evidence is the user's verbatim read-back answer.
    assert detail["evidence"] == readback_answer
    assert detail["payload"]["archetype_id"] == "conductor"
    assert MT.get_script("conductor", 1) is not None  # script untouched


# -- pre-filter -----------------------------------------------------------------------


def test_prefilter_weaver_focus_makes_only_conductor_a_candidate():
    matches = derivation.candidate_seats(_event(WEAVER_MESSAGE))
    seats = [m.seat for m in matches]
    assert seats == ["conductor"]
    match = matches[0]
    assert "prioriti" in match.focus_terms
    assert match.score >= 4


def test_prefilter_neutral_event_has_no_candidates():
    assert derivation.candidate_seats(_event(NEUTRAL_MESSAGE)) == []


def test_prefilter_single_generic_focus_word_is_not_enough():
    # 'integration' alone (one focus hit, nothing else) must not spend
    # a model call — one keyword is not an observation-worthy event.
    matches = derivation.candidate_seats(
        _event("", entity_type="task", entity_id="task-x",
               summary="Task completed: Integration")
    )
    assert matches == []


def test_prefilter_strand_alignment_strengthens_candidacy(ve_ctx, tmp_path):
    """Same thin text, two worlds: without strand weightings the event
    is below the bar; with Weaver-aligned weightings the strand signal
    completes the candidacy and is recorded in the match reasons."""
    user = ve.create_user_account("strand@example.com", "pw", "Strand")
    uid = user["id"]
    thin = dict(
        kind=events.TASK_COMPLETED,
        entity_type="task",
        entity_id="task-strand",
        summary="Task completed: Integration plan",
    )
    event = _event("", user_id=uid, **thin)
    assert derivation.candidate_seats(event) == []

    set_entity_strands(
        uid, "task", "task-strand",
        {"Compass": 0.4, "Logic": 0.2, "Voice": 0.1, "Heart": 0.1,
         "Eye": 0.1, "Hands": 0.05, "Ear": 0.05},
        source="user_stated",
    )
    matches = derivation.candidate_seats(event)
    assert [m.seat for m in matches] == ["conductor"]
    assert matches[0].strand_alignment >= derivation._STRAND_ALIGNMENT_MIN
    assert matches[0].reasons()["strand_alignment"] >= derivation._STRAND_ALIGNMENT_MIN


# -- derivation -------------------------------------------------------------------------


def test_derive_persists_observation_with_verbatim_evidence(tmp_path):
    store = _obs_store(tmp_path)
    event = _event(WEAVER_MESSAGE)
    gen = _gen_returning("The parts are arriving faster than they can be tuned.")
    derived = derivation.derive_observations(event, store, generate_fn=gen)

    (obs,) = derived
    assert obs.seat == "conductor"
    assert obs.event_ref == "evt-test"
    assert obs.event_kind == "conversation_turn"
    assert obs.evidence == WEAVER_MESSAGE  # verbatim, never paraphrased
    assert obs.evidence_kind == "quote"
    assert obs.interpretation == "The parts are arriving faster than they can be tuned."
    assert obs.status == "pending"
    assert "prioriti" in obs.derivation["prefilter"]["focus_terms"]
    # And it really persisted.
    assert store.get("user-1", obs.id) == obs
    store.close()


def test_derive_no_candidates_makes_no_llm_calls(tmp_path):
    store = _obs_store(tmp_path)
    gen = _CountingGen()
    derived = derivation.derive_observations(
        _event(NEUTRAL_MESSAGE), store, generate_fn=gen
    )
    assert derived == []
    assert gen.prompts == []  # the cost law: nobody's ground, no model call
    assert store.list_for_user("user-1") == []
    store.close()


def test_derive_entity_ref_evidence_for_wordless_events(tmp_path):
    store = _obs_store(tmp_path)
    event = _event(
        "",
        kind=events.TASK_COMPLETED,
        entity_type="task",
        entity_id="task-42",
        summary="Task completed: Integration plan for the parts",
    )
    derived = derivation.derive_observations(
        event, store, generate_fn=_gen_returning("The whole is taking shape.")
    )
    (obs,) = derived
    assert obs.evidence == "task:task-42"
    assert obs.evidence_kind == "entity_ref"
    store.close()


def test_derive_seat_declining_leaves_no_row(tmp_path):
    store = _obs_store(tmp_path)
    derived = derivation.derive_observations(
        _event(WEAVER_MESSAGE), store, generate_fn=_gen_returning("NONE")
    )
    assert derived == []
    assert store.list_for_user("user-1") == []
    store.close()


def test_derive_generate_raising_is_swallowed(tmp_path):
    store = _obs_store(tmp_path)
    derived = derivation.derive_observations(
        _event(WEAVER_MESSAGE), store, generate_fn=_gen_raising
    )
    assert derived == []
    assert store.list_for_user("user-1") == []
    store.close()


def test_derive_one_seats_failure_keeps_the_other(tmp_path):
    """An event on both the Weaver's and the Raven's ground: the
    Raven's generation fails; the Weaver's observation still lands."""
    store = _obs_store(tmp_path)
    text = (
        "The priorities keep competing and the whole plan is detuning — "
        "and honestly, what evidence is that claim even based on? Show "
        "me the assumption underneath it."
    )

    def _gen(prompt: str, **kwargs) -> str:
        if "Raven" in prompt:
            raise RuntimeError("model unavailable")
        return "A reading from the Weaver."

    derived = derivation.derive_observations(_event(text), store, generate_fn=_gen)
    assert [o.seat for o in derived] == ["conductor"]
    assert store.list_for_user("user-1", seat="skeptic") == []
    store.close()


# -- derivation wired through the conversation turn (fault isolation) --------------------


def _sink_deriving(obs_store: ObservationStore, gen):
    """A service sink that runs derivation synchronously (the test-time
    stand-in for the background pipeline)."""

    def _sink(**kwargs):
        event = events.emit_event(**kwargs, schedule=False)
        derivation.derive_observations(event, obs_store, generate_fn=gen)

    return _sink


def test_turn_with_deriving_sink_and_raising_gen_still_succeeds(tmp_path, activity_records):
    obs_store = _obs_store(tmp_path)
    svc = _conv_service(tmp_path, sink=_sink_deriving(obs_store, _gen_raising))
    result = svc.turn("user-1", "conductor", WEAVER_MESSAGE)
    assert result.reply.reply == "Fake reply."
    assert obs_store.list_for_user("user-1") == []
    obs_store.close()


def test_turn_with_deriving_sink_persists_observation(tmp_path, activity_records):
    obs_store = _obs_store(tmp_path)
    gen = _gen_returning("Everything is arriving at the bench at once.")
    svc = _conv_service(tmp_path, sink=_sink_deriving(obs_store, gen))
    result = svc.turn("user-1", "conductor", WEAVER_MESSAGE)
    assert result.reply.reply == "Fake reply."
    (obs,) = obs_store.list_for_user("user-1")
    assert obs.seat == "conductor"
    assert obs.evidence == WEAVER_MESSAGE
    obs_store.close()


# -- observations store: lifecycle --------------------------------------------------------


def _add_obs(store: ObservationStore, user_id: str = "user-1", seat: str = "conductor"):
    return store.add(
        user_id=user_id,
        seat=seat,
        event_ref="evt-1",
        event_kind="conversation_turn",
        evidence="verbatim words",
        evidence_kind="quote",
        interpretation="A reading.",
        derivation={"prefilter": {"score": 5}},
    )


def test_observation_status_lifecycle(tmp_path):
    store = _obs_store(tmp_path)
    obs = _add_obs(store)
    assert obs.status == "pending"
    obs = store.set_status("user-1", obs.id, "surfaced")
    assert obs.status == "surfaced"
    obs = store.set_status("user-1", obs.id, "discussed")
    assert obs.status == "discussed"
    # Terminal: no way out of discussed.
    with pytest.raises(ValueError, match="cannot move"):
        store.set_status("user-1", obs.id, "dismissed")
    store.close()


def test_observation_status_transitions_are_checked(tmp_path):
    store = _obs_store(tmp_path)
    obs = _add_obs(store)
    # Skipping surfaced is not a legal move.
    with pytest.raises(ValueError, match="cannot move"):
        store.set_status("user-1", obs.id, "discussed")
    # Dismissal from pending is.
    obs = store.set_status("user-1", obs.id, "dismissed")
    assert obs.status == "dismissed"
    with pytest.raises(ValueError, match="unknown observation status"):
        store.set_status("user-1", obs.id, "pending-ish")
    with pytest.raises(ValueError, match="unknown observation"):
        store.set_status("user-1", "obs-nope", "surfaced")
    store.close()


def test_observation_per_user_isolation_and_filters(tmp_path):
    store = _obs_store(tmp_path)
    mine = _add_obs(store, user_id="user-1", seat="conductor")
    _add_obs(store, user_id="user-1", seat="skeptic")
    _add_obs(store, user_id="user-2", seat="conductor")

    assert store.get("user-2", mine.id) is None  # not theirs to read
    with pytest.raises(ValueError, match="unknown observation"):
        store.set_status("user-2", mine.id, "dismissed")
    assert [o.seat for o in store.list_for_user("user-1")] == ["conductor", "skeptic"]
    assert [o.id for o in store.list_for_user("user-1", seat="skeptic")] != []
    assert store.list_for_user("user-1", status="discussed") == []
    assert len(store.list_for_user("user-2")) == 1
    store.close()


# -- background pipeline ---------------------------------------------------------------------


def test_pipeline_synchronous_scheduler_derives_on_emit(tmp_path, activity_records):
    store = _obs_store(tmp_path)
    derivation.install_default_pipeline(
        store=store,
        generate_fn=_gen_returning("Scheduled reading."),
        scheduler=lambda fn: fn(),
    )
    events.emit_event(
        kind=events.CONVERSATION_TURN,
        user_id="user-1",
        entity_type="conversation",
        entity_id="skeleton",
        evidence_text=WEAVER_MESSAGE,
        summary="Conversation turn with the conductor voice.",
        payload={"archetype_id": "conductor"},
    )
    (obs,) = store.list_for_user("user-1")
    assert obs.seat == "conductor"
    assert obs.interpretation == "Scheduled reading."
    assert obs.event_ref == "evt-1"
    store.close()


def test_pipeline_thread_scheduler_derives_in_background(tmp_path, activity_records):
    store = _obs_store(tmp_path)
    derivation.install_default_pipeline(
        store=store,
        generate_fn=_gen_returning("Background reading."),
    )
    events.emit_event(
        kind=events.CONVERSATION_TURN,
        user_id="user-1",
        entity_type="conversation",
        entity_id="skeleton",
        evidence_text=WEAVER_MESSAGE,
        summary="Conversation turn with the conductor voice.",
    )
    deadline = time.time() + 5
    rows = []
    while time.time() < deadline:
        rows = store.list_for_user("user-1")
        if rows:
            break
        time.sleep(0.05)
    assert [o.interpretation for o in rows] == ["Background reading."]
    store.close()


def test_pipeline_schedule_failure_never_propagates(tmp_path, activity_records):
    def _exploding_scheduler(fn):
        raise RuntimeError("no threads today")

    derivation.install_default_pipeline(
        store=_obs_store(tmp_path), scheduler=_exploding_scheduler
    )
    event = events.emit_event(
        kind=events.CONVERSATION_TURN,
        user_id="user-1",
        entity_type="conversation",
        entity_id="skeleton",
        evidence_text=WEAVER_MESSAGE,
    )
    assert event.id == "evt-1"  # the emit itself is unaffected


# -- control invariant: derivation writes no training signals -------------------------------


def test_derivation_writes_no_training_signals(ve_ctx, tmp_path):
    """The doctrine §9 invariant, behaviorally: derive real
    observations and prove the canonical signals table is untouched."""
    import local_ai.vision_execution.storage as ve_store

    user = ve.create_user_account("invariant@example.com", "pw", "Inv")
    uid = user["id"]
    conn = ve_store.get_connection()
    before = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]

    store = _obs_store(tmp_path)
    derived = derivation.derive_observations(
        _event(WEAVER_MESSAGE, user_id=uid),
        store,
        generate_fn=_gen_returning("A reading that must not train anything."),
    )
    assert len(derived) == 1  # derivation really produced a row
    after = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
    assert after == before
    store.close()
