import { useState } from 'react'
import { apiBase } from '../apiBase'

/**
 * Per-response feedback widget (v1, inert records only).
 *
 * Rendered under a seat response in CouncilChat. Collapsed by default to
 * one small line; expanding it changes nothing in the system. NOTHING is
 * sent until the user explicitly submits — an untouched widget stores
 * nothing, surfaces nothing, and never nags. One submit creates exactly
 * one feedback record via POST /feedback; the record is inert data until
 * a future review-queue tie-in reads it. No analysis, no training writes.
 */

/** The design doc's six proposed presets, adopted as the v1 set. */
export const FEEDBACK_PRESETS = [
  'Sounds like me',
  'Sounds like the seat',
  'Helpful',
  'Missed the mark',
  'Tone feels off',
  'Want more of this',
] as const

export const SLIDER_MIN = 1
export const SLIDER_MAX = 7
/** Neutral middle stop — the default. Untouched means no record at all. */
export const NEUTRAL_SLIDER_VALUE = 4

/** Faces only, no words, no red/green — the note stays the definition. */
export const SLIDER_FACES = ['😞', '🙁', '😕', '😐', '🙂', '😊', '🤩'] as const

export function faceForValue(value: number): string {
  const clamped = Math.max(SLIDER_MIN, Math.min(SLIDER_MAX, Math.round(value)))
  return SLIDER_FACES[clamped - 1]
}

export default function VoiceFeedback({
  messageId,
  seat,
  conversationId,
  defaultExpanded = false,
}: {
  /** Stable response reference: server message id, or a session-scoped
   *  `local-` ref for threads that live in component state only. */
  messageId: string
  /** Responding seat's archetype id (e.g. 'mentor'). */
  seat: string
  /** Thread key: the conversation id, or 'local' for ephemeral threads. */
  conversationId: string
  /** Test seam only: render expanded on mount. Production stays collapsed. */
  defaultExpanded?: boolean
}) {
  const base = apiBase()
  const [expanded, setExpanded] = useState(defaultExpanded)
  const [slider, setSlider] = useState(NEUTRAL_SLIDER_VALUE)
  const [checks, setChecks] = useState<string[]>([])
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState(false)

  const toggleCheck = (label: string) =>
    setChecks((prev) =>
      prev.includes(label) ? prev.filter((c) => c !== label) : [...prev, label],
    )

  const submit = async () => {
    if (saving || saved) return
    setSaving(true)
    setError(false)
    try {
      const r = await fetch(`${base}/feedback`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          response_ref: messageId,
          conversation_id: conversationId,
          seat,
          slider,
          checks,
          note,
        }),
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      setSaved(true)
    } catch {
      setError(true)
    } finally {
      setSaving(false)
    }
  }

  if (!expanded) {
    return (
      <button
        type="button"
        onClick={() => setExpanded(true)}
        aria-expanded={false}
        className="text-xs text-stone-500 hover:text-stone-300 px-1 py-0.5"
      >
        How did this land?
      </button>
    )
  }

  return (
    <div className="rounded-2xl border border-stone-700/60 bg-stone-900/70 px-3 py-2 space-y-2">
      <div className="flex items-center gap-3">
        <span className="text-2xl leading-none" aria-hidden>
          {faceForValue(slider)}
        </span>
        <input
          type="range"
          min={SLIDER_MIN}
          max={SLIDER_MAX}
          step={1}
          value={slider}
          disabled={saved}
          onChange={(e) => setSlider(Number(e.target.value))}
          aria-label="How did this land, 1 to 7"
          className="flex-1 accent-amber-600"
        />
      </div>
      <div className="flex justify-between px-1" aria-hidden>
        {Array.from({ length: SLIDER_MAX }, (_, i) => (
          <span
            key={i}
            className={`inline-block h-1.5 w-1.5 rounded-full ${
              i + 1 === slider ? 'bg-amber-300' : 'bg-stone-600'
            }`}
          />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1">
        {FEEDBACK_PRESETS.map((label) => (
          <label key={label} className="flex items-center gap-1.5 text-xs text-stone-300">
            <input
              type="checkbox"
              checked={checks.includes(label)}
              disabled={saved}
              onChange={() => toggleCheck(label)}
            />
            {label}
          </label>
        ))}
      </div>
      <textarea
        value={note}
        disabled={saved}
        onChange={(e) => setNote(e.target.value)}
        maxLength={2000}
        rows={2}
        placeholder="Say more in your own words…"
        aria-label="Say more in your own words"
        className="w-full bg-stone-950 border border-stone-700 rounded-xl px-3 py-2 text-sm text-stone-200 outline-none focus:border-amber-500/60"
      />
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={submit}
          disabled={saving || saved}
          className="shrink-0 min-h-[36px] px-3 rounded-full bg-amber-600 text-amber-50 text-xs font-semibold disabled:opacity-40"
        >
          {saved ? 'Saved' : saving ? 'Saving…' : 'Save feedback'}
        </button>
        {saved && <span className="text-xs text-stone-400">Saved — thanks.</span>}
        {error && <span className="text-xs text-red-400">Couldn&apos;t save — try again.</span>}
      </div>
    </div>
  )
}
