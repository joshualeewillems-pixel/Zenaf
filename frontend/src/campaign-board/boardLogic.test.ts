import { describe, expect, it } from 'vitest'
import type { CapacityProfile, Person, Project, Task } from '../vision-execution/types'
import {
  buildOverview,
  buildRoutes,
  computePxPerDay,
  createHold,
  createRiverFromSignal,
  createRiverWindow,
  dateAtFraction,
  declareTerrain,
  deriveCapacityPicture,
  deriveObstacles,
  deriveSignalMarkers,
  estimateLabelWidth,
  fractionForDate,
  groupOverviewByInitiative,
  layoutBoardLabels,
  moveHold,
  projectSpan,
  removeHold,
  riverBand,
  setRiverWindow,
  shortDate,
  signalsForProject,
  stripWaypointLabels,
  withdrawRiver,
  type BoardLabelItem,
  type BoardSignal,
  type BoardWaypoint,
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

function person(partial: Partial<Person>): Person {
  return {
    id: 'per1',
    name: 'Pat Printer',
    role: '',
    relationship_type: '',
    contact_info: '',
    strengths: '',
    needs: '',
    wants: '',
    availability: '',
    notes: '',
    created_at: '2026-01-01T00:00:00',
    updated_at: '2026-01-01T00:00:00',
    ...partial,
  }
}

function profile(partial: Partial<CapacityProfile>): CapacityProfile {
  return {
    person_id: 'per1',
    weekly_capacity_hours: 10,
    created_at: '2026-01-01T00:00:00',
    updated_at: '2026-01-01T00:00:00',
    ...partial,
  }
}

function signal(partial: Partial<BoardSignal>): BoardSignal {
  return {
    id: 's1',
    kind: 'blocker',
    title: 'Venue closed for repairs',
    detail: 'The hall is shut until the roof is fixed.',
    source: 'meeting extraction',
    source_excerpt: 'venue is closed for repairs',
    confidence: null,
    linked_initiative_id: null,
    linked_project_id: null,
    linked_task_id: null,
    status: 'new',
    created_at: '2026-06-10T09:00:00',
    ...partial,
  }
}

describe('signalsForProject', () => {
  const proj = project({ id: 'p1', initiative_id: 'i1' })
  const tasks = [task({ id: 't1' }), task({ id: 't2' })]

  it('collects signals linked to the project, its tasks, and its initiative', () => {
    const found = signalsForProject(
      [
        signal({ id: 'a', linked_project_id: 'p1' }),
        signal({ id: 'b', linked_task_id: 't2' }),
        signal({ id: 'c', linked_initiative_id: 'i1' }),
      ],
      proj,
      tasks,
    )
    expect(found.map((f) => [f.signal.id, f.via, f.taskId])).toEqual([
      ['a', 'project', null],
      ['b', 'task', 't2'],
      ['c', 'initiative', null],
    ])
  })

  it('excludes resolved/dismissed signals and other projects’ signals', () => {
    const found = signalsForProject(
      [
        signal({ id: 'a', linked_project_id: 'p1', status: 'resolved' }),
        signal({ id: 'b', linked_project_id: 'p1', status: 'dismissed' }),
        signal({ id: 'c', linked_project_id: 'p2' }),
        signal({ id: 'd', linked_task_id: 'elsewhere' }),
        signal({ id: 'e', linked_project_id: 'p1', status: 'acknowledged' }),
      ],
      proj,
      tasks,
    )
    expect(found.map((f) => f.signal.id)).toEqual(['e'])
  })
})

describe('deriveSignalMarkers', () => {
  const span = projectSpan(project({ start_date: '2026-06-01', end_date: '2026-06-30' }), [], NOW)

  it('stands a task-linked signal where its task stands, at reported standing', () => {
    const t = task({ id: 't1', due_date: '2026-06-16' })
    const markers = deriveSignalMarkers(
      [{ signal: signal({ linked_task_id: 't1' }), via: 'task', taskId: 't1' }],
      [t],
      span,
    )
    expect(markers).toHaveLength(1)
    expect(markers[0].fraction).toBeCloseTo(fractionForDate(span, new Date('2026-06-16').getTime()), 5)
    expect(markers[0].standing).toBe('reported')
    expect(markers[0].kindLabel).toBe('Reported blocker')
    expect(markers[0].taskId).toBe('t1')
  })

  it('stands a project-linked signal at its recorded date in the span', () => {
    const markers = deriveSignalMarkers(
      [{ signal: signal({ created_at: '2026-06-10T09:00:00' }), via: 'project', taskId: null }],
      [],
      span,
    )
    expect(markers[0].fraction).toBeCloseTo(
      fractionForDate(span, new Date('2026-06-10T09:00:00').getTime()),
      5,
    )
    expect(markers[0].rule).toContain('Reported material')
  })
})

describe('deriveCapacityPicture', () => {
  it('sums committed hours over Ready/Active work owned or supported — the Radar rule', () => {
    const mine = project({ id: 'p1', owner_id: 'per1', estimated_weekly_hours: 14 })
    const supported = project({ id: 'p2', supporting_owner_ids: ['per1'], estimated_weekly_hours: 3, status: 'Ready' })
    const parked = project({ id: 'p3', owner_id: 'per1', estimated_weekly_hours: 40, status: 'Parked' })
    const picture = deriveCapacityPicture(mine, [mine, supported, parked], [person({})], [profile({})], [])
    expect(picture).toHaveLength(1)
    expect(picture[0].committedHours).toBe(17)
    expect(picture[0].weeklyCapacityHours).toBe(10)
    expect(picture[0].delta).toBe(7)
    expect(picture[0].over).toBe(true)
  })

  it('includes task assignees as people on the work, and stays unjudged without a profile', () => {
    // The assignee stands on this project's work, but committed hours
    // follow the Radar rule — projects owned or supported (here: a
    // supported project elsewhere), never mere task assignment.
    const proj = project({ id: 'p1', estimated_weekly_hours: 5 })
    const elsewhere = project({ id: 'p9', supporting_owner_ids: ['per1'], estimated_weekly_hours: 5 })
    const t = task({ assignee_id: 'per1' })
    const picture = deriveCapacityPicture(proj, [proj, elsewhere], [person({})], [], [t])
    expect(picture).toHaveLength(1)
    expect(picture[0].committedHours).toBe(5)
    expect(picture[0].weeklyCapacityHours).toBeNull()
    expect(picture[0].delta).toBeNull()
    expect(picture[0].over).toBe(false)
    expect(picture[0].rule).toContain('No weekly capacity is recorded')
  })

  it('does not fire overcapacity within capacity', () => {
    const proj = project({ id: 'p1', owner_id: 'per1', estimated_weekly_hours: 6 })
    const picture = deriveCapacityPicture(proj, [proj], [person({})], [profile({})], [])
    expect(picture[0].over).toBe(false)
    expect(picture[0].delta).toBe(-4)
  })
})

describe('river + hold declarations', () => {
  const span = projectSpan(project({ start_date: '2026-06-01', end_date: '2026-06-30' }), [], NOW)

  it('declares a river from a signal: window opens on the recorded date, default length', () => {
    const river = createRiverFromSignal('river-1', 'p1', signal({}), span)
    expect(river.source).toEqual({ type: 'signal', signalId: 's1', signalTitle: 'Venue closed for repairs' })
    expect(new Date(river.startMs).getDate()).toBe(10)
    expect((river.endMs - river.startMs) / 86_400_000).toBe(3)
    const band = riverBand(span, river)
    expect(band.startFraction).toBeCloseTo(9 / 29, 2)
    expect(band.endFraction).toBeCloseTo(12 / 29, 2)
    expect(band.endFraction).toBeGreaterThan(band.startFraction)
  })

  it('declares a river window directly, mid-span, and re-windows or withdraws it', () => {
    const river = createRiverWindow('river-2', 'p1', span)
    expect(river.source).toEqual({ type: 'window' })
    const moved = setRiverWindow([river], 'river-2', river.startMs + 86_400_000, river.endMs + 86_400_000)
    expect(moved[0].startMs).toBe(river.startMs + 86_400_000)
    // An inverted window is refused, not stored.
    expect(setRiverWindow([river], 'river-2', river.endMs, river.startMs)).toEqual([river])
    expect(withdrawRiver(moved, 'river-2')).toHaveLength(0)
  })

  it('places a hold, moves it clamped to the line, and removes it', () => {
    const hold = createHold('hold-1', 'p1')
    expect(hold.fraction).toBe(0.5)
    const moved = moveHold([hold], 'hold-1', 1.7)
    expect(moved[0].fraction).toBe(0.98)
    expect(moveHold([hold], 'hold-1', -1)[0].fraction).toBe(0.02)
    expect(removeHold(moved, 'hold-1')).toHaveLength(0)
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

  it('flags spanned vs unspanned: recorded dates or task windows span; nothing recorded does not', () => {
    const dated = project({ id: 'pd', start_date: '2026-06-01', end_date: '2026-06-13' })
    const fromTasks = project({ id: 'pt' })
    const undated = project({ id: 'pu' })
    const overview = buildOverview(
      [dated, fromTasks, undated],
      [task({ id: 'x1', project_id: 'pt', due_date: '2026-06-03' }), task({ id: 'x2', project_id: 'pt', due_date: '2026-06-10' })],
      NOW,
    )
    expect(overview.find((o) => o.project.id === 'pd')?.spanned).toBe(true)
    expect(overview.find((o) => o.project.id === 'pt')?.spanned).toBe(true)
    expect(overview.find((o) => o.project.id === 'pu')?.spanned).toBe(false)
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

describe('groupOverviewByInitiative', () => {
  const initiatives = [
    { id: 'i1', title: 'Council fellowship' },
    { id: 'i2', title: 'Zenaf core' },
    { id: 'i-empty', title: 'Nothing running' },
  ]

  it('nests projects under their initiatives, in board order, unanchored last', () => {
    const overview = buildOverview(
      [
        project({ id: 'free1', title: 'Loose one', initiative_id: null }),
        project({ id: 'core1', title: 'Core dated', initiative_id: 'i2', start_date: '2026-06-01', end_date: '2026-06-13' }),
        project({ id: 'bear', title: 'Meet the Bear', initiative_id: 'i1' }),
        project({ id: 'crane', title: 'Meet the Crane', initiative_id: 'i1' }),
        project({ id: 'free2', title: 'Loose two', initiative_id: null }),
      ],
      [],
      NOW,
    )
    const groups = groupOverviewByInitiative(overview, initiatives)
    expect(groups.map((g) => g.initiative?.id ?? null)).toEqual(['i2', 'i1', null])
    expect(groups[0].projects.map((o) => o.project.id)).toEqual(['core1'])
    expect(groups[1].projects.map((o) => o.project.id)).toEqual(['bear', 'crane'])
    expect(groups[1].initiative?.title).toBe('Council fellowship')
    expect(groups[2].projects.map((o) => o.project.id)).toEqual(['free1', 'free2'])
  })

  it('treats a project naming an unfetched initiative as unanchored, and gives empty initiatives no ground', () => {
    const overview = buildOverview(
      [project({ id: 'ghost', initiative_id: 'i-missing' })],
      [],
      NOW,
    )
    const groups = groupOverviewByInitiative(overview, initiatives)
    expect(groups).toHaveLength(1)
    expect(groups[0].initiative).toBeNull()
    expect(groups[0].projects.map((o) => o.project.id)).toEqual(['ghost'])
    expect(groups.some((g) => g.initiative?.id === 'i-empty')).toBe(false)
  })

  it('returns no groups for an empty board', () => {
    expect(groupOverviewByInitiative([], initiatives)).toEqual([])
  })
})

/* ------------------------------------------------------------------ */
/* Label layout + timeline strip (diagnosis 2026-11-25)                */
/* ------------------------------------------------------------------ */

// The focus board's geometry, mirrored from CampaignBoardView so the
// fixture's label items are built exactly as the view builds them.
const MAP_W = 800
const FOCUS_H = 500
const X0 = 64
const X1 = 736
const MID_Y = 252
const ROUTE_A_Y = 148
const ROUTE_B_Y = 356
const LABEL_BOUNDS = { minX: 8, maxX: MAP_W - 8, minY: 8, maxY: FOCUS_H - 8 }

function xForFraction(f: number): number {
  return X0 + f * (X1 - X0)
}
function waypointY(bandY: number, index: number): number {
  return bandY + ((index % 3) - 1) * 12
}

/** A project shaped like the founder's "Meet the Bear" board: a
 *  3-day span whose Route A ends in a pile-up at fraction 0.98 — two
 *  open waypoints due on the last day, an undated done task appended
 *  at 0.98, and a Gate Keeper obstacle standing at 0.98 under the
 *  finish banner. */
function bearFixture() {
  const proj = project({
    id: 'bear',
    title: 'Meet the Bear',
    start_date: '2026-12-01T09:00:00',
    end_date: '2026-12-04T09:00:00',
  })
  const tasks = [
    task({ id: 'strengths', title: 'Strengths', due_date: '2026-12-01T09:00:00' }),
    task({ id: 'echo', title: 'The echo', due_date: '2026-12-02T09:00:00' }),
    task({
      id: 'threshold',
      title: 'The threshold',
      due_date: '2026-12-04T09:00:00',
      completion_criteria: 'The Bear has been met face to face.',
    }),
    task({
      id: 'weaknesses',
      title: 'Weaknesses',
      due_date: '2026-12-04T09:00:00',
      dependency_ids: ['threshold'],
    }),
    task({ id: 'first-meeting', title: 'First meeting', status: 'Done', due_date: null }),
  ]
  const span = projectSpan(proj, tasks, NOW)
  const routes = buildRoutes(tasks, span)
  const obstacles = deriveObstacles(proj, tasks, tasks, span, NOW)
  return { proj, tasks, span, routes, obstacles }
}

/** Label items for the fixture, built with FocusBoard's formulas. */
function bearLabelItems(): BoardLabelItem[] {
  const { span, routes, obstacles } = bearFixture()
  const allWaypoints: { w: BoardWaypoint; bandY: number; index: number }[] = [
    ...routes.a.map((w, index) => ({ w, bandY: ROUTE_A_Y, index })),
    ...routes.b.map((w, index) => ({ w, bandY: ROUTE_B_Y, index })),
  ]
  const title = (w: BoardWaypoint) =>
    w.task.title.length > 26 ? `${w.task.title.slice(0, 25)}…` : w.task.title
  return [
    {
      id: 'banner:start',
      anchorX: X0,
      top: MID_Y + 28 - 11,
      width: estimateLabelWidth(`Start · ${shortDate(new Date(span.startMs))}`, 11),
      height: 14,
    },
    {
      id: 'banner:finish',
      anchorX: X1,
      top: MID_Y + 30 - 11,
      width: estimateLabelWidth(`Finish · ${shortDate(new Date(span.endMs))}`, 11),
      height: 14,
    },
    ...obstacles.map((ob) => ({
      id: `obstacle:${ob.id}`,
      anchorX: xForFraction(ob.fraction),
      top: MID_Y + (ob.kind === 'gate' ? 30 : ob.kind === 'crossing' ? 32 : 26) - 11,
      width: estimateLabelWidth(
        ob.kind === 'gate' ? 'Gate Keeper' : ob.kind === 'crossing' ? 'Crossing' : ob.kindLabel,
        10.5,
      ),
      height: 14,
    })),
    ...allWaypoints.map(({ w, bandY, index }) => {
      const tier = index % 2 === 0 ? 30 : 46
      const sub = w.done ? 'done' : shortDate(dateAtFraction(span, w.fraction))
      return {
        id: `waypoint:${bandY}:${w.task.id}`,
        anchorX: xForFraction(w.fraction),
        top: waypointY(bandY, index) + tier - 11,
        width: Math.max(estimateLabelWidth(title(w), 11), estimateLabelWidth(sub, 10)),
        height: 27,
      }
    }),
  ]
}

function boxesOverlap(
  a: { x: number; top: number; width: number; height: number },
  b: { x: number; top: number; width: number; height: number },
): boolean {
  const ox =
    Math.min(a.x + a.width / 2, b.x + b.width / 2) - Math.max(a.x - a.width / 2, b.x - b.width / 2)
  const oy = Math.min(a.top + a.height, b.top + b.height) - Math.max(a.top, b.top)
  // A hair of tolerance for floating-point dust; a real collision is
  // units deep, not thousandths.
  return ox > 0.01 && oy > 0.01
}

describe('layoutBoardLabels', () => {
  it('places the founder-shaped finish pile-up with no two label boxes overlapping', () => {
    const { routes, obstacles } = bearFixture()
    // The fixture really is the pile-up the diagnosis described.
    expect(routes.a.filter((w) => w.fraction >= 0.97)).toHaveLength(3)
    expect(routes.a.some((w) => w.done && w.fraction === 0.98)).toBe(true)
    expect(obstacles.some((ob) => ob.kind === 'gate' && ob.fraction >= 0.97)).toBe(true)

    const items = bearLabelItems()
    const placed = layoutBoardLabels(items, LABEL_BOUNDS)
    expect(placed).toHaveLength(items.length)
    expect(placed.map((p) => p.id)).toEqual(items.map((i) => i.id))
    for (const p of placed) {
      expect(p.x - p.width / 2).toBeGreaterThanOrEqual(LABEL_BOUNDS.minX - 0.01)
      expect(p.x + p.width / 2).toBeLessThanOrEqual(LABEL_BOUNDS.maxX + 0.01)
      expect(p.top).toBeGreaterThanOrEqual(LABEL_BOUNDS.minY - 0.01)
      expect(p.top + p.height).toBeLessThanOrEqual(LABEL_BOUNDS.maxY + 0.01)
    }
    for (let i = 0; i < placed.length; i++) {
      for (let j = i + 1; j < placed.length; j++) {
        expect(
          boxesOverlap(placed[i], placed[j]),
          `${placed[i].id} overlaps ${placed[j].id}`,
        ).toBe(false)
      }
    }
  })

  it('is deterministic — the same items place the same way twice', () => {
    const items = bearLabelItems()
    expect(layoutBoardLabels(items, LABEL_BOUNDS)).toEqual(layoutBoardLabels(items, LABEL_BOUNDS))
  })

  it('separates six label pairs stacked on a single anchor', () => {
    const items: BoardLabelItem[] = Array.from({ length: 6 }, (_, i) => ({
      id: `pair-${i}`,
      anchorX: xForFraction(0.98),
      top: 160 + (i % 2) * 16,
      width: 120,
      height: 27,
    }))
    const placed = layoutBoardLabels(items, LABEL_BOUNDS)
    for (let i = 0; i < placed.length; i++) {
      for (let j = i + 1; j < placed.length; j++) {
        expect(boxesOverlap(placed[i], placed[j]), `${placed[i].id} overlaps ${placed[j].id}`).toBe(
          false,
        )
      }
    }
  })

  it('returns no placements for no labels', () => {
    expect(layoutBoardLabels([], LABEL_BOUNDS)).toEqual([])
  })
})

describe('stripWaypointLabels', () => {
  it('never duplicates a span bound and never stacks two labels on one anchor', () => {
    const { span, routes } = bearFixture()
    const labels = stripWaypointLabels(routes.a, span)
    // The start-bound waypoint's date repeats the bound above the
    // line, so it is not printed again below it.
    expect(labels.some((l) => l.text.includes(shortDate(new Date(span.startMs))))).toBe(false)
    // One label per anchor, anchors distinct.
    const fractions = labels.map((l) => l.fraction)
    expect(new Set(fractions).size).toBe(fractions.length)
    // The three waypoints sharing the finish anchor merge into ONE
    // label: both dated waypoints' dates repeat the end bound (on a
    // 3-day span the 0.98 fraction still lands on the final day), so
    // only the done marker's text survives.
    const atFinish = labels.filter((l) => l.fraction >= 0.97)
    expect(atFinish).toHaveLength(1)
    expect(atFinish[0].text).toBe('done')
    expect(labels.some((l) => l.text.includes(shortDate(new Date(span.endMs))))).toBe(false)
    // Every date string is emitted at most once across the strip's
    // below-line labels.
    const dateTexts = labels.flatMap((l) => l.text.split(' · ')).filter((t) => t !== 'done')
    expect(new Set(dateTexts).size).toBe(dateTexts.length)
  })

  it('suppresses a waypoint whose date is the end bound it stands on', () => {
    const proj = project({
      id: 'short',
      start_date: '2026-12-01T09:00:00',
      end_date: '2026-12-02T09:00:00',
    })
    const tasks = [task({ id: 'only', title: 'Only step', due_date: '2026-12-02T09:00:00' })]
    const span = projectSpan(proj, tasks, NOW)
    const routes = buildRoutes(tasks, span)
    expect(stripWaypointLabels(routes.a, span)).toEqual([])
  })

  it('merges a done and an open waypoint sharing a mid-span date into one label', () => {
    const proj = project({
      id: 'long',
      start_date: '2026-12-01T09:00:00',
      end_date: '2026-12-11T09:00:00',
    })
    const tasks = [
      task({ id: 'open', title: 'Open step', due_date: '2026-12-06T09:00:00' }),
      task({ id: 'done', title: 'Done step', status: 'Done', due_date: '2026-12-06T09:00:00' }),
    ]
    const span = projectSpan(proj, tasks, NOW)
    const routes = buildRoutes(tasks, span)
    const labels = stripWaypointLabels(routes.a, span)
    expect(labels).toHaveLength(1)
    expect(labels[0].fraction).toBeCloseTo(0.5)
    expect(labels[0].text).toBe('Dec 6 · done')
  })
})
