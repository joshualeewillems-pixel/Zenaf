import { useCallback, useEffect, useRef, useState } from 'react'
import { apiBase } from '../apiBase'
import { WeaveText } from '../components/VoiceWeave'
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
 * Persistence seam: `conversationId` is accepted and carried as the
 * backend conversation-store key, and `initialMessages` hydrates the
 * thread. The store itself lands in a later build — for now the thread
 * lives in component state and nothing is sent to a store.
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
}: {
  /** 'sheet' = compact, trained-only. 'workspace' = roomier + version toggle. */
  environment: 'sheet' | 'workspace'
  /** Pre-selected seat (seat-branch sheets). Omit → chips, no selection. */
  initialArchetypeId?: string | null
  /** Seat fellowship name override for the composer placeholder. */
  displayName?: string
  /** Backend conversation-store key. Accepted and carried; not sent yet. */
  conversationId?: string | null
  /** Hydration seam: messages a future backend store hands back. */
  initialMessages?: ConversationMessage[]
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

  const activeName =
    displayName ?? (activeId ? names[activeId] ?? activeId : null) ?? 'a voice'

  const send = useCallback(async () => {
    const text = input.trim()
    if (!activeId || loading) return
    if (!text && !questionMode) return
    const history = messages.map((m) => ({ role: m.role, content: m.content }))
    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setInput('')
    setLoading(true)
    setSignedOut(false)
    try {
      const r = await fetch(`${base}/voice/chat`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          archetype_id: activeId,
          message: text,
          history,
          mode: environment === 'workspace' ? voiceMode : 'trained',
          question: questionMode,
        }),
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
  }, [input, loading, activeId, messages, base, environment, voiceMode, questionMode, activeName])

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
        <>
          {/* Demo's Respond / Question me toggle. */}
          <div className="flex items-center gap-2">
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
              className="min-h-[44px] px-4 rounded-full bg-amber-600 text-amber-50 text-sm font-semibold disabled:opacity-40"
            >
              Send
            </button>
          </div>
        </>
      )}
    </div>
  )
}
