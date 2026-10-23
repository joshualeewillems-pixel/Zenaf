import { describe, expect, it } from 'vitest'
import type { Edge, Node } from 'reactflow'
import { applyGardenStack, isGardenStackData } from './cairn'
import type { MapNodePayload } from './ontology'

/**
 * Joshua's rule (2026-10-22): when an initiative is stacked, its stones
 * sit ON the parent stone as ONE object — never a second pile floating
 * beside/under the parent. These tests pin that property on the pure
 * transform: one node, the parent's own id/position/edges.
 */

const payload = (over: Record<string, unknown>): MapNodePayload =>
  ({
    kind: 'tree',
    label: 'Meet your council',
    growth: 'dormant',
    condition: 'ok',
    ref: 'stone:initiative:init-1',
    summaryLines: [],
    water_level: 'low',
    fertilizer_pulse: false,
    ...over,
  }) as MapNodePayload

function fixture(): { nodes: Node<MapNodePayload>[]; edges: Edge[] } {
  const tree: Node<MapNodePayload> = {
    id: 'init-1',
    type: 'entity',
    position: { x: 100, y: 100 },
    data: payload({ kind: 'tree' }),
  }
  const cairn: Node<MapNodePayload> = {
    id: 'cairn-proj-1',
    type: 'cairn',
    position: { x: 320, y: 420 },
    data: payload({
      kind: 'cairn',
      label: 'Project One',
      cairnProjectId: 'proj-1',
      cairnCount: 5,
      cairnPreview: [{ growth: 'seed', kind: 'leaf', severity: 2, pulse: false }],
    }),
  }
  const landmark: Node<MapNodePayload> = {
    id: 'lm-1',
    type: 'entity',
    position: { x: 520, y: 100 },
    data: payload({ kind: 'landmark', label: 'A person', ref: 'stone:person:p-1' }),
  }
  const edges: Edge[] = [
    { id: 'e-tree-cairn', source: 'init-1', target: 'cairn-proj-1' },
    { id: 'e-tree-lm', source: 'init-1', target: 'lm-1' },
  ]
  return { nodes: [tree, cairn, landmark], edges }
}

describe('applyGardenStack — one object on the parent stone', () => {
  it('replaces the tree with a single stack node carrying the tree id and position', () => {
    const { nodes, edges } = fixture()
    const out = applyGardenStack(nodes, edges, new Set(['init-1']))

    const forInitiative = out.nodes.filter((n) => n.id === 'init-1')
    expect(forInitiative).toHaveLength(1)
    const stack = forInitiative[0]!
    expect(stack.type).toBe('cairn')
    expect(isGardenStackData(stack.data)).toBe(true)
    expect(stack.position).toEqual({ x: 100, y: 100 })
    expect((stack.data as { cairnCount?: number }).cairnCount).toBe(5)
    // No second object anywhere: no node offset below the parent, no cairn left.
    expect(out.nodes.some((n) => n.position.y === 320)).toBe(false)
    expect(out.nodes.some((n) => n.id === 'cairn-proj-1')).toBe(false)
    expect(out.nodes).toHaveLength(2) // the stack + the landmark
    expect(out.hiddenCairnIds).toEqual(new Set(['cairn-proj-1']))
  })

  it("keeps the parent stone's own edges attached to the stack", () => {
    const { nodes, edges } = fixture()
    const out = applyGardenStack(nodes, edges, new Set(['init-1']))
    expect(out.edges).toEqual([{ id: 'e-tree-lm', source: 'init-1', target: 'lm-1' }])
  })

  it('unstacked initiatives pass through untouched', () => {
    const { nodes, edges } = fixture()
    const out = applyGardenStack(nodes, edges, new Set())
    expect(out.nodes).toHaveLength(3)
    expect(out.nodes.find((n) => n.id === 'init-1')!.data.kind).toBe('tree')
  })
})
