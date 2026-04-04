import type { CoreProfile } from './types'

/**
 * Canonical Brand core row for this user. Matches server `list_core_profiles` order:
 * primary first (`is_primary`), then first row in API order.
 */
export function canonicalCoreProfileId(profiles: CoreProfile[]): string | null {
  if (!profiles.length) return null
  const primary = profiles.find((p) => p.is_primary)
  return (primary ?? profiles[0]).id
}

/**
 * Picklist label for influence / shaping UI. When multiple rows exist, distinguishes
 * Brand core from legacy secondary rows without hiding any `id`.
 */
export function coreProfileInfluencePickLabel(
  p: CoreProfile,
  canonicalId: string | null,
  multipleRows: boolean,
): string {
  const base = (p.name || '').trim() || p.id
  if (!multipleRows || !canonicalId) return base
  return p.id === canonicalId ? `${base} · Brand core` : `${base} · Legacy row`
}
