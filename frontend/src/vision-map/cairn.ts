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
import type { Edge, Node, XYPosition } from '@xyflow/react'
import type { ConditionSeverity, MapNodePayload } from './ontology'
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

export type CairnPreviewStone = {
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
  | { action: 'toggleGardenStack'; treeId: string }
  | { action: 'none' }

/**
 * What a long-press on a stone should do. Expanded members collapse their
 * own cairn back; an initiative (tree) stone toggles that initiative's
 * stack — its children as the pile on its stone vs the full subtree. Everything
 * else: no long-press action, so tap/drag behavior is untouched.
 */
export function longPressTargetFor(
  kind: MapNodePayload['kind'],
  expandedFromCairn: string | null,
  nodeId: string,
): StoneLongPressTarget {
  if (expandedFromCairn) return { action: 'collapseCairn', cairnId: expandedFromCairn }
  if (kind === 'tree') return { action: 'toggleGardenStack', treeId: nodeId }
  return { action: 'none' }
}

/**
 * A stacked initiative is ONE object (Joshua, 2026-10-22): the pile sits
 * ON its parent stone — the merged node carries the tree's own id,
 * position, and edges, flagged `gardenStack` in its data — never a second
 * node floating beside the parent. This predicate is how renderers and
 * the toggle handler recognize that merged object.
 */
export function isGardenStackData(data: unknown): boolean {
  return (
    !!data &&
    typeof data === 'object' &&
    (data as { gardenStack?: unknown }).gardenStack === true
  )
}

/**
 * An initiative's descendant cairn ids: BFS over OUTGOING edges from the
 * tree, collecting cairn nodes only — traversal stops at non-cairn nodes
 * (landmarks, lone stones, seeds stay visible as reference points).
 * Pure.
 */
export function subtreeCairnIds(
  treeId: string,
  nodes: Node<MapNodePayload>[],
  edges: Edge[],
): string[] {
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const outgoing = new Map<string, Edge[]>()
  for (const e of edges) {
    const list = outgoing.get(e.source)
    if (list) list.push(e)
    else outgoing.set(e.source, [e])
  }
  const seen = new Set<string>([treeId])
  const found: string[] = []
  const queue: string[] = [treeId]
  while (queue.length > 0) {
    const cur = queue.shift()!
    for (const e of outgoing.get(cur) ?? []) {
      const nid = e.target
      if (seen.has(nid)) continue
      seen.add(nid)
      const n = byId.get(nid)
      if (!n) continue
      if ((n.data as MapNodePayload).kind === 'cairn') {
        found.push(nid)
        // Cairns are leaves in the base graph (members live in the cairn
        // index) — do not traverse beyond them.
      }
      // Non-cairn nodes: stop here, neither collected nor traversed.
    }
  }
  return found
}

function cairnStoneCount(n: Node<MapNodePayload>): number {
  const c = (n.data as { cairnCount?: unknown }).cairnCount
  return typeof c === 'number' && Number.isFinite(c) ? c : 0
}

/**
 * Build one initiative's garden-stack node: the pile sits ON the parent
 * stone as a single object — the returned node carries the tree's own id
 * and position (its edges follow automatically), flagged `gardenStack`.
 * Pure — the hidden cairns' positions stay in state untouched, so
 * unstacking restores them exactly where they were. The node's `ref`
 * points at its own initiative, so tapping it opens that initiative's
 * briefing sheet (`stone:initiative:{id}`), and its preview carries the
 * subtree's most urgent stones (most urgent on top, like project cairns).
 */
export function buildGardenStackNode(
  tree: Node<MapNodePayload>,
  subtreeCairns: Node<MapNodePayload>[],
): Node<MapNodePayload> {
  const treeData = tree.data as MapNodePayload
  const previews: CairnPreviewStone[] = []
  for (const c of subtreeCairns) {
    const cp = (c.data as { cairnPreview?: unknown }).cairnPreview
    if (Array.isArray(cp)) {
      for (const p of cp) {
        const s = p as Partial<CairnPreviewStone>
        previews.push({
          growth: (s.growth ?? 'dormant') as CairnPreviewStone['growth'],
          kind: (s.kind ?? 'branch') as CairnPreviewStone['kind'],
          severity: typeof s.severity === 'number' ? s.severity : 0,
          pulse: !!s.pulse,
        })
      }
    }
  }
  previews.sort((a, b) => b.severity - a.severity)
  const totalStones = subtreeCairns.reduce((t, c) => t + cairnStoneCount(c), 0)
  let maxSeverity: ConditionSeverity = 0
  let anyPulse = false
  for (const c of subtreeCairns) {
    const s = effectiveConditionSeverity(c.data as MapNodePayload)
    if (s > maxSeverity) maxSeverity = s
    if ((c.data as MapNodePayload).fertilizer_pulse) anyPulse = true
  }
  return {
    id: tree.id,
    type: 'cairn',
    position: { ...tree.position },
    data: {
      ...treeData,
      kind: 'cairn',
      gardenStack: true,
      label: treeData.label?.trim() || 'Stacked initiative',
      subtitle: `${totalStones} stones`,
      condition_severity: maxSeverity,
      summaryLines: [
        `${totalStones} stones stacked — long-press to unstack.`,
        ...((treeData.summaryLines ?? []).slice(0, 2)),
      ],
      fertilizer_pulse: anyPulse,
      cairnProjectId: null,
      cairnCount: totalStones,
      cairnPreview: previews.slice(0, 4),
      ref: treeData.ref,
    },
  }
}

/**
 * Per-initiative stack transform. For each stacked tree: its descendant
 * cairns (and only those) are hidden — not moved — and the tree node
 * itself is replaced by its garden-stack node: the pile sitting on the
 * parent stone as one object, keeping the tree's id, position, and edges.
 * Unstacked initiatives pass through untouched. Trees with no descendant
 * cairns are a no-op (no empty pile).
 *
 * Pure — the view memoizes this, so hidden cairns' positions and the
 * expanded-cairn set survive the round trip untouched.
 */
export function applyGardenStack(
  nodes: Node<MapNodePayload>[],
  edges: Edge[],
  stackedTreeIds: ReadonlySet<string>,
): { nodes: Node<MapNodePayload>[]; edges: Edge[]; hiddenCairnIds: Set<string> } {
  const hiddenCairnIds = new Set<string>()
  if (stackedTreeIds.size === 0) return { nodes, edges, hiddenCairnIds }
  const byId = new Map(nodes.map((n) => [n.id, n]))
  // Work on a shrinking set so a cairn is never claimed by two trees.
  let liveNodes = [...nodes]
  let liveEdges = [...edges]
  const stacks: Node<MapNodePayload>[] = []
  for (const treeId of stackedTreeIds) {
    const tree = byId.get(treeId)
    if (!tree || (tree.data as MapNodePayload).kind !== 'tree') continue
    const cairnIds = subtreeCairnIds(treeId, liveNodes, liveEdges)
    if (cairnIds.length === 0) continue
    const cairnNodes = cairnIds
      .map((id) => liveNodes.find((n) => n.id === id))
      .filter((n): n is Node<MapNodePayload> => !!n)
    const hidden = new Set(cairnIds)
    for (const id of hidden) hiddenCairnIds.add(id)
    liveNodes = liveNodes.filter((n) => !hidden.has(n.id))
    liveEdges = liveEdges.filter((e) => !hidden.has(e.source) && !hidden.has(e.target))
    // The parent stone is replaced by its stack — one object, not two.
    // Its edges reference the tree id, which the stack node keeps, so
    // they stay attached without rewriting.
    liveNodes = liveNodes.filter((n) => n.id !== treeId)
    stacks.push(buildGardenStackNode(tree, cairnNodes))
  }
  return { nodes: [...liveNodes, ...stacks], edges: liveEdges, hiddenCairnIds }
}

/**
 * Apply session drag positions after layout computation. Expanded cairn
 * members keep their fan-out positions unless the user dragged them this
 * session — then the dragged spot wins. Persisted/session position
 * overrides are deliberately NOT applied to expanded members: they would
 * yank stones to stale full-garden spots. Everything else takes the
 * override when present.
 *
 * Pure: the view calls this on the display graph before handing nodes to
 * React Flow, so a dragged member survives graph rebuilds instead of
 * snapping back to its fan-out position.
 */
export function applyDragPositions<T extends Node>(
  nodes: T[],
  expandedMemberIds: ReadonlySet<string>,
  memberDragPositions: Record<string, XYPosition>,
  positionOverrides: Record<string, XYPosition>,
): T[] {
  return nodes.map((n) => {
    const drag = expandedMemberIds.has(n.id) ? memberDragPositions[n.id] : positionOverrides[n.id]
    return drag ? { ...n, position: { ...drag } } : n
  })
}

/**
 * Drop session drag overrides for the given member ids — used when their
 * cairn collapses, so the next fan-out starts from the clean radial layout
 * instead of stale dragged spots. Returns the input unchanged when there
 * is nothing to drop.
 */
export function dropDragPositions(
  prev: Record<string, XYPosition>,
  memberIds: Iterable<string>,
): Record<string, XYPosition> {
  let changed = false
  const next: Record<string, XYPosition> = { ...prev }
  for (const id of memberIds) {
    if (id in next) {
      delete next[id]
      changed = true
    }
  }
  return changed ? next : prev
}
