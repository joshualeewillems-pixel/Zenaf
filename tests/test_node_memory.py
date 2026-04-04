"""
Node memory layer (node_vitality, node_judgment_history) against an isolated temp SQLite DB.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest

from local_ai.judgment_substrate import (
    JudgmentMechanism,
    JudgmentObservation,
    JudgmentTrunk,
    JudgmentVerdict,
    SubjectRef,
)
from local_ai.vision_execution.storage import (
    append_node_judgment,
    append_resonance_rating,
    get_node_judgment_summary,
    get_node_vitality,
    get_resonance_pattern,
    init_db,
    list_node_judgments,
    list_node_vitality_for_user,
    open_sqlite_with_ve_pragmas,
    upsert_node_vitality,
)


@pytest.fixture
def ve_conn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "node_memory_ve.db"
    conn = open_sqlite_with_ve_pragmas(db_path)
    init_db(conn)
    import local_ai.vision_execution.storage as ve_storage

    monkeypatch.setattr(ve_storage, "get_connection", lambda: conn)
    yield conn
    conn.close()


def test_upsert_node_vitality_create_update_same_subject_and_unique(ve_conn: sqlite3.Connection) -> None:
    uid, et, eid = "user-a", "task", "task-1"
    id1 = upsert_node_vitality(
        uid,
        et,
        eid,
        {
            "last_assessed_at": "2026-01-01T12:00:00+00:00",
            "triggered_by_event_id": "act-1",
            "staleness_days": 1.0,
        },
    )
    row1 = get_node_vitality(uid, et, eid)
    assert row1 is not None
    assert row1["id"] == id1
    assert row1["triggered_by_event_id"] == "act-1"
    assert float(row1["staleness_days"]) == 1.0

    id2 = upsert_node_vitality(
        uid,
        et,
        eid,
        {
            "last_assessed_at": "2026-01-15T12:00:00+00:00",
            "triggered_by_event_id": "act-2",
            "staleness_days": 0.0,
        },
    )
    assert id2 == id1
    row2 = get_node_vitality(uid, et, eid)
    assert row2 is not None
    assert row2["last_assessed_at"] == "2026-01-15T12:00:00+00:00"
    assert row2["triggered_by_event_id"] == "act-2"
    assert float(row2["staleness_days"]) == 0.0

    # UNIQUE(user_id, entity_type, entity_id): second INSERT with same key must fail
    from local_ai.vision_execution import models as M

    dup_id = M.new_id()
    with pytest.raises(sqlite3.IntegrityError):
        ve_conn.execute(
            """
            INSERT INTO node_vitality (
              id, user_id, entity_type, entity_id, water, soil, fruit, staleness_days,
              last_activity_at, last_assessed_at, triggered_by_event_id, rules_version, payload_json
            ) VALUES (?, ?, ?, ?, 0, 0, 0, 0, NULL, ?, NULL, 'v1', NULL)
            """,
            (dup_id, uid, et, eid, "2026-02-01T00:00:00+00:00"),
        )


def test_get_node_vitality_hit_and_miss(ve_conn: sqlite3.Connection) -> None:
    upsert_node_vitality("u1", "idea", "idea-99", {"last_assessed_at": "2026-03-01T00:00:00+00:00"})
    got = get_node_vitality("u1", "idea", "idea-99")
    assert got is not None
    assert got["entity_id"] == "idea-99"
    assert got["user_id"] == "u1"
    assert get_node_vitality("u1", "idea", "no-such") is None
    assert get_node_vitality("other", "idea", "idea-99") is None


def test_list_node_vitality_for_user_entity_type_filter(ve_conn: sqlite3.Connection) -> None:
    upsert_node_vitality("u2", "idea", "i1", {"last_assessed_at": "2026-01-01T00:00:01+00:00"})
    upsert_node_vitality("u2", "task", "t1", {"last_assessed_at": "2026-01-01T00:00:02+00:00"})
    upsert_node_vitality("u2", "project", "p1", {"last_assessed_at": "2026-01-01T00:00:03+00:00"})
    ideas_only = list_node_vitality_for_user("u2", entity_type="idea", limit=50)
    assert len(ideas_only) == 1
    assert ideas_only[0]["entity_type"] == "idea"
    assert ideas_only[0]["entity_id"] == "i1"
    all_rows = list_node_vitality_for_user("u2", entity_type=None, limit=50)
    assert len(all_rows) == 3
    types = {r["entity_type"] for r in all_rows}
    assert types == {"idea", "task", "project"}


def _sample_trunk(*, verdict_kind: str = "test_verdict", effect: str = "none", state: str = "proposed") -> JudgmentTrunk:
    return JudgmentTrunk(
        subject=SubjectRef(entity_type="initiative", entity_id="init-1", title="T"),
        observation=JudgmentObservation(pointer="ptr-1", context={"k": 1}),
        verdict=JudgmentVerdict(kind=verdict_kind, payload={"x": 1}),
        mechanism=JudgmentMechanism(mode="llm", model_id="m1"),
        effect=effect,  # type: ignore[arg-type]
        state=state,  # type: ignore[arg-type]
    )


def test_append_node_judgment_requires_trunk_and_stores_columns(ve_conn: sqlite3.Connection) -> None:
    with pytest.raises(TypeError, match="JudgmentTrunk"):
        append_node_judgment("u3", "task", "t1", {"not": "a trunk"}, refs={})

    trunk = _sample_trunk(verdict_kind="council_seat", effect="stream_only", state="applied")
    jid = append_node_judgment(
        "u3",
        "initiative",
        "init-1",
        trunk,
        refs={"council_stream_run_id": "csr-1", "decision_id": None},
    )
    assert jid
    row = ve_conn.execute(
        "SELECT verdict_kind, effect, state, mechanism_mode, council_stream_run_id, trunk_json FROM node_judgment_history WHERE id = ?",
        (jid,),
    ).fetchone()
    assert row is not None
    assert row["verdict_kind"] == "council_seat"
    assert row["effect"] == "stream_only"
    assert row["state"] == "applied"
    assert row["mechanism_mode"] == "llm"
    assert row["council_stream_run_id"] == "csr-1"
    assert "council_seat" in (row["trunk_json"] or "")


def test_list_node_judgments_newest_first_and_parsed_trunk(ve_conn: sqlite3.Connection) -> None:
    uid, et, eid = "u4", "project", "proj-1"
    t1 = _sample_trunk(verdict_kind="first", effect="none", state="proposed")
    t2 = _sample_trunk(verdict_kind="second", effect="none", state="applied")
    id1 = append_node_judgment(uid, et, eid, t1, refs={})
    time.sleep(0.02)
    id2 = append_node_judgment(uid, et, eid, t2, refs={})
    rows = list_node_judgments(uid, et, eid, limit=20)
    assert len(rows) == 2
    assert rows[0]["id"] == id2
    assert rows[1]["id"] == id1
    assert "trunk_json" not in rows[0]
    assert rows[0]["trunk"]["verdict"]["kind"] == "second"
    assert rows[1]["trunk"]["verdict"]["kind"] == "first"


def test_append_resonance_rating(ve_conn: sqlite3.Connection) -> None:
    uid, et, eid = "u-res", "workspace", "ws-abc123"
    jid = append_resonance_rating(
        uid,
        et,
        eid,
        0.82,
        "resp-seat-1",
        "strategist",
        "council_seat",
        None,
    )
    assert jid
    row = ve_conn.execute(
        "SELECT verdict_kind, effect, state, mechanism_mode, trunk_json FROM node_judgment_history WHERE id = ?",
        (jid,),
    ).fetchone()
    assert row is not None
    assert row["verdict_kind"] == "resonance_rating"
    assert row["effect"] == "persist_decision"
    assert row["state"] == "applied"
    assert row["mechanism_mode"] == "human_override"
    trunk = json.loads(row["trunk_json"])
    assert trunk["verdict"]["kind"] == "resonance_rating"
    pl = trunk["verdict"]["payload"]
    assert pl["score"] == pytest.approx(0.82)
    assert pl["response_id"] == "resp-seat-1"
    assert pl["seat_id"] == "strategist"
    assert pl["context_kind"] == "council_seat"
    assert pl["subject_perspective_id"] is None


def test_get_resonance_pattern(ve_conn: sqlite3.Connection) -> None:
    uid = "u-pat"
    append_resonance_rating(uid, "core_profile", "cp-1", 0.8, "r1", "zenaf", "zenaf_training", None)
    time.sleep(0.02)
    append_resonance_rating(uid, "core_profile", "cp-1", 0.2, "r2", "strategist", "council_seat", None)
    time.sleep(0.02)
    append_resonance_rating(uid, "core_profile", "cp-1", 0.9, "r3", "strategist", "council_seat", None)
    time.sleep(0.02)
    append_resonance_rating(uid, "core_profile", "cp-1", 0.1, "r4", "analyst", "council_seat", None)

    full = get_resonance_pattern(uid, limit=100)
    assert full["total_ratings"] == 4
    assert full["average_score"] == pytest.approx((0.8 + 0.2 + 0.9 + 0.1) / 4)
    assert full["high_resonance_count"] == 2
    assert full["low_resonance_count"] == 2
    assert full["average_by_seat_id"]["zenaf"] == pytest.approx(0.8)
    assert full["average_by_seat_id"]["strategist"] == pytest.approx((0.2 + 0.9) / 2)
    assert full["average_by_context_kind"]["zenaf_training"] == pytest.approx(0.8)
    assert full["average_by_context_kind"]["council_seat"] == pytest.approx((0.2 + 0.9 + 0.1) / 3)

    filtered = get_resonance_pattern(uid, context_kind="council_seat", seat_id="strategist", limit=100)
    assert filtered["total_ratings"] == 2
    assert filtered["average_score"] == pytest.approx((0.2 + 0.9) / 2)
    assert filtered["average_by_seat_id"]["strategist"] == pytest.approx((0.2 + 0.9) / 2)
    assert filtered["high_resonance_count"] == 1
    assert filtered["low_resonance_count"] == 1


def _set_judgment_created_at(ve_conn: sqlite3.Connection, jid: str, created_at: str) -> None:
    ve_conn.execute(
        "UPDATE node_judgment_history SET created_at = ? WHERE id = ?",
        (created_at, jid),
    )
    ve_conn.commit()


def test_escalation_signal_derivation(ve_conn: sqlite3.Connection) -> None:
    uid = "u-esc"
    et, eid = "core_profile", "cp-x"

    # Level 1: sparse
    append_resonance_rating(uid, et, eid, 0.5, "a1", "zenaf", "zenaf_training", None)
    p1 = get_resonance_pattern(uid, limit=200)
    assert p1["total_ratings"] == 1
    assert p1["escalation_signal"]["current_level"] == 1
    assert p1["escalation_signal"]["recommended_approach"] == "exploration"
    assert p1["escalation_signal"]["confidence"] < 0.5

    # Level 1: high average with more ratings (engaged)
    for i in range(6):
        append_resonance_rating(uid, et, eid, 0.85, f"hi{i}", "zenaf", "zenaf_training", None)
    p_eng = get_resonance_pattern(uid, limit=200)
    assert p_eng["total_ratings"] == 7
    assert p_eng["escalation_signal"]["current_level"] == 1
    assert p_eng["escalation_signal"]["recommended_approach"] == "exploration"
    assert p_eng["escalation_signal"]["confidence"] > 0.5

    # Fresh user for level 2: 5+ ratings, 2 sessions, same seat with 3× scores in [0.4, 0.7]
    uid2 = "u-esc2"
    j0 = append_resonance_rating(uid2, et, eid, 0.5, "l2a", "strategist", "council_seat", None)
    _set_judgment_created_at(ve_conn, j0, "2026-01-01T10:00:00+00:00")
    for i, sc in enumerate([0.45, 0.55, 0.65, 0.8]):
        jid = append_resonance_rating(uid2, et, eid, sc, f"l2b{i}", "strategist", "council_seat", None)
        _set_judgment_created_at(ve_conn, jid, "2026-02-02T10:00:00+00:00")
    p2 = get_resonance_pattern(uid2, limit=200)
    assert p2["total_ratings"] == 5
    assert p2["escalation_signal"]["current_level"] == 2
    assert p2["escalation_signal"]["recommended_approach"] == "recognition"

    # Level 3: zenaf_training high vs council_seat lower (10+ total)
    uid3 = "u-esc3"
    for i in range(5):
        jid = append_resonance_rating(uid3, et, eid, 0.9, f"z{i}", "zenaf", "zenaf_training", None)
        _set_judgment_created_at(ve_conn, jid, "2026-03-01T12:00:00+00:00")
    for i in range(5):
        jid = append_resonance_rating(uid3, et, eid, 0.35, f"c{i}", "strategist", "council_seat", None)
        _set_judgment_created_at(ve_conn, jid, "2026-03-02T12:00:00+00:00")
    p3 = get_resonance_pattern(uid3, limit=200)
    assert p3["total_ratings"] == 10
    assert p3["escalation_signal"]["current_level"] == 3
    assert p3["escalation_signal"]["recommended_approach"] == "loop"

    # Level 4: drop on governance / skeptic council seats vs baseline
    uid4 = "u-esc4"
    for i in range(4):
        jid = append_resonance_rating(uid4, et, eid, 0.85, f"ok{i}", "zenaf", "zenaf_training", None)
        _set_judgment_created_at(ve_conn, jid, "2026-04-01T12:00:00+00:00")
    for i in range(4):
        jid = append_resonance_rating(uid4, et, eid, 0.25, f"gov{i}", "governance", "council_seat", None)
        _set_judgment_created_at(ve_conn, jid, "2026-04-02T12:00:00+00:00")
    p4 = get_resonance_pattern(uid4, limit=200)
    assert p4["total_ratings"] == 8
    assert p4["escalation_signal"]["current_level"] == 4
    assert p4["escalation_signal"]["recommended_approach"] == "avoidance"

    # Level 5: level-4 pattern + 20+ ratings + 3+ session days + confidence > 0.75
    uid5 = "u-esc5"
    days = ("2026-05-01T12:00:00+00:00", "2026-05-15T12:00:00+00:00", "2026-05-30T12:00:00+00:00")
    for i in range(14):
        jid = append_resonance_rating(uid5, et, eid, 0.9, f"ok5-{i}", "brand", "council_seat", None)
        _set_judgment_created_at(ve_conn, jid, days[i % 3])
    for i in range(10):
        jid = append_resonance_rating(uid5, et, eid, 0.15, f"sk-{i}", "skeptic", "council_seat", None)
        _set_judgment_created_at(ve_conn, jid, days[i % 3])
    p5 = get_resonance_pattern(uid5, limit=200)
    assert p5["total_ratings"] == 24
    assert p5["escalation_signal"]["current_level"] == 5
    assert p5["escalation_signal"]["recommended_approach"] == "confrontation"
    assert p5["escalation_signal"]["confidence"] > 0.75

    # Many ratings + sessions but no avoidance/challenge gap → never level 5 (high engagement)
    uid6 = "u-esc6"
    for i in range(25):
        jid = append_resonance_rating(uid6, et, eid, 0.72, f"flat{i}", "zenaf", "zenaf_training", None)
        _set_judgment_created_at(ve_conn, jid, days[i % 3])
    p6 = get_resonance_pattern(uid6, limit=200)
    assert p6["total_ratings"] == 25
    assert p6["escalation_signal"]["current_level"] != 5
    assert p6["escalation_signal"]["recommended_approach"] == "exploration"


def test_get_node_judgment_summary(ve_conn: sqlite3.Connection) -> None:
    uid, et, eid = "u5", "idea", "idea-x"
    empty = get_node_judgment_summary(uid, et, eid)
    assert empty["count"] == 0
    assert empty["latest_state"] is None
    assert empty["latest_verdict_kind"] is None
    assert empty["latest_created_at"] is None

    append_node_judgment(uid, et, eid, _sample_trunk(verdict_kind="v1", state="proposed"), refs={})
    time.sleep(0.02)
    append_node_judgment(uid, et, eid, _sample_trunk(verdict_kind="v2", state="dismissed"), refs={})
    summ = get_node_judgment_summary(uid, et, eid)
    assert summ["count"] == 2
    assert summ["latest_verdict_kind"] == "v2"
    assert summ["latest_state"] == "dismissed"
    assert summ["latest_created_at"]
