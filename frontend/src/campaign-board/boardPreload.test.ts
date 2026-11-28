// @vitest-environment jsdom
/**
 * The board preload aggregation (founder, 2026-11-28): the
 * painted map and the whole sprite kit are in the set.
 */
import { describe, it, expect } from 'vitest'
import { BOARD_ASSET_URLS } from './boardPreload'

describe('board preload', () => {
  it('aggregates the painted map and every sprite', () => {
    // 1 map + 10 sprites (camp, crag, copse, finish banner,
    // grove, hill, hold waystation, mountain, open ground,
    // stronghold).
    expect(BOARD_ASSET_URLS.length).toBe(11)
    expect(new Set(BOARD_ASSET_URLS).size).toBe(11)
  })
})
