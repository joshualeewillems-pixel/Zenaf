/**
 * Bench painting — canvas ports of the canonical painters:
 *
 * - stills_v2.draw_wood: a bark-textured sweep per branch. The bark
 *   stroke colours are sampled from the machinery's own texture
 *   source (the brush-kit strip stills_v2 samples into BARK_PIXELS;
 *   28 representative pixels are carried here as data). Base fill and
 *   edge are stills_v2's computed BARK_BASE / BARK_EDGE.
 * - build_sumi_bonsai2.paint_branch: tiered ink sweep + darker core +
 *   dry strokes + paper breaths (tiers 0.95 / 0.60 / 0.32).
 * - growth_demo3.draw_pad (wood foliage: blossom stamps tinted toward
 *   the discussing seat) and build_sumi_bonsai2.paint_pad (sumi
 *   foliage: stipple in the seats' own colours).
 * - build_bench_scene: the bench / pot / soil environment, the wire
 *   coil (in the proposing seat's colour, per the definitions §2 —
 *   the scene's COPPER was Valen's red because his was the standing
 *   proposal), the pencil sumi stroke, and the footing — rendered
 *   per the CORRECTED §4: ONE triangle with root textures, never the
 *   scene script's older fan of separate roots.
 *
 * Painting consumes growth.ts geometry and the ports of the Python
 * RNG, so a given tree paints identically on every load. Painting is
 * verified structurally in paint.test.ts (a recording context);
 * on-device painting is the founder's acceptance, still owed.
 */
import { seedRng, type PythonRandom } from './rng'
import {
  chaikin,
  padStyleFor,
  resample,
  sweepPolygon,
  trunkPoint,
  PARAMS,
  SEAT_COLOURS,
  type BenchElement,
  type GrownTree,
  type Pad,
  type Pt,
} from './growth'
import type { BenchRegister, Footing } from './benchLogic'

export const SCENE_W = 800
export const SCENE_H = 676

type RGB = [number, number, number]
const PAPER: RGB = [243, 236, 220]
const SUMI_GROUND: RGB = [247, 241, 222]
const BARK_BASE: RGB = [115, 94, 76]
const BARK_EDGE: RGB = [58, 42, 28]
const TWIGC: RGB = [74, 54, 38]
const JIN: RGB = [207, 196, 174]
const JIN_EDGE: RGB = [168, 156, 130]
const SUMI_INK: RGB = [26, 24, 22]
const PENCIL_FILL: RGB = [46, 38, 34]

const BARK_PALETTE: RGB[] = [
  [223, 209, 198], [150, 123, 104], [210, 187, 169], [125, 98, 79],
  [220, 210, 198], [179, 153, 128], [108, 87, 70], [106, 83, 67],
  [153, 123, 97], [143, 115, 94], [171, 145, 122], [72, 58, 49],
  [122, 104, 90], [161, 133, 111], [154, 140, 129], [120, 93, 74],
  [86, 70, 55], [110, 92, 78], [135, 112, 94], [130, 109, 92],
  [84, 65, 51], [88, 70, 60], [112, 87, 67], [114, 93, 74],
  [109, 90, 75], [86, 72, 61], [122, 114, 111], [154, 143, 137],
]

const A_TRUNK = 0.95
const A_BRANCH = 0.6
const A_TWIG = 0.32

function rgba(c: RGB, a: number): string {
  return `rgba(${c[0]},${c[1]},${c[2]},${a})`
}

function pyRound(x: number): number {
  const f = Math.floor(x)
  const d = x - f
  if (d < 0.5) return f
  if (d > 0.5) return f + 1
  return f % 2 === 0 ? f : f + 1
}

function tracePolygon(ctx: CanvasRenderingContext2D, poly: readonly Pt[]) {
  ctx.beginPath()
  poly.forEach(([x, y], i) => {
    if (i === 0) ctx.moveTo(x, y)
    else ctx.lineTo(x, y)
  })
  ctx.closePath()
}

function strokePath(ctx: CanvasRenderingContext2D, pts: readonly Pt[]) {
  ctx.beginPath()
  pts.forEach(([x, y], i) => {
    if (i === 0) ctx.moveTo(x, y)
    else ctx.lineTo(x, y)
  })
  ctx.stroke()
}

/* ------------------------------------------------------------------ */
/* Wood (stills_v2.draw_wood)                                          */
/* ------------------------------------------------------------------ */

export function drawWoodBranch(
  ctx: CanvasRenderingContext2D,
  rawPoints: readonly Pt[],
  wRoot: number,
  wTip: number,
  rng: PythonRandom,
  flare = 0.0,
): void {
  const path = resample(chaikin(rawPoints, 3), 2.0)
  const { polygon, widths } = sweepPolygon(path, wRoot, wTip, flare)
  ctx.save()
  tracePolygon(ctx, polygon)
  ctx.fillStyle = rgba(BARK_BASE, 1)
  ctx.fill()
  ctx.clip()
  const n = path.length
  for (let i = 0; i < n; i++) {
    const [x, y] = path[i]
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
    const ux = dx / L
    const uy = dy / L
    const nx = -uy
    const ny = ux
    const w = widths[i]
    ctx.lineCap = 'round'
    for (let s = 0; s < 6; s++) {
      const off = rng.uniform(-0.82, 0.82) * w
      const ln = rng.uniform(5.0, 15.0)
      const back = rng.uniform(0.0, ln * 0.5)
      const cx = x + nx * off
      const cy = y + ny * off
      const col = rng.choice(BARK_PALETTE)
      ctx.strokeStyle = rgba(col, rng.randint(95, 175) / 255)
      ctx.lineWidth = Math.max(0.5, rng.uniform(0.9, 2.0) / 2)
      strokePath(ctx, [
        [cx - ux * back, cy - uy * back],
        [cx + ux * (ln - back), cy + uy * (ln - back)],
      ])
    }
    const shading: Array<[number, RGB, number]> = [
      [0.55, [52, 38, 24], 55],
      [-0.55, [255, 240, 214], 45],
    ]
    for (const [offF, col, al] of shading) {
      const ln = rng.uniform(6.0, 13.0)
      const cx = x + nx * offF * w
      const cy = y + ny * offF * w
      ctx.strokeStyle = rgba(col, al / 255)
      ctx.lineWidth = 0.55
      strokePath(ctx, [
        [cx, cy],
        [cx + ux * ln, cy + uy * ln],
      ])
    }
    if (rng.random() < 0.35) {
      const off = rng.uniform(-0.5, 0.5) * w
      const ln = rng.uniform(4.0, 9.0)
      const cx = x + nx * off
      const cy = y + ny * off
      ctx.strokeStyle = rgba([52, 38, 24], 130 / 255)
      ctx.lineWidth = 0.5
      strokePath(ctx, [
        [cx, cy],
        [cx + ux * ln, cy + uy * ln],
      ])
    }
  }
  ctx.restore()
  tracePolygon(ctx, polygon)
  ctx.strokeStyle = rgba(BARK_EDGE, 150 / 255)
  ctx.lineWidth = 0.5
  ctx.stroke()
}

/* ------------------------------------------------------------------ */
/* Sumi ink (build_sumi_bonsai2.paint_branch)                          */
/* ------------------------------------------------------------------ */

export function paintSumiBranch(
  ctx: CanvasRenderingContext2D,
  rawPoints: readonly Pt[],
  wRoot: number,
  wTip: number,
  tier: number,
  rng: PythonRandom,
  flare = 0.0,
): void {
  const path = resample(chaikin(rawPoints, 3), 1.6)
  const { polygon, widths } = sweepPolygon(path, wRoot, wTip, flare)
  const core = sweepPolygon(path, wRoot * 0.55, wTip * 0.55, flare).polygon
  tracePolygon(ctx, polygon)
  ctx.fillStyle = rgba(SUMI_INK, tier)
  ctx.fill()
  tracePolygon(ctx, core)
  ctx.fillStyle = rgba(SUMI_INK, Math.min(0.97, tier * 1.5))
  ctx.fill()
  ctx.save()
  tracePolygon(ctx, polygon)
  ctx.clip()
  const n = path.length
  for (let i = 0; i < n; i++) {
    const [x, y] = path[i]
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
    const ux = dx / L
    const uy = dy / L
    const nx = -uy
    const ny = ux
    const w = widths[i]
    ctx.lineCap = 'round'
    for (let s = 0; s < 4; s++) {
      const off = rng.uniform(-0.8, 0.8) * w
      const ln = rng.uniform(4.0, 13.0)
      const back = rng.uniform(0.0, ln * 0.5)
      const cx = x + nx * off
      const cy = y + ny * off
      ctx.strokeStyle = rgba(SUMI_INK, rng.randint(35, 105) / 255)
      ctx.lineWidth = Math.max(0.4, rng.uniform(0.35, 0.9) / 2)
      strokePath(ctx, [
        [cx - ux * back, cy - uy * back],
        [cx + ux * (ln - back), cy + uy * (ln - back)],
      ])
    }
    if (tier >= A_BRANCH) {
      const off = rng.uniform(-0.5, 0.5) * w
      const ln = rng.uniform(5.0, 11.0)
      const cx = x + nx * off
      const cy = y + ny * off
      ctx.strokeStyle = rgba(SUMI_GROUND, rng.randint(22, 48) / 255)
      ctx.lineWidth = 0.5
      strokePath(ctx, [
        [cx, cy],
        [cx + ux * ln, cy + uy * ln],
      ])
    }
  }
  ctx.restore()
}

/* ------------------------------------------------------------------ */
/* Jin — pale deadwood (§5)                                            */
/* ------------------------------------------------------------------ */

export function drawJinBranch(
  ctx: CanvasRenderingContext2D,
  rawPoints: readonly Pt[],
  wRoot: number,
  wTip: number,
): void {
  const path = resample(chaikin(rawPoints, 2), 2.0)
  const { polygon } = sweepPolygon(path, wRoot, wTip)
  tracePolygon(ctx, polygon)
  ctx.fillStyle = rgba(JIN, 1)
  ctx.fill()
  ctx.strokeStyle = rgba(JIN_EDGE, 1)
  ctx.lineWidth = 0.5
  ctx.stroke()
}

/* ------------------------------------------------------------------ */
/* Foliage pads                                                        */
/* ------------------------------------------------------------------ */

function drawBlossom(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  r: number,
  petal: RGB,
  centre: RGB,
  rng: PythonRandom,
): void {
  const rot = rng.uniform(0, Math.PI * 2)
  ctx.fillStyle = rgba(petal, 0.92)
  for (let k = 0; k < 5; k++) {
    const a = rot + (k * 2 * Math.PI) / 5
    const px = cx + Math.cos(a) * r * 0.52
    const py = cy + Math.sin(a) * r * 0.52
    ctx.beginPath()
    ctx.ellipse(px, py, r * 0.52, r * 0.38, a, 0, Math.PI * 2)
    ctx.fill()
  }
  ctx.beginPath()
  ctx.fillStyle = rgba(centre, 0.95)
  ctx.arc(cx, cy, r * 0.3, 0, Math.PI * 2)
  ctx.fill()
}

/** Wood-register foliage (growth_demo3.draw_pad). */
export function drawPadWood(
  ctx: CanvasRenderingContext2D,
  pad: Pad,
  style: { spacing: number; tints: Array<[RGB, RGB]>; density: number },
  rng: PythonRandom,
): void {
  let spacing = style.spacing
  if (pad.reach) spacing *= 1.5
  const { tints, density } = style
  const [cx, cy] = pad.c
  const { rx, ry } = pad
  const shadows: RGB[] = tints.map(([p]) => [
    Math.trunc(p[0] * 0.52 + 116 * 0.48),
    Math.trunc(p[1] * 0.52 + 82 * 0.48),
    Math.trunc(p[2] * 0.52 + 94 * 0.48),
  ])
  const area = Math.PI * rx * ry
  const nDots = Math.trunc(Math.max(16, Math.min(58, area / 30.0)) * density)
  for (let di = 0; di < nDots; di++) {
    const gx = rng.gauss(0, rx * 0.52)
    const gy = rng.gauss(0, ry * 0.52)
    if ((gx / (rx * 1.02)) ** 2 + (gy / (ry * 1.02)) ** 2 > 1) continue
    const x = cx + gx
    const y = cy + gy
    const r = rng.uniform(5.0, 11.0)
    let col: RGB
    let al: number
    let yy = y
    if (rng.random() < 0.15) {
      col = [96, 118, 70]
      al = rng.randint(30, 54)
      yy += ry * 0.22
    } else {
      col = shadows[di % shadows.length]
      al = rng.randint(34, 66)
    }
    ctx.beginPath()
    ctx.fillStyle = rgba(col, al / 255)
    ctx.ellipse(x, yy, r / 2, (r / 2) * 0.8, 0, 0, Math.PI * 2)
    ctx.fill()
  }
  const nSt = Math.trunc(Math.max(6, area / (spacing * spacing)) * density)
  let si = 0
  for (let s = 0; s < nSt; s++) {
    const gx = rng.gauss(0, rx * 0.55)
    const gy = rng.gauss(0, ry * 0.55)
    if ((gx / (rx * 1.06)) ** 2 + (gy / (ry * 1.06)) ** 2 > 1) continue
    const x = cx + gx
    const y = cy + gy
    const [petal, centre] = tints[si % tints.length]
    si += 1
    const r = rng.uniform(8.0, 15.0)
    if (rng.random() < 0.14) {
      ctx.beginPath()
      ctx.fillStyle = rgba(centre, 235 / 255)
      ctx.arc(x, y, r * 0.3, 0, Math.PI * 2)
      ctx.fill()
    } else {
      drawBlossom(ctx, x, y, r, petal, centre, rng)
    }
  }
}

function deep(rgb: RGB, f = 0.7): RGB {
  return [Math.trunc(rgb[0] * f), Math.trunc(rgb[1] * f), Math.trunc(rgb[2] * f)]
}
function light(rgb: RGB, f = 0.38): RGB {
  const g: RGB = [255, 252, 244]
  return [
    Math.trunc(rgb[0] + (g[0] - rgb[0]) * f),
    Math.trunc(rgb[1] + (g[1] - rgb[1]) * f),
    Math.trunc(rgb[2] + (g[2] - rgb[2]) * f),
  ]
}

/** Sumi-register foliage (build_sumi_bonsai2.paint_pad): stipple in
 *  the discussing seats' OWN colours. */
export function paintPadSumi(
  ctx: CanvasRenderingContext2D,
  pad: Pad,
  seatColours: RGB[],
  density: number,
  rng: PythonRandom,
): void {
  let dens = density
  if (pad.reach) dens *= 0.8
  const [cx, cy] = pad.c
  const { rx, ry } = pad
  const area = Math.PI * rx * ry
  const nUnder = Math.trunc(Math.max(10, area / 26.0) * dens)
  for (let i = 0; i < nUnder; i++) {
    const gx = rng.gauss(0, rx * 0.5)
    const gy = rng.gauss(0, ry * 0.5)
    if ((gx / rx) ** 2 + (gy / ry) ** 2 > 1.0) continue
    const x = cx + gx
    const y = cy + gy
    const r = rng.uniform(3.5, 8.0)
    ctx.beginPath()
    ctx.fillStyle = rgba(deep(seatColours[i % seatColours.length]), rng.randint(24, 48) / 255)
    ctx.ellipse(x, y, r / 2, (r / 2) * 0.82, 0, 0, Math.PI * 2)
    ctx.fill()
  }
  const nSt = Math.trunc(Math.max(24, area / 6.5) * dens)
  for (let i = 0; i < nSt; i++) {
    const gx = rng.gauss(0, rx * 0.55)
    const gy = rng.gauss(0, ry * 0.55)
    if ((gx / (rx * 1.04)) ** 2 + (gy / (ry * 1.04)) ** 2 > 1.0) continue
    const x = cx + gx
    const y = cy + gy
    const base = seatColours[i % seatColours.length]
    const pick = rng.random()
    const col = pick < 0.58 ? base : pick < 0.82 ? deep(base, 0.68) : light(base)
    const r = rng.uniform(0.9, 2.7)
    ctx.beginPath()
    ctx.fillStyle = rgba(col, rng.randint(120, 215) / 255)
    ctx.ellipse(x, y, r, r * 0.85, 0, 0, Math.PI * 2)
    ctx.fill()
  }
}

/* ------------------------------------------------------------------ */
/* Wire coil (§2) — in the proposing seat's colour                     */
/* ------------------------------------------------------------------ */

export function drawCoil(
  ctx: CanvasRenderingContext2D,
  primaryPts: readonly Pt[],
  colour: RGB,
): void {
  const path = resample(chaikin(primaryPts, 2), 1.6)
  const n = path.length
  const wr = PARAMS.woodW.wire
  const coil: Pt[] = []
  ctx.lineCap = 'round'
  for (let i = 0; i < n; i++) {
    const f = i / (n - 1)
    if (!(0.06 <= f && f <= 0.62)) continue
    const [x, y] = path[i]
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
    const w = wr + (0.7 - wr) * f ** 0.85 + 1.1
    coil.push([x + nx * w, y + ny * w])
    if (i % 4 === 0) {
      const ux = dx / L
      const uy = dy / L
      ctx.strokeStyle = rgba(colour, 190 / 255)
      ctx.lineWidth = 1.0
      strokePath(ctx, [
        [x + nx * w + ux * 2.6, y + ny * w + uy * 2.6],
        [x - nx * w - ux * 2.6, y - ny * w - uy * 2.6],
      ])
    }
  }
  if (coil.length > 1) {
    ctx.strokeStyle = rgba(colour, 215 / 255)
    ctx.lineWidth = 1.6
    strokePath(ctx, coil)
  }
}

/* ------------------------------------------------------------------ */
/* Pencil — one sumi stroke (§3, build_bench_scene.draw_sumi_stroke)   */
/* ------------------------------------------------------------------ */

export function drawSumiStroke(
  ctx: CanvasRenderingContext2D,
  start: Pt,
  u: Pt,
  length: number,
): void {
  const n: Pt = [-u[1], u[0]]
  const pts: Pt[] = []
  for (let i = 0; i < 25; i++) {
    const f = i / 24.0
    const bow = Math.sin(f * Math.PI) * 5.0
    pts.push([start[0] + u[0] * length * f + n[0] * bow, start[1] + u[1] * length * f + n[1] * bow])
  }
  const prof = (f: number) =>
    (3.1 + 1.6 * Math.sin(Math.PI * Math.min(1.0, f * 1.15))) * (1.0 - 0.88 * f * f)
  const left: Pt[] = []
  const right: Pt[] = []
  for (let i = 0; i < pts.length; i++) {
    const [x, y] = pts[i]
    const f = i / (pts.length - 1)
    let dx: number, dy: number
    if (i === 0) {
      dx = pts[1][0] - x
      dy = pts[1][1] - y
    } else if (i === pts.length - 1) {
      dx = x - pts[i - 1][0]
      dy = y - pts[i - 1][1]
    } else {
      dx = pts[i + 1][0] - pts[i - 1][0]
      dy = pts[i + 1][1] - pts[i - 1][1]
    }
    const L = Math.hypot(dx, dy) || 1.0
    const nx = -dy / L
    const ny = dx / L
    const w = prof(f)
    left.push([x + nx * w, y + ny * w])
    right.push([x - nx * w, y - ny * w])
  }
  tracePolygon(ctx, [...left, ...right.reverse()])
  ctx.fillStyle = rgba(PENCIL_FILL, 235 / 255)
  ctx.fill()
  const line: Pt[] = []
  for (let i = 0; i < pts.length; i++) {
    const f = i / (pts.length - 1)
    if (!(0.12 <= f && f <= 0.6)) continue
    line.push([pts[i][0] + n[0] * prof(f) * 0.15, pts[i][1] + n[1] * prof(f) * 0.15])
  }
  if (line.length > 1) {
    ctx.strokeStyle = rgba([150, 138, 124], 70 / 255)
    ctx.lineWidth = 0.5
    strokePath(ctx, line)
  }
}

/* ------------------------------------------------------------------ */
/* Footing — ONE triangle with root textures (§4, corrected)           */
/* ------------------------------------------------------------------ */

/** The footing triangle's geometry (§4): size carries the amount of
 *  prose in the record, within a small limit; assumed footing has no
 *  triangle at all. Pure — the view's tap target uses the same box. */
export function footingTriangle(
  footing: Footing,
): { tri: Pt[]; box: { x: number; y: number; w: number; h: number }; cx: number; baseHalf: number; apexH: number } | null {
  if (footing.kind === 'assumed') return null
  const s = footing.proseScale
  const baseHalf = 26 + 30 * s
  const apexH = 40 + 46 * s
  const baseY = 554
  const { point: trunkBase } = trunkPoint(0.02)
  const cx = trunkBase[0]
  const apex: Pt = [trunkPoint(0.1).point[0], 548 - apexH]
  const tri: Pt[] = [
    [cx - baseHalf, baseY],
    [cx + baseHalf, baseY],
    apex,
  ]
  return {
    tri,
    box: { x: cx - baseHalf, y: apex[1], w: baseHalf * 2, h: baseY - apex[1] },
    cx,
    baseHalf,
    apexH,
  }
}

export function drawFooting(
  ctx: CanvasRenderingContext2D,
  footing: Footing,
  register: BenchRegister,
): { x: number; y: number; w: number; h: number } | null {
  const ft = footingTriangle(footing)
  if (!ft) return null
  const { tri, cx, baseHalf, apexH } = ft
  const soilY = 550
  const baseY = 554
  const apex = tri[2]
  const documented = footing.kind === 'documented'
  if (register === 'wood') {
    tracePolygon(ctx, tri)
    ctx.fillStyle = rgba([72, 53, 36], documented ? 0.92 : 0.62)
    ctx.fill()
    // root textures: tapered strokes converging into the trunk —
    // thick and holding for documented, slighter for reported.
    const strokes = documented ? 7 : 4
    ctx.lineCap = 'round'
    for (let i = 0; i < strokes; i++) {
      const f = i / (strokes - 1)
      const bx = cx - baseHalf + 2 * baseHalf * f
      const midX = bx + (apex[0] - bx) * 0.45 + (f - 0.5) * 6
      const midY = soilY - apexH * 0.4
      ctx.strokeStyle = rgba([126, 100, 72], documented ? 0.75 : 0.4)
      ctx.lineWidth = documented ? 2.0 : 1.2
      strokePath(ctx, [
        [bx, baseY],
        [midX, midY],
        [apex[0], apex[1] + 6],
      ])
    }
  } else {
    tracePolygon(ctx, tri)
    ctx.fillStyle = rgba(SUMI_INK, documented ? A_BRANCH : A_TWIG)
    ctx.fill()
    const strokes = documented ? 6 : 3
    for (let i = 0; i < strokes; i++) {
      const f = i / (strokes - 1)
      const bx = cx - baseHalf + 2 * baseHalf * f
      ctx.strokeStyle = rgba(SUMI_GROUND, documented ? 0.5 : 0.28)
      ctx.lineWidth = 1.1
      strokePath(ctx, [
        [bx, baseY],
        [apex[0], apex[1] + 6],
      ])
    }
  }
  return ft.box
}

/* ------------------------------------------------------------------ */
/* Environment (build_bench_scene §12)                                 */
/* ------------------------------------------------------------------ */

function drawEnvironment(ctx: CanvasRenderingContext2D, register: BenchRegister): void {
  if (register === 'wood') {
    ctx.fillStyle = rgba([150, 120, 86], 1)
    ctx.fillRect(0, 584, SCENE_W, 16)
    ctx.fillStyle = rgba([120, 93, 64], 1)
    ctx.fillRect(0, 600, SCENE_W, SCENE_H - 600)
    ctx.strokeStyle = rgba([98, 74, 50], 1)
    ctx.lineWidth = 1
    for (const gx of [90, 260, 470, 640]) {
      strokePath(ctx, [
        [gx, 604],
        [gx + 26, SCENE_H - 8],
      ])
    }
    ctx.strokeStyle = rgba([84, 62, 40], 1)
    ctx.lineWidth = 2
    strokePath(ctx, [
      [0, 584],
      [SCENE_W, 584],
    ])
    // pot + rim + soil
    tracePolygon(ctx, [
      [362, 548],
      [438, 548],
      [428, 584],
      [372, 584],
    ])
    ctx.fillStyle = rgba([162, 103, 74], 1)
    ctx.fill()
    ctx.strokeStyle = rgba([124, 76, 51], 1)
    ctx.lineWidth = 1
    ctx.stroke()
    ctx.fillStyle = rgba([138, 86, 56], 1)
    ctx.fillRect(356, 540, 88, 10)
    ctx.fillStyle = rgba([76, 58, 40], 1)
    ctx.fillRect(359, 543, 82, 7)
    // moss speckles in the soil (scene seed)
    const rng = seedRng('scene1', 'moss')
    for (let i = 0; i < 42; i++) {
      const x = 361 + rng.uniform(0, 78)
      const y = 543.5 + rng.uniform(0, 5.5)
      const r = rng.uniform(0.7, 1.9)
      ctx.beginPath()
      ctx.fillStyle = rgba(rng.choice([[96, 118, 70], [110, 132, 80], [84, 104, 62]] as RGB[]), 0.8)
      ctx.arc(x, y, r, 0, Math.PI * 2)
      ctx.fill()
    }
  } else {
    // Sumi register: the environment in ink, as study 2 paints it.
    ctx.beginPath()
    ctx.fillStyle = rgba(SUMI_INK, A_TWIG * 0.6)
    ctx.ellipse(400, 591, 105, 9, 0, 0, Math.PI * 2)
    ctx.fill()
    tracePolygon(ctx, [
      [362, 548],
      [438, 548],
      [428, 584],
      [372, 584],
    ])
    ctx.fillStyle = rgba(SUMI_INK, A_TRUNK)
    ctx.fill()
    ctx.fillStyle = rgba(SUMI_INK, A_TRUNK)
    ctx.fillRect(356, 540, 88, 10)
    ctx.fillStyle = rgba(SUMI_INK, 0.75)
    ctx.fillRect(359, 543, 82, 7)
    ctx.strokeStyle = rgba(SUMI_INK, A_BRANCH)
    ctx.lineWidth = 1.4
    strokePath(ctx, [
      [0, 584],
      [SCENE_W, 584],
    ])
  }
}

/* ------------------------------------------------------------------ */
/* The whole scene                                                     */
/* ------------------------------------------------------------------ */

export interface SceneBranchInfo {
  id: string
  jin: boolean
  /** §9 emphasis factor: painted width multiplier for this branch. */
  widthScale: number
  /** Pending proposals on this branch (wire shown when > 0). */
  wireSeatColour: RGB | null
}

export interface SceneModel {
  grown: GrownTree
  register: BenchRegister
  elementsByHandle: Map<string, BenchElement>
  discussion: Map<string, string[]>
  branches: SceneBranchInfo[]
  /** Record twigs (tasks) — same per-record paint facts as a
   *  branch: jin, §9 width, wire colour. Their wood, fan twigs and
   *  foliage pads all carry the task's handle, so the painters
   *  below look branches and twigs up in one map. */
  twigs: SceneBranchInfo[]
  footing: Footing
  showExploratory: boolean
  selectedId: string | null
  pencil: { start: Pt; u: Pt; length: number } | null
}

/** Seat colour hex (#rrggbb) -> RGB for the coil. */
export function hexToRgb(hex: string): RGB {
  const m = /^#([0-9a-f]{6})$/i.exec(hex.trim())
  if (!m) return [184, 115, 51]
  const v = parseInt(m[1], 16)
  return [(v >> 16) & 255, (v >> 8) & 255, v & 255]
}

export function paintScene(ctx: CanvasRenderingContext2D, model: SceneModel): void {
  const { grown, register } = model
  ctx.save()
  ctx.clearRect(0, 0, SCENE_W, SCENE_H)
  ctx.fillStyle = rgba(register === 'wood' ? PAPER : SUMI_GROUND, 1)
  ctx.fillRect(0, 0, SCENE_W, SCENE_H)
  drawEnvironment(ctx, register)

  const infoByHandle = new Map(
    [...model.branches, ...model.twigs].map((b) => [b.id, b]),
  )
  const dimmed = (handle: string) =>
    model.selectedId !== null && handle !== model.selectedId && handle !== 'apex'

  // branches, finest generation first (the machinery's draw order)
  for (const gen of [2, 1, 0] as const) {
    for (const w of grown.wood) {
      if (w.gen !== gen) continue
      const info = infoByHandle.get(w.handle)
      const scale = info?.widthScale ?? 1
      ctx.save()
      if (dimmed(w.handle)) ctx.globalAlpha = 0.38
      const seedParts: Array<string | number> = [
        'grammar5',
        w.handle,
        'wood',
        gen,
        pyRound(w.wRoot * 10) / 10,
        pyRound(w.pts[0][0]),
        pyRound(w.pts[0][1]),
      ]
      if (info?.jin) {
        drawJinBranch(ctx, w.pts, w.wRoot * scale, w.wTip * scale)
      } else if (register === 'wood') {
        drawWoodBranch(ctx, w.pts, w.wRoot * scale, w.wTip * scale, seedRng(...seedParts))
      } else {
        paintSumiBranch(
          ctx,
          w.pts,
          w.wRoot * scale,
          w.wTip * scale,
          A_BRANCH,
          seedRng(...seedParts),
        )
      }
      ctx.restore()
    }
  }
  // trunk over all roots
  ctx.save()
  if (register === 'wood') {
    drawWoodBranch(ctx, grown.trunkPath, 12.5, 1.6, seedRng('grammar5', 'trunk', 'wood'), 0.55)
  } else {
    paintSumiBranch(ctx, grown.trunkPath, 12.5, 1.6, A_TRUNK, seedRng('grammar5', 'trunk', 'wood'), 0.55)
  }
  ctx.restore()
  // twigs
  ctx.lineCap = 'round'
  for (const t of grown.twigs) {
    ctx.save()
    if (dimmed(t.handle)) ctx.globalAlpha = 0.38
    const info = infoByHandle.get(t.handle)
    if (info?.jin) {
      ctx.strokeStyle = rgba(JIN_EDGE, 1)
      ctx.lineWidth = 0.55
    } else if (register === 'wood') {
      ctx.strokeStyle = rgba(TWIGC, 1)
      ctx.lineWidth = 0.55
    } else {
      ctx.strokeStyle = rgba(SUMI_INK, A_TWIG)
      ctx.lineWidth = 0.8
    }
    strokePath(ctx, [t.p0, t.p1])
    ctx.restore()
  }
  // footing (over the trunk base, as the scene composes it)
  drawFooting(ctx, model.footing, register)
  // wire coils (exploratory layer) — on a branch's primary, and on
  // a twig's own path: a proposal on a task coils its twig (§2).
  if (model.showExploratory) {
    for (const b of model.branches) {
      if (!b.wireSeatColour) continue
      const primary = grown.primaries.get(b.id)
      if (!primary) continue
      ctx.save()
      if (dimmed(b.id)) ctx.globalAlpha = 0.38
      drawCoil(ctx, primary, b.wireSeatColour)
      ctx.restore()
    }
    for (const t of model.twigs) {
      if (!t.wireSeatColour) continue
      const path = grown.recordTwigs.find((r) => r.handle === t.id)?.pts
      if (!path) continue
      ctx.save()
      if (dimmed(t.id)) ctx.globalAlpha = 0.38
      drawCoil(ctx, path, t.wireSeatColour)
      ctx.restore()
    }
  }
  // foliage pads — ONLY where discussion evidence exists (§7)
  const allPads: Pad[] = []
  for (const pads of grown.padsByHandle.values()) allPads.push(...pads)
  allPads.push(...grown.bridges)
  for (const pad of allPads) {
    const style = padStyleFor(pad, model.elementsByHandle, model.discussion)
    if (!style) continue
    ctx.save()
    if (dimmed(pad.handle)) ctx.globalAlpha = 0.38
    if (register === 'wood') {
      drawPadWood(ctx, pad, style, seedRng('grammar5', pad.handle, 'pad'))
    } else {
      const seats = pad.pair
        ? [...(model.discussion.get(pad.pair[0]) ?? []), ...(model.discussion.get(pad.pair[1]) ?? [])]
        : (model.discussion.get(pad.handle) ?? [])
      const colours = [...new Set(seats)]
        .map((s) => SEAT_COLOURS[s])
        .filter((c): c is RGB => Array.isArray(c))
      if (colours.length) {
        paintPadSumi(ctx, pad, colours, style.density, seedRng('sumi2', 'pad', pad.handle, pyRound(pad.c[0]), pyRound(pad.c[1])))
      }
    }
    ctx.restore()
  }
  // pencil — one session sumi stroke (exploratory layer)
  if (model.showExploratory && model.pencil) {
    drawSumiStroke(ctx, model.pencil.start, model.pencil.u, model.pencil.length)
  }
  ctx.restore()
}
