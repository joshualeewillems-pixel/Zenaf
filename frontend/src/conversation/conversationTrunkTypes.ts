/**
 * Mirrors `local_ai/conversation_trunk.py` — trunk + mediation vocabulary (Zenaf single-seat path).
 * Classification and `derive_mediation_profile` run on the server.
 */
export type QuestionKind =
  | 'state_inventory'
  | 'missing_fields'
  | 'next_step'
  | 'priority_resolution'
  | 'resolution_collapse'
  | 'field_update_direct'
  | 'option_generation'
  | 'conversation_continuity'
  | 'user_providing_precision'
  | 'user_correcting_model'
  | 'integration_status'
  | 'integration_confirm'
  | 'reflective_inquiry'

export type OutputContract =
  | 'inventory_only'
  | 'inventory_then_recommend'
  | 'three_options_then_lean'
  | 'confirm_and_integrate'
  | 'continuity_forward'
  | 'refine_and_continue'
  | 'direct_integration'
  | 'direct_integration_commit'
  | 'reflective_synthesis'

export type AmbiguityType =
  | 'missing_definition'
  | 'unclear_priority'
  | 'competing_priorities'
  | 'unresolved_dependency'
  | 'ownership_gap'
  | 'unknown'

export type ResolutionMode = 'expand' | 'compress' | 'sharpen' | 'decide'

export type MediationMove =
  | 'sequence_precision_layers'
  | 'compress_redundant_work'
  | 'expose_decision_axis'
  | 'recommend_first_collapse'
  | 'resolve_priority'
  | 'ask_discriminating_question'
  | 'enumerate'
  | 'acknowledge_integrate'
  | 'continue_from_subject'
  | 'update_and_continue'
  | 'integration_status_reply'
  | 'commit_and_confirm'

export type MediationProfile = {
  ambiguity_type: AmbiguityType
  resolution_mode: ResolutionMode
  mediation_move: MediationMove
}

export type CaptureConfidence = 'high' | 'medium' | 'low'

export type FieldTarget =
  | 'desired_outcome'
  | 'brief'
  | 'summary'
  | 'acceptance_criteria'
  | 'audience_split'
  | 'next_step'
  | 'goal'
  | 'constraints'
  | 'notes'
  | 'unknown'

export type CaptureTarget = {
  field_target: FieldTarget
  entity_target: string | null
  capture_confidence: CaptureConfidence
}

/** Session echo for thread continuity — mirrors `ConversationSubject` in `local_ai/conversation_trunk.py`. */
export type ConversationSubject = {
  entity_id?: string | null
  entity_type?: string | null
  entity_display_name?: string | null
  active_field?: string
  last_user_contribution?: string
  confidence?: CaptureConfidence
}
