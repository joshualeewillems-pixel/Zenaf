import type { NodeInterpretation } from '../flow/unifiedNodeAssessmentTypes'

/**
 * Mirrors local_ai/developmental_guidance.py — JSON-serializable read model for council_preflight.
 * Hypothesis wording stays non-diagnostic; server normalizes confidence (caps high → medium).
 */
export type DevelopmentalHypothesisKind = 'strength' | 'friction' | 'edge' | 'challenge_style'

export type DevelopmentalConfidence = 'low' | 'medium' | 'high'

export type DevelopmentalGuidanceStyle =
  | 'more_structure'
  | 'more_ambiguity_tolerance'
  | 'more_accountability'
  | 'neutral'

export type DevelopmentalEvidenceRef = {
  source_type: string
  source_id_or_key?: string
  excerpt_or_hash?: string
}

/** GET /vision-execution/coordination/execution-flow-readings — weak overlay for guidance only. */
export type ExecutionFlowReadingSummary = {
  impact: string
  dimension: string
  confidence: number
  pointer?: string
  pointer_kind?: string | null
  coordination_evidence_source?: string | null
  created_at?: string | null
  judgment_row_id?: string | null
}

export type DevelopmentalHypothesis = {
  kind: DevelopmentalHypothesisKind
  statement: string
  confidence: DevelopmentalConfidence
  basis: string[]
}

/** Ephemeral interpretive axis (no scores; not persisted). Mirrors server read model. */
export type DevelopmentalInterpretiveAxis = {
  name: string
  tilt: string
}

/** Server-filled from resonance ratings; mirrors storage escalation_signal. */
export type DevelopmentalEscalationSignal = {
  current_level: number
  confidence: number
  basis: string
  recommended_approach: 'exploration' | 'recognition' | 'loop' | 'avoidance' | 'confrontation'
}

/** Stage scaffolding mirrored from vision-map `guidanceScripts` (seed/tree/branch). */
export type WorkGuidanceFrame = {
  stage: 'seed' | 'tree' | 'branch'
  primary_question: string
  assessment_line?: string
  missing_dimensions: ('water' | 'soil' | 'fruit')[]
}

export type DevelopmentalGuidanceContext = {
  as_of: string
  evidence_refs: DevelopmentalEvidenceRef[]
  signals_summary: Record<string, string | number | boolean | null | string[] | Record<string, string>>
  hypotheses: DevelopmentalHypothesis[]
  suggested_guidance_style: DevelopmentalGuidanceStyle
  /** Optional; server re-derives if omitted. Plain-language only. */
  axes?: DevelopmentalInterpretiveAxis[]
  /** Vision map row when guidance is scoped to a selection; narrows prompt_id / dismiss identity. */
  vm_entity_type?: string
  vm_entity_id?: string
  /** Optional; merged server-side from get_resonance_pattern for council calibration. */
  escalation_signal?: DevelopmentalEscalationSignal
  /** Client hint: user asked for guidance this turn (invocation policy). */
  explicit_guidance_request?: boolean
  /** Product stage lens (idea/initiative/project) — echoed prominently in council Context. */
  work_guidance_frame?: WorkGuidanceFrame
}

/** Snapshot from Vision map selection (assembled in VisionMapView). */
export type MapTriadDevelopmentalSnapshot = {
  node_id: string
  is_nest_aggregate: boolean
  node_kind: string
  triad: { water: number; soil: number; fruit: number }
  missing_dimensions: ('water' | 'soil' | 'fruit')[]
  /** Primary label for system prompt titles (map node or nest root). */
  node_label?: string | null
  /** When set, hypotheses / evidence refs distinguish VE tab focus from map selection. */
  triad_scope?: 'vision_map' | 've_execution_focus'
  /** Unified map node interpretation (stance, summary, prefill) for trunk mediation override. */
  node_interpretation?: NodeInterpretation | null
}
