"""V1 noting capture — the steward-store side: encounter scope, held
material and its hard bound, seat-authored readings and their
supersession lineage, objection evidence, and erasure membership.

Drives ``NotingCaptureWriter`` directly against a temp NarrativeStore
with a stub event resolver — no model calls, no conversation service.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from local_ai.narrative.noting import HELD_NOTE_BOUND_DAYS, NotingCaptureWriter
from local_ai.narrative.store import _ERASURE_USER_TABLES, NarrativeStore

USER = "u-noting-store"
CONVO = "store-convo"
SEAT = "champion"


@pytest.fixture()
def store(tmp_path):
    return NarrativeStore(tmp_path / "narrative.db")


@pytest.fixture()
def writer(store):
    return NotingCaptureWriter(
        store, event_resolver=lambda u, c, m: f"evt-{m}"
    )


def capture(writer, *, notes, user_msg="m-user-1", reply_msg="m-reply-1",
            event="evt-m-user-1", convo=CONVO):
    return writer.capture_turn(
        user_id=USER,
        conversation_id=convo,
        archetype_id=SEAT,
        notes=notes,
        user_message_id=user_msg,
        reply_message_id=reply_msg,
        turn_event_id=event,
    )


def test_encounter_opens_at_first_write_with_span_start(store, writer):
    summary = capture(writer, notes=[])
    scope = store.open_encounter_for(USER, CONVO, SEAT)
    assert scope is not None
    assert scope["thread_id"] == summary["encounter_thread_id"]
    assert scope["state"] == "open"
    assert scope["span_start_message_id"] == "m-user-1"
    assert scope["span_end_message_id"] is None
    # The visitor's turn is cited as Tier E quote evidence.
    evidence = store.evidence_for(USER, scope["thread_id"])
    assert [(e.ref_kind, e.ref_id, e.evidence_kind) for e in evidence] == [
        ("event", "evt-m-user-1", "quote")
    ]


def test_encounter_reused_across_turns_of_one_sitting(store, writer):
    first = capture(writer, notes=[])
    second = capture(
        writer, notes=[], user_msg="m-user-2", reply_msg="m-reply-2",
        event="evt-m-user-2",
    )
    assert first["encounter_thread_id"] == second["encounter_thread_id"]
    evidence = store.evidence_for(USER, first["encounter_thread_id"])
    assert [e.ref_id for e in evidence] == ["evt-m-user-1", "evt-m-user-2"]


def test_close_encounter_fixes_span_end_and_next_capture_reopens(store, writer):
    capture(writer, notes=[])
    closed = writer.close_encounter(
        user_id=USER, conversation_id=CONVO, archetype_id=SEAT,
        span_end_message_id="m-user-9",
    )
    assert closed["state"] == "closed"
    assert closed["span_end_message_id"] == "m-user-9"
    assert store.open_encounter_for(USER, CONVO, SEAT) is None
    capture(writer, notes=[], user_msg="m-user-10", reply_msg="m-reply-10",
            event="evt-m-user-10")
    reopened = store.open_encounter_for(USER, CONVO, SEAT)
    assert reopened is not None
    assert reopened["thread_id"] != closed["thread_id"]
    assert reopened["span_start_message_id"] == "m-user-10"


def test_recognition_lands_held_and_as_seat_authored_reading(store, writer):
    summary = capture(
        writer,
        notes=[{"kind": "recognition", "statement": "The visitor is circling a decision"}],
    )
    held = store.held_notes_for(USER)
    assert len(held) == 1
    note = held[0]
    assert note["kind"] == "recognition"
    assert note["statement"] == "The visitor is circling a decision"
    assert note["author"] == SEAT
    assert note["status"] == "held"
    assert note["source_user_message_id"] == "m-user-1"
    assert note["source_reply_message_id"] == "m-reply-1"
    # The hard bound rides the record: ~HELD_NOTE_BOUND_DAYS out.
    created = datetime.fromisoformat(note["created_at"])
    expires = datetime.fromisoformat(note["expires_at"])
    assert timedelta(days=HELD_NOTE_BOUND_DAYS - 1) < (expires - created)
    assert (expires - created) <= timedelta(days=HELD_NOTE_BOUND_DAYS)

    readings = store.readings_for(USER, summary["encounter_thread_id"])
    assert len(readings) == 1
    reading = readings[0]
    assert reading.author == SEAT
    assert reading.status == "proposed"
    assert reading.reading["recognition"] == "The visitor is circling a decision"
    assert note["reading_id"] == reading.id
    assert summary["reading_ids"] == [reading.id]


def test_later_recognition_supersedes_through_change_machinery(store, writer):
    capture(
        writer,
        notes=[{"kind": "recognition", "statement": "First recognition"}],
    )
    summary2 = capture(
        writer,
        notes=[{"kind": "recognition", "statement": "Revised recognition"}],
        user_msg="m-user-2", reply_msg="m-reply-2", event="evt-m-user-2",
    )
    thread_id = summary2["encounter_thread_id"]
    readings = store.readings_for(USER, thread_id)
    assert [r.reading["recognition"] for r in readings] == [
        "First recognition",
        "Revised recognition",
    ]
    # Never edited: the first reading stands as written, still proposed.
    assert all(r.status == "proposed" for r in readings)
    changes = store.changes_for(USER, thread_id)
    assert len(changes) == 1
    change = changes[0]
    assert change.kind == "extended"
    assert change.prior_reading_id == readings[0].id
    assert summary2["change_ids"] == [change.id]


def test_objection_becomes_tier_e_evidence_on_thread(store, writer):
    summary = capture(
        writer, notes=[{"kind": "objection", "message_id": "m-user-0"}],
    )
    held = store.held_notes_for(USER)
    assert len(held) == 1
    assert held[0]["kind"] == "objection"
    assert held[0]["cited_message_id"] == "m-user-0"
    assert held[0]["evidence_ref_kind"] == "event"
    assert held[0]["evidence_ref_id"] == "evt-m-user-0"
    evidence_ids = {
        e.ref_id for e in store.evidence_for(USER, summary["encounter_thread_id"])
    }
    assert "evt-m-user-0" in evidence_ids


def test_objection_unresolvable_event_keeps_held_record_only(store):
    writer = NotingCaptureWriter(store, event_resolver=lambda u, c, m: None)
    summary = capture(
        writer, notes=[{"kind": "objection", "message_id": "m-gone"}],
        event=None,
    )
    held = store.held_notes_for(USER)
    assert len(held) == 1
    assert held[0]["cited_message_id"] == "m-gone"
    assert held[0]["evidence_ref_id"] is None
    assert store.evidence_for(USER, summary["encounter_thread_id"]) == []


def test_held_material_expires_unexamined(store, writer):
    capture(
        writer,
        notes=[{"kind": "recognition", "statement": "Will expire"}],
    )
    thread_id = store.open_encounter_for(USER, CONVO, SEAT)["thread_id"]
    # A second held note already past its bound, written directly.
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    store.add_held_note(
        USER, thread_id, conversation_id=CONVO, archetype_id=SEAT,
        kind="recognition", statement="Already past bound",
        author=SEAT, expires_at=past,
    )
    # The read path excludes the past-bound row before any sweep.
    live = store.held_notes_for(USER)
    assert [h["statement"] for h in live] == ["Will expire"]
    # The sweep flips it; include_expired (audit reads) still sees it.
    assert store.expire_held_notes(USER) == 1
    all_rows = store.held_notes_for(USER, include_expired=True)
    by_statement = {h["statement"]: h["status"] for h in all_rows}
    assert by_statement == {"Will expire": "held", "Already past bound": "expired"}


def test_held_note_requires_its_bound(store, writer):
    capture(writer, notes=[])
    thread_id = store.open_encounter_for(USER, CONVO, SEAT)["thread_id"]
    with pytest.raises(ValueError):
        store.add_held_note(
            USER, thread_id, conversation_id=CONVO, archetype_id=SEAT,
            kind="recognition", statement="No bound", author=SEAT,
            expires_at="",
        )


def test_new_tables_in_erasure_enumeration_and_erased(store, writer):
    assert "encounter_scopes" in _ERASURE_USER_TABLES
    assert "held_notes" in _ERASURE_USER_TABLES
    capture(
        writer,
        notes=[{"kind": "recognition", "statement": "Erase me"}],
    )
    before = store.erasure_recount(USER)
    assert before["held_notes"] == 1
    assert before["encounter_scopes"] == 1
    store.erase_user_material(USER)
    after = store.erasure_recount(USER)
    assert after["held_notes"] == 0
    assert after["encounter_scopes"] == 0


def test_writer_is_seat_general(store):
    """The same writer serves any archetype: a guardian encounter is
    keyed, held, and authored under 'guardian' with no code change."""
    writer = NotingCaptureWriter(
        store, event_resolver=lambda u, c, m: f"evt-{m}"
    )
    summary = writer.capture_turn(
        user_id=USER, conversation_id=CONVO, archetype_id="guardian",
        notes=[{"kind": "recognition", "statement": "A guardian recognition"}],
        user_message_id="m-user-1", reply_message_id="m-reply-1",
        turn_event_id="evt-m-user-1",
    )
    scope = store.open_encounter_for(USER, CONVO, "guardian")
    assert scope is not None
    readings = store.readings_for(USER, summary["encounter_thread_id"])
    assert [r.author for r in readings] == ["guardian"]
