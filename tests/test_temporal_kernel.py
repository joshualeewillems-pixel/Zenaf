"""Temporal kernel (Temporal Orchestration slice S3) — tests.

The kernel is pure deterministic computation over plain data
assembled by the caller. These tests pin the brief §9 fixtures:

  - the §4 worked scenario (55h / 31h capacity / 26h committed /
    5h available -> 11.0 weeks, labeled simplified: one task, no
    dependencies, no waiting);
  - dependency cycle -> rejection naming the cycle;
  - unknown effort -> finish unknown + known subgraph + unresolved
    ids, and NO sustainable claim;
  - interval effort -> dual runs producing a finish range;
  - unavailable prerequisite -> blocked, the external gate named;
  - conflicting firm commitments -> earliest-found displaces
    non-firm work and reports it; sustainable returns none, naming
    the firm blocker;
  - shared-resource competition across projects on one pool;
  - priority tie-break (order follows priority; priority never
    violates a firm constraint);
  - a firm item with unknown effort -> sustainability unknown;
  - a day-grained hold -> week aggregation + the grain disclaimer
    on the output;
  - milestone / undertaking unlock typing;
  - honesty labels (kernel version, settings hash, fold and
    assumption stamps) ride every output.
"""

from __future__ import annotations

import json

from local_ai.vision_execution import temporal_kernel as K
from local_ai.vision_execution import temporal_standing as T


def _task(tid, project, effort, **kw):
    base = {"id": tid, "project_id": project, "effort": effort}
    base.update(kw)
    return base


def test_worked_scenario_fixture():
    """Brief §4: 55h effort, 31h capacity, 26h committed, 5h
    available -> 11.0 weeks. Labeled simplified: a single task, no
    dependencies, no waiting — the arithmetic kernel of every
    larger arrangement."""
    result = K.compute_arrangement(
        tasks=[_task("t1", "tgt", {"kind": "exact", "hours": 55})],
        capacity_hours_per_week=31,
        established_allocations=[{"weekly_hours": 26}],
        target_project_id="tgt",
    )
    assert result["status"] == "ok"
    target = result["target"]["earliest_found"]
    assert target["elapsed_weeks"] == 11.0
    assert target["complete"] is True
    assert result["sustainable"]["status"] == "sustainable"
    labels = result["labels"]
    assert labels["kernel_version"] == K.KERNEL_VERSION
    assert len(labels["algo_settings_hash"]) == 64
    assert "earliest found" in labels["claim"].lower()
    # Nothing anywhere in the output claims a proven earliest.
    assert "proven earliest" not in json.dumps(result).lower()


def test_dependency_cycle_rejected():
    result = K.compute_arrangement(
        tasks=[
            _task("a", "p", 5, dependencies=["b"]),
            _task("b", "p", 5, dependencies=["a"]),
        ],
        capacity_hours_per_week=10,
        target_project_id="p",
    )
    assert result["status"] == "rejected"
    assert result["rejection"]["reason"] == "dependency_cycle"
    cycle = result["rejection"]["cycle"]
    assert "a" in cycle and "b" in cycle


def test_unknown_effort_finish_unknown():
    result = K.compute_arrangement(
        tasks=[
            _task("x", "tgt", {"kind": "exact", "hours": 10}),
            _task("y", "tgt", {"kind": "unknown"}),
            _task("z", "tgt", {"kind": "exact", "hours": 5}, dependencies=["y"]),
        ],
        capacity_hours_per_week=10,
        target_project_id="tgt",
    )
    finish = result["earliest_found"]["project_finish"]["tgt"]
    assert finish["complete"] is False
    assert finish["elapsed_weeks"] is None
    # The known subgraph still completes and is reported as such.
    assert finish["known_subgraph_elapsed_weeks"] == 1.0
    assert set(finish["unresolved_task_ids"]) == {"y", "z"}
    reasons = {
        entry["task_id"]: entry["reason"]
        for entry in result["earliest_found"]["unresolved"]
    }
    assert reasons["y"] == "unknown_effort"
    assert reasons["z"] == "depends_on_unresolved"
    # No sustainable claim is made over an unknown.
    assert result["sustainable"]["status"] == "unknown"


def test_interval_effort_dual_run_range():
    result = K.compute_arrangement(
        tasks=[
            _task(
                "t1",
                "tgt",
                {"kind": "interval", "low_hours": 10, "high_hours": 20},
            )
        ],
        capacity_hours_per_week=10,
        target_project_id="tgt",
    )
    assert result["inputs_summary"]["dual_bound_runs"] is True
    assert set(result["runs"]) == {"low", "high"}
    assert result["target"]["finish_range_weeks"] == {"low": 1.0, "high": 2.0}


def test_unavailable_prerequisite_blocked():
    result = K.compute_arrangement(
        tasks=[_task("t1", "tgt", 5, dependencies=["ghost-task"])],
        capacity_hours_per_week=10,
        target_project_id="tgt",
    )
    blocked = result["earliest_found"]["blocked"]
    assert len(blocked) == 1
    assert blocked[0]["task_id"] == "t1"
    assert blocked[0]["missing_prerequisites"] == ["ghost-task"]
    finish = result["earliest_found"]["project_finish"]["tgt"]
    assert finish["complete"] is False
    assert finish["elapsed_weeks"] is None


def test_conflicting_firm_commitments():
    """A firm 20h task due week 1 consumes all capacity in weeks
    0-1. The target carries its own firm deadline at week 1, which
    cannot be met: earliest-found reports the firm violation and
    displaces the non-firm task; sustainable returns none, naming
    the firm blocker."""
    result = K.compute_arrangement(
        tasks=[
            _task(
                "firm-task",
                "existing",
                20,
                timeframe_commitment="firm",
                due_week=1,
            ),
            _task("loose-task", "existing", 10, priority="Low"),
            _task(
                "target-task",
                "tgt",
                10,
                timeframe_commitment="firm",
                due_week=1,
            ),
        ],
        capacity_hours_per_week=10,
        target_project_id="tgt",
    )
    earliest = result["earliest_found"]
    violations = {
        (v["task_id"], v["kind"]) for v in earliest["firm_violations"]
    }
    assert ("target-task", "task_deadline") in violations
    # The non-firm task is displaced by a week and the displacement
    # is reported per project.
    disp = result["displacement"]["per_project"]["existing"]
    assert disp["hours_shifted"] == 20.0
    assert disp["finish_slip_weeks"] == 1
    assert disp["tasks_affected"] == ["loose-task"]
    # Sustainable: the frozen baseline leaves no room before the
    # target's firm deadline.
    sustainable = result["sustainable"]
    assert sustainable["status"] == "no sustainable arrangement"
    assert any(
        b["constraint"] == "firm_deadline_met"
        for b in sustainable["blocking_constraints"]
    )


def test_shared_resource_competition():
    """Three projects, one 10h/week pool. Under target-advances the
    target finishes in week 0's boundary; both competing projects
    are displaced and the displacement is reported for each."""
    result = K.compute_arrangement(
        tasks=[
            _task("a", "p1", 20, priority="Medium"),
            _task("b", "p2", 20, priority="Medium"),
            _task("c", "tgt", 10),
        ],
        capacity_hours_per_week=10,
        target_project_id="tgt",
    )
    assert result["target"]["earliest_found"]["elapsed_weeks"] == 1.0
    baseline = result["baseline"]["project_finish"]
    assert baseline["p1"]["elapsed_weeks"] == 2.0
    assert baseline["p2"]["elapsed_weeks"] == 4.0
    per_project = result["displacement"]["per_project"]
    assert per_project["p1"]["hours_shifted"] == 20.0
    assert per_project["p2"]["hours_shifted"] == 20.0
    assert per_project["p1"]["finish_slip_weeks"] == 1
    assert per_project["p2"]["finish_slip_weeks"] == 1


def test_priority_tie_break_and_priority_never_violates():
    # Equal footing: the higher-priority task is served first.
    result = K.compute_arrangement(
        tasks=[
            _task("lo", "p", 10, priority="Low"),
            _task("hi", "p", 10, priority="High"),
        ],
        capacity_hours_per_week=10,
    )
    weeks = result["baseline"]["task_weeks"]
    assert weeks["hi"]["finish_week"] == 0
    assert weeks["lo"]["finish_week"] == 1

    # A firm low-priority task with a deadline beats a non-firm
    # critical task: priority never overrides a firm constraint.
    result = K.compute_arrangement(
        tasks=[
            _task("crit", "p", 10, priority="Critical"),
            _task(
                "firm-lo",
                "p",
                10,
                priority="Low",
                timeframe_commitment="firm",
                due_week=0,
            ),
        ],
        capacity_hours_per_week=10,
    )
    weeks = result["baseline"]["task_weeks"]
    assert weeks["firm-lo"]["finish_week"] == 0
    assert weeks["crit"]["finish_week"] == 1
    assert result["baseline"]["firm_violations"] == []


def test_firm_unknown_effort_sustainability_unknown():
    result = K.compute_arrangement(
        tasks=[
            _task(
                "firm-mystery",
                "existing",
                {"kind": "unknown"},
                timeframe_commitment="firm",
                due_week=3,
            ),
            _task("target-task", "tgt", 10),
        ],
        capacity_hours_per_week=10,
        target_project_id="tgt",
    )
    # The target itself is fully computable...
    assert result["target"]["earliest_found"]["complete"] is True
    # ...but sustainability cannot be certified over a firm unknown.
    sustainable = result["sustainable"]
    assert sustainable["status"] == "unknown"
    assert any(
        u["constraint"] == "firm_effort_known" for u in sustainable["unknowns"]
    )


def test_day_grained_hold_disclaimer():
    """A two-day, 10h hold at the start of week 0 (Mon 2026-11-02)
    aggregates to a full 10h reduction of week 0; the output
    carries the grain disclaimer and the aggregation record."""
    result = K.compute_arrangement(
        tasks=[_task("t1", "tgt", 10)],
        capacity_hours_per_week=10,
        windows=[
            {
                "kind": "hold",
                "start_date": "2026-11-02",
                "end_date": "2026-11-03",
                "hours": 10,
            }
        ],
        start_week="2026-11-02",
        target_project_id="tgt",
    )
    labels = result["labels"]
    assert labels["grain_disclaimer"] == K.GRAIN_DISCLAIMER
    aggregated = labels["aggregated_day_grain_holds"]
    assert len(aggregated) == 1
    assert aggregated[0]["week_hours"] == {"0": 10.0}
    # Week 0 is fully held, so the 10h task lands in week 1.
    assert result["target"]["earliest_found"]["elapsed_weeks"] == 2.0


def test_milestone_and_undertaking_unlocks():
    """Unlock typing: C waits for milestone M1 (both A and B);
    D waits for the whole p1 undertaking. B's dependency rides the
    VE ``dependency_ids`` shorthand; D's rides a bare project id,
    auto-resolved to an undertaking unlock."""
    result = K.compute_arrangement(
        tasks=[
            _task("a", "p1", 10),
            _task("b", "p1", 10, dependency_ids=["a"]),
            _task(
                "c",
                "p2",
                10,
                dependencies=[{"on": "m1", "unlock": "milestone"}],
            ),
            _task("d", "p2", 10, dependencies=["p1"]),
        ],
        milestones=[{"id": "m1", "members": ["a", "b"]}],
        capacity_hours_per_week=20,
    )
    weeks = result["baseline"]["task_weeks"]
    assert weeks["a"]["start_week"] == 0
    assert weeks["b"]["start_week"] == 1  # gated on A despite free capacity
    assert weeks["c"]["start_week"] == 2  # milestone completes at boundary 2
    assert weeks["d"]["start_week"] == 2  # undertaking completes at boundary 2
    assert weeks["c"]["finish_boundary"] == 3
    assert weeks["d"]["finish_boundary"] == 3


def test_scenario_layer_and_fold_series_allocations():
    """Scenario material never enters the baseline and reserves
    nothing; established allocations arrive in the fold's own
    person-week series shape (S1) and pre-consume week 0."""
    result = K.compute_arrangement(
        tasks=[_task("w", "world-proj", 10)],
        scenario_tasks=[
            _task("scenario:scn/s1", "scn", 10, dependencies=["w"])
        ],
        capacity_hours_per_week=10,
        established_allocations={
            "weeks": {"2026-11-02": {"established_hours": 5}}
        },
        start_week="2026-11-02",
        target_project_id="scn",
    )
    assert "scn" not in result["baseline"]["project_finish"]
    # Week 0 has only 5 free hours, so the world task spans weeks
    # 0-1 (boundary 2); the scenario task follows in week 2.
    assert result["baseline"]["project_finish"]["world-proj"]["elapsed_weeks"] == 2.0
    assert result["target"]["earliest_found"]["elapsed_weeks"] == 3.0


def test_labels_carry_fold_and_assumption_stamps():
    result = K.compute_arrangement(
        tasks=[_task("t1", "tgt", 5)],
        capacity_hours_per_week=10,
        target_project_id="tgt",
        fold_seq=42,
        assumption_ids=["alloc-holds", "no-new-commitments"],
    )
    labels = result["labels"]
    assert labels["fold_seq"] == 42
    assert labels["assumption_set_id"] == T.assumption_set_id(
        ["no-new-commitments", "alloc-holds"]
    )
    assert labels["algorithm"] == K.ALGORITHM
