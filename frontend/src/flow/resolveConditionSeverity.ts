import type { MapNodePayload } from '../vision-map/ontology'

/** Map visual condition channel to 0–3 severity for flow scoring. */
export function resolveConditionSeverity(payload: MapNodePayload): 0 | 1 | 2 | 3 {
  switch (payload.condition) {
    case 'healthy':
      return 0
    case 'stale':
      return 1
    case 'blocked':
    case 'teacher-warned':
      return 2
    case 'teacher-vetoed':
      return 3
    default:
      return 0
  }
}
