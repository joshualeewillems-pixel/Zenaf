/**
 * The Bench growth grammar — a faithful TypeScript port of the
 * canonical machinery:
 *
 * - growth_demo3.py: PARAMS, catmull-rom trunk + trunk_point, grow(),
 *   grow_forest(), cluster_pads(), build_pads(), pad_tints() with
 *   seat_tint() over stills_v2's TINTS.
 * - stills_v2.py: chaikin(), resample(), sweep_polygon().
 *
 * Geometry is a pure function of (elements, seeds): the same element
 * table the Python harness deals from the frozen fixture grows the
 * identical polylines here — proven point-for-point in growth.test.ts
 * against growthHarness.py's dump. Painting (paint.ts) consumes this
 * geometry; widths/heights the founder's §9 strand-weight rule deals
 * are applied at paint time so the grown model stays canonical.
 *
 * The demo's held voids belong to its passage data. The fixture and
 * the product record no voids, so VOID_LIST is empty; the void forces
 * inside grow() are ported and simply never trigger.
 */
import { PythonRandom, seedRng } from './rng'

export type Pt = [number, number]
export type GeometryRegister = 'ink' | 'wire' | 'pencil'

export interface BenchElement {
  handle: string
  register: GeometryRegister
  /** 1 = grows to the right (east), -1 = to the left. */
  side: 1 | -1
  /** Station along the trunk, arc fraction 0..1 (dealt, see benchLogic). */
  tGrow: number
  /** Dealt elevation before grow_forest's 12..44 clamp. */
  elev: number
  /** Dealt length before the register's len_scale. */
  lenOld: number
  /** Cherry tint family index (stills_v2 TINTS), 0..4. */
  sprite: number
}

export interface WoodEntry {
  pts: Pt[]
  wRoot: number
  wTip: number
  gen: 0 | 1 | 2
  handle: string
  register: GeometryRegister
}

export interface Pad {
  c: Pt
  handle: string
  rx: number
  ry: number
  n: number
  reach?: boolean
  pair?: [string, string]
}

export interface Twig {
  p0: Pt
  p1: Pt
  handle: string
}

export interface GrownTree {
  primaries: Map<string, Pt[]>
  wood: WoodEntry[]
  twigs: Twig[]
  anchors: Map<string, Pt[]>
  padsByHandle: Map<string, Pad[]>
  bridges: Pad[]
  trunkPath: Pt[]
}

export const PARAMS = {
  generations: 3,
  ratio: [0.38, 0.4] as const,
  spread: [20.0, 21.0] as const,
  lift: [0.03, 0.028, 0.045] as const,
  jitter: [1.3, 1.7, 2.2] as const,
  wireBend: 30.0,
  padSpacing: { ink: 7.6, wire: 9.6, pencil: 12.5 } as Record<GeometryRegister, number>,
  woodW: { ink: 5.4, wire: 4.4, pencil: 3.8 } as Record<GeometryRegister, number>,
  lenScale: { ink: 1.04, wire: 0.97, pencil: 0.9 } as Record<GeometryRegister, number>,
  globalLen: 1.0,
  padMerge: 30.0,
}

/* ------------------------------------------------------------------ */
/* Geometry helpers (stills_v2)                                        */
/* ------------------------------------------------------------------ */

export function chaikin(points: readonly Pt[], iterations: number): Pt[] {
  let p: Pt[] = points.map(([x, y]) => [x, y])
  for (let it = 0; it < iterations; it++) {
    const out: Pt[] = [p[0]]
    for (let i = 0; i < p.length - 1; i++) {
      const [x0, y0] = p[i]
      const [x1, y1] = p[i + 1]
      out.push([0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1])
      out.push([0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1])
    }
    out.push(p[p.length - 1])
    p = out
  }
  return p
}

export function resample(path: readonly Pt[], step = 2.0): Pt[] {
  const out: Pt[] = [path[0]]
  let acc = 0.0
  let prev = path[0]
  for (let ci = 1; ci < path.length; ci++) {
    const cur = path[ci]
    const seg = Math.hypot(cur[0] - prev[0], cur[1] - prev[1])
    let t = step - acc
    while (t < seg) {
      const a = t / seg
      out.push([prev[0] + (cur[0] - prev[0]) * a, prev[1] + (cur[1] - prev[1]) * a])
      t += step
    }
    acc = seg ? (acc + seg) % step : acc
    prev = cur
  }
  const last = path[path.length - 1]
  const tail = out[out.length - 1]
  if (tail[0] !== last[0] || tail[1] !== last[1]) out.push(last)
  return out
}

export function sweepPolygon(
  path: readonly Pt[],
  wRoot: number,
  wTip: number,
  flare = 0.0,
): { polygon: Pt[]; widths: number[] } {
  const n = path.length
  const left: Pt[] = []
  const right: Pt[] = []
  const widths: number[] = []
  for (let i = 0; i < n; i++) {
    const [x, y] = path[i]
    const t = n > 1 ? i / (n - 1) : 0.0
    let w = wRoot + (wTip - wRoot) * t ** 0.85
    if (flare) w *= 1.0 + flare * Math.exp(-t * 9.0)
    widths.push(w)
    let dx: number, dy: number
    if (i === 0) {
      dx = path[1][0] - x
      dy = path[1][1] - y
    } else if (i === n - 1) {
      dx = x - path[i - 1][0]
      dy = y - path[i - 1][1]
    } else {
      dx = path[i + 1][0] - path[i - 1][0]
      dy = path[i + 1][1] - path[i - 1][1]
    }
    const L = Math.hypot(dx, dy) || 1.0
    const nx = -dy / L
    const ny = dx / L
    left.push([x + nx * w, y + ny * w])
    right.push([x - nx * w, y - ny * w])
  }
  return { polygon: [...left, ...right.reverse()], widths }
}

/* ------------------------------------------------------------------ */
/* Trunk (growth_demo3)                                                */
/* ------------------------------------------------------------------ */

export const TRUNK_CTRL: Pt[] = [
  [396, 548],
  [377, 488],
  [363, 428],
  [377, 372],
  [400, 318],
  [413, 262],
  [401, 208],
  [412, 160],
  [424, 124],
]

export function catmullRom(ctrl: readonly Pt[], samplesPerSeg = 14): Pt[] {
  const pts: Pt[] = []
  const ext: Pt[] = [ctrl[0], ...ctrl, ctrl[ctrl.length - 1]]
  for (let i = 0; i < ext.length - 3; i++) {
    const [p0, p1, p2, p3] = [ext[i], ext[i + 1], ext[i + 2], ext[i + 3]]
    for (let j = 0; j < samplesPerSeg; j++) {
      const t = j / samplesPerSeg
      const t2 = t * t
      const t3 = t2 * t
      const point: Pt = [0, 0]
      for (let k = 0; k < 2; k++) {
        point[k] =
          0.5 *
          (2 * p1[k] +
            (-p0[k] + p2[k]) * t +
            (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * t2 +
            (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * t3)
      }
      pts.push(point)
    }
  }
  pts.push(ctrl[ctrl.length - 1])
  return pts
}

export const TRUNK_PATH: Pt[] = resample(catmullRom(TRUNK_CTRL), 2.0)
const TRUNK_CUM: number[] = [0.0]
for (let i = 1; i < TRUNK_PATH.length; i++) {
  TRUNK_CUM.push(
    TRUNK_CUM[i - 1] + Math.hypot(TRUNK_PATH[i][0] - TRUNK_PATH[i - 1][0], TRUNK_PATH[i][1] - TRUNK_PATH[i - 1][1]),
  )
}
export const TRUNK_LEN = TRUNK_CUM[TRUNK_CUM.length - 1]

/** np.searchsorted (side='left'): first index whose value >= target. */
function searchsorted(sorted: readonly number[], target: number): number {
  let lo = 0
  let hi = sorted.length
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if (sorted[mid] < target) lo = mid + 1
    else hi = mid
  }
  return lo
}

/** Point + unit tangent at arc fraction t of the trunk. */
export function trunkPoint(t: number): { point: Pt; tangent: Pt } {
  const target = t * TRUNK_LEN
  let i = searchsorted(TRUNK_CUM, target)
  i = Math.max(1, Math.min(i, TRUNK_PATH.length - 1))
  const seg = TRUNK_CUM[i] - TRUNK_CUM[i - 1] || 1.0
  const a = (target - TRUNK_CUM[i - 1]) / seg
  const x = TRUNK_PATH[i - 1][0] + (TRUNK_PATH[i][0] - TRUNK_PATH[i - 1][0]) * a
  const y = TRUNK_PATH[i - 1][1] + (TRUNK_PATH[i][1] - TRUNK_PATH[i - 1][1]) * a
  const dx = TRUNK_PATH[i][0] - TRUNK_PATH[i - 1][0]
  const dy = TRUNK_PATH[i][1] - TRUNK_PATH[i - 1][1]
  const L = Math.hypot(dx, dy) || 1.0
  return { point: [x, y], tangent: [dx / L, dy / L] }
}

/* ------------------------------------------------------------------ */
/* Voids — none are dealt from the fixture or the product record.      */
/* ------------------------------------------------------------------ */

export interface VoidCircle {
  handle: string
  c: Pt
  r: number
}
export const VOID_LIST: VoidCircle[] = []

export function inVoid(x: number, y: number, pad = 1.0): VoidCircle | null {
  for (const v of VOID_LIST) {
    if (Math.hypot(x - v.c[0], y - v.c[1]) < v.r * pad) return v
  }
  return null
}

/* ------------------------------------------------------------------ */
/* grow() — the grammar itself                                         */
/* ------------------------------------------------------------------ */

function dir(phiDeg: number): Pt {
  const r = (phiDeg * Math.PI) / 180
  return [Math.cos(r), -Math.sin(r)]
}

/** Python 3 round(): half-to-even, as int(round(x)) in the machinery. */
function pyRound(x: number): number {
  const f = Math.floor(x)
  const diff = x - f
  if (diff < 0.5) return f
  if (diff > 0.5) return f + 1
  return f % 2 === 0 ? f : f + 1
}

function linspace(start: number, stop: number, num: number): number[] {
  if (num === 1) return [start]
  const out: number[] = []
  const step = (stop - start) / (num - 1)
  for (let i = 0; i < num; i++) out.push(start + step * i)
  out[num - 1] = stop
  return out
}

interface GrowCollector {
  wood: WoodEntry[]
  twigs: Twig[]
  anchors: Map<string, Pt[]>
}

function grow(
  start: Pt,
  phi: number,
  length: number,
  gen: 0 | 1 | 2,
  el: { handle: string; register: GeometryRegister },
  rng: PythonRandom,
  out: GrowCollector,
  record = true,
): Pt[] {
  const handle = el.handle
  const n = [8, 6, 5][gen]
  const step = length / n
  const pts: Pt[] = [start]
  let pos = start
  const phis: number[] = [phi]
  const wired = el.register === 'wire' && gen === 0
  const bendLo = 0.42
  const bendHi = 0.64
  for (let i = 0; i < n; i++) {
    const f = (i + 0.5) / n
    phi += (90.0 - phi) * PARAMS.lift[gen] * (0.35 + 0.65 * f)
    if (wired && bendLo <= f && f <= bendHi) {
      const nwin = Math.max(1, Math.trunc(n * (bendHi - bendLo)))
      phi +=
        phi !== 90.0
          ? -Math.sign(90.0 - phi) * (PARAMS.wireBend / nwin)
          : -PARAMS.wireBend / nwin
    }
    phi += rng.uniform(-PARAMS.jitter[gen], PARAMS.jitter[gen])
    const d = dir(phi)
    pos = [pos[0] + d[0] * step, pos[1] + d[1] * step]
    pts.push(pos)
    phis.push(phi)
  }
  if (record && gen > 0) {
    const [wr, wt] = gen === 1 ? [2.3, 0.45] : [1.15, 0.28]
    out.wood.push({ pts, wRoot: wr, wTip: wt, gen, handle, register: el.register })
  }
  if (gen === 2) {
    const fanF = [0.62, 0.8, 0.93, 1.0]
    for (let fIdx = 0; fIdx < fanF.length; fIdx++) {
      const f = fanF[fIdx]
      const baseI = Math.min(Math.trunc(f * n), n)
      const [bx, by] = pts[baseI]
      const bphi = phis[baseI]
      const kCount = f > 0.85 ? 3 : 2
      for (let k = 0; k < kCount; k++) {
        const tphi = bphi + rng.uniform(-38, 38) + (90 - bphi) * 0.12
        let tl = rng.uniform(7.0, 13.0) * (1.0 - 0.25 * (fIdx === 0 ? 1 : 0))
        if (el.register === 'pencil') tl *= 0.82
        const td = dir(tphi)
        let tip: Pt = [bx + td[0] * tl, by + td[1] * tl]
        if (inVoid(bx, by, 1.0)) continue
        let sheared = false
        for (const v of VOID_LIST) {
          const dv = Math.hypot(tip[0] - v.c[0], tip[1] - v.c[1])
          if (dv < v.r * 0.97) {
            const db = Math.hypot(bx - v.c[0], by - v.c[1])
            const s = (db - v.r * 0.97) / Math.max(1e-6, db - dv)
            tl *= Math.max(0.1, Math.min(1.0, s))
            tip = [bx + td[0] * tl, by + td[1] * tl]
            sheared = true
            break
          }
        }
        void sheared
        out.twigs.push({ p0: [bx, by], p1: tip, handle })
        const mid: Pt = [(bx + tip[0]) / 2, (by + tip[1]) / 2]
        const anchors = out.anchors.get(handle)
        if (anchors) {
          if (!inVoid(tip[0], tip[1], 1.02)) anchors.push(tip)
          if (!inVoid(mid[0], mid[1], 1.02)) anchors.push(mid)
        }
      }
    }
    return pts
  }
  // children
  let nChild: number
  if (gen === 0) {
    const baseN = { ink: 5, wire: 4, pencil: 4 }[el.register]
    const mult = { ink: 1.1, wire: 1.0, pencil: 0.85 }[el.register]
    nChild = pyRound((baseN + length / 60.0 - 1.5) * mult)
    nChild = Math.max(2, Math.min(6, nChild))
  } else {
    nChild = el.register === 'ink' || el.register === 'wire' ? 3 : 2
  }
  const fracs = linspace(0.42, 0.95, nChild)
    .map((f) => Math.min(0.97, Math.max(0.4, f + rng.uniform(-0.045, 0.045))))
    .sort((a, b) => a - b)
  let sign: number = rng.choice([1, -1] as const)
  for (const f of fracs) {
    const idx = Math.min(Math.trunc(f * n), n)
    const cstart = pts[idx]
    let cphi = phis[idx] + sign * rng.uniform(PARAMS.spread[gen] * 0.82, PARAMS.spread[gen] * 1.3)
    cphi += (90.0 - cphi) * 0.07
    const clen = length * PARAMS.ratio[gen] * (1.04 - 0.48 * f) * rng.uniform(0.85, 1.12)
    const cd = dir(cphi)
    const mid: Pt = [cstart[0] + cd[0] * clen * 0.55, cstart[1] + cd[1] * clen * 0.55]
    const v = inVoid(mid[0], mid[1], 1.12)
    if (v) {
      let best = cphi
      let bestd = -1
      for (const cand of [cphi - 24, cphi + 24]) {
        const cd2 = dir(cand)
        const m2: Pt = [cstart[0] + cd2[0] * clen * 0.55, cstart[1] + cd2[1] * clen * 0.55]
        const dd = Math.hypot(m2[0] - v.c[0], m2[1] - v.c[1])
        if (dd > bestd) {
          best = cand
          bestd = dd
        }
      }
      cphi = best
    }
    cphi = Math.max(-18.0, Math.min(198.0, cphi))
    grow(cstart, cphi, clen, (gen + 1) as 1 | 2, el, rng, out)
    sign = -sign
  }
  return pts
}

/* ------------------------------------------------------------------ */
/* cluster_pads / build_pads                                           */
/* ------------------------------------------------------------------ */

export function clusterPads(handle: string, anchors: readonly Pt[]): Pad[] {
  const raw: Array<{ c: Pt; pts: Pt[] }> = []
  for (const a of anchors) {
    let best: { c: Pt; pts: Pt[] } | null = null
    let bestd = PARAMS.padMerge
    for (const pd of raw) {
      const dd = Math.hypot(a[0] - pd.c[0], a[1] - pd.c[1])
      if (dd < bestd) {
        best = pd
        bestd = dd
      }
    }
    if (best === null) {
      raw.push({ c: a, pts: [a] })
    } else {
      best.pts.push(a)
      const n = best.pts.length
      best.c = [best.c[0] + (a[0] - best.c[0]) / n, best.c[1] + (a[1] - best.c[1]) / n]
    }
  }
  const out: Pad[] = raw.map((pd) => {
    const xs = pd.pts.map((p) => p[0])
    const ys = pd.pts.map((p) => p[1])
    const sx = pd.pts.length > 1 ? (Math.max(...xs) - Math.min(...xs)) / 2 : 10.0
    const sy = pd.pts.length > 1 ? (Math.max(...ys) - Math.min(...ys)) / 2 : 8.0
    return {
      c: pd.c,
      handle,
      rx: Math.max(15.0, Math.min(40.0, sx * 1.25 + 11)),
      ry: Math.max(12.0, Math.min(34.0, sy * 1.25 + 9)),
      n: pd.pts.length,
    }
  })
  const merged: Pad[] = []
  for (const pd of [...out].sort((a, b) => b.n - a.n)) {
    if (pd.n < 3 && merged.length) {
      let tgt = merged[0]
      let bestd = Infinity
      for (const q of merged) {
        const dd = Math.hypot(pd.c[0] - q.c[0], pd.c[1] - q.c[1])
        if (dd < bestd) {
          bestd = dd
          tgt = q
        }
      }
      tgt.rx = Math.min(46.0, tgt.rx + 3)
      tgt.n += pd.n
    } else {
      merged.push(pd)
    }
  }
  return merged
}

export function buildPads(
  elements: readonly BenchElement[],
  anchors: Map<string, Pt[]>,
  crosses: ReadonlyArray<readonly [string, string]>,
): { padsByHandle: Map<string, Pad[]>; bridges: Pad[] } {
  const padsByHandle = new Map<string, Pad[]>()
  for (const el of elements) {
    const pads = clusterPads(el.handle, anchors.get(el.handle) ?? [])
    padsByHandle.set(el.handle, pads.filter((p) => !inVoid(p.c[0], p.c[1], 1.0)))
  }
  if (anchors.get('apex')?.length) {
    padsByHandle.set('apex', clusterPads('apex', anchors.get('apex')!))
  }
  const bridges: Pad[] = []
  const seen = new Set<string>()
  for (const [a, b] of crosses) {
    if (seen.has(`${a}+${b}`)) continue
    seen.add(`${a}+${b}`)
    seen.add(`${b}+${a}`)
    const pa = padsByHandle.get(a) ?? []
    const pb = padsByHandle.get(b) ?? []
    if (!pa.length || !pb.length) continue
    let bx: Pad | null = null
    let by: Pad | null = null
    let bestd = Infinity
    for (const x of pa) {
      for (const y of pb) {
        const dd = Math.hypot(x.c[0] - y.c[0], x.c[1] - y.c[1])
        if (dd < bestd) {
          bestd = dd
          bx = x
          by = y
        }
      }
    }
    if (!bx || !by) continue
    const d = Math.hypot(bx.c[0] - by.c[0], bx.c[1] - by.c[1])
    bridges.push({
      c: [(bx.c[0] + by.c[0]) / 2, (bx.c[1] + by.c[1]) / 2 - 6],
      handle: `${a}+${b}`,
      pair: [a, b],
      rx: Math.max(14.0, Math.min(34.0, d * 0.3)),
      ry: Math.max(10.0, Math.min(22.0, d * 0.3 * 0.62)),
      n: 99,
      reach: d > 210,
    })
  }
  return { padsByHandle, bridges }
}

/* ------------------------------------------------------------------ */
/* growTree — grow_forest over a dealt element table                   */
/* ------------------------------------------------------------------ */

export function growTree(
  elements: readonly BenchElement[],
  crosses: ReadonlyArray<readonly [string, string]> = [],
): GrownTree {
  const out: GrowCollector = { wood: [], twigs: [], anchors: new Map() }
  const crossPartner = new Map<string, string>()
  for (const [a, b] of crosses) {
    crossPartner.set(a, b)
    crossPartner.set(b, a)
  }
  const primaries = new Map<string, Pt[]>()
  for (const el of elements) {
    out.anchors.set(el.handle, [])
    const rng = seedRng('grammar5', el.handle)
    const { point: start } = trunkPoint(el.tGrow)
    const elev = Math.max(12.0, Math.min(44.0, el.elev))
    let phi = el.side > 0 ? elev : 180.0 - elev
    if (crossPartner.has(el.handle)) phi += 5.0 * (phi < 90 ? 1 : -1)
    const length = el.lenOld * PARAMS.lenScale[el.register] * PARAMS.globalLen
    const pts = grow(start, phi, length, 0, el, rng, out)
    primaries.set(el.handle, pts)
    out.wood.push({
      pts,
      wRoot: PARAMS.woodW[el.register],
      wTip: 0.7,
      gen: 0,
      handle: el.handle,
      register: el.register,
    })
  }
  // apex shoot: the trunk's own continuation, no element owns it
  out.anchors.set('apex', [])
  const { point: tip, tangent: tan } = trunkPoint(1.0)
  const elApex = { handle: 'apex', register: 'pencil' as GeometryRegister }
  const rngApex = seedRng('grammar5', 'apex')
  const phiApex = (Math.atan2(-tan[1], tan[0]) * 180) / Math.PI
  const apexPts = grow(tip, phiApex, 34.0, 1, elApex, rngApex, out, false)
  out.wood.push({ pts: apexPts, wRoot: 1.6, wTip: 0.4, gen: 1, handle: 'apex', register: 'pencil' })
  const { padsByHandle, bridges } = buildPads(elements, out.anchors, crosses)
  return {
    primaries,
    wood: out.wood,
    twigs: out.twigs,
    anchors: out.anchors,
    padsByHandle,
    bridges,
    trunkPath: TRUNK_PATH,
  }
}

/* ------------------------------------------------------------------ */
/* Foliage tints (growth_demo3.pad_tints / seat_tint, stills_v2 TINTS) */
/* ------------------------------------------------------------------ */

export const SEAT_COLOURS: Record<string, [number, number, number]> = {
  Rumi: [0x92, 0xb6, 0x92],
  Valen: [0xe2, 0x4e, 0x4e],
  Maeve: [0xac, 0x7c, 0x5b],
  Jynx: [0xa5, 0x5c, 0xce],
  Lucian: [0x5c, 0x9c, 0xea],
  Aria: [0x88, 0x92, 0xc3],
}

export const TINTS: Record<number, [[number, number, number], [number, number, number]]> = {
  0: [
    [214, 158, 198],
    [172, 100, 158],
  ],
  1: [
    [230, 138, 152],
    [182, 80, 100],
  ],
  2: [
    [234, 164, 178],
    [190, 100, 118],
  ],
  3: [
    [232, 178, 204],
    [190, 124, 164],
  ],
  4: [
    [220, 170, 214],
    [176, 112, 176],
  ],
}

type RGB = [number, number, number]

function mix(a: RGB, b: RGB, f: number): RGB {
  return [
    Math.trunc(a[0] * (1.0 - f) + b[0] * f),
    Math.trunc(a[1] * (1.0 - f) + b[1] * f),
    Math.trunc(a[2] * (1.0 - f) + b[2] * f),
  ]
}

function saturate(rgb: RGB, f = 1.45): RGB {
  const m = (rgb[0] + rgb[1] + rgb[2]) / 3.0
  return [
    Math.max(0, Math.min(255, Math.trunc(m + (rgb[0] - m) * f))),
    Math.max(0, Math.min(255, Math.trunc(m + (rgb[1] - m) * f))),
    Math.max(0, Math.min(255, Math.trunc(m + (rgb[2] - m) * f))),
  ]
}

export function seatTint(basePetal: RGB, baseCentre: RGB, seat: string): [RGB, RGB] {
  const sc = saturate(SEAT_COLOURS[seat])
  const petal = mix(basePetal, sc, 0.62)
  const deep: RGB = [Math.trunc(sc[0] * 0.8), Math.trunc(sc[1] * 0.8), Math.trunc(sc[2] * 0.8)]
  const centre = mix(baseCentre, deep, 0.66)
  return [petal, centre]
}

export interface PadStyle {
  spacing: number
  tints: Array<[RGB, RGB]>
  density: number
}

/**
 * The foliage rule (growth_demo3.pad_tints): a pad style exists ONLY
 * for a branch whose record carries discussion with another seat.
 * `discussion` maps branch handle -> discussing seat names (Severine
 * is absent by construction: she is the examiner and her colour is
 * deliberately not in SEAT_COLOURS). Bridge pads foliate only where
 * BOTH cross partners were discussed.
 */
export function padStyleFor(
  pad: Pad,
  elementsByHandle: ReadonlyMap<string, BenchElement>,
  discussion: ReadonlyMap<string, readonly string[]>,
): PadStyle | null {
  if (pad.pair) {
    const [a, b] = pad.pair
    const da = discussion.get(a)
    const db = discussion.get(b)
    if (!da || !db) return null
    const seats = [...da]
    for (const s of db) if (!seats.includes(s)) seats.push(s)
    const ea = elementsByHandle.get(a)
    const eb = elementsByHandle.get(b)
    if (!ea || !eb) return null
    const base = TINTS[ea.sprite]
    const sp = (PARAMS.padSpacing[ea.register] + PARAMS.padSpacing[eb.register]) / 2
    return {
      spacing: sp,
      tints: seats.map((s) => seatTint(base[0], base[1], s)),
      density: seats.length >= 2 ? 1.0 : 0.65,
    }
  }
  if (pad.handle === 'apex') return null
  const seats = discussion.get(pad.handle)
  if (!seats || seats.length === 0) return null
  const el = elementsByHandle.get(pad.handle)
  if (!el) return null
  const base = TINTS[el.sprite]
  return {
    spacing: PARAMS.padSpacing[el.register],
    tints: seats.map((s) => seatTint(base[0], base[1], s)),
    density: seats.length >= 2 ? 1.0 : 0.65,
  }
}
