"""Temporal standing — span records with standing, folded from decisions.

Temporal Orchestration, slice step S1 (brief
``zenaf-temporal-orchestration-slice-brief-2026-11-28.md`` §§1–2).
Founder rulings carried here:

- **Exploration is not a durable decision** (Refinement 1): temporary
  calculations are never persisted; this module records only standing
  records, and the lifecycle events (approval / withdrawal /
  establishment outcome / revision) arrive with their own steps. The
  decisions store is not a simulation log.
- **Independent temporal dimensions** (Refinement 4): every span record
  carries five orthogonal properties — origin, standing,
  conditionality, confidence (derived from the effort representation +
  basis + method), and temporal role. None implies another: a derived
  forecast may become a visitor-approved target without becoming an
  unconditional commitment.
- **Canonical date fields stay reserved**: nothing here writes
  ``projects.start_date`` / ``end_date``. Derived and provisional spans
  live only in this standing representation, never in fields
  indistinguishable from recorded dates.

Persistence follows the declarations precedent (``declarations.py``):
span and allocation records are VE **decisions** — the owner-scoped,
append-only store — with dedicated decision types:

- ``temporal_span_recorded``     — entity ``project``; final snapshot
  is the span record (below). The decision's own id IS the span's id.
- ``temporal_span_withdrawn``    — entity ``project``; snapshot
  ``{span_id}`` removes that span from current standing.
- ``temporal_allocation_recorded`` — entity ``person``; snapshot
  ``{week_start, hours, project_id}`` records established hours in one
  person-week bucket. The decision's id IS the allocation's id.
- ``temporal_allocation_withdrawn`` — entity ``person``; snapshot
  ``{allocation_id}``.

A span record's snapshot shape (all five §2 properties explicit)::

    {
      "start": "2026-11-05" | null,        # ISO date/datetime
      "end":   "2026-12-03" | null,        # null end = open-ended
      "origin":   "visitor-recorded" | "evidence-recovered"
                | "derived" | "proposed",
      "standing": "historical observation" | "evidence-recovered envelope"
                | "provisional" | "derived forecast" | "visitor target"
                | "established commitment",
      "role":     "window" | "deadline" | "milestone" | "hold",
      "conditionality": {"kind": "unconditional"}
                      | {"kind": "conditional",
                         "assumption_set_id": "<sha256 of sorted ids>",
                         "assumptions": [{"id", "type", "statement"}]},
      "effort":   {"kind": "exact", "hours": n}
                | {"kind": "interval", "low_hours": n, "high_hours": n}
                | {"kind": "lower-bound", "hours": n}
                | {"kind": "upper-bound", "hours": n}
                | {"kind": "unknown"},
      "basis":    ["recorded task due dates", ...],   # evidence refs
      "method":   "evidence recovery over recorded task due dates",
      "supersedes": "<span decision id>" | null,
      "note":     "caveats ride here"
    }

Confidence is never free text: the fold derives ``confidence_label``
from the effort representation (exact → "exact", interval → "bounded
interval", lower-bound → "lower bound only", upper-bound → "upper
bound only", unknown → "unknown"). Confidence is not standing, and
neither establishes truth (Ruling §5).

**Fold materialization.** Current standing is DERIVED by folding the
owner's decision rows in recorded order. The fold is materialized with
a monotonic ``fold_seq``: the SQLite ``rowid`` of the latest decision
folded (decisions are append-only, so rowid order is recorded order
and strictly increases with every new decision — including
non-temporal ones, which is the point: ``fold_seq`` catches membership
drift, per brief §1). Every consumer names the fold_seq it read;
``derive_temporal_standing(user_id, at_fold_seq=n)`` folds only rows
with ``rowid <= n``, so a deliberation can re-read the exact snapshot
it computed against (time-travel reads; a short-TTL cache may sit in
front of this later without changing the semantics).

**Allocations are not spans.** The fold also materializes a versioned
**person-week allocation series** — established hours per person per
ISO week — the capacity ledger the scheduling kernel (S3) and the
concurrency tests operate on. In S1 the series is populated only by
allocation decision records; no writer produces them yet (establishment
arrives in S4). Project ``estimated_weekly_hours`` are NOT folded in:
they are unconfirmed demands (brief §5), still served by
``derived.py``'s read-time capacity picture.

Malformed rows degrade exactly as declarations do: a corrupt record
folds to nothing, never to a broken read.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any

from local_ai.vision_execution import models as M
from local_ai.vision_execution import storage as S
from local_ai.vision_execution.declarations import valid_iso_datetime

SPAN_RECORDED = "temporal_span_recorded"
SPAN_WITHDRAWN = "temporal_span_withdrawn"
ALLOCATION_RECORDED = "temporal_allocation_recorded"
ALLOCATION_WITHDRAWN = "temporal_allocation_withdrawn"

TEMPORAL_TYPES = frozenset(
    {SPAN_RECORDED, SPAN_WITHDRAWN, ALLOCATION_RECORDED, ALLOCATION_WITHDRAWN}
)

ORIGINS = frozenset(
    {"visitor-recorded", "evidence-recovered", "derived", "proposed"}
)

STANDINGS = frozenset(
    {
        "historical observation",
        "evidence-recovered envelope",
        "provisional",
        "derived forecast",
        "visitor target",
        "established commitment",
    }
)

ROLES = frozenset({"window", "deadline", "milestone", "hold"})

#: Point roles: a span with one bound is a moment, so the missing
#: bound normalizes to the present one.
POINT_ROLES = frozenset({"deadline", "milestone"})

_EFFORT_KINDS = frozenset(
    {"exact", "interval", "lower-bound", "upper-bound", "unknown"}
)

#: The confidence label FOLLOWS from the effort representation
#: (brief §2) — derived at fold time, never stored as free text.
CONFIDENCE_LABELS = {
    "exact": "exact",
    "interval": "bounded interval",
    "lower-bound": "lower bound only",
    "upper-bound": "upper bound only",
    "unknown": "unknown",
}


# ---------------------------------------------------------------------------
# Assumption sets (brief §2: typed records, hashed by sorted ID set)
# ---------------------------------------------------------------------------


def assumption_set_id(assumption_ids: list[str]) -> str:
    """The canonical id of an assumption set: sha256 over the sorted
    assumption ids, one per line. Any party holding the same id set
    derives the same set id — the fold recomputes it and rejects a
    record whose stamped id does not match its assumptions."""
    joined = "\n".join(sorted(str(a) for a in assumption_ids))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _parse_assumptions(raw: Any) -> list[dict[str, str]] | None:
    if not isinstance(raw, list) or not raw:
        return None
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        aid = item.get("id")
        atype = item.get("type")
        statement = item.get("statement")
        if not (
            isinstance(aid, str)
            and aid.strip()
            and isinstance(atype, str)
            and atype.strip()
            and isinstance(statement, str)
        ):
            return None
        out.append(
            {"id": aid, "type": atype, "statement": statement}
        )
    return out


def _parse_conditionality(raw: Any) -> dict[str, Any] | None:
    """Normalize a conditionality block, or None when malformed.

    Fail-closed on the assumption-set hash: a conditional record whose
    stamped ``assumption_set_id`` does not recompute from its own
    assumption ids is not a record this fold will carry.
    """
    if raw is None:
        return {"kind": "unconditional"}
    if not isinstance(raw, dict):
        return None
    kind = raw.get("kind")
    if kind == "unconditional":
        return {"kind": "unconditional"}
    if kind != "conditional":
        return None
    assumptions = _parse_assumptions(raw.get("assumptions"))
    if assumptions is None:
        return None
    stamped = raw.get("assumption_set_id")
    if stamped != assumption_set_id([a["id"] for a in assumptions]):
        return None
    return {
        "kind": "conditional",
        "assumption_set_id": stamped,
        "assumptions": assumptions,
    }


def build_conditionality(
    assumptions: list[dict[str, str]] | None,
) -> dict[str, Any]:
    """The conditionality block for a record being written: stamp the
    assumption-set id from the assumptions themselves."""
    if not assumptions:
        return {"kind": "unconditional"}
    parsed = _parse_assumptions(assumptions)
    if parsed is None:
        raise ValueError("assumptions must be typed records {id, type, statement}")
    return {
        "kind": "conditional",
        "assumption_set_id": assumption_set_id([a["id"] for a in parsed]),
        "assumptions": parsed,
    }


# ---------------------------------------------------------------------------
# Effort representation (brief §2: the label follows from this, never text)
# ---------------------------------------------------------------------------


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _parse_effort(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return {"kind": "unknown"}
    if not isinstance(raw, dict):
        return None
    kind = raw.get("kind")
    if kind not in _EFFORT_KINDS:
        return None
    if kind == "unknown":
        return {"kind": "unknown"}
    if kind == "interval":
        low, high = raw.get("low_hours"), raw.get("high_hours")
        if not (_is_number(low) and _is_number(high)):
            return None
        if low < 0 or high < low:
            return None
        return {"kind": "interval", "low_hours": float(low), "high_hours": float(high)}
    hours = raw.get("hours")
    if not _is_number(hours) or hours < 0:
        return None
    return {"kind": kind, "hours": float(hours)}


def confidence_label(effort: dict[str, Any]) -> str:
    return CONFIDENCE_LABELS.get(str(effort.get("kind")), "unknown")


# ---------------------------------------------------------------------------
# Span records
# ---------------------------------------------------------------------------


def _snapshot(row: dict[str, Any]) -> dict[str, Any]:
    snap = row.get("final_values_snapshot")
    return snap if isinstance(snap, dict) else {}


def parse_span_record(row: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize one ``temporal_span_recorded`` decision row into a
    span record, or None when the row is malformed in any §2 property
    (a corrupt record degrades to no span, never to a broken fold)."""
    if row.get("decision_type") != SPAN_RECORDED:
        return None
    project_id = str(row.get("entity_id") or "")
    span_id = str(row.get("id") or "")
    if not project_id or not span_id:
        return None
    snap = _snapshot(row)
    origin = snap.get("origin")
    standing = snap.get("standing")
    role = snap.get("role")
    if origin not in ORIGINS or standing not in STANDINGS or role not in ROLES:
        return None
    start = valid_iso_datetime(snap.get("start")) if snap.get("start") is not None else None
    end = valid_iso_datetime(snap.get("end")) if snap.get("end") is not None else None
    if snap.get("start") is not None and start is None:
        return None
    if snap.get("end") is not None and end is None:
        return None
    if start is None and end is None:
        return None
    if role in POINT_ROLES:
        # A deadline/milestone with one bound is that moment.
        if start is None:
            start = end
        if end is None:
            end = start
    if start is not None and end is not None:
        if datetime.fromisoformat(end) < datetime.fromisoformat(start):
            return None
    conditionality = _parse_conditionality(snap.get("conditionality"))
    if conditionality is None:
        return None
    effort = _parse_effort(snap.get("effort"))
    if effort is None:
        return None
    basis_raw = snap.get("basis")
    basis = (
        [str(b) for b in basis_raw if isinstance(b, str)]
        if isinstance(basis_raw, list)
        else []
    )
    supersedes = snap.get("supersedes")
    return {
        "id": span_id,
        "project_id": project_id,
        "start": start,
        "end": end,
        "origin": origin,
        "standing": standing,
        "role": role,
        "conditionality": conditionality,
        "effort": effort,
        "confidence_label": confidence_label(effort),
        "basis": basis,
        "method": str(snap.get("method") or ""),
        "supersedes": supersedes if isinstance(supersedes, str) and supersedes else None,
        "note": str(snap.get("note") or ""),
        "recorded_at": row.get("created_at"),
    }


def parse_allocation_record(row: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize one ``temporal_allocation_recorded`` decision row, or
    None when malformed. ``week_start`` normalizes to the Monday of
    its ISO week — the series is bucketed by week, whatever day the
    recorder named."""
    if row.get("decision_type") != ALLOCATION_RECORDED:
        return None
    person_id = str(row.get("entity_id") or "")
    allocation_id = str(row.get("id") or "")
    if not person_id or not allocation_id:
        return None
    snap = _snapshot(row)
    week = valid_iso_datetime(snap.get("week_start"))
    hours = snap.get("hours")
    if week is None or not _is_number(hours) or hours < 0:
        return None
    day = datetime.fromisoformat(week).date()
    monday = day - timedelta(days=day.weekday())
    project_id = snap.get("project_id")
    return {
        "id": allocation_id,
        "person_id": person_id,
        "week_start": monday.isoformat(),
        "hours": float(hours),
        "project_id": project_id if isinstance(project_id, str) and project_id else None,
        "recorded_at": row.get("created_at"),
    }


# ---------------------------------------------------------------------------
# The fold
# ---------------------------------------------------------------------------


def fold_temporal_standing(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Fold decision rows into current temporal standing.

    ``rows`` are decision dicts in RECORDED order (oldest first), each
    carrying ``seq`` — its position in the owner's append-only decision
    stream (the rowid; see ``_decision_rows_for_fold``). Rows without a
    usable ``seq`` fall back to their list position. Non-temporal rows
    are ignored as records but still advance ``fold_seq``: the stamp
    names the whole stream the fold saw, so any new decision — a river,
    a hold, a span — moves it.

    Returns::

        {
          "fold_seq": int,                # seq of the last row folded
          "folded_decisions": int,
          "projects": {project_id: {
              "spans": [span, ...],                    # all roles
              "spans_by_role": {role: [span, ...]},    # the partition
          }},
          "allocations": {person_id: {
              "weeks": {week_start: {"established_hours": float,
                                     "entries": [allocation, ...]}},
          }},
          "allocation_series_version": int,   # == fold_seq
        }
    """
    spans: dict[str, dict[str, dict[str, Any]]] = {}  # project -> id -> span
    allocations: dict[str, dict[str, dict[str, Any]]] = {}  # person -> id -> alloc
    fold_seq = 0
    folded = 0
    for position, row in enumerate(rows):
        seq = row.get("seq")
        seq = seq if isinstance(seq, int) and seq > 0 else position + 1
        fold_seq = max(fold_seq, seq)
        folded += 1
        dtype = row.get("decision_type")
        if dtype == SPAN_RECORDED:
            span = parse_span_record(row)
            if span is None:
                continue
            project_spans = spans.setdefault(span["project_id"], {})
            if span["supersedes"]:
                project_spans.pop(span["supersedes"], None)
            project_spans[span["id"]] = span
        elif dtype == SPAN_WITHDRAWN:
            project_id = str(row.get("entity_id") or "")
            span_id = str(_snapshot(row).get("span_id") or "")
            if project_id and span_id:
                spans.get(project_id, {}).pop(span_id, None)
        elif dtype == ALLOCATION_RECORDED:
            alloc = parse_allocation_record(row)
            if alloc is None:
                continue
            allocations.setdefault(alloc["person_id"], {})[alloc["id"]] = alloc
        elif dtype == ALLOCATION_WITHDRAWN:
            person_id = str(row.get("entity_id") or "")
            allocation_id = str(_snapshot(row).get("allocation_id") or "")
            if person_id and allocation_id:
                allocations.get(person_id, {}).pop(allocation_id, None)

    projects_out: dict[str, Any] = {}
    for project_id, project_spans in spans.items():
        if not project_spans:
            continue
        ordered = sorted(
            project_spans.values(),
            key=lambda s: (s["start"] is None, s["start"] or "", s["role"], s["id"]),
        )
        by_role: dict[str, list[dict[str, Any]]] = {}
        for span in ordered:
            by_role.setdefault(span["role"], []).append(span)
        projects_out[project_id] = {"spans": ordered, "spans_by_role": by_role}

    allocations_out: dict[str, Any] = {}
    for person_id, person_allocs in allocations.items():
        if not person_allocs:
            continue
        weeks: dict[str, dict[str, Any]] = {}
        for alloc in sorted(
            person_allocs.values(), key=lambda a: (a["week_start"], a["id"])
        ):
            bucket = weeks.setdefault(
                alloc["week_start"], {"established_hours": 0.0, "entries": []}
            )
            bucket["established_hours"] = round(
                bucket["established_hours"] + alloc["hours"], 4
            )
            bucket["entries"].append(alloc)
        allocations_out[person_id] = {"weeks": weeks}

    return {
        "fold_seq": fold_seq,
        "folded_decisions": folded,
        "projects": projects_out,
        "allocations": allocations_out,
        "allocation_series_version": fold_seq,
    }


def _decision_rows_for_fold(
    user_id: str, at_fold_seq: int | None = None
) -> list[dict[str, Any]]:
    """The owner's decision rows in recorded order, each stamped with
    ``seq`` = its rowid. Decisions are append-only, so rowid order IS
    recorded order and the max rowid is a monotonic fold stamp — this
    is why the fold reads the table directly instead of through
    ``list_decisions`` (whose created_at ordering can tie)."""
    S._require_owner_id(user_id)
    conn = S.get_connection()
    sql = (
        "SELECT rowid, id, user_id, entity_type, entity_id, decision_type,"
        " ai_proposal_snapshot, final_values_snapshot, created_at"
        " FROM decisions WHERE user_id = ?"
    )
    params: list[Any] = [user_id]
    if at_fold_seq is not None:
        sql += " AND rowid <= ?"
        params.append(int(at_fold_seq))
    sql += " ORDER BY rowid ASC"
    cur = conn.execute(sql, params)
    rows: list[dict[str, Any]] = []
    for raw in cur.fetchall():
        row = M.row_to_decision(tuple(raw[1:]))
        row["seq"] = int(raw[0])
        rows.append(row)
    return rows


def derive_temporal_standing(
    user_id: str, at_fold_seq: int | None = None
) -> dict[str, Any]:
    """The caller's current temporal standing, folded from their own
    decision records — owner-scoped by the query itself, so another
    owner's records never fold in. ``at_fold_seq`` re-reads the fold
    as of an earlier stamp (time-travel within the stream)."""
    rows = _decision_rows_for_fold(user_id, at_fold_seq=at_fold_seq)
    return fold_temporal_standing(rows)


def current_fold_seq(user_id: str) -> int:
    """The owner's current fold stamp: the rowid of their latest
    decision of ANY type, or 0 when they have none."""
    S._require_owner_id(user_id)
    conn = S.get_connection()
    cur = conn.execute(
        "SELECT MAX(rowid) FROM decisions WHERE user_id = ?", (user_id,)
    )
    value = cur.fetchone()[0]
    return int(value) if value is not None else 0


# ---------------------------------------------------------------------------
# Recording (server-side writers; S1 builds the record path — the
# conversational and establishment callers arrive in later steps)
# ---------------------------------------------------------------------------


def _validate_span_payload(span: dict[str, Any]) -> dict[str, Any]:
    """Normalize a span payload for recording, raising ValueError on
    anything the fold itself would reject — a writer must not be able
    to record what the fold cannot carry."""
    if not isinstance(span, dict):
        raise ValueError("span must be a mapping")
    payload = dict(span)
    if "conditionality" not in payload or payload.get("conditionality") is None:
        payload["conditionality"] = build_conditionality(span.get("assumptions"))
    elif isinstance(payload.get("conditionality"), dict) and payload[
        "conditionality"
    ].get("kind") == "conditional" and "assumption_set_id" not in payload[
        "conditionality"
    ]:
        payload["conditionality"] = build_conditionality(
            payload["conditionality"].get("assumptions")
        )
    probe = {
        "id": "probe",
        "entity_id": "probe",
        "decision_type": SPAN_RECORDED,
        "final_values_snapshot": payload,
        "created_at": "",
    }
    if parse_span_record(probe) is None:
        raise ValueError("span record is malformed (see module docstring for the shape)")
    return payload


def record_span(
    user_id: str, project_id: str, span: dict[str, Any]
) -> dict[str, Any]:
    """Append one span record as a decision. Returns the created
    decision row; the span's id is that decision's id. Canonical
    project dates are never touched."""
    payload = _validate_span_payload(span)
    return S.create_decision(
        M.DecisionCreate(
            user_id=user_id,
            entity_type="project",
            entity_id=project_id,
            decision_type=SPAN_RECORDED,
            final_values_snapshot=payload,
        )
    )


def withdraw_span(user_id: str, project_id: str, span_id: str) -> dict[str, Any]:
    """Append a withdrawal for a span that stands in the caller's
    current fold for this project. Refuses (ValueError) a span that
    does not stand — a withdrawal of nothing is not recorded."""
    current = derive_temporal_standing(user_id)
    live = {
        s["id"] for s in current["projects"].get(project_id, {}).get("spans", [])
    }
    if span_id not in live:
        raise ValueError(f"span {span_id!r} does not stand for project {project_id!r}")
    return S.create_decision(
        M.DecisionCreate(
            user_id=user_id,
            entity_type="project",
            entity_id=project_id,
            decision_type=SPAN_WITHDRAWN,
            final_values_snapshot={"span_id": span_id},
        )
    )


def record_allocation(
    user_id: str,
    person_id: str,
    week_start: str,
    hours: float,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Append one established-allocation record (person-week bucket).
    The stored week is normalized to its Monday by the fold; the
    payload keeps the recorder's stated week."""
    payload: dict[str, Any] = {"week_start": week_start, "hours": hours}
    if project_id:
        payload["project_id"] = project_id
    probe = {
        "id": "probe",
        "entity_id": person_id,
        "decision_type": ALLOCATION_RECORDED,
        "final_values_snapshot": payload,
        "created_at": "",
    }
    if parse_allocation_record(probe) is None:
        raise ValueError("allocation record is malformed (week_start ISO, hours >= 0)")
    return S.create_decision(
        M.DecisionCreate(
            user_id=user_id,
            entity_type="person",
            entity_id=person_id,
            decision_type=ALLOCATION_RECORDED,
            final_values_snapshot=payload,
        )
    )


def withdraw_allocation(
    user_id: str, person_id: str, allocation_id: str
) -> dict[str, Any]:
    """Append a withdrawal for an allocation that stands in the
    caller's current series for this person."""
    current = derive_temporal_standing(user_id)
    live = {
        entry["id"]
        for bucket in current["allocations"].get(person_id, {}).get("weeks", {}).values()
        for entry in bucket["entries"]
    }
    if allocation_id not in live:
        raise ValueError(
            f"allocation {allocation_id!r} does not stand for person {person_id!r}"
        )
    return S.create_decision(
        M.DecisionCreate(
            user_id=user_id,
            entity_type="person",
            entity_id=person_id,
            decision_type=ALLOCATION_WITHDRAWN,
            final_values_snapshot={"allocation_id": allocation_id},
        )
    )
