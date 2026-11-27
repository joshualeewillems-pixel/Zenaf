/**
 * The Living Palace — pure model logic (Maeve's seat home).
 *
 * The Palace renders the visitor's ONE body of work — the same Vision
 * Execution records the Board, the Bench, the Well and the Scroll
 * render — in Maeve's architectural expression:
 *
 *   compound  initiatives as buildings, loose projects as their own
 *             structures, the loose tasks gathered into one building
 *             of the smallest class, undeveloped ideas resting on
 *             the drawing table in the plan, released projects
 *             standing outside the south gate, the bonfire at the
 *             centre burning in the seven council colours;
 *   building  floors = the initiative's projects;
 *   task level the project's tasks as circles in the same dome
 *             (the floor-plan frame is retired, founder
 *             2026-11-26 20:07 PT — the dome serves both levels);
 *             recorded dependency pairs between its tasks ride
 *             along, to shape the circles' seating;
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
  /** Released loose projects — they stand outside the south gate. */
  releasedProjects: Project[]
  /** Tasks belonging nowhere yet — they gather into ONE building
   *  of the smallest class, standing with the rest. */
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
/* task level                                                          */
/* ------------------------------------------------------------------ */

export interface TaskLevelModel {
  /** The grouping the dome is showing: a project, or the loose
   *  tasks gathered as one grouping. Only the identity and the
   *  title ride here — the dome reads nothing else off it. */
  project: { id: string; title: string }
  /** The project's rooms: its top-level tasks, in the title
   *  order the retired floor plan laid them out in. A subtask
   *  stands inside its room's chamber, not as its own circle. */
  tasks: Task[]
  /** Recorded dependency pairs joining two of these tasks, in
   *  either direction — the data the retired floor plan drew
   *  as labelled doorways (there, only the pairs its plan made
   *  neighbours; here EVERY internal pair, because the pairs
   *  now shape the packing itself: partners seat as neighbours
   *  where the dome can achieve it, and a line joins the rest). */
  links: { aId: string; bId: string }[]
}

export function buildTaskLevel(data: PalaceData, project: Project): TaskLevelModel {
  const projectTasks = data.tasks.filter((t) => t.project_id === project.id)
  const projectTaskIds = new Set(projectTasks.map((t) => t.id))
  const tasks = projectTasks
    .filter((t) => !t.parent_task_id || !projectTaskIds.has(t.parent_task_id))
    .slice()
    .sort((a, b) => a.title.localeCompare(b.title))
  const roomIds = new Set(tasks.map((t) => t.id))
  const pairs = new Set<string>()
  for (const t of tasks) {
    for (const dep of t.dependency_ids ?? []) {
      if (dep !== t.id && roomIds.has(dep)) {
        pairs.add([t.id, dep].sort().join('|'))
      }
    }
  }
  return {
    project,
    tasks,
    links: [...pairs].sort().map((key) => {
      const [aId, bId] = key.split('|') as [string, string]
      return { aId, bId }
    }),
  }
}

/** The loose tasks as one task-level grouping — the dome the
 *  compound's smallest building opens into (founder, 2026-11-26:
 *  "Make the loose tasks, the smallest building and put it with
 *  the rest of the buildings"). The task set is the compound
 *  model's own loose set (no project, no parent — a loose task's
 *  subtasks stand inside its chamber, not as circles), in title
 *  order; recorded dependency pairs between two loose tasks ride
 *  along exactly as a project's pairs do. The grouping is a
 *  subject-shaped stand-in, not a Vision Execution record: it
 *  carries no entity the chat can name, so the level rides the
 *  compound's own carriage until a task is entered. */
export function buildLooseTaskLevel(data: PalaceData): TaskLevelModel {
  const tasks = data.tasks
    .filter((t) => !t.project_id && !t.parent_task_id)
    .slice()
    .sort((a, b) => a.title.localeCompare(b.title))
  const roomIds = new Set(tasks.map((t) => t.id))
  const pairs = new Set<string>()
  for (const t of tasks) {
    for (const dep of t.dependency_ids ?? []) {
      if (dep !== t.id && roomIds.has(dep)) {
        pairs.add([t.id, dep].sort().join('|'))
      }
    }
  }
  return {
    project: { id: 'loose-tasks', title: 'Loose tasks' },
    tasks,
    links: [...pairs].sort().map((key) => {
      const [aId, bId] = key.split('|') as [string, string]
      return { aId, bId }
    }),
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
/* the attributed subject read — Thresholds-1, Kintsugi-1, Guests-1    */
/*                                                                     */
/* The wire shape of GET /vision-execution/attributed-read/{type}/     */
/* {id} (local_ai/conversation/attributed_read.py): one shared read,   */
/* not Palace-owned. The drawn world composes two expressions from     */
/* it: the vessel's gold seam and the guest objects' standing. The     */
/* read's remaining substance — boundary states, held questions,       */
/* pending proposals — rides to Maeve in her room-state block, where   */
/* the chat-is-the-work law puts it: in her conversation.              */
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
