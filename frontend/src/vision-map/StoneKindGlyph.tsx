import type { MapNodePayload } from './ontology'
import { MapEntityGlyphFromFruit, mapNodeKindToGlyphEntity } from './glyphs/MapEntityGlyph'

type Kind = MapNodePayload['kind']

const vb = '0 0 64 64'

type Props = {
  kind: Kind
  className?: string
  growth?: MapNodePayload['growth']
  soil01?: number
  fruit01?: number
  condition?: MapNodePayload['condition']
}

function glyphOpacity(
  growth: MapNodePayload['growth'],
  condition: MapNodePayload['condition'],
): number {
  let o = 0.82
  switch (growth) {
    case 'dormant':
    case 'pruned':
      o = 0.32
      break
    case 'germinating':
      o = 0.48
      break
    case 'growing':
      o = 0.88
      break
    case 'fruiting':
      o = 0.93
      break
    case 'decaying':
      o = 0.66
      break
    default:
      o = 0.78
  }
  if (condition === 'stale') o *= 0.72
  return o
}

function glyphStrokeScale(soil01: number): number {
  const coherence = Math.max(0, Math.min(1, soil01))
  return 0.62 + 0.58 * coherence
}

/**
 * Vision Map node glyph: one centered asset per node, tier from `fruit01`.
 * SVG sources: `glyphs/assets/*.svg` (replace files with approved traces; use `currentColor` for tint).
 */
export function StoneKindGlyph({
  kind,
  className = '',
  growth = 'growing',
  soil01 = 0.5,
  fruit01 = 0.45,
  condition = 'healthy',
}: Props) {
  const opacity = glyphOpacity(growth, condition)
  const sc = glyphStrokeScale(soil01)
  const entity = mapNodeKindToGlyphEntity(kind)

  if (kind === 'fruit') {
    return (
      <svg viewBox={vb} className={className} style={{ opacity }} aria-hidden>
        <g transform={`translate(32,32) scale(${sc.toFixed(3)}) translate(-32,-32)`}>
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
        </g>
      </svg>
    )
  }

  if (!entity) {
    return null
  }

  return (
    <div className={className} style={{ opacity }} aria-hidden>
      <div
        className="flex h-full w-full origin-center items-center justify-center"
        style={{ transform: `scale(${sc.toFixed(3)})` }}
      >
        <MapEntityGlyphFromFruit
          entity={entity}
          fruit01={fruit01}
          className="block h-full w-full max-h-full max-w-full [&>svg]:h-full [&>svg]:w-full [&>svg]:max-h-full [&>svg]:max-w-full"
        />
      </div>
    </div>
  )
}
