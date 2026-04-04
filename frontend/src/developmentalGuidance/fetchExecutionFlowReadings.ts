import { VISION_EXECUTION_API } from '../vision-execution/types'
import type { ExecutionFlowReadingSummary } from './types'

/** Best-effort; returns [] on failure (weak overlay). */
export async function fetchExecutionFlowReadings(
  entity_type: string,
  entity_id: string,
  limit = 12,
): Promise<ExecutionFlowReadingSummary[]> {
  const et = entity_type.trim()
  const eid = entity_id.trim()
  if (!et || !eid) return []
  const q = new URLSearchParams({
    entity_type: et,
    entity_id: eid,
    limit: String(Math.max(1, Math.min(limit, 24))),
  })
  const res = await fetch(`${VISION_EXECUTION_API}/coordination/execution-flow-readings?${q}`, {
    credentials: 'include',
  })
  if (!res.ok) return []
  const j = (await res.json()) as { readings?: ExecutionFlowReadingSummary[] }
  return Array.isArray(j.readings) ? j.readings : []
}
