import type { SVGProps } from 'react'

export type IdeaEmergenceStage = 1 | 2 | 3 | 4

/** Shared with flower glyphs so scale reads consistently on stones. */
const VB = '6 4 36 36'

const SW_SEED = 1.85
const SW_SPLIT = 1.35
const SW_SOIL = 1.65
const SW_SOIL_SOFT = 1.35
const SW_STEM = 2
const SW_LEAF = 1.45

/** Stem / mound peak — slight bias, not dead-center symmetry. */
const SX = 23.9

/** Flat wavy baseline — stages 1–2: ground only, seed floats above. */
const SOIL_FLAT =
  'M10.4 34.42C14.2 33.62 18.6 34.48 22.8 33.92C26.4 33.45 30.2 34.08 33.8 33.78C36.2 33.58 38.4 34.15 40.2 34.05'

/**
 * Stage 3 — ground **above** the seed (smaller y): surface sits over the oval; seed reads as below grade.
 * Slight dip (larger y) at `SX` where the stem pierces upward.
 */
const SOIL_STAGE3 =
  'M10.2 26.05C14.5 25.88 19.2 26.35 22.8 25.92C23.6 26.42 24.2 26.48 25.2 25.98C28.5 25.82 33.2 26.22 39 26.02'

/** Stage 3 stem base — where soil crosses `SX` (dip under sprout). */
const STAGE3_SOIL_AT_STEM = 26.42

/**
 * Raised center mound — stage 4: stem meets peak near bottom of frame.
 */
const SOIL_MOUND =
  'M9.6 34.55C15.2 34.35 19.2 33.55 23.4 32.62C27.8 33.52 32.8 34.38 38.6 34.52'

/** Y at mound summit (approx.), for stage-4 stem base. */
const MOUND_PEAK_Y = 32.62

function seedOvalPath(cx: number, cy: number, rx: number, ry: number): string {
  const rxL = rx * 0.94
  const rxR = rx * 1.06
  const ryT = ry * 0.92
  const ryB = ry * 1.08
  return [
    `M${cx - rxL} ${cy}`,
    `C${cx - rxL} ${cy - ryT * 0.58} ${cx - rxL * 0.42} ${cy - ryT} ${cx} ${cy - ryT}`,
    `C${cx + rxR * 0.44} ${cy - ryT} ${cx + rxR} ${cy - ryT * 0.52} ${cx + rxR} ${cy}`,
    `C${cx + rxR} ${cy + ryB * 0.5} ${cx + rxR * 0.4} ${cy + ryB} ${cx} ${cy + ryB}`,
    `C${cx - rxL * 0.38} ${cy + ryB} ${cx - rxL} ${cy + ryB * 0.52} ${cx - rxL} ${cy}`,
    'Z',
  ].join('')
}

/** Slight horizontal wave through seed midline (germination read, not a ruler-straight cut). */
function seedSplitPath(cx: number, cy: number, rx: number): string {
  const x0 = cx - rx * 0.72
  const x1 = cx + rx * 0.74
  return `M${x0} ${cy - 0.15}Q${cx} ${cy + 0.35} ${x1} ${cy + 0.1}`
}

type Props = { stage: IdeaEmergenceStage; className?: string } & Omit<SVGProps<SVGSVGElement>, 'viewBox'>

/**
 * Idea (seed) emergence — bottom-weighted, soil as anchor, no whole-glyph transform.
 *
 * Format (tier mapping in `MapEntityGlyph`):
 * 1 Resting — flat soil, seed above gap, nothing else. (Idea `bare` tier)
 * 2 Sprout — same float; seed midline curve; short stem from oval top + one leaf (still above soil). (`leafy`)
 * 3 Grounded — soil line **above** the seed; stem up from surface; seed sits below grade + one leaf. (flowering band)
 * 4 Established — mound only; stem from mound peak; no seed; several small leaves along stem. (Idea fruiting band)
 */
export function IdeaSeedEmergenceGlyph({ stage, className, ...rest }: Props) {
  // Stages 1–2: same floating seed placement.
  const seedFloat = { cx: SX, cy: 26.35, rx: 8.15, ry: 4.72 }
  // Stage 3: oval mostly below the raised soil line (see SOIL_STAGE3 y ~25.9–26.5).
  const seedGround = { cx: SX, cy: 31.85, rx: 7.9, ry: 4.45 }
  const topFloat = seedFloat.cy - seedFloat.ry * 0.92

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox={VB}
      fill="none"
      className={className}
      aria-hidden
      {...rest}
    >
      <g stroke="currentColor" strokeLinecap="round" strokeLinejoin="round">
        {stage <= 2 ? (
          <path d={SOIL_FLAT} strokeWidth={SW_SOIL} />
        ) : stage === 3 ? (
          <path d={SOIL_STAGE3} strokeWidth={SW_SOIL} />
        ) : (
          <path d={SOIL_MOUND} strokeWidth={SW_SOIL_SOFT} strokeOpacity={0.92} />
        )}

        {stage === 1 && (
          <path d={seedOvalPath(seedFloat.cx, seedFloat.cy, seedFloat.rx, seedFloat.ry)} strokeWidth={SW_SEED} />
        )}

        {stage === 2 && (
          <>
            <path d={`M${SX} ${topFloat}V16.35`} strokeWidth={SW_STEM} />
            <path d={seedOvalPath(seedFloat.cx, seedFloat.cy, seedFloat.rx, seedFloat.ry)} strokeWidth={SW_SEED} />
            <path d={seedSplitPath(seedFloat.cx, seedFloat.cy, seedFloat.rx)} strokeWidth={SW_SPLIT} />
            <path d="M23.85 16.55L20.4 14.85" strokeWidth={SW_LEAF} />
          </>
        )}

        {stage === 3 && (
          <>
            <path d={`M${SX} ${STAGE3_SOIL_AT_STEM}V11.6`} strokeWidth={SW_STEM} />
            <path d={seedOvalPath(seedGround.cx, seedGround.cy, seedGround.rx, seedGround.ry)} strokeWidth={SW_SEED} />
            <path d="M24.05 14.1L27.35 12.45" strokeWidth={SW_LEAF} />
          </>
        )}

        {stage === 4 && (
          <>
            <path d={`M${SX} ${MOUND_PEAK_Y}V9.85`} strokeWidth={SW_STEM} />
            <path d="M24.05 22.6L20.85 20.95" strokeWidth={SW_LEAF} />
            <path d="M24.1 19.15L27.5 17.65" strokeWidth={SW_LEAF} />
            <path d="M23.95 15.4L21.2 13.65" strokeWidth={SW_LEAF} />
            <path d="M24.05 12.1L26.85 10.55" strokeWidth={SW_LEAF} />
          </>
        )}
      </g>
    </svg>
  )
}
