import { useCallback, useEffect, useRef, useState } from 'react'
import { apiBase } from '../apiBase'
import { WeaveText, voiceColor } from '../components/VoiceWeave'
import SeatChips, { useSeatMeta } from './SeatChips'

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
 *
 * - Sheet seat tab → pre-selected seat (character header rendered above by
 *   the sheet, from PR #147's merged Talk+Character tab).
 * - Sheet you-node → chips with no pre-selection: an invitation to pick.
 * - Workspace (Foundation console) → adds the trained/base version toggle.
 *
 * No multi-seat fan-out: the old whole-council POST /run path lived here
 * and was removed — talking is always 1:1. The /run backend stays for the
 * workspace's deliberation console.
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
}: {
  /** 'sheet' = compact, trained-only. 'workspace' = roomier + version toggle. */
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
}) {
  const base = apiBase()
  const { names } = useSeatMeta()

  // The persistent thread — initialized once from the hydration seam.
  // Switching seats never touches this list.
  const [messages, setMessages] = useState<ConversationMessage[]>(initialMessages ?? [])
  const [activeId, setActiveId] = useState<string | null>(initialArchetypeId ?? null)
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  /** Demo's "Respond / Question me" toggle, brought to the authenticated chat. */
  const [questionMode, setQuestionMode] = useState(false)
  /** Workspace-only version toggle; sheets are always the trained voice. */
  const [voiceMode, setVoiceMode] = useState<'trained' | 'base'>('trained')
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
  const namesRef = useRef(names)
  namesRef.current = names
  const [storeEmpty, setStoreEmpty] = useState<boolean | null>(null)
  useEffect(() => {
    if (!conversationId) return
    let cancelled = false
    setStoreEmpty(null)
    fetch(
      `${base}/conversation?conversation_id=${encodeURIComponent(conversationId)}&limit=50`,
      { credentials: 'include' },
    )
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (cancelled) return
        const rows = data && Array.isArray(data.messages) ? data.messages : []
        const mapped: ConversationMessage[] = []
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
            voiceId: role === 'voice' ? aid : null,
            voiceName: role === 'voice' ? namesRef.current[aid ?? ''] ?? aid ?? undefined : undefined,
            voiceColor: role === 'voice' && aid ? voiceColor(aid) : undefined,
          })
        }
        if (mapped.length > 0) {
          setMessages(mapped)
          setStoreEmpty(false)
        } else {
          setStoreEmpty(true)
        }
      })
      .catch(() => {
        if (!cancelled) setStoreEmpty(true)
      })
    return () => {
      cancelled = true
    }
  }, [conversationId, base])

  useEffect(() => {
    if (!conversationId || storeEmpty !== true) return
    if (!seedMessages || seedMessages.length === 0) return
    if (messages.some((m) => m.role === 'user')) return
    setMessages((prev) => (prev.length === 0 ? seedMessages : prev))
  }, [conversationId, storeEmpty, seedMessages, messages])

  // External draft injection (what's-next chips): take the text, don't send.
  const prefillNonce = prefill?.nonce ?? 0
  useEffect(() => {
    if (prefill && prefillNonce > 0) setInput(prefill.text)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefillNonce])

  const activeName =
    displayName ?? (activeId ? names[activeId] ?? activeId : null) ?? 'a voice'

  const send = useCallback(async () => {
    const text = input.trim()
    if (!activeId || loading) return
    if (!text && !questionMode) return
    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setInput('')
    setLoading(true)
    setSignedOut(false)
    try {
      // Skeleton-store thread: persist via POST /conversation/turn with the
      // sheet's live context. Otherwise the legacy client-history path.
      const useStore = Boolean(conversationId)
      const r = await fetch(useStore ? `${base}/conversation/turn` : `${base}/voice/chat`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(
          useStore
            ? {
                conversation_id: conversationId,
                archetype_id: activeId,
                message: text,
                mode: environment === 'workspace' ? voiceMode : 'trained',
                question: questionMode,
                ...(context ? { context } : {}),
              }
            : {
                archetype_id: activeId,
                message: text,
                history: messages.map((m) => ({ role: m.role, content: m.content })),
                mode: environment === 'workspace' ? voiceMode : 'trained',
                question: questionMode,
              },
        ),
      })
      if (r.status === 401) {
        setSignedOut(true)
        setMessages((prev) => prev.slice(0, -1))
        return
      }
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const data = await r.json()
      setMessages((prev) => [
        ...prev,
        {
          role: 'voice',
          content: data.reply,
          voiceId: data.archetype_id ?? activeId,
          voiceName: data.display_name ?? activeName,
          voiceColor: data.voice_color ?? undefined,
        },
      ])
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          role: 'voice',
          content: "I couldn't reach my voice just now — try again in a moment.",
          voiceId: activeId,
          voiceName: activeName,
        },
      ])
    } finally {
      setLoading(false)
    }
  }, [input, loading, activeId, messages, base, environment, voiceMode, questionMode, activeName, conversationId, context])

  const sendDisabled = loading || !activeId || (!input.trim() && !questionMode)

  return (
    <div className="flex flex-col gap-3" data-conversation={conversationKey}>
      {/* Seat switcher — tapping branches the ongoing conversation. */}
      <SeatChips activeId={activeId} onSelect={setActiveId} />

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

      {/* The persistent thread. */}
      <div
        className={`${
          environment === 'workspace' ? 'max-h-[420px]' : 'max-h-[300px]'
        } overflow-y-auto space-y-2`}
        aria-live="polite"
      >
        {!activeId && (
          <p className="text-sm text-stone-400 leading-relaxed px-1 py-2">
            Pick a voice above to begin — one conversation, tap a seat to
            branch it whenever you like.
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
            <div key={i} className="flex justify-start">
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
                <WeaveText text={m.content} />
              </div>
            </div>
          ),
        )}
        {loading && <div className="text-xs text-stone-500">thinking…</div>}
        {signedOut && (
          <div className="text-sm text-stone-400">Please sign in to talk to your voices.</div>
        )}
        <div ref={chatEndRef} />
      </div>

      {activeId && (
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
                questionMode ? 'Add context (optional)…' : `Talk to ${activeName}…`
              }
              maxLength={2000}
              aria-label={`Message ${activeName}`}
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
