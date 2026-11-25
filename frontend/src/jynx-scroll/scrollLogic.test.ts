/**
 * Jynx's Scroll — pure derivation tests.
 *
 * The shelf is a projection of recorded Vision Execution data:
 * grouping follows the real hierarchy, and every visible
 * distinction between scrolls (size, parchment tone, binding cord)
 * is computed from recorded fields only.
 */
import { describe, it, expect } from 'vitest'
import {
  buildScrollShelf,
  drawingsForConversation,
  drawingDurationMs,
  flattenShelf,
  markProgressAt,
  scrollChildren,
  sheetLayout,
  shelfTopLevel,
  JYNX_PURPLE,
  SHEET_BAND_H,
  SHEET_COMPACT_ZONE_MAX,
  TIER_DARK,
  TIER_LIGHT,
  TIER_MID,
  type ScrollDrawing,
  type ShelfScroll,
} from './scrollLogic'
import type { Initiative, Project, Task } from '../vision-execution/types'

function ini(id: string, title: string, status = 'Active', created = '2026-01-01T00:00:00'): Initiative {
  return {
    id, source_idea_id: null, title, brief: '', status, owner_id: null,
    evaluation_priority: null, estimated_cost_ai: '', estimated_timeframe_ai: '',
    philosophical_alignment_ai: '', next_step_ai: '', required_assets: [],
    dependencies: '', risks: '', recommendation: '', kill_criteria: '', notes: '',
    created_at: created, updated_at: created,
  }
}

function proj(id: string, title: string, initiativeId: string | null, status = 'Active', created = '2026-02-01T00:00:00'): Project {
  return {
    id, initiative_id: initiativeId, title, brief: '', status, owner_id: null,
    supporting_owner_ids: [], priority: '', start_date: null, end_date: null,
    estimated_weekly_hours: null, next_step_ai: '', notes: '',
    created_at: created, updated_at: created,
  }
}

function task(id: string, title: string, projectId: string | null, status = 'Todo', created = '2026-03-01T00:00:00', parentId: string | null = null, hours: number | null = null): Task {
  return {
    id, project_id: projectId, parent_task_id: parentId, title, description: '',
    assignee_id: null, status, priority: '', estimated_hours: hours, due_date: null,
    dependency_ids: [], completion_criteria: '', notes: '',
    created_at: created, updated_at: created,
  } as Task
}

describe('buildScrollShelf — grouping by the real hierarchy', () => {
  const initiatives = [ini('i1', 'Council fellowship'), ini('i2', 'Zenaf core')]
  const projects = [
    proj('p1', 'Meet the Bear', 'i1'),
    proj('p2', 'Ship the thing', 'i2'),
    proj('p3', 'Fix the gate latch', null),
  ]
  const tasks = [
    task('t1', 'Bear step one', 'p1'),
    task('t2', 'Bear step two', 'p1'),
    task('t2a', 'Bear sub-step', 'p1', 'Todo', '2026-03-02T00:00:00', 't2'),
    task('t3', 'Ship step', 'p2'),
    task('t4', 'Loose thought', null),
  ]
  const shelf = buildScrollShelf(initiatives, projects, tasks)

  it('makes one bay per initiative, projects nested, tasks under their project', () => {
    expect(shelf).toHaveLength(3)
    expect(shelf[0].initiative?.title).toBe('Council fellowship')
    expect(shelf[0].projects.map((p) => p.scroll.title)).toEqual(['Meet the Bear'])
    expect(shelf[0].projects[0].tasks.map((t) => t.title)).toEqual([
      'Bear step one',
      'Bear step two',
      'Bear sub-step', // subtask directly after its parent
    ])
    expect(shelf[1].initiative?.title).toBe('Zenaf core')
    expect(shelf[1].projects[0].tasks.map((t) => t.title)).toEqual(['Ship step'])
  })

  it('puts unanchored projects and loose tasks in the bin bay', () => {
    const bin = shelf[2]
    expect(bin.initiative).toBeNull()
    expect(bin.projects.map((p) => p.scroll.title)).toEqual(['Fix the gate latch'])
    expect(bin.looseTasks.map((t) => t.title)).toEqual(['Loose thought'])
  })

  it('keeps every recorded item — nothing is filtered off the shelf', () => {
    const flat = flattenShelf(shelf)
    expect(flat.map((s) => s.title)).toEqual([
      'Council fellowship',
      'Meet the Bear',
      'Bear step one',
      'Bear step two',
      'Bear sub-step',
      'Zenaf core',
      'Ship the thing',
      'Ship step',
      'Fix the gate latch',
      'Loose thought',
    ])
  })

  it('a project pointing at a missing initiative lands in the bin, not nowhere', () => {
    const s = buildScrollShelf([], [proj('px', 'Orphan', 'gone')], [])
    expect(s).toHaveLength(1)
    expect(s[0].initiative).toBeNull()
    expect(s[0].projects[0].scroll.title).toBe('Orphan')
  })

  describe('parents + loose — the shelf face and the drill-in', () => {
    const byKey = (s: ShelfScroll) => `${s.kind}:${s.id}`

    it('the shelf face holds only initiatives in the lattice and loose items in the bin', () => {
      const { lattice, bin } = shelfTopLevel(shelf)
      expect(lattice.map(byKey)).toEqual(['initiative:i1', 'initiative:i2'])
      // The bin: the unanchored project and the top-level loose
      // task — NOT the bin project's tasks, NOT any bay's children.
      expect(bin.map(byKey)).toEqual(['project:p3', 'task:t4'])
    })

    it('opening a parent reveals exactly its children, level by level', () => {
      const flat = flattenShelf(shelf)
      const get = (key: string) => flat.find((s) => byKey(s) === key)!
      expect(scrollChildren(shelf, get('initiative:i1')).map(byKey)).toEqual(['project:p1'])
      // A project opens to its TOP-LEVEL tasks — the subtask is
      // not among them; it hangs under its parent task.
      expect(scrollChildren(shelf, get('project:p1')).map(byKey)).toEqual(['task:t1', 'task:t2'])
      expect(scrollChildren(shelf, get('task:t2')).map(byKey)).toEqual(['task:t2a'])
      expect(scrollChildren(shelf, get('task:t2a'))).toEqual([])
      expect(scrollChildren(shelf, get('project:p3'))).toEqual([])
    })

    it('every scroll is reachable: top-level, or a child of a reachable parent', () => {
      const { lattice, bin } = shelfTopLevel(shelf)
      const reachable = new Set<string>()
      const walk = (s: ShelfScroll) => {
        if (reachable.has(byKey(s))) return
        reachable.add(byKey(s))
        for (const c of scrollChildren(shelf, s)) walk(c)
      }
      for (const s of [...lattice, ...bin]) walk(s)
      expect([...reachable].sort()).toEqual(flattenShelf(shelf).map(byKey).sort())
    })

    it('task scrolls carry their recorded parent edge', () => {
      const flat = flattenShelf(shelf)
      expect(flat.find((s) => s.id === 't2a')?.parentTaskId).toBe('t2')
      expect(flat.find((s) => s.id === 't1')?.parentTaskId).toBeNull()
      expect(flat.find((s) => s.id === 'p1')?.parentTaskId).toBeNull()
    })
  })
})

describe('scroll appearance — distinctions from recorded fields only', () => {
  it('a Blocked item wears Jynx’s purple binding; Done fades; open work is plain', () => {
    const shelf = buildScrollShelf(
      [ini('i1', 'I')],
      [proj('p1', 'Stuck', 'i1', 'Blocked'), proj('p2', 'Finished', 'i1', 'Complete')],
      [task('t1', 'Open step', 'p1', 'Todo')],
    )
    const flat = flattenShelf(shelf)
    const byTitle = new Map(flat.map((s) => [s.title, s]))
    expect(byTitle.get('Stuck')!.appearance.cord).toBe(JYNX_PURPLE)
    expect(byTitle.get('Finished')!.appearance.cord).toBe('#8a7a5f')
    expect(byTitle.get('Open step')!.appearance.cord).toBe('#4a3826')
    expect(byTitle.get('Stuck')!.appearance.cordRule).toContain('Blocked')
  })

  it('size follows kind, then recorded mass', () => {
    const shelf = buildScrollShelf(
      [ini('i1', 'I')],
      [proj('p1', 'P', 'i1')],
      [task('t1', 'Small', 'p1', 'Todo', '2026-03-01T00:00:00', null, 2),
       task('t2', 'Heavy', 'p1', 'Todo', '2026-03-01T00:00:00', null, 40)],
    )
    const flat = flattenShelf(shelf)
    const byTitle = new Map(flat.map((s) => [s.title, s]))
    // initiative (1 project) > project (2 tasks) > task; a heavier
    // recorded estimate thickens the task's roll.
    expect(byTitle.get('I')!.appearance.radius).toBe(26)
    expect(byTitle.get('P')!.appearance.radius).toBe(21)
    expect(byTitle.get('Heavy')!.appearance.radius).toBeGreaterThan(
      byTitle.get('Small')!.appearance.radius,
    )
    expect(byTitle.get('P')!.mass).toBe(2)
    expect(byTitle.get('I')!.mass).toBe(1)
  })

  it('parchment tone spreads across the recorded age of the shelf', () => {
    const shelf = buildScrollShelf(
      [ini('i1', 'Oldest', 'Active', '2025-01-01T00:00:00')],
      [proj('p1', 'Newest', 'i1', 'Active', '2026-06-01T00:00:00')],
      [],
    )
    const flat = flattenShelf(shelf)
    const byTitle = new Map(flat.map((s) => [s.title, s]))
    expect(byTitle.get('Oldest')!.appearance.ageTone).toBe(1)
    expect(byTitle.get('Newest')!.appearance.ageTone).toBe(0)
    expect(byTitle.get('Oldest')!.appearance.parchment).not.toBe(
      byTitle.get('Newest')!.appearance.parchment,
    )
  })
})

describe('drawing reveal — marks arrive in order, in the study’s tiers', () => {
  const drawing: ScrollDrawing = {
    id: 'd1',
    title: null,
    space: { w: 600, h: 800 },
    marks: [
      { type: 'stamp', stamp: 'ring', cx: 300, cy: 300, w: 400, tier: TIER_MID },
      { type: 'stamp', stamp: 'arc', cx: 180, cy: 340, w: 320, angle: 24, tier: TIER_DARK },
      { type: 'stroke', d: 'M40 40 L50 50', width: 1.5, tier: TIER_LIGHT },
    ],
    conversationId: 'jynx-scroll:project:p1',
  }

  it('a later mark never starts before the earlier one completes', () => {
    expect(markProgressAt(0, drawing, 0)).toBe(0)
    expect(markProgressAt(310, drawing, 0)).toBeCloseTo(0.5)
    expect(markProgressAt(310, drawing, 1)).toBe(0)
    expect(markProgressAt(620, drawing, 0)).toBe(1)
    expect(markProgressAt(620, drawing, 1)).toBe(0)
    expect(markProgressAt(710 + 310, drawing, 1)).toBeCloseTo(0.5)
    expect(markProgressAt(drawingDurationMs(drawing), drawing, 2)).toBe(1)
    expect(markProgressAt(drawingDurationMs(drawing) + 5000, drawing, 2)).toBe(1)
  })

  it('the tiers are the scroll study’s three ink tiers', () => {
    expect([TIER_DARK, TIER_MID, TIER_LIGHT]).toEqual([0.95, 0.6, 0.32])
  })
})

describe('ideas — each its own scroll unit in the bin', () => {
  it('an idea stands as its own scroll; an initiative keeps its origin edge', () => {
    const shelf = buildScrollShelf(
      [{ ...ini('i1', 'Founded thing'), source_idea_id: 'idea1' }],
      [],
      [],
      [
        {
          id: 'idea1', title: 'The first thought', summary: '', description: '',
          status: 'Captured', tags: [], created_by: '', notes: '',
          created_at: '2025-12-01T00:00:00', updated_at: '2025-12-01T00:00:00',
        },
      ],
    )
    const flat = flattenShelf(shelf)
    const idea = flat.find((s) => s.kind === 'idea')
    expect(idea?.title).toBe('The first thought')
    expect(shelf[0].initiative?.sourceIdeaId).toBe('idea1')
    const bin = shelf[shelf.length - 1]
    expect(bin.initiative).toBeNull()
    expect(bin.ideas.map((s) => s.title)).toEqual(['The first thought'])
  })
})

describe('a scroll’s own drawings — the sheet is keyed to its conversation', () => {
  const mk = (id: string, conversationId: string | null): ScrollDrawing => ({
    id,
    title: null,
    space: { w: 600, h: 800 },
    marks: [],
    conversationId,
  })

  it('keeps only the drawings born in the open conversation, in order', () => {
    const feed = [
      mk('d1', 'jynx-scroll:project:p1'),
      mk('d2', 'jynx-scroll:task:t9'),
      mk('d3', 'jynx-scroll:project:p1'),
      mk('d4', 'jynx-scroll:drawing:d1'),
      mk('d5', null),
    ]
    expect(drawingsForConversation(feed, 'jynx-scroll:project:p1').map((d) => d.id)).toEqual([
      'd1',
      'd3',
    ])
    expect(drawingsForConversation(feed, 'jynx-scroll:task:t9').map((d) => d.id)).toEqual(['d2'])
    expect(drawingsForConversation(feed, 'jynx-scroll:shelf')).toEqual([])
    expect(drawingsForConversation([], 'jynx-scroll:project:p1')).toEqual([])
  })
})

describe('the sheet layout — one continuous sheet, history rolled at the top', () => {
  const mk = (id: string): ScrollDrawing => ({
    id,
    title: null,
    space: { w: 600, h: 800 },
    marks: [],
    conversationId: 'jynx-scroll:project:p1',
  })
  const three = [mk('d1'), mk('d2'), mk('d3')]

  it('an empty sheet is one blank working band', () => {
    const layout = sheetLayout([], 0)
    expect(layout.bands).toHaveLength(1)
    expect(layout.bands[0].drawing).toBeNull()
    expect(layout.bands[0].height).toBe(SHEET_BAND_H)
    expect(layout.focus).toBe(0)
    expect(layout.focusOffset).toBe(0)
  })

  it('bands stand in birth order with the blank working band last', () => {
    const layout = sheetLayout(three, 2)
    expect(layout.bands.map((b) => b.drawing?.id ?? 'blank')).toEqual(['d1', 'd2', 'd3', 'blank'])
    expect(layout.bands.map((b) => b.index)).toEqual([0, 1, 2, 3])
    // Bands tile the sheet: each starts where the previous ended.
    for (let i = 1; i < layout.bands.length; i++) {
      expect(layout.bands[i].y).toBe(layout.bands[i - 1].y + layout.bands[i - 1].height)
    }
    expect(layout.totalHeight).toBe(layout.bands[3].y + SHEET_BAND_H)
  })

  it('bands older than the focus stand compact; the focus and newer stand full', () => {
    const layout = sheetLayout(three, 2)
    expect(layout.bands[0].compact).toBe(true)
    expect(layout.bands[1].compact).toBe(true)
    expect(layout.bands[0].height).toBeLessThan(SHEET_BAND_H)
    expect(layout.bands[2].compact).toBe(false)
    expect(layout.bands[2].height).toBe(SHEET_BAND_H)
    expect(layout.bands[3].height).toBe(SHEET_BAND_H)
    expect(layout.focusOffset).toBe(layout.bands[2].y)
  })

  it('the rolled zone is capped no matter how long the history grows', () => {
    const many = Array.from({ length: 30 }, (_, i) => mk(`d${i}`))
    const layout = sheetLayout(many, 29)
    const rolled = layout.bands.slice(0, 29)
    const rolledTotal = rolled.reduce((sum, b) => sum + b.height, 0)
    expect(rolledTotal).toBeLessThanOrEqual(SHEET_COMPACT_ZONE_MAX + 1e-9)
    expect(rolled.every((b) => b.compact)).toBe(true)
    expect(layout.bands[29].height).toBe(SHEET_BAND_H)
  })

  it('the focus clamps to the sheet: oldest drawing at one end, blank band at the other', () => {
    expect(sheetLayout(three, -4).focus).toBe(0)
    expect(sheetLayout(three, 99).focus).toBe(3)
    const atBlank = sheetLayout(three, 3)
    expect(atBlank.bands.every((b) => b.drawing === null || b.compact)).toBe(true)
    expect(atBlank.focusOffset).toBe(atBlank.bands[3].y)
  })

  it('rolling changes the offset, never the membership', () => {
    const ids = (f: number) => sheetLayout(three, f).bands.map((b) => b.drawing?.id ?? 'blank')
    expect(ids(0)).toEqual(ids(3))
    expect(sheetLayout(three, 0).focusOffset).not.toBe(sheetLayout(three, 2).focusOffset)
  })
})
