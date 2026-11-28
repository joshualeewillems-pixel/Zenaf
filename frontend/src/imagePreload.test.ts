// @vitest-environment jsdom
/**
 * The shared preload factory (founder, 2026-11-28): warms
 * every url once, settles failures without trapping, and
 * caches for the session.
 */
import { describe, it, expect } from 'vitest'
import { createImagePreloader } from './imagePreload'

describe('createImagePreloader', () => {
  it('warms every url once, settles failures, caches', async () => {
    const preloader = createImagePreloader(['a.png', 'b.png', 'c.png'])
    const seen: string[] = []
    const loader = (url: string) => {
      seen.push(url)
      return url === 'b.png' ? Promise.reject(new Error('gone')) : Promise.resolve()
    }
    expect(preloader.ready()).toBe(false)
    await preloader.preload(loader)
    expect(preloader.ready()).toBe(true)
    expect(seen).toEqual(['a.png', 'b.png', 'c.png'])
    await preloader.preload(loader)
    expect(seen).toHaveLength(3)
  })
})
