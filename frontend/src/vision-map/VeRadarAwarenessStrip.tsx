import { useCallback, useEffect, useState } from 'react'
import { VISION_EXECUTION_API } from '../vision-execution/types'
import type { RadarResponse } from '../vision-execution/types'
import {
  buildMostUrgentHint,
  buildRadarSemanticGroups,
  buildRadarStripSegments,
  type VeRadarBucketId,
} from '../vision-execution/veRadarAwareness'

const BUCKET_TITLE: Record<VeRadarBucketId, string> = {
  act_now: 'Attention — initiatives need owner, next step, or linked projects',
  blocked: 'Blocked — projects or tasks marked blocked',
  high_value_stalled: 'Stalled — high-value initiatives not active',
  unanchored: 'Unanchored — projects without an initiative',
  kill_candidates: 'Watch / kill — low-score initiatives',
  overcapacity: 'Over capacity — people over weekly hours',
  signals: 'Signals — meeting extraction and other signal rows',
}

export type VeRadarAwarenessStripProps = {
  /** Open Vision & Execution Radar tab; optional bucket scroll target. */
  onOpenVeRadar: (bucket?: VeRadarBucketId) => void
  /** Call when map refreshes VE projection data — refetch strip in sync. */
  refreshNonce?: number
}

export function VeRadarAwarenessStrip({ onOpenVeRadar, refreshNonce = 0 }: VeRadarAwarenessStripProps) {
  const [data, setData] = useState<RadarResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setErr(null)
    try {
      const res = await fetch(`${VISION_EXECUTION_API}/radar`, { credentials: 'include' })
      const json = (await res.json().catch(() => null)) as RadarResponse | null
      if (!res.ok) {
        setData(null)
        setErr('radar unavailable')
        return
      }
      setData(json && typeof json === 'object' ? json : null)
    } catch {
      setData(null)
      setErr('radar unavailable')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load, refreshNonce])

  const groups = buildRadarSemanticGroups(data)
  const segments = buildRadarStripSegments(groups)
  const hint = buildMostUrgentHint(groups)

  const onSegmentClick = (bucket: VeRadarBucketId) => {
    onOpenVeRadar(bucket)
  }

  const onOpenAll = () => {
    onOpenVeRadar(undefined)
  }

  return (
    <div className="flex flex-col gap-1 min-w-0 max-w-full">
      <div
        className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[11px] text-stone-400 min-h-[1.25rem]"
        title="Live counts from Vision & Execution radar API"
      >
        <span className="text-stone-500 shrink-0 uppercase tracking-wide">Exec</span>
        {loading ? (
          <span className="text-stone-500">…</span>
        ) : err ? (
          <button
            type="button"
            onClick={() => void load()}
            className="text-amber-500/90 hover:text-amber-400 underline-offset-2 hover:underline"
          >
            {err}
          </button>
        ) : segments.length === 0 ? (
          <button
            type="button"
            onClick={onOpenAll}
            className="text-stone-500 hover:text-stone-300 tabular-nums"
          >
            clear
          </button>
        ) : (
          <>
            {segments.map((s, i) => (
              <span key={s.bucket} className="flex items-center gap-x-1.5 shrink-0">
                {i > 0 ? <span className="text-stone-600" aria-hidden>|</span> : null}
                <button
                  type="button"
                  onClick={() => onSegmentClick(s.bucket)}
                  title={BUCKET_TITLE[s.bucket]}
                  className="tabular-nums text-stone-200 hover:text-amber-200/95 hover:underline underline-offset-2"
                >
                  {s.label} {s.count}
                </button>
              </span>
            ))}
            <span className="text-stone-600 mx-0.5" aria-hidden>|</span>
            <button
              type="button"
              onClick={onOpenAll}
              className="text-stone-500 hover:text-stone-300 shrink-0"
              title="Open full Radar tab"
            >
              all
            </button>
          </>
        )}
      </div>
      {hint ? <p className="text-[10px] text-stone-500 truncate">{hint}</p> : null}
    </div>
  )
}
