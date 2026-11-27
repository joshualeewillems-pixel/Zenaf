/**
 * The Palace's plant, painted by Severine's Bench — the founder's
 * direction (2026-11-26): "Use the trees that exist for severine
 * and rumi." The Palace draws no plant of its own: a small bonsai
 * is GROWN by the Bench's canonical growth grammar
 * (bench/growth.ts growTree) and PAINTED by the Bench's own wood
 * painters (bench/paint.ts drawWoodBranch / drawPadWood) onto an
 * offscreen canvas, and the resulting image stands in the plant's
 * slot. The tree is deterministic — the painters' seeds are the
 * grammar's own, so a given state paints identically on every load.
 *
 * State mapping (PlantGlyph's states, carried over): the Bench
 * foliates a pad only where discussion evidence exists
 * (padStyleFor), and its density is 0.65 for one discussing seat,
 * 1.0 for two or more. 'growing' therefore discusses with Rumi
 * alone; 'fruiting' — the fuller state — discusses with Rumi and
 * Maeve, and paints at full density. No other state semantics are
 * claimed.
 *
 * Where canvas is unavailable (jsdom, or a browser without a 2d
 * context), the hook returns null and the caller falls back to the
 * PlantGlyph the Palace already had — the bridge never substitutes
 * other art.
 */
import { useMemo } from 'react'
import {
  growTree,
  padStyleFor,
  type BenchElement,
  type Pad,
} from '../bench/growth'
import { drawPadWood, drawWoodBranch } from '../bench/paint'
import { seedRng } from '../bench/rng'

export type PalacePlantState = 'growing' | 'fruiting'

/** The plant's own little stand of branches, dealt once: three
 *  branches off the trunk at rising stations, alternating sides. */
const ELEMENTS: BenchElement[] = [
  { handle: 'plant-a', register: 'ink', side: -1, tGrow: 0.38, elev: 30, lenOld: 118, sprite: 1 },
  { handle: 'plant-b', register: 'ink', side: 1, tGrow: 0.56, elev: 25, lenOld: 138, sprite: 2 },
  { handle: 'plant-c', register: 'ink', side: -1, tGrow: 0.74, elev: 36, lenOld: 96, sprite: 0 },
]

const CANVAS_W = 480
const CANVAS_H = 400
/** The painted image's aspect (height / width), for placement. */
export const BONSAI_ASPECT = CANVAS_H / CANVAS_W
/** The trunk's base sits this far up from the image's bottom edge
 *  (the fit margin), as a fraction of the image height. */
export const BONSAI_BASE_LIFT = 16 / CANVAS_H

const TWIG_COLOUR = 'rgb(74, 54, 38)'

function paintBonsai(state: PalacePlantState): string | null {
  try {
    if (typeof document === 'undefined') return null
    const canvas = document.createElement('canvas')
    const ctx = canvas.getContext('2d')
    if (!ctx) return null

    const grown = growTree(ELEMENTS)
    const elementsByHandle = new Map(ELEMENTS.map((e) => [e.handle, e]))
    const seats = state === 'fruiting' ? ['Rumi', 'Maeve'] : ['Rumi']
    const discussion = new Map(ELEMENTS.map((e) => [e.handle, seats]))

    // Fit: the bounding box of everything the painters will draw.
    let minX = Infinity
    let minY = Infinity
    let maxX = -Infinity
    let maxY = -Infinity
    const eat = (x: number, y: number) => {
      if (x < minX) minX = x
      if (y < minY) minY = y
      if (x > maxX) maxX = x
      if (y > maxY) maxY = y
    }
    for (const w of grown.wood) for (const [x, y] of w.pts) eat(x, y)
    for (const [x, y] of grown.trunkPath) eat(x, y)
    for (const t of grown.twigs) {
      eat(t.p0[0], t.p0[1])
      eat(t.p1[0], t.p1[1])
    }
    const pads: Pad[] = []
    for (const list of grown.padsByHandle.values()) pads.push(...list)
    pads.push(...grown.bridges)
    for (const p of pads) {
      eat(p.c[0] - p.rx, p.c[1] - p.ry)
      eat(p.c[0] + p.rx, p.c[1] + p.ry)
    }
    if (!Number.isFinite(minX) || maxX <= minX || maxY <= minY) return null

    const M = 16
    const s = Math.min(
      (CANVAS_W - 2 * M) / (maxX - minX),
      (CANVAS_H - 2 * M) / (maxY - minY),
    )
    canvas.width = CANVAS_W
    canvas.height = CANVAS_H
    ctx.setTransform(s, 0, 0, s, M - minX * s, M - minY * s)

    // Branches, finest generation first — the Bench's draw order.
    for (const gen of [2, 1, 0] as const) {
      for (const w of grown.wood) {
        if (w.gen !== gen) continue
        drawWoodBranch(ctx, w.pts, w.wRoot, w.wTip, seedRng('grammar5', w.handle, 'wood'))
      }
    }
    // The trunk over all roots.
    drawWoodBranch(ctx, grown.trunkPath, 12.5, 1.6, seedRng('grammar5', 'trunk', 'wood'), 0.55)
    // Fan twigs.
    ctx.strokeStyle = TWIG_COLOUR
    ctx.lineWidth = 0.55
    ctx.lineCap = 'round'
    for (const t of grown.twigs) {
      ctx.beginPath()
      ctx.moveTo(t.p0[0], t.p0[1])
      ctx.lineTo(t.p1[0], t.p1[1])
      ctx.stroke()
    }
    // Foliage pads, in the discussing seats' tints.
    for (const pad of pads) {
      const style = padStyleFor(pad, elementsByHandle, discussion)
      if (!style) continue
      drawPadWood(ctx, pad, style, seedRng('grammar5', pad.handle, 'pad'))
    }
    return canvas.toDataURL('image/png')
  } catch {
    return null
  }
}

const cache = new Map<PalacePlantState, string | null>()

/** The Bench-painted bonsai for a plant state, as an image href —
 *  or null where canvas painting is unavailable. */
export function useBenchBonsaiImage(state: PalacePlantState): string | null {
  return useMemo(() => {
    if (!cache.has(state)) cache.set(state, paintBonsai(state))
    return cache.get(state) ?? null
  }, [state])
}
