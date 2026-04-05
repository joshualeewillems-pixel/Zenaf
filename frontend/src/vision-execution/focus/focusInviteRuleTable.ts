/**
 * Pass 2 focus invites v1 — rules come from `fieldCapabilityRegistry.ts`, which implements
 * CONTEXT_ACTION_BAR_DESIGN.md Appendix B (`allowed_actions` order per field).
 * Do not add numeric thresholds here; ordering uses registry array indices only.
 */
import type { ActionId } from './types'

export const FOCUS_INVITE_ENTITY_TYPES = ['idea', 'initiative'] as const

export type FocusInviteEntityType = (typeof FOCUS_INVITE_ENTITY_TYPES)[number]

/** Map selection without a text field (`__conversation_entity__`) → registry row for invite generation. */
export const CONVERSATION_ENTITY_INVITE_REGISTRY_FIELD: Record<FocusInviteEntityType, string> = {
  initiative: 'brief',
  idea: 'description',
}

/** Appendix B + product: `rewrite` is completion-oriented → structured_fill invite only. */
export const STRUCTURED_FILL_ACTION_IDS: ReadonlySet<ActionId> = new Set(['rewrite'])

/** Direct bar actions — not duplicated as invites (CONTEXT_ACTION_BAR_DESIGN §6). */
export const EXCLUDED_INVITE_ACTION_IDS: ReadonlySet<ActionId> = new Set(['transcribe'])

export const MAX_FOCUS_INVITES_VISIBLE = 4
