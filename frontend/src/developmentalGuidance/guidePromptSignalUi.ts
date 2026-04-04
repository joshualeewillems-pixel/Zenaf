/**
 * Session-only UX for guide notifications: decay, escalation, and count rules.
 * No persistence — complements prompt_signals on the server.
 *
 * Decay: tier `hidden` (>24h) drops out of bar unread counts and uses a compact list row until the user
 * expands — the full prompt + actions then render at full weight when used by inline thread UI.
 */

import type { GuideEntityKey, GuideThreadMessage } from './guideEntityStack'

export type PromptSignalUiState = {
  created_at: number
  last_seen_at: number | null
  last_interacted_at: number | null
  times_shown: number
}

export type DecayTier = 'full' | 'dim' | 'faint' | 'hidden'

const MIN = 60_000
const HOUR = 3600_000
const DAY = 24 * HOUR

/** Unread + this many stack “visits” without any action → ⚠️ escalation (session-only). */
const ESCALATE_AFTER_VISITS = 3
/**
 * Nudge appears only after one more ignored visit than escalation — calmer than showing both at once.
 */
const NUDGE_AFTER_VISITS = 4

/** Age of signal since first tracked appearance (session). */
export function signalAgeDecayTier(createdAtMs: number, now = Date.now()): DecayTier {
  const age = now - createdAtMs
  if (age < 10 * MIN) return 'full'
  if (age < 60 * MIN) return 'dim'
  if (age < DAY) return 'faint'
  return 'hidden'
}

export function decayTierCollapsedRowClass(tier: DecayTier): string {
  switch (tier) {
    case 'full':
      return ''
    case 'dim':
      return 'opacity-85'
    case 'faint':
      return 'opacity-55'
    case 'hidden':
      return 'opacity-40'
  }
}

export function decayTierBarClass(tier: DecayTier): string {
  switch (tier) {
    case 'full':
      return ''
    case 'dim':
      return 'opacity-90'
    case 'faint':
      return 'opacity-70'
    case 'hidden':
      return 'opacity-55'
  }
}

/** Unread on active node for this long → ⚠️ (without requiring 3 visits). Kept generous so it does not feel jumpy. */
const PERSIST_ESCALATE_MS = 2 * HOUR

function isUnread(pid: string, seenPromptIds: Set<string>): boolean {
  return !seenPromptIds.has(pid)
}

function guideMatchesActiveStack(
  m: GuideThreadMessage,
  stackKey: GuideEntityKey,
  mapNodeId: string | null,
): boolean {
  const t = m.promptSignal?.vm_entity_type?.toLowerCase()?.trim()
  const id = m.promptSignal?.vm_entity_id?.trim()
  if (t && id) {
    return t === stackKey.type.toLowerCase() && id === stackKey.id
  }
  if (mapNodeId && id === mapNodeId) return true
  return false
}

export function shouldEscalateSignal(args: {
  record: PromptSignalUiState
  unread: boolean
  matchesActiveNode: boolean
  now: number
}): boolean {
  const { record, unread, matchesActiveNode, now } = args
  if (!unread) return false
  if (record.last_interacted_at != null) return false
  if (record.times_shown >= ESCALATE_AFTER_VISITS) return true
  if (matchesActiveNode && now - record.created_at >= PERSIST_ESCALATE_MS) return true
  return false
}

export type GuideRowDisplayModel = {
  message: GuideThreadMessage
  promptId: string
  tier: DecayTier
  unread: boolean
  escalated: boolean
  countsForBarUnread: boolean
}

export type GuideStackBarModel = {
  unreadCount: number
  escalatedUnreadCount: number
  barLabel: string
  barDecayTier: DecayTier
  showIgnoreNudge: boolean
  nudgePromptId: string | null
  rows: GuideRowDisplayModel[]
}

function worseTier(a: DecayTier, b: DecayTier): DecayTier {
  const order: DecayTier[] = ['full', 'dim', 'faint', 'hidden']
  return order[Math.max(order.indexOf(a), order.indexOf(b))]!
}

export function formatGuideStackBarModel(args: {
  guides: GuideThreadMessage[]
  getPromptId: (m: GuideThreadMessage) => string
  seenPromptIds: Set<string>
  uiByPromptId: Record<string, PromptSignalUiState>
  barSubtitle: string
  stackKey: GuideEntityKey
  mapNodeId: string | null
  now: number
}): GuideStackBarModel {
  const { guides, getPromptId, seenPromptIds, uiByPromptId, barSubtitle, stackKey, mapNodeId, now } = args

  const rows: GuideRowDisplayModel[] = guides.map((m) => {
    const promptId = getPromptId(m)
    const rec = uiByPromptId[promptId] ?? {
      created_at: now,
      last_seen_at: null,
      last_interacted_at: null,
      times_shown: 0,
    }
    const tier = signalAgeDecayTier(rec.created_at, now)
    const unread = isUnread(promptId, seenPromptIds)
    const matchesActiveNode = guideMatchesActiveStack(m, stackKey, mapNodeId)
    const escalated = shouldEscalateSignal({
      record: rec,
      unread,
      matchesActiveNode,
      now,
    })
    const countsForBarUnread = unread && tier !== 'hidden'
    return { message: m, promptId, tier, unread, escalated, countsForBarUnread }
  })

  const unreadCount = rows.filter((r) => r.countsForBarUnread).length
  const escalatedUnreadCount = rows.filter((r) => r.escalated && r.countsForBarUnread).length

  let barLabel: string
  if (escalatedUnreadCount > 0) {
    barLabel =
      escalatedUnreadCount === 1
        ? `⚠️ 1 thing may need attention — ${barSubtitle}`
        : `⚠️ ${escalatedUnreadCount} things may need attention — ${barSubtitle}`
  } else if (unreadCount > 0) {
    barLabel =
      unreadCount === 1
        ? `🔔 New notification — ${barSubtitle}`
        : `🔔 ${unreadCount} new notifications — ${barSubtitle}`
  } else {
    const total = guides.length
    barLabel =
      total === 1 ? `🔔 1 notification — ${barSubtitle}` : `🔔 ${total} notifications — ${barSubtitle}`
  }

  const staleUnreadOnly =
    rows.some((r) => r.unread) && unreadCount === 0 && rows.some((r) => r.unread && r.tier === 'hidden')
  if (staleUnreadOnly) {
    const n = rows.filter((r) => r.unread).length
    barLabel =
      n === 1
        ? `🔔 Older notification — open to review — ${barSubtitle}`
        : `🔔 ${n} older notifications — open to review — ${barSubtitle}`
  }

  const nudgeRow = rows.find(
    (r) =>
      r.unread &&
      (uiByPromptId[r.promptId]?.times_shown ?? 0) >= NUDGE_AFTER_VISITS &&
      (uiByPromptId[r.promptId]?.last_interacted_at ?? null) == null,
  )

  let barDecayTier: DecayTier = 'full'
  for (const r of rows) {
    if (r.countsForBarUnread) barDecayTier = worseTier(barDecayTier, r.tier)
  }
  if (unreadCount === 0 && staleUnreadOnly) {
    for (const r of rows) {
      if (r.unread) barDecayTier = worseTier(barDecayTier, r.tier)
    }
  }

  return {
    unreadCount,
    escalatedUnreadCount,
    barLabel,
    barDecayTier,
    showIgnoreNudge: Boolean(nudgeRow),
    nudgePromptId: nudgeRow?.promptId ?? null,
    rows,
  }
}

export function initialPromptSignalUi(now = Date.now()): PromptSignalUiState {
  return {
    created_at: now,
    last_seen_at: null,
    last_interacted_at: null,
    times_shown: 0,
  }
}
