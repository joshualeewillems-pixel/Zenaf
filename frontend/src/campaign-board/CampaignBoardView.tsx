/**
 * Valen's Campaign Board — the production surface.
 *
 * A projection of the user's real Vision Execution work: the overview
 * shows every project as a dotted route whose length is its recorded
 * time span (scale key on the map); clicking a route opens the focus
 * board — declared terrain, two speculative routes over the project's
 * recorded tasks, movable waypoints whose position IS the task's due
 * date, and obstacles classified from the record. The focus board also
 * draws the project's reported circumstances (its linked open signals,
 * standing: reported — never upgraded to confirmed) and the capacity
 * load of the people on the work (the Radar's overcapacity rule).
 * Rivers and Holds are the user's own terrain declarations —
 * provisional, session-local, withdrawable, stored nowhere. Date
 * writes go through the existing VE PATCH endpoints only; routes
 * themselves are provisional arrangements and are stored nowhere.
 *
 * Talk is the existing council conversation, locked onto no one but
 * opened with Valen (champion), carrying the focused project/task as
 * live context on every turn — the same seam the Vision Map's stone
 * sheet uses. No separate chat engine.
 *
 * Governing design: zenaf-valen-campaign-board-brief-2026-11-17.md.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import CouncilChat from '../chat/CouncilChat'
import type { Project, Task } from '../vision-execution/types'
import { fetchBoardEntities, patchProjectDates, patchTaskDueDate, type BoardEntities } from './boardApi'
import {
  buildOverview,
  buildRoutes,
  computePxPerDay,
  createHold,
  createRiverFromSignal,
  createRiverWindow,
  dateAtFraction,
  declareTerrain,
  deriveCapacityPicture,
  deriveObstacles,
  deriveSignalMarkers,
  fullDate,
  moveHold,
  obstacleDomainLabel,
  parseDateMs,
  projectSpan,
  removeHold,
  riverBand,
  setRiverWindow,
  shortDate,
  signalsForProject,
  toLocalDateTimeString,
  withdrawRiver,
  type BoardObstacle,
  type BoardSignal,
  type BoardWaypoint,
  type HoldDeclaration,
  type PersonCapacity,
  type RiverDeclaration,
  type SignalMarker,
  type TerrainFeature,
} from './boardLogic'

const MAP_W = 800
const FOCUS_H = 500
const X0 = 64
const X1 = 736
const MID_Y = 252
const ROUTE_A_Y = 148
const ROUTE_B_Y = 356

const INK = '#2b2118'
const PARCHMENT = '#f1e8d0'
const EMBER = '#a63d2a'
const PROJECT_COLORS = ['#54683f', '#a63d2a', '#33655f', '#175e54', '#a8741a', '#7a4a8c', '#8c5a2e']

type Selection =
  | { kind: 'waypoint'; taskId: string }
  | { kind: 'obstacle'; obstacleId: string }
  | { kind: 'terrain'; feature: TerrainFeature }
  | { kind: 'signal'; signalId: string }
  | { kind: 'river'; riverId: string }
  | { kind: 'hold'; holdId: string }
  | { kind: 'capacity'; personId: string }
  | { kind: 'finish' }
  | { kind: 'start' }
  | null

function xForFraction(f: number): number {
  return X0 + f * (X1 - X0)
}

function fractionForX(x: number): number {
  return Math.min(0.98, Math.max(0.02, (x - X0) / (X1 - X0)))
}

function waypointY(bandY: number, index: number): number {
  return bandY + ((index % 3) - 1) * 12
}

/** Smooth path through points (quadratic midpoints). */
function smoothPath(pts: { x: number; y: number }[]): string {
  if (pts.length < 2) return ''
  let d = `M ${pts[0].x} ${pts[0].y}`
  for (let i = 1; i < pts.length - 1; i++) {
    const mx = (pts[i].x + pts[i + 1].x) / 2
    const my = (pts[i].y + pts[i + 1].y) / 2
    d += ` Q ${pts[i].x} ${pts[i].y} ${mx} ${my}`
  }
  const last = pts[pts.length - 1]
  d += ` L ${last.x} ${last.y}`
  return d
}

function routePoints(
  waypoints: BoardWaypoint[],
  bandY: number,
  dragOverride: { taskId: string; fraction: number } | null,
): { x: number; y: number }[] {
  const pts = [{ x: X0, y: MID_Y }]
  waypoints.forEach((w, i) => {
    const f = dragOverride && dragOverride.taskId === w.task.id ? dragOverride.fraction : w.fraction
    pts.push({ x: xForFraction(f), y: waypointY(bandY, i) })
  })
  pts.push({ x: X1, y: MID_Y })
  return pts
}

export default function CampaignBoardView() {
  const [entities, setEntities] = useState<BoardEntities | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [focusId, setFocusId] = useState<string | null>(null)
  const [selection, setSelection] = useState<Selection>(null)
  const [drag, setDrag] = useState<{ taskId: string; fraction: number; moved: boolean } | null>(null)
  const [writeError, setWriteError] = useState<string | null>(null)
  const [dateInput, setDateInput] = useState<string>('')
  // River/Hold declarations — PROVISIONAL, session-local terrain
  // fixings (founder doctrine: terrain is also fixed by the user's
  // declaration). Held in component state only: no record is written,
  // nothing persists past the session, and every declaration can be
  // withdrawn. The declaration-binding standard is deferred.
  const [rivers, setRivers] = useState<RiverDeclaration[]>([])
  const [holds, setHolds] = useState<HoldDeclaration[]>([])
  const declSeq = useRef(0)
  const svgRef = useRef<SVGSVGElement | null>(null)
  const dragStart = useRef<{ x: number; taskId: string } | null>(null)

  const load = useCallback(async () => {
    try {
      setEntities(await fetchBoardEntities())
      setLoadError(null)
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : 'Could not load your work.')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const nowMs = useMemo(() => Date.now(), [entities])
  const overview = useMemo(
    () => (entities ? buildOverview(entities.projects, entities.tasks, nowMs) : []),
    [entities, nowMs],
  )

  const focus = useMemo(() => {
    if (!entities || !focusId) return null
    const project = entities.projects.find((p) => p.id === focusId)
    if (!project) return null
    const projectTasks = entities.tasks.filter((t) => t.project_id === project.id)
    const span = projectSpan(project, projectTasks, nowMs)
    const projectSignals = signalsForProject(entities.signals, project, projectTasks)
    return {
      project,
      projectTasks,
      span,
      obstacles: deriveObstacles(project, projectTasks, entities.tasks, span, nowMs),
      terrain: declareTerrain(projectTasks),
      routes: buildRoutes(projectTasks, span),
      initiative: entities.initiatives.find((i) => i.id === project.initiative_id) ?? null,
      signalMarkers: deriveSignalMarkers(projectSignals, projectTasks, span),
      capacity: deriveCapacityPicture(
        project,
        entities.projects,
        entities.persons,
        entities.capacityProfiles,
        projectTasks,
      ),
      rivers: rivers.filter((r) => r.projectId === project.id),
      holds: holds.filter((h) => h.projectId === project.id),
    }
  }, [entities, focusId, nowMs, rivers, holds])

  /* --------------------- declarations (provisional) --------------------- */

  const nextDeclId = useCallback((prefix: string) => {
    declSeq.current += 1
    return `${prefix}-${declSeq.current}`
  }, [])

  const declareRiverFromSignal = useCallback(
    (signal: BoardSignal) => {
      if (!focus) return
      const river = createRiverFromSignal(nextDeclId('river'), focus.project.id, signal, focus.span)
      setRivers((prev) => [...prev, river])
      setSelection({ kind: 'river', riverId: river.id })
    },
    [focus, nextDeclId],
  )

  const declareRiverWindow = useCallback(() => {
    if (!focus) return
    const river = createRiverWindow(nextDeclId('river'), focus.project.id, focus.span)
    setRivers((prev) => [...prev, river])
    setSelection({ kind: 'river', riverId: river.id })
  }, [focus, nextDeclId])

  const placeHold = useCallback(() => {
    if (!focus) return
    const hold = createHold(nextDeclId('hold'), focus.project.id)
    setHolds((prev) => [...prev, hold])
    setSelection({ kind: 'hold', holdId: hold.id })
  }, [focus, nextDeclId])

  const applyTask = useCallback((updated: Task) => {
    setEntities((prev) =>
      prev ? { ...prev, tasks: prev.tasks.map((t) => (t.id === updated.id ? updated : t)) } : prev,
    )
  }, [])

  const applyProject = useCallback((updated: Project) => {
    setEntities((prev) =>
      prev
        ? { ...prev, projects: prev.projects.map((p) => (p.id === updated.id ? updated : p)) }
        : prev,
    )
  }, [])

  const commitDueDate = useCallback(
    async (taskId: string, localDateTime: string) => {
      setWriteError(null)
      try {
        applyTask(await patchTaskDueDate(taskId, localDateTime))
      } catch (e) {
        setWriteError(e instanceof Error ? e.message : 'That date could not be saved.')
      }
    },
    [applyTask],
  )

  const commitProjectDate = useCallback(
    async (field: 'start_date' | 'end_date', localDateTime: string) => {
      if (!focus) return
      setWriteError(null)
      try {
        applyProject(await patchProjectDates(focus.project.id, { [field]: localDateTime }))
      } catch (e) {
        setWriteError(e instanceof Error ? e.message : 'That date could not be saved.')
      }
    },
    [applyProject, focus],
  )

  /* ------------------------------ drag ------------------------------ */

  const svgX = useCallback((clientX: number): number => {
    const svg = svgRef.current
    if (!svg) return 0
    const rect = svg.getBoundingClientRect()
    return ((clientX - rect.left) / rect.width) * MAP_W
  }, [])

  const onWaypointPointerDown = (e: React.PointerEvent, w: BoardWaypoint) => {
    if (w.done) return
    ;(e.currentTarget as Element).setPointerCapture(e.pointerId)
    dragStart.current = { x: e.clientX, taskId: w.task.id }
    setDrag({ taskId: w.task.id, fraction: w.fraction, moved: false })
  }

  const onWaypointPointerMove = (e: React.PointerEvent, w: BoardWaypoint) => {
    if (!drag || drag.taskId !== w.task.id) return
    const moved = dragStart.current ? Math.abs(e.clientX - dragStart.current.x) > 4 : true
    setDrag({ taskId: w.task.id, fraction: fractionForX(svgX(e.clientX)), moved: moved || drag.moved })
  }

  const onWaypointPointerUp = (e: React.PointerEvent, w: BoardWaypoint) => {
    if (!drag || drag.taskId !== w.task.id) return
    const wasDrag = drag.moved
    const fraction = drag.fraction
    setDrag(null)
    dragStart.current = null
    if (!focus) return
    if (wasDrag) {
      void commitDueDate(w.task.id, toLocalDateTimeString(dateAtFraction(focus.span, fraction)))
    }
    setDateInput(toLocalDateTimeString(dateAtFraction(focus.span, fraction)))
    setSelection({ kind: 'waypoint', taskId: w.task.id })
  }

  /* --------------------------- chat wiring --------------------------- */

  const selectedTaskId =
    selection?.kind === 'waypoint'
      ? selection.taskId
      : selection?.kind === 'obstacle'
        ? (focus?.obstacles.find((o) => o.id === selection.obstacleId)?.taskId ?? null)
        : selection?.kind === 'terrain'
          ? selection.feature.taskId
          : selection?.kind === 'signal'
            ? // A signal selection grounds the conversation on the record
              // the signal points at (its linked task), through the same
              // entity seam — the circumstance's own wording rides the
              // map popup; the seam carries recorded entities only.
              (focus?.signalMarkers.find((m) => m.signal.id === selection.signalId)?.taskId ?? null)
            : null

  const conversationId = focus ? `campaign-board:project:${focus.project.id}` : 'campaign-board:overview'
  const chatContext: Record<string, unknown> = focus
    ? {
        sheet_type: 'campaign_board',
        entity_type: selectedTaskId ? 'task' : 'project',
        entity_id: selectedTaskId ?? focus.project.id,
      }
    : { sheet_type: 'campaign_board' }

  /* ------------------------------ render ----------------------------- */

  if (loadError) {
    return (
      <div className="flex-1 p-6">
        <p className="text-sm text-red-300">{loadError}</p>
        <button
          type="button"
          onClick={() => void load()}
          className="mt-3 min-h-[44px] px-4 rounded-full bg-amber-600 text-amber-50 text-sm font-semibold"
        >
          Try again
        </button>
      </div>
    )
  }
  if (!entities) {
    return (
      <div className="flex-1 p-6">
        <p className="text-sm text-stone-400">Setting out the board…</p>
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col lg:flex-row min-h-0 overflow-y-auto lg:overflow-hidden">
      <div className="flex-1 min-w-0 lg:overflow-y-auto p-3 lg:p-5 space-y-3">
        {focus ? (
          <FocusBoard
            focus={focus}
            selection={selection}
            setSelection={setSelection}
            drag={drag}
            svgRef={svgRef}
            onBack={() => {
              setFocusId(null)
              setSelection(null)
            }}
            onWaypointPointerDown={onWaypointPointerDown}
            onWaypointPointerMove={onWaypointPointerMove}
            onWaypointPointerUp={onWaypointPointerUp}
            dateInput={dateInput}
            setDateInput={setDateInput}
            onCommitDueDate={(taskId, v) => void commitDueDate(taskId, v)}
            onCommitProjectDate={(field, v) => void commitProjectDate(field, v)}
            writeError={writeError}
            onDeclareRiverFromSignal={declareRiverFromSignal}
            onDeclareRiverWindow={declareRiverWindow}
            onPlaceHold={placeHold}
            onSetRiverWindow={(id, startMs, endMs) =>
              setRivers((prev) => setRiverWindow(prev, id, startMs, endMs))
            }
            onWithdrawRiver={(id) => {
              setRivers((prev) => withdrawRiver(prev, id))
              setSelection(null)
            }}
            onMoveHold={(id, fraction) => setHolds((prev) => moveHold(prev, id, fraction))}
            onRemoveHold={(id) => {
              setHolds((prev) => removeHold(prev, id))
              setSelection(null)
            }}
          />
        ) : (
          <OverviewBoard overview={overview} onFocus={(id) => { setFocusId(id); setSelection(null) }} />
        )}
      </div>
      <aside className="shrink-0 lg:w-[380px] lg:overflow-y-auto border-t lg:border-t-0 lg:border-l border-stone-700/60 p-3">
        <div className="rounded-2xl border border-stone-700/60 bg-stone-900/70 p-2">
          <CouncilChat
            key={conversationId}
            environment="workspace"
            initialArchetypeId="champion"
            conversationId={conversationId}
            context={chatContext}
          />
        </div>
      </aside>
    </div>
  )
}

/* ================================================================== */
/* Overview                                                            */
/* ================================================================== */

function OverviewBoard({
  overview,
  onFocus,
}: {
  overview: ReturnType<typeof buildOverview>
  onFocus: (projectId: string) => void
}) {
  const ROW_H = 78
  const TOP = 44
  const availablePx = MAP_W - 70 - 120
  const pxPerDay = computePxPerDay(overview, availablePx)
  const height = TOP + overview.length * ROW_H + 52

  return (
    <section aria-label="Campaign Board — all projects">
      <h1 className="text-lg font-semibold text-stone-100 px-1 pb-2">Campaign Board</h1>
      <div className="rounded-2xl overflow-hidden border border-[#9a7b24]/50 shadow-lg">
        <svg viewBox={`0 0 ${MAP_W} ${height}`} className="w-full block" role="img" aria-label="All projects as routes on one map">
          <rect width={MAP_W} height={height} fill={PARCHMENT} />
          {overview.length === 0 && (
            <text x={MAP_W / 2} y={height / 2} textAnchor="middle" fontSize="15" fill={INK}>
              No projects yet — the board is empty.
            </text>
          )}
          {overview.map((o, i) => {
            const yBase = TOP + i * ROW_H
            const lineY = yBase + 36
            const lineLen = o.routeDays * pxPerDay
            const endX = 70 + lineLen
            const color = PROJECT_COLORS[i % PROJECT_COLORS.length]
            return (
              <g key={o.project.id}>
                <text x={24} y={yBase} fontSize="15" fontWeight="600" fill={INK} style={{ pointerEvents: 'none' }}>
                  {o.project.title}
                </text>
                <text x={24} y={yBase + 17} fontSize="11" fill="#6b5a43" style={{ pointerEvents: 'none' }}>
                  {o.project.status} · {o.openTaskCount} open · {o.doneTaskCount} done
                  {o.span.source !== 'provisional' ? ` · ${o.span.days} days` : ''}
                </text>
                <line x1={70} y1={lineY} x2={endX} y2={lineY} stroke={color} strokeWidth="3" strokeLinecap="round" strokeDasharray="0.5 7" style={{ pointerEvents: 'none' }} />
                <circle cx={70} cy={lineY} r="4.5" fill={color} style={{ pointerEvents: 'none' }} />
                {/* finish banner */}
                <g style={{ pointerEvents: 'none' }}>
                  <line x1={endX} y1={lineY} x2={endX} y2={lineY - 16} stroke={INK} strokeWidth="2" />
                  <path
                    d={`M ${endX} ${lineY - 16} L ${endX + 13} ${lineY - 12.5} L ${endX} ${lineY - 9} Z`}
                    fill={o.span.source === 'provisional' ? 'none' : EMBER}
                    stroke={EMBER}
                    strokeWidth="1.2"
                  />
                </g>
                {o.obstacles.slice(0, 8).map((ob) => (
                  <path
                    key={ob.id}
                    d={`M ${70 + ob.fraction * lineLen} ${lineY - 6} L ${70 + ob.fraction * lineLen + 5} ${lineY} L ${70 + ob.fraction * lineLen} ${lineY + 6} L ${70 + ob.fraction * lineLen - 5} ${lineY} Z`}
                    fill="#8c2e1e"
                    opacity="0.9"
                    style={{ pointerEvents: 'none' }}
                  />
                ))}
                {o.obstacles.length > 0 && (
                  <text x={endX + 22} y={lineY + 4} fontSize="11.5" fill="#8c2e1e" style={{ pointerEvents: 'none' }}>
                    ◆ ×{o.obstacles.length}
                  </text>
                )}
                {o.span.source === 'provisional' && (
                  <text x={endX + 22} y={lineY - 8} fontSize="11" fill="#6b5a43" style={{ pointerEvents: 'none' }}>
                    no dates recorded
                  </text>
                )}
                <rect
                  x={8}
                  y={yBase - 24}
                  width={MAP_W - 16}
                  height={ROW_H - 6}
                  fill="#000"
                  fillOpacity={0}
                  style={{ cursor: 'pointer' }}
                  onClick={() => onFocus(o.project.id)}
                />
              </g>
            )
          })}
          {/* scale key — on the map */}
          <g>
            <line x1={70} y1={height - 22} x2={70 + pxPerDay} y2={height - 22} stroke={INK} strokeWidth="2.4" strokeDasharray="5 3" />
            <line x1={70} y1={height - 27} x2={70} y2={height - 17} stroke={INK} strokeWidth="1.6" />
            <line x1={70 + pxPerDay} y1={height - 27} x2={70 + pxPerDay} y2={height - 17} stroke={INK} strokeWidth="1.6" />
            <text x={70 + pxPerDay + 9} y={height - 18} fontSize="12" fill={INK}>
              = 1 day
            </text>
          </g>
        </svg>
      </div>
    </section>
  )
}

/* ================================================================== */
/* Focus                                                               */
/* ================================================================== */

type FocusData = {
  project: Project
  projectTasks: Task[]
  span: ReturnType<typeof projectSpan>
  obstacles: BoardObstacle[]
  terrain: TerrainFeature[]
  routes: ReturnType<typeof buildRoutes>
  initiative: { id: string; title: string } | null
  signalMarkers: SignalMarker[]
  capacity: PersonCapacity[]
  rivers: RiverDeclaration[]
  holds: HoldDeclaration[]
}

const SIGNAL_COLORS: Record<string, string> = {
  blocker: '#8c2e1e',
  risk: '#a8741a',
  opportunity: '#54683f',
  attention: '#46617e',
}

function FocusBoard({
  focus,
  selection,
  setSelection,
  drag,
  svgRef,
  onBack,
  onWaypointPointerDown,
  onWaypointPointerMove,
  onWaypointPointerUp,
  dateInput,
  setDateInput,
  onCommitDueDate,
  onCommitProjectDate,
  writeError,
  onDeclareRiverFromSignal,
  onDeclareRiverWindow,
  onPlaceHold,
  onSetRiverWindow,
  onWithdrawRiver,
  onMoveHold,
  onRemoveHold,
}: {
  focus: FocusData
  selection: Selection
  setSelection: (s: Selection) => void
  drag: { taskId: string; fraction: number; moved: boolean } | null
  svgRef: React.Ref<SVGSVGElement>
  onBack: () => void
  onWaypointPointerDown: (e: React.PointerEvent, w: BoardWaypoint) => void
  onWaypointPointerMove: (e: React.PointerEvent, w: BoardWaypoint) => void
  onWaypointPointerUp: (e: React.PointerEvent, w: BoardWaypoint) => void
  dateInput: string
  setDateInput: (v: string) => void
  onCommitDueDate: (taskId: string, v: string) => void
  onCommitProjectDate: (field: 'start_date' | 'end_date', v: string) => void
  writeError: string | null
  onDeclareRiverFromSignal: (signal: BoardSignal) => void
  onDeclareRiverWindow: () => void
  onPlaceHold: () => void
  onSetRiverWindow: (id: string, startMs: number, endMs: number) => void
  onWithdrawRiver: (id: string) => void
  onMoveHold: (id: string, fraction: number) => void
  onRemoveHold: (id: string) => void
}) {
  const { project, span, obstacles, terrain, routes, signalMarkers, capacity, rivers, holds } = focus
  // Hold dragging is a local gesture over session state — the override
  // lives here; the committed fraction goes up on release.
  const [holdDrag, setHoldDrag] = useState<{ holdId: string; fraction: number } | null>(null)
  const holdFraction = (h: HoldDeclaration): number =>
    holdDrag && holdDrag.holdId === h.id ? holdDrag.fraction : h.fraction
  const svgLocalX = (clientX: number): number => {
    const svg = (svgRef as React.RefObject<SVGSVGElement | null>)?.current
    if (!svg) return 0
    const rect = svg.getBoundingClientRect()
    return ((clientX - rect.left) / rect.width) * MAP_W
  }
  const dragOverride = drag ? { taskId: drag.taskId, fraction: drag.fraction } : null
  const aPts = routePoints(routes.a.filter((w) => !w.done), ROUTE_A_Y, dragOverride)
  const bPts = routePoints(routes.b, ROUTE_B_Y, dragOverride)
  const allWaypoints: { w: BoardWaypoint; bandY: number; index: number }[] = [
    ...routes.a.map((w, index) => ({ w, bandY: ROUTE_A_Y, index })),
    ...routes.b.map((w, index) => ({ w, bandY: ROUTE_B_Y, index })),
  ]
  const terrainAt = (taskId: string): { x: number; y: number } => {
    const onA = routes.a.find((w) => w.task.id === taskId)
    if (onA) return { x: xForFraction(onA.fraction), y: ROUTE_A_Y }
    return { x: X0 + 40, y: ROUTE_A_Y }
  }

  const openWaypoint = (taskId: string) => {
    const w = [...routes.a, ...routes.b].find((x) => x.task.id === taskId)
    if (w) setDateInput(toLocalDateTimeString(dateAtFraction(span, w.fraction)))
    setSelection({ kind: 'waypoint', taskId })
  }

  const openEndpoint = (kind: 'start' | 'finish') => {
    setDateInput(toLocalDateTimeString(new Date(kind === 'finish' ? span.endMs : span.startMs)))
    setSelection({ kind })
  }

  return (
    <section aria-label={`Campaign Board — ${project.title}`}>
      <div className="flex items-center gap-3 px-1 pb-2 flex-wrap">
        <button
          type="button"
          onClick={onBack}
          className="min-h-[40px] px-3 rounded-full border border-stone-600 text-stone-200 text-sm hover:bg-stone-800"
        >
          ← All projects
        </button>
        <h1 className="text-lg font-semibold text-stone-100">{project.title}</h1>
        <span className="text-xs text-stone-400">
          {focus.initiative ? `${focus.initiative.title} · ` : ''}
          {shortDate(new Date(span.startMs))} – {shortDate(new Date(span.endMs))}
          {span.source === 'provisional' ? ' · dates not recorded yet' : ''}
        </span>
        <span className="flex items-center gap-2 ml-auto">
          <button
            type="button"
            onClick={onDeclareRiverWindow}
            className="min-h-[40px] px-3 rounded-full border border-stone-600 text-stone-200 text-sm hover:bg-stone-800"
          >
            ＋ River
          </button>
          <button
            type="button"
            onClick={onPlaceHold}
            className="min-h-[40px] px-3 rounded-full border border-stone-600 text-stone-200 text-sm hover:bg-stone-800"
          >
            ＋ Hold
          </button>
        </span>
      </div>

      <div className="relative rounded-2xl overflow-hidden border border-[#9a7b24]/50 shadow-lg">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${MAP_W} ${FOCUS_H}`}
          className="w-full block touch-none"
          role="img"
          aria-label={`Campaign map for ${project.title}`}
        >
          <rect width={MAP_W} height={FOCUS_H} fill={PARCHMENT} />
          {/* faint contour wash */}
          <g fill="none" stroke="#d8c9a3" strokeWidth="1.2" opacity="0.7">
            <path d="M-20 90 C 180 40, 320 130, 520 84 C 660 52, 760 96, 830 70" />
            <path d="M-20 420 C 200 380, 340 452, 540 410 C 680 382, 760 420, 830 396" />
          </g>

          {/* terrain — declared from the material, behind the routes */}
          {terrain.map((f) => {
            const at = terrainAt(f.taskId)
            return (
              <g
                key={`${f.kind}-${f.taskId}`}
                transform={`translate(${at.x},${at.y})`}
                style={{ cursor: 'pointer' }}
                onClick={() => setSelection({ kind: 'terrain', feature: f })}
              >
                {f.kind === 'mountain' || f.kind === 'hill' ? (
                  <>
                    <path
                      d={`M -52 18 L -14 ${-(26 + (f.effortDays ?? 1) * 11)} L -2 ${-(26 + (f.effortDays ?? 1) * 11) * 0.6} L 10 ${-(26 + (f.effortDays ?? 1) * 11) * 0.82} L 30 ${-(26 + (f.effortDays ?? 1) * 11) * 0.45} L 52 18 Z`}
                      fill="#93a58c"
                      stroke="#71855e"
                      strokeWidth="1.2"
                      strokeLinejoin="round"
                    />
                    <text y={-(26 + (f.effortDays ?? 1) * 11) - 8} textAnchor="middle" fontSize="11" fill="#54683f">
                      {f.form} · {f.effortDays}d
                    </text>
                  </>
                ) : f.kind === 'open' ? (
                  <>
                    <path d="M-52 16 Q-26 -4 0 8 Q26 -10 52 16 Z" fill="#a9bd8d" opacity="0.85" />
                    <text y="-14" textAnchor="middle" fontSize="11" fill="#54683f">
                      Open Ground · {f.effortDays}d
                    </text>
                  </>
                ) : (
                  <>
                    {Array.from({ length: f.treeCount ?? 0 }).map((_, ti) => {
                      const offs = [[-40, 16], [-24, 26], [34, 18], [50, 28], [16, 30], [-6, 22], [-52, 30], [58, 14]]
                      const o = offs[ti % offs.length]
                      return (
                        <g key={ti} transform={`translate(${o[0]},${o[1]})`}>
                          <path d="M0 -16 L7 0 L3 0 L9 10 L-9 10 L-3 0 L-7 0 Z" fill="#5d7350" />
                          <line x1="0" y1="10" x2="0" y2="15" stroke="#6b5133" strokeWidth="2" />
                        </g>
                      )
                    })}
                    <text y="58" textAnchor="middle" fontSize="11" fill="#54683f">
                      {f.form} · {f.treeCount} tasks
                    </text>
                  </>
                )}
              </g>
            )
          })}

          {/* declared rivers — user-fixed immovable windows crossing the line */}
          {rivers.map((river) => {
            const band = riverBand(span, river)
            const bx0 = xForFraction(band.startFraction)
            const bx1 = xForFraction(band.endFraction)
            const top = ROUTE_A_Y - 62
            const bottom = ROUTE_B_Y + 58
            return (
              <g
                key={river.id}
                style={{ cursor: 'pointer' }}
                onClick={() => setSelection({ kind: 'river', riverId: river.id })}
              >
                <rect x={bx0} y={top} width={Math.max(10, bx1 - bx0)} height={bottom - top} fill="#7fa8b8" opacity="0.38" />
                {[0.22, 0.5, 0.78].map((t) => {
                  const wx = bx0 + (bx1 - bx0) * t
                  return (
                    <path
                      key={t}
                      d={`M ${wx} ${top} q 5 ${(bottom - top) / 4} 0 ${(bottom - top) / 2} q -5 ${(bottom - top) / 4} 0 ${(bottom - top) / 2}`}
                      fill="none"
                      stroke="#4a7d94"
                      strokeWidth="1.8"
                      opacity="0.8"
                    />
                  )
                })}
                <text x={(bx0 + bx1) / 2} y={top - 8} textAnchor="middle" fontSize="11" fontWeight="600" fill="#33617a">
                  The River
                </text>
              </g>
            )
          })}

          {/* routes — speculative arrangements of the recorded steps */}
          <path d={smoothPath(aPts)} fill="none" stroke="#7a3b2e" strokeWidth="2.6" strokeLinecap="round" strokeDasharray="0.5 8" opacity="0.95" />
          <path d={smoothPath(bPts)} fill="none" stroke="#33655f" strokeWidth="2.6" strokeLinecap="round" strokeDasharray="0.5 8" opacity="0.95" />
          <text x={X0 + 6} y={ROUTE_A_Y - 52} fontSize="11.5" fill="#7a3b2e" fontWeight="600">
            Plan A · by date
          </text>
          <text x={X0 + 6} y={ROUTE_B_Y + 66} fontSize="11.5" fill="#33655f" fontWeight="600">
            Plan B · dependencies first
          </text>

          {/* obstacles on the midline */}
          {obstacles.map((ob) => {
            const x = xForFraction(ob.fraction)
            const isGate = ob.kind === 'gate'
            const isCrossing = ob.kind === 'crossing'
            return (
              <g
                key={ob.id}
                transform={`translate(${x},${MID_Y})`}
                style={{ cursor: 'pointer' }}
                onClick={() => setSelection({ kind: 'obstacle', obstacleId: ob.id })}
              >
                {isGate ? (
                  <>
                    <rect x="-16" y="-13" width="5" height="24" fill="#8d8574" stroke="#5f594c" />
                    <rect x="11" y="-13" width="5" height="24" fill="#8d8574" stroke="#5f594c" />
                    <rect x="-19" y="-18" width="38" height="5" rx="2" fill="#75705f" />
                    <text y="30" textAnchor="middle" fontSize="10.5" fill="#7a5a12">
                      Gate Keeper
                    </text>
                  </>
                ) : isCrossing ? (
                  <>
                    <path d="M-13 8 L0 -8 L13 8" fill="none" stroke="#33655f" strokeWidth="2.6" />
                    <path d="M-13 15 L0 -1 L13 15" fill="none" stroke="#33655f" strokeWidth="2.6" opacity="0.6" />
                    <text y="32" textAnchor="middle" fontSize="10.5" fill="#33655f">
                      Crossing
                    </text>
                  </>
                ) : (
                  <>
                    <path d="M0 -9 L7 0 L0 9 L-7 0 Z" fill={ob.kind === 'overdue' ? '#a8741a' : '#8c2e1e'} stroke={INK} strokeWidth="0.8" />
                    <text y="26" textAnchor="middle" fontSize="10.5" fill={ob.kind === 'overdue' ? '#7a5a12' : '#8c2e1e'}>
                      {ob.kindLabel}
                    </text>
                  </>
                )}
              </g>
            )
          })}

          {/* signals — reported circumstances standing above the line */}
          {signalMarkers.map((m) => {
            const x = xForFraction(m.fraction)
            const color = SIGNAL_COLORS[(m.signal.kind || '').toLowerCase()] ?? '#46617e'
            const title =
              m.signal.title.length > 24 ? `${m.signal.title.slice(0, 23)}…` : m.signal.title
            return (
              <g
                key={m.id}
                transform={`translate(${x},${MID_Y - 44})`}
                style={{ cursor: 'pointer' }}
                onClick={() => setSelection({ kind: 'signal', signalId: m.signal.id })}
              >
                <circle r="15" fill="transparent" />
                <line x1="0" y1="10" x2="0" y2="-8" stroke={color} strokeWidth="2" />
                <path d="M0 -8 L13 -4.5 L0 -1 Z" fill={color} />
                <text y="-14" textAnchor="middle" fontSize="10.5" fontWeight="600" fill={color} style={{ pointerEvents: 'none' }}>
                  {m.kindLabel}
                </text>
                <text y="24" textAnchor="middle" fontSize="10" fill={INK} style={{ pointerEvents: 'none' }}>
                  {title}
                </text>
              </g>
            )
          })}

          {/* capacity — the load the people on this work are carrying */}
          {capacity
            .filter((c) => c.weeklyCapacityHours != null)
            .map((c, i) => {
              const x = X0 + 6 + i * 118
              const label = `${c.committedHours}/${c.weeklyCapacityHours}h`
              return (
                <g
                  key={c.personId}
                  transform={`translate(${x},34)`}
                  style={{ cursor: 'pointer' }}
                  onClick={() => setSelection({ kind: 'capacity', personId: c.personId })}
                >
                  <rect x="-4" y="-13" width="106" height="24" rx="12" fill={c.over ? '#f3d9cf' : '#e7dfc8'} stroke={c.over ? EMBER : '#9a7b24'} strokeWidth="1.2" />
                  <text x="6" y="4" fontSize="10.5" fontWeight="600" fill={c.over ? '#8c2e1e' : INK} style={{ pointerEvents: 'none' }}>
                    {c.name.split(' ')[0]} · {label}
                    {c.over ? ' · over' : ''}
                  </text>
                </g>
              )
            })}

          {/* start camp + finish banner */}
          <g transform={`translate(${X0},${MID_Y})`} style={{ cursor: 'pointer' }} onClick={() => openEndpoint('start')}>
            <path d="M-13 10 L0 -12 L13 10 Z" fill="#8a6a42" stroke="#6b5133" strokeWidth="1.2" />
            <text y="28" textAnchor="middle" fontSize="11" fill={INK}>
              Start · {shortDate(new Date(span.startMs))}
            </text>
          </g>
          <g transform={`translate(${X1},${MID_Y})`} style={{ cursor: 'pointer' }} onClick={() => openEndpoint('finish')}>
            <line x1="0" y1="12" x2="0" y2="-24" stroke={INK} strokeWidth="2.2" />
            <path d="M0 -24 L20 -19 L0 -14 Z" fill={EMBER} />
            <text y="30" textAnchor="middle" fontSize="11" fill={INK}>
              Finish · {shortDate(new Date(span.endMs))}
            </text>
          </g>

          {/* waypoints */}
          {allWaypoints.map(({ w, bandY, index }) => {
            const f = drag && drag.taskId === w.task.id ? drag.fraction : w.fraction
            const x = xForFraction(f)
            const y = waypointY(bandY, index)
            const labelTier = index % 2 === 0 ? 30 : 46
            return (
              <g
                key={`${bandY}-${w.task.id}`}
                transform={`translate(${x},${y})`}
                style={{ cursor: w.done ? 'pointer' : 'grab', touchAction: 'none' }}
                onPointerDown={(e) => onWaypointPointerDown(e, w)}
                onPointerMove={(e) => onWaypointPointerMove(e, w)}
                onPointerUp={(e) => onWaypointPointerUp(e, w)}
                onClick={() => {
                  // Non-done waypoints select on pointer-up (drag vs tap is
                  // decided there); done markers never start a drag.
                  if (w.done) openWaypoint(w.task.id)
                }}
              >
                <circle r="17" fill="transparent" />
                {w.done ? (
                  <>
                    <circle r="9" fill="#54683f" stroke="#f1e8d0" strokeWidth="1.6" />
                    <path d="M-4 0 L-1 3 L4 -3" fill="none" stroke="#f1e8d0" strokeWidth="1.8" strokeLinecap="round" />
                  </>
                ) : (
                  <circle r="9" fill={bandY === ROUTE_A_Y ? '#a63d2a' : '#33655f'} stroke="#f1e8d0" strokeWidth="1.6" />
                )}
                <text y={labelTier} textAnchor="middle" fontSize="11" fill={INK} style={{ pointerEvents: 'none' }}>
                  {w.task.title.length > 26 ? `${w.task.title.slice(0, 25)}…` : w.task.title}
                </text>
                <text y={labelTier + 13} textAnchor="middle" fontSize="10" fill="#6b5a43" style={{ pointerEvents: 'none' }}>
                  {w.done ? 'done' : shortDate(dateAtFraction(span, f))}
                </text>
              </g>
            )
          })}

          {/* holds — user-placed review checkpoints, draggable on the line */}
          {holds.map((h) => {
            const f = holdFraction(h)
            const x = xForFraction(f)
            return (
              <g
                key={h.id}
                transform={`translate(${x},${MID_Y})`}
                style={{ cursor: 'grab', touchAction: 'none' }}
                onPointerDown={(e) => {
                  ;(e.currentTarget as Element).setPointerCapture(e.pointerId)
                  setHoldDrag({ holdId: h.id, fraction: f })
                }}
                onPointerMove={(e) => {
                  if (holdDrag && holdDrag.holdId === h.id) {
                    setHoldDrag({ holdId: h.id, fraction: fractionForX(svgLocalX(e.clientX)) })
                  }
                }}
                onPointerUp={() => {
                  if (holdDrag && holdDrag.holdId === h.id) {
                    onMoveHold(h.id, holdDrag.fraction)
                    setHoldDrag(null)
                    setSelection({ kind: 'hold', holdId: h.id })
                  }
                }}
                onClick={() => setSelection({ kind: 'hold', holdId: h.id })}
              >
                <circle r="17" fill="transparent" />
                <line x1="0" y1="8" x2="0" y2="-16" stroke="#6b5133" strokeWidth="2.2" />
                <path d="M0 -16 L14 -12.5 L0 -9 Z" fill="#a8741a" />
                <ellipse cx="-5" cy="10" rx="7" ry="3.4" fill="#8d8574" stroke="#5f594c" strokeWidth="0.8" />
                <ellipse cx="5" cy="10" rx="7" ry="3.4" fill="#9a927f" stroke="#5f594c" strokeWidth="0.8" />
                <ellipse cx="0" cy="6.5" rx="5.5" ry="3" fill="#a39a86" stroke="#5f594c" strokeWidth="0.8" />
                <text y="30" textAnchor="middle" fontSize="10.5" fontWeight="600" fill="#7a5a12" style={{ pointerEvents: 'none' }}>
                  Hold
                </text>
                <text y="43" textAnchor="middle" fontSize="10" fill="#6b5a43" style={{ pointerEvents: 'none' }}>
                  {shortDate(dateAtFraction(span, f))}
                </text>
              </g>
            )
          })}

          {/* drag chip — the projected delivery date while stretching a node */}
          {drag && (
            <g transform={`translate(${xForFraction(drag.fraction)},${ROUTE_A_Y - 84})`} pointerEvents="none">
              <rect x="-62" y="-13" width="124" height="24" rx="12" fill="#1c231c" />
              <text y="4" textAnchor="middle" fontSize="11.5" fontWeight="700" fill="#fffaf0">
                {fullDate(dateAtFraction(span, drag.fraction))}
              </text>
            </g>
          )}

          {/* frame */}
          <g fill="none" stroke="#9a7b24" pointerEvents="none">
            <rect x="9" y="9" width="782" height="482" strokeWidth="2" opacity="0.55" />
            <rect x="15" y="15" width="770" height="470" strokeWidth="0.8" opacity="0.4" />
          </g>
        </svg>

        {selection && (
          <FocusPopup
            focus={focus}
            selection={selection}
            onClose={() => setSelection(null)}
            dateInput={dateInput}
            setDateInput={setDateInput}
            onCommitDueDate={onCommitDueDate}
            onCommitProjectDate={onCommitProjectDate}
            onOpenWaypoint={openWaypoint}
            writeError={writeError}
            onDeclareRiverFromSignal={onDeclareRiverFromSignal}
            onSetRiverWindow={onSetRiverWindow}
            onWithdrawRiver={onWithdrawRiver}
            onRemoveHold={onRemoveHold}
          />
        )}
      </div>

      {/* timeline strip — each step's date between start and finish */}
      <div className="rounded-2xl overflow-hidden border border-[#9a7b24]/50 mt-3">
        <svg viewBox={`0 0 ${MAP_W} 64`} className="w-full block" role="img" aria-label="Timeline of steps between start and finish">
          <rect width={MAP_W} height={64} fill={PARCHMENT} />
          <line x1={X0} y1={30} x2={X1} y2={30} stroke={INK} strokeWidth="1.6" />
          <text x={X0} y={16} fontSize="10.5" fill={INK}>
            {shortDate(new Date(span.startMs))}
          </text>
          <text x={X1} y={16} textAnchor="end" fontSize="10.5" fill={INK}>
            {shortDate(new Date(span.endMs))}
          </text>
          {routes.a.map((w) => (
            <g key={w.task.id} transform={`translate(${xForFraction(w.fraction)},30)`}>
              <line y1="-6" y2="6" stroke={INK} strokeWidth="1.4" />
              <text y={24} textAnchor="middle" fontSize="9.5" fill="#6b5a43">
                {w.done ? 'done' : shortDate(dateAtFraction(span, w.fraction))}
              </text>
            </g>
          ))}
        </svg>
      </div>
    </section>
  )
}

/* ================================================================== */
/* Popup — the dossier lives here and in Valen's chat, not on the map  */
/* ================================================================== */

function FocusPopup({
  focus,
  selection,
  onClose,
  dateInput,
  setDateInput,
  onCommitDueDate,
  onCommitProjectDate,
  onOpenWaypoint,
  writeError,
  onDeclareRiverFromSignal,
  onSetRiverWindow,
  onWithdrawRiver,
  onRemoveHold,
}: {
  focus: FocusData
  selection: Exclude<Selection, null>
  onClose: () => void
  dateInput: string
  setDateInput: (v: string) => void
  onCommitDueDate: (taskId: string, v: string) => void
  onCommitProjectDate: (field: 'start_date' | 'end_date', v: string) => void
  onOpenWaypoint: (taskId: string) => void
  writeError: string | null
  onDeclareRiverFromSignal: (signal: BoardSignal) => void
  onSetRiverWindow: (id: string, startMs: number, endMs: number) => void
  onWithdrawRiver: (id: string) => void
  onRemoveHold: (id: string) => void
}) {
  const { project, span, projectTasks } = focus
  const taskById = new Map(projectTasks.map((t) => [t.id, t]))
  // River window editing — local form state, re-seeded per river.
  const [riverStart, setRiverStart] = useState('')
  const [riverEnd, setRiverEnd] = useState('')
  const riverForForm = selection.kind === 'river' ? focus.rivers.find((r) => r.id === selection.riverId) : undefined
  useEffect(() => {
    if (riverForForm) {
      setRiverStart(toLocalDateTimeString(new Date(riverForForm.startMs)))
      setRiverEnd(toLocalDateTimeString(new Date(riverForForm.endMs)))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [riverForForm?.id])

  let title = ''
  let body: React.ReactNode = null

  if (selection.kind === 'waypoint') {
    const task = taskById.get(selection.taskId)
    if (task) {
      const dueMs = parseDateMs(task.due_date)
      const deps = (task.dependency_ids ?? [])
        .map((id) => taskById.get(id))
        .filter((x): x is Task => !!x)
      title = task.title
      body = (
        <>
          <p className="text-stone-300">
            {task.status === 'Done'
              ? 'Completed step — an existing task, recorded done.'
              : task.due_date
                ? `Recorded step — due ${fullDate(new Date(dueMs ?? 0))}.`
                : 'Recorded step — no date set yet. Its place on the line is by order, not by date.'}
          </p>
          {task.description.trim() && <p className="text-stone-400">{task.description.trim()}</p>}
          {deps.length > 0 && (
            <p className="text-stone-400">
              Waits on: {deps.map((d) => `${d.title} (${d.status.toLowerCase()})`).join(' · ')}
            </p>
          )}
          {task.status !== 'Done' && (
            <div className="flex items-center gap-2 pt-1 flex-wrap">
              <input
                type="datetime-local"
                value={dateInput}
                onChange={(e) => setDateInput(e.target.value)}
                className="bg-stone-950 border border-stone-600 rounded-lg px-2 py-1.5 text-sm text-stone-100"
                aria-label="Set this step's date and time"
              />
              <button
                type="button"
                onClick={() => dateInput && onCommitDueDate(task.id, dateInput)}
                className="min-h-[36px] px-3 rounded-full bg-amber-600 text-amber-50 text-sm font-semibold"
              >
                Set date
              </button>
            </div>
          )}
        </>
      )
    }
  } else if (selection.kind === 'obstacle') {
    const ob = focus.obstacles.find((o) => o.id === selection.obstacleId)
    if (ob) {
      title = `${ob.kindLabel} — ${ob.label}`
      body = (
        <>
          <p className="text-stone-300">
            {obstacleDomainLabel(ob.domain)} · standing: {ob.standing}
          </p>
          <p className="text-stone-400">{ob.rule}</p>
          {ob.detail && <p className="text-stone-400">“{ob.detail}”</p>}
          <button
            type="button"
            onClick={() => onOpenWaypoint(ob.taskId)}
            className="min-h-[36px] px-3 rounded-full border border-stone-500 text-stone-100 text-sm"
          >
            Open the step
          </button>
        </>
      )
    }
  } else if (selection.kind === 'terrain') {
    const f = selection.feature
    title = f.form
    body = (
      <>
        <p className="text-stone-300">{f.fact}</p>
        <p className="text-stone-400">{f.rule}</p>
      </>
    )
  } else if (selection.kind === 'signal') {
    const m = focus.signalMarkers.find((x) => x.signal.id === selection.signalId)
    if (m) {
      const s = m.signal
      const created = parseDateMs(s.created_at)
      title = `${m.kindLabel} — ${s.title}`
      body = (
        <>
          <p className="text-stone-300">Circumstance · standing: reported</p>
          <p className="text-stone-400">{m.rule}</p>
          {s.detail && <p className="text-stone-400">{s.detail}</p>}
          {s.source_excerpt && <p className="text-stone-400">“{s.source_excerpt}”</p>}
          <p className="text-stone-500 text-xs">
            {s.source ? `Source: ${s.source}` : 'Source not recorded'}
            {created != null ? ` · recorded ${fullDate(new Date(created))}` : ''}
            {s.confidence != null ? ` · confidence ${s.confidence}` : ''}
            {m.via === 'task' ? ' · linked to a step on this line' : m.via === 'initiative' ? ' · linked to the initiative' : ' · linked to this project'}
          </p>
          <div className="flex items-center gap-2 pt-1 flex-wrap">
            {m.taskId && (
              <button
                type="button"
                onClick={() => onOpenWaypoint(m.taskId as string)}
                className="min-h-[36px] px-3 rounded-full border border-stone-500 text-stone-100 text-sm"
              >
                Open the step
              </button>
            )}
            <button
              type="button"
              onClick={() => onDeclareRiverFromSignal(s)}
              className="min-h-[36px] px-3 rounded-full bg-amber-600 text-amber-50 text-sm font-semibold"
            >
              Declare a River
            </button>
          </div>
        </>
      )
    }
  } else if (selection.kind === 'river') {
    const river = focus.rivers.find((r) => r.id === selection.riverId)
    if (river) {
      title = 'The River'
      body = (
        <>
          <p className="text-stone-300">
            {river.source.type === 'signal'
              ? `Declared from signal: “${river.source.signalTitle}”`
              : `Declared window: ${shortDate(new Date(river.startMs))} – ${shortDate(new Date(river.endMs))}`}
          </p>
          {river.source.type === 'signal' && (
            <p className="text-stone-400">
              Window: {shortDate(new Date(river.startMs))} – {shortDate(new Date(river.endMs))}. An
              immovable window, fixed by your declaration.
            </p>
          )}
          <div className="flex items-center gap-2 pt-1 flex-wrap">
            <input
              type="datetime-local"
              value={riverStart}
              onChange={(e) => setRiverStart(e.target.value)}
              className="bg-stone-950 border border-stone-600 rounded-lg px-2 py-1.5 text-sm text-stone-100"
              aria-label="River window opens"
            />
            <input
              type="datetime-local"
              value={riverEnd}
              onChange={(e) => setRiverEnd(e.target.value)}
              className="bg-stone-950 border border-stone-600 rounded-lg px-2 py-1.5 text-sm text-stone-100"
              aria-label="River window closes"
            />
            <button
              type="button"
              onClick={() => {
                const sMs = parseDateMs(riverStart)
                const eMs = parseDateMs(riverEnd)
                if (sMs != null && eMs != null && eMs > sMs) onSetRiverWindow(river.id, sMs, eMs)
              }}
              className="min-h-[36px] px-3 rounded-full bg-amber-600 text-amber-50 text-sm font-semibold"
            >
              Set window
            </button>
            <button
              type="button"
              onClick={() => onWithdrawRiver(river.id)}
              className="min-h-[36px] px-3 rounded-full border border-stone-500 text-stone-100 text-sm"
            >
              Withdraw declaration
            </button>
          </div>
        </>
      )
    }
  } else if (selection.kind === 'hold') {
    const hold = focus.holds.find((h) => h.id === selection.holdId)
    if (hold) {
      title = 'Hold'
      body = (
        <>
          <p className="text-stone-300">
            A review checkpoint placed by you, standing at{' '}
            {fullDate(dateAtFraction(span, hold.fraction))}. Drag it along the line to move it.
          </p>
          <button
            type="button"
            onClick={() => onRemoveHold(hold.id)}
            className="min-h-[36px] px-3 rounded-full border border-stone-500 text-stone-100 text-sm"
          >
            Remove hold
          </button>
        </>
      )
    }
  } else if (selection.kind === 'capacity') {
    const c = focus.capacity.find((x) => x.personId === selection.personId)
    if (c) {
      title = `${c.name} — the load`
      body = (
        <>
          <p className="text-stone-300">
            {c.committedHours}h a week committed
            {c.weeklyCapacityHours != null ? ` against ${c.weeklyCapacityHours}h recorded capacity` : ''}
            {c.over ? ` — ${c.delta}h over.` : '.'}
          </p>
          <p className="text-stone-400">{c.rule}</p>
        </>
      )
    }
  } else if (selection.kind === 'finish' || selection.kind === 'start') {
    const isFinish = selection.kind === 'finish'
    const recorded = isFinish ? project.end_date : project.start_date
    title = isFinish ? `Finish — ${project.title}` : `Start — ${project.title}`
    body = (
      <>
        <p className="text-stone-300">
          {recorded
            ? `Recorded: ${fullDate(new Date(parseDateMs(recorded) ?? 0))}.`
            : isFinish
              ? 'No finish date recorded. Date the finish first and the rest of the line gains its context.'
              : 'No start date recorded.'}
        </p>
        <div className="flex items-center gap-2 pt-1 flex-wrap">
          <input
            type="datetime-local"
            value={dateInput}
            onChange={(e) => setDateInput(e.target.value)}
            className="bg-stone-950 border border-stone-600 rounded-lg px-2 py-1.5 text-sm text-stone-100"
            aria-label={isFinish ? 'Set the finish date and time' : 'Set the start date and time'}
          />
          <button
            type="button"
            onClick={() =>
              dateInput && onCommitProjectDate(isFinish ? 'end_date' : 'start_date', dateInput)
            }
            className="min-h-[36px] px-3 rounded-full bg-amber-600 text-amber-50 text-sm font-semibold"
          >
            Set date
          </button>
        </div>
        {span.source === 'provisional' && (
          <p className="text-stone-500 text-xs">
            Until real dates are recorded, the line is drawn against a provisional window and is not
            to scale.
          </p>
        )}
      </>
    )
  }

  return (
    <div className="absolute top-2 right-2 w-[min(92vw,340px)] max-h-[92%] overflow-y-auto rounded-xl bg-stone-900/95 border border-stone-600 shadow-2xl p-3.5 text-sm z-10">
      <div className="flex items-start justify-between gap-2">
        <h3 className="font-semibold text-stone-100 leading-snug">{title}</h3>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="shrink-0 w-8 h-8 rounded-full border border-stone-600 text-stone-300"
        >
          ✕
        </button>
      </div>
      <div className="mt-2 space-y-2">{body}</div>
      {writeError && <p className="mt-2 text-xs text-red-300">{writeError}</p>}
    </div>
  )
}
