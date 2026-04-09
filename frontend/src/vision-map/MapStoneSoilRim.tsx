/**
 * Vision-map **soil rim** (brown perimeter): prompts cleanup where grounding is **lacking**.
 *
 * - **Triad `soil`** = grounding *present* (substrate depth / definition in data).
 * - **Soil rim** = visible *grounding deficit*. Triad soil stacks many partial signals (floor + brief/AI fields +
 *   server vitality), so “barely touched” rows often land **0.45–0.85** — linear `1 − soil` then looks uniformly
 *   faint. We remap deficit with a concave curve so mid-high *present* still reads a muddy cleanup cue. Inspect
 *   `data-map-soil` on `.map-stone-surface` to see the scalar driving this.
 *
 * Orthogonal channels (do not conflate):
 * - **Soil rim** (this) ← deficit from triad soil
 * - **Cracks** ← `effectiveConditionSeverity` (structural strain)
 * - **Gloss** ← `water_level` / triad water (stewardship, hydration read)
 * - **Fruit** ← output / yield scalar (unchanged elsewhere)
 *
 * Flow Spine Charter: rim intensity is the passive map leg of the same grounding read that ranks
 * “Expand steps” vs other invites (`assessFlow` / `buildFlowInputFromMapPayload` on the frontend).
 *
 * Rim **anisotropy** uses live `.map-stone-shape` size (`ResizeObserver`), blended toward initiative (tree) layout
 * reference for non-tree kinds so mud doesn’t read more dramatic than the tree. Size boost on small cards is
 * attenuated the same way so similar `triad.soil` matches tree rim weight.
 * Each rim SVG layer: stable hash flip (4-way) + rotation in ±12° (independent salts).
 */
import type { CSSProperties, FC, SVGProps } from 'react'
import { mapEntityNodeLayoutPx } from './mapEntityNodeLayout'
import type { MapEntityKind } from './ontology'
import RingTop1 from './soilSvgs/ring-top-1.svg?react'
import RingTop3 from './soilSvgs/ring-top-3.svg?react'

type SvgCmp = FC<SVGProps<SVGSVGElement>>

/** Ring layer `aspect-ratio` matches soil SVG viewBox (wider than tall). */
const RING_VIEWBOX_W = 208
const RING_VIEWBOX_H = 179
/** Native width ÷ height of the rim layer box — map mud-ring aspect to match stone mask. */
const RING_NATURAL_W_OVER_H = RING_VIEWBOX_W / RING_VIEWBOX_H
/** Per-layer tilt (stable hash); ±12° from nominal. */
const RIM_LAYER_ROT_MAX_DEG = 12
const UINT32_DENOM = 4294967296

type Props = {
  nodeId: string
  stoneTone: 'light' | 'dark'
  entityKind: MapEntityKind
  /**
   * Measured `.map-stone-shape` box (same element as `border-radius` mask). Drives rim width÷height vs ring art.
   * Parent should ResizeObserver this node and pass content size (px).
   */
  stoneShapeWidthPx: number
  stoneShapeHeightPx: number
  /** Triad soil 0–1 = grounding present; rim uses `1 - soil` as deficit */
  soil01: number
}

function clamp01(x: number): number {
  return Math.max(0, Math.min(1, x))
}

function hashString(s: string): number {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

const TREE_LAYOUT_PX = mapEntityNodeLayoutPx('tree')

/** Initiative (tree) min box edge — raw boost for smaller layout kinds. */
const TREE_MIN_EDGE_PX = Math.min(TREE_LAYOUT_PX.width, TREE_LAYOUT_PX.height)

/** Width÷height of tree RF/layout box — rim “expression” anchor for non-tree anisotropy. */
const TREE_REF_W_OVER_H = TREE_LAYOUT_PX.width / TREE_LAYOUT_PX.height

/**
 * How much non-tree measured aspect follows the live box vs tree ref (0 = tree ref only, 1 = full measured).
 */
const RIM_ASPECT_BLEND_FROM_MEASURED = 0.42

/**
 * How much of the small-card size boost to keep (tree = 1). Lower → closer to tree rim scale at the same soil.
 */
const RIM_SIZE_BOOST_ATTEN = 0.36

/** Tree stays reference sizing; other kinds scale up from smaller layout min-edges (raw). */
function rimKindBoostRaw(kind: MapEntityKind): number {
  if (kind === 'tree') return 1
  const { width, height } = mapEntityNodeLayoutPx(kind)
  return TREE_MIN_EDGE_PX / Math.min(width, height)
}

/** Attenuated boost so tasks/ideas don’t overpower tree at similar triad.soil. */
function rimKindBoost(kind: MapEntityKind): number {
  if (kind === 'tree') return 1
  const raw = rimKindBoostRaw(kind)
  return 1 + (raw - 1) * RIM_SIZE_BOOST_ATTEN
}

/**
 * Mud-ring aspect: tree uses measured box only; others blend measured W/H toward tree layout ref.
 */
function rimShapeXY(
  kind: MapEntityKind,
  stoneW: number,
  stoneH: number,
): Readonly<{ shapeX: number; shapeY: number }> {
  const w = Math.max(stoneW, 1e-6)
  const h = Math.max(stoneH, 1e-6)
  const measuredWOverH = w / h
  const targetWOverH =
    kind === 'tree'
      ? measuredWOverH
      : TREE_REF_W_OVER_H + (measuredWOverH - TREE_REF_W_OVER_H) * RIM_ASPECT_BLEND_FROM_MEASURED
  const shapeX = targetWOverH / RING_NATURAL_W_OVER_H
  return { shapeX, shapeY: 1 }
}

/**
 * Four discrete mirrors (identity, flip X, flip Y, both) — stable per salt.
 */
function rimLayerFlip(salt: string): Readonly<{ fx: number; fy: number }> {
  switch (hashString(salt) % 4) {
    case 0:
      return { fx: 1, fy: 1 }
    case 1:
      return { fx: -1, fy: 1 }
    case 2:
      return { fx: 1, fy: -1 }
    default:
      return { fx: -1, fy: -1 }
  }
}

/** [-RIM_LAYER_ROT_MAX_DEG, +RIM_LAYER_ROT_MAX_DEG] — independent of flip salt. */
function rimLayerRotationDeg(salt: string): number {
  const u = hashString(salt) / UINT32_DENOM
  return -RIM_LAYER_ROT_MAX_DEG + 2 * RIM_LAYER_ROT_MAX_DEG * u
}

/** Brown perimeter behind clipped stone face; only overshoot past the ellipse is visible. */
export function MapStoneSoilRim({
  nodeId,
  stoneTone,
  entityKind,
  stoneShapeWidthPx,
  stoneShapeHeightPx,
  soil01,
}: Props) {
  const soilPresent = clamp01(soil01)
  const linearDeficit = 1 - soilPresent
  /** Concave so mid “inflated” triad.soil still shows a cue; low soil stays near full drive. */
  const rimDrive = clamp01(Math.pow(linearDeficit, 0.68))
  const d = rimDrive
  const h = hashString(nodeId)
  const { shapeX, shapeY } = rimShapeXY(entityKind, stoneShapeWidthPx, stoneShapeHeightPx)
  const { fx: flipBackX, fy: flipBackY } = rimLayerFlip(`${nodeId}:soil-rim-back`)
  const { fx: flipFrontX, fy: flipFrontY } = rimLayerFlip(`${nodeId}:soil-rim-front`)
  const rotBackDeg = rimLayerRotationDeg(`${nodeId}:soil-rim-rot-back`)
  const rotFrontDeg = rimLayerRotationDeg(`${nodeId}:soil-rim-rot-front`)
  const swap = (h >> 17) % 2 === 0
  const BackCmp: SvgCmp = swap ? RingTop3 : RingTop1
  const FrontCmp: SvgCmp = swap ? RingTop1 : RingTop3

  /** High rimDrive (weak grounding) → wide, scaled ring; low soil (~0.15–0.25) should read clearly vs high soil (~0.9). */
  const scale = 1.008 + d * 0.34
  const kindBoost = rimKindBoost(entityKind)
  /** `kindBoost` is attenuated for non-tree so rim weight tracks triad like initiative. */
  const geomMean = scale * kindBoost
  const scaleX = geomMean * Math.sqrt(shapeX / shapeY)
  const scaleY = geomMean * Math.sqrt(shapeY / shapeX)
  const widthPct = 99 + d * 38
  const opacityBack = 0.12 + d * 0.83
  const opacityFront = 0.14 + d * 0.81

  const light =
    stoneTone === 'light'
      ? 'text-[#a0806a]'
      : 'text-[#9a7b62]'
  const dark =
    stoneTone === 'light'
      ? 'text-[#5a3d2e]'
      : 'text-[#4a3022]'

  /** Translate + rotate (±12° hash) + mirror scale. */
  const layer = (rotDeg: number, fx: number, fy: number): CSSProperties => ({
    position: 'absolute',
    left: '50%',
    top: '50%',
    width: `${widthPct.toFixed(2)}%`,
    aspectRatio: '208 / 179',
    maxWidth: 'none',
    pointerEvents: 'none',
    transform: `translate(-50%, -50%) rotate(${rotDeg.toFixed(3)}deg) scale(${(scaleX * fx).toFixed(4)}, ${(scaleY * fy).toFixed(4)})`,
    transformOrigin: 'center center',
  })

  return (
    <div
      className="map-stone-soil-rim pointer-events-none absolute inset-0 overflow-visible"
      style={{ borderRadius: 'inherit' }}
      aria-hidden
    >
      <div style={layer(rotBackDeg, flipBackX, flipBackY)}>
        <BackCmp
          className={`block h-full w-full ${light}`}
          style={{ opacity: opacityBack }}
          focusable={false}
          aria-hidden
        />
      </div>
      <div style={layer(rotFrontDeg, flipFrontX, flipFrontY)}>
        <FrontCmp
          className={`block h-full w-full ${dark}`}
          style={{ opacity: opacityFront }}
          focusable={false}
          aria-hidden
        />
      </div>
    </div>
  )
}
