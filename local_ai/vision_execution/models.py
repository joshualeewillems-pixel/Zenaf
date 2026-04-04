"""
Vision Execution Engine — Pydantic models for API and status enums.

# ARCHITECTURE NOTE:
# These entities currently exist as concrete business modules.
# Long-term they may be treated as typed expressions of a generic
# Subject/Node primitive to support Mandelbrot-scaling decision architecture.
"""
from datetime import datetime, timezone
from typing import Any, Literal
import uuid
from pydantic import BaseModel, Field, field_validator

# --- Status enums (TEXT in DB) ---
IDEA_STATUS = Literal[
    "Captured", "Clarifying", "Contextualized", "Evaluated", "Advanced", "Parked", "Archived"
]
INITIATIVE_STATUS = Literal[
    "Draft", "Evaluating", "Approved", "Active", "Paused", "Complete", "Killed"
]
PROJECT_STATUS = Literal[
    "Draft", "Ready", "Active", "Blocked", "Complete", "Parked"
]
TASK_STATUS = Literal[
    "Todo", "In Progress", "Blocked", "Done", "Dropped"
]
SHARE_VISIBILITY = Literal["private", "shared_unindexed", "shared_indexed", "revoked", "inactive", "deleted"]
SHARE_INDEX_STATE = Literal["private", "shared_unindexed", "shared_indexed", "revoked", "inactive", "deleted"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


# --- Request/response shapes (snake_case for API) ---

class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str


class UserSelfUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=240)
    avatar_data_url: str | None = Field(default=None, max_length=350_000)

    model_config = {"populate_by_name": True}


class AdminUserCreate(BaseModel):
    """Admin-only: create a login account (local / ops use)."""

    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=1, max_length=256)
    display_name: str = Field(default="", max_length=240)
    is_admin: bool = False


class SettingsLLMProfileUpdate(BaseModel):
    default_provider: str = "ollama"
    default_model: str | None = None
    ollama_base_url: str | None = None
    ollama_model: str | None = None


class SettingsLLMCredentialBody(BaseModel):
    api_key: str = Field(..., min_length=1, max_length=2048)


class SettingsLLMTestBody(BaseModel):
    provider: str
    api_key: str | None = Field(default=None, max_length=2048)
    model: str | None = Field(default=None, max_length=256)


class SettingsLLMProviderEnabledBody(BaseModel):
    enabled: bool = True


class SettingsCouncilSeatLLMBody(BaseModel):
    """Council seat LLM routing: ``auto`` = policy default for that run."""

    llm_provider: str = Field(default="auto", max_length=32)


class CouncilWorkspacePerspectivesPut(BaseModel):
    """Perspective agent list for Workspace council (server source of truth when signed in)."""

    perspectives: list[Any] = Field(default_factory=list)

    @field_validator("perspectives")
    @classmethod
    def _cap_list(cls, v: list[Any]) -> list[Any]:
        if len(v) > 200:
            raise ValueError("Too many perspective agents (max 200)")
        return v


class SettingsNotificationUpdate(BaseModel):
    prefs: dict[str, Any] = Field(default_factory=dict)


class SettingsPermissionsUpdate(BaseModel):
    consent_acknowledged: bool = False
    consent_version: str = Field(default="", max_length=64)
    permissions: dict[str, bool] = Field(default_factory=dict)

class CoreProfileCreate(BaseModel):
    name: str = ""
    core_definition: str = ""
    current_goals: str = ""
    growth_focus_12_months: str = ""
    economic_engine: str = ""
    non_negotiables: str = ""
    strategic_filter: str = ""
    current_constraints: str = ""
    capacity_limit: str = ""
    kill_philosophy: str = ""
    strength_positioning: str = ""
    raw_notes: str = ""


class CoreProfileUpdate(BaseModel):
    name: str | None = None
    core_definition: str | None = None
    current_goals: str | None = None
    growth_focus_12_months: str | None = None
    economic_engine: str | None = None
    non_negotiables: str | None = None
    strategic_filter: str | None = None
    current_constraints: str | None = None
    capacity_limit: str | None = None
    kill_philosophy: str | None = None
    strength_positioning: str | None = None
    raw_notes: str | None = None


class AspirationProfileUpsert(BaseModel):
    """Create/replace aspiration profile fields (user-owned)."""

    core_aim: str = ""
    growth_domains: list[str] = Field(default_factory=list)
    current_edge: str = ""
    current_obstacles: str = ""
    near_term_aspirations: str = ""
    long_term_aspirations: str = ""
    guidance_preferences: dict[str, Any] = Field(default_factory=dict)
    anti_goals: str = ""
    use_in_guidance: bool = False
    allow_inference: bool = False


class AspirationProfilePatch(BaseModel):
    """Partial update for aspiration profile."""

    core_aim: str | None = None
    growth_domains: list[str] | None = None
    current_edge: str | None = None
    current_obstacles: str | None = None
    near_term_aspirations: str | None = None
    long_term_aspirations: str | None = None
    guidance_preferences: dict[str, Any] | None = None
    anti_goals: str | None = None
    use_in_guidance: bool | None = None
    allow_inference: bool | None = None


class IdeaCreate(BaseModel):
    title: str = ""
    summary: str = ""
    description: str = ""
    status: str = "Captured"
    tags: list[str] = Field(default_factory=list)
    created_by: str = ""
    desired_outcome: str = ""
    linked_people: list[str] = Field(default_factory=list)
    linked_assets: list[str] = Field(default_factory=list)
    linked_ideas: list[str] = Field(default_factory=list)
    notes: str = ""


class IdeaUpdate(BaseModel):
    title: str | None = None
    summary: str | None = None
    description: str | None = None
    status: str | None = None
    tags: list[str] | None = None
    created_by: str | None = None
    desired_outcome: str | None = None
    linked_people: list[str] | None = None
    linked_assets: list[str] | None = None
    linked_ideas: list[str] | None = None
    notes: str | None = None


class InitiativeSeat(BaseModel):
    role: str = ""
    assigned_person_id: str | None = None
    estimated_effort: str | None = None
    notes: str | None = ""


class InitiativeCreate(BaseModel):
    source_idea_id: str | None = None
    title: str = ""
    brief: str = ""
    status: str = "Draft"
    owner_id: str | None = None
    priority_rank_manual: int | None = None
    strategic_value_manual: int | None = None
    energy_impact_manual: int | None = None
    # Model-suggested priority (0–5); preserved for human vs model delta learning.
    evaluation_priority: int | None = None
    estimated_cost_ai: str = ""
    estimated_timeframe_ai: str = ""
    philosophical_alignment_ai: str = ""
    next_step_ai: str = ""
    # Legacy seat transport (reserved for backward compatibility).
    # Prefer `seats` going forward.
    required_people: list[str] = Field(default_factory=list)
    seats: list[InitiativeSeat] = Field(default_factory=list)
    required_assets: list[str] = Field(default_factory=list)
    dependencies: str = ""
    risks: str = ""
    recommendation: str = ""
    counts_toward_capacity: int = 1
    manual_override: str = ""
    kill_criteria: str = ""
    notes: str = ""


class InitiativeUpdate(BaseModel):
    source_idea_id: str | None = None
    title: str | None = None
    brief: str | None = None
    status: str | None = None
    owner_id: str | None = None
    priority_rank_manual: int | None = None
    strategic_value_manual: int | None = None
    energy_impact_manual: int | None = None
    evaluation_priority: int | None = None
    estimated_cost_ai: str | None = None
    estimated_timeframe_ai: str | None = None
    philosophical_alignment_ai: str | None = None
    next_step_ai: str | None = None
    # Legacy seat transport (reserved for backward compatibility).
    required_people: list[str] | None = None
    seats: list[InitiativeSeat] | None = None
    required_assets: list[str] | None = None
    dependencies: str | None = None
    risks: str | None = None
    recommendation: str | None = None
    counts_toward_capacity: int | None = None
    manual_override: str | None = None
    kill_criteria: str | None = None
    notes: str | None = None


class ExecutionStepCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=4000)
    sort_order: int | None = None


class ExecutionStepUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=4000)
    sort_order: int | None = None
    is_done: bool | None = None


class ExecutionStepReorderBody(BaseModel):
    ordered_ids: list[str] = Field(..., min_length=1)


class ExecutionStepMaterializeBody(BaseModel):
    """Materialize titles into rows. If rows already exist, replace must be True or API returns 409."""

    titles: list[str] = Field(..., min_length=1, max_length=20)
    replace: bool = False
    source: Literal["ai", "import", "user"] = "ai"


class FocusFieldRewriteRequest(BaseModel):
    """Context Action Bar — rewrite focused VE field (review in UI; not auto-applied)."""

    entity_type: Literal["initiative", "idea"]
    entity_id: str = Field(..., min_length=1, max_length=80)
    field_key: str = Field(..., min_length=1, max_length=120)
    field_label: str = Field("", max_length=200)
    text_override: str | None = Field(None, max_length=12000)


class FocusFieldRewriteResponse(BaseModel):
    rewritten_text: str = ""
    error: str | None = None
    source: Literal["override", "stored"] = "stored"


class ProjectCreate(BaseModel):
    initiative_id: str | None = None
    title: str = ""
    brief: str = ""
    status: str = "Draft"
    owner_id: str | None = None
    supporting_owner_ids: list[str] = Field(default_factory=list)
    required_assets: list[str] = Field(default_factory=list)
    priority: str = ""
    start_date: str | None = None
    end_date: str | None = None
    estimated_weekly_hours: float | None = None
    deliverables: str = ""
    complexity: str = ""
    current_focus: str = ""
    next_step_ai: str = ""
    notes: str = ""


class ProjectUpdate(BaseModel):
    initiative_id: str | None = None
    title: str | None = None
    brief: str | None = None
    status: str | None = None
    owner_id: str | None = None
    supporting_owner_ids: list[str] | None = None
    priority: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    estimated_weekly_hours: float | None = None
    deliverables: str | None = None
    complexity: str | None = None
    current_focus: str | None = None
    next_step_ai: str | None = None
    notes: str | None = None


class TaskCreate(BaseModel):
    project_id: str | None = None
    parent_task_id: str | None = None
    title: str = ""
    description: str = ""
    assignee_id: str | None = None
    status: str = "Todo"
    priority: str = ""
    estimated_hours: float | None = None
    due_date: str | None = None
    dependency_ids: list[str] = Field(default_factory=list)
    required_asset_ids: list[str] = Field(default_factory=list)
    completion_criteria: str = ""
    notes: str = ""


class TaskUpdate(BaseModel):
    project_id: str | None = None
    parent_task_id: str | None = None
    title: str | None = None
    description: str | None = None
    assignee_id: str | None = None
    status: str | None = None
    priority: str | None = None
    estimated_hours: float | None = None
    due_date: str | None = None
    dependency_ids: list[str] | None = None
    required_asset_ids: list[str] | None = None
    completion_criteria: str | None = None
    notes: str | None = None


class SeatRequestCreate(BaseModel):
    title: str = ""
    summary: str = ""
    context_type: str = ""
    context_id: str | None = None
    role_tags: list[str] = Field(default_factory=list)
    capability_tags: list[str] = Field(default_factory=list)
    availability_window: str | None = None
    commitment_type: str = ""
    collaboration_mode: str = ""
    timezone_pref: str = ""
    share_until: str | None = None


class SeatRequestUpdate(BaseModel):
    title: str | None = None
    summary: str | None = None
    context_type: str | None = None
    context_id: str | None = None
    role_tags: list[str] | None = None
    capability_tags: list[str] | None = None
    availability_window: str | None = None
    commitment_type: str | None = None
    collaboration_mode: str | None = None
    timezone_pref: str | None = None
    share_until: str | None = None
    is_active: bool | None = None


class CapabilityOfferCreate(BaseModel):
    title: str = ""
    summary: str = ""
    capability_tags: list[str] = Field(default_factory=list)
    role_tags: list[str] = Field(default_factory=list)
    availability_window: str | None = None
    commitment_type: str = ""
    collaboration_mode: str = ""
    timezone_pref: str = ""
    share_until: str | None = None


class CapabilityOfferUpdate(BaseModel):
    title: str | None = None
    summary: str | None = None
    capability_tags: list[str] | None = None
    role_tags: list[str] | None = None
    availability_window: str | None = None
    commitment_type: str | None = None
    collaboration_mode: str | None = None
    timezone_pref: str | None = None
    share_until: str | None = None
    is_active: bool | None = None


class WorkspaceMessageCreate(BaseModel):
    """User-to-user workspace inbox payload (e.g. extraction candidate + optional matching refs)."""

    to_user_id: str
    title: str = ""
    body: dict[str, Any] = Field(default_factory=dict)


class ShareStateUpdate(BaseModel):
    visibility: SHARE_VISIBILITY
    index_state: SHARE_INDEX_STATE
    consent_version: str = ""
    share_until: str | None = None


class MaterialRequestCreate(BaseModel):
    title: str = ""
    summary: str = ""
    material_type: str = ""
    resource_nature: str = ""
    category_tags: list[str] = Field(default_factory=list)
    quantity_needed: float = 0
    quantity_unit: str = ""
    availability_start: str | None = None
    availability_end: str | None = None
    condition_min: str = ""
    access_mode: str = ""
    location_region: str = ""
    max_distance_km: float | None = None
    usage_constraints: list[str] = Field(default_factory=list)
    cost_band_max: str = ""
    share_until: str | None = None


class MaterialRequestUpdate(BaseModel):
    title: str | None = None
    summary: str | None = None
    material_type: str | None = None
    resource_nature: str | None = None
    category_tags: list[str] | None = None
    quantity_needed: float | None = None
    quantity_unit: str | None = None
    availability_start: str | None = None
    availability_end: str | None = None
    condition_min: str | None = None
    access_mode: str | None = None
    location_region: str | None = None
    max_distance_km: float | None = None
    usage_constraints: list[str] | None = None
    cost_band_max: str | None = None
    share_until: str | None = None
    is_active: bool | None = None


class MaterialOfferCreate(BaseModel):
    title: str = ""
    summary: str = ""
    material_type: str = ""
    resource_nature: str = ""
    category_tags: list[str] = Field(default_factory=list)
    quantity_available: float = 0
    quantity_unit: str = ""
    availability_start: str | None = None
    availability_end: str | None = None
    condition_state: str = ""
    access_mode: str = ""
    location_region: str = ""
    service_area_km: float | None = None
    usage_constraints: list[str] = Field(default_factory=list)
    cost_band: str = ""
    share_until: str | None = None


class MaterialOfferUpdate(BaseModel):
    title: str | None = None
    summary: str | None = None
    material_type: str | None = None
    resource_nature: str | None = None
    category_tags: list[str] | None = None
    quantity_available: float | None = None
    quantity_unit: str | None = None
    availability_start: str | None = None
    availability_end: str | None = None
    condition_state: str | None = None
    access_mode: str | None = None
    location_region: str | None = None
    service_area_km: float | None = None
    usage_constraints: list[str] | None = None
    cost_band: str | None = None
    share_until: str | None = None
    is_active: bool | None = None


class PersonCreate(BaseModel):
    name: str = ""
    role: str = ""
    relationship_type: str = ""
    contact_info: str = ""
    strengths: str = ""
    needs: str = ""
    wants: str = ""
    availability: str = ""
    notes: str = ""


class PersonUpdate(BaseModel):
    name: str | None = None
    role: str | None = None
    relationship_type: str | None = None
    contact_info: str | None = None
    strengths: str | None = None
    needs: str | None = None
    wants: str | None = None
    availability: str | None = None
    notes: str | None = None


class CapacityProfileUpsert(BaseModel):
    person_id: str
    weekly_capacity_hours: float = 0


class AssetCreate(BaseModel):
    name: str = ""
    asset_type: str = ""
    owner_id: str | None = None
    status: str = ""
    availability: str = ""
    cost: str = ""
    time_availability: str = ""
    linked_idea_ids: list[str] = Field(default_factory=list)
    linked_initiative_ids: list[str] = Field(default_factory=list)
    linked_project_ids: list[str] = Field(default_factory=list)
    notes: str = ""


class AssetUpdate(BaseModel):
    name: str | None = None
    asset_type: str | None = None
    owner_id: str | None = None
    status: str | None = None
    availability: str | None = None
    cost: str | None = None
    time_availability: str | None = None
    linked_idea_ids: list[str] | None = None
    linked_initiative_ids: list[str] | None = None
    linked_project_ids: list[str] | None = None
    notes: str | None = None


# --- Decision record (for future personality learning; append-only) ---
class DecisionCreate(BaseModel):
    user_id: str | None = None
    entity_type: str  # e.g. "initiative", "project"
    entity_id: str
    decision_type: str  # e.g. "evaluation_applied", "initiative_approved", "initiative_rejected", "priority_change", "manual_score_override"
    ai_proposal_snapshot: dict[str, Any] | None = None
    final_values_snapshot: dict[str, Any] | None = None


class CoordinationClientCheckpointCreate(BaseModel):
    """Client-reported coordination checkpoint (``ActivityEvent.source`` = atria-client-trace)."""

    checkpoint: Literal["ai_action_user_trace", "ai_suggestion_applied"]
    entity_type: str = Field(..., max_length=64)
    entity_id: str = Field(..., max_length=128)
    user_outcome: str | None = Field(None, max_length=64)
    action_intent: str | None = Field(None, max_length=512)
    trace_id: str | None = Field(None, max_length=256)
    detail: str | None = Field(None, max_length=2000)


# --- Radar feed (meeting-extraction signals, etc.) ---
class RadarFeedCreate(BaseModel):
    title: str = ""
    detail: str = ""
    severity: str = "medium"
    source: str = "meeting-extraction"
    source_excerpt: str | None = None
    kind: str = "attention"  # attention | risk | opportunity | blocker


# --- Meeting extract (intake only; no storage) ---


class _ExtractionContextInitiative(BaseModel):
    id: str = ""
    title: str = ""


class _ExtractionContextProject(BaseModel):
    id: str = ""
    title: str = ""
    initiative_id: str | None = Field(None, alias="initiativeId")
    initiative_title: str | None = Field(None, alias="initiativeTitle")


class _ExtractionContextTask(BaseModel):
    id: str = ""
    title: str = ""
    project_id: str | None = Field(None, alias="projectId")
    project_title: str | None = Field(None, alias="projectTitle")
    initiative_id: str | None = Field(None, alias="initiativeId")
    initiative_title: str | None = Field(None, alias="initiativeTitle")


class _ExtractionContextAsset(BaseModel):
    id: str = ""
    name: str = ""
    kind: str | None = None


class _ExtractionContextPerson(BaseModel):
    id: str = ""
    name: str = ""
    role: str | None = None


class ExtractionContextModel(BaseModel):
    initiatives: list[_ExtractionContextInitiative] = []
    projects: list[_ExtractionContextProject] = []
    tasks: list[_ExtractionContextTask] = []
    assets: list[_ExtractionContextAsset] = []
    people: list[_ExtractionContextPerson] = []


class WorkspaceReasoningCapsuleModel(BaseModel):
    themes: list[str] = Field(default_factory=list)
    named_programs: list[str] = Field(default_factory=list, alias="namedPrograms")
    tags: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class WorkspaceContextPacketModel(BaseModel):
    """Prebuilt workspace mirror: Pass 0 anchors + optional reasoning capsule. No filesystem on server."""

    schema_version: int | None = Field(None, alias="schemaVersion")
    domain_hints: list[str] = Field(default_factory=list, alias="domainHints")
    literal_anchors: list[str] = Field(default_factory=list, alias="literalAnchors")
    reasoning_capsule: WorkspaceReasoningCapsuleModel | None = Field(None, alias="reasoningCapsule")

    model_config = {"populate_by_name": True}


class ExtractMeetingRequest(BaseModel):
    notes: str = ""
    context: ExtractionContextModel | None = None
    workspace_packet: WorkspaceContextPacketModel | None = Field(None, alias="workspacePacket")
    profile_id: str | None = Field(None, alias="profileId")
    return_diagnostics: bool = Field(False, alias="returnDiagnostics")
    include_harvest_ledger: bool = Field(True, alias="includeHarvestLedger")
    routing_context: dict[str, Any] | None = Field(None, alias="routingContext")
    evidence_extraction_preset: Literal["default", "fast_local", "exhaustive"] = Field(
        "default",
        alias="evidenceExtractionPreset",
    )
    include_meeting_polish: bool = Field(False, alias="includeMeetingPolish")
    use_external_ai_extraction: bool = Field(False, alias="useExternalAiExtraction")
    external_ai_engine: str | None = Field(None, alias="externalAiEngine")
    wash_data_for_call: bool = Field(True, alias="washDataForCall")

    model_config = {"populate_by_name": True}

    @field_validator("evidence_extraction_preset", mode="before")
    @classmethod
    def _normalize_evidence_extraction_preset(cls, v: Any) -> str:
        if v is None or v == "":
            return "default"
        s = str(v).strip().lower().replace("-", "_")
        if s in ("fast_local", "fastlocal", "interactive"):
            return "fast_local"
        if s in ("exhaustive", "batch", "offline"):
            return "exhaustive"
        return "default"


class ExtractSegmentSummaryRequest(BaseModel):
    """Request for lightweight per-segment summary (long-meeting hierarchical path)."""
    notes: str = ""
    prior_context: dict | None = Field(default=None, alias="priorContext")
    routing_context: dict[str, Any] | None = Field(None, alias="routingContext")

    model_config = {"populate_by_name": True}


class _CandidateSignal(BaseModel):
    kind: str = "attention"
    label: str | None = None
    detail: str | None = None


class _SegmentSummaryItem(BaseModel):
    segment_id: str = Field("", alias="segmentId")
    segment_title: str = Field("", alias="segmentTitle")
    topic: str = ""
    brief_summary: str = Field("", alias="briefSummary")
    candidate_tasks: list[str] = Field(default_factory=list, alias="candidateTasks")
    candidate_entities: list[str] = Field(default_factory=list, alias="candidateEntities")
    candidate_signals: list[_CandidateSignal] = Field(default_factory=list, alias="candidateSignals")

    model_config = {"populate_by_name": True}


class ExtractMeetingSegmentsRequest(BaseModel):
    """Request for segment summaries with rolling prior_context (long-meeting chunk pipeline)."""
    segment_texts: list[str] = Field(default_factory=list, alias="segmentTexts")
    profile_id: str | None = Field(None, alias="profileId")
    return_diagnostics: bool = Field(False, alias="returnDiagnostics")
    routing_context: dict[str, Any] | None = Field(None, alias="routingContext")

    model_config = {"populate_by_name": True}


class ExtractMeetingSynthesisRequest(BaseModel):
    """Request for one full extraction from segment summaries (long-meeting hierarchical path)."""
    segment_summaries: list[_SegmentSummaryItem] = Field(default_factory=list, alias="segmentSummaries")
    context: ExtractionContextModel | None = None
    profile_id: str | None = Field(None, alias="profileId")
    return_diagnostics: bool = Field(False, alias="returnDiagnostics")
    include_harvest_ledger: bool = Field(True, alias="includeHarvestLedger")
    used_rolling_prior: bool = Field(False, alias="usedRollingPrior")
    segment_diagnostics: dict | None = Field(None, alias="segmentDiagnostics")
    routing_context: dict[str, Any] | None = Field(None, alias="routingContext")
    include_meeting_polish: bool = Field(False, alias="includeMeetingPolish")

    model_config = {"populate_by_name": True}


class WorkspaceIdentityScanRequest(BaseModel):
    """Bounded local scan; writes gitignored snapshot under repo .atria/workspace-identity/v1/."""

    roots: list[str] = Field(default_factory=list)
    mode: Literal["deep_initial", "light_refresh"] = "deep_initial"

    model_config = {"populate_by_name": True}


class WorkspaceTranslationTemplateBody(BaseModel):
    """Circumstance-specific workspace layer for packet merge (translation-template.json)."""

    preferred_phrases: list[str] = Field(default_factory=list, alias="preferredPhrases")
    blocked_phrases: list[str] = Field(default_factory=list, alias="blockedPhrases")
    block_from_mirror: list[str] = Field(default_factory=list, alias="blockFromMirror")
    always_allow: list[str] = Field(default_factory=list, alias="alwaysAllow")
    aliases: dict[str, str] = Field(default_factory=dict)
    functional_mappings: dict[str, Any] = Field(default_factory=dict, alias="functionalMappings")
    functional_hints: list[str] = Field(default_factory=list, alias="functionalHints")
    structural_hints: list[str] = Field(default_factory=list, alias="structuralHints")

    model_config = {"populate_by_name": True}


def _json_dumps_list(a: list[str]) -> str:
    import json
    return json.dumps(a if a is not None else [])


def _json_loads_list(s: str | None) -> list[str]:
    import json
    if s is None or (isinstance(s, str) and not s.strip()):
        return []
    try:
        out = json.loads(s) if isinstance(s, str) else s
        return list(out) if isinstance(out, list) else []
    except Exception:
        return []


def _json_dumps_obj(obj: dict[str, Any] | None) -> str:
    import json
    return json.dumps(obj) if obj is not None else "{}"


def _json_loads_obj(s: str | None) -> dict[str, Any]:
    import json
    if s is None or (isinstance(s, str) and not s.strip()):
        return {}
    try:
        out = json.loads(s) if isinstance(s, str) else s
        return dict(out) if isinstance(out, dict) else {}
    except Exception:
        return {}


def row_to_core_profile(row: tuple) -> dict[str, Any]:
    # 16 cols: ... raw_notes, is_primary, created_at, updated_at
    # 15 cols: ... raw_notes, created_at, updated_at (is_primary missing → False)
    # 14 cols: legacy without raw_notes
    n = len(row)
    if n >= 16:
        return {
            "id": row[0], "name": row[1], "core_definition": row[2], "current_goals": row[3],
            "growth_focus_12_months": row[4], "economic_engine": row[5], "non_negotiables": row[6],
            "strategic_filter": row[7], "current_constraints": row[8], "capacity_limit": row[9],
            "kill_philosophy": row[10], "strength_positioning": row[11], "raw_notes": row[12] or "",
            "is_primary": bool(row[13]), "created_at": row[14], "updated_at": row[15],
        }
    if n >= 15:
        return {
            "id": row[0], "name": row[1], "core_definition": row[2], "current_goals": row[3],
            "growth_focus_12_months": row[4], "economic_engine": row[5], "non_negotiables": row[6],
            "strategic_filter": row[7], "current_constraints": row[8], "capacity_limit": row[9],
            "kill_philosophy": row[10], "strength_positioning": row[11], "raw_notes": row[12] or "",
            "is_primary": False,
            "created_at": row[13], "updated_at": row[14],
        }
    return {
        "id": row[0], "name": row[1], "core_definition": row[2], "current_goals": row[3],
        "growth_focus_12_months": row[4], "economic_engine": row[5], "non_negotiables": row[6],
        "strategic_filter": row[7], "current_constraints": row[8], "capacity_limit": row[9],
        "kill_philosophy": row[10], "strength_positioning": row[11], "raw_notes": "",
        "is_primary": False,
        "created_at": row[12], "updated_at": row[13],
    }


def row_to_idea(row: tuple) -> dict[str, Any]:
    notes_val = (row[13] or "") if len(row) >= 14 else ""
    return {
        "id": row[0], "title": row[1], "summary": row[2], "description": row[3], "status": row[4],
        "tags": _json_loads_list(row[5]), "created_by": row[6], "desired_outcome": row[7],
        "linked_people": _json_loads_list(row[8]), "linked_assets": _json_loads_list(row[9]),
        "linked_ideas": _json_loads_list(row[10]), "created_at": row[11], "updated_at": row[12],
        "notes": notes_val,
    }


def row_to_initiative(row: tuple) -> dict[str, Any]:
    return {
        "id": row[0], "source_idea_id": row[1], "title": row[2], "brief": row[3], "status": row[4],
        "owner_id": row[5], "priority_rank_manual": row[6], "strategic_value_manual": row[7],
        "energy_impact_manual": row[8], "evaluation_priority": row[9],
        "estimated_cost_ai": row[10], "estimated_timeframe_ai": row[11],
        "philosophical_alignment_ai": row[12], "next_step_ai": row[13],
        "required_people": _json_loads_list(row[14]), "required_assets": _json_loads_list(row[15]),
        "dependencies": row[16], "risks": row[17], "recommendation": row[18],
        "counts_toward_capacity": row[19], "manual_override": row[20], "kill_criteria": row[21],
        "notes": row[22], "created_at": row[23], "updated_at": row[24],
    }


def row_to_execution_step(row: tuple) -> dict[str, Any]:
    return {
        "id": row[0],
        "user_id": row[1],
        "scope_type": row[2],
        "scope_id": row[3],
        "title": row[4] or "",
        "sort_order": row[5],
        "is_done": bool(row[6]),
        "completed_at": row[7],
        "source": row[8] or "user",
        "source_evaluation_id": row[9],
        "created_at": row[10],
        "updated_at": row[11],
    }


def row_to_project(row: tuple) -> dict[str, Any]:
    # With required_assets: 19 columns; without (legacy): 18 columns
    n = len(row)
    required_assets = _json_loads_list(row[7]) if n > 7 else []
    return {
        "id": row[0], "initiative_id": row[1], "title": row[2], "brief": row[3], "status": row[4],
        "owner_id": row[5], "supporting_owner_ids": _json_loads_list(row[6]), "required_assets": required_assets,
        "priority": row[8] if n > 8 else "", "start_date": row[9] if n > 9 else None, "end_date": row[10] if n > 10 else None,
        "estimated_weekly_hours": row[11] if n > 11 else None, "deliverables": row[12] if n > 12 else "",
        "complexity": row[13] if n > 13 else "", "current_focus": row[14] if n > 14 else "",
        "next_step_ai": row[15] if n > 15 else "", "notes": row[16] if n > 16 else "",
        "created_at": row[17] if n > 17 else "", "updated_at": row[18] if n > 18 else "",
    }


def row_to_task(row: tuple) -> dict[str, Any]:
    n = len(row)
    return {
        "id": row[0], "project_id": row[1], "parent_task_id": row[2], "title": row[3],
        "description": row[4], "assignee_id": row[5], "status": row[6], "priority": row[7],
        "estimated_hours": row[8], "due_date": row[9], "dependency_ids": _json_loads_list(row[10]),
        "required_asset_ids": _json_loads_list(row[11]) if n > 11 else [],
        "completion_criteria": row[12] if n > 12 else "", "notes": row[13] if n > 13 else "",
        "created_at": row[14] if n > 14 else "", "updated_at": row[15] if n > 15 else "",
    }


def row_to_person(row: tuple) -> dict[str, Any]:
    return {
        "id": row[0], "name": row[1], "role": row[2], "relationship_type": row[3],
        "contact_info": row[4], "strengths": row[5], "needs": row[6], "wants": row[7],
        "availability": row[8], "notes": row[9], "created_at": row[10], "updated_at": row[11],
    }


def row_to_capacity(row: tuple) -> dict[str, Any]:
    return {"person_id": row[0], "weekly_capacity_hours": row[1], "created_at": row[2], "updated_at": row[3]}


def row_to_asset(row: tuple) -> dict[str, Any]:
    return {
        "id": row[0], "name": row[1], "asset_type": row[2], "owner_id": row[3], "status": row[4],
        "availability": row[5], "cost": row[6], "time_availability": row[7],
        "linked_idea_ids": _json_loads_list(row[8]), "linked_initiative_ids": _json_loads_list(row[9]),
        "linked_project_ids": _json_loads_list(row[10]), "notes": row[11],
        "created_at": row[12], "updated_at": row[13],
    }


def row_to_decision(row: tuple) -> dict[str, Any]:
    return {
        "id": row[0], "user_id": row[1], "entity_type": row[2], "entity_id": row[3],
        "decision_type": row[4], "ai_proposal_snapshot": _json_loads_obj(row[5]),
        "final_values_snapshot": _json_loads_obj(row[6]), "created_at": row[7],
    }


def row_to_seat_request(row: tuple) -> dict[str, Any]:
    return {
        "id": row[0],
        "user_id": row[1],
        "title": row[2],
        "summary": row[3],
        "context_type": row[4],
        "context_id": row[5],
        "role_tags": _json_loads_list(row[6]),
        "capability_tags": _json_loads_list(row[7]),
        "availability_window": row[8],
        "commitment_type": row[9],
        "collaboration_mode": row[10],
        "timezone_pref": row[11],
        "visibility": row[12],
        "index_state": row[13],
        "consent_version": row[14],
        "consent_at": row[15],
        "share_until": row[16],
        "share_revoked_at": row[17],
        "state_changed_at": row[18],
        "is_active": bool(row[19]),
        "created_at": row[20],
        "updated_at": row[21],
    }


def row_to_capability_offer(row: tuple) -> dict[str, Any]:
    return {
        "id": row[0],
        "user_id": row[1],
        "title": row[2],
        "summary": row[3],
        "capability_tags": _json_loads_list(row[4]),
        "role_tags": _json_loads_list(row[5]),
        "availability_window": row[6],
        "commitment_type": row[7],
        "collaboration_mode": row[8],
        "timezone_pref": row[9],
        "visibility": row[10],
        "index_state": row[11],
        "consent_version": row[12],
        "consent_at": row[13],
        "share_until": row[14],
        "share_revoked_at": row[15],
        "state_changed_at": row[16],
        "is_active": bool(row[17]),
        "created_at": row[18],
        "updated_at": row[19],
    }


def row_to_material_request(row: tuple) -> dict[str, Any]:
    return {
        "id": row[0],
        "user_id": row[1],
        "title": row[2],
        "summary": row[3],
        "material_type": row[4],
        "resource_nature": row[5],
        "category_tags": _json_loads_list(row[6]),
        "quantity_needed": float(row[7] or 0),
        "quantity_unit": row[8],
        "availability_start": row[9],
        "availability_end": row[10],
        "condition_min": row[11],
        "access_mode": row[12],
        "location_region": row[13],
        "max_distance_km": row[14],
        "usage_constraints": _json_loads_list(row[15]),
        "cost_band_max": row[16],
        "visibility": row[17],
        "index_state": row[18],
        "consent_version": row[19],
        "consent_at": row[20],
        "share_until": row[21],
        "share_revoked_at": row[22],
        "state_changed_at": row[23],
        "is_active": bool(row[24]),
        "created_at": row[25],
        "updated_at": row[26],
    }


def row_to_material_offer(row: tuple) -> dict[str, Any]:
    return {
        "id": row[0],
        "user_id": row[1],
        "title": row[2],
        "summary": row[3],
        "material_type": row[4],
        "resource_nature": row[5],
        "category_tags": _json_loads_list(row[6]),
        "quantity_available": float(row[7] or 0),
        "quantity_unit": row[8],
        "availability_start": row[9],
        "availability_end": row[10],
        "condition_state": row[11],
        "access_mode": row[12],
        "location_region": row[13],
        "service_area_km": row[14],
        "usage_constraints": _json_loads_list(row[15]),
        "cost_band": row[16],
        "visibility": row[17],
        "index_state": row[18],
        "consent_version": row[19],
        "consent_at": row[20],
        "share_until": row[21],
        "share_revoked_at": row[22],
        "state_changed_at": row[23],
        "is_active": bool(row[24]),
        "created_at": row[25],
        "updated_at": row[26],
    }


def row_to_radar_feed(row: tuple) -> dict[str, Any]:
    return {
        "id": row[0], "title": row[1], "detail": row[2], "severity": row[3],
        "source": row[4], "source_excerpt": row[5], "kind": row[6], "created_at": row[7],
    }
