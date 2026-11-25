/**
 * Projects Timeline: hierarchical tree (left) + time grid (right).
 * Uses shared initiatives/projects/tasks; supports week/month zoom and detail selection.
 */

import { useState, useMemo, useCallback, useEffect, useRef } from 'react'
import type { Initiative, Project, Task } from '../types'
import { buildTimelineRows, TIMELINE_ROW_HEIGHT_PX } from './timelineUtils'
import { defaultNestedCollapsedIds } from '../nestedVisibility'
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

const ROW_HEIGHT = TIMELINE_ROW_HEIGHT_PX

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
  // Parents + loose by default: every initiative, project, and parent task
  // starts collapsed so only parents and loose items are listed; the loose
  // section groups stay open so loose projects/tasks themselves are listed.
  // Ids are defaulted once each (tracked in nestedSeenRef) so data arriving
  // later also starts nested, while a parent the user already un-nested is
  // never re-collapsed by a refetch.
  const nestedSeenRef = useRef<Set<string>>(new Set())
  useEffect(() => {
    const defaults = defaultNestedCollapsedIds(initiatives, projects, tasks)
    const fresh = [...defaults].filter((id) => !nestedSeenRef.current.has(id))
    if (fresh.length === 0) return
    fresh.forEach((id) => nestedSeenRef.current.add(id))
    setCollapsedIds((prev) => {
      const next = new Set(prev)
      fresh.forEach((id) => next.add(id))
      return next
    })
  }, [initiatives, projects, tasks])

  const expandAll = useCallback(() => setCollapsedIds(new Set()), [])
  const collapseAll = useCallback(() => {
    const defaults = defaultNestedCollapsedIds(initiatives, projects, tasks)
    defaults.forEach((id) => nestedSeenRef.current.add(id))
    setCollapsedIds(defaults)
  }, [initiatives, projects, tasks])

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
      <div className="flex flex-wrap items-center gap-2 sm:gap-4 mb-2 shrink-0">
        <div className="flex rounded-lg border border-slate-600 bg-slate-800/50 p-0.5 shrink-0">
          <button
            type="button"
            onClick={() => setZoom('week')}
            className={`px-3 py-1.5 text-sm rounded-md whitespace-nowrap ${zoom === 'week' ? 'bg-amber-600 text-white' : 'text-slate-400 hover:text-slate-200'}`}
          >
            Week
          </button>
          <button
            type="button"
            onClick={() => setZoom('month')}
            className={`px-3 py-1.5 text-sm rounded-md whitespace-nowrap ${zoom === 'month' ? 'bg-amber-600 text-white' : 'text-slate-400 hover:text-slate-200'}`}
          >
            Month
          </button>
        </div>
        <div className="text-sm text-slate-400 min-w-0">
          {rangeStart.toLocaleDateString(undefined, { month: 'short', year: 'numeric', day: 'numeric' })}
          {' → '}
          {rangeEnd.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
        </div>
        <button
          type="button"
          onClick={() => setAnchorDate(new Date())}
          className="text-xs text-slate-500 hover:text-slate-300 whitespace-nowrap shrink-0"
        >
          Today
        </button>
        <button
          type="button"
          onClick={expandAll}
          className="text-xs text-slate-500 hover:text-slate-300 whitespace-nowrap shrink-0"
        >
          Expand all
        </button>
        <button
          type="button"
          onClick={collapseAll}
          className="text-xs text-slate-500 hover:text-slate-300 whitespace-nowrap shrink-0"
        >
          Collapse all
        </button>
      </div>
      <div className="flex flex-1 min-h-0 overflow-x-auto overflow-y-hidden border border-slate-600 rounded-lg bg-slate-800/30">
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
