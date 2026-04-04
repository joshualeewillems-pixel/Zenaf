/**
 * Projects Timeline: hierarchical tree (left) + time grid (right).
 * Uses shared initiatives/projects/tasks; supports week/month zoom and detail selection.
 */

import { useState, useMemo, useCallback, useEffect, useRef } from 'react'
import type { Initiative, Project, Task } from '../types'
import { buildTimelineRows } from './timelineUtils'
import type { TimelineZoom, TimelineRow } from './timelineTypes'
import { TimelineTree } from './TimelineTree'
import { TimelineGrid, getRange } from './TimelineGrid'

export interface ProjectsTimelineViewProps {
  initiatives: Initiative[]
  projects: Project[]
  tasks: Task[]
  selectedProjectId: string | null
  selectedTaskId: string | null
  onSelectProject: (id: string | null) => void
  onSelectTask: (id: string | null) => void
  onSelectInitiative?: (id: string | null) => void
}

const ROW_HEIGHT = 44

export function ProjectsTimelineView({
  initiatives,
  projects,
  tasks,
  selectedProjectId,
  selectedTaskId,
  onSelectProject,
  onSelectTask,
  onSelectInitiative,
}: ProjectsTimelineViewProps) {
  const [collapsedIds, setCollapsedIds] = useState<Set<string>>(new Set())
  const [zoom, setZoom] = useState<TimelineZoom>('month')
  const [anchorDate, setAnchorDate] = useState(() => new Date())
  const hasInitializedCollapsed = useRef(false)
  useEffect(() => {
    if (hasInitializedCollapsed.current) return
    if (initiatives.length === 0 && projects.length === 0) return
    hasInitializedCollapsed.current = true
    setCollapsedIds((prev) => {
      const next = new Set(prev)
      initiatives.forEach((i) => next.add(i.id))
      projects.forEach((p) => next.add(p.id))
      next.add('_unanchored')
      next.add('_orphan_tasks')
      return next
    })
  }, [initiatives, projects])

  const toggleCollapsed = useCallback((id: string) => {
    setCollapsedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const rows = useMemo(
    () =>
      buildTimelineRows({
        initiatives,
        projects,
        tasks,
        collapsedIds,
      }),
    [initiatives, projects, tasks, collapsedIds]
  )

  const { start: rangeStart, end: rangeEnd } = useMemo(
    () => getRange(zoom, anchorDate),
    [zoom, anchorDate]
  )

  const handleRowClick = useCallback(
    (row: TimelineRow) => {
      if (row.taskId) {
        onSelectTask(row.taskId)
        onSelectProject(row.projectId ?? null)
      } else if (row.projectId) {
        onSelectProject(row.projectId)
        onSelectTask(null)
      } else if (row.initiativeId && onSelectInitiative) {
        onSelectInitiative(row.initiativeId)
      }
    },
    [onSelectProject, onSelectTask, onSelectInitiative]
  )

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="flex items-center gap-4 mb-2 shrink-0">
        <div className="flex rounded-lg border border-slate-600 bg-slate-800/50 p-0.5">
          <button
            type="button"
            onClick={() => setZoom('week')}
            className={`px-3 py-1.5 text-sm rounded-md ${zoom === 'week' ? 'bg-amber-600 text-white' : 'text-slate-400 hover:text-slate-200'}`}
          >
            Week
          </button>
          <button
            type="button"
            onClick={() => setZoom('month')}
            className={`px-3 py-1.5 text-sm rounded-md ${zoom === 'month' ? 'bg-amber-600 text-white' : 'text-slate-400 hover:text-slate-200'}`}
          >
            Month
          </button>
        </div>
        <div className="text-sm text-slate-400">
          {rangeStart.toLocaleDateString(undefined, { month: 'short', year: 'numeric', day: 'numeric' })}
          {' → '}
          {rangeEnd.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
        </div>
        <button
          type="button"
          onClick={() => setAnchorDate(new Date())}
          className="text-xs text-slate-500 hover:text-slate-300"
        >
          Today
        </button>
      </div>
      <div className="flex flex-1 min-h-0 overflow-hidden border border-slate-600 rounded-lg bg-slate-800/30">
        <TimelineTree
          rows={rows}
          rowHeightPx={ROW_HEIGHT}
          onRowClick={handleRowClick}
          onToggle={toggleCollapsed}
          selectedProjectId={selectedProjectId}
          selectedTaskId={selectedTaskId}
        />
        <TimelineGrid
          rows={rows}
          zoom={zoom}
          rangeStart={rangeStart}
          rangeEnd={rangeEnd}
          rowHeightPx={ROW_HEIGHT}
          onRowClick={handleRowClick}
          selectedProjectId={selectedProjectId}
          selectedTaskId={selectedTaskId}
        />
      </div>
    </div>
  )
}
