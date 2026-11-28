/**
 * The Atelier preload (founder, 2026-11-28 — the seat-wide
 * preload): Aria's world warms its whole imagery at the
 * door, behind her pulsing logo — the 84 formation stage
 * paintings, the seven voices' fill layers, and the two
 * garden paintings with their lotus overlays. The list
 * names the same asset files the view renders (Vite
 * resolves both imports to the same URLs); when an atelier
 * image is added to the view, add it here too — the
 * aggregation test counts the set.
 */
import { createImagePreloader } from '../imagePreload'
import { STAGE_IMAGES } from './stageImages'
import ariaFill from './assets/layer-aria-fill.png'
import jynxFill from './assets/layer-jynx-fill.png'
import lucianFill from './assets/layer-lucian-fill.png'
import maeveFill from './assets/layer-maeve-fill.png'
import rumiFill from './assets/layer-rumi-fill.png'
import severineFill from './assets/layer-severine-fill.png'
import valenFill from './assets/layer-valen-fill.png'
import gardenScene1 from './assets/garden-scene1.webp'
import gardenScene1Lotus from './assets/garden-scene1-lotus.png'
import gardenScene2 from './assets/garden-scene2.webp'
import gardenScene2Lotus from './assets/garden-scene2-lotus.png'

export const ATELIER_ASSET_URLS: string[] = [
  ...Object.values(STAGE_IMAGES).flatMap((stages) => [...stages]),
  ariaFill,
  jynxFill,
  lucianFill,
  maeveFill,
  rumiFill,
  severineFill,
  valenFill,
  gardenScene1,
  gardenScene1Lotus,
  gardenScene2,
  gardenScene2Lotus,
]

export const atelierPreloader = createImagePreloader(ATELIER_ASSET_URLS)
