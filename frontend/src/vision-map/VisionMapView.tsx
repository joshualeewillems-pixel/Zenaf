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
  getViewportForBounds,
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
import { NestGroupNode, NEST_NODE_LAYOUT_HEIGHT_PX } from './NestGroupNode'
import {
  CAIRN_NARROW_THRESHOLD,
  CAIRN_WIDE_THRESHOLD,
  MAP_DOUBLE_TAP_MS,
  applyDragPositions,
  applyGardenStack,
  branchAnchorForCairn,
  doubleTapTargetFor,
  dropDragPositions,
  expandCairn,
  isGardenStackData,
  subtreeCairnIds,
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
import { populatedBounds } from './mapFitView'
import { touchGestureGate, useActiveTouchPointerCount } from './touchGestureGate'
import {
  EMPTY_NEST_STATE,
  applyNestTransform,
  computeNestGrowthTriad,
  getNestGroupForRoot,
  updateNestAnchor,
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
/**
 * Open view (2026-11-12): the map opens fitted on the whole garden — every
 * cairn visible, consolidated — instead of centered on a random node at
 * zoom 1. The fit never blows a small garden up past FIT_VIEW_MAX_ZOOM.
 * The open is ALWAYS the computed garden: no saved layout is restored
 * (an earlier build saved dragged positions + viewport to localStorage
 * and restored them verbatim, which scattered the garden on load — the
 * founder's own session drags came back as someone else's map). Dragging
 * still works within a session; nothing persists across loads.
 */
const FIT_VIEW_PADDING = 0.15
const FIT_VIEW_MAX_ZOOM = 0.9
const MAP_MIN_ZOOM = 0.15
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
  zoomLevel: number
  onOpenOperatorMode: () => void
  /** True while a hold-armed node drag is tracking a touch pointer — the rake must not stamp. */
  rakeSuspended: boolean
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
  zoomLevel,
  onOpenOperatorMode,
  rakeSuspended,
}: VisionMapMapWorldProps) {
  const rf = useReactFlow()
  const wrapRef = useRef<HTMLDivElement>(null)
  /* Founder touch gesture contract (2026-11-12, revised 2026-11-13):
     count live touch pointers on the pane and gate React Flow from it —
     with exactly one finger down the finger only rakes (no pan, no
     native node drag); with two or more, the fingers pan + pinch and
     the rake suspends itself. A held finger arms drag for its stone —
     the view tracks that drag itself (see the hold ladder in
     VisionMapFlow), so React Flow's native drag stays off under touch. */
  const touchCount = useActiveTouchPointerCount(wrapRef)
  const gate = touchGestureGate(touchCount)

  /* Object-aware fit: frame what is actually populated — the rendered
     entities only, never nest-group scaffolding — capped at the same
     max zoom as the programmatic fits. Replaces the stock Controls
     fitView, which enclosed every node (containers included) with no
     zoom cap and could zoom out to no man's land. */
  const onFitPopulated = useCallback(() => {
    const bounds = populatedBounds(nodes)
    const el = wrapRef.current
    if (!bounds || !el) return
    const rect = el.getBoundingClientRect()
    if (rect.width <= 0 || rect.height <= 0) return
    const viewport = getViewportForBounds(
      bounds,
      rect.width,
      rect.height,
      MAP_MIN_ZOOM,
      FIT_VIEW_MAX_ZOOM,
      FIT_VIEW_PADDING,
    )
    void rf.setViewport(viewport, { duration: 0 }).then(() => {
      onViewportChange({ zoom: viewport.zoom })
    })
  }, [nodes, rf, onViewportChange])

  return (
    <div
      ref={wrapRef}
      className={`map-world-wrap flex flex-col flex-1 min-w-0 min-h-[480px] relative overflow-hidden ${selectedNodeId ? 'map-focus-active' : ''}`}
      style={{ height: `${sceneHeightPx}px` }}
    >
      <ZenSandCanvas
        ref={sandRef as Ref<ZenSandCanvasHandle>}
        reducedMotion={reduceMotion}
        className={MAP_SAND_LAYER_CLASS}
        rakeEnabled={rakeEnabled}
        rakeSuspended={rakeSuspended}
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
        nodesDraggable={gate.nodesDraggable}
        nodesConnectable={false}
        nodeDragThreshold={10}
        selectNodesOnDrag={false}
        panOnDrag={gate.panOnDrag}
        panOnScroll={true}
        panActivationKeyCode="Space"
        zoomActivationKeyCode="Control"
        selectionKeyCode="Shift"
        elementsSelectable
        fitView={false}
        fitViewOptions={{ padding: FIT_VIEW_PADDING }}
        minZoom={MAP_MIN_ZOOM}
        maxZoom={1.6}
        zoomOnScroll={true}
        zoomOnPinch={true}
        zoomOnDoubleClick={false}
        proOptions={{ hideAttribution: true }}
        debug={false}
        colorMode="dark"
        className={`map-graph-canvas !bg-transparent flex-1 min-h-0 h-full w-full transition-opacity duration-200 ${
          loadState === 'ok' && nodeCount > 0 && !mapViewportReady ? 'opacity-0' : 'opacity-100'
        }`}
        style={{ background: 'transparent' }}
        onMove={(_, viewport) => onViewportChange(viewport)}
      >
        <Controls showInteractive={false} showFitView={false} position="top-left">
          <button
            type="button"
            className="react-flow__controls-button react-flow__controls-fitview"
            onClick={onFitPopulated}
            title="Fit the populated garden"
            aria-label="Fit the populated garden"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 30" aria-hidden>
              <path d="M3.692 4.63c0-.53.4-.938.939-.938h5.215V0H4.708C2.13 0 0 2.054 0 4.63v5.216h3.692V4.631zM27.354 0h-5.2v3.692h5.17c.53 0 .984.4.984.939v5.215H32V4.631A4.624 4.624 0 0027.354 0zm.954 24.83c0 .532-.4.94-.939.94h-5.215v3.768h5.215c2.577 0 4.631-2.13 4.631-4.707v-5.139h-3.692v5.139zm-23.677.94c-.531 0-.939-.4-.939-.94v-5.138H0v5.139c0 2.577 2.13 4.707 4.708 4.707h5.138V25.77H4.631z" />
            </svg>
          </button>
        </Controls>
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
}: VisionMapViewProps) {
  const sandRef = useRef<ZenSandCanvasHandle>(null)
  const loadGenerationRef = useRef(0)
  const baseGraphRef = useRef<{ nodes: Node<MapNodePayload>[]; edges: Edge[] } | null>(null)
  const loadStateRef = useRef<'idle' | 'loading' | 'ok' | 'error'>('idle')
  const [reduceMotion, setReduceMotion] = useState(false)
  const [rakeEnabled, setRakeEnabled] = useState(true)
  const [rakeFadeSec, setRakeFadeSec] = useState<12 | 16 | 20>(16)
  const rf = useReactFlow()
  const [baseGraph, setBaseGraph] = useState<{ nodes: Node<MapNodePayload>[]; edges: Edge[] } | null>(null)
  const [entityBundle, setEntityBundle] = useState<VisionMapEntityBundle | null>(null)
  /** Cairn mode: honest counts for the notice; the index + anchors live in refs (not render state). */
  const [cairnMeta, setCairnMeta] = useState({ totalStones: 0, cairnCount: 0, cairned: false })
  const [expandedCairns, setExpandedCairns] = useState<ReadonlySet<string>>(new Set())
  /** Per-initiative stacking: stacked tree ids. Each stacked initiative
      becomes its garden stack; its descendant cairns hide beneath the pile. */
  const [stackedInitiatives, setStackedInitiatives] = useState<ReadonlySet<string>>(new Set())
  const cairnIndexRef = useRef<CairnIndex>({})
  const cairnAnchorRef = useRef<Record<string, XYPosition>>({})

  /**
   * Hold ladder, tier 1 (founder gesture revision, 2026-11-13): when a
   * still touch hold arms drag for a node, the view — not React Flow —
   * tracks the drag. React Flow's native drag can't be used: it binds
   * at pointerdown, when the touch gate (correctly) has drag off, and
   * flipping it on mid-press starts nothing. So the node reports the
   * arm through the cairn context, and window listeners below translate
   * the pointer's movement into the very same position changes a native
   * drag emits — session position recording, member-drag bookkeeping
   * and all — via `onNodesChange`.
   */
  const armedDragRef = useRef<{
    nodeId: string
    pointerId: number
    startClient: XYPosition
    startFlow: XYPosition
    nodeStart: XYPosition
    lastPos: XYPosition
    moved: boolean
  } | null>(null)
  /** True while an armed drag is tracking — suspends the rake (state, not just a ref, because the sand canvas is a child). */
  const [dragArmedActive, setDragArmedActive] = useState(false)
  /**
   * A spent press's release still produces a click: tier 2 fired, or an
   * armed drag just ended. That click is swallowed once so the gesture
   * doesn't end by selecting whatever it lands on. The next pointerdown
   * expires the flag — the guarded click has either happened or won't.
   */
  const swallowNextClickRef = useRef(false)
  /** Last node tap, for double-tap detection over the ordinary click stream (no click delay is introduced). */
  const lastNodeTapRef = useRef<{ nodeId: string; at: number } | null>(null)
  const nodesRef = useRef<Node<MapNodePayload | NestGroupNodeData>[]>([])
  const onNodesChangeRef = useRef<(changes: NodeChange[]) => void>(() => {})

  /** End the armed drag, if any. `commit` records the final position (and swallows the release click) — the stone stays where it was dragged. */
  const endArmedDrag = useCallback((commit: boolean) => {
    const drag = armedDragRef.current
    if (!drag) return
    armedDragRef.current = null
    setDragArmedActive(false)
    if (!drag.moved) return
    if (commit) {
      onNodesChangeRef.current([
        { type: 'position', id: drag.nodeId, position: drag.lastPos, dragging: false },
      ])
      swallowNextClickRef.current = true
    }
  }, [])

  /** Hold ladder tier 1: a node reports its drag is armed — start tracking its pointer. */
  const onDragArm = useCallback(
    (nodeId: string, pointerId: number, clientX: number, clientY: number) => {
      const node = nodesRef.current.find((n) => n.id === nodeId)
      if (!node) return
      armedDragRef.current = {
        nodeId,
        pointerId,
        startClient: { x: clientX, y: clientY },
        startFlow: rf.screenToFlowPosition({ x: clientX, y: clientY }),
        nodeStart: { ...node.position },
        lastPos: { ...node.position },
        moved: false,
      }
      setDragArmedActive(true)
    },
    [rf],
  )

  /** Hold ladder tier 2 fired on a node: that press is spent. */
  const onPressSpent = useCallback(() => {
    swallowNextClickRef.current = true
  }, [])

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
  /** Overflow menu for the slim chrome header (Refresh data / Reset layout / tables). */
  const [chromeMenuOpen, setChromeMenuOpen] = useState(false)

  const [nodes, setNodes] = useNodesState<Node<MapNodePayload | NestGroupNodeData>>([])
  nodesRef.current = nodes
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

  useEffect(() => {
    baseGraphRef.current = baseGraph
  }, [baseGraph])

  useEffect(() => {
    loadStateRef.current = loadState
  }, [loadState])

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
      /* No saved layout is restored: the map always opens on the computed
         garden. (The old localStorage restore applied a previous session's
         dragged positions verbatim and scattered the open — founder,
         2026-11-12.) Position overrides live only within the session. */
      setEntityBundle(entities)
      cairnIndexRef.current = g.cairnIndex
      cairnAnchorRef.current = {}
      setCairnMeta({ totalStones: g.totalStones, cairnCount: g.cairnCount, cairned: g.cairned })
      setExpandedCairns(new Set())
      setStackedInitiatives(new Set())
      setBaseGraph({ nodes: g.nodes, edges: g.edges })
      setNestState(EMPTY_NEST_STATE)
      setPositionOverrides({})
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
      setStackedInitiatives(new Set())
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  /**
   * Cairn expansion layer. Expanded cairns swap for their member stones,
   * fanned out around the cairn's current position (relative offsets from
   * the original layout are preserved). Members carry `expandedFromCairn`
   * so the view can tell a fanned member from a free stone: a double-tap
   * on a member opens that stone's data, a longer hold stacks the cairn
   * back, and the stone sheet offers the same collapse.
   *
   * Per-initiative stacking runs first: each stacked tree's node becomes
   * its garden stack — the pile sitting on the parent stone as one object
   * — while its descendant cairns hide beneath it. Cairns hidden this way
   * are skipped by the expansion layer — the expanded set is left alone
   * so unstacking restores the prior arrangement.
   */
  const displayGraph = useMemo(() => {
    const empty = new Set<string>()
    if (!baseGraph) return { nodes: [] as Node<MapNodePayload>[], edges: [] as Edge[], expandedMemberIds: empty }
    const stacked = applyGardenStack(baseGraph.nodes, baseGraph.edges, stackedInitiatives)
    if (expandedCairns.size === 0) {
      return { nodes: stacked.nodes, edges: stacked.edges, expandedMemberIds: empty }
    }
    let nodes = [...stacked.nodes]
    let edges = [...stacked.edges]
    const expandedMemberIds = new Set<string>()
    for (const cid of expandedCairns) {
      if (stacked.hiddenCairnIds.has(cid)) continue
      const entry = cairnIndexRef.current[cid]
      if (!entry) continue
      const anchor = cairnAnchorRef.current[cid] ?? entry.cairnNode.position
      const ex = expandCairn(nodes, edges, entry, anchor)
      nodes = ex.nodes
      edges = ex.edges
      for (const m of entry.memberNodes) expandedMemberIds.add(m.id)
    }
    return { nodes, edges, expandedMemberIds }
  }, [baseGraph, expandedCairns, stackedInitiatives])

  const toggleCairn = useCallback(
    (cairnId: string) => {
      // A tier-2 hold can reach here with the press's drag barely armed
      // (a few px of jitter inside the ladder's slop): commit the drag
      // where it stands first — the toggle spends the press either way.
      endArmedDrag(true)
      // A garden stack toggles through this same path — consistent with
      // the cairn grammar (the toggle fans a cairn out; the stack's
      // "members" are that initiative's cairns). The stack IS the parent
      // stone (same id), so the id that arrives here is the tree's own.
      const toggledNode = nodes.find((n) => n.id === cairnId)
      if (toggledNode && isGardenStackData(toggledNode.data)) {
        setStackedInitiatives((prev) => {
          if (!prev.has(cairnId)) return prev
          const next = new Set(prev)
          next.delete(cairnId)
          return next
        })
        return
      }
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
    [nodes, expandedCairns, endArmedDrag],
  )

  /**
   * Per-initiative stack toggle. The longer hold (or a double-tap on the
   * pile) toggles: that initiative's descendant cairns hide under the
   * pile on its own stone (positions preserved in state); toggle again
   * to restore. Other initiatives render fully normally.
   */
  const toggleGardenStack = useCallback(
    (treeId: string) => {
      endArmedDrag(true)
      setStackedInitiatives((prev) => {
        const next = new Set(prev)
        if (next.has(treeId)) next.delete(treeId)
        else next.add(treeId)
        return next
      })
    },
    [endArmedDrag],
  )

  /**
   * Open a stone's data — the exact selection a tap produces
   * (MapChatShell payload included). The double-tap routes here: a hold
   * no longer opens data (it arms drag, then toggles), and collapsing a
   * fanned cairn is the sheet's "Stack back into cairn" action or the
   * longer hold on one of its members.
   */
  const onOpenStoneData = useCallback(
    (nodeId: string) => {
      const node = nodes.find((n) => n.id === nodeId)
      if (!node || node.type === 'nestGroup') return
      setSelectedNodeId(node.id)
      setSelectedPayload((node.data as MapNodePayload) ?? null)
    },
    [nodes],
  )

  const cairnInteractionValue = useMemo(
    () => ({
      onToggleCairn: toggleCairn,
      onToggleGardenStack: toggleGardenStack,
      onOpenStoneData,
      onDragArm,
      onPressSpent,
    }),
    [toggleCairn, toggleGardenStack, onOpenStoneData, onDragArm, onPressSpent],
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
  ])

  useEffect(() => {
    if (!guidancePulseNodeId) return
    const timer = window.setTimeout(() => setGuidancePulseNodeId(null), 2200)
    return () => window.clearTimeout(timer)
  }, [guidancePulseNodeId])

  /**
   * On each new `baseGraph` (load / refresh): open fitted on the whole
   * garden — every cairn visible, consolidated — instead of centered on
   * a random node at zoom 1. Nothing saved is ever restored over this
   * fit. Nesting does not change `baseGraph`, so this does not run again.
   */
  useEffect(() => {
    if (!baseGraph || baseGraph.nodes.length === 0) {
      setMapViewportReady(true)
      return
    }
    setMapViewportReady(false)
    let cancelled = false
    const started = performance.now()

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
      void rf
        .fitView({ padding: FIT_VIEW_PADDING, maxZoom: FIT_VIEW_MAX_ZOOM, duration: 0 })
        .then(() => {
          if (cancelled) return
          setZoomLevel(rf.getViewport().zoom)
          setMapViewportReady(true)
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

  const onNodeClick = useCallback(
    (_: MouseEvent, node: Node<MapNodePayload | NestGroupNodeData>) => {
      // A spent press (tier-2 hold, or an armed drag) ends in a click
      // that means nothing — swallow it and reset the tap tracker.
      if (swallowNextClickRef.current) {
        swallowNextClickRef.current = false
        lastNodeTapRef.current = null
        return
      }
      // Double-tap = open (founder revision, 2026-11-13). Detection
      // rides the ordinary click stream — no tap is ever delayed: the
      // first tap selects as always, the second upgrades to the open
      // action for that node kind.
      const now = performance.now()
      const last = lastNodeTapRef.current
      if (last && last.nodeId === node.id && now - last.at <= MAP_DOUBLE_TAP_MS) {
        lastNodeTapRef.current = null
        const target = doubleTapTargetFor(node.id, node.type, node.data)
        if (target.action === 'fanOutCairn' || target.action === 'unstackGardenStack') {
          toggleCairn(target.action === 'fanOutCairn' ? target.cairnId : target.treeId)
          // The first tap selected the pile and opened its sheet; the
          // fan-out/unstack wins — close the sheet so it doesn't fight.
          setSelectedNodeId(null)
          setSelectedPayload(null)
          return
        }
        if (target.action === 'openStoneData') {
          onOpenStoneData(target.nodeId)
          return
        }
        // 'none' (nest groups): fall through to the ordinary click.
      } else {
        lastNodeTapRef.current = { nodeId: node.id, at: now }
      }
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
    },
    [baseGraph, toggleCairn, onOpenStoneData],
  )

  const onPaneClick = useCallback(() => {
    if (swallowNextClickRef.current) {
      swallowNextClickRef.current = false
      return
    }
    lastNodeTapRef.current = null
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
      // the session position overrides. Nothing is persisted across loads.
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
    },
    [nodes, setNodes],
  )
  onNodesChangeRef.current = onNodesChange

  /**
   * Armed-drag pointer tracking (hold ladder tier 1). Capture-phase
   * window listeners, pointer-id matched: moves translate the pointer's
   * flow-space delta into position changes on the armed node; release
   * or cancel commits the drag where it stands. A second pointer
   * landing mid-drag ends it the same way — the gesture hands over to
   * two-finger navigation. Any fresh pointerdown also expires the
   * spent-press click swallow (see swallowNextClickRef).
   */
  useEffect(() => {
    const onPointerMove = (e: PointerEvent) => {
      const drag = armedDragRef.current
      if (!drag || e.pointerId !== drag.pointerId) return
      if (
        !drag.moved &&
        Math.hypot(e.clientX - drag.startClient.x, e.clientY - drag.startClient.y) < 2
      ) {
        return
      }
      drag.moved = true
      const flow = rf.screenToFlowPosition({ x: e.clientX, y: e.clientY })
      const pos = {
        x: drag.nodeStart.x + (flow.x - drag.startFlow.x),
        y: drag.nodeStart.y + (flow.y - drag.startFlow.y),
      }
      drag.lastPos = pos
      onNodesChangeRef.current([
        { type: 'position', id: drag.nodeId, position: pos, dragging: true },
      ])
    }
    const onPointerUpOrCancel = (e: PointerEvent) => {
      if (armedDragRef.current?.pointerId === e.pointerId) endArmedDrag(true)
    }
    const onPointerDown = (e: PointerEvent) => {
      swallowNextClickRef.current = false
      if (armedDragRef.current && e.pointerId !== armedDragRef.current.pointerId) {
        endArmedDrag(true)
      }
    }
    window.addEventListener('pointermove', onPointerMove, true)
    window.addEventListener('pointerup', onPointerUpOrCancel, true)
    window.addEventListener('pointercancel', onPointerUpOrCancel, true)
    window.addEventListener('pointerdown', onPointerDown, true)
    return () => {
      window.removeEventListener('pointermove', onPointerMove, true)
      window.removeEventListener('pointerup', onPointerUpOrCancel, true)
      window.removeEventListener('pointercancel', onPointerUpOrCancel, true)
      window.removeEventListener('pointerdown', onPointerDown, true)
    }
  }, [rf, endArmedDrag])

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
  }, [baseGraph, selectedNodeId, nestState, positionOverrides])

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
  /** When the selected stone is a member of a fanned-out cairn, the sheet
      offers the collapse path ("Stack back into cairn") — the same
      action as the longer hold on a member; opening the member's data
      is a tap / double-tap, and neither stacks the cairn. */
  const selectedCairnId =
    (selectedPayload as { expandedFromCairn?: string } | null)?.expandedFromCairn ?? null
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
      // Reset opens fitted on the whole garden, like a fresh open —
      // not centered on a random stone.
      void rf
        .fitView({ padding: FIT_VIEW_PADDING, maxZoom: FIT_VIEW_MAX_ZOOM, duration: 0 })
        .then(() => {
          setMapViewportReady(true)
          setZoomLevel(rf.getViewport().zoom)
        })
        .catch(() => {
          setMapViewportReady(true)
        })
    }, 0)
  }, [rf])

  const mapHelpTitle =
    'Live VE projection · stone wash = project hue · glyph = growth (seed/sprout/sapling/bloom/fruit) · amber ring = needs attention · green ring = recent update · cairns stack a project’s stones · touch: one finger rakes the sand · hold a stone to drag it · hold longer to fan out / stack back · double-tap a cairn to fan out, a stone to open it · two fingers pan & pinch · mouse: drag stones, hold to toggle · pan: empty map / Space / right-drag / two-finger trackpad'

  /**
   * Honest notice counts for per-initiative stacking: how many piles are
   * actually standing, and how many cairns they hide. Derived from the base
   * graph (not render state) so it stays truthful across reloads.
   */
  const stackSummary = useMemo(() => {
    if (stackedInitiatives.size === 0 || !baseGraph) return null
    let piles = 0
    let hiddenCairns = 0
    for (const treeId of stackedInitiatives) {
      const ids = subtreeCairnIds(treeId, baseGraph.nodes, baseGraph.edges)
      if (ids.length === 0) continue
      piles += 1
      hiddenCairns += ids.length
    }
    return piles === 0 ? null : { piles, hiddenCairns }
  }, [stackedInitiatives, baseGraph])

  return (
    <CairnInteractionContext.Provider value={cairnInteractionValue}>
    <div id="vision-map-top" className="flex flex-1 min-h-0 flex-col bg-stone-900">
      <header
        data-testid="vision-map-chrome"
        className="shrink-0 border-b border-stone-700 bg-stone-900/85"
      >
        <div className="flex items-center gap-1 px-3 min-h-[44px]">
          <h1
            className="min-w-0 flex-1 truncate text-sm font-semibold text-stone-100"
            title={mapHelpTitle}
          >
            Vision map
            <span className="ml-2 text-[10px] font-normal text-stone-400">
              {loadState === 'ok'
                ? stackSummary
                  ? `${stackSummary.piles} stacked · ${cairnMeta.cairnCount - stackSummary.hiddenCairns} cairns · ${cairnMeta.totalStones} stones — double-tap a pile to unstack`
                  : cairnMeta.cairned
                    ? `${cairnMeta.cairnCount} cairns · ${cairnMeta.totalStones} stones`
                    : `${nodeCount} nodes`
                : loadState}
            </span>
          </h1>
          {loadState === 'ok' && cairnMeta.cairned && onOpenOperatorMode ? (
            <button
              type="button"
              onClick={onOpenOperatorMode}
              className="shrink-0 min-h-[44px] px-2 text-[11px] text-stone-400 underline underline-offset-2 hover:text-stone-200"
            >
              tables
            </button>
          ) : null}
          <div className="relative shrink-0">
            <button
              type="button"
              onClick={() => setChromeMenuOpen((v) => !v)}
              aria-expanded={chromeMenuOpen}
              aria-label="Map options"
              className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg text-xl leading-none text-stone-300 hover:bg-stone-800"
            >
              ⋯
            </button>
            {chromeMenuOpen ? (
              <>
                <button
                  type="button"
                  aria-label="Close map options"
                  onClick={() => setChromeMenuOpen(false)}
                  className="fixed inset-0 z-40 cursor-default bg-transparent"
                />
                <div className="absolute right-0 top-full z-50 mt-1 w-52 overflow-hidden rounded-lg border border-stone-600 bg-stone-900 py-1 shadow-xl">
                  <button
                    type="button"
                    onClick={() => {
                      setChromeMenuOpen(false)
                      void load()
                    }}
                    disabled={loadState === 'loading'}
                    className="block min-h-[44px] w-full px-4 py-2 text-left text-sm text-stone-100 hover:bg-stone-800 disabled:opacity-50"
                  >
                    Refresh data
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setChromeMenuOpen(false)
                      handleResetStoneLayout()
                    }}
                    disabled={loadState !== 'ok' || nodeCount === 0}
                    title="Recompute the automatic layout and fit the whole garden"
                    className="block min-h-[44px] w-full px-4 py-2 text-left text-sm text-stone-200 hover:bg-stone-800 disabled:opacity-40"
                  >
                    Reset layout
                  </button>
                  {onOpenOperatorMode ? (
                    <button
                      type="button"
                      onClick={() => {
                        setChromeMenuOpen(false)
                        onOpenOperatorMode()
                      }}
                      className="block min-h-[44px] w-full px-4 py-2 text-left text-sm text-stone-200 hover:bg-stone-800"
                    >
                      Open tables view
                    </button>
                  ) : null}
                </div>
              </>
            ) : null}
          </div>
        </div>
        {onOpenVeRadar ? (
          <div className="max-w-full px-3 pb-1.5">
            <VeRadarAwarenessStrip
              onOpenVeRadar={onOpenVeRadar}
              refreshNonce={radarStripRefreshNonce}
            />
          </div>
        ) : null}
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
          zoomLevel={zoomLevel}
          onOpenOperatorMode={onOpenOperatorMode}
          rakeSuspended={dragArmedActive}
        />
        {hasContextSelection ? (
          <MapChatShell
            selected={selectedPayload}
            entityBundle={entityBundle}
            onClearSelection={clearSelection}
            canExpandSelected={canExpandSelected}
            onExpandSelected={expandSelectedGroup}
            canCollapseCairnSelected={!!selectedCairnId}
            onCollapseCairnSelected={
              selectedCairnId ? () => toggleCairn(selectedCairnId) : undefined
            }
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
