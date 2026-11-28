/**
 * Warming the whole house (founder, 2026-11-28 — the
 * seat-wide preload): while the visitor stands at the
 * Living Tree, every seat world's imagery warms in the
 * background, one world at a time so the connection is
 * never flooded. By the time a door is opened its world is
 * usually already warm and the door never shows; the
 * door's gate (components/SeatGate) remains the guarantee
 * for a visitor who arrives faster than the warming.
 *
 * Severine's Bench needs no warming: it paints everything
 * with code and owns no raster imagery. Rumi and Lucian
 * have no worlds yet to warm.
 */
import { palacePreloader } from './living-palace/palacePreload'
import { boardPreloader } from './campaign-board/boardPreload'
import { atelierPreloader } from './aria-atelier/atelierPreload'
import { scrollPreloader } from './jynx-scroll/scrollPreload'

let started = false

/** Begin the background warming. Idempotent per session. */
export function warmAllSeatWorlds(): void {
  if (started) return
  started = true
  void (async () => {
    await palacePreloader.preload().catch(() => undefined)
    await boardPreloader.preload().catch(() => undefined)
    await atelierPreloader.preload().catch(() => undefined)
    await scrollPreloader.preload().catch(() => undefined)
  })()
}
