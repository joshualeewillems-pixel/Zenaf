/**
 * Content brief generation: emit `AiActionTrace` after successful `POST /run` only.
 * Same spirit as Workspace — no fetch wrapper; callers keep transport in `ContentView`.
 */

import type { AiActionTrace, AiUserOutcome } from '../ai-actions/types'
import {
  resolveExecutionPolicyPrimaryModelHint,
  resolveExecutionPolicyPrimaryProviderHint,
} from '../ai-actions/executionPolicy/resolveExecutionPolicyForAction'
import { createAiActionTrace, withTraceOutcome } from '../ai-actions/traceHelpers'
import { pushAiActionTrace } from '../ai-actions/traceSink'

/** Aligns with trace design `subject_type` for brief-scoped jobs. */
export const CONTENT_TRACE_SUBJECT_TYPE = 'content_brief' as const

function contentTraceModelHint(actionIntent: string): string | null {
  try {
    return resolveExecutionPolicyPrimaryModelHint({
      surface: 'content',
      action_kind: 'structured_evaluation',
      action_intent: actionIntent,
    })
  } catch {
    return null
  }
}

function contentTraceProviderHint(actionIntent: string): string | null {
  try {
    return resolveExecutionPolicyPrimaryProviderHint({
      surface: 'content',
      action_kind: 'structured_evaluation',
      action_intent: actionIntent,
    })
  } catch {
    return null
  }
}

/** Bounded snapshot: ids, output shape, refinement, source size — not full source text. */
export function buildContentBriefGenerationSnapshot(params: {
  briefId: string
  title?: string
  outputType: 'script' | 'newsletter'
  refinement?: string
  sourceMaterialsLen: number
}): string {
  const lines = [
    `brief_id:${params.briefId}`,
    `output_type:${params.outputType}`,
    params.refinement ? `refinement:${params.refinement}` : null,
    `source_materials_len:${params.sourceMaterialsLen}`,
    params.title?.trim() ? `title:${params.title.trim().slice(0, 120)}` : null,
  ].filter(Boolean) as string[]
  const s = lines.join('\n')
  return s.length > 8000 ? s.slice(0, 8000) : s
}

export function emitContentBriefTraceFromRun(params: {
  action_intent: string
  brief_id: string
  input_snapshot: string
  output_text: string
  prompt_version?: string | null
  resolved_model_used?: string | null
  resolved_provider_used?: string | null
}): AiActionTrace {
  const modelUsed =
    params.resolved_model_used != null && String(params.resolved_model_used).trim() !== ''
      ? String(params.resolved_model_used).trim()
      : contentTraceModelHint(params.action_intent)
  const providerUsed =
    params.resolved_provider_used != null && String(params.resolved_provider_used).trim() !== ''
      ? String(params.resolved_provider_used).trim()
      : contentTraceProviderHint(params.action_intent)
  const sid = (params.brief_id ?? '').trim().slice(0, 512)
  const trace = createAiActionTrace({
    surface: 'content',
    action_kind: 'structured_evaluation',
    action_intent: params.action_intent,
    subject_type: CONTENT_TRACE_SUBJECT_TYPE,
    subject_id: sid || 'no_brief',
    field_key: null,
    input_snapshot: params.input_snapshot.slice(0, 8000),
    model_used: modelUsed,
    provider_used: providerUsed,
    prompt_version: params.prompt_version ?? `content_${params.action_intent}_v1`,
    output: params.output_text.slice(0, 12000),
    user_outcome: 'none',
  })
  pushAiActionTrace(trace)
  return trace
}

export function recordContentTraceOutcome(trace: AiActionTrace, outcome: AiUserOutcome): void {
  pushAiActionTrace(withTraceOutcome(trace, outcome))
}

/** POST /vision-execution/distill-source — themes/claims extraction for a content brief. */
export function emitContentBriefDistillTrace(params: {
  brief_id: string
  source_materials_len: number
  key_themes_n: number
  claims_n: number
  had_error?: boolean
}): AiActionTrace {
  const actionIntent = 'content_brief_distill_source'
  const sid = (params.brief_id ?? '').trim().slice(0, 512)
  const trace = createAiActionTrace({
    surface: 'content',
    action_kind: 'structured_evaluation',
    action_intent: actionIntent,
    subject_type: CONTENT_TRACE_SUBJECT_TYPE,
    subject_id: sid || 'no_brief',
    field_key: null,
    input_snapshot: [
      'POST /vision-execution/distill-source',
      `source_materials_len:${params.source_materials_len}`,
      `key_themes_n:${params.key_themes_n}`,
      `claims_n:${params.claims_n}`,
      params.had_error ? 'had_error:1' : null,
    ]
      .filter(Boolean)
      .join('\n')
      .slice(0, 8000),
    model_used: contentTraceModelHint(actionIntent),
    provider_used: contentTraceProviderHint(actionIntent),
    prompt_version: 'content_distill_source_v1',
    output: JSON.stringify({
      key_themes_n: params.key_themes_n,
      claims_n: params.claims_n,
      had_error: Boolean(params.had_error),
    }).slice(0, 12000),
    user_outcome: 'none',
  })
  pushAiActionTrace(trace)
  return trace
}
