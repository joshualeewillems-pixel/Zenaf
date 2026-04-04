"""
Vision Execution Engine — business layer. Phase 1: thin pass-through to storage.
Phase 2+: derived fields, validation, council/AI orchestration.
"""
from local_ai.activity import ActivityEntityType

from . import models as M
from . import storage as S
from . import derived as D
from . import matching as Match


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
    return profiles[0] if profiles else None


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
    return S.delete_project(project_id, user_id)


# Tasks
def list_tasks(user_id: str, project_id: str | None = None):
    return S.list_tasks(user_id, project_id)


def get_task(task_id: str, user_id: str):
    return S.get_task(task_id, user_id)


def create_task(data: M.TaskCreate, user_id: str):
    return S.create_task(data, user_id)


def update_task(task_id: str, data: M.TaskUpdate, user_id: str):
    return S.update_task(task_id, data, user_id)


def delete_task(task_id: str, user_id: str):
    return S.delete_task(task_id, user_id)


# Persons
def list_persons():
    return S.list_persons()


def get_person(person_id: str):
    return S.get_person(person_id)


def create_person(data: M.PersonCreate):
    return S.create_person(data)


def update_person(person_id: str, data: M.PersonUpdate):
    return S.update_person(person_id, data)


def delete_person(person_id: str):
    return S.delete_person(person_id)


# Capacity (with derived: activeWeeklyHours, capacityDelta, overcapacity)
def list_capacity_profiles(user_id: str | None = None):
    out = S.list_capacity_profiles()
    projects = S.list_projects(user_id) if user_id is not None else S.list_projects()
    for r in out:
        D.add_capacity_derived(r, r["person_id"], projects)
    return out


def get_capacity_profile(person_id: str, user_id: str | None = None):
    out = S.get_capacity_profile(person_id)
    if out is not None:
        projects = S.list_projects(user_id) if user_id is not None else S.list_projects()
        D.add_capacity_derived(out, person_id, projects)
    return out


def upsert_capacity_profile(data: M.CapacityProfileUpsert):
    return S.upsert_capacity_profile(data)


# Assets
def list_assets():
    return S.list_assets()


def get_asset(asset_id: str):
    return S.get_asset(asset_id)


def create_asset(data: M.AssetCreate):
    return S.create_asset(data)


def update_asset(asset_id: str, data: M.AssetUpdate):
    return S.update_asset(asset_id, data)


def delete_asset(asset_id: str):
    return S.delete_asset(asset_id)


# Decisions (append-only; for future personality learning)
def create_decision(data: M.DecisionCreate):
    return S.create_decision(data)


def list_decisions(entity_type: str | None = None, entity_id: str | None = None, limit: int = 500):
    return S.list_decisions(entity_type=entity_type, entity_id=entity_id, limit=limit)


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
