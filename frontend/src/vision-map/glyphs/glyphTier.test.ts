import { describe, expect, it } from 'vitest'
import { initiativeTreeTierFromFruit, mapGlyphTierFromFruit } from './glyphTier'

describe('mapGlyphTierFromFruit', () => {
  it('maps quadrants per fruit scalar', () => {
    expect(mapGlyphTierFromFruit(0)).toBe('leafy')
    expect(mapGlyphTierFromFruit(0.29)).toBe('leafy')
    expect(mapGlyphTierFromFruit(0.3)).toBe('bare')
    expect(mapGlyphTierFromFruit(0.45)).toBe('bare')
    expect(mapGlyphTierFromFruit(0.6)).toBe('bare')
    expect(mapGlyphTierFromFruit(0.61)).toBe('flowering')
    expect(mapGlyphTierFromFruit(0.75)).toBe('flowering')
    expect(mapGlyphTierFromFruit(0.9)).toBe('flowering')
    expect(mapGlyphTierFromFruit(0.91)).toBe('fruiting')
    expect(mapGlyphTierFromFruit(1)).toBe('fruiting')
  })

  it('clamps out-of-range', () => {
    expect(mapGlyphTierFromFruit(-1)).toBe('leafy')
    expect(mapGlyphTierFromFruit(2)).toBe('fruiting')
  })
})

describe('initiativeTreeTierFromFruit (alias)', () => {
  it('matches mapGlyphTierFromFruit', () => {
    expect(initiativeTreeTierFromFruit(0.45)).toBe(mapGlyphTierFromFruit(0.45))
  })
})
