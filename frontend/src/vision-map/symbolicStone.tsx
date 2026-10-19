/**
 * SymbolicStone — the Vision map's rock-garden stone.
 *
 * ONE `<svg>` subtree per stone (no defs/ids, so any number can share the
 * page): an irregular granite silhouette (4 hand-drawn variants, stable per
 * stone), speckles, a soft ground shadow, a growth-state glyph, a thin
 * urgency ring only when the stone needs attention, and a faint
 * strand-palette wash. Matte on purpose — no gloss highlights.
 * Cairn stacks reuse this at smaller scale.
 *
 * Symbolic language:
 * - silhouette: field stone — asymmetric, wider than tall, slight rotation
 * - granite: warm gray tones, deterministic per stone
 * - wash: faint strand-palette tint per project (subtle, not the whole stone)
 * - glyph (lifecycle): seed / sprout / sapling / bloom / fruit (+ wilted)
 * - ring: thin amber ring only when structural severity > 0 (calm, not an
 *   alarm); soft green ring when recently updated (fertilizer pulse)
 */
import type { CSSProperties } from 'react'
import type { ConditionSeverity, GrowthState, MapEntityKind, MapEntityRef } from './ontology'

export const STONE_SVG_VIEWBOX = '0 0 64 64'

/** Seven strand colors (living-tree/strands.ts) — the garden's palette. */
const STRAND_PALETTE = ['#c98f6a', '#7aa3b8', '#c9a86a', '#b983a8', '#9db87a', '#a88fc9', '#7ba889']
const NEUTRAL_WASH = '#a8a29e'
const URGENCY_RING = '#d9a441'
const PULSE_RING = '#86b89a'
const GLYPH_TONE = '#44403c'
const SPECKLE_TONE = '#292524'

/** Granite body tones — warm grays, deterministic per stone. */
const GRANITE_TONES = ['#8d8680', '#7b736b', '#9a9188', '#6e675f']

type StoneVariant = {
  body: string
  speckles: Array<[number, number, number]>
  /** Short matte top-edge light (not a gloss highlight). */
  topLight: string
}

const VARIANTS: StoneVariant[] = [
  {
    body: 'M10 40 C10 33 16 28 24 27 L38 26 C46 26 52 30 54 36 C55 42 50 47 42 49 L24 50 C16 50 10 46 10 40 Z',
    speckles: [
      [24, 36, 1.6],
      [38, 42, 1.2],
      [30, 44, 1.0],
      [44, 34, 1.4],
    ],
    topLight: 'M14 34 C18 30 24 28 30 27',
  },
  {
    body: 'M12 38 C12 31 18 26 26 26 C30 26 34 27 38 29 L50 34 C54 36 55 40 52 44 C48 48 40 50 30 50 L20 49 C14 47 12 43 12 38 Z',
    speckles: [
      [22, 38, 1.3],
      [36, 34, 1.7],
      [44, 42, 1.1],
      [28, 45, 1.0],
    ],
    topLight: 'M16 32 C20 28 26 26 32 27',
  },
  {
    body: 'M9 37 L16 29 L28 27 L42 28 L52 34 L54 41 L46 47 L28 50 L15 47 Z',
    speckles: [
      [20, 36, 1.5],
      [34, 40, 1.2],
      [46, 38, 1.0],
    ],
    topLight: 'M13 33 L20 29 L28 28',
  },
  {
    body: 'M8 41 C8 34 14 29 22 28 L34 27 C44 27 52 31 54 38 C55 44 49 48 40 49 L22 50 C14 50 8 46 8 41 Z',
    speckles: [
      [26, 34, 1.4],
      [40, 44, 1.6],
      [32, 42, 1.0],
      [48, 40, 1.2],
    ],
    topLight: 'M13 35 C17 31 23 29 29 28',
  },
]

function hash32(s: string): number {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

/** Stable strand-palette wash for a project/idea key; neutral when none. */
export function washColorFor(projectKey: string | null | undefined): string {
  if (!projectKey) return NEUTRAL_WASH
  return STRAND_PALETTE[hash32(projectKey) % STRAND_PALETTE.length]!
}

/** Project/idea key driving a stone's wash — stones of a project share a hue. */
export function washKeyForPayload(d: {
  kind: MapEntityKind
  ref: MapEntityRef
  parentRef?: MapEntityRef | null
}): string | null {
  if (d.kind === 'branch' || d.kind === 'cairn') {
    return d.ref.veType === 'project' ? d.ref.id : null
  }
  if (d.kind === 'flower') {
    const pid = d.ref.projectId
    return typeof pid === 'string' && pid ? pid : null
  }
  if (d.kind === 'fruit') {
    return d.parentRef?.veType === 'project' ? d.parentRef.id : null
  }
  if (d.kind === 'tree') return d.ref.veType === 'initiative' ? d.ref.id : null
  if (d.kind === 'seed') return d.ref.veType === 'idea' ? d.ref.id : null
  return null
}

export type StoneGlyph = 'seed' | 'sprout' | 'sapling' | 'bloom' | 'fruit' | 'wilted'

/** Lifecycle glyph. Outcome (fruit-kind) stones are always fruit. */
export function glyphForGrowth(growth: GrowthState, kind: MapEntityKind): StoneGlyph {
  if (kind === 'fruit') return 'fruit'
  switch (growth) {
    case 'dormant':
      return 'seed'
    case 'germinating':
      return 'sprout'
    case 'growing':
      return 'sapling'
    case 'fruiting':
      return 'bloom'
    case 'decaying':
      return 'wilted'
    case 'pruned':
      return 'seed'
    default:
      return 'seed'
  }
}

function Glyph({ glyph }: { glyph: StoneGlyph }) {
  const stroke = {
    stroke: GLYPH_TONE,
    strokeWidth: 2,
    fill: 'none',
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
  } as const
  switch (glyph) {
    case 'seed':
      return <ellipse cx="32" cy="38" rx="3.2" ry="4.4" fill={GLYPH_TONE} stroke="none" />
    case 'sprout':
      return (
        <g {...stroke}>
          <path d="M32 46 L32 37" />
          <path d="M32 40 C28 38 25 38 23.5 40 C26 42 29.5 42 32 40" />
          <path d="M32 40 C36 38 39 38 40.5 40 C38 42 34.5 42 32 40" />
        </g>
      )
    case 'sapling':
      return (
        <g {...stroke}>
          <path d="M32 47 L32 30" />
          <path d="M32 41 C28 39 25 39 23.5 41 C26 43 29.5 43 32 41" />
          <path d="M32 36 C36 34 39 34 40.5 36 C38 38 34.5 38 32 36" />
          <circle cx="32" cy="28" r="1.8" fill={GLYPH_TONE} stroke="none" />
        </g>
      )
    case 'bloom': {
      const petals = [0, 72, 144, 216, 288].map((deg) => (
        <ellipse
          key={deg}
          cx="32"
          cy="31"
          rx="2.8"
          ry="5"
          transform={`rotate(${deg} 32 37)`}
        />
      ))
      return (
        <g {...stroke}>
          {petals}
          <circle cx="32" cy="37" r="2.2" fill={GLYPH_TONE} stroke="none" />
        </g>
      )
    }
    case 'fruit':
      return (
        <g {...stroke}>
          <circle cx="32" cy="37" r="6.5" />
          <path d="M32 30.5 C32 28 33 27 35 26" />
          <path d="M35 26.5 C38 25 41 25 42.5 27 C40 29 37.5 29 35 26.5" />
        </g>
      )
    case 'wilted':
      return (
        <g {...stroke}>
          <path d="M32 46 C31 42 29 40 25 39" />
          <path d="M25 39 C23 41 23 43 24 44.5" />
        </g>
      )
  }
}

export type SymbolicStoneProps = {
  growth: GrowthState
  kind: MapEntityKind
  /** 0–3 structural severity — ring appears only when > 0. */
  severity: ConditionSeverity
  /** Recently updated — soft green ring when no urgency ring. */
  fertilizerPulse?: boolean
  washColor: string
  /** Stable per-stone key — picks the silhouette variant, granite tone and tilt. */
  variantSeed?: string
  /** Rendered px size (square). */
  size?: number
  /** Ground shadow ellipse. Disable for stones stacked in a tower —
      only the base stone touches the ground. Defaults to true. */
  groundShadow?: boolean
  className?: string
  style?: CSSProperties
}

export function SymbolicStone({
  growth,
  kind,
  severity,
  fertilizerPulse,
  washColor,
  variantSeed,
  size = 64,
  groundShadow = true,
  className,
  style,
}: SymbolicStoneProps) {
  const glyph = glyphForGrowth(growth, kind)
  const h = hash32(variantSeed ?? washColor)
  const variant = VARIANTS[h % VARIANTS.length]!
  const granite = GRANITE_TONES[(h >>> 4) % GRANITE_TONES.length]!
  const tilt = ((h >>> 8) % 13) - 6 // -6..+6 degrees
  const ring =
    severity > 0
      ? { color: URGENCY_RING, opacity: 0.45 + 0.18 * severity }
      : fertilizerPulse
        ? { color: PULSE_RING, opacity: 0.85 }
        : null
  return (
    <svg
      viewBox={STONE_SVG_VIEWBOX}
      width={size}
      height={size}
      className={className}
      style={style}
      role="img"
      aria-hidden
      data-glyph={glyph}
      data-severity={severity}
      data-wash={washColor}
    >
      {/* ground shadow — only when this stone touches the ground */}
      {groundShadow ? (
        <ellipse cx="32" cy="53" rx="21" ry="3.6" fill="#1c1917" opacity={0.16} />
      ) : null}
      <g transform={`rotate(${tilt} 32 40)`}>
        <path d={variant.body} fill={granite} />
        <path d={variant.body} fill={washColor} opacity={0.14} />
        {variant.speckles.map(([cx, cy, r], i) => (
          <circle key={i} cx={cx} cy={cy} r={r} fill={SPECKLE_TONE} opacity={0.22} />
        ))}
        <path
          d={variant.topLight}
          fill="none"
          stroke="#fafaf9"
          strokeWidth={2.4}
          strokeLinecap="round"
          opacity={0.13}
        />
        <Glyph glyph={glyph} />
      </g>
      {ring ? (
        <circle
          cx="32"
          cy="36"
          r="29"
          fill="none"
          stroke={ring.color}
          strokeWidth={1.6}
          opacity={ring.opacity}
        />
      ) : null}
    </svg>
  )
}
