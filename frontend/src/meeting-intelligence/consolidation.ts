/**
 * Deterministic "buffer 0.5" pass: merge cross-chunk extraction rows that are partial views
 * of the same concept (shared anchor token or high token overlap). No ML.
 *
 * Runs after per-chunk extract + promote (i.e. on merged MeetingExtraction), before staging/UI normalization.
 */

import type {
  ExtractedAsset,
  ExtractedConfidence,
  ExtractedIdea,
  ExtractedInitiative,
  ExtractedPersonReference,
  ExtractedProject,
  ExtractedSignal,
  ExtractedTask,
  MeetingExtraction,
} from './types'

const STOP = new Set([
  'the',
  'a',
  'an',
  'and',
  'or',
  'for',
  'to',
  'of',
  'in',
  'on',
  'at',
  'by',
  'with',
  'from',
  'as',
  'is',
  'are',
  'was',
  'were',
  'be',
  'been',
  'being',
  'have',
  'has',
  'had',
  'do',
  'does',
  'did',
  'will',
  'would',
  'could',
  'should',
  'may',
  'might',
  'must',
  'this',
  'that',
  'these',
  'those',
  'it',
  'its',
  'we',
  'our',
  'you',
  'your',
  'they',
  'their',
  'i',
  'me',
  'my',
])

const nanoid = () => `ext-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 9)}`

/** Lowercase, strip punctuation, collapse whitespace — for keys and overlap. */
export function normalizeCandidateText(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9\s]+/gi, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

export function tokenSet(norm: string): Set<string> {
  const parts = norm.split(' ').filter(Boolean)
  const out = new Set<string>()
  for (const p of parts) {
    if (p.length < 2 || STOP.has(p)) continue
    out.add(p)
  }
  return out
}

function jaccard(a: Set<string>, b: Set<string>): number {
  if (a.size === 0 && b.size === 0) return 1
  let inter = 0
  for (const t of a) {
    if (b.has(t)) inter++
  }
  const union = a.size + b.size - inter
  return union === 0 ? 0 : inter / union
}

/** Shared anchor: substring containment (word-ish) or strong token overlap. */
export function shouldClusterByTitle(na: string, nb: string): boolean {
  if (!na || !nb) return false
  if (na === nb) return true
  const minLen = Math.min(na.length, nb.length)
  const longer = na.length >= nb.length ? na : nb
  const shorter = na.length >= nb.length ? nb : na
  if (shorter.length >= 4 && longer.includes(shorter)) return true

  const ta = tokenSet(na)
  const tb = tokenSet(nb)
  const jac = jaccard(ta, tb)
  if (jac >= 0.55) return true
  const sigShared = [...ta].filter((t) => t.length >= 4 && tb.has(t))
  if (sigShared.length >= 1 && jac >= 0.35) return true
  if (sigShared.length >= 2 && jac >= 0.25) return true
  if (minLen >= 6 && jac >= 0.45) return true
  return false
}

class DSU {
  private readonly p: number[]
  constructor(n: number) {
    this.p = Array.from({ length: n }, (_, i) => i)
  }
  find(i: number): number {
    if (this.p[i] !== i) this.p[i] = this.find(this.p[i])
    return this.p[i]
  }
  union(a: number, b: number): void {
    const ra = this.find(a)
    const rb = this.find(b)
    if (ra !== rb) this.p[rb] = ra
  }
}

function maxConfidence(cs: (ExtractedConfidence | null | undefined)[]): ExtractedConfidence | null {
  const order: ExtractedConfidence[] = ['high', 'medium', 'low']
  let best: ExtractedConfidence | null = null
  let bi = -1
  for (const c of cs) {
    if (!c) continue
    const i = order.indexOf(c)
    if (i >= 0 && i > bi) {
      bi = i
      best = c
    }
  }
  return best
}

function uniqueNonEmpty(lines: (string | null | undefined)[]): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const raw of lines) {
    const s = (raw ?? '').trim()
    if (!s) continue
    const k = s.toLowerCase()
    if (seen.has(k)) continue
    seen.add(k)
    out.push(s)
  }
  return out
}

function chunkCountFor(items: { segmentId?: string }[]): number {
  return new Set(items.map((i) => i.segmentId).filter(Boolean)).size
}

type WithAnchorRole = { anchorRole?: string | null }

function anchorRolesCompatible(a: WithAnchorRole, b: WithAnchorRole): boolean {
  const ra = (a.anchorRole ?? '').trim()
  const rb = (b.anchorRole ?? '').trim()
  if (!ra || !rb) return true
  if (ra === 'general' || rb === 'general') return true
  return ra === rb
}

function mergedAnchorRole(items: WithAnchorRole[]): string | undefined {
  const rs = items.map((i) => (i.anchorRole ?? '').trim()).filter(Boolean)
  if (rs.length === 0) return undefined
  const u = new Set(rs)
  if (u.size === 1) return rs[0]
  return 'general'
}

function mergeIdeas(items: ExtractedIdea[]): ExtractedIdea {
  const sorted = [...items].sort((a, b) => (b.title?.length ?? 0) - (a.title?.length ?? 0))
  const rep = sorted[0]!
  const excerpts = uniqueNonEmpty(items.map((i) => i.sourceExcerpt ?? undefined))
  const bodies = uniqueNonEmpty(items.flatMap((i) => [i.description, i.summary]))
  const cc = chunkCountFor(items)
  return {
    ...rep,
    id: nanoid(),
    title: rep.title,
    description: bodies.join('\n\n').slice(0, 8000) || rep.description,
    summary: rep.summary,
    sourceExcerpt: excerpts.join('\n\n---\n\n').slice(0, 8000) || rep.sourceExcerpt,
    confidence: maxConfidence(items.map((i) => i.confidence)),
    consolidationMeta: {
      mergedCount: items.length,
      chunkCount: cc,
      mentionCount: items.length,
    },
    anchorRole: mergedAnchorRole(items) ?? rep.anchorRole,
  }
}

function mergeInitiatives(items: ExtractedInitiative[]): ExtractedInitiative {
  const sorted = [...items].sort((a, b) => (b.title?.length ?? 0) - (a.title?.length ?? 0))
  const rep = sorted[0]!
  const excerpts = uniqueNonEmpty(items.map((i) => i.sourceExcerpt ?? undefined))
  const briefs = uniqueNonEmpty(items.map((i) => i.brief ?? i.description))
  const notes = uniqueNonEmpty(items.map((i) => i.notes))
  const cc = chunkCountFor(items)
  const mergedBrief = briefs.join('\n\n').slice(0, 8000)
  return {
    ...rep,
    id: nanoid(),
    title: rep.title,
    brief: mergedBrief || rep.brief,
    description: mergedBrief || rep.description,
    notes: notes.join('\n\n').slice(0, 4000) || rep.notes,
    sourceExcerpt: excerpts.join('\n\n---\n\n').slice(0, 8000) || rep.sourceExcerpt,
    confidence: maxConfidence(items.map((i) => i.confidence)),
    consolidationMeta: {
      mergedCount: items.length,
      chunkCount: cc,
      mentionCount: items.length,
    },
    anchorRole: mergedAnchorRole(items) ?? rep.anchorRole,
  }
}

function mergeTasks(items: ExtractedTask[]): ExtractedTask {
  const sorted = [...items].sort((a, b) => (b.title?.length ?? 0) - (a.title?.length ?? 0))
  const rep = sorted[0]!
  const excerpts = uniqueNonEmpty(items.map((i) => i.sourceExcerpt ?? undefined))
  const descs = uniqueNonEmpty(items.map((i) => i.description))
  const notes = uniqueNonEmpty(items.map((i) => i.notes))
  const cc = chunkCountFor(items)
  return {
    ...rep,
    id: nanoid(),
    title: rep.title,
    description: descs.join('\n\n').slice(0, 8000) || rep.description,
    notes: notes.join('\n\n').slice(0, 4000) || rep.notes,
    sourceExcerpt: excerpts.join('\n\n---\n\n').slice(0, 8000) || rep.sourceExcerpt,
    confidence: maxConfidence(items.map((i) => i.confidence)),
    consolidationMeta: {
      mergedCount: items.length,
      chunkCount: cc,
      mentionCount: items.length,
    },
    anchorRole: mergedAnchorRole(items) ?? rep.anchorRole,
  }
}

function mergeProjects(items: ExtractedProject[]): ExtractedProject {
  const sorted = [...items].sort((a, b) => (b.title?.length ?? 0) - (a.title?.length ?? 0))
  const rep = sorted[0]!
  const excerpts = uniqueNonEmpty(items.map((i) => i.sourceExcerpt ?? undefined))
  const briefs = uniqueNonEmpty(items.map((i) => i.brief))
  const cc = chunkCountFor(items)
  const mergedBrief = briefs.join('\n\n').slice(0, 8000)
  return {
    ...rep,
    id: nanoid(),
    title: rep.title,
    brief: mergedBrief || rep.brief,
    sourceExcerpt: excerpts.join('\n\n---\n\n').slice(0, 8000) || rep.sourceExcerpt,
    confidence: maxConfidence(items.map((i) => i.confidence)),
    consolidationMeta: {
      mergedCount: items.length,
      chunkCount: cc,
      mentionCount: items.length,
    },
  }
}

function mergeAssets(items: ExtractedAsset[]): ExtractedAsset {
  const sorted = [...items].sort((a, b) => (b.name?.length ?? 0) - (a.name?.length ?? 0))
  const rep = sorted[0]!
  const excerpts = uniqueNonEmpty(items.map((i) => i.sourceExcerpt ?? undefined))
  const descs = uniqueNonEmpty(items.map((i) => i.description))
  const cc = chunkCountFor(items)
  return {
    ...rep,
    id: nanoid(),
    name: rep.name,
    description: descs.join('\n\n').slice(0, 8000) || rep.description,
    sourceExcerpt: excerpts.join('\n\n---\n\n').slice(0, 8000) || rep.sourceExcerpt,
    confidence: maxConfidence(items.map((i) => i.confidence)),
    consolidationMeta: {
      mergedCount: items.length,
      chunkCount: cc,
      mentionCount: items.length,
    },
    anchorRole: mergedAnchorRole(items) ?? rep.anchorRole,
  }
}

function mergePeople(items: ExtractedPersonReference[]): ExtractedPersonReference {
  const sorted = [...items].sort((a, b) => (b.name?.length ?? 0) - (a.name?.length ?? 0))
  const rep = sorted[0]!
  const excerpts = uniqueNonEmpty(items.map((i) => i.sourceExcerpt ?? undefined))
  const contexts = uniqueNonEmpty(items.map((i) => i.context))
  const roles = uniqueNonEmpty(items.map((i) => i.role))
  const cc = chunkCountFor(items)
  return {
    ...rep,
    id: nanoid(),
    name: rep.name,
    role: roles[0] ?? rep.role,
    context: contexts.join('\n\n').slice(0, 8000) || rep.context,
    sourceExcerpt: excerpts.join('\n\n---\n\n').slice(0, 8000) || rep.sourceExcerpt,
    confidence: maxConfidence(items.map((i) => i.confidence)),
    consolidationMeta: {
      mergedCount: items.length,
      chunkCount: cc,
      mentionCount: items.length,
    },
    anchorRole: mergedAnchorRole(items) ?? rep.anchorRole,
  }
}

function mergeSignals(items: ExtractedSignal[]): ExtractedSignal {
  const sorted = [...items].sort((a, b) => (b.label?.length ?? 0) - (a.label?.length ?? 0))
  const rep = sorted[0]!
  const excerpts = uniqueNonEmpty(items.map((i) => i.sourceExcerpt ?? undefined))
  const details = uniqueNonEmpty(items.map((i) => i.detail))
  const cc = chunkCountFor(items)
  return {
    ...rep,
    id: nanoid(),
    label: rep.label,
    detail: details.join('\n\n').slice(0, 8000) || rep.detail,
    sourceExcerpt: excerpts.join('\n\n---\n\n').slice(0, 8000) || rep.sourceExcerpt,
    confidence: maxConfidence(items.map((i) => i.confidence)),
    consolidationMeta: {
      mergedCount: items.length,
      chunkCount: cc,
      mentionCount: items.length,
    },
    anchorRole: mergedAnchorRole(items) ?? rep.anchorRole,
  }
}

function clusterIndices<T extends { id: string } & WithAnchorRole>(
  items: T[],
  getTitle: (t: T) => string,
): number[][] {
  const n = items.length
  if (n <= 1) return items.map((_, i) => [i])
  const norms = items.map((it) => normalizeCandidateText(getTitle(it)))
  const dsu = new DSU(n)
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      if (
        shouldClusterByTitle(norms[i]!, norms[j]!) &&
        anchorRolesCompatible(items[i]!, items[j]!)
      ) {
        dsu.union(i, j)
      }
    }
  }
  const buckets = new Map<number, number[]>()
  for (let i = 0; i < n; i++) {
    const r = dsu.find(i)
    const arr = buckets.get(r)
    if (arr) arr.push(i)
    else buckets.set(r, [i])
  }
  return [...buckets.values()].sort((a, b) => a[0]! - b[0]!)
}

function consolidateByTitle<T extends { id: string } & WithAnchorRole>(
  items: T[],
  getTitle: (t: T) => string,
  merge: (group: T[]) => T,
): T[] {
  if (items.length === 0) return []
  const clusters = clusterIndices(items, getTitle)
  return clusters.map((idxs) => {
    const group = idxs.map((i) => items[i]!)
    return group.length === 1 ? group[0]! : merge(group)
  })
}

/**
 * Apply cross-row consolidation to a merged extraction. Idempotent for single-row lists.
 * Preserves summary/insights/error; rewrites entity arrays in stable cluster order.
 */
export function consolidateMeetingExtraction(extraction: MeetingExtraction): MeetingExtraction {
  return {
    ...extraction,
    ideas: consolidateByTitle(extraction.ideas, (i) => i.title, mergeIdeas),
    initiatives: consolidateByTitle(extraction.initiatives, (i) => i.title, mergeInitiatives),
    tasks: consolidateByTitle(extraction.tasks, (i) => i.title, mergeTasks),
    projects: consolidateByTitle(extraction.projects, (i) => i.title, mergeProjects),
    assets: consolidateByTitle(extraction.assets, (i) => i.name, mergeAssets),
    peopleReferences: consolidateByTitle(extraction.peopleReferences, (i) => i.name, mergePeople),
    signals: consolidateByTitle(extraction.signals, (i) => i.label, mergeSignals),
  }
}
