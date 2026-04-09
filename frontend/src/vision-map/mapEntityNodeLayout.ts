import type { MapEntityKind } from './ontology'

/**
 * React Flow `width` / `height` for entity stones — aligned with `entityOrganicClasses` min-w/min-h
 * so the RF wrapper matches the painted `.map-stone-node` box (edges, selection, spacing vs. visuals).
 */
export function mapEntityNodeLayoutPx(kind: MapEntityKind): Readonly<{ width: number; height: number }> {
  switch (kind) {
    case 'tree':
      return { width: 308, height: 252 }
    case 'branch':
      return { width: 262, height: 208 }
    case 'flower':
      return { width: 202, height: 172 }
    case 'fruit':
      return { width: 246, height: 198 }
    case 'seed':
      return { width: 204, height: 176 }
  }
}

/** When kind is unknown (viewport math only) — mid-size stone */
export const MAP_ENTITY_FALLBACK_LAYOUT_PX = { width: 258, height: 210 } as const
