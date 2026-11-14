// @vitest-environment jsdom
/**
 * The cairn VIEW package (founder rulings, 2026-11-13):
 *
 * - D · ALWAYS PILE: a project group with ≥2 linked members forms a
 *   cairn in a garden of ANY size. (Old law: the graph had to pass a
 *   40/80 total-stone gate first — small gardens never piled.)
 * - A · FAN-OUT PAINTED: expanding a cairn no longer restores the old
 *   symbolic-stone member nodes. Each fanned member carries the very
 *   PortedStone its pile's layout assigned it (`fannedStone`), and the
 *   node paints that sprite over its label block. (Old law: expandCairn
 *   restored the original entityMap nodes verbatim.)
 * - B · the project's branch member is flagged parent in the cairn's
 *   member list, so the layout seats it at the pile's base.
 * - C · STACKS ON BY DEFAULT: the view seeds its stacked set with
 *   every initiative on load (defaultStackedTreeIds); the hold toggle
 *   still unstacks/restacks per initiative.
 * - ADDENDUM · NO ON-STONE MARKS: the symbolic stone no longer draws
 *   its lifecycle glyph, and a fanned painted member wears no glyph
 *   either. Rings stay.
 * - ADDENDUM 2, AS CORRECTED · NO KIND SUBTITLE AT ALL: a stone shows
 *   its name and its status; its type is not displayed. Producers
 *   compose no kind subtitle and EntityMapNode renders no subtitle
 *   line. (The cairn count/gesture hint is not a kind label — it
 *   stays.)
 *
 * No JSX (vitest includes *.test.ts only): createElement throughout.
 */
import { describe, expect, it } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import { ReactFlowProvider } from '@xyflow/react'
import type { Edge, Node } from '@xyflow/react'
import {
  applyCairnMode,
  applyGardenStack,
  defaultStackedTreeIds,
  expandCairn,
  type CairnEntry,
} from './cairn'
import { towerLayoutForMembers, type CairnMemberInput, type PortedStone } from './cairnTower'
import { SymbolicStone } from './symbolicStone'
import { EntityMapNode } from './EntityMapNode'
import { buildLiveVisionMapGraph } from './liveProjection'
import type { VisionMapEntityBundle } from './blockersFromVe'
import type { MapNodePayload } from './ontology'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const T = 60_000

const payload = (over: Record<string, unknown>): MapNodePayload =>
  ({
    kind: 'branch',
    label: 'Thing',
    growth: 'growing',
    condition: 'healthy',
    condition_severity: 0,
    ref: { veType: 'project', id: 'p1' },
    summaryLines: [],
    water_level: 'medium',
    fertilizer_pulse: false,
    ...over,
  }) as MapNodePayload

/** One initiative, one project, two tasks — 4 stones total. */
function smallGarden(): { nodes: Node<MapNodePayload>[]; edges: Edge[] } {
  const tree: Node<MapNodePayload> = {
    id: 'tree-i1',
    type: 'entityMap',
    position: { x: 0, y: 0 },
    data: payload({
      kind: 'tree',
      label: 'Initiative One',
      ref: { veType: 'initiative', id: 'i1' },
      entity_created_at: '2026-01-01T00:00:00.000Z',
    }),
  }
  const branch: Node<MapNodePayload> = {
    id: 'branch-p1',
    type: 'entityMap',
    position: { x: 0, y: 200 },
    data: payload({
      kind: 'branch',
      label: 'Project One',
      ref: { veType: 'project', id: 'p1' },
      entity_created_at: '2026-01-02T00:00:00.000Z',
    }),
  }
  const flower = (id: string, taskId: string, label: string, created: string): Node<MapNodePayload> => ({
    id,
    type: 'entityMap',
    position: { x: 100, y: 400 },
    data: payload({
      kind: 'flower',
      label,
      ref: { veType: 'task', id: taskId, projectId: 'p1' },
      entity_created_at: created,
    }),
  })
  const f1 = flower('flower-t1', 't1', 'Task One', '2026-01-03T00:00:00.000Z')
  const f2 = flower('flower-t2', 't2', 'Task Two', '2026-01-04T00:00:00.000Z')
  const edges: Edge[] = [
    { id: 'e-tree-branch', source: 'tree-i1', target: 'branch-p1' },
    { id: 'e-branch-f1', source: 'branch-p1', target: 'flower-t1' },
    { id: 'e-branch-f2', source: 'branch-p1', target: 'flower-t2' },
  ]
  return { nodes: [tree, branch, f1, f2], edges }
}

describe('D · always pile — grouping ignores garden size', () => {
  it('a 4-stone garden piles its ≥2-member project (the old 40/80 gate would have passed it through)', () => {
    const { nodes, edges } = smallGarden()
    const g = applyCairnMode(nodes, edges, 80)
    expect(g.totalStones).toBe(4)
    expect(g.cairned).toBe(true)
    expect(g.cairnCount).toBe(1)
    expect(g.nodes.map((n) => n.id).sort()).toEqual(['cairn-p1', 'tree-i1'])
  })

  it('a lone project stone still does not pile — one stone is not a cairn', () => {
    const { nodes, edges } = smallGarden()
    const lone = nodes.filter((n) => n.id !== 'flower-t1' && n.id !== 'flower-t2')
    const g = applyCairnMode(lone, edges.slice(0, 1), 80)
    expect(g.cairned).toBe(false)
    expect(g.nodes.some((n) => n.id === 'branch-p1')).toBe(true)
  })

  it('B · the cairn member list flags exactly the branch as parent', () => {
    const { nodes, edges } = smallGarden()
    const g = applyCairnMode(nodes, edges, 80)
    const members = g.cairnIndex['cairn-p1']!.cairnNode.data.cairnMembers as CairnMemberInput[]
    expect(members.filter((m) => m.parent).map((m) => m.id)).toEqual(['branch-p1'])
  })
})

describe('A · fan-out painted — members keep their pile stones', () => {
  it('every fanned member carries the PortedStone the pile layout gave it, sprite for sprite', { timeout: T }, () => {
    const { nodes, edges } = smallGarden()
    const g = applyCairnMode(nodes, edges, 80)
    const entry: CairnEntry = g.cairnIndex['cairn-p1']!
    const out = expandCairn(g.nodes, g.edges, entry, entry.cairnNode.position)

    // The pile's own layout, recomputed from the cairn node's members.
    const members = entry.cairnNode.data.cairnMembers as CairnMemberInput[]
    const layout = towerLayoutForMembers('cairn-p1', members)
    const pileStoneByMember = new Map(
      layout.stones.filter((s) => s.role === 'column' && s.memberId).map((s) => [s.memberId!, s]),
    )

    const fanned = out.nodes.filter((n) => n.id !== 'tree-i1')
    expect(fanned.map((n) => n.id).sort()).toEqual(['branch-p1', 'flower-t1', 'flower-t2'])
    expect(out.nodes.some((n) => n.id === 'cairn-p1')).toBe(false)
    for (const n of fanned) {
      const d = n.data as MapNodePayload & { fannedStone?: PortedStone; expandedFromCairn?: string }
      expect(d.expandedFromCairn).toBe('cairn-p1')
      expect(d.fannedStone).toBeTruthy()
      const pileStone = pileStoneByMember.get(n.id)!
      expect(d.fannedStone!.sprite).toBe(pileStone.sprite)
      expect(d.fannedStone!.spriteUrl).toBe(pileStone.spriteUrl)
      expect(d.fannedStone!.tint).toBe(pileStone.tint)
      expect(d.fannedStone!.seed).toBe(pileStone.seed)
    }
    // The parent's fanned stone is the pile's bottom stone.
    const branchStone = (
      fanned.find((n) => n.id === 'branch-p1')!.data as MapNodePayload & { fannedStone: PortedStone }
    ).fannedStone
    expect(branchStone.memberId).toBe('branch-p1')
    const firstColumn = layout.stones.find((s) => s.role === 'column')!
    expect(firstColumn.memberId).toBe('branch-p1')
  })

  it('fanned members keep their label data (the member name rides along)', () => {
    const { nodes, edges } = smallGarden()
    const g = applyCairnMode(nodes, edges, 80)
    const entry = g.cairnIndex['cairn-p1']!
    const out = expandCairn(g.nodes, g.edges, entry, entry.cairnNode.position)
    const byId = new Map(out.nodes.map((n) => [n.id, n]))
    expect(byId.get('branch-p1')!.data.label).toBe('Project One')
    expect(byId.get('flower-t1')!.data.label).toBe('Task One')
    expect(byId.get('flower-t2')!.data.label).toBe('Task Two')
  })
})

describe('C · stacks on by default', () => {
  it('defaultStackedTreeIds collects every initiative tree — and only trees', () => {
    const { nodes } = smallGarden()
    const landmark: Node<MapNodePayload> = {
      id: 'lm-1',
      type: 'entityMap',
      position: { x: 400, y: 0 },
      data: payload({ kind: 'landmark', label: 'A person', ref: { veType: 'person', id: 'per-1' } }),
    }
    expect(defaultStackedTreeIds([...nodes, landmark])).toEqual(new Set(['tree-i1']))
  })

  it('with the default set the initiative renders as its stack; removing its id (the toggle) restores the tree', () => {
    const { nodes, edges } = smallGarden()
    const g = applyCairnMode(nodes, edges, 80)
    const stacked = applyGardenStack(g.nodes, g.edges, defaultStackedTreeIds(g.nodes))
    const stackNode = stacked.nodes.find((n) => n.id === 'tree-i1')!
    expect(stackNode.type).toBe('cairn')
    expect((stackNode.data as { gardenStack?: boolean }).gardenStack).toBe(true)
    expect(stacked.nodes.some((n) => n.id === 'cairn-p1')).toBe(false)

    const unstacked = applyGardenStack(g.nodes, g.edges, new Set())
    const treeBack = unstacked.nodes.find((n) => n.id === 'tree-i1')!
    expect(treeBack.type).toBe('entityMap')
    expect(treeBack.data.kind).toBe('tree')
    expect(unstacked.nodes.some((n) => n.id === 'cairn-p1')).toBe(true)
  })
})

describe('rendered stones — no on-stone marks, labels and rings kept', () => {
  let container: HTMLDivElement
  let root: Root

  function render(el: React.ReactElement) {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    act(() => {
      root.render(el)
    })
  }

  function cleanup() {
    act(() => {
      root.unmount()
    })
    container.remove()
  }

  it('the symbolic stone draws no glyph: silhouette, wash and top-light only', () => {
    render(
      React.createElement(SymbolicStone, {
        growth: 'germinating',
        kind: 'flower',
        severity: 0,
        washColor: '#a8a29e',
        variantSeed: 't1',
        size: 76,
      }),
    )
    const svg = container.querySelector('svg')!
    expect(svg.getAttribute('data-glyph')).toBeNull()
    // body (granite) + body (wash) + top-light = 3 paths; a sprout
    // glyph would add 3 more.
    expect(svg.querySelectorAll('path')).toHaveLength(3)
    cleanup()
  })

  it('a fanned member node paints its pile sprite over its label — and wears no glyph svg', { timeout: T }, () => {
    const members: CairnMemberInput[] = [
      { id: 'branch-p1', kind: 'branch', activity: 0.6, createdAt: '2026-01-02T00:00:00.000Z', growth: 'growing', parent: true },
      { id: 'flower-t1', kind: 'flower', activity: 0.5, createdAt: '2026-01-03T00:00:00.000Z', growth: 'germinating' },
      { id: 'flower-t2', kind: 'flower', activity: 0.4, createdAt: '2026-01-04T00:00:00.000Z', growth: 'dormant' },
    ]
    const layout = towerLayoutForMembers('cairn-p1', members)
    const stone = layout.stones.find((s) => s.memberId === 'flower-t1')!
    const data = payload({
      kind: 'flower',
      label: 'Task One',
      // A subtitle in the payload — legacy or foreign — must NOT
      // render: the kind line is gone (founder correction, 2026-11-13).
      subtitle: 'Kindline Sentinel',
      ref: { veType: 'task', id: 't1', projectId: 'p1' },
      expandedFromCairn: 'cairn-p1',
      fannedStone: stone,
    })
    render(
      React.createElement(
        ReactFlowProvider,
        null,
        React.createElement(EntityMapNode, {
          id: 'flower-t1',
          data,
          selected: false,
          type: 'entityMap',
          dragging: false,
          zIndex: 0,
          isConnectable: true,
          positionAbsoluteX: 0,
          positionAbsoluteY: 0,
        } as never),
      ),
    )
    // The painted sprite: CairnStoneSprite's tint stack + img.
    const stack = container.querySelector('.cairn-tint-stack')
    expect(stack).toBeTruthy()
    expect(stack!.getAttribute('data-tint')).toBe(stone.tint)
    const img = stack!.querySelector('img')
    expect(img!.getAttribute('src')).toBe(stone.spriteUrl)
    // The name is intact; the kind subtitle line is NOT rendered.
    expect(container.textContent).toContain('Task One')
    expect(container.textContent).not.toContain('Kindline Sentinel')
    expect(container.textContent).not.toContain('(flower)')
    // No symbolic stone (it carries data-wash) and no glyph mark.
    expect(container.querySelector('[data-wash]')).toBeNull()
    expect(container.querySelector('[data-glyph]')).toBeNull()
    cleanup()
  })

  it('a plain member node keeps the symbolic stone and its label — still no glyph', () => {
    const data = payload({
      kind: 'flower',
      label: 'Task One',
      subtitle: 'Kindline Sentinel',
      ref: { veType: 'task', id: 't1', projectId: 'p1' },
    })
    render(
      React.createElement(
        ReactFlowProvider,
        null,
        React.createElement(EntityMapNode, {
          id: 'flower-t1',
          data,
          selected: false,
          type: 'entityMap',
          dragging: false,
          zIndex: 0,
          isConnectable: true,
          positionAbsoluteX: 0,
          positionAbsoluteY: 0,
        } as never),
      ),
    )
    expect(container.querySelector('[data-wash]')).toBeTruthy()
    expect(container.querySelector('[data-glyph]')).toBeNull()
    expect(container.textContent).toContain('Task One')
    expect(container.textContent).not.toContain('Kindline Sentinel')
    expect(container.textContent).not.toContain('(flower)')
    cleanup()
  })
})

describe('addendum 2 (corrected) · no kind subtitle anywhere (founder ruling, 2026-11-13)', () => {
  it('the live projection composes NO subtitle on any stone — name and status only', () => {
    const NOW = new Date().toISOString()
    const bundle = {
      ideas: [
        { id: 'idea-1', title: 'Seed idea', summary: '', description: '', status: 'Exploring', tags: [], created_by: 'fixture', created_at: NOW, updated_at: NOW },
      ],
      initiatives: [
        {
          id: 'ini-1', source_idea_id: 'idea-1', title: 'Initiative One', brief: '', status: 'Active', owner_id: null,
          evaluation_priority: 2, estimated_cost_ai: '', estimated_timeframe_ai: '', philosophical_alignment_ai: '',
          next_step_ai: '', required_assets: [], dependencies: '', risks: '', recommendation: '', kill_criteria: '',
          notes: '', created_at: NOW, updated_at: NOW,
        },
      ],
      projects: [
        {
          id: 'p1', initiative_id: 'ini-1', title: 'Project One', brief: 'Shipped the thing', status: 'Done', owner_id: null,
          supporting_owner_ids: [], required_assets: [], priority: '2', start_date: null, end_date: null,
          estimated_weekly_hours: 4, next_step_ai: '', notes: '', created_at: NOW, updated_at: NOW,
        },
      ],
      tasks: [
        {
          id: 't1', project_id: 'p1', parent_task_id: null, title: 'Task One', description: '', assignee_id: null,
          status: 'Todo', priority: '2', estimated_hours: 2, due_date: null, dependency_ids: [],
          completion_criteria: '', notes: '', created_at: NOW, updated_at: NOW,
        },
      ],
    } as unknown as VisionMapEntityBundle
    const g = buildLiveVisionMapGraph(bundle, [], undefined, { cairnThreshold: 80 })
    for (const n of g.nodes) {
      if (n.data.kind === 'cairn') {
        // The cairn node's subtitle is its stone COUNT — a count,
        // not a kind label; the correction preserves it.
        expect(n.data.subtitle).toMatch(/^\d+ stones$/)
      } else {
        expect(n.data.subtitle).toBeUndefined()
      }
    }
    // The pre-cairn graph too: seed, tree, branch, fruit, flower.
    const plain = buildLiveVisionMapGraph(bundle, [])
    expect(plain.nodes.map((n) => n.data.kind).sort()).toEqual(['branch', 'flower', 'fruit', 'seed', 'tree'])
    for (const n of plain.nodes) {
      expect(n.data.subtitle).toBeUndefined()
      expect(n.data.label).toBeTruthy()
    }
  })
})
