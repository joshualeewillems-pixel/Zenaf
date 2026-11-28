"""New-undertaking authoring + seat recompute (Temporal Orchestration S5).

Pins the S5 share of brief §9 against a small fixture world (one
person, 10 h/week recorded capacity; one Active project with work;
one Draft project carrying only a provisional span):

  - authoring: a storefront diagnosis is authored from the
    undertaking template — category structure, every node typed,
    the platform unknown gating the content, fulfillment, and
    platform-build tracks behind its discovery task;
  - the generic fallback template serves unknown kinds;
  - a known fact resolves its unknown at authoring;
  - incomplete diagnosis: the kernel over the authored diagnosis
    reports finish unknown, the gating unknown's tasks named
    unresolved, the known subgraph computed;
  - correction: resolving the unknowns and adding a concrete
    platform task (a new proposal version) yields a bounded finish;
  - establishment: the approved storefront diagnosis creates its
    project + tasks through the canonical paths with origin_*
    written, and nothing else in the world changes;
  - seat recompute: effort and capacity deltas change the stamped
    output; the provisional-layer toggle changes which work is
    counted without the provisional spans reserving capacity in
    either mode; recompute persists nothing;
  - context preparation names the recompute capability for a
    diagnosed project and the seat-facing invocation runs through
    it; an undiagnosed project gets neither;
  - no model calls: the new module's imports are pinned clean.

Conventions mirror test_temporal_diagnosis: ALICE = "u1" (owner).
All kernel dates are pinned via start_week 2026-11-02 (a Monday).
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
from local_ai.vision_execution import temporal_scenario as TS
from local_ai.vision_execution import temporal_standing as T

ALICE = "u1"
ANCHOR = "2026-11-02"  # a Monday

PLATFORM_DISCOVERY = "task:prop:unknown:platform"
GATED_BY_PLATFORM = [
    "task:prop:platform:stand-up",
    "task:prop:offer-content:offer-copy",
    "task:prop:offer-content:media",
    "task:prop:fulfillment:shipping-setup",
]


@pytest.fixture()
def ve_conn(monkeypatch: pytest.MonkeyPatch):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    S.init_db(conn)
    monkeypatch.setattr(S, "get_connection", lambda: conn)
    yield conn
    conn.close()


def _world(capacity: float = 10.0) -> dict:
    person = ve_service.create_person(M.PersonCreate(name="Sam Reyes"), ALICE)
    S.upsert_capacity_profile(
        M.CapacityProfileUpsert(
            person_id=person["id"], weekly_capacity_hours=capacity
        ),
        ALICE,
    )
    active = ve_service.create_project(
        M.ProjectCreate(
            title="Existing build",
            status="Active",
            owner_id=person["id"],
            estimated_weekly_hours=5,
        ),
        ALICE,
    )
    a1 = ve_service.create_task(
        M.TaskCreate(
            title="Existing core work",
            project_id=active["id"],
            estimated_hours=20,
            completion_criteria="core work merged",
        ),
        ALICE,
    )
    bet = ve_service.create_project(
        M.ProjectCreate(
            title="Provisional bet",
            status="Draft",
            owner_id=person["id"],
        ),
        ALICE,
    )
    bet_task = ve_service.create_task(
        M.TaskCreate(
            title="Bet exploration",
            project_id=bet["id"],
            estimated_hours=30,
            completion_criteria="bet evaluated",
        ),
        ALICE,
    )
    T.record_span(
        ALICE,
        bet["id"],
        {
            "start": "2026-11-02",
            "end": "2026-11-29",
            "origin": "proposed",
            "standing": "provisional",
            "role": "window",
            "effort": {"kind": "exact", "hours": 30.0},
            "basis": ["a first-cut sizing, not yet examined"],
            "method": "provisional hypothesis",
            "note": "provisional — reserves nothing",
        },
    )
    return {
        "person": person,
        "active": active,
        "a1": a1,
        "bet": bet,
        "bet_task": bet_task,
    }


def _counts(conn) -> dict[str, int]:
    out = {}
    for table in ("decisions", "diagnosis_proposals", "projects", "tasks"):
        try:
            out[table] = conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
        except sqlite3.OperationalError:
            out[table] = 0  # the proposals table is created lazily
    return out


def _author_storefront(world: dict, **over) -> dict:
    kw = {
        "title": "Passive income storefront",
        "goal_text": "Sell the printables line through my own storefront.",
        "undertaking_kind": "storefront",
        "known_facts": {"person_id": world["person"]["id"]},
    }
    kw.update(over)
    return TS.propose_new_diagnosis(ALICE, **kw)


# ---------------------------------------------------------------------------
# authoring — the storefront scenario structure
# ---------------------------------------------------------------------------


def test_authoring_storefront_structure(ve_conn):
    w = _world()
    proposal = _author_storefront(w)
    diagnosis = proposal["diagnosis"]

    # The undertaking does not exist yet — the proposal is keyed by
    # a prospective project id and no project was created.
    assert proposal["project_id"] == diagnosis["project_id"]
    assert S.get_project(proposal["project_id"], ALICE) is None
    assert diagnosis["prospective_project"]["title"] == (
        "Passive income storefront"
    )
    assert diagnosis["person_id"] == w["person"]["id"]
    assert proposal["state"] == "pending"

    # Category structure inferred from the undertaking type.
    titles = {r["title"] for r in diagnosis["requirements"]}
    assert {
        "Entity & tax",
        "Platform",
        "Payments",
        "Offer & content",
        "Fulfillment",
        "Compliance",
    } <= titles
    for r in diagnosis["requirements"]:
        assert r["acceptance_criteria"], r["id"]
        assert r["origin"] in ("derived", "proposed", "visitor-recorded")

    # Every task node is typed.
    for node in diagnosis["tasks"]:
        assert node["origin"] in ("derived", "proposed", "visitor-recorded")
        assert node["effort"]["kind"] in (
            "exact",
            "interval",
            "lower-bound",
            "upper-bound",
            "unknown",
        )
        assert node["confidence_label"]

    # The platform unknown is a named, gating node: a question, a
    # requirement, and a discovery task — and the gated tracks are
    # effort-unknown and bound to the discovery task.
    questions = {q["id"]: q for q in diagnosis["unresolved_questions"]}
    assert "q:unknown:platform" in questions
    assert set(questions["q:unknown:platform"]["gates"]) == set(GATED_BY_PLATFORM)
    nodes = {n["id"]: n for n in diagnosis["tasks"]}
    assert PLATFORM_DISCOVERY in nodes
    for node_id in GATED_BY_PLATFORM:
        assert nodes[node_id]["effort"] == {"kind": "unknown"}
        assert PLATFORM_DISCOVERY in nodes[node_id]["dependencies"]
    unknown_reqs = {
        r["id"]: r for r in diagnosis["requirements"] if r.get("unknown")
    }
    assert "req:prop:unknown:platform" in unknown_reqs
    assert set(unknown_reqs["req:prop:unknown:platform"]["gates"]) == set(
        GATED_BY_PLATFORM
    )
    # Ungated work keeps its template estimates.
    assert nodes["task:prop:payments:processor-setup"]["effort"]["kind"] == (
        "interval"
    )
    assert nodes["task:prop:entity-tax:confirm-entity"]["effort"] == {
        "kind": "exact",
        "hours": 2.0,
    }


def test_authoring_generic_fallback(ve_conn):
    w = _world()
    proposal = TS.propose_new_diagnosis(
        ALICE,
        title="Something entirely new",
        goal_text="Figure it out as we go.",
        undertaking_kind="underwater basket weaving",
        known_facts={"person_id": w["person"]["id"]},
    )
    diagnosis = proposal["diagnosis"]
    assert diagnosis["undertaking_kind"] == "generic"
    titles = {r["title"] for r in diagnosis["requirements"]}
    assert {"Outcome", "Scope", "Resources", "Prerequisites", "Risks"} <= titles
    question_ids = {q["id"] for q in diagnosis["unresolved_questions"]}
    assert "q:unknown:approach" in question_ids


def test_authoring_known_fact_resolves_unknown(ve_conn):
    w = _world()
    proposal = _author_storefront(
        w,
        known_facts={
            "person_id": w["person"]["id"],
            "platform": "Shopify",
        },
    )
    diagnosis = proposal["diagnosis"]
    question_ids = {q["id"] for q in diagnosis["unresolved_questions"]}
    assert "q:unknown:platform" not in question_ids
    nodes = {n["id"]: n for n in diagnosis["tasks"]}
    # Gated work keeps its template estimates once the platform is
    # a recorded fact; the discovery node becomes a record/setup
    # task the build still follows.
    assert nodes["task:prop:platform:stand-up"]["effort"] == {
        "kind": "interval",
        "low_hours": 4.0,
        "high_hours": 10.0,
    }
    assert nodes[PLATFORM_DISCOVERY]["origin"] == "visitor-recorded"
    req = next(
        r for r in diagnosis["requirements"] if r["id"] == "req:prop:unknown:platform"
    )
    assert req["resolved_by_fact"] == "Shopify"


# ---------------------------------------------------------------------------
# incomplete diagnosis → correction (brief §9)
# ---------------------------------------------------------------------------


def test_incomplete_diagnosis_finish_unknown(ve_conn):
    w = _world()
    proposal = _author_storefront(w)
    proposal = TD.compute_diagnosis_arrangement(
        ALICE, proposal["id"], start_week=ANCHOR
    )
    target = proposal["arrangement"]["target"]
    earliest = target["earliest_found"]
    assert earliest["complete"] is False
    assert earliest["elapsed_weeks"] is None
    # The gated tracks are named unresolved; the known subgraph
    # (entity, payments, the discovery tasks…) still computes.
    for node_id in GATED_BY_PLATFORM:
        assert node_id in earliest["unresolved_task_ids"]
    assert earliest["known_subgraph_elapsed_weeks"] is not None
    # And the diagnosis itself names the gate.
    questions = {q["id"]: q for q in proposal["diagnosis"]["unresolved_questions"]}
    assert set(questions["q:unknown:platform"]["gates"]) == set(GATED_BY_PLATFORM)


def test_correction_resolves_unknowns_to_bounded_finish(ve_conn):
    w = _world()
    proposal = _author_storefront(w)
    edited = TD.edit_diagnosis_proposal(
        ALICE,
        proposal["id"],
        {
            "questions_resolved": [
                "q:unknown:platform",
                "q:unknown:fulfillment-model",
            ],
            "tasks": {
                "task:prop:platform:stand-up": {
                    "effort": {"kind": "interval", "low_hours": 4, "high_hours": 10}
                },
                "task:prop:offer-content:offer-copy": {
                    "effort": {"kind": "interval", "low_hours": 5, "high_hours": 10}
                },
                "task:prop:offer-content:media": {
                    "effort": {"kind": "interval", "low_hours": 4, "high_hours": 8}
                },
                "task:prop:fulfillment:shipping-setup": {
                    "effort": {"kind": "interval", "low_hours": 3, "high_hours": 6}
                },
            },
            "add_tasks": [
                {
                    "id": "task:prop:platform:shopify-theme",
                    "title": "Build the storefront theme on the chosen platform",
                    "effort": {"kind": "exact", "hours": 6},
                    "dependencies": [PLATFORM_DISCOVERY],
                    "requirement_id": "req:prop:platform",
                    "completion_criteria": "Theme live in draft",
                }
            ],
        },
    )
    assert edited["version"] == proposal["version"] + 1
    assert edited["state"] == "pending"
    assert TD.get_diagnosis_proposal(ALICE, proposal["id"])["state"] == (
        "superseded"
    )
    assert edited["diagnosis"]["unresolved_questions"] == []

    edited = TD.compute_diagnosis_arrangement(
        ALICE, edited["id"], start_week=ANCHOR
    )
    target = edited["arrangement"]["target"]
    earliest = target["earliest_found"]
    assert earliest["complete"] is True
    assert earliest["elapsed_weeks"] is not None
    finish_range = target["finish_range_weeks"]
    assert finish_range is not None
    assert finish_range["low"] is not None
    assert finish_range["high"] is not None


# ---------------------------------------------------------------------------
# establishment — diagnosis becomes first-class record
# ---------------------------------------------------------------------------


def test_storefront_establishment_creates_project(ve_conn):
    w = _world()
    before = _counts(ve_conn)
    proposal = _author_storefront(
        w,
        known_facts={
            "person_id": w["person"]["id"],
            "platform": "Shopify",
            "fulfillment_model": "print-on-demand",
        },
    )
    project_id = proposal["project_id"]
    node_count = len(proposal["diagnosis"]["tasks"])
    proposal = TD.compute_diagnosis_arrangement(
        ALICE, proposal["id"], start_week=ANCHOR
    )
    approval = TD.approve_diagnosis_proposal(ALICE, proposal["id"])
    report = TD.establish_diagnosis_proposal(ALICE, proposal["id"])

    assert report["status"] == "established"
    assert report["prospective_project"] is True
    assert report["created_project_id"] == project_id

    project = S.get_project(project_id, ALICE)
    assert project is not None
    assert project["title"] == "Passive income storefront"
    assert project["owner_id"] == w["person"]["id"]
    assert project["status"] == "Draft"
    # Canonical dates were not written by establishment.
    assert project["start_date"] is None
    assert project["end_date"] is None

    tasks = S.list_tasks(ALICE, project_id=project_id)
    assert len(tasks) == node_count
    for element in report["elements"]:
        assert element["status"] == "established"
        created = S.get_task(element["created_task_id"], ALICE)
        assert created["origin_seat"] == "champion"
        assert created["origin_decision_id"] == approval["decision"]["id"]

    # The forecast span and the allocation records fold under the
    # new project / the person.
    fold = T.derive_temporal_standing(ALICE)
    spans = fold["projects"][project_id]["spans"]
    assert any(s["standing"] == "derived forecast" for s in spans)
    assert fold["allocations"][w["person"]["id"]]["weeks"]

    # Nothing else in the world changed: exactly one project and
    # its tasks were added; the existing work is untouched.
    after = _counts(ve_conn)
    assert after["projects"] == before["projects"] + 1
    assert after["tasks"] == before["tasks"] + node_count
    existing = S.get_task(w["a1"]["id"], ALICE)
    assert existing["estimated_hours"] == 20
    assert existing["origin_seat"] is None


# ---------------------------------------------------------------------------
# seat recompute (brief §7)
# ---------------------------------------------------------------------------


def _tier2_proposal(world: dict) -> dict:
    """An S4-shaped diagnosis over recorded work, as a recompute base."""
    tier2 = ve_service.create_project(
        M.ProjectCreate(
            title="Tier 2 — Validation trials",
            status="Draft",
            owner_id=world["person"]["id"],
        ),
        ALICE,
    )
    t2a = ve_service.create_task(
        M.TaskCreate(
            title="Design the trials",
            project_id=tier2["id"],
            estimated_hours=10,
            completion_criteria="trial plan recorded",
            dependency_ids=[world["a1"]["id"]],
        ),
        ALICE,
    )
    ve_service.create_task(
        M.TaskCreate(
            title="Run the trials",
            project_id=tier2["id"],
            estimated_hours=15,
            completion_criteria="trial results recorded",
            dependency_ids=[t2a["id"]],
        ),
        ALICE,
    )
    return TD.assemble_diagnosis(ALICE, tier2["id"])


def test_recompute_deltas_change_stamped_output(ve_conn):
    w = _world()
    proposal = _tier2_proposal(w)
    base = TS.recompute_arrangement(
        ALICE, base={"proposal_id": proposal["id"]}, start_week=ANCHOR
    )
    base_elapsed = base["target"]["earliest_found"]["elapsed_weeks"]
    assert base_elapsed is not None

    # Effort delta on a recorded task, addressed by its diagnosis
    # node id (the form the seat layer holds).
    nodes = {n["id"]: n for n in proposal["diagnosis"]["tasks"]}
    run_node = next(
        nid for nid, n in nodes.items() if n["title"] == "Run the trials"
    )
    heavier = TS.recompute_arrangement(
        ALICE,
        base={"proposal_id": proposal["id"]},
        deltas={"effort": {run_node: {"kind": "exact", "hours": 45}}},
        start_week=ANCHOR,
    )
    assert (
        heavier["target"]["earliest_found"]["elapsed_weeks"] > base_elapsed
    )
    # The applied echo names the id the world actually carries —
    # the canonical task behind the diagnosis node.
    assert heavier["deltas_applied"]["effort"] == [
        nodes[run_node]["ref_task_id"]
    ]

    roomier = TS.recompute_arrangement(
        ALICE,
        base={"proposal_id": proposal["id"]},
        deltas={"capacity_hours_per_week": 20},
        start_week=ANCHOR,
    )
    assert roomier["target"]["earliest_found"]["elapsed_weeks"] < base_elapsed
    assert roomier["deltas_applied"]["capacity_changed"] is True

    # Stamps: the fold consumed, the kernel version, the honesty
    # labels, and a scenario assumption set that tracks the deltas.
    assert base["fold_seq"] == T.current_fold_seq(ALICE)
    assert base["kernel_version"] == K.KERNEL_VERSION
    assert "Week grain" in base["grain_disclaimer"]
    assert base["assumption_set_id"] != heavier["assumption_set_id"]
    again = TS.recompute_arrangement(
        ALICE, base={"proposal_id": proposal["id"]}, start_week=ANCHOR
    )
    assert again["assumption_set_id"] == base["assumption_set_id"]
    assert again["target"] == base["target"]


def test_recompute_persists_nothing(ve_conn):
    w = _world()
    proposal = _tier2_proposal(w)
    before = _counts(ve_conn)
    fold_before = T.current_fold_seq(ALICE)
    TS.recompute_arrangement(
        ALICE,
        base={"proposal_id": proposal["id"]},
        deltas={
            "effort": {},
            "capacity_hours_per_week": 40,
            "add_allocations": {ANCHOR: 5},
        },
        toggles={"include_provisional_layer": True},
        start_week=ANCHOR,
    )
    assert _counts(ve_conn) == before
    assert T.current_fold_seq(ALICE) == fold_before


def test_recompute_provisional_toggle_never_reserves(ve_conn):
    w = _world()
    proposal = _tier2_proposal(w)
    allocations_before = T.derive_temporal_standing(ALICE)["allocations"]

    off = TS.recompute_arrangement(
        ALICE, base={"proposal_id": proposal["id"]}, start_week=ANCHOR
    )
    assert off["provisional_layer"]["included"] is False
    assert off["provisional_layer"]["task_count"] == 0

    on = TS.recompute_arrangement(
        ALICE,
        base={"proposal_id": proposal["id"]},
        toggles={"include_provisional_layer": True},
        start_week=ANCHOR,
    )
    assert on["provisional_layer"]["included"] is True
    assert on["provisional_layer"]["project_ids"] == [w["bet"]["id"]]
    assert on["provisional_layer"]["task_count"] == 1

    # The baseline never sees the scenario layer: identical with
    # the toggle on or off — the provisional work reserves nothing.
    base_off = off["arrangement"]["baseline"]
    base_on = on["arrangement"]["baseline"]
    assert base_on["project_finish"] == base_off["project_finish"]
    assert (
        base_on["residual_free_hours_by_week"]
        == base_off["residual_free_hours_by_week"]
    )
    # And the record itself is untouched by either exploration.
    assert T.derive_temporal_standing(ALICE)["allocations"] == allocations_before


def test_recompute_adhoc_base(ve_conn):
    w = _world()
    out = TS.recompute_arrangement(
        ALICE,
        base={
            "person_id": w["person"]["id"],
            "target_project_id": "scenario:adhoc",
            "tasks": [
                {"id": "task:prop:adhoc:a", "effort": {"kind": "exact", "hours": 10}},
                {
                    "id": "task:prop:adhoc:b",
                    "effort": {"kind": "exact", "hours": 10},
                    "dependencies": ["task:prop:adhoc:a"],
                },
            ],
        },
        start_week=ANCHOR,
    )
    assert out["base"]["kind"] == "adhoc_tasks"
    assert out["target"]["earliest_found"]["complete"] is True


# ---------------------------------------------------------------------------
# context preparation — the seat can invoke it
# ---------------------------------------------------------------------------


def test_context_preparation_names_and_invokes_recompute(
    ve_conn, tmp_path: Path
):
    w = _world()
    proposal = _tier2_proposal(w)
    TD.compute_diagnosis_arrangement(ALICE, proposal["id"], start_week=ANCHOR)
    store = ConversationStore(db_path=tmp_path / "conv.db")
    try:
        block = CP.build_context_preparation(
            ALICE,
            {
                "sheet_type": "bench",
                "entity_type": "project",
                "entity_id": proposal["project_id"],
            },
            conversation_store=store,
        )
    finally:
        store.close()
    assert block is not None
    assert "Hypothetical recalculation" in block

    out = CP.temporal_recompute(
        ALICE,
        proposal["project_id"],
        deltas={"capacity_hours_per_week": 20},
    )
    assert out is not None
    assert out["kind"] == "temporal_recompute"
    assert out["deltas_applied"]["capacity_changed"] is True

    # A project with no diagnosis: no capability, no crash.
    assert CP.temporal_recompute(ALICE, w["bet"]["id"]) is None


# ---------------------------------------------------------------------------
# no model calls in the new module (pinned by source scan)
# ---------------------------------------------------------------------------


def test_no_model_calls_in_scenario_module():
    source = Path(TS.__file__).read_text(encoding="utf-8")
    import_lines = [
        line.strip()
        for line in source.splitlines()
        if line.strip().startswith(("import ", "from "))
    ]
    forbidden = ("llm", "openai", "anthropic", "provider", "urllib", "requests")
    for line in import_lines:
        for token in forbidden:
            assert token not in line.lower(), line
