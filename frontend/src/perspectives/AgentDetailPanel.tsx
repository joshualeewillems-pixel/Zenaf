import type { ReactNode } from 'react'
import type { PerspectiveAgent } from './types'
import { AvatarDisplay } from '../components/AvatarDisplay'

export function AgentDetailPanel({
  agent,
  onEdit,
  onChat,
  onUseInWorkspace,
  onDelete,
  isUserDefined,
  footerExtra,
  readOnlyActions,
  showWorkout,
  onStartWorkout,
}: {
  agent: PerspectiveAgent
  onEdit: () => void
  onChat: () => void
  onUseInWorkspace: () => void
  onDelete?: (agent: PerspectiveAgent) => void
  isUserDefined?: boolean
  /** Optional block below action buttons (e.g. Influences / links). */
  footerExtra?: ReactNode
  /** When true, hide chat / workspace / edit / delete (built-in system actors). */
  readOnlyActions?: boolean
  /** User-defined actors only: opens Perspective Workout (not shown for built-in system actors). */
  showWorkout?: boolean
  onStartWorkout?: () => void
}) {
  const cardTitle = (agent.name || 'Unnamed actor').trim() || 'Unnamed actor'

  return (
    <div className="rounded-xl border border-[color:var(--color-border)] bg-surface-raised/50 overflow-hidden">
      <div className="p-4 border-b border-[color:var(--color-border)]">
        <div className="flex items-start gap-3">
          <AvatarDisplay agent={agent} size="lg" />
          <div className="min-w-0 flex-1">
            <h2 className="text-lg font-semibold text-warm-white truncate" title={cardTitle}>
              {cardTitle}
            </h2>
            {agent.role ? <p className="text-sm text-accent/90 mt-0.5">{agent.role}</p> : null}
          </div>
        </div>
      </div>
      <div className="p-4 space-y-4">
        {agent.purpose ? (
          <div>
            <p className="text-xs text-warm-white/45 uppercase tracking-wide mb-1">Description</p>
            <p className="text-sm text-warm-white/85">{agent.purpose}</p>
          </div>
        ) : null}
        {agent.values.length > 0 ? (
          <div>
            <p className="text-xs text-warm-white/45 uppercase tracking-wide mb-2">Values</p>
            <div className="flex flex-wrap gap-2">
              {agent.values.map((v, i) => (
                <span
                  key={i}
                  className="px-2.5 py-1 rounded-lg bg-surface-sunken border border-[color:var(--color-border)] text-warm-white/90 text-xs font-medium"
                >
                  {v}
                </span>
              ))}
            </div>
          </div>
        ) : null}
        {agent.domain.length > 0 ? (
          <div>
            <p className="text-xs text-warm-white/45 uppercase tracking-wide mb-1">Domain</p>
            <p className="text-sm text-warm-white/60">{agent.domain.join(', ')}</p>
          </div>
        ) : null}
      </div>
      {!readOnlyActions ? (
        <div className="p-4 border-t border-[color:var(--color-border)] flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onChat}
            className="px-3 py-1.5 rounded-lg bg-accent hover:opacity-90 text-warm-white text-xs font-medium"
          >
            Chat with this actor
          </button>
          <button
            type="button"
            onClick={onUseInWorkspace}
            className="px-3 py-1.5 rounded-lg border border-[color:var(--color-border)] text-warm-white/80 hover:bg-surface-raised text-xs font-medium"
          >
            Use in Workspace Organizer
          </button>
          {isUserDefined ? (
            <>
              <button
                type="button"
                onClick={onEdit}
                className="px-3 py-1.5 rounded-lg border border-[color:var(--color-border)] text-warm-white/80 hover:bg-surface-raised text-xs font-medium"
              >
                Edit
              </button>
              {onDelete ? (
                <button
                  type="button"
                  onClick={() => onDelete(agent)}
                  className="px-3 py-1.5 rounded-lg border border-red-800/60 text-red-400 hover:text-red-300 hover:border-red-700 text-xs font-medium"
                >
                  Delete actor
                </button>
              ) : null}
              {showWorkout && onStartWorkout ? (
                <button
                  type="button"
                  onClick={onStartWorkout}
                  className="px-3 py-1.5 rounded-lg bg-flare-bright text-warm-white text-xs font-medium hover:opacity-90"
                >
                  Workout →
                </button>
              ) : null}
            </>
          ) : null}
        </div>
      ) : null}
      {footerExtra ? <div className="border-t border-[color:var(--color-border)]">{footerExtra}</div> : null}
    </div>
  )
}
