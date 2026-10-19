import { describe, expect, it } from 'vitest'
import { composeSynopsis } from './MapChatShell'
import type { MapNodePayload } from './ontology'
import type { VisionMapEntityBundle } from './blockersFromVe'
import type { Idea, Initiative, Project, Task } from '../vision-execution/types'

function payload(over: Partial<MapNodePayload> = {}): MapNodePayload {
  return {
    kind: 'tree',
    label: 'Zenaf',
    subtitle: '',
    growth: 'growing',
    condition: 'ok',
    ref: { veType: 'initiative', id: 'i1' },
    summaryLines: [],
    water_level: 'medium',
    fertilizer_pulse: false,
    ...over,
  } as MapNodePayload
}

const H = 3600 * 1000
const ago = (ms: number) => new Date(Date.now() - ms).toISOString()

function bundle(): VisionMapEntityBundle {
  const initiatives: Initiative[] = [
    {
      id: 'i1',
      source_idea_id: null,
      title: 'Zenaf',
      brief: '',
      status: 'Active',
      owner_id: null,
      evaluation_priority: null,
      estimated_cost_ai: '',
      estimated_timeframe_ai: '',
      philosophical_alignment_ai: '',
      next_step_ai: 'Ship the stone sheet.',
      required_assets: [],
      dependencies: '',
      risks: '',
      recommendation: '',
      kill_criteria: '',
      notes: '',
      created_at: ago(30 * 24 * H),
      updated_at: ago(2 * H),
    },
  ]
  const projects: Project[] = [
    {
      id: 'p1', initiative_id: 'i1', title: 'A', brief: '', status: 'Complete',
      owner_id: null, supporting_owner_ids: [], priority: '', start_date: null,
      end_date: null, estimated_weekly_hours: null, next_step_ai: '', notes: '',
      created_at: ago(20 * 24 * H), updated_at: ago(3 * 24 * H),
    },
    {
      id: 'p2', initiative_id: 'i1', title: 'B', brief: '', status: 'Active',
      owner_id: null, supporting_owner_ids: [], priority: '', start_date: null,
      end_date: null, estimated_weekly_hours: null, next_step_ai: '', notes: '',
      created_at: ago(10 * 24 * H), updated_at: ago(5 * H),
    },
  ]
  const tasks: Task[] = [
    {
      id: 't1', project_id: 'p1', parent_task_id: null, title: 'x', description: '',
      assignee_id: null, status: 'Done', priority: '', estimated_hours: null,
      due_date: null, dependency_ids: [], completion_criteria: '', notes: '',
      created_at: ago(15 * 24 * H), updated_at: ago(3 * 24 * H),
    },
    {
      id: 't2', project_id: 'p2', parent_task_id: null, title: 'y', description: '',
      assignee_id: null, status: 'Todo', priority: '', estimated_hours: null,
      due_date: null, dependency_ids: [], completion_criteria: '', notes: '',
      created_at: ago(9 * 24 * H), updated_at: ago(9 * 24 * H),
    },
    {
      id: 't3', project_id: 'p2', parent_task_id: null, title: 'z', description: '',
      assignee_id: null, status: 'In Progress', priority: '', estimated_hours: null,
      due_date: null, dependency_ids: [], completion_criteria: '', notes: '',
      created_at: ago(8 * 24 * H), updated_at: ago(1 * H),
    },
  ]
  const ideas: Idea[] = []
  return { ideas, initiatives, projects, tasks }
}

describe('composeSynopsis', () => {
  it('states where it is at, where it is going, and last touch for an initiative', () => {
    const lines = composeSynopsis(payload(), bundle())
    expect(lines.length).toBe(3)
    expect(lines[0]).toContain('Active')
    expect(lines[0]).toContain('2 projects')
    expect(lines[0]).toContain('3 tasks')
    expect(lines[0]).toContain('1 done')
    expect(lines[1]).toContain('Ship the stone sheet.')
    expect(lines[2]).toContain('2 hr ago')
  })

  it('omits missing pieces instead of inventing them', () => {
    const lines = composeSynopsis(
      payload({ ref: { veType: 'task', id: 'missing' }, kind: 'flower', label: 'Ghost' }),
      bundle(),
    )
    // Unknown entity and no summary lines: empty, never invented.
    expect(lines).toEqual([])
  })

  it('summarizes a task from status and description', () => {
    const b = bundle()
    b.tasks.push({
      id: 't9', project_id: 'p2', parent_task_id: null, title: 'Fix it',
      description: 'It broke on Tuesday.', assignee_id: null, status: 'Blocked',
      priority: '', estimated_hours: null, due_date: null, dependency_ids: [],
      completion_criteria: '', notes: '', created_at: ago(2 * H), updated_at: ago(30 * 60 * 1000),
    })
    const lines = composeSynopsis(
      payload({ ref: { veType: 'task', id: 't9' }, kind: 'flower', label: 'Fix it' }),
      b,
    )
    expect(lines[0]).toContain('Blocked')
    expect(lines[0]).toContain('It broke on Tuesday.')
    expect(lines[1]).toContain('30 min ago')
  })

  it('never emits soil/water/fruit abstractions', () => {
    const lines = composeSynopsis(payload(), bundle())
    const text = lines.join(' ').toLowerCase()
    expect(text).not.toMatch(/\bsoil\b/)
    expect(text).not.toMatch(/\bwater\b/)
  })
})
