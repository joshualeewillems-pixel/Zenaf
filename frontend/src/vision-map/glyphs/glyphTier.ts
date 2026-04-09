/**
 * Fruit scalar (0–1) → glyph tier. Early bands: bare then leafy. Upper bands: four internal steps — tasks use
 * `DiamondFlowerGlyph`; ideas use `IdeaSeedEmergenceGlyph` stages 3–4; initiative/project use `StructuralGrowthGlyph`.
 */
export type MapGlyphTier =
  | 'leafy'
  | 'bare'
  | 'flowerBud'
  | 'flowerPair'
  | 'flowerTriple'
  | 'flowerQuad'

/** @deprecated alias — same as MapGlyphTier */
export type InitiativeTreeGlyphTier = MapGlyphTier

/** &lt;30% bare · 30–61% leafy · 61–90% four diamond stages · ≥91% open quad (mature) */
export function mapGlyphTierFromFruit(fruit01: number): MapGlyphTier {
  const f = Math.max(0, Math.min(1, fruit01))
  if (f < 0.3) return 'bare'
  if (f < 0.61) return 'leafy'
  if (f < 0.685) return 'flowerBud'
  if (f < 0.76) return 'flowerPair'
  if (f < 0.835) return 'flowerTriple'
  if (f < 0.91) return 'flowerQuad'
  return 'flowerQuad'
}

/** @deprecated use mapGlyphTierFromFruit — kept for legacy imports */
export const initiativeTreeTierFromFruit = mapGlyphTierFromFruit
