import { useCallback, useEffect, useRef, useState } from 'react'
import { apiBase } from '../apiBase'
import CouncilChat from './CouncilChat'
import InvitationList, { INVITATIONS_CHANGED_EVENT } from './InvitationList'
import SeatChips, { useSeatMeta } from './SeatChips'
import { symbolUrl, SYMBOL_COUNT } from '../assets/symbols/symbols'
import {
  TALK_PALETTE,
  useTalkIdentities,
  type TalkIdentity,
} from './talkIdentity'

/**
 * Durable Tree Talk (Slice A): the Tree sheet's conversation mount.
 *
 * Resolution rules (founder-approved, 2026-11-03; lookup refined by
 * the 2026-11-04 navigation correction):
 * - A seat sheet auto-resumes the MOST RECENT conversation involving
 *   that seat — by conversation, never a seat-owned copy: a seat that
 *   already participates in a multi-seat conversation eventually
 *   reopens that conversation, because identity belongs to the
 *   conversation and the seats array is only discovery data.
 *   The lookup is SERVER-side and seat-scoped
 *   (GET /conversation/list?seat=<seat>&limit=1): the server applies
 *   an EXISTS membership predicate BEFORE the limit, so the seat's
 *   thread is found even when newer non-seat threads would fill a
 *   capped general list. Client-side first-match over a capped list
 *   is forbidden — it reintroduces the silent cliff.
 * - Empty lookup → a freshly generated `talk-` id (not yet
 *   persisted — the server row is created on first send). A failed
 *   lookup → the error state, never a fabricated fresh thread.
 * - "New conversation" is always visible and is the only way a new
 *   thread starts; the user — never the system — decides.
 * - The you-node is the rediscovery surface: the recent-talks list
 *   plus "Start new". Picking a talk opens it; starting new offers
 *   the seat chips and then follows seat-sheet resolution (the same
 *   seat-scoped lookup, async; failure → error, not a fresh thread).
 * - If the list cannot be fetched, the sheet shows an error state.
 *   It NEVER falls back to client-history chat from the Tree: an
 *   unresolvable Tree Talk is an error, not a silent ephemeral thread.
 *   (The workspace console keeps its own client-history mount.)
 * - An override mount (invitation shortcut) is a chat mount, so the
 *   conversation list stays reachable via ← Conversations (C2: the
 *   user is never trapped in the shortcut's target).
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

/**
 * A conversation's color + symbol emblem (founder, 2026-11-12):
 * history entries are identified by color + symbol, never by a
 * generated text title. Unset → a dashed circle.
 */
function IdentityBadge({ identity, size = 30 }: { identity: TalkIdentity; size?: number }) {
  const url = symbolUrl(identity.symbol)
  return (
    <span
      aria-hidden="true"
      className="inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full"
      style={{
        width: size,
        height: size,
        background: identity.color ?? 'rgba(245,240,232,.06)',
        border: identity.color
          ? `2px solid ${identity.color}`
          : '1px dashed rgba(245,240,232,.35)',
      }}
    >
      {url ? (
        <img src={url} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
      ) : (
        <span className="text-sm leading-none text-stone-400">+</span>
      )}
    </span>
  )
}

export default function TreeTalkSheet({
  seatKey,
  displayName,
  conversationOverride,
  onChatIdChange,
}: {
  /** Seat node id, or null for the you-node rediscovery surface. */
  seatKey: string | null
  /** Seat fellowship name override for the composer placeholder. */
  displayName?: string
  /** Invitation navigation target (Capability C visible-UX slice).
      When present on mount, the sheet mounts this conversation + seat
      directly and skips the talks fetch (fetched lazily on list-mode
      entry). Override wins over seatKey for the initial mount. It is
      cleared by startNew and by list/pick transitions, so
      back-navigation never resurrects a stale override. If the
      override conversation is gone or its invitation expired, the
      mount still succeeds as an ordinary chat and the in-chat list
      shows its empty state. */
  conversationOverride?: { conversationId: string; seat: string }
  /** Reports the current chat conversation id to the Tree (chat mode
      only; null otherwise) so the header menu can hide the invitation
      shortcut when its target IS the open conversation. */
  onChatIdChange?: (id: string | null) => void
}) {
  const base = apiBase()
  const { names } = useSeatMeta()
  const [mode, setMode] = useState<'loading' | 'chat' | 'list' | 'pick' | 'error' | 'signedout'>(
    conversationOverride ? 'chat' : 'loading',
  )
  const [chatId, setChatId] = useState<string | null>(
    conversationOverride?.conversationId ?? null,
  )
  const [chatSeat, setChatSeat] = useState<string | null>(
    conversationOverride?.seat ?? seatKey,
  )
  // C2 return path: an override mount IS a chat mount reached from a
  // navigation action, so ← Conversations stays reachable from it —
  // the user is never trapped in the shortcut's target conversation.
  const [fromList, setFromList] = useState(!!conversationOverride)
  const [talks, setTalks] = useState<TalkListItem[]>([])
  const [talksFetched, setTalksFetched] = useState(false)
  const [nonce, setNonce] = useState(0)
  /** Bumped after every completed turn so the invitation list
      refetches — joining is observed by the entry disappearing. */
  const [inviteRefreshKey, setInviteRefreshKey] = useState(0)
  /** Per-conversation color + symbol (localStorage; see talkIdentity). */
  const { identities, setIdentity, clearIdentity } = useTalkIdentities()
  /** Seat conversation history beside New conversation (founder,
      2026-11-12): the same GET /conversation/list the seat lookup
      already uses, seat-scoped, limit 10; fetched lazily when the
      panel opens. Zero-message conversations never appear — the
      endpoint only lists conversations with at least one message. */
  const [historyOpen, setHistoryOpen] = useState(false)
  const [history, setHistory] = useState<TalkListItem[] | null>(null)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState(false)
  /** Conversation id whose color/symbol picker is open, or null. */
  const [identityFor, setIdentityFor] = useState<string | null>(null)
  const fetchHistory = useCallback(async () => {
    if (!chatSeat) return
    setHistoryLoading(true)
    setHistoryError(false)
    try {
      const r = await fetch(
        `${base}/conversation/list?seat=${encodeURIComponent(chatSeat)}&limit=10`,
        { credentials: 'include' },
      )
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const data = await r.json()
      setHistory(Array.isArray(data.conversations) ? data.conversations : [])
    } catch {
      setHistoryError(true)
    } finally {
      setHistoryLoading(false)
    }
  }, [base, chatSeat])
  useEffect(() => {
    if (historyOpen) void fetchHistory()
  }, [historyOpen, fetchHistory])
  /** Stable signal for the Tree: a list refetch dropped a row. The
      Tree refetches attention; nothing navigates, nothing transitions. */
  const dispatchInvitationsChanged = useCallback(() => {
    window.dispatchEvent(new CustomEvent(INVITATIONS_CHANGED_EVENT))
  }, [])
  /** Mount-time override (captured once). The override is consumed
      at mount (initial state above + the mount effect's early
      return); startNew and list/pick transitions never re-read it,
      so a stale override can never resurrect — clearing is by
      construction, not by a flag. */
  const mountOverrideRef = useRef(conversationOverride ?? null)

  // Reports the open conversation to the Tree (chat mode only).
  const lastReportedChatRef = useRef<string | null | undefined>(undefined)
  useEffect(() => {
    if (!onChatIdChange) return
    const current = mode === 'chat' ? chatId : null
    if (lastReportedChatRef.current !== current) {
      lastReportedChatRef.current = current
      onChatIdChange(current)
    }
  }, [mode, chatId, onChatIdChange])

  // Seat-scoped lookup shared by the seat mount and pick-mode seat
  // selection: one server fetch, EXISTS-before-LIMIT, limit 1.
  // Empty → fresh id (allowed); failure → error (never fresh id).
  // A superseded lookup resolves 'stale' and callers ignore it —
  // never an error, never a clobbering navigation.
  type SeatLookup =
    | { kind: 'ok'; list: TalkListItem[] }
    | { kind: 'auth' }
    | { kind: 'error' }
    | { kind: 'stale' }
  const lookupSeqRef = useRef(0)
  const lookupSeat = useCallback(
    async (seat: string): Promise<SeatLookup> => {
      const seq = ++lookupSeqRef.current
      try {
        const r = await fetch(
          `${base}/conversation/list?seat=${encodeURIComponent(seat)}&limit=1`,
          { credentials: 'include' },
        )
        if (r.status === 401) return { kind: 'auth' }
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        const data = (await r.json()) as { conversations?: TalkListItem[] }
        const list = Array.isArray(data.conversations) ? data.conversations : []
        if (lookupSeqRef.current !== seq) return { kind: 'stale' }
        return { kind: 'ok', list }
      } catch {
        if (lookupSeqRef.current !== seq) return { kind: 'stale' }
        return { kind: 'error' }
      }
    },
    [base],
  )

  useEffect(() => {
    // Override mount: the conversation + seat are already in initial
    // state, so the talks fetch is skipped entirely (fetched lazily
    // on list-mode entry below). The override conversation may be
    // gone or its invitation expired — the mount still succeeds as
    // an ordinary chat and the in-chat list shows its empty state.
    if (mountOverrideRef.current) return
    let cancelled = false
    setMode('loading')
    if (seatKey) {
      // Seat mount: the seat-scoped lookup only. It must NOT populate
      // the list-mode cache — list mode still fetches the general
      // unfiltered list lazily on entry.
      lookupSeat(seatKey).then((result) => {
        if (cancelled || result.kind === 'stale') return
        if (result.kind === 'auth') {
          setMode('signedout')
          return
        }
        if (result.kind === 'error') {
          setMode('error')
          return
        }
        setChatSeat(seatKey)
        setFromList(false)
        setChatId(result.list.length > 0 ? result.list[0].conversation_id : newTalkId())
        setMode('chat')
      })
    } else {
      // You-node mount: the general list is the rediscovery surface.
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
          setTalksFetched(true)
          setMode('list')
        })
        .catch(() => {
          if (!cancelled) setMode('error')
        })
    }
    return () => {
      cancelled = true
    }
  }, [base, seatKey, nonce, lookupSeat])

  // Lazy talks fetch for override mounts that later reach list mode
  // (the mount fetch was skipped). Never fires after a normal mount
  // fetch, which sets talksFetched. NOTE: this effect must NOT set
  // mode to 'loading' — mode is an effect dep, so that would retrigger
  // the effect and its cleanup would cancel the in-flight fetch
  // (the component would hang on "Loading conversation…" forever).
  // Instead the list render shows a loading line while talksFetched
  // is false; mode stays 'list' throughout the fetch.
  useEffect(() => {
    if (mode !== 'list' || talksFetched) return
    let cancelled = false
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
        setTalksFetched(true)
        setMode('list')
      })
      .catch(() => {
        if (!cancelled) setMode('error')
      })
    return () => {
      cancelled = true
    }
  }, [mode, talksFetched, base])

  const startNew = useCallback(() => {
    setChatId(newTalkId())
    setHistoryOpen(false)
    setIdentityFor(null)
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
            // Same seat-scoped lookup as the seat mount (async);
            // failure → error, never a fabricated fresh thread.
            setMode('loading')
            lookupSeat(id).then((result) => {
              if (result.kind === 'stale') return
              if (result.kind === 'auth') {
                setMode('signedout')
                return
              }
              if (result.kind === 'error') {
                setMode('error')
                return
              }
              setChatSeat(id)
              setFromList(true)
              setChatId(result.list.length > 0 ? result.list[0].conversation_id : newTalkId())
              setMode('chat')
            })
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
        {!talksFetched ? (
          <p className="text-sm text-stone-400 px-1 py-2">Loading conversation…</p>
        ) : talks.length === 0 ? (
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
  // History shows past conversations with this seat (seat-scoped list,
  // most recent first); the open conversation is excluded — it is the
  // one already on screen. Rows are identified by color + symbol,
  // never by a text title; the ✎ opens the color/symbol picker.
  const historyRows = (history ?? []).filter((t) => t.conversation_id !== chatId)
  const currentIdentity = chatId ? identities[chatId] ?? { color: null, symbol: null } : null
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
        {chatSeat && (
          <button
            type="button"
            onClick={() => setHistoryOpen((o) => !o)}
            aria-expanded={historyOpen}
            className="min-h-[44px] px-4 rounded-full border border-stone-700 text-sm text-stone-400"
          >
            History
          </button>
        )}
        {chatId && currentIdentity && (
          <button
            type="button"
            onClick={() => setIdentityFor(identityFor === chatId ? null : chatId)}
            aria-label="Choose a color and symbol for this conversation"
            title="Choose a color and symbol for this conversation"
            className="min-h-[44px] min-w-[44px] px-2 rounded-full border border-stone-700 flex items-center justify-center"
          >
            <IdentityBadge identity={currentIdentity} size={30} />
          </button>
        )}
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
      {historyOpen && (
        <div className="flex flex-col gap-2 rounded-2xl border border-stone-700/60 bg-stone-900/70 px-3 py-2">
          {historyLoading ? (
            <p className="text-sm text-stone-400 px-1 py-2">Loading history…</p>
          ) : historyError ? (
            <p className="text-sm text-stone-400 px-1 py-2">
              Couldn’t load history.{' '}
              <button type="button" onClick={() => void fetchHistory()} className="underline">
                Try again
              </button>
            </p>
          ) : historyRows.length === 0 ? (
            <p className="text-sm text-stone-400 px-1 py-2">
              No past conversations with this seat yet.
            </p>
          ) : (
            historyRows.map((t) => (
              <div
                key={t.conversation_id}
                className="flex items-center gap-2 rounded-xl border border-stone-700/60 bg-stone-900/70"
              >
                <button
                  type="button"
                  onClick={() => {
                    setFromList(true)
                    setChatId(t.conversation_id)
                    setHistoryOpen(false)
                    setIdentityFor(null)
                    setMode('chat')
                  }}
                  className="flex min-w-0 flex-1 items-center gap-3 px-3 py-2 text-left"
                >
                  <IdentityBadge
                    identity={identities[t.conversation_id] ?? { color: null, symbol: null }}
                  />
                  <span className="min-w-0 flex-1">
                    {t.last_message_preview && (
                      <span className="block truncate text-sm text-stone-200">
                        {t.last_message_preview}
                      </span>
                    )}
                    <span className="block text-[11px] text-stone-500">
                      {t.message_count} messages
                      {formatWhen(t.last_message_at)
                        ? ` · ${formatWhen(t.last_message_at)}`
                        : ''}
                    </span>
                  </span>
                </button>
                <button
                  type="button"
                  aria-label="Choose a color and symbol for this conversation"
                  title="Choose a color and symbol"
                  onClick={() =>
                    setIdentityFor(
                      identityFor === t.conversation_id ? null : t.conversation_id,
                    )
                  }
                  className="min-h-[44px] min-w-[44px] px-2 text-sm text-stone-400"
                >
                  ✎
                </button>
              </div>
            ))
          )}
        </div>
      )}
      {identityFor && (
        <div className="flex flex-col gap-3 rounded-2xl border border-stone-700/60 bg-stone-900/70 px-3 py-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-semibold text-stone-200">Color &amp; symbol</span>
            <button
              type="button"
              onClick={() => setIdentityFor(null)}
              className="min-h-[44px] px-3 rounded-full border border-stone-700 text-sm text-stone-400"
            >
              Done
            </button>
          </div>
          <div className="flex flex-wrap gap-2" role="group" aria-label="Color">
            {TALK_PALETTE.map((c) => {
              const selected = identities[identityFor]?.color === c
              return (
                <button
                  key={c}
                  type="button"
                  aria-label={`Color ${c}`}
                  aria-pressed={selected}
                  onClick={() => setIdentity(identityFor, { color: c })}
                  className="h-8 w-8 rounded-full"
                  style={{
                    background: c,
                    outline: selected ? '2px solid #f5f0e8' : '1px solid rgba(245,240,232,.25)',
                    outlineOffset: 2,
                  }}
                />
              )
            })}
            <button
              type="button"
              aria-label="No color"
              aria-pressed={!identities[identityFor]?.color}
              onClick={() => setIdentity(identityFor, { color: null })}
              className="h-8 w-8 rounded-full text-xs text-stone-400"
              style={{ outline: '1px dashed rgba(245,240,232,.35)', outlineOffset: 2 }}
            >
              —
            </button>
          </div>
          <div className="grid grid-cols-6 gap-2" role="group" aria-label="Symbol">
            {Array.from({ length: SYMBOL_COUNT }, (_, i) => i + 1).map((n) => {
              const selected = identities[identityFor]?.symbol === n
              return (
                <button
                  key={n}
                  type="button"
                  aria-label={`Symbol ${n}`}
                  aria-pressed={selected}
                  onClick={() => setIdentity(identityFor, { symbol: n })}
                  className="aspect-square overflow-hidden rounded-full"
                  style={{
                    outline: selected ? '2px solid #f5f0e8' : '1px solid rgba(245,240,232,.25)',
                    outlineOffset: 2,
                  }}
                >
                  <img
                    src={symbolUrl(n) ?? ''}
                    alt=""
                    className="h-full w-full object-cover"
                  />
                </button>
              )
            })}
          </div>
          <button
            type="button"
            onClick={() => {
              clearIdentity(identityFor)
              setIdentityFor(null)
            }}
            className="self-start min-h-[44px] px-3 rounded-full border border-stone-700 text-sm text-stone-400"
          >
            Clear color &amp; symbol
          </button>
        </div>
      )}
      {chatId && (
        <>
          <InvitationList
            conversationId={chatId}
            onInviteSelected={(seat) => {
              // Makes the invited seat the active seat; the user's
              // send does the rest. Tapping the already-active seat
              // is a no-op (key unchanged). Remounting CouncilChat
              // rehydrates messages from GET /conversation; the
              // outgoing composer draft is preserved in the draft
              // store under its own key (navigation correction §3).
              setChatSeat(seat)
            }}
            refreshKey={inviteRefreshKey}
            onRowDisappeared={dispatchInvitationsChanged}
          />
          <CouncilChat
            key={`${chatId}:${chatSeat ?? ''}`}
            environment="sheet"
            conversationId={chatId}
            initialArchetypeId={chatSeat}
            displayName={displayName}
            onTurnSent={() => setInviteRefreshKey((k) => k + 1)}
          />
        </>
      )}
    </div>
  )
}
