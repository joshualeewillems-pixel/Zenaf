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
 * checkpoint) are declared by the user — from a signal, from a chosen
 * window, or placed directly on the line. Declarations are
 * PROVISIONAL, session-local state: the declaration-binding standard
 * is deferred, so they are stored nowhere and can be withdrawn.
 * See the Declarations section below.
 */
import type { CapacityProfile, Person, Project, Task } from '../vision-execution/types'

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

export interface OverviewProject {
  project: Project
  span: BoardSpan
  obstacles: BoardObstacle[]
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
  return projects
    .filter((p) => p.status !== 'Complete')
    .map((project) => {
      const projectTasks = tasks.filter((t) => t.project_id === project.id)
      const span = projectSpan(project, projectTasks, nowMs)
      return {
        project,
        span,
        obstacles: deriveObstacles(project, projectTasks, tasks, span, nowMs),
        openTaskCount: projectTasks.filter(isOpenTask).length,
        doneTaskCount: projectTasks.filter(isDoneTask).length,
        routeDays: span.source === 'provisional' ? NOMINAL_DAYS : span.days,
        spanned: span.source !== 'provisional',
      }
    })
    .sort((x, y) => {
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
  const unanchored: OverviewGroup = { initiative: null, projects: [] }
  for (const o of overview) {
    const initiative = o.project.initiative_id ? byId.get(o.project.initiative_id) : undefined
    if (!initiative) {
      unanchored.projects.push(o)
      continue
    }
    let group = groupByInitiativeId.get(initiative.id)
    if (!group) {
      group = { initiative: { id: initiative.id, title: initiative.title }, projects: [] }
      groupByInitiativeId.set(initiative.id, group)
      groups.push(group)
    }
    group.projects.push(o)
  }
  if (unanchored.projects.length > 0) groups.push(unanchored)
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
/* Capacity — the time-constraint picture (the Radar's computation)    */
/* ------------------------------------------------------------------ */

export interface PersonCapacity {
  personId: string
  name: string
  /** Recorded weekly capacity, or null when no profile is recorded. */
  weeklyCapacityHours: number | null
  /** Committed hours: estimated_weekly_hours summed over the person's
   *  Ready/Active projects (owned or supported) — derived.py's rule,
   *  the same computation the Radar's overcapacity bucket reads. */
  committedHours: number
  /** committed − capacity, or null when no capacity is recorded. */
  delta: number | null
  /** The Radar's overcapacity condition: delta > 0. */
  over: boolean
  rule: string
}

function committedHoursFor(personId: string, projects: Project[]): number {
  let active = 0
  for (const p of projects) {
    const status = (p.status || '').trim()
    if (status !== 'Ready' && status !== 'Active') continue
    if (p.owner_id === personId || (p.supporting_owner_ids ?? []).includes(personId)) {
      active += p.estimated_weekly_hours ?? 0
    }
  }
  return Math.round(active * 10) / 10
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
    const committed = committedHoursFor(pid, allProjects)
    const cap = profileByPerson.get(pid)?.weekly_capacity_hours
    const weeklyCapacityHours = cap != null ? Number(cap) : null
    const delta = weeklyCapacityHours != null ? Math.round((committed - weeklyCapacityHours) * 10) / 10 : null
    const over = delta != null && delta > 0
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
/* Declarations — Rivers and Holds (PROVISIONAL, session-local)        */
/* ------------------------------------------------------------------ */

/**
 * Declarations are the user's own fixings of the terrain (founder
 * doctrine 2026-11-17: terrain is derived, conversed, and DECLARED).
 * They are provisional interface state: held in the board session
 * only, stored in no record, and withdrawable at any time. The
 * declaration-binding standard that would persist them is deferred.
 */

export interface RiverDeclaration {
  id: string
  projectId: string
  /** Where the declaration came from: a signal the user declared a
   *  River, or a window the user chose directly. */
  source:
    | { type: 'signal'; signalId: string; signalTitle: string }
    | { type: 'window' }
  startMs: number
  endMs: number
}

export interface HoldDeclaration {
  id: string
  projectId: string
  fraction: number
}

/** Default length of a freshly declared river window. */
export const RIVER_DEFAULT_DAYS = 3

function startOfDayMs(ms: number): number {
  const d = new Date(ms)
  d.setHours(0, 0, 0, 0)
  return d.getTime()
}

/** Declare a River from a signal: the window opens on the signal's
 *  recorded date and runs RIVER_DEFAULT_DAYS — the user can re-window
 *  it afterwards from the river's own popup. */
export function createRiverFromSignal(
  id: string,
  projectId: string,
  signal: BoardSignal,
  span: BoardSpan,
): RiverDeclaration {
  const created = parseDateMs(signal.created_at)
  const startMs = created != null ? startOfDayMs(created) : startOfDayMs(dateAtFraction(span, 0.5).getTime())
  return {
    id,
    projectId,
    source: { type: 'signal', signalId: signal.id, signalTitle: signal.title },
    startMs,
    endMs: startMs + RIVER_DEFAULT_DAYS * DAY_MS,
  }
}

/** Declare a River by choosing a window directly: opens mid-span at
 *  the default length, ready to be re-windowed from its popup. */
export function createRiverWindow(id: string, projectId: string, span: BoardSpan): RiverDeclaration {
  const startMs = startOfDayMs(dateAtFraction(span, 0.45).getTime())
  return {
    id,
    projectId,
    source: { type: 'window' },
    startMs,
    endMs: startMs + RIVER_DEFAULT_DAYS * DAY_MS,
  }
}

export function setRiverWindow(
  rivers: RiverDeclaration[],
  id: string,
  startMs: number,
  endMs: number,
): RiverDeclaration[] {
  if (!(endMs > startMs)) return rivers
  return rivers.map((r) => (r.id === id ? { ...r, startMs, endMs } : r))
}

export function withdrawRiver(rivers: RiverDeclaration[], id: string): RiverDeclaration[] {
  return rivers.filter((r) => r.id !== id)
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

export function createHold(id: string, projectId: string, fraction = 0.5): HoldDeclaration {
  return { id, projectId, fraction: Math.min(0.98, Math.max(0.02, fraction)) }
}

export function moveHold(holds: HoldDeclaration[], id: string, fraction: number): HoldDeclaration[] {
  const clamped = Math.min(0.98, Math.max(0.02, fraction))
  return holds.map((h) => (h.id === id ? { ...h, fraction: clamped } : h))
}

export function removeHold(holds: HoldDeclaration[], id: string): HoldDeclaration[] {
  return holds.filter((h) => h.id !== id)
}
