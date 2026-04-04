import type { VisionMapEntityBundle } from './blockersFromVe'
import { STAGE_FOCUSED_QUESTIONS } from './guidanceScripts'
import type { GrowthTriadMetrics } from './mapGrowthMetrics'
import { resolveInspectEntityRef } from './mapTriadInspector'
import type { TriadInspectorSection } from './mapTriadInspector'
import type { MapNodePayload } from './ontology'

/** Second line per dimension for the same map kind — rotated on repeat clicks. */
const ALT_FOCUS: Record<'seed' | 'tree' | 'branch', Record<TriadInspectorSection, string>> = {
  seed: {
    water: 'Name one accountable owner for this idea for the next 7 days — what visible motion do you expect by Friday?',
    soil: 'State the problem in one sentence, then name one explicit non-goal so this idea cannot sprawl.',
    fruit: 'What is the smallest artifact you could publish this week that tests whether this idea matters?',
  },
  tree: {
    water: 'Who has decision rights when this initiative stalls — and what is the next checkpoint date on the calendar?',
    soil: 'What boundary would stop adjacent teams from pulling this initiative into different directions?',
    fruit: 'What single milestone would prove this initiative is producing real outcomes, not just activity?',
  },
  branch: {
    water: 'Who is the day-to-day driver — and what weekly signal will show this project is actually moving?',
    soil: 'What acceptance criteria or dependency is still fuzzy for the next increment?',
    fruit: 'What is the next slice users can see or use — and what proves it shipped?',
  },
}

const FLOWER_POOL: Record<TriadInspectorSection, [string, string, string]> = {
  water: [
    'Who owns finishing this task in the next few days, and what is blocking their next hour of work?',
    'If this task slips, who is the one person to escalate to — and what do they need from you?',
    'What handoff or approval is quietly starving this task of attention?',
  ],
  soil: [
    'What does “done” mean for this task — what is still ambiguous in the definition?',
    'List the one dependency that could invalidate the plan for this task if it changes.',
    'What context would a newcomer need to execute this task without another meeting?',
  ],
  fruit: [
    'What concrete output or link proves this task is finished — not just “status updated”?',
    'Who receives the handoff when this task completes, and what do they get?',
    'What is the smallest demo, doc, or artifact that closes the loop on this task?',
  ],
}

const OUTCOME_NODE_POOL: Record<TriadInspectorSection, [string, string]> = {
  water: [
    'Who is accountable for sustaining the value this outcome represents after delivery?',
    'Who should be in the loop if this outcome regresses or needs a follow-on?',
  ],
  soil: [
    'What context does someone need to trust that this outcome was real — not just declared?',
    'What assumptions about scope or quality does this outcome still leave unstated?',
  ],
  fruit: [
    'Name the tangible deliverable or evidence behind this outcome in one line.',
    'If you had to show this outcome to a skeptic, what artifact would you open first?',
  ],
}

const FALLBACK_POOL: Record<TriadInspectorSection, [string, string]> = {
  water: [
    'Who owns forward motion on this item for the next week — and what proves it?',
    'What resource, approval, or handoff is the real bottleneck for people and attention here?',
  ],
  soil: [
    'What is still fuzzy about scope, criteria, or boundaries for this item?',
    'What single clarification would make the next decision obvious?',
  ],
  fruit: [
    'What is the next concrete output or ship signal for this item?',
    'What would “good enough shipped” look like in one sentence?',
  ],
}

function clipLabel(label: string): string {
  const t = label.trim()
  if (t.length <= 56) return t
  return `${t.slice(0, 53)}…`
}

function metricNudge(section: TriadInspectorSection, metrics: GrowthTriadMetrics | null): 0 | 1 {
  if (!metrics) return 0
  if (section === 'water' && metrics.water < 0.42) return 1
  if (section === 'soil' && metrics.soil < 0.42) return 1
  if (section === 'fruit' && metrics.fruit < 0.42) return 1
  return 0
}

/**
 * Local, deterministic suggested council question for the selected map node and triad section.
 * `variantIndex` should increment when the user clicks the same section again for the same selection.
 */
export function buildTriadSuggestedQuestion(
  selected: MapNodePayload,
  bundle: VisionMapEntityBundle | null,
  metrics: GrowthTriadMetrics | null,
  section: TriadInspectorSection,
  variantIndex: number,
): string {
  const label = clipLabel(selected.label || 'this item')
  const nudge = metricNudge(section, metrics)
  const ix = (variantIndex + nudge) % 64

  const kind = selected.kind
  if (kind === 'seed' || kind === 'tree' || kind === 'branch') {
    const primary = STAGE_FOCUSED_QUESTIONS[kind][section]
    const alt = ALT_FOCUS[kind][section]
    return ix % 2 === 0 ? primary : alt
  }

  if (kind === 'flower') {
    const pool = FLOWER_POOL[section]
    return `${pool[ix % pool.length]!} — “${label}”`
  }

  if (kind === 'fruit') {
    const pool = OUTCOME_NODE_POOL[section]
    return `${pool[ix % pool.length]!} — “${label}”`
  }

  const ref = resolveInspectEntityRef(selected)
  const task =
    ref.veType === 'task' && bundle ? bundle.tasks.find((t) => t.id === ref.id) : null
  const blocked = task && (/\bblock/i.test(task.status || '') || /\bblock/i.test(task.notes || ''))
  const base = FALLBACK_POOL[section][ix % 2]!
  if (section === 'water' && blocked) {
    return `${base} — “${label}” (looks blocked — who can unblock it?)`
  }
  return `${base} — “${label}”`
}
