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
      for (const t of projTasks) {
        const taskSpanResult = taskSpan(t, projSpan.start, projSpan.end)
        rows.push({
          id: t.id,
          kind: 'task',
          label: t.title,
          summary: truncateSummary(t.description || t.title, 56),
          status: t.status,
          barStatus: normalizeStatus(t.status, t.notes),
          owner: t.assignee_id,
          depth: 2,
          start: taskSpanResult.start,
          end: taskSpanResult.end,
          taskId: t.id,
          projectId: p.id,
          initiativeId: init.id,
        })
      }
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
          for (const t of projTasks) {
            const taskSpanResult = taskSpan(t, projSpan.start, projSpan.end)
            rows.push({
              id: t.id,
              kind: 'task',
              label: t.title,
              summary: truncateSummary(t.description || t.title, 56),
              status: t.status,
              barStatus: normalizeStatus(t.status, t.notes),
              owner: t.assignee_id,
              depth: 2,
              start: taskSpanResult.start,
              end: taskSpanResult.end,
              taskId: t.id,
              projectId: p.id,
            })
          }
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
      for (const t of orphanTasks) {
        const taskSpanResult = taskSpan(t, null, null)
        rows.push({
          id: t.id,
          kind: 'task',
          label: t.title,
          summary: truncateSummary(t.description || t.title, 56),
          status: t.status,
          barStatus: normalizeStatus(t.status, t.notes),
          owner: t.assignee_id,
          depth: 1,
          start: taskSpanResult.start,
          end: taskSpanResult.end,
          taskId: t.id,
          projectId: null,
        })
      }
    }
  }

  return rows
}
