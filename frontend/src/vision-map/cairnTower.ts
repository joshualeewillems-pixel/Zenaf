/**
 * cairnTower — procedural trail-cairn sculpture layout.
 *
 * Pure module: no imports, no DOM, no React. Everything is deterministic
 * from the cairn id (FNV-1a seeded PRNG), so a cairn renders the identical
 * sculpture on every render.
 *
 * The artistry comes from a "rule of thirds": stones are placed bottom-up,
 * and after each placement the combined center of mass of every consecutive
 * triple must lie within the middle 70% of the triple's base stone. This is
 * looser than whole-stack balancing, so the tower can lean, cantilever and
 * recover — like a real rock-balancing sculpture — while never toppling.
 *
 * Small accent stones perch precariously on the rims of column stones
 * (centers at 75–95% of the host's half-width, slight tilt, small visible
 * contact patch): they should read as "about to fall but doesn't".
 */

export type TowerStone = {
  /** px box: left/top/size of the absolutely-positioned wrapper div */
  left: number
  top: number
  size: number
  /** CSS rotation degrees (clockwise) around the stone body's center */
  rotation: number
  /** preview index driving glyph + variant (accents use -1 → neutral pebble) */
  previewIndex: number
  /** seeded key for silhouette variant / granite / internal tilt */
  seed: string
  /** true for rim-perched accent stones */
  accent: boolean
}

export type TowerLayout = {
  stones: TowerStone[]
  /** px container size (already fit-scaled) */
  width: number
  height: number
  /** column stones, excluding accents */
  columnCount: number
}

/** Body geometry in px: center, body width/height, rotation degrees. */
export type TowerBody = {
  x: number
  y: number
  w: number
  h: number
  rot: number
}

export type TowerAccent = TowerBody & {
  /** index into the column array of the host stone */
  host: number
  /** local horizontal rim offset used (fraction of host half-width) */
  rimU: number
}

export type TowerDebug = {
  col: TowerBody[]
  accents: TowerAccent[]
  /** uniform fit scale applied to reach the container */
  scale: number
}

/** Rendered stones: min(count, 12) — a garden stack gets the full twelve. */
export function towerStoneCount(count: number): number {
  return Math.min(Math.max(Math.floor(count), 1), 12)
}

function hash32(s: string): number {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

/** Deterministic PRNG — same seed, same sculpture, every render. */
function mulberry32(seed: number): () => number {
  let a = seed >>> 0
  return () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/** Body height / width — matches the SymbolicStone silhouette (~47×24). */
const BODY_ASPECT = 0.51
/** Base stone body width, px. */
const BASE_W = 50
/** Horizontal offset bound, as a fraction of the supporting stone's width. */
const DX_FRAC = 0.35
/**
 * Global leash: no column stone's center may drift further than this
 * fraction of the base width from the tower's vertical axis. The rule of
 * thirds alone lets the stack random-walk sideways into a staircase; the
 * leash keeps local artistry while the sculpture stays upright overall.
 */
const LEASH_FRAC = 0.8
/** Triple CoM must lie within this middle fraction of the base stone's width. */
const SUPPORT_MID = 0.7
const ROT_MAX = 14
const ACCENT_ROT_MAX = 25
/** Fit box for the whole composition. */
const FIT_W = 150
const FIT_H = 240
/** Body-center fractions inside the 64×64 stone viewbox. */
const BCX = 31.5 / 64
const BCY = 38 / 64

/**
 * Enforce the rule of thirds for the triple (s0, s1, new stone of w2×h2):
 * the combined center of mass (mass ∝ w×h) must lie within the middle 70%
 * of s0's width. Returns the (possibly adjusted) dx for the new stone.
 * Exact-solve toward the nearest violated edge, clamp into the dx bound,
 * then shrink toward the supporting stone — dx=0 always complies, so this
 * always terminates with a compliant offset.
 */
function enforceTriple(
  s0: TowerBody,
  s1: TowerBody,
  w2: number,
  h2: number,
  dx: number,
  absLo: number,
  absHi: number,
): number {
  const m0 = s0.w * s0.h
  const m1 = s1.w * s1.h
  const m2 = w2 * h2
  const M = m0 + m1 + m2
  const lo = s0.x - (SUPPORT_MID / 2) * s0.w
  const hi = s0.x + (SUPPORT_MID / 2) * s0.w
  // dx bound intersected with the global leash; s1.x always satisfies both
  // (inductively), and dx=0 always satisfies the triple rule, so the
  // shrink fallback below always terminates compliant.
  const xLo = Math.max(s1.x - DX_FRAC * s1.w, absLo)
  const xHi = Math.min(s1.x + DX_FRAC * s1.w, absHi)
  // Clamp up front: the seeded dx is only dx-bounded, and the triple may
  // already be compliant past the leash — every exit below must stay inside.
  let x = Math.max(xLo, Math.min(xHi, s1.x + dx))
  for (let it = 0; it < 12; it++) {
    const com = (m0 * s0.x + m1 * s1.x + m2 * x) / M
    if (com >= lo && com <= hi) return x - s1.x
    const edge = com < lo ? lo + 0.04 * s0.w : hi - 0.04 * s0.w
    const xs = Math.max(xLo, Math.min(xHi, (edge * M - m0 * s0.x - m1 * s1.x) / m2))
    if (Math.abs(xs - x) < 1e-9) {
      x = s1.x + (x - s1.x) * 0.5
      if (Math.abs(x - s1.x) < 1e-9) return 0
    } else {
      x = xs
    }
  }
  return 0
}

function buildBodies(cairnId: string, count: number): { col: TowerBody[]; accents: TowerAccent[] } {
  const n = towerStoneCount(count)
  const nAccents = n >= 9 ? 3 : n >= 6 ? 2 : 0
  const nCol = n - nAccents
  const rand = mulberry32(hash32(cairnId))

  // Column, bottom-up. Base is the largest; above it a seeded mix of
  // slabs, rounds and smalls — deliberately not monotonic.
  const col: TowerBody[] = [
    { x: 0, y: 0, w: BASE_W, h: BASE_W * BODY_ASPECT, rot: (rand() * 2 - 1) * ROT_MAX },
  ]
  for (let k = 1; k < nCol; k++) {
    const prev = col[k - 1]!
    const w = BASE_W * (0.5 + 0.55 * rand())
    const h = w * BODY_ASPECT
    const rot = (rand() * 2 - 1) * ROT_MAX
    // Nest into the stone below: overlap 45% of the smaller height —
    // contact is structural and visible, never floating, never swallowing.
    const step = (prev.h + h) / 2 - 0.45 * Math.min(prev.h, h)
    let dx = (rand() * 2 - 1) * DX_FRAC * prev.w
    if (k >= 2) dx = enforceTriple(col[k - 2]!, prev, w, h, dx, -LEASH_FRAC * BASE_W, LEASH_FRAC * BASE_W)
    else {
      // leash applies from the second stone too
      const x = prev.x + dx
      dx = Math.max(-LEASH_FRAC * BASE_W, Math.min(LEASH_FRAC * BASE_W, x)) - prev.x
    }
    col.push({ x: prev.x + dx, y: prev.y - step, w, h, rot })
  }

  // Accent stones: small pebbles perched precariously on column rims.
  const accents: TowerAccent[] = []
  for (let a = 0; a < nAccents; a++) {
    const hostIdx = 1 + Math.floor(rand() * (nCol - 1))
    const host = col[hostIdx]!
    // Prefer the rim opposite to where the stone above leans — the pebble
    // sits in the open air, like the photo.
    const aboveDx = hostIdx + 1 < nCol ? col[hostIdx + 1]!.x - host.x : 0
    let side = aboveDx >= 0 ? -1 : 1
    if (rand() < 0.25) side = -side
    const uFrac = 0.75 + 0.2 * rand()
    const wA = host.w * (0.3 + 0.15 * rand())
    const hA = wA * BODY_ASPECT
    const rotA = (rand() * 2 - 1) * ACCENT_ROT_MAX
    // Rim point in the host's local frame, rotated into the world.
    const lx = side * uFrac * (host.w / 2)
    const ly = -host.h / 2
    const rad = (host.rot * Math.PI) / 180
    const rimX = host.x + lx * Math.cos(rad) - ly * Math.sin(rad)
    const rimY = host.y + lx * Math.sin(rad) + ly * Math.cos(rad)
    // Rest on the rim: the bottom 15% of the accent dips into the host —
    // a small visible contact patch, never floating.
    accents.push({ x: rimX, y: rimY - 0.35 * hA, w: wA, h: hA, rot: rotA, host: hostIdx, rimU: lx })
  }
  return { col, accents }
}

type Corner = [number, number]

/** Rotated corners of a stone's svg box around its body center. */
function boxCorners(bx: number, by: number, S: number, rotDeg: number): Corner[] {
  const rad = (rotDeg * Math.PI) / 180
  const c = Math.cos(rad)
  const s = Math.sin(rad)
  const out: Corner[] = []
  const offs: Corner[] = [
    [-BCX, -BCY],
    [1 - BCX, -BCY],
    [1 - BCX, 1 - BCY],
    [-BCX, 1 - BCY],
  ]
  for (const [ox, oy] of offs) {
    const px = ox * S
    const py = oy * S
    out.push([bx + px * c - py * s, by + px * s + py * c])
  }
  return out
}

function fitAll(bodies: TowerBody[]): { s: number; minX: number; minY: number; width: number; height: number } {
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (const b of bodies) {
    const S = (b.w * 64) / 47
    for (const [cx, cy] of boxCorners(b.x, b.y, S, b.rot)) {
      if (cx < minX) minX = cx
      if (cy < minY) minY = cy
      if (cx > maxX) maxX = cx
      if (cy > maxY) maxY = cy
    }
  }
  const bw = Math.max(maxX - minX, 1)
  const bh = Math.max(maxY - minY, 1)
  const s = Math.min(1, FIT_W / bw, FIT_H / bh)
  return { s, minX, minY, width: bw * s, height: bh * s }
}

/** Pure tower layout: deterministic sculpture for (cairnId, count). */
export function towerLayout(cairnId: string, count: number): TowerLayout {
  const { col, accents } = buildBodies(cairnId, count)
  const fit = fitAll([...col, ...accents])
  const stones: TowerStone[] = []
  const place = (
    b: TowerBody,
    seed: string,
    previewIndex: number,
    accent: boolean,
  ): void => {
    const x = (b.x - fit.minX) * fit.s
    const y = (b.y - fit.minY) * fit.s
    const w = b.w * fit.s
    const S = (w * 64) / 47
    stones.push({
      left: x - BCX * S,
      top: y - BCY * S,
      size: S,
      rotation: b.rot,
      previewIndex,
      seed,
      accent,
    })
  }
  col.forEach((b, i) => place(b, `${cairnId}:tower:${i}`, col.length - 1 - i, false))
  accents.forEach((a, ai) => place(a, `${cairnId}:accent:${ai}`, -1, true))
  return { stones, width: fit.width, height: fit.height, columnCount: col.length }
}

/** Post-fit body geometry for the harness (triple rule, contacts, fit). */
export function towerDebug(cairnId: string, count: number): TowerDebug {
  const { col, accents } = buildBodies(cairnId, count)
  const fit = fitAll([...col, ...accents])
  const sc = (b: TowerBody): TowerBody => ({
    x: (b.x - fit.minX) * fit.s,
    y: (b.y - fit.minY) * fit.s,
    w: b.w * fit.s,
    h: b.h * fit.s,
    rot: b.rot,
  })
  return {
    col: col.map(sc),
    accents: accents.map((a) => ({ ...sc(a), host: a.host, rimU: a.rimU * fit.s })),
    scale: fit.s,
  }
}
