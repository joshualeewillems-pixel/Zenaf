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
import { capacityDerived } from '../vision-execution/capacityDerived'

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

/** One pending steward proposal naming the subject — a review item
 *  in the review routes' own served shape (Verdict Slice 1). The
 *  item is BORN proposed and rests undecided until the visitor
 *  rules through those routes; this model carries it, it does not
 *  judge it. Payloads are kind-shaped; the helpers below read them
 *  defensively and never invent fields. */
export interface PendingReviewItem {
  item_id: string
  item_kind: string
  thread_id: string
  surface: string
  status: string
  title: string
  payload: {
    reading?: { tensions?: string[]; open_questions?: string[]; milestones?: string[] }
    evidence_refs?: unknown[]
    currency?: { placement: string; labels: string[] }
    kind?: string
    reason?: string | null
    reading_id?: string
    lens_id?: string
    structural_tension?: string
    proposed_relationship?: string
    limitations?: string
    thread_ids?: string[]
    [key: string]: unknown
  }
}

export interface AttributedRead {
  resolved: boolean
  subject: { entity_type: string; entity_id: string; title: string } | null
  steward_gate_open: boolean
  /** The subject's pending review items (Verdict Slice 1) — the
   *  Palace door's material. Empty when the steward gate is closed
   *  or when nothing undecided names this subject. */
  pending: PendingReviewItem[]
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
  openReconsiderations: { reading_id: string; reason: string }[]
  /** The subject's CURRENT readings that stand ACCEPTED — the
   *  material a reconsideration request can be made from (Verdict
   *  Slice 1). A request opens a candidacy; it never un-accepts.
   *  The label is the reading's own first held line, so the door
   *  names the reading by what it says, not by an id. */
  acceptedReadings: { reading_id: string; author: string; label: string }[]
  restorationOfUnderstanding: boolean
  hasMaterial: boolean
}

export function composeVesselHeld(read: AttributedRead | null): VesselHeldModel {
  const empty: VesselHeldModel = {
    openQuestions: [],
    tensions: [],
    openReconsiderations: [],
    acceptedReadings: [],
    restorationOfUnderstanding: false,
    hasMaterial: false,
  }
  if (!read || !read.resolved || !read.kintsugi) return empty
  const openQuestions: VesselHeldModel['openQuestions'] = []
  const tensions: VesselHeldModel['tensions'] = []
  const openReconsiderations: VesselHeldModel['openReconsiderations'] = []
  const acceptedReadings: VesselHeldModel['acceptedReadings'] = []
  for (const thread of read.kintsugi.threads) {
    for (const reading of thread.readings) {
      if (reading.placement !== 'current') continue
      for (const text of reading.open_questions) openQuestions.push({ author: reading.author, text })
      for (const text of reading.tensions) tensions.push({ author: reading.author, text })
      if (reading.status === 'accepted') {
        acceptedReadings.push({
          reading_id: reading.reading_id,
          author: reading.author,
          label: reading.tensions[0] ?? reading.open_questions[0] ?? 'A reading of this subject',
        })
      }
    }
    for (const rec of thread.reconsiderations) {
      if (rec.status === 'proposed') {
        openReconsiderations.push({ reading_id: rec.reading_id, reason: rec.reason })
      }
    }
  }
  const restorationOfUnderstanding = read.kintsugi.restoration_of_understanding
  return {
    openQuestions,
    tensions,
    openReconsiderations,
    acceptedReadings,
    restorationOfUnderstanding,
    hasMaterial:
      openQuestions.length > 0 ||
      tensions.length > 0 ||
      openReconsiderations.length > 0 ||
      restorationOfUnderstanding,
  }
}

/* ------------------------------------------------------------------ */
/* the verdict door — pending review items (Verdict Slice 1)           */
/*                                                                     */
/* The Palace is a DOOR into the one review mechanism, not a second  */
/* one: these composers only shape what the attributed read already  */
/* filtered to this subject. Every ruling act posts to the existing  */
/* steward review routes (palaceApi); nothing here transitions any   */
/* state, counts anything, or ranks anything. Undecided material     */
/* rests — resting is a legitimate state, not a backlog.             */
/* ------------------------------------------------------------------ */

/** All pending items naming the subject — what rests at its
 *  threshold. Order is the review layer's own (oldest first). */
export function composeSubjectPending(read: AttributedRead | null): PendingReviewItem[] {
  if (!read || !read.resolved) return []
  return read.pending ?? []
}

/** The vessel's share of the pending set: the readings and the
 *  reconsideration candidacies — the material the vessel holds. */
export function vesselPending(read: AttributedRead | null): PendingReviewItem[] {
  return composeSubjectPending(read).filter(
    (item) => item.item_kind === 'reading' || item.item_kind === 'reconsideration',
  )
}

/** Which acts the built routes serve for an item, beyond the three
 *  verdicts every kind takes: endorsement is a reading annotation
 *  (not a verdict); exploration rides the Explore-with-Aria bridge
 *  for readings, fittings, and correspondences only. */
export function pendingActs(item: PendingReviewItem): { endorse: boolean; explore: boolean } {
  return {
    endorse: item.item_kind === 'reading',
    explore:
      item.item_kind === 'reading' ||
      item.item_kind === 'fitting' ||
      item.item_kind === 'correspondence',
  }
}

/** The item's evidentiary basis, as recorded refs (DE-1: a ruling
 *  is taken with the basis in front of him). Refs are served as
 *  {kind, ref_id} rows or plain strings; anything else is not
 *  evidence and is not dressed as any. */
export function pendingEvidenceRefs(item: PendingReviewItem): string[] {
  const refs = item.payload?.evidence_refs
  if (!Array.isArray(refs)) return []
  const out: string[] = []
  for (const ref of refs) {
    if (typeof ref === 'string' && ref) {
      out.push(ref)
    } else if (ref && typeof ref === 'object') {
      const row = ref as { kind?: unknown; ref_id?: unknown }
      if (typeof row.ref_id === 'string' && row.ref_id) {
        out.push(typeof row.kind === 'string' && row.kind ? `${row.kind}:${row.ref_id}` : row.ref_id)
      }
    }
  }
  return out
}

/** The item's substance, in its own recorded words — what the
 *  visitor is actually being asked to rule on. */
export function pendingSummaryLines(item: PendingReviewItem): string[] {
  const p = item.payload ?? {}
  const lines: string[] = []
  if (item.item_kind === 'reading') {
    for (const t of p.reading?.tensions ?? []) lines.push(t)
    for (const q of p.reading?.open_questions ?? []) lines.push(q)
  } else if (item.item_kind === 'reconsideration') {
    if (p.reason) lines.push(p.reason)
  } else if (item.item_kind === 'correspondence') {
    if (p.structural_tension) lines.push(p.structural_tension)
    if (p.proposed_relationship) lines.push(p.proposed_relationship)
    if (p.limitations) lines.push(p.limitations)
  } else if (item.item_kind === 'oversight') {
    if (p.reason) lines.push(p.reason)
  } else if (item.item_kind === 'change') {
    if (p.reason) lines.push(p.reason)
  } else if (item.item_kind === 'fitting') {
    if (p.lens_id) lines.push(`The ${p.lens_id} lens, offered for this thread.`)
  }
  return lines
}

/** The door's name for each kind, in the house's register. */
export const PENDING_KIND_LABELS: Record<string, string> = {
  birth: 'A thread the Steward proposes',
  reading: 'A reading the Steward offers',
  change: 'A change proposed on a thread',
  fitting: 'A way of seeing, offered',
  revision: 'A schedule revision awaiting your word',
  oversight: 'An observation from oversight',
  correspondence: 'A correspondence between threads',
  reconsideration: 'A request to look again',
}

/* ------------------------------------------------------------------ */
/* Scales-1 — the weighing: exploration before establishment           */
/*                                                                     */
/* The scales are Maeve's instrument for asking where the balance    */
/* lies. Until now they only displayed: floor scales stand on        */
/* recorded figures, room scales stand empty. Scales-1 lets the      */
/* visitor WEIGH — adjust hypothetical figures, compare alternative  */
/* arrangements, and see the derived consequences — and, only on     */
/* his explicit settle act, establish the settled figures into the   */
/* records (the writes live in palaceApi, through the VE routes      */
/* that already exist; the provenance rides POST /decisions).        */
/*                                                                     */
/* Exploration is session-local and writes nothing (the Campaign     */
/* Board's provisional-declaration honesty): closing the scales      */
/* discards the arrangement. A weighing begins ALWAYS from recorded  */
/* figures, and a figure with no recorded baseline is not            */
/* adjustable — no baseline is invented, and the scales stay empty   */
/* where there is nothing recorded to place on them.                 */
/*                                                                     */
/* The consequence arithmetic is the shared frontend mirror of the   */
/* backend derivation — vision-execution/capacityDerived.ts, which   */
/* restates local_ai/vision_execution/derived.py                     */
/* add_capacity_derived EXACTLY: committed hours are the sum of       */
/* estimated_weekly_hours over projects with status Ready or Active  */
/* that the person owns or supports (a null estimate counts 0;       */
/* owned-and-supported counts once); activeWeeklyHours rounds to     */
/* one decimal; capacityDelta is the UNROUNDED sum minus capacity,   */
/* rounded; overcapacity is the unrounded difference > 0. Where a    */
/* person has no recorded capacity profile, the Palace makes no      */
/* judgement: capacity and delta are null — no figure, no balance    */
/* (the floor scales' standing rule, and the Board's convention).    */
/* ------------------------------------------------------------------ */

export interface WeighingFigures {
  /** The floor's weekly ask — the project's estimated_weekly_hours. */
  projectHours: number | null
  /** The room's own estimate — the task's estimated_hours (room
   *  anchors only; null for a floor weighing). */
  taskHours: number | null
  /** Who keeps the floor — the project's owner_id. */
  keeperId: string | null
  /** The recorded weekly capacity OF keeperId — whoever keeps the
   *  floor in this arrangement — or null where that keeper has no
   *  capacity recorded. */
  keeperCapacity: number | null
}

export interface WeighingBaseline {
  project: Project | null
  task: Task | null
  /** The recorded figures the weighing starts from. */
  figures: WeighingFigures
  /** Only figures with a recorded baseline may be adjusted. */
  adjustable: {
    projectHours: boolean
    taskHours: boolean
    keeper: boolean
    keeperCapacity: boolean
  }
  /** Every recorded person — the keeper may be re-seated only to
   *  someone the record knows. */
  keeperCandidates: Person[]
}

/** A person's recorded weekly capacity, or null where no profile
 *  is recorded for them. */
export function recordedCapacityFor(data: PalaceData, personId: string | null): number | null {
  if (!personId) return null
  const profile = data.capacityProfiles.find((c) => c.person_id === personId)
  return profile ? profile.weekly_capacity_hours : null
}

export function weighingBaseline(
  data: PalaceData,
  project: Project | null,
  task: Task | null,
): WeighingBaseline {
  const keeperId = project?.owner_id ?? null
  const keeperCapacity = recordedCapacityFor(data, keeperId)
  return {
    project,
    task,
    figures: {
      projectHours: project?.estimated_weekly_hours ?? null,
      taskHours: task?.estimated_hours ?? null,
      keeperId,
      keeperCapacity,
    },
    adjustable: {
      projectHours: project?.estimated_weekly_hours != null,
      taskHours: task?.estimated_hours != null,
      keeper: keeperId != null,
      keeperCapacity: keeperCapacity != null,
    },
    keeperCandidates: data.persons,
  }
}

/** Re-seat the keeper in an arrangement: the capacity figure
 *  follows the seat — it becomes the NEW keeper's recorded capacity
 *  (or null where they have none recorded, and so not adjustable
 *  for them). The previous keeper's capacity is never carried onto
 *  another person. */
export function weighingWithKeeper(
  data: PalaceData,
  figures: WeighingFigures,
  keeperId: string,
): WeighingFigures {
  return { ...figures, keeperId, keeperCapacity: recordedCapacityFor(data, keeperId) }
}

export interface WeighingPicture {
  personId: string
  name: string
  /** activeWeeklyHours, in derived.py's terms. */
  committedHours: number
  capacityHours: number | null
  capacityDelta: number | null
  /** derived.py's overcapacity: the unrounded difference > 0. */
  over: boolean
}

/** One person's capacity picture under a given body of projects —
 *  the shared mirror (vision-execution/capacityDerived.ts) of
 *  add_capacity_derived's arithmetic, step for step. */
function capacityPicture(projects: Project[], capacityHours: number | null, person: Person): WeighingPicture {
  const derived = capacityDerived(projects, capacityHours, person.id)
  return {
    personId: person.id,
    name: person.name,
    committedHours: derived.committedHours,
    capacityHours,
    capacityDelta: derived.capacityDelta,
    over: derived.over,
  }
}

/** The hypothetical body of work an arrangement describes: the
 *  anchor project's hours and keeper replaced by the arrangement's,
 *  and a capacity lookup in which the arrangement's keeper capacity
 *  stands for that keeper. Pure — the data given is never mutated,
 *  and figures the arrangement does not carry (null) leave the
 *  record's own values standing. */
export function applyWeighingFigures(
  data: PalaceData,
  baseline: WeighingBaseline,
  figures: WeighingFigures,
): { projects: Project[]; capacityOf: (personId: string) => number | null } {
  const anchor = baseline.project
  const projects = anchor
    ? data.projects.map((p) =>
        p.id === anchor.id
          ? {
              ...p,
              estimated_weekly_hours: figures.projectHours ?? p.estimated_weekly_hours,
              owner_id: figures.keeperId ?? p.owner_id,
            }
          : p,
      )
    : data.projects
  const capacityOf = (personId: string): number | null => {
    if (figures.keeperId === personId && figures.keeperCapacity != null) return figures.keeperCapacity
    return recordedCapacityFor(data, personId)
  }
  return { projects, capacityOf }
}

/** The derived consequences of an arrangement, for every person the
 *  floor's work touches: its keeper (the arrangement's, then the
 *  recorded one, where they differ), its recorded supporters, and
 *  the assignees of its rooms — the same people the Board's
 *  capacity picture reads. Each person's picture is given twice:
 *  as recorded, and as the arrangement would leave it. A room with
 *  no floor (a loose task) has no capacity consequences — task
 *  estimates are not weekly commitments in the derivation, and the
 *  weighing invents none. */
export function weighingConsequences(
  data: PalaceData,
  baseline: WeighingBaseline,
  figures: WeighingFigures,
): { recorded: WeighingPicture; arranged: WeighingPicture }[] {
  const project = baseline.project
  if (!project) return []
  const ids: string[] = []
  const add = (id: string | null | undefined) => {
    if (id && !ids.includes(id)) ids.push(id)
  }
  add(figures.keeperId)
  add(baseline.figures.keeperId)
  for (const id of project.supporting_owner_ids ?? []) add(id)
  for (const t of data.tasks) if (t.project_id === project.id) add(t.assignee_id)
  const recordedArr = applyWeighingFigures(data, baseline, baseline.figures)
  const arrangedArr = applyWeighingFigures(data, baseline, figures)
  const out: { recorded: WeighingPicture; arranged: WeighingPicture }[] = []
  for (const id of ids) {
    const person = data.persons.find((p) => p.id === id)
    if (!person) continue
    out.push({
      recorded: capacityPicture(recordedArr.projects, recordedArr.capacityOf(id), person),
      arranged: capacityPicture(arrangedArr.projects, arrangedArr.capacityOf(id), person),
    })
  }
  return out
}

/* ------------------------------------------------------------------ */
/* establishment — what the settle act would write                     */
/* ------------------------------------------------------------------ */

export interface WeighingChanges {
  /** One PATCH /projects/{id} body carrying every settled floor
   *  figure that changed (the route applies only sent fields). */
  projectPatch: { estimated_weekly_hours?: number; owner_id?: string } | null
  /** PATCH /tasks/{id} — the room's settled estimate. */
  taskPatch: { estimated_hours: number } | null
  /** PUT /capacity-profiles — the settled capacity of whoever
   *  keeps the floor in the settled arrangement. */
  capacityPut: { person_id: string; weekly_capacity_hours: number } | null
  changed: boolean
}

/** The write plan for a settle act: exactly the figures that differ
 *  from their recorded baselines, each through its existing route.
 *  Every adjustable figure has a route — there are no
 *  exploration-only figures in this build. Capacity settles against
 *  the RECORDED capacity of the arrangement's keeper, so re-seating
 *  the keeper alone never rewrites anyone's capacity. */
export function weighingChanges(
  data: PalaceData,
  baseline: WeighingBaseline,
  figures: WeighingFigures,
): WeighingChanges {
  const base = baseline.figures
  let projectPatch: WeighingChanges['projectPatch'] = null
  if (baseline.project) {
    const patch: { estimated_weekly_hours?: number; owner_id?: string } = {}
    if (figures.projectHours != null && figures.projectHours !== base.projectHours) {
      patch.estimated_weekly_hours = figures.projectHours
    }
    if (figures.keeperId != null && figures.keeperId !== base.keeperId) {
      patch.owner_id = figures.keeperId
    }
    if (Object.keys(patch).length > 0) projectPatch = patch
  }
  const taskPatch =
    baseline.task && figures.taskHours != null && figures.taskHours !== base.taskHours
      ? { estimated_hours: figures.taskHours }
      : null
  const capacityPut =
    figures.keeperId != null &&
    figures.keeperCapacity != null &&
    figures.keeperCapacity !== recordedCapacityFor(data, figures.keeperId)
      ? { person_id: figures.keeperId, weekly_capacity_hours: figures.keeperCapacity }
      : null
  return {
    projectPatch,
    taskPatch,
    capacityPut,
    changed: projectPatch != null || taskPatch != null || capacityPut != null,
  }
}

export const WEIGHING_DECISION_TYPE = 'scales_weighing'

export interface WeighingDecisionPayload {
  entity_type: 'project' | 'task'
  entity_id: string
  decision_type: string
  ai_proposal_snapshot: Record<string, unknown>
  final_values_snapshot: Record<string, unknown>
}

function figureSnapshot(baseline: WeighingBaseline, f: WeighingFigures): Record<string, unknown> {
  const snap: Record<string, unknown> = {}
  if (baseline.project) {
    snap.project_id = baseline.project.id
    snap.project_weekly_hours = f.projectHours
    snap.keeper_id = f.keeperId
    snap.keeper_capacity_hours = f.keeperCapacity
  }
  if (baseline.task) {
    snap.task_id = baseline.task.id
    snap.task_estimated_hours = f.taskHours
  }
  return snap
}

/** The weighing's provenance, in POST /decisions' existing shape
 *  (DecisionCreateRequest — no new fields, no widened record): the
 *  explored arrangement rides the proposal snapshot with its
 *  derived consequences; the settled figures ride the final one;
 *  BOTH carry the recorded figures they supersede. Who settled and
 *  when are the decision row's own server-stamped owner and
 *  created_at — the route stamps them, so the client neither sends
 *  nor invents them. The decision is keyed to the entity whose
 *  record principally changed: the floor when any floor figure or
 *  the keeper's capacity settled, otherwise the room. */
export function buildWeighingDecision(
  data: PalaceData,
  baseline: WeighingBaseline,
  figures: WeighingFigures,
  changes: WeighingChanges,
): WeighingDecisionPayload | null {
  const onProject =
    changes.projectPatch != null || changes.capacityPut != null || baseline.task == null
  const anchor = onProject ? baseline.project : baseline.task
  if (!anchor) return null
  const consequences = weighingConsequences(data, baseline, figures)
  return {
    entity_type: onProject ? 'project' : 'task',
    entity_id: anchor.id,
    decision_type: WEIGHING_DECISION_TYPE,
    ai_proposal_snapshot: {
      kind: WEIGHING_DECISION_TYPE,
      explored: figureSnapshot(baseline, figures),
      recorded_before: figureSnapshot(baseline, baseline.figures),
      consequences: consequences.map((c) => ({
        person_id: c.arranged.personId,
        name: c.arranged.name,
        committed_hours: c.arranged.committedHours,
        capacity_hours: c.arranged.capacityHours,
        capacity_delta: c.arranged.capacityDelta,
        overcapacity: c.arranged.over,
      })),
    },
    final_values_snapshot: {
      kind: WEIGHING_DECISION_TYPE,
      settled: figureSnapshot(baseline, figures),
      recorded_before: figureSnapshot(baseline, baseline.figures),
    },
  }
}
