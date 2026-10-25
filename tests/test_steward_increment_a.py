"""Steward increment A — ledger slice (proposal §9/§10).

Covers the proposal's acceptance tests for increment A only:
event→ledger wiring (meeting_completed first), idempotency,
batching + byte-offset cursor (partial line, rotation, shrink,
timestamp-order skew), deferred recovery (§6.4 exact scenario +
crash windows + lease expiry), provisionality (nascent/proposed
only, no promotion, single-event births nothing), no-fabrication
(records-first with gen None / raising gen), turn-path-clean,
per-user scoping, provenance, consent gating (fail-closed,
withdrawal at the next batch boundary, no retroactive derivation),
and the ignored-retention prune (hard delete, steward threads only).

All generations are fake/counting/raising. Stores are tmp SQLite
files; activity logs are tmp JSONL files. No surface is touched:
no UI, no dialogue, no fellowship-derivation change.
"""

from __future__ import annotations

import ast
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from local_ai.fellowship.events import FellowshipEvent
from local_ai.narrative import NarrativeStore
from local_ai.narrative.consent import steward_consent_allowed
from local_ai.narrative.derivation import (
    StewardPipeline,
    analyze_for_threads,
    derive_batch,
    event_to_item,
    work_deferred_prose,
)
from local_ai.narrative import sweep as sweep_mod
from local_ai.narrative.refs import SourceRef
from local_ai.narrative.sweep import (
    prune_ignored_threads,
    run_sweep_for_user,
)

USER = "user-1"
OTHER = "user-2"
ENTITY = "meeting:mentor-k1"
FOCUS_TEXT = "cultivation in the orchard, learning what ripens"

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


def _store(tmp_path):
    return NarrativeStore(db_path=tmp_path / "narrative.db")


def _event(event_id, text, kind="meeting_completed", user=USER, entity=ENTITY):
    entity_type, _, entity_id = entity.partition(":")
    return FellowshipEvent(
        id=event_id,
        kind=kind,
        user_id=user,
        entity_type=entity_type,
        entity_id=entity_id,
        evidence_text=text,
        summary="meeting turn",
        payload={"archetype_id": "mentor", "keystone_index": 1},
    )


def _counting_gen(payload, calls):
    def gen(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return payload

    return gen


def _raising_gen(prompt, **kwargs):
    raise RuntimeError("backend down")


def _log_record(event, created_at="2026-10-25T00:00:00+00:00"):
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


def _line(record):
    return json.dumps(record, ensure_ascii=False) + "\n"


def _write_log(path, chunks):
    with path.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(chunk)


def _two_meeting_log(path):
    _write_log(
        path,
        [
            _line(_log_record(_event("evt-1", FOCUS_TEXT))),
            _line(_log_record(_event("evt-2", FOCUS_TEXT + " again"))),
        ],
    )


def _threads(store, user):
    return store.threads_for(user)


def _readings(store, user, thread_id):
    return store.readings_for(user, thread_id)


def _deferred(store, user, status=None):
    return store.deferred_prose_for(user, status=status)


def _perm_conn(tmp_path, flags_by_user):
    """A tmp permissions DB (VE storage shape, minimal DDL)."""
    db = tmp_path / "ve.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE user_permissions_settings ("
        "user_id TEXT PRIMARY KEY, consent_given INTEGER, "
        "consent_version TEXT, consent_at TEXT, "
        "permissions_json TEXT, updated_at TEXT)"
    )
    for user_id, flags in flags_by_user.items():
        conn.execute(
            "INSERT INTO user_permissions_settings VALUES "
            "(?, 1, 'permissions-v1', NULL, ?, '')",
            (user_id, json.dumps(flags)),
        )
    conn.commit()
    return conn


# -- consent gate ------------------------------------------------------------


def test_consent_gate_reads_flag_only(tmp_path):
    """Gate truth table: on only when the flag itself is true."""
    conn = _perm_conn(
        tmp_path,
        {
            "u-on": {"steward_derivation": True},
            "u-off": {"steward_derivation": False},
            "u-missing": {"behavioral_tracking": True},
            "u-bad": {},
        },
    )
    # Malformed JSON row for u-bad: rewrite its blob unparseable.
    conn.execute(
        "UPDATE user_permissions_settings SET permissions_json = 'not-json' "
        "WHERE user_id = 'u-bad'"
    )
    conn.commit()
    assert steward_consent_allowed("u-on", connection=conn) is True
    assert steward_consent_allowed("u-off", connection=conn) is False
    assert steward_consent_allowed("u-missing", connection=conn) is False
    assert steward_consent_allowed("u-bad", connection=conn) is False
    assert steward_consent_allowed("u-norow", connection=conn) is False
    assert steward_consent_allowed("", connection=conn) is False
    assert steward_consent_allowed(None, connection=conn) is False


def test_consent_gate_never_uses_inserting_helper(tmp_path, monkeypatch):
    """The gate must never call get_user_permissions_settings: that
    helper INSERTs a row for unknown users. Unknown users stay
    rowless after a gate check."""
    import local_ai.vision_execution.storage as ve_storage

    conn = _perm_conn(tmp_path, {"u-on": {"steward_derivation": True}})

    def _boom(user_id):
        raise AssertionError("inserting helper must not be called")

    monkeypatch.setattr(ve_storage, "get_connection", lambda: conn)
    monkeypatch.setattr(ve_storage, "get_user_permissions_settings", _boom)
    assert steward_consent_allowed("u-on") is True
    assert steward_consent_allowed("u-norow") is False
    rows = conn.execute(
        "SELECT user_id FROM user_permissions_settings"
    ).fetchall()
    assert [r[0] for r in rows] == ["u-on"]


def test_pipeline_gates_install_path(tmp_path):
    """Install-path runs check the reader: closed = no derivation,
    open = derivation. Direct-drive pipelines without a reader stay
    ungated (tests/tools only)."""
    store = _store(tmp_path)
    calls: list = []

    closed = StewardPipeline(
        store=store,
        generate_fn=_counting_gen(BIRTH_JSON, calls),
        scheduler=lambda fn: fn(),
        consent_reader=lambda user_id: False,
    )
    closed.schedule_batch(
        USER,
        [
            event_to_item(_event("evt-1", FOCUS_TEXT)),
            event_to_item(_event("evt-2", FOCUS_TEXT + " again")),
        ],
    )
    assert calls == []
    assert _threads(store, USER) == []

    open_pipe = StewardPipeline(
        store=store,
        generate_fn=_counting_gen(BIRTH_JSON, calls),
        scheduler=lambda fn: fn(),
        consent_reader=lambda user_id: True,
    )
    open_pipe.schedule_batch(
        USER,
        [
            event_to_item(_event("evt-1", FOCUS_TEXT)),
            event_to_item(_event("evt-2", FOCUS_TEXT + " again")),
        ],
    )
    assert len(calls) == 1
    assert len(_threads(store, USER)) == 1


def test_pipeline_skips_non_meeting_kinds(tmp_path):
    """Install-path rollout: meeting completions only. A
    conversation_turn never derives on the install path, even with
    consent open and a live thread to extend."""
    store = _store(tmp_path)
    calls: list = []
    gen = _counting_gen(BIRTH_JSON, calls)
    derive_batch(
        USER,
        [
            event_to_item(_event("evt-1", FOCUS_TEXT)),
            event_to_item(_event("evt-2", FOCUS_TEXT + " again")),
        ],
        store,
        generate_fn=gen,
    )
    assert len(_threads(store, USER)) == 1
    calls.clear()
    pipe = StewardPipeline(
        store=store,
        generate_fn=gen,
        scheduler=lambda fn: fn(),
        consent_reader=lambda user_id: True,
    )
    pipe.schedule_event(_event("evt-3", FOCUS_TEXT, kind="conversation_turn"))
    assert calls == []
    assert len(_readings(store, USER, _threads(store, USER)[0].id)) == 1


def test_install_default_pipeline_gates_by_default(tmp_path, monkeypatch):
    """The installed pipeline always gates: its default reader is
    the production reader, and a flag-off user derives nothing
    through it while a flag-on user extends."""
    import local_ai.narrative.derivation as derivation_mod
    import local_ai.vision_execution.storage as ve_storage
    from local_ai.narrative.consent import steward_consent_allowed

    conn = _perm_conn(tmp_path, {USER: {"steward_derivation": False}})
    monkeypatch.setattr(ve_storage, "get_connection", lambda: conn)
    store = _store(tmp_path)
    calls: list = []
    try:
        pipe = derivation_mod.install_default_pipeline(
            store=store,
            generate_fn=_counting_gen(BIRTH_JSON, calls),
            scheduler=lambda fn: fn(),
        )
        assert pipe._consent_reader is steward_consent_allowed
        pipe.schedule_event(_event("evt-1", FOCUS_TEXT))
        assert calls == []
        conn.execute(
            "UPDATE user_permissions_settings SET permissions_json = ? "
            "WHERE user_id = ?",
            (json.dumps({"steward_derivation": True}), USER),
        )
        conn.commit()
        # Gate open, but a single event births nothing (≥2 rule) —
        # so seed a thread directly, then extend through the pipe.
        derive_batch(
            USER,
            [
                event_to_item(_event("evt-1", FOCUS_TEXT)),
                event_to_item(_event("evt-2", FOCUS_TEXT + " again")),
            ],
            store,
            generate_fn=_counting_gen(BIRTH_JSON, calls),
        )
        calls.clear()
        pipe.schedule_event(_event("evt-3", FOCUS_TEXT + " once more"))
        assert len(calls) == 1
    finally:
        derivation_mod._PIPELINE = None


# -- deferred recovery (§6.4) -------------------------------------------------


def test_deferred_recovery_exact_scenario(tmp_path, monkeypatch):
    """§6.4 acceptance bar, derive level: records stored → prose
    fails → restart (new store instance) → backend back → reading
    proposed EXACTLY ONCE, second pass finds nothing owed."""
    import local_ai.narrative.derivation as derivation_mod

    db_path = tmp_path / "narrative.db"
    store = NarrativeStore(db_path=db_path)
    # No-backend derive only: scope the resolver patch to this call
    # so the later worker phase uses the real resolver + counting gen.
    with monkeypatch.context() as mp:
        mp.setattr(derivation_mod, "_resolve_generate_fn", lambda gen: None)
        result = derive_batch(
            USER,
            [
                event_to_item(_event("evt-1", FOCUS_TEXT)),
                event_to_item(_event("evt-2", FOCUS_TEXT + " again")),
            ],
            store,
            generate_fn=None,
        )
    assert result.readings == []
    assert len(result.deferred) == 1
    threads = _threads(store, USER)
    assert len(threads) == 1
    assert threads[0].status == "nascent"
    assert _readings(store, USER, threads[0].id) == []
    rows = _deferred(store, USER, status="pending")
    assert len(rows) == 1
    store.close()

    # Process restart: a new store instance on the same file.
    store2 = NarrativeStore(db_path=db_path)
    assert len(_deferred(store2, USER, status="pending")) == 1
    calls: list = []
    worked = work_deferred_prose(
        store2, USER, generate_fn=_counting_gen(BIRTH_JSON, calls)
    )
    assert len(worked.rendered) == 1
    assert len(calls) == 1
    assert len(_readings(store2, USER, threads[0].id)) == 1
    assert _deferred(store2, USER, status="done")
    assert _deferred(store2, USER, status="pending") == []
    worked2 = work_deferred_prose(
        store2, USER, generate_fn=_counting_gen(BIRTH_JSON, calls)
    )
    assert worked2.rendered == []
    assert len(calls) == 1
    assert len(_readings(store2, USER, threads[0].id)) == 1
    store2.close()


def test_deferred_recovery_through_sweep(tmp_path):
    """§6.4 full scenario: evidence stored → prose fails → cursor
    advances → restart → backend back → reading exactly once."""
    log_path = tmp_path / "activity.log"
    _write_log(
        log_path,
        [
            _line(_log_record(_event("evt-1", FOCUS_TEXT))),
            _line(_log_record(_event("evt-2", FOCUS_TEXT + " again"))),
            _line(_log_record(_event("evt-x", "other", kind="conversation_turn"))),
            _line(
                _log_record(
                    _event("evt-o", FOCUS_TEXT, user=OTHER, entity="meeting:other-k1")
                )
            ),
        ],
    )
    db_path = tmp_path / "narrative.db"
    store = NarrativeStore(db_path=db_path)
    res1 = run_sweep_for_user(
        store,
        USER,
        log_path=log_path,
        generate_fn=_raising_gen,
        consent_reader=lambda user_id: True,
    )
    assert res1.events_derived == 2
    assert res1.offset_after == log_path.stat().st_size
    threads = _threads(store, USER)
    assert len(threads) == 1
    assert _readings(store, USER, threads[0].id) == []
    assert len(_deferred(store, USER, status="pending")) == 1
    assert _threads(store, OTHER) == []
    store.close()

    store2 = NarrativeStore(db_path=db_path)
    calls: list = []
    res2 = run_sweep_for_user(
        store2,
        USER,
        log_path=log_path,
        generate_fn=_counting_gen(BIRTH_JSON, calls),
        consent_reader=lambda user_id: True,
    )
    assert res2.deferred is not None
    assert len(res2.deferred["rendered"]) == 1
    assert len(_readings(store2, USER, threads[0].id)) == 1
    res3 = run_sweep_for_user(
        store2,
        USER,
        log_path=log_path,
        generate_fn=_counting_gen(BIRTH_JSON, calls),
        consent_reader=lambda user_id: True,
    )
    assert res3.deferred is not None
    assert res3.deferred["rendered"] == []
    assert len(_readings(store2, USER, threads[0].id)) == 1
    assert len(calls) == 1
    store2.close()


def test_deferred_completion_guard_no_rerender(tmp_path):
    """Crash between reading commit and row-done commit: a reading
    already covers the evidence → worker marks done WITHOUT
    spending a generation and without duplicating."""
    store = _store(tmp_path)
    derive_batch(
        USER,
        [
            event_to_item(_event("evt-1", FOCUS_TEXT)),
            event_to_item(_event("evt-2", FOCUS_TEXT + " again")),
        ],
        store,
        generate_fn=_raising_gen,
    )
    thread = _threads(store, USER)[0]
    # Pre-seed the crash state: reading exists, row still pending.
    evidence = store.evidence_for(USER, thread.id)
    store.propose_reading(
        USER,
        thread.id,
        author="steward",
        reading={"tensions": [], "open_questions": [], "milestones": []},
        evidence_refs=[e.id for e in evidence],
        scales=["personal"],
        primary_scale="personal",
    )
    assert len(_deferred(store, USER, status="pending")) == 1
    calls: list = []
    worked = work_deferred_prose(
        store, USER, generate_fn=_counting_gen(BIRTH_JSON, calls)
    )
    assert calls == []
    assert worked.already_covered != []
    assert worked.rendered == []
    assert len(_readings(store, USER, thread.id)) == 1
    assert _deferred(store, USER, status="done")


def test_record_commit_without_offset_advance_no_dup(tmp_path):
    """Crash after record commit, before offset advance: the next
    sweep re-reads the segment and is a no-op — no duplicate rows,
    no second deferred row."""
    log_path = tmp_path / "activity.log"
    _two_meeting_log(log_path)
    store = _store(tmp_path)
    run_sweep_for_user(
        store,
        USER,
        log_path=log_path,
        generate_fn=_raising_gen,
        consent_reader=lambda user_id: True,
    )
    assert len(_threads(store, USER)) == 1
    assert len(_deferred(store, USER)) == 1
    # Simulate the crash: offset never advanced.
    pos = store.get_processing_position(USER)
    store.set_processing_position(USER, 0, pos["file_identity"])
    run_sweep_for_user(
        store,
        USER,
        log_path=log_path,
        generate_fn=_raising_gen,
        consent_reader=lambda user_id: True,
    )
    assert len(_threads(store, USER)) == 1
    assert len(_deferred(store, USER)) == 1
    assert _readings(store, USER, _threads(store, USER)[0].id) == []


def test_lease_expiry_retries(tmp_path):
    """A stale rendering row returns to pending and is retried,
    not lost and not duplicated."""
    store = _store(tmp_path)
    derive_batch(
        USER,
        [
            event_to_item(_event("evt-1", FOCUS_TEXT)),
            event_to_item(_event("evt-2", FOCUS_TEXT + " again")),
        ],
        store,
        generate_fn=_raising_gen,
    )
    row = _deferred(store, USER, status="pending")[0]
    claimed = store.claim_deferred_prose(USER, row["id"])
    assert claimed is not None and claimed["attempts"] == 1
    # Age the lease directly (crash-state seeding).
    conn = sqlite3.connect(str(tmp_path / "narrative.db"))
    conn.execute(
        "UPDATE steward_deferred_prose SET last_attempt_at = "
        "'2000-01-01T00:00:00+00:00' WHERE id = ?",
        (row["id"],),
    )
    conn.commit()
    conn.close()
    calls: list = []
    worked = work_deferred_prose(
        store, USER, generate_fn=_counting_gen(BIRTH_JSON, calls)
    )
    assert len(worked.rendered) == 1
    done = _deferred(store, USER, status="done")[0]
    assert done["attempts"] == 2


def test_no_backend_no_row_churn(tmp_path, monkeypatch):
    """No backend, no churn: pending rows wait, attempts do not
    move for backend absence, and the run reports deferred."""
    import local_ai.narrative.derivation as derivation_mod

    monkeypatch.setattr(
        derivation_mod, "_resolve_generate_fn", lambda gen: None
    )
    store = _store(tmp_path)
    result = derive_batch(
        USER,
        [
            event_to_item(_event("evt-1", FOCUS_TEXT)),
            event_to_item(_event("evt-2", FOCUS_TEXT + " again")),
        ],
        store,
        generate_fn=None,
    )
    assert result.readings == []
    assert len(result.deferred) == 1
    assert _readings(store, USER, _threads(store, USER)[0].id) == []
    worked = work_deferred_prose(store, USER, generate_fn=None)
    assert worked.skipped_no_backend is True
    assert worked.rendered == []
    pending = _deferred(store, USER, status="pending")
    assert len(pending) == 1
    assert pending[0]["attempts"] == 0


# -- cursor ------------------------------------------------------------------


def test_offset_advances_only_on_batch_success(tmp_path, monkeypatch):
    """A failed batch leaves the offset unmoved; the next pass
    retries the same segment and succeeds."""
    log_path = tmp_path / "activity.log"
    _two_meeting_log(log_path)
    store = _store(tmp_path)
    real = sweep_mod.derive_batch
    state = {"fail_once": True}

    def flaky(*args, **kwargs):
        if state["fail_once"]:
            state["fail_once"] = False
            raise RuntimeError("boom")
        return real(*args, **kwargs)

    monkeypatch.setattr(sweep_mod, "derive_batch", flaky)
    res1 = run_sweep_for_user(
        store,
        USER,
        log_path=log_path,
        generate_fn=_raising_gen,
        consent_reader=lambda user_id: True,
    )
    assert store.get_processing_position(USER)["byte_offset"] == 0
    assert _threads(store, USER) == []
    res2 = run_sweep_for_user(
        store,
        USER,
        log_path=log_path,
        generate_fn=_raising_gen,
        consent_reader=lambda user_id: True,
    )
    assert res2.offset_after == log_path.stat().st_size
    assert len(_threads(store, USER)) == 1


def test_partial_trailing_line_held_and_reread(tmp_path):
    """A sweep never advances past an incomplete trailing line;
    the next sweep re-reads it complete."""
    log_path = tmp_path / "activity.log"
    line1 = _line(_log_record(_event("evt-1", FOCUS_TEXT)))
    line2 = _line(_log_record(_event("evt-2", FOCUS_TEXT + " again")))
    full3 = _line(_log_record(_event("evt-3", FOCUS_TEXT + " once more")))
    cut = len(full3) // 2
    _write_log(log_path, [line1, line2, full3[:cut]])
    store = _store(tmp_path)
    res1 = run_sweep_for_user(
        store,
        USER,
        log_path=log_path,
        generate_fn=_raising_gen,
        consent_reader=lambda user_id: True,
    )
    assert res1.has_partial_trailing_line is True
    assert store.get_processing_position(USER)["byte_offset"] == len(
        line1 + line2
    )
    assert len(_threads(store, USER)) == 1
    assert len(_deferred(store, USER)) == 1
    # Complete the torn line.
    with log_path.open("a", encoding="utf-8") as f:
        f.write(full3[cut:])
    res2 = run_sweep_for_user(
        store,
        USER,
        log_path=log_path,
        generate_fn=_raising_gen,
        consent_reader=lambda user_id: True,
    )
    assert res2.has_partial_trailing_line is False
    assert store.get_processing_position(USER)["byte_offset"] == (
        log_path.stat().st_size
    )
    assert len(_threads(store, USER)) == 1
    assert len(_deferred(store, USER)) == 2


def test_rotation_guard_rescans(tmp_path):
    """A changed file identity invalidates the offset: bounded
    full rescan, logged, never blind offset trust."""
    log_path = tmp_path / "activity.log"
    _two_meeting_log(log_path)
    store = _store(tmp_path)
    run_sweep_for_user(
        store,
        USER,
        log_path=log_path,
        generate_fn=_raising_gen,
        consent_reader=lambda user_id: True,
    )
    assert len(_threads(store, USER)) == 1
    new_path = tmp_path / "activity.new"
    _write_log(
        new_path,
        [
            _line(
                _log_record(
                    _event("evt-9", FOCUS_TEXT, entity="meeting:guardian-k1")
                )
            ),
            _line(
                _log_record(
                    _event(
                        "evt-10",
                        FOCUS_TEXT + " again",
                        entity="meeting:guardian-k1",
                    )
                )
            ),
        ],
    )
    os.replace(new_path, log_path)
    res = run_sweep_for_user(
        store,
        USER,
        log_path=log_path,
        generate_fn=_raising_gen,
        consent_reader=lambda user_id: True,
    )
    assert res.rescanned is True
    assert len(_threads(store, USER)) == 2


def test_shrink_guard_rescans(tmp_path):
    """A file smaller than the stored offset (truncation, same
    inode) also forces a rescan instead of blind trust."""
    log_path = tmp_path / "activity.log"
    _two_meeting_log(log_path)
    store = _store(tmp_path)
    run_sweep_for_user(
        store,
        USER,
        log_path=log_path,
        generate_fn=_raising_gen,
        consent_reader=lambda user_id: True,
    )
    assert store.get_processing_position(USER)["byte_offset"] > 0
    with log_path.open("r+b") as f:
        f.truncate(10)
    res = run_sweep_for_user(
        store,
        USER,
        log_path=log_path,
        generate_fn=_raising_gen,
        consent_reader=lambda user_id: True,
    )
    assert res.rescanned is True
    assert store.get_processing_position(USER)["byte_offset"] == 0


def test_cursor_order_skew_all_events_processed(tmp_path):
    """File order ≠ created_at order (descheduled writer) must not
    skip anything: the byte offset sees every line regardless of
    timestamp. A timestamp cursor would fail this test."""
    log_path = tmp_path / "activity.log"
    _write_log(
        log_path,
        [
            _line(
                _log_record(
                    _event("evt-late", FOCUS_TEXT),
                    created_at="2026-10-25T00:00:02+00:00",
                )
            ),
            _line(
                _log_record(
                    _event("evt-early", FOCUS_TEXT + " again"),
                    created_at="2026-10-25T00:00:01+00:00",
                )
            ),
        ],
    )
    store = _store(tmp_path)
    res = run_sweep_for_user(
        store,
        USER,
        log_path=log_path,
        generate_fn=_raising_gen,
        consent_reader=lambda user_id: True,
    )
    assert res.events_derived == 2
    thread = _threads(store, USER)[0]
    keys = {(e.ref_kind, e.ref_id) for e in store.evidence_for(USER, thread.id)}
    assert ("event", "evt-late") in keys
    assert ("event", "evt-early") in keys


def test_batch_bounded_50(tmp_path):
    """No batch exceeds 50 fellowship events for the user: 120
    events take 3 batches, not 1."""
    log_path = tmp_path / "activity.log"
    _write_log(
        log_path,
        [
            _line(_log_record(_event(f"evt-{i}", FOCUS_TEXT)))
            for i in range(120)
        ],
    )
    store = _store(tmp_path)
    res = run_sweep_for_user(
        store,
        USER,
        log_path=log_path,
        generate_fn=_raising_gen,
        consent_reader=lambda user_id: True,
    )
    assert res.batches == 3
    assert res.events_derived == 120
    assert res.offset_after == log_path.stat().st_size


# -- provisionality / no-fabrication ------------------------------------------


def test_provisionality_nascent_proposed_only(tmp_path):
    """Births land nascent, readings land proposed; re-analysis
    with no new evidence adds zero rows; a candidate left alone
    stays nascent/proposed — never auto-resolved."""
    store = _store(tmp_path)
    calls: list = []
    gen = _counting_gen(BIRTH_JSON, calls)
    items = [
        event_to_item(_event("evt-1", FOCUS_TEXT)),
        event_to_item(_event("evt-2", FOCUS_TEXT + " again")),
    ]
    derive_batch(USER, items, store, generate_fn=gen)
    thread = _threads(store, USER)[0]
    assert thread.status == "nascent"
    reading = _readings(store, USER, thread.id)[0]
    assert reading.status == "proposed"
    assert store.threads_for(USER, status="active") == []
    derive_batch(USER, items, store, generate_fn=gen)
    assert len(_threads(store, USER)) == 1
    assert len(_readings(store, USER, thread.id)) == 1
    assert store.get_thread(USER, thread.id).status == "nascent"


def test_derivation_never_promotes(tmp_path):
    """Derivation makes no set_thread_status call across a birth +
    extension run (promotion is a visitor act, later increment)."""
    store = _store(tmp_path)
    calls: list = []
    gen = _counting_gen(BIRTH_JSON, calls)
    derive_batch(
        USER,
        [
            event_to_item(_event("evt-1", FOCUS_TEXT)),
            event_to_item(_event("evt-2", FOCUS_TEXT + " again")),
        ],
        store,
        generate_fn=gen,
    )

    def _boom(*args, **kwargs):
        raise AssertionError("derivation must never set thread status")

    store.set_thread_status = _boom  # type: ignore[method-assign]
    derive_batch(
        USER,
        [event_to_item(_event("evt-3", FOCUS_TEXT + " once more"))],
        store,
        generate_fn=_counting_gen(EXTENSION_JSON, calls),
    )
    assert store.get_thread(USER, _threads(store, USER)[0].id).status == "nascent"


def test_single_meeting_event_births_nothing(tmp_path):
    """A meeting-completion event alone proves a meeting happened;
    it births no substantive thread (≥2-to-birth rule)."""
    store = _store(tmp_path)
    analyze_for_threads(_event("evt-1", FOCUS_TEXT), store, generate_fn=_raising_gen)
    assert _threads(store, USER) == []
    log_path = tmp_path / "activity.log"
    _write_log(log_path, [_line(_log_record(_event("evt-1", FOCUS_TEXT)))])
    res = run_sweep_for_user(
        store,
        USER,
        log_path=log_path,
        generate_fn=_raising_gen,
        consent_reader=lambda user_id: True,
    )
    assert res.events_derived == 1
    assert _threads(store, USER) == []
    assert res.offset_after == log_path.stat().st_size


def test_no_fabrication_gen_raises(tmp_path):
    """Generation failure is deferred, never success and never
    decline: records + deferred row land, zero readings."""
    store = _store(tmp_path)
    result = derive_batch(
        USER,
        [
            event_to_item(_event("evt-1", FOCUS_TEXT)),
            event_to_item(_event("evt-2", FOCUS_TEXT + " again")),
        ],
        store,
        generate_fn=_raising_gen,
    )
    assert result.readings == []
    assert result.declines == 0
    assert len(result.deferred) == 1
    thread = _threads(store, USER)[0]
    assert _readings(store, USER, thread.id) == []
    assert len(_deferred(store, USER, status="pending")) == 1


def test_worker_extension_renders_reading_only(tmp_path):
    """A deferred extension renders a reading, never a change:
    invariant 2 forbids recording a change on already-attached
    evidence, so the worker's change_kind is dropped, not forced."""
    store = _store(tmp_path)
    calls: list = []
    derive_batch(
        USER,
        [
            event_to_item(_event("evt-1", FOCUS_TEXT)),
            event_to_item(_event("evt-2", FOCUS_TEXT + " again")),
        ],
        store,
        generate_fn=_counting_gen(BIRTH_JSON, calls),
    )
    thread = _threads(store, USER)[0]
    derive_batch(
        USER,
        [event_to_item(_event("evt-3", FOCUS_TEXT + " once more"))],
        store,
        generate_fn=_raising_gen,
    )
    assert len(_deferred(store, USER, status="pending")) == 1
    assert store.changes_for(USER, thread.id) == []
    worked = work_deferred_prose(
        store, USER, generate_fn=_counting_gen(EXTENSION_JSON, calls)
    )
    assert len(worked.rendered) == 1
    assert len(_readings(store, USER, thread.id)) == 2
    assert store.changes_for(USER, thread.id) == []
    assert _deferred(store, USER, status="done")


# -- turn-path-clean / meeting chokepoint --------------------------------------


def test_turn_path_imports_no_narrative():
    """No local_ai.narrative import on any turn path: events.py
    imports it function-locally only, and turn-path modules never
    name it (mirrors the S1 separation pin)."""
    repo = Path(__file__).resolve().parent.parent
    events_src = (repo / "local_ai" / "fellowship" / "events.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(events_src)
    for node in tree.body:
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        assert not any(name.startswith("local_ai.narrative") for name in names)
    for turn_path in (
        "local_ai/conversation/reply.py",
        "local_ai/conversation/service.py",
        "local_ai/conversation/encounter.py",
        "local_ai/conversation/meeting.py",
    ):
        assert "local_ai.narrative" not in (repo / turn_path).read_text(
            encoding="utf-8"
        )
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import local_ai.fellowship.events; "
            "assert 'local_ai.narrative' not in sys.modules",
        ],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_meeting_completion_guarded_when_steward_raises(monkeypatch):
    """The meeting-completion chokepoint never breaks: even a
    raising steward pipeline is swallowed and the event records."""
    import local_ai.activity as activity_mod
    import local_ai.fellowship.derivation as fellowship_derivation_mod
    import local_ai.fellowship.events as events_mod
    import local_ai.narrative.derivation as derivation_mod
    from local_ai.fellowship.events import emit_event

    records: list = []

    def _fake_log(**kwargs):
        records.append(kwargs)
        return "act-1"

    class Raising:
        def schedule_event(self, event):
            raise RuntimeError("boom")

    monkeypatch.setattr(activity_mod, "log_activity_simple", _fake_log)
    monkeypatch.setattr(fellowship_derivation_mod, "get_pipeline", lambda: None)
    monkeypatch.setattr(derivation_mod, "get_pipeline", lambda: Raising())
    event = events_mod.emit_event(
        kind="meeting_completed",
        user_id=USER,
        entity_type="meeting",
        entity_id="meeting:mentor-k1",
        evidence_text=FOCUS_TEXT,
        summary="done",
    )
    assert event.id == "act-1"
    assert len(records) == 1


# -- per-user scoping / provenance / consent sweep ------------------------------


def test_per_user_scoping(tmp_path):
    """A sweep for one user never reads or writes another user's
    threads, cursor, or deferred rows."""
    log_path = tmp_path / "activity.log"
    _write_log(
        log_path,
        [
            _line(_log_record(_event("evt-1", FOCUS_TEXT))),
            _line(_log_record(_event("evt-2", FOCUS_TEXT + " again"))),
            _line(
                _log_record(
                    _event("evt-o1", FOCUS_TEXT, user=OTHER, entity="meeting:other-k1")
                )
            ),
            _line(
                _log_record(
                    _event(
                        "evt-o2",
                        FOCUS_TEXT + " again",
                        user=OTHER,
                        entity="meeting:other-k1",
                    )
                )
            ),
        ],
    )
    store = _store(tmp_path)
    run_sweep_for_user(
        store,
        USER,
        log_path=log_path,
        generate_fn=_raising_gen,
        consent_reader=lambda user_id: True,
    )
    assert len(_threads(store, USER)) == 1
    assert _threads(store, OTHER) == []
    assert store.get_processing_position(OTHER) is None
    assert _deferred(store, OTHER) == []
    run_sweep_for_user(
        store,
        OTHER,
        log_path=log_path,
        generate_fn=_raising_gen,
        consent_reader=lambda user_id: True,
    )
    assert len(_threads(store, OTHER)) == 1
    assert len(_threads(store, USER)) == 1
    assert len(_deferred(store, USER)) == 1


def test_correction_leaves_evidence_byte_identical(tmp_path):
    """Provenance: a correction (new reading version) leaves every
    evidence row byte-identical and the superseded reading
    readable."""
    store = _store(tmp_path)
    calls: list = []
    derive_batch(
        USER,
        [
            event_to_item(_event("evt-1", FOCUS_TEXT)),
            event_to_item(_event("evt-2", FOCUS_TEXT + " again")),
        ],
        store,
        generate_fn=_counting_gen(BIRTH_JSON, calls),
    )
    thread = _threads(store, USER)[0]
    before = [
        (e.id, e.ref_kind, e.ref_id, e.created_at, e.entity_ref)
        for e in store.evidence_for(USER, thread.id)
    ]
    first = _readings(store, USER, thread.id)[0]
    evidence_ids = [e.id for e in store.evidence_for(USER, thread.id)]
    store.propose_reading(
        USER,
        thread.id,
        author="steward",
        reading={"tensions": ["corrected"], "open_questions": [], "milestones": []},
        evidence_refs=evidence_ids,
        scales=["personal"],
        primary_scale="personal",
    )
    after = [
        (e.id, e.ref_kind, e.ref_id, e.created_at, e.entity_ref)
        for e in store.evidence_for(USER, thread.id)
    ]
    assert before == after
    assert store.readings_for(USER, thread.id, status="proposed")
    assert any(r.id == first.id for r in _readings(store, USER, thread.id))


def test_sweep_gate_closed_consumes_without_deriving(tmp_path):
    """Gate closed: the batch is consume-skipped (offset advances)
    and later opt-in does NOT retroactively derive it."""
    log_path = tmp_path / "activity.log"
    _two_meeting_log(log_path)
    store = _store(tmp_path)
    res = run_sweep_for_user(
        store,
        USER,
        log_path=log_path,
        generate_fn=_raising_gen,
        consent_reader=lambda user_id: False,
    )
    assert res.events_gate_skipped == 2
    assert res.events_derived == 0
    assert _threads(store, USER) == []
    assert res.offset_after == log_path.stat().st_size
    res2 = run_sweep_for_user(
        store,
        USER,
        log_path=log_path,
        generate_fn=_raising_gen,
        consent_reader=lambda user_id: True,
    )
    assert res2.events_derived == 0
    assert _threads(store, USER) == []


def test_withdrawal_stops_at_next_batch_boundary(tmp_path):
    """Withdrawal mid-sweep: the in-flight bounded batch completes,
    nothing further derives (3 batches: 50 derived, 70 skipped)."""
    log_path = tmp_path / "activity.log"
    _write_log(
        log_path,
        [_line(_log_record(_event(f"evt-{i}", FOCUS_TEXT))) for i in range(120)],
    )
    store = _store(tmp_path)
    calls: list = []

    def reader(user_id):
        calls.append(user_id)
        return len(calls) <= 1

    res = run_sweep_for_user(
        store,
        USER,
        log_path=log_path,
        generate_fn=_raising_gen,
        consent_reader=reader,
    )
    assert res.batches == 3
    assert res.events_derived == 50
    assert res.events_gate_skipped == 70
    assert res.offset_after == log_path.stat().st_size
    assert len(_threads(store, USER)) == 1


def test_deferred_dedup_no_second_row(tmp_path):
    """Reprocessing that reaches the deferred write with an
    existing (user, thread, signature) row creates no second row."""
    store = _store(tmp_path)
    derive_batch(
        USER,
        [
            event_to_item(_event("evt-1", FOCUS_TEXT)),
            event_to_item(_event("evt-2", FOCUS_TEXT + " again")),
        ],
        store,
        generate_fn=_raising_gen,
    )
    thread = _threads(store, USER)[0]
    sig = _deferred(store, USER)[0]["evidence_signature"]
    evidence = store.evidence_for(USER, thread.id)
    _, first_id = store.attach_evidence_with_deferred_prose(
        USER,
        thread.id,
        [SourceRef(kind=e.ref_kind, ref_id=e.ref_id) for e in evidence],
        deferred_kind="extension",
        evidence_signature=sig,
        evidence_texts=[],
    )
    assert len(_deferred(store, USER)) == 1
    assert _deferred(store, USER)[0]["id"] == first_id


def test_cursor_set_get_roundtrip(tmp_path):
    """Processing-position rows round-trip (table pin)."""
    store = _store(tmp_path)
    assert store.get_processing_position(USER) is None
    store.set_processing_position(USER, 1234, "1:2")
    pos = store.get_processing_position(USER)
    assert pos["byte_offset"] == 1234
    assert pos["file_identity"] == "1:2"
    store.set_processing_position(USER, 5678, "1:2")
    assert store.get_processing_position(USER)["byte_offset"] == 5678
    assert store.processing_position_users() == [USER]


def test_ignored_prune_hard_deletes_steward_only(tmp_path):
    """Ignored-retention prune: a stale steward-proposal nascent
    thread with only proposed readings and no owed prose is
    HARD-deleted (rows gone, not hidden); fresh, engaged,
    user-declared, and prose-owed threads survive."""
    from datetime import datetime, timedelta, timezone

    store = _store(tmp_path)
    # Stale steward thread: birth records-first, then age it.
    derive_batch(
        USER,
        [
            event_to_item(_event("evt-1", FOCUS_TEXT)),
            event_to_item(_event("evt-2", FOCUS_TEXT + " again")),
        ],
        store,
        generate_fn=_raising_gen,
    )
    stale = _threads(store, USER)[0]
    # Settle its prose so it is not "owed" anymore.
    calls: list = []
    work_deferred_prose(
        store, USER, generate_fn=_counting_gen(BIRTH_JSON, calls)
    )
    assert _deferred(store, USER, status="done")
    conn = sqlite3.connect(str(tmp_path / "narrative.db"))
    old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    conn.execute(
        "UPDATE narrative_threads SET updated_at = ? WHERE id = ?",
        (old, stale.id),
    )
    conn.commit()
    conn.close()
    # Fresh steward thread (recent activity).
    derive_batch(
        USER,
        [
            event_to_item(_event("evt-9", FOCUS_TEXT, entity="meeting:other-k1")),
            event_to_item(
                _event("evt-10", FOCUS_TEXT + " again", entity="meeting:other-k1")
            ),
        ],
        store,
        generate_fn=_raising_gen,
    )
    # User-declared nascent thread, stale.
    user_thread = store.create_thread(USER, origin="user_declared", title="mine")
    conn = sqlite3.connect(str(tmp_path / "narrative.db"))
    conn.execute(
        "UPDATE narrative_threads SET updated_at = ? WHERE id = ?",
        (old, user_thread.id),
    )
    conn.commit()
    conn.close()
    deleted = prune_ignored_threads(store, USER)
    assert deleted == [stale.id]
    assert store.get_thread(USER, stale.id) is None
    assert store.get_thread(USER, user_thread.id) is not None
    assert len(_threads(store, USER)) == 2
    # Hard delete, not hide: no rows remain for the stale thread.
    conn = sqlite3.connect(str(tmp_path / "narrative.db"))
    for table in (
        "narrative_threads",
        "thread_evidence",
        "thread_readings",
        "steward_deferred_prose",
    ):
        col = "id" if table == "narrative_threads" else "thread_id"
        assert (
            conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {col} = ?", (stale.id,)
            ).fetchone()[0]
            == 0
        )
    conn.close()


def test_prune_skips_prose_owed_and_engaged(tmp_path):
    """Prose-owed threads (pending deferred rows) and threads with
    a non-proposed reading (visitor engaged) are never pruned,
    however stale."""
    from datetime import datetime, timedelta, timezone

    store = _store(tmp_path)
    derive_batch(
        USER,
        [
            event_to_item(_event("evt-1", FOCUS_TEXT)),
            event_to_item(_event("evt-2", FOCUS_TEXT + " again")),
        ],
        store,
        generate_fn=_raising_gen,
    )
    owed = _threads(store, USER)[0]
    derive_batch(
        USER,
        [
            event_to_item(_event("evt-9", FOCUS_TEXT, entity="meeting:other-k1")),
            event_to_item(
                _event("evt-10", FOCUS_TEXT + " again", entity="meeting:other-k1")
            ),
        ],
        store,
        generate_fn=_counting_gen(BIRTH_JSON, []),
    )
    engaged = [t for t in _threads(store, USER) if t.id != owed.id][0]
    reading = _readings(store, USER, engaged.id)[0]
    # Rejection keeps the thread nascent but marks the reading
    # non-proposed: the visitor has engaged, so it is not ignored.
    store.reject_reading(USER, reading.id)
    conn = sqlite3.connect(str(tmp_path / "narrative.db"))
    old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    conn.execute("UPDATE narrative_threads SET updated_at = ?", (old,))
    conn.commit()
    conn.close()
    assert prune_ignored_threads(store, USER) == []
    assert store.get_thread(USER, owed.id) is not None
    assert store.get_thread(USER, engaged.id) is not None
