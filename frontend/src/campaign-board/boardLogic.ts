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
 * (incl. the 2026-11-23 overview/focus addendum). Two prototype rules
 * have no source data in the VE store and are deliberately NOT derived:
 *  - Rivers (a recorded window in which work cannot proceed at all):
 *    VE carries no closed-window record.
 *  - Holds (recurring maintenance positions): VE tasks carry no
 *    recurrence field.
 * Both gaps are recorded in the implementation report.
 */
import type { Project, Task } from '../vision-execution/types'

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
      }
    })
    .sort((x, y) => {
      const sx = STATUS_ORDER[x.project.status] ?? 5
      const sy = STATUS_ORDER[y.project.status] ?? 5
      if (sx !== sy) return sx - sy
      return x.project.title.localeCompare(y.project.title)
    })
}

/** Pixels per day so the longest real route fits the map, capped at the
 *  prototype's 26px/day. Provisional spans never stretch the scale. */
export function computePxPerDay(overview: OverviewProject[], availablePx: number): number {
  const realDays = overview.filter((o) => o.span.source !== 'provisional').map((o) => o.span.days)
  const maxDays = realDays.length ? Math.max(...realDays) : 0
  if (!maxDays) return MAX_PX_PER_DAY
  return Math.min(MAX_PX_PER_DAY, Math.max(4, availablePx / maxDays))
}
