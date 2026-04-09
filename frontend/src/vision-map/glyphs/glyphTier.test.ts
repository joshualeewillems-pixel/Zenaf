import { describe, expect, it } from 'vitest'
import { initiativeTreeTierFromFruit, mapGlyphTierFromFruit } from './glyphTier'

describe('mapGlyphTierFromFruit', () => {
  it('maps fruit scalar to bare, leafy, then four diamond flower stages', () => {
    expect(mapGlyphTierFromFruit(0)).toBe('bare')
    expect(mapGlyphTierFromFruit(0.29)).toBe('bare')
    expect(mapGlyphTierFromFruit(0.3)).toBe('leafy')
    expect(mapGlyphTierFromFruit(0.45)).toBe('leafy')
    expect(mapGlyphTierFromFruit(0.6)).toBe('leafy')
    expect(mapGlyphTierFromFruit(0.61)).toBe('flowerBud')
    expect(mapGlyphTierFromFruit(0.684)).toBe('flowerBud')
    expect(mapGlyphTierFromFruit(0.685)).toBe('flowerPair')
    expect(mapGlyphTierFromFruit(0.75)).toBe('flowerPair')
    expect(mapGlyphTierFromFruit(0.8)).toBe('flowerTriple')
    expect(mapGlyphTierFromFruit(0.834)).toBe('flowerTriple')
    expect(mapGlyphTierFromFruit(0.835)).toBe('flowerQuad')
    expect(mapGlyphTierFromFruit(0.9)).toBe('flowerQuad')
    expect(mapGlyphTierFromFruit(0.91)).toBe('flowerQuad')
    expect(mapGlyphTierFromFruit(1)).toBe('flowerQuad')
  })

  it('clamps out-of-range', () => {
    expect(mapGlyphTierFromFruit(-1)).toBe('bare')
    expect(mapGlyphTierFromFruit(2)).toBe('flowerQuad')
  })
})

describe('initiativeTreeTierFromFruit (alias)', () => {
  it('matches mapGlyphTierFromFruit', () => {
    expect(initiativeTreeTierFromFruit(0.45)).toBe(mapGlyphTierFromFruit(0.45))
  })
})
