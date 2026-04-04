import type { AiActionTrace } from './types'
import { getTracePrivacyFlagsForCurrentMode } from './privacyModeBridge'
import { applyTracePrivacyRedaction, type TracePrivacyFlags } from './tracePrivacy'

const RING_MAX = 32
const ring: AiActionTrace[] = []

/** In-memory ring; replace with persistence / API later without changing trace shape. */
export function pushAiActionTrace(trace: AiActionTrace, tracePrivacy?: TracePrivacyFlags | null): void {
  const flags = tracePrivacy === undefined ? getTracePrivacyFlagsForCurrentMode() : tracePrivacy
  const t =
    flags && (flags.redact_trace_snapshot || flags.suppress_trace_output)
      ? applyTracePrivacyRedaction(trace, flags)
      : trace
  ring.push(t)
  while (ring.length > RING_MAX) ring.shift()
}

export function getRecentAiActionTraces(): readonly AiActionTrace[] {
  return ring
}

/** Remove traces that carry council integrity review rows (in-memory only). Returns how many were removed. */
export function clearCouncilIntegrityReviewTraces(): number {
  let removed = 0
  for (let i = ring.length - 1; i >= 0; i--) {
    if (ring[i].council_integrity_review != null) {
      ring.splice(i, 1)
      removed++
    }
  }
  return removed
}
