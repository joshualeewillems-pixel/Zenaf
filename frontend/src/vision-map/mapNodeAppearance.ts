import type { ConditionState, GrowthState, MapEntityKind, MapNodePayload, WaterLevel } from './ontology'

function clamp01(x: number): number {
  return Math.max(0, Math.min(1, x))
}

/** Triad snapshot from graph build, or coarse fallback from legacy `water_level` only. */
export function resolveMapVisualTriadScalars(data: MapNodePayload): {
  water: number
  soil: number
  fruit: number
} {
  const t = data.map_visual_triad
  if (t && [t.water, t.soil, t.fruit].every((n) => typeof n === 'number' && Number.isFinite(n))) {
    return { water: clamp01(t.water), soil: clamp01(t.soil), fruit: clamp01(t.fruit) }
  }
  const wl = data.water_level ?? 'medium'
  const water = wl === 'high' ? 0.82 : wl === 'medium' ? 0.5 : 0.28
  return { water, soil: 0.45, fruit: 0.45 }
}

/** Water scalar for stone surface; stale pulls “dryer” without a heavy crack overlay. */
export function surfaceWater01ForMap(data: MapNodePayload): number {
  const { water } = resolveMapVisualTriadScalars(data)
  if (data.condition === 'stale') return clamp01(water - 0.14)
  return water
}

/** Four-step surface richness: dry / matte / normal / rich (wet stone read). */
export function mapSurfaceWaterClass(w01: number): string {
  if (w01 < 0.32) return 'map-surface-water-dry'
  if (w01 < 0.48) return 'map-surface-water-matte'
  if (w01 < 0.72) return 'map-surface-water-normal'
  return 'map-surface-water-rich'
}

/** DevTools / QA — which surface tier is active (matches `mapSurfaceWaterClass`). */
export function mapSurfaceWaterTier(w01: number): 'dry' | 'matte' | 'normal' | 'rich' {
  if (w01 < 0.32) return 'dry'
  if (w01 < 0.48) return 'matte'
  if (w01 < 0.72) return 'normal'
  return 'rich'
}

/** Subtle lower-body grounding from fruit / output scalar — keep quiet (not a badge). */
export function mapFruitMassClass(f01: number): string {
  if (f01 < 0.3) return ''
  if (f01 < 0.5) return 'map-fruit-mass-soft'
  if (f01 < 0.68) return 'map-fruit-mass-mid'
  return 'map-fruit-mass-firm'
}

/** Label contrast: pale task stone uses dark type; all other kinds use light type on dark material */
export type StoneTextTone = 'on-dark' | 'on-light'

export function stoneTextTone(kind: MapEntityKind): StoneTextTone {
  return kind === 'flower' ? 'on-light' : 'on-dark'
}

/**
 * Three layout tiers (fixed outer box — silhouette micro-variation is transform-only).
 * Large: initiative (tree). Medium: project (branch) + fruit. Small: idea (seed) + task (flower).
 */
export function entityOrganicClasses(kind: MapEntityKind): {
  outer: string
  shape: string
  fill: string
  glyph: string
} {
  switch (kind) {
    case 'tree':
      return {
        outer:
          'map-stone-node map-stone--large min-w-[280px] max-w-[340px] px-5 pt-3 pb-4 min-h-[15rem] w-[min(100%,340px)]',
        shape: 'map-stone-shape map-silhouette-tree map-rim-tree',
        fill: 'bg-gradient-to-b from-[#3f5349] from-0% via-[#2a382f] via-42% to-[#101714]',
        glyph: 'map-stone-glyph w-[5.5rem] h-[5.5rem]',
      }
    case 'branch':
      return {
        outer:
          'map-stone-node map-stone--medium min-w-[232px] max-w-[292px] px-4 pt-3 pb-4 min-h-[12.5rem] w-[min(100%,292px)]',
        shape: 'map-stone-shape map-silhouette-branch map-rim-branch',
        fill: 'bg-gradient-to-b from-[#3a3e45] from-0% via-[#25282e] via-44% to-[#0c0e12]',
        glyph: 'map-stone-glyph w-[4.25rem] h-[4.25rem]',
      }
    case 'flower':
      return {
        outer:
          'map-stone-node map-stone--small min-w-[176px] max-w-[228px] px-3.5 pt-2.5 pb-3 min-h-[10.25rem] w-[min(100%,228px)]',
        shape: 'map-stone-shape map-silhouette-flower map-rim-flower',
        fill: 'bg-gradient-to-b from-[#f4f1ea] from-0% via-[#e0dbd2] via-48% to-[#c4bdb2]',
        glyph: 'map-stone-glyph w-[3.35rem] h-[3.35rem]',
      }
    case 'fruit':
      return {
        outer:
          'map-stone-node map-stone--medium min-w-[220px] max-w-[272px] px-4 pt-3 pb-3.5 min-h-[11.75rem] w-[min(100%,272px)]',
        shape: 'map-stone-shape map-silhouette-fruit map-rim-fruit',
        fill: 'bg-gradient-to-b from-[#5e524a] from-0% via-[#3f3832] via-45% to-[#1c1916]',
        glyph: 'map-stone-glyph w-16 h-16',
      }
    case 'seed':
    default:
      return {
        outer:
          'map-stone-node map-stone--small min-w-[176px] max-w-[232px] px-3.5 pt-2.5 pb-3.5 min-h-[10.5rem] w-[min(100%,232px)]',
        shape: 'map-stone-shape map-silhouette-seed map-rim-seed',
        fill: 'bg-gradient-to-b from-[#5a4030] from-0% via-[#3d2a1f] via-44% to-[#140e0b]',
        glyph: 'map-stone-glyph w-[3.75rem] h-[3.75rem]',
      }
  }
}

export function hierarchyTitleClass(kind: MapEntityKind): string {
  const tone = stoneTextTone(kind)
  const base = 'font-semibold leading-snug tracking-tight'
  if (tone === 'on-light') {
    return `${base} text-[17px] text-[#12100e] [text-shadow:0_1px_0_rgba(255,255,255,0.65)]`
  }
  switch (kind) {
    case 'tree':
      return `${base} text-[23px] text-white [text-shadow:0_1px_2px_rgba(0,0,0,0.55),0_0_20px_rgba(0,0,0,0.25)]`
    case 'branch':
      return `${base} text-[20px] text-white [text-shadow:0_1px_2px_rgba(0,0,0,0.6),0_0_18px_rgba(0,0,0,0.28)]`
    case 'fruit':
      return `${base} text-[18px] text-[#faf7f2] [text-shadow:0_1px_2px_rgba(0,0,0,0.45)]`
    default:
      return `${base} text-[18px] text-white [text-shadow:0_1px_2px_rgba(0,0,0,0.55)]`
  }
}

/** Ontology row under glyph — secondary, quiet */
export function entitySubtitleClass(tone: StoneTextTone): string {
  const wrap = 'break-words [overflow-wrap:anywhere] uppercase tracking-[0.14em]'
  if (tone === 'on-light') {
    return `${wrap} text-[10px] font-medium text-stone-600/85 leading-tight`
  }
  return `${wrap} text-[10px] font-medium text-white/50 leading-tight`
}

/**
 * Short status line; omit when healthy + routine growth (icon + vitality already signal it).
 * Full values remain available via node `title` in EntityMapNode.
 */
export function compactNodeStatusSummary(growth: GrowthState, condition: ConditionState): string | null {
  if (condition === 'blocked') return 'Blocked'
  if (condition === 'teacher-vetoed') return 'Vetoed'
  if (condition === 'teacher-warned') return 'Warned'
  if (condition === 'stale') return 'Stale'
  if (growth === 'dormant') return 'Dormant'
  if (growth === 'pruned') return 'Pruned'
  if (growth === 'decaying') return 'At risk'
  if (growth === 'fruiting') return 'Fruiting'
  return null
}

export function entityCompactStatusClass(tone: StoneTextTone): string {
  if (tone === 'on-light') {
    return 'text-[10px] font-medium leading-tight text-stone-700/75'
  }
  return 'text-[10px] font-medium leading-tight text-amber-100/65'
}

/** Long identifiers (snake_case) wrap instead of overflowing the layout box. */
export function entityLabelTextClass(): string {
  return 'break-words [overflow-wrap:anywhere] hyphens-auto'
}

/** Inset-only stone face (rounded via border-radius + overflow) — no rectangular rings on the node wrapper. */
export function conditionShapeOverlayClass(c: ConditionState): string {
  switch (c) {
    case 'healthy':
      return 'map-cond-overlay map-cond-overlay--neutral'
    case 'blocked':
      return 'map-cond-overlay map-cond-overlay--blocked'
    case 'teacher-warned':
      return 'map-cond-overlay map-cond-overlay--warned'
    case 'teacher-vetoed':
      return 'map-cond-overlay map-cond-overlay--veto'
    case 'stale':
      return 'map-cond-overlay map-cond-overlay--stale-wash'
    default:
      return 'map-cond-overlay map-cond-overlay--neutral'
  }
}

/**
 * Outer wrapper only — no box-shadow “rings” here (rect follows layout box).
 * Water / pulse glow live on `.map-stone-shape` via `vitalityShapePulseClass`.
 */
export function vitalityOuterClass(growth: GrowthState, condition: ConditionState): string {
  const parts: string[] = []
  const quietLife = growth === 'pruned' || growth === 'dormant'

  if (condition === 'blocked') {
    parts.push('map-vitality-blocked')
  } else if (condition === 'teacher-vetoed') {
    parts.push('map-vitality-veto')
  } else if (condition === 'stale') {
    parts.push('map-vitality-stale')
  }

  if (condition !== 'blocked' && condition !== 'teacher-vetoed' && !quietLife) {
    if (growth === 'growing' || growth === 'germinating') {
      parts.push('map-vitality-grow')
    }
  }
  return parts.join(' ')
}

/**
 * Deprecated halo pulse — water reads via surface richness classes; keep empty to avoid
 * healthy-gated glow competing with condition stress.
 */
export function vitalityShapePulseClass(
  _growth: GrowthState,
  _condition: ConditionState,
  _water: WaterLevel,
): string {
  return ''
}
