"""One-time migration of sidecar signal channels into the canonical store.

Two channels bypassed the canonical TrainingSignal store:
  1. agent_intake review corrections -> JSONL sidecar
     (~/.zenaf/agent_intake_corrections.jsonl)
  2. pipeline taste observations -> taste_observations table in pipeline.db

Each migrate_* function is graceful: missing files/tables/rows yield zero
counts, never exceptions. Signal IDs are deterministic and writes use
INSERT OR REPLACE, so re-running is idempotent. After a successful JSONL
import the file is renamed to *.migrated so it can't be imported twice.

ensure_migrated() wraps both with a process-level guard keyed by store
path, so writers can call it cheaply before every write.
"""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .store import PresenceStore

_MIGRATED: set[tuple[str, str]] = set()


def _ts_ms(raw: Any) -> int:
    if isinstance(raw, (int, float)):
        return int(raw)
    if isinstance(raw, str):
        try:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            pass
    return int(time.time() * 1000)


def migrate_corrections_jsonl(
    presence_store: PresenceStore, log_path: Path | str | None = None
) -> dict[str, Any]:
    """Import agent_intake correction rows from the JSONL sidecar."""
    from local_ai.agent_intake import signals as intake_signals
    from local_ai.agent_intake.pipeline import DEFAULT_CORRECTIONS_LOG

    path = Path(log_path) if log_path else DEFAULT_CORRECTIONS_LOG
    if not path.exists():
        return {"migrated": 0, "skipped": "missing file"}
    try:
        lines = path.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return {"migrated": 0, "skipped": "unreadable"}

    built = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        ts_ms = _ts_ms(row.get("ts"))
        if "claim_id" in row:
            # Per-claim review verdict.
            is_claim_row = True
        elif "original" in row or "correction" in row or "agent_id" in row:
            # Agent-level placement correction.
            is_claim_row = False
        else:
            # Unrecognized row shape — skip rather than invent a signal.
            continue
        if is_claim_row:
            built.append(
                intake_signals.claim_feedback_signal(
                    agent_id=str(row.get("agent_id", "")),
                    claim_id=str(row.get("claim_id", "")),
                    claim_type=str(row.get("claim_type", "")),
                    action=str(row.get("action", "unresolved")),
                    user_id="",
                    evidence=str(row.get("evidence", "") or ""),
                    inference=str(row.get("inference", "") or ""),
                    note=str(row.get("user_note", "") or ""),
                )
            )
            # Backfill the row's own timestamp (builder uses now).
            built[-1].ts_ms = ts_ms
        else:
            # Agent-level placement correction.
            built.append(
                intake_signals.placement_correction_signal(
                    agent_id=str(row.get("agent_id", "")),
                    user_id="",
                    original=dict(row.get("original", {}) or {}),
                    correction=dict(row.get("correction", {}) or {}),
                    ts_ms=ts_ms,
                )
            )
    if built:
        presence_store.save_candidate_signals(built)
    # Rename so a later run can't import twice (ids are also idempotent).
    try:
        path.rename(path.with_name(path.name + ".migrated"))
    except OSError:
        pass
    return {"migrated": len(built)}


def migrate_taste_observations(
    presence_store: PresenceStore, pipeline_db_path: Path | str | None = None
) -> dict[str, Any]:
    """Import pipeline taste_observations rows into the canonical store."""
    from local_ai.pipeline.store import DEFAULT_DB_PATH as PIPELINE_DB
    from local_ai.pipeline.taste import taste_observation_signal

    db_path = Path(pipeline_db_path) if pipeline_db_path else PIPELINE_DB
    if not db_path.exists():
        return {"migrated": 0, "skipped": "missing db"}
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        tables = {
            r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "taste_observations" not in tables:
            conn.close()
            return {"migrated": 0, "skipped": "missing table"}
        rows = conn.execute(
            "SELECT obs_id, user_id, question, answer, created_at "
            "FROM taste_observations"
        ).fetchall()
        conn.close()
    except (sqlite3.Error, OSError):
        return {"migrated": 0, "skipped": "unreadable"}

    signals = [
        taste_observation_signal(
            obs_id=str(r["obs_id"]),
            user_id=str(r["user_id"]),
            question=str(r["question"] or ""),
            answer=str(r["answer"] or ""),
            created_at_ms=_ts_ms(r["created_at"]),
        )
        for r in rows
    ]
    if signals:
        presence_store.save_candidate_signals(signals)
    return {"migrated": len(signals)}


def ensure_migrated(
    presence_store: PresenceStore,
    *,
    corrections_log: Path | str | None = None,
    pipeline_db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Run both sidecar migrations once per store path; cheap afterwards."""
    base = str(presence_store.db_path)
    out: dict[str, Any] = {}
    if (base, "corrections") not in _MIGRATED:
        out["corrections"] = migrate_corrections_jsonl(
            presence_store, corrections_log
        )
        _MIGRATED.add((base, "corrections"))
    if (base, "taste") not in _MIGRATED:
        out["taste"] = migrate_taste_observations(
            presence_store, pipeline_db_path
        )
        _MIGRATED.add((base, "taste"))
    return out
