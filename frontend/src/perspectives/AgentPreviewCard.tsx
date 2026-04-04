import type { PerspectiveAgent } from './types'
import { AvatarDisplay } from '../components/AvatarDisplay'
import { iconHintFor } from './roleIcons'

export function AgentPreviewCard({
  agent,
  onSelect,
  compact,
  selected,
  showSystemTag,
  showYourProfileTag,
  makeOwnAction,
  basedOnArchetypeName,
  primaryTitleOverride,
}: {
  agent: PerspectiveAgent
  onSelect?: () => void
  compact?: boolean
  selected?: boolean
  showSystemTag?: boolean
  /** Foundation: subtle label for Brand (core profile). */
  showYourProfileTag?: boolean
  /** Foundation system: duplicate archetype or jump to existing personal copy. */
  makeOwnAction?: { label: string; onClick: () => void }
  /** Foundation Yours: provenance when copied from a system archetype. */
  basedOnArchetypeName?: string | null
  /** When set (e.g. Brand + core profile name), replaces `agent.name` in the card title. */
  primaryTitleOverride?: string
}) {
  const hasDetails = agent.purpose || agent.values.length > 0 || agent.domain.length > 0
  const cardTitle = (primaryTitleOverride?.trim() || agent.name || 'Unnamed actor').trim() || 'Unnamed actor'

  return (
    <div
      role={onSelect ? 'button' : undefined}
      onClick={onSelect}
      className={`group rounded-xl border text-left transition-colors ${
        selected
          ? 'border-accent/60 bg-surface-raised ring-1 ring-accent/25'
          : 'border-[color:var(--color-border)] bg-surface-raised/60'
      } ${onSelect ? 'cursor-pointer hover:border-accent/35 hover:bg-surface-raised' : ''} ${compact ? 'p-3' : 'p-4'}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex items-start gap-2">
          <span className="mt-0.5 shrink-0" title={iconHintFor(agent)}>
            <AvatarDisplay agent={agent} size="sm" className="ring-1 ring-[color:var(--color-border)]/80" />
          </span>
          <div className="min-w-0">
            <h3 className="font-semibold text-warm-white truncate" title={cardTitle}>
              {cardTitle}
            </h3>
            {agent.role && <p className="text-xs text-accent/90 mt-0.5">{agent.role}</p>}
            {showYourProfileTag ? (
              <p className="text-[10px] tracking-wide text-warm-white/45 mt-0.5 italic">your profile</p>
            ) : showSystemTag ? (
              <p className="text-[10px] uppercase tracking-wide text-warm-white/40 mt-0.5">system</p>
            ) : null}
            {basedOnArchetypeName ? (
              <p className="text-[10px] text-warm-white/40 mt-0.5">Based on {basedOnArchetypeName}</p>
            ) : null}
          </div>
        </div>
      </div>
      {makeOwnAction ? (
        <div
          className="mt-2 pt-1.5 border-t border-[color:var(--color-border)] border-opacity-50 opacity-60 group-hover:opacity-100 transition-opacity"
          onClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => e.stopPropagation()}
          role="presentation"
        >
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              makeOwnAction.onClick()
            }}
            className="text-[11px] font-medium text-accent hover:text-accent/90 underline-offset-2 hover:underline bg-transparent p-0 text-left"
          >
            {makeOwnAction.label}
          </button>
        </div>
      ) : null}
      {!compact && hasDetails && (
        <div className="mt-3 space-y-2 text-xs text-warm-white/55">
          {agent.purpose && <p className="line-clamp-2">{agent.purpose}</p>}
          {agent.values.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {agent.values.slice(0, 4).map((v, i) => (
                <span key={i} className="px-2 py-0.5 rounded bg-surface-sunken text-warm-white/80 border border-[color:var(--color-border)]">
                  {v}
                </span>
              ))}
              {agent.values.length > 4 && <span className="text-warm-white/40">+{agent.values.length - 4}</span>}
            </div>
          )}
          {agent.domain.length > 0 && (
            <p className="text-warm-white/45">
              Domain: {agent.domain.slice(0, 3).join(', ')}
              {agent.domain.length > 3 ? '…' : ''}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
