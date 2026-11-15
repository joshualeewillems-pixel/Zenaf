"""Steward D2 — barrier/manifest/concurrency acceptance tests.

Packet tests 7 (§8.7), 10 (§8.7 F1–F4), 11 (§8.7 as amended),
15, 16, 18, 21 (§9.5). Deterministic: concurrency fixtures
synchronize on threading.Event barriers through the generate_fn
seam — never sleeps. BUSY outcomes are treated as inconclusive,
never as passes (test 16 discipline).
"""

from __future__ import annotations

import json
import sqlite3
import threading

import pytest

from local_ai.fellowship.events import FellowshipEvent
from local_ai.fellowship.observations import ObservationStore
from local_ai.identity import service as identity_service
from local_ai.identity.service import grant_scope
from local_ai.identity.store import IdentityStore
from local_ai.narrative.derivation import StewardPipeline, work_deferred_prose
from local_ai.narrative.eligibility import ProvenanceResolver
from local_ai.narrative.friction import run_friction_pass
from local_ai.narrative.refs import SourceRef
from local_ai.narrative.store import ErasureBarrierRefusal, NarrativeStore
from local_ai.narrative.sweep import run_sweep_for_user
from local_ai.presence_ingest.store import PresenceStore

USER = "d2-owner"
T = "2026-11-15T00:00:00+00:00"
PRE = "2026-11-14T00:00:00+00:00"
POST = "2026-11-16T00:00:00+00:00"
POST2 = "2026-11-17T00:00:00+00:00"

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


def _nstore(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    return NarrativeStore(db_path=tmp_path / "narrative.db")


def _tombstoned(tmp_path):
    """A narrative store with a standing barrier at T and one
    post-T thread (born manifested, as production would)."""
    store = _nstore(tmp_path)
    store.write_erasure_tombstone(USER, T, "op-fixture")
    thread = store.create_thread(
        USER,
        title="standing",
        evidence_refs=[SourceRef(kind="event", ref_id="ev-seed")],
        admitted_sources=[("event", "ev-seed", POST)],
    )
    return store, thread


def _log(tmp_path, records):
    path = tmp_path / "activity.log"
    with path.open("a", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


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


def _meeting_event(event_id, conv, text=FOCUS_TEXT):
    return FellowshipEvent(
        id=event_id,
        kind="meeting_completed",
        user_id=USER,
        entity_type="meeting",
        entity_id=conv,
        evidence_text=text,
        summary="meeting turn",
        payload={"archetype_id": "mentor", "keystone_index": 1},
    )


# ---------------------------------------------------------------------
# Test 7 — delayed derivative (deferred completion) after erasure
# ---------------------------------------------------------------------


def test_07_deferred_completion_reevaluates_eligibility(tmp_path):
    """§8.7 test 7: a deferred row whose sources are pre-erasure is
    never rendered after the barrier stands (released, counted
    erasure-skipped, no reading lands); a row whose sources are all
    post-erasure renders normally."""
    store = _nstore(tmp_path)
    # Two records-first births BEFORE any barrier: one founded on a
    # pre-T event, one on a post-T event (their prose is owed).
    pre_thread = store.create_thread_with_deferred_prose(
        USER,
        title="pre",
        evidence_refs=[SourceRef(kind="event", ref_id="ev-pre")],
        deferred_kind="birth",
        evidence_signature="sig-pre",
        evidence_texts=[{"ref": "event:ev-pre", "text": FOCUS_TEXT}],
    )
    post_thread = store.create_thread_with_deferred_prose(
        USER,
        title="post",
        evidence_refs=[SourceRef(kind="event", ref_id="ev-post")],
        deferred_kind="birth",
        evidence_signature="sig-post",
        evidence_texts=[{"ref": "event:ev-post", "text": FOCUS_TEXT}],
    )
    log_path = _log(tmp_path, [
        _log_record(FellowshipEvent(
            id="ev-pre", kind="conversation_turn", user_id=USER,
            entity_type="conversation", entity_id="conv-1",
            evidence_text=FOCUS_TEXT, summary="a turn",
        ), PRE),
        _log_record(FellowshipEvent(
            id="ev-post", kind="conversation_turn", user_id=USER,
            entity_type="conversation", entity_id="conv-1",
            evidence_text=FOCUS_TEXT, summary="a turn",
        ), POST),
    ])
    # The barrier lands (the operation itself is file 1's subject;
    # here the tombstone + resolver are the fixture).
    store.write_erasure_tombstone(USER, T, "op-7")
    resolver = ProvenanceResolver(
        USER, T, narrative_store=store, log_path=log_path
    )

    def gen(prompt, **kwargs):
        return BIRTH_JSON

    result = work_deferred_prose(
        store, USER, generate_fn=gen, erasure_resolver=resolver
    )
    assert len(result.erasure_skipped) == 1
    assert store.readings_for(USER, pre_thread.id) == []
    assert len(store.readings_for(USER, post_thread.id)) == 1
    # The skipped row was released to pending, never settled.
    pending = store.deferred_prose_for(USER, status="pending")
    assert [row["thread_id"] for row in pending] == [pre_thread.id]


# ---------------------------------------------------------------------
# Test 10 — concurrency fixtures F1–F4 (§8.3)
# ---------------------------------------------------------------------


class _FullEnv:
    """Identity + narrative + observations + presence, for the
    fixtures that run the real delete flow mid-flight."""

    def __init__(self, tmp_path):
        self.dir = tmp_path
        self.istore = IdentityStore(db_path=tmp_path / "identity.db")
        identity_service.issue_license(owner_id=USER, store=self.istore)
        grant_scope("delete:execute", store=self.istore)
        self.nstore = _nstore(tmp_path)
        self.ostore = ObservationStore(db_path=tmp_path / "observations.db")
        self.pdb = tmp_path / "signals.db"
        self.pstore = PresenceStore(db_path=self.pdb)
        self.uploads = tmp_path / "uploads"
        self.uploads.mkdir()
        self.log = tmp_path / "activity.log"
        self.log.write_text("", encoding="utf-8")

    def delete(self):
        return identity_service.delete_all(
            "DELETE",
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


def _blocking_gen(entered: threading.Event, release: threading.Event):
    def gen(prompt, **kwargs):
        entered.set()
        release.wait(timeout=30)
        return BIRTH_JSON

    return gen


def test_10_f1_sweep_batch_in_flight_when_tombstone_lands(tmp_path):
    """F1: a sweep batch whose generation is in flight when the
    erasure lands commits NO covered rows afterwards — the funnel
    refuses at write time (the batch was admitted before the
    barrier existed, so only the barrier can stop it)."""
    env = _FullEnv(tmp_path)
    records, rows = [], []
    for i in (1, 2):
        conv = f"conv-f1-{i}"
        records.append(_log_record(_meeting_event(f"f1-evt-{i}", conv), POST))
        rows.append({"conversation_id": conv, "created_at": POST})
    _log(tmp_path, records)  # _FullEnv.log is this same path

    entered, release = threading.Event(), threading.Event()
    outcome: dict = {}

    def run():
        try:
            outcome["res"] = run_sweep_for_user(
                env.nstore,
                USER,
                log_path=env.log,
                generate_fn=_blocking_gen(entered, release),
                consent_reader=lambda user_id: True,
                meeting_provider=lambda user_id: rows,
            )
        except Exception as exc:  # noqa: BLE001 — asserted below
            outcome["error"] = exc

    worker = threading.Thread(target=run)
    worker.start()
    assert entered.wait(timeout=30), "generation never started"
    receipt = env.delete()  # the tombstone lands mid-flight
    assert receipt.summary["stores"]["narrative"] == "verified"
    release.set()
    worker.join(timeout=30)
    assert not worker.is_alive()
    assert "error" not in outcome, outcome.get("error")
    # Nothing from the in-flight batch landed after the barrier.
    assert env.nstore.erasure_recount(USER)["total"] == 0


def test_10_f2_deferred_completion_races_erasure(tmp_path):
    """F2: a deferred row whose completion is IN FLIGHT (generation
    blocked) when the erasure lands never settles a reading — the
    completion hits the barrier (and the row itself is erased);
    nothing lands afterwards."""
    env = _FullEnv(tmp_path)
    thread = env.nstore.create_thread_with_deferred_prose(
        USER,
        title="owed",
        evidence_refs=[SourceRef(kind="event", ref_id="ev-owed")],
        deferred_kind="birth",
        evidence_signature="sig-owed",
        evidence_texts=[{"ref": "event:ev-owed", "text": FOCUS_TEXT}],
    )
    entered, release = threading.Event(), threading.Event()
    outcome: dict = {}

    def run():
        try:
            outcome["res"] = work_deferred_prose(
                env.nstore,
                USER,
                generate_fn=_blocking_gen(entered, release),
            )
        except Exception as exc:  # noqa: BLE001 — asserted below
            outcome["error"] = exc

    worker = threading.Thread(target=run)
    worker.start()
    assert entered.wait(timeout=30), "deferred generation never started"
    receipt = env.delete()  # erasure lands mid-render
    assert receipt.summary["stores"]["narrative"] == "verified"
    release.set()
    worker.join(timeout=30)
    assert not worker.is_alive()
    # No reading settled on the erased thread; nothing remains.
    assert env.nstore.erasure_recount(USER)["total"] == 0
    assert env.nstore.erasure_recount(USER)["thread_readings"] == 0
    assert env.nstore.get_thread(USER, thread.id) is None
    assert env.nstore.deferred_prose_for(USER, status="pending") == []


def test_10_f3_friction_pass_with_pre_erasure_snapshot(tmp_path):
    """F3: a friction pass whose inputs were snapshotted before the
    erasure lands nothing from pre-erasure sources; a post-erasure
    meeting in the same snapshot still produces its observable."""
    store, thread = _tombstoned(tmp_path)
    pre_meeting = {
        "archetype_id": "weaver",
        "keystone_index": 1,
        "stage": "complete",
        "status": "complete",
        "readback_claim": "you are X",
        "readback_response": "",
        "created_at": PRE,
    }
    post_meeting = dict(pre_meeting, created_at=POST, keystone_index=2)
    claims = [{
        "id": "c1", "agent_id": "agent-1", "claim_type": "strand",
        "status": "corrected", "user_note": "",
        "created_at": PRE, "updated_at": PRE,
    }]
    result = run_friction_pass(
        store,
        USER,
        meetings=[pre_meeting, post_meeting],
        claims=claims,
        gate_open=lambda: True,
    )
    observables = store.observables_for(USER)
    # Exactly the post-T meeting's O1 row; nothing from the pre-T
    # meeting and nothing from the claim (Option B: O2 never fires).
    assert len(observables) == 1
    assert observables[0].kind == "impression_unanswered"
    assert result is not None


def test_10_f4_live_pipeline_in_flight_when_tombstone_lands(tmp_path):
    """F4: a live pipeline batch whose generation is in flight
    when the erasure lands writes nothing afterwards — the batch
    was admitted before the barrier existed, so the barrier itself
    is the backstop."""
    from local_ai.narrative.derivation import EvidenceItem
    from local_ai.narrative.eligibility import read_operation_records

    env = _FullEnv(tmp_path)
    entered, release = threading.Event(), threading.Event()
    pipeline = StewardPipeline(
        store=env.nstore,
        generate_fn=_blocking_gen(entered, release),
        consent_reader=lambda user_id: True,
        operation_reader=lambda user_id: read_operation_records(
            env.istore, user_id
        ),
    )
    items = [
        EvidenceItem(
            ref=SourceRef(kind="event", ref_id=f"ev-f4-{i}"),
            text=FOCUS_TEXT,
            entity_ref="meeting:conv-f4",
        )
        for i in (1, 2)
    ]
    worker = threading.Thread(target=pipeline._run_batch, args=(USER, items))
    worker.start()
    assert entered.wait(timeout=30), "pipeline generation never started"
    receipt = env.delete()
    assert receipt.summary["stores"]["narrative"] == "verified"
    release.set()
    worker.join(timeout=30)
    assert not worker.is_alive()
    assert env.nstore.erasure_recount(USER)["total"] == 0


# ---------------------------------------------------------------------
# Test 11 — rollback compatibility (as amended by §9.5)
# ---------------------------------------------------------------------


def test_11_rollback_compatibility(tmp_path):
    """§8.7 test 11 (permit clauses struck; manifest clauses per
    test 15): with no tombstone, every funnel method behaves
    exactly as before with admitted_sources=None, and a funnel
    write that fails midway leaves neither partial rows nor
    manifest rows behind."""
    store = _nstore(tmp_path)
    thread = store.create_thread(
        USER, title="plain",
        evidence_refs=[SourceRef(kind="event", ref_id="ev-1")],
    )
    reading = store.propose_reading(
        USER, thread.id, author="steward", reading={"tensions": ["x"]},
        evidence_refs=[SourceRef(kind="event", ref_id="ev-1")],
    )
    assert reading is not None
    with store._lock:
        manifest_rows = store._conn.execute(
            "SELECT COUNT(*) FROM steward_erasure_manifest"
        ).fetchone()[0]
    assert manifest_rows == 0

    # A failing plumbed write under a tombstone rolls back whole:
    # no thread, no evidence, no manifest residue.
    store2, standing = _tombstoned(tmp_path / "second")
    with pytest.raises(Exception):
        store2.create_thread(
            USER,
            title="doomed",
            evidence_refs=[SourceRef(kind="event", ref_id="ev-doomed")],
            admitted_sources=[("event", "ev-doomed", PRE)],  # stale: rejected
        )
    assert store2.erasure_recount(USER)["narrative_threads"] == 1  # only standing
    with store2._lock:
        leftovers = store2._conn.execute(
            "SELECT COUNT(*) FROM steward_erasure_manifest"
        ).fetchone()[0]
    assert leftovers == 0


# ---------------------------------------------------------------------
# Test 15 — manifest binding (§9.2/§9.5)
# ---------------------------------------------------------------------


def test_15_manifest_binding(tmp_path):
    """§9.5 test 15: under a tombstone, a covered write with no
    manifest is refused at the funnel; with a manifest naming a
    DIFFERENT source it is rejected by the trigger with the pinned
    enforcement signal; with the correct manifest it lands; and no
    manifest row ever persists past the transaction."""
    store, standing = _tombstoned(tmp_path)
    # No manifest at all: funnel refusal.
    with pytest.raises(ErasureBarrierRefusal):
        store.create_thread(
            USER, title="unmanifested",
            evidence_refs=[SourceRef(kind="event", ref_id="ev-x")],
        )
    # Manifest naming a different source: the funnel's own
    # dependency check refuses (the write's named dependencies were
    # not attested).
    with pytest.raises(ErasureBarrierRefusal):
        store.create_thread(
            USER, title="wrong-source",
            evidence_refs=[SourceRef(kind="event", ref_id="ev-x")],
            admitted_sources=[("event", "ev-other", POST)],
        )
    # Manifest naming the right source at a stale time: passes the
    # funnel check, rejected by the TRIGGER with the pinned
    # enforcement signal (the barrier itself, not the funnel).
    with pytest.raises(sqlite3.IntegrityError) as excinfo:
        store.create_thread(
            USER, title="stale-source",
            evidence_refs=[SourceRef(kind="event", ref_id="ev-x")],
            admitted_sources=[("event", "ev-x", PRE)],
        )
    assert excinfo.value.sqlite_errorname == "SQLITE_CONSTRAINT_TRIGGER"
    assert "steward erasure barrier" in str(excinfo.value)
    # Correct manifest: lands.
    born = store.create_thread(
        USER, title="manifested",
        evidence_refs=[SourceRef(kind="event", ref_id="ev-x")],
        admitted_sources=[("event", "ev-x", POST)],
    )
    assert store.get_thread(USER, born.id) is not None
    with store._lock:
        assert store._conn.execute(
            "SELECT COUNT(*) FROM steward_erasure_manifest"
        ).fetchone()[0] == 0


# ---------------------------------------------------------------------
# Test 16 — rollback while a manifest is live (§9.5, Rev 3 form)
# ---------------------------------------------------------------------


def test_16_rollback_while_manifest_live(tmp_path):
    """§9.5 test 16 (as amended): a manifest live in an open
    transaction (a) does not cover a different source even in its
    own transaction, (b) is invisible to another connection, and
    (c) leaves nothing behind when the transaction rolls back.
    BUSY outcomes prove nothing and are not asserted as passes —
    the surviving assertions are never-lands + invisibility."""
    store, standing = _tombstoned(tmp_path)
    db_path = tmp_path / "narrative.db"
    conn_a = sqlite3.connect(db_path)
    conn_b = sqlite3.connect(db_path)
    try:
        conn_a.execute("BEGIN")
        conn_a.execute(
            "INSERT INTO steward_erasure_manifest "
            "(run_id, user_id, erased_at_seen, source_kind, source_id, source_time) "
            "VALUES ('run-a', ?, ?, 'event', 'ev-a', ?)",
            (USER, T, POST),
        )
        # (b) Invisible to connection B while uncommitted.
        seen = conn_b.execute(
            "SELECT COUNT(*) FROM steward_erasure_manifest"
        ).fetchone()[0]
        assert seen == 0
        # (a) The live manifest does not cover a different source,
        # even in its own transaction.
        with pytest.raises(sqlite3.IntegrityError) as excinfo:
            conn_a.execute(
                "INSERT INTO thread_evidence "
                "(id, thread_id, ref_kind, ref_id, evidence_kind, created_at) "
                "VALUES ('evr-x', ?, 'event', 'ev-other', 'quote', ?)",
                (standing.id, POST),
            )
        assert excinfo.value.sqlite_errorname == "SQLITE_CONSTRAINT_TRIGGER"
        conn_a.rollback()
        # (c) Nothing landed; no manifest persists.
        assert conn_b.execute(
            "SELECT COUNT(*) FROM thread_evidence WHERE id = 'evr-x'"
        ).fetchone()[0] == 0
        assert conn_b.execute(
            "SELECT COUNT(*) FROM steward_erasure_manifest"
        ).fetchone()[0] == 0
    finally:
        conn_a.close()
        conn_b.close()


# ---------------------------------------------------------------------
# Test 18 — dependency coverage per family (§9.5)
# ---------------------------------------------------------------------


def test_18_dependency_coverage_per_family(tmp_path):
    """§9.5 test 18: every trigger family binds its own dependency
    shape — an unmanifested (or wrongly manifested) dependency is
    rejected per family; the correctly manifested write lands."""
    store, standing = _tombstoned(tmp_path)
    seed_evidence = store.evidence_for(USER, standing.id)
    seed_row_id = seed_evidence[0].id

    def rejected(fn):
        with pytest.raises((ErasureBarrierRefusal, sqlite3.IntegrityError)):
            fn()

    # Change family — cited evidence (record_change attaches the
    # cited ref itself; the binding is per-ref).
    rejected(lambda: store.record_change(
        USER, standing.id, kind="extended",
        evidence_refs=[SourceRef(kind="event", ref_id="ev-cited")]))
    store.record_change(
        USER, standing.id, kind="extended",
        evidence_refs=[SourceRef(kind="event", ref_id="ev-cited")],
        admitted_sources=[("event", "ev-cited", POST)],
    )
    # Evidence family.
    rejected(lambda: store.add_evidence(
        USER, standing.id, SourceRef(kind="event", ref_id="ev-new")))
    store.add_evidence(
        USER, standing.id, SourceRef(kind="event", ref_id="ev-new"),
        admitted_sources=[("event", "ev-new", POST)],
    )
    # Reading family (cites the manifested evidence row's source).
    rejected(lambda: store.propose_reading(
        USER, standing.id, author="steward", reading={"tensions": ["y"]},
        evidence_refs=[SourceRef(kind="event", ref_id="ev-unseen")]))
    store.propose_reading(
        USER, standing.id, author="steward", reading={"tensions": ["y"]},
        evidence_refs=[SourceRef(kind="event", ref_id="ev-new")],
        admitted_sources=[("event", "ev-new", POST)],
    )
    # Deferred family (attach + deferred row in one commit).
    rejected(lambda: store.attach_evidence_with_deferred_prose(
        USER, standing.id, [SourceRef(kind="event", ref_id="ev-unseen3")],
        evidence_signature="sig-x",
        evidence_texts=[{"ref": "event:ev-unseen3", "text": FOCUS_TEXT}]))
    store.attach_evidence_with_deferred_prose(
        USER, standing.id, [SourceRef(kind="event", ref_id="ev-att")],
        evidence_signature="sig-y",
        evidence_texts=[{"ref": "event:ev-att", "text": FOCUS_TEXT}],
        admitted_sources=[("event", "ev-att", POST)],
    )
    # Observable family — thread-scoped, citing an evidence row id.
    new_evidence = store.evidence_for(USER, standing.id)
    cited_id = [r.id for r in new_evidence if r.ref_id == "ev-att"][0]
    desired = [{
        "id": "obs-fam", "user_id": USER, "thread_id": standing.id,
        "kind": "thread_quiet", "signal_key": "fam-k",
        "evidence_refs": [cited_id], "detail": {},
        "first_seen_at": POST, "last_seen_at": POST, "created_at": POST,
    }]
    rejected(lambda: store.sync_thread_observables(USER, standing.id, desired))
    store.sync_thread_observables(
        USER, standing.id, desired,
        admitted_sources=[("event", "ev-att", POST)],
    )
    assert any(o.signal_key == "fam-k" for o in store.observables_for(USER))
    # Observation family (fellowship store).
    ostore = ObservationStore(db_path=tmp_path / "observations.db")
    ostore.write_erasure_tombstone(USER, T, "op-fixture")
    with pytest.raises(Exception):
        ostore.add(
            user_id=USER, seat="conductor", event_ref="ev-nope",
            event_kind="conversation_turn", evidence="w",
            evidence_kind="quote", interpretation="i",
        )
    ostore.add(
        user_id=USER, seat="conductor", event_ref="ev-yes",
        event_kind="conversation_turn", evidence="w",
        evidence_kind="quote", interpretation="i",
        admitted_sources=[("event", "ev-yes", POST)],
    )
    assert ostore.count_for_user(USER) == 1

    # Change family — reinterpreted: binds the successor through a
    # ('thread', successor) dependency entry, and the trigger joins
    # that the successor is a standing thread of the same user.
    successor = store.create_thread(
        USER, title="successor",
        evidence_refs=[SourceRef(kind="event", ref_id="ev-succ")],
        admitted_sources=[("event", "ev-succ", POST)],
    )
    rejected(lambda: store.record_change(
        USER, standing.id, kind="retired", reason="reinterpreted",
        successor_thread_id=successor.id))
    store.record_change(
        USER, standing.id, kind="retired", reason="reinterpreted",
        successor_thread_id=successor.id,
        admitted_sources=[("thread", successor.id, successor.created_at)],
    )

    # Change family — outgrown: binds the evidence row whose
    # created_at the absence is measured from. Its own store, with
    # an earlier boundary so the absence is honest (evidence dated
    # after the boundary, older than the window).
    (tmp_path / "b").mkdir(exist_ok=True)
    store_b = NarrativeStore(db_path=tmp_path / "b" / "narrative.db")
    early_t = "2026-09-01T00:00:00+00:00"
    evidence_time = "2026-10-01T00:00:00+00:00"
    store_b.write_erasure_tombstone(USER, early_t, "op-early")
    old_thread = store_b.create_thread(
        USER, title="old",
        evidence_refs=[SourceRef(kind="event", ref_id="ev-old")],
        admitted_sources=[("event", "ev-old", evidence_time)],
    )
    with store_b._lock:
        store_b._conn.execute(
            "UPDATE thread_evidence SET created_at = ? WHERE thread_id = ?",
            (evidence_time, old_thread.id),
        )
        store_b._conn.commit()
    rejected(lambda: store_b.record_change(
        USER, old_thread.id, kind="retired", reason="outgrown",
        absence_basis={"window_days": 30, "last_evidence_at": evidence_time}))
    store_b.record_change(
        USER, old_thread.id, kind="retired", reason="outgrown",
        absence_basis={"window_days": 30, "last_evidence_at": evidence_time},
        admitted_sources=[("event", "ev-old", evidence_time)],
    )


# ---------------------------------------------------------------------
# Test 21 — enforcement signal / non-borrowing (§9.5)
# ---------------------------------------------------------------------


def test_21_manifest_cannot_be_borrowed(tmp_path):
    """§9.5 test 21: the non-borrowing triple — (1) a manifest live
    in connection A's transaction is invisible to connection B;
    (2) B's identical covered insert never succeeds while A's
    manifest is live (any failure signal is acceptable here —
    success is the only failing outcome); (3) after A's transaction
    completes by the funnel pattern (insert, delete manifest,
    commit), the identical statement from B fails with exactly the
    enforcement signal."""
    ostore = ObservationStore(db_path=tmp_path / "observations.db")
    ostore.write_erasure_tombstone(USER, T, "op-fixture")
    db_path = tmp_path / "observations.db"
    insert_sql = (
        "INSERT INTO observations "
        "(id, user_id, seat, event_ref, event_kind, evidence, "
        "evidence_kind, interpretation, status, derivation_json, "
        "created_at, updated_at) VALUES (?, ?, 'conductor', 'ev-a', "
        "'conversation_turn', 'w', 'quote', 'i', 'pending', '{}', ?, ?)"
    )
    conn_a = sqlite3.connect(db_path)
    conn_b = sqlite3.connect(db_path)
    try:
        conn_a.execute("BEGIN")
        conn_a.execute(
            "INSERT INTO steward_erasure_manifest "
            "(run_id, user_id, erased_at_seen, source_kind, source_id, source_time) "
            "VALUES ('run-a', ?, ?, 'event', 'ev-a', ?)",
            (USER, T, POST),
        )
        # (1) Invisible to B.
        assert conn_b.execute(
            "SELECT COUNT(*) FROM steward_erasure_manifest"
        ).fetchone()[0] == 0
        # (2) B's identical insert never succeeds.
        with pytest.raises(sqlite3.Error):
            conn_b.execute(insert_sql, ("obs-b", USER, POST, POST))
            conn_b.commit()
        conn_b.rollback()
        # A's own covered insert lands under its manifest; the
        # funnel pattern deletes the manifest before commit.
        conn_a.execute(insert_sql, ("obs-a", USER, POST, POST))
        conn_a.execute("DELETE FROM steward_erasure_manifest")
        conn_a.commit()
        assert conn_b.execute(
            "SELECT COUNT(*) FROM observations WHERE id = 'obs-a'"
        ).fetchone()[0] == 1
        assert conn_b.execute(
            "SELECT COUNT(*) FROM steward_erasure_manifest"
        ).fetchone()[0] == 0
        # (3) Post-release, the identical statement fails with
        # exactly the enforcement signal.
        with pytest.raises(sqlite3.IntegrityError) as excinfo:
            conn_b.execute(insert_sql, ("obs-b2", USER, POST, POST))
            conn_b.commit()
        assert excinfo.value.sqlite_errorname == "SQLITE_CONSTRAINT_TRIGGER"
        assert "steward erasure barrier" in str(excinfo.value)
        conn_b.rollback()
    finally:
        conn_a.close()
        conn_b.close()
