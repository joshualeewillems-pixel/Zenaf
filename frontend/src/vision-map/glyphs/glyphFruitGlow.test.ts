import { describe, expect, it } from 'vitest'
import { fruitGlowFilterCss, fruitGlowIntensity } from './glyphFruitGlow'

describe('fruitGlowIntensity', () => {
  it('eases 0→1 on [0, 0.30] with surge near cap; drops in (0.30, 0.31)', () => {
    expect(fruitGlowIntensity(0)).toBe(0)
    expect(fruitGlowIntensity(0.3)).toBeCloseTo(1, 5)
    expect(fruitGlowIntensity(0.305)).toBe(0)
    // ~27% fruit → should already be very high (ease-out toward first cap)
    expect(fruitGlowIntensity(0.27)).toBeGreaterThan(0.92)
    // Mid-first-band: above linear 0.5
    expect(fruitGlowIntensity(0.15)).toBeGreaterThan(0.5)
  })

  it('eases on [0.31, 0.60] then resets before 0.61', () => {
    expect(fruitGlowIntensity(0.31)).toBe(0)
    expect(fruitGlowIntensity(0.6)).toBeCloseTo(1, 5)
    expect(fruitGlowIntensity(0.605)).toBe(0)
    expect(fruitGlowIntensity(0.455)).toBeGreaterThan(0.5)
  })

  it('eases on [0.61, 0.90] then [0.91, 1]', () => {
    expect(fruitGlowIntensity(0.61)).toBe(0)
    expect(fruitGlowIntensity(0.9)).toBeCloseTo(1, 5)
    expect(fruitGlowIntensity(0.905)).toBe(0)
    expect(fruitGlowIntensity(0.91)).toBe(0)
    expect(fruitGlowIntensity(1)).toBeCloseTo(1, 5)
  })
})

describe('fruitGlowFilterCss', () => {
  it('returns undefined at zero', () => {
    expect(fruitGlowFilterCss(0)).toBeUndefined()
  })

  it('returns triple drop-shadow when intensity > 0', () => {
    const s = fruitGlowFilterCss(1)!
    expect(s.split('drop-shadow').length - 1).toBe(3)
    expect(s).toContain('rgba(201, 162, 39')
  })
})
