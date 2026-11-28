/**
 * The Campaign Board preload (founder, 2026-11-28 — the
 * seat-wide preload): Valen's board warms its painted map
 * and sprite kit at the door, behind his pulsing logo,
 * before the first lane paints. The list names the same
 * asset files the view renders (Vite resolves both imports
 * to the same URLs); when a board image is added to the
 * view, add it here too — the aggregation test counts the
 * set.
 */
import { createImagePreloader } from '../imagePreload'
import campaignMapArt from './assets/campaign-map.jpg'
import spriteCamp from './assets/sprites/camp.webp'
import spriteCrag from './assets/sprites/obstacle-crag.webp'
import spriteCopse from './assets/sprites/the-copse.webp'
import spriteFinishBanner from './assets/sprites/finish-banner.webp'
import spriteGrove from './assets/sprites/the-grove.webp'
import spriteHill from './assets/sprites/the-hill.webp'
import spriteMountain from './assets/sprites/the-mountain.webp'
import spriteOpenGround from './assets/sprites/open-ground.webp'
import spriteStronghold from './assets/sprites/stronghold.webp'

export const BOARD_ASSET_URLS: string[] = [
  campaignMapArt,
  spriteCamp,
  spriteCrag,
  spriteCopse,
  spriteFinishBanner,
  spriteGrove,
  spriteHill,
  spriteMountain,
  spriteOpenGround,
  spriteStronghold,
]

export const boardPreloader = createImagePreloader(BOARD_ASSET_URLS)
