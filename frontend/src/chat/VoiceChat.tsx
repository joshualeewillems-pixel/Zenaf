import { useCallback, useEffect, useRef, useState } from 'react'
import { apiBase } from '../apiBase'
import { WeaveText } from '../components/VoiceWeave'

type ChatMsg = { role: 'user' | 'voice'; content: string }

/**
 * One-on-one chat with a single council voice (seat), via POST /voice/chat.
 *
 * Extracted from the Foundation voice console so the tree's Talk sheets mount
 * the same real conversation — no duplicated chat logic. The console keeps its
 * voice grid / mode toggle / claim-code UI; only the thread + input live here.
 *
 * Replies use the [[u]]...[[/u]] color-weave convention, rendered by the
 * shared WeaveText component.
 */
export default function VoiceChat({
  archetypeId,
  displayName,
  initialColor = '#c9a86a',
  mode = 'trained',
  onClose,
}: {
  archetypeId: string
  displayName: string
  /** Header accent until the first reply returns the voice's real color. */
  initialColor?: string
  mode?: 'trained' | 'base'
  /** When set, shows a close button (Foundation console usage). */
  onClose?: () => void
}) {
  const base = apiBase()
  const [messages, setMessages] = useState<ChatMsg[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [modeUsed, setModeUsed] = useState<string | null>(null)
  const [voiceColor, setVoiceColor] = useState(initialColor)
  const [signedOut, setSignedOut] = useState(false)
  const chatEndRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages.length, loading])

  const send = useCallback(async () => {
    const text = input.trim()
    if (!text || loading) return
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
        body: JSON.stringify({ archetype_id: archetypeId, message: text, history, mode }),
      })
      if (r.status === 401) {
        setSignedOut(true)
        setMessages((prev) => prev.slice(0, -1))
        return
      }
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const data = await r.json()
      setMessages((prev) => [...prev, { role: 'voice', content: data.reply }])
      setModeUsed(data.mode_used ?? null)
      if (data.voice_color) setVoiceColor(data.voice_color)
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: 'voice', content: "I couldn't reach my voice just now — try again in a moment." },
      ])
    } finally {
      setLoading(false)
    }
  }, [input, loading, archetypeId, messages, base, mode])

  return (
    <div className="flex flex-col">
      <div className="flex items-center justify-between mb-2">
        <div className="text-sm font-semibold" style={{ color: voiceColor }}>
          {displayName}
          {modeUsed && (
            <span className="ml-2 text-[11px] font-normal text-stone-500">
              {modeUsed === 'trained' ? 'your trained voice' : 'base voice (no training yet)'}
            </span>
          )}
        </div>
        {onClose && (
          <button
            onClick={onClose}
            className="text-xs text-stone-500 min-h-[44px] px-2"
            aria-label="Close voice chat"
          >
            ✕
          </button>
        )}
      </div>
      {signedOut && (
        <div className="text-sm text-stone-400 mb-2">Please sign in to talk to your voices.</div>
      )}
      <div className="max-h-[300px] overflow-y-auto space-y-2 mb-3">
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[88%] rounded-2xl px-3 py-2 text-sm leading-snug ${
                m.role === 'user' ? 'bg-stone-700 text-stone-100' : 'bg-stone-800/80 border text-stone-200'
              }`}
              style={
                m.role === 'voice'
                  ? { borderColor: `${voiceColor}55`, borderLeftWidth: 3, borderLeftColor: voiceColor }
                  : undefined
              }
            >
              {m.role === 'voice' ? <WeaveText text={m.content} /> : m.content}
            </div>
          </div>
        ))}
        {loading && <div className="text-xs text-stone-500">thinking…</div>}
        <div ref={chatEndRef} />
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
          placeholder={`Talk to ${displayName}…`}
          maxLength={2000}
          aria-label={`Message ${displayName}`}
          className="flex-1 min-w-0 bg-stone-950 border border-stone-700 rounded-full px-4 min-h-[44px] text-sm text-stone-200 outline-none focus:border-amber-500/60"
        />
        <button
          onClick={send}
          disabled={loading || !input.trim()}
          className="min-h-[44px] px-4 rounded-full bg-amber-600 text-amber-50 text-sm font-semibold disabled:opacity-40"
        >
          Send
        </button>
      </div>
    </div>
  )
}
