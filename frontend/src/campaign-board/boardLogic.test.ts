import { describe, expect, it } from 'vitest'
import type { Project, Task } from '../vision-execution/types'
import {
  buildOverview,
  buildRoutes,
  computePxPerDay,
  dateAtFraction,
  declareTerrain,
  deriveObstacles,
  fractionForDate,
  projectSpan,
} from './boardLogic'

const NOW = new Date('2026-06-15T12:00:00').getTime()

function project(partial: Partial<Project>): Project {
  return {
    id: 'p1',
    initiative_id: null,
    title: 'Project',
    brief: '',
    status: 'Active',
    owner_id: null,
    supporting_owner_ids: [],
    priority: '',
    start_date: null,
    end_date: null,
    estimated_weekly_hours: null,
    next_step_ai: '',
    notes: '',
    created_at: '2026-01-01T00:00:00',
    updated_at: '2026-01-01T00:00:00',
    ...partial,
  }
}

function task(partial: Partial<Task>): Task {
  return {
    id: 't1',
    project_id: 'p1',
    parent_task_id: null,
    title: 'Task',
    description: '',
    assignee_id: null,
    status: 'Todo',
    priority: '',
    estimated_hours: null,
    due_date: null,
    dependency_ids: [],
    completion_criteria: '',
    notes: '',
    created_at: '2026-01-01T00:00:00',
    updated_at: '2026-01-01T00:00:00',
    ...partial,
  }
}

describe('projectSpan', () => {
  it('uses the project’s recorded dates when both exist', () => {
    const span = projectSpan(
      project({ start_date: '2026-06-01', end_date: '2026-06-19' }),
      [],
      NOW,
    )
    expect(span.source).toBe('project')
    expect(span.days).toBe(18)
  })

  it('recovers the window from task due dates when the project has none', () => {
    const span = projectSpan(
      project({}),
      [task({ due_date: '2026-06-03' }), task({ id: 't2', due_date: '2026-06-10' })],
      NOW,
    )
    expect(span.source).toBe('tasks')
    expect(span.days).toBe(7)
  })

  it('falls back to a provisional window when nothing is dated', () => {
    const span = projectSpan(project({}), [task({})], NOW)
    expect(span.source).toBe('provisional')
    expect(span.days).toBe(30)
  })

  it('round-trips fraction ↔ date', () => {
    const span = projectSpan(project({ start_date: '2026-06-01', end_date: '2026-06-19' }), [], NOW)
    const mid = dateAtFraction(span, 0.5)
    expect(fractionForDate(span, mid.getTime())).toBeCloseTo(0.5, 5)
  })
})

describe('deriveObstacles', () => {
  const span = projectSpan(project({ start_date: '2026-06-01', end_date: '2026-06-30' }), [], NOW)

  it('declares a blocked task standing with a person as combatant resistance', () => {
    const t = task({ status: 'Blocked', assignee_id: 'person-9' })
    const obs = deriveObstacles(project({}), [t], [t], span, NOW)
    expect(obs).toHaveLength(1)
    expect(obs[0].kind).toBe('resistance')
    expect(obs[0].domain).toBe('people')
    expect(obs[0].standing).toBe('documented')
  })

  it('declares a plain blocked task as a confirmed blockage', () => {
    const dep = task({ id: 'dep', status: 'Todo' })
    const t = task({ id: 't2', status: 'Blocked', dependency_ids: ['dep'] })
    const obs = deriveObstacles(project({}), [t, dep], [t, dep], span, NOW)
    const blocked = obs.find((o) => o.taskId === 't2')
    expect(blocked?.kind).toBe('blocked')
    expect(blocked?.domain).toBe('people')
  })

  it('marks an open task past its recorded date as a time obstacle, neutrally', () => {
    const t = task({ due_date: '2026-06-10' })
    const obs = deriveObstacles(project({}), [t], [t], span, NOW)
    expect(obs).toHaveLength(1)
    expect(obs[0].kind).toBe('overdue')
    expect(obs[0].domain).toBe('time')
  })

  it('does not mark done tasks', () => {
    const t = task({ status: 'Done', due_date: '2026-06-10' })
    expect(deriveObstacles(project({}), [t], [t], span, NOW)).toHaveLength(0)
  })

  it('declares a crossing only for unfinished work in another project', () => {
    const foreign = task({ id: 'fx', project_id: 'p2', status: 'In Progress' })
    const t = task({ id: 't3', dependency_ids: ['fx'] })
    const obs = deriveObstacles(project({}), [t], [t, foreign], span, NOW)
    expect(obs.map((o) => o.kind)).toEqual(['crossing'])

    const foreignDone = task({ id: 'fx', project_id: 'p2', status: 'Done' })
    const obs2 = deriveObstacles(project({}), [t], [t, foreignDone], span, NOW)
    expect(obs2).toHaveLength(0)
  })

  it('declares a gate keeper where others wait behind a stated condition', () => {
    const gate = task({ id: 'g', completion_criteria: 'Vendor confirms in writing' })
    const waiter = task({ id: 'w', dependency_ids: ['g'] })
    const obs = deriveObstacles(project({}), [gate, waiter], [gate, waiter], span, NOW)
    const g = obs.find((o) => o.kind === 'gate')
    expect(g?.taskId).toBe('g')
    expect(g?.detail).toBe('Vendor confirms in writing')
  })
})

describe('declareTerrain', () => {
  it('declares a mountain at 2.5+ workdays of massed effort, a hill at 1+, open ground below', () => {
    const mountain = declareTerrain([task({ estimated_hours: 28 })])
    expect(mountain[0].kind).toBe('mountain')
    expect(mountain[0].effortDays).toBe(3.5)

    const hill = declareTerrain([task({ estimated_hours: 12 })])
    expect(hill[0].kind).toBe('hill')

    const open = declareTerrain([task({ estimated_hours: 4 })])
    expect(open[0].kind).toBe('open')
  })

  it('picks the largest single effort, and stays silent without recorded effort', () => {
    const feats = declareTerrain([task({ estimated_hours: 4 }), task({ id: 'big', estimated_hours: 40 })])
    expect(feats).toHaveLength(1)
    expect(feats[0].taskId).toBe('big')
    expect(declareTerrain([task({})])).toHaveLength(0)
  })

  it('declares a grove for 3+ subtasks under one parent, a copse for 2', () => {
    const parent = task({ id: 'mom', title: 'Finishing work' })
    const kids = [1, 2, 3].map((n) => task({ id: `k${n}`, parent_task_id: 'mom' }))
    const grove = declareTerrain([parent, ...kids]).find((f) => f.kind === 'grove')
    expect(grove?.treeCount).toBe(3)
    expect(grove?.taskId).toBe('mom')

    const copse = declareTerrain([parent, kids[0], kids[1]]).find((f) => f.kind === 'copse')
    expect(copse?.treeCount).toBe(2)

    expect(declareTerrain([parent, kids[0]]).filter((f) => f.kind === 'grove' || f.kind === 'copse')).toHaveLength(0)
  })
})

describe('buildRoutes', () => {
  const span = projectSpan(project({ start_date: '2026-06-01', end_date: '2026-06-30' }), [], NOW)

  it('orders route A by recorded due date and positions by fraction of span', () => {
    const late = task({ id: 'late', due_date: '2026-06-24' })
    const early = task({ id: 'early', due_date: '2026-06-06' })
    const { a } = buildRoutes([late, early], span)
    expect(a.map((w) => w.task.id)).toEqual(['early', 'late'])
    expect(a[0].fraction).toBeLessThan(a[1].fraction)
    expect(a.every((w) => w.dated)).toBe(true)
  })

  it('orders route B so dependencies come before dependents', () => {
    const dependent = task({ id: 'b', dependency_ids: ['a'] })
    const first = task({ id: 'a' })
    const { b } = buildRoutes([dependent, first], span)
    expect(b.map((w) => w.task.id)).toEqual(['a', 'b'])
  })

  it('places undated tasks by rank and rides done tasks as completed markers on A only', () => {
    const open = task({ id: 'open' })
    const done = task({ id: 'done', status: 'Done', due_date: '2026-06-06' })
    const { a, b } = buildRoutes([open, done], span)
    const aOpen = a.find((w) => w.task.id === 'open')
    expect(aOpen?.dated).toBe(false)
    expect(aOpen?.fraction).toBeGreaterThan(0)
    expect(a.find((w) => w.task.id === 'done')?.done).toBe(true)
    expect(b.map((w) => w.task.id)).toEqual(['open'])
  })
})

describe('overview + scale', () => {
  it('excludes completed projects and flags undated ones as nominal-length', () => {
    const done = project({ id: 'pd', title: 'Done', status: 'Complete' })
    const undated = project({ id: 'pu', title: 'Undated', status: 'Active' })
    const dated = project({
      id: 'pt',
      title: 'Dated',
      status: 'Active',
      start_date: '2026-06-01',
      end_date: '2026-06-13',
    })
    const overview = buildOverview([done, undated, dated], [], NOW)
    expect(overview.map((o) => o.project.id)).toEqual(['pt', 'pu'])
    expect(overview.find((o) => o.project.id === 'pu')?.routeDays).toBe(3)
    expect(overview.find((o) => o.project.id === 'pt')?.routeDays).toBe(12)
  })

  it('caps the scale at 26px/day and shrinks it to fit the longest route', () => {
    const short = buildOverview(
      [project({ start_date: '2026-06-01', end_date: '2026-06-05' })],
      [],
      NOW,
    )
    expect(computePxPerDay(short, 610)).toBe(26)

    const long = buildOverview(
      [project({ start_date: '2026-01-01', end_date: '2026-05-01' })],
      [],
      NOW,
    )
    const px = computePxPerDay(long, 610)
    expect(px).toBeLessThan(26)
    expect(px * 120).toBeLessThanOrEqual(610 + 1)
  })
})
