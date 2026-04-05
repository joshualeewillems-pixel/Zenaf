"""Coordination layer: execution_flow_reading validation and client checkpoint ownership."""
from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest

from local_ai.vision_execution.coordination_signals import (
    append_execution_flow_reading,
    list_execution_flow_summaries_for_entity,
    summarize_execution_flow_trunk,
)
from local_ai.vision_execution.storage import (
    init_db,
    log_coordination_client_checkpoint,
    materialize_execution_steps,
    open_sqlite_with_ve_pragmas,
)


@pytest.fixture
def ve_conn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "coord_ve.db"
    conn = open_sqlite_with_ve_pragmas(db_path)
    init_db(conn)
    import local_ai.vision_execution.storage as ve_storage

    monkeypatch.setattr(ve_storage, "get_connection", lambda: conn)
    yield conn
    conn.close()


def _insert_project(conn: sqlite3.Connection, user_id: str, project_id: str) -> None:
    now = "2026-04-01T12:00:00+00:00"
    conn.execute(
        """INSERT INTO projects (
          id, user_id, initiative_id, title, brief, status, supporting_owner_ids, required_assets,
          priority, deliverables, complexity, current_focus, next_step_ai, notes, created_at, updated_at
        ) VALUES (?, ?, NULL, 'P', '', 'Draft', '[]', '[]', '', '', '', '', '', '', ?, ?)""",
        (project_id, user_id, now, now),
    )
    conn.commit()


def test_append_execution_flow_reading_rejects_pointer_evidence_mismatch() -> None:
    with pytest.raises(ValueError, match="council_stream"):
        append_execution_flow_reading(
            user_id="u1",
            entity_type="initiative",
            entity_id="i1",
            pointer="act-1",
            pointer_kind="activity_event",
            evidence_source="council_stream",
            impact="neutral",
            dimension="clarity",
            confidence=0.5,
        )


def test_append_execution_flow_reading_rejects_bad_payload_keys() -> None:
    # Exercised only via internal _validate — use wrong confidence
    with pytest.raises(ValueError, match="confidence"):
        append_execution_flow_reading(
            user_id="u1",
            entity_type="initiative",
            entity_id="i1",
            pointer="act-1",
            pointer_kind="activity_event",
            evidence_source="server-execution",
            impact="neutral",
            dimension="clarity",
            confidence=1.5,
        )


def test_append_and_summarize_execution_flow_reading(ve_conn: sqlite3.Connection) -> None:
    append_execution_flow_reading(
        user_id="u1",
        entity_type="initiative",
        entity_id="in-1",
        pointer="evt-abc",
        pointer_kind="activity_event",
        evidence_source="server-execution",
        impact="positive",
        dimension="capacity",
        confidence=0.7,
    )
    sums = list_execution_flow_summaries_for_entity("u1", "initiative", "in-1", limit=10)
    assert len(sums) == 1
    assert sums[0]["impact"] == "positive"
    assert sums[0]["dimension"] == "capacity"
    assert sums[0]["confidence"] == pytest.approx(0.7)
    assert sums[0]["pointer"] == "evt-abc"
    assert sums[0]["pointer_kind"] == "activity_event"
    assert sums[0]["coordination_evidence_source"] == "server-execution"
    assert sums[0]["judgment_row_id"]


def test_summarize_execution_flow_trunk_filters_other_verdicts() -> None:
    assert summarize_execution_flow_trunk({"verdict": {"kind": "other"}}) is None


def test_log_coordination_client_checkpoint_requires_owned_entity(ve_conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="not found"):
        log_coordination_client_checkpoint(
            "user-x",
            "ai_suggestion_applied",
            "project",
            "missing-proj",
        )
    _insert_project(ve_conn, "user-x", "proj-ok")
    aid = log_coordination_client_checkpoint(
        "user-x",
        "ai_suggestion_applied",
        "project",
        "proj-ok",
        trace_id="tr-1",
        user_outcome="applied",
    )
    assert aid
    sums = list_execution_flow_summaries_for_entity("user-x", "project", "proj-ok", limit=10)
    linked = [s for s in sums if s.get("pointer") == aid and s.get("pointer_kind") == "activity_event"]
    assert len(linked) == 1
    assert linked[0].get("coordination_evidence_source") == "atria-client-trace"
    assert linked[0].get("impact") == "positive"
    assert linked[0].get("dimension") == "capacity"
    assert linked[0].get("confidence") == pytest.approx(0.6)


def test_log_coordination_client_checkpoint_suggestion_dismissed_writes_friction_negative(
    ve_conn: sqlite3.Connection,
) -> None:
    _insert_project(ve_conn, "user-x", "proj-neu")
    aid = log_coordination_client_checkpoint(
        "user-x",
        "ai_suggestion_applied",
        "project",
        "proj-neu",
        user_outcome="dismissed",
    )
    sums = list_execution_flow_summaries_for_entity("user-x", "project", "proj-neu", limit=10)
    linked = [s for s in sums if s.get("pointer") == aid]
    assert len(linked) == 1
    assert linked[0].get("impact") == "negative"
    assert linked[0].get("dimension") == "friction"
    assert linked[0].get("confidence") == pytest.approx(0.6)


def test_log_coordination_client_checkpoint_suggestion_stuck_writes_friction_negative(
    ve_conn: sqlite3.Connection,
) -> None:
    _insert_project(ve_conn, "user-x", "proj-stuck")
    aid = log_coordination_client_checkpoint(
        "user-x",
        "ai_suggestion_applied",
        "project",
        "proj-stuck",
        user_outcome="stuck",
    )
    sums = list_execution_flow_summaries_for_entity("user-x", "project", "proj-stuck", limit=10)
    linked = [s for s in sums if s.get("pointer") == aid]
    assert len(linked) == 1
    assert linked[0].get("impact") == "negative"
    assert linked[0].get("dimension") == "friction"


def test_log_coordination_client_checkpoint_suggestion_other_outcome_stays_neutral_flow_reading(
    ve_conn: sqlite3.Connection,
) -> None:
    _insert_project(ve_conn, "user-x", "proj-other")
    aid = log_coordination_client_checkpoint(
        "user-x",
        "ai_suggestion_applied",
        "project",
        "proj-other",
        user_outcome="copied",
    )
    sums = list_execution_flow_summaries_for_entity("user-x", "project", "proj-other", limit=10)
    linked = [s for s in sums if s.get("pointer") == aid]
    assert len(linked) == 1
    assert linked[0].get("impact") == "neutral"
    assert linked[0].get("confidence") == pytest.approx(0.5)


def test_two_applied_suggestion_checkpoints_produce_two_positive_human_flow_readings(
    ve_conn: sqlite3.Connection,
) -> None:
    """Production-shaped inputs for frontend ≥2 positive activity_event + atria-client-trace cluster."""
    _insert_project(ve_conn, "user-z", "proj-p2")
    log_coordination_client_checkpoint(
        "user-z",
        "ai_suggestion_applied",
        "project",
        "proj-p2",
        user_outcome="applied",
        trace_id="t-a",
    )
    log_coordination_client_checkpoint(
        "user-z",
        "ai_suggestion_applied",
        "project",
        "proj-p2",
        user_outcome="applied",
        trace_id="t-b",
    )
    sums = list_execution_flow_summaries_for_entity("user-z", "project", "proj-p2", limit=20)
    human_pos = [
        s
        for s in sums
        if s.get("impact") == "positive"
        and s.get("pointer_kind") == "activity_event"
        and s.get("coordination_evidence_source") == "atria-client-trace"
    ]
    assert len(human_pos) >= 2
    for s in human_pos:
        assert s.get("confidence") == pytest.approx(0.6)


def test_append_council_stream_run_pointer_requires_persisted_row(ve_conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    import local_ai.vision_execution.storage as ve_storage

    monkeypatch.setattr(ve_storage, "get_connection", lambda: ve_conn)
    rid = ve_storage.append_council_stream_run(
        {"user_id": "cx-user", "integrity_run_id": "integ-1", "artifact": {}, "full_text": ""}
    )
    append_execution_flow_reading(
        user_id="cx-user",
        entity_type="initiative",
        entity_id="in-cx",
        pointer=rid,
        pointer_kind="council_stream_run",
        evidence_source="council_stream",
        impact="neutral",
        dimension="clarity",
        confidence=0.5,
    )
    fake = str(uuid.uuid4())
    with pytest.raises(ValueError, match="council_stream_run"):
        append_execution_flow_reading(
            user_id="cx-user",
            entity_type="initiative",
            entity_id="in-cx",
            pointer=fake,
            pointer_kind="council_stream_run",
            evidence_source="council_stream",
            impact="neutral",
            dimension="clarity",
            confidence=0.5,
        )
    with pytest.raises(ValueError, match="council_stream_run"):
        append_execution_flow_reading(
            user_id="wrong-user",
            entity_type="initiative",
            entity_id="in-cx",
            pointer=rid,
            pointer_kind="council_stream_run",
            evidence_source="council_stream",
            impact="neutral",
            dimension="clarity",
            confidence=0.5,
        )


def test_materialize_logs_coordination_checkpoint(ve_conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    from local_ai.vision_execution import storage as ve_storage

    uid, iid = "mu1", "init-m1"
    now = "2026-04-02T00:00:00+00:00"
    ve_conn.execute(
        """INSERT INTO initiatives (
          id, user_id, title, brief, status, estimated_cost_ai, estimated_timeframe_ai,
          philosophical_alignment_ai, next_step_ai, required_people, required_assets,
          dependencies, risks, recommendation, counts_toward_capacity, manual_override,
          kill_criteria, notes, created_at, updated_at
        ) VALUES (?, ?, 'I', '', 'Draft', '', '', '', '', '[]', '[]', '', '', '', 1, '', '', '', ?, ?)""",
        (iid, uid, now, now),
    )
    ve_conn.commit()
    calls: list[tuple[str, str, str]] = []

    def _capture(**kwargs):
        calls.append((kwargs["type"], kwargs["entity_type"], kwargs["entity_id"]))
        return "evt-x"

    monkeypatch.setattr(ve_storage, "_log_coordination_ve_activity", _capture)
    materialize_execution_steps(uid, ve_storage.EXECUTION_STEPS_SCOPE_INITIATIVE, iid, ["a", "b"], "ai", replace=False)
    assert len(calls) == 1
    from local_ai.activity import ActivityType

    assert calls[0][0] == ActivityType.EXECUTION_STEP_MATERIALIZED.value
    assert calls[0][1] == "initiative"
    assert calls[0][2] == iid
