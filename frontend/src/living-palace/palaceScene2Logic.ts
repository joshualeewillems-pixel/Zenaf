/**
 * Palace Scene 2 — the building as an Apollonian circle, ported to
 * TypeScript.
 *
 * The building layer's ground is one great circle — the cutaway of
 * the building's dome — and the building's floors stand in it as
 * circles in Apollonian fashion, under the law the founder ruled
 * across 2026-11-26 12:53–13:04 PT and the study builder
 * (rendering-test-assets/maeve-palace-study/scene-2/
 * build_study_v5.py) implements — this module is that law's port,
 * and the invariants, not the study's coordinates, are the
 * contract (live data differs):
 *
 *   - each floor (project) is one circle; its AREA is its
 *     percentage share of the filled composition: share = the
 *     floor's roomCount / the building's total rooms, radius =
 *     R × sqrt(share × fill). A floor with 0 rooms still gets a
 *     small tappable circle (MIN_FLOOR_RADIUS); if the building's
 *     total rooms are 0, shares are equal. One floor = one large
 *     circle.
 *   - the composition fills the circle: floors pack largest-first,
 *     tangent-seeking (wall-ring and around-placed candidates,
 *     scored by snugness — the study's score verbatim), fully
 *     deterministic. Remaining gaps close with descending
 *     unlabelled filler circles down to radius 3. No reserved
 *     centre hall.
 *   - one hearth, at the bottom centre: a stone-ring disc reserved
 *     on the bottom arc; nothing overlaps it. (The per-circle
 *     hearths of study v4 were a misread and do not ship.)
 *   - the fill ladder is the study's (0.66 → 0.54). Live data can
 *     be denser than any study, so below the ladder the port keeps
 *     stepping the fill down (to 0.30), then scales every radius
 *     (the minimum included) by 0.9 steps, rather than dropping a
 *     floor silently. Every shape the tests exercise packs under
 *     the strict ladder; the relaxed phases are a documented
 *     safety net, not the design.
 *
 * The study's filler is seeded-random; here it is a fixed-seed
 * PRNG (mulberry32, seed 11 as in the study) running the study's
 * rejection sampling verbatim, so the layout is deterministic:
 * same input → same layout, every run.
 */

/* ------------------------------------------------------------------ */
/* the frame (the study's coordinates)                                 */
/* ------------------------------------------------------------------ */

/** The study's frame: a 1024 square, the great circle centred at
 *  (512, 512) with radius 468. Rendering converts to %. */
export const SCENE2_FRAME = 1024
export const SCENE2_CENTER = 512
export const GREAT_CIRCLE_R = 468

/** The hearth's disc — reserved on the bottom arc, tangent to the
 *  great circle's bottom (the study: r 68, centre 2 units above
 *  the tangent point). */
export const HEARTH_R = 68
export const HEARTH = { x: 512, y: SCENE2_CENTER + GREAT_CIRCLE_R - HEARTH_R - 2 }

/** A floor circle keeps this far from the great circle's rim. */
export const WALL_CLEARANCE = 4
/** …and this far from the hearth's disc. */
export const HEARTH_CLEARANCE = 4
/** Minimum edge-to-edge gap between two floor circles. */
export const FLOOR_GAP = 2

/** The study's fill ladder. */
export const FILL_LADDER = [0.66, 0.62, 0.58, 0.54]
/** Below the ladder, the safety net's fill steps. */
const FILL_SAFETY_STEPS = [0.5, 0.46, 0.42, 0.38, 0.34, 0.3]

/** A floor with few or no rooms still gets a tappable circle of
 *  at least this radius (frame units). */
export const MIN_FLOOR_RADIUS = 34

/** Filler circles descend through these radii, as in the study. */
export const FILLER_RADII = [52, 42, 34, 27, 21, 17, 13, 10, 8, 6, 5, 4, 3]
export const FILLER_ATTEMPTS = 420
export const FILLER_SEED = 11

/* ------------------------------------------------------------------ */
/* types                                                               */
/* ------------------------------------------------------------------ */

export interface Scene2FloorInput {
  /** Stable unique key — the floor's project id. */
  key: string
  roomCount: number
}

export interface Scene2Circle {
  x: number
  y: number
  r: number
}

export interface PlacedFloor extends Scene2Circle {
  key: string
  roomCount: number
  /** The floor's share of the building's rooms (0..1). */
  share: number
}

export interface BuildingSceneLayout {
  floors: PlacedFloor[]
  fillers: Scene2Circle[]
  hearth: Scene2Circle
  /** The fill the packing settled at. */
  fillUsed: number
}

/* ------------------------------------------------------------------ */
/* deterministic PRNG (the filler's seed)                              */
/* ------------------------------------------------------------------ */

/** mulberry32 — small, exact (Math.imul arithmetic), identical
 *  on every engine. */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/* ------------------------------------------------------------------ */
/* the packing (the study's try_pack, verbatim law)                    */
/* ------------------------------------------------------------------ */

interface SizedFloor extends Scene2FloorInput {
  share: number
  r: number
}

function sizedFloors(floors: Scene2FloorInput[], fill: number, radiusScale: number): SizedFloor[] {
  const total = floors.reduce((s, f) => s + f.roomCount, 0)
  return floors.map((f) => {
    const share = total > 0 ? f.roomCount / total : 1 / floors.length
    const r = Math.max(GREAT_CIRCLE_R * Math.sqrt(share * fill), MIN_FLOOR_RADIUS) * radiusScale
    return { ...f, share, r }
  })
}

function fits(x: number, y: number, r: number, placed: PlacedFloor[]): boolean {
  if (Math.hypot(x - SCENE2_CENTER, y - SCENE2_CENTER) + r > GREAT_CIRCLE_R - WALL_CLEARANCE) return false
  if (Math.hypot(x - HEARTH.x, y - HEARTH.y) < r + HEARTH_R + HEARTH_CLEARANCE) return false
  return placed.every((p) => Math.hypot(x - p.x, y - p.y) >= r + p.r + FLOOR_GAP)
}

/** One packing attempt at one fill and radius scale — the study's
 *  candidate search and snugness score, verbatim. Returns null if
 *  any floor finds no lawful place. */
function tryPack(sized: SizedFloor[]): PlacedFloor[] | null {
  const order = sized
    .map((f, i) => ({ f, i }))
    .sort((a, b) => b.f.r - a.f.r || a.i - b.i)
  const placed: PlacedFloor[] = []
  for (const { f } of order) {
    const r = f.r
    // Candidates in the study's generation order: the wall ring
    // first, then around each placed circle in placement order.
    const candidates: { x: number; y: number }[] = []
    const rr = GREAT_CIRCLE_R - WALL_CLEARANCE - r
    for (let i = 0; i < 240; i++) {
      const a = (i * Math.PI) / 120
      candidates.push({ x: SCENE2_CENTER + rr * Math.cos(a), y: SCENE2_CENTER + rr * Math.sin(a) })
    }
    for (const p of placed) {
      const d = r + p.r + FLOOR_GAP
      for (let i = 0; i < 120; i++) {
        const a = (i * Math.PI) / 60
        candidates.push({ x: p.x + d * Math.cos(a), y: p.y + d * Math.sin(a) })
      }
    }
    // The study's score: snugness — least slack to a neighbour,
    // then least slack to the wall; first maximum wins.
    let best: { score: number; x: number; y: number } | null = null
    for (const { x, y } of candidates) {
      if (!fits(x, y, r, placed)) continue
      const slack = placed.length
        ? Math.min(...placed.map((p) => Math.hypot(x - p.x, y - p.y) - (r + p.r)))
        : 0
      const wallSlack = GREAT_CIRCLE_R - (Math.hypot(x - SCENE2_CENTER, y - SCENE2_CENTER) + r)
      const score = -Math.min(slack, 40) - Math.min(wallSlack, 40) * 0.5
      if (best === null || score > best.score) best = { score, x, y }
    }
    if (best === null) return null
    placed.push({ key: f.key, roomCount: f.roomCount, share: f.share, x: best.x, y: best.y, r })
  }
  return placed
}

/** The descending filler — the study's rejection sampling with a
 *  fixed seed: for each target radius, sampled points that stay
 *  inside the great circle, clear of the hearth, and clear of
 *  every circle already standing (floors and earlier filler). */
function planFillers(floors: PlacedFloor[]): Scene2Circle[] {
  const rand = mulberry32(FILLER_SEED)
  const all: Scene2Circle[] = [...floors]
  const fillers: Scene2Circle[] = []
  for (const target of FILLER_RADII) {
    for (let attempt = 0; attempt < FILLER_ATTEMPTS; attempt++) {
      const a = rand() * 2 * Math.PI
      const d = rand() * (GREAT_CIRCLE_R - target)
      const x = SCENE2_CENTER + d * Math.cos(a)
      const y = SCENE2_CENTER + d * Math.sin(a)
      if (Math.hypot(x - SCENE2_CENTER, y - SCENE2_CENTER) + target > GREAT_CIRCLE_R - 3) continue
      if (Math.hypot(x - HEARTH.x, y - HEARTH.y) < target + HEARTH_R + 3) continue
      if (!all.every((p) => Math.hypot(x - p.x, y - p.y) >= target + p.r + FLOOR_GAP)) continue
      const circle = { x, y, r: target }
      fillers.push(circle)
      all.push(circle)
    }
  }
  return fillers
}

/** Plan the building scene: floors as Apollonian circles under the
 *  law, the gaps filled, the hearth reserved. An empty building
 *  plans as the empty circle and the hearth alone. */
export function planBuildingScene(floors: Scene2FloorInput[]): BuildingSceneLayout {
  const hearth: Scene2Circle = { x: HEARTH.x, y: HEARTH.y, r: HEARTH_R }
  if (floors.length === 0) {
    return { floors: [], fillers: [], hearth, fillUsed: FILL_LADDER[0] }
  }
  const attempts: { fill: number; radiusScale: number }[] = [
    ...FILL_LADDER.map((fill) => ({ fill, radiusScale: 1 })),
    ...FILL_SAFETY_STEPS.map((fill) => ({ fill, radiusScale: 1 })),
  ]
  for (let k = 1; k <= 10; k++) {
    attempts.push({ fill: FILL_SAFETY_STEPS[FILL_SAFETY_STEPS.length - 1], radiusScale: 0.9 ** k })
  }
  for (const { fill, radiusScale } of attempts) {
    const placed = tryPack(sizedFloors(floors, fill, radiusScale))
    if (placed) {
      return { floors: placed, fillers: planFillers(placed), hearth, fillUsed: fill }
    }
  }
  // Unreachable for any building whose floors fit the circle at
  // all (the last safety phase stands circles ~12 units wide).
  // Fail loudly rather than place a floor outside the law.
  throw new Error('Palace Scene 2: no lawful placement for the building’s floors')
}
