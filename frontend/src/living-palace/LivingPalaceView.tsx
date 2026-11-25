/**
 * The Living Palace — Maeve's seat home (the fifth seat world).
 *
 * Landing is the standing seat pattern (SEAT_HOME_NAV → guardian):
 * the split screen, the world on the left and Maeve's chat on the
 * right, the divider draggable, the panes scrolling independently,
 * and the chat's subject following the visitor's selections — a
 * building, a floor, a room, or an idea on the drawing table rides
 * into her conversation through the same subject carriage the other
 * worlds use (sheet_type "living_palace", PRs #422/#424/#425's seam,
 * extended to this sheet).
 *
 * The world reads the visitor's real Vision Execution records via
 * palaceApi; it writes nothing. Boundaries: the per-subject boundary
 * store is NOT commissioned — the threshold is an affordance whose
 * panel composes only from records that exist today (core-profile
 * declarations, strand topic boundaries, permission state), fetched
 * lazily when a doorway is tapped.
 *
 * The shared attributed subject read (founder ruling 2026-11-25)
 * composes this world's three further expressions per subject,
 * fetched as the visitor enters a floor or room: Thresholds-1 (the
 * boundaries panel's per-subject states — proposed interpretations
 * in pencil, established decisions/commitments), Kintsugi-1 (the
 * vessel's held questions and its gold seam, earned only by an
 * accepted supersession), and Guests-1 (a seat's object stands only
 * where the read shows that seat attending the subject, with two
 * doors: explore here with Maeve, or follow into the seat's world).
 */
import * as React from 'react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import CouncilChat from '../chat/CouncilChat'
import SplitShell from '../components/SplitShell'
import { SEAT_COLORS, type SeatId } from '../council/colors'
import type { Idea } from '../vision-execution/types'
import {
  attendingGuests,
  buildBuilding,
  buildCompound,
  buildFloor,
  buildRoom,
  composeBoundaryPanel,
  composeSubjectThresholds,
  composeVesselHeld,
  GUEST_OBJECTS,
  type AttributedRead,
  type BoundaryPanelModel,
  type PalaceData,
} from './palaceLogic'
import { fetchAttributedRead, fetchBoundaryMaterial, fetchPalaceEntities } from './palaceApi'
import { BuildingScene, CompoundScene, FloorScene, RoomScene } from './palaceCanvas'
import './palace.css'

type PalaceLayer =
  | { layer: 'compound' }
  | { layer: 'building'; initiativeId: string }
  | { layer: 'floor'; projectId: string }
  | { layer: 'room'; taskId: string }

type Panel =
  | { kind: 'boundaries' }
  | { kind: 'held'; taskId: string }
  | { kind: 'idea'; ideaId: string }
  | { kind: 'vessel' }
  | { kind: 'guest'; seat: SeatId }
  | null

const GUARDIAN = SEAT_COLORS.guardian

export default function LivingPalaceView({
  onFollowGuest,
}: {
  /** Guests-1's second door: follow a guest object into its seat's
   *  own world (the App routes it through SEAT_HOME_NAV). Absent in
   *  surfaces that mount the Palace without navigation. */
  onFollowGuest?: (seat: SeatId) => void
} = {}) {
  const [data, setData] = useState<PalaceData | null>(null)
  const [coreNonNegotiables, setCoreNonNegotiables] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [trail, setTrail] = useState<PalaceLayer[]>([{ layer: 'compound' }])
  const [attendedCompound, setAttendedCompound] = useState(false)
  const [attendedFloorId, setAttendedFloorId] = useState<string | null>(null)
  const [unnestedCompound, setUnnestedCompound] = useState(false)
  const [unnestedFloor, setUnnestedFloor] = useState(false)
  const [selectedIdeaId, setSelectedIdeaId] = useState<string | null>(null)
  const [roomLit, setRoomLit] = useState(false)
  const [toast, setToast] = useState<{ id: number; text: string } | null>(null)
  const [panel, setPanel] = useState<Panel>(null)
  const [boundaryModel, setBoundaryModel] = useState<BoundaryPanelModel | null>(null)
  const [boundaryLoading, setBoundaryLoading] = useState(false)
  const toastTimer = useRef<number | null>(null)

  const current = trail[trail.length - 1]

  useEffect(() => {
    let cancelled = false
    fetchPalaceEntities()
      .then((entities) => {
        if (cancelled) return
        setData(entities)
        setCoreNonNegotiables(entities.coreProfile?.non_negotiables ?? null)
      })
      .catch(() => {
        if (!cancelled) setLoadError('The Palace could not be reached — its records did not load.')
      })
    return () => {
      cancelled = true
    }
  }, [])

  const say = useCallback((text: string) => {
    if (toastTimer.current) window.clearTimeout(toastTimer.current)
    setToast({ id: Date.now(), text })
    toastTimer.current = window.setTimeout(() => setToast(null), 5600)
  }, [])

  /* ---------------- the attributed subject read ---------------- */

  /** The subject the read is fetched for on this layer: a floor's
   *  project, a room's task. Compound and building layers have no
   *  per-subject read in these expressions. */
  const subjectKey =
    current.layer === 'floor'
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
  const subjectReadLoading = subjectKey !== null && (!attributed || attributed.key !== subjectKey)
  const subjectGuests = useMemo(() => attendingGuests(subjectRead), [subjectRead])
  const subjectGuestSeats = useMemo(() => subjectGuests.map((g) => g.seat), [subjectGuests])
  const layerNoun = current.layer === 'room' ? 'room' : 'floor'

  const push = useCallback((next: PalaceLayer) => {
    setTrail((t) => [...t, next])
    setPanel(null)
    setRoomLit(false)
  }, [])

  const goToTrailIndex = useCallback((index: number) => {
    setTrail((t) => t.slice(0, index + 1))
    setPanel(null)
    setRoomLit(false)
  }, [])

  /* ---------------- derived models ---------------- */

  const compound = useMemo(
    () => (data ? buildCompound(data, { unnested: unnestedCompound }) : null),
    [data, unnestedCompound],
  )
  const building = useMemo(() => {
    if (!data || current.layer !== 'building') return null
    const initiative = data.initiatives.find((i) => i.id === current.initiativeId)
    return initiative ? buildBuilding(data, initiative) : null
  }, [data, current])
  const floorProject = useMemo(() => {
    if (!data) return null
    if (current.layer === 'floor') return data.projects.find((p) => p.id === current.projectId) ?? null
    if (current.layer === 'room') {
      const task = data.tasks.find((t) => t.id === current.taskId)
      return task?.project_id ? (data.projects.find((p) => p.id === task.project_id) ?? null) : null
    }
    return null
  }, [data, current])
  const floor = useMemo(
    () => (data && floorProject ? buildFloor(data, floorProject, { unnested: unnestedFloor }) : null),
    [data, floorProject, unnestedFloor],
  )
  const room = useMemo(() => {
    if (!data || current.layer !== 'room') return null
    const task = data.tasks.find((t) => t.id === current.taskId)
    return task ? buildRoom(data, task) : null
  }, [data, current])
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
  const openProject = useCallback(
    (projectId: string) => {
      setSelectedIdeaId(null)
      push({ layer: 'floor', projectId })
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

  /* ---------------- boundaries ---------------- */

  const openBoundaries = useCallback(async () => {
    setPanel({ kind: 'boundaries' })
    if (boundaryModel) return
    setBoundaryLoading(true)
    try {
      const material = await fetchBoundaryMaterial()
      setBoundaryModel(
        composeBoundaryPanel({
          nonNegotiables: coreNonNegotiables,
          strandBoundaries: material.strandBoundaries,
          permissionGroups: material.permissionGroups,
        }),
      )
    } catch {
      setBoundaryModel(
        composeBoundaryPanel({
          nonNegotiables: coreNonNegotiables,
          strandBoundaries: [],
          permissionGroups: [],
        }),
      )
    } finally {
      setBoundaryLoading(false)
    }
  }, [boundaryModel, coreNonNegotiables])

  /* ---------------- furniture ---------------- */

  const onRoomFurniture = useCallback(
    (kind: 'scales' | 'vessel' | 'chest' | 'table' | 'mandala' | 'plant') => {
      if (!room) return
      if (kind === 'scales') {
        say(
          'The scales stand in every room, ready to weigh what a piece of work asks of you. Their pans are empty: weighing is not a built record, so nothing placed here is recorded — an unweighed undertaking, not a claim of balance.',
        )
      } else if (kind === 'vessel') {
        if (composeVesselHeld(subjectRead).hasMaterial) {
          setPanel({ kind: 'vessel' })
        } else if (subjectReadLoading) {
          say('The vessel stands whole and empty — Maeve is still gathering what this room holds.')
        } else {
          say(
            'The Kintsugi vessel stands whole and empty. You may bring something here that needs repair before the system ever recognises it — Maeve keeps the vessel for that. Its gold appears only where a reading of a room was reconsidered and the correction accepted, and no such lineage reaches this room, so it stands plain.',
          )
        }
      } else if (kind === 'chest') {
        if (room.held) setPanel({ kind: 'held', taskId: room.task.id })
        else say('The chest stands empty — this piece of work holds no recorded words of its own yet.')
      } else if (kind === 'table') {
        if (room.people.length > 0) {
          say(
            `Recorded at this table: ${room.people.map((p) => p.name).join(', ')}. The empty places are kept — room held for whoever this work may need.`,
          )
        } else {
          say(
            'No one is recorded at this table yet. The places stand empty on purpose — room held for whoever this work may need.',
          )
        }
      } else if (kind === 'mandala') {
        say(
          `Aria's mandala, earned where recorded work converges: ${room.convergence} recorded edges meet at this room. It stands in the floor where the convergence happens — a guest here, in its own form.`,
        )
      } else if (kind === 'plant') {
        say(
          room.growth === 'fruiting'
            ? "Rumi's plant, fruiting on the sill — the map's reading of a finished piece of work, standing here as a guest in its own form."
            : "Rumi's plant, growing on the sill — the map's reading of work under way, standing here as a guest in its own form.",
        )
      }
    },
    [room, say, subjectRead, subjectReadLoading],
  )

  /* ---------------- chat subject ---------------- */

  const chatSubject = useMemo(() => {
    if (!data) return { conversationId: 'living-palace:compound', context: { sheet_type: 'living_palace' } as Record<string, string> }
    if (current.layer === 'room') {
      return {
        conversationId: `living-palace:task:${current.taskId}`,
        context: { sheet_type: 'living_palace', entity_type: 'task', entity_id: current.taskId },
      }
    }
    if (current.layer === 'floor') {
      return {
        conversationId: `living-palace:project:${current.projectId}`,
        context: { sheet_type: 'living_palace', entity_type: 'project', entity_id: current.projectId },
      }
    }
    if (current.layer === 'building') {
      return {
        conversationId: `living-palace:initiative:${current.initiativeId}`,
        context: { sheet_type: 'living_palace', entity_type: 'initiative', entity_id: current.initiativeId },
      }
    }
    if (selectedIdea) {
      return {
        conversationId: `living-palace:idea:${selectedIdea.id}`,
        context: { sheet_type: 'living_palace', entity_type: 'idea', entity_id: selectedIdea.id },
      }
    }
    return { conversationId: 'living-palace:compound', context: { sheet_type: 'living_palace' } as Record<string, string> }
  }, [data, current, selectedIdea])

  /* ---------------- crumbs ---------------- */

  const crumbs = useMemo(() => {
    const list: { label: string; index: number }[] = [{ label: 'Compound', index: 0 }]
    trail.forEach((step, i) => {
      if (i === 0 || !data) return
      if (step.layer === 'building') {
        list.push({ label: data.initiatives.find((x) => x.id === step.initiativeId)?.title ?? 'Building', index: i })
      } else if (step.layer === 'floor') {
        list.push({ label: data.projects.find((x) => x.id === step.projectId)?.title ?? 'Floor', index: i })
      } else if (step.layer === 'room') {
        list.push({ label: data.tasks.find((x) => x.id === step.taskId)?.title ?? 'Room', index: i })
      }
    })
    return list
  }, [trail, data])

  /* ---------------- render ---------------- */

  const thresholds = composeSubjectThresholds(subjectRead)
  const vesselHeld = composeVesselHeld(subjectRead)
  const guestPanelSeat = panel?.kind === 'guest' ? subjectGuests.find((g) => g.seat === panel.seat) : undefined

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
            {current.layer === 'floor' && (
              <button
                type="button"
                data-testid="palace-unnest-toggle"
                className="rounded-full border border-[#c9b995] bg-white/60 px-2.5 py-1 text-xs text-[#4a3f30]"
                onClick={() => setUnnestedFloor((v) => !v)}
              >
                {unnestedFloor ? 'Nest the subtasks' : 'Un-nest the subtasks'}
              </button>
            )}
            {(current.layer === 'floor' || current.layer === 'room') && (
              <button
                type="button"
                data-testid="palace-boundaries-button"
                className="rounded-full border border-[#c9b995] bg-white/60 px-2.5 py-1 text-xs text-[#4a3f30]"
                onClick={() => void openBoundaries()}
              >
                Boundaries
              </button>
            )}
          </span>
        </div>
        {selectedIdea && current.layer === 'compound' && (
          <p className="mt-1 text-xs text-[#6b5b45]">
            On the drawing table: <span className="font-semibold text-[#4a3f30]">{selectedIdea.title}</span> — Maeve has
            it in view.{' '}
            <button type="button" className="underline decoration-dotted" onClick={() => setPanel({ kind: 'idea', ideaId: selectedIdea.id })}>
              Read it
            </button>{' '}
            <button type="button" className="underline decoration-dotted" onClick={() => setSelectedIdeaId(null)}>
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
            onOpenTask={openTask}
            onSelectIdea={(id) => setSelectedIdeaId(id)}
            selectedIdeaId={selectedIdeaId}
          />
        )}
        {data && building && current.layer === 'building' && (
          <BuildingScene
            model={building}
            attendedFloorId={attendedFloorId}
            onAttend={setAttendedFloorId}
            onOpenFloor={openProject}
          />
        )}
        {data && floor && current.layer === 'floor' && (
          <FloorScene
            model={floor}
            guests={subjectGuestSeats}
            onGuest={(seat) => setPanel({ kind: 'guest', seat })}
            onOpenRoom={openTask}
            onThreshold={() => void openBoundaries()}
            onScales={() =>
              floor.scalesFigures &&
              say(
                `The floor's scales hold recorded figures: this floor asks ${floor.scalesFigures.projectHours} hours a week, against ${floor.scalesFigures.ownerName}'s recorded capacity of ${floor.scalesFigures.capacityHours}. The figures are the record's own — the Palace invents none.`,
              )
            }
          />
        )}
        {data && room && current.layer === 'room' && (
          <RoomScene
            model={room}
            lit={roomLit}
            onBringFire={() => {
              setRoomLit(true)
              say(
                'The fire is lit — in the colours of the council, as every fire here burns. Warmth here is presence, not a record: it marks that you are attending to this room, nothing more.',
              )
            }}
            onThreshold={() => void openBoundaries()}
            onOpenWaitedOn={openTask}
            onFurniture={onRoomFurniture}
            onOpenSubtask={openTask}
            vesselGold={subjectRead?.kintsugi?.restoration_of_understanding ?? false}
            guests={subjectGuestSeats}
            onGuest={(seat) => setPanel({ kind: 'guest', seat })}
          />
        )}
        {toast && (
          <div
            key={toast.id}
            data-testid="palace-toast"
            className="pointer-events-none absolute inset-x-6 bottom-5 rounded-xl bg-[#4a3f30]/92 px-4 py-3 text-center text-[13px] leading-relaxed text-[#f7f1e3] shadow-lg"
          >
            {toast.text}
          </div>
        )}
      </div>

      {panel?.kind === 'boundaries' && (
        <div data-testid="palace-boundaries-panel" className="max-h-[46%] overflow-y-auto border-t border-[#e3d5b8] bg-[#fffaf0] px-4 py-3 text-sm text-[#4a3f30]">
          <div className="flex items-baseline justify-between">
            <h3 className="font-semibold">Boundaries — what the record holds</h3>
            <button type="button" className="text-xs underline decoration-dotted" onClick={() => setPanel(null)}>
              Close
            </button>
          </div>
          {boundaryLoading && <p className="mt-2 text-[#6b5b45]">Gathering what is recorded…</p>}
          {thresholds.hasSubjectMaterial && (
            <div className="mt-2 space-y-3 border-b border-[#e3d5b8] pb-3 leading-relaxed">
              <p className="font-medium">At this {layerNoun}'s own threshold</p>
              {thresholds.proposed.length > 0 && (
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-[#8a7a5c]">
                    Proposed — readings, in pencil
                  </p>
                  <ul className="mt-1 space-y-1.5">
                    {thresholds.proposed.map((item) => (
                      <li key={item.reading_id} className="italic text-[#8a7a5c]">
                        {item.author_name}
                        {item.status === 'accepted' ? ' (a reading you accepted)' : ''}:{' '}
                        {[...item.tensions, ...item.open_questions].join(' · ')}
                      </li>
                    ))}
                  </ul>
                  <p className="mt-1 text-xs not-italic text-[#6b5b45]">
                    A reading is an interpretation offered, not a boundary established. Placement at this door is
                    offered only this way — in pencil — until you settle it yourself.
                  </p>
                </div>
              )}
              {thresholds.established.length > 0 && (
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-[#8a7a5c]">Established</p>
                  <ul className="mt-1 list-inside list-disc text-[#6b5b45]">
                    {thresholds.established.map((item, i) =>
                      item.source === 'decision' ? (
                        <li key={i}>A decision stands recorded here — {item.decision_type?.replace(/_/g, ' ')}</li>
                      ) : (
                        <li key={i}>A commitment you made: {item.text}</li>
                      ),
                    )}
                  </ul>
                </div>
              )}
            </div>
          )}
          {boundaryModel && (
            <div className="mt-2 space-y-3 leading-relaxed">
              {(boundaryModel.nonNegotiables || boundaryModel.strandBoundaries.length > 0) && (
                <p className="text-xs font-semibold uppercase tracking-wide text-[#8a7a5c]">Expressed</p>
              )}
              {boundaryModel.nonNegotiables && (
                <div>
                  <p className="font-medium">Declared in your core profile</p>
                  <p className="whitespace-pre-wrap text-[#6b5b45]">{boundaryModel.nonNegotiables}</p>
                  <p className="text-xs text-[#6b5b45]">
                    The Palace holds these as existing — it does not place them at any particular door. Placement is
                    yours to make.
                  </p>
                </div>
              )}
              {boundaryModel.strandBoundaries.map((set) => (
                <div key={set.strandKey}>
                  <p className="font-medium">{set.strandName} — topics you have bounded</p>
                  <ul className="list-inside list-disc text-[#6b5b45]">
                    {set.topics.map((topic) => (
                      <li key={topic}>{topic}</li>
                    ))}
                  </ul>
                </div>
              ))}
              {boundaryModel.permissionGroups.length > 0 && (
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-[#8a7a5c]">Enforceable</p>
                  <p className="font-medium">Your permission state</p>
                  <ul className="list-inside list-disc text-[#6b5b45]">
                    {boundaryModel.permissionGroups.map((g) => (
                      <li key={g.id}>
                        {g.id.replace(/_/g, ' ')} — {g.state.replace(/_/g, ' ')}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {!boundaryModel.hasAnyRecord && (
                <p className="text-[#6b5b45]">
                  Nothing is recorded yet — no declared non-negotiables, no bounded topics, no permission state served
                  to this surface.
                </p>
              )}
              <p className="border-t border-[#e3d5b8] pt-2 text-[#6b5b45]">
                No boundary is recorded against this room itself — the per-subject boundary record does not exist yet,
                and Maeve will not invent one. She can discover and examine boundaries with you; establishing them
                stays yours. Talk it through with her — she is right there.
              </p>
            </div>
          )}
        </div>
      )}

      {panel?.kind === 'held' && room && (
        <div data-testid="palace-held-panel" className="max-h-[46%] overflow-y-auto border-t border-[#e3d5b8] bg-[#fffaf0] px-4 py-3 text-sm text-[#4a3f30]">
          <div className="flex items-baseline justify-between">
            <h3 className="font-semibold">What this room holds — {room.task.title}</h3>
            <button type="button" className="text-xs underline decoration-dotted" onClick={() => setPanel(null)}>
              Close
            </button>
          </div>
          {room.held && (
            <div className="mt-2 space-y-2 leading-relaxed">
              {room.held.description.trim() && (
                <p>
                  <span className="font-medium">Description.</span>{' '}
                  <span className="whitespace-pre-wrap">{room.held.description}</span>
                </p>
              )}
              {room.held.notes.trim() && (
                <p>
                  <span className="font-medium">Notes.</span> <span className="whitespace-pre-wrap">{room.held.notes}</span>
                </p>
              )}
              {room.held.criteria.trim() && (
                <p>
                  <span className="font-medium">Done when.</span>{' '}
                  <span className="whitespace-pre-wrap">{room.held.criteria}</span>
                </p>
              )}
            </div>
          )}
        </div>
      )}

      {panel?.kind === 'vessel' && room && (
        <div data-testid="palace-vessel-panel" className="max-h-[46%] overflow-y-auto border-t border-[#e3d5b8] bg-[#fffaf0] px-4 py-3 text-sm text-[#4a3f30]">
          <div className="flex items-baseline justify-between">
            <h3 className="font-semibold">The Kintsugi vessel — {room.task.title}</h3>
            <button type="button" className="text-xs underline decoration-dotted" onClick={() => setPanel(null)}>
              Close
            </button>
          </div>
          <div className="mt-2 space-y-3 leading-relaxed">
            {vesselHeld.restorationOfUnderstanding && (
              <p className="border-l-2 border-[#d4af37] pl-3" data-testid="palace-vessel-seam-note">
                The gold seam: a reading of this room was reconsidered, and the correction stands accepted. The
                gold marks the corrected reading — an understanding restored. It does not claim the thing itself
                is mended.
              </p>
            )}
            {vesselHeld.openQuestions.length > 0 && (
              <div>
                <p className="font-medium">Open questions Maeve holds for this room</p>
                <ul className="mt-1 space-y-1 italic text-[#8a7a5c]">
                  {vesselHeld.openQuestions.map((q, i) => (
                    <li key={i}>{q.text}</li>
                  ))}
                </ul>
              </div>
            )}
            {vesselHeld.tensions.length > 0 && (
              <div>
                <p className="font-medium">Tensions she holds open</p>
                <ul className="mt-1 space-y-1 italic text-[#8a7a5c]">
                  {vesselHeld.tensions.map((t, i) => (
                    <li key={i}>{t.text}</li>
                  ))}
                </ul>
                <p className="mt-1 text-xs text-[#6b5b45]">
                  A tension held is not damage done — it is a question that has not finished. The vessel does not
                  crack for it.
                </p>
              </div>
            )}
            {vesselHeld.openReconsiderations.length > 0 && (
              <div>
                <p className="font-medium">Up for reconsideration</p>
                <ul className="mt-1 space-y-1 italic text-[#8a7a5c]">
                  {vesselHeld.openReconsiderations.map((r, i) => (
                    <li key={i}>A reading of this room is up for reconsideration{r.reason ? ` — ${r.reason}` : ''}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      )}

      {panel?.kind === 'guest' && guestPanelSeat && (
        <div data-testid="palace-guest-panel" className="max-h-[46%] overflow-y-auto border-t border-[#e3d5b8] bg-[#fffaf0] px-4 py-3 text-sm text-[#4a3f30]">
          <div className="flex items-baseline justify-between">
            <h3 className="font-semibold">{GUEST_OBJECTS[guestPanelSeat.seat]?.label}</h3>
            <button type="button" className="text-xs underline decoration-dotted" onClick={() => setPanel(null)}>
              Close
            </button>
          </div>
          <div className="mt-2 space-y-2 leading-relaxed">
            {guestPanelSeat.via.includes('reading') && (
              <p>
                {guestPanelSeat.seat_name} has a reading on this {layerNoun}.
              </p>
            )}
            {guestPanelSeat.via.includes('conversation') && (
              <p>
                {guestPanelSeat.seat_name} has spoken of this {layerNoun} in conversation.
              </p>
            )}
            <p className="text-[#6b5b45]">
              The material itself stays in {guestPanelSeat.seat_name}'s keeping — none of it is copied into the
              Palace. It stands here by attribution, and there are two doors.
            </p>
            <div className="flex flex-wrap gap-2 pt-1">
              <button
                type="button"
                data-testid="palace-guest-explore"
                className="rounded-full border border-[#c9b995] bg-white/60 px-3 py-1.5 text-xs text-[#4a3f30]"
                onClick={() => {
                  setPanel(null)
                  say(
                    `This ${layerNoun} is Maeve's subject here — ask her about ${guestPanelSeat.seat_name}'s part in it, and it rides into her conversation from where you stand.`,
                  )
                }}
              >
                Explore it here with Maeve
              </button>
              {guestPanelSeat.seat === 'ambassador' ? (
                <span className="text-xs text-[#6b5b45]">
                  Lucian has no world of his own yet — his cup is explored here, with Maeve.
                </span>
              ) : onFollowGuest ? (
                <button
                  type="button"
                  data-testid="palace-guest-follow"
                  className="rounded-full border border-[#c9b995] bg-white/60 px-3 py-1.5 text-xs text-[#4a3f30]"
                  onClick={() => onFollowGuest(guestPanelSeat.seat)}
                >
                  Follow it into {guestPanelSeat.seat_name}'s world
                </button>
              ) : null}
            </div>
          </div>
        </div>
      )}

      {panel?.kind === 'idea' && selectedIdea && (
        <div data-testid="palace-idea-panel" className="max-h-[46%] overflow-y-auto border-t border-[#e3d5b8] bg-[#fffaf0] px-4 py-3 text-sm text-[#4a3f30]">
          <div className="flex items-baseline justify-between">
            <h3 className="font-semibold">{selectedIdea.title}</h3>
            <button type="button" className="text-xs underline decoration-dotted" onClick={() => setPanel(null)}>
              Close
            </button>
          </div>
          <p className="mt-1 text-xs text-[#6b5b45]">
            An undeveloped idea, resting on the drawing table · {selectedIdea.status}
          </p>
          {selectedIdea.summary.trim() && <p className="mt-2 whitespace-pre-wrap leading-relaxed">{selectedIdea.summary}</p>}
          {selectedIdea.notes?.trim() && <p className="mt-2 whitespace-pre-wrap leading-relaxed">{selectedIdea.notes}</p>}
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
      />
    </div>
  )

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <SplitShell left={left} right={right} storageKey="living-palace-split" />
    </div>
  )
}
