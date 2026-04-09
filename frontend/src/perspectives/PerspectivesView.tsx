import { useCallback, useEffect, useMemo } from 'react'
import type { PerspectiveAgent } from './types'
import {
  BUILT_IN_PERSPECTIVES,
  isUserDefined,
  normalizeStoredPerspectiveAgents,
  FOUNDATION_SYSTEM_ACTOR_ORDER,
  canMakeOwnFromFoundationSystemActor,
  createPersonalArchetypeCopy,
  findPersonalArchetypeInstance,
} from './types'
import { AgentList } from './AgentList'

const STORAGE_KEY = 'zenaf-perspective-agents'

function loadFromStorage(): PerspectiveAgent[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as unknown
    if (!Array.isArray(parsed)) return []
    return parsed as PerspectiveAgent[]
  } catch {
    return []
  }
}

function saveToStorage(agents: PerspectiveAgent[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(agents))
  } catch (_) {}
}

/**
 * Foundation: two columns (System | Yours).
 * Selection list only — actor detail, Brand hero, and edit/create forms render in App’s Foundation panel.
 */
export function PerspectivesView({
  agents: externalAgents,
  onAgentsChange,
  useStorage = true,
  selectedActorId,
  onSelectActorId,
  onRequestNewActor,
  brandCoreProfileDisplayName = '',
}: {
  agents: PerspectiveAgent[]
  onAgentsChange: (agents: PerspectiveAgent[]) => void
  useStorage?: boolean
  selectedActorId: string | null
  onSelectActorId: (id: string) => void
  onRequestNewActor: () => void
  /** User-defined core profile name for the Brand row (synced from server + Brand panel). */
  brandCoreProfileDisplayName?: string
}) {
  const agents = externalAgents

  const systemAgents = useMemo(() => {
    const byId = new Map(agents.map((a) => [a.id, a]))
    return FOUNDATION_SYSTEM_ACTOR_ORDER.map((id) => byId.get(id)).filter((a): a is PerspectiveAgent => a != null)
  }, [agents])

  const userAgents = useMemo(() => agents.filter(isUserDefined), [agents])

  const brandAgent = useMemo(() => agents.find((a) => a.id === 'brand'), [agents])
  const yoursActors = useMemo(() => {
    const tail = userAgents.filter((a) => a.id !== 'brand')
    return brandAgent ? [brandAgent, ...tail] : tail
  }, [brandAgent, userAgents])

  useEffect(() => {
    if (useStorage && externalAgents.length === 0) {
      const stored = loadFromStorage()
      const next =
        stored.length > 0 ? normalizeStoredPerspectiveAgents(stored) : BUILT_IN_PERSPECTIVES
      onAgentsChange(next)
      if (stored.length > 0) saveToStorage(next)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const getMakeOwnAction = useCallback(
    (agent: PerspectiveAgent) => {
      if (!canMakeOwnFromFoundationSystemActor(agent)) return null
      const existing = findPersonalArchetypeInstance(userAgents, agent)
      if (existing) {
        return {
          label: 'You have one →',
          onClick: () => onSelectActorId(existing.id),
        }
      }
      return {
        label: 'Make my own →',
        onClick: () => {
          const copy = createPersonalArchetypeCopy(agent)
          const next = [...agents, copy]
          onAgentsChange(next)
          if (useStorage) {
            try {
              saveToStorage(next)
            } catch {
              /* ignore */
            }
          }
          onSelectActorId(copy.id)
        },
      }
    },
    [agents, userAgents, onAgentsChange, onSelectActorId, useStorage],
  )

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex-1 overflow-auto min-h-0 p-4">
        <div className="grid gap-6 md:grid-cols-2 max-w-5xl mx-auto h-full min-h-0">
          <aside className="space-y-4">
            <div>
              <p className="text-xs font-medium text-warm-white/80 uppercase tracking-wide mb-1">System</p>
              <p className="text-[10px] text-warm-white/45 mb-2">Built-in · read-only</p>
              <AgentList
                agents={systemAgents}
                selectedId={selectedActorId}
                showSystemTag
                readOnly={false}
                onSelect={(a) => onSelectActorId(a.id)}
                getMakeOwnAction={getMakeOwnAction}
              />
            </div>
          </aside>
          <aside className="space-y-4">
            <div>
              <p className="text-xs font-medium text-warm-white/80 uppercase tracking-wide mb-2">Yours</p>
              <AgentList
                agents={yoursActors}
                selectedId={selectedActorId}
                yourProfileActorId="brand"
                emptyMessage="Brand and your custom actors appear here."
                onSelect={(a) => onSelectActorId(a.id)}
                showArchetypeProvenance
                brandCardDisplayName={brandCoreProfileDisplayName}
              />
              <button
                type="button"
                onClick={() => {
                  onRequestNewActor()
                }}
                className="w-full mt-3 px-4 py-2.5 rounded-lg border border-dashed border-[color:var(--color-border)] text-warm-white/70 hover:text-warm-white hover:border-accent/50 text-sm transition-colors"
              >
                + New actor
              </button>
            </div>
          </aside>
        </div>
      </div>
    </div>
  )
}
