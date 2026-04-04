/**
 * Core Profile graph lane — separate from VE `resolveGraphSliceVE`.
 * Anchors on the open/detail profile when `activeProfileId` is set.
 */

import type { CoreProfile } from '../types'
import type { GraphFocusSlice, GraphNodeSnapshot, ProfileGraphDataSnapshot } from './graphSliceTypes'

function asRecord(o: unknown): Record<string, unknown> {
  if (o && typeof o === 'object' && !Array.isArray(o)) return { ...(o as Record<string, unknown>) }
  return {}
}

function nodeFromProfile(p: CoreProfile): GraphNodeSnapshot {
  const key = `core_profile:${p.id}`
  return {
    id: key,
    kind: 'core_profile',
    data: asRecord(p),
    relationships: { parent: null, children: [], linked: [], matched: [] },
  }
}

/**
 * Profile-oriented neighborhood: all listed profiles as nodes; anchor = active detail profile.
 */
export function resolveGraphSliceProfile(
  snapshot: ProfileGraphDataSnapshot | null | undefined,
): GraphFocusSlice | null {
  const aid = (snapshot?.activeProfileId ?? '').trim()
  if (!aid) return null

  const profiles = snapshot?.profiles ?? []
  const resolvedAt = new Date().toISOString()
  const row = profiles.find((p) => p.id === aid)

  if (!row) {
    return {
      anchor: { kind: 'core_profile', id: aid, fieldKey: 'profile' },
      nodes: {},
      edges: [],
      resolvedAt,
      dataUnavailable: true,
    }
  }

  const nodes: Record<string, GraphNodeSnapshot> = {}
  for (const p of profiles) {
    const n = nodeFromProfile(p)
    nodes[n.id] = n
  }

  return {
    anchor: { kind: 'core_profile', id: aid, fieldKey: 'profile' },
    nodes,
    edges: [],
    resolvedAt,
  }
}
