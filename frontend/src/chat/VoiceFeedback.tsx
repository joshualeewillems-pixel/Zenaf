import { useEffect, useRef, useState } from 'react'
import { apiBase } from '../apiBase'

/**
 * Per-response feedback widget (v1, inert records only).
 *
 * Rendered under a seat response in CouncilChat. Three states:
 * inline (default — face + slider + "Say more"), panel (full detail:
 * slider, six presets, note, Save), minimized (saved receipt — saved
 * face + "How did this land? — Saved, tap to change"). A saved answer
 * is never frozen: tapping the minimized row reopens the panel
 * prefilled and fully editable; re-saving appends a new row and the
 * latest row per response_ref wins.
 *
 * Contract (2026-11-10, founder-approved): moving the slider IS the
 * explicit submit for the slider value — debounced (~500 ms), only on
 * a changed value, only after the gesture ends. The panel's Save
 * button remains the explicit submit for checks + note. An untouched
 * widget stores nothing, surfaces nothing, and never nags. One submit
 * creates exactly one feedback record via POST /feedback; the record
 * is inert data until a future review-queue tie-in reads it. No
 * analysis, no training writes.
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

/** Debounce between the last slider movement and the auto-save POST. */
export const SLIDER_AUTOSAVE_DEBOUNCE_MS = 500

export function faceForValue(value: number): string {
  const clamped = Math.max(SLIDER_MIN, Math.min(SLIDER_MAX, Math.round(value)))
  return SLIDER_FACES[clamped - 1]
}

/** A previously saved answer for this response, as CouncilChat loads
 *  it once per conversation. Null means no record exists yet. */
export type InitialFeedback = {
  slider: number
  checks: string[]
  note: string
}

type Mode = 'inline' | 'panel' | 'minimized'

export default function VoiceFeedback({
  messageId,
  seat,
  conversationId,
  defaultExpanded = false,
  initialFeedback = null,
}: {
  /** Stable response reference: server message id, or a session-scoped
   *  `local-` ref for threads that live in component state only. */
  messageId: string
  /** Responding seat's archetype id (e.g. 'mentor'). */
  seat: string
  /** Thread key: the conversation id, or 'local' for ephemeral threads. */
  conversationId: string
  /** Test seam only: render the panel on mount. Production starts inline. */
  defaultExpanded?: boolean
  /** Previously saved record for this response, if any. A widget with
   *  one mounts minimized, prefilled; a late-arriving record is
   *  adopted only while the widget is untouched and inline. */
  initialFeedback?: InitialFeedback | null
}) {
  const base = apiBase()
  const [mode, setMode] = useState<Mode>(() =>
    initialFeedback ? 'minimized' : defaultExpanded ? 'panel' : 'inline',
  )
  const [slider, setSlider] = useState(
    initialFeedback?.slider ?? NEUTRAL_SLIDER_VALUE,
  )
  const [checks, setChecks] = useState<string[]>(initialFeedback?.checks ?? [])
  const [note, setNote] = useState(initialFeedback?.note ?? '')
  const [lastSaved, setLastSaved] = useState<InitialFeedback | null>(
    initialFeedback,
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(false)

  // Ref mirrors for the debounced auto-save and async POST callbacks,
  // so a timer fired later reads current values, not mount-time ones.
  const modeRef = useRef(mode)
  modeRef.current = mode
  const sliderRef = useRef(slider)
  sliderRef.current = slider
  const lastSavedRef = useRef(lastSaved)
  lastSavedRef.current = lastSaved
  const touchedRef = useRef(false)
  const autoTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const autoInFlightRef = useRef<number | null>(null)
  const inFlightRef = useRef(0)

  // Late-arriving prefill (CouncilChat's one GET per conversation can
  // land after the widget mounted): adopt it only while the widget is
  // untouched and inline, so a user's own gesture is never clobbered
  // and an open panel is never yanked away.
  useEffect(() => {
    if (!initialFeedback) return
    if (touchedRef.current) return
    if (lastSavedRef.current) return
    if (modeRef.current !== 'inline') return
    setSlider(initialFeedback.slider)
    setChecks(initialFeedback.checks)
    setNote(initialFeedback.note)
    setLastSaved(initialFeedback)
    setMode('minimized')
  }, [initialFeedback])

  useEffect(
    () => () => {
      if (autoTimerRef.current) clearTimeout(autoTimerRef.current)
    },
    [],
  )

  const applySaved = (rec: InitialFeedback) => {
    setLastSaved(rec)
    lastSavedRef.current = rec
  }

  /** One POST through the existing create-only endpoint. Serialized by
   *  the in-flight counter: concurrent saves share the `saving` state
   *  and the panel Save button stays disabled while any POST is out. */
  const postFeedback = async (body: InitialFeedback): Promise<boolean> => {
    inFlightRef.current += 1
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
          slider: body.slider,
          checks: body.checks,
          note: body.note,
        }),
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      return true
    } catch {
      return false
    } finally {
      inFlightRef.current -= 1
      if (inFlightRef.current === 0) setSaving(false)
    }
  }

  /** Debounced slider auto-save: fires only for a value that differs
   *  from the last saved one, preserves the saved checks/note, and
   *  re-arms itself if a newer move arrived while a POST was out. */
  const fireAutoSave = () => {
    autoTimerRef.current = null
    if (inFlightRef.current > 0) {
      autoTimerRef.current = setTimeout(
        fireAutoSave,
        SLIDER_AUTOSAVE_DEBOUNCE_MS,
      )
      return
    }
    const value = sliderRef.current
    const saved = lastSavedRef.current
    if (saved && value === saved.slider) return
    autoInFlightRef.current = value
    const body: InitialFeedback = {
      slider: value,
      checks: saved?.checks ?? [],
      note: saved?.note ?? '',
    }
    void postFeedback(body).then((ok) => {
      if (autoInFlightRef.current === value) autoInFlightRef.current = null
      if (!ok) {
        setError(true)
      } else {
        applySaved(body)
        // An inline slider minimizes on save; a panel slider stays in
        // the panel — the user is still editing checks and note.
        if (modeRef.current === 'inline') setMode('minimized')
      }
      // A newer move arrived during the flight: save that one too.
      if (sliderRef.current !== lastSavedRef.current?.slider) {
        autoTimerRef.current = setTimeout(
          fireAutoSave,
          SLIDER_AUTOSAVE_DEBOUNCE_MS,
        )
      }
    })
  }

  const scheduleAutoSave = () => {
    if (autoTimerRef.current) clearTimeout(autoTimerRef.current)
    autoTimerRef.current = setTimeout(
      fireAutoSave,
      SLIDER_AUTOSAVE_DEBOUNCE_MS,
    )
  }

  const onSliderChange = (value: number) => {
    touchedRef.current = true
    setSlider(value)
    setError(false)
    if (value === lastSavedRef.current?.slider) {
      if (autoTimerRef.current) clearTimeout(autoTimerRef.current)
      autoTimerRef.current = null
      return
    }
    scheduleAutoSave()
  }

  const toggleCheck = (label: string) => {
    touchedRef.current = true
    setChecks((prev) =>
      prev.includes(label) ? prev.filter((c) => c !== label) : [...prev, label],
    )
  }

  /** Panel Save: the explicit submit for checks + note. Always posts a
   *  new row (latest wins); inputs stay enabled afterwards. */
  const submit = async () => {
    if (saving) return
    const body: InitialFeedback = { slider, checks, note }
    const ok = await postFeedback(body)
    if (!ok) {
      setError(true)
      return
    }
    applySaved(body)
    setMode('minimized')
  }

  /** Collapse affordance: back to the minimized receipt (or the inline
   *  row when nothing is saved yet) without saving. Unsaved
   *  checkbox/note edits are discarded; a slider move still inside
   *  its debounce window is discarded with them — a move whose
   *  auto-save already fired stands, and an in-flight auto-save keeps
   *  its value. */
  const collapse = () => {
    if (autoTimerRef.current) clearTimeout(autoTimerRef.current)
    autoTimerRef.current = null
    const saved = lastSavedRef.current
    const inFlight = autoInFlightRef.current
    setSlider(inFlight ?? saved?.slider ?? NEUTRAL_SLIDER_VALUE)
    setChecks(saved?.checks ?? [])
    setNote(saved?.note ?? '')
    setError(false)
    setMode(saved || inFlight !== null ? 'minimized' : 'inline')
  }

  if (mode === 'minimized') {
    return (
      <div className="space-y-1">
        <button
          type="button"
          onClick={() => setMode('panel')}
          aria-expanded={false}
          className="flex items-center gap-1.5 text-xs text-stone-400 hover:text-stone-200 px-1 py-0.5"
        >
          <span className="text-base leading-none" aria-hidden>
            {faceForValue(slider)}
          </span>
          How did this land? — Saved, tap to change
        </button>
        {error && (
          <p className="text-xs text-red-400 px-1">
            Couldn&apos;t save — try again.
          </p>
        )}
      </div>
    )
  }

  if (mode === 'inline') {
    return (
      <div className="space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xl leading-none" aria-hidden>
            {faceForValue(slider)}
          </span>
          <input
            type="range"
            min={SLIDER_MIN}
            max={SLIDER_MAX}
            step={1}
            value={slider}
            onChange={(e) => onSliderChange(Number(e.target.value))}
            aria-label="How did this land, 1 to 7"
            className="flex-1 min-w-0 accent-amber-600"
          />
          <button
            type="button"
            onClick={() => setMode('panel')}
            className="shrink-0 min-h-[36px] px-3 rounded-full border border-stone-700 text-stone-200 text-xs font-semibold"
          >
            Say more
          </button>
        </div>
        {error && (
          <p className="text-xs text-red-400 px-1">
            Couldn&apos;t save — try again.
          </p>
        )}
      </div>
    )
  }

  return (
    <div className="rounded-2xl border border-stone-700/60 bg-stone-900/70 px-3 py-2 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs text-stone-500">How did this land?</span>
        <button
          type="button"
          onClick={collapse}
          aria-label="Close feedback panel"
          className="text-xs text-stone-500 hover:text-stone-300 px-1 py-0.5"
        >
          Done
        </button>
      </div>
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
          onChange={(e) => onSliderChange(Number(e.target.value))}
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
              onChange={() => toggleCheck(label)}
            />
            {label}
          </label>
        ))}
      </div>
      <textarea
        value={note}
        onChange={(e) => {
          touchedRef.current = true
          setNote(e.target.value)
        }}
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
          disabled={saving}
          className="shrink-0 min-h-[36px] px-3 rounded-full bg-amber-600 text-amber-50 text-xs font-semibold disabled:opacity-40"
        >
          {saving ? 'Saving…' : 'Save feedback'}
        </button>
        {error && <span className="text-xs text-red-400">Couldn&apos;t save — try again.</span>}
      </div>
    </div>
  )
}
