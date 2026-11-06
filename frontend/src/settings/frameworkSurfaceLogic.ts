/**
 * Pure shaping logic for the Slice 2 framework surface (Rev2 §2.2–§2.3,
 * corrections C3, C4.5, R.1–R.4). No fetching, no rendering — the
 * component consumes these, and the tests pin them.
 *
 * C3 (one record, shown twice): the strand group and the general noting
 * group render rows of the SAME R1 capability object, so the two
 * displays cannot disagree — there is no second record to diverge.
 */

import type { FrameworkCapability, FrameworkRow, FrameworkState } from './api'

export type SurfaceGroup = {
  key: string
  title: string
  note?: string
  capabilities: FrameworkCapability[]
  /** Which rows of each capability this group shows (default: all). */
  rowFilter?: (row: FrameworkRow) => boolean
}

export function buildGroups(state: FrameworkState): SurfaceGroup[] {
  const byId = new Map(state.capabilities.map((c) => [c.id, c]))
  const pick = (...ids: string[]): FrameworkCapability[] =>
    ids.flatMap((id) => {
      const cap = byId.get(id)
      return cap ? [cap] : []
    })
  const groups: SurfaceGroup[] = [
    {
      key: 'noting-general',
      title: 'Noting — general',
      capabilities: pick('R1'),
    },
    {
      key: 'strand',
      title: 'Strand interviews',
      note: 'The same noting permission, shown for strand scopes — setting it here sets it everywhere.',
      capabilities: pick('R1'),
      rowFilter: (row) => row.kind === 'strand',
    },
    {
      key: 'steward',
      title: 'Steward',
      note: 'These stance records are the framework\u2019s baseline. The existing steward switches stay authoritative for steward behavior until the capabilities are wired (Slice 6).',
      capabilities: pick('R2', 'R3'),
    },
    {
      key: 'fellowship',
      title: 'Fellowship',
      capabilities: pick('R4'),
    },
    {
      key: 'vision-execution',
      title: 'Vision Execution',
      capabilities: pick('R5', 'R6'),
    },
  ]
  return groups.filter((g) => g.capabilities.length > 0)
}

export function rowsForGroup(group: SurfaceGroup, capability: FrameworkCapability): FrameworkRow[] {
  if (!group.rowFilter) return capability.rows
  return capability.rows.filter(group.rowFilter)
}

/** Plain-words nouns for a capability's retained items (Rev2 §4.2). */
export function retainedItemNoun(capabilityId: string): { singular: string; plural: string } {
  switch (capabilityId) {
    case 'R1':
      return { singular: 'pending note', plural: 'pending notes' }
    case 'R2':
      return { singular: 'derived thread', plural: 'derived threads' }
    case 'R3':
      return { singular: 'distributed observation', plural: 'distributed observations' }
    case 'R4':
      return { singular: 'pending invitation', plural: 'pending invitations' }
    case 'R5':
      return { singular: 'pending proposal', plural: 'pending proposals' }
    case 'R6':
      return { singular: 'live reminder', plural: 'live reminders' }
    default:
      return { singular: 'retained item', plural: 'retained items' }
  }
}

/**
 * The retained-information choice line for a capability, in plain
 * words with its count (R.2). Returns null when there is nothing
 * retained to choose about. Slice 2 deviation (D1, see the surface
 * component): Review is offered only where a real per-item surface
 * exists (R6 → Today); Delete is offered nowhere in Slice 2, because
 * no capability has a lawful bulk-erase for its retained items yet —
 * the full three-action choice lands with the Slice 3 Review queue.
 * The line therefore names, per capability, where the items live
 * instead of offering a Review button that goes nowhere.
 */
export function retainedChoiceText(capability: FrameworkCapability): string | null {
  const n = capability.retained_count
  if (n <= 0) return null
  const noun = retainedItemNoun(capability.id).plural
  const count = `${n} ${noun}`
  switch (capability.id) {
    case 'R1':
      return `Your ${count} are still here. They'll stay pending. Review and delete for notes arrive with the Review queue (Slice 3).`
    case 'R2':
      return `Your ${count} are still here and readable. Review and delete for threads arrive with the Review queue (Slice 3).`
    case 'R4':
      return `Your ${count} are still here. They'll stay pending until you answer them in conversation.`
    case 'R5':
      return `Your ${count} are still here. They'll stay pending until you approve or decline them in conversation.`
    case 'R6':
      return `Your ${count} are still here.`
    default:
      return `Your ${count} are still here.`
  }
}

/** The choice line opens after a revocation that leaves items behind. */
export function shouldOfferRetainedChoice(
  capability: FrameworkCapability,
  lastChange: { capability: string; stance: string } | null,
): boolean {
  return (
    lastChange !== null &&
    lastChange.capability === capability.id &&
    lastChange.stance === 'dont_do_it' &&
    capability.retained_count > 0
  )
}

/**
 * Where "Review" for a capability's retained items goes in Slice 2.
 * Only R6 has a real per-item decision surface today (the Today deck,
 * with ack/snooze per nudge). Every other capability's Review waits
 * for the Slice 3 Review queue; R4/R5 items are answered in their
 * conversations. Returns 'today' or null.
 */
export function reviewDestination(capabilityId: string): 'today' | null {
  return capabilityId === 'R6' ? 'today' : null
}

export function pluralize(count: number, singular: string, plural: string): string {
  return count === 1 ? singular : plural
}
