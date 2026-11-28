"""Temporal standing (Temporal Orchestration slice S1) — tests.

Span and allocation records ride the VE decisions store as dedicated
decision types; current standing is DERIVED by a materialized fold
stamped with a monotonic ``fold_seq``. These tests pin:

  (a) the §2 record shape — five orthogonal properties (origin,
      standing, conditionality, effort representation, role) survive
      a record → fold round-trip, with the confidence label DERIVED
      from the effort representation, never stored as free text;
  (b) canonical ``start_date`` / ``end_date`` are never written by
      recording standing — derived/provisional spans live only in
      the standing representation;
  (c) fold semantics — supersede replaces, withdrawal removes, spans
      partition by role, open-ended spans keep a null end;
  (d) conditionality is fail-closed — an assumption-set id that does
      not recompute from its own assumption ids drops the record;
  (e) the person-week allocation series materializes from allocation
      records (summed per person per ISO week, Monday-normalized),
      stamped with the fold_seq as its version;
  (f) fold_seq is monotonic over the WHOLE decision stream (a river
      declaration advances it too) and time-travel reads at an
      earlier stamp exclude later records;
  (g) owner isolation — another owner's records never fold in;
  (h) malformed records degrade to nothing, never to a broken fold.

Conventions: ALICE = "u1" (owner), BOB = "u2".
"""

from __future__ import annotations

import sqlite3

import pytest

from local_ai.vision_execution import declarations as D
from local_ai.vision_execution import models as M
from local_ai.vision_execution import service as ve_service
from local_ai.vision_execution import storage as S
from local_ai.vision_execution import temporal_standing as T

ALICE = "u1"
BOB = "u2"

#: sha256("\n".join(sorted(ids))) for the two assumption ids used in
#: the conditional tests — the frontend fold must derive the same id
#: for the same set (cross-language agreement is pinned there too).
ASSUMPTION_IDS = ["alloc-holds-tier1", "no-new-commitments"]
ASSUMPTION_SET_ID = "26a7c82c08b9411284435027591e266b5325053f96ede07a635151d612d99a23"
ASSUMPTIONS = [
    {
        "id": "alloc-holds-tier1",
        "type": "allocation",
        "statement": "Tier 1 keeps its recorded 5 h/week allocation, uninterrupted.",
    },
    {
        "id": "no-new-commitments",
        "type": "commitment",
        "statement": "No new established commitments land before the window closes.",
    },
]


@pytest.fixture()
def ve_conn(monkeypatch: pytest.MonkeyPatch):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    S.init_db(conn)
    monkeypatch.setattr(S, "get_connection", lambda: conn)
    yield conn
    conn.close()


def _make_project(user: str, title: str, **kw) -> dict:
    return ve_service.create_project(M.ProjectCreate(title=title, **kw), user)


def _envelope_span(**over) -> dict:
    span = {
        "start": "2026-10-20",
        "end": "2026-12-01",
        "origin": "evidence-recovered",
        "standing": "evidence-recovered envelope",
        "role": "window",
        "effort": {"kind": "exact", "hours": 12.0},
        "basis": ["recorded task due dates 2026-12-01"],
        "method": "evidence recovery over recorded task due dates",
        "note": "start is the project creation date — a fact about the record",
    }
    span.update(over)
    return span


# ---------------------------------------------------------------------------
# (a)+(b) round-trip and canonical-field discipline
# ---------------------------------------------------------------------------


def test_span_round_trip_carries_all_five_properties(ve_conn):
    p = _make_project(ALICE, "Meet the Bear")
    decision = T.record_span(ALICE, p["id"], _envelope_span())
    fold = T.derive_temporal_standing(ALICE)
    project = fold["projects"][p["id"]]
    assert len(project["spans"]) == 1
    span = project["spans"][0]
    assert span["id"] == decision["id"]
    assert span["start"] == "2026-10-20"
    assert span["end"] == "2026-12-01"
    assert span["origin"] == "evidence-recovered"
    assert span["standing"] == "evidence-recovered envelope"
    assert span["role"] == "window"
    assert span["conditionality"] == {"kind": "unconditional"}
    assert span["effort"] == {"kind": "exact", "hours": 12.0}
    assert span["confidence_label"] == "exact"
    assert span["basis"] == ["recorded task due dates 2026-12-01"]
    assert project["spans_by_role"]["window"] == [span]


def test_recording_standing_never_writes_canonical_dates(ve_conn):
    p = _make_project(ALICE, "Undated project")
    assert p["start_date"] is None and p["end_date"] is None
    T.record_span(ALICE, p["id"], _envelope_span())
    after = ve_service.get_project(p["id"], ALICE)
    assert after["start_date"] is None
    assert after["end_date"] is None


def test_confidence_label_follows_the_effort_representation(ve_conn):
    p = _make_project(ALICE, "Labels")
    cases = [
        ({"kind": "exact", "hours": 3}, "exact"),
        ({"kind": "interval", "low_hours": 2, "high_hours": 9}, "bounded interval"),
        ({"kind": "lower-bound", "hours": 2}, "lower bound only"),
        ({"kind": "upper-bound", "hours": 9}, "upper bound only"),
        ({"kind": "unknown"}, "unknown"),
    ]
    for effort, _label in cases:
        T.record_span(ALICE, p["id"], _envelope_span(effort=effort))
    fold = T.derive_temporal_standing(ALICE)
    labels = [s["confidence_label"] for s in fold["projects"][p["id"]]["spans"]]
    # All five spans share a window, so fold order among them is by
    # span id — compare the label SET each effort representation got.
    assert sorted(labels) == sorted(label for _effort, label in cases)


# ---------------------------------------------------------------------------
# (c) fold semantics: supersede / withdraw / roles / open-ended
# ---------------------------------------------------------------------------


def test_supersede_replaces_and_withdrawal_removes(ve_conn):
    p = _make_project(ALICE, "Tier 1")
    first = T.record_span(ALICE, p["id"], _envelope_span(end="2026-12-10"))
    second = T.record_span(
        ALICE, p["id"], _envelope_span(end="2026-12-17", supersedes=first["id"])
    )
    fold = T.derive_temporal_standing(ALICE)
    spans = fold["projects"][p["id"]]["spans"]
    assert [s["id"] for s in spans] == [second["id"]]
    assert spans[0]["end"] == "2026-12-17"

    T.withdraw_span(ALICE, p["id"], second["id"])
    fold = T.derive_temporal_standing(ALICE)
    assert p["id"] not in fold["projects"]


def test_withdrawal_of_a_span_that_does_not_stand_is_refused(ve_conn):
    p = _make_project(ALICE, "Nothing stands")
    with pytest.raises(ValueError):
        T.withdraw_span(ALICE, p["id"], "no-such-span")


def test_spans_partition_by_role_and_points_normalize(ve_conn):
    p = _make_project(ALICE, "Roles")
    T.record_span(ALICE, p["id"], _envelope_span(role="window"))
    T.record_span(
        ALICE,
        p["id"],
        _envelope_span(role="deadline", start="2026-12-03", end=None,
                       standing="visitor target", origin="visitor-recorded"),
    )
    T.record_span(
        ALICE,
        p["id"],
        _envelope_span(role="hold", start="2026-11-16", end="2026-11-20",
                       standing="established commitment", origin="visitor-recorded"),
    )
    fold = T.derive_temporal_standing(ALICE)
    by_role = fold["projects"][p["id"]]["spans_by_role"]
    assert set(by_role) == {"window", "deadline", "hold"}
    deadline = by_role["deadline"][0]
    # A deadline recorded with one bound is that moment, both sides.
    assert deadline["start"] == "2026-12-03"
    assert deadline["end"] == "2026-12-03"


def test_open_ended_span_keeps_its_null_end(ve_conn):
    p = _make_project(ALICE, "Tree as organism")
    T.record_span(ALICE, p["id"], _envelope_span(end=None))
    fold = T.derive_temporal_standing(ALICE)
    span = fold["projects"][p["id"]]["spans"][0]
    assert span["start"] == "2026-10-20"
    assert span["end"] is None


# ---------------------------------------------------------------------------
# (d) conditionality
# ---------------------------------------------------------------------------


def test_conditional_span_stamps_and_carries_its_assumption_set(ve_conn):
    p = _make_project(ALICE, "Tier 1 conditional")
    T.record_span(
        ALICE,
        p["id"],
        _envelope_span(
            standing="derived forecast",
            origin="derived",
            effort={"kind": "interval", "low_hours": 20, "high_hours": 30},
            assumptions=ASSUMPTIONS,
        ),
    )
    fold = T.derive_temporal_standing(ALICE)
    span = fold["projects"][p["id"]]["spans"][0]
    assert span["conditionality"]["kind"] == "conditional"
    assert span["conditionality"]["assumption_set_id"] == ASSUMPTION_SET_ID
    assert [a["id"] for a in span["conditionality"]["assumptions"]] == ASSUMPTION_IDS
    assert T.assumption_set_id(ASSUMPTION_IDS) == ASSUMPTION_SET_ID


def test_assumption_set_id_is_order_insensitive(ve_conn):
    assert T.assumption_set_id(list(reversed(ASSUMPTION_IDS))) == ASSUMPTION_SET_ID


def test_tampered_assumption_set_id_drops_the_record(ve_conn):
    p = _make_project(ALICE, "Forged conditions")
    payload = _envelope_span(
        conditionality={
            "kind": "conditional",
            "assumption_set_id": "0" * 64,
            "assumptions": ASSUMPTIONS,
        }
    )
    # Written raw, bypassing record_span's validation: the fold itself
    # must refuse a set id that does not recompute from its assumptions.
    S.create_decision(
        M.DecisionCreate(
            user_id=ALICE,
            entity_type="project",
            entity_id=p["id"],
            decision_type=T.SPAN_RECORDED,
            final_values_snapshot=payload,
        )
    )
    fold = T.derive_temporal_standing(ALICE)
    assert p["id"] not in fold["projects"]


def test_record_span_rejects_malformed_payloads(ve_conn):
    p = _make_project(ALICE, "Strict writer")
    with pytest.raises(ValueError):
        T.record_span(ALICE, p["id"], _envelope_span(standing="whenever"))
    with pytest.raises(ValueError):
        T.record_span(ALICE, p["id"], _envelope_span(effort={"kind": "vibes"}))
    with pytest.raises(ValueError):
        T.record_span(ALICE, p["id"], _envelope_span(start=None, end=None))
    with pytest.raises(ValueError):
        T.record_span(ALICE, p["id"], _envelope_span(end="2026-10-01"))


# ---------------------------------------------------------------------------
# (e) the person-week allocation series
# ---------------------------------------------------------------------------


def test_allocation_series_sums_per_person_per_week(ve_conn):
    T.record_allocation(ALICE, "person-1", "2026-11-30", 5.0, project_id="tier-1")
    # A Wednesday of the same ISO week lands in the same Monday bucket.
    T.record_allocation(ALICE, "person-1", "2026-12-02", 2.5, project_id="tier-3")
    T.record_allocation(ALICE, "person-1", "2026-12-07", 5.0, project_id="tier-1")
    T.record_allocation(ALICE, "person-2", "2026-11-30", 7.0)
    fold = T.derive_temporal_standing(ALICE)
    weeks = fold["allocations"]["person-1"]["weeks"]
    assert weeks["2026-11-30"]["established_hours"] == 7.5
    assert len(weeks["2026-11-30"]["entries"]) == 2
    assert weeks["2026-12-07"]["established_hours"] == 5.0
    assert fold["allocations"]["person-2"]["weeks"]["2026-11-30"][
        "established_hours"
    ] == 7.0
    assert fold["allocation_series_version"] == fold["fold_seq"]


def test_allocation_withdrawal_removes_its_hours(ve_conn):
    kept = T.record_allocation(ALICE, "person-1", "2026-11-30", 5.0)
    gone = T.record_allocation(ALICE, "person-1", "2026-11-30", 3.0)
    T.withdraw_allocation(ALICE, "person-1", gone["id"])
    fold = T.derive_temporal_standing(ALICE)
    bucket = fold["allocations"]["person-1"]["weeks"]["2026-11-30"]
    assert bucket["established_hours"] == 5.0
    assert [e["id"] for e in bucket["entries"]] == [kept["id"]]
    with pytest.raises(ValueError):
        T.withdraw_allocation(ALICE, "person-1", gone["id"])


# ---------------------------------------------------------------------------
# (f) fold_seq: monotonic over the whole stream; time-travel reads
# ---------------------------------------------------------------------------


def test_fold_seq_advances_on_any_decision_and_time_travels(ve_conn):
    p = _make_project(ALICE, "Sequenced")
    assert T.current_fold_seq(ALICE) == 0
    first = T.record_span(ALICE, p["id"], _envelope_span())
    seq_after_first = T.current_fold_seq(ALICE)
    assert seq_after_first > 0
    # A non-temporal decision (a river declaration) advances the stamp
    # too — fold_seq guards membership drift across the whole stream.
    D.record_declaration(
        ALICE, p["id"], D.RIVER_DECLARATION,
        {"start": "2026-11-01", "end": "2026-11-15"},
    )
    seq_after_river = T.current_fold_seq(ALICE)
    assert seq_after_river > seq_after_first
    second = T.record_span(ALICE, p["id"], _envelope_span(end="2026-12-08"))
    fold_now = T.derive_temporal_standing(ALICE)
    assert fold_now["fold_seq"] == T.current_fold_seq(ALICE)
    assert len(fold_now["projects"][p["id"]]["spans"]) == 2

    fold_then = T.derive_temporal_standing(ALICE, at_fold_seq=seq_after_first)
    assert fold_then["fold_seq"] == seq_after_first
    assert [s["id"] for s in fold_then["projects"][p["id"]]["spans"]] == [first["id"]]
    assert second["id"] not in {
        s["id"] for s in fold_then["projects"][p["id"]]["spans"]
    }


# ---------------------------------------------------------------------------
# (g)+(h) owner isolation; malformed rows degrade
# ---------------------------------------------------------------------------


def test_owner_isolation(ve_conn):
    p = _make_project(ALICE, "Alice only")
    T.record_span(ALICE, p["id"], _envelope_span())
    T.record_allocation(ALICE, "person-1", "2026-11-30", 5.0)
    bob_fold = T.derive_temporal_standing(BOB)
    assert bob_fold["projects"] == {}
    assert bob_fold["allocations"] == {}
    assert bob_fold["fold_seq"] == 0


def test_malformed_rows_degrade_to_nothing(ve_conn):
    p = _make_project(ALICE, "Corrupt neighbours")
    for payload in (
        {"start": "not-a-date", "end": "2026-12-01", "origin": "derived",
         "standing": "provisional", "role": "window"},
        {"start": "2026-11-01", "end": "2026-12-01", "origin": "derived",
         "standing": "provisional", "role": "window",
         "effort": {"kind": "interval", "low_hours": 9, "high_hours": 2}},
    ):
        S.create_decision(
            M.DecisionCreate(
                user_id=ALICE,
                entity_type="project",
                entity_id=p["id"],
                decision_type=T.SPAN_RECORDED,
                final_values_snapshot=payload,
            )
        )
    # A snapshot that is not even a mapping (written raw, as a legacy
    # or corrupt row could be) degrades the same way.
    ve_conn.execute(
        "INSERT INTO decisions (id, user_id, entity_type, entity_id,"
        " decision_type, ai_proposal_snapshot, final_values_snapshot,"
        " created_at) VALUES (?, ?, 'project', ?, ?, NULL, ?, ?)",
        ("corrupt-1", ALICE, p["id"], T.SPAN_RECORDED,
         '"not a mapping"', "2026-11-28T00:00:00"),
    )
    ve_conn.commit()
    T.record_span(ALICE, p["id"], _envelope_span())
    fold = T.derive_temporal_standing(ALICE)
    assert len(fold["projects"][p["id"]]["spans"]) == 1
