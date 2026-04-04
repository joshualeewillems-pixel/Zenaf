import { useCallback, useEffect, useRef, useState } from 'react'
import { VISION_EXECUTION_API } from '../vision-execution/types'

const STORAGE_PREFIX = 'atria.resonance.v1.'

export interface ResonanceSliderProps {
  responseId: string
  seatId?: string
  contextKind: 'council_seat' | 'zenaf_training' | 'perspective_workout'
  entityType: string
  entityId: string
  subjectPerspectiveId?: string
  onRated?: (score: number) => void
}

function storageKey(responseId: string): string {
  return `${STORAGE_PREFIX}${responseId}`
}

function readStoredScore(responseId: string): number | null {
  try {
    const raw = sessionStorage.getItem(storageKey(responseId))
    if (!raw) return null
    const n = Number.parseFloat(raw)
    if (!Number.isFinite(n)) return null
    return Math.min(1, Math.max(0, n))
  } catch {
    return null
  }
}

function writeStoredScore(responseId: string, score: number): void {
  try {
    sessionStorage.setItem(storageKey(responseId), String(score))
  } catch {
    /* ignore quota */
  }
}

function clearStoredScore(responseId: string): void {
  try {
    sessionStorage.removeItem(storageKey(responseId))
  } catch {
    /* ignore */
  }
}

function scoreFromClientX(track: HTMLDivElement, clientX: number): number {
  const r = track.getBoundingClientRect()
  if (r.width <= 0) return 0.5
  const x = Math.min(Math.max(clientX - r.left, 0), r.width)
  return x / r.width
}

/** Fill from 0 → thumb: red-leaning left of center, neutral at ~0.5, green right (matches --color-accent). */
function fillStyleForScore(d: number): { backgroundColor: string } {
  if (d < 0.5) {
    const depth = (0.5 - d) / 0.5
    const alpha = 0.38 + depth * 0.42
    return { backgroundColor: `rgba(200, 75, 85, ${alpha})` }
  }
  if (d > 0.5) {
    const depth = (d - 0.5) / 0.5
    const alpha = 0.38 + depth * 0.42
    return { backgroundColor: `rgba(107, 143, 113, ${alpha})` }
  }
  return { backgroundColor: 'rgba(120, 109, 92, 0.4)' }
}

export function ResonanceSlider({
  responseId,
  seatId,
  contextKind,
  entityType,
  entityId,
  subjectPerspectiveId,
  onRated,
}: ResonanceSliderProps) {
  const trackRef = useRef<HTMLDivElement | null>(null)
  const draggingRef = useRef(false)
  const [hover, setHover] = useState(false)
  const [committed, setCommitted] = useState(false)
  const [score, setScore] = useState(0.5)
  const [preview, setPreview] = useState<number | null>(null)

  useEffect(() => {
    const s = readStoredScore(responseId)
    if (s !== null) {
      setScore(s)
      setCommitted(true)
      setPreview(null)
    } else {
      setScore(0.5)
      setCommitted(false)
      setPreview(null)
    }
  }, [responseId])

  const display = preview !== null ? preview : score
  const showFill = committed || preview !== null

  const postRating = useCallback(
    async (finalScore: number) => {
      const sc = Math.min(1, Math.max(0, finalScore))
      writeStoredScore(responseId, sc)
      setScore(sc)
      setCommitted(true)
      setPreview(null)
      onRated?.(sc)
      try {
        const res = await fetch(`${VISION_EXECUTION_API}/resonance-ratings`, {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            entity_type: entityType,
            entity_id: entityId,
            score: sc,
            response_id: responseId,
            seat_id: seatId ?? null,
            context_kind: contextKind,
            subject_perspective_id: subjectPerspectiveId ?? null,
          }),
        })
        if (!res.ok) {
          /* keep local session state; server may retry later */
        }
      } catch {
        /* non-blocking */
      }
    },
    [contextKind, entityId, entityType, onRated, responseId, seatId, subjectPerspectiveId],
  )

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    const el = trackRef.current
    if (!el) return
    el.setPointerCapture(e.pointerId)
    draggingRef.current = true
    const s = scoreFromClientX(el, e.clientX)
    setPreview(s)
  }

  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!draggingRef.current || !trackRef.current) return
    setPreview(scoreFromClientX(trackRef.current, e.clientX))
  }

  const endDrag = (e: React.PointerEvent<HTMLDivElement>) => {
    const el = trackRef.current
    if (!el) return
    if (draggingRef.current) {
      try {
        el.releasePointerCapture(e.pointerId)
      } catch {
        /* ignore */
      }
      draggingRef.current = false
      const s = scoreFromClientX(el, e.clientX)
      void postRating(s)
    }
  }

  const fillPct = display * 100
  const fillStyle = fillStyleForScore(display)

  const showHandle = hover || committed || preview !== null

  const reset = (ev: React.MouseEvent) => {
    ev.stopPropagation()
    ev.preventDefault()
    clearStoredScore(responseId)
    setCommitted(false)
    setScore(0.5)
    setPreview(null)
  }

  return (
    <div
      className="mt-1.5 w-full select-none"
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => {
        setHover(false)
        if (!draggingRef.current) {
          setPreview(null)
        }
      }}
    >
      <div className="mx-auto flex w-full max-w-md items-center gap-2 sm:gap-3">
        <span className="w-11 shrink-0 text-right text-[9px] text-stone-500/75 tabular-nums sm:w-12">not me</span>
        <div
          ref={trackRef}
          role="slider"
          aria-valuemin={0}
          aria-valuemax={1}
          aria-valuenow={Math.round(display * 1000) / 1000}
          aria-label="Resonance"
          className={`relative h-1 min-w-0 flex-1 rounded-full transition-colors ${
            hover ? 'bg-stone-500/25' : 'bg-stone-600/15'
          }`}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
        >
          {showFill && (
            <div
              className="absolute left-0 top-0 h-full rounded-full pointer-events-none transition-[width,background-color] duration-75"
              style={{ width: `${fillPct}%`, ...fillStyle }}
            />
          )}
          {showHandle && (
            <div
              className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2 w-2.5 h-2.5 rounded-full border border-stone-600/80 bg-stone-200/90 shadow-sm pointer-events-none"
              style={{ left: `${fillPct}%` }}
            />
          )}
        </div>
        <span className="w-11 shrink-0 text-left text-[9px] text-stone-500/75 tabular-nums sm:w-12">exactly me</span>
        {committed && hover && (
          <button
            type="button"
            aria-label="Clear resonance rating"
            className="shrink-0 px-0.5 text-xs leading-none text-stone-500 hover:text-stone-300"
            onClick={reset}
          >
            ×
          </button>
        )}
      </div>
    </div>
  )
}
