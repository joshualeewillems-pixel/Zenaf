/**
 * Map triad snapshots use vision-map node kinds (seed/tree/branch/flower/nest).
 * VE API entity_type for coordination readings uses idea/initiative/project/task.
 */
import type { MapTriadDevelopmentalSnapshot } from './types'

export type VeEntityRef = { entity_type: string; entity_id: string }

export function veEntityRefFromMapTriad(
  t: MapTriadDevelopmentalSnapshot | null | undefined,
): VeEntityRef | null {
  if (!t?.node_id?.trim()) return null
  const id = t.node_id.trim()
  switch (t.node_kind) {
    case 'seed':
      return { entity_type: 'idea', entity_id: id }
    case 'tree':
      return { entity_type: 'initiative', entity_id: id }
    case 'branch':
      return { entity_type: 'project', entity_id: id }
    case 'flower':
      return { entity_type: 'task', entity_id: id }
    default:
      return null
  }
}
