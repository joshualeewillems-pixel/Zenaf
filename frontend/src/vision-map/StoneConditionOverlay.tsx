import type { ConditionState } from './ontology'

type StressCondition = 'blocked' | 'teacher-warned' | 'teacher-vetoed'

function stressKind(c: ConditionState): StressCondition | null {
  if (c === 'blocked') return 'blocked'
  if (c === 'teacher-warned') return 'teacher-warned'
  if (c === 'teacher-vetoed') return 'teacher-vetoed'
  return null
}

/**
 * SVG stress layer for non-stale condition problems — cracks / hatching / veto ring.
 * Stale reads via surface dryness + glyph fade only (plan: avoid overlapping vocabularies).
 */
export function StoneConditionOverlay({ condition }: { condition: ConditionState }) {
  const k = stressKind(condition)
  if (!k) return null

  return (
    <svg
      className="map-stone-stress-svg pointer-events-none absolute inset-0 z-[5] overflow-hidden rounded-[inherit]"
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
      aria-hidden
    >
      {k === 'blocked' ? (
        <g stroke="rgba(245, 200, 120, 0.55)" strokeWidth={1.4} strokeLinecap="round" fill="none">
          <path d="M12 28 L38 52 M22 72 L48 38 M58 18 L82 44 M52 78 L78 58" />
          <path d="M8 58 L32 40" opacity={0.7} />
        </g>
      ) : null}
      {k === 'teacher-warned' ? (
        <g stroke="rgba(251, 191, 36, 0.42)" strokeWidth={0.9} strokeLinecap="round" fill="none">
          <path strokeDasharray="3 5" d="M10 22 L90 22 M10 38 L90 38 M10 54 L90 54 M10 70 L90 70 M10 86 L90 86" />
          <path strokeDasharray="4 6" d="M18 10 L18 90 M34 10 L34 90 M50 10 L50 90 M66 10 L66 90 M82 10 L82 90" opacity={0.65} />
        </g>
      ) : null}
      {k === 'teacher-vetoed' ? (
        <g stroke="rgba(248, 113, 113, 0.62)" strokeWidth={2} strokeLinecap="round" fill="none">
          <path d="M22 22 L78 78 M78 22 L22 78" />
          <rect x="8" y="8" width="84" height="84" rx="10" fill="none" strokeWidth={1.5} opacity={0.55} />
        </g>
      ) : null}
    </svg>
  )
}
