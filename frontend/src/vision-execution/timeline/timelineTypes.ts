/**
 * Types for Projects Timeline view: hierarchical rows + bar placement.
 */

export type TimelineRowKind = 'initiative' | 'project' | 'task'

/** Normalized status for bar styling */
export type TimelineBarStatus = 'in_progress' | 'waiting' | 'done' | 'not_started' | 'overdue'

export interface TimelineRow {
  id: string
  kind: TimelineRowKind
  label: string
  /** Short purpose/summary (brief or description), truncated */
  summary?: string | null
  status: string
  barStatus: TimelineBarStatus
  owner?: string | null
  depth: number
  /** ISO date (YYYY-MM-DD) or null if unscheduled */
  start: string | null
  /** ISO date (YYYY-MM-DD) or null if unscheduled */
  end: string | null
  /** For selection: open project detail */
  projectId?: string | null
  /** For selection: open task detail */
  taskId?: string | null
  /** For selection: open initiative */
  initiativeId?: string | null
  collapsed?: boolean
  childCount?: number
  /** Subtask nesting: id of the parent task, if any (unfolded checklists nest here) */
  parentTaskId?: string | null
  /** Titles of tasks this row waits on, resolved from dependency_ids */
  blockedBy?: string[]
}

export type TimelineZoom = 'week' | 'month'
