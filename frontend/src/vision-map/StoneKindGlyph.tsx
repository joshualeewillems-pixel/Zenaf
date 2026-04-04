import type { MapNodePayload } from './ontology'

type Kind = MapNodePayload['kind']

const vb = '0 0 64 64'

const S = {
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
}

/** Stroke-first mineral glyphs — carved / embedded, not colorful emoji */
export function StoneKindGlyph({ kind, className = '' }: { kind: Kind; className?: string }) {
  switch (kind) {
    case 'seed':
      return (
        <svg viewBox={vb} className={className} aria-hidden>
          <circle cx="32" cy="32" r="21" fill="none" {...S} opacity={0.36} strokeWidth={1.75} />
          <path
            d="M32 11c11.6 0 21 9.4 21 21s-9.4 21-21 21"
            fill="none"
            {...S}
            strokeWidth={2.35}
          />
        </svg>
      )
    case 'tree':
      return (
        <svg viewBox={vb} className={className} aria-hidden>
          <path d="M32 15 L45 38 H19 Z" fill="none" {...S} />
          <line x1="32" y1="38" x2="32" y2="50" {...S} strokeWidth={2.35} />
          <path d="M26 26h12M29 22h6" fill="none" {...S} opacity={0.5} strokeWidth={1.25} />
        </svg>
      )
    case 'branch':
      return (
        <svg viewBox={vb} className={className} aria-hidden>
          <path d="M17 47 L31 30 L47 19" fill="none" {...S} />
          <path d="M31 30 L41 38 M27 35 L21 27" fill="none" {...S} opacity={0.72} strokeWidth={1.6} />
        </svg>
      )
    case 'flower':
      return (
        <svg viewBox={vb} className={className} aria-hidden>
          <circle cx="32" cy="32" r="5" fill="currentColor" fillOpacity={0.11} stroke="none" />
          <ellipse cx="32" cy="19" rx="6.5" ry="9.5" fill="none" {...S} strokeWidth={1.85} />
          <ellipse cx="45" cy="32" rx="9.5" ry="6.5" fill="none" {...S} strokeWidth={1.85} />
          <ellipse cx="32" cy="45" rx="6.5" ry="9.5" fill="none" {...S} strokeWidth={1.85} />
          <ellipse cx="19" cy="32" rx="9.5" ry="6.5" fill="none" {...S} strokeWidth={1.85} />
        </svg>
      )
    case 'fruit':
      return (
        <svg viewBox={vb} className={className} aria-hidden>
          <path
            d="M32 14c-8.2 0-15 7.4-15 17.2 0 9.2 6.2 15.8 15 15.8s15-6.6 15-15.8C47 21.4 40.2 14 32 14z"
            fill="currentColor"
            fillOpacity={0.06}
            stroke="currentColor"
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d="M32 14v-6M27.5 10.5h9"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.5}
            strokeLinecap="round"
            opacity={0.62}
          />
        </svg>
      )
    default:
      return null
  }
}
