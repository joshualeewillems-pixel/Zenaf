"""Steward D1 candidate mentions — CAPTURE-ONLY first scope
(packet Rev 1 §§11/12/13).

Deterministic, hermetic: tmp stores, a tmp VE database behind the
storage module's connection seam, generate_fn always a stub.
Zero model calls.

Coverage map (packet §12 scope tags): the [capture]-tagged tests
T1, T3, T4, T9, T13, T14, and the capture halves of T2 (no
promotion by repetition), T6 (the dismissal rail's capture-side
gate), T10 (seat-echo exclusion), T11 (no auto-resolution of the
registered overlap), T12 (generation impact), T15 (holding-pool
counting). The [delivery]-tagged tests (T5 ask lifecycle, T7
correction acts, T8 confirmation/intent) are pinned for the
delivery scope's separate review and are NOT exercisable here —
no ask, delivery, or correction machinery is built in this
scope. §5.3's routing (sole claimant / holding pool / alias) is
exercised at the store level against fixture-arranged state,
since the user acts that produce multi-claimant state belong to
the delivery scope.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from local_ai.fellowship.events import FellowshipEvent
from local_ai.fellowship.observations import ObservationStore
from local_ai.identity import service as identity_service
from local_ai.identity.service import grant_scope
from local_ai.identity.store import IdentityStore
from local_ai.narrative import consent as consent_mod
from local_ai.narrative.candidates import (
    capture_event_mentions,
    extract_candidate_forms,
)
from local_ai.narrative.derivation import StewardPipeline
from local_ai.narrative.eligibility import (
    OperationRecords,
    ProvenanceResolver,
    audit_narrative_store,
)
from local_ai.narrative.store import ErasureBarrierRefusal, NarrativeStore
from local_ai.narrative.sweep import run_sweep_for_user
from local_ai.presence_ingest.store import PresenceStore
from local_ai.vision_execution import models as ve_models
from local_ai.vision_execution import storage as ve_storage
from local_ai.vision_execution.storage import init_db, open_sqlite_with_ve_pragmas

USER = "d1-user"
OTHER = "d1-other"
PRE = "2026-11-14T00:00:00+00:00"
def _future_day(days: int) -> str:
    """Midnight UTC `days` after today. POST/POST2 must sit strictly
    after the erasure boundary the live delete flow stamps from the
    real clock, so they are computed at import instead of pinned —
    a pinned "future" date becomes a clock bomb once real time
    passes it (the 2026-11-16 pin failed every run from that date
    on). PRE stays pinned: it is strictly before any boundary the
    real clock can stamp, and before test_t9's inline audit
    boundary (2026-11-15), which POST likewise stays after."""
    day = datetime.now(timezone.utc).date() + timedelta(days=days)
    return f"{day.isoformat()}T00:00:00+00:00"


POST = _future_day(2)
POST2 = _future_day(3)
T1_AT = "2026-11-15T10:00:00+00:00"
T2_AT = "2026-11-15T11:00:00+00:00"
T3_AT = "2026-11-15T12:00:00+00:00"

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
FOCUS_TEXT = "cultivation in the orchard, learning what ripens"


def _gen(payload=BIRTH_JSON):
    def gen(prompt, **kwargs):
        return payload

    return gen


def _turn(event_id, text, user=USER, conv="conv-1", created=T1_AT):
    return FellowshipEvent(
        id=event_id,
        kind="conversation_turn",
        user_id=user,
        entity_type="conversation",
        entity_id=conv,
        evidence_text=text,
        summary="Conversation turn with the conductor voice.",
        payload={},
        created_at=created,
    )


@pytest.fixture()
def store(tmp_path):
    return NarrativeStore(db_path=tmp_path / "narrative.db")


@pytest.fixture()
def ve_conn(tmp_path, monkeypatch):
    """A tmp VE database behind the storage module's connection
    seam — the pattern the Slice A suite uses: both the VE
    getters and the steward consent leaf resolve through
    ``ve_storage.get_connection``."""
    conn = open_sqlite_with_ve_pragmas(tmp_path / "ve.db")
    init_db(conn)
    monkeypatch.setattr(ve_storage, "get_connection", lambda: conn)
    yield conn
    conn.close()


def _set_consent(conn, user_id, *, on=True, version="permissions-v2"):
    conn.execute(
        "INSERT INTO user_permissions_settings "
        "(user_id, consent_given, consent_version, consent_at, "
        "permissions_json, updated_at) VALUES (?, 1, ?, NULL, ?, '') "
        "ON CONFLICT(user_id) DO UPDATE SET "
        "consent_version = excluded.consent_version, "
        "permissions_json = excluded.permissions_json",
        (user_id, version, json.dumps({"steward_derivation": on})),
    )
    conn.commit()


def _capture(store, event, **kwargs):
    kwargs.setdefault("disclosed_reader", lambda user_id: True)
    return capture_event_mentions(store, event, **kwargs)


def _sighting(form, surface, event_id, conv="conv-1", seen=T1_AT):
    return {
        "ref_kind": "event",
        "ref_id": event_id,
        "normalized_form": form,
        "surface_form": surface,
        "conversation_id": conv,
        "seen_at": seen,
    }


def _sql(store, statement, params=()):
    with store._lock:
        store._conn.execute(statement, params)
        store._conn.commit()


# ---------------------------------------------------------------------
# The rule family, fixture-pinned in both directions (packet §5.2)
# ---------------------------------------------------------------------

EXTRACT_CASES = [
    # (text, expected normalized forms)
    ("I talked with Ana Ruiz about the orchard.", ["ana ruiz"]),
    ("Ana Ruiz called me yesterday.", ["ana ruiz"]),
    ("Ana called me yesterday.", []),  # sentence-initial single, no frame
    ("I saw Ana yesterday and she was well.", []),  # bare single, no frame
    ("Ana's shop opens at nine.", ["ana"]),
    ("I told my Ana about it.", ["ana"]),
    ("My Ana is here.", ["ana"]),
    ("My Ana Ruiz is here.", ["ana ruiz"]),
    ("We met Ludwig van Beethoven fans.", ["ludwig van beethoven"]),
    ("The meeting is on Monday with Marcus.", []),  # bare single
    ("Marcus Chen and I went to Fort Worth.", ["marcus chen"]),
    ("She works with Mary-Jane Watson now.", ["mary-jane watson"]),
    ("I mentioned it to the Mentor already.", []),  # seat role name
    ("Rumi said the Skeptic agreed.", []),  # seat personal + role names
    ("He lives on Main Street near Ana Ruiz.", ["ana ruiz"]),
    ("Ana Ruiz and Marcus Chen discussed Ana Ruiz at length.",
     ["ana ruiz", "marcus chen"]),  # one mention per event per form
    ("NASA launched and Ana Ruiz watched.", ["ana ruiz"]),  # all-caps out
    ("In May, Ana Ruiz visited.", ["ana ruiz"]),  # comma breaks the span
    ("Did you see O'Brien at the store?", ["o'brien"]),  # compound frame
    ("Yesterday Ana Ruiz called.", ["ana ruiz"]),  # starter shed
    ("The Ana Ruiz I know lives here.", ["ana ruiz"]),
    ("Ruiz, Ana is the inverted form.", []),  # comma form unsupported
    ("I keep thinking about Ana Ruiz and Tomas Ruiz.",
     ["ana ruiz", "tomas ruiz"]),
    ("We drove to Lake Tahoe with Priya Nair.", ["priya nair"]),
    ("Priya Nair lives by the Salt River.", ["priya nair"]),
]


@pytest.mark.parametrize("text,expected", EXTRACT_CASES)
def test_extraction_fixtures(text, expected):
    forms = extract_candidate_forms(text)
    assert [normalized for _, normalized in forms] == expected


def test_extraction_surface_form_is_as_written():
    forms = extract_candidate_forms("I talked with Ana Ruiz about it.")
    assert forms == [("Ana Ruiz", "ana ruiz")]
    # The possessive suffix is the frame's punctuation, not the name.
    forms = extract_candidate_forms("Ana Ruiz's shop opens at nine.")
    assert forms == [("Ana Ruiz", "ana ruiz")]


# ---------------------------------------------------------------------
# T1 / T2 — provisional state; no promotion by repetition [capture]
# ---------------------------------------------------------------------


def test_t1_provisional_state_preservation(store, ve_conn):
    _set_consent(ve_conn, USER)
    for i in range(3):
        _capture(
            store,
            _turn(f"ev-{i}", "I talked with Ana Ruiz about the orchard.",
                  conv=f"conv-{i}", created=T1_AT),
        )
    candidates = store.candidates_for(USER)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.status == "candidate"
    assert candidate.ask_state == "not_asked"
    assert candidate.mention_count == 3
    assert candidate.promoted_person_ref is None
    assert candidate.promotion_intent == {}
    assert candidate.user_label is None
    assert candidate.surface_form == "Ana Ruiz"
    # No identity-shaped field exists to populate: the record's
    # full shape is the §3.1 field list and nothing else.
    assert set(candidate.to_dict()) == {
        "id", "user_id", "surface_form", "normalized_form", "status",
        "ask_state", "mention_count", "first_seen_at", "last_seen_at",
        "promoted_person_ref", "promotion_intent", "user_label",
        "created_at", "updated_at",
    }
    # The VE persons table is untouched (no person created or read
    # into existence by capture).
    rows = ve_conn.execute("SELECT COUNT(*) FROM persons").fetchone()[0]
    assert rows == 0


def test_t2_no_promotion_by_repetition(store):
    for i in range(10):
        _capture(
            store,
            _turn(f"ev-{i}", "Ana Ruiz came up again.",
                  conv=f"conv-{i % 3}", created=T1_AT),
        )
    candidate = store.candidates_for(USER)[0]
    assert candidate.mention_count == 10
    assert candidate.status == "candidate"
    assert candidate.promoted_person_ref is None
    conversations = {
        s.conversation_id
        for s in store.sightings_for_candidate(USER, candidate.id)
    }
    assert len(conversations) == 3


# ---------------------------------------------------------------------
# T3 — consent + disclosure gating [capture]
# ---------------------------------------------------------------------


def test_t3_disclosure_gate_unit(ve_conn):
    _set_consent(ve_conn, USER, on=True, version="permissions-v2")
    assert consent_mod.candidate_capture_disclosed(USER) is True
    # No grandfathering: the same consent under the pre-disclosure
    # wording version does not authorize capture.
    _set_consent(ve_conn, USER, on=True, version="permissions-v1")
    assert consent_mod.candidate_capture_disclosed(USER) is False
    _set_consent(ve_conn, USER, on=False, version="permissions-v2")
    assert consent_mod.candidate_capture_disclosed(USER) is False
    assert consent_mod.candidate_capture_disclosed("nobody") is False
    assert consent_mod.candidate_capture_disclosed(None) is False


def test_t3_capture_requires_disclosed_consent(store, ve_conn):
    event = _turn("ev-1", "I talked with Ana Ruiz.")
    # Flag on, pre-disclosure version: capture does not run.
    _set_consent(ve_conn, USER, on=True, version="permissions-v1")
    assert capture_event_mentions(store, event) is None
    assert store.candidates_for(USER) == []
    # Flag off entirely: capture does not run.
    _set_consent(ve_conn, USER, on=False, version="permissions-v2")
    assert capture_event_mentions(store, event) is None
    assert store.candidates_for(USER) == []
    # Flag on under the disclosed wording: capture runs.
    _set_consent(ve_conn, USER, on=True, version="permissions-v2")
    report = capture_event_mentions(store, event)
    assert report is not None and report["sightings_written"] == 1
    assert len(store.candidates_for(USER)) == 1


def test_capture_switch_off(store, monkeypatch):
    monkeypatch.setenv("ZENAF_CANDIDATE_CAPTURE", "0")
    assert _capture(store, _turn("ev-1", "I talked with Ana Ruiz.")) is None
    assert store.candidates_for(USER) == []


def test_t3_no_retroactive_capture(store, ve_conn, tmp_path):
    """Consent enabled after the corpus exists: the sweep's
    gate-closed consume-skip has already passed the events, and
    capture never backfills them (packet §8.1)."""
    _set_consent(ve_conn, USER, on=True, version="permissions-v2")
    log = tmp_path / "activity.log"
    records = [
        _log_record(_turn("ev-old-1", "I talked with Ana Ruiz."), T1_AT),
        _log_record(_turn("ev-old-2", "Ana Ruiz again.", conv="conv-2"),
                    T2_AT),
    ]
    _write_log(log, records)
    res = run_sweep_for_user(
        store, USER, log_path=log, generate_fn=_gen(),
        consent_reader=lambda user_id: False,
        operation_reader=lambda user_id: OperationRecords(),
    )
    assert res.events_gate_skipped == 2
    res2 = run_sweep_for_user(
        store, USER, log_path=log, generate_fn=_gen(),
        consent_reader=lambda user_id: True,
        operation_reader=lambda user_id: OperationRecords(),
    )
    assert res2.events_derived == 0
    assert store.candidates_for(USER) == []
    assert store.sightings_for(USER) == []


# ---------------------------------------------------------------------
# T4 — owner isolation [capture]
# ---------------------------------------------------------------------


def test_t4_owner_isolation(store):
    _capture(store, _turn("ev-a1", "I talked with Ana Ruiz.", user=USER))
    _capture(store, _turn("ev-b1", "I talked with Ana Ruiz.", user=OTHER))
    _capture(store, _turn("ev-a2", "Ana Ruiz again.", user=USER,
                          conv="conv-2", created=T2_AT))
    mine = store.candidates_for(USER)
    theirs = store.candidates_for(OTHER)
    assert len(mine) == 1 and mine[0].mention_count == 2
    assert len(theirs) == 1 and theirs[0].mention_count == 1
    # A candidate owned by another user reads as absent.
    assert store.get_candidate(OTHER, mine[0].id) is None
    assert store.get_candidate(USER, theirs[0].id) is None
    assert {s.ref_id for s in store.sightings_for(USER)} == {"ev-a1", "ev-a2"}
    assert {s.ref_id for s in store.sightings_for(OTHER)} == {"ev-b1"}


# ---------------------------------------------------------------------
# T6 (capture half) — the dismissal rail gates capture
# ---------------------------------------------------------------------


def test_t6_dismissal_gates_capture_and_survives_routine_clear(store):
    _capture(store, _turn("ev-1", "I talked with Ana Ruiz."))
    assert len(store.candidates_for(USER)) == 1
    store.record_dismissal(
        USER, kind="candidate_mention", signature="marcus chen"
    )
    report = _capture(store, _turn("ev-2", "Marcus Chen was there too."))
    assert report["forms_dismissed"] == 1
    assert [c.normalized_form for c in store.candidates_for(USER)] == [
        "ana ruiz"
    ]
    # Routine clear removes the candidates (steward material) and
    # preserves the dismissal (a visitor act).
    cleared = store.clear_user_material(USER, operation="routine_clear")
    assert cleared["deleted_candidate_count"] == 1
    assert store.candidates_for(USER) == []
    assert len(store.dismissals_for(USER)) == 1
    # Full delete removes the dismissal too (D2 §2.3's disposition).
    store.clear_user_material(USER, operation="full_delete")
    assert store.dismissals_for(USER) == []


# ---------------------------------------------------------------------
# T10 — seat-echo exclusion [capture]
# ---------------------------------------------------------------------


def test_t10_only_user_turn_text_is_captured(store):
    # A non-turn event carrying the name in its evidence: not a
    # source event in v1 (Q7).
    meeting = FellowshipEvent(
        id="ev-m", kind="meeting_completed", user_id=USER,
        entity_type="meeting", entity_id="meeting-1",
        evidence_text="Ana Ruiz was discussed at length.",
        summary="meeting", payload={}, created_at=T1_AT,
    )
    assert _capture(store, meeting) is None
    # A turn event with no user words: nothing to capture.
    assert _capture(store, _turn("ev-empty", "")) is None
    # The summary is never read: a name that appears only in the
    # event's summary boilerplate produces no sighting.
    ev = _turn("ev-sum", "Nothing to report today.")
    ev = FellowshipEvent(
        id=ev.id, kind=ev.kind, user_id=ev.user_id,
        entity_type=ev.entity_type, entity_id=ev.entity_id,
        evidence_text=ev.evidence_text,
        summary="Ana Ruiz was mentioned by the seat.",
        payload={}, created_at=T1_AT,
    )
    assert _capture(store, ev) is None
    assert store.candidates_for(USER) == []


# ---------------------------------------------------------------------
# T11 — the registered overlap is never auto-resolved [capture]
# ---------------------------------------------------------------------


def test_t11_registered_overlap_untouched(store, ve_conn):
    _capture(store, _turn("ev-1", "I talked with Ana Ruiz."))
    before = store.candidates_for(USER)[0]
    person = ve_storage.create_person(
        ve_models.PersonCreate(name="Ana Ruiz"), USER
    )
    assert person["id"]
    after = store.candidates_for(USER)[0]
    assert after == before  # no merge, no link, no retirement
    assert after.status == "candidate"
    assert after.promoted_person_ref is None


# ---------------------------------------------------------------------
# §5.3 routing — sole claimant, holding pool, alias [capture]
# ---------------------------------------------------------------------


def test_routing_spoken_for_form_writes_nothing(store):
    _capture(store, _turn("ev-1", "I talked with Ana Ruiz."))
    candidate = store.candidates_for(USER)[0]
    # Fixture-arranged: the delivery scope's recorded intent state
    # (a user act confirmed this form). Capture must write nothing
    # further — the form is spoken for (§5.3 rule 1).
    _sql(
        store,
        "UPDATE steward_candidate_mentions SET status = 'confirmed' "
        "WHERE id = ?",
        (candidate.id,),
    )
    report = _capture(
        store, _turn("ev-2", "Ana Ruiz again.", conv="conv-2", created=T2_AT)
    )
    assert report["forms_spoken_for"] == 1
    assert len(store.sightings_for(USER)) == 1
    assert store.candidates_for(USER)[0].mention_count == 1


def test_t15_holding_pool_and_alias_routing(store):
    # Candidate A accumulates "ana ruiz".
    _capture(store, _turn("ev-1", "I talked with Ana Ruiz."))
    a = store.candidates_for(USER)[0]
    # Fixture-arranged partition (§3.4/§6.3's result state): a
    # second candidate sharing the same surface form, told apart
    # by the user's label.
    _sql(
        store,
        "INSERT INTO steward_candidate_mentions (id, user_id, "
        "surface_form, normalized_form, status, ask_state, "
        "mention_count, first_seen_at, last_seen_at, "
        "promoted_person_ref, promotion_intent_json, user_label, "
        "created_at, updated_at) VALUES ('cand-b', ?, 'Ana Ruiz', "
        "'ana ruiz', 'candidate', 'not_asked', 0, '', '', NULL, "
        "'{}', 'Ana at work', ?, ?)",
        (USER, T1_AT, T1_AT),
    )
    # Two claimants: the next sighting is written UNLINKED —
    # counted nowhere, eligible for nothing (T15 counting half).
    report = _capture(
        store, _turn("ev-2", "Ana Ruiz again.", conv="conv-2", created=T2_AT)
    )
    assert report["sightings_unlinked"] == 1
    unlinked = store.unlinked_sightings_for(USER)
    assert [s.ref_id for s in unlinked] == ["ev-2"]
    assert store.get_candidate(USER, a.id).mention_count == 1
    assert store.get_candidate(USER, "cand-b").mention_count == 0

    # Alias routing (§5.3): retire B, record a user-authored alias
    # of the form to A — A becomes the sole claimant again and new
    # sightings route to it.
    assert store.retire_candidate(USER, "cand-b") is True
    _sql(
        store,
        "INSERT INTO steward_candidate_acts (id, user_id, kind, "
        "detail_json, created_at) VALUES ('act-1', ?, 'alias', ?, ?)",
        (
            USER,
            json.dumps({"form": "ana ruiz", "candidate_id": a.id}),
            T2_AT,
        ),
    )
    report = _capture(
        store, _turn("ev-3", "Ana Ruiz once more.", conv="conv-3",
               created=T3_AT)
    )
    assert report["sightings_unlinked"] == 0
    assert store.get_candidate(USER, a.id).mention_count == 2
    # The held sighting is untouched by the routing change.
    assert [s.ref_id for s in store.unlinked_sightings_for(USER)] == ["ev-2"]


# ---------------------------------------------------------------------
# Sweep helpers (the D2 suite's log pattern)
# ---------------------------------------------------------------------


def _log_record(event, created_at):
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
        "created_at": created_at,
    }


def _write_log(path, records):
    with path.open("a", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _meeting_pair(prefix, created, text=FOCUS_TEXT):
    records = []
    for i in (1, 2):
        event = FellowshipEvent(
            id=f"{prefix}-evt-{i}",
            kind="meeting_completed",
            user_id=USER,
            entity_type="meeting",
            entity_id=f"{prefix}-{i}",
            evidence_text=text,
            summary="meeting turn",
            payload={"archetype_id": "mentor", "keystone_index": 1},
            created_at=created,
        )
        records.append(_log_record(event, created))
    return records


def _candidate_state(store, user=USER):
    """The full registry state, comparable across processing
    orders: candidates by form, sightings by event, links by
    sighting."""
    candidates = {
        c.normalized_form: (
            c.surface_form, c.status, c.mention_count,
            c.first_seen_at, c.last_seen_at,
        )
        for c in store.candidates_for(user)
    }
    form_of = {c.id: c.normalized_form for c in store.candidates_for(user)}
    sightings = {
        (s.ref_id, s.normalized_form) for s in store.sightings_for(user)
    }
    links = set()
    for s in store.sightings_for(user):
        for m in store.membership_for_sighting(user, s.id):
            if m.superseded_at is None:
                links.add((s.ref_id, form_of[m.candidate_id]))
    return candidates, sightings, links


def _corpus():
    return [
        _turn("ev-1", "I talked with Ana Ruiz about the orchard.",
              conv="conv-1", created=T1_AT),
        _turn("ev-2", "Ana Ruiz and Marcus Chen were both there.",
              conv="conv-1", created=T2_AT),
        _turn("ev-3", "I keep thinking about Ana Ruiz.",
              conv="conv-2", created=T3_AT),
    ]


# ---------------------------------------------------------------------
# T13 — live/sweep idempotency [capture]
# ---------------------------------------------------------------------


def test_t13_live_sweep_idempotency(tmp_path, ve_conn):
    _set_consent(ve_conn, USER, on=True, version="permissions-v2")
    corpus = _corpus()
    log = tmp_path / "activity.log"
    _write_log(log, [_log_record(e, e.created_at) for e in corpus])

    def run_live(store):
        pipe = StewardPipeline(
            store=store,
            generate_fn=_gen(),
            scheduler=lambda fn: fn(),
            consent_reader=lambda user_id: True,
            operation_reader=lambda user_id: OperationRecords(),
        )
        for event in corpus:
            pipe._run_event(event)

    def run_sweep(store):
        run_sweep_for_user(
            store, USER, log_path=log, generate_fn=_gen(),
            consent_reader=lambda user_id: True,
            operation_reader=lambda user_id: OperationRecords(),
        )

    store_a = NarrativeStore(db_path=tmp_path / "a.db")
    run_live(store_a)
    run_sweep(store_a)  # sweep after live: all duplicates
    state_a = _candidate_state(store_a)

    store_b = NarrativeStore(db_path=tmp_path / "b.db")
    run_sweep(store_b)
    run_live(store_b)  # live after sweep: all duplicates
    state_b = _candidate_state(store_b)

    store_c = NarrativeStore(db_path=tmp_path / "c.db")
    run_live(store_c)
    run_live(store_c)  # crash-rescan shape: live twice
    state_c = _candidate_state(store_c)

    assert state_a == state_b == state_c
    candidates, sightings, links = state_a
    assert candidates["ana ruiz"][2] == 3  # mention_count by recount
    assert candidates["marcus chen"][2] == 1
    assert len(sightings) == 4  # one per (event, form)
    assert len(links) == 4


# ---------------------------------------------------------------------
# T14 — capture independence from thread admission [capture]
# ---------------------------------------------------------------------


def test_t14_capture_independent_of_thread_admission(tmp_path, ve_conn):
    _set_consent(ve_conn, USER, on=True, version="permissions-v2")
    # Corpus A: derivation admits nothing (isolated single turns,
    # no cluster births).
    log_a = tmp_path / "a.log"
    _write_log(log_a, [_log_record(e, e.created_at) for e in _corpus()])
    store_a = NarrativeStore(db_path=tmp_path / "a.db")
    run_sweep_for_user(
        store_a, USER, log_path=log_a, generate_fn=_gen(),
        consent_reader=lambda user_id: True,
        operation_reader=lambda user_id: OperationRecords(),
    )
    assert store_a.threads_for(USER, limit=None) == []
    state_a = _candidate_state(store_a)

    # Corpus B: the same turns PLUS a meeting pair derivation
    # admits fully (a thread is born). The sighting set is
    # identical.
    log_b = tmp_path / "b.log"
    _write_log(log_b, [_log_record(e, e.created_at) for e in _corpus()])
    _write_log(log_b, _meeting_pair("meet", T1_AT))
    store_b = NarrativeStore(db_path=tmp_path / "b.db")
    run_sweep_for_user(
        store_b, USER, log_path=log_b, generate_fn=_gen(),
        consent_reader=lambda user_id: True,
        operation_reader=lambda user_id: OperationRecords(),
    )
    assert len(store_b.threads_for(USER, limit=None)) >= 1
    assert _candidate_state(store_b) == state_a


# ---------------------------------------------------------------------
# T12 — generation impact / capture-off parity [capture]
# ---------------------------------------------------------------------


def test_t12_generation_impact(tmp_path, ve_conn, monkeypatch):
    _set_consent(ve_conn, USER, on=True, version="permissions-v2")
    log = tmp_path / "activity.log"
    _write_log(log, [_log_record(e, e.created_at) for e in _corpus()])
    _write_log(log, _meeting_pair("meet", T1_AT))

    def run(db_name):
        calls = []

        def counting_gen(prompt, **kwargs):
            calls.append(prompt)
            return BIRTH_JSON

        store = NarrativeStore(db_path=tmp_path / db_name)
        run_sweep_for_user(
            store, USER, log_path=log, generate_fn=counting_gen,
            consent_reader=lambda user_id: True,
            operation_reader=lambda user_id: OperationRecords(),
        )
        return store, calls

    store_on, calls_on = run("on.db")
    assert store_on.candidates_for(USER) != []
    monkeypatch.setenv("ZENAF_CANDIDATE_CAPTURE", "0")
    store_off, calls_off = run("off.db")
    # Capture is the only delta: identical generation spend,
    # identical threads, no deferred prose added, no candidates.
    assert len(calls_on) == len(calls_off)
    assert len(store_on.threads_for(USER, limit=None)) == len(
        store_off.threads_for(USER, limit=None)
    )
    assert store_off.candidates_for(USER) == []
    assert store_off.deferred_prose_for(USER) == []
    assert store_on.deferred_prose_for(USER) == []


# ---------------------------------------------------------------------
# T9 — D2 Scope S coverage, expanded and reverified [capture]
# ---------------------------------------------------------------------


class _Env:
    """One hermetic installation (the D2 suite's Env shape):
    identity + narrative + observations + presence on temp files."""

    def __init__(self, tmp_path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.istore = IdentityStore(db_path=tmp_path / "identity.db")
        identity_service.issue_license(owner_id=USER, store=self.istore)
        grant_scope("delete:execute", store=self.istore)
        self.nstore = NarrativeStore(db_path=tmp_path / "narrative.db")
        self.ostore = ObservationStore(db_path=tmp_path / "observations.db")
        self.pdb = tmp_path / "signals.db"
        self.pstore = PresenceStore(db_path=self.pdb)
        self.uploads = tmp_path / "uploads"
        self.uploads.mkdir()
        self.log = tmp_path / "activity.log"
        self.log.write_text("", encoding="utf-8")

    def delete(self, **overrides):
        kwargs = dict(
            store=self.istore,
            requesting_user_id=USER,
            narrative_store=self.nstore,
            observation_store=self.ostore,
            presence_store=self.pstore,
            presence_upload_root=self.uploads,
            presence_db_path=self.pdb,
            log_path=self.log,
            owner_resolver=lambda: USER,
        )
        kwargs.update(overrides)
        return identity_service.delete_all("DELETE", **kwargs)

    def reader(self, user_id):
        from local_ai.narrative.eligibility import read_operation_records

        return read_operation_records(self.istore, user_id)


def test_t9_erasure_coverage_expanded(tmp_path, ve_conn):
    _set_consent(ve_conn, USER, on=True, version="permissions-v2")
    env = _Env(tmp_path)
    store = env.nstore

    # Candidate material stands before the erasure (planted via
    # the capture funnel itself).
    report = store.capture_sightings(
        USER,
        [
            _sighting("ana ruiz", "Ana Ruiz", "ev-pre-1", seen=PRE),
            _sighting("ana ruiz", "Ana Ruiz", "ev-pre-2", conv="conv-2",
                      seen=PRE),
        ],
    )
    assert report["candidates_created"] == 1
    assert store.erasure_recount(USER)["steward_candidate_sightings"] == 2

    receipt = env.delete()
    # (e) receipt verification: the candidate families are in the
    # signed receipt's counts, matching independent recounts.
    assert receipt.summary["narrative_candidate_mentions"] == 1
    assert receipt.summary["narrative_candidate_sightings"] == 2
    assert receipt.summary["narrative_candidate_memberships"] == 2
    assert receipt.summary["narrative_candidate_acts"] == 0
    assert receipt.summary["stores"]["narrative"] == "verified"
    # (a) deletion: nothing of the family remains.
    recount = store.erasure_recount(USER)
    assert recount["steward_candidate_mentions"] == 0
    assert recount["steward_candidate_sightings"] == 0
    assert recount["steward_candidate_membership"] == 0
    assert recount["steward_candidate_acts"] == 0
    assert recount["total"] == 0

    # (b) non-resurrection: a rescan over the pre-erasure log
    # captures nothing (the events are eligibility-skipped before
    # capture is ever consulted).
    _write_log(
        env.log,
        [
            _log_record(_turn("ev-pre-1", "I talked with Ana Ruiz."), PRE),
            _log_record(
                _turn("ev-pre-2", "Ana Ruiz again.", conv="conv-2"), PRE
            ),
        ],
    )
    res = run_sweep_for_user(
        store, USER, log_path=env.log, generate_fn=_gen(),
        consent_reader=lambda user_id: True,
        operation_reader=env.reader,
        observation_store=env.ostore,
    )
    assert res.events_erasure_skipped >= 1
    assert store.candidates_for(USER) == []

    # A post-erasure event mentioning the erased form creates a
    # FRESH candidate — count 1, no memory of the erased one.
    _write_log(
        env.log,
        [_log_record(_turn("ev-post-1", "Ana Ruiz, a new mention.",
                           conv="conv-9"), POST)],
    )
    run_sweep_for_user(
        store, USER, log_path=env.log, generate_fn=_gen(),
        consent_reader=lambda user_id: True,
        operation_reader=env.reader,
        observation_store=env.ostore,
    )
    fresh = store.candidates_for(USER)
    assert len(fresh) == 1
    assert fresh[0].mention_count == 1
    assert fresh[0].first_seen_at == POST

    # (d) rollback barrier, enforcement-signal standard (D2 §9.2):
    # a raw write in old shape — no manifest — is refused by the
    # trigger as SQLITE_CONSTRAINT_TRIGGER, distinct from the
    # funnel's own refusal.
    with pytest.raises(sqlite3.IntegrityError) as excinfo:
        _sql(
            store,
            "INSERT INTO steward_candidate_sightings (id, user_id, "
            "ref_kind, ref_id, normalized_form, surface_form, "
            "conversation_id, seen_at, created_at) VALUES "
            "('sgt-raw', ?, 'event', 'ev-pre-1', 'ana ruiz', "
            "'Ana Ruiz', 'conv-1', ?, ?)",
            (USER, PRE, PRE),
        )
    assert "steward erasure barrier" in str(excinfo.value)
    with store._lock:
        store._conn.rollback()
    with pytest.raises(ErasureBarrierRefusal):
        store.capture_sightings(
            USER, [_sighting("marcus chen", "Marcus Chen", "ev-post-9",
                             seen=POST2)]
        )
    # The same write WITH its eligibility attestation lands.
    _write_log(
        env.log,
        [_log_record(_turn("ev-post-9", "Marcus Chen, attested."),
                     POST2)],
    )
    report = store.capture_sightings(
        USER,
        [_sighting("marcus chen", "Marcus Chen", "ev-post-9", seen=POST2)],
        admitted_sources=[("event", "ev-post-9", POST2)],
    )
    assert report["sightings_written"] == 1

    # (c) provenance audit (§9.5): on a fresh store, candidate
    # material is planted and an erasure tombstone is then
    # written directly (the D2 audit fixture's shape — material
    # that survived an incomplete erasure). The audit re-derives
    # eligibility from origin chronology: the pair citing the
    # pre-erasure event is found and removed; the pair citing
    # the post-erasure event is verified and kept.
    audit_store = NarrativeStore(db_path=tmp_path / "audit.db")
    audit_log = tmp_path / "audit.log"
    _write_log(
        audit_log,
        [
            _log_record(_turn("ev-pre-1", "I talked with Stale Name."), PRE),
            _log_record(_turn("ev-post-2", "Fresh Name, kept."), POST),
        ],
    )
    audit_store.capture_sightings(
        USER,
        [
            _sighting("stale name", "Stale Name", "ev-pre-1", seen=PRE),
            _sighting("fresh name", "Fresh Name", "ev-post-2", seen=POST),
        ],
    )
    assert len(audit_store.candidates_for(USER)) == 2
    boundary = "2026-11-15T00:00:00+00:00"
    audit_store.write_erasure_tombstone(USER, boundary, "op-audit")
    resolver = ProvenanceResolver(
        USER, boundary, narrative_store=audit_store, log_path=audit_log
    )
    audit = audit_narrative_store(audit_store, USER, resolver)
    failure_families = {family for family, _ in audit["failures"]}
    assert "candidate_sighting" in failure_families
    assert "candidate_mention" in failure_families
    surviving = {c.normalized_form for c in audit_store.candidates_for(USER)}
    assert surviving == {"fresh name"}
    assert {s.ref_id for s in audit_store.sightings_for(USER)} == {"ev-post-2"}
