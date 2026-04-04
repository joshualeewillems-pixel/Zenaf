import type { MapEntityKind, MapNodePayload } from './ontology'
import type { GrowthTriadMetrics } from './mapGrowthMetrics'

export type GuidanceStage = MapEntityKind
export type GuidanceDimension = 'water' | 'soil' | 'fruit'

export type GuidanceScript = {
  stage: GuidanceStage
  missing_dimensions: GuidanceDimension[]
  next_best_question: string
  suggested_actions: GuidanceAction[]
  optional_assessment?: string
}

export type StructureProposal = {
  outcome: string
  brief_summary: string
  blocker_risk: string
  next_step: string
  possible_project_task_split: string[]
}

export const STRUCTURE_PROPOSAL_TARGET_FIELDS = {
  outcome: 'desired_outcome',
  brief_summary: 'brief',
  blocker_risk: 'risks',
  next_step: 'next_step_ai',
  possible_project_task_split: 'proposed child projects/tasks',
} as const

export type GuidanceAction = {
  id: string
  label: string
  kind: 'ask_user' | 'ask_council' | 'commit_structure'
  councilPrompt?: string
  question?: string
  commitHint?: string
}

const MISSING_DIMENSION_THRESHOLD = 0.45

const DIMENSION_PRIORITY: GuidanceDimension[] = ['water', 'soil', 'fruit']

export const STAGE_BASELINE_QUESTIONS: Record<'seed' | 'tree' | 'branch', string> = {
  seed: 'What is the smallest proof this idea is worth another week of attention?',
  tree: 'What is the single initiative outcome that would make this quarter clearly better?',
  branch: 'What deliverable can this project ship next that people can actually use?',
}

/** Primary triad-dimension prompts for map kinds seed / tree / branch (also used by guidance scripts). */
export const STAGE_FOCUSED_QUESTIONS: Record<
  'seed' | 'tree' | 'branch',
  Record<GuidanceDimension, string>
> = {
  seed: {
    water: 'Who will actively own this idea for the next 7 days, and what check-in proves motion?',
    soil: 'What one-sentence problem and boundary will keep this idea from staying vague?',
    fruit: 'What tiny artifact can you publish this week to test whether this idea creates value?',
  },
  tree: {
    water: 'Who are the accountable owners, and when is the next visible progress checkpoint?',
    soil: 'What is the initiative scope boundary so teams stop interpreting this in different ways?',
    fruit: 'What measurable milestone will prove this initiative is converting effort into outcomes?',
  },
  branch: {
    water: 'Who is driving this project day-to-day, and what weekly signal shows momentum?',
    soil: 'What acceptance criteria and dependencies are still unclear for this project?',
    fruit: 'What is the next shippable increment users can see, touch, or adopt?',
  },
}

const STAGE_ACTIONS: Record<'seed' | 'tree' | 'branch', Record<GuidanceDimension, string[]>> = {
  seed: {
    water: [
      'Assign one owner and schedule a 15-minute check-in this week.',
      'Capture one risk and one next step in the node summary.',
    ],
    soil: [
      'Write a one-sentence problem statement and one explicit non-goal.',
      'Link this seed to the nearest initiative path it could feed.',
    ],
    fruit: [
      'Draft a tiny test artifact (note, mock, or prototype).',
      'Define one success signal you can observe within 7 days.',
    ],
  },
  tree: {
    water: [
      'Confirm responsible owner(s) and publish next checkpoint date.',
      'Ask council for blockers if owner bandwidth looks thin.',
    ],
    soil: [
      'Set 2-3 initiative boundaries and remove adjacent scope drift.',
      'List top dependencies that can stop delivery this cycle.',
    ],
    fruit: [
      'Define one milestone with a clear done signal.',
      'Create or update one branch that directly ships toward that milestone.',
    ],
  },
  branch: {
    water: [
      'Confirm a project driver and one weekly operating cadence.',
      'Escalate unresolved blockers before the next work session.',
    ],
    soil: [
      'Write acceptance criteria for the next increment.',
      'Turn unknowns into concrete tasks with owners.',
    ],
    fruit: [
      'Select the next user-visible deliverable and target date.',
      'Define release evidence (demo, link, adoption, or usage signal).',
    ],
  },
}

/** Exported for council developmental context (same strings as map guidance UI). */
export const STAGE_ASSESSMENT: Record<'seed' | 'tree' | 'branch', string> = {
  seed: 'Optional: ask council to stress-test whether this idea should be promoted to initiative.',
  tree: 'Optional: run a deeper council check for cross-team risks and sequencing conflicts.',
  branch: 'Optional: run a readiness check before committing to ship date or broader rollout.',
}

export const EXAMPLE_GUIDANCE_SCRIPTS: Record<'seed' | 'tree' | 'branch', GuidanceScript> = {
  seed: {
    stage: 'seed',
    missing_dimensions: ['soil', 'fruit'],
    next_best_question: STAGE_FOCUSED_QUESTIONS.seed.soil,
    suggested_actions: [
      {
        id: 'seed_ask_user',
        label: 'Answer the next question for this seed.',
        kind: 'ask_user',
        question: STAGE_FOCUSED_QUESTIONS.seed.soil,
      },
      {
        id: 'seed_ask_council',
        label: 'Ask council for help on this same question.',
        kind: 'ask_council',
        councilPrompt: `Help me answer this seed question:\n"${STAGE_FOCUSED_QUESTIONS.seed.soil}"\nGive concrete next steps and tradeoffs.`,
      },
      {
        id: 'seed_commit_structure',
        label: 'Commit this answer into initiative/project structure suggestions.',
        kind: 'commit_structure',
        commitHint: 'Map this seed answer into candidate initiative, project, owner, and milestone fields.',
      },
    ],
    optional_assessment: STAGE_ASSESSMENT.seed,
  },
  tree: {
    stage: 'tree',
    missing_dimensions: ['water'],
    next_best_question: STAGE_FOCUSED_QUESTIONS.tree.water,
    suggested_actions: [
      {
        id: 'tree_ask_user',
        label: 'Answer the next question for this initiative.',
        kind: 'ask_user',
        question: STAGE_FOCUSED_QUESTIONS.tree.water,
      },
      {
        id: 'tree_ask_council',
        label: 'Ask council for help on this same question.',
        kind: 'ask_council',
        councilPrompt: `Help me answer this initiative question:\n"${STAGE_FOCUSED_QUESTIONS.tree.water}"\nKeep it practical and execution-oriented.`,
      },
      {
        id: 'tree_commit_structure',
        label: 'Commit this answer into initiative/project structure suggestions.',
        kind: 'commit_structure',
        commitHint:
          'Translate this initiative answer into owners, scope boundaries, dependencies, and next milestone fields.',
      },
    ],
    optional_assessment: STAGE_ASSESSMENT.tree,
  },
  branch: {
    stage: 'branch',
    missing_dimensions: ['fruit'],
    next_best_question: STAGE_FOCUSED_QUESTIONS.branch.fruit,
    suggested_actions: [
      {
        id: 'branch_ask_user',
        label: 'Answer the next question for this project.',
        kind: 'ask_user',
        question: STAGE_FOCUSED_QUESTIONS.branch.fruit,
      },
      {
        id: 'branch_ask_council',
        label: 'Ask council for help on this same question.',
        kind: 'ask_council',
        councilPrompt: `Help me answer this project question:\n"${STAGE_FOCUSED_QUESTIONS.branch.fruit}"\nOffer a small shippable plan.`,
      },
      {
        id: 'branch_commit_structure',
        label: 'Commit this answer into project/task/deliverable structure suggestions.',
        kind: 'commit_structure',
        commitHint:
          'Map this project answer into concrete task list, acceptance criteria, and deliverable evidence fields.',
      },
    ],
    optional_assessment: STAGE_ASSESSMENT.branch,
  },
}

export function detectMissingDimensions(metrics: GrowthTriadMetrics): GuidanceDimension[] {
  const values: Record<GuidanceDimension, number> = {
    water: metrics.water,
    soil: metrics.soil,
    fruit: metrics.fruit,
  }
  return [...DIMENSION_PRIORITY]
    .sort((a, b) => values[a] - values[b])
    .filter((dimension) => values[dimension] < MISSING_DIMENSION_THRESHOLD)
}

export function buildGuidanceScriptForNode(
  node: MapNodePayload,
  metrics: GrowthTriadMetrics,
): GuidanceScript | null {
  if (node.kind !== 'seed' && node.kind !== 'tree' && node.kind !== 'branch') return null

  const missing = detectMissingDimensions(metrics)
  const primaryDimension = missing[0]

  const actions: GuidanceAction[] = []
  const pushUnique = (next: GuidanceAction) => {
    if (!actions.some((a) => a.id === next.id || a.label === next.label)) actions.push(next)
  }

  const primary = primaryDimension ?? 'fruit'
  const question = STAGE_FOCUSED_QUESTIONS[node.kind][primary] ?? STAGE_BASELINE_QUESTIONS[node.kind]
  pushUnique({
    id: `${node.kind}_ask_user`,
    label: `Answer this now: ${question}`,
    kind: 'ask_user',
    question,
  })
  pushUnique({
    id: `${node.kind}_ask_council`,
    label: 'Ask council for help on this same question.',
    kind: 'ask_council',
    councilPrompt: [
      `Help me answer this ${node.kind} question:`,
      `"${question}"`,
      `Context: ${node.label}`,
      'Return concise recommendations I can execute now.',
    ].join('\n'),
  })
  pushUnique({
    id: `${node.kind}_commit_structure`,
    label: 'Commit this conversational answer into structured VE suggestions.',
    kind: 'commit_structure',
    commitHint: `Convert this ${node.kind} answer into proposed VE fields (owner, scope, milestones, deliverables).`,
  })

  return {
    stage: node.kind,
    missing_dimensions: missing,
    next_best_question: question,
    suggested_actions: actions.slice(0, 3),
    optional_assessment: STAGE_ASSESSMENT[node.kind],
  }
}

function firstSentence(text: string): string {
  const trimmed = text.trim()
  if (!trimmed) return ''
  const match = trimmed.match(/^(.+?[.!?])(\s|$)/)
  return (match?.[1] ?? trimmed).slice(0, 240)
}

function firstLine(text: string): string {
  const line = text
    .split('\n')
    .map((p) => p.trim())
    .find(Boolean)
  return (line ?? '').slice(0, 180)
}

function splitCandidateLines(answer: string): string[] {
  const lines = answer
    .split('\n')
    .map((l) => l.trim().replace(/^[-*]\s+/, ''))
    .filter(Boolean)
  return lines.length > 0 ? lines : [firstSentence(answer)]
}

export function buildStructureProposalFromAnswer(
  node: MapNodePayload,
  question: string,
  answerDraft: string,
): StructureProposal {
  const base = answerDraft.trim()
  const summary = firstSentence(base) || `${node.label}: working direction captured from conversation.`
  const lines = splitCandidateLines(base)
  const riskLine =
    lines.find((l) => /risk|block|depend|unknown|constraint|delay|unclear/i.test(l)) ??
    `Key risk to watch: unresolved dependencies for ${node.kind} progress.`
  const nextStep =
    lines.find((l) => /next|first|start|ship|draft|assign|plan|define/i.test(l)) ??
    `Run one concrete next step from the answer and review progress in the next check-in.`
  const outcome =
    lines.find((l) => /outcome|result|impact|deliver|ship|value/i.test(l)) ??
    `Desired outcome: a concrete, user-visible improvement tied to "${question}".`

  const splitPrefix =
    node.kind === 'seed'
      ? 'Potential split: promote idea into one initiative and one validation project.'
      : node.kind === 'tree'
        ? 'Potential split: keep initiative milestone and break execution into projects.'
        : 'Potential split: break project into task track and release track.'
  const split = [splitPrefix, ...lines.slice(0, 2)].slice(0, 3)

  return {
    outcome: outcome.slice(0, 220),
    brief_summary: summary.slice(0, 260),
    blocker_risk: riskLine.slice(0, 220),
    next_step: firstLine(nextStep) || nextStep.slice(0, 220),
    possible_project_task_split: split,
  }
}
