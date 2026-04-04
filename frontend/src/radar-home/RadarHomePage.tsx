/**
 * Radar Home — default landing page. Role-specific dashboard backed by **demo seed** domain data.
 * Derives from shared domain; items carry source refs and navigate to VE / queue.
 */

import { useMemo } from 'react'
import { useDomain } from '../domain/DomainContext'
import { getRadarSummaryForRole } from './radarData'
import type { AttentionItem, InventoryAlert } from './types'

/** Display labels only; role ids stay stable for routing. Person names are illustrative, not a real org default. */
const ROLE_LABEL: Record<string, string> = {
  'anna-admin': 'Operations · Admin overview (demo)',
  'phil-program-content': 'Program & content (demo)',
  'josh-executive-builder': 'Executive / builder (demo)',
}

export type RadarNavigation = {
  onOpenQueue?: () => void
  onOpenProject?: (projectId: string) => void
  onOpenTask?: (taskId: string, projectId?: string) => void
  onOpenAsset?: (assetId: string) => void
  onOpenInitiative?: (initiativeId: string) => void
}

type RadarHomePageProps = {
  role?: 'anna-admin'
} & RadarNavigation

function formatDate() {
  return new Date().toLocaleDateString(undefined, {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })
}

function SeverityBadge({ severity }: { severity: AttentionItem['severity'] }) {
  const style =
    severity === 'high'
      ? 'bg-red-900/50 text-red-200 border-red-700'
      : severity === 'medium'
        ? 'bg-amber-900/50 text-amber-200 border-amber-700'
        : 'bg-slate-600/50 text-slate-300 border-slate-500'
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded border ${style}`}>
      {severity}
    </span>
  )
}

function InventoryStatusBadge({ status }: { status: InventoryAlert['status'] }) {
  const style =
    status === 'low'
      ? 'bg-red-900/50 text-red-200'
      : status === 'reorder_soon'
        ? 'bg-amber-900/50 text-amber-200'
        : status === 'pending_order'
          ? 'bg-blue-900/50 text-blue-200'
          : 'bg-slate-600/50 text-slate-300'
  const label =
    status === 'pending_order' ? 'Pending order' : status === 'reorder_soon' ? 'Reorder soon' : status
  return <span className={`text-xs px-1.5 py-0.5 rounded ${style}`}>{label}</span>
}

export function RadarHomePage({
  role = 'anna-admin',
  onOpenQueue,
  onOpenProject,
  onOpenTask,
  onOpenAsset,
  onOpenInitiative: _onOpenInitiative,
}: RadarHomePageProps) {
  const domain = useDomain()
  const viewModel = useMemo(() => getRadarSummaryForRole(domain, role), [domain, role])
  const dateStr = useMemo(() => formatDate(), [])

  return (
    <div className="flex-1 overflow-auto p-6 max-w-6xl mx-auto">
      {/* Header */}
      <header className="mb-8">
        <h1 className="text-2xl font-semibold text-slate-100">Radar Home</h1>
        <p className="text-slate-400 text-sm mt-1">
          What needs attention
        </p>
        <div className="flex flex-wrap items-center gap-4 mt-4 text-sm">
          <span className="px-2.5 py-1 rounded-lg bg-slate-700/80 text-slate-200">
            {ROLE_LABEL[role] ?? role}
          </span>
          <span className="text-slate-500">{dateStr}</span>
        </div>
      </header>

      {/* Card grid: row1 Needs Attention + Today's Operations, row2 Intake + Inventory, row3 Active Projects (wide), row4 Waiting/Blocked */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Row 1: Needs Attention (wide) + Today's Operations */}
        <div className="rounded-xl border border-slate-600 bg-slate-800/50 p-5 lg:row-span-1">
          <h2 className="text-sm font-semibold text-amber-400/90 mb-1">Needs Attention</h2>
          <p className="text-slate-500 text-xs mb-3">Insurance filings, emails, overdue tasks, approvals</p>
          {viewModel.attentionItems.length === 0 ? (
            <p className="text-slate-500 text-sm">Nothing urgent right now.</p>
          ) : (
            <ul className="space-y-2">
              {viewModel.attentionItems.map((item) => {
                const clickable = (item.taskId && onOpenTask) || (item.sourceType === 'inbox' && item.kind !== 'email' && onOpenQueue)
                const onClick = clickable
                  ? () => { if (item.taskId && onOpenTask) onOpenTask(item.taskId!, item.projectId); else if (onOpenQueue) onOpenQueue() }
                  : undefined
                return (
                  <li
                    key={item.id}
                    className={`flex items-center gap-2 text-sm text-slate-200 ${clickable ? 'cursor-pointer hover:bg-slate-700/50 rounded px-1 -mx-1' : ''}`}
                    onClick={onClick}
                    role={clickable ? 'button' : undefined}
                  >
                    <SeverityBadge severity={item.severity} />
                    <span className="flex-1 truncate">{item.label}</span>
                    {item.count != null && (
                      <span className="text-slate-500 shrink-0">{item.count}</span>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
        </div>

        <div className="rounded-xl border border-slate-600 bg-slate-800/50 p-5">
          <h2 className="text-sm font-semibold text-amber-400/90 mb-1">Today&apos;s Operations</h2>
          <p className="text-slate-500 text-xs mb-3">Appointments, consults, follow-ups</p>
          <div className="grid grid-cols-2 gap-3">
            {viewModel.operationsMetrics.map((m) => (
              <div key={m.id} className="rounded-lg bg-slate-900/60 p-3">
                <div className="text-xl font-semibold text-slate-100">{m.value}</div>
                <div className="text-xs text-slate-400">{m.label}</div>
                {m.hint && (
                  <div className="text-xs text-slate-500 mt-0.5">{m.hint}</div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Row 2: Intake / Inbox Queue + Inventory Alerts */}
        <div className="rounded-xl border border-slate-600 bg-slate-800/50 p-5">
          <h2 className="text-sm font-semibold text-amber-400/90 mb-1">Intake / Inbox Queue</h2>
          <p className="text-slate-500 text-xs mb-3">Emails and faxes needing review</p>
          <div className="flex flex-wrap gap-2 mb-3">
            <span className="px-2 py-1 rounded bg-slate-700 text-slate-200 text-sm">
              {viewModel.queueSummary.totalUnreviewed} unreviewed
            </span>
            <span className="px-2 py-1 rounded bg-slate-700 text-slate-300 text-sm">
              {viewModel.queueSummary.emailCount} email
            </span>
            <span className="px-2 py-1 rounded bg-slate-700 text-slate-300 text-sm">
              {viewModel.queueSummary.faxCount} fax
            </span>
            {viewModel.queueSummary.flaggedCount > 0 && (
              <span className="px-2 py-1 rounded bg-amber-900/50 text-amber-200 text-sm">
                {viewModel.queueSummary.flaggedCount} flagged
              </span>
            )}
          </div>
          {onOpenQueue && (
            <button
              type="button"
              onClick={onOpenQueue}
              className="px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 text-white text-sm font-medium"
            >
              Open queue
            </button>
          )}
        </div>

        <div className="rounded-xl border border-slate-600 bg-slate-800/50 p-5">
          <h2 className="text-sm font-semibold text-amber-400/90 mb-1">Inventory Alerts</h2>
          <p className="text-slate-500 text-xs mb-3">Supply and reorder status</p>
          {viewModel.inventoryAlerts.length === 0 ? (
            <p className="text-slate-500 text-sm">All stock levels okay.</p>
          ) : (
            <ul className="space-y-2">
              {viewModel.inventoryAlerts.map((a) => (
                <li
                  key={a.id}
                  className={`flex items-center gap-2 text-sm text-slate-200 ${onOpenAsset ? 'cursor-pointer hover:bg-slate-700/50 rounded px-1 -mx-1' : ''}`}
                  onClick={onOpenAsset && a.assetId ? () => onOpenAsset(a.assetId!) : undefined}
                  role={onOpenAsset && a.assetId ? 'button' : undefined}
                >
                  <InventoryStatusBadge status={a.status} />
                  <span className="flex-1 truncate">{a.itemName}</span>
                  {a.detail && (
                    <span className="text-slate-500 text-xs shrink-0">{a.detail}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Row 3: Active Projects (wide) */}
        <div className="lg:col-span-2 rounded-xl border border-slate-600 bg-slate-800/50 p-5">
          <h2 className="text-sm font-semibold text-amber-400/90 mb-1">Active Projects</h2>
          <p className="text-slate-500 text-xs mb-3">Active work from demo seed data (replace with your initiatives)</p>
          {viewModel.activeProjects.length === 0 ? (
            <p className="text-slate-500 text-sm">No active projects.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {viewModel.activeProjects.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={onOpenProject ? () => onOpenProject(p.projectId) : undefined}
                  className={`px-3 py-1.5 rounded-lg bg-slate-700/80 text-slate-200 text-sm text-left ${onOpenProject ? 'hover:bg-slate-600/80 cursor-pointer' : ''}`}
                >
                  {p.title}
                  {p.note && (
                    <span className="text-slate-500 text-xs ml-1">— {p.note}</span>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="rounded-xl border border-slate-600 bg-slate-800/50 p-5">
          <h2 className="text-sm font-semibold text-amber-400/90 mb-1">Waiting / Blocked</h2>
          <p className="text-slate-500 text-xs mb-3">Stalled items pending input or review</p>
          {viewModel.blockedItems.length === 0 ? (
            <p className="text-slate-500 text-sm">Nothing blocked.</p>
          ) : (
            <ul className="space-y-2">
              {viewModel.blockedItems.map((b) => (
                <li
                  key={b.id}
                  className={`text-sm text-slate-200 ${onOpenTask ? 'cursor-pointer hover:bg-slate-700/50 rounded px-1 -mx-1 py-0.5' : ''}`}
                  onClick={onOpenTask ? () => onOpenTask(b.taskId, b.projectId) : undefined}
                  role={onOpenTask ? 'button' : undefined}
                >
                  <span className="truncate block">{b.label}</span>
                  <span className="text-slate-500 text-xs">Waiting on: {b.waitingOn}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}
