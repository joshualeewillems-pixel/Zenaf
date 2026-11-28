// @vitest-environment jsdom
/**
 * The Palace preload (founder, 2026-11-28): the whole imagery
 * warms at the door. These tests pin the aggregation (every
 * scene image, building master and room plate is in the set),
 * the settle-never-trap behaviour (a failed image cannot hold
 * the door shut), and the session cache (one warm-up, ever).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

describe('palace preload', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('aggregates every palace image: scene art, building masters, room plates', async () => {
    const { PALACE_ASSET_URLS } = await import('./palacePreload')
    // 19 canvas scene images + 9 building masters + 3 room plates.
    expect(PALACE_ASSET_URLS.length).toBe(31)
    expect(new Set(PALACE_ASSET_URLS).size).toBe(31)
    expect(PALACE_ASSET_URLS.every((u) => typeof u === 'string' && u.length > 0)).toBe(true)
  })

  it('warms every url once, settles failures, and caches for the session', async () => {
    const mod = await import('./palacePreload')
    const seen: string[] = []
    const loader = (url: string) => {
      seen.push(url)
      return url.includes('bld') ? Promise.reject(new Error('gone')) : Promise.resolve()
    }
    expect(mod.palaceAssetsReady()).toBe(false)
    await mod.preloadPalaceAssets(loader)
    expect(mod.palaceAssetsReady()).toBe(true)
    expect(seen.length).toBe(mod.PALACE_ASSET_URLS.length)
    // The session cache: a second call warms nothing again.
    await mod.preloadPalaceAssets(loader)
    expect(seen.length).toBe(mod.PALACE_ASSET_URLS.length)
  })
})
