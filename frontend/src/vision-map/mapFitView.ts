import type { XYPosition } from '@xyflow/react'
import { MAP_ENTITY_FALLBACK_LAYOUT_PX } from './mapEntityNodeLayout'

/**
 * Fit-all helpers for the Vision map open view — pure, so the open behavior
 * is testable without mounting React Flow.
 *
 * `fitZoomForBounds` mirrors the zoom math of the installed @xyflow/system
 * `getViewportForBounds` exactly (verified against node_modules source):
 * a numeric padding `p` reserves `floor((pane - pane / (1 + p)) * 0.5)` on
 * EACH side, so the usable span is `pane / (1 + p)` and
 * `zoom = min(paneW / boundsW, paneH / boundsH) / (1 + p)`,
 * clamped to [minZoom, maxZoom]. A naive `(1 - 2p)` factor is WRONG here
 * (for p = 0.15 the usable fraction is 0.87, not 0.70).
 */

export type GraphBounds = { x: number; y: number; width: number; height: number }

export type BoundedNode = {
  position: XYPosition
  width?: number | null
  height?: number | null
  measured?: { width?: number | null; height?: number | null } | null
}

/** Bounding box enclosing every node (top-left origin), or null when empty. */
export function graphBounds(nodes: ReadonlyArray<BoundedNode>): GraphBounds | null {
  if (nodes.length === 0) return null
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (const n of nodes) {
    const w = n.measured?.width ?? n.width ?? MAP_ENTITY_FALLBACK_LAYOUT_PX.width
    const h = n.measured?.height ?? n.height ?? MAP_ENTITY_FALLBACK_LAYOUT_PX.height
    minX = Math.min(minX, n.position.x)
    minY = Math.min(minY, n.position.y)
    maxX = Math.max(maxX, n.position.x + w)
    maxY = Math.max(maxY, n.position.y + h)
  }
  if (!Number.isFinite(minX) || !Number.isFinite(maxX)) return null
  return { x: minX, y: minY, width: maxX - minX, height: maxY - minY }
}

/**
 * Zoom that fits `bounds` into `pane` — the zoom React Flow's fitView would
 * pick for the same bounds/pane/padding, before min/max clamping.
 */
export function fitZoomForBounds(
  bounds: GraphBounds,
  pane: { width: number; height: number },
  opts?: { padding?: number; minZoom?: number; maxZoom?: number },
): number {
  const padding = opts?.padding ?? 0.15
  const minZoom = opts?.minZoom ?? 0.15
  const maxZoom = opts?.maxZoom ?? 0.9
  if (bounds.width <= 0 || bounds.height <= 0 || pane.width <= 0 || pane.height <= 0) {
    return maxZoom
  }
  const raw = Math.min(pane.width / bounds.width, pane.height / bounds.height) / (1 + padding)
  return Math.min(maxZoom, Math.max(minZoom, raw))
}
