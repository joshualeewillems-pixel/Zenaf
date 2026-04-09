import type { CSSProperties, FC, SVGProps } from 'react'
import type { ConditionSeverity } from './ontology'
import Decal01 from './crackSvgs/decal-edge-01.svg?react'
import Decal02 from './crackSvgs/decal-edge-02.svg?react'
import Decal03 from './crackSvgs/decal-edge-03.svg?react'
import Decal04 from './crackSvgs/decal-edge-04.svg?react'
import Decal05 from './crackSvgs/decal-edge-05.svg?react'

type Props = {
  severity: ConditionSeverity
  nodeId: string
  stoneTone?: 'light' | 'dark'
}

type SvgCmp = FC<SVGProps<SVGSVGElement>>

const DECALS: readonly SvgCmp[] = [Decal01, Decal02, Decal03, Decal04, Decal05]

function fnv32(str: string, seed: number): number {
  let h = (2166136261 ^ seed) >>> 0
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i)
    h = Math.imul(h, 16777619) >>> 0
  }
  return h >>> 0
}

function shuffledIndices(count: number, nodeId: string, salt: number): number[] {
  const pool = [0, 1, 2, 3, 4]
  const seed = fnv32(nodeId, salt)
  for (let i = pool.length - 1; i > 0; i--) {
    const j = fnv32(`${nodeId}:${i}`, seed) % (i + 1)
    const tmp = pool[i]!
    pool[i] = pool[j]!
    pool[j] = tmp
  }
  return pool.slice(0, count)
}

type Edge = 0 | 1 | 2 | 3

/**
 * Uniform scale from edge anchor into the stone. Values >>1 so paths approach / reach the far rim.
 * (Previous 0.5–1.0 range visibly *shrank* decals — cracks never read as structural stress.)
 */
function baseReach(severity: ConditionSeverity): number {
  if (severity <= 1) return 2.35
  if (severity === 2) return 3.05
  return 3.85
}

function crackCountForSeverity(severity: ConditionSeverity): number {
  if (severity <= 1) return 3
  if (severity === 2) return 4
  return 5
}

function edgeForSlot(slot: number, edgeSpin: number): Edge {
  return ((edgeSpin + slot * 3) % 4) as Edge
}

function decalWrapperStyle(
  edge: Edge,
  posPct: number,
  jitterDeg: number,
  reach: number,
  armWidthPct: number,
): CSSProperties {
  const base: CSSProperties = {
    position: 'absolute',
    width: `${armWidthPct}%`,
    pointerEvents: 'none',
  }
  // Stretch more along the axis that runs into the stone (top/bottom → deeper vertically, sides → horizontally).
  const isVertical = edge === 0 || edge === 2
  const sx = reach * (isVertical ? 1.06 : 1.32)
  const sy = reach * (isVertical ? 1.34 : 1.04)
  const scale = `scale(${sx.toFixed(3)}, ${sy.toFixed(3)})`
  switch (edge) {
    case 0:
      return {
        ...base,
        top: 0,
        left: `${posPct}%`,
        transform: `translateX(-50%) rotate(${jitterDeg}deg) ${scale}`,
        transformOrigin: '50% 0%',
      }
    case 1:
      return {
        ...base,
        right: 0,
        top: `${posPct}%`,
        transform: `translateY(-50%) rotate(${90 + jitterDeg}deg) ${scale}`,
        transformOrigin: '100% 0%',
      }
    case 2:
      return {
        ...base,
        bottom: 0,
        left: `${posPct}%`,
        transform: `translateX(-50%) rotate(${180 + jitterDeg}deg) ${scale}`,
        transformOrigin: '50% 100%',
      }
    case 3:
    default:
      return {
        ...base,
        left: 0,
        top: `${posPct}%`,
        transform: `translateY(-50%) rotate(${-90 + jitterDeg}deg) ${scale}`,
        transformOrigin: '0% 0%',
      }
  }
}

type Decal = { key: string; patternIndex: number; wrapper: CSSProperties }

function buildDecals(severity: ConditionSeverity, nodeId: string): Decal[] {
  const n = crackCountForSeverity(severity)
  const patternIx = shuffledIndices(n, nodeId, 0x51ed)
  const h1 = fnv32(nodeId, 0x2f09)
  const h2 = fnv32(nodeId, 0xb8a3)
  const h3 = fnv32(nodeId, 0xcafe)
  const base = baseReach(severity)
  const edgeSpin = h1 % 4

  const out: Decal[] = []
  for (let i = 0; i < n; i++) {
    const pi = patternIx[i]!
    const edge = edgeForSlot(i, edgeSpin)
    const pos = 14 + ((fnv32(`${nodeId}:slot${i}`, h2 + i) % 72))
    const jitter = (fnv32(`${nodeId}:jit${i}`, h3 + i) % 13) - 6
    const arm = 26 + (fnv32(`${nodeId}:arm${i}`, h1 + i) % 12) + (severity >= 2 ? 4 : 0)
    const reach = base * (0.94 + ((fnv32(`${nodeId}:reach${i}`, h2 ^ i) % 13) / 100))
    out.push({
      key: `c${i}`,
      patternIndex: pi,
      wrapper: decalWrapperStyle(edge, pos, jitter, reach, arm),
    })
  }
  return out
}

/**
 * Foreground crack ink must be **fully opaque** (`currentColor` on SVG paths). Translucent rgba was
 * compositing with the ghost + stone and reading as muddy grey instead of a sharp black line.
 */
function crackColor(stoneTone: 'light' | 'dark'): string {
  return stoneTone === 'light' ? '#161412' : '#070605'
}

/**
 * Ghost uses opaque rgb + layer `opacity` only (no alpha in `color`) so it doesn’t double-soften with fg.
 */
function crackGhostStyle(stoneTone: 'light' | 'dark', severity: ConditionSeverity): { color: string; opacity: number } {
  if (stoneTone === 'dark') {
    return { color: '#ffffff', opacity: 0.38 + severity * 0.07 }
  }
  return { color: '#2c2622', opacity: 0.4 + severity * 0.055 }
}

function crackGhostOffsetPx(severity: ConditionSeverity, slot: number, nodeId: string): { ox: number; oy: number } {
  const h = fnv32(`${nodeId}:ghost${slot}`, 0x51ab)
  const base = 0.85 + severity * 0.55
  const ax = (h % 7) - 3
  const ay = ((h >> 3) % 7) - 3
  const ox = base + ax * 0.35
  const oy = base * 0.75 + ay * 0.35
  return { ox: ox * 0.5, oy: oy * 0.5 }
}

/**
 * Edge-anchored crack decals — **structural condition** (`conditionSeverity`), not triad soil or water.
 * Severity scales count, reach, and ghost strength toward center.
 */
export function StoneCrackOverlay({ severity, nodeId, stoneTone = 'dark' }: Props) {
  if (severity <= 0) return null

  const decals = buildDecals(severity, nodeId)
  /** Full opacity so opaque crack colors aren’t pre-multiplied grey by the stack. */
  const stackOpacity = 1
  const tint = crackColor(stoneTone)
  const ghost = crackGhostStyle(stoneTone, severity)

  return (
    <div
      className="map-stone-crack-vector-stack pointer-events-none absolute inset-0 z-[6] overflow-hidden rounded-[inherit]"
      style={{ opacity: stackOpacity }}
      aria-hidden
    >
      {decals.map((d, i) => {
        const Svg = DECALS[d.patternIndex]!
        const { ox, oy } = crackGhostOffsetPx(severity, i, nodeId)
        return (
          <div key={d.key} className="map-stone-crack-decal" style={d.wrapper}>
            <div
              className="map-stone-crack-ghost pointer-events-none absolute inset-0 z-[1] select-none"
              style={{
                color: ghost.color,
                opacity: ghost.opacity,
                transform: `translate(${ox.toFixed(2)}px, ${oy.toFixed(2)}px)`,
              }}
              aria-hidden
            >
              <Svg className="block h-auto w-full" focusable="false" aria-hidden />
            </div>
            <div
              className="map-stone-crack-fg pointer-events-none relative z-[20] select-none"
              style={{ color: tint }}
            >
              <Svg className="block h-auto w-full" focusable="false" aria-hidden />
            </div>
          </div>
        )
      })}
    </div>
  )
}
