/**
 * The Living Palace — pure model logic (Maeve's seat home).
 *
 * The Palace renders the visitor's ONE body of work — the same Vision
 * Execution records the Board, the Bench, the Well and the Scroll
 * render — in Maeve's architectural expression:
 *
 *   compound  initiatives as buildings, loose projects as their own
 *             structures, loose tasks standing on the grounds,
 *             undeveloped ideas resting on the drawing table, the
 *             bonfire at the centre burning in the seven council
 *             colours;
 *   building  floors = the initiative's projects;
 *   floor     ONE continuous plan — rooms (tasks) sharing walls, the
 *             hall as real circulation, labelled doorways where a
 *             recorded dependency joins two rooms of the floor;
 *   room      a cutaway carrying the ruled furniture vocabulary.
 *
 * The vocabulary's discipline (founder rulings, 2026-11-25): a
 * REPRESENTATIONAL object stands only on recorded grounds served by
 * an existing endpoint; an AFFORDANCE instrument stands unpopulated
 * (empty scales = unweighed, never an invented figure; the Kintsugi
 * vessel plain — gold only on the attributed read's
 * accepted-supersession lineage, below).
 * Guest objects (scroll, cup, mandala, lens, battle plan, cairn)
 * stand only where an endpoint serves the earning material: the
 * mandala also earns from recorded dependency edges; the rest earn
 * from the shared attributed subject read (conversation linkage and
 * seat-authored readings naming the subject), which the view fetches
 * per subject and composes through the model section at this file's
 * end. Where the read shows no attending seat, no guest object
 * stands.
 *
 * No fetching, no rendering — the view consumes these models, and the
 * tests pin them.
 */
import type {
  Asset,
  CapacityProfile,
  Idea,
  Initiative,
  Person,
  Project,
  Task,
} from '../vision-execution/types'
import { SEAT_COLORS, type SeatId } from '../council/colors'

export interface PalaceData {
  ideas: Idea[]
  initiatives: Initiative[]
  projects: Project[]
  tasks: Task[]
  persons: Person[]
  assets: Asset[]
  capacityProfiles: CapacityProfile[]
}

/* ------------------------------------------------------------------ */
/* status readings                                                     */
/* ------------------------------------------------------------------ */

function statusIncludes(status: string | null | undefined, ...needles: string[]): boolean {
  const s = (status ?? '').toLowerCase()
  return needles.some((n) => s.includes(n))
}

export function isDoneStatus(status: string | null | undefined): boolean {
  return statusIncludes(status, 'done', 'complete')
}

/** A released record (dropped / killed / cancelled / archived) — it
 *  stands at the compound's south gate, named as released. */
export function isReleasedStatus(status: string | null | undefined): boolean {
  return statusIncludes(status, 'drop', 'kill', 'cancel', 'releas', 'archiv', 'abandon')
}

export type GrowthState = 'growing' | 'fruiting'

/** The Palace's plant reading (the prototype's rule, founder-seen):
 *  a plant stands only where the record's own status grows it — In
 *  Progress grows, Done fruits, anything else leaves the sill bare. */
export function growthOf(status: string | null | undefined): GrowthState | null {
  if (isDoneStatus(status)) return 'fruiting'
  if (statusIncludes(status, 'progress')) return 'growing'
  return null
}

/** Recorded words/material a task itself holds — what fills its chest. */
export function taskHoldsMaterial(task: Task): boolean {
  return Boolean(
    (task.notes && task.notes.trim()) ||
      (task.description && task.description.trim()) ||
      (task.completion_criteria && task.completion_criteria.trim()),
  )
}

/* ------------------------------------------------------------------ */
/* the fire — one source                                               */
/* ------------------------------------------------------------------ */

/** Council order around the fire, exactly as the prototype draws
 *  it: Rumi, Valen, Maeve, Jynx (the centre, tallest tongue), Lucian,
 *  Aria, Severine. The colours come from the app's canonical palette
 *  module — the Palace keeps no second copy. */
export const COUNCIL_FLAME_ORDER: SeatId[] = [
  'mentor',
  'champion',
  'guardian',
  'maverick',
  'ambassador',
  'conductor',
  'skeptic',
]

export function councilFlameColors(): string[] {
  return COUNCIL_FLAME_ORDER.map((id) => SEAT_COLORS[id])
}

/* ------------------------------------------------------------------ */
/* compound                                                            */
/* ------------------------------------------------------------------ */

export interface PalaceBuilding {
  initiative: Initiative
  floors: Project[]
  /** Every task standing under this initiative, at any depth. */
  roomCount: number
  /** The prototype's form rule: a house of forty or more rooms
   *  stands in pagoda tiers. */
  form: 'building' | 'pagoda'
}

export interface CompoundModel {
  buildings: PalaceBuilding[]
  /** Projects with no initiative — their own structures. */
  looseProjects: Project[]
  /** Released loose projects — they stand at the south gate. */
  releasedProjects: Project[]
  /** Tasks belonging nowhere yet — they stand on the open ground. */
  looseTasks: Task[]
  /** Undeveloped ideas resting on the drawing table. */
  ideas: Idea[]
  /** Un-nest only: an initiative's projects ALSO standing as their
   *  own structures on the grounds (the display rule's un-nest path;
   *  the nested default keeps them inside their buildings). */
  standingProjects: Project[]
}

export function buildCompound(data: PalaceData, opts: { unnested: boolean }): CompoundModel {
  const projectsByInitiative = new Map<string, Project[]>()
  for (const p of data.projects) {
    if (!p.initiative_id) continue
    const list = projectsByInitiative.get(p.initiative_id) ?? []
    list.push(p)
    projectsByInitiative.set(p.initiative_id, list)
  }
  const tasksByProject = new Map<string, Task[]>()
  for (const t of data.tasks) {
    if (!t.project_id) continue
    const list = tasksByProject.get(t.project_id) ?? []
    list.push(t)
    tasksByProject.set(t.project_id, list)
  }
  const buildings: PalaceBuilding[] = data.initiatives
    .map((initiative) => {
      const floors = projectsByInitiative.get(initiative.id) ?? []
      const roomCount = floors.reduce(
        (n, p) => n + (tasksByProject.get(p.id) ?? []).length,
        0,
      )
      return {
        initiative,
        floors,
        roomCount,
        form: roomCount >= 40 ? ('pagoda' as const) : ('building' as const),
      }
    })
    .sort((a, b) => b.roomCount - a.roomCount || a.initiative.title.localeCompare(b.initiative.title))

  const loose = data.projects.filter((p) => !p.initiative_id)
  const graduatedIdeaIds = new Set(
    data.initiatives.map((i) => i.source_idea_id).filter((x): x is string => Boolean(x)),
  )
  return {
    buildings,
    looseProjects: loose
      .filter((p) => !isReleasedStatus(p.status))
      .sort((a, b) => a.title.localeCompare(b.title)),
    releasedProjects: loose
      .filter((p) => isReleasedStatus(p.status))
      .sort((a, b) => a.title.localeCompare(b.title)),
    looseTasks: data.tasks
      .filter((t) => !t.project_id && !t.parent_task_id)
      .sort((a, b) => a.title.localeCompare(b.title)),
    ideas: data.ideas
      .filter((idea) => !statusIncludes(idea.status, 'graduat') && !graduatedIdeaIds.has(idea.id))
      .sort((a, b) => a.title.localeCompare(b.title)),
    standingProjects: opts.unnested
      ? data.projects
          .filter((p) => p.initiative_id)
          .sort((a, b) => a.title.localeCompare(b.title))
      : [],
  }
}

/* ------------------------------------------------------------------ */
/* building                                                            */
/* ------------------------------------------------------------------ */

export interface BuildingFloor {
  project: Project
  roomCount: number
  /** Aggregate balcony plant, earned by the floor's own rooms: any
   *  room fruiting fruits the balcony plant; else any room growing
   *  grows it; else the ledge stays bare. */
  plant: GrowthState | null
  released: boolean
}

export interface BuildingModel {
  initiative: Initiative
  /** Top floor first (the prototype stacks the first project highest). */
  floors: BuildingFloor[]
}

export function buildBuilding(data: PalaceData, initiative: Initiative): BuildingModel {
  const floors = data.projects
    .filter((p) => p.initiative_id === initiative.id)
    .map((project) => {
      const rooms = data.tasks.filter((t) => t.project_id === project.id)
      const plant: GrowthState | null = rooms.some((t) => isDoneStatus(t.status))
        ? 'fruiting'
        : rooms.some((t) => growthOf(t.status) === 'growing')
          ? 'growing'
          : null
      return { project, roomCount: rooms.length, plant, released: isReleasedStatus(project.status) }
    })
  return { initiative, floors: floors.reverse() }
}

/* ------------------------------------------------------------------ */
/* floor                                                               */
/* ------------------------------------------------------------------ */

export interface FloorRoom {
  task: Task
  col: 0 | 1
  row: number
  /** Recorded dependencies, resolved against the whole body of work
   *  (a dependency may live on another floor — the window still
   *  shows its state). */
  waitsOn: Task[]
  /** Dependencies whose other end is a room of THIS floor. */
  internalWaits: Task[]
  /** Recorded edges in + out — the room's convergence degree. */
  convergence: number
  growth: GrowthState | null
  holdsMaterial: boolean
  subtaskCount: number
}

export interface FloorScalesFigures {
  /** The project's own recorded weekly ask. */
  projectHours: number
  /** The recorded capacity of the person who keeps this floor. */
  capacityHours: number
  ownerName: string
}

export interface FloorModel {
  project: Project
  rooms: FloorRoom[]
  /** Labelled doorways: recorded edges joining two rooms of this
   *  floor that stand in adjacent rows of the same column — the edge
   *  pierces their shared partition. */
  doorways: { aId: string; bId: string }[]
  /** Recorded edges leaving the floor, named in the floor's panel. */
  crossEdges: { room: Task; other: Task }[]
  /** A cabinet stands in the hall only where rooms hold material. */
  cabinets: boolean
  /** Aria's mosaic is earned where a recorded edge joins two rooms
   *  of this floor. */
  mosaic: boolean
  /** Floor scales stand only on recorded figures: the project's
   *  weekly hours AND its keeper's capacity profile. */
  scalesFigures: FloorScalesFigures | null
  /** People recorded against the project (owner + supporting). */
  people: Person[]
}

export function buildFloor(
  data: PalaceData,
  project: Project,
  opts: { unnested: boolean },
): FloorModel {
  const byId = new Map(data.tasks.map((t) => [t.id, t]))
  const projectTasks = data.tasks.filter((t) => t.project_id === project.id)
  const projectTaskIds = new Set(projectTasks.map((t) => t.id))
  const roomTasks = (
    opts.unnested
      ? projectTasks
      : projectTasks.filter((t) => !t.parent_task_id || !projectTaskIds.has(t.parent_task_id))
  )
    .slice()
    .sort((a, b) => a.title.localeCompare(b.title))
  const roomIds = new Set(roomTasks.map((t) => t.id))
  const inbound = new Map<string, number>()
  for (const t of data.tasks) {
    for (const dep of t.dependency_ids ?? []) {
      inbound.set(dep, (inbound.get(dep) ?? 0) + 1)
    }
  }
  const rooms: FloorRoom[] = roomTasks.map((task, i) => {
    const waitsOn = (task.dependency_ids ?? [])
      .map((id) => byId.get(id))
      .filter((t): t is Task => Boolean(t))
    return {
      task,
      col: (i % 2) as 0 | 1,
      row: Math.floor(i / 2),
      waitsOn,
      internalWaits: waitsOn.filter((t) => roomIds.has(t.id)),
      convergence: (task.dependency_ids ?? []).length + (inbound.get(task.id) ?? 0),
      growth: growthOf(task.status),
      holdsMaterial: taskHoldsMaterial(task),
      subtaskCount: data.tasks.filter((t) => t.parent_task_id === task.id).length,
    }
  })
  const roomById = new Map(rooms.map((r) => [r.task.id, r]))
  const crossEdges: { room: Task; other: Task }[] = []
  const internalPairs = new Set<string>()
  for (const room of rooms) {
    for (const other of room.waitsOn) {
      if (roomById.has(other.id)) {
        internalPairs.add([room.task.id, other.id].sort().join('|'))
      } else {
        crossEdges.push({ room: room.task, other })
      }
    }
  }
  // A recorded edge pierces the shared partition as a labelled
  // doorway only where the two rooms stand in adjacent rows of the
  // same column; other internal edges live in the rooms' windows.
  const doorways: { aId: string; bId: string }[] = [...internalPairs]
    .map((key) => key.split('|') as [string, string])
    .filter(([aId, bId]) => {
      const a = roomById.get(aId)!
      const b = roomById.get(bId)!
      return a.col === b.col && Math.abs(a.row - b.row) === 1
    })
    .map(([aId, bId]) => ({ aId, bId }))
  const owner = project.owner_id ? data.persons.find((p) => p.id === project.owner_id) : undefined
  const profile = project.owner_id
    ? data.capacityProfiles.find((c) => c.person_id === project.owner_id)
    : undefined
  const scalesFigures: FloorScalesFigures | null =
    project.estimated_weekly_hours != null && profile
      ? {
          projectHours: project.estimated_weekly_hours,
          capacityHours: profile.weekly_capacity_hours,
          ownerName: owner?.name ?? 'The keeper of this floor',
        }
      : null
  const peopleIds = new Set<string>([
    ...(project.owner_id ? [project.owner_id] : []),
    ...(project.supporting_owner_ids ?? []),
  ])
  return {
    project,
    rooms,
    doorways,
    crossEdges,
    cabinets: rooms.some((r) => r.holdsMaterial),
    mosaic: rooms.some((r) => r.internalWaits.length > 0),
    scalesFigures,
    people: data.persons.filter((p) => peopleIds.has(p.id)),
  }
}

/* ------------------------------------------------------------------ */
/* room                                                                */
/* ------------------------------------------------------------------ */

export interface RoomHeld {
  notes: string
  description: string
  criteria: string
  /** Assets are NOT part of a room's held material: the Asset record
   *  links to ideas, initiatives and projects — VE has no asset→task
   *  link, so no asset is ever claimed as a task's. */
}

export interface RoomModel {
  task: Task
  project: Project | null
  initiative: Initiative | null
  waitsOn: Task[]
  /** The window's reading of the waited-on rooms: a wall still being
   *  built while any waited-on room is unfinished; a completed wall
   *  when every one is done; no window at all when nothing is
   *  waited on. */
  windowState: 'building' | 'complete' | null
  convergence: number
  /** The mandala is earned at two or more recorded edges. */
  mandala: boolean
  growth: GrowthState | null
  held: RoomHeld | null
  /** People recorded for this room: its assignee, then its floor's
   *  keeper and supporters. Empty = the table's places stand empty
   *  (an affordance, never invented company). */
  people: Person[]
  subtasks: Task[]
  /** The Kintsugi vessel stands in every room as an affordance. A
   *  gold seam is representation: it is earned ONLY by the attributed
   *  read's accepted-supersession lineage (an interpretation
   *  reconsidered, its correction accepted — restored UNDERSTANDING,
   *  never repaired circumstances). The VE-only model built here
   *  never earns it alone; the view applies the read's verdict over
   *  this field. */
  vesselGold: boolean
}

export function buildRoom(data: PalaceData, task: Task): RoomModel {
  const byId = new Map(data.tasks.map((t) => [t.id, t]))
  const waitsOn = (task.dependency_ids ?? [])
    .map((id) => byId.get(id))
    .filter((t): t is Task => Boolean(t))
  const inbound = data.tasks.filter((t) => (t.dependency_ids ?? []).includes(task.id)).length
  const convergence = (task.dependency_ids ?? []).length + inbound
  const project = task.project_id
    ? (data.projects.find((p) => p.id === task.project_id) ?? null)
    : null
  const initiative =
    project?.initiative_id != null
      ? (data.initiatives.find((i) => i.id === project.initiative_id) ?? null)
      : null
  const holds = taskHoldsMaterial(task)
    ? {
        notes: task.notes ?? '',
        description: task.description ?? '',
        criteria: task.completion_criteria ?? '',
      }
    : null
  const peopleIds: string[] = []
  if (task.assignee_id) peopleIds.push(task.assignee_id)
  if (project?.owner_id) peopleIds.push(project.owner_id)
  for (const id of project?.supporting_owner_ids ?? []) peopleIds.push(id)
  const people = [...new Set(peopleIds)]
    .map((id) => data.persons.find((p) => p.id === id))
    .filter((p): p is Person => Boolean(p))
  return {
    task,
    project,
    initiative,
    waitsOn,
    windowState:
      waitsOn.length === 0 ? null : waitsOn.every((t) => isDoneStatus(t.status)) ? 'complete' : 'building',
    convergence,
    mandala: convergence >= 2,
    growth: growthOf(task.status),
    held: holds,
    people,
    subtasks: data.tasks
      .filter((t) => t.parent_task_id === task.id)
      .sort((a, b) => a.title.localeCompare(b.title)),
    vesselGold: false,
  }
}

/* ------------------------------------------------------------------ */
/* the boundaries panel — composed ONLY from records that exist        */
/* ------------------------------------------------------------------ */

export interface StrandBoundarySet {
  strandKey: string
  strandName: string
  topics: string[]
}

export interface BoundaryPanelModel {
  /** Declared in the visitor's core profile — existence held at the
   *  Palace level, never placed at a particular door. */
  nonNegotiables: string | null
  /** The visitor's own strand topic boundaries (only strands that
   *  carry at least one). */
  strandBoundaries: StrandBoundarySet[]
  /** Permission/consent state, as the settings home serves it. */
  permissionGroups: { id: string; state: string }[]
  hasAnyRecord: boolean
}

export function composeBoundaryPanel(input: {
  nonNegotiables: string | null
  strandBoundaries: StrandBoundarySet[]
  permissionGroups: { id: string; state: string }[]
}): BoundaryPanelModel {
  const strandBoundaries = input.strandBoundaries.filter((s) => s.topics.length > 0)
  return {
    nonNegotiables: input.nonNegotiables?.trim() ? input.nonNegotiables : null,
    strandBoundaries,
    permissionGroups: input.permissionGroups,
    hasAnyRecord: Boolean(
      input.nonNegotiables?.trim() || strandBoundaries.length > 0 || input.permissionGroups.length > 0,
    ),
  }
}

/* ------------------------------------------------------------------ */
/* the attributed subject read — Thresholds-1, Kintsugi-1, Guests-1    */
/*                                                                     */
/* The wire shape of GET /vision-execution/attributed-read/{type}/     */
/* {id} (local_ai/conversation/attributed_read.py): one shared read,   */
/* not Palace-owned. The Palace composes three expressions from it:    */
/* the threshold's per-subject boundary states, the vessel's Kintsugi  */
/* material and seam, and the guest objects' standing.                 */
/* ------------------------------------------------------------------ */

export interface AttributedProposedItem {
  thread_id: string
  thread_title: string
  reading_id: string
  author: string
  author_name: string
  status: string
  placement: string | null
  currency_labels: string[]
  tensions: string[]
  open_questions: string[]
}

export interface AttributedEstablishedItem {
  source: 'decision' | 'commitment'
  decision_type?: string
  text?: string
  status?: string
  created_at: string
}

export interface KintsugiReadingView {
  reading_id: string
  author: string
  status: string
  placement: string | null
  currency_labels: string[]
  tensions: string[]
  open_questions: string[]
}

export interface KintsugiThreadView {
  thread_id: string
  thread_title: string
  readings: KintsugiReadingView[]
  reconsiderations: { reading_id: string; status: string; reason: string }[]
}

export interface AttendingSeat {
  seat: SeatId
  seat_name: string
  via: Array<'conversation' | 'reading'>
}

export interface AttributedRead {
  resolved: boolean
  subject: { entity_type: string; entity_id: string; title: string } | null
  steward_gate_open: boolean
  boundaries: {
    expressed: unknown[]
    proposed: AttributedProposedItem[]
    established: AttributedEstablishedItem[]
    enforceable: {
      permission_home_enabled: boolean
      permission_consent_given: boolean
      steward_derivation: boolean
      steward_coordination: boolean
    }
  }
  kintsugi: {
    threads: KintsugiThreadView[]
    /** The seam: an interpretation was reconsidered and its
     *  correction accepted. Restored UNDERSTANDING only — never a
     *  claim that the circumstances understood are repaired. */
    restoration_of_understanding: boolean
  } | null
  guests: { attending: AttendingSeat[] }
}

/** The guest objects of the vocabulary, by seat. Maeve is the host —
 *  she has no guest object in her own house. */
export const GUEST_OBJECTS: Partial<Record<SeatId, { object: string; label: string }>> = {
  mentor: { object: 'cairn', label: "Rumi's cairn" },
  champion: { object: 'battle plan', label: "Valen's battle plan" },
  ambassador: { object: 'cup', label: "Lucian's cup" },
  conductor: { object: 'mandala', label: "Aria's mandala" },
  skeptic: { object: 'lens', label: "Severine's lens" },
  maverick: { object: 'scroll', label: "Jynx's scroll" },
}

/** The seats attending this subject, host excluded — the guest
 *  objects that may stand here, and only here. */
export function attendingGuests(read: AttributedRead | null): AttendingSeat[] {
  if (!read || !read.resolved) return []
  return read.guests.attending.filter((g) => g.seat !== 'guardian' && GUEST_OBJECTS[g.seat])
}

export interface SubjectThresholdsModel {
  /** Interpretations naming this subject — proposed, in pencil.
   *  Never established: a reading is not a boundary record. */
  proposed: AttributedProposedItem[]
  /** What the visitor has actually settled about this subject. */
  established: AttributedEstablishedItem[]
  hasSubjectMaterial: boolean
}

export function composeSubjectThresholds(read: AttributedRead | null): SubjectThresholdsModel {
  if (!read || !read.resolved) return { proposed: [], established: [], hasSubjectMaterial: false }
  const proposed = read.boundaries.proposed
  const established = read.boundaries.established
  return { proposed, established, hasSubjectMaterial: proposed.length > 0 || established.length > 0 }
}

/** The vessel's held material: the subject's CURRENT readings'
 *  tensions and open questions (history is not held open), plus
 *  whether a reconsideration stands open over any of them. A tension
 *  here is an open question Maeve holds — the model carries no
 *  damage state, because there is none to carry. */
export interface VesselHeldModel {
  openQuestions: { author: string; text: string }[]
  tensions: { author: string; text: string }[]
  openReconsiderations: { reason: string }[]
  restorationOfUnderstanding: boolean
  hasMaterial: boolean
}

export function composeVesselHeld(read: AttributedRead | null): VesselHeldModel {
  const empty: VesselHeldModel = {
    openQuestions: [],
    tensions: [],
    openReconsiderations: [],
    restorationOfUnderstanding: false,
    hasMaterial: false,
  }
  if (!read || !read.resolved || !read.kintsugi) return empty
  const openQuestions: VesselHeldModel['openQuestions'] = []
  const tensions: VesselHeldModel['tensions'] = []
  const openReconsiderations: VesselHeldModel['openReconsiderations'] = []
  for (const thread of read.kintsugi.threads) {
    for (const reading of thread.readings) {
      if (reading.placement !== 'current') continue
      for (const text of reading.open_questions) openQuestions.push({ author: reading.author, text })
      for (const text of reading.tensions) tensions.push({ author: reading.author, text })
    }
    for (const rec of thread.reconsiderations) {
      if (rec.status === 'proposed') openReconsiderations.push({ reason: rec.reason })
    }
  }
  const restorationOfUnderstanding = read.kintsugi.restoration_of_understanding
  return {
    openQuestions,
    tensions,
    openReconsiderations,
    restorationOfUnderstanding,
    hasMaterial:
      openQuestions.length > 0 ||
      tensions.length > 0 ||
      openReconsiderations.length > 0 ||
      restorationOfUnderstanding,
  }
}
