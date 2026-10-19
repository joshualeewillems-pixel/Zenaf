import { useEffect, useState } from 'react'
import { apiBase } from '../apiBase'
import { voiceColor } from '../components/VoiceWeave'

/** Canonical seat order for the chip row. */
export const SEAT_ORDER = [
  'mentor',
  'champion',
  'guardian',
  'maverick',
  'ambassador',
  'conductor',
  'skeptic',
] as const

type SeatMeta = {
  /** Fellowship display names (honors rename unlocks), keyed by seat id. */
  names: Record<string, string>
  /** Training depth per seat, keyed by seat id. */
  depths: Record<string, number>
}

/**
 * Seat display names + training depth, from the same status endpoint the
 * Foundation console used. Tolerates failure — chips fall back to stock ids.
 */
export function useSeatMeta(): SeatMeta {
  const base = apiBase()
  const [meta, setMeta] = useState<SeatMeta>({ names: {}, depths: {} })
  useEffect(() => {
    let cancelled = false
    fetch(`${base}/council/archetypes/status`, { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (cancelled || !data) return
        const list = data.archetypes ?? data.voices ?? []
        if (!Array.isArray(list)) return
        const names: Record<string, string> = {}
        const depths: Record<string, number> = {}
        for (const a of list) {
          if (!a || typeof a.id !== 'string') continue
          names[a.id] = a.display_name ?? a.id
          depths[a.id] = typeof a.depth === 'number' ? a.depth : 0
        }
        setMeta({ names, depths })
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [base])
  return meta
}

/**
 * Voice chips — the seat switcher. Tapping a chip branches the ongoing
 * conversation to that seat; history carries across (one persistent
 * conversation per user, not isolated per-seat sessions).
 *
 * Depth rides on each chip as a thin bar — the training-depth signal from
 * the old card grid, kept subtle.
 */
export default function SeatChips({
  activeId,
  onSelect,
}: {
  activeId: string | null
  onSelect: (id: string) => void
}) {
  const { names, depths } = useSeatMeta()
  return (
    <div
      role="group"
      aria-label="Choose a voice"
      className="flex gap-2 overflow-x-auto pb-1 -mx-1 px-1"
    >
      {SEAT_ORDER.map((id) => {
        const color = voiceColor(id)
        const active = activeId === id
        const depth = depths[id] ?? 0
        return (
          <button
            key={id}
            type="button"
            onClick={() => onSelect(id)}
            aria-pressed={active}
            title={`${names[id] ?? id} — ${Math.round(depth)} depth`}
            className={`shrink-0 min-h-[44px] px-3 rounded-full border text-sm font-medium flex flex-col items-start justify-center gap-1 ${
              active ? 'bg-stone-800' : 'bg-stone-900/50 hover:bg-stone-800/50'
            }`}
            style={{
              borderColor: active ? color : undefined,
              borderLeftWidth: 3,
              borderLeftColor: color,
            }}
          >
            <span style={{ color }}>{names[id] ?? id}</span>
            <span
              className="w-12 h-1 rounded-full bg-stone-800 overflow-hidden"
              aria-hidden
            >
              <span
                className="block h-full rounded-full"
                style={{ width: `${Math.min(100, depth)}%`, background: color }}
              />
            </span>
          </button>
        )
      })}
    </div>
  )
}
