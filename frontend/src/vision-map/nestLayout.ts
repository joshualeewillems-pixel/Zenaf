import type { Node, XYPosition } from '@xyflow/react'
import type { MapNodePayload } from './ontology'

type Box = { minX: number; minY: number; maxX: number; maxY: number }

function boxFromPoints(points: XYPosition[]): Box {
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (const p of points) {
    minX = Math.min(minX, p.x)
    minY = Math.min(minY, p.y)
    maxX = Math.max(maxX, p.x)
    maxY = Math.max(maxY, p.y)
  }
  return { minX, minY, maxX, maxY }
}

function inflate(b: Box, pad: number): Box {
  return { minX: b.minX - pad, minY: b.minY - pad, maxX: b.maxX + pad, maxY: b.maxY + pad }
}

function inside(b: Box, p: XYPosition): boolean {
  return p.x >= b.minX && p.x <= b.maxX && p.y >= b.minY && p.y <= b.maxY
}

function nearestPointOnBox(b: Box, p: XYPosition): XYPosition {
  const x = Math.max(b.minX, Math.min(b.maxX, p.x))
  const y = Math.max(b.minY, Math.min(b.maxY, p.y))
  const onBoundaryX = x === b.minX || x === b.maxX
  const onBoundaryY = y === b.minY || y === b.maxY
  if (onBoundaryX || onBoundaryY) return { x, y }
  const dLeft = Math.abs(p.x - b.minX)
  const dRight = Math.abs(b.maxX - p.x)
  const dTop = Math.abs(p.y - b.minY)
  const dBottom = Math.abs(b.maxY - p.y)
  const m = Math.min(dLeft, dRight, dTop, dBottom)
  if (m === dLeft) return { x: b.minX, y: p.y }
  if (m === dRight) return { x: b.maxX, y: p.y }
  if (m === dTop) return { x: p.x, y: b.minY }
  return { x: p.x, y: b.maxY }
}

export function expandRelativePositions(
  relativePositions: Record<string, XYPosition>,
  depthById: Record<string, number>,
  opts?: {
    baseScale?: number
    depthStep?: number
    maxScale?: number
    floorRadius?: number
    kindById?: Record<string, MapNodePayload['kind']>
  },
): Record<string, XYPosition> {
  const baseScale = opts?.baseScale ?? 1.06
  const depthStep = opts?.depthStep ?? 0.06
  const maxScale = opts?.maxScale ?? 1.34
  const floorRadius = opts?.floorRadius ?? 38
  const out: Record<string, XYPosition> = {}
  for (const [id, p] of Object.entries(relativePositions)) {
    const d = depthById[id] ?? 0
    let semantic = 0
    const k = opts?.kindById?.[id]
    if (k === 'fruit') semantic += 0.06
    if (k === 'flower') semantic += 0.03
    if (k === 'tree') semantic -= 0.04
    const scale = Math.min(maxScale, baseScale + d * depthStep + semantic)
    const len = Math.hypot(p.x, p.y)
    if (len < 1) {
      const r = floorRadius * (0.9 + Math.min(0.5, d * 0.08))
      out[id] = { x: r * (d % 2 === 0 ? 1 : -1), y: r * 0.18 }
      continue
    }
    out[id] = { x: p.x * scale, y: p.y * scale }
  }
  return out
}

export function applyLocalRepulsion(
  expandedNodeIds: string[],
  allNodes: Node<MapNodePayload>[],
  positions: Record<string, XYPosition>,
  opts?: { padding?: number; maxPush?: number; passCount?: number },
): Record<string, XYPosition> {
  if (expandedNodeIds.length === 0) return positions
  const padding = opts?.padding ?? 160
  const maxPush = opts?.maxPush ?? 190
  const passCount = Math.max(1, opts?.passCount ?? 2)

  const expandedSet = new Set(expandedNodeIds)
  const clusterPts: XYPosition[] = []
  for (const id of expandedNodeIds) {
    const p = positions[id]
    if (p) clusterPts.push(p)
  }
  if (clusterPts.length === 0) return positions
  const bb = inflate(boxFromPoints(clusterPts), padding)
  const center = {
    x: (bb.minX + bb.maxX) * 0.5,
    y: (bb.minY + bb.maxY) * 0.5,
  }

  const out = { ...positions }
  for (let pass = 0; pass < passCount; pass++) {
    for (const n of allNodes) {
      if (expandedSet.has(n.id)) continue
      const p = out[n.id]
      if (!p) continue
      if (!inside(bb, p)) continue
      const nearest = nearestPointOnBox(bb, p)
      let dx = p.x - nearest.x
      let dy = p.y - nearest.y
      if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5) {
        dx = p.x - center.x
        dy = p.y - center.y
      }
      const len = Math.hypot(dx, dy) || 1
      const nx = dx / len
      const ny = dy / len
      const xPen = Math.min(p.x - bb.minX, bb.maxX - p.x)
      const yPen = Math.min(p.y - bb.minY, bb.maxY - p.y)
      const pen = Math.max(0, Math.min(xPen, yPen))
      const push = Math.min(maxPush, 26 + (padding - pen) * 0.38)
      out[n.id] = { x: p.x + nx * push, y: p.y + ny * push }
    }
  }
  return out
}

