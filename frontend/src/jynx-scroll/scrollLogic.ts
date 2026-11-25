/**
 * Jynx's Scroll — pure derivation logic.
 *
 * The shelf is a projection of the user's real Vision Execution
 * hierarchy, fetched through the Vision Map's entity routes — the
 * same fetch the Campaign Board uses. Nothing here invents data:
 * every scroll on the shelf is a recorded item, and every visible
 * distinction between scrolls is computed from recorded fields,
 * with the rule carried on the scroll so the surface (and its
 * tests) can show its working:
 *
 *  - SIZE comes from the item's kind (initiative > project > task;
 *    an idea stands at project size — an origin, not a step) plus
 *    its recorded mass — an initiative's project count, a project's
 *    task count, a task's recorded estimated hours.
 *  - AGE TONE comes from the item's recorded created_at, spread
 *    across the shelf: the oldest item is the deepest parchment,
 *    the newest the freshest.
 *  - The BINDING CORD's colour comes from the item's recorded
 *    status only: a Blocked item wears Jynx's own violet (#a55cce)
 *    — the one scroll that stands out of the plain ones, the way
 *    the founder's reference shelf has one decorated scroll among
 *    plain ones; a Done/Complete item's cord is faded undyed; every
 *    other status wears the plain dark cord. No status, no accent.
 *    (The violet is rationed exactly as the design record rations
 *    it: Jynx's accent, never a tint on the user's work — here it
 *    marks the stuck scroll, and the stand's selection ring.)
 *
 * Grouping (the shelf's arrangement — stated, reversible): the
 * case is arranged in BAYS, one per initiative, in fetch order —
 * the scroll unit of the design record (chalk investigation §4.1:
 * each initiative is its own scroll, its projects and tasks nested
 * under it). A bay holds its initiative scroll at its head, then
 * each of its projects with that project's task scrolls following
 * it (subtasks directly after their parent task). Items with no
 * recorded parent — projects with no initiative, tasks with no
 * project — lie in the open BIN at the case's base, and each IDEA
 * stands in the bin as its own scroll unit (record §4.1/K1: an
 * idea is its own scroll; founding follows the record, so ideas
 * are not nested into initiatives here — an initiative founded
 * from an idea carries that origin on its scroll as
 * `sourceIdeaId`, stated, not drawn as a shelf relation).
 * Nothing is filtered out: Done, Dropped and Complete items keep
 * their scrolls (a shelf holds the whole archive, unlike the
 * Board's active-work overview).
 *
 * Drawings: a drawing is an ordered list of MARKS in the drawing's
 * own coordinate space — the arrival order IS the list order. A
 * mark is one of the two forms Jynx's hand actually has in the
 * record: a STAMP placement from their stencil kit (the kit's
 * closed vocabulary — arc, caret, crescent, fork, frame, leaf,
 * ring, slash, triangle, wave — placed by centre, width, angle,
 * flip, and ink tier, exactly as the approved scroll study's
 * generator places them), or a freehand STROKE (an SVG path in the
 * minimal sumi hand, investigation §10.1/§10.2). Ink tiers are the
 * study's three: DARK 0.95, MID 0.60, LIGHT 0.32. The surface
 * renders marks as gesture in this hand; per the design record's
 * honesty rule (Rev 3 §2.4), a mark's rendering never claims to be
 * a picture of the idea it accompanies — the words in the
 * conversation carry the content; the drawing carries the act.
 */
import type { Idea, Initiative, Project, Task } from '../vision-execution/types'

export type ScrollKind = 'initiative' | 'project' | 'task' | 'idea'

/** Jynx's colour (the Maverick's accent). */
export const JYNX_PURPLE = '#a55cce'

const CORD_BLOCKED = JYNX_PURPLE
const CORD_DONE = '#8a7a5f'
const CORD_PLAIN = '#4a3826'

const FRESH_PARCHMENT = '#efe6cc'
const AGED_PARCHMENT = '#d9c491'

export interface ScrollAppearance {
  /** Roll radius in scene units — kind plus recorded mass. */
  radius: number
  /** 0 = freshest parchment on the shelf, 1 = oldest. */
  ageTone: number
  /** Parchment fill for this age tone (fresh → aged interpolation). */
  parchment: string
  /** Binding cord colour, from recorded status only. */
  cord: string
  /** The rule that produced the cord, for the record. */
  cordRule: string
}

export interface ShelfScroll {
  kind: ScrollKind
  id: string
  title: string
  status: string
  /** For a task scroll: its recorded parent task's id, or null when
   *  the task stands at the top of its list. Always null for other
   *  kinds. The shelf's drill-in walks this edge. */
  parentTaskId: string | null
  /** Recorded mass behind the size: initiative → project count,
   *  project → task count, task → estimated hours (null when the
   *  record carries no estimate); ideas carry no mass here. */
  mass: number | null
  createdAt: string
  /** For an initiative founded from an idea: the idea's id (the
   *  record's source_idea_id origin edge). Null otherwise. */
  sourceIdeaId: string | null
  appearance: ScrollAppearance
}

export interface ShelfBayProject {
  scroll: ShelfScroll
  tasks: ShelfScroll[]
}

export interface ShelfBay {
  /** The bay's initiative scroll, or null for the unanchored bin. */
  initiative: ShelfScroll | null
  projects: ShelfBayProject[]
  /** Tasks with no recorded project — only ever in the bin bay. */
  looseTasks: ShelfScroll[]
  /** Ideas — each its own scroll unit — only ever in the bin bay. */
  ideas: ShelfScroll[]
}

function hexMix(a: string, b: string, t: number): string {
  const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16))
  const pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16))
  const mixed = pa.map((v, i) => Math.round(v + (pb[i] - v) * t))
  return `#${mixed.map((v) => v.toString(16).padStart(2, '0')).join('')}`
}

function cordForStatus(status: string): { cord: string; cordRule: string } {
  const s = (status || '').trim().toLowerCase()
  if (s === 'blocked') {
    return {
      cord: CORD_BLOCKED,
      cordRule:
        'Recorded as Blocked: the binding wears Jynx’s violet — the one scroll that stands out, because the work itself is stuck.',
    }
  }
  if (s === 'done' || s === 'complete' || s === 'completed' || s === 'dropped') {
    return {
      cord: CORD_DONE,
      cordRule: `Recorded as ${status}: the binding is faded undyed cord — settled work, nothing calling out.`,
    }
  }
  return {
    cord: CORD_PLAIN,
    cordRule: `Recorded as ${status || 'without a status'}: the plain dark cord every open scroll wears.`,
  }
}

function baseRadius(kind: ScrollKind): number {
  return kind === 'initiative' ? 25 : kind === 'project' || kind === 'idea' ? 20 : 14
}

function radiusFor(kind: ScrollKind, mass: number | null): number {
  const base = baseRadius(kind)
  if (mass == null) return base
  if (kind === 'initiative') return base + Math.min(6, mass)
  if (kind === 'project') return base + Math.min(5, mass * 0.5)
  return base + Math.min(4, mass / 4)
}

/** Tasks in shelf order: fetch order, each subtask directly after
 *  its parent (a subtask whose parent is absent keeps its place). */
function orderTasks(tasks: Task[]): Task[] {
  const byParent = new Map<string, Task[]>()
  const roots: Task[] = []
  for (const t of tasks) {
    if (t.parent_task_id && tasks.some((x) => x.id === t.parent_task_id)) {
      const arr = byParent.get(t.parent_task_id) ?? []
      arr.push(t)
      byParent.set(t.parent_task_id, arr)
    } else {
      roots.push(t)
    }
  }
  const out: Task[] = []
  const walk = (t: Task) => {
    out.push(t)
    for (const kid of byParent.get(t.id) ?? []) walk(kid)
  }
  for (const r of roots) walk(r)
  return out
}

export function buildScrollShelf(
  initiatives: Initiative[],
  projects: Project[],
  tasks: Task[],
  ideas: Idea[] = [],
): ShelfBay[] {
  // Age spread across everything that will stand on the shelf.
  const stamps = [
    ...initiatives.map((i) => i.created_at),
    ...projects.map((p) => p.created_at),
    ...tasks.map((t) => t.created_at),
    ...ideas.map((i) => i.created_at),
  ]
    .map((s) => new Date(s).getTime())
    .filter((n) => Number.isFinite(n))
  const oldest = stamps.length ? Math.min(...stamps) : 0
  const newest = stamps.length ? Math.max(...stamps) : 0

  const make = (
    kind: ScrollKind,
    id: string,
    title: string,
    status: string,
    mass: number | null,
    createdAt: string,
    sourceIdeaId: string | null = null,
    parentTaskId: string | null = null,
  ): ShelfScroll => {
    const t = new Date(createdAt).getTime()
    const ageTone =
      stamps.length && newest > oldest && Number.isFinite(t)
        ? Math.min(1, Math.max(0, (newest - t) / (newest - oldest)))
        : 0
    const { cord, cordRule } = cordForStatus(status)
    return {
      kind,
      id,
      title,
      status,
      parentTaskId,
      mass,
      createdAt,
      sourceIdeaId,
      appearance: {
        radius: radiusFor(kind, mass),
        ageTone,
        parchment: hexMix(FRESH_PARCHMENT, AGED_PARCHMENT, ageTone),
        cord,
        cordRule,
      },
    }
  }

  const tasksByProject = new Map<string, Task[]>()
  const looseTasks: Task[] = []
  for (const t of tasks) {
    if (t.project_id && projects.some((p) => p.id === t.project_id)) {
      const arr = tasksByProject.get(t.project_id) ?? []
      arr.push(t)
      tasksByProject.set(t.project_id, arr)
    } else {
      looseTasks.push(t)
    }
  }

  const projectScroll = (p: Project): ShelfBayProject => {
    const projectTasks = orderTasks(tasksByProject.get(p.id) ?? [])
    return {
      scroll: make('project', p.id, p.title, p.status, projectTasks.length, p.created_at),
      tasks: projectTasks.map((t) =>
        make('task', t.id, t.title, t.status, t.estimated_hours, t.created_at, null, t.parent_task_id),
      ),
    }
  }

  const bays: ShelfBay[] = initiatives.map((ini) => {
    const iniProjects = projects.filter((p) => p.initiative_id === ini.id)
    return {
      initiative: make(
        'initiative',
        ini.id,
        ini.title,
        ini.status,
        iniProjects.length,
        ini.created_at,
        ini.source_idea_id ?? null,
      ),
      projects: iniProjects.map(projectScroll),
      looseTasks: [],
      ideas: [],
    }
  })

  const unanchored = projects.filter(
    (p) => !p.initiative_id || !initiatives.some((i) => i.id === p.initiative_id),
  )
  const ideaScrolls = ideas.map((idea) =>
    make('idea', idea.id, idea.title, idea.status, null, idea.created_at),
  )
  if (unanchored.length || looseTasks.length || ideaScrolls.length) {
    bays.push({
      initiative: null,
      projects: unanchored.map(projectScroll),
      looseTasks: orderTasks(looseTasks).map((t) =>
        make('task', t.id, t.title, t.status, t.estimated_hours, t.created_at, null, t.parent_task_id),
      ),
      ideas: ideaScrolls,
    })
  }
  return bays
}

/** Every scroll on the shelf in reading order (bay by bay: the
 *  initiative, then each project followed by its tasks; the bin's
 *  projects, loose tasks, and ideas last). The case lays its cells
 *  and bin rows out in this order. */
export function flattenShelf(bays: ShelfBay[]): ShelfScroll[] {
  const out: ShelfScroll[] = []
  for (const bay of bays) {
    if (bay.initiative) out.push(bay.initiative)
    for (const p of bay.projects) {
      out.push(p.scroll)
      out.push(...p.tasks)
    }
    out.push(...bay.looseTasks)
    out.push(...bay.ideas)
  }
  return out
}

/* ------------------------------------------------------------------ */
/* Parents + loose — the shelf's default face (founder, 2026-11-24)    */
/* ------------------------------------------------------------------ */

/**
 * The display rule, stated once for every surface: a collection
 * shows ONLY its top-level parents and its loose items by default;
 * children appear when their parent is opened. On the shelf that
 * means: one scroll per initiative in the lattice, and in the bin
 * one scroll per unanchored project, per top-level loose task, and
 * per idea. A bay's projects, a project's tasks, and a task's
 * subtasks are NOT on the shelf face — they are reached by opening
 * their parent (scrollChildren), so nothing leaves reachability.
 */
export function shelfTopLevel(bays: ShelfBay[]): { lattice: ShelfScroll[]; bin: ShelfScroll[] } {
  const lattice: ShelfScroll[] = []
  const bin: ShelfScroll[] = []
  for (const bay of bays) {
    if (bay.initiative) {
      lattice.push(bay.initiative)
      continue
    }
    for (const p of bay.projects) bin.push(p.scroll)
    bin.push(...topLevelTasks(bay.looseTasks))
    bin.push(...bay.ideas)
  }
  return { lattice, bin }
}

/** The top of a task list: tasks with no recorded parent in the
 *  same list (a parent outside the list leaves the task standing
 *  at the top of its own list, as orderTasks already treats it). */
function topLevelTasks(tasks: ShelfScroll[]): ShelfScroll[] {
  const ids = new Set(tasks.map((t) => t.id))
  return tasks.filter((t) => !t.parentTaskId || !ids.has(t.parentTaskId))
}

/** The task list a task scroll lives in (its project's list, or
 *  the bin's loose list), or null when it is not a task. */
function taskListOf(bays: ShelfBay[], scroll: ShelfScroll): ShelfScroll[] | null {
  if (scroll.kind !== 'task') return null
  for (const bay of bays) {
    for (const p of bay.projects) {
      if (p.tasks.some((t) => t.id === scroll.id)) return p.tasks
    }
    if (bay.looseTasks.some((t) => t.id === scroll.id)) return bay.looseTasks
  }
  return null
}

/**
 * A scroll's children — what opening it reveals, in shelf order:
 * an initiative opens to its projects; a project to its top-level
 * tasks; a task to its subtasks within the same list; an idea has
 * no children. Every scroll on the shelf is either top-level
 * (shelfTopLevel) or the child of exactly one parent reached this
 * way, so the whole archive stays reachable through its parents.
 */
export function scrollChildren(bays: ShelfBay[], scroll: ShelfScroll): ShelfScroll[] {
  switch (scroll.kind) {
    case 'initiative': {
      const bay = bays.find((b) => b.initiative?.id === scroll.id)
      return bay ? bay.projects.map((p) => p.scroll) : []
    }
    case 'project': {
      for (const bay of bays) {
        const found = bay.projects.find((p) => p.scroll.id === scroll.id)
        if (found) return topLevelTasks(found.tasks)
      }
      return []
    }
    case 'task': {
      const list = taskListOf(bays, scroll)
      return list ? list.filter((t) => t.parentTaskId === scroll.id) : []
    }
    case 'idea':
      return []
  }
}

/* ------------------------------------------------------------------ */
/* Drawings — Jynx's marks, in arrival order                           */
/* ------------------------------------------------------------------ */

/** The stencil kit's closed vocabulary — Jynx's stamp forms, as
 *  extracted in ~/workspace/rendering-test-assets/jynx-stencil-kit
 *  (the same PNGs ship as this module's assets, byte-identical). */
export type StampName =
  | 'arc'
  | 'caret'
  | 'crescent'
  | 'fork'
  | 'frame'
  | 'leaf'
  | 'ring'
  | 'slash'
  | 'triangle'
  | 'wave'

/** The study's three ink tiers (build_scroll2.py: DARK/MID/LIGHT). */
export const TIER_DARK = 0.95
export const TIER_MID = 0.6
export const TIER_LIGHT = 0.32

/**
 * One mark of a drawing, in the drawing's own coordinate space.
 * A stamp placement mirrors the approved scroll generator's
 * place() call exactly (centre, width, angle, flip, tier); a
 * stroke is a freehand sumi path (width in drawing units, tier
 * for its opacity). Marks arrive in list order.
 */
export type ScrollMark =
  | {
      type: 'stamp'
      stamp: StampName
      cx: number
      cy: number
      w: number
      angle?: number
      flip?: boolean
      tier: number
    }
  | { type: 'stroke'; d: string; width: number; tier: number }

export interface ScrollDrawing {
  id: string
  title: string | null
  /** The coordinate space the marks are placed in. The payload
   *  owns its space; the surface fits it inside the sheet. */
  space: { w: number; h: number }
  /** Marks in arrival order — the order the drawing is made in. */
  marks: ScrollMark[]
}

/** Time one mark takes to arrive, and the pause between marks. */
export const MARK_DRAW_MS = 620
export const MARK_GAP_MS = 90

export function drawingDurationMs(drawing: ScrollDrawing): number {
  if (!drawing.marks.length) return 0
  return drawing.marks.length * (MARK_DRAW_MS + MARK_GAP_MS) - MARK_GAP_MS
}

/**
 * How far mark `index` has arrived at `elapsedMs` into the
 * drawing's reveal: 0 = not started, 1 = fully arrived, between =
 * mid-arrival (a stroke mid-draw; a stamp mid-fade, in the film's
 * placing rhythm). Marks arrive strictly in order — a later mark
 * never starts before the earlier one completes.
 */
export function markProgressAt(elapsedMs: number, drawing: ScrollDrawing, index: number): number {
  if (index < 0 || index >= drawing.marks.length) return 0
  const start = index * (MARK_DRAW_MS + MARK_GAP_MS)
  const local = (elapsedMs - start) / MARK_DRAW_MS
  return Math.min(1, Math.max(0, local))
}
