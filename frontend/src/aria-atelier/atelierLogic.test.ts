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
  FILL_BAKED,
  FILL_FLOOR,
  FILL_TAU,
  FORMATION_SCALE,
  GARDEN_GAP,
  GARDEN_SEATS,
  SCENE1_BASIN,
  SCENE1_WELL_SCALE_Y,
  SCENE2_DISC,
  SCENE2_LOTUS_OVERLAY,
  SCENE_BASIN_REF,
  SCENE_REF_H,
  SCENE_REF_W,
  STAGE_COUNT,
  STACK_DEFAULT,
  boxIntersectsBasin,
  bringToFront,
  buildGarden,
  buoyancyDrift,
  buoyancyTransform,
  stillComparisonIn,
  twinOffset,
  castInitiative,
  castLooseStone,
  castProject,
  castStone,
  chatContextFor,
  conversationIdFor,
  depthProjectId,
  depthsForSubject,
  fanBoxFor,
  fanPositionClear,
  fillMultiplier,
  fillPresence,
  fillStep,
  gardenFootprint,
  looseCairns,
  ringInitiatives,
  rungOf,
  scenePlacements,
  stageForDepth,
  talkDepth,
  type FanBox,
  type GardenBundle,
  type GardenFootprint,
  type Voice,
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

  it('graded fill: the last speaker stands at full presence, whatever their depth', () => {
    const depths = depthsForSubject({ champion: 1 }, undefined) // Valen depth 1/6
    expect(depths.valen).toBeCloseTo(1 / 6)
    expect(fillPresence('valen', depths, 'valen')).toBe(FILL_BAKED.valen)
    expect(fillMultiplier('valen', depths, 'valen')).toBe(1)
    // Even with no recorded depth at all, having just spoken is
    // the recorded fact that carries full presence.
    expect(fillPresence('jynx', depthsForSubject({}, undefined), 'jynx')).toBe(FILL_BAKED.jynx)
  })

  it('graded fill: recorded depth grades a voice between the floor and its baked level', () => {
    const depths = depthsForSubject({ conductor: 3, mentor: 6 }, undefined)
    // Aria depth 0.5, not the last speaker: .1 + (.5 − .1) × .5 = .3.
    expect(fillPresence('aria', depths, 'rumi')).toBeCloseTo(0.3)
    expect(fillMultiplier('aria', depths, 'rumi')).toBeCloseTo(0.3 / FILL_BAKED.aria)
    // Rumi at full depth holds his full baked level without
    // being selected — presence is data, not a selection.
    expect(fillPresence('rumi', depths, 'aria')).toBeCloseTo(FILL_BAKED.rumi)
  })

  it('graded fill: no recorded talk about the subject sits at the floor', () => {
    const depths = depthsForSubject({ conductor: 2 }, undefined)
    expect(fillPresence('jynx', depths, 'aria')).toBe(FILL_FLOOR)
    expect(fillMultiplier('jynx', depths, 'aria')).toBeCloseTo(FILL_FLOOR / FILL_BAKED.jynx)
    expect(fillPresence('maeve', depths, null)).toBe(FILL_FLOOR)
  })

  it('graded fill: targets never leave the ruled band, for any data', () => {
    const voices: Voice[] = ['rumi', 'valen', 'maeve', 'lucian', 'aria', 'severine', 'jynx']
    for (const v of voices) {
      for (const d of [0, 0.37, 1]) {
        for (const last of [null, v, 'aria' as Voice]) {
          const depths = Object.fromEntries(voices.map((x) => [x, d])) as Record<Voice, number>
          const presence = fillPresence(v, depths, last)
          expect(presence).toBeGreaterThanOrEqual(FILL_FLOOR)
          expect(presence).toBeLessThanOrEqual(FILL_BAKED[v])
          const mult = fillMultiplier(v, depths, last)
          expect(mult).toBeGreaterThan(0)
          expect(mult).toBeLessThanOrEqual(1)
        }
      }
    }
    // Severine's baked level IS the floor — she recedes no further.
    expect(fillPresence('severine', depthsForSubject({}, undefined), null)).toBe(FILL_FLOOR)
    expect(fillMultiplier('severine', depthsForSubject({}, undefined), null)).toBe(1)
  })

  it('stage mapping: the hold stage is the recorded depth of the ladder', () => {
    expect(STAGE_COUNT).toBe(12)
    expect(stageForDepth(0)).toBe(0)
    expect(stageForDepth(1)).toBe(STAGE_COUNT)
    expect(stageForDepth(0.5)).toBe(6)
    expect(stageForDepth(1 / 3)).toBe(4)
    expect(stageForDepth(2)).toBe(STAGE_COUNT)
    expect(stageForDepth(-1)).toBe(0)
  })

  it('fill steps approach base-e and snap at the threshold', () => {
    const oneTau = fillStep(0, 1, FILL_TAU)
    expect(oneTau).toBeCloseTo(1 - Math.exp(-1), 5)
    expect(fillStep(0.999, 1, 0.01)).toBe(1)
    expect(fillStep(0.5, 0.5, 0.1)).toBe(0.5)
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

describe('the painted scenes — measured geometry', () => {
  it('pins Screen 1’s basin ellipse and the well’s perspective squash', () => {
    expect(SCENE1_BASIN).toEqual({ cx: 0.589, cy: 0.506, rx: 0.142, ry: 0.036 })
    // The squash is the ellipse's own aspect on the painting's
    // pixels: (ry × 1448) / (rx × 1086).
    expect(SCENE1_WELL_SCALE_Y).toBeCloseTo(0.338, 3)
    expect(SCENE1_WELL_SCALE_Y).toBeCloseTo((0.036 * 1448) / (0.142 * 1086), 2)
    // The reference-scene ellipse is the same ellipse in px.
    expect(SCENE_BASIN_REF.cx).toBeCloseTo(0.589 * SCENE_REF_W)
    expect(SCENE_BASIN_REF.cy).toBeCloseTo(0.506 * SCENE_REF_H)
    expect(SCENE_BASIN_REF.rx).toBeCloseTo(0.142 * SCENE_REF_W)
    expect(SCENE_BASIN_REF.ry).toBeCloseTo(0.036 * SCENE_REF_H)
  })

  it('pins Screen 2’s disc and the lotus overlay placement', () => {
    expect(SCENE2_DISC).toEqual({ cx: 0.488, cy: 0.49, r: 0.164 })
    expect(SCENE2_LOTUS_OVERLAY.left).toBeCloseTo(311 / 1086)
    expect(SCENE2_LOTUS_OVERLAY.top).toBeCloseTo(616 / 1448)
    expect(SCENE2_LOTUS_OVERLAY.width).toBeCloseTo(163 / 1086)
  })

  it('the seat table: at least ten seats, in the ruled prominence order, every anchor clear of the basin', () => {
    expect(GARDEN_SEATS.length).toBeGreaterThanOrEqual(10)
    expect(GARDEN_SEATS.slice(0, 10)).toEqual([
      { x: 0.24, y: 0.7, scale: 1.15 },
      { x: 0.78, y: 0.72, scale: 1.15 },
      { x: 0.12, y: 0.55, scale: 1.0 },
      { x: 0.88, y: 0.57, scale: 1.0 },
      { x: 0.3, y: 0.86, scale: 1.25 },
      { x: 0.66, y: 0.87, scale: 1.25 },
      { x: 0.33, y: 0.4, scale: 0.8 },
      { x: 0.74, y: 0.41, scale: 0.8 },
      { x: 0.16, y: 0.38, scale: 0.75 },
      { x: 0.86, y: 0.36, scale: 0.75 },
    ])
    // Every seat anchor stands on the sand: its normalised
    // distance from the basin centre is well outside the ellipse.
    for (const seat of GARDEN_SEATS) {
      const q =
        ((seat.x * SCENE_REF_W - SCENE_BASIN_REF.cx) / SCENE_BASIN_REF.rx) ** 2 +
        ((seat.y * SCENE_REF_H - SCENE_BASIN_REF.cy) / SCENE_BASIN_REF.ry) ** 2
      expect(q).toBeGreaterThan(2)
    }
  })
})

describe('scenePlacements — seats on the sand, labels in bounds, nothing on the basin', () => {
  const fp = (title: string, pileH = 90, count = true): GardenFootprint =>
    gardenFootprint({ title, pileWidthPx: 104, pileHeightPx: pileH, showCount: count })

  function expectLegible(items: GardenFootprint[]) {
    const placed = scenePlacements(items)
    expect(placed).toHaveLength(items.length)
    // The water is water: no footprint — pile, name label, count
    // line — covers the basin ellipse.
    for (const [i, p] of placed.entries()) {
      expect(boxIntersectsBasin(p.box), `item ${i} stands on the basin`).toBe(false)
    }
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
    // Every label box is clamped inside the scene — the live
    // defect of labels clipping off the right edge cannot
    // reproduce: no bleed is allowed at all.
    for (const p of placed) {
      expect(p.box.left).toBeGreaterThanOrEqual(-0.5)
      expect(p.box.top).toBeGreaterThanOrEqual(-0.5)
      expect(p.box.left + p.box.width).toBeLessThanOrEqual(SCENE_REF_W + 0.5)
      expect(p.box.top + p.box.height).toBeLessThanOrEqual(SCENE_REF_H + 0.5)
    }
    return placed
  }

  it('seats a small garden in prominence order at seat scale, deterministically', () => {
    const items = [fp('Zenaf — outsourced executive function', 55), fp('Meet your council', 50)]
    expect(scenePlacements(items)).toEqual(scenePlacements(items))
    const placed = expectLegible(items)
    // The first two shown items take the two foreground seats at
    // the seats' own depth scale — within the in-bounds clamp's
    // reach (the second item's wide label is pulled 0.7% in from
    // the scene's right edge, the clamp doing its work).
    for (const [i, p] of placed.entries()) {
      expect(Math.abs(p.x - GARDEN_SEATS[i].x * 100)).toBeLessThan(1.5)
      expect(Math.abs(p.y - GARDEN_SEATS[i].y * 100)).toBeLessThan(1.5)
      expect(p.scale).toBe(GARDEN_SEATS[i].scale)
    }
  })

  it('keeps a full seat table legible — ten shown items, several with label-capping titles', () => {
    const titles = [
      'Zenaf — outsourced executive function',
      'Meet your council',
      'Tier 0 — In flight, decide now',
      'Downstream builds (noting producer + Slice 2)',
      'Capability B trial — dentist follow-up',
      'W1 live test task',
      'Loose errand',
      'Fix the gate latch',
      'Water the greenhouse beds',
      'Sharpen the spare blades',
    ]
    expectLegible(titles.map((t, i) => fp(t, 55 + (i % 4) * 16, i % 3 !== 0)))
  })

  it('an empty garden lays out empty', () => {
    expect(scenePlacements([])).toEqual([])
  })

  it('the founder’s garden: one large initiative, loose projects, loose stones — nothing on the water', () => {
    // The shape of the founder's real garden: several initiatives
    // (one large), loose projects, loose stones. Every
    // placement's footprint + label box must be disjoint from
    // the basin ellipse.
    const items = [
      fp('Zenaf — outsourced executive function', 170),
      fp('Meet your council', 95),
      fp('Tier 0 — In flight, decide now', 80),
      fp('Downstream builds (noting producer + Slice 2)', 75),
      fp('Capability B trial — dentist follow-up', 70),
      gardenFootprint({ title: 'W1 live test task', pileWidthPx: 54, pileHeightPx: 34, showCount: false }),
      gardenFootprint({ title: 'Loose errand', pileWidthPx: 54, pileHeightPx: 30, showCount: false }),
    ]
    const placed = expectLegible(items)
    for (const p of placed) {
      // Disjointness stated geometrically, independent of the
      // helper: the box's closest point to the ellipse centre, in
      // the scaled space where the ellipse is a circle, lies at
      // or beyond the radius.
      const s = SCENE_BASIN_REF.rx / SCENE_BASIN_REF.ry
      const nx = Math.max(p.box.left, Math.min(SCENE_BASIN_REF.cx, p.box.left + p.box.width))
      const ny = Math.max(p.box.top * s, Math.min(SCENE_BASIN_REF.cy * s, (p.box.top + p.box.height) * s))
      expect(
        Math.hypot(nx - SCENE_BASIN_REF.cx, ny - SCENE_BASIN_REF.cy * s),
      ).toBeGreaterThanOrEqual(SCENE_BASIN_REF.rx - 0.001)
    }
  })

  it('a single huge cairn still cannot be pushed onto the basin', () => {
    const placed = scenePlacements([fp('Zenaf — outsourced executive function', 200)])
    expect(placed).toHaveLength(1)
    expect(boxIntersectsBasin(placed[0].box)).toBe(false)
  })
})

describe('boxIntersectsBasin', () => {
  it('a box over the water intersects; a box at the scene’s corner does not', () => {
    expect(
      boxIntersectsBasin({
        left: SCENE_BASIN_REF.cx - 20,
        top: SCENE_BASIN_REF.cy - 8,
        width: 40,
        height: 16,
      }),
    ).toBe(true)
    expect(boxIntersectsBasin({ left: 0, top: 0, width: 40, height: 40 })).toBe(false)
  })

  it('a footprint that merely crosses the water’s edge intersects; one tangent outside does not', () => {
    // A box whose right edge reaches 10px into the ellipse from
    // the left, centred on the ellipse's vertical centre.
    const crossing = {
      left: SCENE_BASIN_REF.cx - SCENE_BASIN_REF.rx - 30,
      top: SCENE_BASIN_REF.cy - 5,
      width: 40,
      height: 10,
    }
    expect(boxIntersectsBasin(crossing)).toBe(true)
    // The same box pulled 11px further out: its closest point is
    // 1px beyond the radius.
    expect(boxIntersectsBasin({ ...crossing, left: crossing.left - 11 })).toBe(false)
  })
})

describe('the fan — never on the water either', () => {
  /** Independent check: dense sampling of the fan box against
   *  the basin ellipse in % space (centre 58.9/50.6, radii 14.2 ×
   *  3.6 — SCENE1_BASIN). A sample strictly inside the ellipse is
   *  a violation. */
  function fanIntersectsBasin(leftPct: number, topPct: number, box: FanBox): boolean {
    const rx = SCENE1_BASIN.rx * 100
    const ry = SCENE1_BASIN.ry * 100
    for (let i = 0; i <= 48; i++) {
      for (let j = 0; j <= 48; j++) {
        const x = leftPct - box.widthPct / 2 + (box.widthPct * i) / 48
        const y = topPct + (box.heightPct * j) / 48
        const q = ((x - SCENE1_BASIN.cx * 100) / rx) ** 2 + ((y - SCENE1_BASIN.cy * 100) / ry) ** 2
        if (q < 0.99) return true
      }
    }
    return false
  }

  it('places fans clear of the basin for anchors at every seat', () => {
    const anchors = GARDEN_SEATS.map((s) => ({ x: s.x * 100, y: s.y * 100 }))
    for (const anchor of anchors) {
      for (const count of [1, 3, 6, 8]) {
        const box = fanBoxFor(count)
        const pos = fanPositionClear(anchor, box)
        expect(
          fanIntersectsBasin(pos.left, pos.top, box),
          `anchor ${anchor.x},${anchor.y} count ${count}`,
        ).toBe(false)
        // And the fan stays inside the scene.
        expect(pos.left - box.widthPct / 2).toBeGreaterThanOrEqual(-0.001)
        expect(pos.left + box.widthPct / 2).toBeLessThanOrEqual(100.001)
        expect(pos.top).toBeGreaterThanOrEqual(-0.001)
        expect(pos.top + box.heightPct).toBeLessThanOrEqual(100.001)
      }
    }
  })

  it('even a twelve-stone fan clears the basin outright', () => {
    // The painted basin is a small ellipse (28.4% × 7.2% of the
    // scene) where the old well disc was 47% wide: at the
    // reference width a 12-stone fan — ~93% × ~38% of the scene —
    // now always finds a fully clear placement.
    for (const anchor of [
      { x: 58.9, y: 40 },
      { x: 24, y: 70 },
      { x: 88, y: 57 },
      { x: 33, y: 40 },
      { x: 66, y: 87 },
    ]) {
      const box = fanBoxFor(12)
      const pos = fanPositionClear(anchor, box)
      expect(
        fanIntersectsBasin(pos.left, pos.top, box),
        `anchor ${anchor.x},${anchor.y}`,
      ).toBe(false)
    }
  })

  it('is deterministic', () => {
    const box = fanBoxFor(6)
    expect(fanPositionClear({ x: 30, y: 30 }, box)).toEqual(fanPositionClear({ x: 30, y: 30 }, box))
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

describe('dynamism — buoyancy (spec §2.1, experimental)', () => {
  it('drift amplitude halves per rank back from the front, floored at 0.3px', () => {
    expect(buoyancyDrift(0)).toBe(1.5)
    expect(buoyancyDrift(1)).toBe(0.75)
    expect(buoyancyDrift(2)).toBe(0.375)
    expect(buoyancyDrift(3)).toBe(0.3)
    expect(buoyancyDrift(6)).toBe(0.3)
    // Z-rank ordering: nearer the front always drifts at least
    // as much as the layer behind it.
    for (let r = 0; r < 6; r++) {
      expect(buoyancyDrift(r)).toBeGreaterThanOrEqual(buoyancyDrift(r + 1))
    }
  })

  it('translation and scale stay inside the spec bounds at every sampled phase', () => {
    for (let rank = 0; rank < 7; rank++) {
      const d = buoyancyDrift(rank)
      for (let s = 0; s < 720; s++) {
        const phase = (s / 720) * Math.PI * 4
        const t = buoyancyTransform(phase, rank)
        // The written values are rounded to 0.1px (per the spec),
        // which can carry a value at most 0.05px past the exact
        // bound; the assertions carry that rounding allowance.
        expect(Math.abs(t.dx), `rank ${rank} phase ${phase}`).toBeLessThanOrEqual(d + 0.05 + 1e-9)
        expect(Math.abs(t.dx)).toBeLessThanOrEqual(1.5 + 0.05 + 1e-9)
        expect(Math.abs(t.dy)).toBeLessThanOrEqual(d * 0.6 + 0.05 + 1e-9)
        expect(t.scale).toBeGreaterThanOrEqual(1.0)
        expect(t.scale).toBeLessThanOrEqual(1.006)
        // Written values are rounded to 0.1px, per the spec.
        expect(Math.abs(t.dx * 10 - Math.round(t.dx * 10))).toBeLessThan(1e-9)
        expect(Math.abs(t.dy * 10 - Math.round(t.dy * 10))).toBeLessThan(1e-9)
      }
    }
  })

  it('at phase zero the front layer rides at its full downward drift', () => {
    const t = buoyancyTransform(0, 0)
    expect(t.dx).toBe(0)
    expect(t.dy).toBe(0.9) // cos(0) × 1.5 × 0.6
    expect(t.scale).toBeCloseTo(1.003, 10)
  })
})

describe('dynamism — the refraction twin offset (spec §2.3)', () => {
  it('never exceeds 2px across or 1.2px down at any sampled phase', () => {
    for (let s = 0; s < 720; s++) {
      const phase = (s / 720) * Math.PI * 4
      const o = twinOffset(phase)
      expect(Math.abs(o.dx)).toBeLessThanOrEqual(2)
      expect(Math.abs(o.dy)).toBeLessThanOrEqual(1.2)
    }
    expect(twinOffset(0)).toEqual({ dx: 0, dy: 1.2 })
  })
})

describe('dynamism — the still comparison (spec §2.1 perceptual gate)', () => {
  it('reads ?still=1 and nothing else', () => {
    expect(stillComparisonIn('?still=1')).toBe(true)
    expect(stillComparisonIn('?foo=2&still=1')).toBe(true)
    expect(stillComparisonIn('?still=0')).toBe(false)
    expect(stillComparisonIn('?still=true')).toBe(false)
    expect(stillComparisonIn('')).toBe(false)
    expect(stillComparisonIn('?')).toBe(false)
  })
})
