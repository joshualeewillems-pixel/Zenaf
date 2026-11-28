// @vitest-environment jsdom
/**
 * The scroll preload aggregation (founder, 2026-11-28):
 * the room, desk, fabric and stamp imagery is in the set.
 */
import { describe, it, expect } from 'vitest'
import { SCROLL_ASSET_URLS } from './scrollPreload'

describe('scroll preload', () => {
  it('aggregates the scene and stamp imagery', () => {
    // 9 scene images + 10 stamps.
    expect(SCROLL_ASSET_URLS.length).toBe(19)
    expect(new Set(SCROLL_ASSET_URLS).size).toBe(19)
  })
})
