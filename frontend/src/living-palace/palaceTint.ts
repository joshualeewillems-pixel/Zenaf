/**
 * Palace Scene 1 — ivy tinting.
 *
 * The nine masters (founder-supplied grey-ivy set, 2026-11-26)
 * carry their ivy in monochrome grey; the stone is warm. A
 * building's ivy takes the colour of the seat that has been
 * talking about its subject (palaceSceneLogic.ivyColorFor) — the
 * recolour happens ONCE per (master, colour) on a canvas, cached,
 * and the building then stands as a plain <img>. Never a CSS
 * filter over the whole building: the stone must not move.
 *
 * The formula (verified on the masters before the build):
 * warmth = R − B; ivy weight = clip((52 − warmth) / 42, 0, 1),
 * gated to alpha > 30; the recoloured pixel is the seat colour
 * scaled so its luminance equals the pixel's own luminance,
 * blended by weight. The stone (warmth ≥ 94) has weight 0 by
 * construction — untouched.
 *
 * Failure-isolated: where canvas or image loading is unavailable
 * (jsdom, a decode failure), the master itself stands, grey ivy
 * and all — the Palace never breaks for its ivy.
 */
import { useEffect, useState } from 'react'
import type { PalaceClassId } from './palaceSceneLogic'
import bldBigS1 from './assets/palace-bld-big-s1.png'
import bldBigS2 from './assets/palace-bld-big-s2.png'
import bldBigS3 from './assets/palace-bld-big-s3.png'
import bldMediumS1 from './assets/palace-bld-medium-s1.png'
import bldMediumS2 from './assets/palace-bld-medium-s2.png'
import bldMediumS3 from './assets/palace-bld-medium-s3.png'
import bldSingleS1 from './assets/palace-bld-single-s1.png'
import bldSingleS2 from './assets/palace-bld-single-s2.png'
import bldSingleS3 from './assets/palace-bld-single-s3.png'

export const MASTER_URLS: Record<PalaceClassId, Record<1 | 2 | 3, string>> = {
  big: { 1: bldBigS1, 2: bldBigS2, 3: bldBigS3 },
  medium: { 1: bldMediumS1, 2: bldMediumS2, 3: bldMediumS3 },
  small: { 1: bldSingleS1, 2: bldSingleS2, 3: bldSingleS3 },
}

function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.replace('#', ''), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function luminance(r: number, g: number, b: number): number {
  return 0.299 * r + 0.587 * g + 0.114 * b
}

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error('master image failed to load'))
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
  const px = imageData.data
  const [cr, cg, cb] = hexToRgb(colour)
  const colourLum = luminance(cr, cg, cb) || 1
  for (let i = 0; i < px.length; i += 4) {
    if (px[i + 3] <= 30) continue
    const warmth = px[i] - px[i + 2]
    let weight = (52 - warmth) / 42
    if (weight <= 0) continue
    if (weight > 1) weight = 1
    const scale = luminance(px[i], px[i + 1], px[i + 2]) / colourLum
    px[i] = px[i] + (cr * scale - px[i]) * weight
    px[i + 1] = px[i + 1] + (cg * scale - px[i + 1]) * weight
    px[i + 2] = px[i + 2] + (cb * scale - px[i + 2]) * weight
  }
  ctx.putImageData(imageData, 0, 0)
  return canvas.toDataURL('image/png')
}

const tintCache = new Map<string, Promise<string>>()

/** The tinted master's URL for (class, stage, colour), recoloured
 *  at most once per combination for the life of the page. */
export function tintedMasterUrl(
  klass: PalaceClassId,
  stage: 1 | 2 | 3,
  colour: string,
): Promise<string> {
  const master = MASTER_URLS[klass][stage]
  const key = `${klass}:${stage}:${colour}`
  let pending = tintCache.get(key)
  if (!pending) {
    pending = recolour(master, colour).catch(() => master)
    tintCache.set(key, pending)
  }
  return pending
}

/** The master's URL now, its tint when the one-time recolour
 *  lands. Starts from the master itself so a building never stands
 *  blank while its ivy is being coloured. */
export function useTintedMaster(klass: PalaceClassId, stage: 1 | 2 | 3, colour: string): string {
  const master = MASTER_URLS[klass][stage]
  const [state, setState] = useState<{ key: string; url: string }>({
    key: `${klass}:${stage}:${colour}`,
    url: master,
  })
  useEffect(() => {
    let live = true
    const key = `${klass}:${stage}:${colour}`
    tintedMasterUrl(klass, stage, colour)
      .then((url) => {
        if (live) setState({ key, url })
      })
      .catch(() => {})
    return () => {
      live = false
    }
  }, [klass, stage, colour])
  return state.key === `${klass}:${stage}:${colour}` ? state.url : master
}
