import { useEffect, useState } from 'react'
import { apiBase } from '../apiBase'
import { voiceColor, useDemoVoices, type DemoVoice } from '../components/VoiceWeave'
import VoiceChat from '../chat/VoiceChat'

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
  const [claimCode, setClaimCode] = useState('')
  const [claimMsg, setClaimMsg] = useState<string | null>(null)
  const [claiming, setClaiming] = useState(false)

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
  }

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

      {/* Chat with the selected voice — the shared VoiceChat component (also used by the tree's Talk sheets). */}
      {activeVoice && (
        <div className="rounded-xl border border-stone-700 bg-stone-900/50 p-3">
          <VoiceChat
            key={activeId}
            archetypeId={activeId!}
            displayName={displayName(activeId!)}
            initialColor={activeVoice.color}
            mode={mode}
            onClose={() => setActiveId(null)}
          />
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
