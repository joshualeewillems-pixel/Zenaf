import type { VisionMapEntityBundle } from './blockersFromVe'
import { computeGrowthTriad, type GrowthTriadMetrics } from './mapGrowthMetrics'
import type { MapNodePayload } from './ontology'

/** Prefer server vitality on payload when present; otherwise same as computeGrowthTriad. */
export function effectiveGrowthTriad(p: MapNodePayload, bundle: VisionMapEntityBundle | null): GrowthTriadMetrics {
  if (p.vitality_source === 'server' && p.growth_triad) {
    const g = p.growth_triad
    if (
      typeof g.water === 'number' &&
      typeof g.soil === 'number' &&
      typeof g.fruit === 'number' &&
      [g.water, g.soil, g.fruit].every(Number.isFinite)
    ) {
      return { water: g.water, soil: g.soil, fruit: g.fruit }
    }
  }
  return computeGrowthTriad(p, bundle)
}
