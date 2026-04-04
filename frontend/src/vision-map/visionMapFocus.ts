import type { Edge, Node } from '@xyflow/react'
import type { MapNodePayload } from './ontology'

/**
 * All nodes in the same connected component as the focus, treating edges as undirected.
 * Keeps sibling branches (projects) under one initiative tree from being dimmed when one is selected.
 */
export function computeLineageNodeIds(edges: Edge[], focusId: string): Set<string> {
  const adj = new Map<string, string[]>()
  const link = (a: string, b: string) => {
    if (!adj.has(a)) adj.set(a, [])
    if (!adj.has(b)) adj.set(b, [])
    adj.get(a)!.push(b)
    adj.get(b)!.push(a)
  }
  for (const e of edges) {
    if (e.source === e.target) continue
    link(e.source, e.target)
  }
  const lineage = new Set<string>()
  const queue = [focusId]
  lineage.add(focusId)
  let q = 0
  while (q < queue.length) {
    const id = queue[q++]!
    for (const nb of adj.get(id) || []) {
      if (!lineage.has(nb)) {
        lineage.add(nb)
        queue.push(nb)
      }
    }
  }
  return lineage
}

export function applyFocusToVisionMap(
  nodes: Node<MapNodePayload>[],
  edges: Edge[],
  focusId: string | null,
): { nodes: Node<MapNodePayload>[]; edges: Edge[] } {
  if (!focusId) {
    return {
      nodes: nodes.map((n) => ({
        ...n,
        selected: false,
        data: { ...n.data, dimmed: false, focusLineage: false },
      })),
      edges: edges.map((e) => {
        const prev = (e.data && typeof e.data === 'object' ? e.data : {}) as Record<string, unknown>
        return { ...e, data: { ...prev, focusHighlight: false } }
      }),
    }
  }
  const lineage = computeLineageNodeIds(edges, focusId)
  const nextNodes = nodes.map((node) => {
    const inLineage = lineage.has(node.id)
    return {
      ...node,
      selected: node.id === focusId,
      data: {
        ...node.data,
        dimmed: !inLineage,
        focusLineage: inLineage && node.id !== focusId,
      },
    }
  })
  const nextEdges = edges.map((e) => {
    const prev = (e.data && typeof e.data === 'object' ? e.data : {}) as Record<string, unknown>
    return {
      ...e,
      data: {
        ...prev,
        focusHighlight: lineage.has(e.source) && lineage.has(e.target),
      },
    }
  })
  return { nodes: nextNodes, edges: nextEdges }
}
