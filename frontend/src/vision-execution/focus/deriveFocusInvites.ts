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

/** Outcome-oriented chip copy for structured_fill (rewrite only in v1). */
function structuredFillInviteLabel(
  action: ActionId,
  et: FocusInviteEntityType,
  fieldKey: string,
  fieldLabel: string,
): string {
  if (action !== 'rewrite') return `${ACTION_LABELS[action]} · ${fieldLabel}`
  if (et === 'idea' && fieldKey === 'description') return 'Write description'
  if (fieldKey === 'summary') return 'Write short note'
  if (fieldKey === 'title') return et === 'idea' ? 'Set idea title' : 'Set title'
  if (et === 'initiative' && fieldKey === 'brief') return 'Draft brief'
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

/**
 * Invites for idea/initiative only. Ordering: tie-break by kind (conversational before structured_fill),
 * then Appendix B order = index in `allowed_actions` for that registry row.
 */
export function deriveFocusInvites(core: FocusContextCore | null | undefined): FocusInvite[] {
  if (!core) return []
  if (!isInviteEntityType(core.entity_type)) return []

  const regField = registryFieldForCore(core)
  if (!regField) return []

  const et = core.entity_type as FocusInviteEntityType
  const caps = getFieldCapabilities(core.entity_type, regField)
  const allowed = caps?.allowed_actions
  if (!allowed?.length) return []

  type Row = { invite: FocusInvite; kind: FocusInviteKind; regIdx: number }
  const rows: Row[] = []

  for (let i = 0; i < allowed.length; i++) {
    const action = allowed[i]!
    if (EXCLUDED_INVITE_ACTION_IDS.has(action)) continue
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

  rows.sort((a, b) => {
    const d = kindRank(a.kind) - kindRank(b.kind)
    if (d !== 0) return d
    return a.regIdx - b.regIdx
  })

  return rows.slice(0, MAX_FOCUS_INVITES_VISIBLE).map((r) => r.invite)
}
