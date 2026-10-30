/**
 * Build flat timeline rows from initiatives → projects → tasks.
 * View over domain entities only — TimelineRow is not persisted.
 * Hierarchy: task under project (project_id), project under initiative (initiative_id).
 * Unanchored projects appear in a separate section. Status normalized for bar styling.
 */

import type { Initiative, Project, Task } from '../types'
import type { TimelineRow, TimelineBarStatus } from './timelineTypes'

function normalizeStatus(status: string, notes?: string | null): TimelineBarStatus {
  const s = status.toLowerCase()
  if (/overdue/i.test(notes || '')) return 'overdue'
  if (s === 'done' || s === 'completed') return 'done'
  if (s === 'waiting' || s === 'blocked') return 'waiting'
  if (s === 'in progress' || s === 'in_progress' || s === 'active') return 'in_progress'
  return 'not_started'
}

function parseDate(s: string | null | undefined): string | null {
  if (!s) return null
  const part = s.slice(0, 10)
  return /^\d{4}-\d{2}-\d{2}$/.test(part) ? part : null
}

function truncateSummary(s: string | null | undefined, maxLen: number): string | null {
  if (!s || typeof s !== 'string') return null
  const t = s.replace(/\s+/g, ' ').trim()
  if (!t) return null
  return t.length <= maxLen ? t : t.slice(0, maxLen) + '…'
}

/**
 * Timeline tree/grid row height (px). Shared by both sides so rows stay
 * aligned (the grid positions bars by row index, so tree rows cannot grow
 * independently). Sized to fit exactly a label line + ONE subline + row
 * padding: 20 (text-sm) + 2 (mt-0.5) + 16.5 (11px at default leading) + 8
 * (py-1) = 46.5px, rounded up to 48. Any row content taller than this paints
 * into the next row, so sublines must be combined (see timelineRowSubline),
 * never stacked.
 */
export const TIMELINE_ROW_HEIGHT_PX = 48

export interface TimelineRowSubline {
  /** Single display line (summary and waits-on combined), or null when neither exists */
  text: string | null
  /** Full untruncated text for the title tooltip */
  title: string | null
  summary: string | null
  waits: string | null
}

/**
 * Combine a timeline row's summary and waits-on note into ONE subline, so a
 * row never needs more than label + subline and always fits
 * TIMELINE_ROW_HEIGHT_PX. No information is dropped: the full text stays in
 * the tooltip, and both parts keep their colors in the rendered line.
 */
export function timelineRowSubline(
  summary: string | null | undefined,
  blockedBy: string[] | undefined,
): TimelineRowSubline {
  const summaryText = summary && summary.trim() ? summary : null
  const waits =
    blockedBy && blockedBy.length > 0
      ? `⏳ waits on ${blockedBy.slice(0, 2).join(', ')}${blockedBy.length > 2 ? ` +${blockedBy.length - 2}` : ''}`
      : null
  const waitsTitle =
    blockedBy && blockedBy.length > 0 ? `Waits on: ${blockedBy.join(', ')}` : null
  const text = [summaryText, waits].filter(Boolean).join(' · ') || null
  const title = [summaryText, waitsTitle].filter(Boolean).join(' · ') || null
  return { text, title, summary: summaryText, waits }
}

/** Project bar: start_date → end_date, or created_at + 4 weeks if missing */
function projectSpan(p: Project): { start: string | null; end: string | null } {
  const start = parseDate(p.start_date)
  const end = parseDate(p.end_date)
  if (start && end) return { start, end }
  if (end) return { start: end, end } // single day
  const created = parseDate(p.created_at)
  if (created) {
    const d = new Date(created)
    d.setDate(d.getDate() + 28)
    return { start: created, end: d.toISOString().slice(0, 10) }
  }
  return { start: null, end: null }
}

/** Task bar: due_date as single-day or week; or project window */
function taskSpan(t: Task, projectStart: string | null, projectEnd: string | null): { start: string | null; end: string | null } {
  const due = parseDate(t.due_date)
  if (due) {
    const d = new Date(due)
    d.setDate(d.getDate() + 3) // 3-day task by default
    return { start: due, end: d.toISOString().slice(0, 10) }
  }
  if (projectStart && projectEnd) return { start: projectStart, end: projectEnd }
  return { start: null, end: null }
}

interface TaskSubtreeCtx {
  tasks: Task[]
  baseDepth: number
  projectId: string | null
  initiativeId?: string | null
  projSpan: { start: string | null; end: string | null }
  collapsedIds: Set<string>
}

/**
 * Push task rows honoring parent_task_id nesting (unfolded checklists land as
 * subtasks) and dependency_ids (surfaced as blocked-by labels).
 * Tasks without dates stay off the timeline only if nothing above them is
 * dated either — dates remain optional, never forced.
 */
function pushTaskSubtree(rows: TimelineRow[], ctx: TaskSubtreeCtx) {
  const { tasks, baseDepth, projectId, initiativeId, projSpan, collapsedIds } = ctx
  const byId = new Map<string, Task>()
  for (const t of tasks) byId.set(t.id, t)
  const titleOf = (id: string) => byId.get(id)?.title ?? id
  const childrenOf = new Map<string, Task[]>()
  const roots: Task[] = []
  for (const t of tasks) {
    const pid = t.parent_task_id ?? null
    if (pid && byId.has(pid) && pid !== t.id) {
      const list = childrenOf.get(pid) || []
      list.push(t)
      childrenOf.set(pid, list)
    } else {
      roots.push(t)
    }
  }
  const visited = new Set<string>()
  const push = (
    t: Task,
    depth: number,
    inheritedSpan: { start: string | null; end: string | null },
  ) => {
    if (visited.has(t.id)) return // cycle guard — never hang on bad data
    visited.add(t.id)
    const own = taskSpan(t, null, null)
    const span =
      own.start && own.end
        ? own
        : inheritedSpan.start && inheritedSpan.end
          ? inheritedSpan
          : projSpan
    const children = childrenOf.get(t.id) || []
    const isCollapsed = collapsedIds.has(t.id)
    const blockedBy = (t.dependency_ids || [])
      .map((id) => titleOf(id))
      .filter((label, idx, arr) => label && arr.indexOf(label) === idx)
    rows.push({
      id: t.id,
      kind: 'task',
      label: t.title,
      summary: truncateSummary(t.description || t.title, 56),
      status: t.status,
      barStatus: normalizeStatus(t.status, t.notes),
      owner: t.assignee_id,
      depth,
      start: span.start,
      end: span.end,
      taskId: t.id,
      projectId,
      initiativeId,
      parentTaskId: t.parent_task_id ?? null,
      blockedBy: blockedBy.length > 0 ? blockedBy : undefined,
      collapsed: children.length > 0 ? isCollapsed : undefined,
      childCount: children.length > 0 ? children.length : undefined,
    })
    if (isCollapsed) return
    for (const c of children) push(c, depth + 1, span)
  }
  for (const r of roots) push(r, baseDepth, { start: null, end: null })
}

export interface BuildTimelineRowsInput {
  initiatives: Initiative[]
  projects: Project[]
  tasks: Task[]
  collapsedIds: Set<string>
}

export function buildTimelineRows({
  initiatives,
  projects,
  tasks,
  collapsedIds,
}: BuildTimelineRowsInput): TimelineRow[] {
  const rows: TimelineRow[] = []
  const tasksByProject = new Map<string, Task[]>()
  const orphanTasks: Task[] = []
  for (const t of tasks) {
    if (!t.project_id) {
      orphanTasks.push(t)
      continue
    }
    const list = tasksByProject.get(t.project_id) || []
    list.push(t)
    tasksByProject.set(t.project_id, list)
  }

  for (const init of initiatives) {
    const initProjects = projects.filter((p) => p.initiative_id === init.id)
    const initCollapsed = collapsedIds.has(init.id)
    rows.push({
      id: init.id,
      kind: 'initiative',
      label: init.title,
      summary: truncateSummary(init.brief, 56),
      status: init.status,
      barStatus: normalizeStatus(init.status),
      owner: init.owner_id,
      depth: 0,
      start: null,
      end: null,
      initiativeId: init.id,
      collapsed: initCollapsed,
      childCount: initProjects.length,
    })
    if (initCollapsed) continue
    for (const p of initProjects) {
      const projSpan = projectSpan(p)
      const projTasks = tasksByProject.get(p.id) || []
      const projCollapsed = collapsedIds.has(p.id)
      rows.push({
        id: p.id,
        kind: 'project',
        label: p.title,
        summary: truncateSummary(p.brief, 56),
        status: p.status,
        barStatus: normalizeStatus(p.status),
        owner: p.owner_id,
        depth: 1,
        start: projSpan.start,
        end: projSpan.end,
        projectId: p.id,
        initiativeId: init.id,
        collapsed: projCollapsed,
        childCount: projTasks.length,
      })
      if (projCollapsed) continue
      pushTaskSubtree(rows, {
        tasks: projTasks,
        baseDepth: 2,
        projectId: p.id,
        initiativeId: init.id,
        projSpan,
        collapsedIds,
      })
    }
  }

  // Unanchored projects (no initiative)
  const unanchored = projects.filter((p) => !p.initiative_id)
  if (unanchored.length > 0) {
    rows.push({
      id: '_unanchored',
      kind: 'initiative',
      label: 'Unanchored projects',
      status: '',
      barStatus: 'not_started',
      depth: 0,
      start: null,
      end: null,
      collapsed: collapsedIds.has('_unanchored'),
      childCount: unanchored.length,
    })
    if (!collapsedIds.has('_unanchored')) {
      for (const p of unanchored) {
        const projSpan = projectSpan(p)
        const projTasks = tasksByProject.get(p.id) || []
        const projCollapsed = collapsedIds.has(p.id)
        rows.push({
          id: p.id,
          kind: 'project',
          label: p.title,
          summary: truncateSummary(p.brief, 56),
          status: p.status,
          barStatus: normalizeStatus(p.status),
          owner: p.owner_id,
          depth: 1,
          start: projSpan.start,
          end: projSpan.end,
          projectId: p.id,
          collapsed: projCollapsed,
          childCount: projTasks.length,
        })
        if (!projCollapsed) {
          pushTaskSubtree(rows, {
            tasks: projTasks,
            baseDepth: 2,
            projectId: p.id,
            projSpan,
            collapsedIds,
          })
        }
      }
    }
  }

  if (orphanTasks.length > 0) {
    rows.push({
      id: '_orphan_tasks',
      kind: 'initiative',
      label: 'Tasks without project',
      status: '',
      barStatus: 'not_started',
      depth: 0,
      start: null,
      end: null,
      collapsed: collapsedIds.has('_orphan_tasks'),
      childCount: orphanTasks.length,
    })
    if (!collapsedIds.has('_orphan_tasks')) {
      pushTaskSubtree(rows, {
        tasks: orphanTasks,
        baseDepth: 1,
        projectId: null,
        projSpan: { start: null, end: null },
        collapsedIds,
      })
    }
  }

  return rows
}
