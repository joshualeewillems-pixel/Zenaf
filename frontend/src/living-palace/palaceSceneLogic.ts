/**
 * Palace Scene 1 — the placement law, ported to TypeScript.
 *
 * The compound layer's ground is the founder's three-court plan
 * (assets/palace-plan.jpg). Buildings stand in it under the law the
 * founder ruled across 2026-11-26 09:37–09:51 PT and the study
 * builder (rendering-test-assets/maeve-palace-study/scene-1/
 * build_study_v16.py) implements — this module is that law's port,
 * and the invariants, not the study's coordinates, are the
 * contract (live data differs):
 *
 *   - each courtyard's ground is the art-derived polygon in
 *     assets/palace-geometry.json; a building belongs to a court by
 *     where its FOUNDATION stands;
 *   - the foundation (the plinth ellipse: rx = 0.5 × plinth × w,
 *     ry = rx × 0.62, centre one ry above the image's bottom edge)
 *     must lie wholly inside the court's usable ground (the court's
 *     ground minus stonework keepout minus gate discs, with the
 *     uniform 3px clearance already applied in the asset);
 *   - foundations never touch each other: pairwise separation by
 *     normalised ellipse distance with an 8px gap;
 *   - layout is a deterministic maximin packing — largest first,
 *     no randomness, no pull to the centre — so buildings occupy
 *     the whole interior, upper and lower arcs alike;
 *   - projection is separate from collision: draw order is
 *     foundation depth (base_y ascending); silhouettes may cross
 *     paths and overlap — that is occlusion, not collision.
 *
 * Class comes from nested count (founder, 2026-11-26 00:31 PT:
 * size varies "depending on how many nested projects"): big ≥ 8,
 * medium 3–7, small ≤ 2. Courts are dealt the buildings
 * largest-first (top, left, right, top, …), then each court packs
 * its own by the law.
 *
 * Yield: a building first tries its ladder size and yields by
 * ×0.93 steps to the 0.64 floor, exactly as the study does. Live
 * data can be denser than any study, so below the floor the port
 * keeps yielding (to 0.40, then with a halved gap, then without
 * the gap, then by containment alone) rather than dropping a
 * building silently — containment is never relaxed. Every live
 * shape the tests exercise places under the strict law; the
 * relaxed phases are a documented safety net, not the design.
 */
import geometryJson from './assets/palace-geometry.json'
import { SEAT_COLORS, type SeatId } from '../council/colors'

/* ------------------------------------------------------------------ */
/* geometry asset                                                      */
/* ------------------------------------------------------------------ */

export type PalaceCourtId = 'top' | 'left' | 'right'
export type PalaceClassId = 'big' | 'medium' | 'small'

export const COURT_ORDER: PalaceCourtId[] = ['top', 'left', 'right']

export interface PalaceGeometry {
  width: number
  height: number
  /** Plinth fraction per class (the asset's key for small is the
   *  master set's name, "single"). */
  plinths: Record<PalaceClassId, number>
  /** Decoded usable-ground mask per court (1 = a foundation may
   *  stand on this pixel). */
  usable: Record<PalaceCourtId, Uint8Array>
  polygons: Record<PalaceCourtId, [number, number][]>
}

interface GeometryJsonShape {
  width: number
  height: number
  plinths: { single: number; medium: number; big: number }
  usableRle: Record<PalaceCourtId, number[]>
  polygons: Record<PalaceCourtId, [number, number][]>
}

/** Decode a row-major run-length mask: runs alternate, starting
 *  with the count of leading 0 pixels (possibly 0). */
export function decodeRle(rle: number[], width: number, height: number): Uint8Array {
  const out = new Uint8Array(width * height)
  let pos = 0
  let value = 0
  for (const run of rle) {
    if (value === 1) out.fill(1, pos, Math.min(pos + run, out.length))
    pos += run
    value = value === 0 ? 1 : 0
  }
  return out
}

function loadGeometry(): PalaceGeometry {
  const g = geometryJson as unknown as GeometryJsonShape
  return {
    width: g.width,
    height: g.height,
    plinths: { big: g.plinths.big, medium: g.plinths.medium, small: g.plinths.single },
    usable: {
      top: decodeRle(g.usableRle.top, g.width, g.height),
      left: decodeRle(g.usableRle.left, g.width, g.height),
      right: decodeRle(g.usableRle.right, g.width, g.height),
    },
    polygons: g.polygons,
  }
}

export const PALACE_GEOMETRY: PalaceGeometry = loadGeometry()

/* ------------------------------------------------------------------ */
/* the masters (grey-ivy asset set, founder-supplied 2026-11-26)       */
/* ------------------------------------------------------------------ */

/** Natural pixel dimensions of the nine masters — the placement
 *  law needs each building's aspect before any image loads. */
export const MASTER_DIMS: Record<PalaceClassId, Record<1 | 2 | 3, { w: number; h: number }>> = {
  big: { 1: { w: 768, h: 755 }, 2: { w: 768, h: 780 }, 3: { w: 768, h: 781 } },
  medium: { 1: { w: 768, h: 813 }, 2: { w: 768, h: 812 }, 3: { w: 768, h: 837 } },
  small: { 1: { w: 768, h: 859 }, 2: { w: 768, h: 896 }, 3: { w: 768, h: 838 } },
}

export function masterAspect(klass: PalaceClassId, stage: 1 | 2 | 3): number {
  const d = MASTER_DIMS[klass][stage]
  return d.h / d.w
}

/* ------------------------------------------------------------------ */
/* classes, ladder, constants                                          */
/* ------------------------------------------------------------------ */

/** Class thresholds on nested count — one place, per the brief. */
export const CLASS_MIN_BIG = 8
export const CLASS_MIN_MEDIUM = 3

export function classForNestedCount(nestedCount: number): PalaceClassId {
  if (nestedCount >= CLASS_MIN_BIG) return 'big'
  if (nestedCount >= CLASS_MIN_MEDIUM) return 'medium'
  return 'small'
}

/** Ladder widths per class; the index is the building's occurrence
 *  number within its court and class, capped at the last rung. */
export const LADDER: Record<PalaceClassId, number[]> = {
  big: [198, 184, 170],
  medium: [136, 126, 116],
  small: [88, 80, 72],
}

/** The far court projects smaller (the art's own depth). */
export const COURT_DEPTH: Record<PalaceCourtId, number> = { top: 0.8, left: 1, right: 1 }

export const GRID_STEP = 6
export const GAP = 8
export const YIELD_FLOOR = 0.64
export const YIELD_STEP = 0.93
/** Plan squash of the foundation ellipse (the art's oblique). */
export const FOOTPRINT_SQUASH = 0.62

/* ------------------------------------------------------------------ */
/* exact Euclidean distance transform (Felzenszwalb–Huttenlocher)      */
/* ------------------------------------------------------------------ */

/** "Infinity" for the EDT: a large FINITE sentinel (real squared
 *  distances here are ≤ ~2.2e6), so the parabola arithmetic never
 *  meets Inf − Inf on a line with no zero pixel. */
const EDT_INF = 1e12

function edt1d(f: Float64Array, n: number, d: Float64Array, v: Int32Array, z: Float64Array): void {
  let k = 0
  v[0] = 0
  z[0] = -Infinity
  z[1] = Infinity
  for (let q = 1; q < n; q++) {
    let s = (f[q] + q * q - (f[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k])
    while (s <= z[k]) {
      k--
      s = (f[q] + q * q - (f[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k])
    }
    k++
    v[k] = q
    z[k] = s
    z[k + 1] = Infinity
  }
  let kk = 0
  for (let q = 0; q < n; q++) {
    while (z[kk + 1] < q) kk++
    d[q] = (q - v[kk]) * (q - v[kk]) + f[v[kk]]
  }
}

/** Distance from every pixel to the nearest 0 pixel of the mask —
 *  the study's scipy distance_transform_edt, exactly. */
export function distanceTransform(mask: Uint8Array, width: number, height: number): Float64Array {
  const n = width * height
  const g = new Float64Array(n)
  for (let i = 0; i < n; i++) g[i] = mask[i] === 0 ? 0 : EDT_INF
  const v = new Int32Array(Math.max(width, height))
  const z = new Float64Array(Math.max(width, height) + 1)
  const col = new Float64Array(height)
  const colOut = new Float64Array(height)
  // columns
  for (let x = 0; x < width; x++) {
    for (let y = 0; y < height; y++) col[y] = g[y * width + x]
    edt1d(col, height, colOut, v, z)
    for (let y = 0; y < height; y++) g[y * width + x] = colOut[y]
  }
  // rows
  const row = new Float64Array(width)
  const rowOut = new Float64Array(width)
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) row[x] = g[y * width + x]
    edt1d(row, width, rowOut, v, z)
    for (let x = 0; x < width; x++) g[y * width + x] = Math.sqrt(rowOut[x])
  }
  return g
}

/* ------------------------------------------------------------------ */
/* foundation containment (exact pixel test, via integral image)       */
/* ------------------------------------------------------------------ */

/** Summed-area table of the court's NOT-usable pixels. */
export function buildIntegral(mask: Uint8Array, width: number, height: number): Float64Array {
  const ii = new Float64Array((width + 1) * (height + 1))
  for (let y = 0; y < height; y++) {
    let rowSum = 0
    for (let x = 0; x < width; x++) {
      rowSum += mask[y * width + x] === 0 ? 1 : 0
      ii[(y + 1) * (width + 1) + (x + 1)] = ii[y * (width + 1) + (x + 1)] + rowSum
    }
  }
  return ii
}

function rectSum(ii: Float64Array, width: number, x0: number, y0: number, x1: number, y1: number): number {
  // inclusive pixel range [x0..x1] × [y0..y1]
  const w1 = width + 1
  return (
    ii[(y1 + 1) * w1 + (x1 + 1)] - ii[y0 * w1 + (x1 + 1)] - ii[(y1 + 1) * w1 + x0] + ii[y0 * w1 + x0]
  )
}

/** The study's ellipse_ok, pixel-exact: every integer pixel of the
 *  foundation ellipse must be usable ground. */
export function ellipseContained(
  ii: Float64Array,
  width: number,
  height: number,
  cx: number,
  cy: number,
  rx: number,
  ry: number,
): boolean {
  const yLo = Math.ceil(cy - ry)
  const yHi = Math.floor(cy + ry)
  if (yLo < 0 || yHi >= height) return false
  for (let gy = yLo; gy <= yHi; gy++) {
    const t = (gy - cy) / ry
    const dx = rx * Math.sqrt(Math.max(0, 1 - t * t))
    const xLo = Math.ceil(cx - dx)
    const xHi = Math.floor(cx + dx)
    if (xLo < 0 || xHi >= width) return false
    if (rectSum(ii, width, xLo, gy, xHi, gy) > 0) return false
  }
  return true
}

/** Independent pixel-exact containment check against a raw mask —
 *  the verification form the tests pin (no integral image). */
export function ellipseContainedInMask(
  mask: Uint8Array,
  width: number,
  height: number,
  cx: number,
  cy: number,
  rx: number,
  ry: number,
): boolean {
  const yLo = Math.floor(cy - ry) - 1
  const yHi = Math.ceil(cy + ry) + 1
  const xLo = Math.floor(cx - rx) - 1
  const xHi = Math.ceil(cx + rx) + 1
  if (xLo < 0 || yLo < 0 || xHi >= width || yHi >= height) return false
  for (let gy = yLo; gy <= yHi; gy++) {
    for (let gx = xLo; gx <= xHi; gx++) {
      const nx = (gx - cx) / rx
      const ny = (gy - cy) / ry
      if (nx * nx + ny * ny <= 1 && mask[gy * width + gx] === 0) return false
    }
  }
  return true
}

/* ------------------------------------------------------------------ */
/* the packing                                                         */
/* ------------------------------------------------------------------ */

export interface SceneStructureInput {
  /** Stable unique key (e.g. "initiative:<id>", "project:<id>"). */
  key: string
  entityType: 'initiative' | 'project'
  entityId: string
  title: string
  /** Floors (projects) for an initiative, rooms (tasks) for a
   *  project — the count the class reads. */
  nestedCount: number
  /** Image height / width of the master this building will wear. */
  aspect: number
}

export interface PlacedStructure extends SceneStructureInput {
  court: PalaceCourtId
  klass: PalaceClassId
  /** Image box in plan coordinates: (bx, by) is the bottom-centre
   *  (the foundation's ground point); the image spans w × h above
   *  and around it. */
  bx: number
  by: number
  w: number
  h: number
  /** Foundation ellipse. */
  fcx: number
  fcy: number
  rx: number
  ry: number
  /** The yield the packing settled at (1 = full ladder size). */
  scaleUsed: number
}

interface CourtPacker {
  mask: Uint8Array
  integral: Float64Array
  edt: Float64Array
  minX: number
  maxX: number
  minY: number
  maxY: number
  placed: { bx: number; fcy: number; rx: number; ry: number }[]
}

function makePacker(geom: PalaceGeometry, court: PalaceCourtId): CourtPacker {
  const mask = geom.usable[court]
  const { width, height } = geom
  let minX = width
  let minY = height
  let maxX = -1
  let maxY = -1
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      if (mask[y * width + x] === 1) {
        if (x < minX) minX = x
        if (x > maxX) maxX = x
        if (y < minY) minY = y
        if (y > maxY) maxY = y
      }
    }
  }
  return {
    mask,
    integral: buildIntegral(mask, width, height),
    edt: distanceTransform(mask, width, height),
    minX,
    maxX,
    minY,
    maxY,
    placed: [],
  }
}

/** One candidate scan at one scale and gap — the study's inner
 *  loop: the contained, separated candidate with the most slack
 *  (min of boundary distance and neighbour slack); first maximum
 *  in scan order wins, so the result is deterministic. */
function scanCandidate(
  packer: CourtPacker,
  geom: PalaceGeometry,
  rx: number,
  ry: number,
  gap: number,
  separation: boolean,
): { bx: number; by: number; fcy: number } | null {
  const { width } = geom
  let best: { slack: number; bx: number; by: number; fcy: number } | null = null
  for (let by = packer.minY; by <= packer.maxY; by += GRID_STEP) {
    for (let bx = packer.minX; bx <= packer.maxX; bx += GRID_STEP) {
      const fcy = by - ry
      // Cheap exact prune: the foundation's centre pixel is itself
      // inside the ellipse, so containment already fails here.
      const cxPx = Math.floor(bx)
      const cyPx = Math.floor(fcy)
      if (cyPx < 0 || cyPx >= geom.height || packer.mask[cyPx * width + cxPx] !== 1) continue
      if (!ellipseContained(packer.integral, width, geom.height, bx, fcy, rx, ry)) continue
      let slack = packer.edt[cyPx * width + cxPx]
      let ok = true
      if (separation) {
        for (const p of packer.placed) {
          const dn =
            ((bx - p.bx) / (rx + p.rx + gap)) ** 2 +
            ((fcy - p.fcy) / (ry + p.ry + gap * FOOTPRINT_SQUASH)) ** 2
          if (dn < 1) {
            ok = false
            break
          }
          slack = Math.min(slack, Math.hypot(bx - p.bx, fcy - p.fcy) - (rx + p.rx))
        }
      }
      if (!ok) continue
      if (best === null || slack > best.slack) best = { slack, bx, by, fcy }
    }
  }
  return best
}

function packOne(
  packer: CourtPacker,
  geom: PalaceGeometry,
  court: PalaceCourtId,
  input: SceneStructureInput,
  klass: PalaceClassId,
  ladderIndex: number,
): PlacedStructure {
  const plinth = geom.plinths[klass]
  const baseW = LADDER[klass][Math.min(ladderIndex, LADDER[klass].length - 1)] * COURT_DEPTH[court]
  // Yield phases: the study's law first (floor 0.64, full gap),
  // then the documented safety net — containment never relaxes.
  const phases: { from: number; to: number; gap: number; separation: boolean }[] = [
    { from: 1, to: YIELD_FLOOR, gap: GAP, separation: true },
    { from: YIELD_FLOOR, to: 0.4, gap: GAP, separation: true },
    { from: 0.4, to: 0.28, gap: GAP / 2, separation: true },
    { from: 0.28, to: 0.15, gap: 0, separation: true },
    { from: 0.15, to: 0.15, gap: 0, separation: false },
  ]
  for (const phase of phases) {
    let scale = phase.from
    for (;;) {
      const w = baseW * scale
      const h = w * input.aspect
      const rx = 0.5 * plinth * w
      const ry = rx * FOOTPRINT_SQUASH
      const found = scanCandidate(packer, geom, rx, ry, phase.gap, phase.separation)
      if (found) {
        packer.placed.push({ bx: found.bx, fcy: found.fcy, rx, ry })
        return {
          ...input,
          court,
          klass,
          bx: found.bx,
          by: found.by,
          w,
          h,
          fcx: found.bx,
          fcy: found.fcy,
          rx,
          ry,
          scaleUsed: scale,
        }
      }
      if (scale <= phase.to) break
      scale = Math.max(phase.to, scale * YIELD_STEP)
      if (scale === phase.from) break
    }
  }
  // Unreachable for any building that fits the court's ground at
  // all (a 0.15-scale foundation is ~30px wide; every court's
  // deepest ground is far wider). Fail loudly rather than place
  // a building outside the law.
  throw new Error(`Palace Scene 1: no lawful placement for ${input.key} in court ${court}`)
}

/** Deal the structures largest-first across the courts and pack
 *  each court by the law. Returns placements in foundation-depth
 *  order (base_y ascending) — the render order. */
export function planCompoundScene(
  structures: SceneStructureInput[],
  geom: PalaceGeometry = PALACE_GEOMETRY,
): PlacedStructure[] {
  const sorted = [...structures].sort(
    (a, b) =>
      b.nestedCount - a.nestedCount ||
      a.title.localeCompare(b.title) ||
      a.key.localeCompare(b.key),
  )
  const dealt: Record<PalaceCourtId, SceneStructureInput[]> = { top: [], left: [], right: [] }
  sorted.forEach((s, i) => {
    dealt[COURT_ORDER[i % COURT_ORDER.length]].push(s)
  })
  const placements: PlacedStructure[] = []
  for (const court of COURT_ORDER) {
    const packer = makePacker(geom, court)
    const occurrence: Record<PalaceClassId, number> = { big: 0, medium: 0, small: 0 }
    for (const input of dealt[court]) {
      const klass = classForNestedCount(input.nestedCount)
      const placed = packOne(packer, geom, court, input, klass, occurrence[klass])
      occurrence[klass] += 1
      placements.push(placed)
    }
  }
  return placements.sort((a, b) => a.by - b.by || a.key.localeCompare(b.key))
}

/* ------------------------------------------------------------------ */
/* ivy — stage and hue from recorded seat interaction                  */
/* ------------------------------------------------------------------ */

export interface SubjectInteraction {
  entity_type: string
  entity_id: string
  total: number
  per_seat: Record<string, number>
}

/** The ivy's natural green when no seat has talked about a
 *  subject (and the masters' grey ivy's resting colour). */
export const NATURAL_IVY_GREEN = '#6f9a52'

/** Stage thresholds — one place, per the brief. */
export function ivyStageFor(total: number): 1 | 2 | 3 {
  if (total >= 5) return 3
  if (total >= 1) return 2
  return 1
}

/** The dominant interacting seat's colour; ties break by seat id
 *  so the choice is deterministic. No recorded interaction (or no
 *  known seat) → natural green. */
export function ivyColorFor(interaction: SubjectInteraction | undefined): string {
  if (!interaction) return NATURAL_IVY_GREEN
  let bestSeat: string | null = null
  let bestCount = 0
  for (const seat of Object.keys(interaction.per_seat).sort()) {
    const count = interaction.per_seat[seat]
    if (count > bestCount && seat in SEAT_COLORS) {
      bestSeat = seat
      bestCount = count
    }
  }
  return bestSeat ? SEAT_COLORS[bestSeat as SeatId] : NATURAL_IVY_GREEN
}

export function interactionKey(entityType: string, entityId: string): string {
  return `${entityType}:${entityId}`
}

export function indexInteractions(
  interactions: SubjectInteraction[] | null | undefined,
): Map<string, SubjectInteraction> {
  const map = new Map<string, SubjectInteraction>()
  for (const s of interactions ?? []) {
    map.set(interactionKey(s.entity_type, s.entity_id), s)
  }
  return map
}
