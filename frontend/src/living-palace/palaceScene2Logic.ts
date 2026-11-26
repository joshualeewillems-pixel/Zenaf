/**
 * Palace Scene 2 — the building as a composition of room-circles
 * inside the founder's dome shell, under the packing rules he
 * ruled across 2026-11-26 (the rules document,
 * goals/seven-seat-worlds/files/
 * zenaf-palace-scene-two-packing-rules-2026-11-26.md, is the
 * contract; studies v12–v17 in rendering-test-assets/
 * maeve-palace-study/scene-2/ explored them, v17's roll-settling
 * with v16's support rule is the reference implementation):
 *
 *   1. THE SPACE. The whole dome interior is the space to fill —
 *      the wall cavity and the floor together (assets/
 *      palace-container.json: the cavity polygon derived from
 *      the shell art ∪ the floor ellipse fitted to its rim;
 *      decoded area 697,884 px in the 1254 frame, pinned by the
 *      tests — the #453 lesson). Its area is the measure.
 *   2. RELATIVE SIZES. Each floor is one circle; its AREA is its
 *      share of the data (its rooms against the building's total
 *      rooms; equal shares when the total is 0) taken against
 *      the space's area under ONE common fill:
 *      r = sqrt(share × fill × containerArea / π). A floor with
 *      0 rooms still gets a small tappable circle
 *      (MIN_FLOOR_RADIUS) — the one break in pure proportion,
 *      kept from the earlier law so no floor loses its door.
 *   3. ROOMS ONLY. No filler circles, no other bubbles; the
 *      ground between the rooms is the dome's wall.
 *   4. NO TEXT. No cards, tags or percentages ride the circles;
 *      a circle is its room, and identity travels through the
 *      chat. (The rendering keeps to this; the law here just
 *      places circles.)
 *   5. GRAVITY + 6. NESTING. Placement is roll-settling (study
 *      v17): each circle, in the attempt's order, falls into the
 *      deepest valley of the pile's surface — the topmost rest
 *      over the ground curve, the placed circles' shoulders and
 *      the hearth's shoulder — then ROLLS downhill along that
 *      surface until it wedges in a pocket, tangent to its
 *      supports, Apollonian fashion.
 *   7. FULL ALL AROUND + 8. SCALE TOGETHER. A fill ladder
 *      (0.75 → 0.40) under a few deterministic placement orders
 *      takes the first VALID layout — the largest supported
 *      composition the search finds, proportions never changing.
 *      Blank wall is what is left over, never the plan.
 *   9. SUPPORT. A layout is valid only when every circle ends
 *      IN CONTACT (the ground, a placed circle, the wall's rim
 *      graze, or the hearth — each within CONTACT_TOLERANCE)
 *      AND SUPPORTED (ground contact, or tangent to a placed
 *      circle whose centre is below its own). The largest
 *      circle must stand on the ground. Leaning on the hearth
 *      or a wall alone does not hold a room up.
 *  10. THE HEARTH. One hearth, at the recorded place: centre
 *      (627, 1022), r 62 in the 1254 frame — on the floor at
 *      the bottom centre; circles keep CIRCLE_GAP clear of it.
 *
 * Clearance is ONE gap (CIRCLE_GAP = 2) with a sub-pixel
 * tolerance (CLEARANCE_TOLERANCE = 0.75) everywhere — rim
 * samples (24) inside the container mask, pairwise, hearth —
 * the studies' two hard lessons: mismatched gaps and
 * exact-tangency arithmetic each made real pockets unplaceable.
 *
 * The frame rules stand from the same day: the composition
 * nests inside the shell's geometry (the wrapper clips to the
 * container's outline — CONTAINER_CLIP_PATH — so rooms standing
 * on the floor are not cut at the cavity's back rim), the shell
 * stands on the Zenaf background, room interiors are the
 * founder's unfurnished plates by size rank cycling
 * rose → spiral → tiers, drawn back-to-front by depth.
 *
 * Safety posture (kept from the earlier law): if no (fill,
 * order) validates, the plan falls back to the lowest fill's
 * best attempt — radii scaled down by 0.9 steps only if a
 * circle cannot settle at all — rather than dropping a floor
 * or losing access. The fallback is a documented net, not
 * the design. Everything is deterministic: fixed grids, fixed
 * order seeds, an exact PRNG — same input, same layout.
 */
import containerJson from './assets/palace-container.json'
import { distanceTransform } from './palaceSceneLogic'

/* ------------------------------------------------------------------ */
/* the frame and the container (the shell's own geometry)              */
/* ------------------------------------------------------------------ */

/** The shell art's frame: a 1254 square. Rendering converts the
 *  placements to % of it. */
export const SCENE2_FRAME = 1254

interface ContainerJsonShape {
  frame: number
  /** The container's recorded area (px) — the tests verify the
   *  shipped RLE decodes to exactly this before it is trusted. */
  containerArea: number
  /** Per-row runs of container pixels: each row is a list of
   *  [start, length] pairs. */
  containerRle: [number, number][][]
  /** The container's outline (360 points) — the clip polygon. */
  clipPolygon: [number, number][]
  ground: { cx: number; cy: number; rx: number; ry: number; lift: number }
  hearth: { cx: number; cy: number; r: number }
}

const CONTAINER_JSON = containerJson as unknown as ContainerJsonShape

/** The hearth's disc — the recorded place in the asset: on the
 *  shell's floor at the bottom centre of the 1254 frame. */
export const HEARTH_R = CONTAINER_JSON.hearth.r
export const HEARTH = { x: CONTAINER_JSON.hearth.cx, y: CONTAINER_JSON.hearth.cy }

/** The floor's recorded geometry: the mid-surface curve the
 *  rooms stand on is groundYAt(x) = cy + lift·sqrt(1 −
 *  ((x − cx)/rx)²) over the floor's span. */
export const GROUND = { ...CONTAINER_JSON.ground }

/** The floor's mid-surface height at column x (frame units), or
 *  null outside the floor's span. A circle resting on the floor
 *  in column x has its centre at groundYAt(x) − r. */
export function groundYAt(x: number): number | null {
  const t = 1 - ((x - GROUND.cx) / GROUND.rx) ** 2
  if (t < 0) return null
  return GROUND.cy + GROUND.lift * Math.sqrt(t)
}

interface Container {
  /** Container mask (1 = inside the space: cavity ∪ floor). */
  mask: Uint8Array
  /** Exact EDT of the mask (Scene 1's transform): a rim sample
   *  is inside iff its EDT > 0; the wall graze reads it too. */
  edt: Float64Array
  /** The decoded container area, in pixels — counted from the
   *  RLE, never trusted from the record alone (the tests pin it
   *  against the recorded 697,884). */
  area: number
  minX: number
  maxX: number
  minY: number
  maxY: number
}

let containerCache: Container | null = null

function loadContainer(): Container {
  if (containerCache) return containerCache
  const size = CONTAINER_JSON.frame
  const mask = new Uint8Array(size * size)
  let area = 0
  let minX = size
  let minY = size
  let maxX = -1
  let maxY = -1
  CONTAINER_JSON.containerRle.forEach((runs, y) => {
    for (const [start, length] of runs) {
      mask.fill(1, y * size + start, y * size + start + length)
      area += length
      if (start < minX) minX = start
      if (start + length - 1 > maxX) maxX = start + length - 1
      if (y < minY) minY = y
      if (y > maxY) maxY = y
    }
  })
  containerCache = {
    mask,
    edt: distanceTransform(mask, size, size),
    area,
    minX,
    maxX,
    minY,
    maxY,
  }
  return containerCache
}

/** The container's decoded area (px) — the space's measure. */
export function containerArea(): number {
  return loadContainer().area
}

/** The container EDT at a point (nearest pixel; 0 outside the
 *  frame). A point is inside the space iff this is > 0. */
export function containerEdtAt(x: number, y: number): number {
  const { edt } = loadContainer()
  const px = Math.round(x)
  const py = Math.round(y)
  if (px < 0 || py < 0 || px >= SCENE2_FRAME || py >= SCENE2_FRAME) return 0
  return edt[py * SCENE2_FRAME + px]
}

/** The container's outline as a CSS clip-path (percent of the
 *  frame) — the composition wrapper clips to the whole space,
 *  floor included, so a room standing on the floor is not cut
 *  at the cavity's back rim. */
export const CONTAINER_CLIP_PATH = `polygon(${CONTAINER_JSON.clipPolygon
  .map(([x, y]) => `${((x / SCENE2_FRAME) * 100).toFixed(2)}% ${((y / SCENE2_FRAME) * 100).toFixed(2)}%`)
  .join(', ')})`

/* ------------------------------------------------------------------ */
/* the law's constants                                                 */
/* ------------------------------------------------------------------ */

/** The one clearance gap: circle-to-circle and circle-to-hearth
 *  alike (frame units). */
export const CIRCLE_GAP = 2
/** Sub-pixel tolerance on every clearance — exact-tangency
 *  seats must not fail by fractions. */
export const CLEARANCE_TOLERANCE = 0.75
/** Rim samples per circle for the inside test. */
export const RIM_SAMPLES = 24
/** A circle is IN CONTACT when it comes within this of the
 *  ground, a placed circle, the wall (see WALL_GRAZE) or the
 *  hearth. */
export const CONTACT_TOLERANCE = 5
/** A circle is SUPPORTED when its ground contact or a tangency
 *  to a circle below holds within this. */
export const SUPPORT_TOLERANCE = 6
/** The wall graze: a rim sample this close to the boundary
 *  (EDT ≤ 3) counts as touching the side. */
export const WALL_GRAZE = 3

/** The column grid roll-settling scans, and the roll's step. */
export const COLUMN_STEP = 4
export const ROLL_STEP = 4
export const ROLL_MAX_STEPS = 300
/** A roll continues only while the neighbouring rest is lower
 *  (larger centre-y) by more than this. */
export const ROLL_DROP = 0.5

/** The fill ladder: relative scaling tries the whole set at
 *  these fills, high to low, and takes the largest valid. */
export const FILL_TOP = 0.75
export const FILL_BOTTOM = 0.4
export const FILL_STEP = 0.025
export const FILL_LADDER: number[] = Array.from(
  { length: Math.round((FILL_TOP - FILL_BOTTOM) / FILL_STEP) + 1 },
  (_, i) => Math.round((FILL_TOP - i * FILL_STEP) * 1000) / 1000,
)
/** Placement orders tried at each fill: largest-first, then
 *  these fixed seeds' neighbour-swap variants (the studies'
 *  rearrangement freedom, kept deterministic). */
export const ORDER_SEEDS = [7, 19, 42]
/** A seeded variant swaps an adjacent pair when its draw is
 *  below this. */
export const ORDER_SWAP_DRAW = 0.4
/** The fallback's radius scale step (0.9^k) and its bound. */
export const FALLBACK_SCALE = 0.9
export const FALLBACK_MAX_SCALES = 12

/** A floor with few or no rooms still gets a tappable circle of
 *  at least this radius (frame units). */
export const MIN_FLOOR_RADIUS = 34

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
  /** The room plate for this floor's interior, by size rank. */
  plate: RoomPlate
}

export interface BuildingSceneLayout {
  /** The placed floors, in size-rank order (largest first;
   *  equal radii keep input order). */
  floors: PlacedFloor[]
  hearth: Scene2Circle
  /** The fill the packing settled at. */
  fillUsed: number
}

/* ------------------------------------------------------------------ */
/* deterministic PRNG (the order variants' seed)                       */
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
/* clearance — one gap, one tolerance (the studies' hard lessons)      */
/* ------------------------------------------------------------------ */

interface PlacedCircle extends Scene2Circle {
  key: string
  roomCount: number
  share: number
  inputIndex: number
}

/** The whole circle inside the space: every rim sample lands on
 *  a container pixel. */
function rimInside(x: number, y: number, r: number): boolean {
  const { mask } = loadContainer()
  for (let k = 0; k < RIM_SAMPLES; k++) {
    const a = (2 * Math.PI * k) / RIM_SAMPLES
    const px = Math.round(x + r * Math.cos(a))
    const py = Math.round(y + r * Math.sin(a))
    if (px < 0 || py < 0 || px >= SCENE2_FRAME || py >= SCENE2_FRAME) return false
    if (mask[py * SCENE2_FRAME + px] === 0) return false
  }
  return true
}

/** A resting position is CLEAR when the circle stands inside
 *  the space and keeps the one gap from the hearth and every
 *  placed circle (each within the sub-pixel tolerance). */
function isClear(x: number, y: number, r: number, placed: PlacedCircle[]): boolean {
  if (!rimInside(x, y, r)) return false
  if (Math.hypot(x - HEARTH.x, y - HEARTH.y) < r + HEARTH_R + CIRCLE_GAP - CLEARANCE_TOLERANCE) return false
  return placed.every(
    (p) => Math.hypot(x - p.x, y - p.y) >= r + p.r + CIRCLE_GAP - CLEARANCE_TOLERANCE,
  )
}

/** The centre-y where a circle of radius r in column x comes to
 *  rest falling from above: the topmost surface beneath it —
 *  the ground curve, each placed circle's shoulder, the
 *  hearth's shoulder. Null when the column cannot hold it (the
 *  rest position is not clear). */
function restYAt(x: number, r: number, placed: PlacedCircle[]): number | null {
  let best: number | null = null
  const gy = groundYAt(x)
  if (gy !== null) best = gy - r
  for (const p of placed) {
    const d = r + p.r + CIRCLE_GAP
    const dx = x - p.x
    if (Math.abs(dx) < d) {
      const y = p.y - Math.sqrt(d * d - dx * dx)
      if (best === null || y < best) best = y
    }
  }
  const dh = r + HEARTH_R + CIRCLE_GAP
  const dxh = x - HEARTH.x
  if (Math.abs(dxh) < dh) {
    const y = HEARTH.y - Math.sqrt(dh * dh - dxh * dxh)
    if (best === null || y < best) best = y
  }
  if (best === null) return null
  return isClear(x, best, r, placed) ? best : null
}

/** Roll-settling (study v17): drop into the deepest valley of
 *  the pile's surface (largest rest centre-y; ties away from
 *  the pile's centroid), then roll sideways while the
 *  neighbouring column's rest is lower, until wedged. */
function settleRoll(r: number, placed: PlacedCircle[]): { x: number; y: number } | null {
  const container = loadContainer()
  const candidates: { restY: number; x: number; away: number }[] = []
  const centroidX = placed.length
    ? placed.reduce((s, p) => s + p.x, 0) / placed.length
    : SCENE2_FRAME / 2
  for (let x = container.minX; x <= container.maxX; x += COLUMN_STEP) {
    const restY = restYAt(x, r, placed)
    if (restY !== null) candidates.push({ restY, x, away: Math.abs(x - centroidX) })
  }
  if (candidates.length === 0) return null
  candidates.sort((a, b) => b.restY - a.restY || b.away - a.away)
  let { x } = candidates[0]
  let y = candidates[0].restY
  for (let step = 0; step < ROLL_MAX_STEPS; step++) {
    let moved = false
    for (const dx of [-ROLL_STEP, ROLL_STEP]) {
      const nx = x + dx
      if (nx < container.minX || nx > container.maxX) continue
      const ny = restYAt(nx, r, placed)
      if (ny !== null && ny > y + ROLL_DROP) {
        x = nx
        y = ny
        moved = true
        break
      }
    }
    if (!moved) break
  }
  return { x, y }
}

/* ------------------------------------------------------------------ */
/* validity — contact and support (rule 9)                             */
/* ------------------------------------------------------------------ */

function groundContact(x: number, y: number, r: number, tolerance: number): boolean {
  const gy = groundYAt(x)
  return gy !== null && Math.abs(y + r - gy) <= tolerance
}

/** IN CONTACT: within CONTACT_TOLERANCE of the ground, a placed
 *  circle or the hearth — or the rim grazes the wall. */
function inContact(c: PlacedCircle, all: PlacedCircle[]): boolean {
  if (groundContact(c.x, c.y, c.r, CONTACT_TOLERANCE)) return true
  if (Math.abs(Math.hypot(c.x - HEARTH.x, c.y - HEARTH.y) - (c.r + HEARTH_R + CIRCLE_GAP)) <= CONTACT_TOLERANCE) {
    return true
  }
  for (const p of all) {
    if (p === c) continue
    if (Math.abs(Math.hypot(c.x - p.x, c.y - p.y) - (c.r + p.r + CIRCLE_GAP)) <= CONTACT_TOLERANCE) {
      return true
    }
  }
  for (let k = 0; k < RIM_SAMPLES; k++) {
    const a = (2 * Math.PI * k) / RIM_SAMPLES
    if (containerEdtAt(c.x + c.r * Math.cos(a), c.y + c.r * Math.sin(a)) <= WALL_GRAZE) return true
  }
  return false
}

/** SUPPORTED: ground contact, or tangent to a placed circle
 *  whose centre is below its own. The hearth and the wall do
 *  not hold a room up. */
function isSupported(c: PlacedCircle, all: PlacedCircle[]): boolean {
  if (groundContact(c.x, c.y, c.r, SUPPORT_TOLERANCE)) return true
  return all.some(
    (p) =>
      p !== c &&
      p.y > c.y &&
      Math.abs(Math.hypot(c.x - p.x, c.y - p.y) - (c.r + p.r + CIRCLE_GAP)) <= SUPPORT_TOLERANCE,
  )
}

/** A layout is VALID when every circle ends in contact and
 *  supported, and a largest circle stands on the ground. */
function isValidLayout(placed: PlacedCircle[]): boolean {
  if (placed.length === 0) return true
  const maxR = Math.max(...placed.map((p) => p.r))
  const largestStands = placed.some(
    (p) => Math.abs(p.r - maxR) <= 1e-9 && groundContact(p.x, p.y, p.r, SUPPORT_TOLERANCE),
  )
  if (!largestStands) return false
  return placed.every((c) => inContact(c, placed) && isSupported(c, placed))
}

/* ------------------------------------------------------------------ */
/* the packing — relative scaling over a fill ladder                   */
/* ------------------------------------------------------------------ */

interface SizedFloor extends Scene2FloorInput {
  share: number
  r: number
  inputIndex: number
}

function sizedFloors(floors: Scene2FloorInput[], fill: number, radiusScale: number): SizedFloor[] {
  const area = loadContainer().area
  const total = floors.reduce((s, f) => s + f.roomCount, 0)
  return floors.map((f, inputIndex) => {
    const share = total > 0 ? f.roomCount / total : 1 / floors.length
    const r = Math.max(Math.sqrt((share * fill * area) / Math.PI), MIN_FLOOR_RADIUS) * radiusScale
    return { ...f, share, r, inputIndex }
  })
}

/** The deterministic placement orders for one attempt set:
 *  largest-first (equal radii keep input order), then each
 *  seed's neighbour-swap variant. */
function placementOrders(sized: SizedFloor[]): SizedFloor[][] {
  const bySize = [...sized].sort((a, b) => b.r - a.r || a.inputIndex - b.inputIndex)
  const orders: SizedFloor[][] = [bySize]
  for (const seed of ORDER_SEEDS) {
    const rand = mulberry32(seed)
    const variant = [...bySize]
    for (let i = 0; i + 1 < variant.length; i++) {
      if (rand() < ORDER_SWAP_DRAW) {
        const tmp = variant[i]
        variant[i] = variant[i + 1]
        variant[i + 1] = tmp
      }
    }
    orders.push(variant)
  }
  return orders
}

/** One packing attempt: roll-settle every floor in the given
 *  order. Null when any circle finds no resting place. */
function tryPack(order: SizedFloor[]): PlacedCircle[] | null {
  const placed: PlacedCircle[] = []
  for (const f of order) {
    const seat = settleRoll(f.r, placed)
    if (seat === null) return null
    placed.push({
      key: f.key,
      roomCount: f.roomCount,
      share: f.share,
      inputIndex: f.inputIndex,
      x: seat.x,
      y: seat.y,
      r: f.r,
    })
  }
  return placed
}

/** Finish a layout: size-rank order (largest first, equal radii
 *  keep input order), plates by rank. */
function finishLayout(placed: PlacedCircle[], fillUsed: number): BuildingSceneLayout {
  const ranked = [...placed].sort((a, b) => b.r - a.r || a.inputIndex - b.inputIndex)
  return {
    floors: ranked.map((p, rank) => ({
      key: p.key,
      roomCount: p.roomCount,
      share: p.share,
      x: p.x,
      y: p.y,
      r: p.r,
      plate: ROOM_PLATE_CYCLE[rank % ROOM_PLATE_CYCLE.length],
    })),
    hearth: { x: HEARTH.x, y: HEARTH.y, r: HEARTH_R },
    fillUsed,
  }
}

/** Plan the building scene: the floors as a composition of
 *  room-circles in the dome's whole space, under the packing
 *  rules. An empty building plans as the empty space and the
 *  hearth alone. */
export function planBuildingScene(floors: Scene2FloorInput[]): BuildingSceneLayout {
  if (floors.length === 0) {
    return { floors: [], hearth: { x: HEARTH.x, y: HEARTH.y, r: HEARTH_R }, fillUsed: FILL_TOP }
  }
  // The ladder: the first (fill, order) whose layout is valid
  // is the largest supported composition the search finds.
  for (const fill of FILL_LADDER) {
    const sized = sizedFloors(floors, fill, 1)
    for (const order of placementOrders(sized)) {
      const placed = tryPack(order)
      if (placed && isValidLayout(placed)) return finishLayout(placed, fill)
    }
  }
  // The safety net: the lowest fill's best attempt, radii
  // scaled down only while a circle cannot settle at all —
  // never drop a floor, never lose access.
  for (let k = 0; k <= FALLBACK_MAX_SCALES; k++) {
    const sized = sizedFloors(floors, FILL_BOTTOM, FALLBACK_SCALE ** k)
    const placed = tryPack(placementOrders(sized)[0])
    if (placed) return finishLayout(placed, FILL_BOTTOM)
  }
  // Unreachable: at the last scale the circles are a few units
  // wide and settle anywhere. Fail loudly rather than place a
  // floor outside the law.
  throw new Error('Palace Scene 2: no lawful placement for the building’s floors')
}
