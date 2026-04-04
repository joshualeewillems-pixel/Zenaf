import type { Idea, Initiative, Project, Task } from '../vision-execution/types'
import { conditionFromSignals, growthFromStatus, isStaleIso } from './deriveVisualState'
import {
  deriveFertilizerPulse,
  vitalForIdea,
  vitalForInitiative,
  vitalForProject,
  vitalForTask,
  waterLevelFromVital,
} from './mapVitalForces'
import type { CouncilTeacherPreview, MapNodePayload } from './ontology'
import type { StudioCouncilRunRow } from './studioCouncilTypes'

/** Synthetic outcome until VE exposes a first-class outcome row (projection-only). */
export type SampleOutcome = {
  id: string
  initiative_id: string
  title: string
  metric?: string
  status: string
  updated_at: string
}

export type VisionMapSampleBundle = {
  idea: Idea
  initiative: Initiative
  projects: Project[]
  tasks: Task[]
  outcomes: SampleOutcome[]
}

const now = new Date().toISOString()

/**
 * Single initiative tree with branches (projects), flowers (tasks), and fruit (outcomes).
 * Read-only prototype data — mirrors VE field names where applicable.
 */
export function getVisionMapSampleBundle(): VisionMapSampleBundle {
  const idea: Idea = {
    id: 'sample-idea-seed',
    title: 'Composable local cockpit',
    summary: 'Unify workspace, council, and vision execution in one operator surface.',
    description: 'Seed concept for the Phase A map prototype.',
    status: 'Exploring',
    tags: ['product', 'ux'],
    created_by: 'prototype',
    desired_outcome: 'Operators trust the map as primary spatial view.',
    linked_people: [],
    linked_assets: [],
    linked_ideas: [],
    created_at: now,
    updated_at: now,
  }

  const initiative: Initiative = {
    id: 'sample-init-tree',
    source_idea_id: idea.id,
    title: 'Vision map + chat shell',
    brief: 'React Flow read-only graph; dual visual channels; node-scoped chat binding.',
    status: 'Active',
    owner_id: null,
    priority_rank_manual: 2,
    strategic_value_manual: 4,
    energy_impact_manual: 3,
    evaluation_priority: 4,
    estimated_cost_ai: 'Medium',
    estimated_timeframe_ai: '4–6 weeks',
    philosophical_alignment_ai: 'Strong',
    next_step_ai: 'Ship Phase A to internal operators.',
    required_people: [],
    required_assets: [],
    dependencies: '',
    risks: 'Layout persistence not in v1',
    recommendation: 'Proceed; keep VE API unchanged.',
    counts_toward_capacity: 1,
    manual_override: '',
    kill_criteria: '',
    notes: '',
    created_at: now,
    updated_at: now,
  }

  const projects: Project[] = [
    {
      id: 'sample-proj-branch-a',
      initiative_id: initiative.id,
      title: 'Canvas & nodes',
      brief: 'React Flow graph, custom nodes, growth + condition styling.',
      status: 'Active',
      owner_id: null,
      supporting_owner_ids: [],
      required_assets: [],
      priority: '2',
      start_date: null,
      end_date: null,
      estimated_weekly_hours: 8,
      deliverables: '',
      complexity: '',
      current_focus: '',
      next_step_ai: 'Polish selection + chat shell.',
      notes: '',
      created_at: now,
      updated_at: now,
    },
    {
      id: 'sample-proj-branch-b',
      initiative_id: initiative.id,
      title: 'Operator bridge',
      brief: 'One-click switch to Vision & Execution tables.',
      status: 'Draft',
      owner_id: null,
      supporting_owner_ids: [],
      required_assets: [],
      priority: '3',
      start_date: null,
      end_date: null,
      estimated_weekly_hours: 4,
      deliverables: '',
      complexity: '',
      current_focus: '',
      next_step_ai: 'Wire deep-link selection (later).',
      notes: '',
      created_at: now,
      // Stale updated_at → condition channel "stale" on this branch
      updated_at: new Date(Date.now() - 30 * 86400000).toISOString(),
    },
  ]

  const tasks: Task[] = [
    {
      id: 'sample-task-flower-1',
      project_id: projects[0].id,
      parent_task_id: null,
      title: 'Install React Flow + sample graph',
      description: '',
      assignee_id: null,
      status: 'In progress',
      priority: '1',
      estimated_hours: 4,
      due_date: null,
      dependency_ids: [],
      completion_criteria: 'Graph renders with one tree.',
      notes: '',
      created_at: now,
      updated_at: now,
    },
    {
      id: 'sample-task-flower-2',
      project_id: projects[0].id,
      parent_task_id: null,
      title: 'Dual-channel node chrome',
      description: '',
      assignee_id: null,
      status: 'Todo',
      priority: '2',
      estimated_hours: 6,
      due_date: null,
      dependency_ids: [],
      completion_criteria: 'Growth + condition visible on nodes.',
      notes: '',
      created_at: now,
      updated_at: now,
    },
    {
      id: 'sample-task-flower-3',
      project_id: projects[0].id,
      parent_task_id: null,
      title: 'Council copy review',
      description: '',
      assignee_id: null,
      status: 'Blocked',
      priority: '1',
      estimated_hours: 2,
      due_date: null,
      dependency_ids: [],
      completion_criteria: 'Sign-off on teacher hints copy.',
      notes: 'Waiting on policy wording.',
      created_at: now,
      updated_at: now,
    },
    {
      id: 'sample-task-flower-4',
      project_id: projects[1].id,
      parent_task_id: null,
      title: 'Add nav entry Vision map',
      description: '',
      assignee_id: null,
      status: 'Todo',
      priority: '2',
      estimated_hours: 1,
      due_date: null,
      dependency_ids: [],
      completion_criteria: 'App.tsx nav + view switch.',
      notes: '',
      created_at: now,
      updated_at: now,
    },
    {
      id: 'sample-task-flower-5',
      project_id: projects[1].id,
      parent_task_id: null,
      title: 'Document projection rules',
      description: '',
      assignee_id: null,
      status: 'Done',
      priority: '3',
      estimated_hours: 2,
      due_date: null,
      dependency_ids: [],
      completion_criteria: 'Short internal doc.',
      notes: '',
      created_at: now,
      updated_at: now,
    },
  ]

  const outcomes: SampleOutcome[] = [
    {
      id: 'sample-outcome-fruit-1',
      initiative_id: initiative.id,
      title: 'Phase A demo approved',
      metric: 'Stakeholder sign-off',
      status: 'Tracking',
      updated_at: now,
    },
    {
      id: 'sample-outcome-fruit-2',
      initiative_id: initiative.id,
      title: 'Map used weekly',
      metric: '≥3 operator sessions / week',
      status: 'Not yet',
      updated_at: now,
    },
  ]

  return { idea, initiative, projects, tasks, outcomes }
}

/** Build per-node payload for the graph (includes demo council/teacher stubs). */
export function buildSampleNodePayloads(bundle: VisionMapSampleBundle): Map<string, MapNodePayload> {
  const { idea, initiative, projects, tasks, outcomes } = bundle
  const map = new Map<string, MapNodePayload>()
  const noRuns: StudioCouncilRunRow[] = []

  const vIdea = vitalForIdea(idea)
  map.set(`seed:${idea.id}`, {
    kind: 'seed',
    label: idea.title,
    subtitle: 'Idea',
    growth: growthFromStatus(idea.status),
    condition: 'healthy',
    ref: { veType: 'idea', id: idea.id },
    summaryLines: [idea.summary, `Status: ${idea.status}`, idea.desired_outcome ? `Desired: ${idea.desired_outcome}` : ''].filter(
      Boolean,
    ),
    councilTeacher: sampleCouncilStub('idea', false, false),
    water_level: waterLevelFromVital(vIdea),
    fertilizer_pulse: deriveFertilizerPulse({ veType: 'idea', id: idea.id }, vIdea.entityUpdatedAt ?? null, noRuns),
  })

  const vIni = vitalForInitiative(initiative)
  map.set(`tree:${initiative.id}`, {
    kind: 'tree',
    label: initiative.title,
    subtitle: 'Initiative',
    growth: growthFromStatus(initiative.status),
    condition: 'healthy',
    ref: { veType: 'initiative', id: initiative.id },
    summaryLines: [
      initiative.brief.slice(0, 200) + (initiative.brief.length > 200 ? '…' : ''),
      `Status: ${initiative.status}`,
      initiative.next_step_ai ? `Next step: ${initiative.next_step_ai}` : '',
    ].filter(Boolean),
    councilTeacher: sampleCouncilStub('initiative', false, false),
    water_level: waterLevelFromVital(vIni),
    fertilizer_pulse: deriveFertilizerPulse({ veType: 'initiative', id: initiative.id }, vIni.entityUpdatedAt ?? null, noRuns),
  })

  for (const p of projects) {
    const stale = isStaleIso(p.updated_at, 14)
    const vP = vitalForProject(p)
    map.set(`branch:${p.id}`, {
      kind: 'branch',
      label: p.title,
      subtitle: 'Project',
      growth: growthFromStatus(p.status),
      condition: conditionFromSignals({ stale, blocked: false }),
      ref: { veType: 'project', id: p.id },
      summaryLines: [
        p.brief.slice(0, 160) + (p.brief.length > 160 ? '…' : ''),
        `Status: ${p.status}`,
        stale ? 'No updates in >14d (demo stale signal)' : '',
      ].filter(Boolean),
      councilTeacher: sampleCouncilStub('project', false, stale),
      water_level: waterLevelFromVital(vP),
      fertilizer_pulse: deriveFertilizerPulse({ veType: 'project', id: p.id }, vP.entityUpdatedAt ?? null, noRuns),
    })
  }

  for (const t of tasks) {
    const blocked = t.status.toLowerCase().includes('block')
    const warn = t.id === 'sample-task-flower-2'
    const veto = t.id === 'sample-task-flower-3'
    const vT = vitalForTask(t)
    map.set(`flower:${t.id}`, {
      kind: 'flower',
      label: t.title,
      subtitle: 'Task',
      growth: growthFromStatus(t.status),
      condition: conditionFromSignals({
        blocked,
        stale: false,
        teacher_vetoed: veto,
        teacher_warning: warn,
      }),
      ref: { veType: 'task', id: t.id },
      summaryLines: [
        `Status: ${t.status}`,
        t.completion_criteria ? `Done when: ${t.completion_criteria}` : '',
        t.notes ? `Notes: ${t.notes}` : '',
      ].filter(Boolean),
      councilTeacher: sampleCouncilStub('task', veto, warn && !veto),
      water_level: waterLevelFromVital(vT),
      fertilizer_pulse: deriveFertilizerPulse({ veType: 'task', id: t.id }, vT.entityUpdatedAt ?? null, noRuns),
    })
  }

  for (const o of outcomes) {
    map.set(`fruit:${o.id}`, {
      kind: 'fruit',
      label: o.title,
      subtitle: 'Outcome',
      growth: growthFromStatus(o.status),
      condition: 'healthy',
      ref: { veType: 'outcome', id: o.id },
      summaryLines: [o.metric ? `Metric: ${o.metric}` : '', `Status: ${o.status}`].filter(Boolean),
      councilTeacher: sampleCouncilStub('outcome', false, false),
      water_level: 'medium',
      fertilizer_pulse: false,
    })
  }

  return map
}

function sampleCouncilStub(
  scope: string,
  vetoed: boolean,
  warned: boolean,
): CouncilTeacherPreview {
  return {
    teacher_enforcement_mode: vetoed ? 'veto' : warned ? 'warn' : 'shadow',
    teacher_vetoed: vetoed,
    teacher_warning: warned,
    teacher_final_source: vetoed ? 'teacher_refusal' : warned ? 'native' : 'native',
    teacher_reason_codes: vetoed
      ? ['privacy_secret_externalization']
      : warned
        ? ['teacher_native_disagreement']
        : [],
    last_run_at: 'prototype',
    summary:
      scope === 'task' && vetoed
        ? 'Last council: teacher veto — replaced native draft with safe refusal (sample).'
        : scope === 'task' && warned
          ? 'Last council: teacher warning — native kept; review dual-channel styling (sample).'
          : 'No recent council run on this node (sample).',
  }
}
