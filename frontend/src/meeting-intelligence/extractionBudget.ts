/**
 * After multi-chunk external extraction, cap merged row counts so total output does not scale with chunk count.
 */
import type {
  ExtractedAsset,
  ExtractedConfidence,
  ExtractedIdea,
  ExtractedInitiative,
  ExtractedPersonReference,
  ExtractedProject,
  ExtractedTask,
  MeetingExtraction,
} from './types'

function confidenceRank(c: ExtractedConfidence | null | undefined): number {
  if (c === 'high') return 3
  if (c === 'medium') return 2
  if (c === 'low') return 1
  return 0
}

function takeSorted<T extends { confidence?: ExtractedConfidence | null }>(items: T[], cap: number): T[] {
  if (items.length <= cap) return items
  return items
    .map((item, idx) => ({ item, idx, r: confidenceRank(item.confidence) }))
    .sort((a, b) => {
      if (b.r !== a.r) return b.r - a.r
      return a.idx - b.idx
    })
    .slice(0, cap)
    .sort((a, b) => a.idx - b.idx)
    .map((x) => x.item)
}

type PrimaryTag = 'idea' | 'initiative' | 'project' | 'task'

/**
 * Pool actionable rows, keep top `primaryCap` by confidence, redistribute back by original type.
 */
function budgetPrimaryBuckets(
  ideas: ExtractedIdea[],
  initiatives: ExtractedInitiative[],
  projects: ExtractedProject[],
  tasks: ExtractedTask[],
  primaryCap: number,
): {
  ideas: ExtractedIdea[]
  initiatives: ExtractedInitiative[]
  projects: ExtractedProject[]
  tasks: ExtractedTask[]
} {
  const tagged: Array<{ tag: PrimaryTag; r: number; idx: number; idea?: ExtractedIdea; ini?: ExtractedInitiative; proj?: ExtractedProject; task?: ExtractedTask }> = []
  ideas.forEach((item, idx) => tagged.push({ tag: 'idea', r: confidenceRank(item.confidence), idx, idea: item }))
  initiatives.forEach((item, idx) => tagged.push({ tag: 'initiative', r: confidenceRank(item.confidence), idx, ini: item }))
  projects.forEach((item, idx) => tagged.push({ tag: 'project', r: confidenceRank(item.confidence), idx, proj: item }))
  tasks.forEach((item, idx) => tagged.push({ tag: 'task', r: confidenceRank(item.confidence), idx, task: item }))

  tagged.sort((a, b) => {
    if (b.r !== a.r) return b.r - a.r
    if (a.tag !== b.tag) return a.tag.localeCompare(b.tag)
    return a.idx - b.idx
  })
  const kept = tagged.slice(0, primaryCap)
  return {
    ideas: kept.filter((k) => k.tag === 'idea').map((k) => k.idea!),
    initiatives: kept.filter((k) => k.tag === 'initiative').map((k) => k.ini!),
    projects: kept.filter((k) => k.tag === 'project').map((k) => k.proj!),
    tasks: kept.filter((k) => k.tag === 'task').map((k) => k.task!),
  }
}

/**
 * Apply document-level caps after merging chunked external extraction results.
 */
export function applyDocumentLevelExtractionBudget(
  extraction: MeetingExtraction,
  transcriptCharLength: number,
): MeetingExtraction {
  const len = Math.max(0, transcriptCharLength)
  const scale = Math.min(1.35, 1 + len / 140_000)
  const primaryCap = Math.min(40, Math.ceil((10 + Math.floor(len / 16_000)) * scale))
  const signalCap = Math.min(28, Math.ceil((8 + Math.floor(len / 22_000)) * scale))
  const insightCap = Math.min(40, Math.ceil((12 + Math.floor(len / 16_000)) * scale))
  const assetCap = Math.min(18, Math.ceil(9 * scale))
  const peopleCap = Math.min(18, Math.ceil(9 * scale))

  const primary = budgetPrimaryBuckets(
    extraction.ideas,
    extraction.initiatives,
    extraction.projects,
    extraction.tasks,
    primaryCap,
  )

  return {
    ...extraction,
    ideas: primary.ideas,
    initiatives: primary.initiatives,
    projects: primary.projects,
    tasks: primary.tasks,
    signals: takeSorted(extraction.signals, signalCap),
    insights: takeSorted(extraction.insights, insightCap),
    assets: takeSorted(extraction.assets as ExtractedAsset[], assetCap) as MeetingExtraction['assets'],
    peopleReferences: takeSorted(extraction.peopleReferences as ExtractedPersonReference[], peopleCap) as MeetingExtraction['peopleReferences'],
  }
}
