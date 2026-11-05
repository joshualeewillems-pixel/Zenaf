import { useCallback, useEffect, useRef, useState } from 'react'
import { apiBase } from '../apiBase'
import { WeaveText, voiceColor } from '../components/VoiceWeave'
import SeatChips, { SEAT_ORDER, useSeatMeta } from './SeatChips'
import TaskProposalCards from './TaskProposalCards'
import { stripTaskProposalBlocks } from './taskProposals'
import VoiceFeedback from './VoiceFeedback'

/**
 * One message in the persistent conversation. Voice turns carry the
 * responding seat's attribution so the thread stays readable as seats
 * change — history is shared across the whole conversation, never
 * partitioned per seat.
 */
export type ConversationMessage = {
  role: 'user' | 'voice'
  content: string
  voiceId?: string | null
  voiceName?: string
  voiceColor?: string
  /** Stable response reference for feedback: the server message id on
   *  the store path, a session-scoped `local-` ref otherwise. Absent for
   *  seed/initial messages and failure notices — those get no widget. */
  messageId?: string | null
}

/** Server message row → thread message. Shared by hydration and
 *  load-earlier so both paths map identically. */
function mapServerMessages(
  rows: unknown,
  names: Record<string, string>,
): ConversationMessage[] {
  const mapped: ConversationMessage[] = []
  if (!Array.isArray(rows)) return mapped
  for (const m of rows) {
    if (!m || typeof m !== 'object') continue
    const body = String((m as Record<string, unknown>).body ?? '').trim()
    if (!body) continue
    const role = (m as Record<string, unknown>).role === 'user' ? 'user' : 'voice'
    const aid =
      typeof (m as Record<string, unknown>).archetype_id === 'string'
        ? ((m as Record<string, unknown>).archetype_id as string)
        : null
    mapped.push({
      role,
      content: body,
      messageId:
        typeof (m as Record<string, unknown>).id === 'string'
          ? ((m as Record<string, unknown>).id as string)
          : null,
      voiceId: role === 'voice' ? aid : null,
      voiceName: role === 'voice' ? names[aid ?? ''] ?? aid ?? undefined : undefined,
      voiceColor: role === 'voice' && aid ? voiceColor(aid) : undefined,
    })
  }
  return mapped
}

/** Session-scoped response ref for threads that live in component state
 *  only (no server message id exists there). The `local-` prefix never
 *  collides with server ids, which are bare hex. */
function newLocalRef(): string {
  const rand =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2)}`
  return `local-${rand}`
}

/**
 * The unified 1:1 conversation — one voice at a time, everywhere.
 *
 * Conversation model: ONE persistent conversation per user (the skeleton)
 * with persona branches. Tapping a seat chip branches the ongoing
 * conversation to that seat; the message list is never cleared on switch.
 * The 7+ persona threads the system maintains in the background are not
 * overt separate chats the user manages — this component shows the one
 * thread, with per-message voice attribution.
 *
 * Persistence: when `conversationId` is present, the thread hydrates from
 * GET /conversation and each turn persists via POST /conversation/turn
 * (carrying the sheet's live `context`). Without it, the thread lives in
 * component state and sends go to POST /voice/chat with client history.
 * Tree Talk (Slice A) always passes a `talk-` conversation id resolved
 * through GET /conversation/list, so Tree threads are server-backed;
 * the workspace console still mounts without one and keeps client history.
 *
 * - Sheet seat tab → pre-selected seat (character header rendered above by
 *   the sheet, from PR #147's merged Talk+Character tab).
 * - Sheet you-node → chips with no pre-selection: an invitation to pick.
 * - Workspace (Foundation console) → adds the trained/base version toggle.
 *
 * Ask the council (Joshua, 2026-10-23 — supersedes the 1:1-only note
 * that stood here): having two chats was confusing, so the workspace
 * console's two conversational powers live here now — the version
 * switch (above) and multi-seat fan-out: the "Ask the council" toggle
 * sends one message to every seat through the same per-seat turn path,
 * and each reply lands in this one thread under its seat's name. The
 * workspace console remains a deliberation console (folder runs,
 * synthesis, recorded insights) — talking lives here.
 */
export default function CouncilChat({
  environment,
  initialArchetypeId = null,
  displayName,
  conversationId = null,
  initialMessages,
  context = null,
  prefill = null,
  seedMessages = null,
  onTurnSent = () => {},
}: {
  /** 'sheet' = compact, with the Zenaf/You side switch. 'workspace' = roomier + version toggle. */
  environment: 'sheet' | 'workspace'
  /** Pre-selected seat (seat-branch sheets). Omit → chips, no selection. */
  initialArchetypeId?: string | null
  /** Seat fellowship name override for the composer placeholder. */
  displayName?: string
  /** Backend conversation-store key. When present, the thread hydrates from
   *  GET /conversation and turns persist via POST /conversation/turn. */
  conversationId?: string | null
  /** Hydration seam: messages a future backend store hands back. */
  initialMessages?: ConversationMessage[]
  /** Skeleton-store live context carried on every turn (sheet + entity in
   *  focus). Only sent when conversationId is present. */
  context?: Record<string, unknown> | null
  /** External draft injection: when nonce changes, the composer takes this
   *  text. Never sends on its own. */
  prefill?: { text: string; nonce: number } | null
  /** Messages folded into the thread when the store thread is empty (e.g.
   *  open questions). Client-side only; the store stays the source of truth
   *  once it has turns. */
  seedMessages?: ConversationMessage[] | null
  /** Capability C visible-UX slice: invoked on SUCCESS arms of the send
   *  handler only (council-results and single-seat), after the reply
   *  lands — never on 'auth', never in the catch arm, never on a
   *  target-mismatch early return. The sheet uses it to refetch the
   *  invitation list, observing a join by the entry disappearing. */
  onTurnSent?: () => void
}) {
  const base = apiBase()
  const { names } = useSeatMeta()

  // The persistent thread — initialized once from the hydration seam.
  // Switching seats never touches this list.
  const [messages, setMessages] = useState<ConversationMessage[]>(initialMessages ?? [])
  const [activeId, setActiveId] = useState<string | null>(initialArchetypeId ?? null)
  /** Ask-the-council fan-out: the next send goes to every seat at once. */
  const [councilMode, setCouncilMode] = useState(false)
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  /** Demo's "Respond / Question me" toggle, brought to the authenticated chat. */
  const [questionMode, setQuestionMode] = useState(false)
  /** Workspace-only trained/base version toggle. Sheets get the Zenaf/You side switch below. */
  const [voiceMode, setVoiceMode] = useState<'trained' | 'base'>('trained')
  /**
   * Sheet-only Zenaf/You switch (per seat): Zenaf = the canonical character
   * (base voice), You = the user's trained echo of the seat (trained voice).
   * Either side can be talked to at any time — the switch selects which
   * voice renders the reply; the You *profile* (name, recognition) is what
   * keystone 4 unlocks, not the talking. Defaults to You, matching the
   * sheet's historical trained-only behavior.
   */
  const [side, setSide] = useState<'you' | 'zenaf'>('you')
  const chatMode: 'trained' | 'base' =
    environment === 'workspace' ? voiceMode : side === 'you' ? 'trained' : 'base'
  const [signedOut, setSignedOut] = useState(false)
  const chatEndRef = useRef<HTMLDivElement | null>(null)

  // The store key rides along for the next build; today it only identifies
  // the thread for future hydration (call sites key on it when it exists).
  const conversationKey = conversationId ?? 'local'

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages.length, loading])

  // Skeleton-store hydration: when a conversationId is present, the thread
  // is the server's. Hydrate once per key; an empty store thread falls back
  // to seedMessages (folded-in open questions), then to initialMessages.
  // Seeds apply only while the user hasn't written yet — never clobbering.
  //
  // Send gating (Slice A, correction C2): send is disabled while
  // hydrating, enabled on success or on a confirmed empty thread, and
  // disabled on hydration failure until a SUCCESSFUL retry — never
  // merely because the error was acknowledged. A failed hydration must
  // never present as an empty thread, and a late response for a
  // previous conversation must never overwrite the current one
  // (request sequence + cleanup invalidation).
  const namesRef = useRef(names)
  namesRef.current = names
  const conversationIdRef = useRef(conversationId)
  conversationIdRef.current = conversationId
  const hydrateSeqRef = useRef(0)
  const sendSeqRef = useRef(0)
  const [storeEmpty, setStoreEmpty] = useState<boolean | null>(null)
  const [hydrating, setHydrating] = useState(false)
  const [hydrateError, setHydrateError] = useState(false)
  const [hydrateNonce, setHydrateNonce] = useState(0)
  const [totalMessages, setTotalMessages] = useState<number | null>(null)
  const [loadingEarlier, setLoadingEarlier] = useState(false)
  const [loadEarlierError, setLoadEarlierError] = useState(false)
  useEffect(() => {
    if (!conversationId) return
    const seq = ++hydrateSeqRef.current
    let cancelled = false
    // A new conversation starts from its own server thread, never from
    // the previous conversation's displayed messages.
    setMessages([])
    setStoreEmpty(null)
    setHydrateError(false)
    setSignedOut(false)
    setHydrating(true)
    setTotalMessages(null)
    fetch(
      `${base}/conversation?conversation_id=${encodeURIComponent(conversationId)}&limit=200`,
      { credentials: 'include' },
    )
      .then(async (r) => {
        if (r.status === 401) return { auth: true as const }
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return (await r.json()) as Record<string, unknown>
      })
      .then((data) => {
        if (cancelled || hydrateSeqRef.current !== seq) return
        if ((data as { auth?: boolean }).auth) {
          setSignedOut(true)
          setHydrateError(true)
          setHydrating(false)
          return
        }
        const mapped = mapServerMessages(
          (data as { messages?: unknown }).messages,
          namesRef.current,
        )
        if (mapped.length > 0) {
          setMessages(mapped)
          setStoreEmpty(false)
        } else {
          setStoreEmpty(true)
        }
        setTotalMessages(
          typeof (data as { total?: unknown }).total === 'number'
            ? ((data as { total: number }).total as number)
            : null,
        )
        setHydrating(false)
      })
      .catch(() => {
        if (cancelled || hydrateSeqRef.current !== seq) return
        // Failure is NOT an empty thread: banner + retry, send stays
        // disabled until a retry succeeds.
        setHydrateError(true)
        setHydrating(false)
      })
    return () => {
      cancelled = true
    }
  }, [conversationId, base, hydrateNonce])

  useEffect(() => {
    if (!conversationId || storeEmpty !== true) return
    if (!seedMessages || seedMessages.length === 0) return
    if (messages.some((m) => m.role === 'user')) return
    setMessages((prev) => (prev.length === 0 ? seedMessages : prev))
  }, [conversationId, storeEmpty, seedMessages, messages])

  /** Load earlier messages via the stable (created_at, id) cursor:
   *  the oldest displayed server message. New arrivals can never
   *  shift, duplicate, or skip rows in earlier pages; merges dedupe
   *  by server id as a second guard. */
  const loadEarlier = useCallback(async () => {
    if (!conversationId || loadingEarlier) return
    const oldest = messages.find((m) => m.messageId && !m.messageId.startsWith('local-'))
    if (!oldest?.messageId) return
    setLoadingEarlier(true)
    setLoadEarlierError(false)
    try {
      const r = await fetch(
        `${base}/conversation?conversation_id=${encodeURIComponent(conversationId)}&limit=200&before=${encodeURIComponent(oldest.messageId)}`,
        { credentials: 'include' },
      )
      if (r.status === 401) {
        setSignedOut(true)
        return
      }
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const data = (await r.json()) as Record<string, unknown>
      const mapped = mapServerMessages(data.messages, namesRef.current)
      const seen = new Set(messages.map((m) => m.messageId).filter(Boolean))
      const fresh = mapped.filter((m) => !m.messageId || !seen.has(m.messageId))
      setMessages((prev) => [...fresh, ...prev])
      if (typeof data.total === 'number') setTotalMessages(data.total)
    } catch {
      setLoadEarlierError(true)
    } finally {
      setLoadingEarlier(false)
    }
  }, [conversationId, messages, loadingEarlier, base])
  const prefillNonce = prefill?.nonce ?? 0
  useEffect(() => {
    if (prefill && prefillNonce > 0) setInput(prefill.text)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefillNonce])

  const activeName =
    displayName ?? (activeId ? names[activeId] ?? activeId : null) ?? 'a voice'

  /** One seat's turn through whichever path this mount uses (skeleton
   *  store when conversationId is present, client-history otherwise).
   *  Returns 'auth' on 401 so callers can settle quietly; throws on
   *  other failures. */
  const askSeat = useCallback(
    async (seatId: string, text: string): Promise<ConversationMessage | 'auth'> => {
      const useStore = Boolean(conversationId)
      const r = await fetch(useStore ? `${base}/conversation/turn` : `${base}/voice/chat`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(
          useStore
            ? {
                conversation_id: conversationId,
                archetype_id: seatId,
                message: text,
                mode: chatMode,
                question: questionMode,
                ...(context ? { context } : {}),
              }
            : {
                archetype_id: seatId,
                message: text,
                history: messages.map((m) => ({ role: m.role, content: m.content })),
                mode: chatMode,
                question: questionMode,
              },
        ),
      })
      if (r.status === 401) return 'auth'
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const data = await r.json()
      // The turn echoes its conversation_id: a reply for another thread
      // must never land in this one.
      if (useStore && data.conversation_id && data.conversation_id !== conversationId) {
        throw new Error('conversation mismatch')
      }
      return {
        role: 'voice',
        content: data.reply,
        // Store path: the server's message id. Local path: no server id
        // exists, so mint a session-scoped ref at receipt time.
        messageId: useStore ? (data.message_id ?? null) : newLocalRef(),
        voiceId: data.archetype_id ?? seatId,
        voiceName:
          data.display_name ?? (seatId === activeId ? activeName : names[seatId] ?? seatId),
        voiceColor: data.voice_color ?? undefined,
      }
    },
    [base, conversationId, context, chatMode, questionMode, messages, names, activeId, activeName],
  )

  const send = useCallback(async () => {
    const text = input.trim()
    if (loading) return
    if (!councilMode && !activeId) return
    if (!text && !questionMode) return
    // The Enter key path bypasses the disabled button: enforce the
    // hydration gate here too — never send into a thread whose
    // history hasn't loaded.
    if (conversationId && (hydrating || hydrateError)) return
    // A send must never target a stale conversation: capture the
    // thread this send belongs to, and only append its results while
    // the user is still on it.
    const targetId = conversationIdRef.current
    const seq = ++sendSeqRef.current
    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setInput('')
    setLoading(true)
    setSignedOut(false)
    try {
      if (councilMode) {
        // Fan out to every seat at once. A seat that fails gets a
        // quiet, honestly-labelled bubble — the others still answer.
        const results = await Promise.all(
          SEAT_ORDER.map(async (seatId) => {
            try {
              return await askSeat(seatId, text)
            } catch {
              return {
                role: 'voice' as const,
                content: "I couldn't reach my voice just now — try again in a moment.",
                voiceId: seatId,
                voiceName: names[seatId] ?? seatId,
              }
            }
          }),
        )
        if (conversationIdRef.current !== targetId) return
        if (results.every((x) => x === 'auth')) {
          setSignedOut(true)
          setMessages((prev) => prev.slice(0, -1))
          return
        }
        setMessages((prev) => [
          ...prev,
          ...results.filter((x): x is ConversationMessage => x !== 'auth'),
        ])
        onTurnSent()
      } else if (activeId) {
        const reply = await askSeat(activeId, text)
        if (conversationIdRef.current !== targetId) return
        if (reply === 'auth') {
          setSignedOut(true)
          setMessages((prev) => prev.slice(0, -1))
          return
        }
        setMessages((prev) => [...prev, reply])
        onTurnSent()
      }
    } catch {
      if (conversationIdRef.current !== targetId) return
      if (!councilMode && activeId) {
        setMessages((prev) => [
          ...prev,
          {
            role: 'voice',
            content: "I couldn't reach my voice just now — try again in a moment.",
            voiceId: activeId,
            voiceName: activeName,
          },
        ])
      }
    } finally {
      if (sendSeqRef.current === seq) setLoading(false)
    }
  }, [input, loading, activeId, councilMode, askSeat, activeName, names, conversationId, hydrating, hydrateError, onTurnSent])

  const sendDisabled =
    loading ||
    (!activeId && !councilMode) ||
    (!input.trim() && !questionMode) ||
    (conversationId ? hydrating || hydrateError : false)

  return (
    <div className="flex flex-col gap-3" data-conversation={conversationKey}>
      {/* Seat switcher — tapping branches the ongoing conversation. */}
      <SeatChips
        activeId={councilMode ? null : activeId}
        onSelect={(id) => {
          setActiveId(id)
          setCouncilMode(false)
        }}
      />

      {/* Ask the council — one message, every seat answers in this thread. */}
      <div className="flex flex-wrap items-center gap-3 -mt-1">
        <button
          type="button"
          onClick={() => setCouncilMode((v) => !v)}
          aria-pressed={councilMode}
          className={`min-h-[44px] px-4 rounded-full border text-sm font-medium ${
            councilMode
              ? 'bg-amber-950/40 text-amber-300 border-amber-700/50'
              : 'border-stone-700 text-stone-400'
          }`}
        >
          Ask the council
        </button>
        {councilMode && (
          <p className="text-[11px] text-stone-500">
            One message — every seat answers here, under its own name.
          </p>
        )}
      </div>

      {environment === 'workspace' && (
        <div className="flex flex-wrap items-center gap-3">
          <div
            role="group"
            aria-label="Voice version"
            className="flex rounded-full border border-stone-700 overflow-hidden"
          >
            {(['trained', 'base'] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setVoiceMode(m)}
                aria-pressed={voiceMode === m}
                className={`min-h-[44px] px-4 text-sm font-medium ${
                  voiceMode === m ? 'bg-amber-950/40 text-amber-300' : 'text-stone-400'
                }`}
              >
                {m === 'trained' ? 'Your voices' : 'Base voices'}
              </button>
            ))}
          </div>
          <p className="text-[11px] text-stone-500">
            {voiceMode === 'trained'
              ? 'Your seats, shaped by your training.'
              : 'The aspirational stock voices — no training.'}
          </p>
        </div>
      )}

      {environment === 'sheet' && activeId && (
        <div className="flex flex-wrap items-center gap-3">
          <div
            role="group"
            aria-label="Zenaf or You — which side of this seat"
            className="flex rounded-full border border-stone-700 overflow-hidden"
          >
            {(['zenaf', 'you'] as const).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setSide(s)}
                aria-pressed={side === s}
                className={`min-h-[44px] px-4 text-sm font-medium ${
                  side === s ? 'bg-amber-950/40 text-amber-300' : 'text-stone-400'
                }`}
              >
                {s === 'zenaf' ? 'Zenaf' : 'You'}
              </button>
            ))}
          </div>
          <p className="text-[11px] text-stone-500">
            {side === 'you'
              ? 'Your echo of the seat — shaped by your approved training.'
              : 'The seat as written — the stock character, before any training.'}
          </p>
        </div>
      )}

      {/* Hydration failure is not an empty thread: banner + retry, and
       *  send stays disabled until a retry succeeds. */}
      {conversationId && hydrateError && (
        <div className="rounded-2xl border border-red-800/60 bg-red-950/30 px-3 py-2 text-sm text-red-200">
          Couldn&apos;t load this conversation — sending is disabled until it loads.
          <button
            type="button"
            onClick={() => setHydrateNonce((n) => n + 1)}
            className="ml-2 underline font-medium"
          >
            Retry
          </button>
        </div>
      )}
      {conversationId && hydrating && (
        <p className="text-xs text-stone-500">Loading conversation…</p>
      )}

      {/* The persistent thread. */}
      <div
        className={`${
          environment === 'workspace' ? 'max-h-[420px]' : 'max-h-[300px]'
        } overflow-y-auto space-y-2`}
        aria-live="polite"
      >
        {conversationId &&
          totalMessages !== null &&
          messages.length < totalMessages &&
          !hydrating && (
            <div className="px-1 py-1">
              <button
                type="button"
                onClick={loadEarlier}
                disabled={loadingEarlier}
                className="text-xs text-stone-400 underline disabled:opacity-40"
              >
                {loadingEarlier ? 'Loading earlier…' : 'Load earlier messages'}
              </button>
              {loadEarlierError && (
                <span className="text-xs text-red-300 ml-2">
                  Couldn&apos;t load earlier messages — try again.
                </span>
              )}
            </div>
          )}
        {!activeId && !councilMode && (
          <p className="text-sm text-stone-400 leading-relaxed px-1 py-2">
            Pick a voice above to begin — one conversation, tap a seat to
            branch it whenever you like. Or ask the whole council at once.
          </p>
        )}
        {messages.map((m, i) =>
          m.role === 'user' ? (
            <div key={i} className="flex justify-end">
              <div className="max-w-[88%] rounded-2xl px-3 py-2 text-sm leading-snug bg-stone-700 text-stone-100">
                {m.content || <span className="text-stone-400 italic">(asked for a question)</span>}
              </div>
            </div>
          ) : (
            <div key={i} className="flex flex-col items-start gap-1">
              <div
                className="max-w-[88%] rounded-2xl px-3 py-2 text-sm leading-snug bg-stone-800/80 border text-stone-200"
                style={
                  m.voiceColor
                    ? {
                        borderColor: `${m.voiceColor}55`,
                        borderLeftWidth: 3,
                        borderLeftColor: m.voiceColor,
                      }
                    : undefined
                }
              >
                {m.voiceName && (
                  <div
                    className="text-xs font-semibold mb-1"
                    style={m.voiceColor ? { color: m.voiceColor } : undefined}
                  >
                    {m.voiceName}
                  </div>
                )}
                {/* Store path only: fenced proposal blocks are replaced
                    by cards below; the raw JSON is never chat text.
                    Client-history path keeps the full text (no cards
                    there in this slice). */}
                <WeaveText
                  text={
                    conversationId && m.messageId && !m.messageId.startsWith('local-')
                      ? stripTaskProposalBlocks(m.content)
                      : m.content
                  }
                />
              </div>
              {conversationId && m.messageId && !m.messageId.startsWith('local-') && m.voiceId && (
                <TaskProposalCards
                  base={base}
                  conversationId={conversationId}
                  messageId={m.messageId}
                  seat={m.voiceId}
                  content={m.content}
                />
              )}
              {m.messageId && m.voiceId && (
                <div className="max-w-[88%] w-full">
                  <VoiceFeedback
                    messageId={m.messageId}
                    seat={m.voiceId}
                    conversationId={conversationKey}
                  />
                </div>
              )}
            </div>
          ),
        )}
        {loading && (
          <div className="text-xs text-stone-500">
            {councilMode ? 'asking the council…' : 'thinking…'}
          </div>
        )}
        {signedOut && (
          <div className="text-sm text-stone-400">Please sign in to talk to your voices.</div>
        )}
        <div ref={chatEndRef} />
      </div>

      {(activeId || councilMode) && (
        <div className="rounded-2xl border border-stone-700/60 bg-stone-900/70 p-2 space-y-2">
          {/* Demo's Respond / Question me toggle. */}
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 px-1">
            <span className="text-xs text-stone-500">Ask to…</span>
            <div
              role="group"
              aria-label="Respond or question mode"
              className="flex rounded-full border border-stone-700 overflow-hidden"
            >
              {(
                [
                  { id: false, label: 'Respond' },
                  { id: true, label: 'Question me' },
                ] as const
              ).map((o) => (
                <button
                  key={o.label}
                  type="button"
                  onClick={() => setQuestionMode(o.id)}
                  aria-pressed={questionMode === o.id}
                  className={`min-h-[44px] px-4 text-sm font-medium ${
                    questionMode === o.id
                      ? 'bg-amber-950/40 text-amber-300'
                      : 'text-stone-400'
                  }`}
                >
                  {o.label}
                </button>
              ))}
            </div>
          </div>

          <div className="flex gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  send()
                }
              }}
              placeholder={
                councilMode
                  ? 'Ask the whole council…'
                  : questionMode
                    ? 'Add context (optional)…'
                    : `Talk to ${activeName}…`
              }
              maxLength={2000}
              aria-label={councilMode ? 'Message the whole council' : `Message ${activeName}`}
              className="flex-1 min-w-0 bg-stone-950 border border-stone-700 rounded-full px-4 min-h-[44px] text-sm text-stone-200 outline-none focus:border-amber-500/60"
            />
            <button
              type="button"
              onClick={send}
              disabled={sendDisabled}
              className="shrink-0 min-h-[44px] px-4 rounded-full bg-amber-600 text-amber-50 text-sm font-semibold disabled:opacity-40"
            >
              Send
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
