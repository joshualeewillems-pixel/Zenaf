/**
 * cairnTower — the ported cairn layout engine (founder's cairn spec,
 * accepted 2026-11-13; studies: cairn-algorithm-study v3.5 +
 * cairn-growth-study Parts 1-2). This module is the consolidation of
 * the three lineages into the existing cairn machinery — no parallel
 * engine, no new state store: a pure function of (cairn id, members).
 *
 * APRIL spine (NestGroupNode.tsx / nesting.ts, first commit): semantic
 * order for initial construction, controlled oscillation (strict L/R
 * alternation, damped x0.52 stones 1-2, x0.72 stone 3, every 4th
 * re-centres) under a hard leash, chained sizing with progressive
 * taper and April's summit shrink/thinning, deep overlap.
 * OCTOBER (this module's previous life, PR #160): local balance —
 * every consecutive triple's combined centre of mass within the middle
 * 70% of the triple's base stone — and rim accents (count by size,
 * base never hosts, rim opposite the lean).
 * NOVEMBER (the studies): prep-time bearing segments + ONE generic
 * pairing rule (+-12 deg), profile-nested seating, summit discipline,
 * companions, per-cairn temperament from the stable cairn id, and the
 * growth law — "placement is historical; vitality is current":
 * members are seated in arrival order (their entity created_at,
 * recovered by cairn.ts) by the refined seat search (search before
 * fallback, rotation only, never mirroring); existing stones never
 * move; order debt against April's ideal order is computed and
 * disclosed in the layout diagnostics, never silently corrected.
 *
 * Determinism (spec section 1): every per-stone random draw is keyed
 * by the STABLE MEMBER ID, never by stack position, so inserting a
 * member cannot change another member's sprite, size character or
 * tint. Temperament derives from the stable cairn id only.
 *
 * The dedicated slab (April 276x132, spec section 5) is column
 * position 0: structural support in the stability model — the first
 * member is seated on its measured geometry by the same generic rule.
 * It is never a member and never hosts accents.
 *
 * All geometry is computed in April units (base width 276) against
 * the sprites' measured alpha (cairnSprites.ts), then fit-scaled to
 * the production fit box (150x240) CairnNode has always used.
 */

import {
  CAIRN_SPRITES,
  SLAB_SPRITE,
  UPPER_POOL,
  UPPER_POOL_EXT,
  type CairnSegment,
  type CairnSprite,
} from './cairnSprites'
import { CAIRN_STAINS, type StrandKey } from '../council/colors'
import type { GrowthState } from './ontology'

/* ================= public types ================= */

export type CairnMemberInput = {
  /** Stable member id (the member's map node id). Keys every draw. */
  id: string
  /** Map entity kind — April's structural kinds get base preference. */
  kind: string
  /** April activity score (nesting.ts activityScore), current value. */
  activity: number
  /** Entity creation time (ISO) — the member's arrival. Null = unknown. */
  createdAt: string | null
  /** Lifecycle growth state, carried on the member record. Placement
      never reads it (vitality is current, placement is historical),
      and the pile renderer no longer paints it on the stone — on-stone
      glyph marks were removed by founder ruling, 2026-11-13. */
  growth?: GrowthState
  /** The member's own strand weight vector (strand keys → weights), as
      surfaced by the vision-map projection. Null/absent = unweighed —
      the member renders grayscale (unknown is honest, never zero). The
      vector keys the member's stain colour only; placement never reads
      it (identity is permanent, arrangement historical). */
  weights?: CairnStrandWeights | null
}

/** A member's strand weight vector, keyed by strand taxonomy key. */
export type CairnStrandWeights = Partial<Record<StrandKey, number>>

export type PortedStone = {
  /** Frame box in fitted px (the sprite raster's full frame). */
  left: number
  top: number
  width: number
  height: number
  rotation: number
  /** Transform origin (the stone body's centre) inside the frame box, px. */
  originX: number
  originY: number
  sprite: string
  spriteUrl: string
  tint: string
  role: 'slab' | 'column' | 'accent' | 'leaner' | 'wedge'
  /** Member id for column stones; null for slab/accents/companions. */
  memberId: string | null
  /** Fitted px size of the stone body (for glyph sizing). */
  bodyWidth: number
  bodyHeight: number
  /** Body centre in fitted px (for glyph placement). */
  bodyCx: number
  bodyCy: number
  seed: string
}

export type CairnInsertionDiagnostic = {
  memberId: string
  /** Sprite the member was assigned (its identity). */
  assignedSprite: string
  /** Sprite actually seated (differs only when the fallback fired). */
  seatedSprite: string
  /** Viable seats the search found for the assigned sprite. */
  viableSeats: number
  /** Exposed cap width (world units) after this insertion. */
  capWidthAfter: number
  /** True when the documented fallback sequence seated the stone. */
  fellBack: boolean
  /** True when no sprite seated and the stone was placed as drawn. */
  exhausted: boolean
}

export type CairnLayoutDiagnostics = {
  /** Blend index 0/1/2 — the cairn's permanent temperament. */
  blend: number
  /** Inversions between the historical build order and April's order. */
  orderDebt: number
  insertions: CairnInsertionDiagnostic[]
  /** Accent/companion drops the discipline rules made, disclosed. */
  dropped: string[]
  /** Triple repairs applied (each moves only the arriving stone). */
  repairs: number
}

export type PortedTowerLayout = {
  /** Paint order: slab, companions, column bottom-up, accents last. */
  stones: PortedStone[]
  width: number
  height: number
  /** Rendered member stones in the column. */
  columnCount: number
  /** Total members (the badge count; may exceed the rendered cap). */
  memberCount: number
  /** Fitted px y of the ground line (the slab's bottom). */
  groundY: number
  /** Fitted px footprint for the garden rings. */
  footprintCx: number
  footprintHalfWidth: number
  diagnostics: CairnLayoutDiagnostics
}

/* ---- legacy shapes (kept for towerDebug consumers) ---- */

export type TowerStone = {
  left: number
  top: number
  size: number
  rotation: number
  previewIndex: number
  seed: string
  accent: boolean
}

export type TowerLayout = {
  stones: TowerStone[]
  width: number
  height: number
  columnCount: number
}

export type TowerBody = {
  x: number
  y: number
  w: number
  h: number
  rot: number
}

export type TowerAccent = TowerBody & {
  host: number
  rimU: number
}

export type TowerDebug = {
  col: TowerBody[]
  accents: TowerAccent[]
  scale: number
}

/** Rendered stones: min(count, 12) — a garden stack gets the full twelve. */
export function towerStoneCount(count: number): number {
  return Math.min(Math.max(Math.floor(count), 1), 12)
}

/** Members actually rendered as column stones (the rest ride the badge). */
export const MAX_COLUMN_MEMBERS = 12

/* ================= constants (the blend gradient) ================= */

type Blend = {
  tag: string
  rotMax: number
  driftLo: number
  driftHi: number
  ovLo: number
  ovHi: number
  ovFloor: number
  ovCap: number
  leash: number
  jitter: number
  onEdgeP: number
}

const BLENDS: Blend[] = [
  { tag: 'grounded', rotMax: 3, driftLo: 0.10, driftHi: 0.17, ovLo: 0.40, ovHi: 0.64, ovFloor: 0.36, ovCap: 0.68, leash: 0.24, jitter: 0, onEdgeP: 0 },
  { tag: 'average', rotMax: 10, driftLo: 0.12, driftHi: 0.22, ovLo: 0.36, ovHi: 0.52, ovFloor: 0.30, ovCap: 0.58, leash: 0.295, jitter: 0.6, onEdgeP: 0 },
  { tag: 'loose', rotMax: 20, driftLo: 0.14, driftHi: 0.26, ovLo: 0.30, ovHi: 0.48, ovFloor: 0.26, ovCap: 0.52, leash: 0.35, jitter: 1.0, onEdgeP: 0.18 },
]

const STRUCTURAL_KINDS = ['tree', 'branch', 'seed']
const BASE_W = 276
const CELL = 3
const PAIR_TOL = 12
const FIT_W = 150
const FIT_H = 240
const NEUTRAL_WASH = '#a8a29e'

/* ================= hashes & small math (April's, verbatim) ================= */

export function hash01(str: string): number {
  let h = 2166136261
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return ((h >>> 0) % 10000) / 10000
}

const clamp = (v: number, lo: number, hi: number): number => Math.max(lo, Math.min(hi, v))

function rotVec(x: number, y: number, deg: number): [number, number] {
  const r = (deg * Math.PI) / 180
  const c = Math.cos(r)
  const s = Math.sin(r)
  return [x * c - y * s, x * s + y * c]
}

/* ================= tints ================= */

function hexToHsl(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16)
  const r = (n >> 16) / 255
  const g = ((n >> 8) & 255) / 255
  const b = (n & 255) / 255
  const mx = Math.max(r, g, b)
  const mn = Math.min(r, g, b)
  let h = 0
  if (mx !== mn) {
    const d = mx - mn
    h = mx === r ? (g - b) / d + (g < b ? 6 : 0) : mx === g ? (b - r) / d + 2 : (r - g) / d + 4
    h *= 60
  }
  const l = (mx + mn) / 2
  const s = mx === mn ? 0 : l > 0.5 ? (mx - mn) / (2 - mx - mn) : (mx - mn) / (mx + mn)
  return [h, s * 100, l * 100]
}

function hslToHex(h: number, s: number, l: number): string {
  h = ((h % 360) + 360) % 360
  s = clamp(s, 0, 100) / 100
  l = clamp(l, 0, 100) / 100
  const c = (1 - Math.abs(2 * l - 1)) * s
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1))
  const m = l - c / 2
  let rgb: [number, number, number] = [0, 0, 0]
  if (h < 60) rgb = [c, x, 0]
  else if (h < 120) rgb = [x, c, 0]
  else if (h < 180) rgb = [0, c, 0]
  else if (h < 240) rgb = [0, x, c]
  else if (h < 300) rgb = [x, 0, c]
  else rgb = [c, 0, x]
  return '#' + rgb.map((v) => Math.round((v + m) * 255).toString(16).padStart(2, '0')).join('')
}

function jitterTint(baseHex: string, key: string, f: number): string {
  if (!f) return baseHex
  const [h, s, l] = hexToHsl(baseHex)
  return hslToHex(
    h + (hash01(key + ':th') - 0.5) * 24 * f,
    s + (hash01(key + ':ts') - 0.5) * 16 * f,
    l + (hash01(key + ':tl') - 0.5) * 20 * f,
  )
}

/* ================= strand blend stains (the Blend ruling) =================
 *
 * Founder's ruling, 2026-11-13: each stone's stain is its OWN strand
 * weight vector mixed in CIELAB over the subdued L2 wood stains
 * (CAIRN_STAINS) — never one wash per pile. The math below ports the
 * colour-comparison sheet's renderer (render-cairn-color-options.py):
 * sRGB → XYZ (D65) → Lab, weighted average by weight, back to sRGB.
 * Unweighed members, fruit, the slab, rim accents and companions carry
 * no stain: they render through NEUTRAL_WASH, which the tint stack
 * reads as grayscale.
 */

function hexToRgb01(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16)
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255]
}

function srgbToLab(rgb: [number, number, number]): [number, number, number] {
  const [r, g, b] = rgb.map((c) => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4))) as [
    number,
    number,
    number,
  ]
  const x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
  const y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
  const z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883
  const f = (t: number) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116)
  const fx = f(x)
  const fy = f(y)
  const fz = f(z)
  return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)]
}

function labToSrgbHex(lab: [number, number, number]): string {
  const [L, a, b] = lab
  const fy = (L + 16) / 116
  const fx = fy + a / 500
  const fz = fy - b / 200
  const inv = (t: number) => {
    const t3 = t * t * t
    return t3 > 0.008856 ? t3 : (t - 16 / 116) / 7.787
  }
  const x = inv(fx) * 0.95047
  const y = inv(fy)
  const z = inv(fz) * 1.08883
  const lin: [number, number, number] = [
    3.2404542 * x - 1.5371385 * y - 0.4985314 * z,
    -0.969266 * x + 1.8760108 * y + 0.041556 * z,
    0.0556434 * x - 0.2040259 * y + 1.0572252 * z,
  ]
  return (
    '#' +
    lin
      .map((c) => {
        const v = c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055
        return Math.round(clamp(v, 0, 1) * 255)
          .toString(16)
          .padStart(2, '0')
      })
      .join('')
  )
}

const STRAND_KEY_ORDER: StrandKey[] = ['word', 'number', 'image', 'sound', 'body', 'people', 'self']

/**
 * The Blend ruling's mix: a strand weight vector → its CIELAB-blended
 * stain hex over CAIRN_STAINS. Null when the vector carries no positive
 * weight (unweighed) — the caller renders the neutral grayscale.
 */
export function blendStainHex(weights: CairnStrandWeights): string | null {
  let sw = 0
  let L = 0
  let A = 0
  let B = 0
  for (const k of STRAND_KEY_ORDER) {
    const w = weights[k]
    if (typeof w !== 'number' || !Number.isFinite(w) || w <= 0) continue
    const lab = srgbToLab(hexToRgb01(CAIRN_STAINS[k]))
    L += lab[0] * w
    A += lab[1] * w
    B += lab[2] * w
    sw += w
  }
  if (sw <= 0) return null
  return labToSrgbHex([L / sw, A / sw, B / sw])
}

/**
 * A member stone's base stain before the member-keyed jitter: its own
 * blend, or the neutral wash when unweighed. Fruit is not a weighable
 * entity type, so fruit stones stay grayscale even if a caller hands
 * them a vector.
 */
function memberBaseTint(member: CairnMemberInput): string {
  if (member.kind === 'fruit' || !member.weights) return NEUTRAL_WASH
  return blendStainHex(member.weights) ?? NEUTRAL_WASH
}

/* ================= stone records ================= */

type StoneRec = {
  sprite: string
  pos: number
  w: number
  h: number
  cx: number
  cy: number
  tilt: number
  scale: number
  tint: string
  fw: number
  fh: number
  mass: number
  fcx: number
  fcy: number
  cenX: number
  cenY: number
  role: 'slab' | 'column' | 'accent' | 'leaner' | 'wedge'
  memberId: string | null
  kind: string | null
  side: number
  onEdge: boolean
  pairOK: boolean
  pair: SegPair | null
  sink: number
  rimSettled: boolean
  overlap: number
  supporter: number
  host: number
  rimU: number
  contact: number
  _cells?: Set<number>
}

function meta(sprite: string): CairnSprite {
  const m = CAIRN_SPRITES[sprite]
  if (!m) throw new Error(`unknown cairn sprite ${sprite}`)
  return m
}

function mkStone(
  sprite: string,
  pos: number,
  w: number,
  h: number,
  cx: number,
  cy: number,
  tilt: number,
  tint: string,
): StoneRec {
  const m = meta(sprite)
  const scale = w / m.bodyW
  const st: StoneRec = {
    sprite,
    pos,
    w,
    h,
    cx,
    cy,
    tilt,
    scale,
    tint,
    fw: m.frame[0] * scale,
    fh: m.frame[1] * scale,
    mass: m.alphaArea * scale * scale,
    fcx: 0,
    fcy: 0,
    cenX: 0,
    cenY: 0,
    role: 'column',
    memberId: null,
    kind: null,
    side: 0,
    onEdge: false,
    pairOK: false,
    pair: null,
    sink: 0,
    rimSettled: false,
    overlap: 0,
    supporter: -1,
    host: -1,
    rimU: 0,
    contact: 0,
  }
  return place(st)
}

function place(st: StoneRec): StoneRec {
  const m = meta(st.sprite)
  const [ox, oy] = rotVec(m.bboxOff[0] * st.scale, m.bboxOff[1] * st.scale, st.tilt)
  st.fcx = st.cx - ox
  st.fcy = st.cy - oy
  const [cox, coy] = rotVec(m.cenOff[0] * st.scale, m.cenOff[1] * st.scale, st.tilt)
  st.cenX = st.fcx + cox
  st.cenY = st.fcy + coy
  st._cells = undefined
  return st
}

/* ================= occupancy & contact (measured alpha) =================
   Perf: a stone's rotated solid-cell offsets and local boundary points
   depend only on (sprite, tilt, scale) — never on position — so they
   are computed once and cached; world values are translations. Pair
   lists depend on the supporter's fixed state + the upper stone's
   (sprite, tilt) — also cached. Placement candidates are numerous;
   these caches are what make the seat search render-grade. */

type RotCache = {
  /** Rotated solid-cell centre offsets from the frame centre. */
  offsets: Array<[number, number]>
  /** Local top/bottom boundary points, relative to the frame centre. */
  topB: Array<[number, number]>
  botB: Array<[number, number]>
}

const rotCache = new Map<string, RotCache>()

function rotCacheFor(st: StoneRec): RotCache {
  const key = `${st.sprite}|${st.tilt.toFixed(2)}|${st.scale.toFixed(4)}`
  const hit = rotCache.get(key)
  if (hit) return hit
  const occ = meta(st.sprite).occ
  const G = 56
  const cw = st.fw / G
  const ch = st.fh / G
  const offsets: Array<[number, number]> = []
  for (let gy = 0; gy < G; gy++) {
    for (let gx = 0; gx < G; gx++) {
      if (occ[gy]![gx] !== '1') continue
      offsets.push(rotVec((gx + 0.5) * cw - st.fw / 2, (gy + 0.5) * ch - st.fh / 2, st.tilt))
    }
  }
  const boundary = (side: 'top' | 'bottom'): Array<[number, number]> => {
    const pts: Array<[number, number]> = []
    for (let gx = 0; gx < G; gx++) {
      let gy = -1
      if (side === 'bottom') {
        for (let y = G - 1; y >= 0; y--) if (occ[y]![gx] === '1') { gy = y; break }
      } else {
        for (let y = 0; y < G; y++) if (occ[y]![gx] === '1') { gy = y; break }
      }
      if (gy < 0) continue
      const lx = (gx + 0.5) * cw - st.fw / 2
      const ly = (gy + 0.5) * ch - st.fh / 2 + (side === 'bottom' ? ch / 2 : -ch / 2)
      pts.push(rotVec(lx, ly, st.tilt))
    }
    return pts.sort((a, b) => a[0] - b[0])
  }
  const entry: RotCache = { offsets, topB: boundary('top'), botB: boundary('bottom') }
  if (rotCache.size > 6000) rotCache.clear()
  rotCache.set(key, entry)
  return entry
}

/** Numeric occupancy-cell key (string keys were the search's hot
    spot): gx in the high part, gy in the low, both biased positive. */
function cellKey(x: number, y: number): number {
  return (Math.floor(x / CELL) + 512) * 4096 + (Math.floor(y / CELL) + 1024)
}

function stoneCells(st: StoneRec): Set<number> {
  if (st._cells) return st._cells
  const { offsets } = rotCacheFor(st)
  const set = new Set<number>()
  for (const [wx, wy] of offsets) {
    set.add(cellKey(st.fcx + wx, st.fcy + wy))
  }
  st._cells = set
  return set
}

function contactCells(a: Set<number>, b: Set<number>): number {
  let n = 0
  for (const k of a) if (b.has(k)) n++
  return n
}

function lowestY(st: StoneRec): number {
  let m = -Infinity
  for (const [ox, oy] of [[-st.w / 2, -st.h / 2], [st.w / 2, -st.h / 2], [st.w / 2, st.h / 2], [-st.w / 2, st.h / 2]] as const) {
    const [, wy] = rotVec(ox, oy, st.tilt)
    m = Math.max(m, st.cy + wy)
  }
  return m
}

function alphaBottom(st: StoneRec): number {
  const m = meta(st.sprite)
  const prof = m.bottomProfile
  const rad = (st.tilt * Math.PI) / 180
  const cs = Math.cos(rad)
  const sn = Math.sin(rad)
  let mx = -Infinity
  for (let k = 0; k < 56; k++) {
    const p = prof[k]
    if (p == null) continue
    const lx = (k + 0.5) / 56 * st.fw - st.fw / 2
    const ly = p * st.scale - st.fh / 2
    mx = Math.max(mx, st.fcy + lx * sn + ly * cs)
  }
  return mx
}

function settleToGround(st: StoneRec, groundY: number): void {
  for (let k = 0; k < 24; k++) {
    const gap = groundY - alphaBottom(st)
    if (gap <= 2.0) break
    st.cy += gap - 1.0
    place(st)
  }
}

function alphaTop(st: StoneRec): number {
  const m = meta(st.sprite)
  const prof = m.topProfile
  const rad = (st.tilt * Math.PI) / 180
  const cs = Math.cos(rad)
  const sn = Math.sin(rad)
  let mn = Infinity
  for (let k = 0; k < 25; k++) {
    const p = prof[k]
    if (p == null) continue
    const lx = (k + 0.5) / 25 * st.fw - st.fw / 2
    const ly = p * st.scale - st.fh / 2
    mn = Math.min(mn, st.fcy + lx * sn + ly * cs)
  }
  return mn
}

function sharedCellStats(
  a: StoneRec,
  b: StoneRec,
): { n: number; cx: number; cy: number; spanX: number; minX: number; maxX: number } {
  const A = stoneCells(a)
  const B = stoneCells(b)
  let n = 0
  let sx = 0
  let sy = 0
  let mnX = Infinity
  let mxX = -Infinity
  for (const k of A) {
    if (!B.has(k)) continue
    const cx = Math.floor(k / 4096) - 512
    const cy = (k % 4096) - 1024
    n++
    sx += cx * CELL + CELL / 2
    sy += cy * CELL + CELL / 2
    mnX = Math.min(mnX, cx * CELL)
    mxX = Math.max(mxX, (cx + 1) * CELL)
  }
  return n ? { n, cx: sx / n, cy: sy / n, spanX: mxX - mnX, minX: mnX, maxX: mxX } : { n: 0, cx: 0, cy: 0, spanX: 0, minX: 0, maxX: 0 }
}

function cellsWidth(st: StoneRec): number {
  const C = stoneCells(st)
  let mn = Infinity
  let mx = -Infinity
  for (const k of C) {
    const cx = Math.floor(k / 4096) - 512
    mn = Math.min(mn, cx)
    mx = Math.max(mx, cx)
  }
  return (mx - mn + 1) * CELL
}

function bottomSpan(st: StoneRec, groundY: number, tol: number): number {
  const m = meta(st.sprite)
  const prof = m.bottomProfile
  const rad = (st.tilt * Math.PI) / 180
  const cs = Math.cos(rad)
  const sn = Math.sin(rad)
  let mn = Infinity
  let mx = -Infinity
  for (let k = 0; k < 56; k++) {
    const p = prof[k]
    if (p == null) continue
    const lx = (k + 0.5) / 56 * st.fw - st.fw / 2
    const ly = p * st.scale - st.fh / 2
    const wx = lx * cs - ly * sn
    const wy = lx * sn + ly * cs
    if (st.fcy + wy >= groundY - tol) {
      mn = Math.min(mn, st.fcx + wx)
      mx = Math.max(mx, st.fcx + wx)
    }
  }
  return mx === -Infinity ? 0 : mx - mn
}

/* ================= October local balance ================= */

function repairTriple(col: StoneRec[], i: number, B: Blend): { n: number; shift: number } {
  const a = col[i - 2]!
  const b = col[i - 1]!
  const st = col[i]!
  const lo = a.cx - 0.35 * a.w
  const hi = a.cx + 0.35 * a.w
  const M = a.mass + b.mass + st.mass
  const off = st.cenX - st.cx
  const x0 = st.cx
  const com = () => (a.mass * a.cenX + b.mass * b.cenX + st.mass * (st.cx + off)) / M
  if (com() >= lo && com() <= hi) return { n: 0, shift: 0 }
  const xLo = Math.max(-B.leash * BASE_W, b.cx - 0.6 * b.w)
  const xHi = Math.min(B.leash * BASE_W, b.cx + 0.6 * b.w)
  for (let it = 0; it < 12; it++) {
    const c = com()
    if (c >= lo && c <= hi) break
    const edge = c < lo ? lo + 0.04 * a.w : hi - 0.04 * a.w
    const need = (edge * M - a.mass * a.cenX - b.mass * b.cenX) / st.mass - off
    let nx = clamp(need, xLo, xHi)
    if (Math.abs(nx - st.cx) < 1e-9) nx = st.cx + (b.cx - st.cx) * 0.5
    st.cx = nx
    place(st)
  }
  if (com() < lo || com() > hi) {
    st.cx = b.cx
    place(st)
  }
  return { n: 1, shift: Math.abs(st.cx - x0) }
}

function triplesOK(trial: StoneRec[]): boolean {
  for (let k = 2; k < trial.length; k++) {
    const a = trial[k - 2]!
    const b = trial[k - 1]!
    const c = trial[k]!
    const M = a.mass + b.mass + c.mass
    const com = (a.mass * a.cenX + b.mass * b.cenX + c.mass * c.cenX) / M
    if (com < a.cx - 0.35 * a.w || com > a.cx + 0.35 * a.w) return false
  }
  return true
}

/* ================= bearing segments: ONE generic rule =================
   Every sprite carries prep-time segment metadata (scripts/
   prep-cairn-sprites.py): runs of roughly constant slope along each
   side's measured alpha profile. A stone may rest only where a segment
   of its bearing side is angle-compatible (within PAIR_TOL) with a
   segment of the supporter's up-facing side AND the stone's centre
   falls inside that segment's world span. No per-sprite rules: flat
   stones degenerate to one wide near-flat segment and pair trivially;
   the faceted shard pairs only where a facet genuinely matches. */

type SegPair = {
  t: CairnSegment
  b: CairnSegment
  tA: number
  bA: number
  dA: number
  tS: [number, number]
  score: number
}

function normAng(a: number): number {
  while (a > 90) a -= 180
  while (a <= -90) a += 180
  return a
}
function angDiff(a: number, b: number): number {
  return Math.abs(normAng(a - b))
}
function downSide(tilt: number): 'top' | 'bottom' | 'left' | 'right' {
  const a = ((tilt % 360) + 360) % 360
  return a < 45 || a >= 315 ? 'bottom' : a < 135 ? 'right' : a < 225 ? 'top' : 'left'
}
const upSide = (tilt: number) => downSide(tilt + 180)

function segSpanWorld(seg: CairnSegment, st: StoneRec): [number, number] {
  const m = meta(st.sprite)
  const W = m.frame[0]
  const px = (x: number, y: number) => {
    const [rx] = rotVec((x - W / 2) * st.scale, (y - m.frame[1] / 2) * st.scale, st.tilt)
    return st.fcx + rx
  }
  const a = px(seg.x0, seg.y0)
  const b = px(seg.x1, seg.y1)
  return [Math.min(a, b), Math.max(a, b)]
}

const pairCache = new WeakMap<StoneRec, Map<string, SegPair[]>>()

function allPairs(L: StoneRec, U: StoneRec): SegPair[] {
  const key = `${L.tilt.toFixed(2)}|${L.scale.toFixed(4)}|${L.fcx.toFixed(1)}|${L.fcy.toFixed(1)}|${U.sprite}|${U.tilt.toFixed(2)}|${U.scale.toFixed(4)}`
  let byKey = pairCache.get(L)
  if (!byKey) {
    byKey = new Map()
    pairCache.set(L, byKey)
  }
  const hit = byKey.get(key)
  if (hit) return hit
  const up = meta(L.sprite).segments[upSide(L.tilt)] || []
  const dn = meta(U.sprite).segments[downSide(U.tilt)] || []
  const out: SegPair[] = []
  for (const t of up) {
    const tA = normAng(t.ang + L.tilt)
    const tS = segSpanWorld(t, L)
    for (const b of dn) {
      const bA = normAng(b.ang + U.tilt)
      out.push({ t, b, tA, bA, dA: angDiff(tA, bA), tS, score: t.span * b.span })
    }
  }
  out.sort((a, b) => b.score - a.score)
  if (byKey.size > 512) byKey.clear()
  byKey.set(key, out)
  return out
}

/** Count of a stone's cells present in another stone's cell set,
    early-exiting at `cap` (the search gates only need small counts). */
function contactCountUpTo(a: StoneRec, bCells: Set<number>, cap: number): number {
  const { offsets } = rotCacheFor(a)
  const seen = new Set<number>()
  let n = 0
  for (const [wx, wy] of offsets) {
    const k = cellKey(a.fcx + wx, a.fcy + wy)
    if (seen.has(k)) continue
    seen.add(k)
    if (bCells.has(k)) {
      n++
      if (n >= cap) return n
    }
  }
  return n
}

function findPair(L: StoneRec, U: StoneRec): SegPair | null {
  return allPairs(L, U).find((p) => p.dA <= PAIR_TOL && U.cx >= p.tS[0] - 1.5 && U.cx <= p.tS[1] + 1.5) || null
}
function findPairOn(L: StoneRec, U: StoneRec, seg: CairnSegment): SegPair | null {
  return allPairs(L, U).find((p) => p.t === seg && p.dA <= PAIR_TOL && U.cx >= p.tS[0] - 1.5 && U.cx <= p.tS[1] + 1.5) || null
}

function centralTopSegs(L: StoneRec): CairnSegment[] {
  const segs = meta(L.sprite).segments[upSide(L.tilt)] || []
  const containing = segs.filter((s) => {
    const sp = segSpanWorld(s, L)
    return sp[0] - 1.5 <= L.cx && L.cx <= sp[1] + 1.5
  })
  if (containing.length) return containing
  let best: CairnSegment | null = null
  let bd = Infinity
  for (const s of segs) {
    const sp = segSpanWorld(s, L)
    const d = Math.abs((sp[0] + sp[1]) / 2 - L.cx)
    if (d < bd) {
      bd = d
      best = s
    }
  }
  return best ? [best] : []
}

function ensurePairing(L: StoneRec, st: StoneRec, B: Blend): boolean {
  if (findPair(L, st)) return true
  const cx0 = st.cx
  const tilt0 = st.tilt
  const shiftInto = (p: SegPair) => {
    const want = clamp(st.cx, p.tS[0] + 1, p.tS[1] - 1)
    st.cx = clamp(cx0 + clamp(want - cx0, -0.22 * L.w, 0.22 * L.w), -B.leash * BASE_W, B.leash * BASE_W)
    place(st)
  }
  const compat = allPairs(L, st).filter((p) => p.dA <= PAIR_TOL)
  for (const p of compat) {
    st.cx = cx0
    st.tilt = tilt0
    place(st)
    shiftInto(p)
    if (findPair(L, st)) return true
  }
  if (!st.onEdge) {
    const all = allPairs(L, st).sort((a, b) => b.score - a.score)
    for (const p of all.slice(0, 4)) {
      const nt = tilt0 + normAng(p.tA - p.bA)
      if (Math.abs(nt) > B.rotMax + 0.01) continue
      st.cx = cx0
      st.tilt = nt
      place(st)
      const pr = allPairs(L, st).filter((q) => q.dA <= PAIR_TOL)
      if (pr.length) shiftInto(pr[0]!)
      if (findPair(L, st)) return true
    }
  }
  st.cx = cx0
  st.tilt = tilt0
  place(st)
  return false
}

/** The cap's pairing: the supporter's CENTRAL segments are preferred. */
function ensurePairingCap(L: StoneRec, st: StoneRec, B: Blend): boolean {
  const csSet = centralTopSegs(L)
  const onSet = (p: SegPair) => csSet.includes(p.t)
  const pairedCentrally = () => csSet.some((cs) => findPairOn(L, st, cs))
  if (csSet.length) {
    if (pairedCentrally()) return true
    const cx0 = st.cx
    const tilt0 = st.tilt
    const shiftInto = (p: SegPair) => {
      const want = clamp(st.cx, p.tS[0] + 1, p.tS[1] - 1)
      st.cx = clamp(cx0 + clamp(want - cx0, -0.22 * L.w, 0.22 * L.w), -B.leash * BASE_W, B.leash * BASE_W)
      place(st)
    }
    const compat = allPairs(L, st).filter((p) => onSet(p) && p.dA <= PAIR_TOL)
    for (const p of compat) {
      st.cx = cx0
      st.tilt = tilt0
      place(st)
      shiftInto(p)
      if (pairedCentrally()) return true
    }
    const all = allPairs(L, st).filter(onSet).sort((a, b) => b.score - a.score)
    for (const p of all.slice(0, 4)) {
      const nt = tilt0 + normAng(p.tA - p.bA)
      if (Math.abs(nt) > B.rotMax + 0.01) continue
      st.cx = cx0
      st.tilt = nt
      place(st)
      const pr = allPairs(L, st).filter((q) => onSet(q) && q.dA <= PAIR_TOL)
      if (pr.length) shiftInto(pr[0]!)
      if (pairedCentrally()) return true
    }
    st.cx = cx0
    st.tilt = tilt0
    place(st)
    let best: { p: SegPair; off: number } | null = null
    for (const p of allPairs(L, st).filter((q) => q.dA <= PAIR_TOL)) {
      const want = clamp(st.cx, p.tS[0] + 1, p.tS[1] - 1)
      const nx = clamp(cx0 + clamp(want - cx0, -0.22 * L.w, 0.22 * L.w), -B.leash * BASE_W, B.leash * BASE_W)
      const off = Math.abs(nx - L.cx)
      if (!best || off < best.off) best = { p, off }
    }
    if (best) {
      shiftInto(best.p)
      if (findPair(L, st)) return true
      st.cx = cx0
      st.tilt = tilt0
      place(st)
    }
  }
  return ensurePairing(L, st, B)
}

/* ================= profile-nested seating =================
   After pairing, the upper stone sinks along Y until the two measured
   alpha profiles meet across the whole interface (the sink closes the
   70th-percentile hovering gap). Bounds: total sink <= 0.60 x own
   height; centre stays above the supporter's centre; the sink's own
   added penetration <= 0.30 x own height. A rim settle (pairing
   segment in the supporter's outer third, shoulder carried below the
   supporter's local top edge) is permitted below the cap. */

const SEAT_PCT = 0.7
const HOVER_MIN = 0.08
const SINK_CEIL = 0.6
const PEN_GUARD = 0.3

function boundaryPts(st: StoneRec, side: 'top' | 'bottom'): Array<[number, number]> {
  if (Math.abs(Math.sin((st.tilt * Math.PI) / 180)) > Math.abs(Math.cos((st.tilt * Math.PI) / 180))) {
    /* Steep tilts (an on-edge stone): the world-facing contour is a
       frame SIDE — bin rotated cell centres by world x. Rare in the
       port (arrivals are never on-edge); kept for correctness. */
    const occ = meta(st.sprite).occ
    const G = 56
    const cw = st.fw / G
    const ch = st.fh / G
    const pts: Array<[number, number]> = []
    const BIN = 3
    const bins = new Map<number, number>()
    const ext = (cw + ch) / 4
    for (let gy = 0; gy < G; gy++) {
      for (let gx = 0; gx < G; gx++) {
        if (occ[gy]![gx] !== '1') continue
        const [wx, wy] = rotVec((gx + 0.5) * cw - st.fw / 2, (gy + 0.5) * ch - st.fh / 2, st.tilt)
        const bx = Math.floor((st.fcx + wx) / BIN)
        const v = st.fcy + wy
        const cur = bins.get(bx)
        if (cur == null || (side === 'bottom' ? v > cur : v < cur)) bins.set(bx, v)
      }
    }
    for (const [bx, v] of bins) pts.push([(bx + 0.5) * BIN, v + (side === 'bottom' ? ext : -ext)])
    return pts.sort((a, b) => a[0] - b[0])
  }
  const local = side === 'bottom' ? rotCacheFor(st).botB : rotCacheFor(st).topB
  const prev = boundaryMemo.get(st)
  if (prev && prev.fcx === st.fcx && prev.fcy === st.fcy && prev[side]) return prev[side]!
  const pts = local.map(([x, y]) => [st.fcx + x, st.fcy + y] as [number, number])
  const entry = prev && prev.fcx === st.fcx && prev.fcy === st.fcy ? prev : { fcx: st.fcx, fcy: st.fcy }
  entry[side] = pts
  boundaryMemo.set(st, entry)
  return pts
}

const boundaryMemo = new WeakMap<StoneRec, { fcx: number; fcy: number; top?: Array<[number, number]>; bottom?: Array<[number, number]> }>()

function interpPts(pts: Array<[number, number]>, x: number): number | null {
  if (!pts.length || x < pts[0]![0] || x > pts[pts.length - 1]![0]) return null
  if (pts.length === 1) return pts[0]![1]
  // Lower-bound binary search: first index whose x >= the query —
  // identical results to a linear scan over the x-sorted points.
  let lo = 1
  let hi = pts.length - 1
  let k = pts.length - 1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (pts[mid]![0] >= x) {
      k = mid
      hi = mid - 1
    } else {
      lo = mid + 1
    }
  }
  const [x0, y0] = pts[k - 1]!
  const [x1, y1] = pts[k]!
  return x1 === x0 ? y1 : y0 + ((y1 - y0) * (x - x0)) / (x1 - x0)
}

function profileSeat(L: StoneRec, U: StoneRec, opts?: { noRim?: boolean }): { sink: number; rim: boolean; hover: number | null } {
  const pair = U.pair || findPair(L, U)
  if (!pair) return { sink: 0, rim: false, hover: null }
  const span = pair.tS
  const bU = boundaryPts(U, 'bottom')
  const tL = boundaryPts(L, 'top')
  if (!bU.length || !tL.length) return { sink: 0, rim: false, hover: null }
  const x0 = Math.max(bU[0]![0], tL[0]![0])
  const x1 = Math.min(bU[bU.length - 1]![0], tL[tL.length - 1]![0])
  if (!(x1 > x0)) return { sink: 0, rim: false, hover: null }
  const N = 40
  const gaps: Array<{ x: number; g: number }> = []
  for (let j = 0; j <= N; j++) {
    const x = x0 + ((x1 - x0) * j) / N
    const bu = interpPts(bU, x)
    const tl = interpPts(tL, x)
    if (bu != null && tl != null) gaps.push({ x, g: tl - bu })
  }
  if (gaps.length < 8) return { sink: 0, rim: false, hover: null }
  const pos = gaps.filter((o) => o.g > 0.5).map((o) => o.g).sort((a, b) => a - b)
  let D = 0
  if (pos.length / gaps.length >= HOVER_MIN) {
    const target = pos[Math.min(pos.length - 1, Math.floor(SEAT_PCT * pos.length))]!
    D = clamp(target, 0, SINK_CEIL * U.h)
    D = Math.min(D, Math.max(0, L.cy - U.cy - 1))
    D = Math.min(D, PEN_GUARD * U.h)
    D = Math.max(0, D)
  }
  if (D > 0.05) {
    U.cy += D
    place(U)
  }
  let rim = false
  const segC = (span[0] + span[1]) / 2
  if (D > 0.5 && Math.abs(segC - L.cx) > L.w / 6) {
    const xo = segC >= L.cx ? span[1] : span[0]
    const bu = interpPts(boundaryPts(U, 'bottom'), xo)
    const tl = interpPts(tL, xo)
    if (bu != null && tl != null && bu - tl > 0.5) rim = true
  }
  if (rim && opts && opts.noRim) {
    const xo = segC >= L.cx ? span[1] : span[0]
    const bu = interpPts(boundaryPts(U, 'bottom'), xo)
    const tl = interpPts(tL, xo)
    if (bu != null && tl != null) {
      const red = Math.min(D, Math.max(0, bu - tl - 0.5))
      if (red > 0) {
        U.cy -= red
        place(U)
        D -= red
      }
    }
    rim = false
  }
  /* Post-sink hover fraction: sinking translates the stone's bottom
     boundary by exactly D, so the seated hover over the same samples
     is #{g - D > 0.5} / samples — the value a separate hover pass
     over the seated stone would compute. */
  let hovCount = 0
  for (const o of gaps) if (o.g - D > 0.5) hovCount++
  return { sink: D, rim, hover: hovCount / gaps.length }
}

/* ================= sprite assignment (member-keyed) =================
   Each member's sprite is its identity: drawn from its own seeded
   walk of the pool, first unused in BUILD ORDER (arrivals append, so
   an existing member's assignment can never be taken by a later
   arrival). Past pool exhaustion the walk wraps to the member's own
   first preference and sprites repeat at different sizes/tints. */

function spriteSequence(seed: string, memberId: string): string[] {
  const k0 = Math.floor(hash01(`${seed}:m${memberId}:spr`) * UPPER_POOL.length)
  const seq: string[] = []
  for (let t = 0; t < UPPER_POOL.length; t++) seq.push(UPPER_POOL[(k0 + t) % UPPER_POOL.length]!)
  seq.push('stone-round', 'stone-standing')
  return seq
}

function assignSprites(seed: string, buildOrder: CairnMemberInput[]): Map<string, string> {
  const used = new Set<string>()
  const out = new Map<string, string>()
  for (const m of buildOrder) {
    const seq = spriteSequence(seed, m.id)
    const pick = seq.find((s) => !used.has(s)) || seq[0]!
    used.add(pick)
    out.set(m.id, pick)
  }
  return out
}

/* ================= the arrival placer (growth law) =================
   An arriving member's size, tint character and draws are fixed by
   its identity; only its SEAT is searched. The search (growth study
   Part 2) tries, for the ASSIGNED sprite: supporters = the pile's top
   stone (cap seat) and the stone below it (shoulder seat); tilts =
   the drawn tilt, a five-point sweep of the temperament's range, and
   the exact angle-matching tilt of every segment pair; positions =
   centres sampled across each candidate segment's span. Gates in
   order: ANGLE -> SPAN -> COLLISION (shoulder seats) -> FLOAT ->
   BALANCE (all October triples). Ranking: summit discipline first
   (central-segment cap seat, then any cap seat, then shoulder), then
   interface float, then pairing residual, then least departure from
   the drawn centre. Only when the assigned sprite has NO viable seat
   does the fallback fire: the member's remaining sequence, each given
   the same full search (wrapping only when every sprite is held).
   Existing stones are never written. */

type DrawnGeom = {
  w: number
  h: number
  tilt: number
  cx: number
  hE: number
  stackT: number
  topShrink: number
  topThin: number
  reset: boolean
  dir: number
}

function drawnFor(
  seed: string,
  member: CairnMemberInput,
  sprite: string,
  pos: number,
  n: number,
  supporter: StoneRec,
  B: Blend,
  leadRight: boolean,
): DrawnGeom {
  const sprMeta = meta(sprite)
  const s = `${seed}:m${member.id}`
  const hA = hash01(s + ':a')
  const hB = hash01(s + ':b')
  const hC = hash01(s + ':c')
  const hD = hash01(s + ':d')
  const hE = hash01(s + ':e')
  const hF = hash01(s + ':f')
  /* Growth-law immobility: stackT is normalized against the render
     cap, NOT the current member count. An arrival's drawn geometry
     may depend only on its build position and the pile as it stood
     when it arrived — never on members that arrive later — or
     existing stones would move every time the pile grows. (The batch
     study normalized by the final count; deviation disclosed in the
     port PR: piles below the cap taper less than the study's batch
     piles; at the 12-member cap the curves coincide exactly.) */
  const upperSpan = Math.max(1, MAX_COLUMN_MEMBERS - 2)
  const stackT = pos === 0 ? 0 : Math.min(1, (pos - 1) / upperSpan)
  const midFlare = hF > 0.86 ? 0.02 + (hF - 0.86) * 0.14 : 0
  let wf = clamp(1 + (hA - 0.5) * 0.34 + (-0.04 - stackT * 0.26) + midFlare, 0.58, 1.14)
  if (pos === 0) wf = clamp(wf, 0.58, 1.0) // the base member never outgrows its slab
  let w = supporter.w * wf
  const topShrink = stackT > 0.65 ? 0.55 + (1 - stackT) * 0.35 + hD * 0.12 : 1
  if (stackT > 0.55) w *= topShrink
  w = clamp(w, BASE_W * 0.1, BASE_W * 1.12)
  let hCap = supporter.h * clamp(0.88 + hD * 0.38, 0.72, 1.28)
  const topThin = stackT > 0.7 ? 0.78 + hE * 0.12 : 1
  if (stackT > 0.7) hCap *= topThin
  let h = (w * sprMeta.bodyH) / sprMeta.bodyW
  if (h > hCap) {
    h = hCap
    w = h / (sprMeta.bodyH / sprMeta.bodyW)
  }
  const tilt = (hC - 0.5) * 2 * B.rotMax
  const dir = leadRight ? (pos % 2 === 0 ? -1 : 1) : (pos % 2 === 0 ? 1 : -1)
  const dScale = pos <= 2 ? 0.52 : pos === 3 ? 0.72 : 1
  const driftMag = w * (B.driftLo + hE * (B.driftHi - B.driftLo)) * dScale
  const osc = dir * (driftMag + w * (0.018 + hC * 0.032))
  let cx = pos === 0 ? 0 : supporter.cx + osc * 0.5
  let reset = false
  if (pos > 0 && pos % 4 === 0) {
    cx = (hF - 0.5) * 2 * w * (0.05 + hB * 0.05)
    reset = true
  }
  cx = clamp(cx, -B.leash * BASE_W, B.leash * BASE_W)
  return { w, h, tilt, cx, hE, stackT, topShrink, topThin, reset, dir }
}

type SearchStats = {
  pairsExamined: number
  angleRejected: number
  positionsTried: number
  spanRejected: number
  collisionRejected: number
  floatRejected: number
  balanceRejected: number
  viable: number
}

type SearchOutcome = {
  stats: SearchStats
  best: { st: StoneRec; tier: number; floatIf: number; dA: number } | null
  drawn: DrawnGeom
}

function searchSeat(
  seed: string,
  member: CairnMemberInput,
  sprite: string,
  pos: number,
  n: number,
  col: StoneRec[],
  B: Blend,
  leadRight: boolean,
  tint: string,
): SearchOutcome {
  const topSt = col[col.length - 1]!
  const g = drawnFor(seed, member, sprite, pos, n, topSt, B, leadRight)
  const stats: SearchStats = {
    pairsExamined: 0, angleRejected: 0, positionsTried: 0, spanRejected: 0,
    collisionRejected: 0, floatRejected: 0, balanceRejected: 0, viable: 0,
  }
  const candidates: Array<{ st: StoneRec; tier: number; floatIf: number; dA: number; dcx: number }> = []
  const supporters: Array<{ S: StoneRec; capSeat: boolean }> = [{ S: topSt, capSeat: true }]
  if (col.length >= 2) supporters.push({ S: col[col.length - 2]!, capSeat: false })
  for (const sup of supporters) {
    const S = sup.S
    const ratio = B.ovLo + g.hE * (B.ovHi - B.ovLo)
    const overlap = Math.min(Math.max(g.h * ratio, S.h * B.ovFloor), S.h * B.ovCap)
    const cy0 = S.cy - S.h / 2 + overlap - g.h / 2
    const central = centralTopSegs(S)
    const tilts = new Set<number>([+g.tilt.toFixed(2)])
    for (const tv of [-B.rotMax, -B.rotMax / 2, 0, B.rotMax / 2, B.rotMax]) tilts.add(tv)
    const probe0 = mkStone(sprite, pos, g.w, g.h, g.cx, cy0, g.tilt, tint)
    for (const p of allPairs(S, probe0)) {
      const nt = clamp(g.tilt + normAng(p.tA - p.bA), -B.rotMax, B.rotMax)
      tilts.add(+nt.toFixed(2))
    }
    const upSegs = meta(S.sprite).segments[upSide(S.tilt)] || []
    /* Seat geometry (pairing on the segment, profile seating, hover,
       collision, balance) depends only on (tilt, cx, supporter
       segment) — never on which bottom-segment pair led here — so it
       is evaluated once per combination and reused across pairs. The
       candidate set and ranking are unchanged. Rejection counters
       below count unique seat evaluations, not raw attempts. */
    const seatCache = new Map<string, { st: StoneRec; hov: number; fp: SegPair } | null>()
    const evalSeat = (tilt: number, cx: number, seg: CairnSegment): { st: StoneRec; hov: number; fp: SegPair } | null => {
      const key = `${tilt}|${cx}|${upSegs.indexOf(seg)}`
      if (seatCache.has(key)) return seatCache.get(key)!
      const st = mkStone(sprite, pos, g.w, g.h, cx, cy0, tilt, tint)
      st.role = 'column'
      st.kind = member.kind
      st.memberId = member.id
      st.onEdge = false
      st.supporter = S.pos
      st.overlap = overlap
      let out: { st: StoneRec; hov: number; fp: SegPair } | null = null
      const fp = findPairOn(S, st, seg)
      if (!fp) {
        stats.spanRejected++
      } else {
        st.pair = fp
        const seat = profileSeat(S, st, { noRim: sup.capSeat })
        st.sink = seat.sink
        st.rimSettled = seat.rim
        st.overlap = overlap + seat.sink
        if (!sup.capSeat && contactCountUpTo(st, stoneCells(topSt), 1) > 0) {
          stats.collisionRejected++
        } else {
          const hov = seat.hover
          if (hov == null || hov > 0.5) {
            stats.floatRejected++
          } else if (!triplesOK([...col, st])) {
            stats.balanceRejected++
          } else {
            out = { st, hov, fp }
          }
        }
      }
      seatCache.set(key, out)
      return out
    }
    for (const tilt of tilts) {
      const probe = mkStone(sprite, pos, g.w, g.h, g.cx, cy0, tilt, tint)
      for (const p of allPairs(S, probe)) {
        stats.pairsExamined++
        if (p.dA > PAIR_TOL) {
          stats.angleRejected++
          continue
        }
        const lo = Math.max(p.tS[0] + 1, -B.leash * BASE_W)
        const hi = Math.min(p.tS[1] - 1, B.leash * BASE_W)
        const cxs = new Set<number>()
        if (hi >= lo) {
          const step = Math.max(2, (hi - lo) / 6)
          for (let x = lo; x <= hi + 0.01; x += step) cxs.add(+x.toFixed(2))
          cxs.add(+((lo + hi) / 2).toFixed(2))
          cxs.add(+hi.toFixed(2))
        }
        if (g.cx >= p.tS[0] - 1.5 && g.cx <= p.tS[1] + 1.5) cxs.add(g.cx)
        for (const cx of cxs) {
          stats.positionsTried++
          const ev = evalSeat(tilt, cx, p.t)
          if (!ev) continue
          stats.viable++
          candidates.push({
            st: { ...ev.st, pair: ev.fp },
            tier: sup.capSeat ? (central.includes(p.t) ? 0 : 1) : 2,
            floatIf: ev.hov,
            dA: ev.fp.dA,
            dcx: Math.abs(cx - g.cx),
          })
        }
      }
    }
  }
  candidates.sort((a, b) => a.tier - b.tier || a.floatIf - b.floatIf || a.dA - b.dA || a.dcx - b.dcx)
  return { stats, best: candidates.length ? candidates[0]! : null, drawn: g }
}

type PlacementResult = {
  st: StoneRec
  seatedSprite: string
  viableSeats: number
  fellBack: boolean
  exhausted: boolean
  repairs: number
}

/** Seat one arriving member. Never writes to existing column stones. */
function placeMember(
  seed: string,
  member: CairnMemberInput,
  assigned: string,
  pos: number,
  n: number,
  col: StoneRec[],
  B: Blend,
  leadRight: boolean,
  tint: string,
): PlacementResult {
  const finish = (st: StoneRec, seatedSprite: string, viableSeats: number, fellBack: boolean, exhausted: boolean): PlacementResult => {
    col.push(st)
    let repairs = 0
    if (col.length - 1 >= 2) {
      const r = repairTriple(col, col.length - 1, B)
      repairs = r.n
    }
    const S = col[st.supporter >= 0 ? st.supporter : col.length - 2]!
    st.pair = findPair(S, st)
    st.pairOK = !!st.pair
    return { st, seatedSprite, viableSeats, fellBack, exhausted, repairs }
  }

  const main = searchSeat(seed, member, assigned, pos, n, col, B, leadRight, tint)
  if (main.best) {
    return finish(main.best.st, assigned, main.stats.viable, false, false)
  }

  /* Documented fallback: the member's remaining sequence, each sprite
     given the same full search; sprites held by placed members are
     skipped — past pool exhaustion the sequence wraps and repeats are
     allowed (the same wrap the assignment itself uses). */
  const held = new Set(col.filter((s) => s.role === 'column').map((s) => s.sprite))
  const seq = spriteSequence(seed, member.id)
  let candList = seq.filter((c) => c !== assigned && !held.has(c))
  if (!candList.length) candList = seq.filter((c) => c !== assigned)
  for (const cand of candList) {
    const r = searchSeat(seed, member, cand, pos, n, col, B, leadRight, tint)
    if (r.best) {
      return finish(r.best.st, cand, main.stats.viable, true, false)
    }
  }

  /* Exhaustion: no sprite seats. The stone is placed as drawn on the
     top stone with the batch nudge (ensurePairingCap) — pairOK is
     reported as found, never repaired away. */
  const topSt = col[col.length - 1]!
  const g = drawnFor(seed, member, assigned, pos, n, topSt, B, leadRight)
  const ratio = B.ovLo + g.hE * (B.ovHi - B.ovLo)
  const overlap = Math.min(Math.max(g.h * ratio, topSt.h * B.ovFloor), topSt.h * B.ovCap)
  const cy = topSt.cy - topSt.h / 2 + overlap - g.h / 2
  const st = mkStone(assigned, pos, g.w, g.h, g.cx, cy, g.tilt, tint)
  st.role = 'column'
  st.kind = member.kind
  st.memberId = member.id
  st.onEdge = false
  st.supporter = topSt.pos
  st.overlap = overlap
  st.pairOK = ensurePairingCap(topSt, st, B)
  st.pair = findPair(topSt, st)
  if (st.pairOK) {
    const seat = profileSeat(topSt, st, { noRim: true })
    st.sink = seat.sink
    st.rimSettled = seat.rim
    st.overlap = overlap + seat.sink
  }
  return finish(st, assigned, main.stats.viable, true, true)
}

/* ================= October rim accents =================
   Count by column size (0 under six members, 2 at six to eight, 3 at
   nine+); hosts drawn from member positions 1..n-3 — the base member
   never hosts (October) and the top two members are the accent-free
   summit zone (founder v3.4). Rim opposite the lean of the stone
   above; contact must be an area on the host's measured rim profile;
   an accent that seats nowhere eligible is dropped and disclosed. */

function buildAccents(
  seed: string,
  col: StoneRec[],
  memberCount: number,
  companions: StoneRec[],
  dropped: string[],
): StoneRec[] {
  const n = memberCount
  const nAccents = n < 6 ? 0 : n <= 8 ? 2 : 3
  const accents: StoneRec[] = []
  // Column indices (slab = 0, members = 1..n): eligible hosts are
  // member positions 1..n-3 -> column indices 2..n-2. Accents host ONLY
  // on stack members — never on the slab, and never on a companion:
  // October's placement checked contact against the host alone, so an
  // accent seated on a member's rim could overlap the leaner leaning
  // against that flank and, painted last, read as sitting ON the
  // companion (founder's correction, 2026-11-13). Companions are built
  // first and any candidate overlapping one beyond the accent-accent
  // tolerance is rejected here; the host loop then tries other members.
  const eligHosts: number[] = []
  for (let h = 2; h <= n - 2; h++) eligHosts.push(h)
  if (nAccents === 0) return accents
  if (!eligHosts.length) {
    dropped.push('accent')
    return accents
  }
  const companionCells = companions.map((c) => stoneCells(c))
  const placedCells: Array<Set<number>> = []
  for (let k = 0; k < nAccents; k++) {
    const K = `${seed}:accent:${k}`
    const rKind = hash01(K + ':kind')
    const spr = rKind < 0.4 ? 'stone-round' : rKind < 0.6 ? 'pebble' : rKind < 0.8 ? 'stone-chunk' : 'stone-standing'
    const sprMeta = meta(spr)
    const tryAccentOn = (hostIdx: number): StoneRec | null => {
      const host = col[hostIdx]!
      const aboveDx = hostIdx + 1 < col.length ? col[hostIdx + 1]!.cx - host.cx : 0
      let side = aboveDx >= 0 ? -1 : 1
      if (hash01(K + ':flip') < 0.25) side = -side
      const u = 0.75 + 0.2 * hash01(K + ':u')
      let wA = host.w * (0.3 + 0.15 * hash01(K + ':size'))
      let hA = (wA * sprMeta.bodyH) / sprMeta.bodyW
      if (hA > 0.5 * host.h) {
        hA = 0.5 * host.h
        wA = hA * (sprMeta.bodyW / sprMeta.bodyH)
      }
      const hostCells = stoneCells(host)
      const hm = meta(host.sprite)
      // Alpha-bbox top in frame coords — profiles are frame-based, the
      // rim point must land in body-centred local coords.
      const bboxTop = hm.frame[1] / 2 + hm.bboxOff[1] - hm.bodyH / 2
      for (const sd of [side, -side]) {
        const strip = clamp(Math.floor((0.5 + (sd * u) / 2) * 25), 0, 24)
        const prof = hm.topProfile[strip]
        if (prof == null) continue
        const topLocalY = -host.h / 2 + (prof - bboxTop) * host.scale
        const [rx, ry] = rotVec(sd * u * (host.w / 2), topLocalY, host.tilt)
        const cand = mkStone(
          spr,
          -1,
          wA,
          hA,
          host.cx + rx,
          host.cy + ry - 0.35 * hA,
          (hash01(K + ':rot') * 2 - 1) * 25,
          NEUTRAL_WASH,
        )
        cand.role = 'accent'
        cand.host = hostIdx
        cand.rimU = sd * u
        let sink = 0
        while (contactCells(stoneCells(cand), hostCells) < 11 && sink < 0.55 * hA) {
          cand.cy += 1.5
          sink += 1.5
          place(cand)
        }
        cand.contact = contactCells(stoneCells(cand), hostCells)
        if (cand.contact < 11) continue
        const cc = stoneCells(cand)
        if (placedCells.some((pc) => contactCells(cc, pc) > 3)) continue
        // Host law: an accent never overlaps a companion (leaner/wedge)
        // beyond the same tolerance two accents allow each other.
        if (companionCells.some((pc) => contactCells(cc, pc) > 3)) continue
        placedCells.push(cc)
        return cand
      }
      return null
    }
    const drawn = eligHosts[Math.floor(hash01(K + ':host') * eligHosts.length)]!
    const hostOrder = [drawn, ...eligHosts.filter((h) => h !== drawn).sort((a, b) => b - a)]
    let acc: StoneRec | null = null
    for (const hIdx of hostOrder) {
      acc = tryAccentOn(hIdx)
      if (acc) break
    }
    if (acc) accents.push(acc)
  }
  if (accents.length < nAccents) dropped.push('accent')
  return accents
}

/* ================= companions =================
   Ground-anchored, outside the balance math, contact-verified: a
   leaner against a lower member's flank (never taller than 0.70x the
   pile, shoulder contact centred below the host's top third) and a
   compact wedge at the slab's corner (ground contact >= ~25% of its
   width, flank contact a real area). Anything the discipline rejects
   is dropped and disclosed. (Column indices are the study's +1: the
   slab occupies position 0.) */

function buildLeaner(seed: string, col: StoneRec[], groundY: number): StoneRec | null {
  const sprite = hash01(`${seed}:comp:leaner:kind`) < 0.55 ? 'stone-standing' : 'stone-angular'
  const side = hash01(`${seed}:comp:leaner:side`) < 0.5 ? -1 : 1
  const hostIdx = Math.min(col.length - 1, 2 + Math.floor(hash01(`${seed}:comp:leaner:host`) * Math.min(2, col.length - 2)))
  const host = col[hostIdx]
  if (!host) return null
  const sprMeta = meta(sprite)
  const longN = Math.max(sprMeta.bodyW, sprMeta.bodyH)
  const shortN = Math.min(sprMeta.bodyW, sprMeta.bodyH)
  const axisRot = sprMeta.bodyH >= sprMeta.bodyW ? 0 : 90
  const phi0 = 18 + hash01(`${seed}:comp:leaner:ang`) * 14
  const colCells = col.map(stoneCells)
  const pileH = groundY - Math.min(...col.map(alphaTop))
  const baseMeta = meta(col[0]!.sprite)
  const baseAlphaW = col[0]!.w * (baseMeta.bodyW / baseMeta.frame[0])
  const hostTop = alphaTop(host)
  const hostH = alphaBottom(host) - hostTop
  for (const dPhi of [0, 3, 6, 9]) {
    for (const tFrac of [0.84, 0.8, 0.76]) {
      const phi = phi0 + dPhi
      const rad = (phi * Math.PI) / 180
      const d: [number, number] = [side * Math.sin(rad), Math.cos(rad)]
      for (const sDrop of [0, 0.1, 0.22]) {
        const S = { x: host.cx + side * host.w * 0.4, y: host.cy - host.h * 0.08 + sDrop * host.h }
        let L = clamp(Math.min((groundY - S.y) / Math.cos(rad) / tFrac, (0.66 * pileH) / Math.cos(rad)), 90, 520)
        for (let adj = 0; adj < 4; adj++) {
          const shortD = (L * shortN) / longN
          const cx = S.x + d[0] * (tFrac * L - L / 2)
          const cy = S.y + d[1] * (tFrac * L - L / 2)
          const rot = axisRot - side * phi
          const st = mkStone(
            sprite,
            -2,
            sprite === 'stone-standing' ? shortD : L,
            sprite === 'stone-standing' ? L : shortD,
            cx,
            cy,
            rot,
            NEUTRAL_WASH,
          )
          st.cy += groundY - lowestY(st)
          place(st)
          settleToGround(st, groundY)
          const hAct = alphaBottom(st) - alphaTop(st)
          if (hAct > 0.685 * pileH) {
            if (adj < 3) {
              L *= (0.66 * pileH) / hAct
              continue
            }
            break
          }
          if (cellsWidth(st) > 0.74 * baseAlphaW) break
          st.role = 'leaner'
          st.host = hostIdx
          st.side = side
          let stats = sharedCellStats(st, host)
          let touch = 0
          colCells.forEach((cc) => {
            touch += contactCells(stoneCells(st), cc)
          })
          for (let k = 1; k <= 5 && stats.n === 0; k++) {
            st.cx -= side * 2
            settleToGround(st, groundY)
            place(st)
            stats = sharedCellStats(st, host)
            touch = 0
            colCells.forEach((cc) => {
              touch += contactCells(stoneCells(st), cc)
            })
          }
          const gap = groundY - alphaBottom(st)
          const relY = stats.n ? (stats.cy - hostTop) / hostH : 0
          if (stats.n >= 4 && touch > 0 && gap <= 2.5 && relY >= 0.36) {
            st.contact = touch
            return st
          }
          break
        }
      }
    }
  }
  return null
}

function settleCentral(st: StoneRec, groundY: number): void {
  const prof = meta(st.sprite).bottomProfile
  const rad = (st.tilt * Math.PI) / 180
  const cs = Math.cos(rad)
  const sn = Math.sin(rad)
  const centralBottom = () => {
    let m = -Infinity
    for (let k = 11; k < 45; k++) {
      const p = prof[k]
      if (p == null) continue
      const lx = ((k + 0.5) / 56) * st.fw - st.fw / 2
      const ly = p * st.scale - st.fh / 2
      m = Math.max(m, st.fcy + lx * sn + ly * cs)
    }
    return m
  }
  for (let k = 0; k < 24; k++) {
    const delta = groundY + 1.5 - centralBottom()
    if (Math.abs(delta) <= 0.4) break
    st.cy += delta * 0.7
    place(st)
  }
}

function buildWedge(
  seed: string,
  col: StoneRec[],
  groundY: number,
  leaner: StoneRec | null,
): StoneRec | null {
  const sprite = ['pebble', 'stone-chunk', 'stone-small'][Math.floor(hash01(`${seed}:comp:wedge:kind`) * 3)]!
  let side: number
  if (leaner) side = hash01(`${seed}:comp:wedge:side`) < 0.6 ? leaner.side : -leaner.side
  else side = hash01(`${seed}:comp:wedge:side`) < 0.5 ? -1 : 1
  const sprMeta = meta(sprite)
  const w = BASE_W * (0.34 + 0.12 * hash01(`${seed}:comp:wedge:size`))
  const h = (w * sprMeta.bodyH) / sprMeta.bodyW
  const tilt0 = (hash01(`${seed}:comp:wedge:rot`) * 2 - 1) * 12
  const base = col[0]!
  const baseCells = stoneCells(base)
  for (const tilt of [tilt0, tilt0 * 0.5, 0, tilt0 * 0.25, tilt0 > 0 ? -3 : 3, tilt0 > 0 ? -6 : 6]) {
    const st = mkStone(sprite, -3, w, h, side * base.w * 0.46 + side * w * 0.38, 0, tilt, NEUTRAL_WASH)
    st.cy = groundY - h / 2
    place(st)
    settleCentral(st, groundY)
    st.role = 'wedge'
    if (bottomSpan(st, groundY, 3.0) < 0.32 * cellsWidth(st)) continue
    for (let k = 0; k <= 18; k++) {
      const n = contactCells(stoneCells(st), baseCells)
      if (n >= 22) {
        st.contact = n
        return st
      }
      st.cx -= side * 1.5
      place(st)
      if (Math.abs(st.cx) < base.w * 0.34) break
    }
  }
  return null
}

/* ================= ordering ================= */

/** Historical build order: arrival (createdAt) ascending, id tiebreak.
    Undated members keep their relative input order (stable sort). */
function buildOrderOf(members: CairnMemberInput[]): CairnMemberInput[] {
  const decorated = members.map((m, idx) => ({
    m,
    idx,
    t: m.createdAt ? Date.parse(m.createdAt) : NaN,
  }))
  decorated.sort((a, b) => {
    const at = Number.isNaN(a.t) ? null : a.t
    const bt = Number.isNaN(b.t) ? null : b.t
    if (at != null && bt != null && at !== bt) return at - bt
    if (at != null && bt == null) return -1
    if (at == null && bt != null) return 1
    if (at != null && bt != null && at === bt) return a.m.id < b.m.id ? -1 : a.m.id > b.m.id ? 1 : a.idx - b.idx
    return a.idx - b.idx
  })
  return decorated.map((d) => d.m)
}

/** April's semantic order over the same members (nesting.ts
    computeStoneKinds): base = highest-activity structural member, the
    rest ascending by activity. Used for the order-debt diagnostic and
    nothing else — placement itself is historical. */
function aprilOrderOf(members: CairnMemberInput[]): CairnMemberInput[] {
  if (!members.length) return []
  const structural = members.filter((m) => STRUCTURAL_KINDS.includes(m.kind))
  const pool = structural.length ? structural : members
  const base = pool.reduce((a, b) => (b.activity > a.activity ? b : a))
  const rest = members
    .filter((m) => m !== base)
    .sort((a, b) => a.activity - b.activity || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))
  return [base, ...rest]
}

function orderDebt(build: CairnMemberInput[], april: CairnMemberInput[]): number {
  const aprilPos = new Map(april.map((m, i) => [m.id, i]))
  const seq = build.map((m) => aprilPos.get(m.id)!)
  let debt = 0
  for (let i = 0; i < seq.length; i++) {
    for (let j = i + 1; j < seq.length; j++) {
      if (seq[i]! > seq[j]!) debt++
    }
  }
  return debt
}

/** The cairn's permanent temperament, from its stable id only. */
export function cairnBlend(cairnId: string): number {
  const h = hash01(`${cairnId}:temperament`)
  return h < 0.34 ? 0 : h < 0.67 ? 1 : 2
}

/* ================= the layout ================= */

type InternalLayout = {
  ported: PortedTowerLayout
  col: StoneRec[]
  accents: StoneRec[]
  companions: StoneRec[]
  scale: number
}

function computeLayout(cairnId: string, membersIn: CairnMemberInput[]): InternalLayout {
  const blendIdx = cairnBlend(cairnId)
  const B = BLENDS[blendIdx]!
  const leadRight = hash01(`${cairnId}:cairn-drift-phase`) >= 0.5
  const build = buildOrderOf(membersIn)
  const rendered = build.slice(0, MAX_COLUMN_MEMBERS)
  const n = rendered.length
  const assigned = assignSprites(cairnId, rendered)
  const dropped: string[] = []
  const insertions: CairnInsertionDiagnostic[] = []
  let repairs = 0

  /* The slab: column position 0, structural support. */
  const slabMeta = meta(SLAB_SPRITE)
  const slabW = BASE_W
  const slabH = (slabW * slabMeta.bodyH) / slabMeta.bodyW
  const slab = mkStone(SLAB_SPRITE, 0, slabW, slabH, 0, 0, 0, NEUTRAL_WASH)
  slab.role = 'slab'
  slab.pos = 0
  const col: StoneRec[] = [slab]
  const groundY = slabH / 2

  /* Members, in historical order. Each is seated by the arrival
     search; the tint is the member's OWN strand blend (the Blend
     ruling) under the member-keyed jitter, with the current cap's
     jitter damped to a third (summit discipline — a visual treatment
     of the stone's CURRENT role; its sprite and seat never change). */
  for (let pos = 0; pos < n; pos++) {
    const member = rendered[pos]!
    const sprite = assigned.get(member.id)!
    const isCap = pos === n - 1
    const tint = jitterTint(memberBaseTint(member), `${cairnId}:tint:m${member.id}`, isCap ? B.jitter / 3 : B.jitter)
    const res = placeMember(cairnId, member, sprite, pos, n, col, B, leadRight, tint)
    res.st.pos = col.length - 1
    repairs += res.repairs
    const top = col[col.length - 1]!
    insertions.push({
      memberId: member.id,
      assignedSprite: sprite,
      seatedSprite: res.seatedSprite,
      viableSeats: res.viableSeats,
      capWidthAfter: Math.round(cellsWidth(top) * 10) / 10,
      fellBack: res.fellBack,
      exhausted: res.exhausted,
    })
  }

  /* Companions, seeded by the cairn id — built BEFORE the accents so
     accent placement can honour the host law (accents sit on stack
     members only, never overlapping a companion). */
  const companions: StoneRec[] = []
  const roll = hash01(`${cairnId}:companions:roll`)
  const pattern = roll < 0.34 ? 'none' : roll < 0.67 ? 'leaner' : 'leaner+wedge'
  if (pattern !== 'none' && n >= 2) {
    const ln = buildLeaner(cairnId, col, groundY)
    if (ln) companions.push(ln)
    else dropped.push('leaner')
    if (pattern === 'leaner+wedge') {
      const wg = buildWedge(cairnId, col, groundY, ln)
      if (wg) companions.push(wg)
      else dropped.push('wedge')
    }
  }

  const accents = buildAccents(cairnId, col, n, companions, dropped)
  accents.forEach((a, k) => {
    a.pos = -10 - k
  })

  /* Fit: bounding box over every stone's rotated frame box, uniform
     scale into the production fit box. */
  const all = [...col, ...companions, ...accents]
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (const st of all) {
    const corners: Array<[number, number]> = [
      [-st.fw / 2, -st.fh / 2],
      [st.fw / 2, -st.fh / 2],
      [st.fw / 2, st.fh / 2],
      [-st.fw / 2, st.fh / 2],
    ]
    for (const [ox, oy] of corners) {
      const [wx, wy] = rotVec(ox, oy, st.tilt)
      const X = st.fcx + wx
      const Y = st.fcy + wy
      if (X < minX) minX = X
      if (Y < minY) minY = Y
      if (X > maxX) maxX = X
      if (Y > maxY) maxY = Y
    }
  }
  const bw = Math.max(maxX - minX, 1)
  const bh = Math.max(maxY - minY, 1)
  const s = Math.min(1, FIT_W / bw, FIT_H / bh)

  const toPorted = (st: StoneRec): PortedStone => {
    const m = meta(st.sprite)
    return {
      left: (st.fcx - minX) * s - (st.fw * s) / 2,
      top: (st.fcy - minY) * s - (st.fh * s) / 2,
      width: st.fw * s,
      height: st.fh * s,
      rotation: st.tilt,
      originX: (m.frame[0] / 2 + m.bboxOff[0]) * st.scale * s,
      originY: (m.frame[1] / 2 + m.bboxOff[1]) * st.scale * s,
      sprite: st.sprite,
      spriteUrl: m.url,
      tint: st.tint,
      role: st.role,
      memberId: st.memberId,
      bodyWidth: st.w * s,
      bodyHeight: st.h * s,
      bodyCx: (st.cx - minX) * s,
      bodyCy: (st.cy - minY) * s,
      seed: st.memberId ? `${cairnId}:member:${st.memberId}` : `${cairnId}:${st.role}:${st.pos}`,
    }
  }

  /* Footprint: the ground-contact span of slab + companions. */
  let gMin = Infinity
  let gMax = -Infinity
  for (const st of [slab, ...companions]) {
    const corners: Array<[number, number]> = [
      [-st.fw / 2, -st.fh / 2],
      [st.fw / 2, -st.fh / 2],
      [st.fw / 2, st.fh / 2],
      [-st.fw / 2, st.fh / 2],
    ]
    for (const [ox, oy] of corners) {
      const [wx] = rotVec(ox, oy, st.tilt)
      const X = (st.fcx + wx - minX) * s
      if (X < gMin) gMin = X
      if (X > gMax) gMax = X
    }
  }
  const footprintCx = (gMin + gMax) / 2
  const footprintHalfWidth = Math.max(footprintCx - gMin, gMax - footprintCx)

  const ported: PortedTowerLayout = {
    stones: [...col, ...companions, ...accents].map(toPorted),
    width: bw * s,
    height: bh * s,
    columnCount: n,
    memberCount: membersIn.length,
    groundY: (groundY - minY) * s,
    footprintCx,
    footprintHalfWidth,
    diagnostics: {
      blend: blendIdx,
      orderDebt: orderDebt(rendered, aprilOrderOf(rendered)),
      insertions,
      dropped,
      repairs,
    },
  }
  return { ported, col, accents, companions, scale: s }
}

/** The ported layout for a cairn's real members. Pure + deterministic. */
export function towerLayoutForMembers(cairnId: string, members: CairnMemberInput[]): PortedTowerLayout {
  return computeLayout(cairnId, members).ported
}

export type CairnDebugBody = {
  memberId: string | null
  role: string
  sprite: string
  x: number
  y: number
  cenX: number
  w: number
  h: number
  rot: number
  pairOK: boolean
  /** Accents only: the host's member index (column index − 1). */
  host?: number
}

/**
 * Unfitted (layout-space) bodies for member piles — the growth law's
 * immobility is a layout-space property (the fit scale is a viewport
 * transform over the whole pile), so tests assert against these
 * coordinates, not the fitted output. Accents and companions ride
 * along so the accent host law can be asserted geometrically.
 */
export function towerDebugForMembers(
  cairnId: string,
  members: CairnMemberInput[],
): { col: CairnDebugBody[]; accents: CairnDebugBody[]; companions: CairnDebugBody[]; scale: number } {
  const internal = computeLayout(cairnId, members)
  const body = (st: StoneRec): CairnDebugBody => ({
    memberId: st.memberId,
    role: st.role,
    sprite: st.sprite,
    x: st.cx,
    y: st.cy,
    cenX: st.cenX,
    w: st.w,
    h: st.h,
    rot: st.tilt,
    pairOK: st.pairOK,
  })
  return {
    col: internal.col.map(body),
    accents: internal.accents.map((a) => ({ ...body(a), host: a.host - 1 })),
    companions: internal.companions.map(body),
    scale: internal.scale,
  }
}

/* ================= legacy wrappers ================= */

const LEGACY_KINDS = ['branch', 'flower', 'fruit', 'seed', 'tree']

function legacyMembers(cairnId: string, count: number): CairnMemberInput[] {
  const n = towerStoneCount(count)
  const out: CairnMemberInput[] = []
  for (let i = 0; i < n; i++) {
    out.push({
      id: `${cairnId}:legacy:${i}`,
      kind: LEGACY_KINDS[i % LEGACY_KINDS.length]!,
      activity: 0.5,
      createdAt: null,
    })
  }
  return out
}

/** Legacy count-based layout (synthesized members, positional ids). */
export function towerLayout(cairnId: string, count: number): TowerLayout {
  const { ported } = computeLayout(cairnId, legacyMembers(cairnId, count))
  let colSeen = -1
  const stones: TowerStone[] = ported.stones
    .filter((st) => st.role === 'column' || st.role === 'accent')
    .map((st) => {
      const accent = st.role === 'accent'
      if (!accent) colSeen++
      return {
        left: st.left,
        top: st.top,
        size: Math.max(st.width, st.height),
        rotation: st.rotation,
        previewIndex: accent ? -1 : ported.columnCount - 1 - colSeen,
        seed: st.seed,
        accent,
      }
    })
  return { stones, width: ported.width, height: ported.height, columnCount: ported.columnCount }
}

/** Post-fit body geometry for the harness (triple rule, contacts, fit). */
export function towerDebug(cairnId: string, count: number): TowerDebug {
  const internal = computeLayout(cairnId, legacyMembers(cairnId, count))
  const s = internal.scale
  const sc = (b: StoneRec): TowerBody => ({
    x: b.cx * s,
    y: b.cy * s,
    w: b.w * s,
    h: b.h * s,
    rot: b.tilt,
  })
  return {
    col: internal.col.filter((st) => st.role === 'column').map(sc),
    accents: internal.accents.map((a) => ({ ...sc(a), host: a.host - 1, rimU: a.rimU })),
    scale: s,
  }
}
