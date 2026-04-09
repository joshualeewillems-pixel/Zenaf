/**
 * localStorage persistence for Vision map manual stone positions + viewport.
 * Scoped by account/workspace context + projection id so backend sync can be added later.
 */

export const VISION_MAP_LAYOUT_SCHEMA_VERSION = 1 as const

export type VisionMapLayoutProjectionId = 'live_ve'

export type VisionMapPersistedViewport = {
  x: number
  y: number
  zoom: number
}

export type VisionMapPersistedLayoutV1 = {
  v: typeof VISION_MAP_LAYOUT_SCHEMA_VERSION
  projection: VisionMapLayoutProjectionId
  /** Entity node ids (ideas/initiatives/projects/tasks) with user-dragged positions. */
  positions: Record<string, { x: number; y: number }>
  /** Last pan/zoom from React Flow. */
  viewport: VisionMapPersistedViewport | null
}

function sanitizeContextSegment(raw: string): string {
  const t = (raw || 'default').trim() || 'default'
  return t.replace(/[^a-zA-Z0-9_-]/g, '_').slice(0, 96)
}

/** Storage key for a given signed-in context and projection (e.g. live VE graph). */
export function visionMapLayoutStorageKey(
  accountContext: string,
  projection: VisionMapLayoutProjectionId = 'live_ve',
): string {
  return `zenaf.visionMap.layout.v${VISION_MAP_LAYOUT_SCHEMA_VERSION}.${sanitizeContextSegment(accountContext)}.${projection}`
}

function isFiniteNum(n: unknown): n is number {
  return typeof n === 'number' && Number.isFinite(n)
}

function parseStored(raw: string | null): VisionMapPersistedLayoutV1 | null {
  if (!raw) return null
  try {
    const j = JSON.parse(raw) as unknown
    if (!j || typeof j !== 'object') return null
    const o = j as Record<string, unknown>
    if (o.v !== VISION_MAP_LAYOUT_SCHEMA_VERSION) return null
    if (o.projection !== 'live_ve') return null
    if (!o.positions || typeof o.positions !== 'object') return null
    const positions: Record<string, { x: number; y: number }> = {}
    for (const [id, pos] of Object.entries(o.positions as Record<string, unknown>)) {
      if (!id || typeof pos !== 'object' || !pos) continue
      const p = pos as Record<string, unknown>
      if (!isFiniteNum(p.x) || !isFiniteNum(p.y)) continue
      positions[id] = { x: p.x, y: p.y }
    }
    let viewport: VisionMapPersistedViewport | null = null
    if (o.viewport && typeof o.viewport === 'object') {
      const v = o.viewport as Record<string, unknown>
      if (isFiniteNum(v.x) && isFiniteNum(v.y) && isFiniteNum(v.zoom)) {
        viewport = { x: v.x, y: v.y, zoom: v.zoom }
      }
    }
    return { v: VISION_MAP_LAYOUT_SCHEMA_VERSION, projection: 'live_ve', positions, viewport }
  } catch {
    return null
  }
}

export function loadVisionMapLayout(storageKey: string): VisionMapPersistedLayoutV1 | null {
  if (typeof window === 'undefined') return null
  try {
    return parseStored(window.localStorage.getItem(storageKey))
  } catch {
    return null
  }
}

export function saveVisionMapLayout(
  storageKey: string,
  payload: {
    positions: Record<string, { x: number; y: number }>
    viewport: VisionMapPersistedViewport | null
    projection?: VisionMapLayoutProjectionId
  },
): void {
  if (typeof window === 'undefined') return
  const doc: VisionMapPersistedLayoutV1 = {
    v: VISION_MAP_LAYOUT_SCHEMA_VERSION,
    projection: payload.projection ?? 'live_ve',
    positions: { ...payload.positions },
    viewport: payload.viewport,
  }
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(doc))
  } catch {
    /* quota / private mode */
  }
}

export function clearVisionMapLayout(storageKey: string): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.removeItem(storageKey)
  } catch {
    /* ignore */
  }
}
