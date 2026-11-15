"""Steward D2 Scope S erasure — acceptance tests (packet §§6.5/8.7/9.5, Rev 4).

Deterministic, hermetic: every store is a fixture/temp file, no
live-user deletion, no model calls (generate_fn is always a stub).
Test numbering follows the packet: tests 1–5 (§6.5), 6–13 (§8.7),
14–21 (§9.5), 22–23 (Rev 4). This file carries the flow-level
tests; tests/test_steward_d2_barrier.py carries the
trigger/manifest/concurrency tests.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from local_ai.fellowship.events import FellowshipEvent
from local_ai.fellowship.observations import ObservationStore
from local_ai.identity import service as identity_service
from local_ai.identity.erasure import (
    COVERAGE_STATEMENT,
    ErasureRefused,
    _save_operation_row,
)
from local_ai.identity.service import ScopeDenied, grant_scope
from local_ai.identity.store import IdentityStore
from local_ai.narrative.eligibility import (
    ProvenanceResolver,
    audit_narrative_store,
    audit_observation_store,
    check_barrier_integrity,
    read_operation_records,
)
from local_ai.narrative.models import THREAD_ORIGINS
from local_ai.narrative.refs import SourceRef
from local_ai.narrative.store import NarrativeStore
from local_ai.narrative.sweep import run_sweep_for_user
from local_ai.presence_ingest.store import PresenceStore

USER = "d2-owner"
OTHER = "d2-other-user"
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


class Env:
    """One hermetic installation: identity + narrative +
    observations + presence stores on temp files."""

    def __init__(self, tmp_path, *, grant: bool = True):
        self.dir = tmp_path
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.istore = IdentityStore(db_path=tmp_path / "identity.db")
        identity_service.issue_license(owner_id=USER, store=self.istore)
        if grant:
            grant_scope("delete:execute", store=self.istore)
        self.license_id = self.istore.get_license().license_id
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
        return read_operation_records(self.istore, user_id)

    def add_observation(self, event_ref="ev-old", user=USER):
        return self.ostore.add(
            user_id=user,
            seat="conductor",
            event_ref=event_ref,
            event_kind="conversation_turn",
            evidence="verbatim words",
            evidence_kind="quote",
            interpretation="A reading.",
        )


@pytest.fixture()
def env(tmp_path):
    return Env(tmp_path)


def _thread_with_material(store, user=USER, origin="user_declared", title="T"):
    thread = store.create_thread(
        user,
        origin=origin,
        title=title,
        evidence_refs=[SourceRef(kind="event", ref_id="ev-seed")],
    )
    store.propose_reading(
        user,
        thread.id,
        author="steward",
        reading={"tensions": ["roots vs. road"]},
        evidence_refs=[SourceRef(kind="event", ref_id="ev-seed")],
    )
    return thread


def _sql(store, statement, params=()):
    with store._lock:
        store._conn.execute(statement, params)
        store._conn.commit()


# ---------------------------------------------------------------------
# §6.5 tests 1–5
# ---------------------------------------------------------------------


def test_01_all_five_origins_erased_including_over_100_threads(env):
    """§6.5 test 1 + §2.3: every origin, >100 threads, and a row in
    every user-wide table the erase operation is specified to clear."""
    threads = []
    for i in range(105):
        origin = THREAD_ORIGINS[i % len(THREAD_ORIGINS)]
        threads.append(
            env.nstore.create_thread(
                USER,
                origin=origin,
                title=f"thread-{i}",
                evidence_refs=[SourceRef(kind="event", ref_id=f"ev-{i}")],
            )
        )
    first = threads[0]
    env.nstore.propose_reading(
        USER, first.id, author="steward",
        reading={"tensions": ["x"]},
        evidence_refs=[SourceRef(kind="event", ref_id="ev-0")],
    )
    # One row in each remaining §2.3 table (fixture-level inserts).
    _sql(env.nstore, "INSERT INTO thread_changes (id, thread_id, kind, evidence_refs_json, status, created_at) VALUES ('chg-1', ?, 'reinterpreted', '[]', 'proposed', ?)", (first.id, PRE))
    _sql(env.nstore, "INSERT INTO lens_fittings (id, thread_id, lens_id, status, evidence_refs_json, proposed_by, created_at) VALUES ('lf-1', ?, 'lens-a', 'proposed', '[]', 'steward', ?)", (first.id, PRE))
    _sql(env.nstore, "INSERT INTO thread_links (id, user_id, parent_thread_id, child_thread_id, relation, created_at) VALUES ('lnk-1', ?, ?, ?, 'grew_from', ?)", (USER, threads[0].id, threads[1].id, PRE))
    _sql(env.nstore, "INSERT INTO involvement_measures (id, user_id, subject_kind, subject_id, created_at, updated_at) VALUES ('im-1', ?, 'thread', ?, ?, ?)", (USER, first.id, PRE, PRE))
    _sql(env.nstore, "INSERT INTO steward_dismissals (id, user_id, kind, signature, created_at) VALUES ('dis-1', ?, 'thread', 'sig', ?)", (USER, PRE))
    _sql(env.nstore, "INSERT INTO steward_deferred_prose (id, user_id, thread_id, kind, evidence_signature, evidence_refs_json, evidence_texts_json, created_at, status) VALUES ('def-1', ?, ?, 'birth', 'sig', '[\"event:ev-0\"]', '{}', ?, 'pending')", (USER, first.id, PRE))
    _sql(env.nstore, "INSERT INTO steward_observables (id, user_id, thread_id, kind, signal_key, evidence_refs_json, detail_json, first_seen_at, last_seen_at, created_at) VALUES ('obs-1', ?, ?, 'thread_dormant', 'k1', '[]', '{}', ?, ?, ?)", (USER, first.id, PRE, PRE, PRE))
    _sql(env.nstore, "INSERT INTO steward_signal_states (user_id, signal_kind, signal_id, delivery_status, updated_at) VALUES (?, 'thread_dormant', 'k1', 'pending', ?)", (USER, PRE))
    _sql(env.nstore, "INSERT INTO steward_relevance_assessments (id, user_id, branch_id, thread_id, evidence_refs_json, relevant, reasons_json, inputs_json, created_at) VALUES ('as-1', ?, 'b1', ?, '[]', 1, '[]', '{}', ?)", (USER, first.id, PRE))
    _sql(env.nstore, "INSERT INTO steward_discrepancy_flags (id, user_id, assessment_id, branch_id, objection, evidence_refs_json, status, created_at) VALUES ('fl-1', ?, 'as-1', 'b1', 'obj', '[]', 'open', ?)", (USER, PRE))
    _sql(env.nstore, "INSERT INTO steward_review_verdicts (id, user_id, item_kind, item_id, verdict, created_at) VALUES ('vd-1', ?, 'thread', ?, 'keep', ?)", (USER, first.id, PRE))
    _sql(env.nstore, "INSERT INTO steward_correspondences (id, user_id, thread_ids_json, evidence_refs_json, status, created_at) VALUES ('co-1', ?, '[]', '[]', 'proposed', ?)", (USER, PRE))
    _sql(env.nstore, "INSERT INTO steward_correspondence_responses (id, correspondence_id, user_id, branch_id, response, created_at) VALUES ('cr-1', 'co-1', ?, 'b1', 'resp', ?)", (USER, PRE))
    _sql(env.nstore, "INSERT INTO steward_oversight_proposals (id, user_id, thread_id, kind, reason, status, created_at) VALUES ('ov-1', ?, ?, 'merge', 'r', 'proposed', ?)", (USER, first.id, PRE))
    _sql(env.nstore, "INSERT INTO steward_reading_reconsiderations (id, user_id, reading_id, thread_id, reason, status, created_at) VALUES ('rc-1', ?, 'rdg-x', ?, 'r', 'open', ?)", (USER, first.id, PRE))
    _sql(env.nstore, "INSERT INTO steward_artifacts (id, user_id, thread_id, title, created_at, updated_at) VALUES ('ar-1', ?, ?, 'art', ?, ?)", (USER, first.id, PRE, PRE))
    _sql(env.nstore, "INSERT INTO steward_artifact_versions (id, artifact_id, user_id, version_no, content_json, created_at) VALUES ('av-1', 'ar-1', ?, 1, '{}', ?)", (USER, PRE))
    env.add_observation()
    # Another user's material must survive untouched.
    other_thread = _thread_with_material(env.nstore, user=OTHER)
    env.add_observation(user=OTHER)

    before = env.nstore.erasure_recount(USER)
    assert before["narrative_threads"] == 105
    assert before["total"] >= 105 + 105 + 18  # threads+evidence+rows

    receipt = env.delete()
    assert receipt.summary["stores"] == {
        "presence": "verified",
        "narrative": "verified",
        "observations": "verified",
        "identity": "verified",
    }
    after = env.nstore.erasure_recount(USER)
    assert after["total"] == 0
    assert env.ostore.count_for_user(USER) == 0
    # The other user is untouched.
    assert env.nstore.erasure_recount(OTHER)["narrative_threads"] == 1
    assert env.ostore.count_for_user(OTHER) == 1
    assert env.nstore.get_thread(OTHER, other_thread.id) is not None


def test_02_counts_agree_preview_executed_receipt(env, tmp_path):
    """§6.5 test 2: preview counts == executed counts == receipt
    summary counts, per category. The erase operation's preview is
    its own fresh uncapped recount (§6.2.1); the test derives every
    number independently — its own recount before the operation —
    and compares against the erase report and the flow's receipt."""
    for i in range(3):
        _thread_with_material(env.nstore, title=f"t-{i}")
    env.add_observation()
    env.add_observation(event_ref="ev-2")

    # The test's own per-category preview (independent recount).
    preview = env.nstore.erasure_recount(USER)
    obs_preview = env.ostore.count_for_user(USER)
    assert preview["narrative_threads"] == 3
    assert obs_preview == 2

    # (a) The store operation: executed counts == preview, per
    # category, and the post-recount is zero everywhere.
    env_b = Env(tmp_path / "b")
    for i in range(3):
        _thread_with_material(env_b.nstore, title=f"t-{i}")
    preview_b = env_b.nstore.erasure_recount(USER)
    report = env_b.nstore.erase_user_material(
        USER, erased_at=T, operation_id="op-test-2", log_path=env_b.log
    )
    for category, count in preview_b.items():
        if category == "total":
            continue
        assert report["per_table"][category] == count, category
    assert report["threads_deleted"] == preview_b["narrative_threads"]
    assert env_b.nstore.erasure_recount(USER)["total"] == 0

    # (b) The wired flow: receipt counts == the same preview.
    receipt = env.delete()
    assert receipt.summary["narrative_threads"] == preview["narrative_threads"]
    assert (
        receipt.summary["narrative_rows"]
        == preview["total"] - preview["narrative_threads"]
    )
    assert receipt.summary["observations"] == obs_preview
    assert env.nstore.erasure_recount(USER)["total"] == 0


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


def _turn_event(event_id, text, user=USER):
    return FellowshipEvent(
        id=event_id,
        kind="conversation_turn",
        user_id=user,
        entity_type="conversation",
        entity_id="conv-1",
        evidence_text=text,
        summary="a turn",
        payload={},
    )


def _gen(payload=BIRTH_JSON):
    def gen(prompt, **kwargs):
        return payload

    return gen


def _meeting_pair(prefix, created, text=FOCUS_TEXT):
    """Two meeting_completed events sharing a focus text (the
    clustering threshold a birth needs) + their meeting rows."""
    records, rows = [], []
    for i in (1, 2):
        conv = f"{prefix}-{i}"
        event = FellowshipEvent(
            id=f"{prefix}-evt-{i}",
            kind="meeting_completed",
            user_id=USER,
            entity_type="meeting",
            entity_id=conv,
            evidence_text=text,
            summary="meeting turn",
            payload={"archetype_id": "mentor", "keystone_index": 1},
        )
        records.append(_log_record(event, created))
        rows.append({"conversation_id": conv, "created_at": created})
    return records, rows


def test_03_non_resurrection_and_post_erasure_event_derives(env):
    """§6.5 test 3 + §8.1: after erasure, a forced rescan over the
    pre-erasure log derives nothing (events consumed-skipped);
    genuinely post-erasure events derive normally."""
    _thread_with_material(env.nstore)
    env.delete()
    assert env.nstore.erasure_recount(USER)["total"] == 0

    old_records, old_rows = _meeting_pair("conv-pre", PRE)
    new_records, new_rows = _meeting_pair("conv-post", POST)
    meeting_rows = old_rows + new_rows
    provider = lambda user_id: meeting_rows  # noqa: E731

    _write_log(env.log, old_records)
    res = run_sweep_for_user(
        env.nstore,
        USER,
        log_path=env.log,
        generate_fn=_gen(),
        consent_reader=lambda user_id: True,
        operation_reader=env.reader,
        observation_store=env.ostore,
        meeting_provider=provider,
    )
    assert res.events_erasure_skipped >= 1
    assert env.nstore.erasure_recount(USER)["total"] == 0

    _write_log(env.log, new_records)
    res2 = run_sweep_for_user(
        env.nstore,
        USER,
        log_path=env.log,
        generate_fn=_gen(),
        consent_reader=lambda user_id: True,
        operation_reader=env.reader,
        observation_store=env.ostore,
        meeting_provider=provider,
    )
    assert res2.events_erasure_skipped == 0
    assert env.nstore.erasure_recount(USER)["narrative_threads"] >= 1


def test_04_file_level_byte_scan(env):
    """§6.5 test 4: after deletion + VACUUM, distinctive content
    strings do not appear in either store's file bytes. (File
    hygiene for these files only — never a claim about backups.)"""
    marker_thread = "ZQXW-unique-thread-title"
    marker_obs = "ZQXW-unique-interpretation"
    thread = env.nstore.create_thread(
        USER, title=marker_thread,
        evidence_refs=[SourceRef(kind="event", ref_id="ev-m")],
    )
    env.ostore.add(
        user_id=USER, seat="conductor", event_ref="ev-m",
        event_kind="conversation_turn", evidence="words",
        evidence_kind="quote", interpretation=marker_obs,
    )
    env.delete()
    narrative_bytes = (env.dir / "narrative.db").read_bytes()
    obs_bytes = (env.dir / "observations.db").read_bytes()
    assert marker_thread.encode() not in narrative_bytes
    assert marker_obs.encode() not in obs_bytes
    assert thread.id.encode() not in narrative_bytes


def test_05_fail_closed_paths(env):
    """§6.5 test 5 + §9.1: wrong session user, missing scope, and a
    terminated license with no record all refuse and delete
    nothing."""
    _thread_with_material(env.nstore)
    env.add_observation()
    before = env.nstore.erasure_recount(USER)["total"]

    with pytest.raises(ErasureRefused):
        env.delete(requesting_user_id="not-the-owner")
    assert env.nstore.erasure_recount(USER)["total"] == before
    assert env.ostore.count_for_user(USER) == 1

    second = env.dir / "second"
    second.mkdir(exist_ok=True)
    env2 = Env(second, grant=False)
    with pytest.raises(ScopeDenied):
        env2.delete()

    # Terminated license, no operation record, no completion.
    env.istore.terminate_license()
    with pytest.raises(ErasureRefused):
        env.delete()
    assert env.nstore.erasure_recount(USER)["total"] == before


# ---------------------------------------------------------------------
# §8.7 tests 6–13 (flow-level subset)
# ---------------------------------------------------------------------


def test_06_eligibility_matrix(env):
    """§8.7 test 6 / §9.3: strictly-after governs; equality fails;
    missing provenance fails closed; culminations resolve to their
    origin record; claims are excluded (Option B); deferred rows
    resolve every ref."""
    meetings = [
        {"conversation_id": "conv-pre", "created_at": PRE},
        {"conversation_id": "conv-post", "created_at": POST},
    ]
    events = [
        _turn_event("evt-pre", "x"),
        _turn_event("evt-eq", "x"),
        _turn_event("evt-post", "x"),
        FellowshipEvent(id="mc-pre", kind="meeting_completed", user_id=USER,
                        entity_type="meeting", entity_id="conv-pre"),
        FellowshipEvent(id="mc-post", kind="meeting_completed", user_id=USER,
                        entity_type="meeting", entity_id="conv-post"),
        FellowshipEvent(id="cd-1", kind="claim_decided", user_id=USER,
                        entity_type="claim", entity_id="claim-1"),
    ]
    _write_log(env.log, [
        _log_record(events[0], PRE),
        _log_record(events[1], T),
        _log_record(events[2], POST),
        _log_record(events[3], POST),   # log time post-T; origin pre-T
        _log_record(events[4], POST2),
        _log_record(events[5], POST),
    ])
    resolver = ProvenanceResolver(
        USER, T, narrative_store=env.nstore, log_path=env.log,
        meeting_rows=meetings,
    )
    assert resolver.origin_time_for_event(events[0]) is None      # before T
    assert resolver.origin_time_for_event(events[1]) is None      # equality fails
    assert resolver.origin_time_for_event(events[2]) is not None  # after T
    assert resolver.origin_time_for_event(events[3]) is None      # origin governs
    assert resolver.origin_time_for_event(events[4]) is not None  # origin post-T
    assert resolver.origin_time_for_event(events[5]) is None      # Option B
    # A culmination with no origin record fails closed.
    orphan = FellowshipEvent(id="mc-x", kind="meeting_completed", user_id=USER,
                             entity_type="meeting", entity_id="conv-missing")
    assert resolver.origin_time_for_event(orphan) is None
    # An ordinary event with no log line may use its carriage time.
    carried = FellowshipEvent(
        id="evt-carried", kind="conversation_turn", user_id=USER,
        entity_type="conversation", entity_id="conv-1",
        evidence_text="x", created_at=POST,
    )
    assert resolver.origin_time_for_event(carried) is not None
    carried_stale = FellowshipEvent(
        id="evt-carried-2", kind="conversation_turn", user_id=USER,
        entity_type="conversation", entity_id="conv-1",
        evidence_text="x", created_at=PRE,
    )
    assert resolver.origin_time_for_event(carried_stale) is None

    # Deferred rows: every ref must resolve post-T.
    host = env.nstore.create_thread(
        USER, title="host",
        evidence_refs=[SourceRef(kind="event", ref_id="ev-post")],
    )
    _sql(env.nstore, "INSERT INTO steward_deferred_prose (id, user_id, thread_id, kind, evidence_signature, evidence_refs_json, evidence_texts_json, created_at, status) VALUES ('def-mixed', ?, ?, 'birth', 's-mixed', '[\"event:evt-pre\", \"event:evt-post\"]', '{}', ?, 'pending')", (USER, host.id, POST2))
    _sql(env.nstore, "INSERT INTO steward_deferred_prose (id, user_id, thread_id, kind, evidence_signature, evidence_refs_json, evidence_texts_json, created_at, status) VALUES ('def-ok', ?, ?, 'birth', 's-ok', '[\"event:evt-post\"]', '{}', ?, 'pending')", (USER, host.id, POST2))
    _sql(env.nstore, "INSERT INTO steward_deferred_prose (id, user_id, thread_id, kind, evidence_signature, evidence_refs_json, evidence_texts_json, created_at, status) VALUES ('def-claim', ?, ?, 'birth', 's-claim', '[\"claim:claim-1\"]', '{}', ?, 'pending')", (USER, host.id, POST2))
    assert resolver.origin_time_for_ref("deferred_prose", "def-mixed") is None
    assert resolver.origin_time_for_ref("deferred_prose", "def-ok") is not None
    assert resolver.origin_time_for_ref("deferred_prose", "def-claim") is None


def test_08_partial_failure_yields_one_signed_incomplete_receipt(env, monkeypatch):
    """§8.7 test 8 / §8.2: a store step's failure produces exactly
    one signed incomplete receipt — per-store status lines, no
    completion coverage anywhere."""
    _thread_with_material(env.nstore)
    env.add_observation()

    def boom(user_id):
        raise RuntimeError("observations store unavailable")

    monkeypatch.setattr(env.ostore, "delete_for_user", boom)
    receipt = env.delete()
    assert receipt.summary["stores"]["observations"] == "incomplete"
    assert receipt.summary["stores"]["narrative"] == "verified"
    assert "INCOMPLETE" in receipt.summary["coverage"]
    assert "Erased: your narrative record" not in receipt.summary["coverage"]
    # The partial state is real: narrative gone, observations remain.
    assert env.nstore.erasure_recount(USER)["total"] == 0
    assert env.ostore.count_for_user(USER) == 1
    # Exactly one opened + one incomplete operation row; one
    # user-facing receipt from this invocation.
    op_rows = [
        r for r in env.istore.list_receipts() if r.summary.get("op_status")
    ]
    assert [r.summary["op_status"] for r in op_rows] == ["incomplete", "opened"]
    user_receipts = [
        r for r in env.istore.list_receipts() if not r.summary.get("op_status")
    ]
    assert len(user_receipts) == 1


def test_09_retry_resumes_same_operation(env, monkeypatch):
    """§8.7 test 9 / §9.1 Rev 3: after a partial failure, a later
    invocation resumes the SAME operation — same operation id,
    same boundary — and completes it."""
    _thread_with_material(env.nstore)
    env.add_observation()
    state = {"fail": True}

    def flaky(user_id):
        if state["fail"]:
            raise RuntimeError("down")
        return ObservationStore.delete_for_user(env.ostore, user_id)

    monkeypatch.setattr(env.ostore, "delete_for_user", flaky)
    first = env.delete()
    assert "INCOMPLETE" in first.summary["coverage"]
    tombstone_t = env.nstore.get_erasure_tombstone(USER)["erased_at"]

    state["fail"] = False
    second = env.delete()
    assert second.summary["stores"]["observations"] == "verified"
    assert second.summary["coverage"] == COVERAGE_STATEMENT
    # Same boundary, same operation, license still terminated.
    assert env.nstore.get_erasure_tombstone(USER)["erased_at"] == tombstone_t
    op_rows = [
        r for r in env.istore.list_receipts() if r.summary.get("op_status")
    ]
    assert len({r.summary["operation_id"] for r in op_rows}) == 1
    assert {r.summary["op_status"] for r in op_rows} == {
        "opened", "incomplete", "completed",
    }
    assert env.istore.get_license().status == "terminated"
    assert env.ostore.count_for_user(USER) == 0


def test_12_truthful_receipts(env):
    """§8.7 test 12 (as amended by Rev 4, governing reading 2):
    the user-facing receipt carries no user id and no erased-content
    identifiers; internal operation rows carry covered_user as the
    signed binding requires; the deletion writes no content-bearing
    line to the activity log (§6.5 fixture review)."""
    marker = "ZQXW-receipt-marker-title"
    thread = _thread_with_material(env.nstore, title=marker)
    receipt = env.delete()
    assert "covered_user" not in receipt.summary
    assert "operation_id" not in receipt.summary
    blob = json.dumps(receipt.summary)
    assert marker not in blob
    assert thread.id not in blob
    assert receipt.summary["coverage"] == COVERAGE_STATEMENT
    # The receipt's signature verifies over its own payload.
    from local_ai.identity.service import _receipt_payload
    from local_ai.identity.signing import verify_mapping

    assert verify_mapping(_receipt_payload(receipt), receipt.signature)
    # Internal rows DO carry the binding (and verify).
    records = read_operation_records(env.istore, USER)
    assert records.completed is not None
    assert records.completed.covered_user == USER
    # No content-bearing log line was emitted by the deletion.
    assert marker.encode() not in env.log.read_bytes()
    assert thread.id.encode() not in env.log.read_bytes()


def test_13_file_hygiene_anti_overclaim(env):
    """§8.7 test 13 / §8.5: the coverage language never claims
    backups, snapshots, Scope F stores, or the future; the receipt
    names only the four Scope S stores."""
    _thread_with_material(env.nstore)
    receipt = env.delete()
    coverage = receipt.summary["coverage"]
    assert "backups or snapshots, which this action cannot reach" in coverage
    assert "everything" not in coverage.lower()
    assert set(receipt.summary["stores"]) == {
        "presence", "narrative", "observations", "identity",
    }
    # The route surface carries the same statement, not the old
    # "Delete everything" summary.
    from api.routes.identity_routes import router

    delete_route = next(r for r in router.routes if r.path == "/identity/delete")
    assert delete_route.description == COVERAGE_STATEMENT
    assert "everything" not in (delete_route.summary or "").lower()


# ---------------------------------------------------------------------
# §9.5 tests 14–21 (flow-level subset)
# ---------------------------------------------------------------------


def test_14_provenance_audit_removes_ineligible_survivors(env):
    """§9.5 test 14: the audit re-derives eligibility from origin
    records (never the operation's own filter) and removes exactly
    the survivors that fail it."""
    env.delete()  # completed operation; tombstones stand at the op's T
    op_t = env.nstore.get_erasure_tombstone(USER)["erased_at"]
    # Plant survivors the way history can produce them: rows written
    # while no barrier stood (pre-D2 binary / pre-barrier window),
    # then the barrier restored. Fixture-level surgery, narrated.
    _sql(env.nstore, "DELETE FROM steward_erasure_tombstones WHERE user_id = ?", (USER,))
    _sql(env.nstore, "INSERT INTO narrative_threads (id, user_id, origin, title, status, created_at, updated_at) VALUES ('thr-rogue', ?, 'steward_proposal', 'rogue', 'standing', ?, ?)", (USER, PRE, PRE))
    _sql(env.nstore, "INSERT INTO narrative_threads (id, user_id, origin, title, status, created_at, updated_at) VALUES ('thr-eligible', ?, 'user_declared', 'eligible', 'standing', ?, ?)", (USER, POST, POST))
    env.nstore.write_erasure_tombstone(USER, op_t, "op-audit")
    _sql(env.ostore, "DELETE FROM steward_erasure_tombstones WHERE user_id = ?", (USER,))
    env.add_observation(event_ref="evt-pre")
    env.add_observation(event_ref="evt-post")
    env.ostore.write_erasure_tombstone(USER, op_t, "op-audit")
    _write_log(env.log, [
        _log_record(_turn_event("evt-pre", "x"), PRE),
        _log_record(_turn_event("evt-post", "x"), POST),
    ])
    resolver = ProvenanceResolver(
        USER, op_t, narrative_store=env.nstore,
        observation_store=env.ostore, log_path=env.log,
    )
    result = audit_narrative_store(env.nstore, USER, resolver)
    assert ("thread", "thr-rogue") in result["failures"]
    assert env.nstore.get_thread(USER, "thr-rogue") is None
    assert env.nstore.get_thread(USER, "thr-eligible") is not None
    obs_result = audit_observation_store(env.ostore, USER, resolver)
    assert obs_result["removed"] == 1
    remaining = env.ostore.list_for_user(USER)
    assert [o.event_ref for o in remaining] == ["evt-post"]


def test_17_incomplete_barrier_recovery(env):
    """§9.5 test 17 / §9.4 Rev 4: a standing opened record with NO
    tombstones (crash after step 0) holds derivation and recovers
    both barriers at the record's T; the next check proceeds."""
    _save_operation_row(
        env.istore, license_id=env.license_id, operation_id="op-crash",
        status="opened", covered_user=USER, erased_at=T,
        stores={}, counts={},
    )
    verdict = check_barrier_integrity(
        USER, narrative_store=env.nstore, observation_store=env.ostore,
        operation_reader=env.reader,
    )
    assert verdict.state == "hold"
    assert set(verdict.recovered) == {"narrative", "observations"}
    assert env.nstore.get_erasure_tombstone(USER)["erased_at"] == T
    assert env.ostore.get_erasure_tombstone(USER)["erased_at"] == T
    verdict2 = check_barrier_integrity(
        USER, narrative_store=env.nstore, observation_store=env.ostore,
        operation_reader=env.reader,
    )
    assert verdict2.state == "proceed"
    assert verdict2.erased_at == T


def test_19_resume_after_license_termination(env, monkeypatch):
    """§9.5 test 19 / §9.1 Rev 3: the first attempt terminates the
    license and clears the ledger but leaves narrative incomplete;
    the resume runs with the license terminated, does not resurrect
    it, does not re-draw on the consumed grant, and completes under
    the original boundary against the terminated license's id."""
    _thread_with_material(env.nstore)
    state = {"fail": True}
    real_erase = NarrativeStore.erase_user_material

    def flaky_erase(self, user_id, **kwargs):
        if state["fail"]:
            raise RuntimeError("narrative store locked")
        return real_erase(self, user_id, **kwargs)

    monkeypatch.setattr(NarrativeStore, "erase_user_material", flaky_erase)
    first = env.delete()
    assert first.summary["stores"]["narrative"] == "incomplete"
    assert first.summary["stores"]["identity"] == "verified"
    assert env.istore.get_license().status == "terminated"
    assert env.istore.list_scope_events() == []  # grant consumed

    state["fail"] = False
    second = env.delete()
    assert second.summary["stores"]["narrative"] == "verified"
    assert second.license_id == env.license_id  # terminated license's id
    assert env.istore.get_license().status == "terminated"  # not resurrected
    assert env.nstore.erasure_recount(USER)["total"] == 0
    records = read_operation_records(env.istore, USER)
    assert records.completed is not None


def test_20_barrier_integrity_classification(env):
    """§9.5 test 20 / §9.4: divergent barriers against a record hold
    WITHOUT any barrier being written by the check; tombstones with
    no record hold and report; a completed record with agreeing
    barriers proceeds."""
    _save_operation_row(
        env.istore, license_id=env.license_id, operation_id="op-20",
        status="incomplete", covered_user=USER, erased_at=T,
        stores={}, counts={},
    )
    env.nstore.write_erasure_tombstone(USER, T, "op-20")
    env.ostore.write_erasure_tombstone(USER, PRE, "op-20")  # divergent
    verdict = check_barrier_integrity(
        USER, narrative_store=env.nstore, observation_store=env.ostore,
        operation_reader=env.reader,
    )
    assert verdict.state == "hold"
    assert verdict.conflict
    # The check wrote nothing: the divergent barrier stands as found.
    assert env.ostore.get_erasure_tombstone(USER)["erased_at"] == PRE

    # No record at all: hold, no boundary invented.
    env2 = Env(env.dir / "norecord")
    env2.nstore.write_erasure_tombstone(USER, T, "op-ghost")
    verdict2 = check_barrier_integrity(
        USER, narrative_store=env2.nstore, observation_store=env2.ostore,
        operation_reader=env2.reader,
    )
    assert verdict2.state == "hold"

    # Completed record + agreeing barriers: proceed.
    env3 = Env(env.dir / "done")
    _save_operation_row(
        env3.istore, license_id=env3.license_id, operation_id="op-done",
        status="completed", covered_user=USER, erased_at=T,
        stores={}, counts={},
    )
    env3.nstore.write_erasure_tombstone(USER, T, "op-done")
    env3.ostore.write_erasure_tombstone(USER, T, "op-done")
    verdict3 = check_barrier_integrity(
        USER, narrative_store=env3.nstore, observation_store=env3.ostore,
        operation_reader=env3.reader,
    )
    assert verdict3.state == "proceed"


# ---------------------------------------------------------------------
# Rev 4 tests 22–23
# ---------------------------------------------------------------------


def _tamper_receipt(env, receipt_id, **changes):
    rows = env.istore.list_receipts()
    row = next(r for r in rows if r.receipt_id == receipt_id)
    summary = dict(row.summary)
    summary.update(changes)
    with env.istore._lock:
        env.istore._conn.execute(
            "UPDATE deletion_receipts SET summary_json = ? WHERE receipt_id = ?",
            (json.dumps(summary), receipt_id),
        )
        env.istore._conn.commit()


def test_22_signed_owner_binding_substitution(env):
    """Rev 4 test 22 / Correction B: substituting ANY bound element
    of the signed operation record fails verification at BOTH
    consumers — the retry (delete flow) and autonomous recovery
    (barrier check) — and nothing is deleted or written."""
    for element, forged in [
        ("covered_user", OTHER),
        ("erased_at", PRE),
        ("scope", "takeout:export"),
        ("operation_id", "op-forged"),
    ]:
        case = Env(env.dir / f"case-{element}")
        _thread_with_material(case.nstore)
        row = _save_operation_row(
            case.istore, license_id=case.license_id,
            operation_id="op-22", status="opened", covered_user=USER,
            erased_at=T, stores={}, counts={},
        )
        _tamper_receipt(case, row.receipt_id, **{element: forged})
        records = read_operation_records(case.istore, USER)
        assert records.conflict, element
        assert records.standing is None
        # Consumer 1: retry refuses, deletes nothing.
        with pytest.raises(ErasureRefused):
            case.delete()
        assert case.nstore.erasure_recount(USER)["total"] > 0
        # Consumer 2: autonomous recovery holds, writes no barrier.
        verdict = check_barrier_integrity(
            USER, narrative_store=case.nstore,
            observation_store=case.ostore, operation_reader=case.reader,
        )
        assert verdict.state == "hold", element
        assert verdict.conflict, element
        assert case.nstore.get_erasure_tombstone(USER) is None


def test_23_crash_recovery_and_state_machine_interpretation(env):
    """Rev 4 test 23 + the founder's state-machine interpretation:
    an opened record with NO tombstones (crash after step 0) holds
    derivation while integrity is missing/reconciling; once the
    barriers verify against the record, later passes derive ONLY
    from eligible post-erasure sources — with the operation STILL
    incomplete. Barrier integrity is not deletion completion."""
    _save_operation_row(
        env.istore, license_id=env.license_id, operation_id="op-23",
        status="opened", covered_user=USER, erased_at=T,
        stores={}, counts={},
    )
    old_records, old_rows = _meeting_pair("conv-23-old", PRE)
    new_records, new_rows = _meeting_pair("conv-23-new", POST)
    meeting_rows = old_rows + new_rows
    provider = lambda user_id: meeting_rows  # noqa: E731
    _write_log(env.log, old_records + new_records)

    # Pass 1: integrity missing → hold. Nothing is consumed,
    # nothing derived, the cursor does not move — but the barriers
    # are recovered at the record's T during this pass.
    res1 = run_sweep_for_user(
        env.nstore, USER, log_path=env.log, generate_fn=_gen(),
        consent_reader=lambda user_id: True,
        operation_reader=env.reader, observation_store=env.ostore,
        meeting_provider=provider,
    )
    assert res1.barrier is not None and res1.barrier["state"] == "hold"
    assert res1.barrier_holds == 1
    assert res1.offset_after == 0
    assert env.nstore.erasure_recount(USER)["total"] == 0
    assert env.nstore.get_erasure_tombstone(USER)["erased_at"] == T
    assert env.ostore.get_erasure_tombstone(USER)["erased_at"] == T

    # Pass 2: barriers verify against the record → derivation
    # proceeds under eligibility. The pre-T event is
    # consumed-skipped; the post-T event derives. The operation is
    # STILL incomplete — no transition row exists.
    res2 = run_sweep_for_user(
        env.nstore, USER, log_path=env.log, generate_fn=_gen(),
        consent_reader=lambda user_id: True,
        operation_reader=env.reader, observation_store=env.ostore,
        meeting_provider=provider,
    )
    assert res2.barrier["state"] == "proceed"
    assert res2.events_erasure_skipped >= 1
    assert env.nstore.erasure_recount(USER)["narrative_threads"] >= 1
    records = read_operation_records(env.istore, USER)
    assert records.standing is not None
    assert records.standing.status == "opened"  # still incomplete
    assert records.completed is None
