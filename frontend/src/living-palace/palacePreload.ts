/**
 * The Palace preload (founder, 2026-11-28): "Can we preload
 * everything? Just have the seats spinning logo until
 * everything nested is accessible" — the door's mark became
 * the tree's pulsing logo the same hour, and the pattern
 * extended to every seat world over the shared factory in
 * src/imagePreload.ts. This module keeps the palace's own
 * aggregation: the list is gathered from the modules that
 * own the images (palaceCanvas's scene list, palaceTint's
 * building masters, palaceGlass's room plates), so a new
 * palace image joins the preload by joining its owner's
 * list.
 */
import { createImagePreloader, type ImageLoader } from '../imagePreload'
import { PALACE_CANVAS_ASSETS } from './palaceCanvas'
import { MASTER_URLS } from './palaceTint'
import { PLATE_URLS } from './palaceGlass'

export const PALACE_ASSET_URLS: string[] = [
  ...PALACE_CANVAS_ASSETS,
  ...Object.values(MASTER_URLS).flatMap((stages) => Object.values(stages)),
  ...Object.values(PLATE_URLS),
]

export type PalaceImageLoader = ImageLoader

const palacePreloader = createImagePreloader(PALACE_ASSET_URLS)

/** Warm every palace image. Idempotent: the same promise is
 *  returned for the whole session. */
export function preloadPalaceAssets(loader?: PalaceImageLoader): Promise<void> {
  return palacePreloader.preload(loader)
}

/** Whether the preload has settled in this session. */
export function palaceAssetsReady(): boolean {
  return palacePreloader.ready()
}

export { palacePreloader }
