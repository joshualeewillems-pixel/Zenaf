import { useEffect, useState } from 'react'
import { PerspectiveRoleIcon } from '../perspectives/roleIcons'
import { coreProfileConversationStorageKey } from '../vision-execution/coreProfilePanels'

export type ZenafPresenceProps = {
  brandCoreProfileId: string | null
  onOpen: () => void
}

function truncatePreview(text: string, max = 60): string {
  const t = text.trim().replace(/\s+/g, ' ')
  if (t.length <= max) return t
  return `${t.slice(0, max - 1)}…`
}

function lastAssistantPreview(profileId: string): string | null {
  try {
    const raw = localStorage.getItem(coreProfileConversationStorageKey(profileId))
    if (!raw) return null
    const parsed = JSON.parse(raw) as unknown
    if (!Array.isArray(parsed)) return null
    for (let i = parsed.length - 1; i >= 0; i--) {
      const m = parsed[i]
      if (!m || typeof m !== 'object') continue
      const role = (m as { role?: unknown }).role
      if (role !== 'assistant') continue
      const content = String((m as { content?: unknown }).content ?? '').trim()
      if (!content) continue
      return truncatePreview(content, 60)
    }
    return null
  } catch {
    return null
  }
}

export function ZenafPresence({ brandCoreProfileId, onOpen }: ZenafPresenceProps) {
  const [preview, setPreview] = useState<string | null>(null)

  useEffect(() => {
    if (!brandCoreProfileId) {
      setPreview(null)
      return
    }
    setPreview(lastAssistantPreview(brandCoreProfileId))
  }, [brandCoreProfileId])

  const centerText =
    !brandCoreProfileId || preview == null ? 'No training sessions yet' : preview

  return (
    <footer
      className="shrink-0 flex items-center gap-2 max-h-[60px] min-h-0 px-3 py-2 border-t border-[color:var(--color-border)] bg-[color:var(--color-surface-sunken)]"
      aria-label="Zenaf"
    >
      <div className="flex items-center gap-1.5 shrink-0">
        <PerspectiveRoleIcon icon="spiral" className="h-4 w-4 text-warm-white/45" />
        <span className="text-xs text-warm-white/50 whitespace-nowrap">Zenaf</span>
      </div>
      <p className="flex-1 min-w-0 text-xs text-warm-white/30 truncate" title={centerText}>
        {centerText}
      </p>
      <button
        type="button"
        onClick={onOpen}
        className="shrink-0 text-xs text-accent hover:opacity-90 whitespace-nowrap"
      >
        {brandCoreProfileId ? 'Open →' : 'Set up your profile →'}
      </button>
    </footer>
  )
}
