/**
 * Helpers to build StagingArea from MeetingExtraction.
 */

import type { MeetingExtraction } from './types'
import type { StagingArea, StagedItem } from './stagingTypes'

/** Section arrays that accept forwarded extraction rows from another user’s inbox. */
export type ForwardableStagingSectionKey =
  | 'insights'
  | 'ideas'
  | 'initiatives'
  | 'projects'
  | 'tasks'
  | 'assets'
  | 'people'
  | 'signals'

export function emptyStagingArea(): StagingArea {
  return {
    summary: null,
    insights: [],
    ideas: [],
    initiatives: [],
    projects: [],
    tasks: [],
    assets: [],
    people: [],
    signals: [],
  }
}

/** Append a forwarded staged row with a fresh id (avoids collisions with sender). */
export function mergeForwardedCandidateIntoStaging(
  staging: StagingArea | null,
  sectionKey: ForwardableStagingSectionKey,
  item: StagedItem
): StagingArea {
  const base = staging ?? emptyStagingArea()
  const arr = base[sectionKey]
  if (!Array.isArray(arr)) return base
  const newId =
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `fwd_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`
  const newItem = { ...item, id: newId, approved: false } as StagedItem
  return { ...base, [sectionKey]: [...arr, newItem] } as StagingArea
}

/** Build a StagingArea from a MeetingExtraction. All items start unapproved. */
export function buildStagingArea(extraction: MeetingExtraction): StagingArea {
  return {
    summary: extraction.summary
      ? {
          id: extraction.summary.id,
          kind: 'summary',
          data: extraction.summary,
          approved: false,
          interpretation: extraction.summary.interpretation,
        }
      : null,
    insights: (extraction.insights ?? []).map((d) => ({
      id: d.id,
      kind: 'insight' as const,
      data: d,
      approved: false,
      interpretation: d.interpretation,
    })),
    ideas: (extraction.ideas ?? []).map((d) => ({
      id: d.id,
      kind: 'idea' as const,
      data: d,
      approved: false,
      interpretation: d.interpretation,
    })),
    initiatives: (extraction.initiatives ?? []).map((d) => ({
      id: d.id,
      kind: 'initiative' as const,
      data: d,
      approved: false,
      interpretation: d.interpretation,
    })),
    projects: (extraction.projects ?? []).map((d) => ({
      id: d.id,
      kind: 'project' as const,
      data: d,
      approved: false,
      interpretation: d.interpretation,
    })),
    tasks: (extraction.tasks ?? []).map((d) => ({
      id: d.id,
      kind: 'task' as const,
      data: d,
      approved: false,
      interpretation: d.interpretation,
    })),
    assets: (extraction.assets ?? []).map((d) => ({
      id: d.id,
      kind: 'asset' as const,
      data: d,
      approved: false,
      interpretation: d.interpretation,
    })),
    people: (extraction.peopleReferences ?? []).map((d) => ({
      id: d.id,
      kind: 'person' as const,
      data: d,
      approved: false,
      interpretation: d.interpretation,
    })),
    signals: (extraction.signals ?? []).map((d) => ({
      id: d.id,
      kind: 'signal' as const,
      data: d,
      approved: false,
      interpretation: d.interpretation,
    })),
  }
}
