/**
 * SymbolicStone — the Vision map's rock-garden stone.
 *
 * ONE `<svg>` subtree per stone (no defs/ids, so any number can share the
 * page): a smooth river-stone silhouette, a growth-state glyph, a thin
 * urgency ring only when the stone needs attention, and a strand-palette
 * color wash. Cairn stacks reuse this at smaller scale.
 *
 * Symbolic language:
 * - silhouette: river stone (rounded pebble), stone-gray base
 * - wash: deterministic strand-palette tint per project — every stone of a
 *   project shares a hue; landmarks stay neutral
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
const GLYPH_TONE = '#57534e'
const STONE_BASE = '#d6d3d1'

/** River-stone silhouette — smooth pebble, wider than tall. */
const STONE_PATH =
  'M9 38 C9 26 21 18 33 18 C46 18 56 27 55 38 C54 49 43 54 31 54 C19 54 9 49 9 38 Z'

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
      return <ellipse cx="32" cy="38" rx="4" ry="5.5" fill={GLYPH_TONE} stroke="none" />
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
  /** Rendered px size (square). */
  size?: number
  className?: string
  style?: CSSProperties
}

export function SymbolicStone({
  growth,
  kind,
  severity,
  fertilizerPulse,
  washColor,
  size = 64,
  className,
  style,
}: SymbolicStoneProps) {
  const glyph = glyphForGrowth(growth, kind)
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
      <path d={STONE_PATH} fill={STONE_BASE} />
      <path d={STONE_PATH} fill={washColor} opacity={0.38} />
      <ellipse cx="25" cy="28" rx="11" ry="5.5" fill="#ffffff" opacity={0.22} transform="rotate(-14 25 28)" />
      <Glyph glyph={glyph} />
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
