import type { FocusContextCore } from './types'

/** Stable key for text getters / selection maps (must match across region + provider). */
export function focusFieldRegistryKey(
  f: Pick<FocusContextCore, 'surface' | 'entity_type' | 'entity_id' | 'field_key'>,
): string {
  return `${f.surface}:${f.entity_type}:${f.entity_id}:${f.field_key}`
}
