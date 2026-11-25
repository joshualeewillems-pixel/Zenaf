"""V3 — pencil carriage for the encountering seat (champion).

Governing basis: narrative architecture I3 / §9 rendering contract,
bounded to champion (Valen vertical slice scoping §3.4). Zero model
spend: every service turn is a recorded output through the real
``ConversationService.turn`` with an injected ``generate_fn``.

Pins:
- the carriage toggle ``ZENAF_PENCIL_CHAMPION`` (read per call,
  default off) gates RENDERING only, independently of every other
  switch — flag-off prompts are byte-identical to V1-head behavior
  and the obligation-block path is untouched either way;
- the encounter-scope preparation path: the active encounter arc
  (V1) is preparable during its own encounter through
  ``prepare_context``'s fresh dual-flag consent re-validation and
  relevance discipline, alongside the standing-thread selection;
- the §9 contract's two added field classes inside the existing
  caps and byte-stable header: ONE verbatim objection quote sourced
  from the CURRENT recognition reading's evidence only (widening to
  thread evidence is an open founder decision and is NOT built),
  and the seat's own recognition in its own words (latest current
  recognition reading only);
- the whitelist: due items, decisions, next steps, milestones and
  positions in an arc's records render NONE of themselves.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from local_ai.conversation.service import ConversationService
from local_ai.conversation.store import ConversationStore
from local_ai.narrative import NarrativeStore
from local_ai.narrative.context import (
    CHAMPION_BRANCH_ID,
    MAX_PENCIL_CHARS,
    MAX_PENCIL_THREADS,
    _PENCIL_HEADER,
    champion_context_provider,
    champion_pencil_context_for,
    pencil_champion_enabled,
)
from local_ai.narrative.refs import SourceRef
from local_ai.vision_execution import obligations as _obligations

USER = "u-v3"
CONVO = "v3-convo"
CHAMPION = "champion"

FLAGS_ON = {"steward_derivation": True, "steward_coordination": True}

TURN_REF = SourceRef(kind="event", ref_id="evt-turn-0", evidence_kind="quote")
OBJ_REF = SourceRef(kind="event", ref_id="evt-obj-1", evidence_kind="quote")
OTHER_REF = SourceRef(kind="event", ref_id="evt-other-2", evidence_kind="quote")

OBJECTION_TEXT = "I never agreed to carry this alone."
TURN_TEXT = "turn zero words that are evidence but not an objection"
EVENT_TEXTS = {
    "evt-turn-0": TURN_TEXT,
    "evt-obj-1": OBJECTION_TEXT,
    "evt-other-2": "some other visitor words entirely",
}

RECOGNITION = "He keeps volunteering while his hands shake."


def _resolver(event_id):
    return EVENT_TEXTS.get(event_id)


def _perm_conn(flags_by_user):
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


def _future():
    return (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()


@pytest.fixture()
def store(tmp_path):
    return NarrativeStore(db_path=tmp_path / "narrative.db")


@pytest.fixture()
def conn():
    return _perm_conn({USER: FLAGS_ON})


@pytest.fixture()
def flags_on(monkeypatch):
    monkeypatch.setenv("ZENAF_STEWARD_PENCIL", "1")
    monkeypatch.setenv("ZENAF_PENCIL_CHAMPION", "1")


def _encounter_thread(store, user=USER):
    thread = store.create_thread(
        user,
        origin="steward_proposal",
        title=f"Encounter — champion — {CONVO}",
        evidence_refs=(TURN_REF,),
    )
    store.open_encounter_scope(
        user,
        thread.id,
        conversation_id=CONVO,
        archetype_id=CHAMPION,
        span_start_message_id="msg-1",
    )
    return store.get_thread(user, thread.id)


def _held_objection(store, thread_id, ref=OBJ_REF, user=USER):
    return store.add_held_note(
        user,
        thread_id,
        conversation_id=CONVO,
        archetype_id=CHAMPION,
        kind="objection",
        cited_message_id="msg-1",
        evidence_ref=ref,
        source_user_message_id="msg-1",
        source_reply_message_id="msg-2",
        author=CHAMPION,
        expires_at=_future(),
    )


def _arc_with_recognition_and_objection(store, user=USER, reading_extra=None):
    """The synthetic arc: a seat-authored recognition reading whose
    own evidence includes the objection's event, plus the held
    objection note citing that same event (the V1 shape)."""
    thread = _encounter_thread(store, user)
    reading_payload = {"recognition": RECOGNITION}
    if reading_extra:
        reading_payload.update(reading_extra)
    reading = store.propose_reading(
        user,
        thread.id,
        author=CHAMPION,
        reading=reading_payload,
        evidence_refs=(OBJ_REF,),
    )
    _held_objection(store, thread.id, user=user)
    return thread, reading


def _prepare(store, conn, **kw):
    kw.setdefault("evidence_text_resolver", _resolver)
    return champion_pencil_context_for(
        store, USER, conversation_id=CONVO, connection=conn, **kw
    )


# -- the carriage toggle --------------------------------------------------------


def test_pencil_champion_enabled_default_off(monkeypatch):
    monkeypatch.delenv("ZENAF_PENCIL_CHAMPION", raising=False)
    assert pencil_champion_enabled() is False
    monkeypatch.setenv("ZENAF_PENCIL_CHAMPION", "")
    assert pencil_champion_enabled() is False
    monkeypatch.setenv("ZENAF_PENCIL_CHAMPION", "1")
    assert pencil_champion_enabled() is True
    monkeypatch.setenv("ZENAF_PENCIL_CHAMPION", "off")
    assert pencil_champion_enabled() is False


def test_master_off_no_carriage(store, conn, monkeypatch):
    monkeypatch.delenv("ZENAF_STEWARD_PENCIL", raising=False)
    monkeypatch.setenv("ZENAF_PENCIL_CHAMPION", "1")
    _arc_with_recognition_and_objection(store)
    prepared = _prepare(store, conn)
    assert prepared.available is False
    assert prepared.reason == "pencil_flag_off"
    assert prepared.block is None


def test_carriage_toggle_off_no_carriage_and_no_store_writes(
    store, conn, monkeypatch
):
    monkeypatch.setenv("ZENAF_STEWARD_PENCIL", "1")
    monkeypatch.delenv("ZENAF_PENCIL_CHAMPION", raising=False)
    _arc_with_recognition_and_objection(store)
    prepared = _prepare(store, conn)
    assert prepared.available is False
    assert prepared.reason == "pencil_champion_flag_off"
    assert prepared.block is None
    # Rendering-only gate: the toggle's absence costs no preparation
    # at all — no relevance assessment rows were recorded.
    assert prepared.assessment_ids == ()


# -- consent: either flag off ⇒ no carriage, fail-closed -------------------------


@pytest.mark.parametrize(
    "flags",
    [
        {"steward_derivation": False, "steward_coordination": True},
        {"steward_derivation": True, "steward_coordination": False},
        {"steward_derivation": False, "steward_coordination": False},
    ],
)
def test_either_consent_flag_off_no_carriage(store, flags_on, flags):
    _arc_with_recognition_and_objection(store)
    conn = _perm_conn({USER: flags})
    prepared = _prepare(store, conn)
    assert prepared.available is False
    assert prepared.reason == "consent_closed"
    assert prepared.block is None


# -- the §9 field classes ---------------------------------------------------------


def test_encounter_arc_renders_recognition_and_verbatim_objection(
    store, conn, flags_on
):
    thread, reading = _arc_with_recognition_and_objection(store)
    prepared = _prepare(store, conn, attended_text="anything at all")
    assert prepared.available is True
    block = prepared.block
    # Header byte-stable, exactly the standing pencil header.
    assert block.splitlines()[0] == _PENCIL_HEADER
    assert "Prepared for Firebrand." in block
    # The seat's own recognition, in its own words.
    assert f'own recognition, in its own words: "{RECOGNITION}"' in block
    # ONE verbatim objection quote, the visitor's exact words.
    assert f'visitor objection, verbatim: "{OBJECTION_TEXT}"' in block
    # Nothing citable travels: no reading id, no evidence ref ids.
    assert reading.id not in block
    assert "evt-obj-1" not in block
    # The turn's own evidence text is not an objection and never renders.
    assert TURN_TEXT not in block
    # Manifest facts name the encounter thread and its reading.
    assert prepared.threads[0]["thread_id"] == thread.id
    assert prepared.threads[0]["reading_id"] == reading.id


def test_whitelist_due_decisions_next_steps_positions_render_none(
    store, conn, flags_on
):
    secrets = {
        "milestones": ["MILESTONE-SECRET-TEXT"],
        "due_items": ["DUE-ITEM-SECRET-TEXT"],
        "decisions": ["DECISION-SECRET-TEXT"],
        "next_steps": ["NEXT-STEP-SECRET-TEXT"],
        "positions": ["POSITION-SECRET-TEXT"],
    }
    _arc_with_recognition_and_objection(store, reading_extra=secrets)
    prepared = _prepare(store, conn)
    assert prepared.available is True
    for values in secrets.values():
        for secret in values:
            assert secret not in prepared.block


def test_objection_outside_current_reading_evidence_never_renders(
    store, conn, flags_on
):
    """The exclusion, pinned: an objection whose evidence is attached
    to the THREAD but is not part of the current recognition
    reading's evidence does not qualify for the slot. Widening the
    sourcing to thread evidence is an open founder decision."""
    thread = _encounter_thread(store)
    store.propose_reading(
        USER,
        thread.id,
        author=CHAMPION,
        reading={"recognition": RECOGNITION},
        evidence_refs=(TURN_REF,),
    )
    # The objection's event IS thread evidence (attached by the held
    # note's own add path is not evidence; attach it directly) — but
    # it is not the current reading's evidence.
    store.add_evidence(USER, thread.id, OTHER_REF)
    _held_objection(store, thread.id, ref=OTHER_REF)
    prepared = _prepare(store, conn)
    assert prepared.available is True
    assert RECOGNITION in prepared.block
    assert EVENT_TEXTS["evt-other-2"] not in prepared.block
    assert "visitor objection" not in prepared.block


def test_only_latest_current_recognition_and_its_objection_render(
    store, conn, flags_on
):
    thread = _encounter_thread(store)
    first = store.propose_reading(
        USER,
        thread.id,
        author=CHAMPION,
        reading={"recognition": "First recognition, later reverted."},
        evidence_refs=(OBJ_REF,),
    )
    _held_objection(store, thread.id)
    # Supersession through the change machinery (the V1 order): the
    # change lands first carrying newly attached evidence, then the
    # new recognition reading.
    store.record_change(
        USER,
        thread.id,
        kind="extended",
        evidence_refs=[OTHER_REF],
        prior_reading_id=first.id,
    )
    store.propose_reading(
        USER,
        thread.id,
        author=CHAMPION,
        reading={"recognition": "Second recognition, the current one."},
        evidence_refs=(OTHER_REF,),
    )
    prepared = _prepare(store, conn)
    assert prepared.available is True
    assert "Second recognition, the current one." in prepared.block
    assert "First recognition, later reverted." not in prepared.block
    # The objection rode the SUPERSEDED reading's evidence only; the
    # current reading's evidence does not include it, so no quote.
    assert OBJECTION_TEXT not in prepared.block


def test_steward_authored_recognition_key_is_not_seat_recognition(
    store, conn, flags_on
):
    thread = _encounter_thread(store)
    store.propose_reading(
        USER,
        thread.id,
        author="steward",
        reading={
            "recognition": "A steward paraphrase, not the seat's words.",
            "tensions": ["a tension that may travel"],
        },
        evidence_refs=(TURN_REF,),
    )
    prepared = _prepare(store, conn)
    assert prepared.available is True
    assert "a tension that may travel" in prepared.block
    assert "A steward paraphrase" not in prepared.block


def test_closed_encounter_is_not_carried(store, conn, flags_on):
    thread, _ = _arc_with_recognition_and_objection(store)
    store.close_encounter_scope(USER, thread.id, span_end_message_id="msg-9")
    prepared = _prepare(store, conn)
    assert prepared.available is False
    assert prepared.block is None


def test_encounter_in_another_conversation_is_not_carried(
    store, conn, flags_on
):
    _arc_with_recognition_and_objection(store)
    prepared = champion_pencil_context_for(
        store,
        USER,
        conversation_id="some-other-conversation",
        connection=conn,
        evidence_text_resolver=_resolver,
    )
    assert prepared.available is False
    assert prepared.block is None


# -- alongside the standing-thread selection --------------------------------------


def _standing_thread(store, user=USER, title="The long climb"):
    thread = store.create_thread(
        user, origin="user_declared", title=title, evidence_refs=(TURN_REF,)
    )
    store.annotate_evidence_entities(
        user, thread.id, {("event", "evt-turn-0"): "person:quinlin"}
    )
    store.set_thread_status(user, thread.id, "active")
    store.propose_reading(
        user,
        thread.id,
        author="steward",
        reading={"tensions": ["progress that does not feel like freedom"]},
        evidence_refs=(TURN_REF,),
    )
    return thread


def test_standing_threads_render_alongside_encounter_arc(
    store, conn, flags_on
):
    _arc_with_recognition_and_objection(store)
    _standing_thread(store)
    prepared = _prepare(store, conn, attended_text="thinking about quinlin")
    assert prepared.available is True
    block = prepared.block
    assert block.count(_PENCIL_HEADER) == 1
    assert RECOGNITION in block
    assert OBJECTION_TEXT in block
    assert "progress that does not feel like freedom" in block
    # The encounter's own arc is carried first.
    assert block.index(RECOGNITION) < block.index(
        "progress that does not feel like freedom"
    )


# -- caps -------------------------------------------------------------------------


def test_caps_thread_cap_and_item_truncation(store, conn, flags_on):
    long_recognition = "R" * 300
    thread = _encounter_thread(store)
    store.propose_reading(
        USER,
        thread.id,
        author=CHAMPION,
        reading={"recognition": long_recognition},
        evidence_refs=(TURN_REF,),
    )
    for i in range(MAX_PENCIL_THREADS + 2):
        _standing_thread(store, title=f"Standing thread {i}")
    prepared = _prepare(store, conn, attended_text="quinlin quinlin")
    assert prepared.available is True
    assert len(prepared.threads) == MAX_PENCIL_THREADS
    # 1 encounter item + (MAX+2) standing items, MAX shown ⇒ 3 hidden.
    assert "+3 more observation(s) not shown." in prepared.block
    # Per-item discipline: the recognition is truncated to 160 chars.
    assert "R" * 160 in prepared.block
    assert "R" * 161 not in prepared.block
    assert len(prepared.block) <= MAX_PENCIL_CHARS + len("\n[…truncated]")


# -- the provider -------------------------------------------------------------------


def test_provider_fail_closed_without_conversation_id(store, conn, flags_on):
    _arc_with_recognition_and_objection(store)
    provider = champion_context_provider(
        store=store, connection=conn, evidence_text_resolver=_resolver
    )
    assert provider(USER, "hello", []) is None
    block = provider(USER, "hello", [], conversation_id=CONVO)
    assert block is not None
    assert OBJECTION_TEXT in block


def test_provider_returns_none_when_toggle_off(store, conn, monkeypatch):
    monkeypatch.setenv("ZENAF_STEWARD_PENCIL", "1")
    monkeypatch.delenv("ZENAF_PENCIL_CHAMPION", raising=False)
    _arc_with_recognition_and_objection(store)
    provider = champion_context_provider(
        store=store, connection=conn, evidence_text_resolver=_resolver
    )
    assert provider(USER, "hello", [], conversation_id=CONVO) is None


# -- the service seam: byte-identity, toggle independence, maverick unchanged ------


class RecordedGen:
    """Fake generate_fn in the Stage 1B shape (see test_noting_capture)."""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.prompts = []

    def __call__(self, prompt, **kw):
        if kw.get("operation") == "conversation-thread-summary":
            return "Rolling summary of the thread."
        self.prompts.append(prompt)
        if self.outputs:
            return self.outputs.pop(0)
        return "Recorded reply with nothing left queued."


@pytest.fixture()
def conv_store(tmp_path):
    store = ConversationStore(db_path=tmp_path / "conv.db")
    yield store
    store.close()


def _champion_provider(store, conn):
    return champion_context_provider(
        store=store,
        connection=conn,
        with_selection=True,
        evidence_text_resolver=_resolver,
    )


def test_flag_off_prompt_byte_identical_to_no_provider(
    tmp_path, store, conn, conv_store, monkeypatch
):
    """ZENAF_PENCIL_CHAMPION off (and the master off): a champion
    turn's assembled prompt is byte-identical with and without the
    V3 provider wired — V1-head behavior given identical state."""
    _arc_with_recognition_and_objection(store)
    monkeypatch.delenv("ZENAF_PENCIL_CHAMPION", raising=False)
    monkeypatch.delenv("ZENAF_STEWARD_PENCIL", raising=False)

    gen_plain = RecordedGen(["Plain answer."])
    svc_plain = ConversationService(
        ConversationStore(db_path=tmp_path / "conv-plain.db"),
        generate_fn=gen_plain,
    )
    svc_plain.turn(USER, CHAMPION, "Hello.", conversation_id=CONVO)

    gen_wired = RecordedGen(["Plain answer."])
    svc_wired = ConversationService(
        conv_store,
        generate_fn=gen_wired,
        champion_pencil_context_provider=_champion_provider(store, conn),
    )
    svc_wired.turn(USER, CHAMPION, "Hello.", conversation_id=CONVO)

    assert gen_wired.prompts == gen_plain.prompts
    assert _PENCIL_HEADER not in gen_wired.prompts[0]


def test_flag_on_renders_and_obligation_block_unchanged(
    store, conn, conv_store, flags_on
):
    """Toggle independence: with carriage ON, the pencil block
    renders and the obligation block (the V4 surface) is present
    byte-for-byte as it is with carriage OFF — the carriage flag
    changes nothing in the obligation-block path."""
    _arc_with_recognition_and_objection(store)
    obligation_block, _status = _obligations.build_obligation_context(USER)

    gen_on = RecordedGen(["Answer."])
    svc_on = ConversationService(
        conv_store,
        generate_fn=gen_on,
        champion_pencil_context_provider=_champion_provider(store, conn),
    )
    svc_on.turn(USER, CHAMPION, "Hello.", conversation_id=CONVO)
    prompt_on = gen_on.prompts[0]
    assert _PENCIL_HEADER in prompt_on
    assert OBJECTION_TEXT in prompt_on
    assert obligation_block in prompt_on


def test_flag_off_obligation_block_still_rendered(
    store, conn, conv_store, monkeypatch
):
    _arc_with_recognition_and_objection(store)
    monkeypatch.setenv("ZENAF_STEWARD_PENCIL", "1")
    monkeypatch.delenv("ZENAF_PENCIL_CHAMPION", raising=False)
    obligation_block, _status = _obligations.build_obligation_context(USER)
    gen_off = RecordedGen(["Answer."])
    svc_off = ConversationService(
        conv_store,
        generate_fn=gen_off,
        champion_pencil_context_provider=_champion_provider(store, conn),
    )
    svc_off.turn(USER, CHAMPION, "Hello.", conversation_id=CONVO)
    assert obligation_block in gen_off.prompts[0]
    assert _PENCIL_HEADER not in gen_off.prompts[0]


def test_champion_flag_does_not_change_maverick_carriage(
    tmp_path, store, conn, monkeypatch
):
    """Maverick carriage unchanged: a maverick turn's prompt is
    identical whether ZENAF_PENCIL_CHAMPION is on or off."""
    from local_ai.narrative.context import jynx_context_provider

    _standing_thread(store)
    monkeypatch.setenv("ZENAF_STEWARD_PENCIL", "1")

    def run(flag_value):
        if flag_value is None:
            monkeypatch.delenv("ZENAF_PENCIL_CHAMPION", raising=False)
        else:
            monkeypatch.setenv("ZENAF_PENCIL_CHAMPION", flag_value)
        gen = RecordedGen(["Maverick answer."])
        svc = ConversationService(
            ConversationStore(db_path=tmp_path / f"conv-mav-{flag_value}.db"),
            generate_fn=gen,
            pencil_context_provider=jynx_context_provider(
                store=store, connection=conn, with_selection=True
            ),
        )
        svc.turn(USER, "maverick", "thinking about quinlin", conversation_id="mav")
        return gen.prompts[0]

    prompt_off = run(None)
    prompt_on = run("1")
    assert "progress that does not feel like freedom" in prompt_off
    assert prompt_on == prompt_off


def test_branch_id_is_champion():
    assert CHAMPION_BRANCH_ID == "seat:champion"
