/**
 * Single bar in the timeline grid. Position and width from date range; color from status.
 */

import type { TimelineBarStatus } from './timelineTypes'

const BAR_STATUS_CLASS: Record<TimelineBarStatus, string> = {
  in_progress: 'bg-amber-500/80 border-amber-400',
  waiting: 'bg-slate-500/80 border-slate-400',
  done: 'bg-emerald-600/80 border-emerald-400',
  not_started: 'bg-slate-600/60 border-slate-500',
  overdue: 'bg-red-600/80 border-red-400',
}

export interface TimelineBarProps {
  startPct: number
  endPct: number
  status: TimelineBarStatus
  label?: string
  blockedBy?: string[]
  onClick?: () => void
  selected?: boolean
}

export function TimelineBar({ startPct, endPct, status, label, blockedBy, onClick, selected }: TimelineBarProps) {
  const width = Math.max(2, endPct - startPct)
  const cls = BAR_STATUS_CLASS[status] ?? BAR_STATUS_CLASS.not_started
  const title =
    blockedBy && blockedBy.length > 0
      ? `${label ?? ''} — waits on: ${blockedBy.join(', ')}`
      : label
  return (
    <div
      className={`absolute top-1 bottom-1 rounded border ${cls} ${onClick ? 'cursor-pointer hover:opacity-90' : ''} ${selected ? 'ring-2 ring-white ring-offset-1 ring-offset-slate-800' : ''}`}
      style={{ left: `${startPct}%`, width: `${width}%` }}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      title={title}
    >
      {label && width > 8 && (
        <span className="absolute inset-0 flex items-center px-1.5 text-xs text-slate-100 truncate">
          {label}
        </span>
      )}
    </div>
  )
}
