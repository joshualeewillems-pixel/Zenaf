/**
 * Piecewise glow driver for map glyphs vs triad `fruit` (0–1).
 * Each band ramps 0→1 with an ease-out so intensity **surges** near 0.30 / 0.60 / 0.90 / 1.0, then resets at 0.31 / 0.61 / 0.91.
 */

const EASE_EXP = 2.35

/** Maps linear progress t∈[0,1] within a band to a curve that is soft at the start and steep near the cap. */
function easeTowardTierCap(t: number): number {
  const x = Math.max(0, Math.min(1, t))
  return 1 - Math.pow(1 - x, EASE_EXP)
}

export function fruitGlowIntensity(fruit01: number): number {
  const f = Math.max(0, Math.min(1, fruit01))
  if (f <= 0.3) return easeTowardTierCap(f / 0.3)
  if (f < 0.31) return 0
  if (f <= 0.6) return easeTowardTierCap((f - 0.31) / (0.6 - 0.31))
  if (f < 0.61) return 0
  if (f <= 0.9) return easeTowardTierCap((f - 0.61) / (0.9 - 0.61))
  if (f < 0.91) return 0
  return easeTowardTierCap((f - 0.91) / (1 - 0.91))
}

/** CSS `filter` for golden outer glow; omit when intensity ~ 0. */
export function fruitGlowFilterCss(intensity: number): string | undefined {
  if (intensity <= 0.0001) return undefined
  const s = 0.45 + 0.55 * intensity
  const a1 = 0.5 + 0.48 * s
  const a2 = 0.26 + 0.45 * s
  const a3 = 0.1 + 0.32 * s
  const b1 = 2.5 + 18 * s
  const b2 = 7 + 36 * s
  const b3 = 16 + 48 * s
  return `drop-shadow(0 0 ${b1}px rgba(255, 214, 125, ${a1})) drop-shadow(0 0 ${b2}px rgba(201, 162, 39, ${a2})) drop-shadow(0 0 ${b3}px rgba(255, 240, 195, ${a3}))`
}
