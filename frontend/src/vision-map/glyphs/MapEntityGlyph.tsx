import type { SVGProps } from 'react'
import type { MapNodePayload } from '../ontology'
import type { MapGlyphTier } from './glyphTier'
import { mapGlyphTierFromFruit } from './glyphTier'
import { DiamondFlowerGlyph } from './DiamondFlowerGlyph'
import { IdeaSeedEmergenceGlyph, type IdeaEmergenceStage } from './IdeaSeedEmergenceGlyph'
import { StructuralGrowthGlyph } from './StructuralGrowthGlyph'

export type MapGlyphEntity = 'idea' | 'initiative' | 'project' | 'task'

/** Idea: bare/leafy = stages 1–2; flowering = buried seed (3); fruiting = mound + shoot, no seed (4). */
const IDEA_EMERGENCE_TIER: Record<MapGlyphTier, IdeaEmergenceStage> = {
  bare: 1,
  leafy: 2,
  flowerBud: 3,
  flowerPair: 3,
  flowerTriple: 4,
  flowerQuad: 4,
}

export function mapNodeKindToGlyphEntity(kind: MapNodePayload['kind']): MapGlyphEntity | null {
  switch (kind) {
    case 'seed':
      return 'idea'
    case 'tree':
      return 'initiative'
    case 'branch':
      return 'project'
    case 'flower':
      return 'task'
    default:
      return null
  }
}

type MapEntityGlyphProps = {
  entity: MapGlyphEntity
  tier: MapGlyphTier
} & SVGProps<SVGSVGElement>

/**
 * Tasks (flowers): `DiamondFlowerGlyph` — bare/leafy = buds; flowering = 4-diamond; fruiting = fruit outline + gloss.
 * Ideas (seeds): emergence stages 1–4 via `IdeaSeedEmergenceGlyph` (fruiting = stage 4, shoot only — no seed).
 * Initiative/project: shared `StructuralGrowthGlyph` (branch rotates 90° for project in `StoneKindGlyph`).
 */
export function MapEntityGlyph({ entity, tier, className, ...rest }: MapEntityGlyphProps) {
  if (entity === 'task') {
    return (
      <DiamondFlowerGlyph
        taskTier={tier}
        className={className}
        role="presentation"
        focusable="false"
        {...rest}
      />
    )
  }
  if (entity === 'idea') {
    return (
      <IdeaSeedEmergenceGlyph
        stage={IDEA_EMERGENCE_TIER[tier]}
        className={className}
        role="presentation"
        focusable="false"
        {...rest}
      />
    )
  }
  if (entity === 'initiative' || entity === 'project') {
    return (
      <StructuralGrowthGlyph
        tier={tier}
        className={className}
        role="presentation"
        focusable="false"
        {...rest}
      />
    )
  }
  return null
}

type MapEntityGlyphFromFruitProps = {
  entity: MapGlyphEntity
  fruit01: number
} & SVGProps<SVGSVGElement>

export function MapEntityGlyphFromFruit({ entity, fruit01, ...rest }: MapEntityGlyphFromFruitProps) {
  const tier = mapGlyphTierFromFruit(fruit01)
  return <MapEntityGlyph entity={entity} tier={tier} {...rest} />
}
