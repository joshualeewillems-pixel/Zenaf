import { useCallback, useEffect, useRef, useState } from 'react'
import { CouncilTranscript } from '../council/CouncilTranscript'
import VoiceChat from './VoiceChat'

type Turn = { role: 'user' | 'council'; content: string }

/**
 * The tree's Talk sheet chat.
 *
 * - Seat node → a one-on-one with that seat's voice (POST /voice/chat — the
 *   same real conversation as the Foundation voice console, via VoiceChat).
 * - You-node → the whole council (POST /run, mode `council`, non-streaming;
 *   replies rendered with the shared CouncilTranscript).
 *
 * Honest boundary: the council API has no seat-scoped whole-council mode
 * (archetypes are strand blends; `included_agents` takes strand keys), so
 * seat Talk is the seat's own voice and you Talk is the full council — no
 * fake scoping. Streaming, resonance, voice input, and the amber filing flow
 * stay in the Workspace view; this is the conversation, kept simple.
 */
export default function CouncilChat({
  archetypeId,
  displayName,
}: {
  /** Engine seat key (e.g. 'guardian'). Omit for the whole-council conversation. */
  archetypeId?: string | null
  /** Seat fellowship name (e.g. 'The Bear') for the voice header. */
  displayName?: string
}) {
  if (archetypeId) {
    return <VoiceChat archetypeId={archetypeId} displayName={displayName ?? 'Seat'} />
  }
  return <WholeCouncilChat />
}

function WholeCouncilChat() {
  const [turns, setTurns] = useState<Turn[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [signedOut, setSignedOut] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const endRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [turns.length, loading])

  const send = useCallback(async () => {
    const text = input.trim()
    if (!text || loading) return
    setTurns((prev) => [...prev, { role: 'user', content: text }])
    setInput('')
    setLoading(true)
    setSignedOut(false)
    setError(null)
    try {
      // RUN_API_BASE is '' (same origin) in App.tsx; /run is proxied in dev.
      const r = await fetch('/run', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mode: 'council',
          params: { question: text, include_synthesis: true },
        }),
      })
      if (r.status === 401) {
        setSignedOut(true)
        setTurns((prev) => prev.slice(0, -1))
        return
      }
      const data = await r.json().catch(() => ({}))
      if (!r.ok || !data.ok || data.result == null) {
        throw new Error(data.error || data.detail || `HTTP ${r.status}`)
      }
      const reply = typeof data.result === 'string' ? data.result : JSON.stringify(data.result)
      setTurns((prev) => [...prev, { role: 'council', content: reply }])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The council could not be reached just now.')
    } finally {
      setLoading(false)
    }
  }, [input, loading])

  return (
    <div className="flex flex-col">
      <div className="text-sm font-semibold text-amber-200/90 mb-2">Your council</div>
      {signedOut && (
        <div className="text-sm text-stone-400 mb-2">Please sign in to talk to your council.</div>
      )}
      <div className="max-h-[320px] overflow-y-auto space-y-3 mb-3">
        {turns.map((t, i) =>
          t.role === 'user' ? (
            <div key={i} className="flex justify-end">
              <div className="max-w-[88%] rounded-2xl px-3 py-2 text-sm leading-snug bg-stone-700 text-stone-100">
                {t.content}
              </div>
            </div>
          ) : (
            <div
              key={i}
              className="rounded-2xl px-3 py-2 bg-stone-800/80 border border-stone-700/60"
            >
              <CouncilTranscript text={t.content} />
            </div>
          ),
        )}
        {loading && <div className="text-xs text-stone-500">the council is conferring…</div>}
        {error && <div className="text-xs text-red-300/80">{error}</div>}
        <div ref={endRef} />
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
          placeholder="Ask your council…"
          maxLength={2000}
          aria-label="Message your council"
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
