/**
 * Palace Scene 2 — stained glass takes the seat's colour.
 *
 * The founder's ruling (2026-11-26 16:27 PT): "stain glass
 * changes color with seat communication". A floor's room plate
 * carries its colour in its stained glass — the rose windows
 * and lancets — and that glass takes the hue of the seat that
 * has been talking about the floor's subject, read from the
 * same subject-interactions the compound's ivy reads (Scene
 * 1's mechanism, this scene's surface). A floor no seat has
 * talked about keeps its natural glass.
 *
 * The recolour happens ONCE per (plate, colour) on a canvas,
 * cached, on the palaceTint pattern — never a CSS filter over
 * the whole room: the stone must not move. The glass key is
 * the plates' own glass family: HSL saturation ≥ 0.35, hue in
 * [190, 330] (the blue → violet → pink of the painted glass),
 * lightness ≥ 0.25. A keyed pixel keeps its own lightness and
 * (nearly) its saturation — ×0.9 — and takes the seat colour's
 * hue. Stone (hue ~35), gold light (hue ~45) and shadow
 * (lightness < 0.25) sit outside the key by construction and
 * never move; the pixel tests pin that.
 *
 * Failure-isolated, like the ivy: where canvas or image
 * loading is unavailable (jsdom, a decode failure), the
 * natural plate stands — the Palace never breaks for its
 * glass.
 */
import { useEffect, useState } from 'react'
import { SEAT_COLORS, type SeatId } from '../council/colors'
import type { SubjectInteraction } from './palaceSceneLogic'
import type { RoomPlate } from './palaceScene2Logic'
import roomRoseImage from './assets/palace-room-rose.jpg'
import roomSpiralImage from './assets/palace-room-spiral.jpg'
import roomTiersImage from './assets/palace-room-tiers.jpg'

export const PLATE_URLS: Record<RoomPlate, string> = {
  rose: roomRoseImage,
  spiral: roomSpiralImage,
  tiers: roomTiersImage,
}

/* ------------------------------------------------------------------ */
/* the colour choice — the dominant seat, or no colour at all          */
/* ------------------------------------------------------------------ */

/** The dominant interacting seat's colour for a floor's
 *  subject; ties break by seat id so the choice is
 *  deterministic (the ivy's reading, palaceSceneLogic.
 *  ivyColorFor). No recorded interaction (or no known seat) →
 *  null: the glass stays natural. */
export function glassColorFor(interaction: SubjectInteraction | undefined): string | null {
  if (!interaction) return null
  let bestSeat: string | null = null
  let bestCount = 0
  for (const seat of Object.keys(interaction.per_seat).sort()) {
    const count = interaction.per_seat[seat]
    if (count > bestCount && seat in SEAT_COLORS) {
      bestSeat = seat
      bestCount = count
    }
  }
  return bestSeat ? SEAT_COLORS[bestSeat as SeatId] : null
}

/* ------------------------------------------------------------------ */
/* the glass key and the recolour (pure — the pixel tests pin these)   */
/* ------------------------------------------------------------------ */

/** RGB (0..255) → HSL (hue in degrees 0..360, s and l in 0..1). */
export function rgbToHsl(r: number, g: number, b: number): [number, number, number] {
  const rn = r / 255
  const gn = g / 255
  const bn = b / 255
  const max = Math.max(rn, gn, bn)
  const min = Math.min(rn, gn, bn)
  const l = (max + min) / 2
  if (max === min) return [0, 0, l]
  const d = max - min
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min)
  let h: number
  if (max === rn) h = ((gn - bn) / d + (gn < bn ? 6 : 0)) * 60
  else if (max === gn) h = ((bn - rn) / d + 2) * 60
  else h = ((rn - gn) / d + 4) * 60
  return [h, s, l]
}

/** HSL (hue in degrees, s and l in 0..1) → RGB (0..255). */
export function hslToRgb(h: number, s: number, l: number): [number, number, number] {
  const hn = (((h % 360) + 360) % 360) / 360
  if (s === 0) {
    const v = Math.round(l * 255)
    return [v, v, v]
  }
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s
  const p = 2 * l - q
  const channel = (t: number) => {
    let tn = t
    if (tn < 0) tn += 1
    if (tn > 1) tn -= 1
    if (tn < 1 / 6) return p + (q - p) * 6 * tn
    if (tn < 1 / 2) return q
    if (tn < 2 / 3) return p + (q - p) * (2 / 3 - tn) * 6
    return p
  }
  return [
    Math.round(channel(hn + 1 / 3) * 255),
    Math.round(channel(hn) * 255),
    Math.round(channel(hn - 1 / 3) * 255),
  ]
}

export function hexToHue(hex: string): number {
  const n = parseInt(hex.replace('#', ''), 16)
  const [h] = rgbToHsl((n >> 16) & 255, (n >> 8) & 255, n & 255)
  return h
}

/** The glass key: the painted glass's own family — saturated,
 *  blue → violet → pink, and lit. Stone, gold light and shadow
 *  all sit outside it. */
export function isGlassHsl(h: number, s: number, l: number): boolean {
  return s >= 0.35 && h >= 190 && h <= 330 && l >= 0.25
}

/** Recolour an RGBA pixel buffer in place: every glass pixel
 *  takes the target colour's hue at its own lightness and its
 *  saturation ×0.9; every other pixel is untouched. Alpha never
 *  moves. */
export function recolourGlassPixels(px: Uint8ClampedArray, colour: string): void {
  const targetHue = hexToHue(colour)
  for (let i = 0; i < px.length; i += 4) {
    const [h, s, l] = rgbToHsl(px[i], px[i + 1], px[i + 2])
    if (!isGlassHsl(h, s, l)) continue
    const [r, g, b] = hslToRgb(targetHue, s * 0.9, l)
    px[i] = r
    px[i + 1] = g
    px[i + 2] = b
  }
}

/* ------------------------------------------------------------------ */
/* the canvas recolour, cached per (plate, colour)                     */
/* ------------------------------------------------------------------ */

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error('plate image failed to load'))
    img.src = url
  })
}

async function recolour(masterUrl: string, colour: string): Promise<string> {
  const img = await loadImage(masterUrl)
  const canvas = document.createElement('canvas')
  canvas.width = img.naturalWidth
  canvas.height = img.naturalHeight
  const ctx = canvas.getContext('2d')
  if (!ctx) return masterUrl
  ctx.drawImage(img, 0, 0)
  const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height)
  recolourGlassPixels(imageData.data, colour)
  ctx.putImageData(imageData, 0, 0)
  return canvas.toDataURL('image/png')
}

const glassCache = new Map<string, Promise<string>>()

/** The glass-tinted plate's URL for (plate, colour), recoloured
 *  at most once per combination for the life of the page. */
export function glassPlateUrl(plate: RoomPlate, colour: string): Promise<string> {
  const master = PLATE_URLS[plate]
  const key = `${plate}:${colour}`
  let pending = glassCache.get(key)
  if (!pending) {
    pending = recolour(master, colour).catch(() => master)
    glassCache.set(key, pending)
  }
  return pending
}

/** The plate's URL now, its glass tinted when the one-time
 *  recolour lands. A null colour is the natural plate, always —
 *  a floor no seat has talked about keeps its own glass. Starts
 *  from the natural plate so a room never stands blank while
 *  its glass is being coloured. */
export function useGlassPlate(plate: RoomPlate, colour: string | null): string {
  const master = PLATE_URLS[plate]
  const key = `${plate}:${colour}`
  const [state, setState] = useState<{ key: string; url: string }>({ key, url: master })
  useEffect(() => {
    if (colour === null) return
    let live = true
    glassPlateUrl(plate, colour)
      .then((url) => {
        if (live) setState({ key, url })
      })
      .catch(() => {})
    return () => {
      live = false
    }
  }, [plate, colour, key])
  return colour !== null && state.key === key ? state.url : master
}
