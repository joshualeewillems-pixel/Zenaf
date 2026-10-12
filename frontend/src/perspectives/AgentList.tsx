import type { PerspectiveAgent } from './types'
import { archetypeLabelForSourceId } from './types'
import { AgentPreviewCard } from './AgentPreviewCard'

export function AgentList({
  agents,
  selectedId,
  onSelect,
  readOnly,
  emptyMessage,
  showSystemTag,
  yourProfileActorId,
  getMakeOwnAction,
  showArchetypeProvenance,
  profileCardDisplayName,
}: {
  agents: PerspectiveAgent[]
  selectedId: string | null
  onSelect: (agent: PerspectiveAgent) => void
  /** Static list (no click affordance). */
  readOnly?: boolean
  emptyMessage?: string
  /** Subtle “system” label on each card (Foundation built-ins). */
  showSystemTag?: boolean
  /** When set, this actor id shows the “your profile” label instead of system. */
  yourProfileActorId?: string | null
  /** Foundation System column: per-agent “Make my own” / “You have one”. */
  getMakeOwnAction?: (agent: PerspectiveAgent) => { label: string; onClick: () => void } | null
  /** Foundation Yours: show “Based on …” from source_archetype_id. */
  showArchetypeProvenance?: boolean
  /** Foundation: override the core-voice card title with the core profile name. */
  profileCardDisplayName?: string
}) {
  if (agents.length === 0) {
    return (
      <div className="rounded-xl border border-[color:var(--color-border)] bg-surface-raised/30 p-6 text-center text-warm-white/45 text-sm">
        {emptyMessage ?? 'No actors yet. Create one to get started.'}
      </div>
    )
  }

  return (
    <ul className="space-y-2">
      {agents.map((agent) => (
        <li key={agent.id}>
          <AgentPreviewCard
            agent={agent}
            compact
            selected={selectedId === agent.id}
            showSystemTag={Boolean(showSystemTag && agent.id !== yourProfileActorId)}
            showYourProfileTag={Boolean(yourProfileActorId && agent.id === yourProfileActorId)}
            onSelect={readOnly ? undefined : () => onSelect(agent)}
            makeOwnAction={getMakeOwnAction?.(agent) ?? undefined}
            basedOnArchetypeName={
              showArchetypeProvenance ? archetypeLabelForSourceId(agent.source_archetype_id) : null
            }
            primaryTitleOverride={
              yourProfileActorId && agent.id === yourProfileActorId ? profileCardDisplayName : undefined
            }
          />
        </li>
      ))}
    </ul>
  )
}
