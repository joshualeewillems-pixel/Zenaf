/**
 * Pure shaping logic for the permission home (Permission
 * Simplification P-2). No fetching, no rendering — the section
 * component consumes these, and the tests pin them.
 *
 * Copy provenance: the flag labels/hints are the legacy surface's
 * own rows (PermissionsSection), carried over so the home speaks
 * with the same words; the two Remember layer scope sentences are
 * the accepted design's refinement-2 wording, verbatim. The
 * fellowship_derivation row's wording was ruled by the founder
 * 2026-11-22 and is carried verbatim below.
 */

import type {
  PermissionHomeControl,
  PermissionHomeGroup,
  PermissionHomeState,
  PermissionHomeWriteReport,
} from './api'

export type FlagCopy = { label: string; hint: string }

export const FLAG_COPY: Record<string, FlagCopy> = {
  behavioral_tracking: {
    label: 'Behavioral tracking',
    hint: 'Allow Zenaf to store interaction events used to understand usage patterns.',
  },
  personalization: {
    label: 'Personalization / adaptive responses',
    hint: 'Allow Zenaf to adapt guidance and response style from prior behavior signals.',
  },
  interaction_pattern_storage: {
    label: 'Store interaction patterns',
    hint: 'Allow storing derived interaction pattern summaries over time.',
  },
  profile_learning: {
    label: 'Profile learning from usage',
    hint: 'Allow updates to developmental/profile learning systems from your actions.',
  },
  analytics_product_improvement: {
    label: 'Optional analytics / product improvement',
    hint: 'Allow anonymized learning outcomes to improve product quality.',
  },
  aspiration_store_explicit: {
    label: 'Store explicit aspirations',
    hint: 'Allow saving your authored aspiration profile (Foundation).',
  },
  aspiration_infer_suggestions: {
    label: 'Infer aspiration suggestions',
    hint: 'Allow bounded, non-canonical aspiration theme suggestions you can accept or dismiss.',
  },
  aspiration_use_in_guidance: {
    label: 'Use aspirations in guidance',
    hint: 'Allow compact aspiration blocks in council / core-profile guidance when you opt in per profile.',
  },
  steward_derivation: {
    label: 'Narrative Steward derivation',
    hint: "Can Zenaf connect our talks into ongoing threads and note what they might mean? The notes are kept in your narrative record. You can turn this off at any time — that stops new notes. If you mention someone who isn't in your records yet, Zenaf may keep a provisional note of their name and where they came up. The note isn't a person record, and it doesn't claim anything about who they are. Its only use is to ask — when coordination is also on — whether you'd like them tracked properly. These notes clear and erase with the rest of your narrative record.",
  },
  steward_coordination: {
    label: 'Narrative Steward coordination',
    hint: 'Can Zenaf share derived observations across branches (conversation lines), so a pattern recognized in one place can inform another?',
  },
  fellowship_derivation: {
    // Founder-ruled wording, 2026-11-22 — verbatim.
    label: 'Cross-conversation noticing',
    hint: 'Allow Zenaf to look across your conversations for things a seat would want to raise — each observation tied to the words it came from. You decide whether any of it matters.',
  },
}

export function flagCopy(control: PermissionHomeControl): FlagCopy | null {
  if (control.kind !== 'flag' || !control.key) return null
  return FLAG_COPY[control.key] ?? null
}

export type IntentCopy = {
  id: string
  title: string
  summary: string
}

export const INTENT_COPY: Record<string, IntentCopy> = {
  remember: {
    id: 'remember',
    title: 'Remember',
    summary: 'What Zenaf keeps from your conversations, and whether it connects them into an ongoing story.',
  },
  connect: {
    id: 'connect',
    title: 'Connect',
    summary: 'Whether what one conversation learns can inform another.',
  },
  suggest: {
    id: 'suggest',
    title: 'Suggest',
    summary: 'Whether seats may surface invitations and task proposals for your attention.',
  },
  follow_through: {
    id: 'follow_through',
    title: 'Follow Through',
    summary: 'Reminders for the commitments you have explicitly asked Zenaf to keep after.',
  },
}

/** Layer presentation: titles and the design's scope sentences. */
export const GROUP_COPY: Record<string, { title: string; scope: string }> = {
  retention: {
    title: 'Retention',
    scope: 'Keeps notes from our conversations.',
  },
  story: {
    title: 'Ongoing story',
    scope: 'Connects those notes into an ongoing story and revises it as things change.',
  },
  connect: {
    title: 'Across conversations',
    scope: 'Shares derived observations across conversation lines, so a pattern recognized in one place can inform another.',
  },
  suggest: {
    title: 'Surfacing',
    scope: 'Seats lighting up with something for your attention, and structured task proposals offered as cards you approve, edit, or decline.',
  },
  follow_through: {
    title: 'Reminders',
    scope: 'One row per commitment you have asked Zenaf to keep after, each with its own cadence choice.',
  },
}

export function intentOrder(state: PermissionHomeState): string[] {
  const known = ['remember', 'connect', 'suggest', 'follow_through']
  const present = state.intents.map((i) => i.id)
  return [
    ...known.filter((id) => present.includes(id)),
    ...present.filter((id) => !known.includes(id)),
  ]
}

export function stateLabel(state: string): string {
  switch (state) {
    case 'on':
      return 'On'
    case 'off':
      return 'Off'
    case 'ask_me':
      return 'Ask me'
    case 'custom':
      return 'Custom'
    default:
      return state
  }
}

/**
 * The sync line for a group, in plain words. Two different Custom
 * states exist and must never be conflated (consistency contract):
 * "your granularity" is an intentional mixed state read from the
 * stores; "out of sync" means a write in this session did not fully
 * take — it is known only from that write's report, never inferred
 * from a later read. An incomplete revocation is named as exactly
 * that (founder acceptance qualification 1): never "turned off".
 */
export function syncText(
  group: PermissionHomeGroup,
  lastWrite: PermissionHomeWriteReport | null,
): string | null {
  if (lastWrite && lastWrite.group === group.id && lastWrite.sync === 'out_of_sync') {
    const byId = new Map(lastWrite.controls.map((c) => [c.id, c]))
    const names = lastWrite.failed_controls
      .map((id) => {
        const control = byId.get(id)
        return control ? controlLabel(control) : id
      })
      .join(', ')
    if (lastWrite.revocation === 'incomplete') {
      return `Still on — this turn-off is an incomplete revocation. The change did not take for: ${names}. Repair re-applies your choice.`
    }
    return `Out of sync — the last change did not fully take for: ${names}. Repair re-applies your choice.`
  }
  if (group.state === 'custom') {
    return 'Custom — your granularity: the controls below are set individually.'
  }
  return null
}

/** Whether the Repair action should be offered for a group. */
export function repairFor(
  group: PermissionHomeGroup,
  lastWrite: PermissionHomeWriteReport | null,
): { group: string; state: string } | null {
  if (lastWrite && lastWrite.group === group.id && lastWrite.repair) {
    return lastWrite.repair
  }
  return null
}

/** Human name for a control, for sync/failure lines. */
export function controlLabel(control: PermissionHomeControl): string {
  if (control.kind === 'flag') {
    if (control.wording_pending) return control.key ?? control.id
    return flagCopy(control)?.label ?? control.key ?? control.id
  }
  return control.label ?? control.id
}

/** Plain sentences for the Outside Zenaf always-asks classes. */
export const ALWAYS_ASKS_COPY: Record<string, string> = {
  train: 'Training a model on your material — always asks, per claim.',
  publish: 'Publishing anything as you — always asks.',
  share: 'Sharing anything outside your account — always asks.',
  spend: 'Spending money — always asks.',
  execute: 'Executing actions outside Zenaf — always asks.',
}

export function alwaysAsksText(cls: string): string {
  return ALWAYS_ASKS_COPY[cls] ?? `${cls} — always asks.`
}

/** The Learn distinction's standing explanation (design §2). */
export const LEARN_EXPLANATION =
  'Learn is not a switch. Whether Zenaf may train on your material is decided per claim, at the point of consequence, in Review — nothing here pre-authorizes training in bulk.'
