"""Palace pass — the chat-is-the-work build (founder rulings
2026-11-25 13:44/13:56 PT; brief zenaf-palace-pass-brief-2026-11-25).

Pins:

* S1 — the room-state block: composed for the guardian on the
  Living Palace sheet with a resolved subject (instruments,
  scales figures or "unweighed", pending itemized without counts,
  accepted readings named for reconsideration, guest objects);
  absent for other seats, other sheets, foreign/unresolved
  subjects; capped at the subject block's 2,000 chars.
* Tentative population: palace_focus validates against the closed
  kinds, an invalid value is scrubbed before the message snapshot,
  a valid one rides the snapshot and the room block's focus line.
* S4 — the verdict tail: chalk-discipline parsing (strip-always,
  fail-closed, verbatim cause, dedupe); execution through the ONE
  verdict writer behind the subject-match gate; endorsement and
  reconsideration (verbatim cause, standing candidacy on re-ask).
* S5 — the weighing tail: the settle-language gate both
  directions; exploration writes nothing; a figure with no
  recorded baseline drops; a settle lands #433's exact writes
  (figures + the scales_weighing decision record) and stops on
  first failure.

Conventions mirror tests/test_verdict_palace_door.py:
ALICE = "u1" (owner), BOB = "u2" (other user). No real model
generation: service turns use capturing fake generate_fns.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from local_ai.conversation import palace_room as PR
from local_ai.conversation import palace_tails as PT
from local_ai.conversation.service import ConversationService
from local_ai.conversation.store import ConversationStore
from local_ai.followthrough.store import FollowthroughStore
from local_ai.narrative.store import NarrativeStore
from local_ai.narrative.refs import SourceRef
from local_ai.vision_execution import models as M
from local_ai.vision_execution import service as ve_service
from local_ai.vision_execution import storage as S

ALICE = "u1"
BOB = "u2"

FLAGS_ON = {"steward_derivation": True, "steward_coordination": True}

CAUSE = "The yard changed its terms —  see Tuesday's note, not the old one."


# ---------------------------------------------------------------------------
# fixtures + seed helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def ve_conn(monkeypatch: pytest.MonkeyPatch):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    S.init_db(conn)
    monkeypatch.setattr(S, "get_connection", lambda: conn)
    yield conn
    conn.close()


@pytest.fixture()
def narrative_store(tmp_path: Path):
    return NarrativeStore(db_path=tmp_path / "narrative.db")


@pytest.fixture()
def conv_store(tmp_path: Path):
    store = ConversationStore(db_path=tmp_path / "conv.db")
    yield store
    store.close()


@pytest.fixture()
def ft_store(tmp_path: Path):
    return FollowthroughStore(db_path=tmp_path / "ft.db")


@pytest.fixture()
def pencil_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ZENAF_STEWARD_PENCIL", "1")


def _perm_conn(flags_by_user: dict) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE user_permissions_settings ("
        "user_id TEXT, permissions_json TEXT, updated_at TEXT)"
    )
    for user_id, flags in flags_by_user.items():
        conn.execute(
            "INSERT INTO user_permissions_settings VALUES (?, ?, ?)",
            (user_id, json.dumps(flags), "2026-11-24T00:00:00Z"),
        )
    conn.commit()
    return conn


def _make_task(user: str, title: str, **kw) -> dict:
    return ve_service.create_task(M.TaskCreate(title=title, **kw), user)


def _make_project(user: str, title: str, **kw) -> dict:
    return ve_service.create_project(M.ProjectCreate(title=title, **kw), user)


def _make_person(user: str, name: str) -> dict:
    return ve_service.create_person(M.PersonCreate(name=name), user)


def _room_block(store, conv, ft, user, entity_type, entity_id, context_extra=None):
    context = {
        "sheet_type": "living_palace",
        "entity_type": entity_type,
        "entity_id": entity_id,
    }
    if context_extra:
        context.update(context_extra)
    return PR.build_room_state_context(
        user,
        context,
        narrative_store=store,
        conversation_store=conv,
        followthrough_store=ft,
        consent_connection=_perm_conn({user: FLAGS_ON}),
    )


def _thread_naming_task(
    narrative_store,
    user,
    task_id,
    *,
    author="steward",
    status="active",
    accept=False,
    tensions=("Sundays keep colliding with deliveries",),
):
    thread = narrative_store.create_thread(
        user, origin="user_declared", title="The boundary thread",
        evidence_refs=(SourceRef(kind="event", ref_id="evt-1", evidence_kind="entity_ref"),),
    )
    narrative_store.annotate_evidence_entities(
        user, thread.id, {("event", "evt-1"): f"task:{task_id}"}
    )
    if status != "nascent":
        narrative_store.set_thread_status(user, thread.id, status)
    reading = narrative_store.propose_reading(
        user, thread.id, author=author,
        reading={"tensions": list(tensions),
                 "open_questions": ["Where does the weekend actually sit?"]},
        evidence_refs=(SourceRef(kind="event", ref_id="evt-1", evidence_kind="entity_ref"),),
    )
    if accept:
        narrative_store.accept_reading(user, reading.id)
    return narrative_store.get_thread(user, thread.id), reading


def _palace_context(task_id: str, **extra) -> dict:
    context = {
        "sheet_type": "living_palace",
        "entity_type": "task",
        "entity_id": task_id,
    }
    context.update(extra)
    return context


# ---------------------------------------------------------------------------
# S1 — the room-state block
# ---------------------------------------------------------------------------


def test_room_block_carries_instruments_and_pending(
    ve_conn, narrative_store, conv_store, ft_store, pencil_on
):
    task = _make_task(ALICE, "Well work", status="In Progress")
    _thread, reading = _thread_naming_task(narrative_store, ALICE, task["id"])
    block = _room_block(
        narrative_store, conv_store, ft_store, ALICE, "task", task["id"]
    )
    assert block is not None
    assert block.startswith(PR.BEGIN_FENCE)
    assert block.endswith(PR.END_FENCE)
    # The room and its native instruments.
    assert "Well work" in block
    assert "The hearth" in block
    assert "The threshold" in block
    assert "Kintsugi vessel" in block
    # The vessel holds the reading's tension as a question held.
    assert "Sundays keep colliding with deliveries" in block
    # The pending reading is itemized with its review id — and no
    # count language anywhere (resting is a legitimate state).
    assert f"[reading:{reading.id}]" in block
    assert "awaiting" not in block.lower()
    # The task is In Progress: Rumi's plant grows here, as a guest.
    assert "Rumi's plant" in block and "growing" in block
    # Unweighed: no estimate recorded, so the scales say so.
    assert "unweighed" in block


def test_room_block_scales_figures_and_keeper_picture(
    ve_conn, narrative_store, conv_store, ft_store, pencil_on
):
    keeper = _make_person(ALICE, "Keeper Kate")
    ve_service.upsert_capacity_profile(
        M.CapacityProfileUpsert(
            person_id=keeper["id"], weekly_capacity_hours=10
        ),
        ALICE,
    )
    project = _make_project(
        ALICE, "Big floor", status="Active",
        owner_id=keeper["id"], estimated_weekly_hours=14,
    )
    task = _make_task(
        ALICE, "Heavy room", project_id=project["id"], estimated_hours=3,
    )
    block = _room_block(
        narrative_store, conv_store, ft_store, ALICE, "task", task["id"]
    )
    assert block is not None
    assert "recorded estimate is 3h" in block
    assert "asks 14h a week" in block
    # The derived picture: 14 committed against 10 capacity — over.
    assert "Keeper Kate" in block
    assert "over by 4h" in block


def test_room_block_absent_off_palace_and_for_foreign_subject(
    ve_conn, narrative_store, conv_store, ft_store, pencil_on
):
    task = _make_task(ALICE, "Alice's room")
    # Another sheet: no block.
    assert (
        PR.build_room_state_context(
            ALICE,
            {"sheet_type": "campaign_board", "entity_type": "task",
             "entity_id": task["id"]},
            narrative_store=narrative_store,
            conversation_store=conv_store,
            followthrough_store=ft_store,
            consent_connection=_perm_conn({ALICE: FLAGS_ON}),
        )
        is None
    )
    # Foreign subject: no block (the record never enters the prompt).
    assert (
        _room_block(narrative_store, conv_store, ft_store, BOB, "task", task["id"])
        is None
    )
    # No selection: no block.
    assert (
        PR.build_room_state_context(
            ALICE, {"sheet_type": "living_palace"},
            narrative_store=narrative_store,
            conversation_store=conv_store,
            followthrough_store=ft_store,
            consent_connection=_perm_conn({ALICE: FLAGS_ON}),
        )
        is None
    )


def test_room_block_gated_steward_material_stays_out(
    ve_conn, narrative_store, conv_store, ft_store, pencil_on
):
    task = _make_task(ALICE, "Quiet room")
    _thread, reading = _thread_naming_task(narrative_store, ALICE, task["id"])
    # Consents OFF: the read's steward sections close — the block
    # still composes the room, but no pending item and no tension
    # reaches it.
    block = PR.build_room_state_context(
        ALICE,
        _palace_context(task["id"]),
        narrative_store=narrative_store,
        conversation_store=conv_store,
        followthrough_store=ft_store,
        consent_connection=_perm_conn({ALICE: {}}),
    )
    assert block is not None
    assert f"[reading:{reading.id}]" not in block
    assert "Sundays keep colliding" not in block


def test_room_block_names_accepted_readings_and_the_gold_seam(
    ve_conn, narrative_store, conv_store, ft_store, pencil_on
):
    task = _make_task(ALICE, "Seamed room")
    thread, reading = _thread_naming_task(
        narrative_store, ALICE, task["id"], accept=True
    )
    # The seam (#430's rule): a reading reconsidered through a
    # contradicted change whose successor stands ACCEPTED.
    successor = narrative_store.propose_reading(
        ALICE, thread.id, author="steward",
        reading={"tensions": ["The calendar, not the yard, is the bottleneck"],
                 "open_questions": []},
        evidence_refs=(SourceRef(kind="event", ref_id="evt-1", evidence_kind="entity_ref"),),
    )
    narrative_store.record_change(
        ALICE, thread.id, kind="contradicted",
        evidence_refs=(SourceRef(kind="event", ref_id="evt-2", evidence_kind="entity_ref"),),
        prior_reading_id=reading.id, new_reading_id=successor.id,
    )
    narrative_store.accept_reading(ALICE, successor.id)
    block = _room_block(
        narrative_store, conv_store, ft_store, ALICE, "task", task["id"]
    )
    assert block is not None
    assert f"reading:{successor.id}" in block
    assert "gold seam" in block.lower()
    assert "restored" in block


def test_room_block_cap_holds(ve_conn, narrative_store, conv_store, ft_store, pencil_on):
    task = _make_task(ALICE, "Crowded room")
    for i in range(6):
        _thread_naming_task(
            narrative_store, ALICE, task["id"],
            tensions=(f"Tension number {i} " + "x" * 150,),
        )
    block = _room_block(
        narrative_store, conv_store, ft_store, ALICE, "task", task["id"]
    )
    assert block is not None
    inner = block[len(PR.BEGIN_FENCE) + 1 : -len(PR.END_FENCE) - 1]
    assert len(inner) <= 2000


def test_focus_validation_closed_set():
    assert PR.validated_palace_focus("scales") == "scales"
    assert PR.validated_palace_focus(" guest:conductor ") == "guest:conductor"
    assert PR.validated_palace_focus("guest:guardian") is None
    assert PR.validated_palace_focus("guest:nobody") is None
    assert PR.validated_palace_focus("../../../etc") is None
    assert PR.validated_palace_focus("") is None
    assert PR.validated_palace_focus(None) is None
    assert PR.validated_palace_focus(42) is None


def test_room_block_focus_line(
    ve_conn, narrative_store, conv_store, ft_store, pencil_on
):
    task = _make_task(ALICE, "Focused room")
    block = _room_block(
        narrative_store, conv_store, ft_store, ALICE, "task", task["id"],
        context_extra={"palace_focus": "scales"},
    )
    assert block is not None
    assert "tapped the scales" in block
    assert "settles" in block and "nothing" in block


# ---------------------------------------------------------------------------
# Tentative population at the service seam
# ---------------------------------------------------------------------------


class _RecordingExecutor:
    def __init__(self):
        self.calls: list[dict] = []

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        return []


def _turn(conv_store, user, arch_id, context, message, reply_text, **svc_kw):
    seen: dict[str, str] = {}

    def _capture(prompt, **kw):
        seen["prompt"] = prompt
        return reply_text

    svc = ConversationService(conv_store, generate_fn=_capture, **svc_kw)
    result = svc.turn(
        user, arch_id, message,
        conversation_id=f"c-{arch_id}-{abs(hash(message)) % 99999}",
        context=context,
    )
    return result, seen.get("prompt", "")


def _user_contexts(store: ConversationStore, user: str, conversation_id: str):
    return [
        m.get("context") or {}
        for m in store.history(user, conversation_id)
        if m.get("role") == "user"
    ]


def test_service_scrubs_invalid_focus_before_snapshot(ve_conn, conv_store):
    task = _make_task(ALICE, "Snapshot room")
    result, _prompt = _turn(
        conv_store, ALICE, "guardian",
        _palace_context(task["id"], palace_focus="not-a-real-focus"),
        "Hello Maeve", "Hello.",
    )
    contexts = _user_contexts(conv_store, ALICE, result.conversation_id)
    assert contexts, "expected a persisted user message"
    assert "palace_focus" not in contexts[-1]


def test_service_valid_focus_rides_snapshot_and_prompt(ve_conn, conv_store):
    task = _make_task(ALICE, "Staged room")
    result, prompt = _turn(
        conv_store, ALICE, "guardian",
        _palace_context(task["id"], palace_focus="scales"),
        "Look at these with me", "Of course.",
    )
    contexts = _user_contexts(conv_store, ALICE, result.conversation_id)
    assert contexts[-1].get("palace_focus") == "scales"
    # The room block rode, with the focus line and both act
    # instructions; the reply the visitor sees is untouched.
    assert "BEGIN THE ROOM YOU ARE KEEPING" in prompt
    assert "tapped the scales" in prompt
    assert "[[verdict]]" in prompt and "[[weighing]]" in prompt


def test_service_no_room_block_for_other_seats(ve_conn, conv_store):
    task = _make_task(ALICE, "Someone else's room")
    _result, prompt = _turn(
        conv_store, ALICE, "mentor",
        _palace_context(task["id"], palace_focus="scales"),
        "Hello Rumi", "Hello.",
    )
    assert "BEGIN THE ROOM YOU ARE KEEPING" not in prompt


# ---------------------------------------------------------------------------
# S4 — the verdict tail: parsing
# ---------------------------------------------------------------------------


def test_verdict_tail_parses_all_acts_and_dedupes():
    text = (
        "Spoken words.\n\n[[verdict]]\n"
        "verdict | accept | reading:rdg-1\n"
        "verdict | accept | reading:rdg-1\n"
        "verdict | reject | birth:thr-2\n"
        "verdict | unresolved | fitting:fit-3\n"
        "verdict | endorse | reading:rdg-4\n"
        f"verdict | reconsider | reading:rdg-5 | cause | {CAUSE}"
    )
    parsed = PT.parse_verdict_tail(text)
    assert parsed.status == "ok"
    assert parsed.body == "Spoken words."
    assert [a.act for a in parsed.acts] == [
        "accept", "reject", "unresolved", "endorse", "reconsider",
    ]
    # The cause is verbatim — double space and inner punctuation.
    assert parsed.acts[-1].cause == CAUSE


def test_verdict_tail_fail_closed_shapes():
    # A non-instruction line inside the tail drops the whole tail;
    # the body survives and no act executes.
    parsed = PT.parse_verdict_tail(
        "Body.\n[[verdict]]\nverdict | accept | reading:rdg-1\nand then prose"
    )
    assert parsed.status == "malformed"
    assert parsed.acts == []
    assert parsed.body == "Body."
    assert "[[verdict]]" not in parsed.body
    # Unknown kind / unknown act / cause on an accept: line drops.
    parsed = PT.parse_verdict_tail(
        "Body.\n[[verdict]]\nverdict | accept | widget:wdg-1\n"
        "verdict | maybe | reading:rdg-1\n"
        "verdict | accept | reading:rdg-1 | cause | why\n"
        "verdict | reject | reading:rdg-9"
    )
    assert parsed.status == "ok"
    assert [a.item_id for a in parsed.acts] == ["reading:rdg-9"]
    # Endorse/reconsider are reading-only; reconsider needs a cause.
    parsed = PT.parse_verdict_tail(
        "Body.\n[[verdict]]\nverdict | endorse | birth:thr-1\n"
        "verdict | reconsider | reading:rdg-1"
    )
    assert parsed.status == "malformed"
    assert parsed.acts == []
    # No delimiter: untouched, byte-identical.
    parsed = PT.parse_verdict_tail("Just words, no tail.")
    assert parsed.status == "absent"
    assert parsed.body == "Just words, no tail."


# ---------------------------------------------------------------------------
# S4 — the verdict tail: execution behind the subject-match gate
# ---------------------------------------------------------------------------


def test_verdict_executor_accepts_through_the_one_writer(
    ve_conn, narrative_store, conv_store, ft_store, pencil_on, monkeypatch
):
    task = _make_task(ALICE, "Ruled room")
    _thread, reading = _thread_naming_task(narrative_store, ALICE, task["id"])
    executor = PT.PalaceVerdictExecutor(store=narrative_store)
    # The executor's attributed read must see consents ON: wire the
    # consent connection by monkeypatching the read it imports at
    # call time.
    import local_ai.conversation.attributed_read as AR

    real_read = AR.attributed_read_for_subject

    def _read(user, et, ei, **kw):
        kw.setdefault("consent_connection", _perm_conn({user: FLAGS_ON}))
        kw.setdefault("conversation_store", conv_store)
        kw.setdefault("followthrough_store", ft_store)
        return real_read(user, et, ei, **kw)

    monkeypatch.setattr(AR, "attributed_read_for_subject", _read)
    diags = executor.execute(
        user_id=ALICE, entity_type="task", entity_id=task["id"],
        acts=[PT.VerdictAct(act="accept", kind="reading", row_id=reading.id)],
    )
    assert diags == []
    readings = narrative_store.readings_for(ALICE, _thread.id)
    assert readings[0].status == "accepted"
    verdicts = narrative_store.verdicts_for(ALICE)
    assert len(verdicts) == 1
    assert verdicts[0].verdict == "accepted"


def test_verdict_executor_subject_match_gate_blocks_foreign_items(
    ve_conn, narrative_store, conv_store, ft_store, pencil_on, monkeypatch
):
    task_a = _make_task(ALICE, "Room A")
    task_b = _make_task(ALICE, "Room B")
    _thread_b, reading_b = _thread_naming_task(
        narrative_store, ALICE, task_b["id"]
    )
    import local_ai.conversation.attributed_read as AR

    real_read = AR.attributed_read_for_subject

    def _read(user, et, ei, **kw):
        kw.setdefault("consent_connection", _perm_conn({user: FLAGS_ON}))
        kw.setdefault("conversation_store", conv_store)
        kw.setdefault("followthrough_store", ft_store)
        return real_read(user, et, ei, **kw)

    monkeypatch.setattr(AR, "attributed_read_for_subject", _read)
    executor = PT.PalaceVerdictExecutor(store=narrative_store)
    # The tail names room B's reading while room A is staged:
    # nothing writes.
    diags = executor.execute(
        user_id=ALICE, entity_type="task", entity_id=task_a["id"],
        acts=[PT.VerdictAct(act="accept", kind="reading", row_id=reading_b.id)],
    )
    assert diags and "not pending at this subject" in diags[0]
    readings = narrative_store.readings_for(ALICE, _thread_b.id)
    assert readings[0].status == "proposed"
    assert narrative_store.verdicts_for(ALICE) == []


def test_verdict_executor_reconsider_verbatim_and_standing(
    ve_conn, narrative_store, conv_store, ft_store, pencil_on, monkeypatch
):
    task = _make_task(ALICE, "Looked-again room")
    _thread, reading = _thread_naming_task(
        narrative_store, ALICE, task["id"], accept=True
    )
    import local_ai.conversation.attributed_read as AR

    real_read = AR.attributed_read_for_subject

    def _read(user, et, ei, **kw):
        kw.setdefault("consent_connection", _perm_conn({user: FLAGS_ON}))
        kw.setdefault("conversation_store", conv_store)
        kw.setdefault("followthrough_store", ft_store)
        return real_read(user, et, ei, **kw)

    monkeypatch.setattr(AR, "attributed_read_for_subject", _read)
    executor = PT.PalaceVerdictExecutor(store=narrative_store)
    act = PT.VerdictAct(
        act="reconsider", kind="reading", row_id=reading.id, cause=CAUSE
    )
    assert executor.execute(
        user_id=ALICE, entity_type="task", entity_id=task["id"], acts=[act]
    ) == []
    rows = narrative_store.reconsiderations_for(ALICE)
    assert len(rows) == 1
    assert rows[0].reason == CAUSE  # verbatim — double space and all
    assert rows[0].status == "proposed"
    # Asking again returns the standing candidacy — no duplicate.
    assert executor.execute(
        user_id=ALICE, entity_type="task", entity_id=task["id"], acts=[act]
    ) == []
    assert len(narrative_store.reconsiderations_for(ALICE)) == 1
    # The reading itself is untouched.
    assert narrative_store.readings_for(ALICE, _thread.id)[0].status == "accepted"


def test_service_verdict_tail_stripped_and_executed(ve_conn, conv_store):
    task = _make_task(ALICE, "Tail room")
    executor = _RecordingExecutor()
    reply = (
        "That reading stands accepted, then.\n\n[[verdict]]\n"
        "verdict | accept | reading:rdg-xyz"
    )
    result, _prompt = _turn(
        conv_store, ALICE, "guardian", _palace_context(task["id"]),
        "Accept that reading.", reply,
        palace_verdict_executor=executor,
    )
    # The visitor never sees the tail — in the result or the record.
    assert "[[verdict]]" not in result.reply.reply
    assert "verdict |" not in result.reply.reply
    msgs = conv_store.history(ALICE, result.conversation_id)
    assistant = [m for m in msgs if m.get("role") == "voice"]
    assert assistant and "[[verdict]]" not in assistant[-1]["body"]
    # The executor got the act, keyed to the staged subject.
    assert len(executor.calls) == 1
    call = executor.calls[0]
    assert call["entity_id"] == task["id"]
    assert [a.item_id for a in call["acts"]] == ["reading:rdg-xyz"]


def test_service_tail_only_reply_drops_acts(ve_conn, conv_store):
    task = _make_task(ALICE, "Empty room")
    executor = _RecordingExecutor()
    result, _prompt = _turn(
        conv_store, ALICE, "guardian", _palace_context(task["id"]),
        "Accept it.", "[[verdict]]\nverdict | accept | reading:rdg-1",
        palace_verdict_executor=executor,
    )
    assert executor.calls == []
    assert "[[verdict]]" not in result.reply.reply


# ---------------------------------------------------------------------------
# S5 — the weighing tail
# ---------------------------------------------------------------------------


def test_settle_language_gate_both_directions():
    assert PT.visitor_settles("Settle it.")
    assert PT.visitor_settles("Yes — lock it in.")
    assert PT.visitor_settles("Make it so.")
    assert PT.visitor_settles("That's settled, then.")
    assert not PT.visitor_settles("What would 6 hours change?")
    assert not PT.visitor_settles("Maybe we weigh it next week.")
    assert not PT.visitor_settles("Tell me about the scales.")


def test_weighing_tail_parsing_fail_closed():
    parsed = PT.parse_weighing_tail(
        "Words.\n[[weighing]]\nsettle | project_hours | 6\n"
        "settle | keeper | per-1\nsettle | task_hours | -2\n"
        "settle | bogus | 1"
    )
    assert parsed.status == "ok"
    assert parsed.body == "Words."
    assert parsed.figures == {"project_hours": 6.0, "keeper": "per-1"}
    parsed = PT.parse_weighing_tail("Words.\n[[weighing]]\nprose follows")
    assert parsed.status == "malformed"
    assert parsed.figures == {}


def _weighing_world():
    # The scales_weighing decision record rides the decisions
    # permission (the POST /decisions route's gate — consent given
    # plus profile_learning): on here.
    S.upsert_user_permissions_settings(
        ALICE,
        permissions={"profile_learning": True},
        consent_acknowledged=True,
        consent_version="v1",
    )
    keeper = _make_person(ALICE, "Keeper Kate")
    ve_service.upsert_capacity_profile(
        M.CapacityProfileUpsert(person_id=keeper["id"], weekly_capacity_hours=25),
        ALICE,
    )
    project = _make_project(
        ALICE, "Weighed floor", status="Active",
        owner_id=keeper["id"], estimated_weekly_hours=10,
    )
    task = _make_task(
        ALICE, "Weighed room", project_id=project["id"], estimated_hours=2,
    )
    return keeper, project, task


def test_weighing_executor_settles_exactly_like_the_panel(ve_conn):
    keeper, project, task = _weighing_world()
    executor = PT.PalaceWeighingExecutor()
    diags = executor.execute(
        user_id=ALICE, entity_type="task", entity_id=task["id"],
        figures={"project_hours": 14.0, "task_hours": 5.0},
    )
    assert diags == []
    after_project = S.get_project(project["id"], ALICE)
    after_task = S.get_task(task["id"], ALICE)
    assert after_project["estimated_weekly_hours"] == 14
    assert after_task["estimated_hours"] == 5
    # The decision record: #433's shape, anchored on the project
    # (a project figure changed).
    decisions = S.list_decisions(ALICE)
    weighing = [d for d in decisions if d["decision_type"] == "scales_weighing"]
    assert len(weighing) == 1
    decision = weighing[0]
    assert decision["entity_type"] == "project"
    assert decision["entity_id"] == project["id"]
    final = decision["final_values_snapshot"]
    assert final["kind"] == "scales_weighing"
    assert final["settled"]["project_weekly_hours"] == 14
    assert final["settled"]["task_estimated_hours"] == 5
    assert final["recorded_before"]["project_weekly_hours"] == 10
    proposal = decision["ai_proposal_snapshot"]
    kate = [c for c in proposal["consequences"] if c["person_id"] == keeper["id"]]
    assert kate and kate[0]["committed_hours"] == 14
    assert kate[0]["capacity_hours"] == 25
    assert kate[0]["overcapacity"] is False


def test_weighing_executor_no_baseline_figure_drops(ve_conn):
    keeper = _make_person(ALICE, "Keeper Kate")
    project = _make_project(
        ALICE, "Unweighed floor", status="Active", owner_id=keeper["id"],
    )
    executor = PT.PalaceWeighingExecutor()
    diags = executor.execute(
        user_id=ALICE, entity_type="project", entity_id=project["id"],
        figures={"project_hours": 6.0},
    )
    assert any("no recorded baseline" in d for d in diags)
    assert S.get_project(project["id"], ALICE)["estimated_weekly_hours"] is None
    assert S.list_decisions(ALICE) == []


def test_weighing_executor_noop_settle_writes_nothing(ve_conn):
    _keeper, project, task = _weighing_world()
    executor = PT.PalaceWeighingExecutor()
    diags = executor.execute(
        user_id=ALICE, entity_type="task", entity_id=task["id"],
        figures={"project_hours": 10.0},
    )
    assert any("matched the record" in d for d in diags)
    assert S.list_decisions(ALICE) == []


def test_service_weighing_requires_the_visitors_settle_words(ve_conn, conv_store):
    task = _make_task(ALICE, "Gated room")
    executor = _RecordingExecutor()
    reply = "At 6 hours the floor would sit heavier.\n\n[[weighing]]\nsettle | task_hours | 6"
    # Exploration: the tail parses but the visitor never settled —
    # the executor is never called and the tail still never shows.
    result, _ = _turn(
        conv_store, ALICE, "guardian", _palace_context(task["id"]),
        "What would 6 hours change?", reply,
        palace_weighing_executor=executor,
    )
    assert executor.calls == []
    assert "[[weighing]]" not in result.reply.reply
    # Settlement: his words open the gate.
    result, _ = _turn(
        conv_store, ALICE, "guardian", _palace_context(task["id"]),
        "Settle it at 6.", reply,
        palace_weighing_executor=executor,
    )
    assert len(executor.calls) == 1
    assert executor.calls[0]["figures"] == {"task_hours": 6.0}
    assert "[[weighing]]" not in result.reply.reply
