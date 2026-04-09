import type { Edge, Node, XYPosition } from '@xyflow/react'
import type { ConditionSeverity, MapNodePayload, VeEntityType } from './ontology'
import type { VisionMapEntityBundle } from './blockersFromVe'
import { mapVisualTriad, type GrowthTriadMetrics } from './mapGrowthMetrics'
import { MAP_SOIL_TIER_LOW_BELOW } from './mapNodeAppearance'
import type { MapEdgeTier } from './MapFlowEdge'
import { effectiveConditionSeverity } from './resolveConditionSeverity'

export type NestVitality = {
  dry: boolean
  soft: boolean
  lush: boolean
}

export type NestGroupNodeData = {
  nestId: string
  rootNodeId: string
  dominantLabel: string
  memberCount: number
  strataKinds: MapNodePayload['kind'][]
  stoneKinds: MapNodePayload['kind'][]
  kindCounts: Partial<Record<MapNodePayload['kind'], number>>
  triad: GrowthTriadMetrics
  vitality: NestVitality
  selected?: boolean
  onExpand?: () => void
  dimmed?: boolean
  focusLineage?: boolean
}

export type NestGroup = {
  id: string
  rootNodeId: string
  memberNodeIds: string[]
  memberEdgeIds: string[]
  collapsed: boolean
  dominantLabel: string
  anchorPosition: XYPosition
  relativePositions: Record<string, XYPosition>
  relativeDepths: Record<string, number>
  strataKinds: MapNodePayload['kind'][]
  stoneKinds: MapNodePayload['kind'][]
  kindCounts: Partial<Record<MapNodePayload['kind'], number>>
  memberKinds: Record<string, MapNodePayload['kind']>
  triad: GrowthTriadMetrics
  vitality: NestVitality
}

export type NestState = {
  groups: Record<string, NestGroup>
  nodeToNestId: Record<string, string | undefined>
  rootToNestId: Record<string, string | undefined>
}

export const EMPTY_NEST_STATE: NestState = {
  groups: {},
  nodeToNestId: {},
  rootToNestId: {},
}

/** Roots that may collapse a downstream subtree into a cairn (initiative/project/idea). */
const NEST_ROOT_VE_TYPES = new Set<VeEntityType>(['initiative', 'project', 'idea'])

export function canNestNode(node: Node<MapNodePayload> | null | undefined): boolean {
  if (!node) return false
  return NEST_ROOT_VE_TYPES.has(node.data.ref.veType)
}

export function getNestGroupForRoot(rootNodeId: string, nestState: NestState): NestGroup | null {
  const nestId = nestState.rootToNestId[rootNodeId]
  if (!nestId) return null
  return nestState.groups[nestId] ?? null
}

export function isNodeHiddenByNest(nodeId: string, nestState: NestState): boolean {
  const nestId = nestState.nodeToNestId[nodeId]
  if (!nestId) return false
  const group = nestState.groups[nestId]
  return Boolean(group?.collapsed)
}

export function isEdgeHiddenByNest(edge: Edge, nestState: NestState): boolean {
  const sNest = nestState.nodeToNestId[edge.source]
  const tNest = nestState.nodeToNestId[edge.target]
  if (!sNest && !tNest) return false
  if (sNest && tNest && sNest === tNest) {
    const g = nestState.groups[sNest]
    return Boolean(g?.collapsed)
  }
  if (sNest) return Boolean(nestState.groups[sNest]?.collapsed)
  if (tNest) return Boolean(nestState.groups[tNest]?.collapsed)
  return false
}

function mapEdgeTier(e: Edge): MapEdgeTier {
  const d = e.data as { tier?: MapEdgeTier } | undefined
  return d?.tier ?? 'structural'
}

/**
 * Downstream adjacency for nest subtree collection. Must match `liveProjection` semantics:
 * - structural / task / outcome: parent → child (source → target)
 * - trunk: edge is `source=seed`, `target=tree`. We add **both** directions so:
 *   - from **tree**, downstream includes the linked seed (initiative “owns” the idea on the map)
 *   - from **seed**, downstream includes the tree and thus projects/tasks (nest group from an idea works)
 *   BFS uses a visited set, so the mutual link does not loop.
 */
export function buildDownstreamAdjacency(edges: Edge[]): Map<string, string[]> {
  const bySource = new Map<string, string[]>()
  const push = (from: string, to: string) => {
    const arr = bySource.get(from) ?? []
    arr.push(to)
    bySource.set(from, arr)
  }
  for (const e of edges) {
    if (e.source === e.target) continue
    const tier = mapEdgeTier(e)
    if (tier === 'trunk') {
      push(e.target, e.source)
      push(e.source, e.target)
    } else {
      push(e.source, e.target)
    }
  }
  return bySource
}

export function collectDescendantSubtree(
  rootNodeId: string,
  nodes: Node<MapNodePayload>[],
  edges: Edge[],
): { nodeIds: string[]; edgeIds: string[]; depths: Record<string, number> } {
  const nodeSet = new Set(nodes.map((n) => n.id))
  if (!nodeSet.has(rootNodeId)) return { nodeIds: [], edgeIds: [], depths: {} }
  const byDownstream = buildDownstreamAdjacency(edges)
  const visited = new Set<string>()
  const depths: Record<string, number> = { [rootNodeId]: 0 }
  const queue = [rootNodeId]
  visited.add(rootNodeId)
  let qIdx = 0
  while (qIdx < queue.length) {
    const cur = queue[qIdx++]!
    const kids = byDownstream.get(cur) ?? []
    for (const kid of kids) {
      if (!nodeSet.has(kid)) continue
      if (visited.has(kid)) continue
      visited.add(kid)
      depths[kid] = (depths[cur] ?? 0) + 1
      queue.push(kid)
    }
  }
  const edgeIds: string[] = []
  for (const e of edges) {
    if (visited.has(e.source) && visited.has(e.target)) edgeIds.push(e.id)
  }
  return { nodeIds: Array.from(visited), edgeIds, depths }
}

export function collectAttachedSubtree(
  rootNodeId: string,
  nodes: Node<MapNodePayload>[],
  edges: Edge[],
): { nodeIds: string[]; edgeIds: string[]; depths: Record<string, number> } {
  const down = collectDescendantSubtree(rootNodeId, nodes, edges)
  const nodeSet = new Set(nodes.map((n) => n.id))
  const byTarget = new Map<string, string[]>()
  for (const e of edges) {
    const arr = byTarget.get(e.target) ?? []
    arr.push(e.source)
    byTarget.set(e.target, arr)
  }
  const visited = new Set(down.nodeIds)
  const depths = { ...down.depths }
  const queue = [rootNodeId]
  let idx = 0
  while (idx < queue.length) {
    const cur = queue[idx++]!
    const parents = byTarget.get(cur) ?? []
    for (const p of parents) {
      if (!nodeSet.has(p) || visited.has(p)) continue
      visited.add(p)
      depths[p] = 0
      queue.push(p)
    }
  }
  const edgeIds: string[] = []
  for (const e of edges) {
    if (visited.has(e.source) && visited.has(e.target)) edgeIds.push(e.id)
  }
  return { nodeIds: Array.from(visited), edgeIds, depths }
}

export function getDominantNestLabel(
  rootNode: Node<MapNodePayload>,
  memberNodes: Node<MapNodePayload>[],
): string {
  const amalgam = getAmalgamatedNestLabel(rootNode, memberNodes)
  if (amalgam) return clip(amalgam, 52)
  const rootLabel = normalizeDominantNestLabel(rootNode.data.label || '')
  if (rootLabel.length >= 6) return clip(rootLabel, 52)
  const best = memberNodes
    .map((n) => normalizeDominantNestLabel(n.data.label ?? ''))
    .filter(Boolean)
    .sort((a, b) => scoreLabel(b) - scoreLabel(a))[0]
  return clip(best || normalizeDominantNestLabel(rootNode.data.label || '') || 'Nested cluster', 52)
}

function getAmalgamatedNestLabel(
  rootNode: Node<MapNodePayload>,
  memberNodes: Node<MapNodePayload>[],
): string {
  const root = normalizeDominantNestLabel(rootNode.data.label || '')
  const ranked = [...memberNodes]
    .filter((n) => n.id !== rootNode.id)
    .sort((a, b) => activityScore(b.data) - activityScore(a.data))
    .map((n) => normalizeDominantNestLabel(n.data.label || ''))
    .filter(Boolean)
  if (!root && ranked.length === 0) return 'Nested cluster'
  if (root && ranked.length === 0) return `${root} cluster`
  const alt = ranked[0]!
  if (!root) return `${alt} cluster`
  const rootCore = root.split(/\s+/).slice(0, 3).join(' ')
  const altCore = alt.split(/\s+/).slice(0, 2).join(' ')
  if (altCore.length < 3 || rootCore.toLowerCase() === altCore.toLowerCase()) return `${rootCore} cluster`
  return `${rootCore} + ${altCore}`
}

function scoreLabel(s: string): number {
  const n = s.length
  const lengthScore = n >= 12 && n <= 56 ? 4 : n >= 7 && n <= 72 ? 3 : 1
  const penalty = /\b(id|uuid|proj-|task-|tree-|branch-)\b/i.test(s) ? 2 : 0
  return lengthScore * 10 + n - penalty
}

export function normalizeDominantNestLabel(label: string): string {
  let s = label.replace(/\s+/g, ' ').trim()
  s = s.replace(/^\s*(project|initiative|task|idea|outcome)\s*[:\-]\s*/i, '')
  s = s.replace(/\s+\((seed|tree|branch|flower|fruit)\)\s*$/i, '')
  s = s.replace(/\b(veType|ref\.id|id)\b[:=]\s*\S+/gi, '').trim()
  return s
}

function clip(s: string, n: number): string {
  if (s.length <= n) return s
  return `${s.slice(0, n - 1)}…`
}

function computeStrataKinds(memberNodes: Node<MapNodePayload>[]): MapNodePayload['kind'][] {
  const order: MapNodePayload['kind'][] = ['tree', 'branch', 'flower', 'fruit', 'seed']
  const seen = new Set<MapNodePayload['kind']>()
  for (const n of memberNodes) seen.add(n.data.kind)
  const kinds = order.filter((k) => seen.has(k))
  return kinds.slice(0, 6)
}

function computeKindCounts(memberNodes: Node<MapNodePayload>[]): Partial<Record<MapNodePayload['kind'], number>> {
  const counts: Partial<Record<MapNodePayload['kind'], number>> = {}
  for (const n of memberNodes) counts[n.data.kind] = (counts[n.data.kind] ?? 0) + 1
  return counts
}

function computeMemberKinds(memberNodes: Node<MapNodePayload>[]): Record<string, MapNodePayload['kind']> {
  const out: Record<string, MapNodePayload['kind']> = {}
  for (const n of memberNodes) out[n.id] = n.data.kind
  return out
}

const CONDITION_ACTIVITY_WEIGHT: Record<ConditionSeverity, number> = {
  0: 1,
  1: 0.65,
  2: 0.4,
  3: 0.28,
}

function activityScore(d: MapNodePayload): number {
  const g =
    d.growth === 'fruiting'
      ? 1
      : d.growth === 'growing'
        ? 0.78
        : d.growth === 'germinating'
          ? 0.56
          : d.growth === 'decaying'
            ? 0.35
            : d.growth === 'dormant'
              ? 0.28
              : 0.18
  const w = d.water_level === 'high' ? 0.9 : d.water_level === 'medium' ? 0.6 : 0.3
  const c = CONDITION_ACTIVITY_WEIGHT[effectiveConditionSeverity(d)]
  const pulse = d.fertilizer_pulse ? 0.12 : 0
  return g * 0.5 + w * 0.28 + c * 0.22 + pulse
}

function computeStoneKinds(memberNodes: Node<MapNodePayload>[]): MapNodePayload['kind'][] {
  if (memberNodes.length === 0) return []
  const prefer = memberNodes
    .filter((n) => n.data.kind === 'branch' || n.data.kind === 'tree' || n.data.kind === 'seed')
    .sort((a, b) => activityScore(b.data) - activityScore(a.data))[0]
  const bottom = prefer ?? [...memberNodes].sort((a, b) => activityScore(b.data) - activityScore(a.data))[0]!
  const rest = memberNodes
    .filter((n) => n.id !== bottom.id)
    .sort((a, b) => activityScore(a.data) - activityScore(b.data))
  return [bottom.data.kind, ...rest.map((n) => n.data.kind)]
}

const kindWeight: Record<MapNodePayload['kind'], number> = {
  tree: 1.45,
  branch: 1.25,
  flower: 1,
  fruit: 1.35,
  seed: 0.95,
}

export function computeNestGrowthTriad(
  group: Pick<NestGroup, 'memberNodeIds'>,
  memberNodes: Node<MapNodePayload>[],
  entityBundle: VisionMapEntityBundle | null,
): GrowthTriadMetrics {
  const byId = new Map(memberNodes.map((n) => [n.id, n]))
  let water = 0
  let soil = 0
  let fruit = 0
  let wSum = 0
  for (const id of group.memberNodeIds) {
    const n = byId.get(id)
    if (!n) continue
    const t = mapVisualTriad(n.data, entityBundle)
    const w = kindWeight[n.data.kind]
    water += t.water * w
    soil += t.soil * w
    fruit += t.fruit * w
    wSum += w
  }
  if (wSum <= 0) return { water: 0.5, soil: 0.5, fruit: 0.5 }
  return { water: water / wSum, soil: soil / wSum, fruit: fruit / wSum }
}

export function computeNestVitality(triad: GrowthTriadMetrics): NestVitality {
  return {
    dry: triad.water < 0.4,
    soft: triad.soil < MAP_SOIL_TIER_LOW_BELOW,
    lush: triad.fruit > 0.66,
  }
}

export function createNestGroup(
  rootNodeId: string,
  nodes: Node<MapNodePayload>[],
  edges: Edge[],
  entityBundle: VisionMapEntityBundle | null,
): NestGroup | null {
  const rootNode = nodes.find((n) => n.id === rootNodeId)
  if (!rootNode || !canNestNode(rootNode)) return null
  /** Rooted subtree only (canonical base graph edges + tier-aware downstream walk). No ancestor expansion. */
  const subtree = collectDescendantSubtree(rootNodeId, nodes, edges)
  if (subtree.nodeIds.length <= 1) return null
  const memberNodeIds = subtree.nodeIds
  const memberNodes = nodes.filter((n) => memberNodeIds.includes(n.id))
  const rel: Record<string, XYPosition> = {}
  const relativeDepths: Record<string, number> = {}
  for (const n of memberNodes) {
    rel[n.id] = {
      x: n.position.x - rootNode.position.x,
      y: n.position.y - rootNode.position.y,
    }
    relativeDepths[n.id] = subtree.depths[n.id] ?? 0
  }
  const nestId = `nest-${rootNodeId}`
  const triad = computeNestGrowthTriad({ memberNodeIds }, memberNodes, entityBundle)
  return {
    id: nestId,
    rootNodeId,
    memberNodeIds,
    memberEdgeIds: subtree.edgeIds,
    collapsed: true,
    dominantLabel: getDominantNestLabel(rootNode, memberNodes),
    anchorPosition: { ...rootNode.position },
    relativePositions: rel,
    relativeDepths,
    strataKinds: computeStrataKinds(memberNodes),
    stoneKinds: computeStoneKinds(memberNodes),
    kindCounts: computeKindCounts(memberNodes),
    memberKinds: computeMemberKinds(memberNodes),
    triad,
    vitality: computeNestVitality(triad),
  }
}

/**
 * Before adding a nest rooted at R, remove any **existing** collapsed nests whose root lies inside
 * the new member set (e.g. nesting an initiative absorbs nested project cairns into one stack).
 */
export function dissolveNestsMergedIntoAncestor(nestState: NestState, incoming: NestGroup): NestState {
  const memberSet = new Set(incoming.memberNodeIds)
  const rootsToStrip = Object.values(nestState.groups)
    .filter((g) => g.rootNodeId !== incoming.rootNodeId && memberSet.has(g.rootNodeId))
    .map((g) => g.rootNodeId)
  let next = nestState
  for (const r of rootsToStrip) {
    next = withRemovedNestGroup(next, r)
  }
  return next
}

export function withAddedNestGroup(nestState: NestState, group: NestGroup): NestState {
  const groups = { ...nestState.groups, [group.id]: group }
  const nodeToNestId = { ...nestState.nodeToNestId }
  for (const id of group.memberNodeIds) nodeToNestId[id] = group.id
  return {
    groups,
    nodeToNestId,
    rootToNestId: { ...nestState.rootToNestId, [group.rootNodeId]: group.id },
  }
}

export function withRemovedNestGroup(nestState: NestState, rootNodeId: string): NestState {
  const nestId = nestState.rootToNestId[rootNodeId]
  if (!nestId) return nestState
  const group = nestState.groups[nestId]
  if (!group) return nestState
  const groups = { ...nestState.groups }
  delete groups[nestId]
  const nodeToNestId = { ...nestState.nodeToNestId }
  for (const id of group.memberNodeIds) delete nodeToNestId[id]
  const rootToNestId = { ...nestState.rootToNestId }
  delete rootToNestId[rootNodeId]
  return { groups, nodeToNestId, rootToNestId }
}

export function updateNestAnchor(nestState: NestState, nestId: string, pos: XYPosition): NestState {
  const g = nestState.groups[nestId]
  if (!g) return nestState
  return {
    ...nestState,
    groups: {
      ...nestState.groups,
      [nestId]: { ...g, anchorPosition: { ...pos } },
    },
  }
}

export function applyNestTransform(
  nodes: Node<MapNodePayload>[],
  edges: Edge[],
  nestState: NestState,
  selectedRootNodeId?: string | null,
  onExpandNest?: (rootNodeId: string) => void,
  focusByNodeId?: Record<string, { dimmed?: boolean; focusLineage?: boolean }>,
): {
  visibleEntityNodes: Node<MapNodePayload>[]
  visibleEdges: Edge[]
  nestNodes: Node<NestGroupNodeData>[]
} {
  const hiddenNodeIds = new Set<string>()
  for (const g of Object.values(nestState.groups)) {
    if (!g.collapsed) continue
    for (const id of g.memberNodeIds) hiddenNodeIds.add(id)
  }

  const visibleEntityNodes = nodes.filter((n) => !hiddenNodeIds.has(n.id))
  const visibleEdges = edges.filter((e) => {
    if (isEdgeHiddenByNest(e, nestState)) return false
    return !hiddenNodeIds.has(e.source) && !hiddenNodeIds.has(e.target)
  })

  const nestNodes: Node<NestGroupNodeData>[] = []
  for (const g of Object.values(nestState.groups)) {
    if (!g.collapsed) continue
    nestNodes.push({
      id: g.id,
      type: 'nestGroup',
      className: 'map-rf-node-nest',
      draggable: true,
      position: { ...g.anchorPosition },
      data: {
        nestId: g.id,
        rootNodeId: g.rootNodeId,
        dominantLabel: g.dominantLabel,
        memberCount: g.memberNodeIds.length,
        strataKinds: g.strataKinds,
        stoneKinds: g.stoneKinds,
        kindCounts: g.kindCounts,
        triad: g.triad,
        vitality: g.vitality,
        selected: selectedRootNodeId === g.rootNodeId,
        onExpand: onExpandNest ? () => onExpandNest(g.rootNodeId) : undefined,
        dimmed: focusByNodeId?.[g.rootNodeId]?.dimmed,
        focusLineage: focusByNodeId?.[g.rootNodeId]?.focusLineage,
      },
    })
    const boundaryIn = edges.filter(
      (e) => g.memberNodeIds.includes(e.target) && !g.memberNodeIds.includes(e.source),
    )
    const inSeen = new Set<string>()
    for (const pe of boundaryIn) {
      const key = `${pe.source}->${g.id}`
      if (inSeen.has(key)) continue
      visibleEdges.push({
        ...pe,
        id: `${pe.id}-in-${g.id}`,
        target: g.id,
        data: { ...(pe.data ?? {}), collapsedBoundary: true, boundaryKind: 'incoming' },
      })
      inSeen.add(key)
    }

    const boundaryOut = edges.filter(
      (e) => g.memberNodeIds.includes(e.source) && !g.memberNodeIds.includes(e.target),
    )
    const outSeen = new Set<string>()
    for (const be of boundaryOut) {
      const key = `${g.id}->${be.target}`
      if (outSeen.has(key)) continue
      outSeen.add(key)
      visibleEdges.push({
        ...be,
        id: `${be.id}-out-${g.id}`,
        source: g.id,
        data: { ...(be.data ?? {}), collapsedBoundary: true, boundaryKind: 'outgoing' },
      })
    }
  }

  return { visibleEntityNodes, visibleEdges, nestNodes }
}

