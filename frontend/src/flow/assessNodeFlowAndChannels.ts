/**
 * Single orchestrator: entity map node → channels + FlowAssessment + interpretation.
 */

import type { VisionMapEntityBundle } from '../vision-map/blockersFromVe'
import { mapVisualTriad, type GrowthTriadMetrics } from '../vision-map/mapGrowthMetrics'
import {
  deriveFertilizerPulse,
  waterLevelFromVital,
  type VitalInput,
} from '../vision-map/mapVitalForces'
import type { MapNodePayload, WaterLevel } from '../vision-map/ontology'

type Severity = 0 | 1 | 2 | 3
import { resolveConditionSeverity } from './resolveConditionSeverity'
import type { StudioCouncilRunRow } from '../vision-map/studioCouncilTypes'
import { assessFlow, type FlowInput } from './flowAssessment'
import { CLEAN_STONE_THRESHOLDS } from './cleanStoneContract'
import { structureHintsForEntity } from './structureHintsForMapEntity'
import type {
  ChannelAssessment,
  ChannelBand,
  ChannelId,
  ReasonRepairBinding,
  UnifiedNodeAssessment,
} from './unifiedNodeAssessmentTypes'
import { UNIFIED_NODE_ASSESSMENT_RULES_VERSION } from './unifiedNodeAssessmentTypes'
import { deriveNodeInterpretation } from './deriveNodeInterpretation'

const MAP_SOIL_TIER_LOW_BELOW = 0.38
const MAP_SOIL_TIER_MEDIUM_BELOW = 0.55

function bandFrom01(score: number, lowBelow: number, medBelow: number): ChannelBand {
  if (score < lowBelow) return 'low'
  if (score < medBelow) return 'medium'
  return 'high'
}

function waterBand(w: number): ChannelBand {
  return bandFrom01(w, 0.38, 0.62)
}

function fruitBand(f: number): ChannelBand {
  return bandFrom01(f, 0.35, 0.55)
}

function conditionBandFromSeverity(sev: Severity): ChannelBand {
  if (sev >= 2) return 'low'
  if (sev === 1) return 'medium'
  return 'high'
}

function conditionHealth01(severity: Severity): number {
  return 1 - severity / 3
}

function pickLowestChannel(
  triad: GrowthTriadMetrics,
  severity: Severity,
  water_level: WaterLevel,
): ChannelId {
  const wSteward = water_level === 'high' ? 1 : water_level === 'medium' ? 0.55 : 0.22
  const scores: Record<ChannelId, number> = {
    water: triad.water * 0.5 + wSteward * 0.5,
    soil: triad.soil,
    fruit: triad.fruit,
    condition: conditionHealth01(severity),
  }
  let best: ChannelId = 'water'
  let bestScore = scores.water
  ;(Object.keys(scores) as ChannelId[]).forEach((k) => {
    if (scores[k]! < bestScore) {
      bestScore = scores[k]!
      best = k
    }
  })
  return best
}

const CORE_BINDINGS: ReasonRepairBinding[] = [
  {
    reasonId: 'water_low',
    channel: 'water',
    execution_kind: 'focus_field',
    field_key: 'owner_id',
  },
  {
    reasonId: 'soil_thin',
    channel: 'soil',
    action: 'distill',
    invite_kind: 'conversational',
    execution_kind: 'run_invite',
  },
  {
    reasonId: 'condition_strain',
    channel: 'condition',
    action: 'surface_tensions',
    invite_kind: 'conversational',
    execution_kind: 'run_invite',
  },
  {
    reasonId: 'fruit_low',
    channel: 'fruit',
    action: 'expand_to_steps',
    invite_kind: 'conversational',
    execution_kind: 'run_invite',
  },
]

function buildChannels(
  triad: GrowthTriadMetrics,
  severity: Severity,
  water_level: WaterLevel,
): Record<ChannelId, ChannelAssessment> {
  const waterReady =
    triad.water >= CLEAN_STONE_THRESHOLDS.water.triad01Min &&
    water_level !== CLEAN_STONE_THRESHOLDS.water.disallowWaterLevel
  const soilReady = triad.soil >= CLEAN_STONE_THRESHOLDS.soil.triad01Min
  const conditionReady = severity <= CLEAN_STONE_THRESHOLDS.condition.maxSeverity
  const fruitReady = triad.fruit >= CLEAN_STONE_THRESHOLDS.fruit.triad01Min

  const waterNeg: { id: string; detail?: string }[] = []
  if (water_level === 'low') waterNeg.push({ id: 'water_low', detail: 'stewardship tier low' })
  if (triad.water < 0.45) waterNeg.push({ id: 'water_triad_low', detail: 'attention signal weak' })

  const soilNeg: { id: string; detail?: string }[] = []
  if (triad.soil < MAP_SOIL_TIER_LOW_BELOW) soilNeg.push({ id: 'soil_thin', detail: 'grounding thin' })
  else if (triad.soil < MAP_SOIL_TIER_MEDIUM_BELOW) soilNeg.push({ id: 'soil_moderate', detail: 'grounding moderate' })

  const condNeg: { id: string; detail?: string }[] = []
  if (severity >= 1) condNeg.push({ id: 'condition_strain', detail: `severity ${severity}/3` })

  const fruitNeg: { id: string; detail?: string }[] = []
  if (triad.fruit < 0.35) fruitNeg.push({ id: 'fruit_low', detail: 'yield signal low' })

  return {
    water: {
      score01: triad.water,
      band: waterBand(triad.water),
      reasons_positive: waterReady ? [{ id: 'water_ok' }] : [],
      reasons_negative: waterNeg,
      repair_actions: [],
      is_ready: waterReady,
    },
    soil: {
      score01: triad.soil,
      band: bandFrom01(triad.soil, MAP_SOIL_TIER_LOW_BELOW, MAP_SOIL_TIER_MEDIUM_BELOW),
      reasons_positive: soilReady ? [{ id: 'soil_ok' }] : [],
      reasons_negative: soilNeg,
      repair_actions: [],
      is_ready: soilReady,
    },
    condition: {
      score01: conditionHealth01(severity),
      band: conditionBandFromSeverity(severity),
      reasons_positive: conditionReady ? [{ id: 'condition_ok' }] : [],
      reasons_negative: condNeg,
      repair_actions: [],
      is_ready: conditionReady,
    },
    fruit: {
      score01: triad.fruit,
      band: fruitBand(triad.fruit),
      reasons_positive: fruitReady ? [{ id: 'fruit_ok' }] : [],
      reasons_negative: fruitNeg,
      repair_actions: [],
      is_ready: fruitReady,
    },
  }
}

export function buildFlowInputForMapNode(
  payload: MapNodePayload,
  bundle: VisionMapEntityBundle | null,
  triad: GrowthTriadMetrics,
  severity: Severity,
): FlowInput {
  const hints = structureHintsForEntity(payload.ref, bundle)
  const kind =
    payload.ref.veType === 'idea' ||
    payload.ref.veType === 'initiative' ||
    payload.ref.veType === 'project' ||
    payload.ref.veType === 'task'
      ? payload.ref.veType
      : undefined
  return {
    water: triad.water,
    soil: triad.soil,
    fruit: triad.fruit,
    waterLevel: payload.water_level,
    conditionSeverity: severity,
    kind,
    hasBrief: hints.hasBrief,
    hasNextStep: hints.hasNextStep,
    hasDeps: hints.hasDeps,
  }
}

export type AssessNodeFlowContext = {
  bundle: VisionMapEntityBundle | null
  councilRuns: StudioCouncilRunRow[]
  vital?: VitalInput
}

export function assessNodeFlowAndChannels(
  basePayload: MapNodePayload,
  ctx: AssessNodeFlowContext,
): UnifiedNodeAssessment {
  const ref = basePayload.ref
  const water_level: WaterLevel = ctx.vital ? waterLevelFromVital(ctx.vital) : basePayload.water_level
  const fertilizer_pulse = ctx.vital
    ? deriveFertilizerPulse(ref, ctx.vital.entityUpdatedAt ?? null, ctx.councilRuns)
    : basePayload.fertilizer_pulse

  const payloadForScoring: MapNodePayload = {
    ...basePayload,
    water_level,
    fertilizer_pulse,
  }

  const map_visual_triad = mapVisualTriad(payloadForScoring, ctx.bundle)
  const condition_severity = resolveConditionSeverity(payloadForScoring)

  const flowInput = buildFlowInputForMapNode(payloadForScoring, ctx.bundle, map_visual_triad, condition_severity)
  const flow = assessFlow(flowInput)

  const channels = buildChannels(map_visual_triad, condition_severity, water_level)
  const lowest_channel = pickLowestChannel(map_visual_triad, condition_severity, water_level)
  const clean_stone_ready =
    channels.water.is_ready &&
    channels.soil.is_ready &&
    channels.condition.is_ready &&
    channels.fruit.is_ready

  const interpretation = deriveNodeInterpretation(
    { flow, lowest_channel, derived: { condition_severity } },
    { kind: basePayload.kind, bundle: ctx.bundle, ref: basePayload.ref },
  )

  return {
    ref,
    channels,
    flow,
    lowest_channel,
    first_repair_path: undefined,
    derived: {
      map_visual_triad,
      condition_severity,
      water_level,
      fertilizer_pulse,
    },
    clean_stone_ready,
    rules_version: UNIFIED_NODE_ASSESSMENT_RULES_VERSION,
    reason_bindings: CORE_BINDINGS,
    interpretation,
  }
}
