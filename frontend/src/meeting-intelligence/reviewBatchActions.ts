/**
 * Batch review actions: accept/reject groups of staged items by confidence,
 * extractor match, segment, or whole section. Also batch "Use existing" linking.
 * All updates preserve array order and item ids.
 */

import type { StagedItem } from './stagingTypes'
import { findBestMatch } from './duplicateDetection'

const DEFAULT_MATCH_THRESHOLD = 0.5

/** Shape used for heuristic match candidate lists (id + title or name). */
export interface ExistingEntitiesLike {
  initiatives?: { id: string; title?: string; name?: string }[]
  projects?: { id: string; title?: string; name?: string }[]
  tasks?: { id: string; title?: string; name?: string }[]
  ideas?: { id: string; title?: string; name?: string }[]
  assets?: { id: string; title?: string; name?: string }[]
  people?: { id: string; title?: string; name?: string }[]
}

type ItemWithData = StagedItem & { data: Record<string, unknown> }

function hasHighConfidence(data: Record<string, unknown>): boolean {
  return data.confidence === 'high'
}

function hasLowConfidence(data: Record<string, unknown>): boolean {
  const c = data.confidence
  return c === 'low' || c == null || c === ''
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

function hasSegmentId(data: Record<string, unknown>, segmentId: string): boolean {
  const id = data.segmentId
  return id != null && String(id).trim() === String(segmentId).trim()
}

/** Set approved to true for items with confidence === 'high'. Others unchanged. */
export function acceptHighConfidence<T extends StagedItem>(items: T[]): T[] {
  return items.map((item) => {
    const data = (item as ItemWithData).data as Record<string, unknown>
    return hasHighConfidence(data) ? { ...item, approved: true } : item
  })
}

/** Set approved to true for items with extractor-suggested existing match. Others unchanged. */
export function acceptExtractorMatches<T extends StagedItem>(items: T[]): T[] {
  return items.map((item) => {
    const data = (item as ItemWithData).data as Record<string, unknown>
    return hasExtractorMatch(data) ? { ...item, approved: true } : item
  })
}

/** Set approved to false for items with low or missing confidence. Others unchanged. */
export function rejectLowConfidence<T extends StagedItem>(items: T[]): T[] {
  return items.map((item) => {
    const data = (item as ItemWithData).data as Record<string, unknown>
    return hasLowConfidence(data) ? { ...item, approved: false } : item
  })
}

/** Set approved to true for items with data.segmentId === segmentId. Others unchanged. */
export function acceptSegment<T extends StagedItem>(items: T[], segmentId: string): T[] {
  return items.map((item) => {
    const data = (item as ItemWithData).data as Record<string, unknown>
    return hasSegmentId(data, segmentId) ? { ...item, approved: true } : item
  })
}

/** Set approved to true for all items in the section. */
export function acceptSection<T extends StagedItem>(items: T[]): T[] {
  return items.map((item) => ({ ...item, approved: true }))
}

/** Set approved to false for all items in the section. */
export function rejectSection<T extends StagedItem>(items: T[]): T[] {
  return items.map((item) => ({ ...item, approved: false }))
}

/** Unique segment ids present in items, with optional title. */
export function getSegmentIdsFromItems(items: StagedItem[]): { segmentId: string; segmentTitle: string }[] {
  const seen = new Set<string>()
  const out: { segmentId: string; segmentTitle: string }[] = []
  for (const item of items) {
    const data = (item as ItemWithData).data as Record<string, unknown>
    const id = data.segmentId != null ? String(data.segmentId).trim() : ''
    if (!id || seen.has(id)) continue
    seen.add(id)
    const title = (data.segmentTitle != null ? String(data.segmentTitle).trim() : id) || id
    out.push({ segmentId: id, segmentTitle: title })
  }
  return out
}

// --- Batch "Use existing" linking

function getExtractorMatchId(data: Record<string, unknown>): string | null {
  const raw =
    data.existingInitiativeMatchId ??
    data.existingProjectMatchId ??
    data.existingTaskMatchId ??
    data.existingAssetMatchId ??
    data.existingPersonMatchId
  const id = raw != null ? String(raw).trim() : ''
  return id || null
}

/** Set acceptedExistingId from extractor-suggested match fields where available. */
export function useExtractorMatches<T extends StagedItem>(items: T[]): T[] {
  return items.map((item) => {
    const data = (item as ItemWithData).data as Record<string, unknown>
    const id = getExtractorMatchId(data)
    return id ? { ...item, acceptedExistingId: id } : item
  })
}

function getCandidates(
  sectionKey: string,
  existing: ExistingEntitiesLike | null
): { id: string; title: string }[] {
  if (!existing) return []
  const list =
    sectionKey === 'ideas' ? existing.ideas
    : sectionKey === 'initiatives' ? existing.initiatives
    : sectionKey === 'projects' ? existing.projects
    : sectionKey === 'tasks' ? existing.tasks
    : sectionKey === 'assets' ? existing.assets
    : sectionKey === 'people' ? existing.people
    : null
  if (!list?.length) return []
  return list.map((e) => ({ id: e.id, title: (e.title ?? e.name ?? '').toString() }))
}

/** Set acceptedExistingId from heuristic best match where no extractor match exists. */
export function useHeuristicMatches<T extends StagedItem>(
  items: T[],
  sectionKey: string,
  existingEntities: ExistingEntitiesLike | null,
  threshold: number = DEFAULT_MATCH_THRESHOLD
): T[] {
  const candidates = getCandidates(sectionKey, existingEntities)
  if (candidates.length === 0) return items
  return items.map((item) => {
    const data = (item as ItemWithData).data as Record<string, unknown>
    if (getExtractorMatchId(data)) return item
    const title = (data.title ?? data.name ?? '').toString().trim()
    const match = findBestMatch(title, candidates, threshold)
    return match ? { ...item, acceptedExistingId: match.id } : item
  })
}

/** Apply linking (extractor then heuristic) only for items in the given segment. */
export function useSegmentMatches<T extends StagedItem>(
  items: T[],
  segmentId: string,
  sectionKey: string,
  existingEntities: ExistingEntitiesLike | null,
  threshold: number = DEFAULT_MATCH_THRESHOLD
): T[] {
  const candidates = getCandidates(sectionKey, existingEntities)
  return items.map((item) => {
    const data = (item as ItemWithData).data as Record<string, unknown>
    if (!hasSegmentId(data, segmentId)) return item
    const extractorId = getExtractorMatchId(data)
    if (extractorId) return { ...item, acceptedExistingId: extractorId }
    if (candidates.length === 0) return item
    const title = (data.title ?? data.name ?? '').toString().trim()
    const match = findBestMatch(title, candidates, threshold)
    return match ? { ...item, acceptedExistingId: match.id } : item
  })
}

/** Clear acceptedExistingId on all items. */
export function clearAcceptedExisting<T extends StagedItem>(items: T[]): T[] {
  return items.map((item) => ({ ...item, acceptedExistingId: null }))
}
