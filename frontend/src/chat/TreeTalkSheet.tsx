import { useCallback, useEffect, useState } from 'react'
import { apiBase } from '../apiBase'
import CouncilChat from './CouncilChat'
import SeatChips, { useSeatMeta } from './SeatChips'

/**
 * Durable Tree Talk (Slice A): the Tree sheet's conversation mount.
 *
 * Resolution rules (founder-approved, 2026-11-03):
 * - A seat sheet auto-resumes the MOST RECENT conversation involving
 *   that seat — by conversation, never a seat-owned copy: a seat that
 *   already participates in a multi-seat conversation eventually
 *   reopens that conversation, because identity belongs to the
 *   conversation and the seats array is only discovery data.
 * - Otherwise it holds a freshly generated `talk-` id (not yet
 *   persisted — the server row is created on first send).
 * - "New conversation" is always visible and is the only way a new
 *   thread starts; the user — never the system — decides.
 * - The you-node is the rediscovery surface: the recent-talks list
 *   plus "Start new". Picking a talk opens it; starting new offers
 *   the seat chips and then follows seat-sheet resolution.
 * - If the list cannot be fetched, the sheet shows an error state.
 *   It NEVER falls back to client-history chat from the Tree: an
 *   unresolvable Tree Talk is an error, not a silent ephemeral thread.
 *   (The workspace console keeps its own client-history mount.)
 */

/** One entry of GET /conversation/list. `seats` is message-derived
 *  discovery data only — seats that have already spoken in the
 *  conversation. It is NOT a participation or authorization record. */
export type TalkListItem = {
  conversation_id: string
  kind: string | null
  created_at: string | null
  updated_at: string | null
  message_count: number
  seats: string[]
  last_message_at: string | null
  last_message_preview: string | null
}

/** `talk-` + 32 lowercase hex chars (37 total, within the route's
 *  64-char max). Disjoint from `skeleton`, `meeting-*`, and `stone:*`
 *  by construction. */
export function newTalkId(): string {
  // Loosely typed on purpose: feature-detect at runtime instead of
  // letting the compiler narrow `crypto` to never after the first check.
  const c = (globalThis as unknown as {
    crypto?: {
      randomUUID?: () => string
      getRandomValues?: (arr: Uint8Array) => Uint8Array
    }
  }).crypto
  if (c?.randomUUID) {
    return `talk-${c.randomUUID().replace(/-/g, '')}`
  }
  if (c?.getRandomValues) {
    return `talk-${Array.from(c.getRandomValues(new Uint8Array(16)))
      .map((b: number) => b.toString(16).padStart(2, '0'))
      .join('')}`
  }
  let hex = ''
  for (let i = 0; i < 32; i++) hex += Math.floor(Math.random() * 16).toString(16)
  return `talk-${hex}`
}

function formatWhen(iso: string | null): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return ''
  }
}

export default function TreeTalkSheet({
  seatKey,
  displayName,
}: {
  /** Seat node id, or null for the you-node rediscovery surface. */
  seatKey: string | null
  /** Seat fellowship name override for the composer placeholder. */
  displayName?: string
}) {
  const base = apiBase()
  const { names } = useSeatMeta()
  const [mode, setMode] = useState<'loading' | 'chat' | 'list' | 'pick' | 'error' | 'signedout'>(
    'loading',
  )
  const [chatId, setChatId] = useState<string | null>(null)
  const [chatSeat, setChatSeat] = useState<string | null>(seatKey)
  const [fromList, setFromList] = useState(false)
  const [talks, setTalks] = useState<TalkListItem[]>([])
  const [nonce, setNonce] = useState(0)

  const resolveSeat = useCallback(
    (list: TalkListItem[], seat: string): string => {
      const found = list.find((t) => t.seats.includes(seat))
      return found ? found.conversation_id : newTalkId()
    },
    [],
  )

  useEffect(() => {
    let cancelled = false
    setMode('loading')
    fetch(`${base}/conversation/list`, { credentials: 'include' })
      .then(async (r) => {
        if (r.status === 401) return { auth: true as const }
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return (await r.json()) as { conversations?: TalkListItem[] }
      })
      .then((data) => {
        if (cancelled) return
        if ((data as { auth?: boolean }).auth) {
          setMode('signedout')
          return
        }
        const list = Array.isArray(
          (data as { conversations?: unknown }).conversations,
        )
          ? ((data as { conversations: TalkListItem[] }).conversations as TalkListItem[])
          : []
        setTalks(list)
        if (seatKey) {
          setChatSeat(seatKey)
          setFromList(false)
          setChatId(resolveSeat(list, seatKey))
          setMode('chat')
        } else {
          setMode('list')
        }
      })
      .catch(() => {
        if (!cancelled) setMode('error')
      })
    return () => {
      cancelled = true
    }
  }, [base, seatKey, nonce, resolveSeat])

  const startNew = useCallback(() => {
    setChatId(newTalkId())
    setMode('chat')
  }, [])

  if (mode === 'loading') {
    return <p className="text-sm text-stone-400 px-1 py-2">Loading conversation…</p>
  }

  if (mode === 'signedout') {
    return <p className="text-sm text-stone-400 px-1 py-2">Please sign in to talk to your voices.</p>
  }

  if (mode === 'error') {
    return (
      <div className="rounded-2xl border border-red-800/60 bg-red-950/30 px-3 py-2 text-sm text-red-200">
        Couldn&apos;t load your conversations.
        <button
          type="button"
          onClick={() => setNonce((n) => n + 1)}
          className="ml-2 underline font-medium"
        >
          Retry
        </button>
      </div>
    )
  }

  if (mode === 'pick') {
    return (
      <div className="flex flex-col gap-3">
        <p className="text-sm text-stone-400 px-1">
          Pick a voice to start with — if you already have a conversation with them, it
          reopens.
        </p>
        <SeatChips
          activeId={null}
          onSelect={(id) => {
            setChatSeat(id)
            setFromList(true)
            setChatId(resolveSeat(talks, id))
            setMode('chat')
          }}
        />
        <button
          type="button"
          onClick={() => setMode('list')}
          className="self-start min-h-[44px] px-4 rounded-full border border-stone-700 text-sm text-stone-400"
        >
          ← Conversations
        </button>
      </div>
    )
  }

  if (mode === 'list') {
    return (
      <div className="flex flex-col gap-3">
        {talks.length === 0 ? (
          <p className="text-sm text-stone-400 px-1 py-2">
            No conversations yet — start one below.
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            {talks.map((t) => (
              <button
                key={t.conversation_id}
                type="button"
                onClick={() => {
                  setChatSeat(null)
                  setFromList(true)
                  setChatId(t.conversation_id)
                  setMode('chat')
                }}
                className="text-left rounded-2xl border border-stone-700/60 bg-stone-900/70 px-3 py-2"
              >
                <span className="block text-sm text-stone-200">
                  {t.seats.map((s) => names[s] ?? s).join(', ') || 'Conversation'}
                </span>
                {t.last_message_preview && (
                  <span className="block text-xs text-stone-400 truncate">
                    {t.last_message_preview}
                  </span>
                )}
                <span className="block text-[11px] text-stone-500">
                  {t.message_count} messages
                  {formatWhen(t.last_message_at) ? ` · ${formatWhen(t.last_message_at)}` : ''}
                </span>
              </button>
            ))}
          </div>
        )}
        <button
          type="button"
          onClick={() => setMode('pick')}
          className="self-start min-h-[44px] px-4 rounded-full bg-amber-600 text-amber-50 text-sm font-semibold"
        >
          Start new
        </button>
      </div>
    )
  }

  // mode === 'chat'
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={startNew}
          className="min-h-[44px] px-4 rounded-full border border-stone-700 text-sm text-stone-400"
        >
          New conversation
        </button>
        {fromList && (
          <button
            type="button"
            onClick={() => setMode('list')}
            className="min-h-[44px] px-4 rounded-full border border-stone-700 text-sm text-stone-400"
          >
            ← Conversations
          </button>
        )}
      </div>
      {chatId && (
        <CouncilChat
          key={chatId}
          environment="sheet"
          conversationId={chatId}
          initialArchetypeId={chatSeat}
          displayName={displayName}
        />
      )}
    </div>
  )
}
