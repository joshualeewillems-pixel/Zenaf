/**
 * Campaign Board — pure derivation logic.
 *
 * Everything on the board is a projection of Vision Execution records
 * (initiatives → projects → tasks). Nothing here invents data: every
 * terrain form, obstacle, and route position is computed from recorded
 * fields (dates, estimated hours, statuses, dependency ids, subtask
 * structure, completion criteria), and each derivation carries the rule
 * that produced it so the map popup can show its working.
 *
 * Governing design: zenaf-valen-campaign-board-brief-2026-11-17.md
 * (incl. the 2026-11-23 overview/focus addendum).
 *
 * The board's material is wider than tasks alone (founder correction
 * 2026-11-24, on the Radar tie-in): the project's linked open SIGNALS
 * (the canonical Layer-1 circumstance entity) are reported material on
 * the map, and the CAPACITY picture (weekly capacity vs committed
 * estimated hours, the Radar's overcapacity computation) is real
 * time-constraint data. See the Signals / Capacity sections below.
 *
 * Rivers and Holds are NOT derivations at all — per the founder's
 * terrain doctrine (2026-11-17) terrain is derived from VE content,
 * understood through conversation with Valen, and FIXED BY THE USER'S
 * DECLARATION. A River (an immovable window) and a Hold (a review
 * checkpoint) are declared by the user in conversation with Valen
 * and recorded as VE decisions; the board derives their current
 * state from those records. See the Declarations section below.
 */
import type { CapacityProfile, Person, Project, Task } from '../vision-execution/types'
import { capacityDerived } from '../vision-execution/capacityDerived'

export const DAY_MS = 86_400_000
/** A working day, for converting estimated_hours into the prototype's
 *  "workdays" of effort mass. */
export const HOURS_PER_WORKDAY = 8
/** Route length for a project with no recorded dates: drawn short and
 *  flagged "not to scale" — never presented as a measured duration. */
export const NOMINAL_DAYS = 3
/** Prototype overview scale cap: at most 26px per day. */
export const MAX_PX_PER_DAY = 26

export function parseDateMs(value: string | null | undefined): number | null {
  if (!value) return null
  const ms = new Date(value).getTime()
  return Number.isNaN(ms) ? null : ms
}

export function isOpenTask(t: Task): boolean {
  return t.status !== 'Done' && t.status !== 'Dropped'
}

export function isDoneTask(t: Task): boolean {
  return t.status === 'Done'
}

/* ------------------------------------------------------------------ */
/* Span: the project's start → finish window                           */
/* ------------------------------------------------------------------ */

export interface BoardSpan {
  startMs: number
  endMs: number
  days: number
  /** 'project' = both dates recorded on the project itself;
   *  'tasks' = window recovered from recorded task due dates;
   *  'provisional' = no dates recorded anywhere — a local planning
   *  window (today → +30d) that writes nothing until the user sets a
   *  real date. */
  source: 'project' | 'tasks' | 'provisional'
}

export function projectSpan(project: Project, tasks: Task[], nowMs: number): BoardSpan {
  const pStart = parseDateMs(project.start_date)
  const pEnd = parseDateMs(project.end_date)
  const dues = tasks
    .map((t) => parseDateMs(t.due_date))
    .filter((x): x is number => x != null)
    .sort((a, b) => a - b)
  const start = pStart ?? (dues.length ? dues[0] : null)
  const end = pEnd ?? (dues.length ? dues[dues.length - 1] : null)
  if (start != null && end != null && end > start) {
    return {
      startMs: start,
      endMs: end,
      days: Math.max(1, Math.round((end - start) / DAY_MS)),
      source: pStart != null && pEnd != null ? 'project' : 'tasks',
    }
  }
  const startOfToday = new Date(nowMs)
  startOfToday.setHours(9, 0, 0, 0)
  return {
    startMs: startOfToday.getTime(),
    endMs: startOfToday.getTime() + 30 * DAY_MS,
    days: 30,
    source: 'provisional',
  }
}

export function fractionForDate(span: BoardSpan, ms: number): number {
  const f = (ms - span.startMs) / (span.endMs - span.startMs)
  return Math.min(0.98, Math.max(0.02, f))
}

export function dateAtFraction(span: BoardSpan, fraction: number): Date {
  return new Date(span.startMs + fraction * (span.endMs - span.startMs))
}

/** Format a Date as a local `YYYY-MM-DDTHH:mm` string — the shape the
 *  VE API stores for due/start/end dates set from datetime inputs. */
export function toLocalDateTimeString(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`
}

export function shortDate(d: Date): string {
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

export function fullDate(d: Date): string {
  return (
    d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' }) +
    ' · ' +
    d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
  )
}

/* ------------------------------------------------------------------ */
/* Obstacles (brief Family B)                                          */
/* ------------------------------------------------------------------ */

export type ObstacleDomain = 'time' | 'money' | 'body' | 'people' | 'knowledge' | 'entropy'
export type ObstacleStanding = 'documented' | 'interpretation' | 'unknown'
export type ObstacleKind = 'blocked' | 'overdue' | 'crossing' | 'gate' | 'resistance'

export interface BoardObstacle {
  /** taskId, plus ':crossing' / ':gate' when a task carries two marks. */
  id: string
  taskId: string
  kind: ObstacleKind
  kindLabel: string
  domain: ObstacleDomain
  standing: ObstacleStanding
  label: string
  /** For a crossing: the unfinished work in other projects this
   *  step waits on — the dependency layers hang from these. */
  waitsOn?: { taskId: string; projectId: string }[]
  /** The recorded wording behind the mark (task description / notes /
   *  completion criteria), preserved for the dossier popup. */
  detail: string
  fraction: number
  rule: string
}

const DOMAIN_LABEL: Record<ObstacleDomain, string> = {
  time: 'Time',
  money: 'Money / resources',
  body: 'Body / energy',
  people: 'People / dependencies',
  knowledge: 'Knowledge / information',
  entropy: 'Entropy / upkeep',
}

export function obstacleDomainLabel(d: ObstacleDomain): string {
  return DOMAIN_LABEL[d]
}

export function deriveObstacles(
  project: Project,
  projectTasks: Task[],
  allTasks: Task[],
  span: BoardSpan,
  nowMs: number,
): BoardObstacle[] {
  const byId = new Map(allTasks.map((t) => [t.id, t]))
  const dependedUpon = new Set<string>()
  for (const t of allTasks) for (const d of t.dependency_ids ?? []) dependedUpon.add(d)

  const out: BoardObstacle[] = []
  const fractionOf = (t: Task, rank: number, count: number): number => {
    const due = parseDateMs(t.due_date)
    if (due != null) return fractionForDate(span, due)
    return (rank + 1) / (count + 1)
  }

  projectTasks.forEach((t, i) => {
    if (!isOpenTask(t)) return
    const frac = fractionOf(t, i, projectTasks.length)
    const detail = (t.description || '').trim() || (t.notes || '').trim()
    const deps = (t.dependency_ids ?? []).map((id) => byId.get(id)).filter((x): x is Task => !!x)
    const incompleteDeps = deps.filter((d) => !isDoneTask(d))

    // State obstacle — at most one per task, strongest first.
    if (t.status === 'Blocked' && t.assignee_id) {
      out.push({
        id: t.id,
        taskId: t.id,
        kind: 'resistance',
        kindLabel: 'Combatant Resistance',
        domain: 'people',
        standing: 'documented',
        label: t.title,
        detail,
        fraction: frac,
        rule: 'A recorded Blocked task standing with a named person: what can refuse or be negotiated with is declared a combatant resistance — not weather, not terrain.',
      })
    } else if (t.status === 'Blocked') {
      out.push({
        id: t.id,
        taskId: t.id,
        kind: 'blocked',
        kindLabel: 'Confirmed blockage',
        domain: incompleteDeps.length > 0 ? 'people' : 'knowledge',
        standing: 'documented',
        label: t.title,
        detail,
        fraction: frac,
        rule:
          incompleteDeps.length > 0
            ? `Recorded as Blocked, with ${incompleteDeps.length} unfinished ${incompleteDeps.length === 1 ? 'dependency' : 'dependencies'} in front of it.`
            : 'Recorded as Blocked in Vision Execution. The block is documented; its nature is not yet examined.',
      })
    } else {
      const due = parseDateMs(t.due_date)
      if (due != null && due < nowMs) {
        out.push({
          id: t.id,
          taskId: t.id,
          kind: 'overdue',
          kindLabel: 'Past its recorded date',
          domain: 'time',
          standing: 'documented',
          label: t.title,
          detail,
          fraction: frac,
          rule: 'The recorded due date has passed and the task is still open. A neutral observation from the record — not a verdict.',
        })
      }
    }

    // Crossing — continuation depends on another project's unfinished work.
    const crossDeps = incompleteDeps.filter((d) => d.project_id && d.project_id !== project.id)
    if (crossDeps.length > 0) {
      out.push({
        id: `${t.id}:crossing`,
        taskId: t.id,
        kind: 'crossing',
        kindLabel: 'Crossing',
        domain: 'people',
        standing: 'documented',
        label: t.title,
        detail,
        fraction: frac,
        waitsOn: crossDeps.map((d) => ({ taskId: d.id, projectId: d.project_id! })),
        rule: `This step waits on unfinished work in another project: ${crossDeps.map((d) => `“${d.title}”`).join(', ')}. A crossing — continuation depends on something not yet secured.`,
      })
    }

    // Gate Keeper — a stated condition other work waits behind.
    if ((t.completion_criteria || '').trim() && dependedUpon.has(t.id)) {
      out.push({
        id: `${t.id}:gate`,
        taskId: t.id,
        kind: 'gate',
        kindLabel: 'Gate Keeper',
        domain: 'people',
        standing: 'documented',
        label: t.title,
        detail: (t.completion_criteria || '').trim(),
        fraction: frac,
        rule: 'Other recorded work depends on this step, and it carries a stated completion condition. Anything that must be satisfied before passage is declared a gate keeper.',
      })
    }
  })
  return out
}

/* ------------------------------------------------------------------ */
/* Terrain (declared from the material, never decoration)              */
/* ------------------------------------------------------------------ */

export type TerrainKind = 'mountain' | 'hill' | 'open' | 'grove' | 'copse'

export interface TerrainFeature {
  kind: TerrainKind
  form: string
  /** Anchor task id — the feature stands where its source task stands. */
  taskId: string
  sourceLabel: string
  effortDays?: number
  treeCount?: number
  rule: string
  fact: string
}

export function declareTerrain(projectTasks: Task[]): TerrainFeature[] {
  const features: TerrainFeature[] = []
  const open = projectTasks.filter(isOpenTask)

  // The Mountain / Hill / Open Ground: the largest single massed effort.
  const withEffort = open.filter((t) => t.estimated_hours != null && t.estimated_hours > 0)
  if (withEffort.length > 0) {
    const biggest = withEffort.reduce((a, b) => ((b.estimated_hours ?? 0) > (a.estimated_hours ?? 0) ? b : a))
    const days = Math.round(((biggest.estimated_hours ?? 0) / HOURS_PER_WORKDAY) * 10) / 10
    const kind: TerrainKind = days >= 2.5 ? 'mountain' : days >= 1 ? 'hill' : 'open'
    const form = kind === 'mountain' ? 'The Mountain' : kind === 'hill' ? 'The Hill' : 'Open Ground'
    features.push({
      kind,
      form,
      taskId: biggest.id,
      sourceLabel: biggest.title,
      effortDays: days,
      rule: `Largest single effort between start and finish: ${days} workdays in one step (${biggest.estimated_hours} recorded hours). Effort massed in one place is declared a mountain; under 2.5 workdays it is only a hill, and under one it is open ground.`,
      fact: `It is “${biggest.title}”. Its height on the map is its recorded effort — ${days} workdays.`,
    })
  }

  // The Grove / Copse: a cluster of small tasks under one parent.
  const childrenByParent = new Map<string, Task[]>()
  for (const t of projectTasks) {
    if (t.parent_task_id) {
      const arr = childrenByParent.get(t.parent_task_id) ?? []
      arr.push(t)
      childrenByParent.set(t.parent_task_id, arr)
    }
  }
  const parents = [...childrenByParent.entries()]
    .map(([parentId, kids]) => ({
      parent: projectTasks.find((t) => t.id === parentId),
      kids: kids.filter((k) => k.status !== 'Dropped'),
    }))
    .filter((x): x is { parent: Task; kids: Task[] } => !!x.parent && x.kids.length >= 2)
    .sort((a, b) => b.kids.length - a.kids.length)
    .slice(0, 3)
  for (const { parent, kids } of parents) {
    const kind: TerrainKind = kids.length >= 3 ? 'grove' : 'copse'
    features.push({
      kind,
      form: kind === 'grove' ? 'The Grove' : 'The Copse',
      taskId: parent.id,
      sourceLabel: parent.title,
      treeCount: kids.length,
      rule: `Not one task but a cluster of ${kids.length} small ones under “${parent.title}”. Many small trunks close together are declared a grove — no single tree blocks you; the walking-through is the work.`,
      fact: `One tree per subtask — ${kids.length} trees standing for ${kids.length} named pieces of work under “${parent.title}”.`,
    })
  }
  return features
}

/* ------------------------------------------------------------------ */
/* Routes & waypoints                                                  */
/* ------------------------------------------------------------------ */

export interface BoardWaypoint {
  task: Task
  fraction: number
  /** True when the position comes from a recorded due date (vs. rank
   *  placement for an undated task). */
  dated: boolean
  done: boolean
}

function topoOrder(tasks: Task[]): Task[] {
  const ids = new Set(tasks.map((t) => t.id))
  const byId = new Map(tasks.map((t) => [t.id, t]))
  const done = new Set<string>()
  const out: Task[] = []
  const rest = [...tasks]
  let guard = rest.length * rest.length + 1
  while (rest.length && guard-- > 0) {
    const idx = rest.findIndex((t) =>
      (t.dependency_ids ?? []).every((d) => !ids.has(d) || done.has(d) || !byId.has(d)),
    )
    if (idx === -1) {
      out.push(...rest)
      break
    }
    const [t] = rest.splice(idx, 1)
    done.add(t.id)
    out.push(t)
  }
  return out
}

function withFractions(ordered: Task[], span: BoardSpan): BoardWaypoint[] {
  return ordered.map((task, i) => {
    const due = parseDateMs(task.due_date)
    return {
      task,
      fraction: due != null ? fractionForDate(span, due) : (i + 1) / (ordered.length + 1),
      dated: due != null,
      done: isDoneTask(task),
    }
  })
}

/**
 * Two speculative routes over the same recorded steps (brief Family D):
 *  - Route A, "By date": steps in recorded due-date order.
 *  - Route B, "Dependencies first": steps in dependency order, heaviest
 *    effort first among equals.
 * Both are proposals — arrangements of existing tasks, never new records.
 * Done tasks ride Route A as completed markers only.
 */
export function buildRoutes(
  projectTasks: Task[],
  span: BoardSpan,
): { a: BoardWaypoint[]; b: BoardWaypoint[] } {
  const open = projectTasks.filter(isOpenTask)
  const doneTasks = projectTasks.filter(isDoneTask)
  const byDate = [...open].sort((x, y) => {
    const dx = parseDateMs(x.due_date)
    const dy = parseDateMs(y.due_date)
    if (dx != null && dy != null) return dx - dy
    if (dx != null) return -1
    if (dy != null) return 1
    return x.created_at.localeCompare(y.created_at)
  })
  const byDeps = topoOrder(
    [...open].sort((x, y) => (y.estimated_hours ?? -1) - (x.estimated_hours ?? -1)),
  )
  const a = withFractions(byDate, span)
  for (const d of doneTasks) {
    const due = parseDateMs(d.due_date)
    a.push({
      task: d,
      fraction: due != null ? fractionForDate(span, due) : 0.98,
      dated: due != null,
      done: true,
    })
  }
  a.sort((x, y) => x.fraction - y.fraction)
  return { a, b: withFractions(byDeps, span) }
}

/* ------------------------------------------------------------------ */
/* Overview                                                            */
/* ------------------------------------------------------------------ */

/** A declared terrain feature placed on the overview route:
 *  the feature itself, plus where it stands — the anchor task's
 *  recorded due date within the span, else its rank among the
 *  project's tasks (the obstacle placement rule). */
export interface OverviewTerrain extends TerrainFeature {
  fraction: number
}

/** One layer of a route's Gantt of sentences (founder,
 *  2026-11-27): a sub-journey pinned to the main route at a
 *  dependency joint (♦) or at a grove (🌳), drawn as its own
 *  sentence — its own tally, its own terrain, its own finish.
 *  A crossing's layer is the waited-on project's whole route;
 *  a grove's layer is the parent step's children, branching
 *  off the route where the grove stands. */
export interface OverviewLayer {
  id: string
  kind: 'crossing' | 'grove'
  /** Where the layer pins on the main route, 0..1 of the line. */
  pinFraction: number
  /** The name the layer carries: the waited-on step for a
   *  crossing, the parent step for a grove — real names. */
  label: string
  /** The other project's title for a crossing; '' for a grove. */
  subLabel: string
  /** The sub-journey's own length in days. */
  spanDays: number
  /** The sub-journey's placed terrain. */
  terrain: OverviewTerrain[]
  /** Fractions within the sub-journey where its own
   *  dependency joints (crossings and gates) stand. */
  joints: number[]
}

export interface OverviewProject {
  project: Project
  span: BoardSpan
  obstacles: BoardObstacle[]
  terrain: OverviewTerrain[]
  /** Dependency and grove layers under the route, in pin
   *  order, at most four. */
  layers: OverviewLayer[]
  openTaskCount: number
  doneTaskCount: number
  /** Days of line to draw: the real span, or NOMINAL_DAYS (flagged
   *  not-to-scale) when no dates are recorded. */
  routeDays: number
  /** True when the project carries a real recorded span (its own
   *  dates, or a window recovered from task due dates). An unspanned
   *  project has no dates recorded anywhere: on the overview map it
   *  stands at its camp with its finish flag unplanted — its route is
   *  never stretched to an invented length. */
  spanned: boolean
}

const STATUS_ORDER: Record<string, number> = { Active: 0, Blocked: 1, Ready: 2, Draft: 3, Parked: 4 }

export function buildOverview(
  projects: Project[],
  tasks: Task[],
  nowMs: number,
): OverviewProject[] {
  const base: OverviewProject[] = projects
    .filter((p) => p.status !== 'Complete')
    .map((project) => {
      const projectTasks = tasks.filter((t) => t.project_id === project.id)
      const span = projectSpan(project, projectTasks, nowMs)
      const terrain: OverviewTerrain[] = declareTerrain(projectTasks).map((f) => {
        const idx = projectTasks.findIndex((t) => t.id === f.taskId)
        const anchor = idx >= 0 ? projectTasks[idx] : null
        const due = anchor ? parseDateMs(anchor.due_date) : null
        return {
          ...f,
          fraction: due != null ? fractionForDate(span, due) : (idx + 1) / (projectTasks.length + 1),
        }
      })
      return {
        project,
        span,
        obstacles: deriveObstacles(project, projectTasks, tasks, span, nowMs),
        terrain,
        layers: [] as OverviewLayer[],
        openTaskCount: projectTasks.filter(isOpenTask).length,
        doneTaskCount: projectTasks.filter(isDoneTask).length,
        routeDays: span.source === 'provisional' ? NOMINAL_DAYS : span.days,
        spanned: span.source !== 'provisional',
      }
    })

  // Second pass: the layers. A crossing's layer is the
  // waited-on project's own sentence, pinned at the joint; a
  // grove's layer is its parent step's children, branching
  // from where the grove stands — their window is the
  // children's recorded dates, and a grove whose children
  // carry no dates grows no layer (no invented length).
  const byId = new Map(base.map((o) => [o.project.id, o]))
  const placeIn = (list: Task[], span: BoardSpan): OverviewTerrain[] =>
    declareTerrain(list).map((f) => {
      const idx = list.findIndex((t) => t.id === f.taskId)
      const anchor = idx >= 0 ? list[idx] : null
      const due = anchor ? parseDateMs(anchor.due_date) : null
      return { ...f, fraction: due != null ? fractionForDate(span, due) : (idx + 1) / (list.length + 1) }
    })
  for (const o of base) {
    const layers: OverviewLayer[] = []
    for (const ob of o.obstacles) {
      if (ob.kind !== 'crossing' || !ob.waitsOn?.length) continue
      const other = byId.get(ob.waitsOn[0].projectId)
      if (!other || other.project.id === o.project.id) continue
      const waited = tasks.find((t) => t.id === ob.waitsOn![0].taskId)
      layers.push({
        id: `${ob.id}:layer`,
        kind: 'crossing',
        pinFraction: ob.fraction,
        label: waited?.title ?? ob.label,
        subLabel: other.project.title,
        spanDays: other.span.days,
        terrain: other.terrain,
        joints: other.obstacles
          .filter((x) => x.kind === 'crossing' || x.kind === 'gate')
          .map((x) => x.fraction),
      })
    }
    const projectTasks = tasks.filter((t) => t.project_id === o.project.id)
    for (const f of o.terrain) {
      if (f.kind !== 'grove') continue
      const children = projectTasks.filter((t) => t.parent_task_id === f.taskId)
      if (children.length === 0) continue
      const dues = children
        .map((t) => parseDateMs(t.due_date))
        .filter((x): x is number => x != null)
        .sort((a, b) => a - b)
      const parent = projectTasks.find((t) => t.id === f.taskId)
      const parentDue = parent ? parseDateMs(parent.due_date) : null
      const start = dues.length ? dues[0] : parentDue
      let end = dues.length ? dues[dues.length - 1] : parentDue
      if (start == null || end == null) continue
      if (end <= start) end = start + DAY_MS
      const childSpan: BoardSpan = {
        startMs: start,
        endMs: end,
        days: Math.max(1, Math.round((end - start) / DAY_MS)),
        source: 'tasks',
      }
      const childObstacles = deriveObstacles(o.project, children, tasks, childSpan, nowMs)
      layers.push({
        id: `${f.taskId}:grove-layer`,
        kind: 'grove',
        pinFraction: f.fraction,
        label: f.sourceLabel,
        subLabel: '',
        spanDays: childSpan.days,
        terrain: placeIn(children, childSpan),
        joints: childObstacles
          .filter((x) => x.kind === 'crossing' || x.kind === 'gate')
          .map((x) => x.fraction),
      })
    }
    o.layers = layers.sort((a, b) => a.pinFraction - b.pinFraction).slice(0, 4)
  }

  return base.sort((x, y) => {
    const sx = STATUS_ORDER[x.project.status] ?? 5
    const sy = STATUS_ORDER[y.project.status] ?? 5
    if (sx !== sy) return sx - sy
    return x.project.title.localeCompare(y.project.title)
  })
}

/* ------------------------------------------------------------------ */
/* Overview nesting — projects under their initiatives                 */
/* ------------------------------------------------------------------ */

export interface OverviewGroup {
  /** The initiative this ground belongs to, or null for the
   *  unanchored ground (projects with no initiative — the Radar's
   *  "unanchored"). */
  initiative: { id: string; title: string } | null
  projects: OverviewProject[]
  /** The initiative's own timeline: the envelope of its
   *  projects' recorded spans — earliest start to latest
   *  finish — or null when no project under it carries dates.
   *  An initiative with no dated work has no timeline; the
   *  board never invents one. */
  span: BoardSpan | null
}

/**
 * Nest the overview under initiatives: one ground per initiative,
 * its projects' routes running within it. Groups appear in the order
 * their first project appears on the board (the overview's own
 * status/title order); the unanchored ground comes last. A project
 * whose initiative_id names no fetched initiative is unanchored for
 * the map's purposes — the board cannot letter a name it does not
 * have. Initiatives with no projects on the board get no ground.
 */
export function groupOverviewByInitiative(
  overview: OverviewProject[],
  initiatives: { id: string; title: string }[],
): OverviewGroup[] {
  const byId = new Map(initiatives.map((i) => [i.id, i]))
  const groups: OverviewGroup[] = []
  const groupByInitiativeId = new Map<string, OverviewGroup>()
  const unanchored: OverviewGroup = { initiative: null, projects: [], span: null }
  for (const o of overview) {
    const initiative = o.project.initiative_id ? byId.get(o.project.initiative_id) : undefined
    if (!initiative) {
      unanchored.projects.push(o)
      continue
    }
    let group = groupByInitiativeId.get(initiative.id)
    if (!group) {
      group = { initiative: { id: initiative.id, title: initiative.title }, projects: [], span: null }
      groupByInitiativeId.set(initiative.id, group)
      groups.push(group)
    }
    group.projects.push(o)
  }
  if (unanchored.projects.length > 0) groups.push(unanchored)
  for (const g of groups) {
    const spanned = g.projects.filter((o) => o.spanned)
    if (spanned.length === 0) continue
    const startMs = Math.min(...spanned.map((o) => o.span.startMs))
    const endMs = Math.max(...spanned.map((o) => o.span.endMs))
    g.span = {
      startMs,
      endMs,
      days: Math.max(1, Math.round((endMs - startMs) / DAY_MS)),
      source: 'tasks',
    }
  }
  return groups
}

/** Pixels per day so the longest real route fits the map, capped at the
 *  prototype's 26px/day. Provisional spans never stretch the scale. */
export function computePxPerDay(overview: OverviewProject[], availablePx: number): number {
  const realDays = overview.filter((o) => o.span.source !== 'provisional').map((o) => o.span.days)
  const maxDays = realDays.length ? Math.max(...realDays) : 0
  if (!maxDays) return MAX_PX_PER_DAY
  return Math.min(MAX_PX_PER_DAY, Math.max(4, availablePx / maxDays))
}

/* ------------------------------------------------------------------ */
/* Signals — reported circumstance material (Layer 1)                  */
/* ------------------------------------------------------------------ */

/**
 * A Signal row as returned by GET /signals (the canonical Layer-1
 * circumstance entity; the Radar is a view over these). Links to
 * initiatives/projects/tasks are owner-validated at write time.
 */
export interface BoardSignal {
  id: string
  kind: string
  title: string
  detail: string | null
  source: string
  source_excerpt: string | null
  confidence: number | null
  linked_initiative_id: string | null
  linked_project_id: string | null
  linked_task_id: string | null
  status: string
  created_at: string
}

export type SignalLinkVia = 'project' | 'task' | 'initiative'

export interface ProjectSignal {
  signal: BoardSignal
  via: SignalLinkVia
  /** The project's task the signal is linked to, when via === 'task'. */
  taskId: string | null
}

const OPEN_SIGNAL_EXCLUDED = new Set(['resolved', 'dismissed'])

/**
 * The project's open signals: linked to the project itself, to one of
 * its tasks, or to its initiative. The board asks the API for
 * status_not=resolved,dismissed (the Radar's own filter); the status
 * check is repeated here so the rule holds whatever the caller fetched.
 */
export function signalsForProject(
  signals: BoardSignal[],
  project: Project,
  projectTasks: Task[],
): ProjectSignal[] {
  const taskIds = new Set(projectTasks.map((t) => t.id))
  const out: ProjectSignal[] = []
  for (const s of signals) {
    if (OPEN_SIGNAL_EXCLUDED.has((s.status || '').toLowerCase())) continue
    if (s.linked_project_id === project.id) {
      out.push({ signal: s, via: 'project', taskId: null })
    } else if (s.linked_task_id && taskIds.has(s.linked_task_id)) {
      out.push({ signal: s, via: 'task', taskId: s.linked_task_id })
    } else if (project.initiative_id && s.linked_initiative_id === project.initiative_id) {
      out.push({ signal: s, via: 'initiative', taskId: null })
    }
  }
  return out.sort((a, b) => a.signal.created_at.localeCompare(b.signal.created_at))
}

export interface SignalMarker {
  /** `signal:${signal.id}` */
  id: string
  signal: BoardSignal
  via: SignalLinkVia
  taskId: string | null
  fraction: number
  /** Signals are REPORTED material — a circumstance someone recorded,
   *  never a confirmed state of the work. The board never upgrades a
   *  signal's standing. */
  standing: 'reported'
  kindLabel: string
  rule: string
}

const SIGNAL_KIND_LABEL: Record<string, string> = {
  blocker: 'Reported blocker',
  risk: 'Reported risk',
  opportunity: 'Reported opening',
  attention: 'Reported circumstance',
}

export function signalKindLabel(kind: string): string {
  return SIGNAL_KIND_LABEL[(kind || '').toLowerCase()] ?? 'Reported circumstance'
}

/**
 * Place the project's signals on the line. A task-linked signal stands
 * where its task stands (recorded due date, else rank — the obstacle
 * rule). Any other signal stands at its recorded date within the span.
 */
export function deriveSignalMarkers(
  projectSignals: ProjectSignal[],
  projectTasks: Task[],
  span: BoardSpan,
): SignalMarker[] {
  return projectSignals.map((ps, i) => {
    let fraction: number
    const task = ps.taskId ? projectTasks.find((t) => t.id === ps.taskId) : undefined
    if (task) {
      const due = parseDateMs(task.due_date)
      fraction =
        due != null
          ? fractionForDate(span, due)
          : (projectTasks.indexOf(task) + 1) / (projectTasks.length + 1)
    } else {
      const created = parseDateMs(ps.signal.created_at)
      fraction = created != null ? fractionForDate(span, created) : (i + 1) / (projectSignals.length + 1)
    }
    const created = parseDateMs(ps.signal.created_at)
    return {
      id: `signal:${ps.signal.id}`,
      signal: ps.signal,
      via: ps.via,
      taskId: ps.taskId,
      fraction,
      standing: 'reported' as const,
      kindLabel: signalKindLabel(ps.signal.kind),
      rule:
        `A circumstance recorded as a signal${created != null ? ` on ${shortDate(new Date(created))}` : ''}` +
        (ps.signal.source ? `, from ${ps.signal.source}` : '') +
        '. Reported material — it has not been confirmed against the work itself.',
    }
  })
}

/* ------------------------------------------------------------------ */
/* Capacity — the time-constraint picture (the Radar's computation).   */
/* The arithmetic is the shared frontend mirror of derived.py's        */
/* add_capacity_derived (vision-execution/capacityDerived.ts): the     */
/* committed sum is judged UNROUNDED — rounding is display only, so    */
/* 10.04 committed against a capacity of 10 is over, exactly as the    */
/* backend (and the Radar's bucket) rules it.                          */
/* ------------------------------------------------------------------ */

export interface PersonCapacity {
  personId: string
  name: string
  /** Recorded weekly capacity, or null when no profile is recorded. */
  weeklyCapacityHours: number | null
  /** Committed hours (derived.py's activeWeeklyHours): the sum over
   *  the person's Ready/Active projects (owned or supported), rounded
   *  to one decimal for display — judgements never read this figure. */
  committedHours: number
  /** derived.py's capacityDelta: the UNROUNDED committed sum minus
   *  capacity, rounded to one decimal for display; null when no
   *  capacity is recorded. */
  delta: number | null
  /** derived.py's overcapacity: the UNROUNDED difference > 0 — the
   *  same condition the Radar's overcapacity bucket reads. */
  over: boolean
  rule: string
}

/**
 * The capacity picture for the people on this project's work: its
 * owner, its supporting owners, and the assignees of its tasks —
 * each against ALL their committed work, because capacity is spent
 * across projects, not inside one.
 */
export function deriveCapacityPicture(
  project: Project,
  allProjects: Project[],
  persons: Person[],
  profiles: CapacityProfile[],
  projectTasks: Task[],
): PersonCapacity[] {
  const personIds: string[] = []
  const add = (id: string | null | undefined) => {
    if (id && !personIds.includes(id)) personIds.push(id)
  }
  add(project.owner_id)
  for (const id of project.supporting_owner_ids ?? []) add(id)
  for (const t of projectTasks) add(t.assignee_id)

  const byId = new Map(persons.map((p) => [p.id, p]))
  const profileByPerson = new Map(profiles.map((c) => [c.person_id, c]))
  const out: PersonCapacity[] = []
  for (const pid of personIds) {
    const person = byId.get(pid)
    if (!person) continue
    const cap = profileByPerson.get(pid)?.weekly_capacity_hours
    const weeklyCapacityHours = cap != null ? Number(cap) : null
    const derived = capacityDerived(allProjects, weeklyCapacityHours, pid)
    const committed = derived.committedHours
    const delta = derived.capacityDelta
    const over = derived.over
    out.push({
      personId: pid,
      name: person.name,
      weeklyCapacityHours,
      committedHours: committed,
      delta,
      over,
      rule: over
        ? `Committed work totals ${committed}h a week across Ready/Active projects ${person.name} owns or supports, against a recorded capacity of ${weeklyCapacityHours}h — the overcapacity condition the Radar watches for.`
        : weeklyCapacityHours != null
          ? `Committed work totals ${committed}h a week across Ready/Active projects ${person.name} owns or supports, within a recorded capacity of ${weeklyCapacityHours}h.`
          : `Committed work totals ${committed}h a week across Ready/Active projects ${person.name} owns or supports. No weekly capacity is recorded, so no overcapacity judgement is made.`,
    })
  }
  return out.sort((a, b) => Number(b.over) - Number(a.over) || a.name.localeCompare(b.name))
}

/* ------------------------------------------------------------------ */
/* Declarations — Rivers and Holds (recorded, derived from decisions)  */
/* ------------------------------------------------------------------ */

/**
 * Declarations are the user's own fixings of the terrain (founder
 * doctrine 2026-11-17: terrain is derived, conversed, and DECLARED).
 * Since the Board interaction pass (2026-11-25) they are made in
 * conversation with Valen and recorded as Vision Execution DECISIONS
 * (dedicated decision types; see local_ai/vision_execution/
 * declarations.py). The board only READS them: current state is
 * derived here by folding the project's declaration decisions in
 * recorded order — the mirror of the backend fold, over the same
 * rows. One River per project (the latest river event wins; a
 * withdrawal clears it); Holds are many, keyed by their placing
 * decision's id, moved and removed by later decisions naming it.
 */

export interface RiverDeclaration {
  /** The river_declaration decision's id. */
  id: string
  projectId: string
  startMs: number
  endMs: number
}

export interface HoldDeclaration {
  /** The hold_placed decision's id — the hold's name in the record. */
  id: string
  projectId: string
  /** Where the checkpoint stands, as a recorded moment. Its place
   *  on the line is derived against the current span at render. */
  atMs: number
}

/** A decision row as returned by GET /decisions (owner-scoped). */
export interface BoardDecisionRow {
  id: string
  entity_type: string
  entity_id: string
  decision_type: string
  final_values_snapshot: Record<string, unknown> | null
  created_at: string
}

export interface ProjectDeclarations {
  river: RiverDeclaration | null
  holds: HoldDeclaration[]
}

const DECLARATION_TYPES = new Set([
  'river_declaration',
  'river_withdrawal',
  'hold_placed',
  'hold_moved',
  'hold_removed',
])

function snapshotMs(snap: Record<string, unknown> | null, key: string): number | null {
  if (!snap) return null
  const v = snap[key]
  return typeof v === 'string' ? parseDateMs(v) : null
}

/**
 * Fold decision rows (any order — the API returns newest first)
 * into per-project declaration state. The replay is oldest-first,
 * mirroring the backend fold over the same rows: a malformed row
 * degrades to no declaration, never to a broken board.
 */
export function deriveDeclarations(decisions: BoardDecisionRow[]): {
  rivers: RiverDeclaration[]
  holds: HoldDeclaration[]
} {
  const byProject = new Map<string, { river: RiverDeclaration | null; holds: Map<string, HoldDeclaration> }>()
  const rows = [...decisions].reverse()
  for (const row of rows) {
    if (!DECLARATION_TYPES.has(row.decision_type)) continue
    if (row.entity_type !== 'project' || !row.entity_id) continue
    let entry = byProject.get(row.entity_id)
    if (!entry) {
      entry = { river: null, holds: new Map() }
      byProject.set(row.entity_id, entry)
    }
    const snap = row.final_values_snapshot
    if (row.decision_type === 'river_declaration') {
      const startMs = snapshotMs(snap, 'start')
      const endMs = snapshotMs(snap, 'end')
      if (startMs != null && endMs != null) {
        entry.river = { id: row.id, projectId: row.entity_id, startMs, endMs }
      }
    } else if (row.decision_type === 'river_withdrawal') {
      entry.river = null
    } else if (row.decision_type === 'hold_placed') {
      const atMs = snapshotMs(snap, 'at')
      if (atMs != null && row.id) {
        entry.holds.set(row.id, { id: row.id, projectId: row.entity_id, atMs })
      }
    } else if (row.decision_type === 'hold_moved') {
      const holdId = typeof snap?.hold_id === 'string' ? snap.hold_id : ''
      const atMs = snapshotMs(snap, 'at')
      const hold = entry.holds.get(holdId)
      if (hold && atMs != null) entry.holds.set(holdId, { ...hold, atMs })
    } else if (row.decision_type === 'hold_removed') {
      const holdId = typeof snap?.hold_id === 'string' ? snap.hold_id : ''
      entry.holds.delete(holdId)
    }
  }
  const rivers: RiverDeclaration[] = []
  const holds: HoldDeclaration[] = []
  for (const entry of byProject.values()) {
    if (entry.river) rivers.push(entry.river)
    holds.push(...[...entry.holds.values()].sort((a, b) => a.atMs - b.atMs))
  }
  return { rivers, holds }
}

/** The river's band on the line: span fractions for its window,
 *  always wide enough to see and to tap. */
export function riverBand(
  span: BoardSpan,
  river: RiverDeclaration,
): { startFraction: number; endFraction: number } {
  const raw = (ms: number) => (ms - span.startMs) / (span.endMs - span.startMs)
  let start = Math.min(0.97, Math.max(0.01, raw(river.startMs)))
  let end = Math.min(0.99, Math.max(0.03, raw(river.endMs)))
  if (end - start < 0.02) end = Math.min(0.99, start + 0.02)
  return { startFraction: start, endFraction: end }
}

/* ------------------------------------------------------------------ */
/* Label layout — de-overlap for the focus board's lettering           */
/* ------------------------------------------------------------------ */

/**
 * The focus board's labels (waypoint title/date pairs, the start and
 * finish banner labels, obstacle labels) used to be placed by pure
 * functions of fraction and index — nothing ever looked at another
 * label, so wherever dates cluster (above all at the finish, where
 * both routes converge and done tasks are appended at fraction 0.98)
 * the lettering printed on top of itself. This pass is the board's
 * equivalent of the Atelier Well's gardenLayout: a pure, deterministic
 * de-overlap over label boxes. It moves lettering only — routes,
 * fractions, and derivations are untouched.
 */

export interface BoardLabelItem {
  /** Stable identity, echoed back in the placement. */
  id: string
  /** Desired center x of the label box (board units). */
  anchorX: number
  /** Desired top y of the label box (board units). */
  top: number
  /** Estimated box width (board units). */
  width: number
  /** Box height (board units). */
  height: number
}

export interface BoardLabelPlacement {
  id: string
  /** Placed center x — the box lies inside the bounds. */
  x: number
  /** Placed top y — the box lies inside the bounds. */
  top: number
  width: number
  height: number
}

export interface BoardLabelBounds {
  minX: number
  maxX: number
  minY: number
  maxY: number
}

/** Estimated rendered width of a line of SVG text. Deliberately a
 *  touch generous (the diagnosis measured ≈5.6 units per character
 *  at fontSize 11): an over-estimate costs a little air, an
 *  under-estimate costs a collision. */
export function estimateLabelWidth(text: string, fontSize: number): number {
  return text.length * fontSize * 0.55 + 4
}

interface LabelBox {
  id: string
  cx: number
  top: number
  w: number
  h: number
}

function labelOverlap(a: LabelBox, b: LabelBox, gap: number): { ox: number; oy: number } | null {
  const ox =
    Math.min(a.cx + a.w / 2 + gap, b.cx + b.w / 2 + gap) - Math.max(a.cx - a.w / 2, b.cx - b.w / 2)
  const oy = Math.min(a.top + a.h + gap, b.top + b.h + gap) - Math.max(a.top, b.top)
  return ox > 0 && oy > 0 ? { ox, oy } : null
}

function clampLabelBox(box: LabelBox, bounds: BoardLabelBounds): void {
  if (box.w >= bounds.maxX - bounds.minX) {
    box.cx = (bounds.minX + bounds.maxX) / 2
  } else {
    box.cx = Math.min(bounds.maxX - box.w / 2, Math.max(bounds.minX + box.w / 2, box.cx))
  }
  if (box.h >= bounds.maxY - bounds.minY) {
    box.top = bounds.minY
  } else {
    box.top = Math.min(bounds.maxY - box.h, Math.max(bounds.minY, box.top))
  }
}

/**
 * Place label boxes so they do not overlap. Deterministic: fixed
 * iteration order, no randomness — the same items always place the
 * same way, and placements come back in input order.
 *
 * Method (the Well's pattern): start every box at its anchor, clamped
 * into the bounds; relax by pushing each overlapping pair apart along
 * their smaller overlap axis, half and half, re-clamping as we go;
 * if any pair still overlaps after the relaxation budget, finish with
 * a deterministic vertical stack sweep (the lower box moves below the
 * upper, in reading order) until no pair overlaps or the sweep budget
 * runs out.
 *
 * The promise: every returned box lies entirely inside the bounds
 * (any box that itself fits the bounds), and no label is ever dropped.
 * Pairwise non-overlap holds whenever the labels can be stacked
 * within the field in their anchor columns — the sweep enforces it
 * unless a single column's labels are together taller than the field
 * itself, in which case the boxes stay clamped in-bounds in their
 * least-overlapping deterministic arrangement.
 */
export function layoutBoardLabels(
  items: BoardLabelItem[],
  bounds: BoardLabelBounds,
  gap = 2,
): BoardLabelPlacement[] {
  if (items.length === 0) return []
  const placed: LabelBox[] = items.map((it) => {
    const box: LabelBox = { id: it.id, cx: it.anchorX, top: it.top, w: it.width, h: it.height }
    clampLabelBox(box, bounds)
    return box
  })

  // Relaxation — push overlapping pairs apart along the smaller axis.
  for (let iter = 0; iter < 240; iter++) {
    let moved = false
    for (let i = 0; i < placed.length; i++) {
      for (let j = i + 1; j < placed.length; j++) {
        const o = labelOverlap(placed[i], placed[j], gap)
        if (!o) continue
        moved = true
        const a = placed[i]
        const b = placed[j]
        if (o.ox < o.oy) {
          const dir = b.cx >= a.cx ? 1 : -1
          a.cx -= (dir * o.ox) / 2
          b.cx += (dir * o.ox) / 2
        } else {
          const dir = b.top >= a.top ? 1 : -1
          a.top -= (dir * o.oy) / 2
          b.top += (dir * o.oy) / 2
        }
        clampLabelBox(a, bounds)
        clampLabelBox(b, bounds)
      }
    }
    if (!moved) break
  }

  // Stack sweep — the guarantee's backstop: any pair still
  // overlapping is separated vertically, the lower box (later in
  // reading order on a tie) moving below the upper one.
  for (let pass = 0; pass < 60; pass++) {
    let moved = false
    for (let i = 0; i < placed.length; i++) {
      for (let j = i + 1; j < placed.length; j++) {
        if (!labelOverlap(placed[i], placed[j], gap)) continue
        const upper = placed[i].top <= placed[j].top ? placed[i] : placed[j]
        const lower = upper === placed[i] ? placed[j] : placed[i]
        lower.top = upper.top + upper.h + gap
        clampLabelBox(lower, bounds)
        moved = true
      }
    }
    if (!moved) break
  }

  return placed.map((p) => ({ id: p.id, x: p.cx, top: p.top, width: p.w, height: p.h }))
}

/* ------------------------------------------------------------------ */
/* Timeline strip — one label per anchor, no bound printed twice       */
/* ------------------------------------------------------------------ */

export interface StripLabel {
  /** The anchor the label (and its tick) stands at. */
  fraction: number
  /** The single label printed at that anchor. */
  text: string
}

/** Two waypoints stand at the same anchor when their fractions are
 *  this close — on any realistic span that means the same recorded
 *  moment (identical dates produce identical fractions, and the
 *  fraction clamps pile the ends onto 0.02 / 0.98 exactly). */
const STRIP_ANCHOR_EPSILON = 0.005
/** A waypoint coincides with a span bound when its (clamped)
 *  fraction sits this close to the corresponding end. */
const STRIP_BOUND_EPSILON = 0.03

/**
 * The timeline strip's below-line labels, derived from Route A.
 *
 * The strip used to print the span's start and end dates above the
 * line AND every waypoint's date below it — so each bound date
 * appeared twice by construction, and two waypoints sharing the
 * finish anchor printed glyph-on-glyph. Here: waypoints are grouped
 * by anchor; within a group, a date that merely repeats the span
 * bound the group coincides with is dropped (the bound above the
 * line already says it); the group's surviving texts are merged into
 * ONE label. Each date is therefore printed at most once per anchor,
 * bounds are never duplicated, and no anchor carries two labels.
 */
export function stripWaypointLabels(waypoints: BoardWaypoint[], span: BoardSpan): StripLabel[] {
  const startText = shortDate(new Date(span.startMs))
  const endText = shortDate(new Date(span.endMs))
  const groups: { fraction: number; texts: string[] }[] = []
  const sorted = [...waypoints].sort((a, b) => a.fraction - b.fraction)
  for (const w of sorted) {
    const text = w.done ? 'done' : shortDate(dateAtFraction(span, w.fraction))
    // A date that duplicates the bound this anchor coincides with is
    // already printed above the line — do not print it again.
    if (w.fraction <= STRIP_BOUND_EPSILON && text === startText) continue
    if (w.fraction >= 1 - STRIP_BOUND_EPSILON && text === endText) continue
    let group = groups[groups.length - 1]
    if (!group || Math.abs(w.fraction - group.fraction) > STRIP_ANCHOR_EPSILON) {
      group = { fraction: w.fraction, texts: [] }
      groups.push(group)
    }
    if (!group.texts.includes(text)) group.texts.push(text)
  }
  return groups
    .filter((g) => g.texts.length > 0)
    .map((g) => ({ fraction: g.fraction, text: g.texts.join(' · ') }))
}
