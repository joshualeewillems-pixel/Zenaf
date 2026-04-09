/**
 * Flow Spine — deterministic read of movement / coherence / strain / ripeness.
 * Single narrative gravity for map copy, invite ranking, mediation tone.
 */

import type { ActionId } from '../vision-execution/focus/types'

export type FlowAxis = number

export type DominantIssue = 'clarify' | 'structure' | 'tension' | 'decide'

export type InviteAction =
  | 'distill'
  | 'expand_to_steps'
  | 'surface_tensions'
  | 'summarize_for_council'

export interface FlowAxes {
  focus: FlowAxis
  structure: FlowAxis
  tension: FlowAxis
  decisionReadiness: FlowAxis
  vitality: FlowAxis
  grounding: FlowAxis
  condition: FlowAxis
  maturity: FlowAxis
}

export interface FlowAssessment {
  axes: FlowAxes
  dominantIssue: DominantIssue
  primaryAction: InviteAction
  rankedActions: InviteAction[]
  trunkSummary: string
  bestNextLabel: string
}

export interface FlowInput {
  water: number
  soil: number
  fruit: number
  waterLevel?: 'low' | 'medium' | 'high'
  conditionSeverity: 0 | 1 | 2 | 3
  kind?: 'idea' | 'initiative' | 'project' | 'task'
  growthStage?: number
  hasBrief?: boolean
  hasNextStep?: boolean
  hasDeps?: boolean
}

const INVITE_ACTIONS: readonly InviteAction[] = [
  'distill',
  'expand_to_steps',
  'surface_tensions',
  'summarize_for_council',
] as const

export function isInviteAction(a: ActionId): a is InviteAction {
  return (INVITE_ACTIONS as readonly string[]).includes(a)
}

export function clamp01(v: number): number {
  return Math.max(0, Math.min(1, v))
}

export function severityTo01(s: 0 | 1 | 2 | 3): number {
  return s / 3
}

export function resolveDominantIssue(a: FlowAxes): DominantIssue {
  if (a.tension > 0.7) return 'tension'
  if (a.structure < 0.45) return 'structure'
  if (a.focus < 0.45) return 'clarify'
  if (a.decisionReadiness > 0.7) return 'decide'
  return 'structure'
}

export function rankActions(issue: DominantIssue): InviteAction[] {
  switch (issue) {
    case 'clarify':
      return ['distill', 'expand_to_steps', 'surface_tensions', 'summarize_for_council']
    case 'structure':
      return ['expand_to_steps', 'distill', 'surface_tensions', 'summarize_for_council']
    case 'tension':
      return ['surface_tensions', 'expand_to_steps', 'distill', 'summarize_for_council']
    case 'decide':
      return ['summarize_for_council', 'expand_to_steps', 'surface_tensions', 'distill']
  }
}

export function buildSummary(a: FlowAxes, issue: DominantIssue): { text: string; next: string } {
  const hasMovement = a.vitality > 0.5
  const strained = a.tension > 0.6

  switch (issue) {
    case 'structure':
      return {
        text:
          `This work has ${hasMovement ? 'movement' : 'limited movement'}, but not enough grounding. ` +
          `It is active enough to avoid sharpening focus as the first move, but too structurally thin for clean synthesis. ` +
          `${strained ? 'Stress is beginning to accumulate around unresolved dependencies and assumptions. ' : ''}` +
          `Best next intervention: expand steps.`,
        next: 'Expand steps',
      }
    case 'tension':
      return {
        text:
          `This work is reasonably articulated and grounded, but carries unresolved tensions. ` +
          `The issue is not definition or sequencing, but contradiction across constraints or incentives. ` +
          `Best next intervention: explore tensions.`,
        next: 'Explore tensions',
      }
    case 'clarify':
      return {
        text:
          `This work is not yet clearly articulated. ` +
          `Before structuring or evaluating tradeoffs, it needs a sharper definition of what it is. ` +
          `Best next intervention: sharpen focus.`,
        next: 'Sharpen focus',
      }
    case 'decide':
      return {
        text:
          `This work is sufficiently grounded, active, and coherent to support a decision. ` +
          `Further expansion is unlikely to change the direction materially. ` +
          `Best next intervention: summarize for council.`,
        next: 'Summarize for council',
      }
  }
}

function deriveAxes(input: FlowInput): FlowAxes {
  const vitality = input.waterLevel
    ? input.waterLevel === 'low'
      ? 0.25
      : input.waterLevel === 'medium'
        ? 0.6
        : 0.9
    : input.water

  const grounding = input.soil
  const condition = severityTo01(input.conditionSeverity)
  const tension = clamp01(condition * 0.75 + (1 - grounding) * 0.25)

  let structure = grounding
  if (input.hasNextStep) structure += 0.05
  if (input.hasDeps) structure += 0.05
  structure = clamp01(structure)

  let focus = 0.4
  if (input.hasBrief) focus += 0.3
  if (structure > 0.6) focus += 0.2
  focus = clamp01(focus)

  const maturity = clamp01(input.fruit * 0.7 + grounding * 0.3)
  const decisionReadiness = clamp01(
    focus * 0.25 + structure * 0.25 + vitality * 0.2 + maturity * 0.2 + (1 - tension) * 0.1,
  )

  return {
    focus,
    structure,
    tension,
    decisionReadiness,
    vitality,
    grounding,
    condition,
    maturity,
  }
}

export function assessFlow(input: FlowInput): FlowAssessment {
  const axes = deriveAxes(input)
  const dominantIssue = resolveDominantIssue(axes)
  const rankedActions = rankActions(dominantIssue)
  const primaryAction = rankedActions[0]!
  const { text, next } = buildSummary(axes, dominantIssue)

  return {
    axes,
    dominantIssue,
    primaryAction,
    rankedActions,
    trunkSummary: text,
    bestNextLabel: next,
  }
}
