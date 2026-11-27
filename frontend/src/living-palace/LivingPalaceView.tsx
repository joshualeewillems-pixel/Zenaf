/**
 * The Living Palace — Maeve's seat home (the fifth seat world).
 *
 * Landing is the standing seat pattern (SEAT_HOME_NAV → guardian):
 * the split screen, the world on the left and Maeve's chat on the
 * right, the divider draggable, the panes scrolling independently,
 * and the chat's subject following the visitor's selections — a
 * building, a project, a room, or an idea on the drawing table rides
 * into her conversation through the same subject carriage the other
 * worlds use (sheet_type "living_palace", PRs #422/#424/#425's seam,
 * extended to this sheet). The descent is the founder's frame model
 * (2026-11-26): compound (parent tier) → the dome at project level
 * → the dome at task level → the room (task frame). The floor-plan
 * frame that once stood between the dome and the room is retired;
 * the dome serves both levels, and a project's subject carriage is
 * exactly what it was on the floor layer.
 *
 * The world reads the visitor's real Vision Execution records via
 * palaceApi. This surface writes NOTHING — the chat-is-the-work law
 * (founder, 2026-11-25 13:44 PT): "For all interfaces. The chat is
 * the work, the images are metaphors." The verdict buttons (#432)
 * and the weighing panel (#433) that once lived here are superseded
 * as forms; their semantics live in Maeve's conversation now — she
 * carries the room's state into her prompt (the room-state block),
 * rulings land through her verdict tail, and a weighing settles
 * only through the visitor's own settle words in chat. What a tap
 * does here is stage, never settle:
 *
 * Tentative population (founder ruling 2026-11-25 13:56 PT): a tap
 * on the room's furniture — the scales, the vessel, the chest, the
 * table, the threshold, the hearth, a guest object — stages that
 * object in the chat tentatively (the turn context's palace_focus).
 * It writes nothing to the ledger; clicking away discards it
 * silently; it joins the ledger only via the per-message context
 * snapshot when the visitor sends a turn while it is staged.
 *
 * The shared attributed subject read (founder ruling 2026-11-25)
 * still composes this world's drawn expressions per subject,
 * fetched as the visitor enters a project or room: the vessel's gold
 * seam, earned only by an accepted supersession, and the guest
 * objects — a seat's object stands only where the read shows that
 * seat attending the subject, with two slim doors: explore here
 * with Maeve (which stages the object), or follow into the seat's
 * world. After a chat turn lands, the view re-reads the subject and
 * the entities (the Scroll #431 precedent): conversation is where
 * the record changes now, and the world reflects it.
 *
 * Boundaries: there is NO per-subject boundary store and this
 * surface invents none — the threshold is an affordance, and its
 * states ride to Maeve in her room-state block, where boundaries
 * are discovered and examined with her; establishing them stays
 * the visitor's alone.
 */
import * as React from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import CouncilChat from '../chat/CouncilChat'
import SplitShell from '../components/SplitShell'
import { SEAT_COLORS, type SeatId } from '../council/colors'
import type { Idea } from '../vision-execution/types'
import {
  attendingGuests,
  buildBuilding,
  buildCompound,
  buildLooseTaskLevel,
  buildRoom,
  buildTaskLevel,
  GUEST_OBJECTS,
  type AttributedRead,
  type PalaceData,
} from './palaceLogic'
import {
  fetchAttributedRead,
  fetchPalaceEntities,
  fetchPalaceLayout,
  fetchSubjectInteractions,
  savePalaceLayout,
} from './palaceApi'
import type { SubjectInteraction } from './palaceSceneLogic'
import { plateForFloor, taskSizeWeight, type RoomPlate } from './palaceScene2Logic'
import {
  planOverheadLayout,
  type OverheadArtifactKind,
  type OverheadLayout,
} from './palaceOverheadLogic'
import { BuildingScene, CompoundScene, OverheadScene, RoomScene } from './palaceCanvas'
import './palace.css'

type PalaceLayer =
  | { layer: 'compound' }
  | { layer: 'building'; initiativeId: string }
  | { layer: 'tasks'; projectId: string }
  /** The dome at task level over the loose tasks — the compound's
   *  smallest building opens here (founder, 2026-11-26). The
   *  grouping names no single record, so this layer rides the
   *  compound's chat carriage until a task is entered. */
  | { layer: 'loose-tasks' }
  | { layer: 'room'; taskId: string }

const GUARDIAN = SEAT_COLORS.guardian

const DOOR_BUTTON =
  'rounded-full border border-[#c9b995] bg-white/60 px-3 py-1.5 text-xs text-[#4a3f30]'

/** The staged focus a tap can carry — the room's own instruments,
 *  plus a guest object staged as "guest:<seat>". These strings are
 *  the turn context's palace_focus values; the server validates
 *  them against the same closed set and scrubs anything else. */
type StagedFocus =
  | 'scales'
  | 'vessel'
  | 'chest'
  | 'table'
  | 'threshold'
  | 'hearth'
  | 'mandala'
  | 'plant'
  | `guest:${string}`

const FOCUS_LABELS: Record<string, string> = {
  scales: 'the scales',
  vessel: 'the Kintsugi vessel',
  chest: 'the chest',
  table: 'the gathering table',
  threshold: 'the threshold',
  hearth: 'the hearth',
  mandala: "Aria's mandala",
  plant: "Rumi's plant",
}

function focusLabel(focus: StagedFocus): string {
  if (focus.startsWith('guest:')) {
    const seat = focus.slice('guest:'.length) as SeatId
    return GUEST_OBJECTS[seat]?.label ?? 'a guest object'
  }
  return FOCUS_LABELS[focus] ?? 'an object in this room'
}

export default function LivingPalaceView({
  onFollowGuest,
}: {
  /** Guests-1's second door: follow a guest object into its seat's
   *  own world (the App routes it through SEAT_HOME_NAV). Absent in
   *  surfaces that mount the Palace without navigation. */
  onFollowGuest?: (seat: SeatId) => void
} = {}) {
  const [data, setData] = useState<PalaceData | null>(null)
  /** Per-subject seat-interaction counts — Scene 1's ivy read.
   *  Null until loaded; a failed read leaves it null and every
   *  building stands at resting ivy (stage 1, natural green). */
  const [interactions, setInteractions] = useState<SubjectInteraction[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [trail, setTrail] = useState<PalaceLayer[]>([{ layer: 'compound' }])
  const [attendedCompound, setAttendedCompound] = useState(false)
  const [attendedFloorId, setAttendedFloorId] = useState<string | null>(null)
  const [unnestedCompound, setUnnestedCompound] = useState(false)
  const [selectedIdeaId, setSelectedIdeaId] = useState<string | null>(null)
  const [roomLit, setRoomLit] = useState(false)
  /** Tentative population: the object a tap staged in the chat.
   *  Client-side only — it rides the chat context while staged and
   *  is discarded silently by any navigation or by setting it down. */
  const [stagedFocus, setStagedFocus] = useState<StagedFocus | null>(null)
  /** The guest whose slim door strip stands open, if any. */
  const [guestDoorSeat, setGuestDoorSeat] = useState<SeatId | null>(null)

  const current = trail[trail.length - 1]

  const loadEntities = useCallback(async () => {
    const entities = await fetchPalaceEntities()
    setData(entities)
  }, [])

  const loadInteractions = useCallback(async () => {
    const rows = await fetchSubjectInteractions()
    setInteractions(rows)
  }, [])

  useEffect(() => {
    let cancelled = false
    loadEntities().catch(() => {
      if (!cancelled) setLoadError('The Palace could not be reached — its records did not load.')
    })
    void loadInteractions()
    return () => {
      cancelled = true
    }
  }, [loadEntities, loadInteractions])

  /* ---------------- the attributed subject read ---------------- */

  /** The subject the read is fetched for on this layer: the task
   *  level's project, a room's task. Compound and building layers
   *  have no per-subject read in these expressions. */
  const subjectKey =
    current.layer === 'tasks'
      ? `project:${current.projectId}`
      : current.layer === 'room'
        ? `task:${current.taskId}`
        : null
  const [attributed, setAttributed] = useState<{ key: string; read: AttributedRead | null } | null>(null)

  useEffect(() => {
    if (!subjectKey) return
    let cancelled = false
    const [entityType, entityId] = subjectKey.split(':') as ['project' | 'task', string]
    fetchAttributedRead(entityType, entityId).then((read) => {
      if (!cancelled) setAttributed({ key: subjectKey, read })
    })
    return () => {
      cancelled = true
    }
  }, [subjectKey])

  /** The read for the CURRENT subject only — a stale read for a
   *  previous room never paints this one. Null while loading or
   *  when the read failed: the world then stands unadorned. */
  const subjectRead = attributed && attributed.key === subjectKey ? attributed.read : null

  /** After a ruling or a weighing in chat, re-read the subject:
   *  the world shows the mechanism's new state, never a local
   *  guess at it. */
  const refreshSubjectRead = useCallback(async () => {
    if (!subjectKey) return
    const [entityType, entityId] = subjectKey.split(':') as ['project' | 'task', string]
    const read = await fetchAttributedRead(entityType, entityId)
    setAttributed({ key: subjectKey, read })
  }, [subjectKey])

  /** A chat turn landed (the Scroll #431 precedent): the record
   *  may have changed in conversation — re-read the subject and
   *  the entities so the drawn world reflects it. */
  const onTurnLanded = useCallback(() => {
    void refreshSubjectRead()
    void loadEntities().catch(() => {})
    void loadInteractions()
  }, [refreshSubjectRead, loadEntities, loadInteractions])

  const subjectGuests = useMemo(() => attendingGuests(subjectRead), [subjectRead])
  const subjectGuestSeats = useMemo(() => subjectGuests.map((g) => g.seat), [subjectGuests])
  const guestDoor = guestDoorSeat ? subjectGuests.find((g) => g.seat === guestDoorSeat) : undefined

  /* ---------------- staging + navigation ---------------- */

  const stage = useCallback((focus: StagedFocus) => {
    setStagedFocus(focus)
    setGuestDoorSeat(null)
  }, [])

  /** Every navigation discards a staged object silently — clicking
   *  away is the discard (tentative population). */
  const push = useCallback((next: PalaceLayer) => {
    setTrail((t) => [...t, next])
    setStagedFocus(null)
    setGuestDoorSeat(null)
    setRoomLit(false)
  }, [])

  const goToTrailIndex = useCallback((index: number) => {
    setTrail((t) => t.slice(0, index + 1))
    setStagedFocus(null)
    setGuestDoorSeat(null)
    setRoomLit(false)
  }, [])

  /* ---------------- derived models ---------------- */

  const compound = useMemo(
    () => (data ? buildCompound(data, { unnested: unnestedCompound }) : null),
    [data, unnestedCompound],
  )
  /** Room (task) counts per project — Scene 1's class reading for
   *  project structures (an initiative's class reads its floors
   *  from the compound model itself). */
  const projectRoomCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    if (data) {
      for (const t of data.tasks) {
        if (t.project_id) counts[t.project_id] = (counts[t.project_id] ?? 0) + 1
      }
    }
    return counts
  }, [data])
  const building = useMemo(() => {
    if (!data || current.layer !== 'building') return null
    const initiative = data.initiatives.find((i) => i.id === current.initiativeId)
    return initiative ? buildBuilding(data, initiative) : null
  }, [data, current])
  /** The project in view: the task level's own project, or the
   *  project the open room belongs to. */
  const subjectProject = useMemo(() => {
    if (!data) return null
    if (current.layer === 'tasks') return data.projects.find((p) => p.id === current.projectId) ?? null
    if (current.layer === 'room') {
      const task = data.tasks.find((t) => t.id === current.taskId)
      return task?.project_id ? (data.projects.find((p) => p.id === task.project_id) ?? null) : null
    }
    return null
  }, [data, current])
  const taskLevel = useMemo(() => {
    if (!data) return null
    if (current.layer === 'tasks' && subjectProject) return buildTaskLevel(data, subjectProject)
    if (current.layer === 'loose-tasks') return buildLooseTaskLevel(data)
    return null
  }, [data, current, subjectProject])
  /** The chamber plate of a project, read off the building
   *  scene's own plan (plateForFloor — the shared assignment,
   *  never re-derived): the task level's circles show it, and
   *  the project's rooms open into it. A project with no
   *  initiative — a loose project — stands in the rose chamber. */
  const plateForProject = useCallback(
    (project: { id: string; initiative_id: string | null } | null): RoomPlate => {
      if (!data || !project?.initiative_id) return 'rose'
      const initiative = data.initiatives.find((i) => i.id === project.initiative_id)
      if (!initiative) return 'rose'
      const buildingModel = buildBuilding(data, initiative)
      return plateForFloor(
        buildingModel.floors.map((f) => ({ key: f.project.id, roomCount: f.roomCount })),
        project.id,
      )
    },
    [data],
  )
  /* ---------------- the overhead layout (the third layer) ---------------- */

  /** The layout record's key for this layer: the project's id —
   *  the loose grouping's synthetic project carries the reserved
   *  'loose-tasks' id, so one rule serves both. */
  const overheadKey =
    (current.layer === 'tasks' || current.layer === 'loose-tasks') && taskLevel
      ? taskLevel.project.id
      : null
  /** A fingerprint of the collection the layout answers for:
   *  the layout recomputes when the collection itself changes
   *  (a task added in conversation, an estimate recorded) — the
   *  hybrid transition then moves the rooms, and the scene's
   *  rooms travel to their new seats. */
  const overheadFingerprint = taskLevel
    ? taskLevel.tasks.map((t) => `${t.id}:${t.estimated_hours ?? ''}`).join('|') +
      '#' +
      taskLevel.links.map((l) => `${l.aId}>${l.bId}`).join('|')
    : null
  const [overhead, setOverhead] = useState<{ key: string; layout: OverheadLayout } | null>(null)
  useEffect(() => {
    if (!taskLevel || !overheadKey) return
    let cancelled = false
    const level = taskLevel
    const key = overheadKey
    void (async () => {
      const stored = await fetchPalaceLayout(key)
      if (cancelled) return
      const partners = new Map<string, Set<string>>()
      const link = (a: string, b: string) => {
        const set = partners.get(a) ?? new Set<string>()
        set.add(b)
        partners.set(a, set)
      }
      for (const l of level.links) {
        link(l.aId, l.bId)
        link(l.bId, l.aId)
      }
      const result = planOverheadLayout(
        level.tasks.map((t) => ({ id: t.id, weight: taskSizeWeight(t.estimated_hours) })),
        partners,
        stored,
        { fixtures: true },
      )
      // Written only when a layout is computed or changes — the
      // standing record is never rewritten.
      if (result.changed) void savePalaceLayout(key, result.record)
      if (!cancelled) setOverhead({ key: `${key}::${overheadFingerprint}`, layout: result })
    })()
    return () => {
      cancelled = true
    }
    // overheadFingerprint is the render key, not a trigger: the
    // effect re-runs when the level model itself is rebuilt
    // (entity data reloaded), which is when a recompute is due.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskLevel, overheadKey])
  const overheadReady =
    overhead !== null && overhead.key === `${overheadKey}::${overheadFingerprint}`
  /** The layer key at which the drawing-table room was opened —
   *  the project stands on the drawing table (the compound's
   *  table announcement, carried to the plan) until it is set
   *  down or navigation discards it. */
  const [tableLayerKey, setTableLayerKey] = useState<string | null>(null)
  const onOverheadArtifact = useCallback(
    (kind: OverheadArtifactKind) => {
      stage(kind)
      if (kind === 'table') setTableLayerKey(overheadKey)
    },
    [stage, overheadKey],
  )
  /** Navigation sets the project down from the table, silently —
   *  the same discard as any staged object. */
  useEffect(() => {
    setTableLayerKey(null)
  }, [current])

  const room = useMemo(() => {
    if (!data || current.layer !== 'room') return null
    const task = data.tasks.find((t) => t.id === current.taskId)
    return task ? buildRoom(data, task) : null
  }, [data, current])
  /** The room's chamber: the plate of the project the room
   *  belongs to, read off the building scene's own plan
   *  (plateForFloor — the shared assignment, never re-derived).
   *  A room whose project cannot be resolved — a loose task, a
   *  loose project — stands in the rose chamber. */
  const roomPlate: RoomPlate = useMemo(() => {
    if (current.layer !== 'room') return 'rose'
    return plateForProject(subjectProject)
  }, [current, plateForProject, subjectProject])
  const selectedIdea: Idea | null = useMemo(() => {
    if (!data || !selectedIdeaId || current.layer !== 'compound') return null
    return data.ideas.find((i) => i.id === selectedIdeaId) ?? null
  }, [data, selectedIdeaId, current])

  /* ---------------- navigation ---------------- */

  const openBuilding = useCallback(
    (initiativeId: string) => {
      setSelectedIdeaId(null)
      push({ layer: 'building', initiativeId })
    },
    [push],
  )
  /** A project opens the dome at TASK level: from the building
   *  layer (a floor circle tapped — the project stages in the
   *  chat exactly as a floor tap staged it) and from the compound
   *  alike (a loose or standing project has no building layer to
   *  pass through). */
  const openProject = useCallback(
    (projectId: string) => {
      setSelectedIdeaId(null)
      push({ layer: 'tasks', projectId })
    },
    [push],
  )
  const openTask = useCallback(
    (taskId: string) => {
      setSelectedIdeaId(null)
      push({ layer: 'room', taskId })
    },
    [push],
  )
  /** The loose-tasks building opens the dome at TASK level over
   *  the loose tasks — no project stands between the compound
   *  and these circles. */
  const openLooseTasks = useCallback(() => {
    setSelectedIdeaId(null)
    push({ layer: 'loose-tasks' })
  }, [push])

  /* ---------------- furniture: taps stage, never settle ---------------- */

  const onRoomFurniture = useCallback(
    (kind: 'scales' | 'vessel' | 'chest' | 'table' | 'mandala' | 'plant') => {
      stage(kind)
    },
    [stage],
  )

  /* ---------------- chat subject ---------------- */

  const chatSubject = useMemo(() => {
    const base = { sheet_type: 'living_palace' } as Record<string, string>
    if (!data) return { conversationId: 'living-palace:compound', context: base }
    if (current.layer === 'room') {
      return {
        conversationId: `living-palace:task:${current.taskId}`,
        context: {
          ...base,
          entity_type: 'task',
          entity_id: current.taskId,
          ...(stagedFocus ? { palace_focus: stagedFocus } : {}),
        },
      }
    }
    if (current.layer === 'tasks') {
      return {
        conversationId: `living-palace:project:${current.projectId}`,
        context: {
          ...base,
          entity_type: 'project',
          entity_id: current.projectId,
          ...(stagedFocus ? { palace_focus: stagedFocus } : {}),
        },
      }
    }
    if (current.layer === 'building') {
      return {
        conversationId: `living-palace:initiative:${current.initiativeId}`,
        context: { ...base, entity_type: 'initiative', entity_id: current.initiativeId },
      }
    }
    if (selectedIdea) {
      return {
        conversationId: `living-palace:idea:${selectedIdea.id}`,
        context: { ...base, entity_type: 'idea', entity_id: selectedIdea.id },
      }
    }
    return { conversationId: 'living-palace:compound', context: base }
  }, [data, current, selectedIdea, stagedFocus])

  /* ---------------- crumbs ---------------- */

  const crumbs = useMemo(() => {
    const list: { label: string; index: number }[] = [{ label: 'Compound', index: 0 }]
    trail.forEach((step, i) => {
      if (i === 0 || !data) return
      if (step.layer === 'building') {
        list.push({ label: data.initiatives.find((x) => x.id === step.initiativeId)?.title ?? 'Building', index: i })
      } else if (step.layer === 'loose-tasks') {
        list.push({ label: 'Loose tasks', index: i })
      } else if (step.layer === 'tasks') {
        list.push({ label: data.projects.find((x) => x.id === step.projectId)?.title ?? 'Project', index: i })
      } else if (step.layer === 'room') {
        list.push({ label: data.tasks.find((x) => x.id === step.taskId)?.title ?? 'Room', index: i })
      }
    })
    return list
  }, [trail, data])

  /* ---------------- render ---------------- */

  const left = (
    <div className="flex h-full flex-col bg-[#f7f1e3]">
      <div className="border-b border-[#e3d5b8] px-4 py-3">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h2 className="text-base font-semibold text-[#4a3f30]">
            Maeve's Living Palace <span style={{ color: GUARDIAN }}>· Guardian</span>
          </h2>
          <nav className="flex flex-wrap items-center gap-1 text-xs text-[#6b5b45]" aria-label="Palace trail">
            {crumbs.map((crumb, i) => (
              <span key={crumb.index} className="flex items-center gap-1">
                {i > 0 && <span aria-hidden>›</span>}
                {crumb.index === trail.length - 1 ? (
                  <span className="font-semibold text-[#4a3f30]">{crumb.label}</span>
                ) : (
                  <button type="button" className="underline decoration-dotted" onClick={() => goToTrailIndex(crumb.index)}>
                    {crumb.label}
                  </button>
                )}
              </span>
            ))}
          </nav>
          <span className="ml-auto flex gap-2">
            {current.layer === 'compound' && (
              <button
                type="button"
                data-testid="palace-unnest-toggle"
                className="rounded-full border border-[#c9b995] bg-white/60 px-2.5 py-1 text-xs text-[#4a3f30]"
                onClick={() => setUnnestedCompound((v) => !v)}
              >
                {unnestedCompound ? 'Nest the projects' : 'Un-nest the projects'}
              </button>
            )}

          </span>
        </div>
        {selectedIdea && current.layer === 'compound' && (
          <p className="mt-1 text-xs text-[#6b5b45]">
            On the drawing table: <span className="font-semibold text-[#4a3f30]">{selectedIdea.title}</span> — Maeve has
            it in view.{' '}
            <button type="button" className="underline decoration-dotted" onClick={() => setSelectedIdeaId(null)}>
              Set it down
            </button>
          </p>
        )}
        {tableLayerKey !== null &&
          tableLayerKey === overheadKey &&
          (current.layer === 'tasks' || current.layer === 'loose-tasks') &&
          taskLevel && (
            <p className="mt-1 text-xs text-[#6b5b45]">
              On the drawing table: <span className="font-semibold text-[#4a3f30]">{taskLevel.project.title}</span> — Maeve has
              it in view.{' '}
              <button type="button" className="underline decoration-dotted" onClick={() => setTableLayerKey(null)}>
                Set it down
              </button>
            </p>
          )}
      </div>

      <div className="living-palace-scene relative min-h-0 flex-1 overflow-y-auto px-3 py-3">
        {loadError && (
          <div className="mx-auto mt-10 max-w-md rounded-xl border border-[#d8c9a3] bg-white/70 p-4 text-sm text-[#4a3f30]">
            {loadError}
          </div>
        )}
        {!data && !loadError && <p className="mt-10 text-center text-sm text-[#6b5b45]">Walking to the Palace…</p>}
        {data && compound && current.layer === 'compound' && (
          <CompoundScene
            model={compound}
            attended={attendedCompound}
            onAttend={setAttendedCompound}
            onOpenBuilding={openBuilding}
            onOpenProject={openProject}
            onOpenLooseTasks={openLooseTasks}
            interactions={interactions}
            projectRoomCounts={projectRoomCounts}
            onSelectIdea={(id) => {
              setSelectedIdeaId(id)
              setStagedFocus(null)
            }}
            selectedIdeaId={selectedIdeaId}
          />
        )}
        {data && building && current.layer === 'building' && (
          <BuildingScene
            model={building}
            attendedFloorId={attendedFloorId}
            onAttend={setAttendedFloorId}
            onOpenFloor={openProject}
            interactions={interactions}
          />
        )}
        {data && taskLevel && (current.layer === 'tasks' || current.layer === 'loose-tasks') && (
          overheadReady ? (
            <OverheadScene
              model={taskLevel}
              layout={overhead.layout}
              vesselGold={subjectRead?.kintsugi?.restoration_of_understanding ?? false}
              onOpenTask={openTask}
              onOpenArtifact={onOverheadArtifact}
            />
          ) : (
            <p className="mt-10 text-center text-sm text-[#6b5b45]">Composing the plan…</p>
          )
        )}
        {data && room && current.layer === 'room' && (
          <RoomScene
            model={room}
            plate={roomPlate}
            lit={roomLit}
            onBringFire={() => {
              setRoomLit(true)
              stage('hearth')
            }}
            onThreshold={() => stage('threshold')}
            onOpenWaitedOn={openTask}
            onFurniture={onRoomFurniture}
            onOpenSubtask={openTask}
            vesselGold={subjectRead?.kintsugi?.restoration_of_understanding ?? false}
            guests={subjectGuestSeats}
            onGuest={(seat) => setGuestDoorSeat(seat)}
          />
        )}
      </div>

      {guestDoor && (
        <div
          data-testid="palace-guest-strip"
          className="flex flex-wrap items-center gap-2 border-t border-[#e3d5b8] bg-[#fffaf0] px-4 py-2.5 text-sm text-[#4a3f30]"
        >
          <span className="font-semibold">{GUEST_OBJECTS[guestDoor.seat]?.label}</span>
          <span className="ml-auto flex flex-wrap items-center gap-2">
            <button
              type="button"
              data-testid="palace-guest-explore"
              className={DOOR_BUTTON}
              onClick={() => stage(`guest:${guestDoor.seat}`)}
            >
              Explore it here with Maeve
            </button>
            {guestDoor.seat === 'ambassador' ? (
              <span className="text-xs text-[#6b5b45]">
                Lucian has no world of his own yet — his cup is explored here, with Maeve.
              </span>
            ) : onFollowGuest ? (
              <button
                type="button"
                data-testid="palace-guest-follow"
                className={DOOR_BUTTON}
                onClick={() => onFollowGuest(guestDoor.seat)}
              >
                Follow it into {guestDoor.seat_name}'s world
              </button>
            ) : null}
            <button
              type="button"
              data-testid="palace-guest-close"
              className="text-xs underline decoration-dotted"
              onClick={() => setGuestDoorSeat(null)}
            >
              Close
            </button>
          </span>
        </div>
      )}
    </div>
  )

  const right = (
    <div className="flex h-full flex-col bg-white">
      <CouncilChat
        environment="workspace"
        initialArchetypeId="guardian"
        conversationId={chatSubject.conversationId}
        context={chatSubject.context}
        onTurnSent={onTurnLanded}
        stagedLabel={stagedFocus ? focusLabel(stagedFocus) : null}
        onStagedClear={() => setStagedFocus(null)}
      />
    </div>
  )

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <SplitShell left={left} right={right} storageKey="living-palace-split" />
    </div>
  )
}
