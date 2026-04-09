/**
 * Shaping links between entities (localStorage, Phase 1).
 *
 * Semantics: each link means **this source entity is partially shaped by** the target
 * profile or perspective (`target_id` + `target_type`), with a **weight** (low | medium | high).
 *
 * Valid targets are **core_profile** and **perspective** only — not persons.
 */

export type InfluenceSourceKind = 'core_profile' | 'perspective' | 'person'

export type InfluenceTargetKind = 'core_profile' | 'perspective'

/** Display labels for target type (dropdowns, row editors). */
export const INFLUENCE_TARGET_KIND_LABEL: Record<InfluenceTargetKind, string> = {
  core_profile: 'Brand / legacy row',
  perspective: 'Actor (lens)',
}

export type InfluenceWeight = 'low' | 'medium' | 'high'

export type InfluenceLink = {
  targetKind: InfluenceTargetKind
  targetId: string
  weight: InfluenceWeight
}

const STORAGE_KEY = 'zenaf-entity-influences-v1'

export type InfluencesStore = Record<string, InfluenceLink[]>

export function influenceSourceKey(sourceKind: InfluenceSourceKind, sourceId: string): string {
  return `${sourceKind}:${sourceId}`
}

function sanitizeWeight(w: unknown): InfluenceWeight {
  return w === 'low' || w === 'medium' || w === 'high' ? w : 'medium'
}

/** Drop legacy person targets and malformed rows. */
function sanitizeLinks(links: unknown): InfluenceLink[] {
  if (!Array.isArray(links)) return []
  const out: InfluenceLink[] = []
  for (const x of links) {
    if (!x || typeof x !== 'object') continue
    const raw = (x as { targetKind?: string; targetId?: unknown; weight?: unknown }).targetKind
    if (raw !== 'core_profile' && raw !== 'perspective') continue
    const tid = String((x as { targetId?: string }).targetId ?? '').trim()
    if (!tid) continue
    out.push({
      targetKind: raw,
      targetId: tid,
      weight: sanitizeWeight((x as { weight?: unknown }).weight),
    })
  }
  return out
}

export function loadAllInfluences(): InfluencesStore {
  try {
    const raw = typeof localStorage !== 'undefined' ? localStorage.getItem(STORAGE_KEY) : null
    if (!raw) return {}
    const p = JSON.parse(raw) as unknown
    if (!p || typeof p !== 'object') return {}
    const sanitized: InfluencesStore = {}
    for (const [k, v] of Object.entries(p as Record<string, unknown>)) {
      sanitized[k] = sanitizeLinks(v)
    }
    return sanitized
  } catch {
    return {}
  }
}

export function saveAllInfluences(store: InfluencesStore) {
  try {
    if (typeof localStorage !== 'undefined') localStorage.setItem(STORAGE_KEY, JSON.stringify(store))
  } catch {
    /* ignore quota */
  }
}

export function getInfluencesForSource(sourceKind: InfluenceSourceKind, sourceId: string): InfluenceLink[] {
  const key = influenceSourceKey(sourceKind, sourceId)
  const all = loadAllInfluences()
  const row = all[key]
  return Array.isArray(row) ? sanitizeLinks(row) : []
}

export function setInfluencesForSource(
  sourceKind: InfluenceSourceKind,
  sourceId: string,
  links: InfluenceLink[],
) {
  const key = influenceSourceKey(sourceKind, sourceId)
  const all = { ...loadAllInfluences(), [key]: sanitizeLinks(links) }
  saveAllInfluences(all)
}
