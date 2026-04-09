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
  '[Zenaf focus invite — conversational / Thinking Partner framing]'

export const STRUCTURED_FILL_INVITE_MARKER = '[Zenaf focus invite — structured field completion]'

const CONVERSATIONAL_DISPLAY_BY_ACTION: Partial<Record<ActionId, string>> = {
  surface_tensions: 'Thinking partner · Exploring tensions',
  expand_to_steps: 'Thinking partner · Expanding steps',
  distill: 'Thinking partner · Sharpening focus',
  extract_constraints: 'Thinking partner · Defining constraints',
  compare_with_evaluation: 'Thinking partner · Comparing to evaluation',
  summarize_for_council: 'Thinking partner · Council summary',
}

const SHARED_AUTHORITY_LINES =
  'Use PRIMARY / VE focus context as authoritative where provided. Do not invent entity IDs or imply database writes — the human applies changes in Vision & Execution.'

/** Per-invite rules sent with the council question (distinct intent, shared authority line). */
function conversationalRulesLines(action: ActionId): string[] {
  switch (action) {
    case 'distill':
      return [
        'Goal: Remove ambiguity and produce a clean, decisive articulation of what this work actually is.',
        'Rules:',
        '- No fluff, meta-commentary, or hedging ("we should consider…"). Prefer commitment over exploration.',
        '- Do not discuss Zenaf UI, invites, or "the system". Stay in the substance of the work.',
        '- No process narration or "checking boxes."',
        '- This is articulation of what the work *is* (scope, stakes, crisp phrasing) — not a task list, execution plan, or stakeholder map.',
        'Output:',
        '- One to three tight formulations (bullets or very short paragraphs).',
        '- Optional: one decisive recommendation if one option is clearly strongest.',
      ]
    case 'expand_to_steps':
      return [
        'Goal: Turn this into executable structure grounded in how work actually ships in an org like this one.',
        'Rules:',
        '- Think in real work units: phases, tasks, dependencies, ownership, sequencing, and what must exist before the next step.',
        '- Prefer granular, verifiable steps over vague phases. Avoid generic career advice.',
        '- Assume output should be mappable into Vision & Execution objects (initiatives, projects, tasks, people) even if you only name them in prose.',
        '- Call out what is missing (roles, decisions, inputs) before execution can start.',
        'Output:',
        '- Structured breakdown: ordered steps with dependencies and suggested owners or roles where inferable.',
        '- Optional: "smallest viable next three moves" if the full tree would be too long.',
      ]
    case 'surface_tensions':
      return [
        'Goal: Surface conflicts, tradeoffs, and constraints — strategic, operational, and human — without forcing premature resolution.',
        'Rules:',
        '- Do NOT pick a single path or optimize away tension. Do NOT write a neutral summary that smooths over conflict.',
        '- Expand perspective: time, money, attention, capability, reputation, and competing commitments.',
        '- Prefer uncomfortable truths over clean narratives when evidence supports them.',
        '- External reality: you may reference benchmarks, typical costs, or calendar reality. If you lack browsing, state assumptions and ranges clearly — do not fake precision.',
        '- Assumption audit: surface hidden premises and what fails if each is wrong (no need to fix them here).',
        '- Pre-mortem / post-mortem angles: credible failure modes, kill criteria or stop signals, and "if we already tried this, what went wrong?"',
        '- Stakeholders: who must align vs who only needs visibility; competing accountabilities and incentives.',
        'Output:',
        '- Tensions grouped (e.g. strategic / operational / resource / stakeholder / assumptions).',
        '- For cost and time, give rough orders of magnitude or ranges with stated assumptions.',
      ]
    case 'summarize_for_council':
      return [
        'Goal: Move from complexity toward a decision-ready direction for this focus (council-style clarity).',
        'Rules:',
        '- You must resolve tensions enough to recommend a direction (not an endless option menu).',
        '- Default to one primary path unless genuine uncertainty is critical — then name at most two paths and the decision between them.',
        '- No neutral "on the one hand" essays. Be solution-oriented: if we proceed, how should we?',
        '- No fake certainty; flag key risks and what would change the recommendation.',
        '- Stakeholders: who to win over vs who to inform; likely objections and how to address them in one pass.',
        'Output:',
        '- Chosen path (or two with decision criterion), why, and ordered next moves (who does what).',
        '- Close with: smallest concrete next action, definition of done for that action, and what *not* to do so this does not slide back into endless planning.',
      ]
    case 'extract_constraints':
      return [
        'Goal: Make blocking factors, prerequisites, and non-negotiable scope limits explicit.',
        'Rules:',
        '- Anchor in PRIMARY / focus text; distinguish hard blockers from soft risks.',
        'Output:',
        '- Grouped constraints and, where possible, what would unblock each.',
      ]
    case 'compare_with_evaluation':
      return [
        'Goal: Align this field with evaluation-style artifacts (e.g. cost, timeframe, recommendation) when they appear in context.',
        'Rules:',
        '- Call out contradictions explicitly; propose harmonized wording only where justified.',
        'Output:',
        '- Comparison, gaps, and suggested edits (prose the user could paste).',
      ]
    default:
      return [
        'Goal: Provide focused Thinking Partner help aligned with the intent label.',
        'Rules:',
        '- Prefer clarification, constraints, and human-owned next moves over false certainty.',
        'Output:',
        '- Direct, usable prose for the user.',
      ]
  }
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

/** Client-only framing for the API question. VE snapshot lives in `council_preflight`; rules differ per intent. */
export function buildConversationalInvitePreface(invite: FocusInvite, _core: FocusContextCore): string {
  const actLabel = ACTION_LABELS[invite.sourceAction]
  const rules = conversationalRulesLines(invite.sourceAction)
  return [
    CONVERSATIONAL_INVITE_MARKER,
    `Intent: ${invite.sourceAction} — ${actLabel}.`,
    '',
    ...rules,
    '',
    SHARED_AUTHORITY_LINES,
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
