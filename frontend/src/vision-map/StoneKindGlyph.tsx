import type { CSSProperties } from 'react'
import type { ConditionSeverity, MapNodePayload } from './ontology'
import { FRUIT_LEAF_D, FRUIT_LEAF_SW, FRUIT_LEAF_VEIN_D } from './glyphs/DiamondFlowerGlyph'
import { MapEntityGlyphFromFruit, mapNodeKindToGlyphEntity } from './glyphs/MapEntityGlyph'
import { fruitGlowFilterCss, fruitGlowIntensity } from './glyphs/glyphFruitGlow'

type Kind = MapNodePayload['kind']

/** Pic-2 style: round fruit, gloss, pit, short stem + teardrop leaf (center x = 32). */
const fruitViewBox = '15 4 34 40'

const FRUIT_CX = 32
const FRUIT_CY = 27.55
const FRUIT_R = 8.22
const FRUIT_OUTLINE_SW = 1.75
const FRUIT_STEM_SW = 2
/** ~⅓ of fruit diameter — pic 2 short stem. */
const FRUIT_STEM_TOP = 13.7
/** ~¾ task-fruit leaf scale — reads smaller vs stem. */
const FRUIT_LEAF_SCALE_STONE = 1.82

/** Carve layer: filled blob only so offset transform does not draw a second ring (no “vesica” double outline). */
function OutcomeFruitCarveBlob() {
  return (
    <circle
      cx={FRUIT_CX}
      cy={FRUIT_CY}
      r={FRUIT_R + FRUIT_OUTLINE_SW * 0.45}
      fill="currentColor"
      stroke="none"
    />
  )
}

function OutcomeFruitForegroundMarkup() {
  const fruitTop = FRUIT_CY - FRUIT_R
  const leafAttachY = FRUIT_STEM_TOP + (fruitTop - FRUIT_STEM_TOP) * 0.38
  const swLeaf = FRUIT_LEAF_SW / FRUIT_LEAF_SCALE_STONE
  return (
    <g strokeLinecap="round" strokeLinejoin="round">
      <circle
        cx={FRUIT_CX}
        cy={FRUIT_CY}
        r={FRUIT_R}
        fill="none"
        stroke="currentColor"
        strokeWidth={FRUIT_OUTLINE_SW}
      />
      {/* Gloss — lighter, tighter so it stays crisp (single fg pass). */}
      <ellipse
        cx={28.65}
        cy={25.85}
        rx={2.35}
        ry={3.25}
        fill="currentColor"
        fillOpacity={0.12}
        stroke="none"
      />
      <ellipse
        cx={33.95}
        cy={24.1}
        rx={1.35}
        ry={1.95}
        fill="currentColor"
        fillOpacity={0.16}
        stroke="none"
      />
      <circle cx={32.05} cy={21.45} r={0.72} fill="currentColor" fillOpacity={0.22} stroke="none" />
      {/* Pit — slight vertical ellipse reads more “stone” than a perfect disk. */}
      <ellipse
        cx={FRUIT_CX}
        cy={32.05}
        rx={0.92}
        ry={1.18}
        fill="currentColor"
        stroke="none"
      />
      <path
        d={`M${FRUIT_CX} ${FRUIT_STEM_TOP}V${fruitTop}`}
        stroke="currentColor"
        strokeWidth={FRUIT_STEM_SW}
        fill="none"
      />
      <g
        transform={`translate(${FRUIT_CX} ${leafAttachY}) rotate(45) scale(${FRUIT_LEAF_SCALE_STONE})`}
      >
        <path d={FRUIT_LEAF_D} fill="none" stroke="currentColor" strokeWidth={swLeaf} />
        <path
          d={FRUIT_LEAF_VEIN_D}
          fill="none"
          stroke="currentColor"
          strokeWidth={swLeaf}
          strokeLinecap="round"
        />
      </g>
    </g>
  )
}

type Props = {
  kind: Kind
  className?: string
  growth?: MapNodePayload['growth']
  soil01?: number
  fruit01?: number
  conditionSeverity?: ConditionSeverity
}

/**
 * Vision Map node glyph: gold foreground + dark carve duplicate (offset up, slightly larger; scale nudges with fruit glow).
 * Initiative and project share one structural growth glyph; branch (project) rotates 90° CW.
 */
export function StoneKindGlyph({
  kind,
  className = '',
  growth: _growth = 'growing',
  soil01: _soil01 = 0.5,
  fruit01 = 0.45,
  conditionSeverity: _conditionSeverity = 0,
}: Props) {
  void _growth
  void _soil01
  void _conditionSeverity
  const entity = mapNodeKindToGlyphEntity(kind)
  const glowI = fruitGlowIntensity(fruit01)
  const glowCss = fruitGlowFilterCss(glowI)
  const carveScale = 1.028 + 0.028 * glowI
  const carveUpPx = 3 + 2.5 * glowI
  const carveTransform: CSSProperties = {
    transform: `translateY(-${carveUpPx}px) scale(${carveScale})`,
    transformOrigin: 'center center',
  }

  const branchRotate = kind === 'branch' ? '[&>svg]:rotate-90' : ''

  if (kind === 'fruit') {
    return (
      <div className={['relative isolate h-full w-full', className].filter(Boolean).join(' ')} aria-hidden>
        <svg
          viewBox={fruitViewBox}
          className="pointer-events-none absolute inset-0 h-full w-full"
          style={carveTransform}
          aria-hidden
        >
          <g className="map-stone-glyph-carve-svg">
            <OutcomeFruitCarveBlob />
          </g>
        </svg>
        <svg
          viewBox={fruitViewBox}
          className="relative z-[1] h-full w-full"
          style={glowCss ? { filter: glowCss } : undefined}
          aria-hidden
        >
          <g className="map-stone-glyph-fg-svg">
            <OutcomeFruitForegroundMarkup />
          </g>
        </svg>
      </div>
    )
  }

  if (!entity) {
    return null
  }

  const glyphClass = 'block h-full w-full max-h-full max-w-full'
  const layerClass = ['flex h-full w-full origin-center items-center justify-center', branchRotate]
    .filter(Boolean)
    .join(' ')

  return (
    <div className={['relative isolate', className].filter(Boolean).join(' ')} aria-hidden>
      <div
        className={[
          'map-stone-glyph-carve pointer-events-none absolute inset-0 flex items-center justify-center',
          layerClass,
        ].join(' ')}
        style={carveTransform}
      >
        <MapEntityGlyphFromFruit entity={entity} fruit01={fruit01} className={glyphClass} />
      </div>
      <div
        className={['map-stone-glyph-fg relative z-[1] flex items-center justify-center', layerClass].join(' ')}
        style={glowCss ? { filter: glowCss } : undefined}
      >
        <MapEntityGlyphFromFruit entity={entity} fruit01={fruit01} className={glyphClass} />
      </div>
    </div>
  )
}
