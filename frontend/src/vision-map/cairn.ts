/**
 * Cairn mode — dense-garden stacking for the Vision map.
 *
 * When a garden grows past the render threshold, project subtrees
 * (branch + its task flowers + outcome fruit) collapse into a single
 * **cairn** node: a small vertical stack of symbolic stones with a count
 * badge. Nothing is dropped — stones are stacked, not hidden.
 *
 * Below the threshold the graph passes through untouched.
 *
 * Urgency ordering reuses the map's existing severity scale
 * (`effectiveConditionSeverity`, 0–3, the same signal that paints stone
 * cracks): the most urgent stone sits on top of each cairn.
 *
 * All functions here are pure (no React) so they can be driven directly
 * in a jsdom/node harness.
 */
import type { Edge, Node } from '@xyflow/react'
import type { MapNodePayload } from './ontology'
import { effectiveConditionSeverity } from './resolveConditionSeverity'

/** Rendered-node thresholds: past these, project subtrees become cairns. */
export const CAIRN_NARROW_THRESHOLD = 40
export const CAIRN_WIDE_THRESHOLD = 80
/** Long-press dwell that toggles a cairn (tap keeps select/focus behavior). */
export const CAIRN_LONG_PRESS_MS = 550

export type CairnEntry = {
  cairnId: string
  projectId: string
  projectTitle: string
  /** The collapsed cairn node (re-added on collapse). */
  cairnNode: Node<MapNodePayload>
  /** tree → cairn edge (re-added on collapse). */
  treeCairnEdge: Edge | null
  /** Member stones, most urgent first, at their original layout positions. */
  memberNodes: Node<MapNodePayload>[]
  /** Internal edges + the original tree → branch edge (restored on expand). */
  memberEdges: Edge[]
  /** Branch position at build time — fan-out is relative to this. */
  branchPosition: { x: number; y: number }
}

export type CairnIndex = Record<string, CairnEntry>

export type CairnModeResult = {
  nodes: Node<MapNodePayload>[]
  edges: Edge[]
  /** Individual stone count before stacking (for the honest notice). */
  totalStones: number
  cairnCount: number
  cairned: boolean
  cairnIndex: CairnIndex
}

function projectIdOf(node: Node<MapNodePayload>): string | null {
  const d = node.data as MapNodePayload
  if (d.kind === 'branch') return d.ref.veType === 'project' ? d.ref.id : null
  if (d.kind === 'flower') {
    const pid = d.ref.projectId
    return typeof pid === 'string' && pid ? pid : null
  }
  if (d.kind === 'fruit') return d.parentRef?.veType === 'project' ? d.parentRef.id : null
  return null
}

function urgencyRank(node: Node<MapNodePayload>): number {
  const d = node.data as MapNodePayload
  return effectiveConditionSeverity(d) * 100 + (d.fertilizer_pulse ? 50 : 0)
}

function compareUrgencyDesc(a: Node<MapNodePayload>, b: Node<MapNodePayload>): number {
  const r = urgencyRank(b) - urgencyRank(a)
  if (r !== 0) return r
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0
}

type CairnPreviewStone = {
  growth: MapNodePayload['growth']
  kind: MapNodePayload['kind']
  severity: number
  pulse: boolean
}

/**
 * Collapse project subtrees into cairns when the node count passes the
 * threshold. Trees, seeds and landmarks always stay individual.
 */
export function applyCairnMode(
  nodes: Node<MapNodePayload>[],
  edges: Edge[],
  threshold: number,
): CairnModeResult {
  const totalStones = nodes.length
  if (!Number.isFinite(threshold) || threshold <= 0 || totalStones <= threshold) {
    return { nodes, edges, totalStones, cairnCount: 0, cairned: false, cairnIndex: {} }
  }

  const branches = new Map<string, Node<MapNodePayload>>()
  const membersByProject = new Map<string, Node<MapNodePayload>[]>()
  const singles: Node<MapNodePayload>[] = []
  for (const n of nodes) {
    const kind = (n.data as MapNodePayload).kind
    const pid = projectIdOf(n)
    if ((kind === 'branch' || kind === 'flower' || kind === 'fruit') && pid) {
      if (kind === 'branch') branches.set(pid, n)
      const list = membersByProject.get(pid) ?? []
      list.push(n)
      membersByProject.set(pid, list)
    } else {
      singles.push(n)
    }
  }

  const edgeByTarget = new Map<string, Edge[]>()
  for (const e of edges) {
    const list = edgeByTarget.get(e.target) ?? []
    list.push(e)
    edgeByTarget.set(e.target, list)
  }

  const cairnedMemberIds = new Set<string>()
  const cairnNodes: Node<MapNodePayload>[] = []
  const cairnIndex: CairnIndex = {}
  const treeCairnEdges: Edge[] = []

  for (const [pid, branch] of branches) {
    const rest = (membersByProject.get(pid) ?? []).filter((m) => m.id !== branch.id)
    const all = [branch, ...rest]
    // A lone stone is not a cairn — leave it individual.
    if (all.length < 2) {
      singles.push(...all)
      continue
    }
    const ranked = [...all].sort(compareUrgencyDesc)
    const bd = branch.data as MapNodePayload
    const topSeverity = effectiveConditionSeverity(ranked[0]!.data as MapNodePayload)
    const cairnId = `cairn-${pid}`
    const preview: CairnPreviewStone[] = ranked.slice(0, 4).map((m) => {
      const d = m.data as MapNodePayload
      return {
        growth: d.growth,
        kind: d.kind,
        severity: effectiveConditionSeverity(d),
        pulse: !!d.fertilizer_pulse,
      }
    })
    const cairnNode: Node<MapNodePayload> = {
      ...branch,
      id: cairnId,
      type: 'cairn',
      position: { ...branch.position },
      data: {
        ...bd,
        kind: 'cairn',
        label: bd.label || 'Project',
        subtitle: `${all.length} stones`,
        condition_severity: topSeverity,
        summaryLines: [
          `${all.length} stones stacked — long-press to fan them out.`,
          ...bd.summaryLines.slice(0, 2),
        ],
        fertilizer_pulse: ranked.some((m) => !!((m.data as MapNodePayload).fertilizer_pulse)),
        cairnProjectId: pid,
        cairnCount: all.length,
        cairnPreview: preview,
      },
    }

    const memberIdSet = new Set(all.map((m) => m.id))
    for (const m of all) cairnedMemberIds.add(m.id)
    const memberEdges: Edge[] = []
    for (const e of edges) {
      if (memberIdSet.has(e.source) && memberIdSet.has(e.target)) memberEdges.push(e)
    }
    // The tree → branch structural edge belongs to the cairn; it becomes tree → cairn.
    const treeEdge = (edgeByTarget.get(branch.id) ?? []).find((e) => !memberIdSet.has(e.source)) ?? null
    if (treeEdge) memberEdges.push(treeEdge)
    const treeCairnEdge: Edge | null = treeEdge
      ? { ...treeEdge, id: `e-${treeEdge.source}-${cairnId}`, target: cairnId }
      : null
    if (treeCairnEdge) treeCairnEdges.push(treeCairnEdge)

    cairnNodes.push(cairnNode)
    cairnIndex[cairnId] = {
      cairnId,
      projectId: pid,
      projectTitle: bd.label || 'Project',
      cairnNode,
      treeCairnEdge,
      memberNodes: ranked,
      memberEdges,
      branchPosition: { ...branch.position },
    }
  }

  // Members whose project had no branch (shouldn't happen) stay individual.
  for (const [pid, list] of membersByProject) {
    if (!branches.has(pid)) singles.push(...list)
  }

  const keptEdges = edges.filter((e) => !cairnedMemberIds.has(e.source) && !cairnedMemberIds.has(e.target))
  return {
    nodes: [...singles, ...cairnNodes],
    edges: [...keptEdges, ...treeCairnEdges],
    totalStones,
    cairnCount: cairnNodes.length,
    cairned: cairnNodes.length > 0,
    cairnIndex,
  }
}

/**
 * Expand a cairn: members fan out around the anchor (the cairn's current
 * position), keeping their relative layout offsets. Members are tagged
 * `expandedFromCairn` so a long-press on any of them collapses back.
 */
export function expandCairn(
  nodes: Node<MapNodePayload>[],
  edges: Edge[],
  entry: CairnEntry,
  anchor: { x: number; y: number },
): { nodes: Node<MapNodePayload>[]; edges: Edge[] } {
  const dx = anchor.x - entry.branchPosition.x
  const dy = anchor.y - entry.branchPosition.y
  const nextNodes = nodes.filter((n) => n.id !== entry.cairnId)
  for (const m of entry.memberNodes) {
    nextNodes.push({
      ...m,
      position: { x: m.position.x + dx, y: m.position.y + dy },
      data: { ...(m.data as object), expandedFromCairn: entry.cairnId } as MapNodePayload,
    })
  }
  const nextEdges = edges.filter((e) => e.source !== entry.cairnId && e.target !== entry.cairnId)
  nextEdges.push(...entry.memberEdges)
  return { nodes: nextNodes, edges: nextEdges }
}

/**
 * Collapse expanded members back into their cairn, placed at the anchor
 * (the branch stone's current position, so the cairn follows a drag).
 */
export function collapseCairn(
  nodes: Node<MapNodePayload>[],
  edges: Edge[],
  entry: CairnEntry,
  anchor: { x: number; y: number },
): { nodes: Node<MapNodePayload>[]; edges: Edge[] } {
  const memberIds = new Set(entry.memberNodes.map((m) => m.id))
  const memberEdgeIds = new Set(entry.memberEdges.map((e) => e.id))
  return {
    nodes: [
      ...nodes.filter((n) => !memberIds.has(n.id)),
      { ...entry.cairnNode, position: { ...anchor } },
    ],
    edges: [
      ...edges.filter((e) => !memberEdgeIds.has(e.id)),
      ...(entry.treeCairnEdge ? [entry.treeCairnEdge] : []),
    ],
  }
}

type ExpandedTag = { expandedFromCairn?: string }
function expandedTagOf(n: Node<MapNodePayload>): ExpandedTag {
  return (n.data ?? {}) as ExpandedTag
}

/**
 * Collapse anchor for one cairn: the branch stone's current position, so the
 * cairn reappears where its branch sits now (following drags). Null when the
 * branch member isn't on screen — the caller keeps the last stored anchor.
 * This is the single-collapse restore path; collapse-all reuses it per cairn.
 */
export function branchAnchorForCairn(
  nodes: Node<MapNodePayload>[],
  cairnId: string,
): { x: number; y: number } | null {
  const branch = nodes.find(
    (n) => expandedTagOf(n).expandedFromCairn === cairnId && n.data.kind === 'branch',
  )
  return branch ? { ...branch.position } : null
}

export type StoneLongPressTarget =
  | { action: 'collapseCairn'; cairnId: string }
  | { action: 'collapseAll' }
  | { action: 'none' }

/**
 * What a long-press on a stone should do. Expanded members collapse their
 * own cairn back; the initiative (tree) stone collapses ALL expanded cairns
 * — the garden-wide tidy-up gesture. Everything else: no long-press action,
 * so tap/drag behavior is untouched.
 */
export function longPressTargetFor(
  kind: MapNodePayload['kind'],
  expandedFromCairn: string | null,
): StoneLongPressTarget {
  if (expandedFromCairn) return { action: 'collapseCairn', cairnId: expandedFromCairn }
  if (kind === 'tree') return { action: 'collapseAll' }
  return { action: 'none' }
}
