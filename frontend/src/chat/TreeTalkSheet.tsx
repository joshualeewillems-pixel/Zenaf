import { useCallback, useEffect, useRef, useState } from 'react'
import { apiBase } from '../apiBase'
import { voiceColor } from '../council/colors'
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
 * - "+" is always visible and is the only way a new thread starts;
 *   the user — never the system — decides. Tapping it on a
 *   conversation with messages first asks its disposition —
 *   "Archive for data" / "Delete all system references" /
 *   "Keep open" — and archive/keep-open choose the conversation's
 *   logo (symbol + color, its wordless title) in the same step.
 *   The seat's strip beside "+" IS the seat's conversations —
 *   open and kept past in one continuum, the open one marked, the
 *   first meeting pinned at the head. There is no History surface:
 *   it was superfluous in kind (founder, 2026-11-12).
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
 *  conversation. It is NOT a participation or authorization record.
 *  `archived` / `symbol` / `color` are the conversation row's
 *  lifecycle fields (founder, 2026-11-12): the archived flag and
 *  the save-as identity written by the "+" disposition flow. */
export type TalkListItem = {
  conversation_id: string
  kind: string | null
  created_at: string | null
  updated_at: string | null
  message_count: number
  seats: string[]
  last_message_at: string | null
  last_message_preview: string | null
  archived?: boolean
  symbol?: number | null
  color?: string | null
}

/** A list entry's effective identity: the server's save-as identity
 *  wins; the localStorage identity (talkIdentity) is the fallback
 *  for conversations that predate the server field. */
export function effectiveIdentity(
  item: Pick<TalkListItem, 'symbol' | 'color'>,
  local: TalkIdentity | undefined,
): TalkIdentity {
  return {
    color: item.color ?? local?.color ?? null,
    symbol: item.symbol ?? local?.symbol ?? null,
  }
}

/** Meeting entries in the list (founder, 2026-11-12: meetings join
 *  the chat list). A meeting conversation id is `meeting-{seat}-{n}`
 *  by construction (the backend's conversation_id_for), disjoint from
 *  `talk-` ids; `kind` says the same thing ('meeting') when the
 *  conversation row exists. The id is the discriminator because it
 *  is definitional, not data-dependent. */
export function isMeetingListItem(t: TalkListItem): boolean {
  return t.conversation_id.startsWith('meeting-')
}

/** The seat a meeting list entry belongs to, parsed from its id.
 *  Seat ids are single lowercase tokens, so the parse is exact.
 *  Null for non-meeting items and malformed ids. */
export function meetingSeatOf(t: TalkListItem): string | null {
  const m = /^meeting-([a-z]+)-\d+$/.exec(t.conversation_id)
  return m ? m[1] : null
}

/** `talk-` + 32 lowercase hex chars (37 total, within the route's
 *  64-char max). Disjoint from `skeleton`, `meeting-*`, and `stone:*`
 *  by construction. */
export function newTalkId(): string {  // Loosely typed on purpose: feature-detect at runtime instead of
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
 * conversations are identified by color + symbol, never by a
 * generated text title. The glyph itself takes the color: the
 * silver-on-black symbol art is multiplied over the identity
 * color, so the white-enough glyph renders IN the color (the
 * founder's multiply-mask direction) instead of sitting inside a
 * colored ring. No color → the art renders as-is; no symbol → a
 * plain disc in the color (or a dashed unset circle).
 */
function IdentityBadge({ identity, size = 30 }: { identity: TalkIdentity; size?: number }) {
  const url = symbolUrl(identity.symbol)
  if (!url) {
    return (
      <span
        aria-hidden="true"
        className="inline-flex shrink-0 items-center justify-center rounded-full"
        style={{
          width: size,
          height: size,
          background: identity.color ?? 'rgba(245,240,232,.06)',
          border: identity.color
            ? `2px solid ${identity.color}`
            : '1px dashed rgba(245,240,232,.35)',
        }}
      >
        {!identity.color && <span className="text-sm leading-none text-stone-400">+</span>}
      </span>
    )
  }
  return (
    <span
      aria-hidden="true"
      className="inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full"
      style={{
        width: size,
        height: size,
        background: identity.color ?? '#000',
        border: '1px solid rgba(245,240,232,.25)',
      }}
    >
      <img
        src={url}
        alt=""
        style={{
          width: '100%',
          height: '100%',
          objectFit: 'cover',
          mixBlendMode: identity.color ? 'multiply' : undefined,
        }}
      />
    </span>
  )
}

/**
 * The save-as identity picker (founder, 2026-11-12): palette +
 * symbol grid over a DRAFT identity. Symbols preview tinted with
 * the draft color — pick the color first and the whole grid shows
 * what each emblem would look like in it. Used only by the "+"
 * disposition flow: a conversation's logo is chosen at the moment
 * it is saved (archive / keep open), nowhere else.
 */
function SaveAsPicker({
  color,
  symbol,
  onColor,
  onSymbol,
}: {
  color: string
  symbol: number
  onColor: (c: string) => void
  onSymbol: (n: number) => void
}) {
  return (
    <>
      <div className="flex flex-wrap gap-2" role="group" aria-label="Color">
        {TALK_PALETTE.map((c) => {
          const selected = color === c
          return (
            <button
              key={c}
              type="button"
              aria-label={`Color ${c}`}
              aria-pressed={selected}
              onClick={() => onColor(c)}
              className="h-8 w-8 rounded-full"
              style={{
                background: c,
                outline: selected ? '2px solid #f5f0e8' : '1px solid rgba(245,240,232,.25)',
                outlineOffset: 2,
              }}
            />
          )
        })}
      </div>
      <div className="grid grid-cols-6 gap-2" role="group" aria-label="Symbol">
        {Array.from({ length: SYMBOL_COUNT }, (_, i) => i + 1).map((n) => {
          const selected = symbol === n
          return (
            <button
              key={n}
              type="button"
              aria-label={`Symbol ${n}`}
              aria-pressed={selected}
              onClick={() => onSymbol(n)}
              className="aspect-square overflow-hidden rounded-full"
              style={{
                background: color,
                outline: selected ? '2px solid #f5f0e8' : '1px solid rgba(245,240,232,.25)',
                outlineOffset: 2,
              }}
            >
              <img
                src={symbolUrl(n) ?? ''}
                alt=""
                className="h-full w-full object-cover"
                style={{ mixBlendMode: 'multiply' }}
              />
            </button>
          )
        })}
      </div>
    </>
  )
}

export default function TreeTalkSheet({
  seatKey,
  displayName,
  conversationOverride,
  onChatIdChange,
  onOpenMeeting,
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
  /** Opens the seat's first-meeting overlay (the Tree's MeetingView)
      when a meeting entry in a list is tapped (founder, 2026-11-12).
      A meeting is never opened as a talk thread. When absent (a
      mount outside the Tree), meeting rows fall back to opening as
      a conversation, as every row did before. */
  onOpenMeeting?: (seat: string) => void
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
  /** The seat's conversation strip (the rail): this seat's
      non-archived talks in one continuum — open and kept past
      together, newest first — plus the seat's first meeting, which
      the render pins at the head. Same GET /conversation/list the
      seat lookup already uses, seat-scoped, opting into meetings;
      archived conversations are excluded by the endpoint's default.
      The fetch bound (100, the route's max) is an implementation
      detail, not a product cap. Zero-message conversations never
      appear — the endpoint only lists conversations with at least
      one message. The seat LOOKUP below never opts into meetings —
      it resolves talks to resume, and a meeting must not become
      the resumed thread. */
  const [rail, setRail] = useState<TalkListItem[] | null>(null)
  const [railNonce, setRailNonce] = useState(0)
  /** The seat whose strip is shown: the sheet's seat; for a
      conversation opened from the you-node list (no sheet seat),
      the open conversation's first spoken seat. Null → no strip. */
  const openItem = talks.find((t) => t.conversation_id === chatId)
  const railSeat = chatSeat ?? openItem?.seats[0] ?? null
  useEffect(() => {
    if (mode !== 'chat' || !railSeat) {
      setRail(null)
      return
    }
    let cancelled = false
    fetch(
      `${base}/conversation/list?seat=${encodeURIComponent(railSeat)}&limit=100&include_meetings=true`,
      { credentials: 'include' },
    )
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return (await r.json()) as { conversations?: TalkListItem[] }
      })
      .then((data) => {
        if (cancelled) return
        setRail(Array.isArray(data.conversations) ? data.conversations : [])
      })
      .catch(() => {
        // The strip is a convenience surface: on failure it is
        // simply absent — the conversation on screen is unaffected
        // and "+" still works (its count check hydrates directly).
        if (!cancelled) setRail(null)
      })
    return () => {
      cancelled = true
    }
  }, [base, mode, railSeat, railNonce, inviteRefreshKey])
  /** The "+" disposition flow (founder, 2026-11-12): choose a
      disposition → (archive / keep open) the save-as logo step, or
      (delete) one explicit confirmation. Cancel at any step writes
      nothing and stays in the current conversation. */
  type PlusFlow =
    | { step: 'choose' }
    | { step: 'saveas'; action: 'archive' | 'keep_open'; color: string; symbol: number }
    | { step: 'confirmDelete' }
  const [plusFlow, setPlusFlow] = useState<PlusFlow | null>(null)
  const [plusBusy, setPlusBusy] = useState(false)
  const [plusError, setPlusError] = useState(false)
  /** Archived talks for the you-node archive section (rediscovery,
      not a queue): fetched in list mode with include_archived and
      partitioned on the entries' archived flag. */
  const [archivedTalks, setArchivedTalks] = useState<TalkListItem[]>([])
  useEffect(() => {
    if (mode !== 'list') return
    let cancelled = false
    fetch(`${base}/conversation/list?include_meetings=true&include_archived=true&limit=100`, {
      credentials: 'include',
    })
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return (await r.json()) as { conversations?: TalkListItem[] }
      })
      .then((data) => {
        if (cancelled) return
        const list = Array.isArray(data.conversations) ? data.conversations : []
        setArchivedTalks(list.filter((t) => t.archived))
      })
      .catch(() => {
        if (!cancelled) setArchivedTalks([])
      })
    return () => {
      cancelled = true
    }
  }, [base, mode, nonce])
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
      // It opts into meetings: a seat's first meeting is listed here
      // and routes to the meeting overlay when tapped.
      fetch(`${base}/conversation/list?include_meetings=true`, { credentials: 'include' })
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
    fetch(`${base}/conversation/list?include_meetings=true`, { credentials: 'include' })
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
    setPlusFlow(null)
    setPlusError(false)
    setMode('chat')
  }, [])

  /** "+" tapped. A conversation with no messages has nothing to
      save: reset to a fresh thread immediately, no prompt. With
      messages, ask the disposition first. The count is the rail
      entry's when the strip has the conversation, else the hydrate
      endpoint's total. An unreadable count still prompts — losing
      the save-as moment is worse than prompting an empty thread. */
  const openPlusFlow = useCallback(async () => {
    if (!chatId || plusFlow) return
    setPlusError(false)
    const railItem = (rail ?? []).find((t) => t.conversation_id === chatId)
    let total: number | null = railItem ? railItem.message_count : null
    if (total === null) {
      try {
        const r = await fetch(
          `${base}/conversation?conversation_id=${encodeURIComponent(chatId)}&limit=1`,
          { credentials: 'include' },
        )
        if (r.ok) {
          const data = (await r.json()) as { total?: unknown }
          total = typeof data.total === 'number' ? data.total : null
        }
      } catch {
        total = null
      }
    }
    if (total === 0) {
      startNew()
      return
    }
    setPlusFlow({ step: 'choose' })
  }, [base, chatId, plusFlow, rail, startNew])

  /** Enter the save-as step for archive / keep open: the draft
      identity preselects the conversation's current identity, else
      the seat's color + the first symbol — one tap accepts it. */
  const beginSaveAs = (action: 'archive' | 'keep_open') => {
    if (!chatId) return
    const item =
      (rail ?? []).find((t) => t.conversation_id === chatId) ??
      talks.find((t) => t.conversation_id === chatId)
    const eff = item
      ? effectiveIdentity(item, identities[chatId])
      : identities[chatId] ?? { color: null, symbol: null }
    setPlusError(false)
    setPlusFlow({
      step: 'saveas',
      action,
      color: eff.color ?? voiceColor(railSeat ?? ''),
      symbol: eff.symbol ?? 1,
    })
  }

  const submitSaveAs = async () => {
    if (!chatId || plusFlow?.step !== 'saveas' || plusBusy) return
    setPlusBusy(true)
    setPlusError(false)
    try {
      const r = await fetch(`${base}/conversation/disposition`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          conversation_id: chatId,
          action: plusFlow.action,
          symbol: plusFlow.symbol,
          color: plusFlow.color,
        }),
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      // Mirror into the local identity store so surfaces still
      // reading it (fallbacks for older conversations) agree.
      setIdentity(chatId, { color: plusFlow.color, symbol: plusFlow.symbol })
      setPlusFlow(null)
      setRailNonce((n) => n + 1)
      startNew()
    } catch {
      setPlusError(true)
    } finally {
      setPlusBusy(false)
    }
  }

  const submitDelete = async () => {
    if (!chatId || plusFlow?.step !== 'confirmDelete' || plusBusy) return
    setPlusBusy(true)
    setPlusError(false)
    try {
      const r = await fetch(
        `${base}/conversation/${encodeURIComponent(chatId)}`,
        { method: 'DELETE', credentials: 'include' },
      )
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      clearIdentity(chatId)
      setPlusFlow(null)
      setRailNonce((n) => n + 1)
      startNew()
    } catch {
      setPlusError(true)
    } finally {
      setPlusBusy(false)
    }
  }

  /** Routes a meeting list entry to the Tree's meeting overlay and
      reports whether it did. Talks (and meetings on a mount without
      a meeting handler) return false and take the normal chat-open
      path in the caller. A meeting is never opened as a talk thread
      when the handler exists. */
  const routeMeeting = (t: TalkListItem): boolean => {
    const seat = meetingSeatOf(t)
    if (seat && onOpenMeeting) {
      onOpenMeeting(seat)
      return true
    }
    return false
  }

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
    const renderRow = (t: TalkListItem) => {
      const meetingSeat = meetingSeatOf(t)
      const eff = effectiveIdentity(t, identities[t.conversation_id])
      const badgeIdentity: TalkIdentity =
        eff.color || eff.symbol
          ? eff
          : { color: t.seats[0] ? voiceColor(t.seats[0]) : null, symbol: null }
      return (
        <button
          key={t.conversation_id}
          type="button"
          onClick={() => {
            if (routeMeeting(t)) return
            setChatSeat(null)
            setFromList(true)
            setChatId(t.conversation_id)
            setMode('chat')
          }}
          className="flex items-center gap-3 text-left rounded-2xl border border-stone-700/60 bg-stone-900/70 px-3 py-2"
        >
          <IdentityBadge identity={badgeIdentity} />
          <span className="min-w-0 flex-1">
            <span className="block text-sm text-stone-200">
              {meetingSeat
                ? `${names[meetingSeat] ?? meetingSeat} · First meeting`
                : t.seats.map((s) => names[s] ?? s).join(', ') || 'Conversation'}
            </span>
            {t.last_message_preview && (
              <span className="block text-xs text-stone-400 truncate">
                {t.last_message_preview}
              </span>
            )}
            <span className="block text-[11px] text-stone-500">
              {t.archived ? 'Archived · ' : ''}
              {t.message_count} messages
              {formatWhen(t.last_message_at) ? ` · ${formatWhen(t.last_message_at)}` : ''}
            </span>
          </span>
        </button>
      )
    }
    return (
      <div className="flex flex-col gap-3">
        {!talksFetched ? (
          <p className="text-sm text-stone-400 px-1 py-2">Loading conversation…</p>
        ) : talks.length === 0 ? (
          <p className="text-sm text-stone-400 px-1 py-2">
            No conversations yet — start one below.
          </p>
        ) : (
          <div className="flex flex-col gap-2">{talks.map(renderRow)}</div>
        )}
        <button
          type="button"
          onClick={() => setMode('pick')}
          className="self-start min-h-[44px] px-4 rounded-full bg-amber-600 text-amber-50 text-sm font-semibold"
        >
          Start new
        </button>
        {archivedTalks.length > 0 && (
          <div className="flex flex-col gap-2">
            <p className="px-1 text-[11px] font-semibold uppercase tracking-wider text-stone-500">
              Archived
            </p>
            {archivedTalks.map(renderRow)}
          </div>
        )}
      </div>
    )
  }

  // mode === 'chat'
  // The header row is "+" and the seat's conversation strip — the
  // strip IS the seat's conversations (open and kept past in one
  // continuum), so the open conversation is IN it, marked. The
  // seat's first meeting is pinned at the head and routes to the
  // meeting overlay; every other badge populates its conversation
  // in place. Badges are identified by color + symbol, never by a
  // text title. Switching badges mid-flow cancels the flow —
  // nothing is written until a disposition is confirmed.
  const railItems = rail ?? []
  const firstMeetingItem =
    railItems.find((t) => t.conversation_id === `meeting-${railSeat}-1`) ?? null
  const railOrdered = firstMeetingItem
    ? [firstMeetingItem, ...railItems.filter((t) => t !== firstMeetingItem)]
    : railItems
  const railBadgeIdentity = (t: TalkListItem): TalkIdentity => {
    if (isMeetingListItem(t)) {
      return { color: voiceColor(railSeat ?? ''), symbol: null }
    }
    const eff = effectiveIdentity(t, identities[t.conversation_id])
    return eff.color || eff.symbol
      ? eff
      : { color: voiceColor(railSeat ?? ''), symbol: null }
  }
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => void openPlusFlow()}
          aria-label="New conversation"
          title="New conversation"
          className="flex min-h-[44px] min-w-[44px] shrink-0 items-center justify-center rounded-full border border-stone-700 text-lg leading-none text-stone-200"
        >
          +
        </button>
        {railOrdered.length > 0 && (
          <div
            className="flex flex-1 items-center gap-2 overflow-x-auto py-1"
            role="group"
            aria-label="Conversations with this seat"
          >
            {railOrdered.map((t) => {
              const open = t.conversation_id === chatId
              const meeting = isMeetingListItem(t)
              return (
                <button
                  key={t.conversation_id}
                  type="button"
                  onClick={() => {
                    setPlusFlow(null)
                    if (routeMeeting(t)) return
                    setChatId(t.conversation_id)
                    setMode('chat')
                  }}
                  aria-label={
                    meeting
                      ? 'First meeting'
                      : t.last_message_preview ?? 'Conversation'
                  }
                  aria-current={open ? 'true' : undefined}
                  title={
                    meeting
                      ? 'First meeting'
                      : t.last_message_preview ?? 'Conversation'
                  }
                  className="flex min-h-[44px] min-w-[44px] shrink-0 items-center justify-center rounded-full"
                  style={
                    open
                      ? { outline: '2px solid #f5f0e8', outlineOffset: 2 }
                      : undefined
                  }
                >
                  <IdentityBadge identity={railBadgeIdentity(t)} size={34} />
                </button>
              )
            })}
          </div>
        )}
        {fromList && (
          <button
            type="button"
            onClick={() => setMode('list')}
            className="min-h-[44px] shrink-0 px-4 rounded-full border border-stone-700 text-sm text-stone-400"
          >
            ← Conversations
          </button>
        )}
      </div>
      {plusFlow?.step === 'choose' && (
        <div className="flex flex-col gap-2 rounded-2xl border border-stone-700/60 bg-stone-900/70 px-3 py-3">
          <p className="text-sm text-stone-300">
            Save this conversation and start a new one?
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => beginSaveAs('archive')}
              className="min-h-[44px] px-4 rounded-full border border-stone-700 text-sm text-stone-200"
            >
              Archive for data
            </button>
            <button
              type="button"
              onClick={() => beginSaveAs('keep_open')}
              className="min-h-[44px] px-4 rounded-full border border-stone-700 text-sm text-stone-200"
            >
              Keep open
            </button>
            <button
              type="button"
              onClick={() => {
                setPlusError(false)
                setPlusFlow({ step: 'confirmDelete' })
              }}
              className="min-h-[44px] px-4 rounded-full border border-red-900/70 text-sm text-red-300"
            >
              Delete all system references
            </button>
            <button
              type="button"
              onClick={() => setPlusFlow(null)}
              className="min-h-[44px] px-4 rounded-full text-sm text-stone-400"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
      {plusFlow?.step === 'confirmDelete' && (
        <div className="flex flex-col gap-2 rounded-2xl border border-red-900/60 bg-red-950/30 px-3 py-3">
          <p className="text-sm text-red-200">
            Delete this conversation and all system references to it? This cannot
            be undone.
          </p>
          {plusError && (
            <p className="text-sm text-red-300">Couldn’t delete — try again.</p>
          )}
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void submitDelete()}
              disabled={plusBusy}
              className="min-h-[44px] px-4 rounded-full bg-red-900/70 text-sm font-semibold text-red-50"
            >
              Delete all system references
            </button>
            <button
              type="button"
              onClick={() => setPlusFlow(null)}
              className="min-h-[44px] px-4 rounded-full text-sm text-stone-300"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
      {plusFlow?.step === 'saveas' && (
        <div className="flex flex-col gap-3 rounded-2xl border border-stone-700/60 bg-stone-900/70 px-3 py-3">
          <div className="flex items-center gap-3">
            <IdentityBadge
              identity={{ color: plusFlow.color, symbol: plusFlow.symbol }}
              size={40}
            />
            <span className="text-sm text-stone-300">
              {plusFlow.action === 'archive' ? 'Archive for data' : 'Keep open'} —
              this logo is the conversation’s title. No words needed.
            </span>
          </div>
          <SaveAsPicker
            color={plusFlow.color}
            symbol={plusFlow.symbol}
            onColor={(c) =>
              setPlusFlow((f) => (f?.step === 'saveas' ? { ...f, color: c } : f))
            }
            onSymbol={(n) =>
              setPlusFlow((f) => (f?.step === 'saveas' ? { ...f, symbol: n } : f))
            }
          />
          {plusError && (
            <p className="text-sm text-red-300">Couldn’t save — try again.</p>
          )}
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void submitSaveAs()}
              disabled={plusBusy}
              className="min-h-[44px] px-4 rounded-full bg-amber-600 text-sm font-semibold text-amber-50"
            >
              Save &amp; start new
            </button>
            <button
              type="button"
              onClick={() => setPlusFlow({ step: 'choose' })}
              className="min-h-[44px] px-4 rounded-full border border-stone-700 text-sm text-stone-400"
            >
              Back
            </button>
            <button
              type="button"
              onClick={() => setPlusFlow(null)}
              className="min-h-[44px] px-4 rounded-full text-sm text-stone-400"
            >
              Cancel
            </button>
          </div>
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
