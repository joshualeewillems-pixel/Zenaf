/**
 * Palace Scene 2 — placement-law invariants, nested in the dome
 * shell. The study builder verifies by rendering; these pin the
 * law itself as tests: the cavity asset's decoded area (verified
 * against the record before use — the #453 lesson), containment
 * (every placed circle's centre has cavity-EDT ≥ its radius, so
 * the whole circle stands inside the cavity), separation incl.
 * the hearth, share monotonicity, the area-share rule, and
 * determinism — on the shapes the Palace must actually stand,
 * the founder's live building first.
 */
import { describe, it, expect } from 'vitest'
import {
  FILL_LADDER,
  FILLER_HEARTH_MARGIN,
  FILLER_WALL_MARGIN,
  FLOOR_GAP,
  HEARTH,
  HEARTH_CLEARANCE,
  HEARTH_R,
  MIN_FLOOR_RADIUS,
  cavityEdtAt,
  cavityUsableArea,
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
    expect(cavityEdtAt(p.x, p.y), `${p.key} crosses the shell's frame`).toBeGreaterThanOrEqual(p.r - EPS)
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

describe('Palace Scene 2 — the Apollonian building law, nested in the shell', () => {
  it('the cavity asset decodes to its recorded usable area', () => {
    // Verified before use (the #453 lesson): the RLE shipped in
    // palace-cavity.json decodes to exactly the 543,190 px the
    // derivation recorded.
    expect(cavityUsableArea()).toBe(543190)
  })

  it.each(SHAPES)('containment and separation hold: %s', (_name, shape) => {
    const layout = planBuildingScene(shape)
    expect(layout.floors).toHaveLength(shape.length)
    expectLawful(layout.floors, layout.hearth)
  })

  it.each(SHAPES)('determinism: %s plans identically twice', (_name, shape) => {
    expect(planBuildingScene(shape)).toEqual(planBuildingScene(shape))
  })

  it('the live building packs whole — all eight floors placed', () => {
    const layout = planBuildingScene(LIVE_SHAPE)
    expect(layout.floors).toHaveLength(LIVE_SHAPE.length)
    expect(layout.fillUsed).toBeLessThanOrEqual(FILL_LADDER[0])
  })

  it('area is the percentage share of the filled cavity: radius² tracks rooms', () => {
    const layout = planBuildingScene(LIVE_SHAPE)
    const total = LIVE_SHAPE.reduce((s, f) => s + f.roomCount, 0)
    for (const p of layout.floors) {
      const expected = Math.sqrt(((p.roomCount / total) * layout.fillUsed * cavityUsableArea()) / Math.PI)
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
    expect(layout.floors[0].r).toBeCloseTo(
      Math.sqrt((layout.fillUsed * cavityUsableArea()) / Math.PI),
      6,
    )
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

  it('the hearth stands at the recorded place, on the shell’s floor', () => {
    const layout = planBuildingScene(LIVE_SHAPE)
    expect(layout.hearth).toEqual({ x: HEARTH.x, y: HEARTH.y, r: HEARTH_R })
    expect(layout.hearth).toEqual({ x: 627, y: 1022, r: 62 })
  })

  it('filler closes the gaps: contained, separated, descending, clear of the hearth', () => {
    const layout = planBuildingScene(LIVE_SHAPE)
    expect(layout.fillers.length).toBeGreaterThan(40)
    const all = [...layout.floors, ...layout.fillers]
    for (const c of layout.fillers) {
      expect(cavityEdtAt(c.x, c.y)).toBeGreaterThanOrEqual(c.r + FILLER_WALL_MARGIN - EPS)
      const dh = Math.hypot(c.x - layout.hearth.x, c.y - layout.hearth.y)
      expect(dh).toBeGreaterThanOrEqual(c.r + HEARTH_R + FILLER_HEARTH_MARGIN - EPS)
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

  it('an empty building plans as the empty cavity and the hearth alone', () => {
    const layout = planBuildingScene([])
    expect(layout.floors).toEqual([])
    expect(layout.fillers).toEqual([])
    expect(layout.hearth).toEqual({ x: 627, y: 1022, r: 62 })
  })
})
