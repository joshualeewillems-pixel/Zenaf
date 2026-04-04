/**
 * Client-side trace field redaction for privacy modes (no persistence).
 * Preserves: action_kind, action_intent, user_outcome, created_at, trace_id, surface, subject_*, field_key, prompt_version, model_used, provider_used (metadata only).
 */

import type { AiActionTrace } from './types'

export type TracePrivacyFlags = {
  redact_trace_snapshot: boolean
  suppress_trace_output: boolean
}

export const DEFAULT_TRACE_PRIVACY_FLAGS: TracePrivacyFlags = {
  redact_trace_snapshot: false,
  suppress_trace_output: false,
}

const REDACTED_SNAPSHOT_PLACEHOLDER = '[redacted]'
const SUPPRESSED_OUTPUT_PLACEHOLDER = '{"suppressed":true}'

/** Aggressive trim + placeholder when redaction is on (no regex PII pass in Phase 1). */
export function redactTraceInputSnapshot(snapshot: string, enabled: boolean): string {
  if (!enabled) return snapshot
  const t = String(snapshot ?? '').trim()
  if (t.length <= 80) return REDACTED_SNAPSHOT_PLACEHOLDER
  return `${REDACTED_SNAPSHOT_PLACEHOLDER} len=${t.length}`
}

export function suppressTraceOutputField(output: string, enabled: boolean): string {
  if (!enabled) return output
  return SUPPRESSED_OUTPUT_PLACEHOLDER
}

export function applyTracePrivacyRedaction(trace: AiActionTrace, flags: TracePrivacyFlags): AiActionTrace {
  if (!flags.redact_trace_snapshot && !flags.suppress_trace_output) return trace
  const review = trace.council_integrity_review
  const reviewOut =
    review && flags.suppress_trace_output
      ? { ...review, synthesis_text: SUPPRESSED_OUTPUT_PLACEHOLDER }
      : review
  return {
    ...trace,
    input_snapshot: redactTraceInputSnapshot(trace.input_snapshot, flags.redact_trace_snapshot),
    output: suppressTraceOutputField(trace.output, flags.suppress_trace_output),
    ...(reviewOut !== undefined ? { council_integrity_review: reviewOut } : {}),
  }
}
