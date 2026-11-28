"""Temporal kernel — deterministic scheduling and reconciliation.

Temporal Orchestration, slice step S3 (brief
``zenaf-temporal-orchestration-slice-brief-2026-11-28.md`` §4, §9).
This is the one genuinely new engine the capability audit found
absent: the computation that turns effort + dependencies + capacity
into temporal arrangements. It is **pure deterministic computation**:

- no model calls, no DB reads or writes, no clock, no randomness —
  the same input always produces the same output;
- inputs are plain data structures assembled by the caller from VE
  records and a fold snapshot (S1's ``derive_temporal_standing``);
- outputs are plain data structures carrying their honesty labels.

Founder rulings carried here:

- **Computational honesty** (Refinement 5): unknown effort does not
  permit a bounded range — the affected branch is unbounded and the
  arrangement reports finish *unknown* for it, with the known
  subgraph's completion and the unresolved node ids named. Recorded
  due dates constrain only at their recorded standing: a task is a
  firm constraint only when ``timeframe_commitment == "firm"`` (a due
  date is a record, not a promise). A firm item with unknown effort
  makes sustainability *unknown*, never a pass. Nothing is ever
  labeled a proven earliest — single-resource precedence scheduling
  admits no cheap optimality certificate, so every arrangement is an
  **earliest found under the stated settings**.
- **Provisional arrangements do not reserve capacity** (Refinement
  3): the baseline is built from established allocations, declared
  windows/holds, and protected time only. Scenario layers (the
  provisional / hypothetical material) enter only the earliest-found
  and sustainable passes, as a named unit, and reserve nothing.
- **Priority participates, never governs** (spec §C): priority orders
  ready work inside a pass; it never overrides a firm constraint or
  an immovable, and it is never the sole determinant — firm slack
  outranks it.

## Inputs

``compute_arrangement`` takes keyword arguments; all data is plain
dicts/lists as a caller would assemble them from VE rows:

- ``tasks``: the recorded world. Each task::

      {
        "id": str, "project_id": str,
        "effort": {"kind": "exact", "hours": n}
                | {"kind": "interval", "low_hours": n, "high_hours": n}
                | {"kind": "lower-bound", "hours": n}
                | {"kind": "upper-bound", "hours": n}
                | {"kind": "unknown"}
                | n            # shorthand: an exact recorded estimate
                | None,        # shorthand: no estimate recorded -> unknown
        "dependencies": ["<task id>",
                         {"on": "<id>", "unlock": "task" | "milestone"
                                                       | "undertaking"}],
        "dependency_ids": ["<task id>", ...],   # VE shorthand, merged in
        "timeframe_commitment": "firm" | "tentative" | None,
        "due_date": "YYYY-MM-DD" | None,   # needs the start_week anchor
        "due_week": int | None,            # week index; wins over due_date
        "priority": number | str | {dimension: number} | None,
        "release_week": int,               # default 0
        "release_date": "YYYY-MM-DD" | None,
        "status": str | None,              # Done/Complete -> pre-completed
        "established": bool,               # covered by established
                                           # allocations -> pre-completed
      }

  A plain string dependency auto-resolves: task id, then milestone
  id, then project id (an undertaking unlock), else an external gate.
  Pre-completed tasks are never scheduled and demand no capacity;
  they satisfy gates from week 0 (their hours already sit in the
  established allocation buckets).

- ``scenario_tasks``: one scenario layer, same task shape, with
  namespaced ids. The layer enters earliest-found / sustainable as a
  unit; the baseline never sees it.
- ``milestones``: ``[{"id": str, "members": [task id, ...]}]`` —
  materialized zero-duration nodes; a milestone completes when all
  its members complete. Members must resolve (a dangling member is a
  malformed input, ValueError — unlike a dangling *dependency*,
  which is an external gate, a scheduling outcome).
- ``capacity_hours_per_week``: the person's weekly capacity (> 0).
  ``capacity_overrides``: ``{week_index | ISO Monday: hours}`` for
  changing availability.
- ``established_allocations``: the immovable person-week buckets, in
  any of these forms: the fold's series for the person
  (``{"weeks": {"2026-11-02": {"established_hours": n}}}``), a list
  of ``{"week": int, "hours": n}`` / ``{"week_start": iso, "hours":
  n}`` / ``{"weekly_hours": n}``, or ``{"week_hours": {key: n}}``.
- ``windows``: declared windows. ``{"kind": "hold", ...}`` entries
  reduce capacity (same week/hour forms as allocations; a date-range
  hold ``{"start_date", "end_date", "hours"}`` is day-grained and is
  aggregated to week-hours by overlap days — with no ``hours`` it
  blocks the overlapped weeks fully). ``{"kind": "deadline",
  "project_id", "due_week" | "due_date"}`` entries are firm project
  deadlines. A window with no kind is a hold.
- ``protected_time``: capacity carve-outs, same reduction forms as
  holds (plus ``{"weekly_hours": n}``). Hard: never allocated into.
- ``start_week``: ISO date anchoring week 0 (normalized to its
  Monday). Any date-based input requires it.
- ``target_project_id``: the undertaking being arranged. May name a
  world project or a scenario-layer project. ``None`` computes the
  baseline only.
- ``target_advances``: the named earliest-pass assumption (default
  True): target tasks are served before non-firm work within the
  non-firm class. Firm constraints and immovables are never
  overridden by it.
- ``priority_dimensions``: dimension order when a task's priority is
  a dict (default: the dict's sorted keys).
- ``horizon_weeks``: scheduling horizon (default 104).
- ``fold_seq`` / ``assumption_set_id`` / ``assumption_ids``: stamps
  carried into the output labels (the set id is derived from the ids
  with S1's canonical hash when only ids are given).

## Outputs

A dict with ``status`` ("ok" | "rejected"), ``labels`` (algorithm,
``kernel_version``, ``algo_settings_hash``, fold/assumption stamps,
the claim and the grain disclaimer), per-bound ``runs`` and — mirrored
from the lower-bound run — ``baseline``, ``earliest_found``,
``sustainable``, ``displacement``, and a ``target`` summary. Efforts
that are not all exact trigger dual runs (lower-bound and upper-bound
efforts); the target summary then carries ``finish_range_weeks``
whose high end is None when no defensible upper bound exists.

Each pass reports per-task weeks (``start_week``, ``finish_week``,
``finish_boundary``, ``hours_by_week``), per-project finishes,
residual free capacity, unresolved task ids with reasons, blocked
tasks with their missing prerequisites named, and firm violations.
Weeks are indices from 0; ``elapsed_weeks`` counts from boundary 0 to
the project's finish boundary. ``sustainable`` is a verdict against a
named constraint set printed with it — capacity ceiling every week,
protected time intact, established commitments unmoved, firm
deadlines met — with status "sustainable" | "no sustainable
arrangement" | "unknown" and the blocking constraints listed.

``KERNEL_VERSION`` is a real constant: the establishment path (S4)
pins it in basis tuples, and a version change is one of the
stale-record abort conditions.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, timedelta
from typing import Any

from local_ai.vision_execution.temporal_standing import (
    assumption_set_id as _assumption_set_id,
)

KERNEL_VERSION = "1.0.0"

ALGORITHM = "weekly-list-schedule"

GRAIN_DISCLAIMER = (
    "Week grain: holds and windows are aggregated to week-hours; "
    "intra-week feasibility is unknown."
)

CLAIM = (
    "Earliest found under the stated settings; optimality is not "
    "certified and no proven-earliest claim is made."
)

_EPS = 1e-9

_DONE_STATUSES = frozenset({"done", "complete", "completed"})

_PRIORITY_WORDS = {
    "critical": 4.0,
    "urgent": 4.0,
    "high": 3.0,
    "medium": 2.0,
    "normal": 2.0,
    "low": 1.0,
}


# ---------------------------------------------------------------------------
# Effort representation (brief §2 shapes; the label follows from these)
# ---------------------------------------------------------------------------


def effort_from_hours(hours: float | None) -> dict[str, Any]:
    """The §2 effort representation for a VE ``estimated_hours``
    value: a recorded estimate is exact; no estimate is unknown."""
    if hours is None:
        return {"kind": "unknown"}
    return {"kind": "exact", "hours": float(hours)}


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _normalize_effort(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {"kind": "unknown"}
    if _is_number(raw):
        if raw < 0:
            raise ValueError("effort hours must be >= 0")
        return {"kind": "exact", "hours": float(raw)}
    if not isinstance(raw, dict):
        raise ValueError(f"effort must be a §2 mapping, a number, or None: {raw!r}")
    kind = raw.get("kind")
    if kind == "unknown":
        return {"kind": "unknown"}
    if kind == "interval":
        low, high = raw.get("low_hours"), raw.get("high_hours")
        if not (_is_number(low) and _is_number(high)) or low < 0 or high < low:
            raise ValueError(f"interval effort needs 0 <= low <= high: {raw!r}")
        return {"kind": "interval", "low_hours": float(low), "high_hours": float(high)}
    if kind in ("exact", "lower-bound", "upper-bound"):
        hours = raw.get("hours")
        if not _is_number(hours) or hours < 0:
            raise ValueError(f"{kind} effort needs hours >= 0: {raw!r}")
        return {"kind": kind, "hours": float(hours)}
    raise ValueError(f"unknown effort kind: {kind!r}")


def _effort_bound(effort: dict[str, Any], bound: str) -> float | None:
    """The effort value under one bound run, or None when the task
    has no defensible value at that bound (unknown effort at either
    bound; a lower-bound-only effort at the upper bound)."""
    kind = effort["kind"]
    if kind == "unknown":
        return None
    if kind == "exact":
        return effort["hours"]
    if kind == "interval":
        return effort["low_hours"] if bound == "low" else effort["high_hours"]
    if kind == "lower-bound":
        return effort["hours"] if bound == "low" else None
    # upper-bound: at most `hours`, at least nothing.
    return 0.0 if bound == "low" else effort["hours"]


def _all_exact(tasks: list[dict[str, Any]]) -> bool:
    return all(t["effort"]["kind"] == "exact" for t in tasks)


# ---------------------------------------------------------------------------
# Dates and week indices
# ---------------------------------------------------------------------------


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _parse_date(raw: Any, what: str) -> date:
    if not isinstance(raw, str):
        raise ValueError(f"{what} must be an ISO date string: {raw!r}")
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        raise ValueError(f"{what} is not an ISO date: {raw!r}") from None


class _Anchor:
    """Week-index <-> date conversion. Date-based inputs require an
    anchor; index-based inputs never do."""

    def __init__(self, start_week: Any):
        self.monday: date | None = None
        if start_week is not None:
            self.monday = _monday_of(_parse_date(start_week, "start_week"))

    def require(self, what: str) -> date:
        if self.monday is None:
            raise ValueError(f"{what} is date-based and requires the start_week anchor")
        return self.monday

    def week_of(self, raw: Any, what: str) -> int:
        anchor = self.require(what)
        d = _monday_of(_parse_date(raw, what))
        return (d - anchor).days // 7

    def week_containing(self, raw: Any, what: str) -> int:
        anchor = self.require(what)
        d = _parse_date(raw, what)
        return (d - anchor).days // 7


# ---------------------------------------------------------------------------
# Week-hour reductions (allocations, holds, protected time)
# ---------------------------------------------------------------------------


def _accumulate_reduction(
    out: dict[int, float],
    day_grain: list[dict[str, Any]],
    entry: dict[str, Any],
    anchor: _Anchor,
    capacity: float,
    horizon: int,
    source: str,
) -> None:
    """Fold one reduction entry into ``out`` (week index -> hours).
    Accepts the forms documented in the module docstring."""
    if not isinstance(entry, dict):
        raise ValueError(f"{source} entries must be mappings: {entry!r}")
    if "week_hours" in entry:
        mapping = entry["week_hours"]
        if not isinstance(mapping, dict):
            raise ValueError(f"{source} week_hours must be a mapping: {entry!r}")
        for key, hours in mapping.items():
            if not _is_number(hours) or hours < 0:
                raise ValueError(f"{source} hours must be >= 0: {entry!r}")
            if isinstance(key, int) and not isinstance(key, bool):
                week = key
            elif isinstance(key, str) and key.lstrip("-").isdigit():
                week = int(key)
            else:
                week = anchor.week_of(key, f"{source} week_hours key")
            if 0 <= week < horizon:
                out[week] = out.get(week, 0.0) + float(hours)
        return
    if "weekly_hours" in entry:
        hours = entry["weekly_hours"]
        if not _is_number(hours) or hours < 0:
            raise ValueError(f"{source} weekly_hours must be >= 0: {entry!r}")
        for week in range(horizon):
            out[week] = out.get(week, 0.0) + float(hours)
        return
    if "start_date" in entry or "end_date" in entry:
        # Day-grained: aggregate to week-hours by overlap days.
        anchor.require(f"{source} date range")
        start = _parse_date(entry.get("start_date"), f"{source} start_date")
        end = _parse_date(entry.get("end_date"), f"{source} end_date")
        if end < start:
            raise ValueError(f"{source} end_date precedes start_date: {entry!r}")
        total_days = (end - start).days + 1
        hours = entry.get("hours")
        full = hours is None
        if not full and (not _is_number(hours) or hours < 0):
            raise ValueError(f"{source} hours must be >= 0: {entry!r}")
        per_week: dict[int, float] = {}
        cursor = start
        while cursor <= end:
            monday = _monday_of(cursor)
            week = (monday - anchor.monday).days // 7  # type: ignore[operator]
            week_end = monday + timedelta(days=6)
            overlap = (min(week_end, end) - max(monday, start)).days + 1
            if full:
                per_week[week] = capacity * overlap / 7.0
            else:
                per_week[week] = float(hours) * overlap / total_days
            cursor = week_end + timedelta(days=1)
        for week, hrs in per_week.items():
            if 0 <= week < horizon:
                out[week] = out.get(week, 0.0) + hrs
        day_grain.append(
            {
                "source": source,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "hours": None if full else float(hours),
                "full_block": full,
                "week_hours": {str(w): round(h, 4) for w, h in sorted(per_week.items())},
            }
        )
        return
    hours = entry.get("hours")
    if not _is_number(hours) or hours < 0:
        raise ValueError(f"{source} entry needs hours >= 0: {entry!r}")
    if "week" in entry:
        week = entry["week"]
        if not isinstance(week, int) or isinstance(week, bool):
            raise ValueError(f"{source} week must be an int: {entry!r}")
    elif "week_start" in entry:
        week = anchor.week_of(entry["week_start"], f"{source} week_start")
    else:
        raise ValueError(f"{source} entry names no week: {entry!r}")
    if 0 <= week < horizon:
        out[week] = out.get(week, 0.0) + float(hours)


def _reductions(
    spec: Any,
    anchor: _Anchor,
    capacity: float,
    horizon: int,
    source: str,
) -> tuple[dict[int, float], list[dict[str, Any]]]:
    """Normalize any accepted reduction spec into week -> hours,
    plus the list of day-grained aggregations performed."""
    out: dict[int, float] = {}
    day_grain: list[dict[str, Any]] = []
    if spec is None:
        return out, day_grain
    if isinstance(spec, dict) and "weeks" in spec:
        # The fold's person-week series shape (S1).
        weeks = spec["weeks"]
        if not isinstance(weeks, dict):
            raise ValueError(f"{source} series weeks must be a mapping")
        for monday_iso, bucket in weeks.items():
            hours = bucket.get("established_hours") if isinstance(bucket, dict) else None
            if not _is_number(hours) or hours < 0:
                raise ValueError(f"{source} series bucket is malformed: {bucket!r}")
            week = anchor.week_of(monday_iso, f"{source} series week")
            if 0 <= week < horizon:
                out[week] = out.get(week, 0.0) + float(hours)
        return out, day_grain
    entries = spec if isinstance(spec, list) else [spec]
    for entry in entries:
        _accumulate_reduction(out, day_grain, entry, anchor, capacity, horizon, source)
    return out, day_grain


# ---------------------------------------------------------------------------
# Task normalization
# ---------------------------------------------------------------------------


def _priority_rank(priority: Any, dimensions: list[str] | None) -> tuple[float, ...]:
    if priority is None:
        return ()
    if _is_number(priority):
        return (float(priority),)
    if isinstance(priority, str):
        text = priority.strip().lower()
        if not text:
            return ()
        try:
            return (float(text),)
        except ValueError:
            pass
        for word, value in _PRIORITY_WORDS.items():
            if text.startswith(word):
                return (value,)
        return ()
    if isinstance(priority, dict):
        dims = dimensions if dimensions is not None else sorted(priority)
        rank: list[float] = []
        for dim in dims:
            value = priority.get(dim)
            rank.append(float(value) if _is_number(value) else 0.0)
        return tuple(rank)
    return ()


def _normalize_gates(
    raw_task: dict[str, Any],
    task_ids: set[str],
    milestone_ids: set[str],
    project_ids: set[str],
) -> list[dict[str, str]]:
    gates: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, on: str) -> None:
        key = (kind, on)
        if key not in seen:
            seen.add(key)
            gates.append({"kind": kind, "on": on})

    raw_deps: list[Any] = []
    deps = raw_task.get("dependencies")
    if isinstance(deps, list):
        raw_deps.extend(deps)
    dep_ids = raw_task.get("dependency_ids")
    if isinstance(dep_ids, list):
        raw_deps.extend(dep_ids)
    for dep in raw_deps:
        if isinstance(dep, str):
            if dep in task_ids:
                add("task", dep)
            elif dep in milestone_ids:
                add("milestone", dep)
            elif dep in project_ids:
                add("undertaking", dep)
            else:
                add("task", dep)  # dangling: an external gate on a task id
        elif isinstance(dep, dict):
            on = dep.get("on")
            unlock = dep.get("unlock") or "task"
            if not isinstance(on, str) or not on:
                raise ValueError(f"dependency needs an 'on' id: {dep!r}")
            if unlock not in ("task", "milestone", "undertaking"):
                raise ValueError(f"unknown unlock kind: {unlock!r}")
            add(unlock, on)
        else:
            raise ValueError(f"dependency must be an id or a mapping: {dep!r}")
    return gates


def normalize_task(
    raw: dict[str, Any],
    *,
    seq: int = 0,
    layer: str = "world",
    anchor: _Anchor | None = None,
    priority_dimensions: list[str] | None = None,
    task_ids: set[str] | None = None,
    milestone_ids: set[str] | None = None,
    project_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Normalize one caller-assembled task record into the kernel's
    internal shape. Exported for S4/S5 assemblers: the same
    normalization the kernel applies internally, so an assembler's
    validation matches the kernel's exactly."""
    if not isinstance(raw, dict):
        raise ValueError(f"task must be a mapping: {raw!r}")
    task_id = raw.get("id")
    project_id = raw.get("project_id")
    if not isinstance(task_id, str) or not task_id:
        raise ValueError(f"task needs a string id: {raw!r}")
    if not isinstance(project_id, str) or not project_id:
        raise ValueError(f"task {task_id!r} needs a string project_id")
    anchor = anchor or _Anchor(None)
    due_week = raw.get("due_week")
    if due_week is None and raw.get("due_date") is not None:
        due_week = anchor.week_containing(raw["due_date"], f"task {task_id} due_date")
    if due_week is not None and (not isinstance(due_week, int) or isinstance(due_week, bool)):
        raise ValueError(f"task {task_id} due_week must be an int: {due_week!r}")
    release_week = raw.get("release_week")
    if release_week is None and raw.get("release_date") is not None:
        release_week = anchor.week_containing(
            raw["release_date"], f"task {task_id} release_date"
        )
    if release_week is None:
        release_week = 0
    status = raw.get("status")
    precompleted = bool(raw.get("established")) or (
        isinstance(status, str) and status.strip().lower() in _DONE_STATUSES
    )
    return {
        "id": task_id,
        "project_id": project_id,
        "effort": _normalize_effort(raw.get("effort")),
        "gates": _normalize_gates(
            raw,
            task_ids if task_ids is not None else set(),
            milestone_ids if milestone_ids is not None else set(),
            project_ids if project_ids is not None else set(),
        ),
        "firm": (raw.get("timeframe_commitment") or None) == "firm",
        "due_week": due_week,
        "priority_rank": _priority_rank(raw.get("priority"), priority_dimensions),
        "release_week": int(release_week),
        "precompleted": precompleted,
        "seq": seq,
        "layer": layer,
    }


# ---------------------------------------------------------------------------
# Graph: cycle detection over world ∪ scenario ∪ milestones ∪ undertakings
# ---------------------------------------------------------------------------


def _undertaking_node(project_id: str) -> str:
    return f"undertaking:{project_id}"


def _find_cycle(
    tasks: list[dict[str, Any]],
    milestones: dict[str, list[str]],
    project_tasks: dict[str, list[str]],
) -> list[str] | None:
    """One concrete dependency cycle (node ids in cycle order), or
    None. Deterministic: nodes and edges are visited in sorted
    order, so the reported cycle is stable for a given input."""
    edges: dict[str, list[str]] = {}

    def node_edges(node: str) -> list[str]:
        if node not in edges:
            out: list[str] = []
            if node in milestones:
                out = list(milestones[node])
            elif node.startswith("undertaking:"):
                out = list(project_tasks.get(node.split(":", 1)[1], []))
            edges[node] = sorted(out)
        return edges[node]

    task_by_id = {t["id"]: t for t in tasks}
    for task in tasks:
        outs: list[str] = []
        for gate in task["gates"]:
            if gate["kind"] == "task":
                if gate["on"] in task_by_id:
                    outs.append(gate["on"])
            elif gate["kind"] == "milestone":
                if gate["on"] in milestones:
                    outs.append(gate["on"])
            else:
                outs.append(_undertaking_node(gate["on"]))
        edges[task["id"]] = sorted(set(outs))
    for mid in milestones:
        node_edges(mid)
    for pid in project_tasks:
        node_edges(_undertaking_node(pid))

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        color[node] = GRAY
        stack.append(node)
        for nxt in edges.get(node, []):
            state = color.get(nxt, WHITE)
            if state == GRAY:
                return stack[stack.index(nxt):] + [nxt]
            if state == WHITE:
                found = visit(nxt)
                if found is not None:
                    return found
        stack.pop()
        color[node] = BLACK
        return None

    for node in sorted(edges):
        if color.get(node, WHITE) == WHITE:
            found = visit(node)
            if found is not None:
                return found
    return None


# ---------------------------------------------------------------------------
# One scheduling run (a bound mode over a task set)
# ---------------------------------------------------------------------------


class _Pass:
    """Weekly list scheduling over one task set under one effort
    bound. See the module docstring for the semantics."""

    def __init__(
        self,
        *,
        all_tasks: list[dict[str, Any]],
        task_set: list[dict[str, Any]],
        milestones: dict[str, list[str]],
        project_tasks: dict[str, list[str]],
        bound: str,
        base_free: list[float],
        capacity_by_week: list[float],
        horizon: int,
        target_project_id: str | None,
        target_advances: bool,
        project_deadlines: dict[str, int],
        frozen: dict[str, dict[int, float]] | None = None,
        seed_boundaries: dict[str, int] | None = None,
    ):
        self.all_by_id = {t["id"]: t for t in all_tasks}
        self.task_set = task_set
        self.set_ids = {t["id"] for t in task_set}
        self.milestones = milestones
        self.project_tasks = project_tasks
        self.bound = bound
        self.horizon = horizon
        self.target_project_id = target_project_id
        self.target_advances = target_advances
        self.project_deadlines = project_deadlines
        self.frozen = frozen or {}
        self.capacity_by_week = capacity_by_week

        # Free capacity: base free minus frozen (baseline) placements.
        self.free: list[float] = []
        for w in range(horizon):
            used = sum(hours.get(w, 0.0) for hours in self.frozen.values())
            self.free.append(max(0.0, base_free[w] - used))

        self.bound_value: dict[str, float | None] = {
            t["id"]: _effort_bound(t["effort"], bound) for t in task_set
        }
        # Pre-completed tasks (anywhere in the input) finish at 0.
        # Seeded boundaries (the sustainable pass seeds the baseline
        # placements) count as already-finished work for gate
        # purposes: their hours are frozen, their completions real.
        self.finish_boundary: dict[str, int] = {
            t["id"]: 0 for t in all_tasks if t["precompleted"]
        }
        if seed_boundaries:
            self.finish_boundary.update(seed_boundaries)
        self.seeded: set[str] = set(seed_boundaries or ())
        self.unresolved: dict[str, dict[str, Any]] = {}
        self.blocked: list[dict[str, Any]] = []
        self._resolve()

    # -- gate evaluation ---------------------------------------------------

    def _gate_state(self, gate: dict[str, str], resolvable: set[str]) -> str:
        """'ok' when the gate can complete inside this pass,
        'external' when it names something absent from the input,
        'excluded' when it names input work outside this pass."""
        kind, on = gate["kind"], gate["on"]
        if kind == "task":
            dep = self.all_by_id.get(on)
            if dep is None:
                return "external"
            if dep["precompleted"] or on in self.seeded:
                return "ok"
            return "ok" if on in resolvable else "waiting"
        if kind == "milestone":
            members = self.milestones.get(on)
            if members is None:
                return "external"
            for member in members:
                dep = self.all_by_id.get(member)
                if dep is None:
                    return "external"
                if dep["precompleted"] or member in self.seeded:
                    continue
                if member not in resolvable:
                    return "waiting"
            return "ok"
        # undertaking
        members = self.project_tasks.get(on)
        if not members:
            return "external"
        for member in members:
            dep = self.all_by_id[member]
            if dep["precompleted"] or member in self.seeded:
                continue
            if member not in resolvable:
                return "waiting"
        return "ok"

    def _resolve(self) -> None:
        """Fixpoint resolvability: a task is resolvable when its own
        bound value exists and every gate can complete in this pass.
        Everything else is unresolved, with the root cause named."""
        resolvable: set[str] = set()
        changed = True
        while changed:
            changed = False
            for task in self.task_set:
                tid = task["id"]
                if tid in resolvable or self.bound_value[tid] is None:
                    continue
                if all(
                    self._gate_state(gate, resolvable) == "ok"
                    for gate in task["gates"]
                ):
                    resolvable.add(tid)
                    changed = True
        for task in self.task_set:
            tid = task["id"]
            if tid in resolvable:
                continue
            if self.bound_value[tid] is None:
                self.unresolved[tid] = {
                    "task_id": tid,
                    "reason": "unknown_effort",
                    "detail": (
                        "effort is unknown at the "
                        f"{self.bound} bound; no defensible duration exists"
                    ),
                }
                continue
            missing: list[str] = []
            excluded: list[str] = []
            waiting_on: list[str] = []
            for gate in task["gates"]:
                state = self._gate_state(gate, resolvable)
                if state == "external":
                    missing.append(gate["on"])
                elif state == "waiting":
                    # Waiting on a node that is itself unresolved, or
                    # on work outside this pass.
                    on = gate["on"]
                    if gate["kind"] == "task" and on in self.all_by_id and on not in self.set_ids:
                        excluded.append(on)
                    elif gate["kind"] == "undertaking" and any(
                        m not in self.set_ids and not self.all_by_id[m]["precompleted"]
                        for m in self.project_tasks.get(on, [])
                    ):
                        excluded.append(on)
                    else:
                        waiting_on.append(on)
            if missing:
                reason = "blocked_external_gate"
                detail = f"prerequisite(s) absent from the input: {missing}"
                self.blocked.append(
                    {"task_id": tid, "missing_prerequisites": missing}
                )
            elif excluded:
                reason = "prerequisite_outside_pass"
                detail = f"prerequisite work is outside this pass: {excluded}"
            else:
                reason = "depends_on_unresolved"
                detail = f"depends on unresolved work: {waiting_on}"
            self.unresolved[tid] = {
                "task_id": tid,
                "reason": reason,
                "detail": detail,
            }
        self.resolvable = resolvable

    # -- effective deadlines (firm-derived slack) ---------------------------

    def _effective_due(self) -> dict[str, int]:
        """Each resolvable task's effective firm deadline week,
        propagated backward through dependents: a prerequisite of a
        firm task inherits urgency from it. Durations use this run's
        bound values at full weekly capacity — an ordering heuristic,
        documented as such, never a feasibility claim."""
        capacity0 = self.capacity_by_week[0] if self.capacity_by_week else 0.0
        rate = capacity0 if capacity0 > _EPS else 1.0

        def duration_weeks(tid: str) -> int:
            value = self.bound_value.get(tid)
            if value is None or value <= _EPS:
                return 0
            return max(1, math.ceil(value / rate))

        due: dict[str, int] = {}
        for task in self.task_set:
            tid = task["id"]
            own: int | None = None
            if task["firm"] and task["due_week"] is not None:
                own = task["due_week"]
            project_due = self.project_deadlines.get(task["project_id"])
            if project_due is not None:
                own = project_due if own is None else min(own, project_due)
            if own is not None:
                due[tid] = own
        # Reverse adjacency over finish influence.
        dependents: dict[str, set[str]] = {t["id"]: set() for t in self.task_set}
        for task in self.task_set:
            for gate in task["gates"]:
                if gate["kind"] == "task" and gate["on"] in dependents:
                    dependents[gate["on"]].add(task["id"])
                elif gate["kind"] == "milestone":
                    for member in self.milestones.get(gate["on"], []):
                        if member in dependents:
                            dependents[member].add(task["id"])
                elif gate["kind"] == "undertaking":
                    for member in self.project_tasks.get(gate["on"], []):
                        if member in dependents:
                            dependents[member].add(task["id"])
        # Propagate in reverse topological order (the graph is
        # acyclic — cycles were rejected before any pass ran).
        order: list[str] = []
        seen: set[str] = set()

        def topo(tid: str) -> None:
            if tid in seen:
                return
            seen.add(tid)
            for dep in dependents.get(tid, ()):  # dependents first
                topo(dep)
            order.append(tid)

        for task in self.task_set:
            topo(task["id"])
        for tid in order:  # order has dependents before prerequisites
            if tid not in due:
                continue
            # This task's due flows back to its prerequisites.
            task = self.all_by_id[tid]
            for gate in task["gates"]:
                targets: list[str] = []
                if gate["kind"] == "task":
                    targets = [gate["on"]]
                elif gate["kind"] == "milestone":
                    targets = list(self.milestones.get(gate["on"], []))
                elif gate["kind"] == "undertaking":
                    targets = list(self.project_tasks.get(gate["on"], []))
                for pre in targets:
                    if pre not in self.set_ids:
                        continue
                    inherited = due[tid] - duration_weeks(tid)
                    if pre not in due or inherited < due[pre]:
                        due[pre] = inherited
        return due

    # -- the list schedule ---------------------------------------------------

    def run(self) -> dict[str, Any]:
        horizon = self.horizon
        remaining: dict[str, float] = {
            tid: float(self.bound_value[tid] or 0.0) for tid in self.resolvable
        }
        hours_by_week: dict[str, dict[int, float]] = {tid: {} for tid in self.resolvable}
        start_week: dict[str, int] = {}
        finish_week: dict[str, int] = {}
        completed: set[str] = set()
        due_eff = self._effective_due()

        def gates_met(task: dict[str, Any], week: int) -> bool:
            for gate in task["gates"]:
                kind, on = gate["kind"], gate["on"]
                if kind == "task":
                    boundary = self.finish_boundary.get(on)
                    if boundary is None or boundary > week:
                        return False
                elif kind == "milestone":
                    for member in self.milestones.get(on, []):
                        boundary = self.finish_boundary.get(member)
                        if boundary is None or boundary > week:
                            return False
                else:
                    for member in self.project_tasks.get(on, []):
                        boundary = self.finish_boundary.get(member)
                        if boundary is None or boundary > week:
                            return False
            return True

        def selection_key(task: dict[str, Any], week: int) -> tuple:
            tid = task["id"]
            value = self.bound_value[tid] or 0.0
            rate = self.capacity_by_week[week] if week < len(self.capacity_by_week) else 0.0
            duration = 0 if value <= _EPS else max(1, math.ceil(value / (rate or 1.0)))
            if tid in due_eff:
                slack: float = due_eff[tid] - (week + duration - 1)
                firm_bucket = 0
            else:
                slack = 0.0
                firm_bucket = 1
            boost = 0
            if (
                self.target_advances
                and self.target_project_id is not None
                and firm_bucket == 1
            ):
                boost = 0 if task["project_id"] == self.target_project_id else 1
            neg_priority = tuple(-v for v in task["priority_rank"])
            return (firm_bucket, slack, boost, neg_priority, task["release_week"], task["seq"])

        for week in range(horizon):
            # Zero-effort fixpoint: tasks with no duration complete at
            # their start boundary and unlock dependents this week.
            changed = True
            while changed:
                changed = False
                for task in self.task_set:
                    tid = task["id"]
                    if tid not in self.resolvable or tid in completed:
                        continue
                    if (self.bound_value[tid] or 0.0) > _EPS:
                        continue
                    if task["release_week"] > week:
                        continue
                    if not gates_met(task, week):
                        continue
                    boundary = week
                    for gate in task["gates"]:
                        kind, on = gate["kind"], gate["on"]
                        members = (
                            [on]
                            if kind == "task"
                            else list(
                                self.milestones.get(on, [])
                                if kind == "milestone"
                                else self.project_tasks.get(on, [])
                            )
                        )
                        for member in members:
                            boundary = max(boundary, self.finish_boundary.get(member, 0))
                    boundary = max(boundary, task["release_week"])
                    self.finish_boundary[tid] = boundary
                    start_week[tid] = boundary
                    finish_week[tid] = boundary
                    completed.add(tid)
                    changed = True
            # Allocate this week's free capacity.
            while self.free[week] > _EPS:
                ready = [
                    task
                    for task in self.task_set
                    if task["id"] in self.resolvable
                    and task["id"] not in completed
                    and remaining[task["id"]] > _EPS
                    and task["release_week"] <= week
                    and gates_met(task, week)
                ]
                if not ready:
                    break
                ready.sort(key=lambda t: selection_key(t, week))
                task = ready[0]
                tid = task["id"]
                take = min(remaining[tid], self.free[week])
                hours_by_week[tid][week] = hours_by_week[tid].get(week, 0.0) + take
                if tid not in start_week:
                    start_week[tid] = week
                remaining[tid] -= take
                self.free[week] -= take
                if remaining[tid] <= _EPS:
                    finish_week[tid] = week
                    self.finish_boundary[tid] = week + 1
                    completed.add(tid)
            if len(completed) >= len(self.resolvable):
                # Remaining weeks stay untouched; stop early.
                if all(tid in completed for tid in self.resolvable):
                    break

        beyond_horizon = sorted(tid for tid in self.resolvable if tid not in completed)
        task_weeks: dict[str, Any] = {}
        for tid in sorted(completed):
            task_weeks[tid] = {
                "start_week": start_week[tid],
                "finish_week": finish_week[tid],
                "finish_boundary": self.finish_boundary[tid],
                "hours_by_week": {
                    str(w): round(h, 4) for w, h in sorted(hours_by_week[tid].items())
                },
            }
        # Frozen placements ride along so consumers see the whole
        # arrangement (sustainable pass); they are marked as such.
        for tid, hours in self.frozen.items():
            if tid in task_weeks or not hours:
                continue
            weeks = sorted(hours)
            task_weeks[tid] = {
                "start_week": weeks[0],
                "finish_week": weeks[-1],
                "finish_boundary": weeks[-1] + 1,
                "hours_by_week": {str(w): round(h, 4) for w, h in sorted(hours.items())},
                "frozen_from_baseline": True,
            }

        project_finish: dict[str, Any] = {}
        project_ids = sorted(
            {t["project_id"] for t in self.task_set}
            | ({self.target_project_id} if self.target_project_id else set())
        )
        for pid in project_ids:
            members = [t for t in self.task_set if t["project_id"] == pid]
            member_ids = [t["id"] for t in members]
            unresolved_ids = [tid for tid in member_ids if tid in self.unresolved]
            horizon_ids = [tid for tid in member_ids if tid in beyond_horizon]
            done_ids = [tid for tid in member_ids if tid in completed]
            # Pre-completed members count toward completion.
            pre = [t["id"] for t in members if t["precompleted"]]
            complete = (
                len(members) > 0
                and not unresolved_ids
                and not horizon_ids
                and len(done_ids) + len(pre) >= len(members)
            )
            # The known subgraph's completion is always reported;
            # the project's FINISH is reported only when the project
            # actually completes — an incomplete undertaking's finish
            # is unknown, never its partial progress dressed as one.
            known_boundary: int | None = None
            if done_ids:
                known_boundary = max(self.finish_boundary[tid] for tid in done_ids)
            elif pre and len(pre) == len(members):
                known_boundary = 0
            boundary = known_boundary if complete else None
            last_work_week: int | None = None
            if complete and done_ids:
                last_work_week = max(finish_week[tid] for tid in done_ids)
            elif complete:
                last_work_week = 0
            project_finish[pid] = {
                "finish_week": last_work_week,
                "finish_boundary": boundary,
                "elapsed_weeks": float(boundary) if boundary is not None else None,
                "known_subgraph_elapsed_weeks": (
                    float(known_boundary) if known_boundary is not None else None
                ),
                "complete": complete and boundary is not None,
                "unresolved_task_ids": unresolved_ids,
                "beyond_horizon_task_ids": horizon_ids,
                "task_ids": member_ids,
            }

        firm_violations: list[dict[str, Any]] = []
        for task in self.task_set:
            tid = task["id"]
            if tid not in completed:
                continue
            if task["firm"] and task["due_week"] is not None:
                if finish_week[tid] > task["due_week"]:
                    firm_violations.append(
                        {
                            "task_id": tid,
                            "due_week": task["due_week"],
                            "finish_week": finish_week[tid],
                            "kind": "task_deadline",
                        }
                    )
            project_due = self.project_deadlines.get(task["project_id"])
            if project_due is not None and finish_week[tid] > project_due:
                firm_violations.append(
                    {
                        "task_id": tid,
                        "due_week": project_due,
                        "finish_week": finish_week[tid],
                        "kind": "project_deadline",
                    }
                )

        last_busy = 0
        for w in range(horizon):
            if self.free[w] < self.capacity_by_week[w] - _EPS:
                last_busy = max(last_busy, w)
        for tid in completed:
            if finish_week.get(tid) is not None:
                last_busy = max(last_busy, finish_week[tid])
        residual = {
            str(w): round(self.free[w], 4) for w in range(last_busy + 1)
        }
        return {
            "task_weeks": task_weeks,
            "project_finish": project_finish,
            "residual_free_hours_by_week": residual,
            "unresolved": [self.unresolved[tid] for tid in sorted(self.unresolved)],
            "unresolved_task_ids": sorted(self.unresolved),
            "blocked": sorted(self.blocked, key=lambda b: b["task_id"]),
            "beyond_horizon_task_ids": beyond_horizon,
            "firm_violations": firm_violations,
        }


# ---------------------------------------------------------------------------
# Displacement (baseline vs earliest-found, non-established non-firm work)
# ---------------------------------------------------------------------------


def _displacement(
    baseline: dict[str, Any],
    earliest: dict[str, Any],
    all_tasks: list[dict[str, Any]],
    project_deadlines: dict[str, int],
    target_project_id: str | None,
) -> dict[str, Any]:
    firm_ids = {
        t["id"]
        for t in all_tasks
        if t["firm"] or t["project_id"] in project_deadlines
    }
    base_weeks = baseline["task_weeks"]
    early_weeks = earliest["task_weeks"]
    per_project: dict[str, Any] = {}
    for task in all_tasks:
        tid = task["id"]
        if tid in firm_ids or task["project_id"] == target_project_id:
            continue
        if tid not in base_weeks or tid not in early_weeks:
            continue
        base_hours = {int(w): h for w, h in base_weeks[tid]["hours_by_week"].items()}
        early_hours = {int(w): h for w, h in early_weeks[tid]["hours_by_week"].items()}
        shifted = sum(
            abs(base_hours.get(w, 0.0) - early_hours.get(w, 0.0))
            for w in set(base_hours) | set(early_hours)
        )
        moved = shifted > _EPS or (
            base_weeks[tid]["start_week"] != early_weeks[tid]["start_week"]
            or base_weeks[tid]["finish_week"] != early_weeks[tid]["finish_week"]
        )
        if not moved:
            continue
        entry = per_project.setdefault(
            task["project_id"],
            {"hours_shifted": 0.0, "finish_slip_weeks": None, "tasks_affected": []},
        )
        entry["hours_shifted"] = round(entry["hours_shifted"] + shifted, 4)
        entry["tasks_affected"].append(tid)
    for pid, entry in per_project.items():
        base_finish = baseline["project_finish"].get(pid, {})
        early_finish = earliest["project_finish"].get(pid, {})
        if (
            base_finish.get("finish_boundary") is not None
            and early_finish.get("finish_boundary") is not None
        ):
            entry["finish_slip_weeks"] = (
                early_finish["finish_boundary"] - base_finish["finish_boundary"]
            )
    return {"per_project": per_project, "basis": "lower-bound efforts"}


# ---------------------------------------------------------------------------
# The arrangement computation
# ---------------------------------------------------------------------------


def compute_arrangement(
    *,
    tasks: list[dict[str, Any]],
    capacity_hours_per_week: float,
    target_project_id: str | None = None,
    scenario_tasks: list[dict[str, Any]] | None = None,
    milestones: list[dict[str, Any]] | None = None,
    established_allocations: Any = None,
    windows: list[dict[str, Any]] | None = None,
    protected_time: Any = None,
    capacity_overrides: dict[Any, float] | None = None,
    start_week: str | None = None,
    horizon_weeks: int = 104,
    target_advances: bool = True,
    priority_dimensions: list[str] | None = None,
    fold_seq: int | None = None,
    assumption_set_id: str | None = None,
    assumption_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Compute the baseline, earliest-found, and sustainable
    arrangements for one undertaking against one person's world.
    Pure and deterministic; see the module docstring for the full
    input/output contract."""
    if not _is_number(capacity_hours_per_week) or capacity_hours_per_week <= 0:
        raise ValueError("capacity_hours_per_week must be a number > 0")
    capacity = float(capacity_hours_per_week)
    if not isinstance(horizon_weeks, int) or horizon_weeks <= 0:
        raise ValueError("horizon_weeks must be a positive int")
    horizon = horizon_weeks
    anchor = _Anchor(start_week)

    if assumption_set_id is None and assumption_ids is not None:
        assumption_set_id = _assumption_set_id(assumption_ids)

    # -- milestones ---------------------------------------------------------
    milestone_members: dict[str, list[str]] = {}
    for raw_ms in milestones or []:
        if not isinstance(raw_ms, dict) or not isinstance(raw_ms.get("id"), str):
            raise ValueError(f"milestone needs a string id: {raw_ms!r}")
        members = raw_ms.get("members")
        if not isinstance(members, list) or not all(
            isinstance(m, str) for m in members
        ):
            raise ValueError(f"milestone {raw_ms['id']!r} members must be task ids")
        milestone_members[raw_ms["id"]] = list(members)

    # -- tasks ---------------------------------------------------------------
    raw_all = [(raw, "world") for raw in tasks] + [
        (raw, "scenario") for raw in (scenario_tasks or [])
    ]
    raw_ids: set[str] = set()
    for raw, _layer in raw_all:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
            raise ValueError(f"task needs a string id: {raw!r}")
        if raw["id"] in raw_ids:
            raise ValueError(f"duplicate task id: {raw['id']!r}")
        raw_ids.add(raw["id"])
    for mid, members in milestone_members.items():
        if mid in raw_ids:
            raise ValueError(f"milestone id collides with a task id: {mid!r}")
        for member in members:
            if member not in raw_ids:
                raise ValueError(
                    f"milestone {mid!r} member {member!r} is not a task in the input"
                )
    project_ids = {
        raw.get("project_id") for raw, _ in raw_all if isinstance(raw.get("project_id"), str)
    }
    all_tasks: list[dict[str, Any]] = []
    for seq, (raw, layer) in enumerate(raw_all):
        all_tasks.append(
            normalize_task(
                raw,
                seq=seq,
                layer=layer,
                anchor=anchor,
                priority_dimensions=priority_dimensions,
                task_ids=raw_ids,
                milestone_ids=set(milestone_members),
                project_ids=project_ids,  # type: ignore[arg-type]
            )
        )
    project_tasks: dict[str, list[str]] = {}
    for task in all_tasks:
        project_tasks.setdefault(task["project_id"], []).append(task["id"])

    # -- windows: holds reduce capacity; deadlines constrain projects -------
    project_deadlines: dict[str, int] = {}
    hold_entries: list[dict[str, Any]] = []
    for window in windows or []:
        if not isinstance(window, dict):
            raise ValueError(f"window must be a mapping: {window!r}")
        kind = window.get("kind") or "hold"
        if kind == "deadline":
            pid = window.get("project_id")
            if not isinstance(pid, str) or not pid:
                raise ValueError(f"deadline window needs a project_id: {window!r}")
            due = window.get("due_week")
            if due is None and window.get("due_date") is not None:
                due = anchor.week_containing(window["due_date"], "deadline due_date")
            if not isinstance(due, int) or isinstance(due, bool):
                raise ValueError(f"deadline window needs due_week or due_date: {window!r}")
            project_deadlines[pid] = (
                due if pid not in project_deadlines else min(project_deadlines[pid], due)
            )
        elif kind == "hold":
            hold_entries.append(window)
        else:
            raise ValueError(f"unknown window kind: {kind!r}")

    # -- capacity by week ------------------------------------------------------
    capacity_by_week = [capacity] * horizon
    for key, hours in (capacity_overrides or {}).items():
        if not _is_number(hours) or hours < 0:
            raise ValueError(f"capacity override hours must be >= 0: {key!r}")
        if isinstance(key, int) and not isinstance(key, bool):
            week = key
        elif isinstance(key, str) and key.lstrip("-").isdigit():
            week = int(key)
        else:
            week = anchor.week_of(key, "capacity override key")
        if 0 <= week < horizon:
            capacity_by_week[week] = float(hours)

    alloc_by_week, alloc_day = _reductions(
        established_allocations, anchor, capacity, horizon, "established allocations"
    )
    hold_by_week, hold_day = _reductions(
        hold_entries, anchor, capacity, horizon, "windows/holds"
    )
    protected_by_week, protected_day = _reductions(
        protected_time, anchor, capacity, horizon, "protected time"
    )
    day_grain = alloc_day + hold_day + protected_day

    base_free: list[float] = []
    over_committed: list[dict[str, Any]] = []
    for w in range(horizon):
        immovable = (
            alloc_by_week.get(w, 0.0)
            + hold_by_week.get(w, 0.0)
            + protected_by_week.get(w, 0.0)
        )
        free = capacity_by_week[w] - immovable
        if free < -_EPS:
            over_committed.append(
                {
                    "week": w,
                    "capacity_hours": capacity_by_week[w],
                    "immovable_hours": round(immovable, 4),
                }
            )
        base_free.append(max(0.0, free))

    # -- labels -----------------------------------------------------------------
    algo_settings: dict[str, Any] = {
        "algorithm": ALGORITHM,
        "grain": "week",
        "selection_order": [
            "firm_slack",
            "target_advances",
            "priority",
            "release_week",
            "fifo",
        ],
        "target_advances": bool(target_advances),
        "horizon_weeks": horizon,
        "priority_dimensions": priority_dimensions,
    }
    settings_hash = hashlib.sha256(
        json.dumps(algo_settings, sort_keys=True).encode("utf-8")
    ).hexdigest()
    labels: dict[str, Any] = {
        "algorithm": ALGORITHM,
        "kernel_version": KERNEL_VERSION,
        "algo_settings_hash": settings_hash,
        "algo_settings": algo_settings,
        "fold_seq": fold_seq,
        "assumption_set_id": assumption_set_id,
        "claim": CLAIM,
        "grain": "week",
        "grain_disclaimer": GRAIN_DISCLAIMER,
        "aggregated_day_grain_holds": day_grain,
        "start_week": anchor.monday.isoformat() if anchor.monday else None,
    }

    # -- cycle gate ---------------------------------------------------------------
    cycle = _find_cycle(all_tasks, milestone_members, project_tasks)
    if cycle is not None:
        return {
            "status": "rejected",
            "rejection": {"reason": "dependency_cycle", "cycle": cycle},
            "labels": labels,
            "target_project_id": target_project_id,
        }

    world_tasks = [t for t in all_tasks if t["layer"] == "world"]
    scenario = [t for t in all_tasks if t["layer"] == "scenario"]
    dual = not _all_exact(all_tasks)
    bounds = ["low", "high"] if dual else ["low"]

    runs: dict[str, Any] = {}
    for bound in bounds:
        if target_project_id is None:
            baseline_set = list(all_tasks)
        else:
            baseline_set = [
                t for t in world_tasks if t["project_id"] != target_project_id
            ]
        baseline_pass = _Pass(
            all_tasks=all_tasks,
            task_set=baseline_set,
            milestones=milestone_members,
            project_tasks=project_tasks,
            bound=bound,
            base_free=base_free,
            capacity_by_week=capacity_by_week,
            horizon=horizon,
            target_project_id=None,
            target_advances=False,
            project_deadlines=project_deadlines,
        )
        baseline = baseline_pass.run()
        run_out: dict[str, Any] = {"baseline": baseline}

        if target_project_id is not None:
            full_set = list(world_tasks) + list(scenario)
            earliest_pass = _Pass(
                all_tasks=all_tasks,
                task_set=full_set,
                milestones=milestone_members,
                project_tasks=project_tasks,
                bound=bound,
                base_free=base_free,
                capacity_by_week=capacity_by_week,
                horizon=horizon,
                target_project_id=target_project_id,
                target_advances=target_advances,
                project_deadlines=project_deadlines,
            )
            earliest = earliest_pass.run()
            run_out["earliest_found"] = earliest
            run_out["displacement"] = _displacement(
                baseline, earliest, all_tasks, project_deadlines, target_project_id
            )

            frozen = {
                tid: {int(w): h for w, h in info["hours_by_week"].items()}
                for tid, info in baseline["task_weeks"].items()
            }
            seed_boundaries = {
                tid: info["finish_boundary"]
                for tid, info in baseline["task_weeks"].items()
            }
            sustainable_pass = _Pass(
                all_tasks=all_tasks,
                task_set=[
                    t for t in full_set if t["project_id"] == target_project_id
                ],
                milestones=milestone_members,
                project_tasks=project_tasks,
                bound=bound,
                base_free=base_free,
                capacity_by_week=capacity_by_week,
                horizon=horizon,
                target_project_id=target_project_id,
                target_advances=False,
                project_deadlines=project_deadlines,
                frozen=frozen,
                seed_boundaries=seed_boundaries,
            )
            sustainable_run = sustainable_pass.run()
            run_out["sustainable"] = _sustainable_verdict(
                sustainable_run=sustainable_run,
                baseline=baseline,
                all_tasks=all_tasks,
                target_project_id=target_project_id,
                base_free=base_free,
                capacity_by_week=capacity_by_week,
                alloc_by_week=alloc_by_week,
                protected_by_week=protected_by_week,
                horizon=horizon,
            )
        runs[bound] = run_out

    headline = runs["low"]
    result: dict[str, Any] = {
        "status": "ok",
        "rejection": None,
        "labels": labels,
        "target_project_id": target_project_id,
        "runs": runs,
        "baseline": headline["baseline"],
        "earliest_found": headline.get("earliest_found"),
        "sustainable": headline.get("sustainable"),
        "displacement": headline.get("displacement"),
        "over_committed_weeks": over_committed,
        "inputs_summary": {
            "world_tasks": len(world_tasks),
            "scenario_tasks": len(scenario),
            "projects": len(project_tasks),
            "milestones": len(milestone_members),
            "dual_bound_runs": dual,
        },
    }
    if target_project_id is not None:
        result["target"] = _target_summary(runs, target_project_id, dual)
    return result


def _target_summary(
    runs: dict[str, Any], target_project_id: str, dual: bool
) -> dict[str, Any]:
    low_earliest = runs["low"].get("earliest_found") or {}
    low_finish = low_earliest.get("project_finish", {}).get(target_project_id, {})
    summary: dict[str, Any] = {
        "project_id": target_project_id,
        "earliest_found": {
            "finish_week": low_finish.get("finish_week"),
            "finish_boundary": low_finish.get("finish_boundary"),
            "elapsed_weeks": low_finish.get("elapsed_weeks"),
            "complete": bool(low_finish.get("complete")),
            "known_subgraph_elapsed_weeks": low_finish.get(
                "known_subgraph_elapsed_weeks"
            ),
            "unresolved_task_ids": low_finish.get("unresolved_task_ids", []),
            "label": "earliest found under the stated settings",
        },
        "sustainable_status": (runs["low"].get("sustainable") or {}).get("status"),
    }
    if dual:
        high_earliest = runs["high"].get("earliest_found") or {}
        high_finish = high_earliest.get("project_finish", {}).get(target_project_id, {})
        summary["finish_range_weeks"] = {
            "low": low_finish.get("elapsed_weeks"),
            "high": high_finish.get("elapsed_weeks"),
        }
    else:
        summary["finish_range_weeks"] = None
    return summary


def _sustainable_verdict(
    *,
    sustainable_run: dict[str, Any],
    baseline: dict[str, Any],
    all_tasks: list[dict[str, Any]],
    target_project_id: str,
    base_free: list[float],
    capacity_by_week: list[float],
    alloc_by_week: dict[int, float],
    protected_by_week: dict[int, float],
    horizon: int,
) -> dict[str, Any]:
    """The sustainable verdict against the named constraint set.
    Capacity and firm deadlines are checked against the composed
    arrangement. Protected time and established commitments hold by
    construction — their reductions are pre-consumed from free
    capacity before any pass allocates, and immovables are inputs
    the kernel never reallocates — and are reported with their hour
    values so a consumer can verify them against the record."""
    target_finish = sustainable_run["project_finish"].get(target_project_id, {})
    blocking: list[dict[str, Any]] = []
    unknowns: list[dict[str, Any]] = []

    # Firm deadlines: baseline-frozen work and the target placement.
    for violation in baseline["firm_violations"]:
        blocking.append({"constraint": "firm_deadline_met", **violation, "pass": "baseline"})
    for violation in sustainable_run["firm_violations"]:
        blocking.append({"constraint": "firm_deadline_met", **violation, "pass": "sustainable"})

    # A firm item with unknown effort anywhere in the arrangement
    # makes sustainability uncertifiable (brief §4).
    firm_unknown = [
        entry
        for entry in baseline["unresolved"] + sustainable_run["unresolved"]
        if entry["reason"] == "unknown_effort"
        and any(
            t["id"] == entry["task_id"] and t["firm"] for t in all_tasks
        )
    ]
    for entry in firm_unknown:
        unknowns.append(
            {
                "constraint": "firm_effort_known",
                "task_id": entry["task_id"],
                "detail": "a firm item's effort is unknown; sustainability cannot be certified",
            }
        )

    # Target-side unknowns and blockers.
    for entry in sustainable_run["unresolved"]:
        if entry["task_id"] in target_finish.get("task_ids", []):
            if entry["reason"] == "unknown_effort":
                unknowns.append(
                    {"constraint": "target_effort_known", **entry}
                )
            else:
                unknowns.append({"constraint": "target_schedulable", **entry})
    if target_finish.get("beyond_horizon_task_ids"):
        blocking.append(
            {
                "constraint": "horizon",
                "detail": "target work does not fit within the horizon at residual capacity",
                "task_ids": target_finish["beyond_horizon_task_ids"],
            }
        )

    # Capacity ceiling check over the composed arrangement.
    composed: dict[int, float] = {}
    for info in baseline["task_weeks"].values():
        for w, h in info["hours_by_week"].items():
            composed[int(w)] = composed.get(int(w), 0.0) + h
    for tid, info in sustainable_run["task_weeks"].items():
        if info.get("frozen_from_baseline"):
            continue
        for w, h in info["hours_by_week"].items():
            composed[int(w)] = composed.get(int(w), 0.0) + h
    capacity_violations = []
    for w in range(horizon):
        immovable = (capacity_by_week[w] - base_free[w])
        total = immovable + composed.get(w, 0.0)
        if total > capacity_by_week[w] + 1e-6:
            capacity_violations.append(
                {"week": w, "total_hours": round(total, 4), "capacity_hours": capacity_by_week[w]}
            )
    if capacity_violations:
        blocking.append(
            {"constraint": "capacity_ceiling", "weeks": capacity_violations}
        )

    constraint_set = {
        "capacity_ceiling_respected_every_week": not capacity_violations,
        "protected_time_intact": True,  # reductions pre-consumed, never allocated into
        "protected_hours_by_week": {
            str(w): round(h, 4) for w, h in sorted(protected_by_week.items()) if h > _EPS
        },
        "established_commitments_unmoved": True,  # immovables are inputs, never reallocated
        "established_hours_by_week": {
            str(w): round(h, 4) for w, h in sorted(alloc_by_week.items()) if h > _EPS
        },
        "firm_deadlines_met": not any(
            b["constraint"] == "firm_deadline_met" for b in blocking
        ),
    }

    if blocking:
        status = "no sustainable arrangement"
    elif unknowns:
        status = "unknown"
    elif not target_finish.get("complete"):
        status = "unknown"
        unknowns.append(
            {
                "constraint": "target_complete",
                "detail": "the target undertaking did not fully schedule",
            }
        )
    else:
        status = "sustainable"

    return {
        "status": status,
        "constraint_set": constraint_set,
        "blocking_constraints": blocking,
        "unknowns": unknowns,
        "target_placement": {
            tid: info
            for tid, info in sustainable_run["task_weeks"].items()
            if not info.get("frozen_from_baseline")
        },
        "target_finish": target_finish,
        "unresolved": sustainable_run["unresolved"],
        "firm_violations": sustainable_run["firm_violations"],
    }
