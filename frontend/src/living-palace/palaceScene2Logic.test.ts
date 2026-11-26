/**
 * Palace Scene 2 — placement-law invariants. The study builder
 * verifies by rendering; these pin the law itself as tests:
 * containment (every floor circle inside the great circle, clear
 * of the hearth), separation, share monotonicity (more rooms → not
 * smaller), the area-share rule, and determinism — on the shapes
 * the Palace must actually stand, the founder's live building
 * first.
 */
import { describe, it, expect } from 'vitest'
import {
  FILL_LADDER,
  FLOOR_GAP,
  GREAT_CIRCLE_R,
  HEARTH_CLEARANCE,
  HEARTH_R,
  MIN_FLOOR_RADIUS,
  SCENE2_CENTER,
  WALL_CLEARANCE,
  planBuildingScene,
  type PlacedFloor,
  type Scene2FloorInput,
} from './palaceScene2Logic'

const EPS = 1e-6

function floor(key: string, roomCount: number): Scene2FloorInput {
  return { key, roomCount }
}

/** The founder's live building — Zenaf build directions: eight
 *  floors, rooms 7/6/7/5/9/5/18/5 (his 2026-11-26 screenshot). */
const LIVE_SHAPE: Scene2FloorInput[] = [
  floor('tier0', 7),
  floor('tier1', 6),
  floor('tier2', 7),
  floor('tier3', 5),
  floor('tier4', 9),
  floor('tier5', 5),
  floor('tier6', 18),
  floor('seven', 5),
]

const SHAPES: [string, Scene2FloorInput[]][] = [
  ['the live building', LIVE_SHAPE],
  ['one floor', [floor('only', 12)]],
  ['one floor, no rooms', [floor('only', 0)]],
  ['two floors', [floor('a', 3), floor('b', 9)]],
  ['equal floors', [floor('a', 4), floor('b', 4), floor('c', 4), floor('d', 4)]],
  ['a zero-room floor among rooms', [floor('a', 10), floor('b', 0), floor('c', 6)]],
  ['no rooms anywhere', [floor('a', 0), floor('b', 0), floor('c', 0)]],
  ['many floors', Array.from({ length: 16 }, (_, i) => floor(`f${i}`, (i * 7) % 13))],
]

function expectLawful(placed: PlacedFloor[], hearth: { x: number; y: number; r: number }) {
  for (const p of placed) {
    const dc = Math.hypot(p.x - SCENE2_CENTER, p.y - SCENE2_CENTER)
    expect(dc + p.r, `${p.key} leaves the great circle`).toBeLessThanOrEqual(
      GREAT_CIRCLE_R - WALL_CLEARANCE + EPS,
    )
    const dh = Math.hypot(p.x - hearth.x, p.y - hearth.y)
    expect(dh, `${p.key} overlaps the hearth`).toBeGreaterThanOrEqual(p.r + HEARTH_R + HEARTH_CLEARANCE - EPS)
  }
  for (let i = 0; i < placed.length; i++) {
    for (let j = i + 1; j < placed.length; j++) {
      const a = placed[i]
      const b = placed[j]
      const d = Math.hypot(a.x - b.x, a.y - b.y)
      expect(d, `${a.key} overlaps ${b.key}`).toBeGreaterThanOrEqual(a.r + b.r + FLOOR_GAP - EPS)
    }
  }
}

describe('Palace Scene 2 — the Apollonian building law', () => {
  it.each(SHAPES)('containment and separation hold: %s', (_name, shape) => {
    const layout = planBuildingScene(shape)
    expect(layout.floors).toHaveLength(shape.length)
    expectLawful(layout.floors, layout.hearth)
  })

  it.each(SHAPES)('determinism: %s plans identically twice', (_name, shape) => {
    expect(planBuildingScene(shape)).toEqual(planBuildingScene(shape))
  })

  it('the live building packs under the strict ladder, at its first rung', () => {
    const layout = planBuildingScene(LIVE_SHAPE)
    expect(layout.fillUsed).toBe(FILL_LADDER[0])
  })

  it('area is the percentage share: radius² tracks rooms', () => {
    const layout = planBuildingScene(LIVE_SHAPE)
    const total = LIVE_SHAPE.reduce((s, f) => s + f.roomCount, 0)
    for (const p of layout.floors) {
      const expected = GREAT_CIRCLE_R * Math.sqrt((p.roomCount / total) * layout.fillUsed)
      expect(p.r, p.key).toBeCloseTo(expected, 6)
      expect(p.share).toBeCloseTo(p.roomCount / total, 9)
    }
  })

  it('room plates cycle rose → spiral → tiers by size rank', () => {
    const layout = planBuildingScene(LIVE_SHAPE)
    // layout.floors is in placement order = size rank, largest first:
    // tier6 (18) rose, tier4 (9) spiral, then the 7-room pair in
    // input order — tier0 tiers, tier2 rose — and so on down.
    expect(layout.floors.map((f) => [f.key, f.plate])).toEqual([
      ['tier6', 'rose'],
      ['tier4', 'spiral'],
      ['tier0', 'tiers'],
      ['tier2', 'rose'],
      ['tier1', 'spiral'],
      ['tier3', 'tiers'],
      ['tier5', 'rose'],
      ['seven', 'spiral'],
    ])
    // a single floor stands in the rose room
    expect(planBuildingScene([floor('only', 3)]).floors[0].plate).toBe('rose')
  })

  it('share monotonicity: more rooms never means a smaller circle', () => {
    for (const [, shape] of SHAPES) {
      const layout = planBuildingScene(shape)
      const byRooms = [...layout.floors].sort((a, b) => a.roomCount - b.roomCount)
      for (let i = 1; i < byRooms.length; i++) {
        expect(byRooms[i].r, `${byRooms[i].key} vs ${byRooms[i - 1].key}`).toBeGreaterThanOrEqual(
          byRooms[i - 1].r - EPS,
        )
      }
    }
  })

  it('one floor is one large circle', () => {
    const layout = planBuildingScene([floor('only', 12)])
    expect(layout.floors).toHaveLength(1)
    expect(layout.floors[0].r).toBeCloseTo(GREAT_CIRCLE_R * Math.sqrt(FILL_LADDER[0]), 6)
  })

  it('a zero-room floor still gets the minimum tappable circle', () => {
    const layout = planBuildingScene([floor('a', 10), floor('b', 0)])
    const empty = layout.floors.find((f) => f.key === 'b')!
    expect(empty.r).toBe(MIN_FLOOR_RADIUS)
  })

  it('no rooms anywhere: shares are equal', () => {
    const layout = planBuildingScene([floor('a', 0), floor('b', 0), floor('c', 0), floor('d', 0)])
    const radii = layout.floors.map((f) => f.r)
    for (const r of radii) expect(r).toBeCloseTo(radii[0], 9)
    for (const f of layout.floors) expect(f.share).toBeCloseTo(0.25, 9)
  })

  it('the hearth stands at the bottom centre, tangent to the rim', () => {
    const layout = planBuildingScene(LIVE_SHAPE)
    expect(layout.hearth.x).toBe(SCENE2_CENTER)
    expect(layout.hearth.r).toBe(HEARTH_R)
    const dc = Math.hypot(layout.hearth.x - SCENE2_CENTER, layout.hearth.y - SCENE2_CENTER)
    expect(dc + layout.hearth.r).toBeLessThanOrEqual(GREAT_CIRCLE_R)
    expect(layout.hearth.y).toBeGreaterThan(SCENE2_CENTER)
  })

  it('filler closes the gaps: contained, separated, descending, clear of the hearth', () => {
    const layout = planBuildingScene(LIVE_SHAPE)
    expect(layout.fillers.length).toBeGreaterThan(40)
    const all = [...layout.floors, ...layout.fillers]
    for (const c of layout.fillers) {
      const dc = Math.hypot(c.x - SCENE2_CENTER, c.y - SCENE2_CENTER)
      expect(dc + c.r).toBeLessThanOrEqual(GREAT_CIRCLE_R - 3 + EPS)
      const dh = Math.hypot(c.x - layout.hearth.x, c.y - layout.hearth.y)
      expect(dh).toBeGreaterThanOrEqual(c.r + HEARTH_R + 3 - EPS)
    }
    for (let i = 0; i < all.length; i++) {
      for (let j = i + 1; j < all.length; j++) {
        const d = Math.hypot(all[i].x - all[j].x, all[i].y - all[j].y)
        expect(d).toBeGreaterThanOrEqual(all[i].r + all[j].r + FLOOR_GAP - EPS)
      }
    }
    const radii = layout.fillers.map((f) => f.r)
    for (let i = 1; i < radii.length; i++) {
      expect(radii[i]).toBeLessThanOrEqual(radii[i - 1])
    }
  })

  it('an empty building plans as the empty circle and the hearth alone', () => {
    const layout = planBuildingScene([])
    expect(layout.floors).toEqual([])
    expect(layout.fillers).toEqual([])
    expect(layout.hearth.r).toBe(HEARTH_R)
  })
})
