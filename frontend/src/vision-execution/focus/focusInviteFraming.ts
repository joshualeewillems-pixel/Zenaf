/**
 * Client-only council question prefaces (Pass 2 v1). See CONTEXT_ACTION_BAR_DESIGN.md Appendix D
 * for limitations (`force_full_council`) and future explicit-preflight note.
 */
import { ACTION_LABELS } from './fieldCapabilityRegistry'
import type { FocusInvite } from './focusInviteTypes'
import type { FocusContextCore } from './types'

/** Detected in `App.runCouncil` to apply Thinking Partner mandates for that run only (no extra refs). */
export const CONVERSATIONAL_INVITE_MARKER =
  '[Atria focus invite — conversational / Thinking Partner framing]'

export const STRUCTURED_FILL_INVITE_MARKER = '[Atria focus invite — structured field completion]'

/** Bounded node-transform heuristics must not intercept automated invite questions. */
export function boundedTransformDisabledForQuestion(q: string): boolean {
  return q.includes(CONVERSATIONAL_INVITE_MARKER) || q.includes(STRUCTURED_FILL_INVITE_MARKER)
}

/** Replace prior structured-fill block only; keep trimmed text above the marker (no preface stacking). */
export function replaceStructuredFillComposerValue(prev: string, newPreface: string): string {
  const idx = prev.indexOf(STRUCTURED_FILL_INVITE_MARKER)
  if (idx === -1) return newPreface
  const before = prev.slice(0, idx).trimEnd()
  return before ? `${before}\n\n${newPreface}` : newPreface
}

/** Client-only preflight framing (no new `council_preflight` keys). Prepended to the council question. */
export function buildConversationalInvitePreface(invite: FocusInvite, core: FocusContextCore): string {
  const actLabel = ACTION_LABELS[invite.sourceAction]
  return [
    CONVERSATIONAL_INVITE_MARKER,
    `Surface: ${core.surface}. Entity: ${core.entity_type} (${core.entity_id}). Field: ${core.field_label}.`,
    `Intent: ${invite.sourceAction} — ${actLabel}.`,
    '',
    'Use PRIMARY / VE focus context as authoritative where provided. Prefer clarification, tensions, constraints, and human-owned next moves over false certainty.',
    '',
    'Question:',
  ].join('\n')
}

/** Structured completion contract — explicit user click only; still client-only (question text). */
export function buildStructuredFillInvitePreface(_invite: FocusInvite, core: FocusContextCore): string {
  return [
    STRUCTURED_FILL_INVITE_MARKER,
    `Surface: ${core.surface}. Target: ${core.field_label} on ${core.entity_type} (${core.entity_id}).`,
    'Structured output: one paste-ready draft for that field only (no Socratic preamble, no meeting agenda).',
    '',
    'Notes:',
  ].join('\n')
}
