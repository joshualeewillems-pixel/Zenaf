/**
 * Single fruit scalar (0–1) → one of four approved reference tiers (same thresholds for all entity kinds).
 */
export type MapGlyphTier = 'leafy' | 'bare' | 'flowering' | 'fruiting'

/** @deprecated alias — same as MapGlyphTier */
export type InitiativeTreeGlyphTier = MapGlyphTier

/** Maps to reference sheet quadrants: &lt;30% · 30–60% · 61–90% · 90–100% */
export function mapGlyphTierFromFruit(fruit01: number): MapGlyphTier {
  const f = Math.max(0, Math.min(1, fruit01))
  if (f < 0.3) return 'leafy'
  if (f < 0.61) return 'bare'
  if (f < 0.91) return 'flowering'
  return 'fruiting'
}

/** @deprecated use mapGlyphTierFromFruit — kept for legacy imports */
export const initiativeTreeTierFromFruit = mapGlyphTierFromFruit
