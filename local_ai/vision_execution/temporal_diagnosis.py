"""Temporal diagnosis, arrangement, and establishment (slice S4).

Temporal Orchestration, slice step S4 (brief
``zenaf-temporal-orchestration-slice-brief-2026-11-28.md`` §§1, 6, 8,
9). This module carries the Tier 2 scenario end to end:

1. **Diagnosis assembly (read-side, §6).** A project's recorded
   reality — its tasks, estimates, dependencies, completion
   criteria — plus its gap inventory is assembled into a
   *proposal-class, versioned* diagnosis: goal → requirements →
   tasks, every node typed (origin, effort representation,
   confidence, assumption refs), with unresolved questions as named
   nodes carrying a directed discovery step and the nodes they gate.
   The diagnosis is a retained proposal (brief §1): persisted,
   editable, approvable — and possessed of no authority until
   established. It is NOT a decision and NOT canonical tasks.

2. **Arrangement (§§4, 6).** The S3 kernel runs over the assembled
   world (the owner's Ready/Active projects + the target, one
   person's capacity) and the result is attached to the proposal
   together with its **basis tuple** (brief §1): fold_seq,
   assumption_set_id, kernel_version, algo_settings_hash, an
   entity_version_vector over every record the computation touched,
   and a snapshot of the fold's temporal standing it consumed.
   Running the kernel writes nothing — simulation is not a durable
   decision (§1).

3. **Approval (§§1, 8).** Approval freezes the proposal version,
   the assumption set, the algorithm settings, and the basis, and is
   recorded as a VE decision (``temporal_approval``). A partial
   approval must be dependency-closed: a prerequisite outside the
   approved subset that is not already canonical record is marked
   **external-gated** — unschedulable, never silently satisfied.

4. **Establishment (§8).** The transactional core. Inside ONE
   write transaction: every basis-referenced entity is re-resolved
   at its current version and compared field by field (the
   tolerance whitelist is description/notes text only — every
   scheduling-relevant field is in the vector); the fold's temporal
   standing is re-derived and compared against the basis snapshot;
   the kernel version is checked; feasibility is recomputed under
   the frozen settings and compared against the frozen arrangement.
   Any non-tolerated drift ABORTS the whole establishment — nothing
   is written — and the offenders are enumerated (entity, field,
   from → to, failure class). When validation passes, writes go
   through the canonical paths only (``_insert_task`` — the shared
   writer behind ``create_task``/``approve_task_proposal`` — and
   ``update_task``), and establishment writes the task ``origin_*``
   provenance columns for the first time: origin_seat is the seat
   whose diagnosis this was, origin_decision_id is the approval
   decision's id. Outcomes are per-element with failure classes; a
   failed element never half-writes and never blocks honest
   reporting of the elements that succeeded. The outcome is
   recorded as a decision (``temporal_establishment_outcome``).
   Existing commitments are never modified: establishment writes
   only the target undertaking's own elements, its forecast span,
   and its allocation records.

Decision inserts inside the establishment transaction mirror
``storage.create_decision``'s INSERT exactly: that function's raw
``conn.commit()`` makes it unusable inside a caller-owned
transaction (it would commit the establishment mid-flight), so the
in-transaction writer below performs the same insert without the
commit, under the transaction owner's discipline — the same reason
``_insert_task`` exists beside ``create_task``.

Fold-seq currency (§8) is verified over the fold's temporal
*content* (span set + allocation series) plus the entity vector —
the two guards brief §1 names — rather than by raw fold_seq
equality: the approval decision itself is a decision written after
the basis was computed, so raw equality would abort every
establishment on its own approval. The current fold_seq is still
reported with every outcome.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from typing import Any

from local_ai.vision_execution import models as M
from local_ai.vision_execution import storage as S
from local_ai.vision_execution import temporal_kernel as K
from local_ai.vision_execution import temporal_standing as T

# Decision types for the arrangement lifecycle family (brief §1).
APPROVAL = "temporal_approval"
ESTABLISHMENT_OUTCOME = "temporal_establishment_outcome"
REVISION = "temporal_revision"
WITHDRAWAL = "temporal_withdrawal"

#: The seat whose diagnosis scenario 1 is (brief §6: Valen, the
#: champion). Diagnosis records carry it as their origin seat.
DIAGNOSIS_SEAT = "champion"

_PROPOSAL_STATES = (
    "pending",
    "approved",
    "established",
    "partially_established",
    "superseded",
    "withdrawn",
)

#: Scheduling-relevant fields per entity type — the entity version
#: vector's content. Anything NOT listed here (description, notes,
#: and other free text) is the brief §1 tolerance whitelist: a
#: change there never aborts an establishment. Identity fields
#: (title) are listed, so they are never cosmetic.
_TASK_VECTOR_FIELDS = (
    "title",
    "project_id",
    "parent_task_id",
    "status",
    "priority",
    "estimated_hours",
    "due_date",
    "dependency_ids",
    "completion_criteria",
    "timeframe_commitment",
    "assignee_id",
)
_PROJECT_VECTOR_FIELDS = (
    "title",
    "status",
    "owner_id",
    "supporting_owner_ids",
    "priority",
    "estimated_weekly_hours",
    "start_date",
    "end_date",
)
_CAPACITY_VECTOR_FIELDS = ("weekly_capacity_hours",)


class DiagnosisNotFound(Exception):
    """Diagnosis proposal missing or foreign. Fail-closed, like
    ProposalNotFound: existence is never confirmed to a non-owner."""


class DiagnosisConflict(Exception):
    """The proposal is in a state that refuses the requested
    transition (edit of an established version, approval of an
    already-decided proposal, establishment without approval)."""


# ---------------------------------------------------------------------------
# The proposal store (proposal-class records; brief §1, §6)
# ---------------------------------------------------------------------------


def _ensure_table(conn) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS diagnosis_proposals (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          project_id TEXT NOT NULL,
          version INTEGER NOT NULL,
          supersedes_id TEXT,
          state TEXT NOT NULL DEFAULT 'pending',
          diagnosis TEXT NOT NULL,
          arrangement TEXT,
          basis TEXT,
          approved_subset TEXT,
          external_gates TEXT,
          establishment TEXT,
          approval_decision_id TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          decided_at TEXT,
          UNIQUE(user_id, project_id, version)
        )"""
    )
    # The table is created by this module (above); a database made
    # by an earlier build of this same step gets the column by
    # PRAGMA-checked ALTER, never a backfill.
    cols = {
        r[1] for r in conn.execute("PRAGMA table_info(diagnosis_proposals)")
    }
    if "approval_decision_id" not in cols:
        conn.execute(
            "ALTER TABLE diagnosis_proposals ADD COLUMN approval_decision_id TEXT"
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_diagnosis_proposals_user_project "
        "ON diagnosis_proposals (user_id, project_id, version)"
    )


_PROPOSAL_COLUMNS = (
    "id, user_id, project_id, version, supersedes_id, state, diagnosis, "
    "arrangement, basis, approved_subset, external_gates, establishment, "
    "created_at, updated_at, decided_at, approval_decision_id"
)


def _json_loads(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _row_to_proposal(row: tuple) -> dict[str, Any]:
    return {
        "id": row[0],
        "user_id": row[1],
        "project_id": row[2],
        "version": row[3],
        "supersedes_id": row[4],
        "state": row[5],
        "diagnosis": _json_loads(row[6]) or {},
        "arrangement": _json_loads(row[7]),
        "basis": _json_loads(row[8]),
        "approved_subset": _json_loads(row[9]),
        "external_gates": _json_loads(row[10]) or [],
        "establishment": _json_loads(row[11]),
        "created_at": row[12],
        "updated_at": row[13],
        "decided_at": row[14],
        "approval_decision_id": row[15] if len(row) > 15 else None,
    }


def _get_proposal_row(conn, proposal_id: str, user_id: str):
    return conn.execute(
        "SELECT " + _PROPOSAL_COLUMNS + " FROM diagnosis_proposals "
        "WHERE id = ? AND user_id = ?",
        (proposal_id, user_id),
    ).fetchone()


def get_diagnosis_proposal(user_id: str, proposal_id: str) -> dict[str, Any] | None:
    """One diagnosis proposal, strictly per-owner (fail-closed)."""
    S._require_owner_id(user_id)
    conn = S.get_connection()
    _ensure_table(conn)
    row = _get_proposal_row(conn, proposal_id, user_id)
    return _row_to_proposal(tuple(row)) if row else None


def _require_proposal(user_id: str, proposal_id: str) -> dict[str, Any]:
    proposal = get_diagnosis_proposal(user_id, proposal_id)
    if proposal is None:
        raise DiagnosisNotFound("Diagnosis proposal not found")
    return proposal


def list_diagnosis_proposals(
    user_id: str, project_id: str
) -> list[dict[str, Any]]:
    """All versions of the diagnosis for one project, oldest first."""
    S._require_owner_id(user_id)
    conn = S.get_connection()
    _ensure_table(conn)
    cur = conn.execute(
        "SELECT " + _PROPOSAL_COLUMNS + " FROM diagnosis_proposals "
        "WHERE user_id = ? AND project_id = ? ORDER BY version ASC",
        (user_id, project_id),
    )
    return [_row_to_proposal(tuple(r)) for r in cur.fetchall()]


def latest_diagnosis_proposal(
    user_id: str, project_id: str
) -> dict[str, Any] | None:
    """The newest version of the project's diagnosis, any state —
    the read the seat carriage (S4 §3) renders."""
    proposals = list_diagnosis_proposals(user_id, project_id)
    return proposals[-1] if proposals else None


def _next_version(conn, user_id: str, project_id: str) -> int:
    row = conn.execute(
        "SELECT MAX(version) FROM diagnosis_proposals "
        "WHERE user_id = ? AND project_id = ?",
        (user_id, project_id),
    ).fetchone()
    return int(row[0] or 0) + 1


def _insert_proposal(
    conn,
    *,
    user_id: str,
    project_id: str,
    version: int,
    supersedes_id: str | None,
    diagnosis: dict[str, Any],
) -> str:
    pid = M.new_id()
    now = S._now()
    conn.execute(
        "INSERT INTO diagnosis_proposals ("
        "id, user_id, project_id, version, supersedes_id, state, diagnosis, "
        "arrangement, basis, approved_subset, external_gates, establishment, "
        "created_at, updated_at, decided_at"
        ") VALUES (?, ?, ?, ?, ?, 'pending', ?, NULL, NULL, NULL, '[]', NULL, ?, ?, NULL)",
        (
            pid,
            user_id,
            project_id,
            version,
            supersedes_id,
            json.dumps(diagnosis),
            now,
            now,
        ),
    )
    return pid


def _create_next_version(
    user_id: str,
    project_id: str,
    diagnosis: dict[str, Any],
    *,
    supersedes_id: str | None,
) -> dict[str, Any]:
    """Insert the next version as pending and mark the superseded
    row (when given) — the version discipline of brief §1: edits
    never mutate a version in place."""
    conn = S.get_connection()
    _ensure_table(conn)
    with S.ve_write_transaction(conn, purpose="diagnosis_new_version"):
        version = _next_version(conn, user_id, project_id)
        pid = _insert_proposal(
            conn,
            user_id=user_id,
            project_id=project_id,
            version=version,
            supersedes_id=supersedes_id,
            diagnosis=diagnosis,
        )
        if supersedes_id:
            conn.execute(
                "UPDATE diagnosis_proposals SET state = 'superseded', "
                "updated_at = ? WHERE id = ? AND user_id = ? "
                "AND state IN ('pending', 'approved', 'partially_established')",
                (S._now(), supersedes_id, user_id),
            )
        S._commit_if_owner(conn)
    return _require_proposal(user_id, pid)


# ---------------------------------------------------------------------------
# Diagnosis assembly (brief §6, scenario 1: from the record)
# ---------------------------------------------------------------------------


def _effort_label(effort: dict[str, Any]) -> str:
    return T.confidence_label(effort)


def _question(qid: str, question: str, discovery: str, gates: list[str]) -> dict:
    return {
        "id": qid,
        "question": question,
        "discovery": discovery,
        "gates": gates,
        "origin": "derived",
    }


def assemble_diagnosis(user_id: str, project_id: str) -> dict[str, Any]:
    """Assemble a diagnosis for one project from the owner's VE
    records and persist it as the next pending proposal version.

    Read-side only against the canonical record: assembly creates a
    PROPOSAL, never canonical tasks and never a decision (brief §1).
    A prior pending/approved version is superseded by the new one.
    """
    S._require_owner_id(user_id)
    project = S.get_project(project_id, user_id)
    if project is None:
        raise DiagnosisNotFound("Project not found")
    tasks = S.list_tasks(user_id, project_id=project_id)
    person_id = project.get("owner_id") or None

    by_id = {str(t["id"]): t for t in tasks}
    children: dict[str, list[dict]] = {}
    top_level: list[dict] = []
    for t in tasks:
        parent = t.get("parent_task_id")
        if parent and str(parent) in by_id:
            children.setdefault(str(parent), []).append(t)
        else:
            top_level.append(t)

    questions: list[dict[str, Any]] = []
    requirements: list[dict[str, Any]] = []
    task_nodes: list[dict[str, Any]] = []

    def task_node(t: dict, requirement_id: str) -> dict[str, Any]:
        effort = K.effort_from_hours(t.get("estimated_hours"))
        node = {
            "id": f"task:{t['id']}",
            "ref_task_id": str(t["id"]),
            "requirement_id": requirement_id,
            "title": t.get("title") or "",
            "origin": "visitor-recorded",
            "effort": effort,
            "confidence_label": _effort_label(effort),
            "dependencies": [str(d) for d in (t.get("dependency_ids") or [])],
            "status": t.get("status") or "",
            "priority": t.get("priority") or "",
            "due_date": t.get("due_date"),
            "timeframe_commitment": t.get("timeframe_commitment"),
            "completion_criteria": t.get("completion_criteria") or "",
            "assumption_refs": [],
        }
        if effort["kind"] == "unknown":
            questions.append(
                _question(
                    f"q:estimate:{t['id']}",
                    f"No effort estimate is recorded for '{node['title']}'.",
                    "Estimate the work, or bound it — an unknown effort "
                    "makes every finish that depends on it unknown.",
                    [node["id"]],
                )
            )
        if not node["completion_criteria"]:
            questions.append(
                _question(
                    f"q:criteria:{t['id']}",
                    f"No completion criteria are recorded for '{node['title']}'.",
                    "Name what would count as this being done.",
                    [node["id"]],
                )
            )
        if node["due_date"] and not node["timeframe_commitment"]:
            questions.append(
                _question(
                    f"q:standing:{t['id']}",
                    f"'{node['title']}' carries a due date "
                    f"({node['due_date']}) with no recorded standing.",
                    "Decide whether that date is a firm commitment or "
                    "tentative — a due date is a record, not a promise.",
                    [node["id"]],
                )
            )
        return node

    for t in top_level:
        requirement_id = f"req:{t['id']}"
        effort = K.effort_from_hours(t.get("estimated_hours"))
        node_ids: list[str] = []
        own = task_node(t, requirement_id)
        task_nodes.append(own)
        node_ids.append(own["id"])
        for child in children.get(str(t["id"]), []):
            child_node = task_node(child, requirement_id)
            task_nodes.append(child_node)
            node_ids.append(child_node["id"])
        requirements.append(
            {
                "id": requirement_id,
                "ref_task_id": str(t["id"]),
                "title": t.get("title") or "",
                "acceptance_criteria": t.get("completion_criteria") or "",
                "origin": "visitor-recorded",
                "effort": effort,
                "confidence_label": _effort_label(effort),
                "dependencies": [str(d) for d in (t.get("dependency_ids") or [])],
                "unlock": "task",
                "task_node_ids": node_ids,
                "assumption_refs": [],
            }
        )

    if person_id is None:
        questions.append(
            _question(
                "q:capacity",
                "The project has no recorded owner, so no capacity "
                "profile can be read for it.",
                "Name the person whose capacity this undertaking "
                "draws on.",
                [n["id"] for n in task_nodes],
            )
        )
    elif S.get_capacity_profile(str(person_id), user_id) is None:
        questions.append(
            _question(
                "q:capacity",
                "No capacity profile is recorded for the project's owner.",
                "Record the owner's weekly capacity — without it no "
                "arrangement can be computed.",
                [n["id"] for n in task_nodes],
            )
        )

    gap_inventory = _gap_inventory(user_id, project, tasks)
    if gap_inventory:
        for gap in gap_inventory["questions"]:
            questions.append(gap)

    diagnosis: dict[str, Any] = {
        "kind": "temporal_diagnosis",
        "project_id": project_id,
        "person_id": person_id,
        "seat": DIAGNOSIS_SEAT,
        "goal": {
            "title": project.get("title") or "",
            "brief": project.get("brief") or "",
            "origin": "visitor-recorded",
        },
        "requirements": requirements,
        "tasks": task_nodes,
        "unresolved_questions": questions,
        "assumptions": [
            {
                "id": "recorded-capacity-holds",
                "type": "capacity",
                "statement": "The owner's recorded weekly capacity "
                "holds uninterrupted over the arranged window.",
            }
        ],
    }
    if gap_inventory:
        diagnosis["gap_inventory_text"] = gap_inventory["text"]

    prior = latest_diagnosis_proposal(user_id, project_id)
    supersedes = (
        prior["id"]
        if prior
        and prior["state"] in ("pending", "approved", "partially_established")
        else None
    )
    return _create_next_version(
        user_id, project_id, diagnosis, supersedes_id=supersedes
    )


def _gap_inventory(
    user_id: str, project: dict[str, Any], tasks: list[dict]
) -> dict[str, Any] | None:
    """The completeness/gap inventory, where it fits (brief §6):
    when the project hangs under an initiative, the initiative
    completeness machinery's own block rides as seat-facing text,
    and the blank core fields it checks become structured
    unresolved questions. Project-level gaps are computed in
    ``assemble_diagnosis`` itself."""
    initiative_id = project.get("initiative_id")
    if not initiative_id:
        return None
    initiative = S.get_initiative(str(initiative_id), user_id)
    if initiative is None:
        return None
    questions: list[dict[str, Any]] = []
    for field, label in (
        ("owner_id", "owner"),
        ("brief", "brief"),
        ("dependencies", "dependencies"),
        ("risks", "risks"),
        ("kill_criteria", "kill criteria"),
    ):
        if not str(initiative.get(field) or "").strip():
            questions.append(
                _question(
                    f"q:initiative:{field}",
                    f"The initiative '{initiative.get('title') or ''}' "
                    f"has no recorded {label}.",
                    f"Record the initiative's {label}, or confirm it "
                    "is genuinely unsettled.",
                    [],
                )
            )
    text = ""
    try:
        from local_ai.vision_execution.initiative_completeness import (
            build_initiative_completeness_block,
        )

        initiative_tasks = S.list_tasks(user_id, initiative_id=str(initiative_id))
        text = build_initiative_completeness_block(
            initiative,
            user_id=user_id,
            execution_step_count=len(initiative_tasks),
        )
    except Exception:
        text = ""
    return {"questions": questions, "text": text}


# ---------------------------------------------------------------------------
# Editing — a correction is a new version (brief §§1, 6)
# ---------------------------------------------------------------------------

_EDITABLE_NODE_FIELDS = (
    "title",
    "effort",
    "dependencies",
    "due_date",
    "timeframe_commitment",
    "priority",
    "completion_criteria",
)


def edit_diagnosis_proposal(
    user_id: str, proposal_id: str, patch: dict[str, Any]
) -> dict[str, Any]:
    """Apply a correction as a NEW proposal version.

    ``patch`` shape::

        {
          "tasks": {"<node id>": {"effort": {...}, "title": "...", ...}},
          "add_tasks": [{"id": "task:prop:<name>", "title": ...,
                         "effort": {...}, "dependencies": [...]}],
          "remove_tasks": ["<node id>", ...],
          "questions_resolved": ["<question id>", ...]
        }

    The edited row is superseded; the new version is pending and —
    when the old one was approved — needs fresh approval before
    anything establishes (the freeze rule, brief §1). A partially
    established diagnosis is correctable the same way (brief §8: a
    failed element leaves the proposal revisable; its established
    elements stay established and are carried in the record).
    Fully established versions are immutable history and refuse
    edits outright.
    """
    proposal = _require_proposal(user_id, proposal_id)
    if proposal["state"] not in ("pending", "approved", "partially_established"):
        raise DiagnosisConflict(
            f"Proposal is {proposal['state']}; only a pending, "
            "approved, or partially established diagnosis can be "
            "corrected into a new version"
        )
    import copy

    diagnosis = copy.deepcopy(proposal["diagnosis"])
    nodes = {n["id"]: n for n in diagnosis.get("tasks", [])}

    for node_id in patch.get("remove_tasks") or []:
        nodes.pop(node_id, None)
    for node_id, fields in (patch.get("tasks") or {}).items():
        node = nodes.get(node_id)
        if node is None:
            raise DiagnosisNotFound(f"Task node {node_id!r} not in diagnosis")
        for key in _EDITABLE_NODE_FIELDS:
            if key in fields:
                node[key] = fields[key]
        if "effort" in fields:
            node["confidence_label"] = _effort_label(node["effort"])
    for raw in patch.get("add_tasks") or []:
        node_id = str(raw.get("id") or "")
        if not node_id.startswith("task:prop:"):
            raise ValueError(
                "proposed task nodes need a namespaced id (task:prop:...)"
            )
        if node_id in nodes:
            raise DiagnosisConflict(f"Task node {node_id!r} already exists")
        effort = raw.get("effort") or {"kind": "unknown"}
        nodes[node_id] = {
            "id": node_id,
            "ref_task_id": None,
            "requirement_id": raw.get("requirement_id"),
            "title": str(raw.get("title") or ""),
            "origin": "proposed",
            "effort": effort,
            "confidence_label": _effort_label(effort),
            "dependencies": [str(d) for d in (raw.get("dependencies") or [])],
            "status": "Todo",
            "priority": raw.get("priority") or "",
            "due_date": raw.get("due_date"),
            "timeframe_commitment": raw.get("timeframe_commitment"),
            "completion_criteria": raw.get("completion_criteria") or "",
            "assumption_refs": [],
        }
    diagnosis["tasks"] = list(nodes.values())
    resolved = set(patch.get("questions_resolved") or [])
    if resolved:
        diagnosis["unresolved_questions"] = [
            q
            for q in diagnosis.get("unresolved_questions", [])
            if q["id"] not in resolved
        ]
    new_proposal = _create_next_version(
        user_id,
        proposal["project_id"],
        diagnosis,
        supersedes_id=proposal["id"],
    )
    if proposal["state"] in ("approved", "partially_established"):
        # Correcting an APPROVED diagnosis is a revision event in
        # the lifecycle family (brief §1): the approval it supersedes
        # stays in the record, and the new version needs fresh
        # approval before anything establishes.
        S.create_decision(
            M.DecisionCreate(
                user_id=user_id,
                entity_type="project",
                entity_id=proposal["project_id"],
                decision_type=REVISION,
                final_values_snapshot={
                    "from_proposal_id": proposal["id"],
                    "from_version": proposal["version"],
                    "to_proposal_id": new_proposal["id"],
                    "to_version": new_proposal["version"],
                },
            )
        )
    return new_proposal


# ---------------------------------------------------------------------------
# The assembled world + basis (brief §§1, 4)
# ---------------------------------------------------------------------------


def _vector_for(
    fields: tuple[str, ...], row: dict[str, Any] | None
) -> dict[str, Any] | None:
    if row is None:
        return None
    out: dict[str, Any] = {}
    for f in fields:
        v = row.get(f)
        if isinstance(v, (list, dict)):
            v = json.loads(json.dumps(v))
        out[f] = v
    return out


def _span_fingerprint(span: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(span, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _assemble_world(
    user_id: str, diagnosis: dict[str, Any]
) -> dict[str, Any]:
    """Assemble the kernel inputs + basis material from the record.

    The world is the owner's Ready/Active projects (brief §11 S4:
    the capacity machinery's committed set) plus the target. Target
    tasks come from the DIAGNOSIS nodes (the proposal may carry
    corrected estimates); every other project's tasks come from the
    record. Returns the kernel kwargs, the entity version vector,
    and the fold snapshot the computation consumed.
    """
    project_id = diagnosis["project_id"]
    person_id = diagnosis.get("person_id")
    if not person_id:
        raise ValueError(
            "Diagnosis has no person: the target project has no "
            "recorded owner, so no capacity can be read (see the "
            "diagnosis's unresolved questions)."
        )
    profile = S.get_capacity_profile(str(person_id), user_id)
    if profile is None:
        raise ValueError(
            "No capacity profile is recorded for the project's "
            "owner; an arrangement cannot be computed."
        )
    capacity = float(profile.get("weekly_capacity_hours") or 0)
    if capacity <= 0:
        raise ValueError("The owner's recorded weekly capacity is not positive.")

    projects = S.list_projects(user_id)
    by_project: dict[str, dict] = {str(p["id"]): p for p in projects}
    target_project = by_project.get(project_id)
    if target_project is None:
        raise DiagnosisNotFound("Project not found")

    vector: dict[str, dict[str, Any]] = {}
    vector[f"capacity:{person_id}"] = _vector_for(
        _CAPACITY_VECTOR_FIELDS, profile
    ) or {}
    vector[f"project:{project_id}"] = _vector_for(
        _PROJECT_VECTOR_FIELDS, target_project
    ) or {}

    world_tasks: list[dict[str, Any]] = []
    for p in projects:
        pid = str(p["id"])
        if pid == project_id:
            continue
        if p.get("owner_id") != person_id:
            continue
        if (p.get("status") or "") not in ("Ready", "Active"):
            continue
        vector[f"project:{pid}"] = _vector_for(_PROJECT_VECTOR_FIELDS, p) or {}
        for t in S.list_tasks(user_id, project_id=pid):
            vector[f"task:{t['id']}"] = _vector_for(_TASK_VECTOR_FIELDS, t) or {}
            world_tasks.append(
                {
                    "id": str(t["id"]),
                    "project_id": pid,
                    "effort": K.effort_from_hours(t.get("estimated_hours")),
                    "dependencies": [
                        str(d) for d in (t.get("dependency_ids") or [])
                    ],
                    "timeframe_commitment": t.get("timeframe_commitment"),
                    "due_date": t.get("due_date"),
                    "priority": t.get("priority") or "",
                    "status": t.get("status") or "",
                }
            )

    # Target tasks: recorded ones enter the world under their
    # diagnosis nodes (corrected values win); proposed ones enter
    # as the scenario layer under their namespaced node ids.
    target_tasks: list[dict[str, Any]] = []
    scenario_tasks: list[dict[str, Any]] = []
    recorded_target = S.list_tasks(user_id, project_id=project_id)
    for t in recorded_target:
        vector[f"task:{t['id']}"] = _vector_for(_TASK_VECTOR_FIELDS, t) or {}
    for node in diagnosis.get("tasks", []):
        entry = {
            "id": node["id"] if not node.get("ref_task_id") else str(node["ref_task_id"]),
            "project_id": project_id,
            "effort": node.get("effort") or {"kind": "unknown"},
            "dependencies": [str(d) for d in (node.get("dependencies") or [])],
            "timeframe_commitment": node.get("timeframe_commitment"),
            "due_date": node.get("due_date"),
            "priority": node.get("priority") or "",
            "status": node.get("status") or "",
        }
        if node.get("ref_task_id"):
            target_tasks.append(entry)
        else:
            scenario_tasks.append(entry)

    fold = T.derive_temporal_standing(user_id)
    person_series = fold["allocations"].get(str(person_id))
    windows: list[dict[str, Any]] = []
    span_fingerprints: dict[str, str] = {}
    involved = set(by_project)  # all of the owner's projects
    for pid, pdata in fold["projects"].items():
        for span in pdata.get("spans", []):
            span_fingerprints[span["id"]] = _span_fingerprint(span)
            if pid not in involved:
                continue
            if span["role"] == "deadline" and span.get("end"):
                windows.append(
                    {
                        "kind": "deadline",
                        "project_id": pid,
                        "due_date": span["end"][:10],
                    }
                )
            elif span["role"] == "hold" and span.get("start") and span.get("end"):
                hold: dict[str, Any] = {
                    "kind": "hold",
                    "start_date": span["start"][:10],
                    "end_date": span["end"][:10],
                }
                if span["effort"].get("kind") == "exact":
                    hold["hours"] = span["effort"]["hours"]
                windows.append(hold)

    allocation_snapshot: dict[str, float] = {}
    if person_series:
        for week, bucket in person_series["weeks"].items():
            allocation_snapshot[week] = bucket["established_hours"]

    return {
        "kernel_kwargs": {
            "tasks": world_tasks + target_tasks,
            "scenario_tasks": scenario_tasks,
            "capacity_hours_per_week": capacity,
            "target_project_id": project_id,
            "established_allocations": person_series or None,
            "windows": windows,
            "fold_seq": fold["fold_seq"],
            "assumption_set_id": T.assumption_set_id(
                [a["id"] for a in diagnosis.get("assumptions", [])]
            ),
        },
        "vector": vector,
        "temporal_snapshot": {
            "spans": span_fingerprints,
            "allocations": {str(person_id): allocation_snapshot},
            "allocation_series_version": fold["allocation_series_version"],
        },
        "fold_seq": fold["fold_seq"],
        "person_id": str(person_id),
        "capacity": capacity,
    }


def compute_diagnosis_arrangement(
    user_id: str,
    proposal_id: str,
    *,
    start_week: str | None = None,
    horizon_weeks: int = 104,
    target_advances: bool = True,
) -> dict[str, Any]:
    """Run the S3 kernel over the assembled world and attach the
    arrangement + basis tuple to the (pending) proposal.

    Pure with respect to the durable record: the kernel computes,
    the proposal retains. No decision is written, no canonical
    record changes (brief §1 — simulation is not a decision).
    """
    proposal = _require_proposal(user_id, proposal_id)
    if proposal["state"] != "pending":
        raise DiagnosisConflict(
            f"Proposal is {proposal['state']}; arrangements attach "
            "to a pending diagnosis (an approved one is frozen)"
        )
    diagnosis = proposal["diagnosis"]
    world = _assemble_world(user_id, diagnosis)
    if start_week is None:
        today = date.fromisoformat(S._now()[:10])
        start_week = (today - timedelta(days=today.weekday())).isoformat()
    result = K.compute_arrangement(
        start_week=start_week,
        horizon_weeks=horizon_weeks,
        target_advances=target_advances,
        **world["kernel_kwargs"],
    )
    labels = result.get("labels") or {}
    basis = {
        "fold_seq": world["fold_seq"],
        "assumption_set_id": world["kernel_kwargs"]["assumption_set_id"],
        "kernel_version": K.KERNEL_VERSION,
        "algo_settings_hash": labels.get("algo_settings_hash"),
        "entity_version_vector": world["vector"],
        "temporal_snapshot": world["temporal_snapshot"],
        "target_project_id": diagnosis["project_id"],
        "person_id": world["person_id"],
        "target_task_ids": sorted(_target_task_ids(diagnosis)),
        "start_week": labels.get("start_week") or start_week,
        "horizon_weeks": horizon_weeks,
        "target_advances": target_advances,
    }
    conn = S.get_connection()
    _ensure_table(conn)
    with S.ve_write_transaction(conn, purpose="diagnosis_attach_arrangement"):
        conn.execute(
            "UPDATE diagnosis_proposals SET arrangement = ?, basis = ?, "
            "updated_at = ? WHERE id = ? AND user_id = ? AND state = 'pending'",
            (
                json.dumps(result),
                json.dumps(basis),
                S._now(),
                proposal_id,
                user_id,
            ),
        )
        S._commit_if_owner(conn)
    return _require_proposal(user_id, proposal_id)


# ---------------------------------------------------------------------------
# Approval — the freeze (brief §§1, 8)
# ---------------------------------------------------------------------------


def _resolve_dependency(user_id: str, diagnosis: dict, dep: str):
    """Resolve one dependency reference against the diagnosis and
    the canonical record. Returns (kind, value): ("node", node) for
    a diagnosis task node, ("task", task_id) for a canonical task,
    ("project", project_id) for an undertaking gate, or
    ("missing", None)."""
    nodes = diagnosis.get("tasks", [])
    by_node_id = {n["id"]: n for n in nodes}
    if dep in by_node_id:
        return ("node", by_node_id[dep])
    ref = dep[5:] if dep.startswith("task:") else dep
    for n in nodes:
        if n.get("ref_task_id") and str(n["ref_task_id"]) == ref:
            return ("node", n)
    if S.get_task(ref, user_id) is not None:
        return ("task", ref)
    if S.get_project(ref, user_id) is not None:
        return ("project", ref)
    return ("missing", None)


def approve_diagnosis_proposal(
    user_id: str,
    proposal_id: str,
    subset: list[str] | None = None,
) -> dict[str, Any]:
    """Approve a pending diagnosis + arrangement, freezing the
    proposal version, assumption set, algorithm settings, and basis
    (brief §1). The approval is a VE decision; the frozen basis
    rides in its final snapshot.

    ``subset`` approves only the named task nodes (a partial
    approval). Closure: a prerequisite of an approved node that is
    neither in the subset nor already canonical record is marked
    external-gated — the dependent node is approved but
    unschedulable, and establishment will refuse it rather than
    treat the gate as satisfied.
    """
    proposal = _require_proposal(user_id, proposal_id)
    if proposal["state"] != "pending":
        raise DiagnosisConflict(
            f"Proposal is {proposal['state']}; only a pending "
            "diagnosis can be approved"
        )
    if not proposal["arrangement"] or not proposal["basis"]:
        raise DiagnosisConflict(
            "No arrangement has been computed for this diagnosis; "
            "there is nothing to freeze or establish"
        )
    diagnosis = proposal["diagnosis"]
    nodes = {n["id"]: n for n in diagnosis.get("tasks", [])}
    approved = list(subset) if subset is not None else list(nodes)
    for node_id in approved:
        if node_id not in nodes:
            raise DiagnosisNotFound(f"Task node {node_id!r} not in diagnosis")

    gates: list[dict[str, Any]] = []
    for node_id in approved:
        for dep in nodes[node_id].get("dependencies") or []:
            kind, value = _resolve_dependency(user_id, diagnosis, str(dep))
            if kind == "node" and value["id"] not in approved:
                gates.append(
                    {
                        "node_id": node_id,
                        "gated_by": str(dep),
                        "gated_by_node_id": value["id"],
                        "reason": "prerequisite proposed but not approved",
                    }
                )
            elif kind == "missing":
                gates.append(
                    {
                        "node_id": node_id,
                        "gated_by": str(dep),
                        "gated_by_node_id": None,
                        "reason": "prerequisite does not exist in the record",
                    }
                )

    decision = S.create_decision(
        M.DecisionCreate(
            user_id=user_id,
            entity_type="project",
            entity_id=proposal["project_id"],
            decision_type=APPROVAL,
            ai_proposal_snapshot={
                "proposal_id": proposal_id,
                "version": proposal["version"],
                "diagnosis_kind": diagnosis.get("kind"),
                "task_nodes": len(nodes),
                "unresolved_questions": len(
                    diagnosis.get("unresolved_questions", [])
                ),
            },
            final_values_snapshot={
                "proposal_id": proposal_id,
                "version": proposal["version"],
                "approved_subset": approved,
                "external_gates": gates,
                "basis": proposal["basis"],
            },
        )
    )
    conn = S.get_connection()
    _ensure_table(conn)
    with S.ve_write_transaction(conn, purpose="diagnosis_approve"):
        conn.execute(
            "UPDATE diagnosis_proposals SET state = 'approved', "
            "approved_subset = ?, external_gates = ?, "
            "approval_decision_id = ?, decided_at = ?, updated_at = ? "
            "WHERE id = ? AND user_id = ? AND state = 'pending'",
            (
                json.dumps(approved),
                json.dumps(gates),
                decision["id"],
                S._now(),
                S._now(),
                proposal_id,
                user_id,
            ),
        )
        S._commit_if_owner(conn)
    return {
        "proposal": _require_proposal(user_id, proposal_id),
        "decision": decision,
        "external_gates": gates,
    }


def withdraw_diagnosis_proposal(
    user_id: str, proposal_id: str
) -> dict[str, Any]:
    """Withdraw a pending or approved diagnosis (a decision; the
    proposal row records the terminal state)."""
    proposal = _require_proposal(user_id, proposal_id)
    if proposal["state"] not in ("pending", "approved"):
        raise DiagnosisConflict(
            f"Proposal is {proposal['state']}; it cannot be withdrawn"
        )
    decision = S.create_decision(
        M.DecisionCreate(
            user_id=user_id,
            entity_type="project",
            entity_id=proposal["project_id"],
            decision_type=WITHDRAWAL,
            final_values_snapshot={
                "proposal_id": proposal_id,
                "version": proposal["version"],
                "from_state": proposal["state"],
            },
        )
    )
    conn = S.get_connection()
    _ensure_table(conn)
    with S.ve_write_transaction(conn, purpose="diagnosis_withdraw"):
        conn.execute(
            "UPDATE diagnosis_proposals SET state = 'withdrawn', "
            "decided_at = ?, updated_at = ? WHERE id = ? AND user_id = ?",
            (S._now(), S._now(), proposal_id, user_id),
        )
        S._commit_if_owner(conn)
    return {"proposal": _require_proposal(user_id, proposal_id), "decision": decision}


# ---------------------------------------------------------------------------
# Establishment — the transactional core (brief §8)
# ---------------------------------------------------------------------------


class _EstablishmentAbort(Exception):
    """Internal: non-tolerated drift. Carries the offender list;
    raising it inside the establishment transaction rolls every
    write back — an aborted establishment writes nothing."""

    def __init__(self, offenders: list[dict[str, Any]]):
        super().__init__("establishment aborted: non-tolerated drift")
        self.offenders = offenders


def _insert_decision_in_txn(
    conn,
    *,
    user_id: str,
    entity_type: str,
    entity_id: str,
    decision_type: str,
    ai_proposal_snapshot: Any = None,
    final_values_snapshot: Any = None,
) -> str:
    """Insert a decision row inside a caller-owned transaction.
    Mirrors ``storage.create_decision``'s INSERT exactly, minus its
    commit (which would break the caller's transaction) — see the
    module docstring."""
    did = M.new_id()
    conn.execute(
        "INSERT INTO decisions ("
        "id, user_id, entity_type, entity_id, decision_type, "
        "ai_proposal_snapshot, final_values_snapshot, created_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            did,
            user_id,
            entity_type,
            entity_id,
            decision_type,
            M._json_dumps_obj(ai_proposal_snapshot),
            M._json_dumps_obj(final_values_snapshot),
            S._now(),
        ),
    )
    return did


def _validate_vector(user_id: str, basis: dict[str, Any]) -> list[dict]:
    """Re-resolve every basis-referenced entity at its current
    version and compare the scheduling-relevant fields. Only
    description/notes-class text is tolerated (brief §1) — those
    fields are simply not in the vector."""
    offenders: list[dict[str, Any]] = []
    vector = basis.get("entity_version_vector") or {}
    for key, stored in vector.items():
        kind, _, entity_id = key.partition(":")
        if kind == "task":
            row = S.get_task(entity_id, user_id)
            fields = _TASK_VECTOR_FIELDS
        elif kind == "project":
            row = S.get_project(entity_id, user_id)
            fields = _PROJECT_VECTOR_FIELDS
        elif kind == "capacity":
            row = S.get_capacity_profile(entity_id, user_id)
            fields = _CAPACITY_VECTOR_FIELDS
        else:
            continue
        if row is None:
            offenders.append(
                {
                    "failure_class": "deleted",
                    "entity_type": kind,
                    "entity_id": entity_id,
                    "field": None,
                    "from": stored,
                    "to": None,
                    "detail": "a basis-referenced record no longer exists",
                }
            )
            continue
        current = _vector_for(fields, row) or {}
        for field in fields:
            if stored.get(field) != current.get(field):
                offenders.append(
                    {
                        "failure_class": "stale_record",
                        "entity_type": kind,
                        "entity_id": entity_id,
                        "field": field,
                        "from": stored.get(field),
                        "to": current.get(field),
                    }
                )
    return offenders


def _validate_temporal_snapshot(
    basis: dict[str, Any],
    fold_now: dict[str, Any],
    frozen_arrangement: dict[str, Any] | None,
) -> list[dict]:
    """Compare the fold's temporal content against the basis
    snapshot: the span set (any span added, withdrawn, or altered
    for any project) and the person's allocation series. A changed
    allocation bucket the frozen arrangement planned to write into
    is a concurrent change; any other standing change is drift."""
    offenders: list[dict[str, Any]] = []
    snapshot = basis.get("temporal_snapshot") or {}
    stored_spans: dict[str, str] = snapshot.get("spans") or {}
    current_spans: dict[str, str] = {}
    for pdata in (fold_now.get("projects") or {}).values():
        for span in pdata.get("spans", []):
            current_spans[span["id"]] = _span_fingerprint(span)
    for span_id in sorted(set(stored_spans) | set(current_spans)):
        if stored_spans.get(span_id) != current_spans.get(span_id):
            offenders.append(
                {
                    "failure_class": "standing_drift",
                    "entity_type": "span",
                    "entity_id": span_id,
                    "field": "standing",
                    "from": stored_spans.get(span_id),
                    "to": current_spans.get(span_id),
                    "detail": "temporal standing changed since the basis",
                }
            )

    person_id = basis.get("person_id")
    stored_alloc = (snapshot.get("allocations") or {}).get(str(person_id), {})
    current_alloc: dict[str, float] = {}
    series = (fold_now.get("allocations") or {}).get(str(person_id))
    if series:
        for week, bucket in series["weeks"].items():
            current_alloc[week] = bucket["established_hours"]
    planned_weeks = _planned_allocation_weeks(frozen_arrangement, basis)
    for week in sorted(set(stored_alloc) | set(current_alloc)):
        if stored_alloc.get(week, 0.0) != current_alloc.get(week, 0.0):
            offenders.append(
                {
                    "failure_class": (
                        "concurrent_change"
                        if week in planned_weeks
                        else "standing_drift"
                    ),
                    "entity_type": "allocation_bucket",
                    "entity_id": f"{person_id}:{week}",
                    "field": "established_hours",
                    "from": stored_alloc.get(week, 0.0),
                    "to": current_alloc.get(week, 0.0),
                    "detail": "an established-allocation bucket changed "
                    "since the basis",
                }
            )
    return offenders


def _target_task_ids(diagnosis: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for node in diagnosis.get("tasks", []):
        ids.add(str(node["ref_task_id"]) if node.get("ref_task_id") else node["id"])
    return ids


def _chosen_pass(
    result: dict[str, Any], diagnosis: dict[str, Any]
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """The pass establishment writes from: the sustainable
    placement when the verdict is sustainable, else the
    earliest-found pass. Returns (pass_name, placement, finish)
    where placement maps kernel task id → per-task weeks."""
    target_ids = _target_task_ids(diagnosis)
    pid = diagnosis["project_id"]
    sustainable = result.get("sustainable") or {}
    if sustainable.get("status") == "sustainable" and sustainable.get(
        "target_placement"
    ):
        return (
            "sustainable",
            dict(sustainable["target_placement"]),
            sustainable.get("target_finish") or {},
        )
    earliest = result.get("earliest_found") or {}
    placement = {
        tid: info
        for tid, info in (earliest.get("task_weeks") or {}).items()
        if tid in target_ids
    }
    finish = (earliest.get("project_finish") or {}).get(pid, {})
    return ("earliest_found", placement, finish)


def _planned_allocation_weeks(
    arrangement: dict[str, Any] | None, basis: dict[str, Any]
) -> set[str]:
    """The ISO week-starts the frozen arrangement planned to write
    allocations into (from its chosen pass)."""
    if not arrangement:
        return set()
    # The diagnosis is not needed for the id set here: the chosen
    # pass placement is recomputed from the stored arrangement
    # against the stored target id set in the basis.
    target_ids = set(basis.get("target_task_ids") or [])
    if not target_ids:
        return set()
    anchor_raw = basis.get("start_week")
    if not anchor_raw:
        return set()
    anchor = date.fromisoformat(str(anchor_raw)[:10])
    sustainable = arrangement.get("sustainable") or {}
    if sustainable.get("status") == "sustainable" and sustainable.get(
        "target_placement"
    ):
        placement = sustainable["target_placement"]
    else:
        earliest = arrangement.get("earliest_found") or {}
        placement = {
            tid: info
            for tid, info in (earliest.get("task_weeks") or {}).items()
            if tid in target_ids
        }
    weeks: set[str] = set()
    for info in placement.values():
        for w in (info.get("hours_by_week") or {}):
            weeks.add((anchor + timedelta(weeks=int(w))).isoformat())
    return weeks


def _same_feasibility(
    frozen: dict[str, Any] | None, result: dict[str, Any]
) -> tuple[bool, str]:
    """The recomputed arrangement must be the frozen one: same
    settings hash, same earliest-found finish for the target, same
    sustainable verdict. Anything else means an input the vector
    did not enumerate changed — abort rather than establish a
    different arrangement than the one approved."""
    if not frozen:
        return (False, "no frozen arrangement to compare against")
    fl = frozen.get("labels") or {}
    rl = result.get("labels") or {}
    if fl.get("algo_settings_hash") != rl.get("algo_settings_hash"):
        return (False, "algorithm settings hash changed")
    ft = (frozen.get("target") or {}).get("earliest_found") or {}
    rt = (result.get("target") or {}).get("earliest_found") or {}
    if ft.get("finish_boundary") != rt.get("finish_boundary"):
        return (
            False,
            "earliest-found finish moved "
            f"({ft.get('finish_boundary')} -> {rt.get('finish_boundary')})",
        )
    fs = (frozen.get("sustainable") or {}).get("status")
    rs = (result.get("sustainable") or {}).get("status")
    if fs != rs:
        return (False, f"sustainable verdict changed ({fs} -> {rs})")
    if result.get("status") != "ok":
        return (False, f"recomputation rejected: {result.get('rejection')}")
    return (True, "")


def _topo_order(
    nodes: dict[str, dict], diagnosis: dict[str, Any], user_id: str
) -> list[str]:
    """Order the given elements so prerequisites establish before
    their dependents (edges only among the given elements). A
    residual cycle leaves the remaining nodes in id order — each
    will fail validation against the kernel-rejected graph rather
    than loop here."""
    deps: dict[str, set[str]] = {nid: set() for nid in nodes}
    for nid, node in nodes.items():
        for dep in node.get("dependencies") or []:
            kind, value = _resolve_dependency(user_id, diagnosis, str(dep))
            if kind == "node" and value["id"] in nodes and value["id"] != nid:
                deps[nid].add(value["id"])
    order: list[str] = []
    ready = sorted(nid for nid, d in deps.items() if not d)
    remaining = {nid: set(d) for nid, d in deps.items()}
    while ready:
        nid = ready.pop(0)
        order.append(nid)
        for other, d in remaining.items():
            if nid in d:
                d.discard(nid)
                if not d and other not in order and other not in ready:
                    ready.append(other)
        ready.sort()
    for nid in sorted(remaining):
        if nid not in order:
            order.append(nid)
    return order


def _resolved_dependency_ids(
    user_id: str,
    diagnosis: dict[str, Any],
    node: dict[str, Any],
    created: dict[str, str],
) -> tuple[list[str], list[str]]:
    """Bind a node's dependencies to canonical task ids for a
    write. Returns (bindable_task_ids, problems): a dependency
    naming a proposed node binds to that node's created task;
    naming a canonical task binds directly; naming a project is an
    undertaking gate (not a task dependency — reported as a
    problem-free note via the second list's gate entries prefixed
    'gate:'); naming nothing fails the element."""
    bound: list[str] = []
    problems: list[str] = []
    for dep in node.get("dependencies") or []:
        dep = str(dep)
        kind, value = _resolve_dependency(user_id, diagnosis, dep)
        if kind == "node":
            target = value
            if target.get("ref_task_id"):
                bound.append(str(target["ref_task_id"]))
            elif target["id"] in created:
                bound.append(created[target["id"]])
            else:
                problems.append(
                    f"dependency {dep!r} is a proposed node that was "
                    "not established"
                )
        elif kind == "task":
            bound.append(value)
        elif kind == "project":
            problems.append(f"gate:{dep}")
        else:
            problems.append(
                f"dependency {dep!r} references a record that does "
                "not exist"
            )
    return bound, problems


def _establish_one(
    conn,
    user_id: str,
    proposal: dict[str, Any],
    node: dict[str, Any],
    created: dict[str, str],
    outcomes: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Establish one element through the canonical write paths.
    Never raises for an element-level problem: the outcome carries
    the failure class instead (brief §8 — a failed element never
    half-writes and never blocks the others' honest reporting)."""
    diagnosis = proposal["diagnosis"]
    element_id = node["id"]
    base: dict[str, Any] = {
        "element_id": element_id,
        "kind": "task_create" if not node.get("ref_task_id") else "task_existing",
        "status": "failed",
        "failure_class": None,
        "detail": "",
        "created_task_id": None,
    }
    # A dependency element that failed refuses this one too.
    for dep in node.get("dependencies") or []:
        kind, value = _resolve_dependency(user_id, diagnosis, str(dep))
        if kind == "node" and not value.get("ref_task_id"):
            prior = outcomes.get(value["id"])
            if prior and prior["status"] in ("failed", "refused"):
                base["failure_class"] = "dependency_failed"
                base["detail"] = (
                    f"prerequisite node {value['id']!r} did not establish"
                )
                return base
    bound, problems = _resolved_dependency_ids(
        user_id, diagnosis, node, created
    )
    hard_problems = [p for p in problems if not p.startswith("gate:")]
    if hard_problems:
        base["failure_class"] = "validation_failed"
        base["detail"] = "; ".join(hard_problems)
        return base

    try:
        if node.get("ref_task_id"):
            task_id = str(node["ref_task_id"])
            current = S.get_task(task_id, user_id)
            if current is None:
                base["failure_class"] = "validation_failed"
                base["detail"] = "the recorded task no longer exists"
                return base
            diffs: dict[str, Any] = {}
            if (node.get("title") or "") != (current.get("title") or ""):
                diffs["title"] = node.get("title") or ""
            if (node.get("completion_criteria") or "") != (
                current.get("completion_criteria") or ""
            ):
                diffs["completion_criteria"] = node.get("completion_criteria") or ""
            if node.get("due_date") != current.get("due_date"):
                diffs["due_date"] = node.get("due_date")
            if node.get("timeframe_commitment") != current.get(
                "timeframe_commitment"
            ):
                diffs["timeframe_commitment"] = node.get("timeframe_commitment")
            if (node.get("priority") or "") != (current.get("priority") or ""):
                diffs["priority"] = node.get("priority") or ""
            effort = node.get("effort") or {"kind": "unknown"}
            if effort.get("kind") == "exact" and float(
                effort["hours"]
            ) != float(current.get("estimated_hours") or -1):
                diffs["estimated_hours"] = float(effort["hours"])
            current_deps = [str(d) for d in (current.get("dependency_ids") or [])]
            if sorted(bound) != sorted(current_deps):
                diffs["dependency_ids"] = bound
            if diffs:
                S.update_task(task_id, M.TaskUpdate(**diffs), user_id)
                base["status"] = "updated"
                base["detail"] = (
                    "canonical task updated to the approved diagnosis: "
                    + ", ".join(sorted(diffs))
                )
            else:
                base["status"] = "already_canonical"
                base["detail"] = "the recorded task already matches the diagnosis"
            return base

        effort = node.get("effort") or {"kind": "unknown"}
        data = M.TaskCreate(
            project_id=diagnosis["project_id"],
            title=node.get("title") or "",
            status="Todo",
            priority=node.get("priority") or "",
            estimated_hours=(
                float(effort["hours"]) if effort.get("kind") == "exact" else None
            ),
            due_date=node.get("due_date"),
            dependency_ids=bound,
            completion_criteria=node.get("completion_criteria") or "",
            timeframe_commitment=node.get("timeframe_commitment"),
        )
        S._guard_legacy_write(
            conn,
            S._resolve_task_payload_subtree(
                conn, data.parent_task_id, data.project_id, user_id
            ),
            target_id=None,
            target_kind="task",
        )
        tid = S._insert_task(
            conn,
            data,
            user_id,
            origin_seat=DIAGNOSIS_SEAT,
            origin_conversation_id=None,
            origin_message_id=None,
            origin_claim_id=None,
            # The approval IS a decision: its id is the provenance
            # anchor W1 never had (there, no decision existed).
            origin_decision_id=proposal.get("approval_decision_id"),
            responsible_seat=None,
        )
        created[node["id"]] = tid
        base["status"] = "established"
        base["created_task_id"] = tid
        base["detail"] = "canonical task created with origin_* provenance"
        return base
    except ValueError as exc:
        base["failure_class"] = "validation_failed"
        base["detail"] = str(exc)
        return base
    except Exception as exc:  # a write problem is an outcome, not a crash
        base["failure_class"] = "write_failed"
        base["detail"] = f"{type(exc).__name__}: {exc}"
        return base


def _combined_effort(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Combine task-node effort representations into one span-level
    representation: exact sums stay exact, intervals widen, and any
    unknown or one-sided bound makes the whole unknown (no
    fabricated precision)."""
    total = 0.0
    low = 0.0
    high = 0.0
    saw_interval = False
    for node in nodes:
        effort = node.get("effort") or {"kind": "unknown"}
        kind = effort.get("kind")
        if kind == "exact":
            total += float(effort["hours"])
            low += float(effort["hours"])
            high += float(effort["hours"])
        elif kind == "interval":
            saw_interval = True
            low += float(effort["low_hours"])
            high += float(effort["high_hours"])
        else:
            return {"kind": "unknown"}
    if saw_interval:
        return {"kind": "interval", "low_hours": low, "high_hours": high}
    return {"kind": "exact", "hours": total}


def _record_abort(
    user_id: str, proposal: dict[str, Any], offenders: list[dict[str, Any]]
) -> dict[str, Any]:
    """Record an aborted establishment as an outcome decision and
    return the report. The proposal keeps its approved state —
    nothing was established, and the freeze stands until the world
    is reconciled or the diagnosis revised."""
    report = {
        "status": "aborted",
        "proposal_id": proposal["id"],
        "version": proposal["version"],
        "offenders": offenders,
        "elements": [],
        "fold_seq_at_basis": (proposal.get("basis") or {}).get("fold_seq"),
        "fold_seq_now": T.current_fold_seq(user_id),
    }
    decision = S.create_decision(
        M.DecisionCreate(
            user_id=user_id,
            entity_type="project",
            entity_id=proposal["project_id"],
            decision_type=ESTABLISHMENT_OUTCOME,
            ai_proposal_snapshot={
                "proposal_id": proposal["id"],
                "version": proposal["version"],
            },
            final_values_snapshot=report,
        )
    )
    report["outcome_decision_id"] = decision["id"]
    return report


def establish_diagnosis_proposal(
    user_id: str, proposal_id: str
) -> dict[str, Any]:
    """Establish an approved diagnosis arrangement (brief §8).

    One transaction: basis revalidation (entity vector + fold
    content + kernel version), feasibility recomputation under the
    frozen settings, then per-element canonical writes. Drift
    aborts everything and is reported with offenders enumerated;
    element failures are per-element outcomes and leave the
    proposal partially established and revisable.
    """
    proposal = _require_proposal(user_id, proposal_id)
    if proposal["state"] not in ("approved", "partially_established"):
        raise DiagnosisConflict(
            f"Proposal is {proposal['state']}; only an approved "
            "diagnosis can be established"
        )
    basis = proposal["basis"]
    if not basis:
        raise DiagnosisConflict("Proposal carries no basis; nothing to establish")
    diagnosis = proposal["diagnosis"]

    if basis.get("kernel_version") != K.KERNEL_VERSION:
        return _record_abort(
            user_id,
            proposal,
            [
                {
                    "failure_class": "kernel_version_changed",
                    "entity_type": "kernel",
                    "entity_id": "temporal_kernel",
                    "field": "kernel_version",
                    "from": basis.get("kernel_version"),
                    "to": K.KERNEL_VERSION,
                    "detail": "the arrangement was computed under a "
                    "different kernel version; recompute before "
                    "establishing",
                }
            ],
        )

    nodes = {n["id"]: n for n in diagnosis.get("tasks", [])}
    approved = proposal["approved_subset"] or list(nodes)
    gated = {g["node_id"] for g in proposal.get("external_gates") or []}
    prior = proposal.get("establishment") or {}
    prior_outcomes = {
        e["element_id"]: e for e in prior.get("elements", []) if isinstance(e, dict)
    }

    conn = S.get_connection()
    _ensure_table(conn)
    elements: list[dict[str, Any]] = []
    span_id: str | None = None
    allocation_ids: list[str] = []
    pass_used: str | None = None
    try:
        with S.ve_write_transaction(conn, purpose="temporal_establishment"):
            offenders = _validate_vector(user_id, basis)
            fold_now = T.derive_temporal_standing(user_id)
            offenders += _validate_temporal_snapshot(
                basis, fold_now, proposal.get("arrangement")
            )
            if offenders:
                raise _EstablishmentAbort(offenders)

            world = _assemble_world(user_id, diagnosis)
            result = K.compute_arrangement(
                start_week=basis["start_week"],
                horizon_weeks=basis["horizon_weeks"],
                target_advances=basis["target_advances"],
                **world["kernel_kwargs"],
            )
            same, why = _same_feasibility(proposal.get("arrangement"), result)
            if not same:
                raise _EstablishmentAbort(
                    [
                        {
                            "failure_class": "feasibility_changed",
                            "entity_type": "arrangement",
                            "entity_id": diagnosis["project_id"],
                            "field": "feasibility",
                            "from": "the approved arrangement",
                            "to": why,
                            "detail": "recomputation under the frozen "
                            "settings no longer reproduces the approved "
                            "arrangement",
                        }
                    ]
                )

            created: dict[str, str] = {}
            outcomes: dict[str, dict[str, Any]] = {}
            for node_id in _topo_order(
                {nid: nodes[nid] for nid in approved if nid in nodes},
                diagnosis,
                user_id,
            ):
                node = nodes[node_id]
                if node_id in gated:
                    outcomes[node_id] = {
                        "element_id": node_id,
                        "kind": "task_create"
                        if not node.get("ref_task_id")
                        else "task_existing",
                        "status": "refused",
                        "failure_class": "external_gate",
                        "detail": "an unapproved or missing prerequisite "
                        "gates this element; it is unschedulable until "
                        "the gate exists",
                        "created_task_id": None,
                    }
                    continue
                prior_outcome = prior_outcomes.get(node_id)
                if prior_outcome and prior_outcome.get("status") in (
                    "established",
                    "updated",
                    "already_canonical",
                ):
                    outcomes[node_id] = prior_outcome
                    if prior_outcome.get("created_task_id"):
                        created[node_id] = prior_outcome["created_task_id"]
                    continue
                outcomes[node_id] = _establish_one(
                    conn, user_id, proposal, node, created, outcomes
                )
            elements = [outcomes[nid] for nid in approved if nid in outcomes]

            fully = all(
                e["status"] in ("established", "updated", "already_canonical")
                for e in elements
            )
            if fully:
                pass_used, placement, finish = _chosen_pass(result, diagnosis)
                anchor = date.fromisoformat(str(basis["start_week"])[:10])
                if finish.get("complete") and placement:
                    start_weeks = [
                        info.get("start_week")
                        for info in placement.values()
                        if info.get("start_week") is not None
                    ]
                    if start_weeks and finish.get("finish_boundary") is not None:
                        span_payload = {
                            "start": (
                                anchor + timedelta(weeks=min(start_weeks))
                            ).isoformat(),
                            "end": (
                                anchor
                                + timedelta(
                                    weeks=int(finish["finish_boundary"]), days=-1
                                )
                            ).isoformat(),
                            "origin": "derived",
                            "standing": "derived forecast",
                            "role": "window",
                            "conditionality": T.build_conditionality(
                                diagnosis.get("assumptions")
                            ),
                            "effort": _combined_effort(
                                [nodes[nid] for nid in approved]
                            ),
                            "basis": [
                                f"kernel {K.KERNEL_VERSION} "
                                f"({result['labels']['algorithm']})",
                                f"basis fold_seq {basis['fold_seq']}",
                                f"pass: {pass_used}",
                            ],
                            "method": "temporal kernel arrangement, "
                            "established on approval",
                            "note": result["labels"]["claim"],
                        }
                        probe = {
                            "id": "probe",
                            "entity_id": diagnosis["project_id"],
                            "decision_type": T.SPAN_RECORDED,
                            "final_values_snapshot": span_payload,
                            "created_at": "",
                        }
                        if T.parse_span_record(probe) is not None:
                            span_id = _insert_decision_in_txn(
                                conn,
                                user_id=user_id,
                                entity_type="project",
                                entity_id=diagnosis["project_id"],
                                decision_type=T.SPAN_RECORDED,
                                final_values_snapshot=span_payload,
                            )
                    by_week: dict[int, float] = {}
                    for info in placement.values():
                        for w, h in (info.get("hours_by_week") or {}).items():
                            by_week[int(w)] = by_week.get(int(w), 0.0) + float(h)
                    person_id = basis["person_id"]
                    for w in sorted(by_week):
                        hours = round(by_week[w], 4)
                        if hours <= 0:
                            continue
                        allocation_ids.append(
                            _insert_decision_in_txn(
                                conn,
                                user_id=user_id,
                                entity_type="person",
                                entity_id=str(person_id),
                                decision_type=T.ALLOCATION_RECORDED,
                                final_values_snapshot={
                                    "week_start": (
                                        anchor + timedelta(weeks=w)
                                    ).isoformat(),
                                    "hours": hours,
                                    "project_id": diagnosis["project_id"],
                                },
                            )
                        )

            new_state = "established" if fully else "partially_established"
            report = {
                "status": new_state,
                "proposal_id": proposal_id,
                "version": proposal["version"],
                "elements": elements,
                "pass_used": pass_used,
                "span_id": span_id,
                "allocation_ids": allocation_ids,
                "fold_seq_at_basis": basis.get("fold_seq"),
                "fold_seq_now": fold_now["fold_seq"],
            }
            outcome_id = _insert_decision_in_txn(
                conn,
                user_id=user_id,
                entity_type="project",
                entity_id=diagnosis["project_id"],
                decision_type=ESTABLISHMENT_OUTCOME,
                ai_proposal_snapshot={
                    "proposal_id": proposal_id,
                    "version": proposal["version"],
                },
                final_values_snapshot=report,
            )
            report["outcome_decision_id"] = outcome_id
            conn.execute(
                "UPDATE diagnosis_proposals SET state = ?, establishment = ?, "
                "updated_at = ? WHERE id = ? AND user_id = ?",
                (
                    new_state,
                    json.dumps(report),
                    S._now(),
                    proposal_id,
                    user_id,
                ),
            )
            S._commit_if_owner(conn)
    except _EstablishmentAbort as abort:
        return _record_abort(user_id, proposal, abort.offenders)
    return report
