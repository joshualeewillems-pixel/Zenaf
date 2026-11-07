"""Upload rapid-fire S1 — extraction + jobs + records tests (brief §16, T1–T28, T51).

Deterministic: seeded rows, canned model stubs (never a live model),
tmp SQLite via tmp_path (isolated --basetemp when run). All store
calls use the real ConversationStore API (user_id first; save_* return
the full row dict; the worker takes (store, job_id) and needs
probe_fn=True in tests, since there is no Ollama server here).
"""

from __future__ import annotations

import json
import logging
import re
import threading
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import local_ai.conversation.upload_extraction as ue
from local_ai.conversation.store import ConversationStore

USER = "u1"
STRAND = "heart"

# The nine ConversationStore upload tables (brief §2.1–§2.9) + the one
# VE carrier table (brief §2.10) = the ten-table inventory (U-5).
UPLOAD_TABLES = [
    "upload_extraction_jobs",
    "upload_extraction_job_calls",
    "upload_spans",
    "upload_observations",
    "upload_interpretations",
    "upload_outcomes",
    "upload_artifacts",
    "upload_rounds",
    "upload_offers",
]

SPAN_A = "The morning light fell across the kitchen table"
SPAN_B = "the wind had changed, and the careful plan for the garden gave way"

DOC_TEXT = (
    SPAN_A
    + "\n"
    + "The gardener reads the room slowly, noticing which seeds are already sprouting. " * 30
    + "\n\n"
    + "By afternoon the wind had changed, and the careful plan for the garden gave way to "
    "improvisation, the way it always does when the soil is warmer than the forecast promised. " * 15
    + "\n\n"
    + "In the evening the notebook came out, and the day's work was recorded in the same plain "
    "hand as every other day. " * 22
)
# Three paragraphs, each ~2,500 chars: no two pack into one 4,000-char
# chunk, so the document is exactly 3 chunks (seg-0000..seg-0002).
assert len(ue.chunk_upload_text(DOC_TEXT)[0]) == 3


@pytest.fixture()
def store(tmp_path: Path) -> ConversationStore:
    s = ConversationStore(db_path=tmp_path / "conv.db")
    yield s
    s.close()


def _table_names(conn) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


def _seed_paste(store: ConversationStore, text: str = DOC_TEXT, strand: str = STRAND):
    """A pasted strand source with full text; returns (conversation_id, document_id)."""
    convo = store.resolve_strand_thread(USER, strand)["conversation_id"]
    src = store.add_strand_source(
        USER,
        strand,
        convo,
        kind="paste",
        ref="paste-1",
        label="Field notes",
        excerpt_redacted=text[:2000],
        paste_full_text=text,
    )
    return convo, src["id"]


def _seed_span(
    store: ConversationStore,
    doc: str,
    text: str,
    version: int = 1,
    segment: str = "seg-0000",
) -> str:
    row = store.save_upload_span(
        USER, doc, version, segment, text, "redacted", f"{segment}:0-{len(text)}"
    )
    return row["span_id"]


def _seed_interpretation(
    store: ConversationStore,
    doc: str,
    text: str,
    span_ids: list[str],
    *,
    lens: str = STRAND,
    version: int = 1,
    proposed_outcome: str = "task",
    observation_ids: list[str] | None = None,
    origin: str = "extracted",
    is_transformation: bool = False,
    evidence_roles: dict[str, str] | None = None,
) -> str:
    row = store.save_upload_interpretation(
        USER,
        doc,
        version,
        lens,
        "strand",
        text,
        [
            {"span_id": s, "role": (evidence_roles or {}).get(s, "primary")}
            for s in span_ids
        ],
        observation_ids or [],
        origin,
        is_transformation,
        proposed_outcome,
        None,
        None,
        False,
    )
    return row["interpretation_id"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lease_iso(seconds: int = 240) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _evidence_stub(prompt: str) -> str:
    """Canned evidence JSON: one span per chunk, the chunk's first line."""
    chunk = prompt.split("CHUNK:", 1)[1] if "CHUNK:" in prompt else prompt
    first = chunk.strip().split("\n", 1)[0]
    return json.dumps(
        {"spans": [{"text": first, "why": "opening line", "kind": "fact"}]}
    )


def _interpretation_stub(prompt: str) -> str:
    """Canned interpretation JSON: one reading, proposed task. Cites
    the first span the batch's evidence lists (a real span row the
    worker wrote), as a dict entry — the prompt's own JSON shape.
    Citing a literal that is not a stored span row drops the reading
    (worker rule), so the stub reads the evidence it is given."""
    match = re.search(r'^- "(.+)" \[', prompt, re.M)
    spans = [{"text": match.group(1), "role": "primary"}] if match else []
    return json.dumps(
        {
            "interpretations": [
                {
                    "text": "The day moved from order to improvisation.",
                    "spans": spans,
                    "observations": [],
                    "proposed_outcome": "task",
                }
            ]
        }
    )


def _stub_complete(prompt: str) -> str:
    if "one chunk" in prompt:
        return _evidence_stub(prompt)
    return _interpretation_stub(prompt)


def _run(store, job_id, complete_fn=_stub_complete):
    return ue.run_upload_extraction_job(
        store, job_id, complete_fn=complete_fn, probe_fn=lambda: True
    )


# -- schema (T1–T8) ---------------------------------------------------------------


def test_t1_nine_upload_tables_on_fresh_db(store):
    names = _table_names(store._conn)
    missing = [t for t in UPLOAD_TABLES if t not in names]
    assert not missing, f"missing upload tables: {missing}"


def test_t2_carrier_table_on_fresh_ve_db(tmp_path):
    import sqlite3

    import local_ai.vision_execution.storage as ve_storage

    conn = sqlite3.connect(tmp_path / "ve.db")
    ve_storage.init_db(conn)
    names = _table_names(conn)
    assert "upload_outcome_creations" in names
    # PK is outcome_id.
    pk = [
        r[1]
        for r in conn.execute(
            "PRAGMA table_info(upload_outcome_creations)"
        ).fetchall()
        if r[5]
    ]
    assert pk == ["outcome_id"]
    conn.close()


def test_t3_paste_compression_round_trips(store):
    convo, doc = _seed_paste(store, DOC_TEXT)
    src = store.get_strand_source(USER, doc)
    assert src is not None
    assert src["paste_text_encoding"] == "zlib"
    # The blob is NOT plaintext at rest.
    raw = store._conn.execute(
        "SELECT paste_text_blob FROM strand_sources WHERE id = ?", (doc,)
    ).fetchone()[0]
    assert DOC_TEXT.encode() not in bytes(raw)
    assert zlib.decompress(bytes(raw)).decode() == DOC_TEXT
    assert store.get_paste_full_text(doc) == DOC_TEXT


def test_t4_excerpt_unchanged_by_compression_write(store):
    long_text = "word " * 900  # 4,500 chars — excerpt capped by the route, not the store.
    convo, doc = _seed_paste(store, long_text)
    src = store.get_strand_source(USER, doc)
    assert src["excerpt_redacted"] == long_text[:2000].strip()
    assert store.get_paste_full_text(doc) == long_text


def test_t5_guarded_alter_adds_columns_to_pre_upload_db(tmp_path):
    # A pre-upload DB: strand_sources WITHOUT the paste columns.
    import sqlite3

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE strand_sources (\n"
        "  id TEXT PRIMARY KEY,\n"
        "  user_id TEXT NOT NULL,\n"
        "  strand_key TEXT NOT NULL,\n"
        "  conversation_id TEXT NOT NULL,\n"
        "  kind TEXT NOT NULL,\n"
        "  ref TEXT NOT NULL,\n"
        "  label TEXT NOT NULL DEFAULT '',\n"
        "  excerpt_redacted TEXT NOT NULL DEFAULT '',\n"
        "  created_at TEXT NOT NULL\n"
        ")"
    )
    conn.commit()
    conn.close()
    store = ConversationStore(db_path=path)
    try:
        cols = {
            r["name"]
            for r in store._conn.execute(
                "PRAGMA table_info(strand_sources)"
            ).fetchall()
        }
        assert "paste_text_blob" in cols
        assert "paste_text_encoding" in cols
        assert _table_names(store._conn) >= set(UPLOAD_TABLES)
    finally:
        store.close()


def test_t6_migration_noop_on_second_run(store):
    before = _table_names(store._conn)
    store._migrate_paste_text_columns()
    store._migrate_paste_text_columns()
    assert _table_names(store._conn) == before


def test_t53_amendment_columns_status_defaults_index_and_migration(tmp_path):
    # Amendment A3: the status columns default 'current', the
    # (span_hash, location) index exists, and the guarded migration
    # restores all four columns on a pre-amendment DB (simulated by
    # dropping them — a DB opened before the amendment).
    path = tmp_path / "pre-amendment.db"
    store = ConversationStore(db_path=path)
    try:
        convo, doc = _seed_paste(store)
        span = store.save_upload_span(
            USER, doc, 1, "seg-0000", SPAN_A, "redacted", f"seg-0000:0-{len(SPAN_A)}"
        )
        assert span["status"] == "current"
        obs = store.save_upload_observation(
            USER, doc, 1, "The day moved slowly.", [span["span_id"]]
        )
        assert obs["status"] == "current"
        interp = _seed_interpretation(store, doc, "Reading one.", [span["span_id"]])
        assert store.get_upload_interpretation(USER, interp)["uncertain_match"] is None
        found = False
        for idx in store._conn.execute("PRAGMA index_list(upload_spans)").fetchall():
            cols = [
                r["name"]
                for r in store._conn.execute(
                    f"PRAGMA index_info({idx['name']})"
                ).fetchall()
            ]
            if cols == ["span_hash", "location"]:
                found = True
        assert found, "missing (span_hash, location) index on upload_spans"
        # Simulate the pre-amendment DB: drop the four columns +
        # the index, then close. Re-opening must restore them.
        store._conn.execute("DROP INDEX IF EXISTS idx_upload_spans_hash_loc")
        for table, column in (
            ("upload_interpretations", "uncertain_match"),
            ("upload_spans", "status"),
            ("upload_observations", "status"),
            ("upload_extraction_jobs", "interpreted_chunks"),
        ):
            store._conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        store._conn.commit()
        span_id = span["span_id"]
    finally:
        store.close()
    store2 = ConversationStore(db_path=path)
    try:
        for table, column in (
            ("upload_interpretations", "uncertain_match"),
            ("upload_spans", "status"),
            ("upload_observations", "status"),
            ("upload_extraction_jobs", "interpreted_chunks"),
        ):
            cols = {
                r["name"]
                for r in store2._conn.execute(
                    f"PRAGMA table_info({table})"
                ).fetchall()
            }
            assert column in cols, f"{table}.{column} not restored by the migration"
        # The pre-existing span row survives, backfilled 'current'
        # by the NOT NULL DEFAULT.
        assert store2.get_upload_span(USER, span_id)["status"] == "current"
    finally:
        store2.close()


def test_t7_outcome_unique_interpretation_kind(store):
    convo, doc = _seed_paste(store)
    span = _seed_span(store, doc, SPAN_A)
    interp = _seed_interpretation(store, doc, "Reading one.", [span])
    out1 = store.create_upload_outcome(USER, doc, 1, interp, "keep", None)
    out2 = store.create_upload_outcome(USER, doc, 1, interp, "keep", None)
    assert out1 == out2  # idempotent: the UNIQUE rejects a second row.
    out3 = store.create_upload_outcome(USER, doc, 1, interp, "explore", None)
    assert out3["outcome_id"] != out1["outcome_id"]


def test_t8_carrier_pk_rejects_duplicate_outcome_id(tmp_path):
    import sqlite3

    import local_ai.vision_execution.storage as ve_storage

    conn = sqlite3.connect(tmp_path / "ve.db")
    ve_storage.init_db(conn)
    conn.execute(
        "INSERT INTO upload_outcome_creations "
        "(outcome_id, ve_kind, ve_id, user_id, created_at) "
        "VALUES ('out-1', 'task', 'task-1', 'u1', '2026-11-07T00:00:00Z')"
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO upload_outcome_creations "
            "(outcome_id, ve_kind, ve_id, user_id, created_at) "
            "VALUES ('out-1', 'task', 'task-2', 'u1', '2026-11-07T00:00:00Z')"
        )
    conn.close()


# -- jobs (T9–T14) ----------------------------------------------------------------


def test_t10_claim_race_two_workers_one_job(store):
    convo, doc = _seed_paste(store)
    job = store.create_upload_job(USER, doc, 1)
    assert store.claim_upload_job(job["job_id"], "worker-a", _now_iso(), _lease_iso()) is True
    assert store.claim_upload_job(job["job_id"], "worker-b", _now_iso(), _lease_iso()) is False
    assert store.get_upload_job(USER, job["job_id"])["state"] == "running"


def test_t11_reconciler_marks_interrupted_and_started_call_never_complete(store):
    convo, doc = _seed_paste(store)
    job = store.create_upload_job(USER, doc, 1)
    store.claim_upload_job(job["job_id"], "worker-a", _now_iso(), _lease_iso())
    call = store.start_upload_job_call(job["job_id"], 0, "evidence")
    # Stale: backdate the heartbeat AND the creation past the 240s
    # threshold (the stale query requires both).
    old = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
    with store._lock:
        store._conn.execute(
            "UPDATE upload_extraction_jobs SET last_heartbeat_at = ?, created_at = ? "
            "WHERE job_id = ?",
            (old, old, job["job_id"]),
        )
        store._conn.commit()
    interrupted = ue.reconcile_stale_upload_jobs(store=store)
    assert interrupted == 1
    assert store.get_upload_job(USER, job["job_id"])["state"] == "interrupted"
    calls = store.list_upload_job_calls(job["job_id"])
    assert calls[0]["state"] == "failed"
    assert calls[0]["code"] == "interrupted"
    # The started call was never counted complete.
    assert store.get_upload_job(USER, job["job_id"])["completed_calls"] == 0


def test_t12_resume_fills_only_missing_chunks_in_same_version(store):
    convo, doc = _seed_paste(store)
    job = store.create_upload_job(USER, doc, 1)
    # Simulate an interrupted job: chunk 1 done (spans exist), chunks 2–3 missing.
    _seed_span(store, doc, SPAN_A, version=1, segment="seg-0000")
    calls = []

    def counting_stub(prompt: str) -> str:
        calls.append(prompt)
        return _stub_complete(prompt)

    result = _run(store, job["job_id"], counting_stub)
    # Chunk 1 was skipped (spans exist); only chunks 2–3 ran evidence.
    evidence_calls = [c for c in calls if "one chunk" in c]
    assert len(evidence_calls) == 2
    assert result["state"] in ("complete", "partial")


def test_t13_semaphore_serializes_concurrent_calls(store, tmp_path):
    # Hold the semaphore; a worker in a thread (its own store on the
    # same file, as the real thread starter does) must not call the
    # model until it is released — asserted by the call event, not
    # by timing luck.
    convo, doc = _seed_paste(store)
    job = store.create_upload_job(USER, doc, 1)
    called = threading.Event()
    calls = []

    def stub(prompt: str) -> str:
        calls.append(prompt)
        called.set()
        return _stub_complete(prompt)

    sem = ue.EXTRACTION_MODEL_SEMAPHORE
    assert sem.acquire(blocking=False)  # hold it in this thread
    done = threading.Event()
    result: dict = {}

    def run():
        worker_store = ConversationStore(db_path=tmp_path / "conv.db")
        try:
            result.update(
                ue.run_upload_extraction_job(
                    worker_store, job["job_id"], complete_fn=stub,
                    probe_fn=lambda: True,
                )
            )
        finally:
            worker_store.close()
            done.set()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    # The worker is blocked on the semaphore: no model call within the window.
    assert called.wait(timeout=0.5) is False
    assert calls == []
    sem.release()
    assert done.wait(timeout=15) is True
    assert calls  # the worker proceeded once the semaphore was free.
    assert result["state"] in ("complete", "partial")


def test_t54_distill_and_upload_model_calls_serialize(store):
    # Amendment A5 (§16): a distill batch call and an upload call
    # serialize — asserted by call timestamps. Both stubs sleep
    # inside the model call (inside the slot), so if the two paths
    # did NOT share the semaphore their intervals would overlap;
    # sharing it, they are disjoint.
    import time

    from local_ai.presence_ingest.distill import PresenceEvent, distill_events

    convo, doc = _seed_paste(store)
    job = store.create_upload_job(USER, doc, 1)
    barrier = threading.Barrier(2)
    intervals: dict[str, list[tuple[float, float]]] = {"distill": [], "upload": []}

    def slow_distill(prompt: str) -> str:
        start = time.monotonic()
        time.sleep(0.3)
        intervals["distill"].append((start, time.monotonic()))
        return json.dumps({"extractions": []})

    def slow_upload(prompt: str) -> str:
        start = time.monotonic()
        time.sleep(0.3)
        intervals["upload"].append((start, time.monotonic()))
        return _stub_complete(prompt)

    def run_distill():
        barrier.wait(timeout=10)
        distill_events(
            [
                PresenceEvent(
                    event_id="e1",
                    source="chatgpt",
                    actor="user",
                    kind="message",
                    text="I decided to take the startup offer.",
                    context={},
                    provenance={},
                )
            ],
            complete_fn=slow_distill,
            zone_hint="career",
            session_id="t54",
        )

    def run_upload():
        barrier.wait(timeout=10)
        ue.run_upload_extraction_job(
            store, job["job_id"], complete_fn=slow_upload, probe_fn=lambda: True
        )

    t1 = threading.Thread(target=run_distill, daemon=True)
    t2 = threading.Thread(target=run_upload, daemon=True)
    t1.start()
    t2.start()
    t1.join(timeout=20)
    t2.join(timeout=20)
    assert not t1.is_alive() and not t2.is_alive()
    assert intervals["distill"], "distill made no model call"
    assert intervals["upload"], "upload made no model call"
    for d_start, d_end in intervals["distill"]:
        for u_start, u_end in intervals["upload"]:
            assert d_end <= u_start or u_end <= d_start, (
                "distill and upload model calls overlapped: "
                f"distill=({d_start:.3f}, {d_end:.3f}) "
                f"upload=({u_start:.3f}, {u_end:.3f})"
            )


def test_t14_cancel_stops_future_calls_and_keeps_completed_rows(store):
    convo, doc = _seed_paste(store)
    job = store.create_upload_job(USER, doc, 1)
    store.set_upload_job_state(job["job_id"], "cancelled")
    result = _run(store, job["job_id"])
    assert result["state"] == "cancelled"
    # Nothing ran (the worker returns early on a cancelled job).
    assert store.list_upload_job_calls(job["job_id"]) == []


def test_t14b_semaphore_shared_with_distill():
    import inspect

    import local_ai.presence_ingest.distill as distill
    from local_ai.conversation import upload_extraction as ue
    from local_ai.extraction_concurrency import (
        EXTRACTION_MODEL_SEMAPHORE,
        extraction_slot,
    )

    # Amendment A5: the semaphore's home is the neutral module
    # local_ai/extraction_concurrency.py; both paths take the slot
    # from there (distill lazily, inside distill_events; the worker
    # around its generate call). One instance, shared — two
    # independently instantiated Semaphore(1) objects would
    # enforce nothing.
    assert "extraction_slot" in inspect.getsource(distill.distill_events)
    assert "extraction_slot" in inspect.getsource(ue._run_model_call)
    assert ue.EXTRACTION_MODEL_SEMAPHORE is EXTRACTION_MODEL_SEMAPHORE
    with extraction_slot():
        pass


# -- extraction behavior (T15–T19) -----------------------------------------------


def test_t15_first_interpretation_committed_after_chunk_1(store):
    # Two chunks; the evidence and interpretation calls interleave
    # (amendment A1) — the first interpretation call fires when
    # chunk 1's evidence commits, over chunk 1's rows alone (P5,
    # N=1): its evidence covers exactly seg-0000.
    two_chunk = (
        SPAN_A
        + "\n"
        + "The gardener reads the room slowly, noticing which seeds are already sprouting. " * 30
        + "\n\n"
        + "By afternoon the wind had changed, and the careful plan for the garden gave way to "
        "improvisation, the way it always does when the soil is warmer than the forecast promised. " * 15
    )
    assert len(ue.chunk_upload_text(two_chunk)[0]) == 2
    convo, doc = _seed_paste(store, two_chunk)
    job = store.create_upload_job(USER, doc, 1)
    seen: dict = {}

    def stub(prompt: str) -> str:
        if "one chunk" not in prompt and "first_batch" not in seen:
            # First interpretation call: its SPANS section covers chunk 1 only.
            seen["first_batch"] = set(re.findall(r"\[(seg-\d+):", prompt))
        return _stub_complete(prompt)

    result = _run(store, job["job_id"], stub)
    assert result["state"] == "complete"
    assert result["first_interpretation_at"] is not None
    assert seen["first_batch"] == {"seg-0000"}
    assert len(store.list_upload_interpretations(USER, doc, 1)) >= 1


def test_t16_failed_job_offers_nothing(store):
    convo, doc = _seed_paste(store)
    job = store.create_upload_job(USER, doc, 1)

    def boom(prompt: str) -> str:
        raise RuntimeError("boom")

    result = _run(store, job["job_id"], boom)
    assert result["state"] == "failed"
    assert store.list_upload_interpretations(USER, doc, 1) == []
    assert store.pending_upload_interpretations(USER, doc, STRAND) == []


def test_t17_partial_job_coverage_is_honest(store):
    # A 3-chunk document (each paragraph ~2,500 chars so none pack
    # together) whose third chunk's evidence call fails.
    text = "\n\n".join(
        f"Paragraph {i}. " + "The day moved slowly through its ordinary hours. " * 55
        for i in range(3)
    )
    assert len(ue.chunk_upload_text(text)[0]) == 3
    convo, doc = _seed_paste(store, text)
    job = store.create_upload_job(USER, doc, 1)
    calls = {"n": 0}

    def flaky(prompt: str) -> str:
        if "one chunk" in prompt:
            calls["n"] += 1
            if calls["n"] == 3:
                return "not json at all"
        return _stub_complete(prompt)

    result = _run(store, job["job_id"], flaky)
    assert result["state"] == "partial"
    from local_ai.conversation.upload_round import upload_coverage

    # Amendment A1: the coverage names INTERPRETED chunks. The
    # failed third chunk wrote no rows, so 2 of 3 chunks were
    # extracted and both were read (P5 + flush).
    assert upload_coverage(store, USER, doc) == "first 2 of 3 chunks, as read"


def test_t18_twelve_chunk_cap_records_remainder_unextracted(store):
    # Thirteen paragraphs, each ~2,500 chars: 13 chunks, capped at 12.
    text = "\n\n".join(
        f"Paragraph {i}. " + "The day moved slowly through its ordinary hours. " * 55
        for i in range(13)
    )
    chunks, total = ue.chunk_upload_text(text)
    assert total == 13
    assert len(chunks) == 12
    convo, doc = _seed_paste(store, text)
    job = store.create_upload_job(USER, doc, 1)
    result = _run(store, job["job_id"])
    assert result["state"] == "complete"
    evidence_calls = [
        c
        for c in store.list_upload_job_calls(job["job_id"])
        if c["call_kind"] == "evidence"
    ]
    assert len(evidence_calls) == 12
    from local_ai.conversation.upload_round import upload_coverage

    # Amendment A1: the coverage names INTERPRETED chunks — all
    # 12 extracted chunks were read (P5 + flush, 2 calls).
    assert upload_coverage(store, USER, doc) == "first 12 of 13 chunks, as read"


def test_t19_per_call_output_cap_is_the_named_constant():
    assert ue.UPLOAD_MAX_INTERPRETATIONS_PER_CALL == 30
    # The interpretation prompt names the cap.
    prompt = ue._interpretation_prompt("heart", "strand", "")
    assert "30" in prompt


def test_t52_interpretation_calls_capped_at_five(store):
    # Amendment A1: six chunks x 30 spans = 180 rows. The P5 call
    # covers chunk 1 (30 rows); each further chunk's 30 rows fire
    # a call — five calls cover the first five chunks; the sixth
    # chunk's rows stay uninterpreted (no overflow, no sixth call).
    def thirty_lines(c: int) -> str:
        return "\n".join(
            f"Chunk {c} line {i:02d}. The day moved slowly through its ordinary hours today."
            for i in range(30)
        )

    text = "\n\n".join(thirty_lines(c) for c in range(6))
    chunks, total = ue.chunk_upload_text(text)
    assert len(chunks) == 6 and total == 6
    convo, doc = _seed_paste(store, text)
    job = store.create_upload_job(USER, doc, 1)

    def many_spans(prompt: str) -> str:
        if "one chunk" in prompt:
            chunk = prompt.split("CHUNK:", 1)[1] if "CHUNK:" in prompt else prompt
            lines = [ln.strip() for ln in chunk.strip().split("\n") if ln.strip()]
            return json.dumps({"spans": [{"text": ln} for ln in lines[:30]]})
        return _interpretation_stub(prompt)

    result = _run(store, job["job_id"], many_spans)
    assert result["state"] == "complete"
    interp_calls = [
        c
        for c in store.list_upload_job_calls(job["job_id"])
        if c["call_kind"] == "interpretation"
    ]
    assert len(interp_calls) == 5
    assert ue.UPLOAD_MAX_INTERPRETATION_CALLS_PER_JOB == 5
    final = store.get_upload_job(USER, job["job_id"])
    assert final["interpreted_chunks"] == [f"seg-{i:04d}" for i in range(5)]
    from local_ai.conversation.upload_round import upload_coverage

    # Interpreted lags extracted: both numbers are named.
    assert upload_coverage(store, USER, doc) == (
        "first 6 of 6 chunks extracted, first 5 of 6 chunks as read"
    )


# -- records (T20–T24) ------------------------------------------------------------


def test_t20_multi_interpretation_fixtures(store):
    convo, doc = _seed_paste(store)
    span = _seed_span(store, doc, SPAN_A)
    other = _seed_span(store, doc, SPAN_B)
    # One span, two readings.
    i1 = _seed_interpretation(store, doc, "Reading one.", [span])
    i2 = _seed_interpretation(store, doc, "Reading two.", [span])
    assert i1 != i2
    # One interpretation, two spans, one in contrast role.
    i3 = _seed_interpretation(
        store,
        doc,
        "Reading three.",
        [span, other],
        evidence_roles={other: "contrast"},
    )
    rec = store.get_upload_interpretation(USER, i3)
    assert rec is not None
    roles = {e["span_id"]: e["role"] for e in rec["evidence_ids"]}
    assert roles[other] == "contrast"
    assert roles[span] == "primary"


def test_t21_observation_claim_substring_of_span_rejected(store):
    convo, doc = _seed_paste(store)
    span = _seed_span(store, doc, SPAN_A)
    with pytest.raises(ValueError, match="quotation"):
        store.save_upload_observation(USER, doc, 1, "The morning light fell across", [span])


def test_t22_excerpt_fidelity_against_stored_redacted_text(store):
    # The span must be an exact substring of the STORED redacted text,
    # not the raw upload: a raw-only span (an email the redactor removed)
    # does not resolve.
    redacted = "Reach me at [redacted] for the garden plan."
    convo, doc = _seed_paste(store, redacted)
    job = store.create_upload_job(USER, doc, 1)

    def stub(prompt: str) -> str:
        if "one chunk" in prompt:
            return json.dumps(
                {"spans": [{"text": "joshua@example.com", "why": "contact", "kind": "fact"}]}
            )
        return json.dumps({"interpretations": []})

    _run(store, job["job_id"], stub)
    assert store.list_upload_spans(USER, doc, 1) == []


def test_t23_transformation_with_no_cited_span_rejected(store):
    convo, doc = _seed_paste(store)
    with pytest.raises(ValueError, match="at least one"):
        store.save_upload_interpretation(
            USER, doc, 1, STRAND, "strand", "A reading with no evidence.",
            [], [], "extracted", True, "task", None, None, False,
        )


def test_t24_transformation_observation_ids_empty_by_design(store):
    convo, doc = _seed_paste(store)
    span = _seed_span(store, doc, SPAN_A)
    interp = _seed_interpretation(
        store, doc, "A transformation.", [span], is_transformation=True
    )
    rec = store.get_upload_interpretation(USER, interp)
    assert rec is not None
    assert rec["observation_ids"] == []
    assert "observation_ids" in rec  # the field exists; it is empty by design.


# -- re-extraction (T25–T28) ------------------------------------------------------


def _auto_link_pair(store, doc, *, version: int, text: str, span_text: str):
    span = _seed_span(store, doc, span_text, version=version)
    interp = _seed_interpretation(
        store, doc, text, [span], version=version, proposed_outcome="task"
    )
    return span, interp


def _supporting_keys(store, doc, span_id: str):
    row = store.get_upload_span(USER, span_id)
    return [(row["span_hash"], row["location"])]


def test_t25_identical_text_and_spans_auto_link(store):
    convo, doc = _seed_paste(store)
    span, interp = _auto_link_pair(
        store, doc, version=1, text="The day moved.", span_text=SPAN_A
    )
    store.set_upload_interpretation_status(USER, interp, "ruled")
    # Re-extraction v2, identical text + identical spans: the v1 reading
    # is ruled at write time (§5.3).
    span2 = _seed_span(store, doc, SPAN_A, version=2)
    interp2 = _seed_interpretation(
        store, doc, "The day moved.", [span2], version=2
    )
    assert store.get_upload_interpretation(USER, interp2)["status"] == "ruled"


def test_t26_same_text_shifted_span_is_uncertain_not_ruled(store):
    convo, doc = _seed_paste(store)
    span, interp = _auto_link_pair(
        store, doc, version=1, text="The day moved.", span_text=SPAN_A
    )
    store.set_upload_interpretation_status(USER, interp, "ruled")
    # Same text, but the span is a different passage: uncertain, not ruled.
    shifted = "the wind had changed, and the careful plan"
    span2 = _seed_span(store, doc, shifted, version=2)
    interp2 = _seed_interpretation(
        store, doc, "The day moved.", [span2], version=2
    )
    assert store.get_upload_interpretation(USER, interp2)["status"] == "pending"
    # Amendment A3: the uncertain marker lives on the row — the
    # column (parsed) names the prior and which condition matched.
    assert store.get_upload_interpretation(USER, interp2)["uncertain_match"] == {
        "prior_interpretation_id": interp,
        "matched": "text",
    }
    match = store.match_ruled_interpretation(
        USER, doc, STRAND, "the day moved", _supporting_keys(store, doc, span2)
    )
    assert match is not None and match["kind"] == "text_only"
    from local_ai.conversation.upload_round import uncertain_match_for

    assert uncertain_match_for(
        store, USER, store.get_upload_interpretation(USER, interp2)
    ) is not None


def test_t27_same_spans_reworded_text_is_uncertain_not_ruled(store):
    convo, doc = _seed_paste(store)
    span, interp = _auto_link_pair(
        store, doc, version=1, text="The day moved.", span_text=SPAN_A
    )
    store.set_upload_interpretation_status(USER, interp, "ruled")
    span2 = _seed_span(store, doc, SPAN_A, version=2)
    interp2 = _seed_interpretation(
        store, doc, "The day moved in a new direction.", [span2], version=2
    )
    assert store.get_upload_interpretation(USER, interp2)["status"] == "pending"
    # Amendment A3: the uncertain marker lives on the row.
    assert store.get_upload_interpretation(USER, interp2)["uncertain_match"] == {
        "prior_interpretation_id": interp,
        "matched": "spans",
    }
    match = store.match_ruled_interpretation(
        USER, doc, STRAND, "the day moved in a new direction",
        _supporting_keys(store, doc, span2),
    )
    assert match is not None and match["kind"] == "spans_only"


def test_t28_re_extraction_never_alters_superseded_row_text(store):
    import hashlib

    convo, doc = _seed_paste(store)
    span, interp = _auto_link_pair(
        store, doc, version=1, text="The day moved.", span_text=SPAN_A
    )
    before = hashlib.sha256(
        store.get_upload_interpretation(USER, interp)["text"].encode()
    ).hexdigest()
    # A full re-extraction v2 with identical model output.
    job2 = store.create_upload_job(USER, doc, 2)
    _run(store, job2["job_id"])
    after = hashlib.sha256(
        store.get_upload_interpretation(USER, interp)["text"].encode()
    ).hexdigest()
    assert before == after
    # Amendment A3 / §5.4: the v2 job superseded the v1 set — the
    # v1 span is 'superseded', the v1 PENDING interpretation is
    # 'orphaned' (preserved, never presented). The text itself is
    # untouched (the hash above).
    assert store.get_upload_interpretation(USER, interp)["status"] == "orphaned"
    assert store.get_upload_span(USER, span)["status"] == "superseded"


# -- log rule (T51) ----------------------------------------------------------------


def test_t51_log_contains_no_fixture_text(store, caplog):
    convo, doc = _seed_paste(store)
    job = store.create_upload_job(USER, doc, 1)
    with caplog.at_level(logging.INFO, logger="local_ai.conversation.upload_extraction"):
        _run(store, job["job_id"])
    log_text = caplog.text
    assert SPAN_A not in log_text
    assert "The day moved from order to improvisation." not in log_text
    # No prompt text and no model-output excerpt.
    assert "You are reading" not in log_text
    assert "opening line" not in log_text
    # The P1–P5 line is present (numbers only).
    assert "upload extraction: job" in log_text
    assert "total_calls=" in log_text
