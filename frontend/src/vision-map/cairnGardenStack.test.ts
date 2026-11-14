import { describe, expect, it } from 'vitest'
import type { Edge, Node } from 'reactflow'
import { applyGardenStack, buildGardenStackNode, isGardenStackData } from './cairn'
import { towerDebugForMembers, towerLayoutForMembers, type CairnMemberInput } from './cairnTower'
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
    // NEW LAW (founder ruling, 2026-11-13): the tree's own stone is a
    // member of the pile and is counted — 5 subtree stones + the tree.
    // (This assertion pinned 5 under the old host-not-member law.)
    expect((stack.data as { cairnCount?: number }).cairnCount).toBe(6)
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

describe('garden stack — the tree nests as a member (founder ruling, 2026-11-13)', () => {
  it('the tree is the stack pile’s first member, flagged parent, with its arrival threaded', () => {
    const { nodes } = fixture()
    const tree = {
      ...nodes[0]!,
      data: payload({ kind: 'tree', entity_created_at: '2026-01-15T00:00:00.000Z' }),
    }
    const cairn = nodes[1]!
    const stack = buildGardenStackNode(tree, [cairn])
    const members = (stack.data as { cairnMembers?: CairnMemberInput[] }).cairnMembers!
    // 5 synthetic subtree members + the tree itself.
    expect(members).toHaveLength(6)
    expect(members[0]).toMatchObject({
      id: 'init-1',
      kind: 'tree',
      parent: true,
      createdAt: '2026-01-15T00:00:00.000Z',
    })
    // The tree is the stack's ONLY parent.
    expect(members.filter((m) => m.parent)).toHaveLength(1)
  })

  it('a project branch’s parent flag does not survive into the stack — and the layout seats the tree at the base', () => {
    const { nodes } = fixture()
    const tree = nodes[0]!
    const cairnWithMembers: Node<MapNodePayload> = {
      id: 'cairn-proj-9',
      type: 'cairn',
      position: { x: 320, y: 420 },
      data: payload({
        kind: 'cairn',
        label: 'Project Nine',
        cairnProjectId: 'proj-9',
        cairnCount: 2,
        cairnPreview: [],
        cairnMembers: [
          { id: 'branch-proj-9', kind: 'branch', activity: 0.9, createdAt: '2026-01-01T00:00:00.000Z', growth: 'growing', parent: true },
          { id: 'flower-9', kind: 'flower', activity: 0.4, createdAt: '2026-02-01T00:00:00.000Z', growth: 'germinating' },
        ] as CairnMemberInput[],
      }),
    }
    const stack = buildGardenStackNode(tree, [cairnWithMembers])
    const members = (stack.data as { cairnMembers?: CairnMemberInput[] }).cairnMembers!
    expect(members.map((m) => m.id)).toEqual(['init-1', 'branch-proj-9', 'flower-9'])
    expect(members.filter((m) => m.parent).map((m) => m.id)).toEqual(['init-1'])
    const dbg = towerDebugForMembers(stack.id, members)
    expect(dbg.col[0]!.role).toBe('slab')
    expect(dbg.col[1]!.memberId).toBe('init-1')
  })
})

describe('garden stack — Blend threading (reconciliation union, 2026-11-14)', () => {
  it('stack members carry strand weights: the tree member takes the tree payload’s vector, subtree weights survive the parent-flag strip, and the weights stain the pile', () => {
    const { nodes } = fixture()
    const treeWeights = { word: 0.5, people: 0.5 }
    const tree = {
      ...nodes[0]!,
      data: payload({ kind: 'tree', entity_strand_weights: treeWeights }),
    }
    const branchWeights = { image: 0.75, word: 0.25 }
    const cairnWithMembers: Node<MapNodePayload> = {
      id: 'cairn-proj-9',
      type: 'cairn',
      position: { x: 320, y: 420 },
      data: payload({
        kind: 'cairn',
        label: 'Project Nine',
        cairnProjectId: 'proj-9',
        cairnCount: 1,
        cairnPreview: [],
        cairnMembers: [
          {
            id: 'branch-proj-9',
            kind: 'branch',
            activity: 0.9,
            createdAt: '2026-01-01T00:00:00.000Z',
            growth: 'growing',
            parent: true,
            weights: branchWeights,
          },
        ] as CairnMemberInput[],
      }),
    }
    const stack = buildGardenStackNode(tree, [cairnWithMembers])
    const members = (stack.data as { cairnMembers?: CairnMemberInput[] }).cairnMembers!
    expect(members[0]!.id).toBe('init-1')
    expect(members[0]!.weights).toEqual(treeWeights)
    const branch = members.find((m) => m.id === 'branch-proj-9')!
    expect(branch.parent).toBeUndefined()
    expect(branch.weights).toEqual(branchWeights)

    // The weights actually stain the pile: the same members without
    // vectors lay out with identical sprites but neutral tints.
    const stained = towerLayoutForMembers(stack.id, members)
    const bare = towerLayoutForMembers(
      stack.id,
      members.map((m) => ({ ...m, weights: null })),
    )
    for (const id of ['init-1', 'branch-proj-9']) {
      const sStone = stained.stones.find((s) => s.memberId === id)!
      const bStone = bare.stones.find((s) => s.memberId === id)!
      expect(sStone.sprite).toBe(bStone.sprite)
      expect(sStone.tint).not.toBe(bStone.tint)
    }
  })
})
