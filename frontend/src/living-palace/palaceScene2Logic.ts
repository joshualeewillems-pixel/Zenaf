/**
 * Palace Scene 2 — the building as a composition of room-circles
 * inside the founder's architecture dome, under the relaxed
 * Apollonian spacing he ruled 2026-11-26 16:19 PT ("Forget
 * gravity and try to space them all as relatively apollonian as
 * possible"), on the architecture background he supplied the
 * same afternoon. The algorithm of record is the study's
 * (rendering-test-assets/maeve-palace-study/scene-2/
 * build_study_v21_apollonian.py, study v21 — approved by the
 * founder 2026-11-26 16:27 PT: "Yep! That's it"); this module
 * is its port, not a redesign.
 *
 *   1. THE SPACE. The whole dome interior is the space — the
 *      wall cavity and the floor together (assets/
 *      palace-container.json: the cavity polygon derived from
 *      the shell art ∪ the floor ellipse fitted to its rim;
 *      decoded area 697,884 px in the 1254 frame, pinned by the
 *      tests — the #453 lesson). Its area is the measure.
 *   2. RELATIVE SIZES. Each floor is one circle; its AREA is
 *      its share of the data (its rooms against the building's
 *      total rooms; equal shares when the total is 0) taken
 *      against the space's area under ONE common fill:
 *      r = sqrt(share × fill × containerArea / π). Sizes stay
 *      clearly differentiated and the large rooms are
 *      distributed through the composition, never pooled at
 *      the bottom (the founder's refinement, 2026-11-26
 *      16:20 PT). A floor with 0 rooms still gets a small
 *      tappable circle (MIN_FLOOR_RADIUS) — the one break in
 *      pure proportion, kept so no floor loses its door.
 *   3. ROOMS ONLY. No filler circles, no other bubbles; the
 *      ground between the rooms is the dome's wall.
 *   4. NO TEXT. No cards, tags or percentages ride the circles;
 *      a circle is its room, and identity travels through the
 *      chat. (The rendering keeps to this; the law here just
 *      places circles.)
 *   5. RELAXED APOLLONIAN SPACING. No gravity, no support
 *      rule, no floor-standing requirement (the gravity law
 *      of PR #460 is retired). Placement, largest first: the
 *      biggest floor ANCHORS the composition at the clearest
 *      seat near the dome's centre (627, 600); each next floor
 *      seats in the TIGHTEST POCKET it fits — a seat tangent
 *      (plus the one relaxed gap, CIRCLE_GAP = 12) to a pair of
 *      already-placed circles or the hearth, or one of 36
 *      sampled seats tangent to a single placed circle —
 *      scored by snugness (the rim distance to the nearest
 *      third party: another circle, the hearth, or the wall),
 *      bucketed coarsely, then by closeness to the
 *      composition's heart (627, 640). Smaller rooms nestle
 *      into the gaps between larger ones; exact tangency is
 *      not required — the gap leaves room for walls.
 *   6. SCALE TOGETHER. A fill ladder (0.66 → 0.48, steps of
 *      0.03) takes the first fill at which every floor seats —
 *      the largest composition the spacing finds, proportions
 *      never changing. Blank wall is what is left over, never
 *      the plan.
 *   7. THE HEARTH. One hearth: the architecture dome's own
 *      stone ring on its floor (1254 frame: centre 627, 1095,
 *      r 88 — the new background's ring, superseding the old
 *      shell's recorded disc in palace-container.json).
 *      Circles keep the full CIRCLE_GAP clear of it.
 *
 * Clearance is ONE gap (CIRCLE_GAP = 12) everywhere, with the
 * study's two tolerances kept exactly: pairwise seats allow a
 * 0.75 sub-pixel tolerance (exact-tangency arithmetic must not
 * make real pockets unplaceable), while the hearth's clearance
 * is strict. Containment is the study's reading: the centre's
 * EDT must clear r + 2 and 24 rim samples at r + 1 must land
 * inside the container mask.
 *
 * The frame rules stand: the composition nests inside the
 * dome's geometry (the wrapper clips to the container's
 * outline — CONTAINER_CLIP_PATH), the dome stands on the Zenaf
 * background, room interiors are the founder's unfurnished
 * plates by size rank cycling rose → spiral → tiers, drawn
 * back-to-front by depth.
 *
 * Safety posture: if no fill seats every floor in its pocket,
 * the plan falls back to the lowest fill with the whole set
 * scaled down together by 0.9 steps (proportions unchanged)
 * and, behind the last scale, a rescue grid scan for any clear
 * seat — so every floor is always placed, contained and
 * separated rather than dropped. The fallback is a documented
 * net, not the design. Everything
 * is deterministic: fixed grids, fixed candidate order, the
 * study's scoring — same input, same layout.
 *
 * THE TASK LEVEL (founder, 2026-11-26 20:07 PT). The dome
 * serves both levels now: a project's tasks are circles in the
 * same composition, under the same law — sizes from recorded
 * data (a task's estimate when recorded, else one equal unit),
 * one common fill, the same ladder and fallback. The recorded
 * dependencies between a project's tasks — the data the
 * retired floor plan drew as doorways — shape this packing:
 * "instead of a door, we can set it up to where the room
 * itself moves next to another room where it's connected or
 * at least draws a line to it". A task being seated PREFERS a
 * seat adjacent to an already-seated dependency partner (the
 * preference leads the seat score; containment, the common
 * fill and the one gap still gate every seat). A pair the
 * finished packing did not seat adjacent is reported in the
 * layout's `links`, and the scene draws one line for it.
 */
import containerJson from './assets/palace-container.json'
import { distanceTransform } from './palaceSceneLogic'

/* ------------------------------------------------------------------ */
/* the frame and the container (the dome's own geometry)               */
/* ------------------------------------------------------------------ */

/** The dome art's frame: a 1254 square. Rendering converts the
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
}

const CONTAINER_JSON = containerJson as unknown as ContainerJsonShape

/** The hearth's disc — the architecture dome's own stone ring
 *  on its floor, in the 1254 frame (founder's background,
 *  2026-11-26 16:15 PT). This supersedes the old shell's
 *  recorded disc in palace-container.json. */
export const HEARTH_R = 88
export const HEARTH = { x: 627, y: 1095 }

/** The FLAME's breathing room (founder, 2026-11-26 22:28 PT, on
 *  the live dome: "give the fire a little more breathing room
 *  don't have rooms spawn directly covered by it"). The flame
 *  stands 221 tall in the ring (palaceCanvas HEARTH_FLAME_H —
 *  the two move together): its box spans y 874–1095, x 627±71.
 *  No circle may seat where the flame would cover it, so seats
 *  must clear an ellipse over that box with air around it —
 *  ~30 units above the flame's top, ~40 at its sides. */
export const FLAME_ZONE = { cx: 627, cy: 984, rx: 112, ry: 140 }

/** True when a circle at (x, y, r) stays clear of the flame's
 *  breathing room: the ellipse inflated by the circle's radius. */
function clearsFlame(x: number, y: number, r: number): boolean {
  const dx = (x - FLAME_ZONE.cx) / (FLAME_ZONE.rx + r)
  const dy = (y - FLAME_ZONE.cy) / (FLAME_ZONE.ry + r)
  return dx * dx + dy * dy >= 1
}

/** The anchor's home: the dome's centre, where the largest
 *  floor anchors the composition, and the composition's heart,
 *  the point pocket seats are scored for closeness to. */
export const ANCHOR = { x: 627, y: 600 }
export const COMPOSITION_HEART = { x: 627, y: 640 }

interface Container {
  /** Container mask (1 = inside the space: cavity ∪ floor). */
  mask: Uint8Array
  /** Exact EDT of the mask (Scene 1's transform). */
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

/** The container EDT at a point, truncated the way the study
 *  reads it (Python's int() over positive frame coordinates). */
function edtTruncAt(x: number, y: number): number {
  const { edt } = loadContainer()
  const px = Math.trunc(x)
  const py = Math.trunc(y)
  if (px < 0 || py < 0 || px >= SCENE2_FRAME || py >= SCENE2_FRAME) return 0
  return edt[py * SCENE2_FRAME + px]
}

/** The container's outline as a CSS clip-path (percent of the
 *  frame) — the composition wrapper clips to the whole space,
 *  floor included, so a room is not cut at the cavity's back
 *  rim. */
export const CONTAINER_CLIP_PATH = `polygon(${CONTAINER_JSON.clipPolygon
  .map(([x, y]) => `${((x / SCENE2_FRAME) * 100).toFixed(2)}% ${((y / SCENE2_FRAME) * 100).toFixed(2)}%`)
  .join(', ')})`

/* ------------------------------------------------------------------ */
/* the law's constants (the study's, verbatim)                         */
/* ------------------------------------------------------------------ */

/** The one relaxed gap: circle-to-circle and circle-to-hearth
 *  alike (frame units) — the separation that leaves room for
 *  walls between the rooms. */
export const CIRCLE_GAP = 12
/** Sub-pixel tolerance on pairwise clearance — exact-tangency
 *  seats must not fail by fractions. (The hearth's clearance
 *  takes no tolerance: the study's asymmetry, kept.) */
export const CLEARANCE_TOLERANCE = 0.75
/** Rim samples per circle for the inside test. */
export const RIM_SAMPLES = 24
/** The containment margin: a seat's centre EDT must clear
 *  r + CONTAINMENT_MARGIN. */
export const CONTAINMENT_MARGIN = 2

/** The fill ladder: relative scaling tries the whole set at
 *  these fills, high to low, and takes the largest at which
 *  every floor seats in its pocket. */
export const FILL_LADDER: number[] = [0.66, 0.63, 0.6, 0.57, 0.54, 0.51, 0.48]
export const FILL_TOP = FILL_LADDER[0]
export const FILL_BOTTOM = FILL_LADDER[FILL_LADDER.length - 1]

/** The anchor search: a grid around ANCHOR (dx −60..60,
 *  dy −40..60, step 10), scored by Manhattan distance. */
export const ANCHOR_SEARCH = { dxMin: -60, dxMax: 60, dyMin: -40, dyMax: 60, step: 10 }
/** Sampled seats around a single placed circle, for pockets
 *  only one neighbour bounds. */
export const TANGENT_SAMPLES = 36
/** The snugness bucket: seats compete first on their rim
 *  distance to the nearest third party, in buckets this wide —
 *  the study's coarse rounding, so centrality breaks near-ties
 *  instead of float dust. */
export const SNUG_BUCKET = 14

/** The fallback's grid scan step and radius shrink. */
export const RESCUE_GRID_STEP = 8
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
/* the task level — a project's tasks as circles in the same dome      */
/* ------------------------------------------------------------------ */

export interface Scene2TaskInput {
  /** Stable unique key — the task's id. */
  key: string
  /** The size weight: the task's recorded estimate when it has
   *  one, else one equal unit (taskSizeWeight). */
  weight: number
}

/** A recorded dependency pair between two tasks of one project
 *  (either direction — the pair is symmetric here). */
export interface TaskLinkPair {
  aKey: string
  bKey: string
}

export interface PlacedTask extends Scene2Circle {
  key: string
  weight: number
  /** The task's share of the project's total weight (0..1). */
  share: number
}

export interface TaskSceneLayout {
  /** The placed tasks, in size-rank order (largest first;
   *  equal radii keep input order). */
  tasks: PlacedTask[]
  hearth: Scene2Circle
  /** The fill the packing settled at. */
  fillUsed: number
  /** Dependency pairs the packing seated adjacent — neighbours,
   *  no line drawn. */
  adjacent: TaskLinkPair[]
  /** Dependency pairs the packing did NOT seat adjacent — the
   *  scene draws one line for each. */
  links: TaskLinkPair[]
}

/** A task circle's size weight, from its recorded estimate
 *  (the Task record's estimated_hours): the estimate itself
 *  when recorded and > 0, else one equal unit share — a task
 *  with no estimate still stands, at the common unit size. */
export function taskSizeWeight(estimatedHours: number | null | undefined): number {
  return estimatedHours != null && estimatedHours > 0 ? estimatedHours : 1
}

/** The slack on the standard gap within which two circles read
 *  as NEIGHBOURS: tangent seats sit exactly at CIRCLE_GAP, and
 *  the packing's own clearance tolerance lets a rim sit a
 *  fraction inside it; a seat beyond gap + slack is a
 *  neighbour in name only, and its pair takes the line. */
export const ADJACENCY_SLACK = 1.5

/** The rim distance between two circles: centre distance less
 *  the two radii — the gap the eye reads between their rims. */
export function rimDistance(a: Scene2Circle, b: Scene2Circle): number {
  return Math.hypot(a.x - b.x, a.y - b.y) - (a.r + b.r)
}

/** Two placed circles are adjacent when their rims sit at the
 *  composition's standard gap, within the adjacency slack. */
export function areAdjacent(a: Scene2Circle, b: Scene2Circle): boolean {
  return rimDistance(a, b) <= CIRCLE_GAP + ADJACENCY_SLACK
}

/* ------------------------------------------------------------------ */
/* clearance — the study's reading, exactly                            */
/* ------------------------------------------------------------------ */

interface PlacedCircle extends Scene2Circle {
  key: string
  /** The size weight the circle was sized from — a floor's
   *  rooms, a task's estimate-or-unit. */
  weight: number
  share: number
  inputIndex: number
}

/** A seat is CLEAR when the whole circle stands inside the
 *  space — the centre's EDT clears r + CONTAINMENT_MARGIN and
 *  every rim sample at r + 1 lands on a container pixel — and
 *  it keeps the one gap from the hearth (strict), clears the
 *  flame's breathing room, and keeps the gap from every placed
 *  circle (within the sub-pixel tolerance). */
function isClear(x: number, y: number, r: number, placed: PlacedCircle[]): boolean {
  const { mask } = loadContainer()
  if (!(Math.trunc(x) >= 0 && Math.trunc(x) < SCENE2_FRAME && Math.trunc(y) >= 0 && Math.trunc(y) < SCENE2_FRAME)) {
    return false
  }
  if (edtTruncAt(x, y) < r + CONTAINMENT_MARGIN) return false
  for (let k = 0; k < RIM_SAMPLES; k++) {
    const a = (2 * Math.PI * k) / RIM_SAMPLES
    const px = Math.trunc(x + (r + 1) * Math.cos(a))
    const py = Math.trunc(y + (r + 1) * Math.sin(a))
    if (px < 0 || py < 0 || px >= SCENE2_FRAME || py >= SCENE2_FRAME) return false
    if (mask[py * SCENE2_FRAME + px] === 0) return false
  }
  if (Math.hypot(x - HEARTH.x, y - HEARTH.y) < r + HEARTH_R + CIRCLE_GAP) return false
  if (!clearsFlame(x, y, r)) return false
  return placed.every(
    (p) => Math.hypot(x - p.x, y - p.y) >= r + p.r + CIRCLE_GAP - CLEARANCE_TOLERANCE,
  )
}

/** A seat's SNUGNESS: the rim distance to the nearest third
 *  party — another placed circle, the hearth, or the wall
 *  (the centre's EDT beyond the circle's own radius). */
function snugness(x: number, y: number, r: number, placed: PlacedCircle[]): number {
  let snug = edtTruncAt(x, y) - r
  for (const p of placed) {
    snug = Math.min(snug, Math.hypot(x - p.x, y - p.y) - (r + p.r))
  }
  snug = Math.min(snug, Math.hypot(x - HEARTH.x, y - HEARTH.y) - (r + HEARTH_R))
  return snug
}

/** Python's round() — half to even — for the snugness bucket,
 *  so the port scores seats exactly as the study did. */
function pyRound(v: number): number {
  const f = Math.floor(v)
  const diff = v - f
  if (diff > 0.5) return f + 1
  if (diff < 0.5) return f
  return f % 2 === 0 ? f : f + 1
}

/** The seat score: at the task level, a seat ADJACENT to an
 *  already-seated dependency partner leads (the founder's
 *  adjacency preference — 0 when the seat touches a partner,
 *  or when no partner stands yet to touch); then the tightest
 *  pocket (snugness, bucketed); then the seat closest to the
 *  composition's heart. Lower is better; the study's strict
 *  ordering, with the partner component constant 0 wherever
 *  no partners are in play (the project level packs exactly
 *  as it always did). */
function seatScore(
  x: number,
  y: number,
  r: number,
  placed: PlacedCircle[],
  partners?: ReadonlySet<string>,
): [number, number, number] {
  let partnerMiss = 0
  if (partners && partners.size > 0) {
    const standing = placed.filter((p) => partners.has(p.key))
    if (standing.length > 0) {
      partnerMiss = standing.some((p) => areAdjacent({ x, y, r }, p)) ? 0 : 1
    }
  }
  return [
    partnerMiss,
    pyRound(snugness(x, y, r, placed) / SNUG_BUCKET),
    Math.hypot(x - COMPOSITION_HEART.x, y - COMPOSITION_HEART.y),
  ]
}

function scoreLess(a: [number, number, number], b: [number, number, number]): boolean {
  return a[0] < b[0] || (a[0] === b[0] && (a[1] < b[1] || (a[1] === b[1] && a[2] < b[2])))
}

/* ------------------------------------------------------------------ */
/* seats — the anchor and the pockets                                  */
/* ------------------------------------------------------------------ */

/** The anchor seat for the largest floor: the clearest seat on
 *  the search grid around the dome's centre, scored by
 *  Manhattan distance from it. */
function anchorSeat(r: number): { x: number; y: number } | null {
  let best: { s: number; x: number; y: number } | null = null
  for (let dx = ANCHOR_SEARCH.dxMin; dx <= ANCHOR_SEARCH.dxMax; dx += ANCHOR_SEARCH.step) {
    for (let dy = ANCHOR_SEARCH.dyMin; dy <= ANCHOR_SEARCH.dyMax; dy += ANCHOR_SEARCH.step) {
      const x = ANCHOR.x + dx
      const y = ANCHOR.y + dy
      if (!isClear(x, y, r, [])) continue
      const s = Math.abs(dx) + Math.abs(dy)
      if (best === null || s < best.s) best = { s, x, y }
    }
  }
  return best === null ? null : { x: best.x, y: best.y }
}

/** The pocket seat for the next floor: among the seats tangent
 *  (plus the gap) to a pair of obstacles — the placed circles
 *  and the hearth — and the sampled seats tangent to a single
 *  obstacle, the clear seat with the best score: the tightest
 *  pocket it fits, nearest the composition's heart. */
function pocketSeat(
  r: number,
  placed: PlacedCircle[],
  partners?: ReadonlySet<string>,
): { x: number; y: number } | null {
  const obstacles: Scene2Circle[] = [
    ...placed.map((p) => ({ x: p.x, y: p.y, r: p.r })),
    { x: HEARTH.x, y: HEARTH.y, r: HEARTH_R },
  ]
  const candidates: { x: number; y: number }[] = []
  for (let i = 0; i < obstacles.length; i++) {
    for (let j = i + 1; j < obstacles.length; j++) {
      const o1 = obstacles[i]
      const o2 = obstacles[j]
      const d = Math.hypot(o2.x - o1.x, o2.y - o1.y)
      const R1 = o1.r + r + CIRCLE_GAP
      const R2 = o2.r + r + CIRCLE_GAP
      if (d > R1 + R2 || d < Math.abs(R1 - R2) || d === 0) continue
      const aa = (R1 * R1 - R2 * R2 + d * d) / (2 * d)
      const h2 = R1 * R1 - aa * aa
      if (h2 < 0) continue
      const h = Math.sqrt(h2)
      const xm = o1.x + (aa * (o2.x - o1.x)) / d
      const ym = o1.y + (aa * (o2.y - o1.y)) / d
      for (const s of [1, -1]) {
        candidates.push({
          x: xm + (s * h * (o2.y - o1.y)) / d,
          y: ym - (s * h * (o2.x - o1.x)) / d,
        })
      }
    }
  }
  for (const o of obstacles) {
    for (let k = 0; k < TANGENT_SAMPLES; k++) {
      const a = (2 * Math.PI * k) / TANGENT_SAMPLES
      candidates.push({
        x: o.x + (o.r + r + CIRCLE_GAP) * Math.cos(a),
        y: o.y + (o.r + r + CIRCLE_GAP) * Math.sin(a),
      })
    }
  }
  let best: { score: [number, number, number]; x: number; y: number } | null = null
  for (const c of candidates) {
    if (!isClear(c.x, c.y, r, placed)) continue
    const score = seatScore(c.x, c.y, r, placed, partners)
    if (best === null || scoreLess(score, best.score)) best = { score, x: c.x, y: c.y }
  }
  return best === null ? null : { x: best.x, y: best.y }
}

/** The rescue seat: a grid scan of the whole space for any
 *  clear seat, scored like a pocket seat. The fallback's net —
 *  the study's pockets are the design; this only guarantees a
 *  floor is never dropped. */
function rescueSeat(
  r: number,
  placed: PlacedCircle[],
  partners?: ReadonlySet<string>,
): { x: number; y: number } | null {
  const container = loadContainer()
  let best: { score: [number, number, number]; x: number; y: number } | null = null
  for (let x = container.minX; x <= container.maxX; x += RESCUE_GRID_STEP) {
    for (let y = container.minY; y <= container.maxY; y += RESCUE_GRID_STEP) {
      if (!isClear(x, y, r, placed)) continue
      const score = seatScore(x, y, r, placed, partners)
      if (best === null || scoreLess(score, best.score)) best = { score, x, y }
    }
  }
  return best === null ? null : { x: best.x, y: best.y }
}

/* ------------------------------------------------------------------ */
/* the packing — relative scaling over the fill ladder                 */
/* ------------------------------------------------------------------ */

interface SizedItem {
  key: string
  weight: number
  share: number
  r: number
  inputIndex: number
}

/** Size a set of circles from their weights under one common
 *  fill: each circle's AREA is its weight's share of the whole,
 *  taken against the space's area — the relative-scaling law,
 *  for floors (weight = rooms) and tasks (weight = estimate
 *  or unit) alike. */
function sizedItems(items: { key: string; weight: number }[], fill: number): SizedItem[] {
  const area = loadContainer().area
  const total = items.reduce((s, f) => s + f.weight, 0)
  return items.map((f, inputIndex) => {
    const share = total > 0 ? f.weight / total : 1 / items.length
    const r = Math.max(Math.sqrt((share * fill * area) / Math.PI), MIN_FLOOR_RADIUS)
    return { key: f.key, weight: f.weight, share, r, inputIndex }
  })
}

/** Placement order: largest first — supports and pockets alike
 *  exist only once the big rooms stand (equal radii keep input
 *  order, as the study's stable sort did). */
function bySizeDesc(sized: SizedItem[]): SizedItem[] {
  return [...sized].sort((a, b) => b.r - a.r || a.inputIndex - b.inputIndex)
}

/** Dependency partners by key, for the task level's seating
 *  preference. Absent at the project level — floors pack
 *  exactly as the study did. */
type PartnerMap = Map<string, ReadonlySet<string>>

/** One packing attempt at a fill: anchor the largest, then
 *  seat each next circle in its tightest pocket — at the task
 *  level, preferring a seat beside its dependency partners.
 *  Null when any circle finds no pocket. */
function tryPack(sized: SizedItem[], partnersByKey?: PartnerMap): PlacedCircle[] | null {
  const order = bySizeDesc(sized)
  const placed: PlacedCircle[] = []
  for (let i = 0; i < order.length; i++) {
    const f = order[i]
    const seat = i === 0 ? anchorSeat(f.r) : pocketSeat(f.r, placed, partnersByKey?.get(f.key))
    if (seat === null) return null
    placed.push({
      key: f.key,
      weight: f.weight,
      share: f.share,
      inputIndex: f.inputIndex,
      x: seat.x,
      y: seat.y,
      r: f.r,
    })
  }
  return placed
}

/** The fallback attempt at the lowest fill: the whole set
 *  scaled down together by 0.9 steps — one common scale, so
 *  proportions never change — until every floor seats in its
 *  pocket; behind the last scale, a per-floor rescue scan.
 *  Every floor placed, contained and separated, never dropped. */
function fallbackPack(
  items: { key: string; weight: number }[],
  partnersByKey?: PartnerMap,
): PlacedCircle[] | null {
  for (let k = 0; k <= FALLBACK_MAX_SCALES; k++) {
    const scale = FALLBACK_SCALE ** k
    const sized = sizedItems(items, FILL_BOTTOM).map((f) => ({ ...f, r: f.r * scale }))
    const placed = tryPack(sized, partnersByKey)
    if (placed) return placed
  }
  // The last resort: at the smallest common scale, seat each
  // circle in its pocket or, failing that, anywhere clear.
  const scale = FALLBACK_SCALE ** FALLBACK_MAX_SCALES
  const sized = sizedItems(items, FILL_BOTTOM).map((f) => ({ ...f, r: f.r * scale }))
  const order = bySizeDesc(sized)
  const placed: PlacedCircle[] = []
  for (let i = 0; i < order.length; i++) {
    const f = order[i]
    const partners = partnersByKey?.get(f.key)
    const seat =
      (i === 0 ? anchorSeat(f.r) : pocketSeat(f.r, placed, partners)) ??
      rescueSeat(f.r, placed, partners)
    if (seat === null) return null
    placed.push({
      key: f.key,
      weight: f.weight,
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
      roomCount: p.weight,
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
 *  room-circles in the dome's whole space, spaced in the
 *  relaxed Apollonian fashion. An empty building plans as the
 *  empty space and the hearth alone. */
export function planBuildingScene(floors: Scene2FloorInput[]): BuildingSceneLayout {
  if (floors.length === 0) {
    return { floors: [], hearth: { x: HEARTH.x, y: HEARTH.y, r: HEARTH_R }, fillUsed: FILL_TOP }
  }
  const items = floors.map((f) => ({ key: f.key, weight: f.roomCount }))
  // The ladder: the first fill at which every floor seats in
  // its pocket is the largest composition the spacing finds.
  for (const fill of FILL_LADDER) {
    const placed = tryPack(sizedItems(items, fill))
    if (placed) return finishLayout(placed, fill)
  }
  // The safety net: the lowest fill's best attempt — the whole
  // set scaled together, the rescue scan behind the pockets —
  // never drop a floor, never lose access.
  const fallback = fallbackPack(items)
  if (fallback) return finishLayout(fallback, FILL_BOTTOM)
  // Unreachable: at the last scale the circles are a few units
  // wide and seat anywhere in the space. Fail loudly rather
  // than place a floor outside the law.
  throw new Error('Palace Scene 2: no lawful placement for the building’s floors')
}

/** Plan the task level: a project's tasks as circles in the
 *  same dome, under the same spacing law, their recorded
 *  dependency pairs shaping the seating — partners as
 *  neighbours where the packing can achieve it, and the pairs
 *  it could not seat adjacent reported as `links` for the
 *  scene to draw. Pairs naming a task outside the set, a task
 *  paired with itself, and duplicate pairs are set aside:
 *  only pairs of standing circles can sit together or be
 *  joined by a line. */
export function planTaskScene(tasks: Scene2TaskInput[], pairs: TaskLinkPair[]): TaskSceneLayout {
  const hearth = { x: HEARTH.x, y: HEARTH.y, r: HEARTH_R }
  if (tasks.length === 0) {
    return { tasks: [], hearth, fillUsed: FILL_TOP, adjacent: [], links: [] }
  }
  const keys = new Set(tasks.map((t) => t.key))
  const seen = new Set<string>()
  const cleanPairs: TaskLinkPair[] = []
  for (const p of pairs) {
    if (p.aKey === p.bKey || !keys.has(p.aKey) || !keys.has(p.bKey)) continue
    const [aKey, bKey] = p.aKey < p.bKey ? [p.aKey, p.bKey] : [p.bKey, p.aKey]
    const id = `${aKey}|${bKey}`
    if (seen.has(id)) continue
    seen.add(id)
    cleanPairs.push({ aKey, bKey })
  }
  cleanPairs.sort((a, b) => (a.aKey < b.aKey ? -1 : a.aKey > b.aKey ? 1 : a.bKey < b.bKey ? -1 : 1))
  const partnersByKey: PartnerMap = new Map()
  for (const p of cleanPairs) {
    for (const [k, other] of [
      [p.aKey, p.bKey],
      [p.bKey, p.aKey],
    ] as const) {
      const set = new Set(partnersByKey.get(k) ?? [])
      set.add(other)
      partnersByKey.set(k, set)
    }
  }
  const items = tasks.map((t) => ({ key: t.key, weight: t.weight }))
  let placed: PlacedCircle[] | null = null
  let fillUsed = FILL_BOTTOM
  for (const fill of FILL_LADDER) {
    placed = tryPack(sizedItems(items, fill), partnersByKey)
    if (placed) {
      fillUsed = fill
      break
    }
  }
  if (!placed) {
    placed = fallbackPack(items, partnersByKey)
    fillUsed = FILL_BOTTOM
  }
  if (!placed) {
    throw new Error('Palace Scene 2: no lawful placement for the project’s tasks')
  }
  const ranked = [...placed].sort((a, b) => b.r - a.r || a.inputIndex - b.inputIndex)
  const byKey = new Map(ranked.map((p) => [p.key, p]))
  const adjacent: TaskLinkPair[] = []
  const links: TaskLinkPair[] = []
  for (const p of cleanPairs) {
    const a = byKey.get(p.aKey)!
    const b = byKey.get(p.bKey)!
    ;(areAdjacent(a, b) ? adjacent : links).push(p)
  }
  return {
    tasks: ranked.map((p) => ({
      key: p.key,
      weight: p.weight,
      share: p.share,
      x: p.x,
      y: p.y,
      r: p.r,
    })),
    hearth,
    fillUsed,
    adjacent,
    links,
  }
}

/** The room plate of one floor, read off the SAME plan the
 *  building scene renders: a room takes the chamber of the floor
 *  it belongs to (founder, 2026-11-26 18:55 PT). The plan is the
 *  assignment — shared, never re-derived. Unresolvable — an
 *  empty building, an unknown key, a plan that cannot seat —
 *  reads as the rose chamber, the plate the room's seats were
 *  first tuned on. */
export function plateForFloor(floors: Scene2FloorInput[], key: string): RoomPlate {
  if (floors.length === 0) return 'rose'
  try {
    return planBuildingScene(floors).floors.find((f) => f.key === key)?.plate ?? 'rose'
  } catch {
    return 'rose'
  }
}
