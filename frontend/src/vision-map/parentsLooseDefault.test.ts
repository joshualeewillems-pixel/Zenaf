/**
 * Parents + loose by default (founder rulings, 2026-11-24/25):
 * "All screens are overwhelmed and should only be parents and loose
 * by default"; "should be able to un nest in all cases but default
 * should be nested."
 *
 * On the Vision Map the nested default is the composition the view
 * itself builds on load: cairn mode (a project + its tasks/outcomes
 * pile into one cairn) followed by the garden stack seeded with every
 * initiative (`defaultStackedTreeIds`). These tests pin that
 * composition — including the gap it used to leak: a project with NO
 * tasks never piles into a cairn, so it (and an initiative whose only
 * projects are lone ones) used to stand flat in the default view.
 * The stack now nests lone children too.
 *
 * The un-nest grammar is the map's own: unstack an initiative to
 * reveal its projects/cairns, fan a cairn out to reveal its stones.
 * Reapplying the default composition restores the nested view —
 * nothing is deleted, only stacked.
 */
import { describe, expect, it } from 'vitest'
import type { Edge, Node } from '@xyflow/react'
import {
  applyCairnMode,
  applyGardenStack,
  defaultStackedTreeIds,
  expandCairn,
  isGardenStackData,
  subtreeChildNodeIds,
  type CairnIndex,
} from './cairn'
import { buildLiveVisionMapGraph } from './liveProjection'
import type { VisionMapEntityBundle } from './blockersFromVe'
import type { MapNodePayload } from './ontology'

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

const node = (
  id: string,
  kind: string,
  over: Record<string, unknown>,
  x = 0,
  y = 0,
): Node<MapNodePayload> => ({
  id,
  type: 'entityMap',
  position: { x, y },
  data: payload({ kind, ...over }),
})

/**
 * One initiative with: a piled project (branch + 2 tasks), a LONE
 * project (branch only — never cairns), its source seed, plus loose
 * stones: an orphan seed, a standalone task, a landmark.
 */
function garden(): { nodes: Node<MapNodePayload>[]; edges: Edge[] } {
  const seed = node('seed-idea1', 'seed', {
    label: 'Source idea',
    ref: { veType: 'idea', id: 'idea1' },
  })
  const tree = node('tree-i1', 'tree', {
    label: 'Initiative One',
    ref: { veType: 'initiative', id: 'i1' },
  })
  const branch = node('branch-p1', 'branch', {
    label: 'Project One',
    ref: { veType: 'project', id: 'p1' },
  })
  const lone = node('branch-p2', 'branch', {
    label: 'Lone Project',
    ref: { veType: 'project', id: 'p2' },
  })
  const flower = (id: string, taskId: string, label: string): Node<MapNodePayload> =>
    node(id, 'flower', { label, ref: { veType: 'task', id: taskId, projectId: 'p1' } })
  const looseTask = node('flower-loose', 'flower', {
    label: 'Loose Task',
    ref: { veType: 'task', id: 't-loose' },
  })
  const orphanSeed = node('seed-orphan', 'seed', {
    label: 'Orphan idea',
    ref: { veType: 'idea', id: 'idea-orphan' },
  })
  const landmark = node('lm-1', 'landmark', {
    label: 'A person',
    ref: { veType: 'person', id: 'per-1' },
  })
  const edges: Edge[] = [
    { id: 'e-trunk', source: 'seed-idea1', target: 'tree-i1', data: { tier: 'trunk' } },
    { id: 'e-tree-p1', source: 'tree-i1', target: 'branch-p1' },
    { id: 'e-tree-p2', source: 'tree-i1', target: 'branch-p2' },
    { id: 'e-p1-t1', source: 'branch-p1', target: 'flower-t1' },
    { id: 'e-p1-t2', source: 'branch-p1', target: 'flower-t2' },
  ]
  return {
    nodes: [
      seed,
      tree,
      branch,
      lone,
      flower('flower-t1', 't1', 'Task One'),
      flower('flower-t2', 't2', 'Task Two'),
      looseTask,
      orphanSeed,
      landmark,
    ],
    edges,
  }
}

/** The view's default composition: cairn mode, then every initiative stacked. */
function defaultView(nodes: Node<MapNodePayload>[], edges: Edge[]) {
  const g = applyCairnMode(nodes, edges, 80)
  const stacked = applyGardenStack(g.nodes, g.edges, defaultStackedTreeIds(g.nodes))
  return { ...stacked, cairnIndex: g.cairnIndex }
}

describe('parents + loose default — the nested view', () => {
  it('(1) renders parents + loose only: children — piled AND lone — are absent', () => {
    const { nodes, edges } = garden()
    const out = defaultView(nodes, edges)
    const ids = out.nodes.map((n) => n.id).sort()
    // The initiative as its stack (the parent), its source seed, and
    // the loose stones. Nothing else.
    expect(ids).toEqual(['flower-loose', 'lm-1', 'seed-idea1', 'seed-orphan', 'tree-i1'])
    const stack = out.nodes.find((n) => n.id === 'tree-i1')!
    expect(stack.type).toBe('cairn')
    expect(isGardenStackData(stack.data)).toBe(true)
    // Every stone is accounted for in the pile: tree + piled project
    // (3) + lone project (1) = 5 — nothing deleted, only nested.
    expect((stack.data as { cairnCount?: number }).cairnCount).toBe(5)
    // Children absent by name: the cairn, both branches, both tasks.
    for (const child of ['cairn-p1', 'branch-p1', 'branch-p2', 'flower-t1', 'flower-t2']) {
      expect(ids).not.toContain(child)
    }
    expect(out.hiddenCairnIds).toEqual(new Set(['cairn-p1']))
    expect(out.hiddenChildNodeIds).toEqual(new Set(['branch-p2']))
    // No edge points at a hidden child either.
    for (const e of out.edges) {
      expect(ids).toContain(e.source)
      expect(ids).toContain(e.target)
    }
  })

  it('(1b) subtreeChildNodeIds collects piled and lone children, and stops at seeds/landmarks/trees', () => {
    const { nodes, edges } = garden()
    const g = applyCairnMode(nodes, edges, 80)
    expect(subtreeChildNodeIds('tree-i1', g.nodes, g.edges).sort()).toEqual([
      'branch-p2',
      'cairn-p1',
    ])
  })

  it('(2) un-nesting the parent reveals its children; fanning the cairn reveals the tasks', () => {
    const { nodes, edges } = garden()
    const g = applyCairnMode(nodes, edges, 80)
    // Unstack the initiative (the view's toggle): its projects appear —
    // the piled one as its cairn, the lone one as itself.
    const unstacked = applyGardenStack(g.nodes, g.edges, new Set())
    const ids = unstacked.nodes.map((n) => n.id)
    expect(ids).toContain('cairn-p1')
    expect(ids).toContain('branch-p2')
    expect(unstacked.nodes.find((n) => n.id === 'tree-i1')!.data.kind).toBe('tree')
    // Fan the cairn out (the view's other toggle): every task reachable.
    const entry = g.cairnIndex['cairn-p1']!
    const fanned = expandCairn(unstacked.nodes, unstacked.edges, entry, entry.cairnNode.position)
    const fannedIds = fanned.nodes.map((n) => n.id).sort()
    expect(fannedIds).toEqual([
      'branch-p1',
      'branch-p2',
      'flower-loose',
      'flower-t1',
      'flower-t2',
      'lm-1',
      'seed-idea1',
      'seed-orphan',
      'tree-i1',
    ])
  })

  it('(3) reapplying the default composition restores the nested view exactly', () => {
    const { nodes, edges } = garden()
    const first = defaultView(nodes, edges)
    const restored = defaultView(nodes, edges)
    expect(restored.nodes.map((n) => n.id).sort()).toEqual(first.nodes.map((n) => n.id).sort())
    expect(restored.edges.map((e) => e.id).sort()).toEqual(first.edges.map((e) => e.id).sort())
  })
})

describe('parents + loose default — through the live projection', () => {
  it('an initiative whose only project is lone (no tasks) still nests by default', () => {
    const NOW = new Date().toISOString()
    const bundle = {
      ideas: [],
      initiatives: [
        {
          id: 'ini-1', source_idea_id: null, title: 'Initiative One', brief: '', status: 'Active', owner_id: null,
          evaluation_priority: 2, estimated_cost_ai: '', estimated_timeframe_ai: '', philosophical_alignment_ai: '',
          next_step_ai: '', required_assets: [], dependencies: '', risks: '', recommendation: '', kill_criteria: '',
          notes: '', created_at: NOW, updated_at: NOW,
        },
      ],
      projects: [
        {
          id: 'p-lone', initiative_id: 'ini-1', title: 'Lone Project', brief: '', status: 'Active', owner_id: null,
          supporting_owner_ids: [], required_assets: [], priority: '2', start_date: null, end_date: null,
          estimated_weekly_hours: 4, next_step_ai: '', notes: '', created_at: NOW, updated_at: NOW,
        },
        {
          id: 'p-busy', initiative_id: 'ini-1', title: 'Busy Project', brief: '', status: 'Active', owner_id: null,
          supporting_owner_ids: [], required_assets: [], priority: '2', start_date: null, end_date: null,
          estimated_weekly_hours: 4, next_step_ai: '', notes: '', created_at: NOW, updated_at: NOW,
        },
      ],
      tasks: [
        {
          id: 't1', project_id: 'p-busy', parent_task_id: null, title: 'Task One', description: '', assignee_id: null,
          status: 'Todo', priority: '2', estimated_hours: 2, due_date: null, dependency_ids: [],
          completion_criteria: '', notes: '', created_at: NOW, updated_at: NOW,
        },
      ],
    } as unknown as VisionMapEntityBundle
    const g = buildLiveVisionMapGraph(bundle, [], undefined, { cairnThreshold: 80 })
    // Pre-stack sanity: the busy project piled; the lone one did not.
    expect(g.nodes.map((n) => n.id).sort()).toEqual(['cairn-p-busy', 'branch-p-lone', 'tree-ini-1'].sort())
    const stacked = applyGardenStack(g.nodes, g.edges, defaultStackedTreeIds(g.nodes))
    // Default view: the parent alone — no branch, no cairn, no task.
    expect(stacked.nodes.map((n) => n.id)).toEqual(['tree-ini-1'])
    expect(isGardenStackData(stacked.nodes[0]!.data)).toBe(true)
    expect((stacked.nodes[0]!.data as { cairnCount?: number }).cairnCount).toBe(4)
    // Un-nest: unstacking reveals both projects (one as its cairn).
    const unstacked = applyGardenStack(g.nodes, g.edges, new Set())
    expect(unstacked.nodes.map((n) => n.id).sort()).toEqual(
      ['branch-p-lone', 'cairn-p-busy', 'tree-ini-1'].sort(),
    )
    const idx: CairnIndex = g.cairnIndex
    const fanned = expandCairn(
      unstacked.nodes,
      unstacked.edges,
      idx['cairn-p-busy']!,
      idx['cairn-p-busy']!.cairnNode.position,
    )
    expect(fanned.nodes.map((n) => n.id).sort()).toEqual(
      ['branch-p-busy', 'branch-p-lone', 'flower-t1', 'tree-ini-1'].sort(),
    )
  })
})
