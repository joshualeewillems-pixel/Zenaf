/**
 * Valen's Campaign Board — the production surface.
 *
 * A projection of the user's real Vision Execution work: the overview
 * is one shared map — every project nested under its initiative's
 * ground, dated projects running dotted routes whose length is their
 * recorded time span (scale key on the map), undated projects standing
 * unspanned at their camp; clicking a route opens the focus
 * board — declared terrain, two speculative routes over the project's
 * recorded tasks, movable waypoints whose position IS the task's due
 * date, and obstacles classified from the record. The focus board also
 * draws the project's reported circumstances (its linked open signals,
 * standing: reported — never upgraded to confirmed) and the capacity
 * load of the people on the work (the Radar's overcapacity rule).
 * Rivers and Holds are the user's own terrain declarations — made
 * in conversation with Valen and recorded as VE decisions; the
 * board reads them from that record on load and never writes them.
 * A tap stages an object tentatively in the conversation; a drag
 * never stages anything. The one surface write is a dragged
 * waypoint's due date, through the existing VE PATCH endpoint;
 * routes themselves are provisional arrangements, stored nowhere.
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
import SplitShell from '../components/SplitShell'
import type { Project, Task } from '../vision-execution/types'
import { fetchBoardEntities, patchTaskDueDate, type BoardEntities } from './boardApi'
import campaignMapArt from './assets/campaign-map.jpg'
import spriteCamp from './assets/sprites/camp.webp'
import spriteCrag from './assets/sprites/obstacle-crag.webp'
import spriteCopse from './assets/sprites/the-copse.webp'
import spriteFinishBanner from './assets/sprites/finish-banner.webp'
import spriteGrove from './assets/sprites/the-grove.webp'
import spriteHill from './assets/sprites/the-hill.webp'
import spriteMountain from './assets/sprites/the-mountain.webp'
import spriteOpenGround from './assets/sprites/open-ground.webp'
import spriteStronghold from './assets/sprites/stronghold.webp'
import {
  buildOverview,
  buildRoutes,
  dateAtFraction,
  declareTerrain,
  deriveCapacityPicture,
  deriveDeclarations,
  deriveObstacles,
  deriveSignalMarkers,
  estimateLabelWidth,
  fractionForDate,
  fullDate,
  groupOverviewByInitiative,
  layoutBoardLabels,
  projectSpan,
  riverBand,
  shortDate,
  signalsForProject,
  stripWaypointLabels,
  toLocalDateTimeString,
  type BoardLabelItem,
  type BoardLabelPlacement,
  type BoardObstacle,
  type BoardWaypoint,
  type HoldDeclaration,
  type OverviewProject,
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
  /* A no-timeframe project's red !, tapped on the overview:
   * the project stages in Valen's chat under a provisional-
   * timeframe ask (founder, 2026-11-27) until the chip is
   * set down or another lane takes the stage. */
  const [provisionalAskId, setProvisionalAskId] = useState<string | null>(null)
  const [drag, setDrag] = useState<{ taskId: string; fraction: number; moved: boolean } | null>(null)
  const [writeError, setWriteError] = useState<string | null>(null)
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
  // River/Hold declarations are read from the record: folded from
  // the owner's decision rows on load (Board interaction pass,
  // 2026-11-25). The board never holds declaration state of its own.
  const declarations = useMemo(
    () => (entities ? deriveDeclarations(entities.decisions) : { rivers: [], holds: [] }),
    [entities],
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
      rivers: declarations.rivers.filter((r) => r.projectId === project.id),
      holds: declarations.holds.filter((h) => h.projectId === project.id),
    }
  }, [entities, focusId, nowMs, declarations])

  const applyTask = useCallback((updated: Task) => {
    setEntities((prev) =>
      prev ? { ...prev, tasks: prev.tasks.map((t) => (t.id === updated.id ? updated : t)) } : prev,
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
      // A drag is a surface-native reschedule gesture and nothing
      // more: it commits the due date and stages NOTHING — no card,
      // no chat change (S1 of the Board interaction pass).
      void commitDueDate(w.task.id, toLocalDateTimeString(dateAtFraction(focus.span, fraction)))
      return
    }
    // A tap stages the waypoint tentatively in the conversation:
    // pure client state, no write; it enters the record only when
    // the visitor sends a turn while it is staged.
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
    : provisionalAskId
      ? {
          sheet_type: 'campaign_board',
          entity_type: 'project',
          entity_id: provisionalAskId,
          intent: 'provisional_timeframe',
        }
      : { sheet_type: 'campaign_board' }

  /* The staged selection's plain name, carried by the chat's
   * staging chip while the selection stands: the record's own
   * title where the selection is a record, and the board's own
   * names for the rest — the River, a Hold and its day, the Start
   * and Finish, the keeper of a load. */
  const stagedLabel = ((): string | null => {
    if (!focus && provisionalAskId) {
      const asked = overview.find((o) => o.project.id === provisionalAskId)
      return asked ? `${asked.project.title} — no timeframe yet` : null
    }
    if (!selection || !focus) return null
    switch (selection.kind) {
      case 'waypoint':
        return focus.projectTasks.find((t) => t.id === selection.taskId)?.title ?? null
      case 'obstacle':
        return focus.obstacles.find((o) => o.id === selection.obstacleId)?.label ?? null
      case 'terrain':
        return selection.feature.sourceLabel
      case 'signal':
        return focus.signalMarkers.find((m) => m.signal.id === selection.signalId)?.signal.title ?? null
      case 'river':
        return 'The River'
      case 'hold': {
        const hold = focus.holds.find((h) => h.id === selection.holdId)
        return hold ? `Hold · ${shortDate(new Date(hold.atMs))}` : null
      }
      case 'capacity':
        return focus.capacity.find((c) => c.personId === selection.personId)?.name ?? null
      case 'start':
        return `Start · ${shortDate(new Date(focus.span.startMs))}`
      case 'finish':
        return `Finish · ${shortDate(new Date(focus.span.endMs))}`
    }
  })()

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
    <SplitShell
      storageKey="campaign-board"
      left={
        <div className="p-3 lg:p-5 space-y-3">
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
              writeError={writeError}
            />
          ) : (
            <OverviewBoard
              overview={overview}
              initiatives={entities.initiatives}
              onFocus={(id) => { setFocusId(id); setSelection(null); setProvisionalAskId(null) }}
              onProvisionalAsk={(id) => setProvisionalAskId(id)}
            />
          )}
        </div>
      }
      right={
        <div className="p-3">
          <div className="rounded-2xl border border-stone-700/60 bg-stone-900/70 p-2">
            <CouncilChat
              key={conversationId}
              environment="workspace"
              initialArchetypeId="champion"
              conversationId={conversationId}
              context={chatContext}
              stagedLabel={stagedLabel}
              onStagedClear={() => { setSelection(null); setProvisionalAskId(null) }}
            />
          </div>
        </div>
      }
    />
  )
}

/* ================================================================== */
/* Overview — ONE shared map, projects nested under their initiatives  */
/* ================================================================== */

/**
 * The overview is a single map, not a list — and it follows the
 * standing display rule (founder, 2026-11-24: parents and loose
 * items only). Each initiative stands as a ground (its name
 * lettered on it, a camp marker at its head, its project count
 * beside the name) with its project lanes HIDDEN until the ground
 * is tapped open; the unanchored ground's camps — the loose
 * projects — always stand. Inside an open ground, dated projects
 * run dotted routes whose length is their recorded span on the one
 * shared scale (key drawn on the map). Undated projects stand
 * UNSPANNED at their camp — camp, obstacle ticks, and the finish flag
 * planted at the camp, no invented line; "no dates recorded" is said
 * in the camp popup, never as surface text. Tapping a route opens
 * its focus board; tapping a camp opens its popup.
 */

const OV_W = 480
const OV_CAMP_X = 46
/** A project lane is a small scene, not a symbol row (founder,
 *  2026-11-27): the project's stronghold stands at its start,
 *  its camp at the stronghold's foot, its declared terrain and
 *  obstacles painted along the route, and the finish banner at
 *  the route's end — the sprite kit painted from the campaign
 *  map, one piece per system definition. */
const OV_LANE_H = 132

/** Painted terrain by kind: sprite, display height, aspect. */
const OV_TERRAIN_SPRITES: Record<string, { src: string; h: number; ar: number }> = {
  mountain: { src: spriteMountain, h: 46, ar: 449 / 310 },
  hill: { src: spriteHill, h: 34, ar: 471 / 232 },
  open: { src: spriteOpenGround, h: 20, ar: 431 / 231 },
  grove: { src: spriteGrove, h: 40, ar: 421 / 354 },
  copse: { src: spriteCopse, h: 34, ar: 446 / 280 },
}

/** One painted piece standing on the map: centred on cx, its
 *  base on `base`. Never interactive — the lane's own targets
 *  carry every tap. */
function OvSprite({
  src,
  cx,
  base,
  h,
  ar,
  name,
}: {
  src: string
  cx: number
  base: number
  h: number
  ar: number
  name: string
}) {
  const w = h * ar
  return (
    <image
      data-testid="lane-sprite"
      data-sprite={name}
      href={src}
      x={cx - w / 2}
      y={base - h}
      width={w}
      height={h}
      style={{ pointerEvents: 'none' }}
    />
  )
}
const OV_GROUP_HEAD_H = 28
const OV_GROUP_PAD_TOP = 4
const OV_GROUP_PAD_BOT = 10
const OV_GROUP_GAP = 12
const OV_TOP_PAD = 12
const OV_KEY_STRIP = 44
/** Fixed cluster width for an unspanned project's ticks + flag: a
 *  camp grouping, never a scaled length. */
/** Where an unspanned lane's obstacle markers cluster: past
 *  the stronghold and its camp, which stand at the lane's
 *  start. */
const OV_UNSPANNED_CLUSTER = 104
/** The scale key's settings, in toggle order (founder,
 *  2026-11-27): the key is a toggle through period counts —
 *  three periods make a day, five make a week, seven make a
 *  month. A route is divided into periods at the toggled
 *  setting: a job's timeline is its span counted in periods,
 *  so finer settings stretch every timeline out. A month
 *  counts 30 days, the board's nominal month. */
const OV_KEY_UNITS = [
  { id: 'day', days: 1, periods: 3 },
  { id: 'week', days: 7, periods: 5 },
  { id: 'month', days: 30, periods: 7 },
] as const
/** The key's own dot pitch — fixed and legible at every
 *  setting; the routes' pitch adapts so the longest route
 *  fits the map (see dotPitch below). */
const OV_KEY_DOT_PITCH = 8.1
type OvKeyUnit = (typeof OV_KEY_UNITS)[number]['id']
/** The founder's painted campaign map (supplied 2026-11-27) —
 *  screen one's ground. Native 1122×1402; drawn at the panel's
 *  width and faded into the parchment before the key strip. */
const OV_ART_W = 1122
const OV_ART_H = 1402

function OverviewBoard({
  overview,
  initiatives,
  onFocus,
  onProvisionalAsk,
}: {
  overview: OverviewProject[]
  initiatives: { id: string; title: string }[]
  onFocus: (projectId: string) => void
  onProvisionalAsk: (projectId: string) => void
}) {
  const [popupId, setPopupId] = useState<string | null>(null)
  const [openInitiativeId, setOpenInitiativeId] = useState<string | null>(null)
  const [keyUnit, setKeyUnit] = useState<OvKeyUnit>('day')
  const groups = groupOverviewByInitiative(overview, initiatives)
  // The period model (founder, 2026-11-27): at the key's
  // setting, one period lasts unit-days / periods (a third of
  // a day, 1.4 days, or ~4.3 days). A spanned job's timeline
  // is its span counted in whole periods — at least one — and
  // drawn at a shared dot pitch that adapts so the longest
  // timeline fits the map, capped at the key's own pitch.
  const keyUnitDef = OV_KEY_UNITS.find((u) => u.id === keyUnit)!
  const periodDays = keyUnitDef.days / keyUnitDef.periods
  const periodsFor = (days: number) => Math.max(1, Math.round(days / periodDays))
  const maxPeriods = Math.max(1, ...overview.filter((o) => o.spanned).map((o) => periodsFor(o.span.days)))
  const dotPitch = Math.min(OV_KEY_DOT_PITCH, (OV_W - OV_CAMP_X - 108) / maxPeriods)

  // Lay out the grounds top to bottom. An initiative's ground is
  // closed by default — header only, no lanes — until tapped
  // open; the unanchored ground (loose projects) always stands
  // open. Lanes keep their board-order colours whether shown or
  // not, so opening a ground never recolours another lane.
  let cursor = OV_TOP_PAD
  let colorSeq = 0
  const laidOut = groups.map((group, gi) => {
    const headH = group.initiative ? OV_GROUP_HEAD_H : 6
    const isOpen = !group.initiative || openInitiativeId === group.initiative.id
    const shown = isOpen ? group.projects : []
    const y = cursor
    const height = headH + OV_GROUP_PAD_TOP + shown.length * OV_LANE_H + OV_GROUP_PAD_BOT
    cursor += height + OV_GROUP_GAP
    const lanes = shown.map((o, li) => ({
      o,
      laneTop: y + headH + OV_GROUP_PAD_TOP + li * OV_LANE_H,
      color: PROJECT_COLORS[colorSeq++ % PROJECT_COLORS.length],
    }))
    if (!isOpen) colorSeq += group.projects.length
    return { group, gi, y, height, lanes, isOpen }
  })
  const height = Math.max(cursor - OV_GROUP_GAP + OV_KEY_STRIP, 200)
  const keyY = height - 18
  // The scale key shows the setting itself: the unit's period
  // count as a dotted line — three dots for a day, five for a
  // week, seven for a month — at the key's fixed dot pitch.
  // Layout: 'inline' when line + label fit one row (the
  // standing look); 'stacked' when they don't, the label
  // dropping below the line's start.
  const keyLabel = `[-----] = 1 ${keyUnit}`
  const keyLen = keyUnitDef.periods * OV_KEY_DOT_PITCH
  const keyLayout =
    OV_CAMP_X + keyLen + 10 + estimateLabelWidth(keyLabel, 11.5) <= OV_W - 8 ? 'inline' : 'stacked'
  // The painted map fills the panel's width at the top; on a
  // tall board it ends (and fades) well above the key strip,
  // on a short board it is cropped at the strip — the key
  // always sits on plain parchment.
  const artH = Math.min((OV_W * OV_ART_H) / OV_ART_W, Math.max(height - OV_KEY_STRIP, 0))
  const popupEntry = popupId
    ? laidOut.flatMap((l) => l.lanes).find((l) => l.o.project.id === popupId)
    : undefined

  const diamond = (cx: number, cy: number, s: number) =>
    `M ${cx} ${cy - s} L ${cx + s} ${cy} L ${cx} ${cy + s} L ${cx - s} ${cy} Z`

  return (
    <section aria-label="Campaign Board — all projects">
      <h1 className="text-lg font-semibold text-stone-100 px-1 pb-2">Campaign Board</h1>
      <div className="rounded-2xl overflow-hidden border border-[#9a7b24]/50 shadow-lg">
        <svg
          viewBox={`0 0 ${OV_W} ${height}`}
          className="w-full block"
          role="img"
          aria-label="All projects on one map, nested under their initiatives"
        >
          <rect width={OV_W} height={height} fill={PARCHMENT} />
          {/* Screen one is the founder's painted campaign map
              (2026-11-27): the grounds stand on the painting.
              It fills the panel's width at the top and fades
              into the parchment at its lower edge. The painting
              is washed to half strength over the parchment —
              at full strength its own painted lettering (the
              banner, the legend scroll) fought the board's
              lettering (founder's verdict on the first pass,
              2026-11-27 evening); washed, it reads as the land
              under the camps. */}
          <image
            href={campaignMapArt}
            x={0}
            y={0}
            width={OV_W}
            height={artH}
            opacity={0.5}
            preserveAspectRatio="xMidYMin slice"
            style={{ pointerEvents: 'none' }}
          />
          <rect
            x={0}
            y={Math.max(artH - 90, 0)}
            width={OV_W}
            height={Math.min(90, artH)}
            fill="url(#ov-art-fade)"
            style={{ pointerEvents: 'none' }}
          />
          <defs>
            <linearGradient id="ov-art-fade" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor={PARCHMENT} stopOpacity="0" />
              <stop offset="1" stopColor={PARCHMENT} stopOpacity="1" />
            </linearGradient>
          </defs>
          {overview.length === 0 && (
            <text x={OV_W / 2} y={height / 2} textAnchor="middle" fontSize="14" fill={INK}>
              No projects yet — the board is empty.
            </text>
          )}
          {laidOut.map(({ group, gi, y, height: groupH, lanes, isOpen }) => (
            <g key={group.initiative?.id ?? 'unanchored'}>
              {/* the initiative's ground */}
              <rect
                x={10}
                y={y}
                width={OV_W - 20}
                height={groupH}
                rx={14}
                fill={group.initiative ? (gi % 2 === 0 ? '#e0d0a4' : '#d5dbb0') : '#eae0c6'}
                fillOpacity={0.7}
                stroke="#9a7b24"
                strokeOpacity={0.35}
              />
              {group.initiative && (
                <g style={{ pointerEvents: 'none' }}>
                  {/* the shared camp marker at the head of the ground */}
                  <path d={`M 22 ${y + 22} L 30 ${y + 11} L 38 ${y + 22} Z`} fill="none" stroke={INK} strokeWidth="1.6" />
                  <line x1={30} y1={y + 11} x2={30} y2={y + 4} stroke={INK} strokeWidth="1.4" />
                  <path d={`M 30 ${y + 4} L 37 ${y + 6.5} L 30 ${y + 9} Z`} fill={EMBER} />
                  <text
                    x={48}
                    y={y + 20}
                    fontSize="11.5"
                    fontWeight="700"
                    letterSpacing="1.6"
                    fill="#6d5c22"
                  >
                    {group.initiative.title.toUpperCase()}
                  </text>
                  {/* the ground's count — an aggregate fact about
                      the parent, lettered beside its name */}
                  <text
                    x={OV_W - 24}
                    y={y + 20}
                    textAnchor="end"
                    fontSize="10.5"
                    fill="#6d5c22"
                  >
                    {group.projects.length} {group.projects.length === 1 ? 'project' : 'projects'}
                  </text>
                </g>
              )}
              {group.initiative && (
                /* the ground is the door to its projects: tap
                   toggles the ground open or closed. Lanes render
                   after this rect, so their own tap targets stand
                   above it when the ground is open. */
                <rect
                  x={10}
                  y={y}
                  width={OV_W - 20}
                  height={groupH}
                  fill="#000"
                  fillOpacity={0}
                  style={{ cursor: 'pointer' }}
                  data-initiative-ground={group.initiative.id}
                  aria-label={`${isOpen ? 'Close' : 'Open'} ${group.initiative.title}`}
                  onClick={() =>
                    setOpenInitiativeId((cur) =>
                      cur === group.initiative!.id ? null : group.initiative!.id,
                    )
                  }
                />
              )}
              {lanes.map(({ o, laneTop, color }) => {
                const lineY = laneTop + 74
                const lineLen = periodsFor(o.span.days) * dotPitch
                const endX = OV_CAMP_X + lineLen
                // Where the finish flag stands: at the route's end when
                // spanned; planted at the camp when unspanned.
                const flagX = o.spanned
                  ? endX
                  : OV_CAMP_X + OV_UNSPANNED_CLUSTER + o.obstacles.slice(0, 8).length * 13 + 6
                return (
                  <g key={o.project.id}>
                    <text x={OV_CAMP_X} y={laneTop + 15} fontSize="14" fontWeight="600" fill={INK} style={{ pointerEvents: 'none' }}>
                      {o.project.title}
                    </text>
                    {/* The project's seat and its muster point:
                        the stronghold stands at the lane's start,
                        the camp at its foot, spanned or not. */}
                    <OvSprite src={spriteStronghold} name="stronghold" cx={OV_CAMP_X + 18} base={lineY - 2} h={56} ar={446 / 326} />
                    <OvSprite src={spriteCamp} name="camp" cx={OV_CAMP_X + 74} base={lineY + 34} h={30} ar={409 / 359} />
                    {o.spanned &&
                      o.terrain
                        .filter((f) => f.kind === 'open')
                        .map((f) => {
                          const s = OV_TERRAIN_SPRITES[f.kind]
                          return (
                            <OvSprite
                              key={`${f.kind}-${f.taskId}`}
                              src={s.src}
                              name={f.kind}
                              cx={OV_CAMP_X + f.fraction * lineLen}
                              base={lineY + 8}
                              h={s.h}
                              ar={s.ar}
                            />
                          )
                        })}
                    {o.spanned ? (
                      <>
                        <text x={OV_CAMP_X} y={laneTop + 122} fontSize="10.5" fill="#6b5a43" style={{ pointerEvents: 'none' }}>
                          {o.span.days} days · {shortDate(new Date(o.span.startMs))} – {shortDate(new Date(o.span.endMs))}
                        </text>
                        {/* The project's declared terrain stands
                            along its route where its anchor steps
                            stand — the mountain for its greatest
                            effort, groves and copses for its
                            branching steps. */}
                        {o.terrain
                          .filter((f) => f.kind !== 'open')
                          .map((f) => {
                            const s = OV_TERRAIN_SPRITES[f.kind]
                            return (
                              <OvSprite
                                key={`${f.kind}-${f.taskId}`}
                                src={s.src}
                                name={f.kind}
                                cx={OV_CAMP_X + f.fraction * lineLen}
                                base={lineY - 2}
                                h={s.h}
                                ar={s.ar}
                              />
                            )
                          })}
                        {/* Obstacles stand on the route as crags. */}
                        {o.obstacles.slice(0, 8).map((ob) => (
                          <OvSprite
                            key={ob.id}
                            src={spriteCrag}
                            name="obstacle-crag"
                            cx={OV_CAMP_X + ob.fraction * lineLen}
                            base={lineY - 2}
                            h={30}
                            ar={419 / 305}
                          />
                        ))}
                        {/* The route is its span counted in
                            periods at the key's setting (founder,
                            2026-11-27): one dot per period, at
                            the shared dot pitch — toggling the
                            key re-divides every route, and finer
                            settings stretch the timelines out.
                            When the pitch runs too fine to bead,
                            the line stands solid — the dots have
                            merged, which is the density read. */}
                        <line
                          data-testid="route-line"
                          x1={OV_CAMP_X}
                          y1={lineY}
                          x2={endX}
                          y2={lineY}
                          stroke={color}
                          strokeWidth="5"
                          strokeLinecap="round"
                          strokeDasharray={dotPitch >= 1.2 ? `0.1 ${dotPitch - 0.1}` : undefined}
                          style={{ pointerEvents: 'none' }}
                        />
                      </>
                    ) : (
                      <>
                        {/* Unspanned: no route is drawn. The obstacle
                            ticks cluster at the camp as markers, not
                            positions on a scale. */}
                        {o.obstacles.slice(0, 8).map((ob, ti) => (
                          <path
                            key={ob.id}
                            d={diamond(OV_CAMP_X + OV_UNSPANNED_CLUSTER + ti * 13, lineY, 5)}
                            fill="#8c2e1e"
                            stroke="#fff"
                            strokeWidth="1"
                            opacity="0.95"
                            style={{ pointerEvents: 'none' }}
                          />
                        ))}
                      </>
                    )}
                    {/* The finish: the painted banner at a recorded
                        end; the small outline flag while the
                        finish is not yet dated. */}
                    {o.spanned ? (
                      <OvSprite src={spriteFinishBanner} name="finish-banner" cx={endX} base={lineY + 6} h={52} ar={422 / 384} />
                    ) : (
                      <g style={{ pointerEvents: 'none' }}>
                        <line x1={flagX} y1={lineY} x2={flagX} y2={lineY - 15} stroke={INK} strokeWidth="1.8" />
                        <path
                          d={`M ${flagX} ${lineY - 15} L ${flagX + 12} ${lineY - 11.5} L ${flagX} ${lineY - 8} Z`}
                          fill="none"
                          stroke={EMBER}
                          strokeWidth="1.2"
                        />
                      </g>
                    )}
                    {o.obstacles.length > 0 && (
                      <text x={(o.spanned ? endX + 36 : flagX + 20)} y={lineY + 4} fontSize="11.5" fill="#8c2e1e" style={{ pointerEvents: 'none' }}>
                        ◆ ×{o.obstacles.length}
                      </text>
                    )}
                    {/* the lane is the route's tap target — focus */}
                    <rect
                      x={14}
                      y={laneTop + 2}
                      width={OV_W - 28}
                      height={OV_LANE_H - 4}
                      fill="#000"
                      fillOpacity={0}
                      style={{ cursor: 'pointer' }}
                      onClick={() => onFocus(o.project.id)}
                    />
                    {/* the camp's own tap target — its popup */}
                    <circle
                      cx={OV_CAMP_X}
                      cy={lineY}
                      r="15"
                      fill="#000"
                      fillOpacity={0}
                      style={{ cursor: 'pointer' }}
                      onClick={(e) => {
                        e.stopPropagation()
                        setPopupId((prev) => (prev === o.project.id ? null : o.project.id))
                      }}
                    />
                    {/* No timeframe recorded: a red ! stands by
                        the camp (founder, 2026-11-27). Tapping it
                        stages the project in Valen's chat, where
                        he asks for a provisional timeframe. It
                        renders last in the lane so its tap target
                        stands above the lane's own. */}
                    {!o.spanned &&
                      (() => {
                        const bangX = flagX + 20 + (o.obstacles.length > 0 ? 36 : 0)
                        return (
                          <g
                            data-testid="no-timeframe-bang"
                            style={{ cursor: 'pointer' }}
                            onClick={(e) => {
                              e.stopPropagation()
                              onProvisionalAsk(o.project.id)
                            }}
                          >
                            <circle cx={bangX + 3} cy={lineY} r="13" fill="#000" fillOpacity={0} />
                            <text
                              x={bangX}
                              y={lineY + 6}
                              fontSize="17"
                              fontWeight="800"
                              fill="#b3261e"
                              style={{ pointerEvents: 'none' }}
                            >
                              !
                            </text>
                          </g>
                        )
                      })()}
                  </g>
                )
              })}
            </g>
          ))}
          {/* scale key — the period toggle (founder, 2026-11-27):
              tapping the key strip cycles the setting — three
              periods to a day, five to a week, seven to a month —
              and every route on the map re-divides to match. The
              key's line is the setting's own period count in
              dots. */}
          <g data-testid="scale-key">
            {keyLayout === 'inline' && (
              <>
                <line
                  x1={OV_CAMP_X}
                  y1={keyY}
                  x2={OV_CAMP_X + keyLen}
                  y2={keyY}
                  stroke={INK}
                  strokeWidth="4"
                  strokeLinecap="round"
                  strokeDasharray="0.1 8"
                />
                <text x={OV_CAMP_X + keyLen + 10} y={keyY + 4} fontSize="11.5" fontWeight="600" fill={INK}>
                  {keyLabel}
                </text>
              </>
            )}
            {keyLayout === 'stacked' && (
              <>
                <line
                  x1={OV_CAMP_X}
                  y1={keyY - 8}
                  x2={OV_CAMP_X + keyLen}
                  y2={keyY - 8}
                  stroke={INK}
                  strokeWidth="4"
                  strokeLinecap="round"
                  strokeDasharray="0.1 8"
                />
                <text x={OV_CAMP_X} y={keyY + 13} fontSize="11.5" fontWeight="600" fill={INK}>
                  {keyLabel}
                </text>
              </>
            )}
            {/* the key strip is the toggle's tap target */}
            <rect
              x={8}
              y={height - OV_KEY_STRIP}
              width={OV_W - 16}
              height={OV_KEY_STRIP}
              fill="#000"
              fillOpacity={0}
              style={{ cursor: 'pointer' }}
              onClick={() =>
                setKeyUnit(
                  (u) => OV_KEY_UNITS[(OV_KEY_UNITS.findIndex((k) => k.id === u) + 1) % OV_KEY_UNITS.length].id,
                )
              }
            />
          </g>
          {/* camp popup — the project's facts, incl. the undated fact
              that is never printed on the surface */}
          {popupEntry && (
            <g>
              <rect
                x={0}
                y={0}
                width={OV_W}
                height={height}
                fill="#000"
                fillOpacity={0}
                onClick={() => setPopupId(null)}
              />
              {(() => {
                const o = popupEntry.o
                const panelW = 252
                const panelH = 98
                const px = Math.min(Math.max(OV_CAMP_X - 6, 8), OV_W - panelW - 8)
                const below = popupEntry.laneTop + OV_LANE_H + panelH + 6 <= height - OV_KEY_STRIP
                const py = below
                  ? popupEntry.laneTop + OV_LANE_H + 2
                  : Math.max(8, popupEntry.laneTop - panelH - 6)
                return (
                  <g>
                    <rect x={px} y={py} width={panelW} height={panelH} rx={10} fill="#fbf5df" stroke="#9a7b24" />
                    <text x={px + 12} y={py + 20} fontSize="13" fontWeight="700" fill={INK}>
                      {o.project.title}
                    </text>
                    <text x={px + 12} y={py + 38} fontSize="11" fill="#6b5a43">
                      {o.project.status} · {o.openTaskCount} open · {o.doneTaskCount} done
                    </text>
                    <text x={px + 12} y={py + 54} fontSize="11" fill="#6b5a43">
                      {o.spanned
                        ? `${shortDate(new Date(o.span.startMs))} – ${shortDate(new Date(o.span.endMs))} · ${o.span.days} days`
                        : 'No dates recorded'}
                    </text>
                    {o.obstacles.length > 0 && (
                      <text x={px + 12} y={py + 70} fontSize="11" fill="#8c2e1e">
                        ◆ ×{o.obstacles.length} — detail in focus
                      </text>
                    )}
                    <g
                      style={{ cursor: 'pointer' }}
                      onClick={() => {
                        setPopupId(null)
                        onFocus(o.project.id)
                      }}
                    >
                      <rect x={px + 12} y={py + panelH - 26} width={88} height={20} rx={10} fill={EMBER} />
                      <text x={px + 56} y={py + panelH - 12} textAnchor="middle" fontSize="11" fontWeight="600" fill="#fff">
                        Focus →
                      </text>
                    </g>
                  </g>
                )
              })()}
            </g>
          )}
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
  writeError,
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
  writeError: string | null
}) {
  const { project, span, obstacles, terrain, routes, signalMarkers, capacity, rivers, holds } = focus
  const dragOverride = drag ? { taskId: drag.taskId, fraction: drag.fraction } : null
  const aPts = routePoints(routes.a.filter((w) => !w.done), ROUTE_A_Y, dragOverride)
  const bPts = routePoints(routes.b, ROUTE_B_Y, dragOverride)
  const allWaypoints: { w: BoardWaypoint; bandY: number; index: number }[] = [
    ...routes.a.map((w, index) => ({ w, bandY: ROUTE_A_Y, index })),
    ...routes.b.map((w, index) => ({ w, bandY: ROUTE_B_Y, index })),
  ]

  /* Label de-overlap (diagnosis 2026-11-25): waypoint pairs, the
   * start/finish banner labels, and obstacle labels are laid out as
   * boxes by layoutBoardLabels — until this pass, placement was a
   * pure function of fraction and index and the lettering collided
   * wherever dates cluster, above all at the finish. The items carry
   * each label's natural anchor (the positions it would have had);
   * the pass returns placements that never overlap and stay on the
   * map. Rendering below reads the placement back as an offset inside
   * each label's own group, so handlers and structure are unchanged.
   * The anchors are committed fractions only (drag-stability fix,
   * 2026-11-25): during a drag the whole layout stands frozen and
   * the dragged waypoint's label rides its dot at the frozen offset. */
  const waypointTitle = (w: BoardWaypoint): string =>
    w.task.title.length > 26 ? `${w.task.title.slice(0, 25)}…` : w.task.title
  const obstacleLabelText = (ob: BoardObstacle): string =>
    ob.kind === 'gate' ? 'Gate Keeper' : ob.kind === 'crossing' ? 'Crossing' : ob.kindLabel
  const obstacleLabelY = (ob: BoardObstacle): number =>
    ob.kind === 'gate' ? 30 : ob.kind === 'crossing' ? 32 : 26
  const labelItems: BoardLabelItem[] = [
    {
      id: 'banner:start',
      anchorX: X0,
      top: MID_Y + 28 - 11,
      width: estimateLabelWidth(`Start · ${shortDate(new Date(span.startMs))}`, 11),
      height: 14,
    },
    {
      id: 'banner:finish',
      anchorX: X1,
      top: MID_Y + 30 - 11,
      width: estimateLabelWidth(`Finish · ${shortDate(new Date(span.endMs))}`, 11),
      height: 14,
    },
    ...obstacles.map((ob) => ({
      id: `obstacle:${ob.id}`,
      anchorX: xForFraction(ob.fraction),
      top: MID_Y + obstacleLabelY(ob) - 11,
      width: estimateLabelWidth(obstacleLabelText(ob), 10.5),
      height: 14,
    })),
    ...allWaypoints.map(({ w, bandY, index }) => {
      // The label layout is a property of the COMMITTED board: its
      // anchors are the recorded fractions only, never the drag's
      // provisional one. Feeding the live drag fraction in here made
      // the de-overlap pass re-solve every label on every pointer
      // move — neighbours shoved, swapped sides, and cascaded while
      // one node was dragged (founder report 2026-11-25). The
      // dragged node's label instead follows its node rigidly, at
      // the offset this frozen layout gave it (see the waypoint
      // render below); the layout re-solves once, at release, when
      // the commit lands — like every other data change.
      const f = w.fraction
      const tier = index % 2 === 0 ? 30 : 46
      const sub = w.done ? 'done' : shortDate(dateAtFraction(span, f))
      return {
        id: `waypoint:${bandY}:${w.task.id}`,
        anchorX: xForFraction(f),
        top: waypointY(bandY, index) + tier - 11,
        width: Math.max(estimateLabelWidth(waypointTitle(w), 11), estimateLabelWidth(sub, 10)),
        height: 27,
      }
    }),
  ]
  const labelPlacements = new Map<string, BoardLabelPlacement>(
    layoutBoardLabels(labelItems, { minX: 8, maxX: MAP_W - 8, minY: 8, maxY: FOCUS_H - 8 }).map(
      (p) => [p.id, p],
    ),
  )
  const placedLabel = (id: string): BoardLabelPlacement | undefined => labelPlacements.get(id)
  const startLabel = placedLabel('banner:start')
  const finishLabel = placedLabel('banner:finish')
  const terrainAt = (taskId: string): { x: number; y: number } => {
    const onA = routes.a.find((w) => w.task.id === taskId)
    if (onA) return { x: xForFraction(onA.fraction), y: ROUTE_A_Y }
    return { x: X0 + 40, y: ROUTE_A_Y }
  }

  // A tap stages tentatively — selection only, no card, no write.
  // The conversation with Valen is where the staged thing is
  // discussed and where anything about it is decided or recorded.
  const openWaypoint = (taskId: string) => {
    setSelection({ kind: 'waypoint', taskId })
  }

  const openEndpoint = (kind: 'start' | 'finish') => {
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
      </div>
      {writeError && <p className="px-1 pb-2 text-xs text-red-300">{writeError}</p>}

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
            const staged = selection?.kind === 'river' && selection.riverId === river.id
            return (
              <g
                key={river.id}
                style={{ cursor: 'pointer' }}
                onClick={() => setSelection({ kind: 'river', riverId: river.id })}
              >
                <rect x={bx0} y={top} width={Math.max(10, bx1 - bx0)} height={bottom - top} fill="#7fa8b8" opacity="0.38" />
                {staged && (
                  <rect x={bx0} y={top} width={Math.max(10, bx1 - bx0)} height={bottom - top} fill="none" stroke="#33617a" strokeWidth="2" />
                )}
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
            const lp = placedLabel(`obstacle:${ob.id}`)
            const labelX = lp ? lp.x - x : 0
            const labelY = lp ? lp.top + 11 - MID_Y : obstacleLabelY(ob)
            return (
              <g
                key={ob.id}
                transform={`translate(${x},${MID_Y})`}
                style={{ cursor: 'pointer' }}
                onClick={() => setSelection({ kind: 'obstacle', obstacleId: ob.id })}
              >
                {selection?.kind === 'obstacle' && selection.obstacleId === ob.id && (
                  <circle r="15" fill="none" stroke={EMBER} strokeWidth="2" />
                )}
                {isGate ? (
                  <>
                    <rect x="-16" y="-13" width="5" height="24" fill="#8d8574" stroke="#5f594c" />
                    <rect x="11" y="-13" width="5" height="24" fill="#8d8574" stroke="#5f594c" />
                    <rect x="-19" y="-18" width="38" height="5" rx="2" fill="#75705f" />
                    <text x={labelX} y={labelY} textAnchor="middle" fontSize="10.5" fill="#7a5a12">
                      Gate Keeper
                    </text>
                  </>
                ) : isCrossing ? (
                  <>
                    <path d="M-13 8 L0 -8 L13 8" fill="none" stroke="#33655f" strokeWidth="2.6" />
                    <path d="M-13 15 L0 -1 L13 15" fill="none" stroke="#33655f" strokeWidth="2.6" opacity="0.6" />
                    <text x={labelX} y={labelY} textAnchor="middle" fontSize="10.5" fill="#33655f">
                      Crossing
                    </text>
                  </>
                ) : (
                  <>
                    <path d="M0 -9 L7 0 L0 9 L-7 0 Z" fill={ob.kind === 'overdue' ? '#a8741a' : '#8c2e1e'} stroke={INK} strokeWidth="0.8" />
                    <text x={labelX} y={labelY} textAnchor="middle" fontSize="10.5" fill={ob.kind === 'overdue' ? '#7a5a12' : '#8c2e1e'}>
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
                {selection?.kind === 'signal' && selection.signalId === m.signal.id && (
                  <circle r="13" fill="none" stroke={EMBER} strokeWidth="2" />
                )}
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
                  <rect x="-4" y="-13" width="106" height="24" rx="12" fill={c.over ? '#f3d9cf' : '#e7dfc8'} stroke={selection?.kind === 'capacity' && selection.personId === c.personId ? EMBER : c.over ? EMBER : '#9a7b24'} strokeWidth={selection?.kind === 'capacity' && selection.personId === c.personId ? 2.4 : 1.2} />
                  <text x="6" y="4" fontSize="10.5" fontWeight="600" fill={c.over ? '#8c2e1e' : INK} style={{ pointerEvents: 'none' }}>
                    {c.name.split(' ')[0]} · {label}
                    {c.over ? ' · over' : ''}
                  </text>
                </g>
              )
            })}

          {/* start camp + finish banner */}
          <g transform={`translate(${X0},${MID_Y})`} style={{ cursor: 'pointer' }} onClick={() => openEndpoint('start')}>
            {selection?.kind === 'start' && <circle r="16" fill="none" stroke={EMBER} strokeWidth="2" />}
            <path d="M-13 10 L0 -12 L13 10 Z" fill="#8a6a42" stroke="#6b5133" strokeWidth="1.2" />
            <text x={startLabel ? startLabel.x - X0 : 0} y={startLabel ? startLabel.top + 11 - MID_Y : 28} textAnchor="middle" fontSize="11" fill={INK}>
              Start · {shortDate(new Date(span.startMs))}
            </text>
          </g>
          <g transform={`translate(${X1},${MID_Y})`} style={{ cursor: 'pointer' }} onClick={() => openEndpoint('finish')}>
            {selection?.kind === 'finish' && <circle r="16" fill="none" stroke={EMBER} strokeWidth="2" />}
            <line x1="0" y1="12" x2="0" y2="-24" stroke={INK} strokeWidth="2.2" />
            <path d="M0 -24 L20 -19 L0 -14 Z" fill={EMBER} />
            <text x={finishLabel ? finishLabel.x - X1 : 0} y={finishLabel ? finishLabel.top + 11 - MID_Y : 30} textAnchor="middle" fontSize="11" fill={INK}>
              Finish · {shortDate(new Date(span.endMs))}
            </text>
          </g>

          {/* waypoints */}
          {allWaypoints.map(({ w, bandY, index }) => {
            const f = drag && drag.taskId === w.task.id ? drag.fraction : w.fraction
            const x = xForFraction(f)
            const y = waypointY(bandY, index)
            const labelTier = index % 2 === 0 ? 30 : 46
            const lp = placedLabel(`waypoint:${bandY}:${w.task.id}`)
            // The placement is read against the node's COMMITTED
            // anchor, so the label's offset from its node is
            // constant: at rest x IS the committed anchor and this
            // reads exactly as before; during a drag the label rides
            // the node rigidly at its frozen offset rather than
            // being re-solved against the provisional position.
            const labelX = lp ? lp.x - xForFraction(w.fraction) : 0
            const titleY = lp ? lp.top + 11 - y : labelTier
            const subY = lp ? lp.top + 24 - y : labelTier + 13
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
                {selection?.kind === 'waypoint' && selection.taskId === w.task.id && (
                  <circle r="13.5" fill="none" stroke={EMBER} strokeWidth="2" />
                )}
                {w.done ? (
                  <>
                    <circle r="9" fill="#54683f" stroke="#f1e8d0" strokeWidth="1.6" />
                    <path d="M-4 0 L-1 3 L4 -3" fill="none" stroke="#f1e8d0" strokeWidth="1.8" strokeLinecap="round" />
                  </>
                ) : (
                  <circle r="9" fill={bandY === ROUTE_A_Y ? '#a63d2a' : '#33655f'} stroke="#f1e8d0" strokeWidth="1.6" />
                )}
                <text x={labelX} y={titleY} textAnchor="middle" fontSize="11" fill={INK} style={{ pointerEvents: 'none' }}>
                  {waypointTitle(w)}
                </text>
                <text x={labelX} y={subY} textAnchor="middle" fontSize="10" fill="#6b5a43" style={{ pointerEvents: 'none' }}>
                  {w.done ? 'done' : shortDate(dateAtFraction(span, f))}
                </text>
              </g>
            )
          })}

          {/* holds — review checkpoints recorded in conversation; a tap
              stages one tentatively. Moving or removing a hold is a
              conversational act with Valen, never a surface drag. */}
          {holds.map((h) => {
            const f = fractionForDate(span, h.atMs)
            const x = xForFraction(f)
            const staged = selection?.kind === 'hold' && selection.holdId === h.id
            return (
              <g
                key={h.id}
                transform={`translate(${x},${MID_Y})`}
                style={{ cursor: 'pointer' }}
                onClick={() => setSelection({ kind: 'hold', holdId: h.id })}
              >
                <circle r="17" fill="transparent" />
                {staged && <circle r="15" fill="none" stroke="#a8741a" strokeWidth="2" />}
                <line x1="0" y1="8" x2="0" y2="-16" stroke="#6b5133" strokeWidth="2.2" />
                <path d="M0 -16 L14 -12.5 L0 -9 Z" fill="#a8741a" />
                <ellipse cx="-5" cy="10" rx="7" ry="3.4" fill="#8d8574" stroke="#5f594c" strokeWidth="0.8" />
                <ellipse cx="5" cy="10" rx="7" ry="3.4" fill="#9a927f" stroke="#5f594c" strokeWidth="0.8" />
                <ellipse cx="0" cy="6.5" rx="5.5" ry="3" fill="#a39a86" stroke="#5f594c" strokeWidth="0.8" />
                <text y="30" textAnchor="middle" fontSize="10.5" fontWeight="600" fill="#7a5a12" style={{ pointerEvents: 'none' }}>
                  Hold
                </text>
                <text y="43" textAnchor="middle" fontSize="10" fill="#6b5a43" style={{ pointerEvents: 'none' }}>
                  {shortDate(new Date(h.atMs))}
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
          {stripWaypointLabels(routes.a, span).map((label) => (
            <g key={label.fraction} transform={`translate(${xForFraction(label.fraction)},30)`}>
              <line y1="-6" y2="6" stroke={INK} strokeWidth="1.4" />
              <text y={24} textAnchor="middle" fontSize="9.5" fill="#6b5a43">
                {label.text}
              </text>
            </g>
          ))}
        </svg>
      </div>
    </section>
  )
}
