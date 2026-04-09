/**
 * Node interpretation — single cognitive read for map + council preflight.
 *
 * Product law (conservative clarify_first):
 * Use `clarify_first` only when one discriminating answer would materially change the recommended action.
 * Otherwise keep `proceed` and let `actionLine` drive repair.
 * Ordinary underdevelopment (low soil/fruit alone) does NOT trigger clarify_first.
 */

import type { VisionMapEntityBundle } from '../vision-map/blockersFromVe'
import type { MapEntityRef, MapNodePayload } from '../vision-map/ontology'
import { STAGE_FOCUSED_QUESTIONS } from '../vision-map/guidanceScripts'
import { structureHintsForEntity } from './structureHintsForMapEntity'
import type {
  ChannelId,
  NodeInterpretation,
  NodeInterpretationAmbiguityType,
} from './unifiedNodeAssessmentTypes'
import type { FlowAssessment, InviteAction } from './flowAssessment'

type DeriveCtx = {
  kind: MapNodePayload['kind']
  bundle: VisionMapEntityBundle | null
  ref: MapEntityRef
}

type DeriveInput = {
  flow: FlowAssessment
  lowest_channel: ChannelId
  derived: { condition_severity: 0 | 1 | 2 | 3 }
}

function mapKindToStage(kind: MapNodePayload['kind']): 'seed' | 'tree' | 'branch' | null {
  if (kind === 'seed') return 'seed'
  if (kind === 'tree') return 'tree'
  if (kind === 'branch') return 'branch'
  return null
}

function inspectorSectionFromLowest(low: ChannelId): 'water' | 'soil' | 'fruit' {
  if (low === 'water') return 'water'
  if (low === 'fruit') return 'fruit'
  return 'soil'
}

function clarifyQuestionForChannel(low: ChannelId): string {
  switch (low) {
    case 'water':
      return 'Who has decision rights for the next move on this work, and what is still unknown about ownership or stewardship?'
    case 'soil':
      return 'What is the one-sentence problem statement for this work, and what is explicitly out of scope?'
    case 'fruit':
      return 'What would a skeptical stakeholder need to see to agree this work is worth doing next?'
    case 'condition':
    default:
      return 'What is the single biggest risk or assumption that could invalidate the plan if it were wrong?'
  }
}

function actionLineForProceed(primary: InviteAction, low: ChannelId): string {
  switch (primary) {
    case 'distill':
      return 'Sharpen definition before expanding structure or commitments.'
    case 'expand_to_steps':
      if (low === 'fruit')
        return 'Expand into concrete steps tied to measurable outcomes.'
      if (low === 'water') return 'Assign ownership and checkpoints, then break work into executable steps.'
      if (low === 'soil') return 'Pin scope and boundaries, then list the next concrete steps.'
      return 'Break this into executable steps with clear owners.'
    case 'surface_tensions':
      return 'Surface the main tensions and constraints before closing the loop.'
    case 'summarize_for_council':
      return 'Summarize the current state for a decision-ready council read.'
    default:
      return 'Take the next concrete step suggested by your plan data.'
  }
}

function proceedChatPrefill(
  kind: MapNodePayload['kind'],
  low: ChannelId,
  primary: InviteAction,
): string {
  const stage = mapKindToStage(kind)
  const section = inspectorSectionFromLowest(low)
  if (stage) {
    const row = STAGE_FOCUSED_QUESTIONS[stage][section]
    if (row) return row
  }
  if (primary === 'summarize_for_council') {
    return 'What decision do we need from council, and what two facts would change the call?'
  }
  if (primary === 'surface_tensions') {
    return 'What constraint or incentive conflict is most likely to block delivery if we ignore it?'
  }
  return 'What is the single next move that would most reduce risk for this work?'
}

function shouldClarifyFirst(
  flow: FlowAssessment,
  hints: ReturnType<typeof structureHintsForEntity>,
  derived: { condition_severity: 0 | 1 | 2 | 3 },
): { yes: boolean; ambiguityType?: NodeInterpretationAmbiguityType } {
  if (flow.dominantIssue === 'clarify' && hints.hasBrief === false) {
    return { yes: true, ambiguityType: 'missing_definition' }
  }
  if (flow.dominantIssue === 'tension' && derived.condition_severity >= 3) {
    return { yes: true, ambiguityType: 'competing_priorities' }
  }
  return { yes: false }
}

function ambiguityForClarify(
  t: NodeInterpretationAmbiguityType | undefined,
  low: ChannelId,
): NodeInterpretationAmbiguityType {
  if (t) return t
  if (low === 'water') return 'ownership_gap'
  return 'unclear_priority'
}

export function deriveNodeInterpretation(input: DeriveInput, ctx: DeriveCtx): NodeInterpretation {
  const { flow, lowest_channel, derived } = input
  const hints = structureHintsForEntity(ctx.ref, ctx.bundle)
  const clarifyGate = shouldClarifyFirst(flow, hints, derived)

  const summary = flow.trunkSummary
  const primary = flow.primaryAction

  if (clarifyGate.yes) {
    const q = clarifyQuestionForChannel(lowest_channel)
    const amb = ambiguityForClarify(clarifyGate.ambiguityType, lowest_channel)
    return {
      stance: 'clarify_first',
      blockingClarification: true,
      summary,
      actionLine: 'One clarification is needed before choosing the next move.',
      chatPrefill: q,
      clarificationQuestion: q,
      ambiguityType: amb,
    }
  }

  const actionLine = actionLineForProceed(primary, lowest_channel)
  const chatPrefill = proceedChatPrefill(ctx.kind, lowest_channel, primary)
  return {
    stance: 'proceed',
    blockingClarification: false,
    summary,
    actionLine,
    chatPrefill,
  }
}
