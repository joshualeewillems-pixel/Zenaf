/**
 * Transcript candidate grouping — the founder's parents/loose
 * display rule applied to the TranscriptSorter result.
 *
 * The sorter result's own data model anchors every candidate
 * (task / decision / idea) to a topic segment via `segment_id`,
 * and `topics` is the list of those segments. So the parent of a
 * candidate is its topic; a candidate whose `segment_id` matches
 * no topic is loose. The default listing shows the topic parents
 * (and loose candidates) only; expanding a topic reveals its
 * candidates in place.
 */

export interface TranscriptTopicLike {
  segment_id: string
  topic_title?: string
  substantive?: boolean
}

export interface SegmentCandidateGroup<T> {
  segment_id: string
  topic: TranscriptTopicLike | null
  items: T[]
}

export interface SegmentGrouping<T> {
  groups: SegmentCandidateGroup<T>[]
  /** Candidates whose segment_id matches no topic. */
  loose: T[]
}

export function groupCandidatesBySegment<T extends { segment_id?: string }>(
  items: T[],
  topics: TranscriptTopicLike[],
): SegmentGrouping<T> {
  const topicBySegment = new Map(topics.map((t) => [t.segment_id, t]))
  const bySegment = new Map<string, T[]>()
  const loose: T[] = []
  for (const item of items) {
    const seg = item.segment_id || ''
    if (seg && topicBySegment.has(seg)) {
      const arr = bySegment.get(seg) ?? []
      arr.push(item)
      bySegment.set(seg, arr)
    } else {
      loose.push(item)
    }
  }
  // Groups render in topic order (the transcript's own order).
  const groups: SegmentCandidateGroup<T>[] = []
  for (const topic of topics) {
    const arr = bySegment.get(topic.segment_id)
    if (arr && arr.length > 0) {
      groups.push({ segment_id: topic.segment_id, topic, items: arr })
    }
  }
  return { groups, loose }
}
