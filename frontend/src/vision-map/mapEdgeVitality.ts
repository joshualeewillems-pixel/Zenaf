import type { ConditionState, WaterLevel } from './ontology'
import type { MapEdgeTier } from './MapFlowEdge'

export type MapEdgeVitality = 'blocked' | 'stale' | 'active' | 'normal'

export type MapEdgeEndpointMeta = {
  touch?: string | null
  condition?: ConditionState
  water_level?: WaterLevel
}

/**
 * Edge motion + weight from relationship recency and endpoint `ConditionState` (projection-only).
 * Node stone paint uses `condition_severity` only; edges intentionally stay on merged condition for now.
 */
export function computeMapEdgeVitality(
  source: MapEdgeEndpointMeta | undefined,
  target: MapEdgeEndpointMeta | undefined,
  _tier: MapEdgeTier,
): MapEdgeVitality {
  void _tier
  if (source?.condition === 'blocked' || target?.condition === 'blocked') return 'blocked'

  const staleCond = source?.condition === 'stale' || target?.condition === 'stale'
  const ta = source?.touch ? Date.parse(source.touch) : NaN
  const tb = target?.touch ? Date.parse(target.touch) : NaN
  const tNew = Math.max(Number.isFinite(ta) ? ta : 0, Number.isFinite(tb) ? tb : 0)
  const daysSince = tNew > 0 ? (Date.now() - tNew) / 86400000 : 120

  if (staleCond || daysSince > 42) return 'stale'
  if (daysSince < 14) return 'active'
  return 'normal'
}
