"""Temporal diagnosis + establishment (Temporal Orchestration S4).

Pins the S4 share of brief §9 against a Tier-1/Tier-2-shaped
fixture world (one person, 10 h/week recorded capacity; Tier 1
Active with 20 h of work; Tier 2 — Validation trials, Draft, its
tasks depending on Tier 1's):

  - diagnosis assembly from the record (typed nodes, unresolved
    questions as named nodes, owner isolation);
  - diagnosis correction as a new version (the approved version is
    the one established);
  - the happy path: arrangement computed (Tier 2's earliest-found
    start not before its Tier 1 prerequisite's baseline finish),
    approval, establishment — canonical writes with origin_*
    provenance, the forecast span and allocation records folded;
  - the stale-record battery: capacity drift, protected time
    added (a decision-recorded hold), deadline tightened,
    dependency added, estimate changed, item deleted, kernel
    version changed — each aborts establishment enumerating the
    offender, and writes nothing;
  - concurrent establishment: a second establishment against the
    same person-week buckets fails its optimistic check;
  - failed establishment: one element's dependency is deleted
    after approval — per-element outcomes with failure classes,
    no writes for the failed element, proposal left revisable;
  - partial approval: a subset excluding a prerequisite leaves
    the dependent element external-gated and refused;
  - seat carriage: Valen's prepared context for Tier 2 carries the
    diagnosis summary and the kernel's arrangement figures.

Conventions: ALICE = "u1" (owner), BOB = "u2". All dates are
pinned via an explicit kernel anchor (start_week 2026-11-02, a
Monday).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from local_ai.conversation import context_preparation as CP
from local_ai.conversation.store import ConversationStore
from local_ai.vision_execution import models as M
from local_ai.vision_execution import service as ve_service
from local_ai.vision_execution import storage as S
from local_ai.vision_execution import temporal_diagnosis as TD
from local_ai.vision_execution import temporal_kernel as K
from local_ai.vision_execution import temporal_standing as T

ALICE = "u1"
BOB = "u2"
ANCHOR = "2026-11-02"  # a Monday


@pytest.fixture()
def ve_conn(monkeypatch: pytest.MonkeyPatch):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    S.init_db(conn)
    monkeypatch.setattr(S, "get_connection", lambda: conn)
    yield conn
    conn.close()


def _world(capacity: float = 10.0) -> dict:
    """The Tier-shaped world. Returns the rows a test needs."""
    person = ve_service.create_person(M.PersonCreate(name="Sam Reyes"), ALICE)
    S.upsert_capacity_profile(
        M.CapacityProfileUpsert(
            person_id=person["id"], weekly_capacity_hours=capacity
        ),
        ALICE,
    )
    tier1 = ve_service.create_project(
        M.ProjectCreate(
            title="Tier 1 — Foundation",
            status="Active",
            owner_id=person["id"],
            estimated_weekly_hours=5,
        ),
        ALICE,
    )
    t1 = ve_service.create_task(
        M.TaskCreate(
            title="Tier 1 core build",
            project_id=tier1["id"],
            estimated_hours=20,
            completion_criteria="core build merged",
        ),
        ALICE,
    )
    tier2 = ve_service.create_project(
        M.ProjectCreate(
            title="Tier 2 — Validation trials",
            status="Draft",
            owner_id=person["id"],
        ),
        ALICE,
    )
    t2a = ve_service.create_task(
        M.TaskCreate(
            title="Design the trials",
            project_id=tier2["id"],
            estimated_hours=10,
            completion_criteria="trial plan recorded",
            dependency_ids=[t1["id"]],
        ),
        ALICE,
    )
    t2b = ve_service.create_task(
        M.TaskCreate(
            title="Run the trials",
            project_id=tier2["id"],
            estimated_hours=15,
            completion_criteria="trial results recorded",
            dependency_ids=[t2a["id"]],
        ),
        ALICE,
    )
    return {
        "person": person,
        "tier1": tier1,
        "tier2": tier2,
        "t1": t1,
        "t2a": t2a,
        "t2b": t2b,
    }


def _approved(world: dict, **compute_kw) -> dict:
    """Assemble → compute → approve. Returns the approved proposal."""
    proposal = TD.assemble_diagnosis(ALICE, world["tier2"]["id"])
    proposal = TD.compute_diagnosis_arrangement(
        ALICE, proposal["id"], start_week=ANCHOR, **compute_kw
    )
    TD.approve_diagnosis_proposal(ALICE, proposal["id"])
    return TD.get_diagnosis_proposal(ALICE, proposal["id"])


# ---------------------------------------------------------------------------
# diagnosis assembly
# ---------------------------------------------------------------------------


def test_diagnosis_assembly_from_record(ve_conn):
    w = _world()
    # One more Tier 2 task with no estimate and no criteria: the
    # diagnosis must name both as unresolved questions.
    ve_service.create_task(
        M.TaskCreate(title="Unscoped follow-up", project_id=w["tier2"]["id"]),
        ALICE,
    )
    proposal = TD.assemble_diagnosis(ALICE, w["tier2"]["id"])
    assert proposal["state"] == "pending"
    assert proposal["version"] == 1
    diagnosis = proposal["diagnosis"]
    assert diagnosis["goal"]["title"] == "Tier 2 — Validation trials"
    nodes = {n["id"]: n for n in diagnosis["tasks"]}
    assert len(nodes) == 3
    a = nodes[f"task:{w['t2a']['id']}"]
    assert a["origin"] == "visitor-recorded"
    assert a["effort"] == {"kind": "exact", "hours": 10.0}
    assert a["confidence_label"] == "exact"
    assert a["dependencies"] == [w["t1"]["id"]]
    reqs = {r["id"]: r for r in diagnosis["requirements"]}
    assert reqs[f"req:{w['t2a']['id']}"]["acceptance_criteria"] == (
        "trial plan recorded"
    )
    qids = {q["id"] for q in diagnosis["unresolved_questions"]}
    unscoped = [
        t
        for t in S.list_tasks(ALICE, project_id=w["tier2"]["id"])
        if t["title"] == "Unscoped follow-up"
    ][0]
    assert f"q:estimate:{unscoped['id']}" in qids
    assert f"q:criteria:{unscoped['id']}" in qids
    # Assembly is a proposal: no decisions, no canonical changes.
    assert S.list_decisions(ALICE) == []
    # Owner isolation: Bob cannot assemble Alice's project.
    with pytest.raises(TD.DiagnosisNotFound):
        TD.assemble_diagnosis(BOB, w["tier2"]["id"])


def test_diagnosis_correction_new_version_and_approved_version_establishes(
    ve_conn,
):
    w = _world()
    v1 = TD.assemble_diagnosis(ALICE, w["tier2"]["id"])
    node_id = f"task:{w['t2a']['id']}"
    v2 = TD.edit_diagnosis_proposal(
        ALICE,
        v1["id"],
        {"tasks": {node_id: {"effort": {"kind": "exact", "hours": 12.0}}}},
    )
    assert v2["version"] == 2
    assert TD.get_diagnosis_proposal(ALICE, v1["id"])["state"] == "superseded"
    v2 = TD.compute_diagnosis_arrangement(ALICE, v2["id"], start_week=ANCHOR)
    TD.approve_diagnosis_proposal(ALICE, v2["id"])
    # The superseded version can no longer establish.
    with pytest.raises(TD.DiagnosisConflict):
        TD.establish_diagnosis_proposal(ALICE, v1["id"])
    report = TD.establish_diagnosis_proposal(ALICE, v2["id"])
    assert report["status"] == "established"
    # The correction in the APPROVED version is what landed.
    assert S.get_task(w["t2a"]["id"], ALICE)["estimated_hours"] == 12.0
    outcomes = {e["element_id"]: e for e in report["elements"]}
    assert outcomes[node_id]["status"] == "updated"


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


def test_happy_path_arrangement_and_establishment(ve_conn):
    w = _world()
    proposal = TD.assemble_diagnosis(ALICE, w["tier2"]["id"])
    proposal = TD.compute_diagnosis_arrangement(
        ALICE, proposal["id"], start_week=ANCHOR
    )
    arrangement = proposal["arrangement"]
    assert arrangement["status"] == "ok"
    # Tier 2's first task cannot start before its Tier 1
    # prerequisite finishes in the baseline (the frozen world).
    baseline = arrangement["baseline"]
    earliest = arrangement["earliest_found"]
    t1_finish_boundary = baseline["task_weeks"][w["t1"]["id"]]["finish_boundary"]
    t2a_start = earliest["task_weeks"][w["t2a"]["id"]]["start_week"]
    assert t2a_start >= t1_finish_boundary
    basis = proposal["basis"]
    assert basis["kernel_version"] == K.KERNEL_VERSION
    assert basis["fold_seq"] == arrangement["labels"]["fold_seq"]
    assert basis["algo_settings_hash"] == arrangement["labels"][
        "algo_settings_hash"
    ]
    assert f"task:{w['t1']['id']}" in basis["entity_version_vector"]

    # Add a proposed node, re-approve the new version, establish.
    proposal = TD.edit_diagnosis_proposal(
        ALICE,
        proposal["id"],
        {
            "add_tasks": [
                {
                    "id": "task:prop:write-up",
                    "title": "Write up the trial results",
                    "effort": {"kind": "exact", "hours": 5.0},
                    "dependencies": [w["t2b"]["id"]],
                    "completion_criteria": "write-up recorded",
                }
            ]
        },
    )
    proposal = TD.compute_diagnosis_arrangement(
        ALICE, proposal["id"], start_week=ANCHOR
    )
    approval = TD.approve_diagnosis_proposal(ALICE, proposal["id"])
    assert approval["external_gates"] == []
    report = TD.establish_diagnosis_proposal(ALICE, proposal["id"])
    assert report["status"] == "established", report
    outcomes = {e["element_id"]: e for e in report["elements"]}
    assert outcomes[f"task:{w['t2a']['id']}"]["status"] == "already_canonical"
    created_id = outcomes["task:prop:write-up"]["created_task_id"]
    assert outcomes["task:prop:write-up"]["status"] == "established"
    created = S.get_task(created_id, ALICE)
    assert created["title"] == "Write up the trial results"
    assert created["dependency_ids"] == [w["t2b"]["id"]]
    # origin_* provenance is written for the first time.
    assert created["origin_seat"] == "champion"
    assert created["origin_decision_id"] == approval["decision"]["id"]

    # The forecast span and the allocation records fold in.
    standing = T.derive_temporal_standing(ALICE)
    spans = standing["projects"][w["tier2"]["id"]]["spans"]
    assert any(
        s["standing"] == "derived forecast" and s["role"] == "window"
        for s in spans
    )
    weeks = standing["allocations"][w["person"]["id"]]["weeks"]
    total = sum(b["established_hours"] for b in weeks.values())
    assert total == pytest.approx(30.0)  # 10 + 15 recorded + 5 proposed
    # The outcome decision is recorded.
    outcomes_decisions = [
        d
        for d in S.list_decisions(ALICE)
        if d["decision_type"] == TD.ESTABLISHMENT_OUTCOME
    ]
    assert len(outcomes_decisions) == 1
    assert outcomes_decisions[0]["final_values_snapshot"]["status"] == (
        "established"
    )


# ---------------------------------------------------------------------------
# stale-record battery — each aborts, enumerating the offender
# ---------------------------------------------------------------------------


def _assert_aborted(report: dict, *, failure_class: str, field: str | None):
    assert report["status"] == "aborted", report
    matches = [
        o
        for o in report["offenders"]
        if o["failure_class"] == failure_class
        and (field is None or o.get("field") == field)
    ]
    assert matches, report["offenders"]


def test_stale_capacity_drift_aborts(ve_conn):
    w = _world()
    proposal = _approved(w)
    S.upsert_capacity_profile(
        M.CapacityProfileUpsert(
            person_id=w["person"]["id"], weekly_capacity_hours=6
        ),
        ALICE,
    )
    report = TD.establish_diagnosis_proposal(ALICE, proposal["id"])
    _assert_aborted(report, failure_class="stale_record", field="weekly_capacity_hours")
    assert report["offenders"][0]["from"] == 10.0
    assert report["offenders"][0]["to"] == 6.0
    # Nothing was established.
    assert T.derive_temporal_standing(ALICE)["allocations"] == {}


def test_stale_protected_time_added_aborts(ve_conn):
    w = _world()
    proposal = _approved(w)
    # Protected time in this slice rides the decision-recorded
    # window machinery: a hold recorded after the basis freezes.
    T.record_span(
        ALICE,
        w["tier1"]["id"],
        {
            "start": "2026-11-09",
            "end": "2026-11-13",
            "origin": "visitor-recorded",
            "standing": "established commitment",
            "role": "hold",
            "effort": {"kind": "exact", "hours": 10.0},
            "basis": ["founder-declared protected week"],
            "method": "visitor declaration",
        },
    )
    report = TD.establish_diagnosis_proposal(ALICE, proposal["id"])
    _assert_aborted(report, failure_class="standing_drift", field="standing")


def test_stale_firm_deadline_tightened_aborts(ve_conn):
    w = _world()
    # A recorded due date on the prerequisite: in this slice a VE
    # task's timeframe set is {None, tentative} — firmness arrives
    # via decision-recorded deadlines — but a recorded date is in
    # the basis vector either way, and tightening it must abort.
    S.update_task(
        w["t1"]["id"], M.TaskUpdate(due_date="2026-12-18"), ALICE
    )
    proposal = _approved(w)
    S.update_task(w["t1"]["id"], M.TaskUpdate(due_date="2026-11-20"), ALICE)
    report = TD.establish_diagnosis_proposal(ALICE, proposal["id"])
    _assert_aborted(report, failure_class="stale_record", field="due_date")
    match = [
        o for o in report["offenders"] if o.get("field") == "due_date"
    ][0]
    assert match["from"] == "2026-12-18"
    assert match["to"] == "2026-11-20"


def test_stale_dependency_added_aborts(ve_conn):
    w = _world()
    extra = ve_service.create_task(
        M.TaskCreate(
            title="Tier 1 side quest",
            project_id=w["tier1"]["id"],
            estimated_hours=4,
            completion_criteria="done",
        ),
        ALICE,
    )
    proposal = _approved(w)
    S.update_task(
        w["t1"]["id"], M.TaskUpdate(dependency_ids=[extra["id"]]), ALICE
    )
    report = TD.establish_diagnosis_proposal(ALICE, proposal["id"])
    _assert_aborted(report, failure_class="stale_record", field="dependency_ids")


def test_stale_estimate_changed_aborts(ve_conn):
    w = _world()
    proposal = _approved(w)
    S.update_task(w["t1"]["id"], M.TaskUpdate(estimated_hours=30), ALICE)
    report = TD.establish_diagnosis_proposal(ALICE, proposal["id"])
    _assert_aborted(report, failure_class="stale_record", field="estimated_hours")


def test_stale_item_deleted_aborts(ve_conn):
    w = _world()
    proposal = _approved(w)
    assert S.delete_task(w["t1"]["id"], ALICE)
    report = TD.establish_diagnosis_proposal(ALICE, proposal["id"])
    _assert_aborted(report, failure_class="deleted", field=None)
    match = [
        o for o in report["offenders"] if o["failure_class"] == "deleted"
    ][0]
    assert match["entity_id"] == w["t1"]["id"]


def test_stale_kernel_version_changed_aborts(ve_conn, monkeypatch):
    w = _world()
    proposal = _approved(w)
    monkeypatch.setattr(K, "KERNEL_VERSION", "9.9.9")
    report = TD.establish_diagnosis_proposal(ALICE, proposal["id"])
    _assert_aborted(report, failure_class="kernel_version_changed", field="kernel_version")
    # The proposal stays approved — the freeze stands, nothing wrote.
    assert (
        TD.get_diagnosis_proposal(ALICE, proposal["id"])["state"] == "approved"
    )


# ---------------------------------------------------------------------------
# concurrent establishment
# ---------------------------------------------------------------------------


def test_concurrent_establishment_second_fails_optimistic_check(ve_conn):
    w = _world()
    # A second Draft undertaking on the same person's pool, with
    # its own diagnosis approved against the SAME basis snapshot
    # (no allocations recorded yet).
    tier2b = ve_service.create_project(
        M.ProjectCreate(
            title="Tier 2 — Second front",
            status="Draft",
            owner_id=w["person"]["id"],
        ),
        ALICE,
    )
    ve_service.create_task(
        M.TaskCreate(
            title="Second front build",
            project_id=tier2b["id"],
            estimated_hours=20,
            completion_criteria="built",
        ),
        ALICE,
    )
    first = _approved(w)
    other = TD.assemble_diagnosis(ALICE, tier2b["id"])
    other = TD.compute_diagnosis_arrangement(
        ALICE, other["id"], start_week=ANCHOR
    )
    TD.approve_diagnosis_proposal(ALICE, other["id"])

    report_a = TD.establish_diagnosis_proposal(ALICE, first["id"])
    assert report_a["status"] == "established", report_a
    # The second establishment's basis no longer matches the
    # person-week buckets the first one wrote into.
    report_b = TD.establish_diagnosis_proposal(ALICE, other["id"])
    assert report_b["status"] == "aborted", report_b
    classes = {o["failure_class"] for o in report_b["offenders"]}
    assert "concurrent_change" in classes, report_b["offenders"]
    buckets = [
        o
        for o in report_b["offenders"]
        if o["failure_class"] == "concurrent_change"
    ]
    assert all(o["entity_type"] == "allocation_bucket" for o in buckets)


# ---------------------------------------------------------------------------
# failed establishment — per-element outcomes, proposal revisable
# ---------------------------------------------------------------------------


def test_failed_establishment_per_element_outcomes(ve_conn):
    w = _world()
    # A task in a Parked project: canonical (so approval treats the
    # dependency as satisfied) but outside the arranged world, so
    # it is NOT in the basis vector — deleting it is caught at
    # element validation time, not by the basis check.
    parked = ve_service.create_project(
        M.ProjectCreate(
            title="Parked — Later", status="Parked", owner_id=w["person"]["id"]
        ),
        ALICE,
    )
    external = ve_service.create_task(
        M.TaskCreate(
            title="External prerequisite",
            project_id=parked["id"],
            estimated_hours=3,
            completion_criteria="done",
        ),
        ALICE,
    )
    proposal = TD.assemble_diagnosis(ALICE, w["tier2"]["id"])
    proposal = TD.edit_diagnosis_proposal(
        ALICE,
        proposal["id"],
        {
            "add_tasks": [
                {
                    "id": "task:prop:dependent",
                    "title": "Work depending on the external prerequisite",
                    "effort": {"kind": "exact", "hours": 4.0},
                    "dependencies": [external["id"]],
                }
            ]
        },
    )
    proposal = TD.compute_diagnosis_arrangement(
        ALICE, proposal["id"], start_week=ANCHOR
    )
    TD.approve_diagnosis_proposal(ALICE, proposal["id"])
    assert S.delete_task(external["id"], ALICE)

    report = TD.establish_diagnosis_proposal(ALICE, proposal["id"])
    assert report["status"] == "partially_established", report
    outcomes = {e["element_id"]: e for e in report["elements"]}
    failed = outcomes["task:prop:dependent"]
    assert failed["status"] == "failed"
    assert failed["failure_class"] == "validation_failed"
    assert failed["created_task_id"] is None
    # The recorded elements established honestly alongside it.
    assert outcomes[f"task:{w['t2a']['id']}"]["status"] == "already_canonical"
    # No task was created for the failed element, and the
    # arrangement-level records (span, allocations) were not
    # written for a schedule that did not fully establish.
    tier2_tasks = S.list_tasks(ALICE, project_id=w["tier2"]["id"])
    assert {t["title"] for t in tier2_tasks} == {
        "Design the trials",
        "Run the trials",
    }
    standing = T.derive_temporal_standing(ALICE)
    assert standing["allocations"] == {}
    assert w["tier2"]["id"] not in standing["projects"]
    # The proposal is left revisable: a correction produces a new
    # version rather than a dead end.
    revised = TD.edit_diagnosis_proposal(
        ALICE,
        proposal["id"],
        {"remove_tasks": ["task:prop:dependent"]},
    )
    assert revised["state"] == "pending"
    assert revised["version"] == proposal["version"] + 1


# ---------------------------------------------------------------------------
# partial approval — dependency closure
# ---------------------------------------------------------------------------


def test_partial_approval_external_gate_refused(ve_conn):
    w = _world()
    proposal = TD.assemble_diagnosis(ALICE, w["tier2"]["id"])
    proposal = TD.edit_diagnosis_proposal(
        ALICE,
        proposal["id"],
        {
            "add_tasks": [
                {
                    "id": "task:prop:recon",
                    "title": "Reconnaissance pass",
                    "effort": {"kind": "exact", "hours": 6.0},
                }
            ],
            "tasks": {
                f"task:{w['t2b']['id']}": {
                    "dependencies": [w["t2a"]["id"], "task:prop:recon"]
                }
            },
        },
    )
    proposal = TD.compute_diagnosis_arrangement(
        ALICE, proposal["id"], start_week=ANCHOR
    )
    subset = [
        n["id"] for n in proposal["diagnosis"]["tasks"]
        if n["id"] != "task:prop:recon"
    ]
    approval = TD.approve_diagnosis_proposal(
        ALICE, proposal["id"], subset=subset
    )
    gates = approval["external_gates"]
    assert len(gates) == 1
    assert gates[0]["node_id"] == f"task:{w['t2b']['id']}"
    assert gates[0]["gated_by_node_id"] == "task:prop:recon"

    report = TD.establish_diagnosis_proposal(ALICE, proposal["id"])
    outcomes = {e["element_id"]: e for e in report["elements"]}
    gated = outcomes[f"task:{w['t2b']['id']}"]
    assert gated["status"] == "refused"
    assert gated["failure_class"] == "external_gate"
    # The unapproved prerequisite was never created, and the gated
    # element's canonical record was not touched.
    assert S.get_task(w["t2b"]["id"], ALICE)["dependency_ids"] == [
        w["t2a"]["id"]
    ]
    assert report["status"] == "partially_established"


def test_diagnosis_initiative_gap_inventory(ve_conn):
    """Where the project hangs under an initiative, the
    completeness machinery's gaps join the diagnosis: blank
    initiative fields become structured unresolved questions and
    the completeness block rides as seat-facing text."""
    w = _world()
    initiative = ve_service.create_initiative(
        M.InitiativeCreate(title="Build directions", status="Active"),
        ALICE,
    )
    S.update_project(
        w["tier2"]["id"],
        M.ProjectUpdate(initiative_id=initiative["id"]),
        ALICE,
    )
    proposal = TD.assemble_diagnosis(ALICE, w["tier2"]["id"])
    diagnosis = proposal["diagnosis"]
    qids = {q["id"] for q in diagnosis["unresolved_questions"]}
    assert "q:initiative:brief" in qids
    assert "q:initiative:risks" in qids
    assert "gap_inventory_text" in diagnosis
    assert "Build directions" in diagnosis["gap_inventory_text"]


# ---------------------------------------------------------------------------
# seat carriage — Valen's prepared context carries the figures
# ---------------------------------------------------------------------------


def test_seat_carriage_carries_diagnosis_and_arrangement(
    ve_conn, tmp_path: Path
):
    w = _world()
    proposal = TD.assemble_diagnosis(ALICE, w["tier2"]["id"])
    TD.compute_diagnosis_arrangement(ALICE, proposal["id"], start_week=ANCHOR)
    store = ConversationStore(db_path=tmp_path / "conv.db")
    try:
        block = CP.build_context_preparation(
            ALICE,
            {
                "sheet_type": "bench",
                "entity_type": "project",
                "entity_id": w["tier2"]["id"],
            },
            conversation_store=store,
        )
    finally:
        store.close()
    assert block is not None
    assert "Temporal diagnosis (v1, pending)" in block
    assert "Arrangement (kernel, earliest found" in block
    assert "Sustainable verdict:" in block
    assert f"kernel {K.KERNEL_VERSION}" in block
