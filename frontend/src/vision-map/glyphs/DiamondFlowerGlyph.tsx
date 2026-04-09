import type { ReactNode, SVGProps } from 'react'
import type { MapGlyphTier } from './glyphTier'

const VB = '6 4 36 36'
const SW = 1.75
const STEM = 2
const LEAF = 1.5

/** Flower center (joint): all diamond bottom tips + stem top meet here. */
const CX = 24
const CY = 16

/**
 * Half-length along vertical axis: joint → waist = h, waist → top tip = h (tip-to-tip height = 2h).
 * Width at waist = h so full width is half of full height (tall rhombus).
 */
const MAIN_H = 4.35

/** Task bare / leafy: joint sits lower so stem is shorter and the crown is visually heavier. */
const CY_COMPACT = 21.35
const MAIN_H_COMPACT = 5.05

/**
 * Rhombus in local space: bottom tip at (0,0), top at (0, -2h).
 * Waist half-width = h/2 → full width h = (2h)/2 (half as wide as tall).
 */
function diamondPathFromJoint(h: number): string {
  const w = h / 2
  return `M0 0 L${w} ${-h} L0 ${-2 * h} L${-w} ${-h} Z`
}

const STEM_FOOT = 36

/** Side leaf rides on the lower ~60% of the stem so it stays readable when the joint moves. */
function stemAndLeaf(jointY: number = CY) {
  const leafY = jointY + (STEM_FOOT - jointY) * 0.63
  return (
    <>
      <path
        d={`M${CX} ${jointY}V${STEM_FOOT}`}
        stroke="currentColor"
        strokeWidth={STEM}
        strokeLinecap="round"
      />
      <path d={`M${CX} ${leafY}L${CX - 4} ${leafY - 1.7}`} stroke="currentColor" strokeWidth={LEAF} strokeLinecap="round" />
    </>
  )
}

type RadialDiamondsProps = {
  anglesDeg: number[]
  h: number
  strokeWidth: number
  /** Flower/stem joint; defaults to `CY`. */
  jointY?: number
}

/** All diamonds share bottom tip at origin after translate(CX,jointY); each arm is rotate(angle) only. */
function RadialDiamonds({ anglesDeg, h, strokeWidth, jointY = CY }: RadialDiamondsProps) {
  const d = diamondPathFromJoint(h)
  return (
    <g transform={`translate(${CX} ${jointY})`} stroke="currentColor" strokeWidth={strokeWidth} strokeLinejoin="miter">
      {anglesDeg.map((deg, i) => (
        <g key={i} transform={`rotate(${deg} 0 0)`}>
          <path d={d} fill="none" />
        </g>
      ))}
    </g>
  )
}

/** Stage 1: vertical bud axis + optional inner spine (local, unrotated arm). */
function BudInnerSpine({ h, jointY = CY }: { h: number; jointY?: number }) {
  const y0 = -0.35 * (2 * h)
  const y1 = -0.82 * (2 * h)
  return (
    <g transform={`translate(${CX} ${jointY})`}>
      <path d={`M0 ${y0}V${y1}`} stroke="currentColor" strokeWidth={1.35} strokeLinecap="round" />
    </g>
  )
}

/** Task bare — compact stem, larger single diamond + spine. */
function Stage1TaskCompact() {
  return (
    <>
      <RadialDiamonds anglesDeg={[0]} h={MAIN_H_COMPACT} strokeWidth={SW} jointY={CY_COMPACT} />
      <BudInnerSpine h={MAIN_H_COMPACT} jointY={CY_COMPACT} />
      {stemAndLeaf(CY_COMPACT)}
    </>
  )
}

/** Task leafy — compact stem, larger V pair. */
function Stage2TaskCompact() {
  return (
    <>
      <RadialDiamonds anglesDeg={[-30, 30]} h={MAIN_H_COMPACT} strokeWidth={SW} jointY={CY_COMPACT} />
      {stemAndLeaf(CY_COMPACT)}
    </>
  )
}

/** Stage 4 — diagonal radial (NE / NW / SW / SE): whole quad rotated 45° from cardinals. */
function Stage4Main() {
  return (
    <>
      <RadialDiamonds anglesDeg={[45, 135, 225, 315]} h={MAIN_H} strokeWidth={SW} />
      {stemAndLeaf()}
    </>
  )
}

/** Teardrop at origin: narrow tip at (0,-tipY), wide base near stem junction; same language as `StructuralGrowthGlyph` leaves. */
export const FRUIT_LEAF_D =
  'M0 -3.95c0.62 0.72 0.98 1.22 0.98 1.78c0 0.62-0.45 1.02-0.98 1.02s-0.98-0.4-0.98-1.02c0-0.56 0.36-1.06 0.98-1.78z'
export const FRUIT_LEAF_VEIN_D = 'M0 -2.88V-0.5'
/** Target stroke after `scale(FRUIT_LEAF_SCALE)` — pre-scale width keeps line weight in family with other strokes. */
export const FRUIT_LEAF_SW = 1.38
const FRUIT_LEAF_SCALE = 2.625
/** Reference stem top for computing shortened upper stem (2/3 of previous segment length). */
const FRUIT_STEM_TOP_REF = 13.35

/** Task fruiting — stem from above, 45° teardrop leaf, outlined fruit + solid gloss dots; peduncle to foot for stone alignment. */
function TaskFruitTierGlyph() {
  const fx = 24
  const fy = 27.1
  const fr = 7.38
  const fruitTop = fy - fr
  const prevStemLen = fruitTop - FRUIT_STEM_TOP_REF
  const stemLen = prevStemLen * (2 / 3)
  const stemTop = fruitTop - stemLen
  const leafAttachY = stemTop + stemLen * 0.4
  const swLeaf = FRUIT_LEAF_SW / FRUIT_LEAF_SCALE
  return (
    <g strokeLinecap="round" strokeLinejoin="round">
      <path d={`M${fx} ${stemTop}V${fruitTop}`} stroke="currentColor" strokeWidth={STEM} fill="none" />
      <g transform={`translate(${fx} ${leafAttachY}) rotate(45) scale(${FRUIT_LEAF_SCALE})`}>
        <path d={FRUIT_LEAF_D} fill="none" stroke="currentColor" strokeWidth={swLeaf} />
        <path d={FRUIT_LEAF_VEIN_D} fill="none" stroke="currentColor" strokeWidth={swLeaf} strokeLinecap="round" />
      </g>
      <circle cx={fx} cy={fy} r={fr} fill="none" stroke="currentColor" strokeWidth={SW} />
      <circle cx={20.65} cy={23.95} r={1.22} fill="currentColor" stroke="none" />
      <circle cx={22.62} cy={22.55} r={0.86} fill="currentColor" stroke="none" />
      <circle cx={20.05} cy={25.25} r={0.58} fill="currentColor" stroke="none" />
      <path d={`M${fx} ${fy + fr}V${STEM_FOOT}`} stroke="currentColor" strokeWidth={STEM} fill="none" />
    </g>
  )
}

type Props = { taskTier: MapGlyphTier; className?: string } & Omit<SVGProps<SVGSVGElement>, 'viewBox'>

/**
 * Task (flower) stones: `taskTier` from fruit scalar — bare / leafy compact diamonds; flowering = 4-diamond;
 * fruiting = circle + gloss + stem + teardrop leaf.
 */
export function DiamondFlowerGlyph({ taskTier, className, ...rest }: Props) {
  let body: ReactNode = null
  switch (taskTier) {
    case 'bare':
      body = <Stage1TaskCompact />
      break
    case 'leafy':
      body = <Stage2TaskCompact />
      break
    case 'flowerBud':
    case 'flowerPair':
      body = <Stage4Main />
      break
    case 'flowerTriple':
    case 'flowerQuad':
      body = <TaskFruitTierGlyph />
      break
  }

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox={VB}
      fill="none"
      className={className}
      aria-hidden
      {...rest}
    >
      {body}
    </svg>
  )
}
