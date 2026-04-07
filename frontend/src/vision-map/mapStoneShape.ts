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
 * Smooth elliptical outline (jittered % border-radius) + tiny rotate/scale on the stone face only.
 * Low soil coherence adds a bit more angular wobble (form less “resolved”).
 */
export function stoneShapeMicroStyle(
  nodeId: string,
  kind: MapEntityKind,
  soilCoherence01: number = 0.5,
): CSSProperties {
  const h = hash32(`${kind}:${nodeId}`)
  const coherence = Math.max(0, Math.min(1, soilCoherence01))
  const rough = 1 - coherence
  const rotBase = ((h % 17) - 8) * 0.065
  const rot = rotBase + rough * (((h >>> 12) % 9) - 4) * 0.055
  const sx =
    1 + ((h >>> 4) % 7) * 0.003 - 0.009 + rough * ((((h >>> 16) % 5) - 2) * 0.004)
  const sy =
    1 + ((h >>> 8) % 7) * 0.003 - 0.009 + rough * ((((h >>> 20) % 5) - 2) * 0.004)
  return {
    borderRadius: organicEllipticalBorderRadiusFromSeed(`${kind}:${nodeId}`),
    overflow: 'hidden',
    transform: `rotate(${rot.toFixed(3)}deg) scale(${sx.toFixed(4)},${sy.toFixed(4)})`,
    transformOrigin: 'center center',
  }
}
