/**
 * Left-side hierarchical tree: initiative → project → task.
 * Tasks nest under their project; projects nest under their initiative (where defined).
 * Shows name, type, status; expand/collapse; click to select.
 */

import type { TimelineRow } from './timelineTypes'
import { timelineRowSubline } from './timelineUtils'

const KIND_LABEL: Record<string, string> = {
  initiative: 'Initiative',
  project: 'Project',
  task: 'Task',
}

const DEPTH_INDENT_PX = 20
const DEPTH_BORDER = ['border-l-slate-600', 'border-l-amber-600/40', 'border-l-slate-500/50']

export interface TimelineTreeProps {
  rows: TimelineRow[]
  rowHeightPx?: number
  onRowClick?: (row: TimelineRow) => void
  onToggle?: (id: string) => void
  selectedProjectId?: string | null
  selectedTaskId?: string | null
}

export function TimelineTree({
  rows,
  rowHeightPx = 32,
  onRowClick,
  onToggle,
  selectedProjectId,
  selectedTaskId,
}: TimelineTreeProps) {
  return (
    <div className="w-72 shrink-0 flex flex-col border-r border-slate-600 bg-slate-800/30">
      <div className="flex border-b border-slate-600 bg-slate-800/80 shrink-0 px-2 py-1.5 text-xs font-medium text-slate-400 uppercase">
        <span className="flex-1 truncate">Name</span>
        <span className="w-16 shrink-0 text-center">Type</span>
        <span className="w-20 shrink-0 truncate">Status</span>
      </div>
      <div className="flex-1 overflow-auto">
        {rows.map((row) => {
          const selected =
            (row.projectId != null && row.projectId === selectedProjectId) ||
            (row.taskId != null && row.taskId === selectedTaskId) ||
            (row.kind === 'initiative' && row.initiativeId && false) // initiative detail not wired yet
          const hasChildren = (row.childCount ?? 0) > 0
          const isCollapsed = row.collapsed === true
          const subline = timelineRowSubline(row.summary, row.blockedBy)
          return (
            <div
              key={row.id}
              className={`flex items-start gap-2 px-2 py-1 border-b border-slate-700/50 text-sm border-l-2 ${selected ? 'border-l-amber-500 bg-amber-900/20' : DEPTH_BORDER[Math.min(row.depth, 2)]} ${!selected && row.depth === 0 ? 'bg-slate-800/50 font-medium' : ''} ${onRowClick ? 'cursor-pointer hover:bg-slate-700/50' : ''}`}
              style={{
                height: rowHeightPx,
                paddingLeft: 12 + row.depth * DEPTH_INDENT_PX,
              }}
              onClick={() => {
                if (row.kind === 'project' && onRowClick) onRowClick(row)
                else if (row.kind === 'task' && onRowClick) onRowClick(row)
                else if (row.kind === 'initiative' && onRowClick) onRowClick(row)
              }}
              role="button"
            >
              <div className="flex-1 min-w-0 flex flex-col justify-center">
                <div className="flex items-center gap-1">
                  {(row.kind === 'initiative' || row.kind === 'project' || row.kind === 'task') && hasChildren && (
                    <span
                      className="inline-block w-4 h-4 shrink-0 text-slate-400 select-none"
                      onClick={(e) => {
                        e.stopPropagation()
                        onToggle?.(row.id)
                      }}
                    >
                      {isCollapsed ? '▶' : '▼'}
                    </span>
                  )}
                  <span className="truncate text-slate-200" title={row.label}>
                    {row.label}
                  </span>
                </div>
                {subline.text && (
                  <p className="text-[11px] truncate mt-0.5" title={subline.title ?? undefined}>
                    {subline.summary && <span className="text-slate-500">{subline.summary}</span>}
                    {subline.summary && subline.waits && <span className="text-slate-500"> · </span>}
                    {subline.waits && <span className="text-amber-400/70">{subline.waits}</span>}
                  </p>
                )}
              </div>
              <div className="shrink-0 flex flex-col justify-center items-end gap-0.5">
                <span className="w-16 text-xs text-slate-500 text-center">
                  {KIND_LABEL[row.kind] ?? row.kind}
                </span>
                <span className="w-20 text-xs text-slate-400 truncate" title={row.status}>
                  {row.status || '—'}
                </span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
