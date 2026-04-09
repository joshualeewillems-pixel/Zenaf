import type { FlowAssessment } from '../../flow/flowAssessment'
import { isInviteAction } from '../../flow/flowAssessment'
import { CONVERSATION_ENTITY_FIELD_KEY } from './conversationEntityFocus'
import {
  CONVERSATION_ENTITY_INVITE_REGISTRY_FIELD,
  EXCLUDED_INVITE_ACTION_IDS,
  FOCUS_INVITE_ENTITY_TYPES,
  MAX_FOCUS_INVITES_VISIBLE,
  STRUCTURED_FILL_ACTION_IDS,
  type FocusInviteEntityType,
} from './focusInviteRuleTable'
import type { FocusInvite, FocusInviteKind } from './focusInviteTypes'
import { ACTION_LABELS, getFieldCapabilities } from './fieldCapabilityRegistry'
import type { ActionId, FocusContextCore } from './types'

const RANK_FALLBACK = 100

function flowRankIndex(action: ActionId, ranked: FlowAssessment['rankedActions']): number {
  if (!isInviteAction(action)) return RANK_FALLBACK
  const i = ranked.indexOf(action)
  return i === -1 ? RANK_FALLBACK : i
}

/** Outcome-oriented chip copy for structured_fill (rewrite only in v1). */
function structuredFillInviteLabel(
  action: ActionId,
  et: FocusInviteEntityType,
  fieldKey: string,
  fieldLabel: string,
): string {
  if (action !== 'rewrite') return `${ACTION_LABELS[action]} · ${fieldLabel}`
  if (fieldKey === 'description') return 'Write description'
  if (fieldKey === 'summary') return 'Write short note'
  if (fieldKey === 'title') return et === 'idea' ? 'Set idea title' : 'Set title'
  if (fieldKey === 'recommendation') return 'Fill recommendation'
  if (fieldKey === 'philosophical_alignment_ai') return 'Fill strategic alignment'
  if (fieldKey === 'dependencies') return 'Add dependencies'
  return `Fill ${fieldLabel}`
}

/** Conversational invite chips: short, intent-shaped (not internal action ids). */
function conversationalInviteLabel(action: ActionId): string {
  switch (action) {
    case 'surface_tensions':
      return 'Explore tensions'
    case 'expand_to_steps':
      return 'Expand steps'
    case 'distill':
      return 'Sharpen focus'
    case 'extract_constraints':
      return 'Define constraints'
    case 'compare_with_evaluation':
      return 'Compare to evaluation'
    case 'summarize_for_council':
      return 'Summarize for council'
    default:
      return ACTION_LABELS[action]
  }
}

function isInviteEntityType(t: string): t is FocusInviteEntityType {
  return (FOCUS_INVITE_ENTITY_TYPES as readonly string[]).includes(t)
}

function registryFieldForCore(core: FocusContextCore): string | null {
  const et = core.entity_type
  if (!isInviteEntityType(et)) return null
  if (core.field_key === CONVERSATION_ENTITY_FIELD_KEY) {
    return CONVERSATION_ENTITY_INVITE_REGISTRY_FIELD[et]
  }
  return core.field_key
}

function inviteLabel(
  action: ActionId,
  kind: FocusInviteKind,
  et: FocusInviteEntityType,
  fieldKey: string,
  fieldLabel: string,
): string {
  if (kind === 'structured_fill') {
    return structuredFillInviteLabel(action, et, fieldKey, fieldLabel)
  }
  return conversationalInviteLabel(action)
}

function kindRank(k: FocusInviteKind): number {
  return k === 'conversational' ? 0 : 1
}

type Row = { invite: FocusInvite; kind: FocusInviteKind; regIdx: number }

/**
 * FLOW_RECEPTION (invite layer)
 * (1) Reads: full `FlowAssessment` when provided — `rankedActions`, `primaryAction`, `dominantIssue` (via sort order).
 * (2) Behavior: registry `allowed_actions` = capability allowlist; conversational rows sorted by index in
 *     `flowAssessment.rankedActions`; `flowTier` primary | secondary | tertiary by sort position.
 * (3) Hard vs productive: hard — do not treat demoted chips as co-equal (tertiary styling); summarize_for_council
 *     still allowed if in registry (user may choose; productive tension). No blocking clicks in v1.
 */
export function deriveFocusInvites(
  core: FocusContextCore | null | undefined,
  flowAssessment?: FlowAssessment | null,
): FocusInvite[] {
  if (!core) return []
  if (!isInviteEntityType(core.entity_type)) return []

  const regField = registryFieldForCore(core)
  if (!regField) return []

  const et = core.entity_type as FocusInviteEntityType
  const caps = getFieldCapabilities(core.entity_type, regField)
  const allowed = caps?.allowed_actions
  if (!allowed?.length) return []

  const rows: Row[] = []

  for (let i = 0; i < allowed.length; i++) {
    const action = allowed[i]!
    if (EXCLUDED_INVITE_ACTION_IDS.has(action)) continue
    if (action === 'rewrite' && regField === 'brief') continue
    const kind: FocusInviteKind = STRUCTURED_FILL_ACTION_IDS.has(action) ? 'structured_fill' : 'conversational'
    rows.push({
      regIdx: i,
      kind,
      invite: {
        id: `${kind}:${core.entity_type}:${regField}:${action}`,
        kind,
        sourceAction: action,
        label: inviteLabel(action, kind, et, regField, caps?.field_label ?? core.field_label),
      },
    })
  }

  if (!flowAssessment) {
    rows.sort((a, b) => {
      const d = kindRank(a.kind) - kindRank(b.kind)
      if (d !== 0) return d
      return a.regIdx - b.regIdx
    })
    return rows.slice(0, MAX_FOCUS_INVITES_VISIBLE).map((r) => r.invite)
  }

  const conv = rows.filter((r) => r.kind === 'conversational')
  const struct = rows.filter((r) => r.kind === 'structured_fill')
  conv.sort((a, b) => {
    const ai = flowRankIndex(a.invite.sourceAction, flowAssessment.rankedActions)
    const bi = flowRankIndex(b.invite.sourceAction, flowAssessment.rankedActions)
    if (ai !== bi) return ai - bi
    return a.regIdx - b.regIdx
  })
  conv.forEach((r, i) => {
    r.invite.flowTier = i === 0 ? 'primary' : i === 1 ? 'secondary' : 'tertiary'
  })
  struct.sort((a, b) => a.regIdx - b.regIdx)
  const merged = [...conv, ...struct]
  return merged.slice(0, MAX_FOCUS_INVITES_VISIBLE).map((r) => r.invite)
}
