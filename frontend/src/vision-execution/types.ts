/** Vision → Execution API base. Relative URL in dev so Vite proxies to backend (no CORS). All entities use snake_case from backend. */
export const VISION_EXECUTION_API = '/vision-execution'

export interface CoreProfile {
  /** True for the single canonical Brand core row (from GET /core-profiles). */
  is_canonical?: boolean
  id: string
  name: string
  core_definition: string
  current_goals: string
  growth_focus_12_months: string
  economic_engine: string
  non_negotiables: string
  strategic_filter: string
  current_constraints: string
  capacity_limit: string
  kill_philosophy: string
  strength_positioning: string
  raw_notes?: string
  /** Canonical profile for Foundation / training (at most one per user). */
  is_primary?: boolean
  created_at: string
  updated_at: string
}

export interface Idea {
  id: string
  title: string
  summary: string
  description: string
  status: string
  tags: string[]
  created_by: string
  desired_outcome?: string
  linked_people?: string[]
  linked_assets?: string[]
  linked_ideas?: string[]
  /** Free-form notes (e.g. meeting extraction append); separate from description. */
  notes?: string
  created_at: string
  updated_at: string
}

export interface Initiative {
  id: string
  source_idea_id: string | null
  title: string
  brief: string
  status: string
  owner_id: string | null
  /** Model-suggested priority (0–5). AI metadata, not a user decision. */
  evaluation_priority: number | null
  estimated_cost_ai: string
  estimated_timeframe_ai: string
  philosophical_alignment_ai: string
  next_step_ai: string
  seats?: InitiativeSeat[]
  required_assets: string[]
  dependencies: string
  risks: string
  recommendation: string
  kill_criteria: string
  notes: string
  created_at: string
  updated_at: string
  /** Derived (read-only): 0–100 score from AI evaluation_priority; null when missing */
  weightedScore?: number | null
  /** Derived (read-only): true when score ≥ 60, brief set, status Draft/Evaluating */
  approvalReady?: boolean
  /** Derived (read-only): 0–1, presence of cost/timeframe AI estimates */
  returnOnTime?: number
}

/** First-class execution checklist row (Phase 1). Canonical vs legacy `next_step_ai`. */
export interface ExecutionStep {
  id: string
  user_id: string
  scope_type: 'initiative' | 'project'
  scope_id: string
  title: string
  sort_order: number
  is_done: boolean
  completed_at: string | null
  source: 'ai' | 'user' | 'import'
  source_evaluation_id: string | null
  created_at: string
  updated_at: string
}

export interface InitiativeSeat {
  role: string
  assigned_person_id: string | null
  estimated_effort: string | null
  notes: string
}

export interface Project {
  id: string
  initiative_id: string | null
  title: string
  brief: string
  status: string
  owner_id: string | null
  supporting_owner_ids: string[]
  /** Prefer numeric string "1"–"5" from UI; legacy free text may still exist in older rows. */
  priority: string
  start_date: string | null
  end_date: string | null
  estimated_weekly_hours: number | null
  next_step_ai: string
  notes: string
  created_at: string
  updated_at: string
  /** Execution dependency: asset ids required by this project (backend may return). */
  required_assets?: string[]
  /** Derived (read-only): calendar days between start and end; null if missing */
  duration?: number | null
  /** Derived (read-only): 0–1 readiness score */
  completionReadiness?: number
  /** Derived (read-only): true when initiative_id is null */
  unanchoredFlag?: boolean
}

export interface Task {
  id: string
  /** Set when the task lives under a project; omit or null for standalone tasks */
  project_id: string | null
  parent_task_id: string | null
  title: string
  description: string
  assignee_id: string | null
  status: string
  priority: string
  estimated_hours: number | null
  due_date: string | null
  dependency_ids: string[]
  /** Execution dependency: asset ids required for this task (backend may return). */
  required_asset_ids?: string[]
  completion_criteria: string
  notes: string
  created_at: string
  updated_at: string
}

export interface Person {
  id: string
  name: string
  role: string
  relationship_type: string
  contact_info: string
  strengths: string
  needs: string
  wants: string
  availability: string
  notes: string
  created_at: string
  updated_at: string
}

export interface CapacityProfile {
  person_id: string
  weekly_capacity_hours: number
  created_at: string
  updated_at: string
  /** Derived (read-only): sum of project weekly hours for active/ready projects */
  activeWeeklyHours?: number
  /** Derived (read-only): activeWeeklyHours - weekly_capacity_hours */
  capacityDelta?: number
  /** Derived (read-only): true when capacityDelta > 0 */
  overcapacity?: boolean
}

export interface Asset {
  id: string
  name: string
  asset_type: string
  owner_id: string | null
  status: string
  availability: string
  cost: string
  time_availability: string
  linked_idea_ids: string[]
  linked_initiative_ids: string[]
  linked_project_ids: string[]
  notes: string
  created_at: string
  updated_at: string
}

/** Meeting extract: proposed items (no id until saved) */
export type ExtractedConfidence = 'high' | 'medium' | 'low'

export type ExtractedCandidateProposedType =
  | 'project'
  | 'task'
  | 'initiative'
  | 'decision'
  | 'research'
  | 'signal'
  | 'observation'

export interface ExtractedIdea {
  title: string
  summary?: string
  description?: string
  status?: string
  confidence?: ExtractedConfidence | null
  sourceExcerpt?: string | null
  /** External single-shot extraction: model-suggested class for review. */
  proposedType?: ExtractedCandidateProposedType | null
}

export interface ExtractedInitiative {
  title: string
  brief?: string
  status?: string
  ownerName?: string | null
  notes?: string
  confidence?: ExtractedConfidence | null
  sourceExcerpt?: string | null
  existingInitiativeMatchId?: string | null
  matchConfidence?: number | null
}

export interface ExtractedTask {
  title: string
  description?: string
  status?: string
  assigneeName?: string | null
  notes?: string
  confidence?: ExtractedConfidence | null
  sourceExcerpt?: string | null
  existingProjectMatchId?: string | null
  existingTaskMatchId?: string | null
  existingPersonMatchId?: string | null
  matchConfidence?: number | null
}

/** Flat observation from meeting extract (no extract-time entity typing). */
/** fast_local extract timing / internal segment counts (server-computed). */
export interface MeetingExtractionMeta {
  evidenceSegmentsPlanned?: number
  evidenceSegmentsProcessed?: number
  evidenceLlmMsTotal?: number
  evidencePostProcessMs?: number
  interactiveStopReason?: string | null
  interactiveEarlyStop?: boolean
  literalAnchorOnly?: boolean
  literalAnchorCount?: number
  literalAnchorRawCount?: number
  literalAnchorsCapped?: boolean
  /** This chunk skipped segment LLM (Pass 0 exact anchors only). */
  skipLLM?: boolean
  /** 1 if this chunk skipped LLM, else 0 (sum across chunks for a run). */
  llmSkippedCount?: number
  /** Server wall time for Pass 0 + segment LLM path (ms). */
  evidencePhaseMs?: number
  candidateCountPerChunk?: number
  literalCandidateCount?: number
  modelCandidateCount?: number
  lowValueLiteralAnchor?: boolean
  diagnosticsChunkId?: string | null
  /** Present when extraction used the single-call external LLM path. */
  extractionEngineType?: 'local' | 'external'
  selectedExternalAiEngine?: string | null
  washDataForCall?: boolean
  resolvedProviderUsed?: string | null
  resolvedModelUsed?: string | null
  promptCharLen?: number
  parseOutcome?: string | null
  candidatesRawCount?: number
  candidatesAfterDedupe?: number
  policyBlockedUnwashedOutbound?: boolean
  /** External typed path: model returned ideas/initiatives/projects/tasks buckets directly. */
  externalTypedBuckets?: boolean
  typedIdeasCount?: number | null
  typedInitiativesCount?: number | null
  typedProjectsCount?: number | null
  typedTasksCount?: number | null
}

/** Mirrors meeting-intelligence GraphInterpretation (avoid circular imports). */
export type ExtractMeetingGraphInterpretationType =
  | 'existing_enrichment'
  | 'existing_amendment'
  | 'child_of_existing'
  | 'genuinely_new'
  | 'signal_only'

export type ExtractMeetingGraphInterpretationAction =
  | 'update'
  | 'patch'
  | 'create_child'
  | 'create_new'
  | 'ignore'

export interface ExtractMeetingGraphInterpretationPayload {
  title?: string
  description?: string
  notes?: string
  parentId?: string
  fieldsToPatch?: Record<string, unknown>
}

export interface ExtractMeetingGraphInterpretation {
  type: ExtractMeetingGraphInterpretationType
  targetId?: string
  confidence?: number
  action?: ExtractMeetingGraphInterpretationAction
  payload?: ExtractMeetingGraphInterpretationPayload
}

export interface ExtractMeetingCandidate {
  id?: string
  kind?: string
  text?: string
  summary?: string | null
  confidence?: number | null
  confidenceLabel?: ExtractedConfidence | null
  sourceStage?: string | null
  segmentId?: string | null
  sourceExcerpt?: string | null
  possibleMatches?: Array<{ id: string; type: string; similarity: number }>
  anchorRole?: string | null
  proposedType?: ExtractedCandidateProposedType | string | null
  interpretation?: ExtractMeetingGraphInterpretation
}

export interface ExtractMeetingResponse {
  candidates?: ExtractMeetingCandidate[]
  ideas: ExtractedIdea[]
  initiatives: ExtractedInitiative[]
  tasks: ExtractedTask[]
  projects?: Array<Record<string, unknown>>
  assets?: Array<Record<string, unknown>>
  peopleReferences?: Array<Record<string, unknown>>
  signals?: Array<Record<string, unknown>>
  meeting_id?: string
  harvest_ledger?: {
    transcript_id: string
    created_at: string
    items: Array<{
      id: string
      ordinal: number
      label: string
      raw_text: string
      speaker?: string | null
      source_segment_id?: string | null
      source_turn_index?: number | null
      category_hint?: string | null
      speculative?: boolean
      confidence?: number | null
      normalized_from?: string | null
      mapped_entity_ids?: string[]
      notes?: string | null
    }>
  } | null
  /** Error code when extraction failed (e.g. parse_failure, provider_unavailable). */
  error?: string
  /** Human-readable message; prefer this for display when present. */
  message?: string
  /** Interactive (fast_local) extract succeeded but quality gate removed all rows. */
  noDurableCandidates?: boolean
  /** Present on fast_local responses: internal evidence segment counts and LLM/post-process timing. */
  extractionMeta?: MeetingExtractionMeta
  /** Sample of raw model output (e.g. first 500 chars) for parse_failure. */
  sample?: string
  /** True when execution policy / privacy_mode blocked the run (no model used). */
  execution_blocked?: boolean
}

/** Response from POST /extract-segment-summary (lightweight per-segment). */
export interface SegmentSummaryResponse {
  topic: string
  briefSummary: string
  candidateTasks: string[]
  candidateEntities: string[]
  candidateSignals: Array<{ kind: string; label?: string; detail?: string }>
  error?: string
}

/** Payload for POST /extract-meeting-synthesis (long-meeting hierarchical path). */
export interface SegmentSummaryForSynthesis {
  segmentId: string
  segmentTitle: string
  topic: string
  briefSummary: string
  candidateTasks: string[]
  candidateEntities: string[]
  candidateSignals: Array<{ kind: string; label?: string; detail?: string }>
}

/** Strategic Radar item (minimal reference). Backend uses snake_case. */
export interface RadarItem {
  type: 'initiative' | 'project' | 'task' | 'person'
  id: string
  title?: string
  name?: string
  status?: string
  reason?: string
  project_id?: string
  weighted_score?: number
  active_weekly_hours?: number
  weekly_capacity_hours?: number
}

/** Radar feed item: view over Layer 1 Signal (severity derived from kind). */
export interface RadarSignalItem {
  id: string
  title: string
  detail: string
  severity: string
  source: string
  source_excerpt?: string | null
  kind: string
  created_at: string
  status?: string
}

export interface RadarResponse {
  act_now: RadarItem[]
  blocked: RadarItem[]
  overcapacity: RadarItem[]
  unanchored: RadarItem[]
  high_value_stalled: RadarItem[]
  kill_candidates: RadarItem[]
  signals?: RadarSignalItem[]
}
