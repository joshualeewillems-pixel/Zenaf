/**
 * The overhead plan — the hybrid packing law, ported.
 *
 * A direct port of the study machinery the founder adopted
 * (2026-11-27): `palace_pack.py` (the persistent incremental
 * relaxed-Apollonian placer), `palace_adaptive.py`'s search (the
 * largest common scale at which the whole collection seats), and
 * `palace_hybrid2.py` (the contraction-corrected hybrid transition
 * rule), all in
 * ~/workspace/rendering-test-assets/maeve-palace-study/scene-2/overhead/.
 * The law, as adopted in the port proposal
 * (zenaf-palace-overhead-port-proposal-v2-2026-11-27.md):
 *
 * - Radii: `r = sqrt(weight) x s`, ONE common scale `s` per layout
 *   — relative sizes exact by construction. Weight is the standing
 *   task-size rule (estimated_hours when recorded and > 0, else one
 *   equal unit share — palaceScene2Logic.taskSizeWeight). No
 *   clamping, ever.
 * - Spacing: hard clearance 1.2 wall-to-wall; preferred passage
 *   6.0; preferred edge gap 2.0 (plan units; the floor radius is
 *   100 plan units and every constant scales with it).
 * - The centre is the fire: a hearth disc (r = 12) stands before
 *   any room, never moves, never counts as a room.
 * - Founding: the first nine placements are guided to the
 *   triangular site order; beyond nine, newcomers join gaps by the
 *   spacing preference; dependency adjacency outranks the site;
 *   the standing composition outranks everything.
 * - Transitions (the hybrid): on GROWTH the target scale is the
 *   largest at which the seeded placement seats everyone, and the
 *   working scale moves only HALFWAY toward it (damping 0.5); on
 *   CONTRACTION the scale moves IN FULL, in the same operation, to
 *   the cold-search target for the smaller collection. Placement
 *   descends the reflow ladder — seeded (all seats offered) ->
 *   seeded-large (largest half) -> seeded-anchor (largest three)
 *   -> cold — the first rung that seats everyone wins; the x0.97
 *   step-down is the last resort on growth. Every transition is
 *   recorded (rung, step-downs, moved rooms).
 * - Honest capacity: a room that still cannot seat is returned as
 *   an explicit unplaced record {id, radius, cause} — never
 *   resized, overlapped, or hidden.
 * - Integrity: containment + pairwise clearance + hearth
 *   clearance are verified in the ground plane before any render;
 *   the layout function never returns an illegal layout — a
 *   violation grows the unplaced list instead.
 *
 * Deterministic: fixed iteration orders, no randomness, no clock,
 * no dependence on input order. Same rooms + same prior state give
 * the same layout. (Python's round() is round-half-even; pyRound
 * below carries that behaviour into the score buckets the study
 * placer compares, so the port tracks the study's choices.)
 */

export const OVERHEAD_R_FLOOR = 100
const MARGIN = 0 // rooms may stand tangent to the outer wall
export const OVERHEAD_CLEARANCE = 1.2 // hard minimum wall-to-wall gap
export const OVERHEAD_SPACING = 6.0 // preferred wall-to-wall gap
export const OVERHEAD_EDGE_GAP = 2.0 // preferred gap to the outer wall
const REPAIR_BUDGET = 60 // the hybrid's enlarged repair budget (study: 60, not the base 30)
export const OVERHEAD_HEARTH_R = 12
const HEARTH_ID = '__hearth__'
const EPS = 1e-9
const KEEP_TOL = 0.05

export const PROVEN_INFEASIBLE = 'PROVEN_INFEASIBLE'
export const SEARCH_EXHAUSTION = 'SEARCH_EXHAUSTION'

/** The layout record's version — the packing rule's version, so a
 *  future rule change re-lays-out visibly instead of corrupting
 *  silently. */
export const PALACE_LAYOUT_VERSION = 1

export interface OverheadRoomInput {
  id: string
  weight: number
}

export interface UnplacedRoom {
  id: string
  radius: number
  cause: string
}

interface PlacedCircle {
  id: string
  x: number
  y: number
  r: number
}

export interface PlacementResult {
  positions: Record<string, [number, number]>
  radii: Record<string, number>
  unplaced: (UnplacedRoom & { detail: string; evictedFromPrior: boolean })[]
  kept: string[]
  strategyUsed: string
  snugSeats: string[]
  repairs: { id: string; from: [number, number]; to: [number, number]; dist: number }[]
  evictedUnrepaired: string[]
  placedCount: number
  requestedCount: number
  validation: {
    boundaryViolations: string[]
    overlaps: [string, string, number][]
    hearthViolations: string[]
    conserved: boolean
  }
}

type Partners = Map<string, Set<string>>

/* ------------------------------------------------------------------ */
/* the standing artifact rooms (founder addendum, 2026-11-27         */
/* 12:22 PT)                                                           */
/*                                                                     */
/* Four rooms stand in every project's overhead plan besides the     */
/* task rooms: the vessel room, the scales room, the drawing-table   */
/* room and the chest room. They are FIXTURES, as the hearth is:     */
/* seated before the task rooms, never counted as task rooms (not    */
/* in the packing law's counts, not in occupancy), and the task      */
/* packer clears them by the same clearance law. Each carries one    */
/* equal unit share at the layout's scale (r = s), and they stand    */
/* at the compass points around the hearth, one preferred passage    */
/* (SPACING) from the fire's disc: centre distance 12 + 6 + s. At    */
/* any scale the search can return (s <= 40) that ring is lawful     */
/* by construction: neighbours sit d x sqrt(2) apart against a       */
/* 2s + 1.2 need (holds to s = 41.4), and the outer reach            */
/* 18 + 2s stays inside the floor (98 of 100 at s = 40).             */
/* ------------------------------------------------------------------ */

export type OverheadArtifactKind = 'vessel' | 'scales' | 'table' | 'chest'

export interface OverheadFixture {
  id: string
  kind: OverheadArtifactKind
  x: number
  y: number
  r: number
}

/** The compass assignment (y south): the vessel to the north, the
 *  scales to the east, the drawing table to the south — the
 *  visitor's side — and the chest to the west. */
const ARTIFACT_COMPASS: { id: string; kind: OverheadArtifactKind; angleDeg: number }[] = [
  { id: 'artifact:vessel', kind: 'vessel', angleDeg: -90 },
  { id: 'artifact:scales', kind: 'scales', angleDeg: 0 },
  { id: 'artifact:table', kind: 'table', angleDeg: 90 },
  { id: 'artifact:chest', kind: 'chest', angleDeg: 180 },
]

export function overheadFixtureCircles(scale: number): OverheadFixture[] {
  const d = OVERHEAD_HEARTH_R + OVERHEAD_SPACING + scale
  return ARTIFACT_COMPASS.map(({ id, kind, angleDeg }) => {
    const a = (angleDeg * Math.PI) / 180
    return { id, kind, x: d * Math.cos(a), y: d * Math.sin(a), r: scale }
  })
}

/** The scale an empty palace stands at (no task rooms to search
 *  against): a declared, calm size near the small-palace scales,
 *  so the hearth and the four artifact rooms stand at a modest
 *  radius even before the first task arrives. */
export const OVERHEAD_EMPTY_SCALE = 12

/** Extra standing obstacles (the artifact fixtures) the placer
 *  must clear, as a function of the candidate scale — their
 *  radius IS the scale, so they are rebuilt at every candidate. */
type ObstaclesForScale = (scale: number) => PlacedCircle[]

/** Python's round(): round-half-even on the binary double. */
function pyRound(x: number, digits = 0): number {
  const m = 10 ** digits
  const v = x * m
  const f = Math.floor(v)
  const diff = v - f
  let r: number
  if (diff > 0.5) r = f + 1
  else if (diff < 0.5) r = f
  else r = f % 2 === 0 ? f : f + 1
  return r / m
}

export function overheadRadiusOf(weight: number, scale: number): number {
  return Math.sqrt(weight) * scale
}

function lawful(
  x: number,
  y: number,
  r: number,
  placed: PlacedCircle[],
  tol = 0,
): boolean {
  if (Math.hypot(x, y) + r > OVERHEAD_R_FLOOR - MARGIN + tol) return false
  for (const p of placed) {
    if (Math.hypot(x - p.x, y - p.y) < r + p.r + OVERHEAD_CLEARANCE - tol) return false
  }
  return true
}

function gapMin(x: number, y: number, r: number, placed: PlacedCircle[]): number {
  let g = Infinity
  for (const p of placed) {
    g = Math.min(g, Math.hypot(x - p.x, y - p.y) - (r + p.r))
  }
  return g
}

function edgeGap(x: number, y: number, r: number): number {
  return OVERHEAD_R_FLOOR - MARGIN - (Math.hypot(x, y) + r)
}

function spacingErr(x: number, y: number, r: number, placed: PlacedCircle[]): number {
  if (placed.length === 0) return 0
  return Math.abs(gapMin(x, y, r, placed) - OVERHEAD_SPACING)
}

function intersect(
  c0: [number, number],
  r0: number,
  c1: [number, number],
  r1: number,
): [number, number][] {
  const d = Math.hypot(c1[0] - c0[0], c1[1] - c0[1])
  if (d > r0 + r1 + EPS || d < Math.abs(r0 - r1) - EPS || d < EPS) return []
  const a = (r0 * r0 - r1 * r1 + d * d) / (2 * d)
  const h2 = r0 * r0 - a * a
  if (h2 < -EPS) return []
  const h = Math.sqrt(Math.max(h2, 0))
  const mx = c0[0] + (a * (c1[0] - c0[0])) / d
  const my = c0[1] + (a * (c1[1] - c0[1])) / d
  const rx = -(c1[1] - c0[1]) / d
  const ry = (c1[0] - c0[0]) / d
  return [
    [mx + h * rx, my + h * ry],
    [mx - h * rx, my - h * ry],
  ]
}

/** Curved-gap seats at the PREFERRED spacing: a full SPACING gap
 *  to two placed circles, or a full SPACING gap to one placed
 *  circle with EDGE_GAP to the boundary. Fixed enumeration order. */
function gapCandidates(r: number, placed: PlacedCircle[]): [number, number][] {
  const cands: [number, number][] = []
  const n = placed.length
  for (let i = 0; i < n; i++) {
    const { x: xi, y: yi, r: ri } = placed[i]
    cands.push(
      ...intersect([0, 0], OVERHEAD_R_FLOOR - OVERHEAD_EDGE_GAP - r, [xi, yi], r + ri + OVERHEAD_SPACING),
    )
    for (let j = i + 1; j < n; j++) {
      const { x: xj, y: yj, r: rj } = placed[j]
      cands.push(...intersect([xi, yi], r + ri + OVERHEAD_SPACING, [xj, yj], r + rj + OVERHEAD_SPACING))
    }
  }
  return cands
}

function angleKey(x: number, y: number): number {
  return pyRound(Math.atan2(y, x), 6)
}

/** Triangular site order: three anchors (N, SE, SW), then the
 *  three bisectors (NW, NE, S), then every remaining arc bisected
 *  level by level. Angles in degrees, world coords (y south). */
function buildSites(): number[] {
  const order = [-90.0, 30.0, 150.0]
  let have = [...order].sort((a, b) => a - b)
  while (order.length < 72) {
    const mids: number[] = []
    const m = have.length
    for (let i = 0; i < m; i++) {
      const a0 = have[i]
      const a1 = have[(i + 1) % m] + (i === m - 1 ? 360.0 : 0.0)
      const mid = (a0 + a1) / 2
      mids.push(mid >= 180.0 ? mid - 360.0 : mid)
    }
    order.push(...mids)
    have = [...new Set([...have, ...mids])].sort((a, b) => a - b)
  }
  return order
}

const SITE_ANGLES = buildSites()

function siteLevel(index: number): number {
  let level = 0
  let rest = index
  for (;;) {
    const count = level <= 1 ? 3 : 3 * 2 ** (level - 1)
    if (rest < count) return level
    rest -= count
    level += 1
  }
}

/** Where a room of radius r is guided, by placement order: its
 *  level's angle, on a ring that steps inward per level, never
 *  closer to the fire than SPACING allows. */
function sitePoint(index: number, r: number): [number, number] {
  const ang = (SITE_ANGLES[index % SITE_ANGLES.length] * Math.PI) / 180
  const factor = Math.max(0.55, 1.0 - 0.11 * siteLevel(index))
  let d = (OVERHEAD_R_FLOOR - OVERHEAD_EDGE_GAP - r) * factor
  d = Math.max(d, OVERHEAD_HEARTH_R + r + OVERHEAD_SPACING + 2.0)
  return [d * Math.cos(ang), d * Math.sin(ang)]
}

type Strategy = 'spaced' | 'rim' | 'spread'
const STRATEGIES: Strategy[] = ['spaced', 'rim', 'spread']

function compareScore(a: number[], b: number[]): number {
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return a[i] < b[i] ? -1 : 1
  }
  return 0
}

/** Best lawful seat for a new room: [x, y, snug] or null. Score
 *  order: partner proximity first under every strategy; then the
 *  strategy's preference. SPACING is a preference, not a law: if
 *  no preferred seat is lawful, a snug seat at hard CLEARANCE is
 *  tried before the room is given up (flagged snug). */
function seatNew(
  rid: string,
  r: number,
  placed: PlacedCircle[],
  partnersOf: Partners,
  strategy: Strategy = 'spaced',
  site: [number, number] | null = null,
): [number, number, boolean] | null {
  if (placed.length === 0) {
    return lawful(0, 0, r, placed) ? [0, 0, false] : null
  }
  const partners = partnersOf.get(rid) ?? new Set<string>()

  const scoreOf = (x: number, y: number): number[] => {
    let adj = 1
    for (const p of placed) {
      if (partners.has(p.id) && Math.hypot(x - p.x, y - p.y) - (r + p.r) <= OVERHEAD_SPACING + 1.5) {
        adj = 0
        break
      }
    }
    const errB = pyRound(spacingErr(x, y, r, placed) / 2.0)
    const edgeB = pyRound(Math.abs(edgeGap(x, y, r) - OVERHEAD_EDGE_GAP) / 2.0)
    const distB = pyRound(Math.hypot(x, y) / 2.0)
    const ang = angleKey(x, y)
    if (strategy === 'rim') return [adj, edgeB, errB, ang]
    if (strategy === 'spread') return [adj, -distB, errB, ang]
    if (site !== null) {
      const siteB = pyRound(Math.hypot(x - site[0], y - site[1]) / 3.0)
      return [adj, siteB, errB, -distB, ang]
    }
    return [adj, errB, -distB, ang]
  }

  const bestOf = (
    cands: [number, number][],
  ): { score: number[]; x: number; y: number } | null => {
    let best: { score: number[]; x: number; y: number } | null = null
    for (const [x, y] of cands) {
      if (!lawful(x, y, r, placed)) continue
      const score = scoreOf(x, y)
      if (best === null || compareScore(score, best.score) < 0) best = { score, x, y }
    }
    return best
  }

  const cands = gapCandidates(r, placed)
  if (site !== null) {
    const [sx, sy] = site
    const sd = Math.hypot(sx, sy)
    const sa = Math.atan2(sy, sx)
    for (const da of [0.0, -0.18, 0.18, -0.36, 0.36]) {
      for (const dd of [0.0, -6.0, 6.0, -12.0, 12.0]) {
        cands.push([(sd + dd) * Math.cos(sa + da), (sd + dd) * Math.sin(sa + da)])
      }
    }
    cands.push([sx, sy])
  }
  for (const p of placed) {
    for (let sIdx = 0; sIdx < 36; sIdx++) {
      const a = (sIdx * 10 * Math.PI) / 180
      cands.push([p.x + (r + p.r + OVERHEAD_SPACING) * Math.cos(a), p.y + (r + p.r + OVERHEAD_SPACING) * Math.sin(a)])
    }
  }
  for (let sIdx = 0; sIdx < 36; sIdx++) {
    const a = (sIdx * 10 * Math.PI) / 180
    cands.push([
      (OVERHEAD_R_FLOOR - OVERHEAD_EDGE_GAP - r) * Math.cos(a),
      (OVERHEAD_R_FLOOR - OVERHEAD_EDGE_GAP - r) * Math.sin(a),
    ])
  }
  const best = bestOf(cands)
  if (best !== null) return [best.x, best.y, false]

  // Snug pass: the same candidate shapes at hard CLEARANCE.
  const snugCands: [number, number][] = []
  const n = placed.length
  for (let i = 0; i < n; i++) {
    const { x: xi, y: yi, r: ri } = placed[i]
    snugCands.push(
      ...intersect([0, 0], OVERHEAD_R_FLOOR - MARGIN - r, [xi, yi], r + ri + OVERHEAD_CLEARANCE),
    )
    for (let j = i + 1; j < n; j++) {
      const { x: xj, y: yj, r: rj } = placed[j]
      snugCands.push(...intersect([xi, yi], r + ri + OVERHEAD_CLEARANCE, [xj, yj], r + rj + OVERHEAD_CLEARANCE))
    }
    for (let sIdx = 0; sIdx < 36; sIdx++) {
      const a = (sIdx * 10 * Math.PI) / 180
      snugCands.push([xi + (r + ri + OVERHEAD_CLEARANCE) * Math.cos(a), yi + (r + ri + OVERHEAD_CLEARANCE) * Math.sin(a)])
    }
  }
  for (let sIdx = 0; sIdx < 36; sIdx++) {
    const a = (sIdx * 10 * Math.PI) / 180
    snugCands.push([
      (OVERHEAD_R_FLOOR - MARGIN - r) * Math.cos(a),
      (OVERHEAD_R_FLOOR - MARGIN - r) * Math.sin(a),
    ])
  }
  const snugBest = bestOf(snugCands)
  if (snugBest !== null) return [snugBest.x, snugBest.y, true]

  // Bounded fallback scan — fixed rings from the edge inward.
  let d = OVERHEAD_R_FLOOR
  while (d >= 0.0) {
    for (let sIdx = 0; sIdx < 120; sIdx++) {
      const a = (sIdx * 3 * Math.PI) / 180
      const x = d * Math.cos(a)
      const y = d * Math.sin(a)
      if (lawful(x, y, r, placed)) return [x, y, true]
    }
    d -= 2.0
  }
  return null
}

/** Nearest lawful seat to the prior position within the movement
 *  budget, or null (search exhaustion within budget). */
function seatRepair(
  rid: string,
  r: number,
  priorXY: [number, number],
  placed: PlacedCircle[],
): [number, number] | null {
  void rid
  const [px0, py0] = priorXY
  const cands = gapCandidates(r, placed)
  for (let dist = 2; dist < 31; dist += 2) {
    for (let sIdx = 0; sIdx < 48; sIdx++) {
      const a = (sIdx * 7.5 * Math.PI) / 180
      cands.push([px0 + dist * Math.cos(a), py0 + dist * Math.sin(a)])
    }
  }
  let best: { score: number[]; x: number; y: number } | null = null
  for (const [x, y] of cands) {
    const dist = Math.hypot(x - px0, y - py0)
    if (dist > REPAIR_BUDGET + EPS) continue
    if (!lawful(x, y, r, placed)) continue
    const score = [pyRound(dist, 3), pyRound(spacingErr(x, y, r, placed) / 2.0), angleKey(x - px0, y - py0)]
    if (best === null || compareScore(score, best.score) < 0) best = { score, x, y }
  }
  return best ? [best.x, best.y] : null
}

/**
 * The placer (palace_pack.place): rooms = (id, weight) pairs;
 * prior = the standing composition's positions; k = the common
 * scale. Keeps lawful prior seats exactly, repairs conflicts
 * locally within the budget, seats new rooms into curved gaps
 * under a fixed set of deterministic strategies, and reports —
 * never hides — the rooms it cannot seat.
 */
export function placeOverheadRooms(
  rooms: OverheadRoomInput[],
  prior: Record<string, [number, number]>,
  scale: number,
  partners: Partners = new Map(),
  obstaclesForScale?: ObstaclesForScale,
): PlacementResult {
  const radii: Record<string, number> = {}
  for (const room of rooms) radii[room.id] = overheadRadiusOf(room.weight, scale)
  const order = Object.keys(radii).sort((a, b) => {
    const dr = radii[b] - radii[a]
    return dr !== 0 ? dr : a < b ? -1 : a > b ? 1 : 0
  })
  const totalAreaRatio =
    Object.values(radii).reduce((sum, r) => sum + (r + OVERHEAD_CLEARANCE / 2) ** 2, 0) /
    (OVERHEAD_R_FLOOR + OVERHEAD_CLEARANCE / 2) ** 2

  const placed: PlacedCircle[] = [
    { id: HEARTH_ID, x: 0, y: 0, r: OVERHEAD_HEARTH_R },
    ...(obstaclesForScale ? obstaclesForScale(scale) : []),
  ]
  const positions: Record<string, [number, number]> = {}
  const kept: string[] = []
  const repairs: PlacementResult['repairs'] = []
  const evicted: string[] = []
  const newRooms: string[] = []

  const commit = (rid: string, x: number, y: number) => {
    placed.push({ id: rid, x, y, r: radii[rid] })
    positions[rid] = [x, y]
  }

  // Phase 1 — KEEP: lawful prior positions stay exactly.
  const repairQueue: string[] = []
  for (const rid of order) {
    if (!(rid in prior)) {
      newRooms.push(rid)
      continue
    }
    const [x, y] = prior[rid]
    if (lawful(x, y, radii[rid], placed, KEEP_TOL)) {
      commit(rid, x, y)
      kept.push(rid)
    } else {
      repairQueue.push(rid)
    }
  }

  // Phase 2 — LOCAL REPAIR within the movement budget. A room
  // whose repair fails is deferred once: chained conflicts often
  // resolve after their neighbours have moved.
  const tryRepair = (rid: string): boolean => {
    const seat = seatRepair(rid, radii[rid], prior[rid], placed)
    if (seat === null) return false
    commit(rid, seat[0], seat[1])
    repairs.push({
      id: rid,
      from: prior[rid],
      to: seat,
      dist: pyRound(Math.hypot(seat[0] - prior[rid][0], seat[1] - prior[rid][1]), 3),
    })
    return true
  }
  const deferred: string[] = []
  for (const rid of repairQueue) {
    if (!tryRepair(rid)) deferred.push(rid)
  }
  for (const rid of deferred) {
    if (!tryRepair(rid)) evicted.push(rid)
  }

  // Phase 3 — GAP PLACEMENT: new + evicted, largest first, under
  // the fixed strategy set; the attempt that seats the most rooms
  // wins (ties -> earliest strategy). Placed rooms (phases 1-2)
  // are the fixed starting point for every strategy.
  const queue = [...newRooms, ...evicted].sort((a, b) => {
    const dr = radii[b] - radii[a]
    return dr !== 0 ? dr : a < b ? -1 : a > b ? 1 : 0
  })
  const basePlaced = [...placed]
  // Task rooms already standing (kept + repaired), for the
  // founding-site index: minus the hearth, minus any fixture
  // obstacles — fixtures are not placements.
  const baseCount = basePlaced.length - 1 - (obstaclesForScale ? obstaclesForScale(scale).length : 0)
  const sites: Record<string, [number, number] | null> = {}
  queue.forEach((rid, j) => {
    sites[rid] = baseCount + j < 9 ? sitePoint(baseCount + j, radii[rid]) : null
  })

  let best: {
    strategy: Strategy
    placedList: PlacedCircle[]
    unplaced: PlacementResult['unplaced']
    newPositions: Record<string, [number, number]>
    snug: string[]
  } | null = null

  for (const strategy of STRATEGIES) {
    const trial: PlacedCircle[] = [...basePlaced]
    const trialPos: Record<string, [number, number]> = {}
    const trialSnug: string[] = []
    const trialUnplaced: PlacementResult['unplaced'] = []
    for (const rid of queue) {
      const seat = seatNew(rid, radii[rid], trial, partners, strategy, strategy === 'spaced' ? sites[rid] : null)
      if (seat !== null) {
        trial.push({ id: rid, x: seat[0], y: seat[1], r: radii[rid] })
        trialPos[rid] = [seat[0], seat[1]]
        if (seat[2]) trialSnug.push(rid)
      } else {
        let cause: string
        let detail: string
        if (radii[rid] > OVERHEAD_R_FLOOR - MARGIN || totalAreaRatio > 1.0) {
          cause = PROVEN_INFEASIBLE
          detail =
            radii[rid] > OVERHEAD_R_FLOOR - MARGIN
              ? 'radius exceeds the floor'
              : `request area ratio ${totalAreaRatio.toFixed(2)} > 1.00 (discs cannot overlap)`
        } else {
          cause = SEARCH_EXHAUSTION
          detail = `no lawful gap seat found with ${trial.length} rooms placed; a wider reflow might succeed — not attempted`
        }
        trialUnplaced.push({
          id: rid,
          radius: pyRound(radii[rid], 3),
          cause,
          detail,
          evictedFromPrior: evicted.includes(rid),
        })
      }
    }
    if (best === null || trialUnplaced.length < best.unplaced.length) {
      best = {
        strategy,
        placedList: trial,
        unplaced: trialUnplaced,
        newPositions: trialPos,
        snug: trialSnug,
      }
    }
  }

  const chosen = best!
  for (const rid of queue) {
    if (rid in chosen.newPositions) positions[rid] = chosen.newPositions[rid]
  }

  // Validation — ground-plane, before any rendering.
  const ids = Object.keys(positions)
  const boundaryViolations = ids.filter(
    (rid) => Math.hypot(positions[rid][0], positions[rid][1]) + radii[rid] > OVERHEAD_R_FLOOR - MARGIN + 1e-6,
  )
  const overlaps: [string, string, number][] = []
  for (let i = 0; i < ids.length; i++) {
    for (let j = i + 1; j < ids.length; j++) {
      const a = ids[i]
      const b = ids[j]
      const d = Math.hypot(positions[a][0] - positions[b][0], positions[a][1] - positions[b][1])
      if (d < radii[a] + radii[b] + OVERHEAD_CLEARANCE - 1e-6) {
        overlaps.push([a, b, pyRound(d - radii[a] - radii[b], 3)])
      }
    }
  }
  const hearthViolations = ids.filter(
    (rid) => Math.hypot(positions[rid][0], positions[rid][1]) < radii[rid] + OVERHEAD_HEARTH_R + OVERHEAD_CLEARANCE - 1e-6,
  )

  return {
    positions: Object.fromEntries(
      Object.entries(positions).map(([rid, [x, y]]) => [rid, [pyRound(x, 6), pyRound(y, 6)] as [number, number]]),
    ),
    radii: Object.fromEntries(Object.entries(radii).map(([rid, r]) => [rid, pyRound(r, 6)])),
    unplaced: chosen.unplaced,
    kept,
    strategyUsed: chosen.strategy,
    snugSeats: chosen.snug,
    repairs,
    evictedUnrepaired: chosen.unplaced.filter((u) => u.evictedFromPrior).map((u) => u.id),
    placedCount: Object.keys(positions).length,
    requestedCount: Object.keys(radii).length,
    validation: {
      boundaryViolations,
      overlaps,
      hearthViolations,
      conserved: Object.keys(positions).length + chosen.unplaced.length === Object.keys(radii).length,
    },
  }
}

/** The largest common scale at which the whole collection seats
 *  with integrity. Cold by default; with a prior, feasibility is
 *  judged on the seeded (living) placement. Deterministic binary
 *  search — palace_adaptive.search_scale. */
export function searchOverheadScale(
  rooms: OverheadRoomInput[],
  prior: Record<string, [number, number]> = {},
  partners: Partners = new Map(),
  obstaclesForScale?: ObstaclesForScale,
): number {
  let lo = 1.0
  let hi = 40.0
  for (let i = 0; i < 22; i++) {
    const mid = (lo + hi) / 2
    const lay = placeOverheadRooms(rooms, prior, mid, partners, obstaclesForScale)
    if (lay.unplaced.length === 0) lo = mid
    else hi = mid
  }
  return lo
}

/** Descend the reflow ladder at scale s: the same placer with a
 *  progressively thinner prior. The first rung that seats
 *  everyone wins. Returns null when no rung seats everyone. */
function ladder(
  rooms: OverheadRoomInput[],
  prior: Record<string, [number, number]>,
  scale: number,
  partners: Partners,
  obstaclesForScale?: ObstaclesForScale,
): { layout: PlacementResult; rung: string } | null {
  const weights: Record<string, number> = {}
  for (const room of rooms) weights[room.id] = room.weight
  const bySize = Object.keys(prior).sort((a, b) => (weights[b] ?? 0) - (weights[a] ?? 0))
  const half: Record<string, [number, number]> = {}
  for (const rid of bySize.slice(0, Math.max(1, Math.floor(bySize.length / 2)))) half[rid] = prior[rid]
  const anchors: Record<string, [number, number]> = {}
  for (const rid of bySize.slice(0, 3)) anchors[rid] = prior[rid]
  const rungs: [string, Record<string, [number, number]>][] = [
    ['seeded', prior],
    ['seeded-large', half],
    ['seeded-anchor', anchors],
    ['cold', {}],
  ]
  for (const [name, pr] of rungs) {
    const lay = placeOverheadRooms(rooms, pr, scale, partners, obstaclesForScale)
    if (lay.unplaced.length === 0) return { layout: lay, rung: name }
  }
  return null
}

function movements(
  before: Record<string, [number, number]>,
  after: Record<string, [number, number]>,
): Record<string, number> {
  const out: Record<string, number> = {}
  for (const rid of Object.keys(before)) {
    if (rid in after) {
      const d = Math.hypot(after[rid][0] - before[rid][0], after[rid][1] - before[rid][1])
      if (d > 1e-6) out[rid] = pyRound(d, 3)
    }
  }
  return out
}

/* ------------------------------------------------------------------ */
/* the layout record + the hybrid transition                           */
/* ------------------------------------------------------------------ */

export interface PalaceLayoutRecord {
  version: number
  scale: number
  positions: Record<string, [number, number]>
  /** The (id -> weight) collection this layout was computed for.
   *  Beyond the proposal's minimal record: without it, a weight
   *  change (an estimate edited in chat) is indistinguishable from
   *  no change, and the standing fast path below would serve a
   *  stale composition as if nothing had happened. */
  weights: Record<string, number>
  lastTransition: { reflow: boolean; steppedDown: number; movedRooms: number }
  unplaced: UnplacedRoom[]
}

export interface OverheadLayout {
  record: PalaceLayoutRecord
  /** Render-ready rooms in ground units, in placement order. */
  placed: { id: string; x: number; y: number; r: number }[]
  unplaced: UnplacedRoom[]
  /** The four standing artifact rooms at this layout's scale —
   *  present when the layout was computed with fixtures (the
   *  app's path); empty on the study's bare packing path. */
  fixtures: OverheadFixture[]
  /** The ladder rung that produced this layout ('standing' when
   *  the stored record was reused verbatim). */
  rung: string
  /** True when the record differs from the stored one passed in
   *  (or none was passed) — the caller persists only then. */
  changed: boolean
}

function integrityClean(
  positions: Record<string, [number, number]>,
  radii: Record<string, number>,
  tol: number,
  obstacles: PlacedCircle[] = [],
): boolean {
  const ids = Object.keys(positions)
  for (const rid of ids) {
    const [x, y] = positions[rid]
    if (Math.hypot(x, y) + radii[rid] > OVERHEAD_R_FLOOR - MARGIN + tol) return false
    if (Math.hypot(x, y) < radii[rid] + OVERHEAD_HEARTH_R + OVERHEAD_CLEARANCE - tol) return false
    for (const ob of obstacles) {
      if (Math.hypot(x - ob.x, y - ob.y) < radii[rid] + ob.r + OVERHEAD_CLEARANCE - tol) return false
    }
  }
  for (let i = 0; i < ids.length; i++) {
    for (let j = i + 1; j < ids.length; j++) {
      const a = ids[i]
      const b = ids[j]
      const d = Math.hypot(positions[a][0] - positions[b][0], positions[a][1] - positions[b][1])
      if (d < radii[a] + radii[b] + OVERHEAD_CLEARANCE - tol) return false
    }
  }
  return true
}

function recordFrom(
  layout: PlacementResult,
  scale: number,
  rooms: OverheadRoomInput[],
  transition: { reflow: boolean; steppedDown: number; movedRooms: number },
): PalaceLayoutRecord {
  const weights: Record<string, number> = {}
  for (const room of rooms) weights[room.id] = room.weight
  return {
    version: PALACE_LAYOUT_VERSION,
    scale,
    positions: layout.positions,
    weights,
    lastTransition: transition,
    unplaced: layout.unplaced.map((u) => ({ id: u.id, radius: u.radius, cause: u.cause })),
  }
}

function placedList(layout: PlacementResult): { id: string; x: number; y: number; r: number }[] {
  return Object.entries(layout.positions).map(([id, [x, y]]) => ({ id, x, y, r: layout.radii[id] }))
}

/**
 * Compute the overhead layout for one project's rooms, honouring
 * the stored record when one is passed:
 *
 * - Same collection (ids + weights) as the record, and the stored
 *   composition still lawful: the record stands verbatim — no
 *   transition runs, nothing moves, nothing is rewritten.
 * - Otherwise the hybrid transition runs (see the header): growth
 *   damps halfway toward the seeded-search target; contraction
 *   moves in full to the cold-search target; placement descends
 *   the reflow ladder; the x0.97 step-down is the last resort on
 *   growth. (A same-count change of membership or weights takes
 *   the growth path — the study's chain moves by count; the damped
 *   seeded path is the conservative reading for a swap.)
 *
 * Safety net the study never needed (its fixtures always seat):
 * if the ladder still fails after the growth step-downs, fall
 * back to a cold place at the cold-search scale and report
 * whatever remains unplaced — honest capacity, never a crash and
 * never an illegal layout.
 */
export function planOverheadLayout(
  rooms: OverheadRoomInput[],
  partners: Partners = new Map(),
  stored: PalaceLayoutRecord | null = null,
  options: { fixtures?: boolean } = {},
): OverheadLayout {
  const withFixtures = options.fixtures === true
  const obstaclesForScale: ObstaclesForScale | undefined = withFixtures
    ? (s) => overheadFixtureCircles(s)
    : undefined
  const fixturesAt = (s: number): OverheadFixture[] =>
    withFixtures ? overheadFixtureCircles(s) : []
  const weights: Record<string, number> = {}
  for (const room of rooms) weights[room.id] = room.weight

  if (stored && stored.version === PALACE_LAYOUT_VERSION) {
    const sameCollection =
      Object.keys(stored.weights).length === rooms.length &&
      rooms.every((room) => stored!.weights[room.id] === room.weight)
    if (sameCollection) {
      const radii: Record<string, number> = {}
      for (const room of rooms) radii[room.id] = pyRound(overheadRadiusOf(room.weight, stored.scale), 6)
      // Stored positions were rounded to 6dp when written; the
      // standing check allows 1e-4 of slack for that rounding.
      if (integrityClean(stored.positions, radii, 1e-4, fixturesAt(stored.scale))) {
        const placed = Object.entries(stored.positions).map(([id, [x, y]]) => ({
          id,
          x,
          y,
          r: radii[id],
        }))
        return {
          record: stored,
          placed,
          unplaced: stored.unplaced,
          fixtures: fixturesAt(stored.scale),
          rung: 'standing',
          changed: false,
        }
      }
    }
  }

  if (rooms.length === 0) {
    const record: PalaceLayoutRecord = {
      version: PALACE_LAYOUT_VERSION,
      scale: stored?.scale ?? (withFixtures ? OVERHEAD_EMPTY_SCALE : 1),
      positions: {},
      weights: {},
      lastTransition: { reflow: false, steppedDown: 0, movedRooms: 0 },
      unplaced: [],
    }
    return {
      record,
      placed: [],
      unplaced: [],
      fixtures: fixturesAt(record.scale),
      rung: stored ? 'seeded' : 'cold',
      changed: true,
    }
  }

  const priorPos = stored?.positions ?? {}
  const priorCount = stored ? Object.keys(stored.positions).length + stored.unplaced.length : 0
  let layout: PlacementResult
  let scale: number
  let rung: string
  let steppedDown = 0

  if (!stored) {
    // Founding: the cold search scale, a fresh composition.
    scale = searchOverheadScale(rooms, {}, partners, obstaclesForScale)
    layout = placeOverheadRooms(rooms, {}, scale, partners, obstaclesForScale)
    rung = 'cold'
  } else if (rooms.length < priorCount) {
    // Contraction: the scale moves in full, in the same
    // operation, to the cold-search target for the smaller
    // collection; placement descends the ladder.
    scale = searchOverheadScale(rooms, {}, partners, obstaclesForScale)
    const via = ladder(rooms, priorPos, scale, partners, obstaclesForScale)
    if (via) {
      layout = via.layout
      rung = via.rung
    } else {
      // The ladder's cold rung at the cold-search scale seats by
      // that scale's definition; reaching here means float noise
      // at the boundary — step down until it seats, and say so.
      let s = scale
      let fallback: { layout: PlacementResult; rung: string } | null = null
      while (fallback === null && steppedDown < 12) {
        s *= 0.97
        steppedDown += 1
        fallback = ladder(rooms, priorPos, s, partners, obstaclesForScale)
      }
      if (fallback) {
        scale = s
        layout = fallback.layout
        rung = fallback.rung
      } else {
        layout = placeOverheadRooms(rooms, {}, s, partners, obstaclesForScale)
        scale = s
        rung = 'cold'
      }
    }
  } else {
    // Growth (or a same-count change): damped halfway toward the
    // seeded-search target; seeded placement; the ladder on
    // failure; the x0.97 step-down as the last resort.
    const target = searchOverheadScale(rooms, priorPos, partners, obstaclesForScale)
    scale = stored.scale + 0.5 * (target - stored.scale)
    layout = placeOverheadRooms(rooms, priorPos, scale, partners, obstaclesForScale)
    if (layout.unplaced.length === 0) {
      rung = 'seeded'
    } else {
      let via = ladder(rooms, priorPos, scale, partners, obstaclesForScale)
      while (via === null && steppedDown < 8) {
        scale *= 0.97
        steppedDown += 1
        via = ladder(rooms, priorPos, scale, partners, obstaclesForScale)
      }
      if (via) {
        layout = via.layout
        rung = via.rung
      } else {
        // Safety net (see header): a cold place at the
        // cold-search scale, with honest unplaced records.
        scale = searchOverheadScale(rooms, {}, partners, obstaclesForScale)
        layout = placeOverheadRooms(rooms, {}, scale, partners, obstaclesForScale)
        rung = 'cold'
      }
    }
  }

  const moved = stored ? movements(priorPos, layout.positions) : {}
  const record = recordFrom(layout, scale, rooms, {
    reflow: stored !== null && rung !== 'seeded',
    steppedDown,
    movedRooms: Object.keys(moved).length,
  })
  return {
    record,
    placed: placedList(layout),
    unplaced: record.unplaced,
    fixtures: fixturesAt(scale),
    rung,
    changed: true,
  }
}

/** Occupancy of a layout: the rooms' share of the floor's area —
 *  the study's fullness measure, kept for the acceptance suite. */
export function overheadOccupancy(radii: Record<string, number>): number {
  return (
    Object.values(radii).reduce((sum, r) => sum + r * r, 0) / (OVERHEAD_R_FLOOR * OVERHEAD_R_FLOOR)
  )
}
