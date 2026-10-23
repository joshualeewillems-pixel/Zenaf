import { describe, expect, it } from 'vitest'
import { seatKeysForWeights } from './seatStrands'

/**
 * The reach rule behind seat-organized review (Joshua, 2026-10-22): an
 * upload belongs in a seat's review queue when any of the seat's strands
 * reaches the sorter's routing threshold (0.25) in its sort weights.
 */
describe('seatKeysForWeights', () => {
  it('attributes an agent to every seat whose strands it reaches', () => {
    // Every seat's weave carries 'self' (Compass), so a Compass-heavy
    // agent at 0.6 lands in all six review queues.
    const keys = seatKeysForWeights({ self: 0.6, word: 0.1 })
    expect(keys).toEqual(['mentor', 'champion', 'guardian', 'ambassador', 'conductor', 'maverick'])
  })

  it('a sound-heavy agent reaches the seats that carry the Ear strand', () => {
    // 'sound' is in maverick's and conductor's weaves only.
    expect(seatKeysForWeights({ sound: 0.5 })).toEqual(['conductor', 'maverick'])
  })

  it('below-threshold weights reach no seat', () => {
    expect(seatKeysForWeights({ self: 0.2, word: 0.24 })).toEqual([])
  })

  it('unsorted agents (no weights) belong to no seat yet', () => {
    expect(seatKeysForWeights(null)).toEqual([])
    expect(seatKeysForWeights(undefined)).toEqual([])
  })
})
