"""Upload rapid-fire S1 — round planning + service tests (brief §16, T29–T33).

Deterministic: seeded rows, a capturing fake generate_fn, tmp SQLite.
The planner never writes; the service performs the park / offer /
round-record effects after generation succeeds. All store calls use
the real ConversationStore API (user_id first; append_message returns
the message dict; the turn signature is (user, seat, message, convo, mode)).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import local_ai.conversation.service as service_mod
import local_ai.conversation.upload_round as UR
from local_ai.agent_intake.store import AgentStore
from local_ai.conversation.service import ConversationService
from local_ai.conversation.store import ConversationStore

USER = "u1"
STRAND = "heart"


@pytest.fixture()
def store(tmp_path: Path) -> ConversationStore:
    s = ConversationStore(db_path=tmp_path / "conv.db")
    yield s
    s.close()


@pytest.fixture()
def agent_store(tmp_path: Path) -> AgentStore:
    s = AgentStore(db_path=tmp_path / "agents.db", user_id=USER)
    yield s
    s.close()


@pytest.fixture()
def round_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ZENAF_UPLOAD_ROUND", "1")
    yield


def _seed_doc(store: ConversationStore, n: int = 1, *, strand: str = STRAND):
    """A pasted source + n pending interpretations; returns (convo, doc, ids)."""
    convo = store.resolve_strand_thread(USER, strand)["conversation_id"]
    text = (
        "The morning light fell across the kitchen table where the letters "
        "had been left in a neat stack."
    )
    src = store.add_strand_source(
        USER, strand, convo, kind="paste", ref="paste-1", label="Field notes",
        excerpt_redacted=text, paste_full_text=text,
    )
    doc = src["id"]
    ids = []
    for i in range(n):
        span = store.save_upload_span(
            USER, doc, 1, "seg-0000", text, "redacted", f"seg-0000:0-{len(text)}"
        )
        row = store.save_upload_interpretation(
            USER, doc, 1, strand, "strand",
            f"Reading {i + 1}: the day moved.",
            [{"span_id": span["span_id"], "role": "primary"}],
            [], "extracted", False, "task", None, None, False,
        )
        ids.append(row["interpretation_id"])
    return convo, doc, ids


def _marker_msg(store, convo, round_id, state, interp_id=None):
    return store.append_message(
        USER, convo, "conductor", "voice", "reply", "talk",
        {"round_kind": "upload", "round_id": round_id,
         "round_state": state, "round_interpretation_id": interp_id},
    )


def _add_interpretation(store: ConversationStore, doc: str, text: str) -> str:
    """One more pending interpretation on an EXISTING document (same
    span row — save_upload_span dedupes by hash+location)."""
    span_text = (
        "The morning light fell across the kitchen table where the letters "
        "had been left in a neat stack."
    )
    span = store.save_upload_span(
        USER, doc, 1, "seg-0000", span_text, "redacted",
        f"seg-0000:0-{len(span_text)}",
    )
    row = store.save_upload_interpretation(
        USER, doc, 1, STRAND, "strand", text,
        [{"span_id": span["span_id"], "role": "primary"}],
        [], "extracted", False, "task", None, None, False,
    )
    return row["interpretation_id"]


def _turn_service(store, agent_store, captured, monkeypatch):
    # The service calls generate_fn as gen(prompt, provider_id=...,
    # user_id=..., operation=..., timeout=...). When the prompt carries
    # the offer block, the seat voices it with the marker on its own
    # line — that is what records the offer row.
    def fake(prompt, **kw):
        captured.append(prompt)
        if "[[round-offer]]" in prompt:
            return "Some readings are waiting for you.\n[[round-offer]]"
        return "noted"

    monkeypatch.setattr(service_mod, "AgentStore", lambda user_id: agent_store)
    return ConversationService(store, generate_fn=fake)


def _turn(svc, convo, text):
    return svc.turn(USER, "conductor", text, convo, "talk")


# -- round (T29–T33) ---------------------------------------------------------------


def test_t29_offer_fires_at_three_pending_not_below(store):
    # Invoke NEVER offers: it starts a fresh round with item 1. The
    # offer gate runs only on ordinary (non-invoke) turns.
    convo, doc, ids = _seed_doc(store, n=2)
    plan = UR.plan_upload_round_turn(store, USER, convo, "The garden needs watering today.")
    assert plan is None or plan.offer is None
    _add_interpretation(store, doc, "Reading 3: the day moved.")
    plan = UR.plan_upload_round_turn(store, USER, convo, "The garden needs watering today.")
    assert plan.offer is not None
    assert plan.offer_invited is True
    assert "up to 3 readings" in plan.block
    assert "[[round-offer]]" in plan.block


def test_t30_explicit_invocation_at_zero_is_honest_nothing_waiting(store):
    convo = store.resolve_strand_thread(USER, STRAND)["conversation_id"]
    plan = UR.plan_upload_round_turn(store, USER, convo, "What's waiting for me?")
    assert plan is not None
    assert not plan.has_effect
    assert plan.item is None
    assert plan.block is None


def test_t31_cap_ten_then_checkpoint(store, agent_store, round_on, monkeypatch):
    convo, doc, ids = _seed_doc(store, n=11)
    captured: list = []
    svc = _turn_service(store, agent_store, captured, monkeypatch)
    r1 = _turn(svc, convo, "What's waiting for me?")
    assert r1.round_item is not None
    assert r1.round_item["interpretation_id"] == ids[0]
    # Nine skip turns present items 2–10.
    for i in range(1, 10):
        r = _turn(svc, convo, "I need to check")
        assert r.round_item is not None, f"item {i + 1} missing"
        assert r.round_item["interpretation_id"] == ids[i]
    # The eleventh turn: another skip, but the segment is exhausted —
    # the checkpoint block, no eleventh item without the user's word.
    # (The message must be a skip, not a stop: "that's enough" is a
    # STOP phrase and would end the round instead of checkpointing.)
    r11 = _turn(svc, convo, "I need to check")
    assert r11.round_item is None
    assert "[Upload rapid fire — checkpoint]" in captured[-1]
    assert "10 readings" in captured[-1]


def test_t31b_continue_after_checkpoint_presents_item_eleven(store, agent_store, round_on, monkeypatch):
    # Amendment A7.1: the per-round presented-count resets to 0 on
    # continue, so the checkpoint fires when the count reaches 10
    # and the eleventh item presents after the user's word.
    convo, doc, ids = _seed_doc(store, n=11)
    captured: list = []
    svc = _turn_service(store, agent_store, captured, monkeypatch)
    r1 = _turn(svc, convo, "What's waiting for me?")
    assert r1.round_item is not None
    assert r1.round_item["interpretation_id"] == ids[0]
    for i in range(1, 10):
        r = _turn(svc, convo, "I need to check")
        assert r.round_item is not None, f"item {i + 1} missing"
        assert r.round_item["interpretation_id"] == ids[i]
    r11 = _turn(svc, convo, "I need to check")
    assert r11.round_item is None
    assert "[Upload rapid fire — checkpoint]" in captured[-1]
    # The user's word to continue: the segment resets, item 11 presents.
    r12 = _turn(svc, convo, "keep going")
    assert r12.round_item is not None
    assert r12.round_item["interpretation_id"] == ids[10]
    assert "Reading 11" in captured[-1]


def test_t32_mid_round_invoke_restarts_fresh_with_new_round_id(store):
    convo, doc, ids = _seed_doc(store, n=4)
    plan1 = UR.plan_upload_round_turn(store, USER, convo, "What's waiting?")
    assert plan1 is not None and plan1.round_record is not None
    first_round_id = plan1.round_record["round_id"]
    # Simulate the service's marker write for the first turn.
    _marker_msg(store, convo, first_round_id, "item", ids[0])
    # Park one item, then invoke again: a fresh round, parks cleared.
    store.park_round_item(USER, convo, "upload", ids[0])
    plan2 = UR.plan_upload_round_turn(store, USER, convo, "What's waiting?")
    assert plan2 is not None
    assert plan2.round_record is not None
    assert plan2.round_record["round_id"] != first_round_id
    assert plan2.clear_parked is True
    assert plan2.item is not None
    assert plan2.item["interpretation_id"] == ids[0]


def test_t33_unrelated_message_neither_advances_nor_ends(store):
    convo, doc, ids = _seed_doc(store, n=4)
    plan1 = UR.plan_upload_round_turn(store, USER, convo, "What's waiting?")
    assert plan1 is not None and plan1.item is not None
    _marker_msg(store, convo, plan1.round_record["round_id"], "item", ids[0])
    plan2 = UR.plan_upload_round_turn(
        store, USER, convo, "The garden needs watering today."
    )
    assert plan2 is None or not plan2.has_effect


def test_t33b_declined_offer_with_never_is_not_re_offered(store):
    convo, doc, ids = _seed_doc(store, n=4)
    plan = UR.plan_upload_round_turn(store, USER, convo, "The garden needs watering today.")
    assert plan is not None and plan.offer is not None
    # Decline the offer with snooze NULL (never): no second offer.
    offer = store.save_upload_offer(
        USER, doc, STRAND, "offered", "first 1 of 1 chunks", None
    )
    store.set_upload_offer_state(USER, offer["offer_id"], "declined", None)
    plan2 = UR.plan_upload_round_turn(store, USER, convo, "The garden needs watering today.")
    assert plan2 is None or plan2.offer is None


def test_t33c_offered_marker_bars_second_offer(store):
    convo, doc, ids = _seed_doc(store, n=4)
    plan = UR.plan_upload_round_turn(store, USER, convo, "The garden needs watering today.")
    assert plan is not None and plan.offer is not None
    _marker_msg(store, convo, "round-1", "offered")
    plan2 = UR.plan_upload_round_turn(store, USER, convo, "The garden needs watering today.")
    assert plan2 is None or plan2.offer is None


# -- service integration ------------------------------------------------------------


def test_service_invoke_skip_stop_turns(store, agent_store, round_on, monkeypatch):
    convo, doc, ids = _seed_doc(store, n=4)
    captured: list = []
    svc = _turn_service(store, agent_store, captured, monkeypatch)
    r1 = _turn(svc, convo, "What's waiting for me?")
    assert r1.round_item is not None
    assert r1.round_item["kind"] == "interpretation"
    assert r1.round_item["interpretation_id"] == ids[0]
    assert r1.round_state == "item"
    # The block is in the prompt.
    assert "Reading 1" in captured[-1]
    # Ordinary message: no item, no block.
    r2 = _turn(svc, convo, "The garden needs watering today.")
    assert r2.round_item is None
    # Skip prose parks item 1 and advances to item 2.
    r3 = _turn(svc, convo, "I need to check")
    assert r3.round_item is not None
    assert r3.round_item["interpretation_id"] == ids[1]
    assert store.list_parked_round_items(USER, convo, "upload") == [ids[0]]
    # Stop ends the round.
    r4 = _turn(svc, convo, "Stop the round")
    assert r4.round_item is None


def test_service_offer_gate_and_record(store, agent_store, round_on, monkeypatch):
    convo, doc, ids = _seed_doc(store, n=3)
    # A job row gives the offer its coverage claim (no job → no claim).
    # Amendment A1: the coverage names INTERPRETED chunks, so the
    # job carries its interpreted chunk (the seed's one span segment).
    job = store.create_upload_job(USER, doc, 1)
    store.set_upload_job_state(
        job["job_id"], "complete", interpreted_chunks=["seg-0000"]
    )
    captured: list = []
    svc = _turn_service(store, agent_store, captured, monkeypatch)
    r = _turn(svc, convo, "The garden needs watering today.")
    assert r.round_item is None  # offer, not an item
    assert "[[round-offer]]" in captured[-1]
    offer = store.get_upload_offer(USER, doc, STRAND)
    assert offer is not None
    assert offer["state"] == "offered"
    assert offer["coverage"] == "first 1 of 1 chunks, as read"


def test_service_upload_wins_over_weaver_in_strand_thread(
    store, agent_store, round_on, monkeypatch
):
    # A strand thread with an upload queue AND a pending Weaver claim:
    # the upload block wins; Weaver's plan is dropped for the turn.
    monkeypatch.setenv("ZENAF_WEAVER_ROUND", "1")
    convo, doc, ids = _seed_doc(store, n=2)
    captured: list = []
    svc = _turn_service(store, agent_store, captured, monkeypatch)
    r = _turn(svc, convo, "What's waiting for me?")
    assert r.round_item is not None
    assert r.round_item["kind"] == "interpretation"


def test_service_no_block_when_kill_switch_off(store, agent_store, monkeypatch):
    # An explicit "0" disables the round; deleting the variable does
    # NOT — local dev (no FLY_APP_NAME) defaults ON.
    monkeypatch.setenv("ZENAF_UPLOAD_ROUND", "0")
    convo, doc, ids = _seed_doc(store, n=4)
    captured: list = []
    svc = _turn_service(store, agent_store, captured, monkeypatch)
    r = _turn(svc, convo, "What's waiting for me?")
    assert r.round_item is None
    assert "Reading 1" not in captured[-1]


def test_round_queue_excludes_exact_match_discovered_at_queue_time(store):
    convo, doc, ids = _seed_doc(store, n=2)
    # A twin of Reading 1, ruled after the queue was seeded: the
    # original Reading 1 is its exact twin and must never be
    # presented twice.
    span = store.list_upload_spans(USER, doc, 1)[0]
    twin = store.save_upload_interpretation(
        USER, doc, 1, STRAND, "strand",
        "Reading 1: the day moved.",
        [{"span_id": span["span_id"], "role": "primary"}],
        [], "extracted", False, "task", None, None, False,
    )
    store.set_upload_interpretation_status(
        USER, twin["interpretation_id"], "ruled"
    )
    queue = UR.compose_upload_queue(
        store, USER, doc, STRAND,
        parked_ids=set(), reserved_ids=set(), round_started_at=None,
    )
    texts = [it["text"] for it in queue]
    assert "Reading 1: the day moved." not in texts
    assert texts == ["Reading 2: the day moved."]


def test_round_uncertain_match_carried_as_marker(store):
    convo, doc, ids = _seed_doc(store, n=1)
    # Rule a reading with the same text but different spans.
    other_span = store.save_upload_span(
        USER, doc, 1, "seg-0000", "had been left in a neat stack",
        "redacted", "seg-0000:50-82",
    )
    row = store.save_upload_interpretation(
        USER, doc, 1, STRAND, "strand",
        "Reading 1: the day moved.",
        [{"span_id": other_span["span_id"], "role": "primary"}],
        [], "extracted", False, "task", None, None, False,
    )
    store.set_upload_interpretation_status(USER, row["interpretation_id"], "ruled")
    queue = UR.compose_upload_queue(
        store, USER, doc, STRAND,
        parked_ids=set(), reserved_ids=set(), round_started_at=None,
    )
    assert len(queue) == 1
    assert queue[0]["uncertain_match"] is not None
    assert queue[0]["uncertain_match"]["kind"] == "text_only"
