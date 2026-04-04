import { useEffect, useState } from 'react'
import { VISION_EXECUTION_API } from '../vision-execution/types'

type ResonancePatternsResponse = {
  total_ratings?: number
  escalation_signal?: {
    confidence?: number
    recommended_approach?: string
  }
}

function approachToPhrase(approach: string): string {
  switch (approach) {
    case 'exploration':
      return 'exploring'
    case 'recognition':
      return 'in recognition mode'
    case 'loop':
      return 'naming a recurring pattern'
    case 'avoidance':
      return 'keeping things gentle'
    case 'confrontation':
      return 'speaking plainly'
    default:
      return 'exploring'
  }
}

/**
 * Subtle Foundation hint: how Zenaf is calibrated from resonance ratings (no numeric score).
 */
export function ZenafInteractionCalibrationLine({
  enabled,
  refreshKey,
}: {
  enabled: boolean
  /** Bumps refetch when e.g. training thread grows (new ratings possible). */
  refreshKey?: number | string
}) {
  const [line, setLine] = useState<string | null>(null)

  useEffect(() => {
    if (!enabled) {
      setLine(null)
      return
    }
    let cancelled = false
    ;(async () => {
      try {
        const res = await fetch(`${VISION_EXECUTION_API}/resonance-patterns`, {
          credentials: 'include',
        })
        if (!res.ok) {
          if (!cancelled) setLine(null)
          return
        }
        const p = (await res.json()) as ResonancePatternsResponse
        const es = p.escalation_signal
        const n = typeof p.total_ratings === 'number' ? p.total_ratings : 0
        const conf = typeof es?.confidence === 'number' ? es.confidence : 0
        if (!es || conf <= 0.5 || n < 5) {
          if (!cancelled) setLine(null)
          return
        }
        const app = String(es.recommended_approach || 'exploration').trim()
        if (!cancelled) setLine(`Zenaf is ${approachToPhrase(app)}`)
      } catch {
        if (!cancelled) setLine(null)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [enabled, refreshKey])

  if (!line) return null
  return <p className="text-xs text-warm-white/40 pt-1">{line}</p>
}
