import type { SVGProps } from 'react'
import type { MapGlyphTier } from './glyphTier'

/**
 * Initiative / project glyph in one place: fixed skeleton + tier overlays.
 * Reference: floating marks (not merged into branch strokes). Leafy = leaves only; flower/fruit tiers
 * replace leaves (no overlap). Bare = skeleton only.
 * viewBox matches prior initiative SVGs (48×48).
 */
const VB = '0 0 48 48'

const SW_SK = 2
const SW_FLOAT = 1.65

type Props = {
  tier: MapGlyphTier
  className?: string
} & Omit<SVGProps<SVGSVGElement>, 'viewBox'>

export function StructuralGrowthGlyph({ tier, className, ...rest }: Props) {
  const showLeaves = tier === 'leafy'
  const showStars = tier === 'flowerBud' || tier === 'flowerPair'
  const showFruitRings = tier === 'flowerTriple' || tier === 'flowerQuad'

  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox={VB} fill="none" className={className} aria-hidden {...rest}>
      <g stroke="currentColor" strokeWidth={SW_SK} strokeLinecap="round" strokeLinejoin="round">
        <path d="M24 30L24 12" />
        <path d="M14 30L34 30" />
        <path d="M24 12L16 8" />
        <path d="M24 12L32 8" />
        <path d="M24 20L18 18" />
        <path d="M24 20L30 18" />
      </g>

      {showLeaves && (
        <g stroke="currentColor" strokeWidth={SW_FLOAT} strokeLinecap="round" strokeLinejoin="round" fill="none">
          {/* Top — floats above Y; not attached */}
          <path d="M24 3.9c1.35 1.55 2.1 2.65 2.1 3.85c0 1.35-0.95 2.25-2.1 2.25s-2.1-0.9-2.1-2.25c0-1.2 0.75-2.3 2.1-3.85z" />
          <path d="M24 5.4v3.15" />
          {/* Near left secondary zone */}
          <path d="M14.8 12.4c1.05 1.2 1.65 2.05 1.65 3c0 1.05-0.75 1.75-1.65 1.75s-1.65-0.7-1.65-1.75c0-0.95 0.6-1.8 1.65-3z" />
          <path d="M14.8 13.65v2.45" />
          {/* Near right secondary zone */}
          <path d="M33.2 12.4c1.05 1.2 1.65 2.05 1.65 3c0 1.05-0.75 1.75-1.65 1.75s-1.65-0.7-1.65-1.75c0-0.95 0.6-1.8 1.65-3z" />
          <path d="M33.2 13.65v2.45" />
        </g>
      )}

      {showStars && (
        <g stroke="currentColor" strokeWidth={1.55} strokeLinejoin="round" fill="none">
          {/* Eight-point glints; explicit positions (floated, uneven) */}
          <path d="M24 3.3L24.924 4.576L26.2 5.5L24.924 6.424L24 7.7L23.076 6.424L21.8 5.5L23.076 4.576Z" />
          <path d="M15 12.3L15.924 13.576L17.2 14.5L15.924 15.424L15 16.7L14.076 15.424L12.8 14.5L14.076 13.576Z" />
          <path d="M33.4 13.05L34.324 14.326L35.6 15.25L34.324 16.174L33.4 17.45L32.476 16.174L31.2 15.25L32.476 14.326Z" />
        </g>
      )}

      {showFruitRings && (
        <g stroke="currentColor" strokeWidth={SW_FLOAT} fill="none">
          <circle cx={24} cy={5.35} r={2.48} />
          <circle cx={15.05} cy={14.5} r={1.58} />
          <circle cx={33.45} cy={15.35} r={1.5} />
        </g>
      )}
    </svg>
  )
}
