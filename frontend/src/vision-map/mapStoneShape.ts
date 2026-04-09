import type { CSSProperties } from 'react'
import { organicEllipticalBorderRadiusFromSeed } from './organicBorderRadius'
import type { MapEntityKind } from './ontology'

/** Deterministic 32-bit FNV-1a — stable silhouette “grain” per node id */
function hash32(s: string): number {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

/**
 * Smooth elliptical outline (jittered % border-radius) + tiny fixed rotate only.
 * Soil rim (`MapStoneSoilRim`) sits under the clipped fill — shows grounding **deficit** (`1 − triad.soil`), not condition.
 */
export function stoneShapeMicroStyle(nodeId: string, kind: MapEntityKind): CSSProperties {
  const h = hash32(`${kind}:${nodeId}`)
  const rot = ((h % 17) - 8) * 0.028
  return {
    borderRadius: organicEllipticalBorderRadiusFromSeed(`${kind}:${nodeId}`),
    /* Visible so perimeter soil can extend past the smooth ellipse; layers use border-radius + own overflow where needed. */
    overflow: 'visible',
    transform: `rotate(${rot.toFixed(3)}deg)`,
    transformOrigin: 'center center',
  }
}
