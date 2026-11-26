/**
 * Palace Scene 2 — the packing rules as tests. The founder's
 * rules (2026-11-26) are the contract: the container asset's
 * decoded area (verified against the record before use — the
 * #453 lesson), relative scaling (radius² tracks the data share
 * under one common fill), containment (every rim sample inside
 * the space), separation under the one gap, gravity (every
 * circle in contact and supported; a largest circle standing on
 * the ground), and determinism — on the shapes the Palace must
 * actually stand, the founder's live building first.
 *
 * Two families of shapes: those the law can satisfy whole, and
 * those where one floor so dominates that it cannot stand on
 * the ground beside the hearth at any fill (a single floor; a
 * 75%-of-rooms floor) — those take the documented fallback
 * (lowest fill, every floor still placed, contained, separated,
 * in contact) and are pinned as such, not as valid layouts.
 */
import { describe, it, expect } from 'vitest'
import {
  CIRCLE_GAP,
  CLEARANCE_TOLERANCE,
  CONTACT_TOLERANCE,
  FILL_BOTTOM,
  FILL_TOP,
  HEARTH,
  HEARTH_R,
  MIN_FLOOR_RADIUS,
  RIM_SAMPLES,
  SUPPORT_TOLERANCE,
  WALL_GRAZE,
  containerArea,
  containerEdtAt,
  groundYAt,
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

const VALID_SHAPES: [string, Scene2FloorInput[]][] = [
  ['the live building', LIVE_SHAPE],
  ['equal floors', [floor('a', 4), floor('b', 4), floor('c', 4), floor('d', 4)]],
  ['no rooms anywhere', [floor('a', 0), floor('b', 0), floor('c', 0)]],
  [
    'many floors',
    Array.from({ length: 16 }, (_, i) => floor(`f${i}`, (i * 7) % 13)),
  ],
]

const FALLBACK_SHAPES: [string, Scene2FloorInput[]][] = [
  ['one floor', [floor('only', 12)]],
  ['one floor, no rooms', [floor('only', 0)]],
  ['a dominant floor', [floor('a', 3), floor('b', 9)]],
  ['a zero-room floor among rooms', [floor('a', 10), floor('b', 0), floor('c', 6)]],
]

const ALL_SHAPES = [...VALID_SHAPES, ...FALLBACK_SHAPES]

/* The law's own checks, restated over the exported primitives —
 * the same reading the module's validity gate applies. */

function groundContact(p: PlacedFloor, tolerance: number): boolean {
  const gy = groundYAt(p.x)
  return gy !== null && Math.abs(p.y + p.r - gy) <= tolerance
}

function inContact(p: PlacedFloor, all: PlacedFloor[]): boolean {
  if (groundContact(p, CONTACT_TOLERANCE)) return true
  if (Math.abs(Math.hypot(p.x - HEARTH.x, p.y - HEARTH.y) - (p.r + HEARTH_R + CIRCLE_GAP)) <= CONTACT_TOLERANCE) {
    return true
  }
  for (const q of all) {
    if (q === p) continue
    if (Math.abs(Math.hypot(p.x - q.x, p.y - q.y) - (p.r + q.r + CIRCLE_GAP)) <= CONTACT_TOLERANCE) {
      return true
    }
  }
  for (let k = 0; k < RIM_SAMPLES; k++) {
    const a = (2 * Math.PI * k) / RIM_SAMPLES
    if (containerEdtAt(p.x + p.r * Math.cos(a), p.y + p.r * Math.sin(a)) <= WALL_GRAZE) return true
  }
  return false
}

function isSupported(p: PlacedFloor, all: PlacedFloor[]): boolean {
  if (groundContact(p, SUPPORT_TOLERANCE)) return true
  return all.some(
    (q) =>
      q !== p &&
      q.y > p.y &&
      Math.abs(Math.hypot(p.x - q.x, p.y - q.y) - (p.r + q.r + CIRCLE_GAP)) <= SUPPORT_TOLERANCE,
  )
}

function expectContainedAndSeparated(placed: PlacedFloor[]) {
  for (const p of placed) {
    for (let k = 0; k < RIM_SAMPLES; k++) {
      const a = (2 * Math.PI * k) / RIM_SAMPLES
      expect(
        containerEdtAt(p.x + p.r * Math.cos(a), p.y + p.r * Math.sin(a)),
        `${p.key} crosses the shell's frame`,
      ).toBeGreaterThan(0)
    }
    const dh = Math.hypot(p.x - HEARTH.x, p.y - HEARTH.y)
    expect(dh, `${p.key} crowds the hearth`).toBeGreaterThanOrEqual(
      p.r + HEARTH_R + CIRCLE_GAP - CLEARANCE_TOLERANCE - EPS,
    )
    expect(inContact(p, placed), `${p.key} touches nothing`).toBe(true)
  }
  for (let i = 0; i < placed.length; i++) {
    for (let j = i + 1; j < placed.length; j++) {
      const a = placed[i]
      const b = placed[j]
      const d = Math.hypot(a.x - b.x, a.y - b.y)
      expect(d, `${a.key} overlaps ${b.key}`).toBeGreaterThanOrEqual(
        a.r + b.r + CIRCLE_GAP - CLEARANCE_TOLERANCE - EPS,
      )
    }
  }
}

function expectValid(placed: PlacedFloor[]) {
  for (const p of placed) {
    expect(isSupported(p, placed), `${p.key} is not held up`).toBe(true)
  }
  const maxR = Math.max(...placed.map((p) => p.r))
  const largestStands = placed.some(
    (p) => Math.abs(p.r - maxR) <= 1e-9 && groundContact(p, SUPPORT_TOLERANCE),
  )
  expect(largestStands, 'a largest circle stands on the ground').toBe(true)
}

describe('Palace Scene 2 — the packing rules, nested in the shell', () => {
  it('the container asset decodes to its recorded area', () => {
    // Verified before use (the #453 lesson): the RLE shipped in
    // palace-container.json decodes to exactly the 697,884 px
    // the derivation recorded (cavity ∪ floor).
    expect(containerArea()).toBe(697884)
  })

  it.each(ALL_SHAPES)('every floor placed, contained, separated, in contact: %s', (_name, shape) => {
    const layout = planBuildingScene(shape)
    expect(layout.floors).toHaveLength(shape.length)
    expectContainedAndSeparated(layout.floors)
  })

  it.each(VALID_SHAPES)('gravity holds — supported, a largest on the ground: %s', (_name, shape) => {
    expectValid(planBuildingScene(shape).floors)
  })

  it.each(FALLBACK_SHAPES)('the dominant shapes take the documented fallback: %s', (_name, shape) => {
    // One floor so dominates that it cannot stand on the ground
    // beside the hearth at any fill; the plan falls back to the
    // lowest fill rather than dropping a floor.
    const layout = planBuildingScene(shape)
    expect(layout.fillUsed).toBe(FILL_BOTTOM)
    expect(layout.floors).toHaveLength(shape.length)
  })

  it.each(ALL_SHAPES)('determinism: %s plans identically twice', (_name, shape) => {
    expect(planBuildingScene(shape)).toEqual(planBuildingScene(shape))
  })

  it.each(ALL_SHAPES)('rooms only: %s — no filler rides the layout', (_name, shape) => {
    const layout = planBuildingScene(shape)
    expect('fillers' in layout).toBe(false)
    expect(layout.floors).toHaveLength(shape.length)
  })

  it('the live building packs whole, near the studies’ fill', () => {
    const layout = planBuildingScene(LIVE_SHAPE)
    expect(layout.floors).toHaveLength(LIVE_SHAPE.length)
    expect(layout.fillUsed).toBeGreaterThanOrEqual(0.5)
    expect(layout.fillUsed).toBeLessThanOrEqual(FILL_TOP)
  })

  it('the live building: the two largest stand on the floor flanking the hearth', () => {
    const layout = planBuildingScene(LIVE_SHAPE)
    const [largest, second] = layout.floors
    expect(largest.key).toBe('tier6')
    expect(second.key).toBe('tier4')
    expect(groundContact(largest, SUPPORT_TOLERANCE)).toBe(true)
    expect(groundContact(second, SUPPORT_TOLERANCE)).toBe(true)
    expect(largest.x).toBeLessThan(HEARTH.x)
    expect(second.x).toBeGreaterThan(HEARTH.x)
  })

  it('relative scaling: radius² tracks the data share under one common fill', () => {
    const layout = planBuildingScene(LIVE_SHAPE)
    const total = LIVE_SHAPE.reduce((s, f) => s + f.roomCount, 0)
    for (const p of layout.floors) {
      const expected = Math.sqrt(((p.roomCount / total) * layout.fillUsed * containerArea()) / Math.PI)
      expect(p.r, p.key).toBeCloseTo(expected, 6)
      expect(p.share).toBeCloseTo(p.roomCount / total, 9)
    }
    // and pairwise: the ratio of two radii is the square root of
    // the ratio of their shares — proportions never change.
    const [a, b] = [layout.floors[0], layout.floors[2]]
    expect(a.r / b.r).toBeCloseTo(Math.sqrt(a.share / b.share), 9)
  })

  it('room plates cycle rose → spiral → tiers by size rank', () => {
    const layout = planBuildingScene(LIVE_SHAPE)
    // layout.floors is in size-rank order: tier6 (18) rose,
    // tier4 (9) spiral, then the 7-room pair in input order —
    // tier0 tiers, tier2 rose — and so on down.
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
    for (const [, shape] of ALL_SHAPES) {
      const layout = planBuildingScene(shape)
      const byRooms = [...layout.floors].sort((a, b) => a.roomCount - b.roomCount)
      for (let i = 1; i < byRooms.length; i++) {
        expect(byRooms[i].r, `${byRooms[i].key} vs ${byRooms[i - 1].key}`).toBeGreaterThanOrEqual(
          byRooms[i - 1].r - EPS,
        )
      }
    }
  })

  it('one floor is one large circle, sized by the fill it settled at', () => {
    const layout = planBuildingScene([floor('only', 12)])
    expect(layout.floors).toHaveLength(1)
    expect(layout.floors[0].r).toBeCloseTo(Math.sqrt((layout.fillUsed * containerArea()) / Math.PI), 6)
  })

  it('a zero-room floor still gets the minimum tappable circle', () => {
    const layout = planBuildingScene([floor('a', 10), floor('b', 0), floor('c', 6)])
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

  it('the live building plans fast — the search stays bounded', () => {
    planBuildingScene(LIVE_SHAPE) // warm the container load
    const t0 = performance.now()
    planBuildingScene(LIVE_SHAPE)
    expect(performance.now() - t0).toBeLessThan(1000)
  })

  it('an empty building plans as the empty space and the hearth alone', () => {
    const layout = planBuildingScene([])
    expect(layout.floors).toEqual([])
    expect(layout.hearth).toEqual({ x: 627, y: 1022, r: 62 })
    expect(layout.fillUsed).toBe(FILL_TOP)
  })
})
