/**
 * Deterministic review prioritization: blockers/risks and low-confidence first.
 * Used to sort staged items so operators see important/ambiguous items first.
 */

import type { ExtractedConfidence, ExtractedSignalKind } from './types'
import type { StagedItem, StagedItemKind, StagingArea } from './stagingTypes'

// --- Signal priority: blocker > risk > attention > opportunity; then low confidence; then by label

const SIGNAL_KIND_ORDER: Record<ExtractedSignalKind, number> = {
  blocker: 0,
  risk: 1,
  attention: 2,
  opportunity: 3,
}

function confidenceOrder(c: ExtractedConfidence | null | undefined): number {
  if (!c) return 0 // unknown = treat as needs attention
  switch (c) {
    case 'low': return 0
    case 'medium': return 1
    case 'high': return 2
    default: return 0
  }
}

/** Sort key for a signal: [kindOrder, confidenceOrder, label]. Lower = higher priority. */
export function getSignalPriority(signal: { kind: ExtractedSignalKind; label: string; confidence?: ExtractedConfidence | null }): [number, number, string] {
  const kindOrder = SIGNAL_KIND_ORDER[signal.kind] ?? 4
  const confOrder = confidenceOrder(signal.confidence)
  const label = (signal.label ?? '').trim().toLowerCase()
  return [kindOrder, confOrder, label]
}

/** Compare two signals for sort (signals first by kind, then low confidence, then label). */
export function compareSignals(
  a: { kind: ExtractedSignalKind; label: string; confidence?: ExtractedConfidence | null },
  b: { kind: ExtractedSignalKind; label: string; confidence?: ExtractedConfidence | null }
): number {
  const [ka, ca, la] = getSignalPriority(a)
  const [kb, cb, lb] = getSignalPriority(b)
  if (ka !== kb) return ka - kb
  if (ca !== cb) return ca - cb
  return la.localeCompare(lb)
}

// --- Generic item priority: low confidence, extractor match, risk/blocker language, then stable by title/name

const RISK_BLOCKER_WORDS = /\b(blocker|blocked|risk|urgent|critical|blocking)\b/i

function hasRiskBlockerLanguage(data: { title?: string; name?: string; description?: string; brief?: string }): boolean {
  const text = [data.title, data.name, data.description, data.brief].filter(Boolean).join(' ')
  return RISK_BLOCKER_WORDS.test(text)
}

function hasExtractorMatch(data: Record<string, unknown>): boolean {
  return !!(
    data.existingInitiativeMatchId ||
    data.existingProjectMatchId ||
    data.existingTaskMatchId ||
    data.existingAssetMatchId ||
    data.existingPersonMatchId
  )
}

/** Numeric score for generic items. Lower = show first (more important/ambiguous). */
export function getItemPriority(item: StagedItem): number {
  const data = item.data as unknown as Record<string, unknown>
  let score = 500 // baseline

  // Low confidence first (0–200)
  const conf = data.confidence as ExtractedConfidence | null | undefined
  score += confidenceOrder(conf) * 80

  // Extractor-suggested match: needs human decision (subtract 150)
  if (hasExtractorMatch(data)) score -= 150

  // Risk/blocker language: show earlier (subtract 100)
  const title = (data.title ?? data.name ?? '') as string
  const desc = (data.description ?? data.brief ?? '') as string
  if (hasRiskBlockerLanguage({ title, description: desc, brief: desc })) score -= 100

  return score
}

function getItemSortKey(item: StagedItem): string {
  const data = item.data as unknown as Record<string, unknown>
  const title = (data.title ?? data.name ?? item.id) as string
  return (title ?? '').toString().trim().toLowerCase()
}

/** Sort staged items by priority for the given kind. Returns new array; does not mutate. */
export function sortStagedItems<T extends StagedItem>(items: T[], kind: StagedItemKind): T[] {
  if (items.length <= 1) return items.slice()
  if (kind === 'signal') {
    return (items as Array<StagedItem & { data: { kind: ExtractedSignalKind; label: string; confidence?: ExtractedConfidence | null } }>)
      .slice()
      .sort((a, b) => compareSignals(a.data, b.data)) as T[]
  }
  return items.slice().sort((a, b) => {
    const pa = getItemPriority(a)
    const pb = getItemPriority(b)
    if (pa !== pb) return pa - pb
    return getItemSortKey(a).localeCompare(getItemSortKey(b))
  })
}

// --- Section summaries (counts for UI)

export interface SectionSummaryCounts {
  lowConfidence: number
  blockers: number
  possibleDuplicates: number
}

function isLowConfidence(data: Record<string, unknown>): boolean {
  const c = data.confidence as string | null | undefined
  return c === 'low' || !c
}

function countLowConfidence(items: StagedItem[]): number {
  return items.filter((i) => isLowConfidence((i as StagedItem).data as unknown as Record<string, unknown>)).length
}

function countBlockers(items: StagedItem[]): number {
  return items.filter((i) => (i as StagedItem).kind === 'signal' && ((i as StagedItem).data as { kind: string }).kind === 'blocker').length
}

function countPossibleDuplicates(items: StagedItem[]): number {
  return items.filter((i) => hasExtractorMatch((i as StagedItem).data as unknown as Record<string, unknown>)).length
}

/** Derive summary counts from staging area for the given array and kind. */
export function getSectionSummary(items: StagedItem[], kind: StagedItemKind): SectionSummaryCounts {
  const lowConfidence = countLowConfidence(items)
  const blockers = kind === 'signal' ? countBlockers(items) : 0
  const possibleDuplicates = countPossibleDuplicates(items)
  return { lowConfidence, blockers, possibleDuplicates }
}
