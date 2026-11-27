/**
 * Palace Scene 2 — the relaxed Apollonian spacing as tests.
 * The founder's rulings (2026-11-26) are the contract: the
 * container asset's decoded area (verified against the record
 * before use — the #453 lesson), relative scaling (radius²
 * tracks the data share under one common fill), containment
 * (every rim sample inside the space), separation under the
 * one relaxed gap, the anchor (the largest floor anchors the
 * composition near the dome's centre), NO gravity (nothing
 * needs the floor; the big rooms are distributed, never pooled
 * at the bottom), and determinism — on the shapes the Palace
 * must actually stand, the founder's live building first. The
 * live building's seats are pinned exactly: they are study
 * v21's seats, the composition the founder approved
 * (build_study_v21_apollonian.py).
 *
 * Two families of shapes: those the spacing seats whole on
 * the fill ladder, and those whose pockets only open at the
 * lowest fill with the whole set scaled down together (the
 * documented fallback — proportions unchanged, every floor
 * still placed, contained, separated).
 */
import { describe, it, expect } from 'vitest'
import {
  ANCHOR,
  CIRCLE_GAP,
  CLEARANCE_TOLERANCE,
  FILL_BOTTOM,
  FILL_LADDER,
  FILL_TOP,
  HEARTH,
  HEARTH_R,
  MIN_FLOOR_RADIUS,
  RIM_SAMPLES,
  containerArea,
  containerEdtAt,
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

const LADDER_SHAPES: [string, Scene2FloorInput[]][] = [
  ['the live building', LIVE_SHAPE],
  [
    'many floors',
    Array.from({ length: 16 }, (_, i) => floor(`f${i}`, (i * 7) % 13)),
  ],
  ['one floor', [floor('only', 12)]],
  ['one floor, no rooms', [floor('only', 0)]],
]

const FALLBACK_SHAPES: [string, Scene2FloorInput[]][] = [
  ['equal floors', [floor('a', 4), floor('b', 4), floor('c', 4), floor('d', 4)]],
  ['no rooms anywhere', [floor('a', 0), floor('b', 0), floor('c', 0)]],
  ['a dominant floor', [floor('a', 3), floor('b', 9)]],
  ['a zero-room floor among rooms', [floor('a', 10), floor('b', 0), floor('c', 6)]],
]

const ALL_SHAPES = [...LADDER_SHAPES, ...FALLBACK_SHAPES]

function expectContainedAndSeparated(placed: PlacedFloor[]) {
  for (const p of placed) {
    for (let k = 0; k < RIM_SAMPLES; k++) {
      const a = (2 * Math.PI * k) / RIM_SAMPLES
      expect(
        containerEdtAt(p.x + p.r * Math.cos(a), p.y + p.r * Math.sin(a)),
        `${p.key} crosses the dome's frame`,
      ).toBeGreaterThan(0)
    }
    // the hearth's clearance is the full gap, strict (the
    // study's reading — no tolerance at the ring)
    const dh = Math.hypot(p.x - HEARTH.x, p.y - HEARTH.y)
    expect(dh, `${p.key} crowds the hearth`).toBeGreaterThanOrEqual(
      p.r + HEARTH_R + CIRCLE_GAP - EPS,
    )
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

/** Radius² tracks the data share under one common fill — the
 *  relative-scaling identity, checked against a layout's own
 *  fill and (for the fallback) its one common scale. */
function shareRadius(share: number, fill: number): number {
  return Math.max(Math.sqrt((share * fill * containerArea()) / Math.PI), MIN_FLOOR_RADIUS)
}

describe('Palace Scene 2 — the relaxed Apollonian spacing, nested in the dome', () => {
  it('the container asset decodes to its recorded area', () => {
    // Verified before use (the #453 lesson): the RLE shipped in
    // palace-container.json decodes to exactly the 697,884 px
    // the derivation recorded (cavity ∪ floor).
    expect(containerArea()).toBe(697884)
  })

  it.each(ALL_SHAPES)('every floor placed, contained, separated: %s', (_name, shape) => {
    const layout = planBuildingScene(shape)
    expect(layout.floors).toHaveLength(shape.length)
    expectContainedAndSeparated(layout.floors)
  })

  it.each(ALL_SHAPES)('determinism: %s plans identically twice', (_name, shape) => {
    expect(planBuildingScene(shape)).toEqual(planBuildingScene(shape))
  })

  it.each(ALL_SHAPES)('rooms only: %s — no filler rides the layout', (_name, shape) => {
    const layout = planBuildingScene(shape)
    expect('fillers' in layout).toBe(false)
    expect(layout.floors).toHaveLength(shape.length)
  })

  it.each(LADDER_SHAPES)('the ladder seats it whole at a ladder fill: %s', (_name, shape) => {
    const layout = planBuildingScene(shape)
    expect(FILL_LADDER).toContain(layout.fillUsed)
    // radii are the share formula at that fill, exactly — one
    // common fill, proportions pure
    for (const p of layout.floors) {
      expect(p.r, p.key).toBeCloseTo(shareRadius(p.share, layout.fillUsed), 6)
    }
  })

  it.each(FALLBACK_SHAPES)('the hard shapes take the documented fallback: %s', (_name, shape) => {
    // The pockets only open at the lowest fill with the whole
    // set scaled down together — one common scale (a power of
    // 0.9), so proportions never change and no floor is dropped.
    const layout = planBuildingScene(shape)
    expect(layout.fillUsed).toBe(FILL_BOTTOM)
    expect(layout.floors).toHaveLength(shape.length)
    const largest = layout.floors[0]
    const scale = largest.r / shareRadius(largest.share, FILL_BOTTOM)
    expect(scale).toBeLessThanOrEqual(1 + EPS)
    for (const p of layout.floors) {
      expect(p.r, p.key).toBeCloseTo(shareRadius(p.share, FILL_BOTTOM) * scale, 6)
    }
  })

  it('the live building IS study v21 — the approved composition, seat for seat', () => {
    const layout = planBuildingScene(LIVE_SHAPE)
    expect(layout.fillUsed).toBe(0.48)
    // The study's seats (build_study_v21_apollonian.py printed
    // them rounded; the port reproduces them exactly — these
    // are its values): Tier 6 anchors the centre; the rest
    // nestle around it.
    const seats: Record<string, [number, number, number]> = {
      tier6: [627.0, 600.0, 175.9453],
      tier4: [333.48, 706.8325, 124.4121],
      tier0: [920.1443, 651.6892, 109.7212],
      tier2: [824.0734, 1023.2711, 109.7212],
      tier1: [527.9758, 872.0668, 101.5821],
      tier3: [861.3049, 445.4665, 92.7313],
      tier5: [411.9892, 419.5845, 92.7313],
      seven: [584.0131, 322.6347, 92.7313],
    }
    expect(layout.floors).toHaveLength(8)
    for (const p of layout.floors) {
      const [x, y, r] = seats[p.key]
      expect(p.x, `${p.key} x`).toBeCloseTo(x, 2)
      expect(p.y, `${p.key} y`).toBeCloseTo(y, 2)
      expect(p.r, `${p.key} r`).toBeCloseTo(r, 2)
    }
  })

  it('the anchor: the largest floor anchors the composition near the dome’s centre', () => {
    for (const [, shape] of LADDER_SHAPES) {
      const layout = planBuildingScene(shape)
      const largest = layout.floors[0]
      expect(Math.abs(largest.x - ANCHOR.x), largest.key).toBeLessThanOrEqual(60)
      expect(largest.y, largest.key).toBeGreaterThanOrEqual(ANCHOR.y - 40)
      expect(largest.y, largest.key).toBeLessThanOrEqual(ANCHOR.y + 60)
    }
    // the live building's anchor is exact: Tier 6 at the centre
    const live = planBuildingScene(LIVE_SHAPE)
    expect(live.floors[0].key).toBe('tier6')
    expect(live.floors[0].x).toBe(ANCHOR.x)
    expect(live.floors[0].y).toBe(ANCHOR.y)
  })

  it('no gravity: the largest room floats at the centre, and the sizes are distributed', () => {
    const layout = planBuildingScene(LIVE_SHAPE)
    const largest = layout.floors[0]
    // Tier 6's base is far above the floor — nothing holds it
    // up and nothing needs to (the retired law's ground contact
    // is gone): its bottom does not come near the hearth's row.
    expect(largest.y + largest.r).toBeLessThan(HEARTH.y - 200)
    // the composition spans the dome — crown to floor — and the
    // big rooms are not pooled at the bottom: none of the three
    // largest centres sits in the dome's bottom quarter.
    const tops = Math.min(...layout.floors.map((p) => p.y - p.r))
    const bottoms = Math.max(...layout.floors.map((p) => p.y + p.r))
    expect(tops).toBeLessThan(250)
    expect(bottoms).toBeGreaterThan(1050)
    for (const p of layout.floors.slice(0, 3)) {
      expect(p.y, p.key).toBeLessThan(940)
    }
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
    // pinned on a ladder shape (the 16-floor building): its two
    // zero-room floors stand at exactly the minimum radius
    const layout = planBuildingScene(LADDER_SHAPES[1][1])
    const empties = layout.floors.filter((f) => f.roomCount === 0)
    expect(empties).toHaveLength(2)
    for (const e of empties) expect(e.r).toBe(MIN_FLOOR_RADIUS)
  })

  it('no rooms anywhere: shares are equal, and so are the circles', () => {
    const layout = planBuildingScene([floor('a', 0), floor('b', 0), floor('c', 0), floor('d', 0)])
    for (const f of layout.floors) expect(f.share).toBeCloseTo(0.25, 9)
    const radii = layout.floors.map((f) => f.r)
    for (const r of radii) expect(r).toBeCloseTo(radii[0], 6)
  })

  it('the hearth stands at the architecture dome’s own ring', () => {
    const layout = planBuildingScene(LIVE_SHAPE)
    expect(layout.hearth).toEqual({ x: HEARTH.x, y: HEARTH.y, r: HEARTH_R })
    expect(layout.hearth).toEqual({ x: 627, y: 1095, r: 88 })
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
    expect(layout.hearth).toEqual({ x: 627, y: 1095, r: 88 })
    expect(layout.fillUsed).toBe(FILL_TOP)
  })
})
