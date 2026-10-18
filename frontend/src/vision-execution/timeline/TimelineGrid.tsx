/**
 * Right-side time grid: week or month columns, with row bars positioned by date range.
 */

import { useMemo } from 'react'
import type { TimelineRow, TimelineZoom } from './timelineTypes'
import { TimelineBar } from './TimelineBar'

export interface TimelineGridProps {
  rows: TimelineRow[]
  zoom: TimelineZoom
  rangeStart: Date
  rangeEnd: Date
  rowHeightPx?: number
  onRowClick?: (row: TimelineRow) => void
  selectedProjectId?: string | null
  selectedTaskId?: string | null
}

export function getRange(zoom: TimelineZoom, anchor: Date): { start: Date; end: Date } {
  const start = new Date(anchor)
  const end = new Date(anchor)
  if (zoom === 'week') {
    const day = start.getDay()
    const diff = start.getDate() - day + (day === 0 ? -6 : 1)
    start.setDate(diff)
    start.setHours(0, 0, 0, 0)
    end.setTime(start.getTime())
    end.setDate(end.getDate() + 6)
    end.setHours(23, 59, 59, 999)
  } else {
    start.setDate(1)
    start.setHours(0, 0, 0, 0)
    end.setTime(start.getTime())
    end.setDate(start.getDate() + 7 * 5 - 1) // 5 weeks
    end.setHours(23, 59, 59, 999)
  }
  return { start, end }
}

function dateToPct(date: Date, rangeStart: Date, rangeEnd: Date): number {
  const total = rangeEnd.getTime() - rangeStart.getTime()
  const t = date.getTime() - rangeStart.getTime()
  return Math.max(0, Math.min(100, (t / total) * 100))
}

export function TimelineGrid({
  rows,
  zoom,
  rangeStart,
  rangeEnd,
  rowHeightPx = 32,
  onRowClick,
  selectedProjectId,
  selectedTaskId,
}: TimelineGridProps) {
  const columnLabels = useMemo(() => {
    const labels: string[] = []
    const d = new Date(rangeStart)
    if (zoom === 'week') {
      for (let i = 0; i < 7; i++) {
        const day = new Date(d)
        day.setDate(d.getDate() + i)
        labels.push(day.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric' }))
      }
    } else {
      for (let w = 0; w < 5; w++) {
        const weekStart = new Date(d)
        weekStart.setDate(d.getDate() + w * 7)
        labels.push(weekStart.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }))
      }
    }
    return labels
  }, [zoom, rangeStart])

  return (
    <div className="flex-1 min-w-0 flex flex-col border-l border-slate-600">
      {/* Header: time labels */}
      <div className="flex border-b border-slate-600 bg-slate-800/80 shrink-0">
        {columnLabels.map((label, i) => (
          <div
            key={i}
            className="flex-1 min-w-[48px] px-1 py-1.5 text-xs text-slate-400 text-center border-r border-slate-600 last:border-r-0"
          >
            {label}
          </div>
        ))}
      </div>
      {/* Rows */}
      <div className="flex-1 overflow-auto">
        {rows.map((row) => {
          const hasBar = row.start != null && row.end != null
          const startDate = row.start ? new Date(row.start) : null
          const endDate = row.end ? new Date(row.end) : null
          const startPct = startDate && endDate
            ? dateToPct(startDate, rangeStart, rangeEnd)
            : 0
          const endPct = startDate && endDate
            ? dateToPct(endDate, rangeStart, rangeEnd)
            : 0
          const selected =
            (row.projectId != null && row.projectId === selectedProjectId) ||
            (row.taskId != null && row.taskId === selectedTaskId)
          const rowBg = row.depth === 0 ? 'bg-slate-800/40' : row.depth === 1 ? 'bg-slate-800/20' : ''
          return (
            <div
              key={row.id}
              className={`border-b border-slate-700/50 flex items-stretch relative ${rowBg}`}
              style={{ height: rowHeightPx }}
            >
              <div className="absolute inset-0 flex">
                {columnLabels.map((_, i) => (
                  <div
                    key={i}
                    className="flex-1 min-w-[48px] border-r border-slate-700/50 last:border-r-0"
                  />
                ))}
              </div>
              {(row.kind === 'project' || row.kind === 'task') && (
                <div className="absolute inset-0 px-0.5">
                  {hasBar ? (
                    <TimelineBar
                      startPct={startPct}
                      endPct={endPct}
                      status={row.barStatus}
                      label={row.kind === 'task' ? row.label : undefined}
                      blockedBy={row.blockedBy}
                      onClick={onRowClick ? () => onRowClick(row) : undefined}
                      selected={selected}
                    />
                  ) : (
                    <div
                      className="absolute top-1 bottom-1 left-1 right-1 rounded border border-dashed border-slate-500 text-slate-500 text-xs flex items-center px-2"
                      onClick={onRowClick ? () => onRowClick(row) : undefined}
                      role={onRowClick ? 'button' : undefined}
                    >
                      Unscheduled
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

