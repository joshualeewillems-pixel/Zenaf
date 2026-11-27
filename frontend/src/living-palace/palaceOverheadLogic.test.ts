/**
 * The overhead packing law — the ported acceptance suite.
 *
 * The adaptive-density study and its contraction correction
 * become the tests (port proposal v2, "Tests that port with it"):
 * cold snapshots at 3/6/9/12/20/30, the seeded chain
 * 3 -> 6 -> 9 -> 12 -> 20 -> 30 -> 12, determinism, and the
 * unplaced diagnostic. Expected values are the studies' own
 * recorded numbers:
 * - snapshots: adaptive-results.json, method B_search (the cold
 *   search the hybrid shares), in
 *   ~/workspace/rendering-test-assets/maeve-palace-study/scene-2/overhead/
 * - chain: hybrid2-results.json (the contraction-corrected
 *   hybrid, C2), same directory.
 *
 * The fixture is the studies' own: t01..t30 with the standing
 * weight sequence of palace_adaptive.py.
 *
 * Tolerance note: the governing quantities — rung, step-downs,
 * scale, occupancy, moved-room counts, integrity — are asserted
 * tight against the study. The movement MEAN is asserted within
 * 25 plan units (a quarter of the floor's radius): a
 * cross-language port hits knife-edge ties in the repair search
 * (two lawful seats a rounding bucket apart), and one flipped
 * repair cascades through a dense step's distances while every
 * governing quantity still lands on the study's values. The
 * band keeps the study's behavioural distinction — barely-moved
 * steps (means 2.0, 4.4) versus long-move reorganizations
 * (means 68-118) — which the port reproduces at every step.
 * The port's own determinism is asserted exactly (same input ->
 * identical layout, byte for byte).
 */
import { describe, expect, it } from 'vitest'
import {
  PROVEN_INFEASIBLE,
  SEARCH_EXHAUSTION,
  overheadOccupancy,
  placeOverheadRooms,
  planOverheadLayout,
  searchOverheadScale,
  type OverheadRoomInput,
  type PalaceLayoutRecord,
} from './palaceOverheadLogic'

const SEQ = [
  10, 8, 7, 6, 6, 5, 5, 4, 4, 3, 3, 2, // t01..t12
  4, 3, 5, 2, 6, 3, 2, 4, // t13..t20
  4, 3, 5, 2, 6, 3, 2, 4, 3, 2, // t21..t30
]
const IDS = SEQ.map((_, i) => `t${String(i + 1).padStart(2, '0')}`)

function rooms(n: number): OverheadRoomInput[] {
  return IDS.slice(0, n).map((id, i) => ({ id, weight: SEQ[i] }))
}

function violationsOf(lay: ReturnType<typeof placeOverheadRooms>): number {
  const v = lay.validation
  return v.boundaryViolations.length + v.overlaps.length + v.hearthViolations.length
}

function movementStats(
  before: Record<string, [number, number]>,
  after: Record<string, [number, number]>,
): { moved: number; mean: number } {
  const vals: number[] = []
  for (const rid of Object.keys(before)) {
    if (rid in after) {
      const d = Math.hypot(after[rid][0] - before[rid][0], after[rid][1] - before[rid][1])
      if (d > 1e-6) vals.push(d)
    }
  }
  return {
    moved: vals.length,
    mean: vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0,
  }
}

/* Cold snapshots — adaptive-results.json, B_search. */
const SNAPSHOTS: { n: number; scale: number; occupancy: number }[] = [
  { n: 3, scale: 13.7243, occupancy: 0.471 },
  { n: 6, scale: 12.2035, occupancy: 0.625 },
  { n: 9, scale: 10.1581, occupancy: 0.568 },
  { n: 12, scale: 10.1345, occupancy: 0.647 },
  { n: 20, scale: 7.9935, occupancy: 0.588 },
  { n: 30, scale: 6.8977, occupancy: 0.599 },
]

describe('overhead packing — cold snapshots (the adaptive study)', () => {
  for (const snap of SNAPSHOTS) {
    it(
      `seats all ${snap.n} rooms cold at the study's scale and occupancy`,
      () => {
        const rm = rooms(snap.n)
        const s = searchOverheadScale(rm)
        expect(s).toBeCloseTo(snap.scale, 1)
        const lay = placeOverheadRooms(rm, {}, s)
        expect(lay.unplaced).toEqual([])
        expect(lay.placedCount).toBe(snap.n)
        expect(violationsOf(lay)).toBe(0)
        expect(lay.validation.conserved).toBe(true)
        expect(overheadOccupancy(lay.radii)).toBeCloseTo(snap.occupancy, 2)
      },
      120_000,
    )
  }
})

/* The seeded chain — hybrid2-results.json (C2). */
const CHAIN: {
  n: number
  rung: string
  steppedDown: number
  scale: number
  occupancy: number
  moved?: number
  movementMean?: number
}[] = [
  { n: 3, rung: 'cold', steppedDown: 0, scale: 13.7243, occupancy: 0.471 },
  { n: 6, rung: 'seeded-large', steppedDown: 2, scale: 12.1072, occupancy: 0.616, moved: 2, movementMean: 4.43 },
  { n: 9, rung: 'cold', steppedDown: 2, scale: 9.9315, occupancy: 0.542, moved: 6, movementMean: 118.13 },
  { n: 12, rung: 'seeded', steppedDown: 0, scale: 10.0851, occupancy: 0.641, moved: 1, movementMean: 2.0 },
  { n: 20, rung: 'seeded-large', steppedDown: 3, scale: 7.9499, occupancy: 0.581, moved: 6, movementMean: 79.68 },
  { n: 30, rung: 'cold', steppedDown: 0, scale: 7.0126, occupancy: 0.62, moved: 20, movementMean: 87.81 },
  { n: 12, rung: 'seeded-anchor', steppedDown: 0, scale: 10.1345, occupancy: 0.647, moved: 12, movementMean: 67.73 },
]

function runChain(): { record: PalaceLayoutRecord; rung: string }[] {
  const out: { record: PalaceLayoutRecord; rung: string }[] = []
  let stored: PalaceLayoutRecord | null = null
  for (const step of CHAIN) {
    const result = planOverheadLayout(rooms(step.n), new Map(), stored)
    out.push({ record: result.record, rung: result.rung })
    stored = result.record
  }
  return out
}

describe('overhead packing — the seeded chain (hybrid v2, contraction-corrected)', () => {
  it(
    'walks 3 -> 6 -> 9 -> 12 -> 20 -> 30 -> 12 on the study\'s rungs, scales and occupancies',
    () => {
      let stored: PalaceLayoutRecord | null = null
      let prevPositions: Record<string, [number, number]> = {}
      CHAIN.forEach((step, i) => {
        const result = planOverheadLayout(rooms(step.n), new Map(), stored)
        const rec = result.record
        expect(result.rung, `step ${i} (n=${step.n}) rung`).toBe(step.rung)
        expect(rec.lastTransition.steppedDown, `step ${i} stepped down`).toBe(step.steppedDown)
        expect(rec.lastTransition.reflow, `step ${i} reflow`).toBe(i > 0 && step.rung !== 'seeded')
        expect(rec.scale, `step ${i} scale`).toBeCloseTo(step.scale, 1)
        expect(rec.unplaced, `step ${i} unplaced`).toEqual([])
        const radii: Record<string, number> = {}
        for (const room of rooms(step.n)) radii[room.id] = Math.sqrt(room.weight) * rec.scale
        expect(overheadOccupancy(radii), `step ${i} occupancy`).toBeCloseTo(step.occupancy, 2)
        if (step.moved !== undefined) {
          const mv = movementStats(prevPositions, rec.positions)
          expect(mv.moved, `step ${i} moved rooms`).toBe(step.moved)
          expect(rec.lastTransition.movedRooms, `step ${i} recorded moved`).toBe(step.moved)
          expect(
            Math.abs(mv.mean - step.movementMean!),
            `step ${i} movement mean`,
          ).toBeLessThan(25)
        }
        prevPositions = rec.positions
        stored = rec
      })
    },
    300_000,
  )

  it(
    'is deterministic: the same chain run twice lands identically',
    () => {
      const a = runChain()
      const b = runChain()
      expect(JSON.stringify(a.map((s) => s.record))).toBe(JSON.stringify(b.map((s) => s.record)))
    },
    300_000,
  )

  it(
    'the contraction recovers the born-at-twelve density in the same operation',
    () => {
      const chain = runChain()
      const returned = chain[chain.length - 1].record
      const bornAt12 = SNAPSHOTS.find((s) => s.n === 12)!
      const radii: Record<string, number> = {}
      for (const room of rooms(12)) radii[room.id] = Math.sqrt(room.weight) * returned.scale
      expect(overheadOccupancy(radii)).toBeCloseTo(bornAt12.occupancy, 2)
    },
    300_000,
  )
})

describe('overhead packing — the standing composition and honest capacity', () => {
  it(
    'an unchanged collection stands verbatim: no transition, no rewrite',
    () => {
      const first = planOverheadLayout(rooms(12), new Map(), null)
      const second = planOverheadLayout(rooms(12), new Map(), first.record)
      expect(second.rung).toBe('standing')
      expect(second.changed).toBe(false)
      expect(second.record).toBe(first.record)
      expect(second.placed).toEqual(first.placed)
    },
    120_000,
  )

  it(
    'a room too large for the floor is reported, never resized or hidden',
    () => {
      // r = sqrt(3600) x 1 = 60: it cannot clear the hearth
      // (needs 73.2 from the centre) and stay contained (needs
      // <= 40) — a search exhaustion, named as such.
      const lay = placeOverheadRooms([{ id: 'huge', weight: 3600 }], {}, 1)
      expect(lay.placedCount).toBe(0)
      expect(lay.unplaced).toHaveLength(1)
      expect(lay.unplaced[0].id).toBe('huge')
      expect(lay.unplaced[0].cause).toBe(SEARCH_EXHAUSTION)
      expect(lay.unplaced[0].radius).toBeCloseTo(60, 3)
    },
    60_000,
  )

  it(
    'a request whose discs cannot fit is proven infeasible, by the area bound',
    () => {
      // Eight r = 42 discs (weight 1764 at scale 1): each seats
      // alone on the hearth's snug ring, but their
      // clearance-inflated area is 1.43x the floor's — the area
      // bound proves the whole request infeasible, so every
      // refusal carries PROVEN_INFEASIBLE, never a quiet shrink.
      const rm = Array.from({ length: 8 }, (_, i) => ({ id: `d${i}`, weight: 1764 }))
      const lay = placeOverheadRooms(rm, {}, 1)
      expect(lay.placedCount).toBeGreaterThanOrEqual(1)
      expect(lay.unplaced.length).toBeGreaterThanOrEqual(1)
      for (const u of lay.unplaced) expect(u.cause).toBe(PROVEN_INFEASIBLE)
      expect(lay.validation.conserved).toBe(true)
      expect(violationsOf(lay)).toBe(0)
    },
    60_000,
  )

  it(
    'relative sizes are exact: one common scale, square-root ratios',
    () => {
      const rm = rooms(12)
      const s = searchOverheadScale(rm)
      const lay = placeOverheadRooms(rm, {}, s)
      for (const room of rm) {
        expect(lay.radii[room.id]).toBeCloseTo(Math.sqrt(room.weight) * s, 5)
      }
    },
    120_000,
  )
})

/* The standing artifact rooms (founder addendum, 2026-11-27
 * 12:22 PT): fixtures like the hearth — always present, at the
 * compass points, cleared by the task packer, never counted. */
describe('overhead packing — the standing artifact rooms', () => {
  const EXPECTED_IDS = ['artifact:chest', 'artifact:scales', 'artifact:table', 'artifact:vessel']

  for (const n of [0, 3, 12, 30]) {
    it(
      `the four fixtures stand at the compass points with ${n} task rooms`,
      () => {
        const result = planOverheadLayout(rooms(n), new Map(), null, { fixtures: true })
        const s = result.record.scale
        expect(result.unplaced).toEqual([])
        expect(result.fixtures).toHaveLength(4)
        expect(result.fixtures.map((f) => f.id).sort()).toEqual(EXPECTED_IDS)
        const d = 12 + 6 + s // hearth disc + preferred passage + one unit share
        const byKind = Object.fromEntries(result.fixtures.map((f) => [f.kind, f]))
        // The compass points, exactly (y south).
        expect(byKind.vessel.x).toBeCloseTo(0, 6)
        expect(byKind.vessel.y).toBeCloseTo(-d, 6)
        expect(byKind.scales.x).toBeCloseTo(d, 6)
        expect(byKind.scales.y).toBeCloseTo(0, 6)
        expect(byKind.table.x).toBeCloseTo(0, 6)
        expect(byKind.table.y).toBeCloseTo(d, 6)
        expect(byKind.chest.x).toBeCloseTo(-d, 6)
        expect(byKind.chest.y).toBeCloseTo(0, 6)
        for (const f of result.fixtures) {
          expect(f.r).toBeCloseTo(s, 9)
          // Clear of the hearth by the preferred passage.
          expect(Math.hypot(f.x, f.y) - f.r - 12).toBeGreaterThanOrEqual(6 - 1e-6)
          // Contained.
          expect(Math.hypot(f.x, f.y) + f.r).toBeLessThanOrEqual(100 + 1e-6)
          // Clear of every other fixture by the hard clearance.
          for (const g of result.fixtures) {
            if (g.id === f.id) continue
            expect(Math.hypot(f.x - g.x, f.y - g.y) - f.r - g.r).toBeGreaterThanOrEqual(1.2 - 1e-6)
          }
          // Clear of every task room by the hard clearance.
          for (const p of result.placed) {
            expect(Math.hypot(f.x - p.x, f.y - p.y) - f.r - p.r).toBeGreaterThanOrEqual(1.2 - 1e-4)
          }
        }
        // The fixtures are not task rooms: the record holds only
        // the collection's own positions and weights.
        expect(Object.keys(result.record.positions)).toHaveLength(n)
        expect(Object.keys(result.record.weights)).toHaveLength(n)
      },
      180_000,
    )
  }

  it(
    'fixtures are obstacles, not decoration: the same collection packs to a different scale around them',
    () => {
      const bare = planOverheadLayout(rooms(12), new Map(), null)
      const withFix = planOverheadLayout(rooms(12), new Map(), null, { fixtures: true })
      expect(withFix.fixtures).toHaveLength(4)
      expect(bare.fixtures).toEqual([])
      // Four extra rooms' worth of floor is spoken for; the
      // common scale answers for it (never by distorting a room).
      expect(withFix.record.scale).toBeLessThan(bare.record.scale)
      expect(withFix.unplaced).toEqual([])
    },
    180_000,
  )
})
