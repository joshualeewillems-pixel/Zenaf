/**
 * Core profile substrate: bounded traces for reconcile + training conversation.
 * @see docs/02_ACTIVE_DESIGN/CORE_PROFILE_SUBSTRATE_PREP.md
 */

import type { AiActionTrace, AiUserOutcome } from '../ai-actions/types'
import {
  resolveExecutionPolicyPrimaryModelHint,
  resolveExecutionPolicyPrimaryProviderHint,
} from '../ai-actions/executionPolicy/resolveExecutionPolicyForAction'
import { createAiActionTrace, withTraceOutcome } from '../ai-actions/traceHelpers'
import { pushAiActionTrace } from '../ai-actions/traceSink'

export const CORE_PROFILE_TRACE_SUBJECT_TYPE = 'core_profile' as const

export const CORE_PROFILE_ACTION_INTENTS = {
  reconcile: 'core_profile_reconcile',
  conversation: 'core_profile_conversation',
} as const

function modelHint(actionIntent: string, actionKind: 'structured_evaluation' | 'suggestion_batch'): string | null {
  try {
    return resolveExecutionPolicyPrimaryModelHint({
      surface: 'core_profile',
      action_kind: actionKind,
      action_intent: actionIntent,
    })
  } catch {
    return null
  }
}

function providerHint(actionIntent: string, actionKind: 'structured_evaluation' | 'suggestion_batch'): string | null {
  try {
    return resolveExecutionPolicyPrimaryProviderHint({
      surface: 'core_profile',
      action_kind: actionKind,
      action_intent: actionIntent,
    })
  } catch {
    return null
  }
}

/** Bounded: no raw notes or message bodies. */
export function buildCoreProfileReconcileSnapshot(params: {
  profileId: string
  conversationTurnsN: number
  notesLen: number
  structuredKeysPresentN: number
}): string {
  const lines = [
    `profile_id:${params.profileId}`,
    `conversation_turns_n:${params.conversationTurnsN}`,
    `notes_len:${params.notesLen}`,
    `structured_keys_present_n:${params.structuredKeysPresentN}`,
  ]
  return lines.join('\n').slice(0, 8000)
}

export function buildCoreProfileConversationSnapshot(params: {
  profileId: string
  conversationTurnsN: number
  notesLen: number
}): string {
  const lines = [
    `profile_id:${params.profileId}`,
    `conversation_turns_n:${params.conversationTurnsN}`,
    `notes_len:${params.notesLen}`,
  ]
  return lines.join('\n').slice(0, 8000)
}

function summarizeProposedOutput(proposed: Record<string, string>, prior: Record<string, string>): string {
  let changed = 0
  let nonempty = 0
  for (const k of Object.keys(proposed)) {
    const p = (proposed[k] ?? '').trim()
    const b = (prior[k] ?? '').trim()
    if (p) nonempty += 1
    if (p !== b) changed += 1
  }
  const preview = Object.entries(proposed)
    .filter(([, v]) => (v ?? '').trim())
    .slice(0, 3)
    .map(([k, v]) => `${k}:${String(v).trim().slice(0, 120)}`)
  const payload = {
    fields_changed: changed,
    proposed_nonempty_fields: nonempty,
    sample: preview,
  }
  try {
    return JSON.stringify(payload).slice(0, 12000)
  } catch {
    return '{"summary":"proposed"}'
  }
}

export function emitCoreProfileReconcileTrace(params: {
  profileId: string
  input_snapshot: string
  proposed: Record<string, string>
  priorForm: Record<string, string>
  prompt_version?: string | null
}): AiActionTrace {
  const intent = CORE_PROFILE_ACTION_INTENTS.reconcile
  const trace = createAiActionTrace({
    surface: 'core_profile',
    action_kind: 'structured_evaluation',
    action_intent: intent,
    subject_type: CORE_PROFILE_TRACE_SUBJECT_TYPE,
    subject_id: params.profileId.slice(0, 512),
    field_key: null,
    input_snapshot: params.input_snapshot.slice(0, 8000),
    model_used: modelHint(intent, 'structured_evaluation'),
    provider_used: providerHint(intent, 'structured_evaluation'),
    prompt_version: params.prompt_version ?? 'core_profile_reconcile_v1',
    output: summarizeProposedOutput(params.proposed, params.priorForm),
    user_outcome: 'none',
  })
  pushAiActionTrace(trace)
  return trace
}

export function emitCoreProfileConversationTrace(params: {
  profileId: string
  input_snapshot: string
  reply: string
  prompt_version?: string | null
}): AiActionTrace {
  const intent = CORE_PROFILE_ACTION_INTENTS.conversation
  const reply = params.reply.trim()
  const out =
    JSON.stringify({
      reply_len: reply.length,
      preview: reply.slice(0, 200),
    }).slice(0, 12000)
  const trace = createAiActionTrace({
    surface: 'core_profile',
    action_kind: 'suggestion_batch',
    action_intent: intent,
    subject_type: CORE_PROFILE_TRACE_SUBJECT_TYPE,
    subject_id: params.profileId.slice(0, 512),
    field_key: null,
    input_snapshot: params.input_snapshot.slice(0, 8000),
    model_used: modelHint(intent, 'suggestion_batch'),
    provider_used: providerHint(intent, 'suggestion_batch'),
    prompt_version: params.prompt_version ?? 'core_profile_conversation_v1',
    output: out,
    user_outcome: 'none',
  })
  pushAiActionTrace(trace)
  return trace
}

export function recordCoreProfileTraceOutcome(trace: AiActionTrace, outcome: AiUserOutcome): void {
  pushAiActionTrace(withTraceOutcome(trace, outcome))
}
