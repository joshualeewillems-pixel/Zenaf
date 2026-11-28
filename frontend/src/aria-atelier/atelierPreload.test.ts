// @vitest-environment jsdom
/**
 * The atelier preload aggregation (founder, 2026-11-28):
 * every formation stage, fill layer and garden painting is
 * in the set.
 */
import { describe, it, expect } from 'vitest'
import { ATELIER_ASSET_URLS } from './atelierPreload'

describe('atelier preload', () => {
  it('aggregates stages, fills and garden scenes', () => {
    // 84 stages (7 voices × 12) + 7 fill layers + 2 garden
    // scenes + 2 lotus overlays.
    expect(ATELIER_ASSET_URLS.length).toBe(95)
    expect(new Set(ATELIER_ASSET_URLS).size).toBe(95)
  })
})
