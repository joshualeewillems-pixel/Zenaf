"""Signals consolidation: corrections + taste -> canonical TrainingSignal store.

Covers the three unified channels:
  1. agent_intake placement corrections (was: JSONL sidecar)
  2. agent_intake claim feedback (was: JSONL sidecar, plus a parallel
     canonical write in the route layer)
  3. pipeline taste observations (was: taste_observations table)

And the one-time graceful migration of existing sidecar data.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from local_ai.agent_intake.pipeline import (
    confirm_agent,
    connect_agent,
    log_claim_feedback,
)
from local_ai.agent_intake.store import AgentStore
from local_ai.pipeline.store import PipelineStore
from local_ai.presence_ingest import migrate
from local_ai.presence_ingest.schema import TrainingSignal
from local_ai.presence_ingest.store import PresenceStore

USER = "user-signals"


@pytest.fixture()
def signals_store(tmp_path: Path) -> PresenceStore:
    s = PresenceStore(tmp_path / "signals.db")
    yield s
    s.close()


@pytest.fixture()
def agent_store(tmp_path: Path) -> AgentStore:
    s = AgentStore(db_path=tmp_path / "agents.db")
    yield s
    s.close()


@pytest.fixture()
def pstore(tmp_path: Path):
    signals = PresenceStore(tmp_path / "signals.db")
    s = PipelineStore(tmp_path / "pipe.db", presence_store=signals)
    yield s
    s.close()
    signals.close()


# ---------------------------------------------------------------------------
# Channel 1: placement corrections
# ---------------------------------------------------------------------------


def test_placement_correction_roundtrip(agent_store, signals_store):
    agent = connect_agent(
        "Mediator Bot",
        "chatgpt",
        "Helps me write difficult emails to my team.",
        store=agent_store,
    )
    original_strand = agent.sort.primary_strand
    confirm_agent(
        agent.id,
        accepted=True,
        corrections={"primary_strand": "people", "kind": "talent"},
        store=agent_store,
        user_id=USER,
        presence_store=signals_store,
    )
    found = signals_store.list_signals_by_kind("placement_correction")
    assert len(found) == 1
    signal = found[0]
    assert signal.kind == "placement_correction"
    assert signal.actor == USER
    assert signal.valence == "corrected"
    assert signal.layer == "guidance"
    assert signal.status == "approved"
    assert signal.zone == "people"
    assert signal.provenance["agent_id"] == agent.id
    diff = json.loads(signal.correction_diff)
    assert diff["original"]["primary_strand"] == original_strand
    assert diff["correction"] == {"primary_strand": "people", "kind": "talent"}
    # The sort itself still took the correction.
    assert agent_store.get(agent.id).sort.primary_strand == "people"


# ---------------------------------------------------------------------------
# Channel 2: claim feedback
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action,valence,layer",
    [
        ("accepted", "endorsed", "behavior"),
        ("rejected", "rejected", "behavior"),
        ("corrected", "corrected", "guidance"),
        ("explained", "corrected", "guidance"),
        ("unresolved", "observed", "guidance"),
    ],
)
def test_claim_feedback_roundtrip(
    signals_store, action: str, valence: str, layer: str, tmp_path: Path
):
    claim_id = "agent-1:strand:people"
    log_claim_feedback(
        "agent-1",
        claim_id,
        "strand",
        action,
        note="user note",
        evidence="a quote",
        inference="an inference",
        claim_title="People",
        user_id=USER,
        presence_store=signals_store,
    )
    found = signals_store.list_signals_by_kind("claim_feedback")
    assert len(found) == 1
    signal = found[0]
    assert signal.kind == "claim_feedback"
    assert signal.signal_id == f"intake:{claim_id}:{action}"
    assert signal.valence == valence
    assert signal.layer == layer
    assert signal.zone == "people"
    assert signal.actor == USER
    assert signal.status == "approved"
    assert signal.summary == "an inference"
    assert signal.payload_redacted == "a quote"
    assert signal.correction_diff == "user note"
    assert signal.provenance["claim_type"] == "strand"
    assert signal.provenance["action"] == action
    # No sidecar JSONL was created anywhere.
    assert not (Path.home() / ".zenaf" / "agent_intake_corrections.jsonl").exists()


def test_claim_feedback_is_idempotent(signals_store):
    for _ in range(2):
        log_claim_feedback(
            "agent-1",
            "agent-1:strand:people",
            "strand",
            "accepted",
            user_id=USER,
            presence_store=signals_store,
        )
    assert (
        signals_store.count_signals_by_kind("claim_feedback") == 1
    )


# ---------------------------------------------------------------------------
# Channel 3: taste observations
# ---------------------------------------------------------------------------


def test_taste_observation_roundtrip(pstore):
    obs = pstore.add_taste_observation(USER, "favorite style", "blues")
    assert obs["obs_id"]
    assert obs["user_id"] == USER
    assert obs["question"] == "favorite style"
    assert obs["answer"] == "blues"
    assert pstore.count_observations(USER) == 1
    listed = pstore.list_observations(USER)
    assert len(listed) == 1
    row = listed[0]
    assert row["obs_id"] == obs["obs_id"]
    assert row["question"] == "favorite style"
    assert row["answer"] == "blues"
    assert row["created_at"]


def test_taste_counts_are_per_user_and_kind(pstore):
    signals = pstore._signals()
    pstore.add_taste_observation(USER, "q", "a")
    pstore.add_taste_observation("other-user", "q", "a")
    signals.save_candidate_signals(
        [
            # A distilled signal must not leak into taste counts.
            TrainingSignal(
                signal_id="distilled-1",
                ts_ms=1,
                layer="behavior",
                zone="self",
                actor=USER,
                summary="x",
                context_ref={},
                payload_redacted="",
                valence="observed",
                correction_diff=None,
                provenance={},
                supersedes=None,
                status="approved",
                session_id="",
            )
        ]
    )
    assert pstore.count_observations(USER) == 1
    assert pstore.count_observations("other-user") == 1
    assert signals.count_signals_by_kind("taste_observation") == 2


# ---------------------------------------------------------------------------
# Migration: JSONL sidecar
# ---------------------------------------------------------------------------


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )


def test_migrate_corrections_jsonl(tmp_path: Path, signals_store):
    log_path = tmp_path / "agent_intake_corrections.jsonl"
    _write_jsonl(
        log_path,
        [
            {
                "agent_id": "a1",
                "ts": "2026-10-18T10:00:00+00:00",
                "original": {"primary_strand": "word", "kind": "skill"},
                "correction": {"primary_strand": "people"},
            },
            {
                "agent_id": "a1",
                "claim_id": "a1:strand:people",
                "claim_type": "strand",
                "ts": "2026-10-18T11:00:00+00:00",
                "action": "accepted",
                "evidence": "quote",
                "inference": "inf",
                "user_note": "",
            },
            "not a json line",
            {"no": "useful keys"},
        ],
    )
    out = migrate.migrate_corrections_jsonl(signals_store, log_path)
    assert out["migrated"] == 2  # garbage line and garbage dict skipped
    assert signals_store.count_signals_by_kind("placement_correction") == 1
    assert signals_store.count_signals_by_kind("claim_feedback") == 1
    # File renamed so it can't be imported twice.
    assert not log_path.exists()
    assert log_path.with_name(log_path.name + ".migrated").exists()
    # Re-run is a clean no-op on the renamed path (ids are idempotent too).
    out2 = migrate.migrate_corrections_jsonl(signals_store, log_path)
    assert out2 == {"migrated": 0, "skipped": "missing file"}


def test_migrate_corrections_missing_file_is_clean(tmp_path: Path, signals_store):
    out = migrate.migrate_corrections_jsonl(
        signals_store, tmp_path / "does-not-exist.jsonl"
    )
    assert out == {"migrated": 0, "skipped": "missing file"}


# ---------------------------------------------------------------------------
# Migration: taste_observations table
# ---------------------------------------------------------------------------


def _legacy_pipeline_db(path: Path, rows: list[tuple]) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        """CREATE TABLE taste_observations (
            obs_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            question TEXT NOT NULL DEFAULT '',
            answer TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )
    conn.executemany(
        "INSERT INTO taste_observations VALUES (?,?,?,?,?)", rows
    )
    conn.commit()
    conn.close()


def test_migrate_taste_observations(tmp_path: Path, signals_store):
    db_path = tmp_path / "pipeline.db"
    _legacy_pipeline_db(
        db_path,
        [
            ("obs-1", USER, "favorite style", "blues", "2026-10-18T10:00:00+00:00"),
            ("obs-2", USER, "tools", "Suno", "2026-10-18T11:00:00+00:00"),
        ],
    )
    out = migrate.migrate_taste_observations(signals_store, db_path)
    assert out == {"migrated": 2}
    listed = signals_store.list_signals_by_kind("taste_observation", actor=USER)
    assert {s.signal_id for s in listed} == {"taste:obs-1", "taste:obs-2"}
    assert all(s.kind == "taste_observation" for s in listed)
    by_id = {s.signal_id: s for s in listed}
    assert by_id["taste:obs-1"].summary == "favorite style -> blues"
    assert by_id["taste:obs-1"].provenance["question"] == "favorite style"
    # Idempotent: re-run replaces, doesn't duplicate.
    out2 = migrate.migrate_taste_observations(signals_store, db_path)
    assert out2 == {"migrated": 2}
    assert signals_store.count_signals_by_kind("taste_observation") == 2


def test_migrate_taste_missing_table_is_clean(tmp_path: Path, signals_store):
    db_path = tmp_path / "empty.db"
    sqlite3.connect(str(db_path)).close()
    out = migrate.migrate_taste_observations(signals_store, db_path)
    assert out == {"migrated": 0, "skipped": "missing table"}


def test_migrate_taste_missing_db_is_clean(tmp_path: Path, signals_store):
    out = migrate.migrate_taste_observations(
        signals_store, tmp_path / "nope.db"
    )
    assert out == {"migrated": 0, "skipped": "missing db"}


# ---------------------------------------------------------------------------
# ensure_migrated: lazy, once-per-store, never crashes
# ---------------------------------------------------------------------------


def test_ensure_migrated_runs_once_and_never_crashes(tmp_path: Path, signals_store):
    # Both channels absent: clean zeros.
    out = migrate.ensure_migrated(
        signals_store,
        corrections_log=tmp_path / "nope.jsonl",
        pipeline_db_path=tmp_path / "nope.db",
    )
    assert out["corrections"] == {"migrated": 0, "skipped": "missing file"}
    assert out["taste"] == {"migrated": 0, "skipped": "missing db"}
    # Second call is a no-op (process-level guard).
    assert migrate.ensure_migrated(signals_store) == {}
