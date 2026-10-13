import { describe, expect, it } from 'vitest'
import { deriveWaterLevel, waterLevelFromVital, vitalForInitiative, vitalForProject, vitalForTask } from './mapVitalForces'
import type { Initiative, Project, Task } from '../vision-execution/types'

describe('deriveWaterLevel', () => {
  it('high when owner and execution shape complete', () => {
    expect(deriveWaterLevel(true, null, true)).toBe('high')
  })

  it('medium when owner but shape incomplete', () => {
    expect(deriveWaterLevel(true, null, false)).toBe('medium')
  })

  it('medium when shape complete without owner', () => {
    expect(deriveWaterLevel(false, null, true)).toBe('medium')
  })

  it('medium when recent update only', () => {
    const iso = new Date().toISOString()
    expect(deriveWaterLevel(false, iso, false)).toBe('medium')
  })

  it('low when nothing applies', () => {
    expect(deriveWaterLevel(false, '2000-01-01T00:00:00.000Z', false)).toBe('low')
  })
})

describe('vitalForProject + waterLevelFromVital', () => {
  const base = (over: Partial<Project>): Project =>
    ({
      id: 'p1',
      initiative_id: 'i1',
      title: 'T',
      brief: '',
      status: 'active',
      owner_id: 'o1',
      supporting_owner_ids: [],
      priority: '3',
      start_date: null,
      end_date: null,
      estimated_weekly_hours: null,
      next_step_ai: '',
      notes: '',
      created_at: '2025-01-01T00:00:00Z',
      updated_at: '2025-01-01T00:00:00Z',
      ...over,
    }) as Project

  it('high when owner, dates, and weekly hours set', () => {
    const v = vitalForProject(
      base({
        start_date: '2025-02-01',
        end_date: '2025-06-01',
        estimated_weekly_hours: 4,
      }),
    )
    expect(waterLevelFromVital(v)).toBe('high')
  })

  it('medium when owner but missing hours', () => {
    const v = vitalForProject(
      base({
        start_date: '2025-02-01',
        end_date: '2025-06-01',
        estimated_weekly_hours: null,
      }),
    )
    expect(waterLevelFromVital(v)).toBe('medium')
  })
})

describe('vitalForInitiative', () => {
  const base = (over: Partial<Initiative>): Initiative =>
    ({
      id: 'i1',
      source_idea_id: null,
      title: 'Ini',
      brief: 'b',
      status: 'Draft',
      owner_id: 'o1',
      estimated_timeframe_ai: 'Q2',
      seats: [],
      required_assets: [],
      dependencies: '',
      risks: '',
      recommendation: '',
      kill_criteria: '',
      notes: '',
      next_step_ai: '',
      estimated_cost_ai: '',
      philosophical_alignment_ai: '',
      evaluation_priority: null,
      created_at: '2025-01-01T00:00:00Z',
      updated_at: '2025-01-01T00:00:00Z',
      ...over,
    }) as Initiative

  it('high when owner, timeframe, and no seats (optional)', () => {
    const v = vitalForInitiative(base({ estimated_timeframe_ai: '6 weeks', seats: [] }))
    expect(waterLevelFromVital(v)).toBe('high')
  })

  it('medium when seats exist but one unassigned', () => {
    const v = vitalForInitiative(
      base({
        estimated_timeframe_ai: '6 weeks',
        seats: [
          { role: 'A', assigned_person_id: 'p1', estimated_effort: null, notes: '' },
          { role: 'B', assigned_person_id: null, estimated_effort: null, notes: '' },
        ],
      }),
    )
    expect(waterLevelFromVital(v)).toBe('medium')
  })

  it('high when all seats assigned', () => {
    const v = vitalForInitiative(
      base({
        estimated_timeframe_ai: '6 weeks',
        seats: [
          { role: 'A', assigned_person_id: 'p1', estimated_effort: null, notes: '' },
          { role: 'B', assigned_person_id: 'p2', estimated_effort: null, notes: '' },
        ],
      }),
    )
    expect(waterLevelFromVital(v)).toBe('high')
  })
})

describe('vitalForTask', () => {
  const base = (over: Partial<Task>): Task =>
    ({
      id: 't1',
      project_id: 'p1',
      parent_task_id: null,
      title: 'Task',
      description: '',
      assignee_id: 'a1',
      status: 'open',
      priority: '2',
      estimated_hours: null,
      due_date: null,
      dependency_ids: [],
      completion_criteria: '',
      notes: '',
      created_at: '2025-01-01T00:00:00Z',
      updated_at: '2025-01-01T00:00:00Z',
      ...over,
    }) as Task

  it('high with assignee and due_date', () => {
    expect(waterLevelFromVital(vitalForTask(base({ due_date: '2025-03-15' })))).toBe('high')
  })

  it('medium with assignee but no due or hours', () => {
    expect(waterLevelFromVital(vitalForTask(base({ due_date: null, estimated_hours: null })))).toBe('medium')
  })
})
