import { BaseEdge, getBezierPath, type EdgeProps } from '@xyflow/react'
import type { MapEdgeVitality } from './mapEdgeVitality'

export type MapEdgeTier = 'trunk' | 'structural' | 'outcome' | 'task'

export type MapFlowEdgeData = {
  tier: MapEdgeTier
  vitality?: MapEdgeVitality
  /** Combined endpoint water → brighter / dryer strokes */
  waterTone?: 'bright' | 'normal' | 'dry'
  focusHighlight?: boolean
  collapsedBoundary?: boolean
  boundaryKind?: 'incoming' | 'outgoing'
}

export function MapFlowEdge(props: EdgeProps) {
  const [path] = getBezierPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    sourcePosition: props.sourcePosition,
    targetX: props.targetX,
    targetY: props.targetY,
    targetPosition: props.targetPosition,
  })

  const data = props.data as MapFlowEdgeData | undefined
  const tier = data?.tier ?? 'structural'
  const vitality = data?.vitality ?? 'normal'
  const waterTone = data?.waterTone ?? 'normal'
  const focus = Boolean(data?.focusHighlight)
  const collapsedBoundary = Boolean(data?.collapsedBoundary)

  const strokeW = tier === 'trunk' ? 2.65 : tier === 'structural' ? 1.85 : tier === 'outcome' ? 1.45 : 1.05
  let opacity = tier === 'task' ? 0.42 : tier === 'outcome' ? 0.55 : tier === 'trunk' ? 0.82 : 0.62
  if (focus) opacity = Math.min(1, opacity + 0.28)
  if (waterTone === 'bright') opacity = Math.min(1, opacity + 0.22)
  if (waterTone === 'dry') opacity *= 0.78
  if (vitality === 'stale') opacity *= 0.72
  if (vitality === 'blocked') opacity *= 0.85
  if (collapsedBoundary) opacity *= focus ? 0.62 : 0.45

  let stroke =
    tier === 'outcome'
      ? '#6d6674'
      : tier === 'trunk'
        ? '#5a6a62'
        : tier === 'structural'
          ? '#7a828c'
          : '#5e646e'
  if (vitality === 'blocked') stroke = '#94a3b8'
  if (waterTone === 'bright' && vitality !== 'blocked') {
    stroke =
      tier === 'outcome'
        ? '#5d5668'
        : tier === 'trunk'
          ? '#4a5c52'
          : tier === 'structural'
            ? '#5d6570'
            : '#4e5560'
  }
  if (collapsedBoundary) stroke = tier === 'trunk' ? '#7d7f86' : '#8b9098'

  const animClass =
    collapsedBoundary
      ? 'map-edge-anim map-edge-anim--collapsed-boundary'
      : vitality === 'blocked'
      ? 'map-edge-anim map-edge-anim--blocked'
      : vitality === 'stale'
        ? 'map-edge-anim map-edge-anim--stale'
        : vitality === 'active'
          ? 'map-edge-anim map-edge-anim--active'
          : 'map-edge-anim map-edge-anim--normal'

  return (
    <g className={`map-flow-edge map-flow-edge--${tier} map-edge-vitality--${vitality}${focus ? ' map-edge--focus' : ''}`}>
      <path
        d={path}
        fill="none"
        stroke={stroke}
        strokeWidth={strokeW + 2.2}
        strokeOpacity={focus ? 0.12 : 0.07}
        strokeLinecap="round"
      />
      <BaseEdge
        path={path}
        style={{
          stroke,
          strokeWidth: focus ? strokeW + 0.35 : strokeW,
          strokeOpacity: opacity,
          strokeLinecap: 'round',
        }}
        className={animClass}
      />
    </g>
  )
}
