import { useCallback, useState } from 'react'
import { DEFAULT_SEAT_COLOR, VOICE_COLORS } from '../components/VoiceWeave'
import { STRANDS } from '../living-tree/strands'

/**
 * Per-conversation color + symbol identity (founder, 2026-11-12):
 * conversations are identified by color + symbol, not by text
 * titles. The SERVER conversation row is the primary store now —
 * the "+" disposition flow writes symbol + color there (archive /
 * keep open), and list entries carry them. This localStorage map
 * remains as the fallback for conversations that predate the
 * server field and as the write-through mirror when the flow sets
 * an identity, so badges agree across surfaces.
 */
export type TalkIdentity = {
  color: string | null
  symbol: number | null
}

export const TALK_IDENTITY_STORAGE_KEY = 'zenaf.talkIdentity.v1'

/** Palette: the 7 seat colors + the 7 strand colors (deduped) + neutrals. */
export const TALK_PALETTE: string[] = (() => {
  const seen = new Set<string>()
  const out: string[] = []
  const push = (c: string) => {
    const k = c.toLowerCase()
    if (!seen.has(k)) {
      seen.add(k)
      out.push(c)
    }
  }
  for (const id of ['mentor', 'champion', 'guardian', 'maverick', 'ambassador', 'conductor', 'skeptic']) {
    push(VOICE_COLORS[id] ?? DEFAULT_SEAT_COLOR)
  }
  for (const s of STRANDS) push(s.color)
  push('#f5f0e8')
  push('#e8a33d')
  return out
})()

type IdentityMap = Record<string, TalkIdentity>

function readAll(): IdentityMap {
  try {
    const raw = localStorage.getItem(TALK_IDENTITY_STORAGE_KEY)
    if (!raw) return {}
    const data: unknown = JSON.parse(raw)
    if (!data || typeof data !== 'object' || Array.isArray(data)) return {}
    const out: IdentityMap = {}
    for (const [k, v] of Object.entries(data as Record<string, unknown>)) {
      if (!v || typeof v !== 'object') continue
      const color =
        typeof (v as { color?: unknown }).color === 'string'
          ? ((v as { color: string }).color as string)
          : null
      const symbol =
        typeof (v as { symbol?: unknown }).symbol === 'number'
          ? ((v as { symbol: number }).symbol as number)
          : null
      if (color || symbol) out[k] = { color, symbol }
    }
    return out
  } catch {
    return {}
  }
}

function writeAll(map: IdentityMap): void {
  try {
    localStorage.setItem(TALK_IDENTITY_STORAGE_KEY, JSON.stringify(map))
  } catch {
    // Storage full or unavailable — identity stays in-memory for the session.
  }
}

export function getTalkIdentity(conversationId: string): TalkIdentity {
  return readAll()[conversationId] ?? { color: null, symbol: null }
}

/**
 * Local state + write-through for the identity map. Components read
 * identities through this hook so a pick re-renders every badge.
 */
export function useTalkIdentities(): {
  identities: IdentityMap
  setIdentity: (conversationId: string, patch: Partial<TalkIdentity>) => void
  clearIdentity: (conversationId: string) => void
} {
  const [identities, setIdentities] = useState<IdentityMap>(() => readAll())
  const setIdentity = useCallback((conversationId: string, patch: Partial<TalkIdentity>) => {
    setIdentities((prev) => {
      const next = { ...prev }
      const cur = next[conversationId] ?? { color: null, symbol: null }
      const merged = { ...cur, ...patch }
      if (!merged.color && !merged.symbol) delete next[conversationId]
      else next[conversationId] = merged
      writeAll(next)
      return next
    })
  }, [])
  const clearIdentity = useCallback((conversationId: string) => {
    setIdentities((prev) => {
      if (!(conversationId in prev)) return prev
      const next = { ...prev }
      delete next[conversationId]
      writeAll(next)
      return next
    })
  }, [])
  return { identities, setIdentity, clearIdentity }
}
