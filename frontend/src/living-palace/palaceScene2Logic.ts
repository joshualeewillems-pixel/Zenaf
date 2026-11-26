/**
 * Palace Scene 2 — the building as an Apollonian circle, nested in
 * the dome shell. Ported to TypeScript.
 *
 * The building layer's ground is the founder's empty dome shell
 * (assets/palace-shell.jpg) and the building's floors stand as
 * circles INSIDE its cavity, in Apollonian fashion, under the law
 * the founder ruled across 2026-11-26 12:53–13:33 PT — the study
 * builder (rendering-test-assets/maeve-palace-study/scene-2/
 * build_study_v5.py) implements the packing, and the shell ruling
 * ("It needs to nest In this geometry", 2026-11-26 13:33 PT) sets
 * the container: the cavity derived from the shell art itself
 * (assets/palace-cavity.json — 720-ray radial derivation from
 * (627, 655), the polygon eroded 6px; usable area 543,190 px,
 * verified against the decoded RLE by the tests, the #453
 * lesson). This module is that law's port, and the invariants,
 * not the study's coordinates, are the contract (live data
 * differs):
 *
 *   - each floor (project) is one circle; its AREA is its
 *     percentage share of the filled composition: share = the
 *     floor's roomCount / the building's total rooms, area =
 *     share × fill × the cavity's usable area. A floor with 0
 *     rooms still gets a small tappable circle (MIN_FLOOR_RADIUS);
 *     if the building's total rooms are 0, shares are equal. One
 *     floor = one large circle.
 *   - containment is the cavity's own: a placed circle's centre
 *     must have cavity-EDT ≥ its radius (the EDT of the usable
 *     mask decoded from the shipped RLE, Scene 1's exact
 *     transform) — the whole circle then stands inside the
 *     cavity, never crossing the shell's frame.
 *   - the composition fills the cavity: floors pack largest-first,
 *     tangent-seeking (tangency candidates around placed circles
 *     plus a deterministic coarse grid over the cavity, scored by
 *     the study's snugness — least slack to a neighbour, then to
 *     the boundary via EDT), fully deterministic. Remaining gaps
 *     close with descending unlabelled filler circles down to
 *     radius 3. No reserved centre hall.
 *   - one hearth, at the recorded place: centre (627, 1022),
 *     r 62 in the 1254 frame — standing on the shell's floor at
 *     the bottom centre; nothing overlaps it. (The per-circle
 *     hearths of study v4 were a misread and do not ship.)
 *   - each floor circle's interior is one of the founder's three
 *     unfurnished room plates, assigned by size rank cycling
 *     rose → spiral → tiers (addendum 2026-11-26 13:16 PT).
 *   - the fill ladder is the study's (0.66 → 0.54). Live data can
 *     be denser than any study, so below the ladder the port keeps
 *     stepping the fill down (to 0.30), then scales every radius
 *     (the minimum included) by 0.9 steps, rather than dropping a
 *     floor silently. The relaxed phases are a documented safety
 *     net, not the design.
 *
 * The study's filler is seeded-random; here it is a fixed-seed
 * PRNG (mulberry32, seed 11 as in the study) running rejection
 * sampling over the cavity, so the layout is deterministic:
 * same input → same layout, every run.
 */
import cavityJson from './assets/palace-cavity.json'
import { distanceTransform } from './palaceSceneLogic'

/* ------------------------------------------------------------------ */
/* the frame and the cavity (the shell's own geometry)                 */
/* ------------------------------------------------------------------ */

/** The shell art's frame: a 1254 square. Rendering converts the
 *  placements to % of it. */
export const SCENE2_FRAME = 1254

interface CavityJsonShape {
  frame: number
  centre: [number, number]
  polygon: [number, number][]
  /** Per-row runs of usable pixels: each row is a list of
   *  [start, length] pairs. */
  usableRle: [number, number][][]
  usableArea: number
  polygonArea: number
  hearth: { cx: number; cy: number; r: number }
}

const CAVITY_JSON = cavityJson as unknown as CavityJsonShape

/** The cavity's recorded centre (the derivation's ray origin). */
export const CAVITY_CENTER = { x: CAVITY_JSON.centre[0], y: CAVITY_JSON.centre[1] }

/** The hearth's disc — the recorded place in the asset: standing
 *  on the shell's floor at the bottom centre of the 1254 frame. */
export const HEARTH_R = CAVITY_JSON.hearth.r
export const HEARTH = { x: CAVITY_JSON.hearth.cx, y: CAVITY_JSON.hearth.cy }

interface Cavity {
  /** Usable-ground mask (1 = a circle may stand on this pixel). */
  mask: Uint8Array
  /** Exact EDT of the mask: distance to the nearest unusable
   *  pixel. A circle of radius r centred where edt ≥ r stands
   *  wholly inside the cavity. */
  edt: Float64Array
  /** The decoded usable area, in pixels — counted from the RLE,
   *  never trusted from the record alone (the tests pin it
   *  against the recorded 543,190). */
  usableArea: number
  minX: number
  maxX: number
  minY: number
  maxY: number
}

let cavityCache: Cavity | null = null

function loadCavity(): Cavity {
  if (cavityCache) return cavityCache
  const size = CAVITY_JSON.frame
  const mask = new Uint8Array(size * size)
  let usableArea = 0
  let minX = size
  let minY = size
  let maxX = -1
  let maxY = -1
  CAVITY_JSON.usableRle.forEach((runs, y) => {
    for (const [start, length] of runs) {
      mask.fill(1, y * size + start, y * size + start + length)
      usableArea += length
      if (start < minX) minX = start
      if (start + length - 1 > maxX) maxX = start + length - 1
      if (y < minY) minY = y
      if (y > maxY) maxY = y
    }
  })
  cavityCache = {
    mask,
    edt: distanceTransform(mask, size, size),
    usableArea,
    minX,
    maxX,
    minY,
    maxY,
  }
  return cavityCache
}

/** The cavity's decoded usable area (px). */
export function cavityUsableArea(): number {
  return loadCavity().usableArea
}

/** The cavity EDT at a point (nearest pixel; 0 outside the
 *  frame). Containment reads: cavityEdtAt(x, y) ≥ r. */
export function cavityEdtAt(x: number, y: number): number {
  const { edt } = loadCavity()
  const px = Math.round(x)
  const py = Math.round(y)
  if (px < 0 || py < 0 || px >= SCENE2_FRAME || py >= SCENE2_FRAME) return 0
  return edt[py * SCENE2_FRAME + px]
}

/** The cavity polygon as a CSS clip-path (percent of the frame) —
 *  belt-and-braces over the composition: containment already
 *  guarantees no floor paints outside the cavity. */
export const CAVITY_CLIP_PATH = `polygon(${CAVITY_JSON.polygon
  .map(([x, y]) => `${((x / SCENE2_FRAME) * 100).toFixed(2)}% ${((y / SCENE2_FRAME) * 100).toFixed(2)}%`)
  .join(', ')})`

/* ------------------------------------------------------------------ */
/* the law's constants                                                 */
/* ------------------------------------------------------------------ */

/** A floor circle keeps this far from the hearth's disc. */
export const HEARTH_CLEARANCE = 4
/** Minimum edge-to-edge gap between two floor circles. */
export const FLOOR_GAP = 2
/** Filler circles keep this much EDT margin inside the cavity. */
export const FILLER_WALL_MARGIN = 3
/** …and this far from the hearth's disc. */
export const FILLER_HEARTH_MARGIN = 3

/** The study's fill ladder. */
export const FILL_LADDER = [0.66, 0.62, 0.58, 0.54]
/** Below the ladder, the safety net's fill steps. */
const FILL_SAFETY_STEPS = [0.5, 0.46, 0.42, 0.38, 0.34, 0.3]

/** A floor with few or no rooms still gets a tappable circle of
 *  at least this radius (frame units). */
export const MIN_FLOOR_RADIUS = 34

/** The candidate grid's step over the cavity (frame units). */
export const GRID_STEP = 10

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

/** The founder's three unfurnished room plates (addendum
 *  2026-11-26 13:16 PT). A floor circle's interior is one plate,
 *  assigned by SIZE RANK cycling rose → spiral → tiers: the
 *  largest floor stands in the rose room, the next in the spiral
 *  room, the next in the tiers room, then the cycle repeats. */
export type RoomPlate = 'rose' | 'spiral' | 'tiers'
export const ROOM_PLATE_CYCLE: RoomPlate[] = ['rose', 'spiral', 'tiers']

export interface PlacedFloor extends Scene2Circle {
  key: string
  roomCount: number
  /** The floor's share of the building's rooms (0..1). */
  share: number
  /** The room plate for this floor's interior, by size rank —
   *  floors pack largest first, so placement order IS size rank. */
  plate: RoomPlate
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
/* the packing (the study's law, the cavity as container)              */
/* ------------------------------------------------------------------ */

interface SizedFloor extends Scene2FloorInput {
  share: number
  r: number
}

function sizedFloors(floors: Scene2FloorInput[], fill: number, radiusScale: number): SizedFloor[] {
  const usableArea = loadCavity().usableArea
  const total = floors.reduce((s, f) => s + f.roomCount, 0)
  return floors.map((f) => {
    const share = total > 0 ? f.roomCount / total : 1 / floors.length
    const r = Math.max(Math.sqrt((share * fill * usableArea) / Math.PI), MIN_FLOOR_RADIUS) * radiusScale
    return { ...f, share, r }
  })
}

function fits(x: number, y: number, r: number, placed: PlacedFloor[]): boolean {
  if (cavityEdtAt(x, y) < r) return false
  if (Math.hypot(x - HEARTH.x, y - HEARTH.y) < r + HEARTH_R + HEARTH_CLEARANCE) return false
  return placed.every((p) => Math.hypot(x - p.x, y - p.y) >= r + p.r + FLOOR_GAP)
}

/** One packing attempt at one fill and radius scale. Candidates:
 *  a deterministic coarse grid over the cavity, then tangency
 *  candidates around each placed circle (the study's second
 *  family). The study's score: snugness — least slack to a
 *  neighbour, then least slack to the boundary (EDT); first
 *  maximum wins. Returns null if any floor finds no lawful
 *  place. */
function tryPack(sized: SizedFloor[]): PlacedFloor[] | null {
  const cavity = loadCavity()
  const order = sized
    .map((f, i) => ({ f, i }))
    .sort((a, b) => b.f.r - a.f.r || a.i - b.i)
  const placed: PlacedFloor[] = []
  for (const { f } of order) {
    const r = f.r
    const candidates: { x: number; y: number }[] = []
    for (let y = cavity.minY; y <= cavity.maxY; y += GRID_STEP) {
      for (let x = cavity.minX; x <= cavity.maxX; x += GRID_STEP) {
        candidates.push({ x, y })
      }
    }
    for (const p of placed) {
      const d = r + p.r + FLOOR_GAP
      for (let i = 0; i < 120; i++) {
        const a = (i * Math.PI) / 60
        candidates.push({ x: p.x + d * Math.cos(a), y: p.y + d * Math.sin(a) })
      }
    }
    let best: { score: number; x: number; y: number } | null = null
    for (const { x, y } of candidates) {
      if (!fits(x, y, r, placed)) continue
      const slack = placed.length
        ? Math.min(...placed.map((p) => Math.hypot(x - p.x, y - p.y) - (r + p.r)))
        : 0
      const wallSlack = cavityEdtAt(x, y) - r
      const score = -Math.min(slack, 40) - Math.min(wallSlack, 40) * 0.5
      if (best === null || score > best.score) best = { score, x, y }
    }
    if (best === null) return null
    placed.push({
      key: f.key,
      roomCount: f.roomCount,
      share: f.share,
      x: best.x,
      y: best.y,
      r,
      plate: ROOM_PLATE_CYCLE[placed.length % ROOM_PLATE_CYCLE.length],
    })
  }
  return placed
}

/** The descending filler — rejection sampling with a fixed seed
 *  over the cavity's bounds: sampled points whose circle stands
 *  inside the cavity (EDT, with the rim margin), clear of the
 *  hearth, and clear of every circle already standing (floors
 *  and earlier filler). */
function planFillers(floors: PlacedFloor[]): Scene2Circle[] {
  const cavity = loadCavity()
  const rand = mulberry32(FILLER_SEED)
  const all: Scene2Circle[] = [...floors]
  const fillers: Scene2Circle[] = []
  const spanX = cavity.maxX - cavity.minX
  const spanY = cavity.maxY - cavity.minY
  for (const target of FILLER_RADII) {
    for (let attempt = 0; attempt < FILLER_ATTEMPTS; attempt++) {
      const x = cavity.minX + rand() * spanX
      const y = cavity.minY + rand() * spanY
      if (cavityEdtAt(x, y) < target + FILLER_WALL_MARGIN) continue
      if (Math.hypot(x - HEARTH.x, y - HEARTH.y) < target + HEARTH_R + FILLER_HEARTH_MARGIN) continue
      if (!all.every((p) => Math.hypot(x - p.x, y - p.y) >= target + p.r + FLOOR_GAP)) continue
      const circle = { x, y, r: target }
      fillers.push(circle)
      all.push(circle)
    }
  }
  return fillers
}

/** Plan the building scene: floors as Apollonian circles nested
 *  in the dome shell's cavity, the gaps filled, the hearth
 *  reserved on the floor. An empty building plans as the empty
 *  cavity and the hearth alone. */
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
  // Unreachable for any building whose floors fit the cavity at
  // all (the last safety phase stands circles ~12 units wide).
  // Fail loudly rather than place a floor outside the law.
  throw new Error('Palace Scene 2: no lawful placement for the building’s floors')
}
