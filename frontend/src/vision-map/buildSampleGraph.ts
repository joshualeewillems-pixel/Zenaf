import type { Edge, Node } from '@xyflow/react'
import type { MapNodePayload } from './ontology'
import { buildSampleNodePayloads, getVisionMapSampleBundle } from './sampleDataset'
import {
  branchAnglesForCount,
  branchTopLeft,
  fruitTopLeft,
  seedTopLeftAboveTree,
  taskTopLeft,
  treeTopLeftForColumn,
  VISION_MAP_LAYOUT,
} from './mapVisionLayout'

const RF_STONE_WRAPPER_CLASS = 'map-rf-node-stone'

/**
 * Sample graph — same spatial language as live projection (arc + buffer + task stacks).
 */
export function buildSampleVisionMapGraph(): {
  nodes: Node<MapNodePayload>[]
  edges: Edge[]
} {
  const bundle = getVisionMapSampleBundle()
  const payloads = buildSampleNodePayloads(bundle)
  const { idea, initiative, projects, tasks, outcomes } = bundle

  const nodes: Node<MapNodePayload>[] = []

  const id = {
    seed: `seed-${idea.id}`,
    tree: `tree-${initiative.id}`,
    fruit: (oid: string) => `fruit-${oid}`,
    branch: (pid: string) => `branch-${pid}`,
    flower: (tid: string) => `flower-${tid}`,
  }

  const columnCenterX = 560
  const treeTL = treeTopLeftForColumn(columnCenterX, VISION_MAP_LAYOUT.TREE_TOP_Y)

  nodes.push({
    id: id.seed,
    type: 'entityMap',
    className: RF_STONE_WRAPPER_CLASS,
    position: seedTopLeftAboveTree(treeTL),
    data: payloads.get(`seed:${idea.id}`)!,
  })

  nodes.push({
    id: id.tree,
    type: 'entityMap',
    className: RF_STONE_WRAPPER_CLASS,
    position: treeTL,
    data: payloads.get(`tree:${initiative.id}`)!,
  })

  const sortedProjects = [...projects].sort((a, b) => (a.title || '').localeCompare(b.title || ''))
  const projAngles = branchAnglesForCount(sortedProjects.length)
  const branchTLByProjectId = new Map<string, { x: number; y: number }>()

  sortedProjects.forEach((p, i) => {
    const bTL = branchTopLeft(treeTL, projAngles[i] ?? Math.PI / 2)
    branchTLByProjectId.set(p.id, bTL)
    nodes.push({
      id: id.branch(p.id),
      type: 'entityMap',
      className: RF_STONE_WRAPPER_CLASS,
      position: bTL,
      data: payloads.get(`branch:${p.id}`)!,
    })
  })

  const outcomeAngles = branchAnglesForCount(Math.max(1, outcomes.length))
  outcomes.forEach((o, i) => {
    nodes.push({
      id: id.fruit(o.id),
      type: 'entityMap',
      className: RF_STONE_WRAPPER_CLASS,
      position: fruitTopLeft(treeTL, outcomeAngles[i] ?? Math.PI / 2),
      data: payloads.get(`fruit:${o.id}`)!,
    })
  })

  const tasksByProject = new Map<string, typeof tasks>()
  for (const t of tasks) {
    if (!t.project_id) continue
    const list = tasksByProject.get(t.project_id) || []
    list.push(t)
    tasksByProject.set(t.project_id, list)
  }

  for (const p of sortedProjects) {
    const list = (tasksByProject.get(p.id) || []).sort((a, b) => (a.title || '').localeCompare(b.title || ''))
    const bTL = branchTLByProjectId.get(p.id)!
    const n = list.length
    list.forEach((t, ti) => {
      nodes.push({
        id: id.flower(t.id),
        type: 'entityMap',
        className: RF_STONE_WRAPPER_CLASS,
        position: taskTopLeft(bTL, ti, n),
        data: payloads.get(`flower:${t.id}`)!,
      })
    })
  }

  const edges: Edge[] = [{ id: 'e-seed-tree', source: id.seed, target: id.tree, animated: false }]

  for (const o of outcomes) {
    edges.push({
      id: `e-tree-fruit-${o.id}`,
      source: id.tree,
      target: id.fruit(o.id),
      style: { stroke: '#a78bfa', strokeWidth: 1.5, strokeDasharray: '4 3' },
    })
  }

  for (const p of projects) {
    edges.push({ id: `e-tree-branch-${p.id}`, source: id.tree, target: id.branch(p.id) })
    const list = tasksByProject.get(p.id) || []
    for (const t of list) {
      edges.push({ id: `e-branch-flower-${t.id}`, source: id.branch(p.id), target: id.flower(t.id) })
    }
  }

  return { nodes, edges }
}
