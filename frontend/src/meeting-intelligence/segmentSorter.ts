/**
 * Classify transcript segments into topic buckets using simple heuristics:
 * keyword detection, speaker hints, segment title cues.
 * Used to skip "noise" segments before extraction.
 */

import type { TranscriptSegment } from './types'

export type SegmentTopic =
  | 'operations'
  | 'planning'
  | 'strategy'
  | 'logistics'
  | 'inventory'
  | 'marketing'
  | 'discussion'
  | 'noise'

export interface SortedSegments {
  operations: TranscriptSegment[]
  planning: TranscriptSegment[]
  strategy: TranscriptSegment[]
  logistics: TranscriptSegment[]
  inventory: TranscriptSegment[]
  marketing: TranscriptSegment[]
  discussion: TranscriptSegment[]
  noise: TranscriptSegment[]
}

const TOPIC_ORDER: SegmentTopic[] = [
  'operations',
  'planning',
  'strategy',
  'logistics',
  'inventory',
  'marketing',
  'discussion',
  'noise',
]

/** Keyword lists (lowercase) per topic. First match wins when scanning title then text. */
const KEYWORDS: Record<Exclude<SegmentTopic, 'noise' | 'discussion'>, string[]> = {
  operations: [
    'operations', 'operational', 'run rate', 'throughput', 'capacity', 'process', 'workflow',
    'sop', 'runbook', 'execution', 'delivery', 'fulfillment', 'production', 'manufacturing',
  ],
  planning: [
    'plan', 'planning', 'roadmap', 'timeline', 'schedule', 'milestone', 'deadline', 'q1', 'q2', 'q3', 'q4',
    'next week', 'next month', 'quarter', 'budget', 'forecast', 'target date', 'launch date',
  ],
  strategy: [
    'strategy', 'strategic', 'vision', 'goal', 'objective', 'priority', 'initiative', 'okr', 'kpi',
    'direction', 'positioning', 'competitive', 'market', 'growth', 'expansion', 'pivot',
  ],
  logistics: [
    'logistics', 'shipping', 'delivery', 'supply chain', 'warehouse', 'distribution', 'freight',
    'transport', 'inbound', 'outbound', 'carrier', 'lead time', 'fulfillment',
  ],
  inventory: [
    'inventory', 'stock', 'sku', 'warehouse', 'reorder', 'safety stock', 'buffer', 'on hand',
    'backorder', 'allocation', 'lot', 'batch', 'cycle count',
  ],
  marketing: [
    'marketing', 'campaign', 'brand', 'promotion', 'channel', 'demand', 'lead', 'conversion',
    'audience', 'messaging', 'content', 'social', 'advertising', 'awareness',
  ],
}

/** Title cues: phrases in segment title that strongly suggest a topic. */
const TITLE_CUES: Record<Exclude<SegmentTopic, 'noise' | 'discussion'>, string[]> = {
  operations: ['operations', 'ops', 'run rate', 'process', 'execution'],
  planning: ['planning', 'plan', 'roadmap', 'timeline', 'schedule', 'quarter'],
  strategy: ['strategy', 'strategic', 'goals', 'priorities', 'initiatives'],
  logistics: ['logistics', 'shipping', 'supply', 'delivery', 'distribution'],
  inventory: ['inventory', 'stock', 'warehouse', 'sku'],
  marketing: ['marketing', 'campaign', 'brand', 'channel'],
}

/** Minimum content length to avoid labeling as noise. Very short segments are noise. */
const MIN_CONTENT_LENGTH = 40

/** Classify a single segment into a topic bucket. */
function classifySegment(segment: TranscriptSegment): SegmentTopic {
  const title = (segment.title ?? '').trim().toLowerCase()
  const text = (segment.text ?? '').trim().toLowerCase()
  const combined = `${title} ${text}`

  if (combined.length < MIN_CONTENT_LENGTH) return 'noise'
  if (/^(ok|yes|no|thanks|thank you|sure|sounds good|got it|bye|hello|hi)\s*\.?$/i.test(combined.trim())) return 'noise'
  if (/^[\s\-\–\—\*\•\.\,\:]+$/.test(combined.replace(/\s/g, ''))) return 'noise'

  // Check title cues first (stronger signal)
  for (const topic of TOPIC_ORDER) {
    if (topic === 'noise' || topic === 'discussion') continue
    const cues = TITLE_CUES[topic]
    if (cues.some((c) => title.includes(c))) return topic
  }

  // Keyword detection in title then text
  for (const topic of TOPIC_ORDER) {
    if (topic === 'noise' || topic === 'discussion') continue
    const words = KEYWORDS[topic]
    if (words.some((w) => title.includes(w) || text.includes(w))) return topic
  }

  return 'discussion'
}

/**
 * Sort segments into topic buckets. Each segment is assigned to exactly one bucket.
 * Preserves segment id and segmentTitle; segments are not mutated.
 */
export function sortSegmentsByTopic(segments: TranscriptSegment[]): SortedSegments {
  const result: SortedSegments = {
    operations: [],
    planning: [],
    strategy: [],
    logistics: [],
    inventory: [],
    marketing: [],
    discussion: [],
    noise: [],
  }
  for (const seg of segments) {
    const topic = classifySegment(seg)
    result[topic].push(seg)
  }
  return result
}

/**
 * Return segments that should be sent to extraction (all topics except noise),
 * in a deterministic order: operations, planning, strategy, logistics, inventory, marketing, discussion.
 */
export function getSegmentsToExtract(sorted: SortedSegments): TranscriptSegment[] {
  const out: TranscriptSegment[] = []
  for (const topic of TOPIC_ORDER) {
    if (topic === 'noise') continue
    out.push(...sorted[topic])
  }
  return out
}
