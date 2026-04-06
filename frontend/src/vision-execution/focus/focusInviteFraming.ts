/**
 * Client-only council question prefaces (Pass 2 v1). See CONTEXT_ACTION_BAR_DESIGN.md Appendix D
 * for limitations (`force_full_council`) and future explicit-preflight note.
 *
 * Markers + full preface are sent to the API; human-readable lines are for thread UI only.
 */
import { ACTION_LABELS } from './fieldCapabilityRegistry'
import type { FocusInvite } from './focusInviteTypes'
import type { ActionId, FocusContextCore } from './types'

/** Detected in `App.runCouncil` to apply Thinking Partner mandates for that run only (no extra refs). */
export const CONVERSATIONAL_INVITE_MARKER =
  '[Atria focus invite — conversational / Thinking Partner framing]'

export const STRUCTURED_FILL_INVITE_MARKER = '[Atria focus invite — structured field completion]'

const CONVERSATIONAL_DISPLAY_BY_ACTION: Partial<Record<ActionId, string>> = {
  surface_tensions: 'Thinking partner · Exploring tensions',
  expand_to_steps: 'Thinking partner · Expanding steps',
  distill: 'Thinking partner · Sharpening focus',
  extract_constraints: 'Thinking partner · Defining constraints',
  compare_with_evaluation: 'Thinking partner · Comparing to evaluation',
  summarize_for_council: 'Thinking partner · Council summary',
}

/** Strip internal "idea: …" style prefixes so the banner reads like a title, not a protocol. */
function stripConversationEntityHeadPrefix(head: string): string {
  const t = head.trim()
  const m = t.match(/^(idea|task|artifact|evaluation)\s*:\s*(.+)$/i)
  return m ? m[2]!.trim() : t
}

/** Single-line header for scoped banner + thread row (no ids or surface keys). */
export function buildScopedContextLabelFromCore(core: FocusContextCore): string {
  const typeLabel = core.entity_type.charAt(0).toUpperCase() + core.entity_type.slice(1)
  const head = core.lineage_labels?.[0]?.trim()
  if (head) return `${typeLabel} · ${stripConversationEntityHeadPrefix(head)}`
  return `${typeLabel} · ${core.field_label}`
}

/** Visible thread line for a conversational focus invite run (API still uses full preface). */
export function buildConversationalInviteDisplayLine(invite: FocusInvite, core: FocusContextCore): string {
  const specific = CONVERSATIONAL_DISPLAY_BY_ACTION[invite.sourceAction]
  if (specific) return specific
  const act = ACTION_LABELS[invite.sourceAction] ?? invite.sourceAction
  return `Thinking partner · ${act}`
}

/** Visible hint when structured-fill framing is in the composer (optional). */
export function buildStructuredFillDisplayLine(core: FocusContextCore): string {
  const fl = core.field_label?.trim() || 'this field'
  return `Draft · ${fl}`
}

/**
 * Derive a user-visible thread line from a council question that includes invite markers
 * (e.g. manual Send after structured-fill preface).
 */
export function threadDisplayLineForCouncilQuestion(q: string): string | undefined {
  if (q.includes(CONVERSATIONAL_INVITE_MARKER)) {
    const intent = q.match(/Intent:\s*(\S+)\s*[—-]\s*([^\n.]+)/)
    if (intent) {
      const action = intent[1] as ActionId
      const specific = CONVERSATIONAL_DISPLAY_BY_ACTION[action]
      if (specific) return specific
      const act = ACTION_LABELS[action] ?? action
      return `Thinking partner · ${act}`
    }
    return 'Thinking partner · Focused help'
  }
  if (q.includes(STRUCTURED_FILL_INVITE_MARKER)) {
    const fieldLine = q.match(/Field:\s*([^\n]+)/i)
    if (fieldLine) {
      const raw = fieldLine[1]!.replace(/\s*\([^)]*\)\s*\.?\s*$/, '').trim()
      if (raw) return `Draft · ${raw}`
    }
    const m = q.match(/Target:\s*([^\n.]+?)\s+on\s+/)
    const field = m?.[1]?.trim()
    if (field) return `Draft · ${field}`
    return 'Draft for field'
  }
  return undefined
}

/** Bounded node-transform heuristics must not intercept automated invite questions. */
export function boundedTransformDisabledForQuestion(q: string): boolean {
  return q.includes(CONVERSATIONAL_INVITE_MARKER) || q.includes(STRUCTURED_FILL_INVITE_MARKER)
}

/**
 * Structured invite: composer is always **replaced** with the new contract (no appending user text).
 * @deprecated Prefer assigning `buildStructuredFillInvitePreface(...)` directly to composer state.
 */
export function replaceStructuredFillComposerValue(_prev: string, newPreface: string): string {
  return newPreface
}

/** Client-only framing for the API question. VE snapshot lives in `council_preflight`; keep this compact. */
export function buildConversationalInvitePreface(invite: FocusInvite, _core: FocusContextCore): string {
  const actLabel = ACTION_LABELS[invite.sourceAction]
  return [
    CONVERSATIONAL_INVITE_MARKER,
    `Intent: ${invite.sourceAction} — ${actLabel}.`,
    '',
    'Use PRIMARY / VE focus context as authoritative where provided. Prefer clarification, tensions, constraints, and human-owned next moves over false certainty.',
    '',
    'Question:',
  ].join('\n')
}

/** Structured completion contract — composer-only until Send; no ids (server uses `council_preflight.ve_focus`). */
export function buildStructuredFillInvitePreface(_invite: FocusInvite, core: FocusContextCore): string {
  const fl = core.field_label?.trim() || 'this field'
  const et = core.entity_type
  return [
    STRUCTURED_FILL_INVITE_MARKER,
    `Field: ${fl} (${et}).`,
    'Reply with one paste-ready draft for this field only. No preamble, agenda, or follow-up questions.',
    '',
    'Draft:',
  ].join('\n')
}
