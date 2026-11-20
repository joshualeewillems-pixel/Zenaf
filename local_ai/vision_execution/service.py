"""
Vision Execution Engine — business layer. Phase 1: thin pass-through to storage.
Phase 2+: derived fields, validation, council/AI orchestration.
"""
import logging

from local_ai.activity import ActivityEntityType

from . import models as M
from . import storage as S
from . import derived as D
from . import matching as Match

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# W3 §8.2 — deletion-time followthrough cleanup (unlink-first two-step)
#
# The VE and followthrough stores are separate SQLite databases with no
# shared transaction (§0), so there is no cross-database atomicity to
# rely on. The founder's verdict + refinement (2026-11-06) makes
# atomicity a DESIRED consistency property, not a mandatory mechanism:
# the actual requirement is that a task deletion must never permanently
# strand an open commitment or silently erase its obligation. The
# operation below is a recoverable, idempotent two-step with a defined
# order + failure behavior, safe retries, and detection + reconciliation
# of partial completion — no distributed transaction coordinator.
# ---------------------------------------------------------------------------

def _followthrough_store():
    """Followthrough store for the W3 deletion-time cleanup (§8.2).

    A lazy factory (not a singleton) so this module stays importable
    without the followthrough package at import time, and so tests
    can substitute a tmp store via monkeypatch.
    """
    from local_ai.followthrough.store import FollowthroughStore

    return FollowthroughStore()


def _resolve_deleted_nudges(user_id, entity_type, entity_id, ft_store):
    """Best-effort deletion-time nudge resolution (W3 §8.2): resolve
    the entity's live nudges after its VE delete commits — including
    snoozed rows, which the auto-resolve loop cannot see until their
    snooze expires. Raises propagate to the caller, which logs and
    continues: the delete already committed, and the read-time
    exclusion (§8.1) plus the next compute's auto-resolve are the
    guarantee."""
    for row in ft_store.list_live_nudges_for_entity(user_id, entity_type, entity_id):
        ft_store.resolve_nudge(row["id"], user_id)


# Core profiles
def list_core_profiles(user_id: str):
    return S.list_core_profiles(user_id)


def canonical_core_profile_for_user(user_id: str) -> dict | None:
    """
    Default core profile row for server-side context (evaluate, summaries, etc.).

    Uses the same ordering as ``list_core_profiles`` / storage:
    ``ORDER BY is_primary DESC, updated_at DESC``. Do not pick from an unsorted list.
    """
    profiles = S.list_core_profiles(user_id)
    # First element of ordered list (primary-first sort from storage); use iterator to avoid indexed peering pattern.
    return next(iter(profiles), None) if profiles else None


def get_core_profile(profile_id: str, user_id: str):
    return S.get_core_profile(profile_id, user_id)


def create_core_profile(data: M.CoreProfileCreate, user_id: str):
    return S.create_core_profile(data, user_id)


def update_core_profile(profile_id: str, data: M.CoreProfileUpdate, user_id: str):
    return S.update_core_profile(profile_id, data, user_id)


def set_core_profile_primary(profile_id: str, user_id: str):
    return S.set_core_profile_primary(profile_id, user_id)


# Ideas
def list_ideas(user_id: str):
    return S.list_ideas(user_id)


def get_idea(idea_id: str, user_id: str):
    return S.get_idea(idea_id, user_id)


def create_idea(data: M.IdeaCreate, user_id: str):
    return S.create_idea(data, user_id)


def update_idea(idea_id: str, data: M.IdeaUpdate, user_id: str):
    return S.update_idea(idea_id, data, user_id)


def delete_idea(idea_id: str, user_id: str):
    return S.delete_idea(idea_id, user_id)


def promote_idea(idea_id: str, target_level: str, user_id: str):
    """Graduate a confirmed idea into a task, project, or initiative.

    Explicit user verdict — readiness is advisory here (the user decides);
    use idea_readiness() for the hint. The idea's checklist unfolds into the
    work breakdown and is kept as provenance, marked superseded.
    Raises ValueError for unknown ideas/levels or already-graduated ideas.
    The idea is marked "Graduated"; the new entity links back to it
    (source_idea_id for initiatives, notes otherwise).
    """
    from . import graduation as G

    idea = S.get_idea(idea_id, user_id)
    if idea is None:
        raise ValueError("Idea not found")
    if (idea.get("status") or "") == "Graduated":
        raise ValueError("Idea already graduated")
    if target_level not in G.GRADUATE_LEVELS:
        raise ValueError(
            f"unknown target_level: {target_level!r} (expected one of {G.GRADUATE_LEVELS})"
        )
    items = S.list_checklist_items(idea_id, user_id)
    return _do_graduate(idea, items, target_level, user_id)


def _do_graduate(
    idea: dict, items: list[dict], target_level: str, user_id: str
) -> dict:
    """Shared graduation core: shell entity + checklist unfolding.

    `idea` is the idea dict (must have an "id" when persisted; proposals pass
    a transient dict and are persisted first by the caller). `items` are the
    idea's non-superseded checklist items (flat, with depends_on).
    Returns {"idea": updated_idea_or_input, "entity_type": ..., "entity": ...,
             "task_ids": [...]}.
    """
    from . import graduation as G

    idea_id = idea.get("id")
    entity_type, payload = G.build_graduated_payload(
        idea, target_level, source_idea_id=idea_id
    )
    if entity_type == "task":
        created = S.create_task(M.TaskCreate(**payload), user_id)
        root_task_id = _eid(created)
        project_id = None
    elif entity_type == "project":
        created = S.create_project(M.ProjectCreate(**payload), user_id)
        root_task_id = None
        project_id = _eid(created)
    else:
        created = S.create_initiative(M.InitiativeCreate(**payload), user_id)
        initiative_id = _eid(created)
        # The breakdown needs a project home: one plan project under the
        # initiative carries the unfolded checklist as tasks.
        plan = S.create_project(
            M.ProjectCreate(
                title=f"{(idea.get('title') or 'Idea').strip()} — plan",
                brief=(idea.get("description") or idea.get("summary") or "").strip(),
                status="Draft",
                initiative_id=initiative_id,
                notes=f"Work breakdown unfolded from idea '{(idea.get('title') or '').strip()}'"
                + (f" ({idea_id})" if idea_id else ""),
            ),
            user_id,
        )
        root_task_id = None
        project_id = _eid(plan)

    task_ids = _unfold_checklist(
        items,
        user_id,
        project_id=project_id,
        root_parent_task_id=root_task_id,
        provenance_title=(idea.get("title") or "").strip(),
    )

    created_id = _eid(created)
    result: dict = {
        "idea": idea,
        "entity_type": entity_type,
        "entity": created,
        "task_ids": task_ids,
    }

    if idea_id:
        # Keep the graduated checklist as provenance, then mark the idea.
        S.mark_checklist_superseded(idea_id, user_id)
        provenance = (
            f"Graduated to {entity_type}"
            + (f" ({created_id})" if created_id else "")
            + (f" with {len(task_ids)} unfolded tasks" if task_ids else "")
        )
        existing_notes = (idea.get("notes") or "").strip()
        updated = S.update_idea(
            idea_id,
            M.IdeaUpdate(
                status="Graduated",
                notes=(existing_notes + "\n\n" + provenance).strip(),
            ),
            user_id,
        )
        result["idea"] = updated
    return result


def _eid(obj) -> str:
    return obj.get("id") if isinstance(obj, dict) else getattr(obj, "id", "")


def _unfold_checklist(
    items: list[dict],
    user_id: str,
    project_id: str | None,
    root_parent_task_id: str | None,
    provenance_title: str,
) -> list[str]:
    """Turn checklist items into tasks, preserving nesting and dependencies.

    Top-level items become tasks (under project_id and/or root_parent_task_id);
    nested items become subtasks via parent_task_id; checklist dependencies
    carry over to task dependency_ids. Item status maps open->Todo, done->Done.
    Returns the created task ids.
    """
    from . import graduation as G

    tree = G.build_checklist_tree([it for it in items if not it.get("superseded")])
    item_to_task: dict[str, str] = {}
    created_ids: list[str] = []

    def _status(item: dict) -> str:
        return "Done" if (item.get("status") or "") == "done" else "Todo"

    def _create(nodes: list[dict], parent_task_id: str | None) -> None:
        for node in nodes:
            title = (node.get("title") or "Untitled").strip() or "Untitled"
            asset_id = node.get("asset_id")
            task = S.create_task(
                M.TaskCreate(
                    title=title,
                    description="",
                    project_id=project_id,
                    parent_task_id=parent_task_id,
                    status=_status(node),
                    assignee_id=node.get("person_id"),
                    required_asset_ids=[asset_id] if asset_id else [],
                    notes=(
                        f"Unfolded from checklist of idea '{provenance_title}'"
                        if provenance_title
                        else "Unfolded from idea checklist"
                    ),
                ),
                user_id,
            )
            tid = _eid(task)
            item_to_task[node["id"]] = tid
            created_ids.append(tid)
            _create(node.get("children", []), tid)

    _create(tree, root_parent_task_id)

    # Second pass: dependencies (all tasks exist now, so ids resolve).
    for node in _walk_tree(tree):
        deps = node.get("depends_on") or []
        target_ids = [item_to_task[d] for d in deps if d in item_to_task]
        if not target_ids:
            continue
        tid = item_to_task[node["id"]]
        before = S.get_task(tid, user_id) or {}
        existing = _as_str_list(before.get("dependency_ids"))
        merged = existing + [t for t in target_ids if t not in existing]
        S.update_task(tid, M.TaskUpdate(dependency_ids=merged), user_id)

    return created_ids


def _walk_tree(nodes: list[dict]):
    for node in nodes:
        yield node
        yield from _walk_tree(node.get("children", []))


def _as_str_list(v) -> list[str]:
    import json as _json

    if not v:
        return []
    if isinstance(v, str):
        try:
            parsed = _json.loads(v)
            return [str(x) for x in parsed] if isinstance(parsed, list) else []
        except Exception:
            return []
    return [str(x) for x in v]


# --- Idea checklists ---


def create_checklist_items_batch(
    idea_id: str, items: list[dict], user_id: str
) -> list[dict]:
    """Batch-create a nested checklist. Each item: {title, children?[], status?, person_id?, asset_id?}.

    Returns the nested tree (as get_checklist_tree). Positions follow order.
    """
    from . import graduation as G

    idea = S.get_idea(idea_id, user_id)
    if idea is None:
        raise ValueError("Idea not found")

    def _create(nodes: list[dict], parent_id: str | None, start: int) -> None:
        for offset, node in enumerate(nodes):
            title = (node.get("title") or "").strip()
            if not title:
                continue
            status = (node.get("status") or "open").strip().lower()
            created = S.create_checklist_item(
                user_id, idea_id, title,
                parent_id=parent_id, position=start + offset, status=status,
                person_id=node.get("person_id"), asset_id=node.get("asset_id"),
            )
            _create(node.get("children") or [], created["id"], 0)

    _create(items, None, 0)
    return get_checklist_tree(idea_id, user_id)


def get_checklist_tree(idea_id: str, user_id: str) -> list[dict]:
    """The idea's live checklist as a nested tree (non-superseded)."""
    from . import graduation as G

    items = S.list_checklist_items(idea_id, user_id)
    return G.build_checklist_tree(items)


def update_checklist_item(
    item_id: str,
    user_id: str,
    title: str | None = None,
    status: str | None = None,
    position: int | None = None,
    person_id: str | None = None,
    asset_id: str | None = None,
    clear_person: bool = False,
    clear_asset: bool = False,
) -> dict | None:
    return S.update_checklist_item(
        item_id, user_id, title, status, position,
        person_id=person_id, asset_id=asset_id,
        _clear_person=clear_person, _clear_asset=clear_asset,
    )


def delete_checklist_item(item_id: str, user_id: str) -> bool:
    return S.delete_checklist_item(item_id, user_id)


def add_checklist_dependency(item_id: str, depends_on_id: str, user_id: str) -> dict:
    return S.add_checklist_dependency(item_id, depends_on_id, user_id)


def remove_checklist_dependency(item_id: str, depends_on_id: str, user_id: str) -> bool:
    return S.remove_checklist_dependency(item_id, depends_on_id, user_id)


def idea_readiness(idea_id: str, user_id: str) -> dict:
    """Advisory readiness hint: is this idea's checklist worked through?"""
    from . import graduation as G

    idea = S.get_idea(idea_id, user_id)
    if idea is None:
        raise ValueError("Idea not found")
    items = S.list_checklist_items(idea_id, user_id)
    ready, missing, stats = G.checklist_readiness(items)
    return {
        "ready": ready,
        "missing": missing,
        "levels": list(G.GRADUATE_LEVELS),
        **stats,
    }


# Initiatives (with derived: weightedScore, approvalReady, returnOnTime)
def list_initiatives(user_id: str):
    out = S.list_initiatives(user_id)
    for r in out:
        D.add_initiative_derived(r)
    return out


def get_initiative(initiative_id: str, user_id: str):
    out = S.get_initiative(initiative_id, user_id)
    if out is not None:
        D.add_initiative_derived(out)
    return out


def create_initiative(data: M.InitiativeCreate, user_id: str):
    return S.create_initiative(data, user_id)


def update_initiative(initiative_id: str, data: M.InitiativeUpdate, user_id: str):
    return S.update_initiative(initiative_id, data, user_id)


def delete_initiative(initiative_id: str, user_id: str):
    return S.delete_initiative(initiative_id, user_id)


# Execution steps (Phase 1)
def list_execution_steps_for_initiative(initiative_id: str, user_id: str):
    return S.list_execution_steps(S.EXECUTION_STEPS_SCOPE_INITIATIVE, initiative_id, user_id)


def list_execution_steps_for_project(project_id: str, user_id: str):
    return S.list_execution_steps(S.EXECUTION_STEPS_SCOPE_PROJECT, project_id, user_id)


def create_execution_step_for_initiative(initiative_id: str, data: M.ExecutionStepCreate, user_id: str):
    return S.create_execution_step(
        user_id,
        S.EXECUTION_STEPS_SCOPE_INITIATIVE,
        initiative_id,
        data.title,
        data.sort_order,
        "user",
        None,
    )


def create_execution_step_for_project(project_id: str, data: M.ExecutionStepCreate, user_id: str):
    return S.create_execution_step(
        user_id,
        S.EXECUTION_STEPS_SCOPE_PROJECT,
        project_id,
        data.title,
        data.sort_order,
        "user",
        None,
    )


def update_execution_step(step_id: str, data: M.ExecutionStepUpdate, user_id: str):
    patch = data.model_dump(exclude_unset=True)
    return S.update_execution_step(step_id, user_id, patch)


def delete_execution_step(step_id: str, user_id: str):
    return S.delete_execution_step(step_id, user_id)


def materialize_execution_steps_for_initiative(
    initiative_id: str, body: M.ExecutionStepMaterializeBody, user_id: str
):
    return S.materialize_execution_steps(
        user_id,
        S.EXECUTION_STEPS_SCOPE_INITIATIVE,
        initiative_id,
        body.titles,
        body.source,
        replace=body.replace,
    )


def materialize_execution_steps_for_project(project_id: str, body: M.ExecutionStepMaterializeBody, user_id: str):
    return S.materialize_execution_steps(
        user_id,
        S.EXECUTION_STEPS_SCOPE_PROJECT,
        project_id,
        body.titles,
        body.source,
        replace=body.replace,
    )


def reorder_execution_steps_for_initiative(initiative_id: str, body: M.ExecutionStepReorderBody, user_id: str):
    return S.reorder_execution_steps(user_id, S.EXECUTION_STEPS_SCOPE_INITIATIVE, initiative_id, body.ordered_ids)


def reorder_execution_steps_for_project(project_id: str, body: M.ExecutionStepReorderBody, user_id: str):
    return S.reorder_execution_steps(user_id, S.EXECUTION_STEPS_SCOPE_PROJECT, project_id, body.ordered_ids)


# Projects (with derived: duration, completionReadiness, unanchoredFlag)
def list_projects(user_id: str):
    out = S.list_projects(user_id)
    for r in out:
        D.add_project_derived(r)
    return out


def get_project(project_id: str, user_id: str):
    out = S.get_project(project_id, user_id)
    if out is not None:
        D.add_project_derived(out)
    return out


def create_project(data: M.ProjectCreate, user_id: str):
    return S.create_project(data, user_id)


def update_project(project_id: str, data: M.ProjectUpdate, user_id: str):
    return S.update_project(project_id, data, user_id)


def delete_project(project_id: str, user_id: str):
    """Delete a project (W3 §8.2: unlink-first two-step, founder
    verdict + refinement 2026-11-06).

    C1a §6: the storage layer no longer cascades — S.delete_project
    refuses while the project has tasks (ProjectHasTasks 409), so a
    storage-level cascade would orphan the tasks' node counterparts.
    The service therefore deletes the tasks first, each via
    delete_task (which keeps the W3 unlink-first two-step per task:
    unlink, VE delete, nudge resolution), then deletes the now-empty
    project. Order + failure behavior: a task delete that raises
    aborts the project delete (that task stays, so the storage guard
    refuses the project too); a failure after a task is deleted
    leaves that task gone and its commitments unlinked (temporarily
    detached, safe and recoverable — they resurface as
    commitment_open on the next compute; retry is idempotent).
    After the project delete commits, the project nudge is resolved
    best-effort (each task nudge was already resolved by its own
    delete_task).
    """
    if S.get_project(project_id, user_id) is None:
        return False
    ft_store = _followthrough_store()
    task_ids = [t["id"] for t in S.list_tasks(user_id, project_id)]
    for tid in task_ids:
        delete_task(tid, user_id)
    deleted = S.delete_project(project_id, user_id)
    if deleted:
        try:
            _resolve_deleted_nudges(user_id, "project", project_id, ft_store)
        except Exception:
            logger.exception(
                "W3 deletion cleanup: nudge resolution failed after project "
                "delete; read-time exclusion + next compute cover it"
            )
    return deleted


# Tasks
def list_tasks(user_id: str, project_id: str | None = None, timeframe_commitment: str | None = None):
    return S.list_tasks(user_id, project_id, timeframe_commitment=timeframe_commitment)


def get_task(task_id: str, user_id: str):
    return S.get_task(task_id, user_id)


def list_task_proposals_by_parent(
    user_id: str, parent_task_id: str, state: str | None = "pending", limit: int = 100
):
    """Node-scoped proposal read (S3, verdict OQ5). Passthrough to the
    storage read of the same name; ``user_id`` required, exact parent
    match only — see storage for the contract."""
    return S.list_task_proposals_by_parent(user_id, parent_task_id, state, limit)


def create_task(data: M.TaskCreate, user_id: str):
    return S.create_task(data, user_id)


def update_task(task_id: str, data: M.TaskUpdate, user_id: str):
    return S.update_task(task_id, data, user_id)


def delete_task(task_id: str, user_id: str):
    """Delete a task (W3 §8.2: unlink-first two-step, founder verdict
    + refinement 2026-11-06).

    Order (defined) + failure behavior:
      1. Unlink commitments linked to the task (followthrough store,
         owner-scoped, idempotent). If this raises, the task is NOT
         deleted — the operation aborts before any VE write.
      2. Delete the task (VE store). If this raises after step 1,
         the commitments stay unlinked: temporarily detached, safe
         and recoverable — they resurface as commitment_open on the
         next compute, and retrying the delete is safe (step 1 is a
         no-op on already-unlinked rows, no duplicate attention
         items: the engine dedups by (kind, entity_type, entity_id)).
      3. After the delete commits, resolve the task's live nudges
         (best-effort, including snoozed rows). A failure here is
         logged and does not fail the delete — the read-time
         exclusion (§8.1) and the next compute's auto-resolve are
         the guarantee.

    Children survive as roots (storage NULLs their parent_task_id);
    their nudges stand — a child is not deleted by this call.
    """
    if S.get_task(task_id, user_id) is None:
        return False
    ft_store = _followthrough_store()
    ft_store.unlink_commitments_for_task(user_id, task_id)
    deleted = S.delete_task(task_id, user_id)
    if deleted:
        try:
            _resolve_deleted_nudges(user_id, "task", task_id, ft_store)
        except Exception:
            logger.exception(
                "W3 deletion cleanup: nudge resolution failed after task "
                "delete; read-time exclusion + next compute cover it"
            )
    return deleted


# Sticky seat unlocks (see keystone_seeding.maybe_record_entry_unlock).
def record_seat_unlocks(user_id: str, seat_refs: list[str]) -> None:
    return S.record_seat_unlocks(user_id, seat_refs)


def get_seat_unlocks(user_id: str) -> set[str]:
    return S.get_seat_unlocks(user_id)


# Persons
def list_persons(user_id: str):
    return S.list_persons(user_id)


def get_person(person_id: str, user_id: str):
    return S.get_person(person_id, user_id)


def create_person(data: M.PersonCreate, user_id: str):
    return S.create_person(data, user_id)


def update_person(person_id: str, data: M.PersonUpdate, user_id: str):
    return S.update_person(person_id, data, user_id)


def delete_person(person_id: str, user_id: str):
    return S.delete_person(person_id, user_id)


# Capacity (with derived: activeWeeklyHours, capacityDelta, overcapacity)
def list_capacity_profiles(user_id: str):
    out = S.list_capacity_profiles(user_id)
    projects = S.list_projects(user_id)
    for r in out:
        D.add_capacity_derived(r, r["person_id"], projects)
    return out


def get_capacity_profile(person_id: str, user_id: str):
    out = S.get_capacity_profile(person_id, user_id)
    if out is not None:
        projects = S.list_projects(user_id)
        D.add_capacity_derived(out, person_id, projects)
    return out


def upsert_capacity_profile(data: M.CapacityProfileUpsert, user_id: str):
    return S.upsert_capacity_profile(data, user_id)


# Assets
def list_assets(user_id: str):
    return S.list_assets(user_id)


def get_asset(asset_id: str, user_id: str):
    return S.get_asset(asset_id, user_id)


def create_asset(data: M.AssetCreate, user_id: str):
    return S.create_asset(data, user_id)


def update_asset(asset_id: str, data: M.AssetUpdate, user_id: str):
    return S.update_asset(asset_id, data, user_id)


def delete_asset(asset_id: str, user_id: str):
    return S.delete_asset(asset_id, user_id)


# Decisions (append-only; for future personality learning)
def create_decision(data: M.DecisionCreate):
    return S.create_decision(data)


def list_decisions(user_id: str, entity_type: str | None = None, entity_id: str | None = None, limit: int = 500):
    """List decision rows owned by ``user_id`` — owner-scoped at storage.

    ``user_id`` is required (first positional); an empty or missing owner
    is rejected at the storage boundary, never silently unscoped.
    """
    return S.list_decisions(user_id, entity_type=entity_type, entity_id=entity_id, limit=limit)


def log_coordination_client_checkpoint(user_id: str, body: M.CoordinationClientCheckpointCreate) -> str:
    return S.log_coordination_client_checkpoint(
        user_id,
        body.checkpoint,
        body.entity_type,
        body.entity_id,
        user_outcome=body.user_outcome,
        action_intent=body.action_intent,
        trace_id=body.trace_id,
        detail=body.detail,
    )


def list_coordination_execution_flow_readings(user_id: str, entity_type: str, entity_id: str, limit: int = 20):
    from local_ai.vision_execution.coordination_signals import list_execution_flow_summaries_for_entity

    et = (entity_type or "").strip().lower()
    eid = (entity_id or "").strip()
    if not et or not eid:
        raise ValueError("entity_type and entity_id required")
    if et == ActivityEntityType.INITIATIVE.value:
        if S.get_initiative(eid, user_id) is None:
            raise ValueError("entity not found or not owned")
    elif et == ActivityEntityType.PROJECT.value:
        if S.get_project(eid, user_id) is None:
            raise ValueError("entity not found or not owned")
    elif et == ActivityEntityType.IDEA.value:
        if S.get_idea(eid, user_id) is None:
            raise ValueError("entity not found or not owned")
    else:
        raise ValueError("unsupported entity_type")
    return list_execution_flow_summaries_for_entity(user_id, et, eid, limit=limit)


# Radar (orientation summary + optional feed items e.g. meeting signals)
def get_radar(user_id: str):
    from . import radar as R
    return R.get_radar(user_id)


def create_radar_item(data: M.RadarFeedCreate):
    return S.create_radar_item(data)


# Content briefs
def list_content_briefs(user_id: str):
    return S.list_content_briefs(user_id)


def get_content_brief(brief_id: str, user_id: str):
    return S.get_content_brief(brief_id, user_id)


def create_content_brief(data: dict, user_id: str):
    return S.create_content_brief(data, user_id)


def update_content_brief(brief_id: str, data: dict, user_id: str):
    return S.update_content_brief(brief_id, data, user_id)


# Auth (Phase 1A)
def authenticate_user(email: str, password: str):
    return S.authenticate_user(email, password)


def create_session(user_id: str):
    return S.create_session(user_id)


def get_session_user(session_token: str):
    return S.get_session_user(session_token)


def get_user_by_email(email: str):
    return S.get_user_by_email(email)


def list_users():
    return S.list_users()


def revoke_session(session_token: str):
    return S.revoke_session(session_token)


def update_user_display_name(user_id: str, display_name: str):
    return S.update_user_display_name(user_id, display_name)


def patch_user_profile(user_id: str, fields: dict):
    return S.patch_user_profile(user_id, fields)


def create_user_account(email: str, password: str, display_name: str, *, is_admin: bool = False):
    return S.create_user_account(email, password, display_name, is_admin=is_admin)


# Shareability + matching (S2/S3/S4-lite)
def list_seat_requests(user_id: str):
    return S.list_seat_requests(user_id)


def get_seat_request(seat_request_id: str, user_id: str):
    return S.get_seat_request(seat_request_id, user_id)


def create_seat_request(data: M.SeatRequestCreate, user_id: str):
    return S.create_seat_request(data, user_id)


def update_seat_request(seat_request_id: str, data: M.SeatRequestUpdate, user_id: str):
    return S.update_seat_request(seat_request_id, data, user_id)


def delete_seat_request(seat_request_id: str, user_id: str):
    return S.delete_seat_request(seat_request_id, user_id)


def set_seat_request_share_state(seat_request_id: str, data: M.ShareStateUpdate, user_id: str):
    return S.set_seat_request_share_state(seat_request_id, data, user_id)


def candidate_offers_for_seat_request(seat_request_id: str, user_id: str, limit: int = 25):
    seat_request = S.get_seat_request(seat_request_id, user_id)
    if seat_request is None:
        return None
    return Match.candidate_offers_for_seat_request(seat_request, limit=limit)


def list_capability_offers(user_id: str):
    return S.list_capability_offers(user_id)


def get_capability_offer(offer_id: str, user_id: str):
    return S.get_capability_offer(offer_id, user_id)


def create_capability_offer(data: M.CapabilityOfferCreate, user_id: str):
    return S.create_capability_offer(data, user_id)


def update_capability_offer(offer_id: str, data: M.CapabilityOfferUpdate, user_id: str):
    return S.update_capability_offer(offer_id, data, user_id)


def delete_capability_offer(offer_id: str, user_id: str):
    return S.delete_capability_offer(offer_id, user_id)


def set_capability_offer_share_state(offer_id: str, data: M.ShareStateUpdate, user_id: str):
    return S.set_capability_offer_share_state(offer_id, data, user_id)


def candidate_requests_for_capability_offer(offer_id: str, user_id: str, limit: int = 25):
    offer = S.get_capability_offer(offer_id, user_id)
    if offer is None:
        return None
    return Match.candidate_requests_for_capability_offer(offer, limit=limit)


def list_material_requests(user_id: str):
    return S.list_material_requests(user_id)


def get_material_request(request_id: str, user_id: str):
    return S.get_material_request(request_id, user_id)


def create_material_request(data: M.MaterialRequestCreate, user_id: str):
    return S.create_material_request(data, user_id)


def update_material_request(request_id: str, data: M.MaterialRequestUpdate, user_id: str):
    return S.update_material_request(request_id, data, user_id)


def delete_material_request(request_id: str, user_id: str):
    return S.delete_material_request(request_id, user_id)


def set_material_request_share_state(request_id: str, data: M.ShareStateUpdate, user_id: str):
    return S.set_material_request_share_state(request_id, data, user_id)


def candidate_offers_for_material_request(request_id: str, user_id: str, limit: int = 25):
    request = S.get_material_request(request_id, user_id)
    if request is None:
        return None
    return Match.candidate_offers_for_material_request(request, limit=limit)


def list_material_offers(user_id: str):
    return S.list_material_offers(user_id)


def get_material_offer(offer_id: str, user_id: str):
    return S.get_material_offer(offer_id, user_id)


def create_material_offer(data: M.MaterialOfferCreate, user_id: str):
    return S.create_material_offer(data, user_id)


def update_material_offer(offer_id: str, data: M.MaterialOfferUpdate, user_id: str):
    return S.update_material_offer(offer_id, data, user_id)


def delete_material_offer(offer_id: str, user_id: str):
    return S.delete_material_offer(offer_id, user_id)


def set_material_offer_share_state(offer_id: str, data: M.ShareStateUpdate, user_id: str):
    return S.set_material_offer_share_state(offer_id, data, user_id)


def candidate_requests_for_material_offer(offer_id: str, user_id: str, limit: int = 25):
    offer = S.get_material_offer(offer_id, user_id)
    if offer is None:
        return None
    return Match.candidate_requests_for_material_offer(offer, limit=limit)


# Prompt signals (system prompts — engaged / dismissed / deferred)
def record_prompt_signal(
    user_id: str,
    *,
    prompt_id: str,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    prompt_summary: str = "",
    deferred_until: str | None = None,
):
    """
    engaged: user chose to discuss (not “resolved”).
    deferred: revisit later (not endorsement); optional entity scopes the reminder row.
    dismissed: suppress this exact ``prompt_id`` for the check window; NULL entity = global for reinjection.
    """
    return S.insert_prompt_signal(
        user_id,
        prompt_id=prompt_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        prompt_summary=prompt_summary,
        deferred_until=deferred_until,
    )


def should_show_prompt_after_dismiss(user_id: str, prompt_id: str, *, within_days: int = 7) -> bool:
    """
    False if this exact ``prompt_id`` was dismissed recently, or has an active defer (``deferred_until`` in the future).
    """
    if S.recently_dismissed_prompt(user_id, prompt_id, within_days=within_days):
        return False
    if S.active_future_defer_blocks_prompt(user_id, prompt_id):
        return False
    return True


def list_deferred_prompts_for_entity(user_id: str, entity_type: str, entity_id: str):
    """Compact, sorted deferred reminders for one entity (deduped, capped in storage)."""
    return S.list_active_deferred_prompts_for_entity(user_id, entity_type, entity_id)


# Workspace inbox (extraction handoff, matching context)
def list_workspace_users_directory(user_id: str):
    return S.list_workspace_users_directory(user_id)


def list_workspace_messages(user_id: str, box: str):
    return S.list_workspace_messages(user_id, box)


def create_workspace_message(from_user_id: str, data: M.WorkspaceMessageCreate):
    return S.create_workspace_message(from_user_id, data.to_user_id, data.title, data.body)


def mark_workspace_message_read(message_id: str, user_id: str) -> bool:
    return S.mark_workspace_message_read(message_id, user_id)


def count_unread_workspace_messages(user_id: str) -> int:
    return S.count_unread_workspace_messages(user_id)
