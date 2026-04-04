/**
 * Map guide opener — weak-area copy + optional interpretive axis sentence from the same canonical
 * strings as developmental guidance (`interpretive_axis_copy.json`). Runtime-only; not a profile.
 */
import type { MapNodePayload } from './ontology'
import type { GrowthTriadMetrics } from './mapGrowthMetrics'
import type { GuidanceDimension, GuidanceScript } from './guidanceScripts'
import type { DevelopmentalGuidanceStyle } from '../developmentalGuidance/types'
import { deriveInterpretiveAxes, interpretiveAxesGuideSentence } from '../developmentalGuidance/interpretiveAxes'

function stageVoice(kind: MapNodePayload['kind']): string {
  switch (kind) {
    case 'seed':
      return 'an idea'
    case 'tree':
      return 'an initiative'
    case 'branch':
      return 'a project'
    case 'flower':
      return 'a task'
    case 'fruit':
      return 'an outcome'
    default:
      return 'this item'
  }
}

function dimensionNudge(kind: MapNodePayload['kind'], d: GuidanceDimension): string {
  if (kind === 'seed') {
    if (d === 'water') return 'steady ownership and check-ins feel thin'
    if (d === 'soil') return 'the framing and boundaries could still be tighter'
    return 'there is not much visible proof or artifact yet'
  }
  if (kind === 'tree') {
    if (d === 'water') return 'attention and accountability across stakeholders needs a clearer cadence'
    if (d === 'soil') return 'scope and interpretation may still be drifting between teams'
    return 'outputs and milestones are not quite telling the story yet'
  }
  if (kind === 'branch') {
    if (d === 'water') return 'day-to-day drive on this project could use reinforcement'
    if (d === 'soil') return 'acceptance criteria and dependencies still feel fuzzy'
    return 'the next shippable slice is not obvious'
  }
  if (d === 'water') return 'attention and follow-through look like the leverage point'
  if (d === 'soil') return 'definition and constraints are where ambiguity lingers'
  return 'tangible forward motion is the gap'
}

function weakAreasParagraph(kind: MapNodePayload['kind'], missing: GuidanceDimension[]): string {
  if (missing.length === 0) {
    return 'Nothing is screaming “broken” on the map heuristic — still worth pressure-testing your own read before the next commitment.'
  }
  const bits = missing.map((d) => dimensionNudge(kind, d))
  if (bits.length === 1) return `From the map signals, ${bits[0]}.`
  const last = bits.pop()!
  return `From the map signals, ${bits.join('; ')}, and ${last}.`
}

function styleFromMissingDimensions(missing: GuidanceDimension[]): DevelopmentalGuidanceStyle {
  if (missing.includes('soil')) return 'more_structure'
  if (missing.includes('water')) return 'more_accountability'
  return 'neutral'
}

function softenQuestion(q: string): string {
  const t = q.trim()
  if (!t) return 'What is your honest read, in plain language?'
  if (t.endsWith('?')) return t
  return `${t}?`
}

/**
 * Single guide bubble: conversational opener for the council thread when a map node is in focus.
 */
export function buildGuideOpeningMessage(
  node: MapNodePayload,
  triad: GrowthTriadMetrics | null,
  script: GuidanceScript | null,
): string {
  const title = node.label.trim() || 'this node'
  const stage = stageVoice(node.kind)

  if (!script || (node.kind !== 'seed' && node.kind !== 'tree' && node.kind !== 'branch')) {
    return [
      `You're looking at “${title}” — I'm reading it as ${stage} on the vision map.`,
      '',
      'What do you want to figure out or decide while it is fresh? Reply below; when you want more seats at the table, use Run Council.',
    ].join('\n')
  }

  const weak = weakAreasParagraph(node.kind, script.missing_dimensions)
  const ask = softenQuestion(script.next_best_question)
  const axisSentence = interpretiveAxesGuideSentence(
    deriveInterpretiveAxes({
      missingDimensions: script.missing_dimensions,
      suggestedGuidanceStyle: styleFromMissingDimensions(script.missing_dimensions),
      tally: null,
    }),
  )
  const axisBlock = axisSentence ? ['', axisSentence] : []

  return [
    `Let's tighten this up.`,
    '',
    `You're on “${title}” (${stage}). ${weak}`,
    ...axisBlock,
    '',
    ask,
  ].join('\n')
}
