import { useCallback, useEffect, useRef, useState } from 'react'
import { apiBase } from '../apiBase'
import { normalizeWeave, WeaveText, voiceColor } from '../components/VoiceWeave'

/* ------------------------------------------------------------------ */
/* Streaming reveal (Joshua, 2026-10-23): meeting messages type out   */
/* character by character, the way generated text arrives — paced,    */
/* sequential, one bubble at a time. A resumed meeting never retypes  */
/* its history; tapping the typing bubble completes it instantly.     */
/* ------------------------------------------------------------------ */

const WEAVE_OPEN = '[[u]]'
const WEAVE_CLOSE = '[[/u]]'
const WEAVE_SEG_RE = /\[\[u\]\]([\s\S]*?)\[\[\/u\]\]/g

function weaveSegments(body: string): { weave: boolean; content: string }[] {
  const src = normalizeWeave(body)
  const segs: { weave: boolean; content: string }[] = []
  let last = 0
  let m: RegExpExecArray | null
  WEAVE_SEG_RE.lastIndex = 0
  while ((m = WEAVE_SEG_RE.exec(src)) !== null) {
    if (m.index > last) segs.push({ weave: false, content: src.slice(last, m.index) })
    segs.push({ weave: true, content: m[1] })
    last = m.index + m[0].length
  }
  if (last < src.length) segs.push({ weave: false, content: src.slice(last) })
  return segs
}

function visibleLength(body: string): number {
  return weaveSegments(body).reduce((n, s) => n + s.content.length, 0)
}

/** The raw text containing exactly `count` visible characters — weave
 *  markers travel atomically, and a partially revealed woven span is
 *  closed so it highlights as it types. */
function weavePrefix(body: string, count: number): string {
  let remaining = count
  let out = ''
  for (const s of weaveSegments(body)) {
    if (remaining <= 0) break
    const take = s.content.slice(0, remaining)
    remaining -= take.length
    out += s.weave ? `${WEAVE_OPEN}${take}${WEAVE_CLOSE}` : take
  }
  return out
}

/**
 * The keystone meeting — a guided first-meeting conversation with one seat.
 *
 * The server runs the stage machine (opening → encounter → read-back →
 * reveal) and owns the state; this view is a window onto it: it hydrates
 * from GET /conversation/meeting, begins/resumes via POST .../meeting/start,
 * and sends turns via POST .../meeting/turn, always re-rendering from the
 * returned state. Leaving loses nothing — the meeting waits at its beat.
 *
 * Identity discipline: inside the room, the character is not name-labelled
 * until the meeting completes and the reveal has happened. The bubbles
 * carry the seat's color; the name arrives when it's earned.
 */

type MeetingMessage = {
  id: string
  role: 'user' | 'voice'
  body: string
  archetype_id?: string | null
}

type MeetingState = {
  archetype_id: string
  keystone_index: number
  conversation_id: string
  status: 'not_started' | 'active' | 'paused' | 'complete'
  stage: string | null
  has_script: boolean
  character: string | null
  demeanor: string | null
  messages: MeetingMessage[]
}

const STYLE = `
.mtg-root{position:fixed;inset:0;z-index:70;font-family:system-ui,-apple-system,sans-serif;-webkit-tap-highlight-color:transparent}
.mtg-backdrop{position:absolute;inset:0;background:rgba(0,0,0,.6)}
.mtg-panel{position:absolute;left:0;right:0;bottom:0;top:4vh;display:flex;flex-direction:column;background:#0b0a09;border:1px solid rgba(201,168,106,.3);border-bottom:none;border-radius:20px 20px 0 0;color:#f5f0e8;box-shadow:0 -12px 48px rgba(0,0,0,.5)}
.mtg-head{display:flex;align-items:flex-start;gap:10px;padding:16px 18px 10px;border-bottom:1px solid rgba(201,168,106,.18)}
.mtg-title{margin:0;font-size:17px;font-weight:600}
.mtg-sub{font-size:12px;color:#a89f8d;letter-spacing:.04em;text-transform:uppercase}
.mtg-close{margin-left:auto;min-width:44px;min-height:44px;border-radius:999px;border:1px solid rgba(201,168,106,.35);background:transparent;color:#f5f0e8;font-size:16px}
.mtg-body{flex:1;overflow-y:auto;padding:14px 16px}
.mtg-foot{padding:10px 14px 16px;border-top:1px solid rgba(201,168,106,.18)}
.mtg-reveal{margin:4px 0 14px;padding:14px;border:1px solid rgba(232,163,61,.55);border-radius:14px;background:rgba(232,163,61,.08)}
`

export function MeetingView({
  archetypeId,
  onClose,
}: {
  archetypeId: string
  onClose: () => void
}) {
  const base = apiBase()
  const [state, setState] = useState<MeetingState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const endRef = useRef<HTMLDivElement | null>(null)

  // Streaming reveal state: ids already shown in full, whether the
  // first hydration has happened (history never retypes), and the
  // bubble currently typing.
  const seenRef = useRef<Set<string>>(new Set())
  const primedRef = useRef(false)
  const [typing, setTyping] = useState<{ id: string; count: number } | null>(null)
  const reduceMotion =
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches

  const finishTyping = useCallback(() => {
    setState((cur) => {
      if (cur) for (const m of cur.messages) seenRef.current.add(m.id)
      return cur
    })
    setTyping(null)
  }, [])

  // Prime on first hydration; afterwards, start typing the oldest
  // voice message that hasn't been shown yet.
  useEffect(() => {
    if (!state) return
    if (!primedRef.current) {
      primedRef.current = true
      for (const m of state.messages) seenRef.current.add(m.id)
      return
    }
    if (typing) return
    if (reduceMotion) {
      for (const m of state.messages) seenRef.current.add(m.id)
      return
    }
    const next = state.messages.find((m) => m.role === 'voice' && !seenRef.current.has(m.id))
    if (next) setTyping({ id: next.id, count: 0 })
  }, [state, typing, reduceMotion])

  // Advance the typing bubble at ~110 visible chars/sec (bounded).
  useEffect(() => {
    if (!typing || !state) return
    const msg = state.messages.find((m) => m.id === typing.id)
    if (!msg) {
      setTyping(null)
      return
    }
    const total = visibleLength(msg.body)
    if (typing.count >= total) {
      seenRef.current.add(typing.id)
      setTyping(null)
      return
    }
    const duration = Math.min(3200, Math.max(350, (total / 110) * 1000))
    const step = Math.max(1, Math.ceil(total / (duration / 24)))
    const t = setTimeout(() => {
      setTyping((cur) =>
        cur && cur.id === typing.id
          ? { id: cur.id, count: Math.min(total, cur.count + step) }
          : cur,
      )
    }, 24)
    return () => clearTimeout(t)
  }, [typing, state])

  const apply = useCallback((s: MeetingState) => {
    setState(s)
    setError(null)
  }, [])

  const call = useCallback(
    async (path: string, body?: Record<string, unknown>) => {
      setBusy(true)
      try {
        const res = await fetch(`${base}/conversation/meeting${path}`, {
          method: body ? 'POST' : 'GET',
          credentials: 'include',
          headers: body ? { 'Content-Type': 'application/json' } : undefined,
          body: body ? JSON.stringify(body) : undefined,
        })
        const data = await res.json().catch(() => null)
        if (!res.ok) {
          setError((data && data.detail) || 'The meeting could not continue just now.')
          return null
        }
        return data as MeetingState
      } catch {
        setError('The meeting could not continue just now.')
        return null
      } finally {
        setBusy(false)
      }
    },
    [base],
  )

  useEffect(() => {
    let cancelled = false
    fetch(
      `${base}/conversation/meeting?archetype_id=${encodeURIComponent(archetypeId)}&keystone_index=1`,
      { credentials: 'include' },
    )
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!cancelled && data) apply(data as MeetingState)
        else if (!cancelled) setError('Could not load the meeting just now.')
      })
      .catch(() => {
        if (!cancelled) setError('Could not load the meeting just now.')
      })
    return () => {
      cancelled = true
    }
  }, [archetypeId, base, apply])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [state?.messages.length, busy, typing?.count])

  const begin = async () => {
    const s = await call('/start', { archetype_id: archetypeId, keystone_index: 1 })
    if (s) apply(s)
  }

  const send = async () => {
    const text = input.trim()
    if (!text || busy) return
    finishTyping() // sending settles whatever is still typing
    setInput('')
    const s = await call('/turn', { archetype_id: archetypeId, keystone_index: 1, message: text })
    if (s) apply(s)
    else setInput(text)
  }

  const pauseAndClose = async () => {
    await call('/pause', { archetype_id: archetypeId, keystone_index: 1 })
    onClose()
  }

  const color = voiceColor(archetypeId)
  const complete = state?.status === 'complete'
  const inRoom = state && (state.status === 'active' || state.status === 'paused')

  return (
    <div className="mtg-root" role="dialog" aria-modal="true" aria-label="First meeting">
      <style>{STYLE}</style>
      <div className="mtg-backdrop" onClick={onClose} aria-hidden="true" />
      <section className="mtg-panel">
        <header className="mtg-head">
          <div>
            <div className="mtg-sub">Keystone 1 of 4 · First meeting</div>
            <h3 className="mtg-title">
              {complete && state?.character ? `You've met the ${state.character}` : 'A first meeting'}
            </h3>
          </div>
          <button type="button" className="mtg-close" onClick={onClose} aria-label="Close meeting">
            ✕
          </button>
        </header>

        <div className="mtg-body">
          {error && <p className="text-sm text-amber-200/90 leading-relaxed">{error}</p>}
          {!state && !error && <p className="text-sm text-stone-400">Opening the door…</p>}

          {state && state.status === 'not_started' && (
            <div>
              {state.has_script ? (
                <>
                  <p className="text-sm text-stone-300 leading-relaxed">
                    Someone on your council would like to meet you properly — not a chat, a
                    first meeting. It takes a few exchanges, it can be paused at any point, and
                    nothing from it is kept as training without your say.
                  </p>
                  <button
                    type="button"
                    onClick={begin}
                    disabled={busy}
                    className="mt-4 min-h-[44px] px-5 rounded-full bg-amber-600 text-amber-50 text-sm font-semibold disabled:opacity-40"
                  >
                    {busy ? 'Opening…' : 'Begin the meeting →'}
                  </button>
                </>
              ) : (
                <p className="text-sm text-stone-400 leading-relaxed">
                  This meeting isn't written yet. Each seat gets its own first meeting, in its
                  own way — this one's turn hasn't come.
                </p>
              )}
            </div>
          )}

          {state && state.messages.length > 0 && (
            <div className="space-y-2" aria-live="polite">
              {state.messages.map((m) => {
                if (m.role === 'user') {
                  return (
                    <div key={m.id} className="flex justify-end">
                      <div className="max-w-[88%] rounded-2xl px-3 py-2 text-sm leading-snug bg-stone-700 text-stone-100">
                        {m.body}
                      </div>
                    </div>
                  )
                }
                const isTyping = typing?.id === m.id
                if (!isTyping && !seenRef.current.has(m.id)) {
                  return null // queued — appears when its turn to type comes
                }
                return (
                  <div key={m.id} className="flex justify-start">
                    <div
                      className="max-w-[88%] rounded-2xl px-3 py-2 text-sm leading-snug bg-stone-800/80 border text-stone-200"
                      style={{ borderColor: `${color}55`, borderLeftWidth: 3, borderLeftColor: color }}
                      onClick={isTyping ? finishTyping : undefined}
                    >
                      <WeaveText text={isTyping ? weavePrefix(m.body, typing.count) : m.body} />
                    </div>
                  </div>
                )
              })}
              {busy && <div className="text-xs text-stone-500">listening…</div>}
              <div ref={endRef} />
            </div>
          )}

          {complete && state && (
            <div className="mtg-reveal">
              <div className="text-xs font-semibold tracking-wide" style={{ color: '#e8a33d' }}>
                FIRST MEETING — COMPLETE
              </div>
              <div className="mt-1 text-base font-semibold">{state.character}</div>
              {state.demeanor && (
                <div className="text-sm text-stone-300">{state.demeanor}</div>
              )}
              <p className="mt-2 text-sm text-stone-400 leading-relaxed">
                Name, face, and demeanor unlocked. The other seats are waiting to be met in
                their own time — each will introduce themselves.
              </p>
            </div>
          )}
        </div>

        {inRoom && state.status === 'active' && (
          <div className="mtg-foot">
            <div className="flex gap-2">
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    void send()
                  }
                }}
                placeholder="Answer in your own words… (or “pass”)"
                maxLength={2000}
                aria-label="Your reply in the meeting"
                className="flex-1 min-w-0 bg-stone-950 border border-stone-700 rounded-full px-4 min-h-[44px] text-sm text-stone-200 outline-none focus:border-amber-500/60"
              />
              <button
                type="button"
                onClick={() => void send()}
                disabled={busy || !input.trim()}
                className="shrink-0 min-h-[44px] px-4 rounded-full bg-amber-600 text-amber-50 text-sm font-semibold disabled:opacity-40"
              >
                Send
              </button>
            </div>
            <button
              type="button"
              onClick={() => void pauseAndClose()}
              className="mt-2 min-h-[44px] px-2 text-sm text-stone-400 underline underline-offset-4"
            >
              Pause the meeting — it will wait at this exact point
            </button>
          </div>
        )}

        {inRoom && state.status === 'paused' && (
          <div className="mtg-foot">
            <button
              type="button"
              onClick={begin}
              disabled={busy}
              className="min-h-[44px] px-5 rounded-full bg-amber-600 text-amber-50 text-sm font-semibold disabled:opacity-40"
            >
              {busy ? 'Resuming…' : 'Resume the meeting →'}
            </button>
          </div>
        )}

        {complete && (
          <div className="mtg-foot">
            <button
              type="button"
              onClick={onClose}
              className="min-h-[44px] px-5 rounded-full bg-amber-600 text-amber-50 text-sm font-semibold"
            >
              Back to the tree
            </button>
          </div>
        )}
      </section>
    </div>
  )
}
