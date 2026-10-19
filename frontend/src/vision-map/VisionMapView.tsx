import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type MouseEvent,
  type Ref,
  type RefObject,
  type SetStateAction,
  type WheelEvent as ReactWheelEvent,
} from 'react'
import type { MapTriadDevelopmentalSnapshot } from '../developmentalGuidance/types'
import {
  Controls,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  applyNodeChanges,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
  type XYPosition,
} from '@xyflow/react'
import type { MapNodePayload } from './ontology'
import '@xyflow/react/dist/style.css'
import './mapAesthetics.css'

import { EntityMapNode } from './EntityMapNode'
import { CairnNode } from './CairnNode'
import { NestGroupNode, NEST_NODE_LAYOUT_HEIGHT_PX, NEST_NODE_LAYOUT_WIDTH_PX } from './NestGroupNode'
import {
  CAIRN_NARROW_THRESHOLD,
  CAIRN_WIDE_THRESHOLD,
  applyDragPositions,
  branchAnchorForCairn,
  collapseCairn,
  dropDragPositions,
  expandCairn,
  type CairnEntry,
  type CairnIndex,
} from './cairn'
import { CairnInteractionContext } from './cairnContext'
import { MapFlowEdge } from './MapFlowEdge'
import { MapChatShell } from './MapChatShell'
import { fetchNodeVitalityMap, fetchVisionMapEntities } from './veMapApi'
import { fetchStudioCouncilRuns } from './fetchStudioCouncilRuns'
import { buildLiveVisionMapGraph } from './liveProjection'
import { MAP_ENTITY_FALLBACK_LAYOUT_PX, mapEntityNodeLayoutPx } from './mapEntityNodeLayout'
import type { VisionMapEntityBundle } from './blockersFromVe'
import { applyFocusToVisionMap } from './visionMapFocus'
import { MapSandRakeControls } from './MapSandRakeControls'
import { ZenSandCanvas, type ZenSandCanvasHandle } from './ZenSandCanvas'
import type { VisionMapCouncilInteraction } from './visionMapCouncilInteraction'
import {
  clearVisionMapLayout,
  loadVisionMapLayout,
  saveVisionMapLayout,
  visionMapLayoutStorageKey,
  type VisionMapPersistedViewport,
} from './visionMapLayoutPersistence'
import {
  EMPTY_NEST_STATE,
  applyNestTransform,
  canNestNode,
  computeNestGrowthTriad,
  createNestGroup,
  dissolveNestsMergedIntoAncestor,
  getNestGroupForRoot,
  updateNestAnchor,
  withAddedNestGroup,
  withRemovedNestGroup,
  type NestGroupNodeData,
  type NestState,
} from './nesting'
import { applyLocalRepulsion, expandRelativePositions } from './nestLayout'
import { mapVisualTriad } from './mapGrowthMetrics'
import { detectMissingDimensions } from './guidanceScripts'
import { assessNodeFlowAndChannels } from '../flow/assessNodeFlowAndChannels'
import { useVisionExecutionFocusOptional } from '../vision-execution/focus/VisionExecutionFocusContext'
import { mapPayloadToConversationFocusDescriptor } from './mapFocusDescriptor'
import { VeRadarAwarenessStrip } from './VeRadarAwarenessStrip'
import type { VeRadarBucketId } from '../vision-execution/veRadarAwareness'

const nodeTypes = { entityMap: EntityMapNode, nestGroup: NestGroupNode, cairn: CairnNode }
const edgeTypes = { mapFlow: MapFlowEdge }
const TRACKPAD_ZOOM_GAIN = 2.2
const SCENE_BASE_HEIGHT_PX = 560
const SCENE_CONTENT_PADDING_PX = 260
/** Fallback node size before React Flow measures — matches painted stone box (see mapEntityNodeLayout). */
const DEFAULT_ENTITY_W = MAP_ENTITY_FALLBACK_LAYOUT_PX.width
const DEFAULT_ENTITY_H = MAP_ENTITY_FALLBACK_LAYOUT_PX.height
const INITIAL_MAP_ZOOM = 1
const ORIENT_RETRY_MS = 600

const MAP_SAND_LAYER_CLASS = 'map-sand-layer'

type VisionMapMapWorldProps = {
  sandRef: RefObject<ZenSandCanvasHandle | null>
  reduceMotion: boolean
  rakeEnabled: boolean
  setRakeEnabled: Dispatch<SetStateAction<boolean>>
  rakeFadeSec: 12 | 16 | 20
  setRakeFadeSec: Dispatch<SetStateAction<12 | 16 | 20>>
  loadState: 'idle' | 'loading' | 'ok' | 'error'
  loadErr: string | null
  onRetryLoad: () => void
  baseGraph: { nodes: Node<MapNodePayload>[]; edges: Edge[] } | null
  nodeCount: number
  mapViewportReady: boolean
  selectedNodeId: string | null
  sceneHeightPx: number
  nodes: Node<MapNodePayload | NestGroupNodeData>[]
  edges: Edge[]
  onNodesChange: (changes: NodeChange[]) => void
  onEdgesChange: (changes: EdgeChange<Edge>[]) => void
  onNodeClick: (_: MouseEvent, node: Node<MapNodePayload | NestGroupNodeData>) => void
  onPaneClick: () => void
  onViewportChange: (viewport: { zoom: number }) => void
  onMoveEnd: () => void
  zoomLevel: number
  onOpenOperatorMode: () => void
}

/** Sand + rake controls + React Flow — isolated from `councilQuestionDraft` so typing in chat does not re-render the zen canvas. */
const VisionMapMapWorld = memo(function VisionMapMapWorld({
  sandRef,
  reduceMotion,
  rakeEnabled,
  setRakeEnabled,
  rakeFadeSec,
  setRakeFadeSec,
  loadState,
  loadErr,
  onRetryLoad,
  baseGraph,
  nodeCount,
  mapViewportReady,
  selectedNodeId,
  sceneHeightPx,
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  onNodeClick,
  onPaneClick,
  onViewportChange,
  onMoveEnd,
  zoomLevel,
  onOpenOperatorMode,
}: VisionMapMapWorldProps) {
  return (
    <div
      className={`map-world-wrap flex flex-col flex-1 min-w-0 min-h-[480px] relative overflow-hidden ${selectedNodeId ? 'map-focus-active' : ''}`}
      style={{ height: `${sceneHeightPx}px` }}
    >
      <ZenSandCanvas
        ref={sandRef as Ref<ZenSandCanvasHandle>}
        reducedMotion={reduceMotion}
        className={MAP_SAND_LAYER_CLASS}
        rakeEnabled={rakeEnabled}
        rakeFadeAfterMs={rakeFadeSec * 1000}
      />
      <MapSandRakeControls
        sandRef={sandRef}
        rakeEnabled={rakeEnabled}
        onRakeEnabledChange={setRakeEnabled}
        fadeSec={rakeFadeSec}
        onFadeSecChange={setRakeFadeSec}
      />
      {loadState === 'loading' && !baseGraph && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-stone-100/85 text-stone-700 text-sm backdrop-blur-[2px]">
          Loading Vision Execution…
        </div>
      )}
      {loadState === 'error' && (
        <div className="absolute inset-0 z-30 flex items-center justify-center bg-stone-950/88 text-stone-100 p-6 backdrop-blur-sm">
          <div className="max-w-md rounded-xl border border-red-900/60 bg-stone-900/95 px-5 py-4 shadow-lg space-y-3 text-center">
            <h2 className="text-sm font-semibold text-stone-100">Couldn’t load map data</h2>
            <p className="text-xs text-stone-300 leading-relaxed">{loadErr ?? 'Something went wrong.'}</p>
            <div className="flex flex-wrap gap-2 justify-center pt-1">
              <button
                type="button"
                onClick={onRetryLoad}
                className="px-3 py-2 rounded-lg bg-amber-600 hover:bg-amber-500 text-white text-xs font-medium"
              >
                Refresh data
              </button>
              <button
                type="button"
                onClick={onOpenOperatorMode}
                className="px-3 py-2 rounded-lg border border-stone-600 text-stone-200 hover:bg-stone-800 text-xs font-medium"
              >
                Open operator mode
              </button>
            </div>
          </div>
        </div>
      )}
      {loadState === 'ok' && nodeCount === 0 && (
        <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 bg-stone-100/90 text-stone-700 text-sm p-6 text-center backdrop-blur-[2px]">
          <p>No ideas, initiatives, projects, or tasks yet.</p>
          <button
            type="button"
            onClick={onOpenOperatorMode}
            className="text-yellow-800 hover:text-yellow-700 underline text-xs font-medium"
          >
            Open operator mode to add data
          </button>
        </div>
      )}
      {loadState === 'ok' && nodeCount > 0 && !mapViewportReady && (
        <div
          className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-2 bg-stone-900 text-stone-400 text-sm"
          aria-live="polite"
        >
          <span
            className="inline-block h-5 w-5 animate-pulse rounded-full border-2 border-stone-500 border-t-amber-600/80"
            aria-hidden
          />
          <span>Placing the map…</span>
        </div>
      )}
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        nodesDraggable={true}
        nodesConnectable={false}
        nodeDragThreshold={10}
        selectNodesOnDrag={false}
        panOnDrag={[0, 2]}
        panOnScroll={true}
        panActivationKeyCode="Space"
        zoomActivationKeyCode="Control"
        selectionKeyCode="Shift"
        elementsSelectable
        fitView={false}
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.2}
        maxZoom={1.6}
        zoomOnScroll={true}
        zoomOnPinch={true}
        proOptions={{ hideAttribution: true }}
        debug={false}
        colorMode="dark"
        className={`map-graph-canvas !bg-transparent flex-1 min-h-0 h-full w-full transition-opacity duration-200 ${
          loadState === 'ok' && nodeCount > 0 && !mapViewportReady ? 'opacity-0' : 'opacity-100'
        }`}
        style={{ background: 'transparent' }}
        onMove={(_, viewport) => onViewportChange(viewport)}
        onMoveEnd={() => onMoveEnd()}
      >
        <Controls showInteractive={false} position="top-left" />
        <Panel position="top-left" className="ml-12 mt-1 pointer-events-none">
          <div className="rounded-md border border-stone-700/70 bg-stone-900/78 px-2 py-1 text-[11px] font-medium text-stone-200">
            {Math.round(zoomLevel * 100)}%
          </div>
        </Panel>
      </ReactFlow>
    </div>
  )
})

export type VisionMapViewProps = {
  onOpenOperatorMode: () => void
  /** Jump to Vision & Execution Radar tab; optional bucket for scroll target. */
  onOpenVeRadar?: (bucket?: VeRadarBucketId) => void
  councilQuestionDraft: string
  onVisionMapCouncilInteraction: (action: VisionMapCouncilInteraction) => void
  /** Growth triad snapshot for developmental guidance (council preflight); cleared when selection clears. */
  onDevelopmentalSignalsChange?: (payload: MapTriadDevelopmentalSnapshot | null) => void
  /** Latest VE entity lists (for council triad when not on this tab); optional. */
  onCouncilEntityBundleSnapshot?: (bundle: VisionMapEntityBundle | null) => void
  /**
   * Scopes saved stone positions + viewport (localStorage). Use a stable account/workspace id.
   * @default 'default'
   */
  layoutPersistenceContext?: string
  /** Sync map node selection to App `veSelection` + global focus (Pass 1). */
  onMapEntitySelectionChange?: (payload: MapNodePayload | null) => void
}

function VisionMapFlow({
  onOpenOperatorMode,
  onOpenVeRadar,
  councilQuestionDraft,
  onVisionMapCouncilInteraction,
  onDevelopmentalSignalsChange,
  onCouncilEntityBundleSnapshot,
  onMapEntitySelectionChange,
  layoutPersistenceContext = 'default',
}: VisionMapViewProps) {
  const sandRef = useRef<ZenSandCanvasHandle>(null)
  const loadGenerationRef = useRef(0)
  const viewportRestoreRef = useRef<VisionMapPersistedViewport | null>(null)
  const positionOverridesRef = useRef<Record<string, XYPosition>>({})
  const baseGraphRef = useRef<{ nodes: Node<MapNodePayload>[]; edges: Edge[] } | null>(null)
  const loadStateRef = useRef<'idle' | 'loading' | 'ok' | 'error'>('idle')
  const layoutStorageKey = useMemo(
    () => visionMapLayoutStorageKey(layoutPersistenceContext),
    [layoutPersistenceContext],
  )
  const persistDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [reduceMotion, setReduceMotion] = useState(false)
  const [rakeEnabled, setRakeEnabled] = useState(true)
  const [rakeFadeSec, setRakeFadeSec] = useState<12 | 16 | 20>(16)
  const rf = useReactFlow()
  const [baseGraph, setBaseGraph] = useState<{ nodes: Node<MapNodePayload>[]; edges: Edge[] } | null>(null)
  const [entityBundle, setEntityBundle] = useState<VisionMapEntityBundle | null>(null)
  /** Cairn mode: honest counts for the notice; the index + anchors live in refs (not render state). */
  const [cairnMeta, setCairnMeta] = useState({ totalStones: 0, cairnCount: 0, cairned: false })
  const [expandedCairns, setExpandedCairns] = useState<ReadonlySet<string>>(new Set())
  const cairnIndexRef = useRef<CairnIndex>({})
  const cairnAnchorRef = useRef<Record<string, XYPosition>>({})

  useEffect(() => {
    onCouncilEntityBundleSnapshot?.(entityBundle)
  }, [entityBundle, onCouncilEntityBundleSnapshot])
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [selectedPayload, setSelectedPayload] = useState<MapNodePayload | null>(null)
  const [nestState, setNestState] = useState<NestState>(EMPTY_NEST_STATE)
  const [positionOverrides, setPositionOverrides] = useState<Record<string, XYPosition>>({})
  /**
   * Session-only drag positions for expanded cairn members. Dragged members
   * keep their spots across graph rebuilds instead of snapping back to the
   * fan-out layout; dropped per-cairn on collapse so the next fan-out
   * starts clean. Never persisted to the layout store.
   */
  const [memberDragPositions, setMemberDragPositions] = useState<Record<string, XYPosition>>({})
  const [loadState, setLoadState] = useState<'idle' | 'loading' | 'ok' | 'error'>('idle')
  const [loadErr, setLoadErr] = useState<string | null>(null)
  /** Bumps VeRadarAwarenessStrip refresh when map reloads VE entities. */
  const [radarStripRefreshNonce, setRadarStripRefreshNonce] = useState(0)
  /** False until first viewport is centered on a node (avoid fit-to-full-canvas zoom-out flash). */
  const [mapViewportReady, setMapViewportReady] = useState(false)

  const [nodes, setNodes] = useNodesState<Node<MapNodePayload | NestGroupNodeData>>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const [zoomLevel, setZoomLevel] = useState(1)
  const [guidancePulseNodeId, setGuidancePulseNodeId] = useState<string | null>(null)

  const mapFocusCtx = useVisionExecutionFocusOptional()
  const mapFocusCtxRef = useRef(mapFocusCtx)
  mapFocusCtxRef.current = mapFocusCtx

  const onMapEntitySelectionChangeRef = useRef(onMapEntitySelectionChange)
  onMapEntitySelectionChangeRef.current = onMapEntitySelectionChange

  /** Avoid re-notifying focus when parent re-renders with the same map selection (prevents focus bar / invite flicker). */
  const lastConversationFocusKeyRef = useRef<string | null>(null)

  useEffect(() => {
    onMapEntitySelectionChangeRef.current?.(selectedPayload)
    if (selectedPayload) {
      const desc = mapPayloadToConversationFocusDescriptor(selectedPayload)
      if (desc) {
        const k = `${desc.surface}\0${desc.entity_type}\0${desc.entity_id}\0${desc.field_key}\0${desc.field_label}`
        if (lastConversationFocusKeyRef.current !== k) {
          lastConversationFocusKeyRef.current = k
          mapFocusCtxRef.current?.notifyConversationEntityFocus(desc)
        }
      } else {
        lastConversationFocusKeyRef.current = null
        mapFocusCtxRef.current?.clearConversationEntityShell()
      }
    } else {
      lastConversationFocusKeyRef.current = null
      mapFocusCtxRef.current?.clearConversationEntityShell()
    }
  }, [selectedPayload])

  const onViewportChange = useCallback(({ zoom }: { zoom: number }) => {
    setZoomLevel(zoom)
  }, [])

  const flushPersistLayout = useCallback(() => {
    const bg = baseGraphRef.current
    const ls = loadStateRef.current
    if (!bg || ls !== 'ok') return
    let vp: { x: number; y: number; zoom: number }
    try {
      vp = rf.getViewport()
    } catch {
      return
    }
    const entityIds = new Set(bg.nodes.map((node) => node.id))
    const positions: Record<string, { x: number; y: number }> = {}
    for (const [id, pos] of Object.entries(positionOverridesRef.current)) {
      if (entityIds.has(id)) positions[id] = { x: pos.x, y: pos.y }
    }
    saveVisionMapLayout(layoutStorageKey, { positions, viewport: { x: vp.x, y: vp.y, zoom: vp.zoom } })
  }, [layoutStorageKey, rf])

  const schedulePersistLayout = useCallback(() => {
    if (persistDebounceRef.current) window.clearTimeout(persistDebounceRef.current)
    persistDebounceRef.current = window.setTimeout(() => {
      persistDebounceRef.current = null
      flushPersistLayout()
    }, 400)
  }, [flushPersistLayout])

  useEffect(() => {
    positionOverridesRef.current = positionOverrides
  }, [positionOverrides])

  useEffect(() => {
    baseGraphRef.current = baseGraph
  }, [baseGraph])

  useEffect(() => {
    loadStateRef.current = loadState
  }, [loadState])

  useEffect(
    () => () => {
      if (persistDebounceRef.current) window.clearTimeout(persistDebounceRef.current)
    },
    [],
  )

  const load = useCallback(async () => {
    setLoadState('loading')
    setMapViewportReady(false)
    setLoadErr(null)
    try {
      const [entities, runs, serverVitality] = await Promise.all([
        fetchVisionMapEntities(),
        fetchStudioCouncilRuns(80),
        fetchNodeVitalityMap().catch(() => undefined),
      ])
      const narrow =
        typeof window !== 'undefined' && window.matchMedia('(max-width: 767px)').matches
      const g = buildLiveVisionMapGraph(entities, runs, serverVitality, {
        cairnThreshold: narrow ? CAIRN_NARROW_THRESHOLD : CAIRN_WIDE_THRESHOLD,
      })
      const persisted = loadVisionMapLayout(layoutStorageKey)
      const ids = new Set(g.nodes.map((node) => node.id))
      const restoredPos: Record<string, XYPosition> = {}
      if (persisted?.positions) {
        for (const [id, pos] of Object.entries(persisted.positions)) {
          if (ids.has(id)) restoredPos[id] = { x: pos.x, y: pos.y }
        }
      }
      viewportRestoreRef.current = persisted?.viewport ?? null
      setEntityBundle(entities)
      cairnIndexRef.current = g.cairnIndex
      cairnAnchorRef.current = {}
      setCairnMeta({ totalStones: g.totalStones, cairnCount: g.cairnCount, cairned: g.cairned })
      setExpandedCairns(new Set())
      setBaseGraph({ nodes: g.nodes, edges: g.edges })
      setNestState(EMPTY_NEST_STATE)
      setPositionOverrides(restoredPos)
      setMemberDragPositions({})
      setSelectedNodeId(null)
      setSelectedPayload(null)
      setLoadState('ok')
      setRadarStripRefreshNonce((n) => n + 1)
    } catch (err) {
      setLoadState('error')
      setLoadErr(err instanceof Error ? err.message : String(err))
      setBaseGraph(null)
      setEntityBundle(null)
      cairnIndexRef.current = {}
      setCairnMeta({ totalStones: 0, cairnCount: 0, cairned: false })
      setExpandedCairns(new Set())
      viewportRestoreRef.current = null
    }
  }, [layoutStorageKey])

  useEffect(() => {
    void load()
  }, [load])

  /**
   * Cairn expansion layer. Expanded cairns swap for their member stones,
   * fanned out around the cairn's current position (relative offsets from
   * the original layout are preserved). Members carry `expandedFromCairn`
   * so a long-press on any of them collapses back.
   */
  const displayGraph = useMemo(() => {
    const empty = new Set<string>()
    if (!baseGraph) return { nodes: [] as Node<MapNodePayload>[], edges: [] as Edge[], expandedMemberIds: empty }
    if (expandedCairns.size === 0) {
      return { nodes: baseGraph.nodes, edges: baseGraph.edges, expandedMemberIds: empty }
    }
    let nodes = [...baseGraph.nodes]
    let edges = [...baseGraph.edges]
    const expandedMemberIds = new Set<string>()
    for (const cid of expandedCairns) {
      const entry = cairnIndexRef.current[cid]
      if (!entry) continue
      const anchor = cairnAnchorRef.current[cid] ?? entry.cairnNode.position
      const ex = expandCairn(nodes, edges, entry, anchor)
      nodes = ex.nodes
      edges = ex.edges
      for (const m of entry.memberNodes) expandedMemberIds.add(m.id)
    }
    return { nodes, edges, expandedMemberIds }
  }, [baseGraph, expandedCairns])

  const toggleCairn = useCallback(
    (cairnId: string) => {
      const entry: CairnEntry | undefined = cairnIndexRef.current[cairnId]
      if (!entry) return
      if (expandedCairns.has(cairnId)) {
        // Collapsing: the cairn reappears where its branch stone sits now.
        const anchor = branchAnchorForCairn(nodes, cairnId)
        if (anchor) cairnAnchorRef.current[cairnId] = anchor
        // Drop this cairn's member drag spots so the next fan-out starts
        // from the clean radial layout.
        setMemberDragPositions((prev) =>
          dropDragPositions(
            prev,
            entry.memberNodes.map((m) => m.id),
          ),
        )
        setExpandedCairns((prev) => {
          const next = new Set(prev)
          next.delete(cairnId)
          return next
        })
      } else {
        const cairn = nodes.find((n) => n.id === cairnId)
        if (cairn) cairnAnchorRef.current[cairnId] = { ...cairn.position }
        setExpandedCairns((prev) => new Set(prev).add(cairnId))
      }
    },
    [nodes, expandedCairns],
  )

  /**
   * Garden-wide tidy-up: collapse every expanded cairn, each restored where
   * its branch stone sits (the same restore path as a single collapse).
   * Silent no-op when nothing is expanded — no flicker, no notice.
   */
  const collapseAllCairns = useCallback(() => {
    if (expandedCairns.size === 0) return
    for (const cairnId of expandedCairns) {
      const anchor = branchAnchorForCairn(nodes, cairnId)
      if (anchor) cairnAnchorRef.current[cairnId] = anchor
    }
    // Every cairn collapsed: all member drag spots go, next fan-outs start clean.
    setMemberDragPositions({})
    setExpandedCairns(new Set())
  }, [nodes, expandedCairns])

  const cairnInteractionValue = useMemo(
    () => ({ onToggleCairn: toggleCairn, onCollapseAllCairns: collapseAllCairns }),
    [toggleCairn, collapseAllCairns],
  )

  /** After a failed load the graph is empty; reset pan/zoom so a prior 20% zoom doesn’t hide the next success. */
  useEffect(() => {
    if (loadState !== 'error') return
    try {
      void rf.setViewport({ x: 0, y: 0, zoom: 1 }, { duration: 0 })
    } catch {
      /* ignore */
    }
    setZoomLevel(1)
  }, [loadState, rf])

  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    setReduceMotion(mq.matches)
    const onChange = () => setReduceMotion(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  useEffect(() => {
    if (!selectedNodeId || !baseGraph) return
    const nestId = nestState.nodeToNestId[selectedNodeId]
    if (!nestId) return
    const g = nestState.groups[nestId]
    if (!g?.collapsed) return
    const rootNode = baseGraph.nodes.find((n) => n.id === g.rootNodeId)
    if (!rootNode) return
    if (selectedNodeId === g.rootNodeId) return
    setSelectedNodeId(g.rootNodeId)
    setSelectedPayload(rootNode.data)
  }, [selectedNodeId, nestState, baseGraph])

  useEffect(() => {
    const viewGraph = displayGraph
    if (!baseGraph) {
      setNodes([])
      setEdges([])
      return
    }
    const baseNodes = applyDragPositions(
      viewGraph.nodes,
      viewGraph.expandedMemberIds,
      memberDragPositions,
      positionOverrides,
    ).map((n) => ({
      ...n,
      data: {
        ...n.data,
        fertilizer_pulse: n.data.fertilizer_pulse || n.id === guidancePulseNodeId,
      },
    }))
    const focusAll = applyFocusToVisionMap(
      baseNodes as Node<MapNodePayload>[],
      viewGraph.edges,
      selectedNodeId,
    )
    const focusByNodeId: Record<string, { dimmed?: boolean; focusLineage?: boolean }> = {}
    for (const n of focusAll.nodes) {
      focusByNodeId[n.id] = { dimmed: n.data.dimmed, focusLineage: n.data.focusLineage }
    }
    const transformed = applyNestTransform(
      focusAll.nodes as Node<MapNodePayload>[],
      focusAll.edges,
      nestState,
      selectedNodeId,
      (rootNodeId: string) => {
        setSelectedNodeId(rootNodeId)
        requestAnimationFrame(() => {
          const g = getNestGroupForRoot(rootNodeId, nestState)
          if (!g) return
          const expandedRel = expandRelativePositions(g.relativePositions, g.relativeDepths, {
            baseScale: 1.06,
            depthStep: 0.07,
            maxScale: 1.34,
            floorRadius: 34,
            kindById: g.memberKinds,
          })
          const restored: Record<string, XYPosition> = {}
          for (const id of g.memberNodeIds) {
            const rel = expandedRel[id]
            if (!rel) continue
            restored[id] = { x: g.anchorPosition.x + rel.x, y: g.anchorPosition.y + rel.y }
          }
          const allNodesWithPos = baseGraph.nodes.map((n) => ({
            ...n,
            position: restored[n.id] ?? positionOverrides[n.id] ?? n.position,
          }))
          const mergedPos: Record<string, XYPosition> = {}
          for (const n of allNodesWithPos) mergedPos[n.id] = n.position
          const repulsed = applyLocalRepulsion(
            g.memberNodeIds,
            allNodesWithPos as Node<MapNodePayload>[],
            mergedPos,
            { padding: 180, maxPush: 190, passCount: 2 },
          )
          setPositionOverrides((prev) => ({ ...prev, ...restored, ...repulsed }))
          setNestState((prev) => withRemovedNestGroup(prev, rootNodeId))
          schedulePersistLayout()
        })
      },
      focusByNodeId,
    )
    const focused = applyFocusToVisionMap(
      transformed.visibleEntityNodes as Node<MapNodePayload>[],
      transformed.visibleEdges,
      selectedNodeId,
    )
    setNodes([...(focused.nodes as Node<MapNodePayload>[]), ...transformed.nestNodes])
    setEdges(focused.edges)
  }, [
    displayGraph,
    baseGraph,
    selectedNodeId,
    setNodes,
    setEdges,
    nestState,
    positionOverrides,
    memberDragPositions,
    guidancePulseNodeId,
    schedulePersistLayout,
  ])

  useEffect(() => {
    if (!guidancePulseNodeId) return
    const timer = window.setTimeout(() => setGuidancePulseNodeId(null), 2200)
    return () => window.clearTimeout(timer)
  }, [guidancePulseNodeId])

  /**
   * On each new `baseGraph` (load / refresh): restore saved viewport, or else center on a random node at a fixed zoom.
   * Nesting does not change `baseGraph`, so this does not run again.
   */
  useEffect(() => {
    if (!baseGraph || baseGraph.nodes.length === 0) {
      setMapViewportReady(true)
      return
    }
    setMapViewportReady(false)
    let cancelled = false
    const started = performance.now()
    const savedVp = viewportRestoreRef.current
    viewportRestoreRef.current = null

    if (
      savedVp &&
      Number.isFinite(savedVp.x) &&
      Number.isFinite(savedVp.y) &&
      Number.isFinite(savedVp.zoom) &&
      savedVp.zoom > 0
    ) {
      const outerVp = window.setTimeout(() => {
        requestAnimationFrame(() => {
          void rf
            .setViewport(
              { x: savedVp.x, y: savedVp.y, zoom: savedVp.zoom },
              { duration: 0 },
            )
            .then(() => {
              if (!cancelled) {
                setZoomLevel(savedVp.zoom)
                setMapViewportReady(true)
              }
            })
            .catch(() => {
              if (!cancelled) setMapViewportReady(true)
            })
        })
      }, 0)
      return () => {
        cancelled = true
        clearTimeout(outerVp)
      }
    }

    const orient = () => {
      if (cancelled) return
      const live = rf.getNodes()
      if (live.length === 0) {
        if (performance.now() - started < ORIENT_RETRY_MS) {
          requestAnimationFrame(orient)
        } else {
          setMapViewportReady(true)
        }
        return
      }
      const pick = live[Math.floor(Math.random() * live.length)]!
      const defaultH = pick.type === 'nestGroup' ? NEST_NODE_LAYOUT_HEIGHT_PX : DEFAULT_ENTITY_H
      const defaultW = pick.type === 'nestGroup' ? NEST_NODE_LAYOUT_WIDTH_PX : DEFAULT_ENTITY_W
      const w = pick.measured?.width ?? pick.width ?? defaultW
      const h = pick.measured?.height ?? pick.height ?? defaultH
      const cx = pick.position.x + w / 2
      const cy = pick.position.y + h / 2
      void rf
        .setCenter(cx, cy, { zoom: INITIAL_MAP_ZOOM, duration: 0 })
        .then(() => {
          if (!cancelled) setMapViewportReady(true)
        })
        .catch(() => {
          if (!cancelled) setMapViewportReady(true)
        })
    }

    const outer = window.setTimeout(() => {
      requestAnimationFrame(() => {
        requestAnimationFrame(orient)
      })
    }, 0)
    return () => {
      cancelled = true
      clearTimeout(outer)
    }
  }, [baseGraph, rf])

  const onNodeClick = useCallback((_: MouseEvent, node: Node<MapNodePayload | NestGroupNodeData>) => {
    if (node.type === 'nestGroup') {
      const nestData = node.data as unknown as NestGroupNodeData
      const rootId = nestData.rootNodeId
      const rootNode = baseGraph?.nodes.find((n) => n.id === rootId)
      setSelectedNodeId(rootId)
      setSelectedPayload(rootNode?.data ?? null)
      return
    }
    setSelectedNodeId(node.id)
    setSelectedPayload((node.data as MapNodePayload) ?? null)
  }, [baseGraph])

  const onPaneClick = useCallback(() => {
    setSelectedNodeId(null)
    setSelectedPayload(null)
  }, [])

  const clearSelection = useCallback(() => {
    setSelectedNodeId(null)
    setSelectedPayload(null)
  }, [])

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      // Selection is owned by `selectedNodeId` + `applyFocusToVisionMap`. Applying RF `select` changes
      // fights that and causes rapid A↔B bouncing between clicks.
      const structural = changes.filter((c) => c.type !== 'select')
      if (structural.length > 0) {
        setNodes((nds) => applyNodeChanges(structural, nds) as Node<MapNodePayload | NestGroupNodeData>[])
      }
      const moveChanges = structural.filter(
        (c) => c.type === 'position' && !!(c as { position?: XYPosition }).position && !(c as { dragging?: boolean }).dragging,
      ) as Array<{ id: string; position: XYPosition }>
      if (moveChanges.length === 0) return
      // Expanded cairn members record session-only drag spots (kept across
      // rebuilds so they don't snap back); everything else records into
      // the persisted position overrides.
      const memberMoves: Array<{ id: string; position: XYPosition }> = []
      const otherMoves: Array<{ id: string; position: XYPosition }> = []
      for (const c of moveChanges) {
        const n = nodes.find((nn) => nn.id === c.id)
        if (n?.type === 'nestGroup') {
          setNestState((cur) => updateNestAnchor(cur, c.id, c.position))
        } else if ((n?.data as { expandedFromCairn?: string } | undefined)?.expandedFromCairn) {
          memberMoves.push(c)
        } else {
          otherMoves.push(c)
        }
      }
      if (memberMoves.length > 0) {
        setMemberDragPositions((prev) => {
          const next = { ...prev }
          for (const c of memberMoves) next[c.id] = { ...c.position }
          return next
        })
      }
      if (otherMoves.length > 0) {
        setPositionOverrides((prev) => {
          const next = { ...prev }
          for (const c of otherMoves) next[c.id] = { ...c.position }
          return next
        })
      }
      schedulePersistLayout()
    },
    [nodes, setNodes, schedulePersistLayout],
  )

  const nestSelectedGroup = useCallback(() => {
    if (!baseGraph || !selectedNodeId) return
    const rootNode = baseGraph.nodes.find((n) => n.id === selectedNodeId)
    if (!rootNode || !canNestNode(rootNode)) return
    if (getNestGroupForRoot(rootNode.id, nestState)) return
    const nodesWithPos = baseGraph.nodes.map((n) => ({
      ...n,
      position: positionOverrides[n.id] ? { ...positionOverrides[n.id]! } : n.position,
    }))
    const group = createNestGroup(
      rootNode.id,
      nodesWithPos as Node<MapNodePayload>[],
      baseGraph.edges,
      entityBundle,
    )
    if (!group) return
    setNestState((prev) => withAddedNestGroup(dissolveNestsMergedIntoAncestor(prev, group), group))
    if (selectedNodeId && group.memberNodeIds.includes(selectedNodeId)) {
      setSelectedNodeId(group.rootNodeId)
      setSelectedPayload(rootNode.data)
    }
    schedulePersistLayout()
  }, [baseGraph, selectedNodeId, nestState, positionOverrides, entityBundle, schedulePersistLayout])

  const expandSelectedGroup = useCallback(() => {
    if (!baseGraph || !selectedNodeId) return
    const g = getNestGroupForRoot(selectedNodeId, nestState)
    if (!g) return
    const expandedRel = expandRelativePositions(g.relativePositions, g.relativeDepths, {
      baseScale: 1.06,
      depthStep: 0.07,
      maxScale: 1.34,
      floorRadius: 34,
      kindById: g.memberKinds,
    })
    const restored: Record<string, XYPosition> = {}
    for (const id of g.memberNodeIds) {
      const rel = expandedRel[id]
      if (!rel) continue
      restored[id] = {
        x: g.anchorPosition.x + rel.x,
        y: g.anchorPosition.y + rel.y,
      }
    }
    const allNodesWithPos = baseGraph.nodes.map((n) => ({
      ...n,
      position: restored[n.id] ?? positionOverrides[n.id] ?? n.position,
    }))
    const mergedPos: Record<string, XYPosition> = {}
    for (const n of allNodesWithPos) mergedPos[n.id] = n.position
    const repulsed = applyLocalRepulsion(
      g.memberNodeIds,
      allNodesWithPos as Node<MapNodePayload>[],
      mergedPos,
      { padding: 180, maxPush: 190, passCount: 2 },
    )
    setPositionOverrides((prev) => ({ ...prev, ...restored, ...repulsed }))
    setNestState((prev) => withRemovedNestGroup(prev, selectedNodeId))
    schedulePersistLayout()
  }, [baseGraph, selectedNodeId, nestState, positionOverrides, schedulePersistLayout])

  const canNestSelected = (() => {
    if (!selectedNodeId || !baseGraph) return false
    const root = baseGraph.nodes.find((n) => n.id === selectedNodeId)
    if (!root || !canNestNode(root)) return false
    return !getNestGroupForRoot(root.id, nestState)
  })()

  const canExpandSelected = (() => {
    if (!selectedNodeId) return false
    return Boolean(getNestGroupForRoot(selectedNodeId, nestState))
  })()

  const selectedNest = selectedNodeId ? getNestGroupForRoot(selectedNodeId, nestState) : null
  /** Must be memoized — a fresh object every render was invalidating `developmentalSnapshotForPrompt` and re-firing parent/shell effects. */
  const selectedNestTriad = useMemo(() => {
    if (!selectedNest || !baseGraph) return null
    const members = baseGraph.nodes.filter((n) => selectedNest.memberNodeIds.includes(n.id))
    return computeNestGrowthTriad(selectedNest, members, entityBundle)
  }, [selectedNest, baseGraph, entityBundle])

  const developmentalSnapshotForPrompt = useMemo((): MapTriadDevelopmentalSnapshot | null => {
    if (!selectedNodeId || !selectedPayload) return null
    const triad = selectedNestTriad ?? mapVisualTriad(selectedPayload, entityBundle)
    const missing_dimensions = detectMissingDimensions(triad)
    let node_interpretation = null as MapTriadDevelopmentalSnapshot['node_interpretation']
    if (!selectedNestTriad) {
      node_interpretation = assessNodeFlowAndChannels(selectedPayload, {
        bundle: entityBundle,
        councilRuns: [],
      }).interpretation
    }
    return {
      node_id: selectedNodeId,
      is_nest_aggregate: Boolean(selectedNestTriad),
      node_kind: selectedNestTriad ? 'nest' : selectedPayload.kind,
      triad,
      missing_dimensions,
      node_label: selectedPayload.label?.trim() || null,
      triad_scope: 'vision_map',
      node_interpretation,
    }
  }, [selectedNodeId, selectedPayload, entityBundle, selectedNestTriad])

  const lastDevSnapshotJsonRef = useRef<string | null>(null)
  useEffect(() => {
    const cb = onDevelopmentalSignalsChange
    if (!cb) return
    const json =
      developmentalSnapshotForPrompt == null ? '\0null' : JSON.stringify(developmentalSnapshotForPrompt)
    if (lastDevSnapshotJsonRef.current === json) return
    lastDevSnapshotJsonRef.current = json
    cb(developmentalSnapshotForPrompt)
  }, [onDevelopmentalSignalsChange, developmentalSnapshotForPrompt])

  const nodeCount = displayGraph.nodes.length
  const hasContextSelection = Boolean(selectedPayload)
  const sceneHeightPx = useMemo(() => {
    if (nodes.length === 0) return SCENE_BASE_HEIGHT_PX
    let minY = Number.POSITIVE_INFINITY
    let maxY = Number.NEGATIVE_INFINITY
    for (const n of nodes) {
      const y = n.position.y
      const h =
        n.measured?.height ??
        (n.type === 'nestGroup'
          ? NEST_NODE_LAYOUT_HEIGHT_PX
          : n.type === 'entityMap'
            ? mapEntityNodeLayoutPx((n.data as MapNodePayload).kind).height
            : MAP_ENTITY_FALLBACK_LAYOUT_PX.height)
      minY = Math.min(minY, y)
      maxY = Math.max(maxY, y + h)
    }
    if (!Number.isFinite(minY) || !Number.isFinite(maxY)) return SCENE_BASE_HEIGHT_PX
    return Math.max(SCENE_BASE_HEIGHT_PX, Math.ceil(maxY - minY + SCENE_CONTENT_PADDING_PX))
  }, [nodes])

  const handleResetStoneLayout = useCallback(() => {
    clearVisionMapLayout(layoutStorageKey)
    viewportRestoreRef.current = null
    if (persistDebounceRef.current) {
      window.clearTimeout(persistDebounceRef.current)
      persistDebounceRef.current = null
    }
    setPositionOverrides({})
    setNestState(EMPTY_NEST_STATE)
    const bg = baseGraphRef.current
    if (!bg?.nodes.length) {
      setMapViewportReady(true)
      try {
        void rf.setViewport({ x: 0, y: 0, zoom: 1 }, { duration: 0 })
      } catch {
        /* ignore */
      }
      setZoomLevel(1)
      return
    }
    setMapViewportReady(false)
    window.setTimeout(() => {
      const pick = bg.nodes[Math.floor(Math.random() * bg.nodes.length)]!
      const lw =
        pick.type === 'entityMap'
          ? mapEntityNodeLayoutPx(pick.data.kind).width
          : pick.type === 'nestGroup'
            ? NEST_NODE_LAYOUT_WIDTH_PX
            : DEFAULT_ENTITY_W
      const lh =
        pick.type === 'entityMap'
          ? mapEntityNodeLayoutPx(pick.data.kind).height
          : pick.type === 'nestGroup'
            ? NEST_NODE_LAYOUT_HEIGHT_PX
            : DEFAULT_ENTITY_H
      const cx = pick.position.x + lw / 2
      const cy = pick.position.y + lh / 2
      void rf.setCenter(cx, cy, { zoom: INITIAL_MAP_ZOOM, duration: 0 }).then(() => {
        setMapViewportReady(true)
        setZoomLevel(INITIAL_MAP_ZOOM)
      })
    }, 0)
  }, [layoutStorageKey, rf])

  const mapHelpTitle =
    'Live VE projection · stone wash = project hue · glyph = growth (seed/sprout/sapling/bloom/fruit) · amber ring = needs attention · green ring = recent update · cairns stack a project\u2019s stones \u2014 long-press to fan out · drag stones · pan: empty map / Space / right-drag / two-finger trackpad'

  return (
    <CairnInteractionContext.Provider value={cairnInteractionValue}>
    <div className="flex flex-1 min-h-0 flex-col bg-stone-900">
      <header className="flex items-start justify-between gap-3 px-4 py-2 border-b border-stone-700 bg-stone-900/85 shrink-0 flex-wrap">
        <div className="min-w-0 flex-1">
          <h1 className="text-lg font-semibold text-stone-100" title={mapHelpTitle}>
            Vision map
          </h1>
          {loadState === 'ok' && cairnMeta.cairned ? (
            <p className="text-[10px] leading-snug text-stone-400" title={mapHelpTitle}>
              {cairnMeta.cairnCount} cairns · {cairnMeta.totalStones} stones — long-press a cairn to fan it out
              {onOpenOperatorMode ? (
                <>
                  {' '}·{' '}
                  <button
                    type="button"
                    onClick={onOpenOperatorMode}
                    className="underline underline-offset-2 hover:text-stone-200"
                  >
                    full set in Vision tables
                  </button>
                </>
              ) : null}
            </p>
          ) : (
            <p className="text-[10px] text-stone-500 truncate" title={mapHelpTitle}>
              {loadState === 'ok' ? `${nodeCount} nodes` : loadState} · hover title for map legend
            </p>
          )}
          {onOpenVeRadar ? (
            <div className="mt-1.5 max-w-full">
              <VeRadarAwarenessStrip
                onOpenVeRadar={onOpenVeRadar}
                refreshNonce={radarStripRefreshNonce}
              />
            </div>
          ) : null}
        </div>
        <div className="flex items-center gap-2 shrink-0 flex-wrap pt-0.5">
          <button
            type="button"
            onClick={() => void load()}
            disabled={loadState === 'loading'}
            className="px-3 py-1.5 rounded-lg text-xs font-medium bg-stone-800 border border-stone-600 hover:bg-stone-700 disabled:opacity-50 text-stone-100"
          >
            Refresh data
          </button>
          <button
            type="button"
            onClick={handleResetStoneLayout}
            disabled={loadState !== 'ok' || nodeCount === 0}
            title="Clear saved stone positions and viewport; use auto-layout positions again"
            className="px-3 py-1.5 rounded-lg text-xs font-medium border border-stone-600 text-stone-300 hover:bg-stone-800 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Reset layout
          </button>
          <button
            type="button"
            onClick={onOpenOperatorMode}
            className="px-4 py-2 rounded-lg bg-stone-700 hover:bg-stone-600 text-sm font-medium text-stone-100 border border-stone-500"
          >
            Operator mode (tables)
          </button>
        </div>
      </header>

      <div className="flex flex-1 min-h-0">
        <VisionMapMapWorld
          sandRef={sandRef}
          reduceMotion={reduceMotion}
          rakeEnabled={rakeEnabled}
          setRakeEnabled={setRakeEnabled}
          rakeFadeSec={rakeFadeSec}
          setRakeFadeSec={setRakeFadeSec}
          loadState={loadState}
          loadErr={loadErr}
          onRetryLoad={() => void load()}
          baseGraph={baseGraph}
          nodeCount={nodeCount}
          mapViewportReady={mapViewportReady}
          selectedNodeId={selectedNodeId}
          sceneHeightPx={sceneHeightPx}
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={onNodeClick}
          onPaneClick={onPaneClick}
          onViewportChange={onViewportChange}
          onMoveEnd={schedulePersistLayout}
          zoomLevel={zoomLevel}
          onOpenOperatorMode={onOpenOperatorMode}
        />
        {hasContextSelection ? (
          <MapChatShell
            selected={selectedPayload}
            entityBundle={entityBundle}
            onClearSelection={clearSelection}
            canNestSelected={canNestSelected}
            canExpandSelected={canExpandSelected}
            onNestSelected={nestSelectedGroup}
            onExpandSelected={expandSelectedGroup}
          />
        ) : null}
      </div>
    </div>
    </CairnInteractionContext.Provider>
  )
}

export function VisionMapView(props: VisionMapViewProps) {
  return (
    <ReactFlowProvider>
      <VisionMapFlow {...props} />
    </ReactFlowProvider>
  )
}
