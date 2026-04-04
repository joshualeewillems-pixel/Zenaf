/**
 * Workspace Organizer: emit `AiActionTrace` after successful `/run` or `/run/stream` calls.
 * Does not perform fetch — call sites keep existing transport; invoke emitters on success only.
 * @see docs/02_ACTIVE_DESIGN/AI_ACTION_TRACE_AND_ROUTING_DESIGN.md
 */

import type { AiActionTrace, AiUserOutcome, CouncilIntegrityReviewSample } from './types'
import type { ActionRoutingContext } from './executionPolicy/types'
import {
  resolveExecutionPolicyForAction,
  resolveExecutionPolicyPrimaryModelHint,
} from './executionPolicy/resolveExecutionPolicyForAction'
import { createAiActionTrace, withTraceOutcome } from './traceHelpers'
import { pushAiActionTrace } from './traceSink'
import { readPrivacyMode } from './privacyModeBridge'

/** Mirrors `RunRoutingContext` on `POST /run` / `POST /run/stream` (Workspace seam). */
export type WorkspaceRunRoutingContextPayload = {
  surface: 'workspace_organizer'
  action_kind: 'structured_evaluation'
  action_intent: string
  streaming?: boolean
  sensitivity?: string
  privacy_mode?: string
  /** Must match merged execution + privacy policy; server default is false if omitted. */
  allows_externalization: boolean
}

function workspaceRoutingActionContext(actionIntent: string): ActionRoutingContext {
  return {
    surface: 'workspace_organizer',
    action_kind: 'structured_evaluation',
    action_intent: actionIntent,
  }
}

/**
 * Whether cloud externalization is allowed for this workspace intent under current privacy + policy JSON.
 * Aligns with `resolution.allow_cloud` after `applyPrivacyToExecutionResolution` (see `privacyApply.ts`).
 */
export function workspaceAllowsExternalizationForIntent(actionIntent: string): boolean {
  const r = resolveExecutionPolicyForAction(workspaceRoutingActionContext(actionIntent))
  if (r.execution_blocked) return false
  return Boolean(r.resolution.allow_cloud)
}

/** Phase 1 substrate for Workspace `POST /run` / stream — includes explicit externalization opt-in. */
export function buildWorkspaceRunRoutingContext(
  actionIntent: string,
  streaming: boolean,
): WorkspaceRunRoutingContextPayload {
  return {
    surface: 'workspace_organizer',
    action_kind: 'structured_evaluation',
    action_intent: actionIntent,
    streaming,
    privacy_mode: readPrivacyMode(),
    allows_externalization: workspaceAllowsExternalizationForIntent(actionIntent),
  }
}

/** Client-side hint from execution policy (Phase 0); server may use a different model. */
function workspaceTraceModelUsedHint(actionIntent: string): string | null {
  try {
    return resolveExecutionPolicyPrimaryModelHint({
      surface: 'workspace_organizer',
      action_kind: 'structured_evaluation',
      action_intent: actionIntent,
    })
  } catch {
    return null
  }
}

/** Stable `subject_type` for folder-scoped workspace jobs. */
export const WORKSPACE_TRACE_SUBJECT_TYPE = 'workspace_folder' as const

/** Snake_case intents for Workspace AI flows (not a TS enum). */
export const WORKSPACE_ACTION_INTENTS = {
  analyze: 'workspace_analyze',
  simulate: 'workspace_simulate',
  assess: 'workspace_assess',
  recommend: 'workspace_recommend',
  council: 'workspace_council',
  folder_advisor: 'workspace_folder_advisor',
  web_research: 'workspace_web_research',
  next_step: 'workspace_next_step',
  reassess: 'workspace_reassess',
  /** POST /vision-execution/suggest-node-transform from workspace council (bounded transform). */
  bounded_node_transform: 'workspace_bounded_node_transform',
} as const

export type WorkspaceActionIntentKey = keyof typeof WORKSPACE_ACTION_INTENTS

export function workspaceTraceSubjectId(folderPath: string | null | undefined): string {
  const p = (folderPath ?? '').trim()
  return p ? p.slice(0, 512) : 'no_folder'
}

function normalizeTraceOutputFromJson(payload: unknown): string {
  try {
    const s = JSON.stringify(payload)
    return s.length > 12000 ? s.slice(0, 12000) : s
  } catch {
    return String(payload).slice(0, 12000)
  }
}

/**
 * Emit a workspace trace for a JSON-serializable API result (`POST /run` body.result).
 */
export function emitWorkspaceTraceFromResult(params: {
  action_intent: string
  folder_path?: string | null
  input_snapshot: string
  result: unknown
  prompt_version?: string | null
  resolved_model_used?: string | null
}): AiActionTrace {
  const modelUsed =
    params.resolved_model_used != null && String(params.resolved_model_used).trim() !== ''
      ? String(params.resolved_model_used).trim()
      : workspaceTraceModelUsedHint(params.action_intent)
  const trace = createAiActionTrace({
    surface: 'workspace_organizer',
    action_kind: 'structured_evaluation',
    action_intent: params.action_intent,
    subject_type: WORKSPACE_TRACE_SUBJECT_TYPE,
    subject_id: workspaceTraceSubjectId(params.folder_path),
    field_key: null,
    input_snapshot: params.input_snapshot.slice(0, 8000),
    model_used: modelUsed,
    prompt_version: params.prompt_version ?? `ws_${params.action_intent}_v1`,
    output: normalizeTraceOutputFromJson(params.result),
    user_outcome: 'none',
  })
  pushAiActionTrace(trace)
  return trace
}

/**
 * Emit a workspace trace for a text-primary result (council stream, folder advisor).
 */
export function emitWorkspaceTraceFromText(params: {
  action_intent: string
  folder_path?: string | null
  input_snapshot: string
  output_text: string
  prompt_version?: string | null
  resolved_model_used?: string | null
  /** Optional council synthesis integrity row for local review export (in-memory ring). */
  council_integrity_review?: CouncilIntegrityReviewSample | null
}): AiActionTrace {
  const modelUsed =
    params.resolved_model_used != null && String(params.resolved_model_used).trim() !== ''
      ? String(params.resolved_model_used).trim()
      : workspaceTraceModelUsedHint(params.action_intent)
  const trace = createAiActionTrace({
    surface: 'workspace_organizer',
    action_kind: 'structured_evaluation',
    action_intent: params.action_intent,
    subject_type: WORKSPACE_TRACE_SUBJECT_TYPE,
    subject_id: workspaceTraceSubjectId(params.folder_path),
    field_key: null,
    input_snapshot: params.input_snapshot.slice(0, 8000),
    model_used: modelUsed,
    prompt_version: params.prompt_version ?? `ws_${params.action_intent}_v1`,
    output: params.output_text.slice(0, 12000),
    user_outcome: 'none',
    council_integrity_review: params.council_integrity_review ?? undefined,
  })
  pushAiActionTrace(trace)
  return trace
}

/** Re-push trace with updated user outcome (ring buffer gets a new entry; same pattern as VE). */
export function recordWorkspaceTraceOutcome(trace: AiActionTrace, outcome: AiUserOutcome): void {
  pushAiActionTrace(withTraceOutcome(trace, outcome))
}

/** Snapshot for synchronous `POST /run` folder modes. */
export function buildWorkspaceJsonRunSnapshot(
  apiMode: string,
  folderPath: string,
  extra?: { suggested_folders?: string[] },
): string {
  const base = `POST /run | mode=${apiMode} | folder_path=${folderPath || '(empty)'}`
  if (extra?.suggested_folders?.length) {
    return `${base} | suggested_folders_n=${extra.suggested_folders.length}`.slice(0, 8000)
  }
  return base.slice(0, 8000)
}

/** Snapshot for council stream (main council UI). */
export function buildWorkspaceCouncilStreamSnapshot(params: {
  question: string
  included_agent_ids?: string[]
  folder_workflow: boolean
  folder_path?: string | null
}): string {
  const agents = params.included_agent_ids?.length ? params.included_agent_ids.join(',') : 'default'
  const fp = params.folder_path?.trim() || '(empty)'
  return `POST /run/stream | mode=council | folder_path=${fp} | folder_workflow=${params.folder_workflow ? 'yes' : 'no'} | agents=${agents} | question=${params.question.slice(0, 3500)}`.slice(
    0,
    8000,
  )
}

/** Snapshot for folder advisor (same API mode as council, different UI intent). */
export function buildWorkspaceFolderAdvisorSnapshot(params: { question: string; folder_path?: string | null }): string {
  const fp = params.folder_path?.trim() || '(empty)'
  return `POST /run/stream | mode=council | workflow_kind=folder | folder_path=${fp} | question=${params.question.slice(0, 3500)}`.slice(
    0,
    8000,
  )
}

export function buildWorkspaceWebResearchSnapshot(query: string): string {
  return `POST /run | mode=web_research | query=${query.slice(0, 4000)}`.slice(0, 8000)
}

export function buildWorkspaceNextStepSnapshot(params: {
  folder_path: string
  has_context_block: boolean
  question?: string
}): string {
  const q = (params.question ?? '').trim().slice(0, 2000)
  return `POST /run | mode=next_step | folder_path=${params.folder_path || '(empty)'} | context_block=${params.has_context_block ? 'yes' : 'no'} | question=${q}`.slice(
    0,
    8000,
  )
}

export function buildWorkspaceReassessSnapshot(params: {
  folder_path: string
  items_n: number
  reviewer_name: string
}): string {
  return `POST /run | mode=reassess_low_confidence | folder_path=${params.folder_path || '(empty)'} | items_n=${params.items_n} | reviewer=${params.reviewer_name.slice(0, 200)}`.slice(
    0,
    8000,
  )
}
