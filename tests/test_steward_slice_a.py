"""Steward Slice A (Packet C1, revised, Revision 2) — Talk-path
subject carriage.

Acceptance tests T1–T10 from the revised contract §5, plus the
corrected headline scenario and the §5 rollback positions. All
deterministic: generations are counting fakes on the injectable
seam, stores are tmp SQLite files, the VE store is a tmp database
behind the storage module's own connection seam. Zero model calls.

The design in one paragraph (contract §§4.2–4.8-R): a Talk turn
maintains the conversation's subject snapshot in the existing
ConversationStore (anchor step from the LiveContext hint, validated
through owner-scoped project/task getters only; then the trunk's
shared merge with absent inputs as None). The post-turn subject
rides the turn event's payload ONLY when it names an entity AND the
visitor's steward_derivation consent is active at emission.
Derivation reads the carried subject as an ANCHOR (in-memory
``EvidenceItem.anchor_ref``, never persisted, never an annotation):
its only consumption is one clustering rule, "shared conversation
anchor <ref>". Referents (``entity_ref``) are untouched everywhere.
"""

from __future__ import annotations

import json
import sqlite3
import threading

import pytest

from local_ai.conversation.service import ConversationService
from local_ai.conversation.store import ConversationStore
from local_ai.fellowship.events import FellowshipEvent
from local_ai.narrative import NarrativeStore
from local_ai.narrative.changes import detect_changes_for_event
from local_ai.narrative.derivation import (
    cluster_items,
    derive_batch,
    event_to_item,
    subject_key_for_cluster,
    subject_key_for_thread,
)
from local_ai.narrative.refs import SourceRef
from local_ai.narrative.sweep import reconstruct_event
from local_ai.vision_execution import models as ve_models
from local_ai.vision_execution import storage as ve_storage
from local_ai.vision_execution.storage import init_db, open_sqlite_with_ve_pragmas

USER = "user-a"
OTHER = "user-b"

BIRTH_JSON = json.dumps(
    {
        "title": "The orchard years",
        "tensions": ["roots vs. road"],
        "open_questions": ["what endures?"],
        "milestones": ["planted the first row"],
        "scales": ["personal"],
        "primary_scale": "personal",
    }
)

EXTENSION_JSON = json.dumps(
    {
        "tensions": ["roots vs. road, revisited"],
        "open_questions": ["what endures now?"],
        "milestones": ["pruned the old row"],
        "scales": ["personal"],
        "primary_scale": "personal",
        "change_kind": "extended",
    }
)


# -- fixtures -----------------------------------------------------------------


@pytest.fixture
def ve_conn(tmp_path, monkeypatch):
    """A tmp VE database behind the storage module's connection seam.

    Both the anchor validation getters and the steward consent leaf
    reader resolve through ``ve_storage.get_connection``, so this
    one seam puts projects, tasks, and permission rows under the
    test's control — the pattern the existing VE suites use.
    """
    conn = open_sqlite_with_ve_pragmas(tmp_path / "ve.db")
    init_db(conn)
    monkeypatch.setattr(ve_storage, "get_connection", lambda: conn)
    yield conn
    conn.close()


def _set_consent(conn, user_id: str, on: bool) -> None:
    conn.execute(
        "INSERT INTO user_permissions_settings "
        "(user_id, consent_given, consent_version, consent_at, "
        "permissions_json, updated_at) VALUES (?, 1, 'permissions-v1', "
        "NULL, ?, '') "
        "ON CONFLICT(user_id) DO UPDATE SET "
        "permissions_json = excluded.permissions_json",
        (user_id, json.dumps({"steward_derivation": on})),
    )
    conn.commit()


def _project(user_id: str, title: str = "Orchard Gate") -> str:
    row = ve_storage.create_project(ve_models.ProjectCreate(title=title), user_id)
    return str(row["id"])


def _task(user_id: str, title: str = "Replace the hinge") -> str:
    row = ve_storage.create_task(ve_models.TaskCreate(title=title), user_id)
    return str(row["id"])


def _fake_generate(prompt: str, **kwargs) -> str:
    return "Fake reply."


def _svc(tmp_path, sink=None):
    store = ConversationStore(db_path=tmp_path / "conv.db")
    svc = ConversationService(store, generate_fn=_fake_generate, event_sink=sink)
    return svc, store


def _sink():
    events: list[dict] = []

    def sink(**kwargs):
        events.append(kwargs)

    return events, sink


def _nstore(tmp_path, name="narrative.db"):
    return NarrativeStore(db_path=tmp_path / name)


def _counting_gen(calls: list):
    def gen(prompt, **kwargs):
        calls.append(prompt)
        if "A thread already exists" in prompt:
            return EXTENSION_JSON
        return BIRTH_JSON

    return gen


def _turn_event(event_id, user, conversation_id, text, subject=None):
    payload = {"archetype_id": "mentor", "message_id": f"msg-{event_id}"}
    if subject is not None:
        payload["subject"] = subject
    return FellowshipEvent(
        id=event_id,
        kind="conversation_turn",
        user_id=user,
        entity_type="conversation",
        entity_id=conversation_id,
        evidence_text=text,
        summary="Conversation turn with the mentor voice.",
        payload=payload,
    )


def _subject(entity_type, entity_id, confidence, name="Orchard Gate"):
    return {
        "entity_id": entity_id,
        "entity_type": entity_type,
        "entity_display_name": name,
        "active_field": "unknown",
        "confidence": confidence,
    }


# -- T1: subjectless byte-identity ---------------------------------------------


@pytest.mark.parametrize("consent", [True, False])
def test_t1_subjectless_payload_byte_identical(tmp_path, ve_conn, consent):
    """No validated anchor ⇒ the emitted payload is exactly today's
    {archetype_id, message_id} shape, with consent on or off."""
    _set_consent(ve_conn, USER, consent)
    events, sink = _sink()
    svc, store = _svc(tmp_path, sink)
    result = svc.turn(USER, "mentor", "I need to plan my week")
    assert len(events) == 1
    payload = events[0]["payload"]
    expected = {
        "archetype_id": "mentor",
        "message_id": result.user_message["id"],
    }
    assert payload == expected
    assert json.dumps(payload, sort_keys=True) == json.dumps(
        expected, sort_keys=True
    )
    assert store.get_conversation_subject(USER, "skeleton") is None
    store.close()


def test_t1_contribution_only_subject_rides_nothing(tmp_path, ve_conn):
    """A correction with no anchor forms a contribution-only snapshot
    (conversation state) that names no entity — it rides nothing,
    even with consent on."""
    _set_consent(ve_conn, USER, True)
    events, sink = _sink()
    svc, store = _svc(tmp_path, sink)
    svc.turn(USER, "mentor", "No, actually the meeting is on Thursday")
    snapshot = store.get_conversation_subject(USER, "skeleton")
    assert snapshot is not None and not snapshot.get("entity_id")
    assert "subject" not in events[0]["payload"]
    store.close()


# -- T2: owner isolation ---------------------------------------------------------


def test_t2_owner_isolation(tmp_path, ve_conn):
    """User B's conversation (same conversation_id) hinting at A's
    project forms no anchor; A's snapshot is unreachable from B; a
    legacy NULL-owned project anchors for nobody."""
    project_a = _project(USER)
    # Legacy row: user_id NULL (pre-ownership) — fail-closed for all.
    legacy = _project(USER, "Old Project")
    ve_conn.execute(
        "UPDATE projects SET user_id = NULL WHERE id = ?", (legacy,)
    )
    ve_conn.commit()
    _set_consent(ve_conn, USER, True)
    _set_consent(ve_conn, OTHER, True)
    events, sink = _sink()
    svc, store = _svc(tmp_path, sink)

    svc.turn(
        OTHER, "mentor", "Looking at the gate project",
        conversation_id="shared-id",
        context={"entity_type": "project", "entity_id": project_a},
    )
    assert store.get_conversation_subject(OTHER, "shared-id") is None
    assert "subject" not in events[-1]["payload"]

    svc.turn(
        USER, "mentor", "Looking at the gate project",
        conversation_id="shared-id",
        context={"entity_type": "project", "entity_id": project_a},
    )
    snapshot_a = store.get_conversation_subject(USER, "shared-id")
    assert snapshot_a is not None
    assert snapshot_a["entity_id"] == project_a
    # Keyed (user, conversation): B still has nothing under the same id.
    assert store.get_conversation_subject(OTHER, "shared-id") is None
    assert events[-1]["payload"]["subject"]["entity_id"] == project_a

    svc.turn(
        USER, "mentor", "Looking at the old project",
        conversation_id="legacy-conv",
        context={"entity_type": "project", "entity_id": legacy},
    )
    assert store.get_conversation_subject(USER, "legacy-conv") is None
    assert "subject" not in events[-1]["payload"]
    store.close()


def test_t2_derivation_is_per_user(tmp_path, ve_conn):
    """Derivation over A's anchor-carrying events lands in A's
    namespace only; B's view of the same store stays empty."""
    project_a = _project(USER)
    subject = _subject("project", project_a, "high")
    events_a = [
        _turn_event("a1", USER, "conv-a1", "Cultivation notes for the north beds.", subject),
        _turn_event("a2", USER, "conv-a2", "Stewardship of the tool library falls to Mara.", subject),
    ]
    nstore = _nstore(tmp_path)
    calls: list = []
    result = derive_batch(
        USER, [event_to_item(e) for e in events_a], nstore,
        generate_fn=_counting_gen(calls),
    )
    assert len(result.births) == 1
    assert nstore.threads_for(USER)
    assert nstore.threads_for(OTHER) == []
    # B's own subjectless events derive nothing for B.
    events_b = [
        _turn_event("b1", OTHER, "conv-b1", "Cultivation notes for the north beds."),
        _turn_event("b2", OTHER, "conv-b2", "Stewardship of the tool library falls to Mara."),
    ]
    result_b = derive_batch(
        OTHER, [event_to_item(e) for e in events_b], nstore,
        generate_fn=_counting_gen(calls),
    )
    assert result_b.births == [] and result_b.calls == 0
    assert nstore.threads_for(OTHER) == []


# -- T3: consent on/off carriage (Q4) --------------------------------------------


def test_t3_consent_gates_carriage_not_state(tmp_path, ve_conn):
    project = _project(USER)
    events, sink = _sink()
    svc, store = _svc(tmp_path, sink)
    hint = {"entity_type": "project", "entity_id": project}

    # Consent OFF: the snapshot is maintained; the event carries nothing.
    _set_consent(ve_conn, USER, False)
    svc.turn(USER, "mentor", "Opening the gate sheet", context=hint)
    snapshot = store.get_conversation_subject(USER, "skeleton")
    assert snapshot is not None and snapshot["entity_id"] == project
    assert "subject" not in events[-1]["payload"]

    # Consent ON mid-conversation: the first consented turn carries
    # the then-current snapshot (medium — navigation alone).
    _set_consent(ve_conn, USER, True)
    svc.turn(USER, "mentor", "Tell me more about the timeline")
    block = events[-1]["payload"]["subject"]
    assert block["entity_id"] == project
    assert block["entity_type"] == "project"
    assert block["confidence"] == "medium"
    assert block["entity_display_name"] == "Orchard Gate"
    # The contribution is never carried (the event holds the words).
    assert "last_user_contribution" not in block

    # Withdrawal: later events are subjectless again, from the next turn.
    _set_consent(ve_conn, USER, False)
    svc.turn(USER, "mentor", "And the budget side of it")
    assert "subject" not in events[-1]["payload"]
    # The snapshot itself is untouched by the withdrawal.
    assert store.get_conversation_subject(USER, "skeleton")["entity_id"] == project
    store.close()


# -- T4: navigation, correction, re-anchoring -------------------------------------


def test_t4_navigation_correction_reanchoring(tmp_path, ve_conn):
    project_p = _project(USER, "Orchard Gate")
    project_q = _project(USER, "Ferry Landing")
    _set_consent(ve_conn, USER, True)
    events, sink = _sink()
    svc, store = _svc(tmp_path, sink)

    svc.turn(
        USER, "mentor", "Let me look at where this stands",
        context={"entity_type": "project", "entity_id": project_p},
    )
    first = events[-1]["payload"]["subject"]
    assert first["entity_id"] == project_p and first["confidence"] == "medium"
    # Medium is preserved in the record but consumed by nothing.
    item = event_to_item(_turn_event("x1", USER, "skeleton", "t", first))
    assert item.anchor_ref is None

    svc.turn(USER, "mentor", "No, actually the gate hinges were replaced last week")
    second = events[-1]["payload"]["subject"]
    assert second["entity_id"] == project_p and second["confidence"] == "high"
    item = event_to_item(_turn_event("x2", USER, "skeleton", "t", second))
    assert item.anchor_ref == f"project:{project_p}"

    svc.turn(
        USER, "mentor", "Now the other undertaking",
        context={"entity_type": "project", "entity_id": project_q},
    )
    third = events[-1]["payload"]["subject"]
    assert third["entity_id"] == project_q and third["confidence"] == "medium"

    # Earlier events still carry what they carried (no rewriting).
    assert events[0]["payload"]["subject"]["entity_id"] == project_p
    assert events[0]["payload"]["subject"]["confidence"] == "medium"
    assert events[1]["payload"]["subject"]["confidence"] == "high"
    store.close()


def test_t4_task_anchor(tmp_path, ve_conn):
    task = _task(USER)
    _set_consent(ve_conn, USER, True)
    events, sink = _sink()
    svc, store = _svc(tmp_path, sink)
    svc.turn(
        USER, "mentor", "Looking at the hinge task",
        context={"entity_type": "task", "entity_id": task},
    )
    block = events[-1]["payload"]["subject"]
    assert block["entity_type"] == "task" and block["entity_id"] == task
    store.close()


# -- T5: historical provenance, no retrospective rewriting -------------------------


def _log_record(event):
    return {
        "id": event.id,
        "type": event.kind,
        "entity_type": event.entity_type,
        "entity_id": event.entity_id,
        "related_entity_id": None,
        "actor": event.user_id,
        "source": "fellowship",
        "detail": json.dumps(
            {
                "summary": event.summary,
                "evidence": event.evidence_text,
                "payload": event.payload,
            },
            ensure_ascii=False,
        ),
        "created_at": "2026-10-25T00:00:00+00:00",
    }


def test_t5_pre_carriage_events_derive_as_today(tmp_path):
    """Events logged before carriage existed (no subject key)
    reconstruct without one and derive exactly as today; the log
    record itself never gains a subject after the fact."""
    old = _turn_event(
        "old-1", USER, "conv-old", "Cultivation in the orchard, learning what ripens"
    )
    record = _log_record(old)
    rebuilt = reconstruct_event(record)
    assert rebuilt is not None
    assert "subject" not in rebuilt.payload
    item = event_to_item(rebuilt)
    assert item.anchor_ref is None
    assert item.entity_ref == "conversation:conv-old"

    nstore = _nstore(tmp_path)
    calls: list = []
    pair = [
        event_to_item(rebuilt),
        event_to_item(
            _turn_event(
                "old-2", USER, "conv-old",
                "Cultivation in the orchard, learning what ripens, again",
            )
        ),
    ]
    result = derive_batch(USER, pair, nstore, generate_fn=_counting_gen(calls))
    assert len(result.births) == 1
    # The record is untouched by having been derived from.
    assert "subject" not in json.loads(record["detail"])["payload"]
    rebuilt_again = reconstruct_event(record)
    assert "subject" not in rebuilt_again.payload


def test_t5_carried_subject_survives_log_round_trip(tmp_path, ve_conn):
    project = _project(USER)
    carried = _turn_event(
        "new-1", USER, "conv-new", "Words about the gate",
        _subject("project", project, "high"),
    )
    rebuilt = reconstruct_event(_log_record(carried))
    assert rebuilt is not None
    assert rebuilt.payload["subject"]["entity_id"] == project
    assert event_to_item(rebuilt).anchor_ref == f"project:{project}"


def test_t5_existing_annotations_survive_anchor_derivation(tmp_path, ve_conn):
    """Evidence rows annotated before this packet keep their
    annotations unchanged after anchor-linked derivation runs."""
    project = _project(USER)
    nstore = _nstore(tmp_path)
    calls: list = []
    base_events = [
        _turn_event("base-1", USER, "conv-base", "Cultivation in the orchard, learning what ripens"),
        _turn_event("base-2", USER, "conv-base", "Cultivation in the orchard, learning what ripens, again"),
    ]
    base = derive_batch(
        USER, [event_to_item(e) for e in base_events], nstore,
        generate_fn=_counting_gen(calls),
    )
    base_thread = base.births[0]
    before = {
        (r.ref_kind, r.ref_id): r.entity_ref
        for r in nstore.evidence_for(USER, base_thread)
    }
    assert before and all(v == "conversation:conv-base" for v in before.values())

    subject = _subject("project", project, "high")
    anchored = [
        _turn_event("anc-1", USER, "conv-a1", "Cultivation notes for the north beds.", subject),
        _turn_event("anc-2", USER, "conv-a2", "Stewardship of the tool library falls to Mara.", subject),
    ]
    derive_batch(
        USER, [event_to_item(e) for e in anchored], nstore,
        generate_fn=_counting_gen(calls),
    )
    after = {
        (r.ref_kind, r.ref_id): r.entity_ref
        for r in nstore.evidence_for(USER, base_thread)
    }
    assert after == before


# -- T6: concurrent subject updates -------------------------------------------------


def test_t6_concurrent_subject_updates(tmp_path):
    """Two barrier-synchronized updates to one conversation's
    snapshot: the final snapshot is one of the two sequential
    compositions, each update returns its own merge's product, and
    the stored JSON is never torn."""
    anchor_p = {
        "entity_id": "P", "entity_type": "project",
        "entity_display_name": "P", "active_field": "unknown",
        "last_user_contribution": "", "confidence": "medium",
    }
    anchor_q = dict(anchor_p, entity_id="Q", entity_display_name="Q")
    x_kwargs = dict(
        anchor=anchor_p,
        question="No, actually it is March",
        question_kind="user_correcting_model",
        output_contract="refine_and_continue",
    )
    y_kwargs = dict(
        anchor=anchor_q,
        question="quiet reflection on the matter",
        question_kind="reflective_inquiry",
        output_contract="reflective",
    )

    def sequential(order):
        store = ConversationStore(db_path=tmp_path / f"seq-{order}.db")
        returns = {}
        for name in order:
            returns[name] = store.update_conversation_subject(
                USER, "conv", **(x_kwargs if name == "x" else y_kwargs)
            )
        final = store.get_conversation_subject(USER, "conv")
        store.close()
        return returns, final

    returns_xy, final_xy = sequential("xy")
    returns_yx, final_yx = sequential("yx")
    # Each update's return is order-independent here by construction
    # (a differing anchor resets before the merge), which is what
    # makes the concurrent assertions exact rather than statistical.
    assert returns_xy["x"] == returns_yx["x"]
    assert returns_xy["y"] == returns_yx["y"]
    assert final_xy != final_yx  # the two compositions genuinely differ

    for round_no in range(8):
        store = ConversationStore(db_path=tmp_path / f"conc-{round_no}.db")
        store.ensure_conversation(USER, "conv")
        barrier = threading.Barrier(2)
        returns: dict = {}
        errors: list = []

        def run(name, kwargs):
            try:
                barrier.wait(timeout=10)
                returns[name] = store.update_conversation_subject(
                    USER, "conv", **kwargs
                )
            except Exception as exc:  # pragma: no cover - failure path
                errors.append(exc)

        threads = [
            threading.Thread(target=run, args=("x", x_kwargs)),
            threading.Thread(target=run, args=("y", y_kwargs)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert not errors
        assert returns["x"] == returns_xy["x"]
        assert returns["y"] == returns_xy["y"]
        final = store.get_conversation_subject(USER, "conv")
        assert final in (final_xy, final_yx)
        store.close()


# -- T7: Slice A / Slice B separation -----------------------------------------------


@pytest.mark.parametrize(
    "entity_type", ["person", "asset", "job", "initiative", "nonsense"]
)
def test_t7_non_project_task_hints_never_anchor(tmp_path, ve_conn, entity_type):
    ve_storage.create_person(ve_models.PersonCreate(name="Mara Ellison"), USER)
    ve_storage.create_asset(ve_models.AssetCreate(name="Ladder"), USER)
    _set_consent(ve_conn, USER, True)
    events, sink = _sink()
    svc, store = _svc(tmp_path, sink)
    svc.turn(
        USER, "mentor", "Looking at this record",
        context={"entity_type": entity_type, "entity_id": "whatever-1"},
    )
    assert store.get_conversation_subject(USER, "skeleton") is None
    assert "subject" not in events[-1]["payload"]
    store.close()


def test_t7_person_named_in_text_produces_no_person_machinery(tmp_path, ve_conn):
    """A turn whose text verbatim-names a VE person, inside a
    project-anchored conversation, produces no person annotation,
    no ve_entity evidence row, and no person subject key."""
    ve_storage.create_person(ve_models.PersonCreate(name="Mara Ellison"), USER)
    project = _project(USER)
    subject = _subject("project", project, "high")
    events = [
        _turn_event(
            "p1", USER, "conv-p1",
            "Mara Ellison called about cultivation at the gate", subject,
        ),
        _turn_event(
            "p2", USER, "conv-p2",
            "Stewardship of the tool library falls to Mara", subject,
        ),
    ]
    nstore = _nstore(tmp_path)
    calls: list = []
    result = derive_batch(
        USER, [event_to_item(e) for e in events], nstore,
        generate_fn=_counting_gen(calls),
    )
    assert len(result.births) == 1
    rows = nstore.evidence_for(USER, result.births[0])
    assert rows and all(r.ref_kind == "event" for r in rows)
    assert all(not (r.entity_ref or "").startswith("person:") for r in rows)
    key, precision = subject_key_for_thread(nstore, USER, _thread(nstore, result.births[0]))
    assert key is None or not key.startswith("person:")


def _thread(store, thread_id):
    for thread in store.threads_for(USER, limit=None):
        if thread.id == thread_id:
            return thread
    raise AssertionError("thread not found")


# -- T8: anchor is not referent (Correction 1) ---------------------------------------


def test_t8_anchor_is_not_referent(tmp_path, ve_conn):
    project = _project(USER)
    subject = _subject("project", project, "high")
    # Two conversations (the §4.9 case (i) shape): items from ONE
    # conversation would link by their shared conversation referent
    # first — the anchor reason is recorded when the anchor is the
    # link that joins them, across conversations.
    events = [
        _turn_event("c1a", USER, "conv-c1a", "Cultivation notes for the north beds.", subject),
        _turn_event("c1b", USER, "conv-c1b", "Stewardship of the tool library falls to Mara.", subject),
    ]
    items = [event_to_item(e) for e in events]
    clusters = cluster_items(items)
    cluster = next(c for c in clusters if len(c.items) == 2)
    # The recorded cohesion basis is the anchor reason, never "shared entity".
    assert f"shared conversation anchor project:{project}" in cluster.cohesion
    assert not any(r.startswith("shared entity") for r in cluster.cohesion)
    # The offer subject key comes from referents only (the dominant
    # conversation referent — never the anchor project at PRECISE).
    key, precision = subject_key_for_cluster(cluster)
    assert (key, precision) == ("conversation:conv-c1a", "precise")

    nstore = _nstore(tmp_path)
    calls: list = []
    result = derive_batch(USER, items, nstore, generate_fn=_counting_gen(calls))
    assert len(result.births) == 1
    thread = _thread(nstore, result.births[0])
    rows = nstore.evidence_for(USER, thread.id)
    # Each evidence row annotates its own conversation referent,
    # never the anchor project.
    assert {r.entity_ref for r in rows} == {
        "conversation:conv-c1a", "conversation:conv-c1b",
    }
    key, precision = subject_key_for_thread(nstore, USER, thread)
    assert (key, precision) == ("conversation:conv-c1a", "precise")

    # The change detectors see the events exactly as if no subject
    # had been carried: identical outcomes with subjects stripped.
    with_subjects = [
        (c.kind, c.thread_id)
        for e in events
        for c in detect_changes_for_event(nstore, USER, e)
    ]
    stripped = [
        _turn_event(e.id, USER, e.entity_id, e.evidence_text) for e in events
    ]
    without_subjects = [
        (c.kind, c.thread_id)
        for e in stripped
        for c in detect_changes_for_event(nstore, USER, e)
    ]
    assert with_subjects == without_subjects


# -- T10: medium is not consumed -------------------------------------------------------


def test_t10_medium_is_not_consumed(tmp_path, ve_conn):
    project = _project(USER)
    medium = _subject("project", project, "medium")
    events = [
        _turn_event("m1", USER, "conv-m1", "Cultivation notes for the north beds.", medium),
        _turn_event("m2", USER, "conv-m2", "Stewardship of the tool library falls to Mara.", medium),
    ]
    items = [event_to_item(e) for e in events]
    assert all(i.anchor_ref is None for i in items)
    clusters = cluster_items(items)
    assert all(len(c.items) == 1 for c in clusters)
    nstore = _nstore(tmp_path)
    calls: list = []
    result = derive_batch(USER, items, nstore, generate_fn=_counting_gen(calls))
    assert result.calls == 0 and result.births == []
    # A medium beside a high on the same project still links nothing.
    high = _subject("project", project, "high")
    mixed = [
        event_to_item(events[0]),
        event_to_item(_turn_event("m3", USER, "conv-m3", "Stewardship of the tool library falls to Mara.", high)),
    ]
    assert all(len(c.items) == 1 for c in cluster_items(mixed))


# -- T9: generation impact (Correction 2, contract §4.9) ------------------------------
#
# The pinned corpus. Texts are token-audited by the fixture itself:
# the only designed token links are (c3a, c3b) and (ve, c4); every
# other pair shares at most one distinctive token. Focus terms
# ("cultivation", "stewardship", "courage") put the designed
# clusters on a seat's ground for jurisdiction candidacy.
#
# Delivery note (measured, on the record): the corpus is delivered
# in two batches — the turn cases, then the VE-replay case — because
# cases (i) and (v) deliberately share project P. Delivered as ONE
# batch, Arm C's anchor rule also merges case (i)'s cluster into
# case (v)'s extension cluster; that composition is pinned
# separately in test_t9_single_batch_composition so the effect is
# measured, not hidden: net calls are unchanged and the extension's
# new-items set grows by exactly the anchor-linked items.

_T9_TEXTS = {
    "c1a": "Cultivation notes: the north beds need turning before frost.",
    "c1b": "Stewardship of the tool library falls to Mara this winter.",
    "c2": "The ferry schedule changed again on Tuesday morning.",
    "c3a": "Pruning the old apple row took longer than anyone expected.",
    "c3b": "Pruning the apple row again, second pass before the rain — courage for the ladder work.",
    "solo": "A quiet note about bus timetables and parking fines.",
    "ve": "Task completed for the orchard gate repair and hinge replacement.",
    "c4": "The orchard gate repair finished; hinge replacement verified on site.",
}


def _t9_events(project_p, project_q, *, subjects: bool):
    subj_p = _subject("project", project_p, "high") if subjects else None
    subj_p_med = _subject("project", project_p, "medium") if subjects else None
    subj_q = _subject("project", project_q, "high", "Ferry Landing") if subjects else None
    turn = {
        "c1a": _turn_event("c1a", USER, "conv-c1a", _T9_TEXTS["c1a"], subj_p),
        "c1b": _turn_event("c1b", USER, "conv-c1b", _T9_TEXTS["c1b"], subj_p),
        "c2": _turn_event("c2", USER, "conv-c2", _T9_TEXTS["c2"], subj_p_med),
        "c3a": _turn_event("c3a", USER, "conv-c3", _T9_TEXTS["c3a"], subj_q),
        "c3b": _turn_event("c3b", USER, "conv-c3", _T9_TEXTS["c3b"], subj_q),
        "solo": _turn_event("solo", USER, "conv-c5", _T9_TEXTS["solo"]),
        "c4": _turn_event("c4", USER, "conv-c4", _T9_TEXTS["c4"], subj_p),
    }
    ve = FellowshipEvent(
        id="ve",
        kind="task_completed",
        user_id=USER,
        entity_type="project",
        entity_id=project_p,
        evidence_text=_T9_TEXTS["ve"],
        summary="Task completed.",
        payload={},
    )
    return turn, ve


def _t9_seed_store(tmp_path, name, ve_event, project_p):
    """The fixed initial state: one live thread whose evidence is
    referent-annotated project:P via the VE event (not a turn)."""
    nstore = _nstore(tmp_path, name)
    thread = nstore.create_thread(
        USER,
        origin="steward_proposal",
        title="Orchard gate",
        evidence_refs=[
            SourceRef(kind="event", ref_id=ve_event.id, evidence_kind="quote")
        ],
    )
    nstore.annotate_evidence_entities(
        USER, thread.id, {("event", ve_event.id): f"project:{project_p}"}
    )
    return nstore, thread.id


def _t9_snapshot(nstore):
    """Landed state keyed by evidence set (thread ids are per-store
    uuids and must not leak into cross-arm comparisons)."""
    snap = {}
    for thread in nstore.threads_for(USER, limit=None):
        rows = nstore.evidence_for(USER, thread.id)
        key = frozenset((r.ref_kind, r.ref_id) for r in rows)
        snap[key] = {
            "title": thread.title,
            "annotations": sorted(
                (r.ref_kind, r.ref_id, r.entity_ref) for r in rows
            ),
        }
    return snap


def _run_t9_arm(tmp_path, arm, project_p, project_q, monkeypatch, gen_mode):
    """One arm of the §4.9 comparison. Returns (result, snapshot, calls)."""
    if arm == "B":
        monkeypatch.setenv("ZENAF_STEWARD_ANCHOR_CHANNEL", "0")
    else:
        monkeypatch.delenv("ZENAF_STEWARD_ANCHOR_CHANNEL", raising=False)
    turn, ve = _t9_events(project_p, project_q, subjects=(arm != "A"))
    nstore, _seed_id = _t9_seed_store(
        tmp_path, f"t9-{arm}-{gen_mode}.db", ve, project_p
    )
    calls: list = []
    gen = _counting_gen(calls) if gen_mode == "gen" else None
    batch1 = [turn[k] for k in ("c1a", "c1b", "c2", "c3a", "c3b", "solo")]
    batch2 = [ve, turn["c4"]]
    r1 = derive_batch(USER, [event_to_item(e) for e in batch1], nstore, generate_fn=gen)
    r2 = derive_batch(USER, [event_to_item(e) for e in batch2], nstore, generate_fn=gen)
    merged = {
        "calls": r1.calls + r2.calls,
        "births": r1.births + r2.births,
        "readings": r1.readings + r2.readings,
        "declines": r1.declines + r2.declines,
        "deferred": r1.deferred + r2.deferred,
        "skipped": sorted(r1.skipped + r2.skipped),
    }
    return merged, _t9_snapshot(nstore), len(calls)


def test_t9_generation_impact_three_arms(tmp_path, ve_conn, monkeypatch):
    project_p = _project(USER, "Orchard Gate")
    project_q = _project(USER, "Ferry Landing")

    # Corpus self-audit: the designed token links are the only ones.
    from local_ai.narrative.derivation import _tokens

    designed = {frozenset(("c3a", "c3b")), frozenset(("ve", "c4"))}
    keys = list(_T9_TEXTS)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            shared = _tokens(_T9_TEXTS[a]) & _tokens(_T9_TEXTS[b])
            if frozenset((a, b)) in designed:
                assert len(shared) >= 2, (a, b, shared)
            else:
                assert len(shared) <= 1, (a, b, shared)

    arm_a, snap_a, fake_a = _run_t9_arm(tmp_path, "A", project_p, project_q, monkeypatch, "gen")
    arm_b, snap_b, fake_b = _run_t9_arm(tmp_path, "B", project_p, project_q, monkeypatch, "gen")
    arm_c, snap_c, fake_c = _run_t9_arm(tmp_path, "C", project_p, project_q, monkeypatch, "gen")

    # Arm B equals Arm A exactly — same counts, same landed state.
    assert arm_b["calls"] == arm_a["calls"] == 2
    assert len(arm_b["births"]) == len(arm_a["births"]) == 1
    assert len(arm_b["readings"]) == len(arm_a["readings"])
    assert len(arm_b["deferred"]) == len(arm_a["deferred"])
    assert arm_b["declines"] == arm_a["declines"]
    assert fake_a == fake_b == 2
    assert snap_b == snap_a

    # Arm C: exactly +1 generation over B — the case (i) anchor birth.
    assert arm_c["calls"] == 3 and fake_c == 3
    assert len(arm_c["births"]) == len(arm_b["births"]) + 1
    extra_keys = [k for k in snap_c if k not in snap_b]
    assert extra_keys == [frozenset({("event", "c1a"), ("event", "c1b")})]
    # The extra birth is anchor-attributable, mechanically: strip the
    # anchor refs and the cluster that produced it falls apart.
    turn, _ve = _t9_events(project_p, project_q, subjects=True)
    monkeypatch.delenv("ZENAF_STEWARD_ANCHOR_CHANNEL", raising=False)
    items = [event_to_item(turn[k]) for k in ("c1a", "c1b")]
    assert any(len(c.items) == 2 for c in cluster_items(items))
    monkeypatch.setenv("ZENAF_STEWARD_ANCHOR_CHANNEL", "0")
    items_off = [event_to_item(turn[k]) for k in ("c1a", "c1b")]
    assert all(len(c.items) == 1 for c in cluster_items(items_off))
    monkeypatch.delenv("ZENAF_STEWARD_ANCHOR_CHANNEL", raising=False)

    # The gen=None arm obeys the same rule on deferred rows.
    def_a, _, _ = _run_t9_arm(tmp_path, "A", project_p, project_q, monkeypatch, "none")
    def_b, _, _ = _run_t9_arm(tmp_path, "B", project_p, project_q, monkeypatch, "none")
    def_c, _, _ = _run_t9_arm(tmp_path, "C", project_p, project_q, monkeypatch, "none")
    assert len(def_b["deferred"]) == len(def_a["deferred"]) == 2
    assert len(def_c["deferred"]) == len(def_b["deferred"]) + 1
    assert def_a["calls"] == def_b["calls"] == def_c["calls"] == 0


def test_t9_single_batch_composition(tmp_path, ve_conn, monkeypatch):
    """The whole corpus in ONE batch (see the delivery note above):
    Arm B still equals Arm A exactly; in Arm C the case (i) items
    join case (v)'s extension cluster through the shared anchor —
    net generation count unchanged, and the extension's landed
    evidence grows by exactly the anchor-linked items."""
    project_p = _project(USER, "Orchard Gate")
    project_q = _project(USER, "Ferry Landing")
    outcomes = {}
    for arm in ("A", "B", "C"):
        if arm == "B":
            monkeypatch.setenv("ZENAF_STEWARD_ANCHOR_CHANNEL", "0")
        else:
            monkeypatch.delenv("ZENAF_STEWARD_ANCHOR_CHANNEL", raising=False)
        turn, ve = _t9_events(project_p, project_q, subjects=(arm != "A"))
        nstore, seed_id = _t9_seed_store(
            tmp_path, f"t9-single-{arm}.db", ve, project_p
        )
        calls: list = []
        batch = [turn[k] for k in ("c1a", "c1b", "c2", "c3a", "c3b", "solo", "c4")]
        batch.insert(6, ve)
        result = derive_batch(
            USER, [event_to_item(e) for e in batch], nstore,
            generate_fn=_counting_gen(calls),
        )
        seed_rows = {
            r.ref_id for r in nstore.evidence_for(USER, seed_id)
        }
        outcomes[arm] = (result, seed_rows)
    monkeypatch.delenv("ZENAF_STEWARD_ANCHOR_CHANNEL", raising=False)

    res_a, seed_a = outcomes["A"]
    res_b, seed_b = outcomes["B"]
    res_c, seed_c = outcomes["C"]
    assert res_b.calls == res_a.calls == 2
    assert seed_b == seed_a == {"ve", "c4"}
    # Arm C: no extra generation; the seed thread's evidence grew by
    # exactly the anchor-linked case (i) items, nothing else.
    assert res_c.calls == res_b.calls == 2
    assert seed_c == seed_b | {"c1a", "c1b"}


# -- Headline scenario (corrected mechanics) -----------------------------------------


def test_headline_scenario(tmp_path, ve_conn, monkeypatch):
    """A project anchored via a sheet-hinted Talk turn (medium;
    nothing consumed); a correction raises the anchor to high; a
    second conversation anchored high to the same project joins the
    first into one proposed thread whose evidence holds both
    conversations' event rows — each annotated with its own
    conversation referent, both source references distinct and
    cited. (Within a conversation, turns cohere by their shared
    conversation referent, as they always have; the anchor link is
    what joins the two conversations — proven by the channel-off
    contrast at the end, where the same items birth two threads.)"""
    project = _project(USER)
    _set_consent(ve_conn, USER, True)
    events, sink = _sink()
    svc, store = _svc(tmp_path, sink)
    hint = {"entity_type": "project", "entity_id": project}

    svc.turn(USER, "mentor", "Let me look at where this stands today",
             conversation_id="conv-1", context=hint)
    svc.turn(USER, "mentor", "No, actually the cultivation gate hinges were replaced last week",
             conversation_id="conv-1")
    svc.turn(USER, "mentor", "Opening the sheet to check the current state",
             conversation_id="conv-2", context=hint)
    svc.turn(USER, "mentor", "No, actually the stewardship notes already cover the latches",
             conversation_id="conv-2")
    store.close()

    assert events[0]["payload"]["subject"]["confidence"] == "medium"
    assert events[1]["payload"]["subject"]["confidence"] == "high"
    assert events[3]["payload"]["subject"]["confidence"] == "high"

    fellowship_events = [
        FellowshipEvent(
            id=f"evt-{i}",
            kind=kw["kind"],
            user_id=kw["user_id"],
            entity_type=kw["entity_type"],
            entity_id=kw["entity_id"],
            evidence_text=kw["evidence_text"],
            summary=kw["summary"],
            payload=kw["payload"],
        )
        for i, kw in enumerate(events)
    ]
    items = [event_to_item(e) for e in fellowship_events]
    # Only the two high turns carry an anchor; mediums populate none.
    assert [i.anchor_ref for i in items] == [
        None, f"project:{project}", None, f"project:{project}",
    ]
    clusters = cluster_items(items)
    assert len(clusters) == 1 and len(clusters[0].items) == 4
    # The pairwise link between the two conversations' high turns is
    # the anchor link. (The cluster's cohesion summary is not
    # asserted here: cluster_items keys reasons by union-find root
    # at pair time, so reasons recorded under a root that later
    # merges away are dropped from the summary — pre-existing
    # bookkeeping behavior, visible in this four-item merge, and
    # out of this packet's scope. The two-item case (i) cluster
    # records the anchor reason exactly; see T8.)
    from local_ai.narrative.derivation import _linked

    assert _linked(items[1], items[3]) == (
        f"shared conversation anchor project:{project}"
    )

    nstore = _nstore(tmp_path)
    calls: list = []
    result = derive_batch(USER, items, nstore, generate_fn=_counting_gen(calls))
    assert result.calls == 1 and len(result.births) == 1
    thread = _thread(nstore, result.births[0])
    rows = nstore.evidence_for(USER, thread.id)
    assert {r.ref_id for r in rows} == {"evt-0", "evt-1", "evt-2", "evt-3"}
    assert {r.ref_id: r.entity_ref for r in rows} == {
        "evt-0": "conversation:conv-1",
        "evt-1": "conversation:conv-1",
        "evt-2": "conversation:conv-2",
        "evt-3": "conversation:conv-2",
    }

    # Contrast: with the anchor channel off, the same items form two
    # per-conversation clusters and spend two births — the anchor
    # link is what joined the conversations into one story.
    monkeypatch.setenv("ZENAF_STEWARD_ANCHOR_CHANNEL", "0")
    items_off = [event_to_item(e) for e in fellowship_events]
    assert len(cluster_items(items_off)) == 2
    nstore_off = _nstore(tmp_path, "narrative-off.db")
    calls_off: list = []
    result_off = derive_batch(
        USER, items_off, nstore_off, generate_fn=_counting_gen(calls_off)
    )
    assert result_off.calls == 2 and len(result_off.births) == 2


# -- Rollback positions (§5) ------------------------------------------------------------


def test_rollback_carriage_switch(tmp_path, ve_conn, monkeypatch):
    """Carriage off ⇒ payloads return to exactly today's shape
    regardless of consent; snapshot maintenance (working state)
    continues — the switch governs carriage, not state."""
    project = _project(USER)
    _set_consent(ve_conn, USER, True)
    monkeypatch.setenv("ZENAF_TALK_SUBJECT_CARRIAGE", "0")
    events, sink = _sink()
    svc, store = _svc(tmp_path, sink)
    svc.turn(
        USER, "mentor", "Opening the gate sheet",
        context={"entity_type": "project", "entity_id": project},
    )
    assert "subject" not in events[-1]["payload"]
    snapshot = store.get_conversation_subject(USER, "skeleton")
    assert snapshot is not None and snapshot["entity_id"] == project
    store.close()


def test_rollback_anchor_channel_switch(tmp_path, ve_conn, monkeypatch):
    """Anchor channel off ⇒ carried subjects populate no anchor_ref
    and form no anchor links (the §4.9 Arm B position)."""
    project = _project(USER)
    subject = _subject("project", project, "high")
    event = _turn_event("r1", USER, "conv-r1", "Cultivation notes.", subject)
    monkeypatch.setenv("ZENAF_STEWARD_ANCHOR_CHANNEL", "0")
    assert event_to_item(event).anchor_ref is None
    monkeypatch.delenv("ZENAF_STEWARD_ANCHOR_CHANNEL")
    assert event_to_item(event).anchor_ref == f"project:{project}"
