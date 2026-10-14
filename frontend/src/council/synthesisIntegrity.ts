/**
 * Council synthesis integrity: SSE envelope ingestion, combined summary derivation,
 * and compact review samples for local trace / export (no analytics backend).
 */

import type {
  CouncilIntegrityReviewSample,
  CouncilSynthesisCombinedSummary,
  CouncilSynthesisIntegrityState,
} from '../ai-actions/types'
import type { ConversationSubject } from '../conversation/conversationTrunkTypes'

/** Mirrors `CouncilIntegrityEnvelope` JSON from council SSE (Phase 1). */
export type CouncilIntegrityEnvelopePayload = {
  schema_version?: number
  surface?: string
  default_mode?: string
  integrity_mode?: string | null
  synthesis_type?: string | null
  synthesis_support_status?: string | null
  subject_refs?: Array<{
    entity_type?: string
    entity_id?: string | null
    role_in_output?: string
  }>
  provenance?: { run_id?: string }
  policies_applied?: string[]
}

/** Server-built proposed capture; client echoes as `context.pending_integration` until commit or superseded. */
export type PendingIntegrationPayload = {
  integration_state: 'proposed'
  entity_id: string
  entity_type: string
  /** Canonical storage key (e.g. description, desired_outcome). */
  field: string
  /** Schema UI label — use for display paths (matches Vision & Execution forms). */
  field_label?: string
  value: string
  entity_display_name?: string
}

const _VE_ENTITY_UI_LABEL: Record<string, string> = {
  idea: 'Idea',
  initiative: 'Initiative',
  project: 'Project',
  task: 'Task',
}

/** Matches server `build_ui_path_label` (schema UI label segment, not trunk tokens). */
export function formatPendingIntegrationUiPathLabel(p: PendingIntegrationPayload): string {
  const et = (p.entity_type || '').trim().toLowerCase()
  const typeLabel = _VE_ENTITY_UI_LABEL[et] || (et ? et.charAt(0).toUpperCase() + et.slice(1) : 'Item')
  const name = (p.entity_display_name || '').trim() || 'item'
  const fieldHuman = (p.field_label || '').trim() || (p.field || '').trim() || 'field'
  return `${typeLabel} → ${name} → ${fieldHuman}`
}

/** After a successful VE write; echo as `context.last_integration_commit` for “where is this?” turns. */
export type LastIntegrationCommitPayload = {
  ok?: boolean
  error?: string
  entity_id?: string
  entity_type?: string
  field?: string
  field_label?: string
  entity_title?: string
  ui_surface?: string
}

/** SSE `done` payload when a precision line was written to Vision & Execution this turn. */
export type IntegrationCommitPayload = {
  status: 'captured_only' | 'committed' | 'candidate_target'
  entity_id?: string
  entity_type?: string
  entity_display_name?: string
  field?: string
  field_label?: string
  recorded_text?: string
  ui_path_label?: string
  verified_match?: boolean
}

/** Two-step Lane A elicitation: echoed as `context.pending_ve_elicitation` until cleared. */
export type PendingVeElicitationPayload = {
  version: number
  phase: 'awaiting_value' | 'awaiting_confirm'
  elicitation_kind: 'person_assign' | 'text_set' | 'collection_add'
  entity_type: string
  entity_id: string
  field_key: string
  /** Canonical surface (`text_set` or initiative `collection_add`); mirrored in `field_key` after normalize. */
  surface_key?: string
  proposed_person_name?: string
  proposed_value?: string
  proposed_items?: string[]
}

/** Lane A: server-side direct VE mutation result on stream `done` (council LLM skipped). */
export type DirectVeActionPayload = {
  kind?: string
  status?: string
  message?: string
  refresh_hint?: string | null
  created_entities?: Array<{ entity_type?: string; entity_id?: string; title?: string }>
  pending_ve_elicitation?: PendingVeElicitationPayload | null
}

export type CouncilStreamSsePayload = {
  /** First SSE from server before council work; keeps dev proxies and clients unblocked. */
  stream_open?: boolean
  chunk?: string
  done?: boolean
  error?: string
  /** Present on `done` when the server handled a scoped imperative VE write without council. */
  direct_ve_action?: DirectVeActionPayload | null
  /** Echo next request as `context.conversation_subject` for Zenaf thread continuity. */
  conversation_subject?: ConversationSubject | null
  /** Proposed precision not yet written; echo on next POST until user affirms or server omits it. */
  pending_integration?: PendingIntegrationPayload | null
  /** Lane A elicitation bridge — echo until confirm or clear. */
  pending_ve_elicitation?: PendingVeElicitationPayload | null
  /** Last successful integration commit facts for location Q&A. */
  last_integration_commit?: LastIntegrationCommitPayload | null
  /** Present on `done` when this turn performed a VE write (Thinking Partner stream). */
  integration_commit?: IntegrationCommitPayload | null
  /** After a successful commit inside a scoped sub-thread — client pops digression and resumes main thread. */
  digression_summary?: string | null
  synthesis_integrity_state?: CouncilSynthesisIntegrityState | null
  synthesis_type?: string | null
  integrity_mode?: string | null
  integrity_warning?: string | null
  integrity_envelope?: unknown
  integrity_envelope_synthesis?: unknown
  /** Council personality mode used for this run (base | mirror | blend). */
  council_personality_mode?: string | null
  /** Mirror mode: strand keys whose seats fell back to aspirational. */
  mirror_empty_strands?: string[] | null
  /** Human-readable mirror-fallback notice (null when every seat had mirror content). */
  mirror_notice?: string | null
}

const REVIEW_SYNTHESIS_MAX = 8000

export function shortIntegrityRunId(runId: string | undefined): string {
  if (!runId || typeof runId !== 'string') return '—'
  const t = runId.trim()
  if (t.length <= 10) return t
  return `${t.slice(0, 8)}…`
}

export function ingestSynthesisEnvelopeFromPayload(payload: CouncilStreamSsePayload): CouncilIntegrityEnvelopePayload | null {
  const syn = payload.integrity_envelope_synthesis
  if (syn && typeof syn === 'object') return syn as CouncilIntegrityEnvelopePayload
  const env = payload.integrity_envelope
  if (env && typeof env === 'object' && (env as CouncilIntegrityEnvelopePayload).surface === 'council_synthesis') {
    return env as CouncilIntegrityEnvelopePayload
  }
  return null
}

export function labelCouncilSynthesisIntegrity(state: CouncilSynthesisIntegrityState): string {
  switch (state) {
    case 'anchored':
      return 'Anchored'
    case 'weak':
      return 'Weak anchor'
    case 'unanchored':
      return 'Unanchored'
  }
}

export function councilSynthesisIntegrityClass(state: CouncilSynthesisIntegrityState): string {
  switch (state) {
    case 'anchored':
      return 'text-emerald-400/95'
    case 'weak':
      return 'text-amber-300/95'
    case 'unanchored':
      return 'text-rose-400/90'
  }
}

export function deriveCouncilSynthesisCombinedSummary(
  state: CouncilSynthesisIntegrityState,
  warning: string | null,
  synthesisSupportStatus: string | null | undefined,
): CouncilSynthesisCombinedSummary {
  if (state === 'weak') return 'weak_support'
  if (state === 'unanchored' || warning === 'missing_primary_anchor') return 'unreliable'
  const s = synthesisSupportStatus
  if (s == null || s === '' || s === 'supported') return 'grounded'
  if (s === 'partially_supported' || s === 'unsupported_expansion') return 'grounded_but_interpretive'
  return 'grounded'
}

export function labelCouncilSynthesisCombinedSummary(summary: CouncilSynthesisCombinedSummary): string {
  switch (summary) {
    case 'grounded':
      return 'Grounded'
    case 'grounded_but_interpretive':
      return 'Grounded but interpretive'
    case 'weak_support':
      return 'Weak support'
    case 'unreliable':
      return 'Unreliable'
  }
}

/**
 * Neutral, material gradation for combined summary (dark UI): trust via contrast, weight, opacity — no semantic hues.
 * Label uses the mapping weights; description matches tone with slightly softer weight for readability.
 */
export function councilSynthesisCombinedPresentation(summary: CouncilSynthesisCombinedSummary): {
  labelClassName: string
  descriptionClassName: string
} {
  switch (summary) {
    case 'grounded':
      return {
        labelClassName: 'text-stone-100 font-semibold opacity-100',
        descriptionClassName: 'text-stone-200 font-normal opacity-100',
      }
    case 'grounded_but_interpretive':
      return {
        labelClassName: 'text-stone-200 font-medium opacity-[0.88]',
        descriptionClassName: 'text-stone-300/95 font-normal opacity-[0.87]',
      }
    case 'weak_support':
      return {
        labelClassName: 'text-stone-400 font-normal opacity-[0.72]',
        descriptionClassName: 'text-stone-400/95 font-normal opacity-[0.70]',
      }
    case 'unreliable':
      return {
        labelClassName: 'text-stone-500 font-light opacity-[0.55]',
        descriptionClassName: 'text-stone-500 font-light opacity-[0.52]',
      }
  }
}

export function councilSynthesisCombinedSummaryLine(summary: CouncilSynthesisCombinedSummary): string {
  switch (summary) {
    case 'grounded':
      return 'PRIMARY anchoring looks good and seat-level wording overlap is strong.'
    case 'grounded_but_interpretive':
      return 'PRIMARY anchoring looks good, but the synthesis may go beyond what seats literally said.'
    case 'weak_support':
      return 'No authoritative PRIMARY in the packet, so treat synthesis as lightly grounded at best.'
    case 'unreliable':
      return 'PRIMARY was expected but the synthesis likely does not tie back to it (or is empty).'
  }
}

export function councilSynthesisWhyLine(state: CouncilSynthesisIntegrityState): string {
  switch (state) {
    case 'anchored':
      return 'The council packet had an authoritative PRIMARY block, and the synthesis text appears to reference that primary object.'
    case 'weak':
      return 'No authoritative PRIMARY block was present in the council packet, so synthesis grounding is weaker.'
    case 'unanchored':
      return 'An authoritative PRIMARY was present, but the synthesis may not reference it (or it was empty).'
  }
}

export function explainSynthesisSupportStatus(code: string | undefined | null): { label: string; body: string } | null {
  if (code == null || code === '') return null
  switch (code) {
    case 'supported':
      return {
        label: 'Supported',
        body: 'Most distinctive synthesis terms (long, non-stop words) also appear in the combined seat outputs.',
      }
    case 'partially_supported':
      return {
        label: 'Partially supported',
        body: 'Some distinctive synthesis terms are missing from seat text; overlap is only partial.',
      }
    case 'unsupported_expansion':
      return {
        label: 'Unsupported expansion',
        body: 'Many distinctive synthesis terms are absent from seat outputs; the synthesis may be going beyond what seats said.',
      }
    default:
      return { label: code, body: 'Reported by server; interpretation not built into this UI.' }
  }
}

export function buildCouncilIntegrityReviewSample(params: {
  includeSynthesis: boolean
  synthesisIntegrityState: CouncilSynthesisIntegrityState | null
  integrityWarning: string | null
  envelope: CouncilIntegrityEnvelopePayload | null
  fullCouncilOutput: string
}): CouncilIntegrityReviewSample | null {
  if (!params.includeSynthesis || params.synthesisIntegrityState == null) return null
  const st = params.synthesisIntegrityState
  const sup = params.envelope?.synthesis_support_status ?? null
  const combined = deriveCouncilSynthesisCombinedSummary(st, params.integrityWarning, sup)
  const policies = (params.envelope?.policies_applied ?? []).filter(Boolean)
  const runId = params.envelope?.provenance?.run_id ?? null
  return {
    schema: 'council_integrity_review_v1',
    combined_summary: combined,
    combined_summary_label: labelCouncilSynthesisCombinedSummary(combined),
    synthesis_integrity_state: st,
    synthesis_support_status: sup,
    integrity_warning: params.integrityWarning,
    policies_applied: policies,
    provenance_run_id: runId,
    include_synthesis: true,
    synthesis_text: (params.fullCouncilOutput ?? '').slice(0, REVIEW_SYNTHESIS_MAX),
  }
}
