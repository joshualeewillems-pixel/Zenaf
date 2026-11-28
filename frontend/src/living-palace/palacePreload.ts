/**
 * The Palace preload (founder, 2026-11-28): "Can we preload
 * everything? Just have the seats spinning logo until
 * everything nested is accessible."
 *
 * The palace's imagery is heavy — painted masters for every
 * level of the descent (compound, dome, overhead, room) —
 * and fetched level by level it painted in pieces: bare
 * circles, then plates, then furniture, at every step down.
 * Now the whole set warms once, at the door: every image the
 * scenes can draw is requested and decoded before the first
 * scene paints, and the seat's logo spins while it does.
 * Once warm, the descent is instant for the rest of the
 * session — the promise is cached, and re-entering the
 * palace never waits again.
 *
 * The list is aggregated from the modules that own the
 * images (palaceCanvas's scene list, palaceTint's building
 * masters, palaceGlass's room plates), so a new scene image
 * joins the preload by joining its owner's list.
 *
 * A failed image settles its slot rather than trapping the
 * visitor at the door: the palace opens with what it has,
 * and the missing image behaves as images always have.
 */
import { PALACE_CANVAS_ASSETS } from './palaceCanvas'
import { MASTER_URLS } from './palaceTint'
import { PLATE_URLS } from './palaceGlass'

export const PALACE_ASSET_URLS: string[] = [
  ...PALACE_CANVAS_ASSETS,
  ...Object.values(MASTER_URLS).flatMap((stages) => Object.values(stages)),
  ...Object.values(PLATE_URLS),
]

/** Loads one image to decoded readiness; never rejects. */
export type PalaceImageLoader = (url: string) => Promise<void>

const loadOne: PalaceImageLoader = (url) =>
  new Promise((resolve) => {
    const img = new Image()
    let settled = false
    const finish = () => {
      if (!settled) {
        settled = true
        resolve()
      }
    }
    img.onload = () => {
      if (typeof img.decode === 'function') {
        img.decode().then(finish, finish)
      } else {
        finish()
      }
    }
    img.onerror = finish
    img.src = url
    // Already cached (warm from an earlier visit in this
    // session): the load event may never fire.
    if (img.complete) {
      if (img.naturalWidth > 0) {
        if (typeof img.decode === 'function') {
          img.decode().then(finish, finish)
        } else {
          finish()
        }
      } else {
        finish()
      }
    }
  })

let cached: Promise<void> | null = null
let ready = false

/** Warm every palace image. Idempotent: the same promise is
 *  returned for the whole session, and once it settles the
 *  palace is marked ready. */
export function preloadPalaceAssets(loader: PalaceImageLoader = loadOne): Promise<void> {
  if (!cached) {
    cached = Promise.all(PALACE_ASSET_URLS.map((url) => loader(url).catch(() => undefined))).then(
      () => {
        ready = true
      },
    )
  }
  return cached
}

/** Whether the preload has settled in this session. */
export function palaceAssetsReady(): boolean {
  return ready
}
