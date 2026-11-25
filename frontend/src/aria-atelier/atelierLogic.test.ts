/**
 * Atelier pure logic — the garden model, cast scopes, and the layer
 * stack's channels, driven from the real hierarchy shapes: a
 * graph-piled cairn (the Vision map's cairn index), projects the
 * graph left unpiled, and standalone tasks. A scope the data does
 * not carry (a project under no initiative) resolves to absent —
 * never invented.
 */
import { describe, it, expect } from 'vitest'
import type { Node } from '@xyflow/react'
import type { CairnEntry, CairnIndex } from '../vision-map/cairn'
import type { MapNodePayload } from '../vision-map/ontology'
import type { Initiative, Project, Task } from '../vision-execution/types'
import {
  FILL_TAU,
  FORMATION_SCALE,
  GARDEN_GAP,
  GARDEN_REF_H,
  GARDEN_REF_W,
  STACK_DEFAULT,
  bringToFront,
  buildGarden,
  castInitiative,
  castLooseStone,
  castProject,
  castStone,
  chatContextFor,
  conversationIdFor,
  depthProjectId,
  depthsForSubject,
  fillStep,
  fillTarget,
  floorMult,
  gardenFootprint,
  gardenLayout,
  gardenPositions,
  looseCairns,
  ringInitiatives,
  rungOf,
  talkDepth,
  type GardenBundle,
  type GardenFootprint,
} from './atelierLogic'

const initiative = (over: Record<string, unknown>): Initiative =>
  ({ id: 'i1', title: 'Spring line', ...over }) as unknown as Initiative
const project = (over: Record<string, unknown>): Project =>
  ({
    id: 'p1',
    initiative_id: 'i1',
    title: 'Spring collection launch',
    created_at: '2026-05-01T00:00:00',
    ...over,
  }) as unknown as Project
const task = (over: Record<string, unknown>): Task =>
  ({
    id: 't1',
    project_id: 'p1',
    title: 'Confirm the print run',
    created_at: '2026-05-01T00:00:00',
    ...over,
  }) as unknown as Task

const payload = (over: Record<string, unknown>): MapNodePayload =>
  ({
    kind: 'flower',
    label: 'A stone',
    growth: 'dormant',
    condition: 'ok',
    ref: { veType: 'task', id: 't1' },
    summaryLines: [],
    water_level: 'low',
    fertilizer_pulse: false,
    ...over,
  }) as unknown as MapNodePayload

const node = (id: string, over: Record<string, unknown>): Node<MapNodePayload> =>
  ({ id, type: 'entity', position: { x: 0, y: 0 }, data: payload(over) }) as Node<MapNodePayload>

/** A graph-piled cairn for p1: branch parent + two task flowers + a
 *  synthesized fruit (in the pile, never a castable stone). */
function piledIndex(): CairnIndex {
  const memberNodes = [
    node('branch-p1', { kind: 'branch', label: 'Spring collection launch', ref: { veType: 'project', id: 'p1' } }),
    node('flower-t1', { label: 'Confirm the print run', ref: { veType: 'task', id: 't1' } }),
    node('flower-t2', { label: 'Book the photographer', ref: { veType: 'task', id: 't2' } }),
    node('fruit-o1', { kind: 'fruit', label: 'Collection shipped', ref: { veType: 'outcome', id: 'o1' } }),
  ]
  const entry = {
    cairnId: 'cairn-p1',
    projectId: 'p1',
    projectTitle: 'Spring collection launch',
    memberNodes,
  } as unknown as CairnEntry
  return { 'cairn-p1': entry }
}

const bundle = (over: Partial<GardenBundle> = {}): GardenBundle => ({
  initiatives: [initiative({})],
  projects: [project({})],
  tasks: [
    task({}),
    task({ id: 't2', title: 'Book the photographer' }),
    task({ id: 't3', project_id: null, title: 'Loose errand' }),
  ],
  ...over,
})

describe('buildGarden', () => {
  it('keeps a graph-piled cairn’s members verbatim and reads its stones from the member nodes', () => {
    const garden = buildGarden(bundle(), piledIndex())
    expect(garden.cairns).toHaveLength(1)
    const cairn = garden.cairns[0]
    expect(cairn.cairnId).toBe('cairn-p1')
    expect(cairn.projectId).toBe('p1')
    expect(cairn.initiativeId).toBe('i1')
    expect(cairn.initiativeTitle).toBe('Spring line')
    // The branch member is the pile's parent; every member is carried.
    const parent = cairn.members.find((m) => m.id === 'branch-p1')
    expect(parent?.parent).toBe(true)
    expect(cairn.members.map((m) => m.id)).toEqual(['branch-p1', 'flower-t1', 'flower-t2', 'fruit-o1'])
    // Stones are the task members only — the fruit is not a stone.
    expect(cairn.stones).toEqual([
      { taskId: 't1', title: 'Confirm the print run', memberId: 'flower-t1' },
      { taskId: 't2', title: 'Book the photographer', memberId: 'flower-t2' },
    ])
    // The piled project's tasks are not loose; the standalone task is.
    expect(garden.looseStones.map((s) => s.taskId)).toEqual(['t3'])
  })

  it('carries an unpiled project as a lone pile built from the bundle', () => {
    const garden = buildGarden(bundle(), {})
    const cairn = garden.cairns.find((c) => c.projectId === 'p1')
    expect(cairn).toBeDefined()
    expect(cairn!.cairnId).toBe('atelier-cairn-p1')
    expect(cairn!.members[0]).toMatchObject({ id: 'branch-p1', parent: true })
    // Stones are carried in title order, as the bundle path sorts them.
    expect(cairn!.stones.map((s) => s.taskId)).toEqual(['t2', 't1'])
    expect(garden.looseStones.map((s) => s.taskId)).toEqual(['t3'])
  })

  it('a project under no initiative carries no initiative title', () => {
    const garden = buildGarden(
      bundle({ projects: [project({ initiative_id: null })] }),
      {},
    )
    expect(garden.cairns[0].initiativeId).toBeNull()
    expect(garden.cairns[0].initiativeTitle).toBeNull()
  })
})

describe('cast scopes', () => {
  const garden = buildGarden(bundle(), piledIndex())
  const cairn = garden.cairns[0]

  it('resolves stone, project, and initiative casts from the cairn', () => {
    expect(castStone(cairn, cairn.stones[0])).toMatchObject({
      scope: 'task',
      taskId: 't1',
      title: 'Confirm the print run',
    })
    expect(castProject(cairn)).toMatchObject({ scope: 'project', projectId: 'p1' })
    expect(castInitiative(cairn)).toMatchObject({
      scope: 'initiative',
      initiativeId: 'i1',
      title: 'Spring line',
    })
    expect(castLooseStone(garden.looseStones[0])).toMatchObject({ scope: 'loose', taskId: 't3' })
  })

  it('an initiative cast is absent — never invented — when the project has none', () => {
    const bare = buildGarden(bundle({ projects: [project({ initiative_id: null })] }), {})
    expect(castInitiative(bare.cairns[0])).toBeNull()
  })

  it('keys each scope’s conversation and chat context', () => {
    const stone = castStone(cairn, cairn.stones[0])
    expect(conversationIdFor(stone)).toBe('aria-atelier:task:t1')
    expect(chatContextFor(stone)).toEqual({
      sheet_type: 'aria_atelier',
      entity_type: 'task',
      entity_id: 't1',
    })
    expect(conversationIdFor(castProject(cairn))).toBe('aria-atelier:project:p1')
    expect(chatContextFor(castProject(cairn))).toEqual({
      sheet_type: 'aria_atelier',
      entity_type: 'project',
      entity_id: 'p1',
    })
    expect(conversationIdFor(castInitiative(cairn))).toBe('aria-atelier:initiative:i1')
    expect(chatContextFor(castInitiative(cairn))).toEqual({
      sheet_type: 'aria_atelier',
      entity_type: 'initiative',
      entity_id: 'i1',
    })
    expect(conversationIdFor(castLooseStone(garden.looseStones[0]))).toBe('aria-atelier:task:t3')
    expect(conversationIdFor(null)).toBe('aria-atelier:garden')
    expect(chatContextFor(null)).toEqual({ sheet_type: 'aria_atelier' })
  })

  it('scopes talk depth: a task speaks within its project, an initiative through its broadest cairn, a loose stone nowhere', () => {
    expect(depthProjectId(castStone(cairn, cairn.stones[0]), garden)).toBe('p1')
    expect(depthProjectId(castProject(cairn), garden)).toBe('p1')
    expect(depthProjectId(castInitiative(cairn)!, garden)).toBe('p1')
    expect(depthProjectId(castLooseStone(garden.looseStones[0]), garden)).toBeNull()
  })
})

describe('talk depth', () => {
  it('maps real counts: six turns saturate, a keystone arc counts as four', () => {
    expect(talkDepth(0, 0)).toBe(0)
    expect(talkDepth(6, 0)).toBe(1)
    expect(talkDepth(60, 0)).toBe(1)
    expect(talkDepth(2, 1)).toBe(1)
    expect(talkDepth(3, 0)).toBe(0.5)
    expect(talkDepth(-2, -1)).toBe(0)
  })

  it('reads per-voice depths from per-archetype counts', () => {
    const depths = depthsForSubject({ conductor: 3, champion: 6 }, { mentor: 1 })
    expect(depths.aria).toBe(0.5)
    expect(depths.valen).toBe(1)
    expect(depths.rumi).toBeCloseTo(4 / 6)
    expect(depths.jynx).toBe(0)
    expect(depthsForSubject({}, undefined).severine).toBe(0)
  })

  it('rungs run 1–5', () => {
    expect(rungOf(0)).toBe(1)
    expect(rungOf(0.2)).toBe(1)
    expect(rungOf(0.21)).toBe(2)
    expect(rungOf(1)).toBe(5)
  })
})

describe('the stack channels', () => {
  it('brings the interacted voice to the front, the rest in relative order', () => {
    expect(bringToFront([...STACK_DEFAULT], 'maeve')).toEqual([
      'rumi',
      'valen',
      'lucian',
      'aria',
      'jynx',
      'severine',
      'maeve',
    ])
    expect(bringToFront([...STACK_DEFAULT], 'severine')).toEqual(STACK_DEFAULT)
  })

  it('fill targets: the selected voice at the ceiling scale, the rest at their floor', () => {
    expect(fillTarget('aria', 'aria', 80)).toBe(1)
    expect(fillTarget('aria', 'all', 80)).toBe(1)
    expect(fillTarget('aria', 'aria', 40)).toBe(0.5)
    // floorMult puts baked × mult at the 10% floor: Valen .5 → .2, Rumi .8 → .125.
    expect(floorMult('valen')).toBeCloseTo(0.2)
    expect(fillTarget('valen', 'aria', 80)).toBeCloseTo(0.2)
    expect(fillTarget('rumi', 'aria', 80)).toBeCloseTo(0.125)
    // Severine's baked level IS the floor — she recedes no further.
    expect(fillTarget('severine', 'aria', 80)).toBe(1)
    expect(fillTarget('valen', 'aria', 40)).toBeCloseTo(0.1)
  })

  it('fill steps approach base-e and snap at the threshold', () => {
    const oneTau = fillStep(0, 1, FILL_TAU)
    expect(oneTau).toBeCloseTo(1 - Math.exp(-1), 5)
    expect(fillStep(0.999, 1, 0.01)).toBe(1)
    expect(fillStep(0.5, 0.5, 0.1)).toBe(0.5)
  })
})

describe('gardenPositions', () => {
  it('is deterministic and keeps every cairn inside the field', () => {
    expect(gardenPositions(6)).toEqual(gardenPositions(6))
    for (const n of [1, 2, 5, 9, 14]) {
      for (const p of gardenPositions(n)) {
        expect(p.x).toBeGreaterThanOrEqual(14)
        expect(p.x).toBeLessThanOrEqual(86)
        expect(p.y).toBeGreaterThanOrEqual(17)
        expect(p.y).toBeLessThanOrEqual(83)
      }
    }
    expect(gardenPositions(0)).toEqual([])
  })
})

describe('parents + loose — the ring grouping', () => {
  it('groups an initiative’s cairns into one ring pile; loose cairns stand alone', () => {
    const g = buildGarden(
      bundle({
        projects: [
          project({}),
          project({ id: 'p2', title: 'Second project' }),
          project({ id: 'p3', initiative_id: null, title: 'Loose project' }),
        ],
        tasks: [
          task({}),
          task({ id: 't2', title: 'Book the photographer' }),
          task({ id: 't9', project_id: 'p2', title: 'Second stone' }),
          task({ id: 't3', project_id: null, title: 'Loose errand' }),
        ],
      }),
      piledIndex(),
    )
    const piles = ringInitiatives(g)
    expect(piles).toHaveLength(1)
    expect(piles[0].initiativeId).toBe('i1')
    expect(piles[0].title).toBe('Spring line')
    expect(piles[0].cairns.map((c) => c.projectId).sort()).toEqual(['p1', 'p2'])
    // Stones counted across both projects (2 piled + 1 unpiled).
    expect(piles[0].stoneCount).toBe(3)
    // Member ids stay unique across the union, and only one
    // branch keeps the parent flag.
    const ids = piles[0].members.map((m) => m.id)
    expect(new Set(ids).size).toBe(ids.length)
    expect(piles[0].members.filter((m) => m.parent)).toHaveLength(1)

    const loose = looseCairns(g)
    expect(loose.map((c) => c.projectId)).toEqual(['p3'])
    // Reachability: every garden cairn is in exactly one ring pile
    // or stands loose.
    const covered = [...piles.flatMap((p) => p.cairns), ...loose]
    expect(covered.map((c) => c.projectId).sort()).toEqual(
      g.cairns.map((c) => c.projectId).sort(),
    )
  })
})

describe('gardenLayout — shown labels never overlap', () => {
  const fp = (title: string, pileH = 90, count = true): GardenFootprint =>
    gardenFootprint({ title, pileWidthPx: 104, pileHeightPx: pileH, showCount: count })

  function expectLegible(items: GardenFootprint[]) {
    const placed = gardenLayout(items)
    expect(placed).toHaveLength(items.length)
    // Pairwise: no two footprint boxes come within the gap.
    for (let i = 0; i < placed.length; i++) {
      for (let j = i + 1; j < placed.length; j++) {
        const a = placed[i].box
        const b = placed[j].box
        const ox = Math.min(a.left + a.width, b.left + b.width) - Math.max(a.left, b.left)
        const oy = Math.min(a.top + a.height, b.top + b.height) - Math.max(a.top, b.top)
        expect(
          ox <= -GARDEN_GAP + 0.5 || oy <= -GARDEN_GAP + 0.5,
          `items ${i} and ${j} overlap (ox=${ox.toFixed(1)}, oy=${oy.toFixed(1)})`,
        ).toBe(true)
      }
    }
    for (const p of placed) {
      // Inside the field (6px edge bleed allowed, as the garden
      // already lets piles kiss the rim).
      expect(p.box.left).toBeGreaterThanOrEqual(-6.5)
      expect(p.box.top).toBeGreaterThanOrEqual(-6.5)
      expect(p.box.left + p.box.width).toBeLessThanOrEqual(GARDEN_REF_W + 6.5)
      expect(p.box.top + p.box.height).toBeLessThanOrEqual(GARDEN_REF_H + 6.5)
    }
    return placed
  }

  it('lays out a small garden legibly and deterministically', () => {
    const items = [fp('Zenaf — outsourced executive function', 95), fp('Meet your council', 80)]
    expect(gardenLayout(items)).toEqual(gardenLayout(items))
    const placed = expectLegible(items)
    // A garden that fits stands at full size.
    expect(placed.every((p) => p.scale === 1)).toBe(true)
  })

  it('a crowded garden shrinks uniformly rather than overlapping', () => {
    const titles = [
      'Zenaf — outsourced executive function',
      'Meet your council',
      'Tier 0 — In flight, decide now',
      'Downstream builds (noting producer + Slice 2)',
      'Capability B trial — dentist follow-up',
      'W1 live test task',
      'Loose errand',
      'Fix the gate latch',
    ]
    const placed = expectLegible(titles.map((t, i) => fp(t, 55 + (i % 4) * 16, i % 3 !== 0)))
    // One uniform scale for the whole set, never below the floor.
    expect(new Set(placed.map((p) => p.scale)).size).toBe(1)
    expect(placed[0].scale).toBeGreaterThanOrEqual(0.55)
  })

  it('keeps a crowded garden legible — long titles, eight shown items', () => {
    // The crowded end of what the parents+loose rule shows: two
    // initiative piles plus a half-dozen loose items, several
    // with label-capping titles.
    const titles = [
      'Zenaf — outsourced executive function',
      'Meet your council',
      'Tier 0 — In flight, decide now',
      'Downstream builds (noting producer + Slice 2)',
      'Capability B trial — dentist follow-up',
      'W1 live test task',
      'Loose errand',
      'Fix the gate latch',
    ]
    expectLegible(titles.map((t, i) => fp(t, 55 + (i % 4) * 16, i % 3 !== 0)))
  })

  it('an empty garden lays out empty', () => {
    expect(gardenLayout([])).toEqual([])
  })
})

describe('the formation scale', () => {
  it('stands substantially larger in the bowl than the unscaled stack', () => {
    // The founder’s correction: the formation must fill
    // substantially more of the bowl’s inner diameter, water
    // still visible as a rim — a scale above 1.25 and below the
    // point where the rim disappears entirely.
    expect(FORMATION_SCALE).toBeGreaterThan(1.25)
    expect(FORMATION_SCALE).toBeLessThan(1.45)
  })
})
