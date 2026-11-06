"""Unified-node read-only projection (Slice A).

Presents the four existing VE tables — ideas, initiatives, projects,
tasks — plus checklist items and execution steps as nodes, computed on
read from those tables (rev2 design §5 Slice A, §8).

The projection is a pure function over the current rows: it holds no
state of its own, creates no table and no store, and performs no
writes of any kind. The four tables remain the sole authoritative
write path; if the projection and a table disagree, the table is
right and the projection is wrong. This module contains no SQL of its
own — it reads only through the existing storage list functions.

Mapping (rev2 §3.2 as corrected, §3.3):
- kind comes from the source table (checklist items and execution
  steps project as kind "task", §2.5);
- parent comes from the corrected §3.2 mapping — a task with both a
  project and a parent task keeps its immediate task parent, with the
  project reached through that ancestor's chain; an initiative's
  source idea is an origin edge, not a parent;
- status comes from the §3.3 unified work-state mapping.

Fail-closed rules (reported, never guessed):
- a parent reference that does not resolve to a projected node of the
  expected kind raises ValueError;
- a status value with no §3.3 mapping raises ValueError;
- two rows sharing one id raise ValueError.
Origin references (an initiative's source idea) are carried verbatim
as provenance, not structure, so a dangling origin does not fail the
read — the parent rules above are the structural ones.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import storage as S

# Unified work-state vocabulary (rev2 §2.1, §3.3).
NODE_STATUSES = ("Open", "Active", "Blocked", "Done", "Dropped", "Parked")
NODE_KINDS = ("idea", "initiative", "project", "task")

# Legacy status -> unified work state (rev2 §3.3).
_IDEA_STATUS_MAP = {
    "Captured": "Open",
    "Clarifying": "Open",
    "Contextualized": "Open",
    "Evaluated": "Open",
    "Advanced": "Active",
    "Parked": "Parked",
    "Archived": "Parked",
    "Graduated": "Done",
}
_INITIATIVE_STATUS_MAP = {
    "Draft": "Open",
    "Evaluating": "Open",
    "Approved": "Open",
    "Active": "Active",
    "Paused": "Parked",
    "Complete": "Done",
    "Killed": "Dropped",
}
_PROJECT_STATUS_MAP = {
    "Draft": "Open",
    "Ready": "Open",
    "Active": "Active",
    "Blocked": "Blocked",
    "Complete": "Done",
    "Parked": "Parked",
}
_TASK_STATUS_MAP = {
    "Todo": "Open",
    "In Progress": "Active",
    "Blocked": "Blocked",
    "Done": "Done",
    "Dropped": "Dropped",
}
# Checklist item status -> unified work state (rev2 §2.5: is_done -> Done).
_CHECKLIST_STATUS_MAP = {"open": "Open", "done": "Done"}

_STATUS_MAPS = {
    "ideas": _IDEA_STATUS_MAP,
    "initiatives": _INITIATIVE_STATUS_MAP,
    "projects": _PROJECT_STATUS_MAP,
    "tasks": _TASK_STATUS_MAP,
}


@dataclass(frozen=True)
class ProjectedNode:
    """One row projected as a unified node (rev2 §2.1 core + provenance).

    The §2.1 core is id / user_id / title / parent_id / kind / status /
    owner_id / created_at / updated_at. The remaining fields are
    provenance and the fields §3.2 carries unchanged: source_table and
    original_status name where the node came from; visibility carries
    the archived distinction (§3.3: an Archived idea is Parked work
    state with archived visibility; a superseded checklist item is
    likewise archived, never silently dropped); origin_id is an
    initiative's source idea as an origin edge; dependency_ids,
    due_date, timeframe_commitment, seat_ref, and the origin_* columns
    are the task fields §3.2 carries unchanged; position preserves
    checklist / execution-step ordering (§2.5).
    """

    id: str
    user_id: str
    title: str
    parent_id: str | None
    kind: str
    status: str
    owner_id: str | None
    created_at: str
    updated_at: str
    source_table: str
    original_status: str
    visibility: str = "visible"
    origin_id: str | None = None
    dependency_ids: tuple[str, ...] = ()
    position: int | None = None
    due_date: str | None = None
    timeframe_commitment: str | None = None
    seat_ref: str | None = None
    origin_seat: str | None = None
    origin_conversation_id: str | None = None
    origin_message_id: str | None = None
    origin_claim_id: str | None = None
    origin_decision_id: str | None = None
    responsible_seat: str | None = None


def map_status(source_table: str, original_status: str) -> tuple[str, str]:
    """Map a legacy status to (unified status, visibility) per rev2 §3.3.

    An Archived idea maps to Parked work state with archived
    visibility — archived is a visibility state, not a work state
    (lifecycle addendum §2.2). Raises ValueError on a status with no
    mapping: an unmapped status is reported, never silently relabeled.
    """
    mapping = _STATUS_MAPS.get(source_table)
    if mapping is None:
        raise ValueError(f"no status mapping for source table {source_table!r}")
    try:
        status = mapping[original_status]
    except KeyError:
        raise ValueError(
            f"unmapped {source_table} status {original_status!r}"
        ) from None
    visibility = (
        "archived"
        if (source_table == "ideas" and original_status == "Archived")
        else "visible"
    )
    return status, visibility


def _map_checklist_status(original_status: str) -> str:
    """Map a checklist item status to the unified work state (§2.5)."""
    try:
        return _CHECKLIST_STATUS_MAP[(original_status or "").strip().lower()]
    except KeyError:
        raise ValueError(
            f"unmapped checklist item status {original_status!r}"
        ) from None


def project_nodes(user_id: str) -> list[ProjectedNode]:
    """Project every VE row owned by `user_id` as a unified node.

    Reads the four tables plus checklist items and execution steps,
    all owner-scoped, and returns one node per live row. The result is
    a flat list; order is not part of the contract — look nodes up by
    id. Parent references that do not resolve to a projected node of
    the expected kind raise ValueError (reported, not guessed).
    """
    ideas = S.list_ideas(user_id)
    initiatives = S.list_initiatives(user_id)
    projects = S.list_projects(user_id)
    tasks = S.list_tasks(user_id)
    items = S.list_all_checklist_items(user_id)
    steps = S.list_all_execution_steps(user_id)

    nodes: list[ProjectedNode] = []
    # node id -> kinds its parent must have (empty tuple = must be a root).
    expected_parent_kind: dict[str, tuple[str, ...]] = {}

    def _add(node: ProjectedNode, parent_kinds: tuple[str, ...]) -> None:
        nodes.append(node)
        expected_parent_kind[node.id] = parent_kinds

    for row in ideas:
        status, visibility = map_status("ideas", row["status"])
        _add(
            ProjectedNode(
                id=row["id"],
                user_id=user_id,
                title=row["title"],
                parent_id=None,
                kind="idea",
                status=status,
                owner_id=None,
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                source_table="ideas",
                original_status=row["status"],
                visibility=visibility,
            ),
            (),
        )

    for row in initiatives:
        status, _visibility = map_status("initiatives", row["status"])
        _add(
            ProjectedNode(
                id=row["id"],
                user_id=user_id,
                title=row["title"],
                parent_id=None,
                kind="initiative",
                status=status,
                owner_id=row.get("owner_id"),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                source_table="initiatives",
                original_status=row["status"],
                origin_id=row.get("source_idea_id") or None,
            ),
            (),
        )

    for row in projects:
        status, _visibility = map_status("projects", row["status"])
        parent_id = row.get("initiative_id") or None
        _add(
            ProjectedNode(
                id=row["id"],
                user_id=user_id,
                title=row["title"],
                parent_id=parent_id,
                kind="project",
                status=status,
                owner_id=row.get("owner_id"),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                source_table="projects",
                original_status=row["status"],
            ),
            ("initiative",) if parent_id is not None else (),
        )

    for row in tasks:
        status, _visibility = map_status("tasks", row["status"])
        # Corrected §3.2 rule: the immediate task parent wins over the
        # project; the project is reached through the ancestor chain.
        if row.get("parent_task_id"):
            parent_id = row["parent_task_id"]
            parent_kinds: tuple[str, ...] = ("task",)
        elif row.get("project_id"):
            parent_id = row["project_id"]
            parent_kinds = ("project",)
        else:
            parent_id = None
            parent_kinds = ()
        _add(
            ProjectedNode(
                id=row["id"],
                user_id=user_id,
                title=row["title"],
                parent_id=parent_id,
                kind="task",
                status=status,
                owner_id=row.get("assignee_id"),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                source_table="tasks",
                original_status=row["status"],
                dependency_ids=tuple(row.get("dependency_ids") or []),
                due_date=row.get("due_date"),
                timeframe_commitment=row.get("timeframe_commitment"),
                seat_ref=row.get("seat_ref") or None,
                origin_seat=row.get("origin_seat"),
                origin_conversation_id=row.get("origin_conversation_id"),
                origin_message_id=row.get("origin_message_id"),
                origin_claim_id=row.get("origin_claim_id"),
                origin_decision_id=row.get("origin_decision_id"),
                responsible_seat=row.get("responsible_seat"),
            ),
            parent_kinds,
        )

    for row in items:
        status = _map_checklist_status(row["status"])
        if row.get("parent_id"):
            parent_id = row["parent_id"]
            parent_kinds = ("task",)
        else:
            parent_id = row["idea_id"]
            parent_kinds = ("idea",)
        _add(
            ProjectedNode(
                id=row["id"],
                user_id=user_id,
                title=row["title"],
                parent_id=parent_id,
                kind="task",
                status=status,
                owner_id=None,
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                source_table="checklist_items",
                original_status=row["status"],
                visibility="archived" if row.get("superseded") else "visible",
                dependency_ids=tuple(row.get("depends_on") or []),
                position=row.get("position"),
            ),
            parent_kinds,
        )

    for row in steps:
        status = "Done" if row.get("is_done") else "Open"
        scope_kind = (
            "initiative" if row.get("scope_type") == "initiative" else "project"
        )
        _add(
            ProjectedNode(
                id=row["id"],
                user_id=user_id,
                title=row["title"],
                parent_id=row["scope_id"],
                kind="task",
                status=status,
                owner_id=None,
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                source_table="execution_steps",
                original_status="done" if row.get("is_done") else "open",
                position=row.get("sort_order"),
            ),
            (scope_kind,),
        )

    # Resolve parents: every parent reference must name a projected
    # node of the expected kind. A missing or wrong-kind parent is a
    # data error to report, not a row to guess a home for.
    by_id: dict[str, ProjectedNode] = {}
    for node in nodes:
        if node.id in by_id:
            raise ValueError(f"duplicate projected node id {node.id!r}")
        by_id[node.id] = node
    for node in nodes:
        if node.parent_id is None:
            continue
        parent = by_id.get(node.parent_id)
        if parent is None:
            raise ValueError(
                f"projected node {node.id!r} ({node.source_table}) has a parent "
                f"{node.parent_id!r} that does not resolve to a projected node"
            )
        if parent.kind not in expected_parent_kind[node.id]:
            raise ValueError(
                f"projected node {node.id!r} ({node.source_table}) has a parent "
                f"{node.parent_id!r} of kind {parent.kind!r}, expected "
                f"{expected_parent_kind[node.id]}"
            )
    return nodes
