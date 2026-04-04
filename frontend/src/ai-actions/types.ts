/**
 * Product-wide AI action trace model (implementation may start in Vision & Execution).
 * Surfaces, subjects, and action kinds are not VE-specific.
 * @see docs/02_ACTIVE_DESIGN/AI_ACTION_TRACE_AND_ROUTING_DESIGN.md
 */

/** Where in the app the action was invoked (routing + analytics dimension). */
export type AtriaSurface =
  | 'vision_execution'
  | 'core_profile'
  | 'meeting_extraction'
  | 'perspectives'
  | 'team'
  | 'workspace_organizer'
  | 'content'
  | 'intake'
  | 'settings'

/**
 * What class of AI operation ran — stable across surfaces.
 * VE maps: context-bar rewrite → field_text_rewrite; suggested work → suggestion_batch; evaluate → structured_evaluation.
 */
export type AiActionKind =
  | 'field_text_rewrite'
  | 'suggestion_batch'
  | 'structured_evaluation'

export type AiUserOutcome = 'applied' | 'dismissed' | 'edited' | 'copied' | 'none'

/** Council streaming-only; PRIMARY anchor heuristic from server. */
export type CouncilSynthesisIntegrityState = 'anchored' | 'weak' | 'unanchored'

/** UI-derived from anchor state + seat support (frontend only). */
export type CouncilSynthesisCombinedSummary =
  | 'grounded'
  | 'grounded_but_interpretive'
  | 'weak_support'
  | 'unreliable'

/**
 * Compact row for human review of council synthesis integrity (bounded instrumentation).
 * Attached to workspace council traces when synthesis + integrity signals exist.
 */
export type CouncilIntegrityReviewSample = {
  schema: 'council_integrity_review_v1'
  combined_summary: CouncilSynthesisCombinedSummary
  /** User-facing label for the combined summary (same as UI “Combined reading”). */
  combined_summary_label: string
  synthesis_integrity_state: CouncilSynthesisIntegrityState
  synthesis_support_status: string | null
  integrity_warning: string | null
  policies_applied: string[]
  provenance_run_id: string | null
  include_synthesis: boolean
  /** Truncated council output focusing on reviewability; full text also in trace.output (until redacted). */
  synthesis_text: string
}

/**
 * One user-visible AI gesture; safe to persist later without raw prompts or chain-of-thought.
 * subject_* = domain record the action targeted (not “VE-only”: may be brief, perspective, person, folder job, etc.).
 */
export type AiActionTrace = {
  trace_id: string
  surface: AtriaSurface
  action_kind: AiActionKind
  /**
   * Finer pipeline / template identity (snake_case string, not a closed enum).
   * Use with coarse `action_kind` for analytics and future routing.
   */
  action_intent?: string | null
  /** Domain type of the target (e.g. initiative, idea, project, task, content_brief, perspective_agent, person, workspace_job). */
  subject_type: string
  subject_id: string
  /** Null when not field-scoped (e.g. whole-subject evaluation). */
  field_key: string | null
  /** Bounded snapshot (trimmed text, route id, param hash); never full prompt. */
  input_snapshot: string
  model_used: string | null
  /** When known (e.g. POST /run with routing_context); optional for older traces. */
  provider_used?: string | null
  prompt_version: string | null
  output: string
  user_outcome: AiUserOutcome
  created_at: string
  /** Present on workspace council runs with synthesis integrity signals (local ring buffer only). */
  council_integrity_review?: CouncilIntegrityReviewSample | null
}

/** Logical template version for field rewrite prompts (backend task names may differ). */
export const PROMPT_VERSION_FIELD_TEXT_REWRITE = 'field_text_rewrite_body_v1'
