/**
 * Meeting extraction (Vision Execution): emit-only `AiActionTrace` after a completed extract
 * that yields reviewable staging. Same spirit as Content / Workspace — transport stays in callers.
 * @see docs/02_ACTIVE_DESIGN/MEETING_EXTRACTION_TRACE_PREP.md
 */

import type { StagingArea } from '../meeting-intelligence/stagingTypes'
import type { AiActionTrace, AiUserOutcome } from './types'
import {
  resolveExecutionPolicyPrimaryModelHint,
  resolveExecutionPolicyPrimaryProviderHint,
} from './executionPolicy/resolveExecutionPolicyForAction'
import { createAiActionTrace, withTraceOutcome } from './traceHelpers'
import { pushAiActionTrace } from './traceSink'

export const MEETING_EXTRACTION_SUBJECT_TYPE = 'meeting_capture' as const

export type MeetingExtractionPath = 'single' | 'chunks' | 'synthesis'

export type MeetingExtractActionIntent =
  | 'meeting_extract_single'
  | 'meeting_extract_chunks'
  | 'meeting_extract_external_single'
  | 'meeting_extract_synthesis'
  | 'candidate_placement_suggest'
  | 'candidate_presort_triage'

function meetingTraceModelHint(actionIntent: MeetingExtractActionIntent): string | null {
  try {
    return resolveExecutionPolicyPrimaryModelHint({
      surface: 'meeting_extraction',
      action_kind: 'suggestion_batch',
      action_intent: actionIntent,
    })
  } catch {
    return null
  }
}

function meetingTraceProviderHint(actionIntent: MeetingExtractActionIntent): string | null {
  try {
    return resolveExecutionPolicyPrimaryProviderHint({
      surface: 'meeting_extraction',
      action_kind: 'suggestion_batch',
      action_intent: actionIntent,
    })
  } catch {
    return null
  }
}

/** Stable subject id when backend does not assign a persisted meeting id. */
export function meetingExtractionSubjectId(meetingId?: string | null): string {
  const m = (meetingId ?? '').trim()
  return m ? m.slice(0, 512) : 'unpersisted_meeting'
}

/**
 * Bounded metadata only — no notes body, no prompts.
 */
export function buildMeetingExtractionInputSnapshot(params: {
  meeting_id?: string | null
  path: MeetingExtractionPath
  notes_char_len: number
  chunk_total?: number
  chunk_succeeded?: number
  themes_n?: number
  /** External extract: one full-transcript call vs chunked fallback. */
  external_single_call?: boolean
  /** Character limit used to choose single vs chunked external path. */
  external_chunk_threshold_chars?: number
  /** Number of extract-meeting HTTP calls for this run (1 for external single). */
  extract_calls_n?: number
  document_budget_applied?: boolean
}): string {
  const lines = [
    params.meeting_id?.trim() ? `meeting_id:${params.meeting_id.trim().slice(0, 200)}` : null,
    `path:${params.path}`,
    `notes_char_len:${params.notes_char_len}`,
    params.chunk_total != null ? `chunk_total:${params.chunk_total}` : null,
    params.chunk_succeeded != null ? `chunk_succeeded:${params.chunk_succeeded}` : null,
    params.themes_n != null ? `themes_n:${params.themes_n}` : null,
    params.external_single_call != null ? `external_single_call:${params.external_single_call}` : null,
    params.external_chunk_threshold_chars != null
      ? `external_chunk_threshold_chars:${params.external_chunk_threshold_chars}`
      : null,
    params.extract_calls_n != null ? `extract_calls_n:${params.extract_calls_n}` : null,
    params.document_budget_applied != null ? `document_budget_applied:${params.document_budget_applied}` : null,
  ].filter(Boolean) as string[]
  const s = lines.join('\n')
  return s.length > 8000 ? s.slice(0, 8000) : s
}

function countApproved(arr: { approved?: boolean }[]): number {
  return arr.filter((x) => x.approved).length
}

/** Compact staging summary for trace output (counts + approved tallies). */
export function buildMeetingExtractionStagingOutputSummary(staging: StagingArea): string {
  const approvedArrays = [
    ...staging.ideas,
    ...staging.initiatives,
    ...staging.projects,
    ...staging.tasks,
    ...staging.assets,
    ...staging.people,
    ...staging.signals,
    ...staging.insights,
  ]
  const approvedItems = countApproved(approvedArrays) + (staging.summary?.approved ? 1 : 0)
  const payload = {
    summary: staging.summary != null,
    insights_n: staging.insights.length,
    ideas_n: staging.ideas.length,
    initiatives_n: staging.initiatives.length,
    projects_n: staging.projects.length,
    tasks_n: staging.tasks.length,
    assets_n: staging.assets.length,
    people_n: staging.people.length,
    signals_n: staging.signals.length,
    approved_items_n: approvedItems,
  }
  try {
    const s = JSON.stringify(payload)
    return s.length > 12000 ? s.slice(0, 12000) : s
  } catch {
    return '{}'
  }
}

export function emitMeetingExtractionTrace(params: {
  action_intent: MeetingExtractActionIntent
  meeting_id?: string | null
  input_snapshot: string
  output_summary: string
  prompt_version?: string | null
  resolved_model_used?: string | null
  resolved_provider_used?: string | null
}): AiActionTrace {
  const modelUsed =
    params.resolved_model_used != null && String(params.resolved_model_used).trim() !== ''
      ? String(params.resolved_model_used).trim()
      : meetingTraceModelHint(params.action_intent)
  const providerUsed =
    params.resolved_provider_used != null && String(params.resolved_provider_used).trim() !== ''
      ? String(params.resolved_provider_used).trim()
      : meetingTraceProviderHint(params.action_intent)

  const trace = createAiActionTrace({
    surface: 'meeting_extraction',
    action_kind: 'suggestion_batch',
    action_intent: params.action_intent,
    subject_type: MEETING_EXTRACTION_SUBJECT_TYPE,
    subject_id: meetingExtractionSubjectId(params.meeting_id),
    field_key: null,
    input_snapshot: params.input_snapshot.slice(0, 8000),
    model_used: modelUsed,
    provider_used: providerUsed,
    prompt_version: params.prompt_version ?? `meeting_${params.action_intent}_v1`,
    output: params.output_summary.slice(0, 12000),
    user_outcome: 'none',
  })
  pushAiActionTrace(trace)
  return trace
}

export function recordMeetingExtractionTraceOutcome(trace: AiActionTrace, outcome: AiUserOutcome): void {
  pushAiActionTrace(withTraceOutcome(trace, outcome))
}
