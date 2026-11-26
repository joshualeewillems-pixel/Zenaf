/**
 * Scene 1 logic — measured gates (build brief, 2026-11-25).
 *
 * The deflation port is checked against the canonical Python
 * builder's own numbers (build_composite_v4.py, verified against
 * the stage1c source table): 890 thin + 1440 thick halves after 6
 * deflations, 1140 rhombs merged over their shared diagonals,
 * 230 standing on the wall after the wall + exclusion filters
 * (146 thick, 84 thin). Cubby assignment must be deterministic
 * and honour the left/right placement rule; the cluster rule and
 * the long-press route are pinned at their boundaries.
 */
import { describe, it, expect } from 'vitest'
import { buildScrollShelf, type ShelfBay, type ShelfScroll } from './scrollLogic'
import {
  CLUSTER_SHOWN,
  SHEET_CENTRE,
  assignCubbies,
  buildPenroseFabric,
  cellInDiameter,
  clusterChildren,
  longPressRoute,
  popupSynopsis,
  scrollKey,
  scrollPlacementFor,
  SCROLL_CONTOUR,
  tableRows,
  trailForScroll,
  type FabricRhomb,
} from './sceneLogic'

const base = {
  brief: '', owner_id: null, supporting_owner_ids: [], priority: '',
  start_date: null, end_date: null, estimated_weekly_hours: null,
  next_step_ai: '', notes: '', created_at: '2026-02-01T00:00:00', updated_at: '2026-02-01T00:00:00',
}
const ibase = {
  brief: '', owner_id: null, evaluation_priority: null, estimated_cost_ai: '',
  estimated_timeframe_ai: '', philosophical_alignment_ai: '', next_step_ai: '',
  required_assets: [], dependencies: '', risks: '', recommendation: '',
  kill_criteria: '', notes: '', updated_at: '2026-01-01T00:00:00',
}
const tbase = {
  parent_task_id: null, description: '', assignee_id: null, priority: '',
  estimated_hours: null, due_date: null, dependency_ids: [],
  completion_criteria: '', notes: '', created_at: '2026-03-01T00:00:00', updated_at: '2026-03-01T00:00:00',
}

function fixtureShelf(): ShelfBay[] {
  return buildScrollShelf(
    [
      { ...ibase, id: 'i1', title: 'Council fellowship', status: 'Active', source_idea_id: null, created_at: '2026-01-01T00:00:00' },
      { ...ibase, id: 'i2', title: 'Quiet garden', status: 'Active', source_idea_id: null, created_at: '2026-01-02T00:00:00' },
    ],
    [
      { ...base, id: 'p1', initiative_id: 'i1', title: 'Meet the Bear', status: 'Blocked', start_date: '2026-01-05', end_date: '2026-03-30' },
      { ...base, id: 'p2', initiative_id: 'i1', title: 'Stock the pantry', status: 'Active' },
      { ...base, id: 'p3', initiative_id: null, title: 'Fix the gate latch', status: 'Blocked' },
    ],
    [
      { ...tbase, id: 't1', project_id: 'p1', title: 'Bear step one', status: 'Todo', estimated_hours: 3, due_date: '2026-02-14' },
      { ...tbase, id: 't2', project_id: 'p1', title: 'Bear step two', status: 'Todo' },
      { ...tbase, id: 't3', project_id: 'p2', title: 'Pantry list', status: 'Todo' },
      { ...tbase, id: 't4', project_id: 'p3', title: 'Hinges', status: 'Todo' },
      { ...tbase, id: 't5', project_id: null, title: 'Loose thought', status: 'Todo' },
    ],
    [
      { id: 'idea1', title: 'A loose idea', summary: '', description: '', status: 'Captured', tags: [], created_by: '', notes: '', created_at: '2025-12-01T00:00:00', updated_at: '2025-12-01T00:00:00' },
    ],
  )
}

function find(bays: ShelfBay[], kind: ShelfScroll['kind'], id: string): ShelfScroll {
  const all: ShelfScroll[] = []
  for (const b of bays) {
    if (b.initiative) all.push(b.initiative)
    for (const p of b.projects) all.push(p.scroll, ...p.tasks)
    all.push(...b.looseTasks, ...b.ideas)
  }
  const s = all.find((x) => x.kind === kind && x.id === id)
  if (!s) throw new Error(`missing ${kind}:${id}`)
  return s
}

describe('the Penrose fabric port', () => {
  it('matches the canonical builder’s counts exactly', () => {
    const f = buildPenroseFabric()
    expect(f.thinHalves).toBe(890)
    expect(f.thickHalves).toBe(1440)
    expect(f.mergedRhombs).toBe(1140)
    expect(f.rhombs).toHaveLength(230)
    expect(f.rhombs.filter((r) => r.thick)).toHaveLength(146)
    expect(f.rhombs.filter((r) => !r.thick)).toHaveLength(84)
  })

  it('is deterministic — the same fabric on every build', () => {
    const a = buildPenroseFabric()
    const b = buildPenroseFabric()
    expect(b.rhombs.map((r) => [r.centre.x, r.centre.y, r.thick])).toEqual(
      a.rhombs.map((r) => [r.centre.x, r.centre.y, r.thick]),
    )
  })

  it('keeps every rhomb out of the sheet’s exclusion rect and inside the wall field', () => {
    const f = buildPenroseFabric()
    for (const r of f.rhombs) {
      expect(r.centre.x).toBeGreaterThanOrEqual(105 - 40)
      expect(r.centre.x).toBeLessThanOrEqual(1400 + 40)
      expect(r.centre.y).toBeGreaterThanOrEqual(262 - 40)
      expect(r.centre.y).toBeLessThanOrEqual(852 + 40)
      const inExcl = (x: number, y: number) => x >= 518 && x <= 950 && y >= 366 && y <= 862
      expect(inExcl(r.centre.x, r.centre.y)).toBe(false)
      for (const c of r.corners) expect(inExcl(c.x, c.y)).toBe(false)
    }
  })
})

describe('the cubby ground rules — scrolls fitted within the large rhombi', () => {
  const insideQuad = (p: { x: number; y: number }, quad: { x: number; y: number }[]) => {
    let sign = 0
    for (let i = 0; i < 4; i++) {
      const a = quad[i]
      const b = quad[(i + 1) % 4]
      const cross = (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x)
      if (cross !== 0) {
        if (sign === 0) sign = Math.sign(cross)
        else if (Math.sign(cross) !== sign) return false
      }
    }
    return true
  }

  it('scrollPlacementFor fits the scroll’s whole silhouette inside its rhomb', () => {
    const a = assignCubbies(fixtureShelf(), buildPenroseFabric().rhombs)
    expect(a.length).toBeGreaterThan(0)
    for (const x of a) {
      const place = scrollPlacementFor(x.cell, x.side)
      const flip = x.side === 'right' ? -1 : 1
      for (const [dx, dy] of SCROLL_CONTOUR) {
        expect(
          insideQuad(
            { x: place.cx + flip * dx * place.width, y: place.cy + dy * place.width },
            x.cell.corners,
          ),
          `the silhouette of ${x.unit.head.title}'s scroll stands outside its rhomb`,
        ).toBe(true)
      }
      // and it still reads: never larger than the old face-fit,
      // never a thumbnail
      expect(place.width).toBeLessThanOrEqual(cellInDiameter(x.cell) / 0.6 + 0.001)
      expect(place.width).toBeGreaterThan(30)
    }
  })

  it('assignment stands scrolls only in large (thick) rhombi while they remain', () => {
    const a = assignCubbies(fixtureShelf(), buildPenroseFabric().rhombs)
    for (const x of a) expect(x.cell.thick).toBe(true)
  })

  it('a nearer thin rhomb never takes a scroll from a large one; thin is the last resort', () => {
    const cell = (x: number, y: number, thick: boolean): FabricRhomb => ({
      corners: [
        { x: x - 10, y: y - 10 },
        { x: x + 10, y: y - 10 },
        { x: x + 10, y: y + 10 },
        { x: x - 10, y: y + 10 },
      ],
      centre: { x, y },
      thick,
    })
    // the thin cell stands much closer to the sheet; the thick
    // cell must still be taken first, the thin only once no
    // large rhomb remains
    const cells = [cell(700, 500, false), cell(400, 400, true)]
    const a = assignCubbies(fixtureShelf(), cells)
    expect(a).toHaveLength(2)
    expect(a[0].cell.thick).toBe(true)
    expect(a[1].cell.thick).toBe(false)
  })

  it('assignment keeps cubbies inside the wall band while cells remain there', () => {
    const a = assignCubbies(fixtureShelf(), buildPenroseFabric().rhombs)
    for (const x of a) {
      expect(x.cell.centre.x).toBeGreaterThanOrEqual(175)
      expect(x.cell.centre.x).toBeLessThanOrEqual(1330)
      expect(x.cell.centre.y).toBeGreaterThanOrEqual(290)
      expect(x.cell.centre.y).toBeLessThanOrEqual(780)
    }
  })

  it('assignment exhausts in-band cells — crowded ones included — before any out-of-band cell', () => {
    // Three in-band cells, mutually crowded (all within the
    // separation distance of each other), and two cells outside
    // the band (above it, below it). Five units: the first three
    // must take ALL the in-band cells — a crowded in-band cell
    // beats a free out-of-band one, so no scroll ever stands on
    // the floor while wall remains.
    const cell = (x: number, y: number): FabricRhomb => ({
      corners: [
        { x: x - 10, y: y - 10 },
        { x: x + 10, y: y - 10 },
        { x: x + 10, y: y + 10 },
        { x: x - 10, y: y + 10 },
      ],
      centre: { x, y },
      thick: true,
    })
    const cells = [cell(400, 400), cell(440, 420), cell(480, 400), cell(734, 200), cell(300, 900)]
    const a = assignCubbies(fixtureShelf(), cells)
    expect(a).toHaveLength(5)
    const used = a.map((x) => `${x.cell.centre.x},${x.cell.centre.y}`)
    expect(used.slice(0, 3).sort()).toEqual(['400,400', '440,420', '480,400'])
    expect(used.slice(3).sort()).toEqual(['300,900', '734,200'])
  })
})

describe('cubby assignment', () => {
  it('is deterministic and gives every unit its own cell', () => {
    const bays = fixtureShelf()
    const fabric = buildPenroseFabric()
    const a = assignCubbies(bays, fabric.rhombs)
    const b = assignCubbies(bays, fabric.rhombs)
    const shape = (xs: typeof a) =>
      xs.map((x) => [scrollKey(x.unit.head), x.cell.centre.x, x.cell.centre.y, x.side])
    expect(shape(b)).toEqual(shape(a))
    // Five top-level units: i1, i2, p3, t5, idea1.
    expect(a).toHaveLength(5)
    const cells = new Set(a.map((x) => `${x.cell.centre.x},${x.cell.centre.y}`))
    expect(cells.size).toBe(a.length)
  })

  it('honours the left/right placement rule against the sheet’s centre line', () => {
    const a = assignCubbies(fixtureShelf(), buildPenroseFabric().rhombs)
    for (const x of a) {
      expect(x.side).toBe(x.cell.centre.x < SHEET_CENTRE.x ? 'left' : 'right')
    }
    // Both sides of the room are used.
    expect(a.some((x) => x.side === 'left')).toBe(true)
    expect(a.some((x) => x.side === 'right')).toBe(true)
  })

  it('orders units by recorded size — the largest initiative takes the first cell', () => {
    const a = assignCubbies(fixtureShelf(), buildPenroseFabric().rhombs)
    expect(scrollKey(a[0].unit.head)).toBe('initiative:i1')
    const radii = a.map((x) => x.unit.head.appearance.radius)
    expect([...radii].sort((m, n) => n - m)).toEqual(radii)
  })

  it('keeps cubbies readable — no two assigned centres crowd each other', () => {
    const a = assignCubbies(fixtureShelf(), buildPenroseFabric().rhombs)
    for (let i = 0; i < a.length; i++) {
      for (let j = i + 1; j < a.length; j++) {
        const d = Math.hypot(
          a[i].cell.centre.x - a[j].cell.centre.x,
          a[i].cell.centre.y - a[j].cell.centre.y,
        )
        expect(d).toBeGreaterThanOrEqual(105)
      }
    }
  })
})

describe('the cluster rule', () => {
  it('a leaf bay clusters nothing; a nested bay clusters projects first, then tasks', () => {
    const bays = fixtureShelf()
    expect(clusterChildren(bays, find(bays, 'initiative', 'i2'))).toEqual([])
    expect(clusterChildren(bays, find(bays, 'idea', 'idea1'))).toEqual([])
    const cluster = clusterChildren(bays, find(bays, 'initiative', 'i1'))
    expect(cluster.map((s) => scrollKey(s))).toEqual([
      'project:p1',
      'project:p2',
      'task:t1',
      'task:t2',
      'task:t3',
    ])
    // A project's cluster is its tasks.
    expect(clusterChildren(bays, find(bays, 'project', 'p1')).map((s) => scrollKey(s))).toEqual([
      'task:t1',
      'task:t2',
    ])
  })

  it('caps the shown cluster at three and carries the overflow in the synopsis', () => {
    const bays = fixtureShelf()
    const ini = find(bays, 'initiative', 'i1')
    expect(clusterChildren(bays, ini).length).toBe(5)
    expect(Math.min(CLUSTER_SHOWN, clusterChildren(bays, ini).length)).toBe(3)
    const lines = popupSynopsis(bays, ini)
    expect(lines[0]).toBe('Initiative · Active')
    expect(lines).toContain('2 projects · 3 tasks within')
    expect(lines).toContain('…and 2 more within')
  })
})

describe('the popup synopsis — recorded fields only', () => {
  it('carries a project’s status, task count and declared window', () => {
    const bays = fixtureShelf()
    const lines = popupSynopsis(bays, find(bays, 'project', 'p1'))
    expect(lines[0]).toBe('Project · Blocked')
    expect(lines).toContain('2 tasks')
    expect(lines).toContain('5 Jan 2026 – 30 Mar 2026')
  })

  it('carries a task’s estimate and due date', () => {
    const bays = fixtureShelf()
    const lines = popupSynopsis(bays, find(bays, 'task', 't1'))
    expect(lines[0]).toBe('Task · Todo')
    expect(lines).toContain('3h estimated')
    expect(lines).toContain('due 14 Feb 2026')
  })
})

describe('trails and the long-press route', () => {
  it('walks a task’s trail through its project and initiative', () => {
    const bays = fixtureShelf()
    expect(trailForScroll(bays, find(bays, 'task', 't1'))).toEqual([
      'initiative:i1',
      'project:p1',
      'task:t1',
    ])
    expect(trailForScroll(bays, find(bays, 'project', 'p3'))).toEqual(['project:p3'])
    expect(trailForScroll(bays, find(bays, 'initiative', 'i2'))).toEqual(['initiative:i2'])
  })

  it('routes a scroll with children to the table and a leaf to the sheet', () => {
    const bays = fixtureShelf()
    expect(longPressRoute(bays, find(bays, 'initiative', 'i1'))).toBe('table')
    expect(longPressRoute(bays, find(bays, 'project', 'p1'))).toBe('table')
    expect(longPressRoute(bays, find(bays, 'initiative', 'i2'))).toBe('sheet')
    expect(longPressRoute(bays, find(bays, 'task', 't1'))).toBe('sheet')
    expect(longPressRoute(bays, find(bays, 'idea', 'idea1'))).toBe('sheet')
  })

  it('stands a bay’s projects on its table, each with its task cluster', () => {
    const bays = fixtureShelf()
    const rows = tableRows(bays, find(bays, 'initiative', 'i1'))
    expect(rows.map((r) => scrollKey(r.scroll))).toEqual(['project:p1', 'project:p2'])
    expect(rows[0].cluster.map((s) => scrollKey(s))).toEqual(['task:t1', 'task:t2'])
    expect(rows[1].cluster.map((s) => scrollKey(s))).toEqual(['task:t3'])
  })
})
