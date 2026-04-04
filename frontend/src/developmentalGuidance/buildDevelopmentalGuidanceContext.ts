/**
 * Read-only assembler (v1): no new persistence. Inputs are passed in at call time.
 *
 * Primary signal sources wired here:
 * - Vision map growth triad + missing dimensions: mapGrowthMetrics.computeGrowthTriad,
 *   guidanceScripts.detectMissingDimensions (caller supplies MapTriadDevelopmentalSnapshot from VisionMapView).
 * - Recent workspace council runs: ai-actions/traceSink.getRecentAiActionTraces filtered by
 *   workspaceRunWithTrace.WORKSPACE_ACTION_INTENTS.council (user_outcome + optional integrity sample).
 * - council_preflight passthrough: App merges this object into POST /run context for
 *   local_ai.council_preflight.parse_preflight_from_request → build_enriched_council_context.
 *
 * Execution-flow readings: optional ``executionFlowReadings`` from GET
 * /vision-execution/coordination/execution-flow-readings — raw rows as evidence refs plus at most one
 * negative and one positive compact hypothesis (human checkpoint rows preferred over council_stream).
 *
 * Not wired in v1 (reserved for later slices): intake judgment codes API, delegation learning ring,
 * VE decision lists, server-side-only mirrors.
 *
 * Interpretive axis tilts/names: canonical `interpretive_axis_copy.json` (loaded via interpretiveAxisCopy.ts);
 * Python reads the same file — keep derivation gates aligned with `interpretiveAxes.ts`.
 */
import type { AiActionTrace } from '../ai-actions/types'
import { WORKSPACE_ACTION_INTENTS } from '../ai-actions/workspaceRunWithTrace'
import { STAGE_ASSESSMENT, STAGE_BASELINE_QUESTIONS, STAGE_FOCUSED_QUESTIONS } from '../vision-map/guidanceScripts'
import type {
  DevelopmentalEvidenceRef,
  DevelopmentalGuidanceContext,
  DevelopmentalGuidanceStyle,
  DevelopmentalHypothesis,
  ExecutionFlowReadingSummary,
  MapTriadDevelopmentalSnapshot,
} from './types'
import { deriveInterpretiveAxes } from './interpretiveAxes'

const HYPOTHESIS_PREFIX = 'One possible read (uncertain):'

export function developmentalHypothesisLeadIn(): string {
  return HYPOTHESIS_PREFIX
}

export type BuildDevelopmentalGuidanceInput = {
  mapTriad: MapTriadDevelopmentalSnapshot | null | undefined
  recentTraces: readonly AiActionTrace[]
  /** Max council traces to scan from the ring (most recent first). */
  councilTraceLookback?: number
  /**
   * Server summaries from GET /coordination/execution-flow-readings.
   * Evidence refs + at most two flow-derived hypotheses (one negative, one positive; human checkpoint preferred).
   */
  executionFlowReadings?: readonly ExecutionFlowReadingSummary[] | null
}

function tallyCouncilTraces(traces: readonly AiActionTrace[], lookback: number) {
  const council = traces.filter((t) => t.action_intent === WORKSPACE_ACTION_INTENTS.council).slice(-lookback)
  const outcomes: Record<string, number> = {}
  let weakIntegrity = 0
  for (const t of council) {
    const o = t.user_outcome || 'none'
    outcomes[o] = (outcomes[o] ?? 0) + 1
    const rev = t.council_integrity_review
    if (rev && (rev.combined_summary === 'weak_support' || rev.combined_summary === 'unreliable')) {
      weakIntegrity += 1
    }
  }
  return { council, outcomes, weakIntegrity }
}

function mapHypothesesAndStyle(
  mapTriad: MapTriadDevelopmentalSnapshot,
): Pick<DevelopmentalGuidanceContext, 'hypotheses' | 'suggested_guidance_style' | 'evidence_refs'> {
  const fromVeFocus = mapTriad.triad_scope === 've_execution_focus'
  const focusLabel = fromVeFocus ? 'this Vision & Execution focus' : 'this map focus'
  const refs = [
    {
      source_type: fromVeFocus ? 've_execution_focus_triad' : 'vision_map_triad',
      source_id_or_key: mapTriad.node_id,
      excerpt_or_hash: `${mapTriad.is_nest_aggregate ? 'nest' : 'node'}:${mapTriad.node_kind}`,
    },
  ]
  const hypotheses: DevelopmentalGuidanceContext['hypotheses'] = []
  const missing = mapTriad.missing_dimensions
  if (missing.includes('water')) {
    hypotheses.push({
      kind: 'friction',
      confidence: 'medium',
      basis: ['map_triad', 'missing_water'],
      statement: `${HYPOTHESIS_PREFIX} on the follow-through ↔ drop-off axis, ownership cadence for ${focusLabel} may be thin — naming one accountable owner and a short checkpoint could help.`,
    })
  }
  if (missing.includes('soil')) {
    hypotheses.push({
      kind: 'friction',
      confidence: 'medium',
      basis: ['map_triad', 'missing_soil'],
      statement: `${HYPOTHESIS_PREFIX} on the clarity ↔ ambiguity axis, scope for ${focusLabel} may still be loose — tighter boundaries and acceptance hints could reduce rework.`,
    })
  }
  if (missing.includes('fruit')) {
    hypotheses.push({
      kind: 'edge',
      confidence: 'medium',
      basis: ['map_triad', 'missing_fruit'],
      statement: `${HYPOTHESIS_PREFIX} on the action ↔ ideation axis, visible output for ${focusLabel} may lag — a small shippable increment could unblock momentum.`,
    })
  }

  let suggested_guidance_style: DevelopmentalGuidanceContext['suggested_guidance_style'] = 'neutral'
  if (missing.includes('soil')) suggested_guidance_style = 'more_structure'
  else if (missing.includes('water')) suggested_guidance_style = 'more_accountability'

  return { hypotheses, suggested_guidance_style, evidence_refs: refs }
}

function workGuidanceFrameFromMapTriad(
  t: MapTriadDevelopmentalSnapshot,
): DevelopmentalGuidanceContext['work_guidance_frame'] | null {
  const k = t.node_kind
  if (k !== 'seed' && k !== 'tree' && k !== 'branch') return null
  const missing = t.missing_dimensions
  const primary = (missing[0] ?? 'fruit') as 'water' | 'soil' | 'fruit'
  const question = STAGE_FOCUSED_QUESTIONS[k][primary] ?? STAGE_BASELINE_QUESTIONS[k]
  return {
    stage: k,
    primary_question: question,
    assessment_line: STAGE_ASSESSMENT[k],
    missing_dimensions: [...missing],
  }
}

function traceHypotheses(
  tally: ReturnType<typeof tallyCouncilTraces>,
): DevelopmentalGuidanceContext['hypotheses'] {
  const { council, outcomes, weakIntegrity } = tally
  if (council.length < 2) return []
  const n = council.length
  const dismissed = outcomes.dismissed ?? 0
  const applied = outcomes.applied ?? 0
  const out: DevelopmentalGuidanceContext['hypotheses'] = []

  if (dismissed >= 2 && dismissed >= applied) {
    out.push({
      kind: 'friction',
      confidence: 'medium',
      basis: ['ai_action_trace', 'user_outcome_dismissed'],
      statement: `${HYPOTHESIS_PREFIX} on the integration ↔ fragmentation axis, several recent council answers were dismissed — shorter, more concrete options might land better (session-only pattern).`,
    })
  }

  if (weakIntegrity >= 2) {
    out.push({
      kind: 'friction',
      confidence: 'medium',
      basis: ['council_integrity_review', 'weak_or_unreliable'],
      statement: `${HYPOTHESIS_PREFIX} synthesis grounding has looked uneven — naming assumptions or evidence explicitly in the next reply may help threads hold together.`,
    })
  }

  return out
}

/** Single use of coordination_evidence_source: dichotomy for evidence bullets only. */
function executionFlowSourcePrefix(coordinationEvidenceSource: string | null | undefined): string {
  const s = String(coordinationEvidenceSource ?? '').trim()
  if (s === 'council_stream') return '[COUNCIL] '
  if (s === 'atria-client-trace') return '[HUMAN] '
  return ''
}

function appendExecutionFlowReadingEvidence(
  readings: readonly ExecutionFlowReadingSummary[] | undefined | null,
  evidence_refs: DevelopmentalEvidenceRef[],
): void {
  if (!readings?.length) return
  for (const r of readings.slice(0, 8)) {
    const confPct = typeof r.confidence === 'number' ? `${Math.round(r.confidence * 100)}%` : ''
    const parts = [r.impact, r.dimension, confPct].filter(Boolean)
    const pk = r.pointer_kind ? String(r.pointer_kind) : ''
    const body = [...parts, pk].filter(Boolean).join(' · ')
    const ex = `${executionFlowSourcePrefix(r.coordination_evidence_source)}${body}`.slice(0, 240)
    evidence_refs.push({
      source_type: 'execution_flow_reading',
      source_id_or_key: (r.judgment_row_id || r.pointer || 'reading').slice(0, 120),
      excerpt_or_hash: ex,
    })
  }
}

function isHumanCheckpointFlowReading(r: ExecutionFlowReadingSummary): boolean {
  return (
    String(r.pointer_kind ?? '').trim() === 'activity_event' &&
    String(r.coordination_evidence_source ?? '').trim() === 'atria-client-trace'
  )
}

const _flowNegativeConfFloor = (x: ExecutionFlowReadingSummary): boolean =>
  x.impact === 'negative' && typeof x.confidence === 'number' && x.confidence >= 0.45

const _flowPositiveHit = (x: ExecutionFlowReadingSummary): boolean => x.impact === 'positive'

/**
 * At most one negative + one positive hypothesis from execution_flow_readings (compact; council preflight).
 * Prefer activity_event + atria-client-trace when choosing gate and wording; council_stream fallback.
 */
function maybeAppendExecutionFlowReadingHypotheses(
  readings: readonly ExecutionFlowReadingSummary[] | undefined | null,
  hypotheses: DevelopmentalHypothesis[],
): void {
  if (!readings?.length) return

  if (hypotheses.length < 6) {
    const humanNeg = readings.filter(isHumanCheckpointFlowReading).filter(_flowNegativeConfFloor)
    const anyNeg = readings.filter(_flowNegativeConfFloor)
    if (humanNeg.length >= 2) {
      hypotheses.push({
        kind: 'friction',
        confidence: 'low',
        basis: ['execution_flow_reading', 'negative_cluster', 'human_checkpoint'],
        statement: `${HYPOTHESIS_PREFIX} repeated checkpoint-backed reads suggest strain on clarity, capacity, or friction — worth a light touch, not a verdict.`,
      })
    } else if (anyNeg.length >= 2) {
      hypotheses.push({
        kind: 'friction',
        confidence: 'low',
        basis: ['execution_flow_reading', 'negative_cluster', 'council_or_mixed'],
        statement: `${HYPOTHESIS_PREFIX} several execution-flow signals on this focus leaned negative — a light check on clarity, capacity, or friction may help (tentative).`,
      })
    }
  }

  if (hypotheses.length < 6) {
    const humanPos = readings.filter(isHumanCheckpointFlowReading).filter(_flowPositiveHit)
    const anyPos = readings.filter(_flowPositiveHit)
    if (humanPos.length >= 2) {
      hypotheses.push({
        kind: 'strength',
        confidence: 'low',
        basis: ['execution_flow_reading', 'positive_cluster', 'human_checkpoint'],
        statement: `${HYPOTHESIS_PREFIX} recent acknowledged execution on this focus may be building capacity.`,
      })
    } else if (anyPos.length >= 2) {
      hypotheses.push({
        kind: 'strength',
        confidence: 'low',
        basis: ['execution_flow_reading', 'positive_cluster', 'council_or_mixed'],
        statement: `${HYPOTHESIS_PREFIX} recent execution-flow signals on this focus leaned positive — momentum may be present (tentative).`,
      })
    }
  }
}

/**
 * Returns null when there is nothing meaningful to send (avoids empty preflight noise).
 */
export function buildDevelopmentalGuidanceContext(input: BuildDevelopmentalGuidanceInput): DevelopmentalGuidanceContext | null {
  const lookback = input.councilTraceLookback ?? 12
  const tally = tallyCouncilTraces(input.recentTraces, lookback)
  const as_of = new Date().toISOString()
  const flowReadings = input.executionFlowReadings ?? []

  const mapPart = input.mapTriad ? mapHypothesesAndStyle(input.mapTriad) : null
  const traceHy = traceHypotheses(tally)

  let hypotheses = [...(mapPart?.hypotheses ?? [])]
  maybeAppendExecutionFlowReadingHypotheses(flowReadings, hypotheses)
  hypotheses = [...hypotheses, ...traceHy]

  const evidence_refs = [...(mapPart?.evidence_refs ?? [])]
  if (tally.council.length > 0) {
    evidence_refs.push({
      source_type: 'ai_action_trace_ring',
      source_id_or_key: `last_${tally.council.length}_council`,
      excerpt_or_hash: `outcomes=${JSON.stringify(tally.outcomes)}`,
    })
  }

  appendExecutionFlowReadingEvidence(flowReadings, evidence_refs)
  hypotheses = hypotheses.slice(0, 6)

  const signals_summary: DevelopmentalGuidanceContext['signals_summary'] = {
    council_runs_in_window: tally.council.length,
  }
  if (flowReadings.length > 0) {
    signals_summary.execution_flow_readings_supplied = Math.min(flowReadings.length, 24)
  }
  if (input.mapTriad) {
    signals_summary.map_triad_water = Math.round(input.mapTriad.triad.water * 100) / 100
    signals_summary.map_triad_soil = Math.round(input.mapTriad.triad.soil * 100) / 100
    signals_summary.map_triad_fruit = Math.round(input.mapTriad.triad.fruit * 100) / 100
    signals_summary.map_missing_dimensions = input.mapTriad.missing_dimensions.join(',') || '(none)'
    signals_summary.map_node_kind = input.mapTriad.node_kind
    signals_summary.map_is_nest_aggregate = input.mapTriad.is_nest_aggregate
    signals_summary.triad_scope = input.mapTriad.triad_scope ?? 'vision_map'
  }

  const workGuidanceFrame = input.mapTriad ? workGuidanceFrameFromMapTriad(input.mapTriad) : null

  const suggested_guidance_style: DevelopmentalGuidanceStyle =
    mapPart?.suggested_guidance_style ??
    (traceHy.length > 0 ? 'more_structure' : 'neutral')

  const axes = deriveInterpretiveAxes({
    missingDimensions: input.mapTriad?.missing_dimensions ?? [],
    suggestedGuidanceStyle: suggested_guidance_style,
    tally: {
      councilCount: tally.council.length,
      dismissed: tally.outcomes.dismissed ?? 0,
      applied: tally.outcomes.applied ?? 0,
      weakIntegrity: tally.weakIntegrity,
    },
  })

  const hasMap = input.mapTriad != null
  const scannedCouncil = tally.council.length > 0
  const hasFlowReadings = flowReadings.length > 0
  if (hypotheses.length === 0 && !hasMap && !scannedCouncil && !hasFlowReadings) {
    return null
  }

  return {
    as_of,
    evidence_refs,
    signals_summary,
    hypotheses,
    suggested_guidance_style,
    ...(axes.length > 0 ? { axes } : {}),
    ...(input.mapTriad
      ? { vm_entity_type: input.mapTriad.node_kind, vm_entity_id: input.mapTriad.node_id }
      : {}),
    ...(workGuidanceFrame ? { work_guidance_frame: workGuidanceFrame } : {}),
  }
}

/** Plain-language snippet for the main chat (same data as preflight; no new persistence). */
export function developmentalGuidanceUserSummary(ctx: DevelopmentalGuidanceContext): string {
  const blocks: string[] = []
  if (ctx.axes && ctx.axes.length > 0) {
    const lines = ['What might deserve attention:']
    for (const a of ctx.axes.slice(0, 5)) {
      lines.push(`• ${a.name} — ${a.tilt}`)
    }
    blocks.push(lines.join('\n'))
  }
  if (ctx.hypotheses.length > 0) {
    const lines = ['Angles to consider:']
    for (const h of ctx.hypotheses.slice(0, 6)) {
      lines.push(`• ${h.statement}`)
    }
    blocks.push(lines.join('\n'))
  }
  if (ctx.suggested_guidance_style && ctx.suggested_guidance_style !== 'neutral') {
    blocks.push(`Suggested tone: ${ctx.suggested_guidance_style.replace(/_/g, ' ')}.`)
  }
  if (blocks.length === 0) return ''
  return [
    'A quick read on this map view (this shapes how Atria listens for this run; it is not saved as a profile):',
    '',
    ...blocks,
  ].join('\n\n')
}
