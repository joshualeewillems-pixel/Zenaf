/**
 * cairnSprites — the painted sumi-e stone sprites and their prep-time
 * alpha metadata (frame, alpha bbox, centroid, 56x56 occupancy raster,
 * top/bottom profiles, bearing segments per side).
 *
 * Metadata is computed ONCE by scripts/prep-cairn-sprites.py from the
 * PNGs in src/assets/cairn/ (the flood-fill-keyed study sprites, source
 * RGB untouched — never luma-keyed, spec section 4) and committed as
 * cairnSpriteData.json. The layout engine reads it; nothing is measured
 * per render.
 *
 * `cairn-slab` is the dedicated base slab (spec section 5): stone-large
 * flattened to April's 276x132 proportions by the same prep pipeline.
 */
import rawData from './cairnSpriteData.json'
import pebbleUrl from '../assets/cairn/pebble.png'
import stoneAngularUrl from '../assets/cairn/stone-angular.png'
import stoneChunkUrl from '../assets/cairn/stone-chunk.png'
import stoneLargeUrl from '../assets/cairn/stone-large.png'
import stoneMediumUrl from '../assets/cairn/stone-medium.png'
import stoneRoundUrl from '../assets/cairn/stone-round.png'
import stoneSmallUrl from '../assets/cairn/stone-small.png'
import stoneStandingUrl from '../assets/cairn/stone-standing.png'
import cairnSlabUrl from '../assets/cairn/cairn-slab.png'

export type CairnSegment = {
  x0: number
  y0: number
  x1: number
  y1: number
  /** Line angle in frame coords, degrees, normalized to (-90, 90]. */
  ang: number
  /** Extent along the profile axis, native px. */
  span: number
}

export type CairnSpriteMeta = {
  frame: [number, number]
  bodyW: number
  bodyH: number
  /** Alpha-bbox centre offset from frame centre, native px. */
  bboxOff: [number, number]
  /** Alpha centroid offset from frame centre, native px. */
  cenOff: [number, number]
  alphaArea: number
  occ: string[]
  topProfile: (number | null)[]
  bottomProfile: (number | null)[]
  segments: Record<'top' | 'bottom' | 'left' | 'right', CairnSegment[]>
}

export type CairnSprite = CairnSpriteMeta & { url: string }

const META = rawData as unknown as Record<string, CairnSpriteMeta>

function withUrl(name: string, url: string): CairnSprite {
  const meta = META[name]
  if (!meta) throw new Error(`cairn sprite metadata missing for ${name}`)
  return { ...meta, url }
}

export const CAIRN_SPRITES: Record<string, CairnSprite> = {
  pebble: withUrl('pebble', pebbleUrl),
  'stone-angular': withUrl('stone-angular', stoneAngularUrl),
  'stone-chunk': withUrl('stone-chunk', stoneChunkUrl),
  'stone-large': withUrl('stone-large', stoneLargeUrl),
  'stone-medium': withUrl('stone-medium', stoneMediumUrl),
  'stone-round': withUrl('stone-round', stoneRoundUrl),
  'stone-small': withUrl('stone-small', stoneSmallUrl),
  'stone-standing': withUrl('stone-standing', stoneStandingUrl),
  'cairn-slab': withUrl('cairn-slab', cairnSlabUrl),
}

/** The slab's sprite key — structural support, never a member. */
export const SLAB_SPRITE = 'cairn-slab'
/** Member sprite pool, in study order (assignSprites2's walk). */
export const UPPER_POOL = ['stone-medium', 'stone-small', 'stone-chunk', 'pebble', 'stone-angular']
export const UPPER_POOL_EXT = [...UPPER_POOL, 'stone-round', 'stone-standing']
