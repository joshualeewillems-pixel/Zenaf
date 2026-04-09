/**
 * Unified node assessment — single orchestrator output (Four-channel VE plan).
 * Surfaces must not recompute channel/flow/repair state outside this contract.
 */

import type { ActionId } from '../vision-execution/focus/types'
import type { MapEntityRef } from '../vision-map/ontology'
import type { WaterLevel } from '../vision-map/ontology'
import type { FlowAssessment } from './flowAssessment'

export const UNIFIED_NODE_ASSESSMENT_RULES_VERSION = '1'

export type InterpretationStance = 'proceed' | 'clarify_first'

/**
 * Transport enum for council_preflight / trunk — not display copy.
 * Keep in lockstep with `local_ai/conversation_trunk.AmbiguityType`.
 */
export type NodeInterpretationAmbiguityType =
  | 'missing_definition'
  | 'unclear_priority'
  | 'competing_priorities'
  | 'unresolved_dependency'
  | 'ownership_gap'
  | 'unknown'

export type NodeInterpretation = {
  stance: InterpretationStance
  /** True when a discriminating answer is required before a responsible next move. */
  blockingClarification?: boolean
  summary: string
  actionLine: string
  chatPrefill: string
  clarificationQuestion?: string
  ambiguityType?: NodeInterpretationAmbiguityType
}

export type ChannelId = 'water' | 'soil' | 'condition' | 'fruit'

export type ChannelBand = 'low' | 'medium' | 'high'

export type ReasonRepairBinding = {
  reasonId: string
  channel: ChannelId
  action?: ActionId
  invite_kind?: 'conversational' | 'structured_fill'
  field_key?: string
  execution_kind: 'run_invite' | 'focus_field' | 'navigate' | 'manual_only'
}

export type ChannelAssessment = {
  score01: number
  band: ChannelBand
  reasons_positive: { id: string; detail?: string }[]
  reasons_negative: { id: string; detail?: string }[]
  repair_actions: {
    action: ActionId
    kind: 'conversational' | 'structured_fill'
    suggested_field_key?: string
    label: string
  }[]
  is_ready: boolean
}

export type FirstRepairPath = {
  reasonId: string
  action?: ActionId
  execution_kind: ReasonRepairBinding['execution_kind']
}

export type UnifiedNodeAssessment = {
  ref: MapEntityRef
  channels: Record<ChannelId, ChannelAssessment>
  flow: FlowAssessment
  lowest_channel: ChannelId
  /** Required when deficit panel / primary repair CTA ships; optional during migration */
  first_repair_path?: FirstRepairPath
  derived: {
    map_visual_triad: { water: number; soil: number; fruit: number }
    condition_severity: 0 | 1 | 2 | 3
    water_level: WaterLevel
    fertilizer_pulse: boolean
  }
  clean_stone_ready: boolean
  rules_version: string
  reason_bindings: ReasonRepairBinding[]
  /** Single cognitive read: summary, action, prefill, optional clarify-first stance. */
  interpretation: NodeInterpretation
}
