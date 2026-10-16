import { useCallback, useEffect, useRef, useState } from 'react'
import { apiBase } from '../apiBase'
import { WeaveText, voiceColor, useDemoVoices, type DemoVoice } from '../components/VoiceWeave'

/**
 * Foundation tab voice console — Joshua's 2026-10-16 concept.
 *
 * Two rows of the 7 voices: BASE (aspirational stock, the "empty" reference)
 * and YOURS (trained — depth bars show how each seat is coming along).
 * Tap a voice to talk to it directly; the conversation can surface training
 * moments for granular per-voice shaping.
 *
 * Also hosts the demo claim-code entry: "continue the conversation" —
 * a landing-demo transcript pulled into the intake pipeline.
 */

type ChatMsg = { role: 'user' | 'voice'; content: string }

type VoiceStatus = {
  id: string
  display_name: string
  depth: number
  avatar_url?: string | null
}

export default function VoiceConsole() {
  const base = apiBase()
  const demoVoices = useDemoVoices(base)
  const [mode, setMode] = useState<'trained' | 'base'>('trained')
  const [statuses, setStatuses] = useState<VoiceStatus[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMsg[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [modeUsed, setModeUsed] = useState<string | null>(null)
  const [claimCode, setClaimCode] = useState('')
  const [claimMsg, setClaimMsg] = useState<string | null>(null)
  const [claiming, setClaiming] = useState(false)
  const chatEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Per-voice training depth (the "how it's coming along" bars).
  useEffect(() => {
    let cancelled = false
    fetch(`${base}/council/archetypes/status`, { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (cancelled || !data) return
        const list = data.archetypes ?? data.voices ?? []
        if (Array.isArray(list)) {
          setStatuses(
            list.map((a: any) => ({
              id: a.id,
              display_name: a.display_name ?? a.id,
              depth: typeof a.depth === 'number' ? a.depth : 0,
              avatar_url: a.avatar_url ?? null,
            })),
          )
        }
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [base])

  const voices: DemoVoice[] = demoVoices.length
    ? demoVoices
    : ['mentor', 'champion', 'guardian', 'maverick', 'ambassador', 'conductor', 'skeptic'].map((id) => ({
        id,
        name: id[0].toUpperCase() + id.slice(1),
        color: voiceColor(id),
        frame: '',
      }))

  const displayName = (id: string) => {
    const s = statuses.find((x) => x.id === id)
    if (s) return s.display_name
    return voices.find((v) => v.id === id)?.name ?? id
  }
  const depthOf = (id: string) => statuses.find((x) => x.id === id)?.depth ?? 0

  const openVoice = (id: string) => {
    setActiveId(id)
    setMessages([])
    setModeUsed(null)
  }

  const send = useCallback(async () => {
    const text = input.trim()
    if (!text || loading || !activeId) return
    const history = messages.map((m) => ({ role: m.role, content: m.content }))
    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setInput('')
    setLoading(true)
    try {
      const r = await fetch(`${base}/voice/chat`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ archetype_id: activeId, message: text, history, mode }),
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const data = await r.json()
      setMessages((prev) => [...prev, { role: 'voice', content: data.reply }])
      setModeUsed(data.mode_used)
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: 'voice', content: "I couldn't reach my voice just now — try again in a moment." },
      ])
    } finally {
      setLoading(false)
    }
  }, [input, loading, activeId, messages, base, mode])

  const claim = async () => {
    const code = claimCode.trim().toUpperCase()
    if (!code || claiming) return
    setClaiming(true)
    setClaimMsg(null)
    try {
      // 1. Pull the demo transcript into this account.
      const rc = await fetch(`${base}/demo/claim`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ claim_code: code }),
      })
      if (!rc.ok) throw new Error(rc.status === 404 ? 'not-found' : `HTTP ${rc.status}`)
      const { transcript } = await rc.json()
      // 2. Run it through the standard intake pipeline (same as the bookmarklet).
      const rs = await fetch(`${base}/agents/connect/share-text`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: 'zenaf.ai/demo',
          transcript,
          title: 'Landing demo conversation',
          name: 'Landing demo conversation',
        }),
      })
      if (!rs.ok) throw new Error(`intake HTTP ${rs.status}`)
      setClaimMsg('Continued — your demo conversation is now in the review queue.')
      setClaimCode('')
    } catch (e: any) {
      setClaimMsg(
        e?.message === 'not-found'
          ? "That code didn't match anything — check it and try again."
          : 'Something went wrong pulling that conversation in. Try again.',
      )
    } finally {
      setClaiming(false)
    }
  }

  const activeVoice = activeId ? voices.find((v) => v.id === activeId) : null

  return (
    <div className="flex flex-col gap-4">
      {/* Mode toggle */}
      <div className="flex gap-2">
        {(['trained', 'base'] as const).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            aria-pressed={mode === m}
            className={`min-h-[44px] px-4 rounded-full text-sm font-medium border ${
              mode === m
                ? 'border-amber-500/60 text-amber-300 bg-amber-950/30'
                : 'border-stone-700 text-stone-400'
            }`}
          >
            {m === 'trained' ? 'Your voices' : 'Base voices'}
          </button>
        ))}
      </div>
      <p className="text-xs text-stone-500 -mt-2">
        {mode === 'trained'
          ? 'Your seats, shaped by your training. Depth bars show how each is coming along.'
          : 'The aspirational stock voices — the "empty" reference, no training.'}
      </p>

      {/* Voice grid */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {voices.map((v) => {
          const depth = depthOf(v.id)
          const active = activeId === v.id
          return (
            <button
              key={v.id}
              onClick={() => openVoice(v.id)}
              aria-pressed={active}
              className={`min-h-[64px] rounded-xl border p-3 text-left ${
                active ? 'bg-stone-800/70' : 'bg-stone-900/40 hover:bg-stone-800/40'
              }`}
              style={{ borderColor: active ? v.color : undefined, borderLeftWidth: 3, borderLeftColor: v.color }}
            >
              <div className="text-sm font-semibold" style={{ color: v.color }}>
                {displayName(v.id)}
              </div>
              {mode === 'trained' && (
                <div className="mt-2">
                  <div className="h-1.5 rounded-full bg-stone-800 overflow-hidden">
                    <div
                      className="h-full rounded-full"
                      style={{ width: `${Math.min(100, depth)}%`, background: v.color }}
                    />
                  </div>
                  <div className="text-[11px] text-stone-500 mt-1">{Math.round(depth)} depth</div>
                </div>
              )}
              {mode === 'base' && v.frame && (
                <div className="text-[11px] text-stone-500 mt-1 leading-snug">{v.frame}</div>
              )}
            </button>
          )
        })}
      </div>

      {/* Chat with the selected voice */}
      {activeVoice && (
        <div className="rounded-xl border border-stone-700 bg-stone-900/50 p-3">
          <div className="flex items-center justify-between mb-2">
            <div className="text-sm font-semibold" style={{ color: activeVoice.color }}>
              {displayName(activeVoice.id)}
              {modeUsed && (
                <span className="ml-2 text-[11px] font-normal text-stone-500">
                  {modeUsed === 'trained' ? 'your trained voice' : 'base voice (no training yet)'}
                </span>
              )}
            </div>
            <button
              onClick={() => setActiveId(null)}
              className="text-xs text-stone-500 min-h-[44px] px-2"
              aria-label="Close voice chat"
            >
              ✕
            </button>
          </div>
          <div className="max-h-[300px] overflow-y-auto space-y-2 mb-3">
            {messages.map((m, i) => (
              <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div
                  className={`max-w-[88%] rounded-2xl px-3 py-2 text-sm leading-snug ${
                    m.role === 'user' ? 'bg-stone-700 text-stone-100' : 'bg-stone-800/80 border text-stone-200'
                  }`}
                  style={m.role === 'voice' ? { borderColor: `${activeVoice.color}55`, borderLeftWidth: 3, borderLeftColor: activeVoice.color } : undefined}
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
              placeholder={`Talk to ${displayName(activeVoice.id)}…`}
              maxLength={2000}
              className="flex-1 min-w-0 bg-stone-950 border border-stone-700 rounded-full px-4 py-2.5 text-sm text-stone-200 outline-none focus:border-amber-500/60"
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
      )}

      {/* Claim code — "continue the conversation" */}
      <div className="rounded-xl border border-dashed border-stone-700 p-3">
        <div className="text-xs font-semibold text-stone-400 uppercase tracking-wide mb-1">
          Continue the conversation
        </div>
        <p className="text-xs text-stone-500 mb-2">
          Talked to the voices on zenaf.ai? Enter your conversation code to pull it into your review queue.
        </p>
        <div className="flex gap-2">
          <input
            value={claimCode}
            onChange={(e) => setClaimCode(e.target.value.toUpperCase().replace(/[^A-Z2-9]/g, '').slice(0, 12))}
            placeholder="ABC123"
            maxLength={12}
            className="flex-1 min-w-0 bg-stone-950 border border-stone-700 rounded-lg px-3 py-2.5 text-sm tracking-[0.2em] text-stone-200 outline-none focus:border-amber-500/60 uppercase"
          />
          <button
            onClick={claim}
            disabled={claiming || !claimCode.trim()}
            className="min-h-[44px] px-4 rounded-lg border border-amber-500/50 text-amber-400 text-sm disabled:opacity-40"
          >
            {claiming ? '…' : 'Claim'}
          </button>
        </div>
        {claimMsg && <div className="text-xs text-stone-400 mt-2">{claimMsg}</div>}
      </div>
    </div>
  )
}
