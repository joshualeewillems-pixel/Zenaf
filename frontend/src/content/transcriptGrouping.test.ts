/**
 * Transcript candidate grouping — candidates nest under their
 * topic segment (segment_id); unmatched candidates are loose.
 */
import { describe, it, expect } from 'vitest'
import { groupCandidatesBySegment } from './transcriptGrouping'

const TOPICS = [
  { segment_id: 'seg_1', topic_title: 'Budget' },
  { segment_id: 'seg_2', topic_title: 'Hiring' },
  { segment_id: 'seg_3', topic_title: 'No candidates' },
]

describe('groupCandidatesBySegment', () => {
  it('groups by segment in topic order and leaves unmatched candidates loose', () => {
    const items = [
      { id: 'a', segment_id: 'seg_2' },
      { id: 'b', segment_id: 'seg_1' },
      { id: 'c', segment_id: 'seg_1' },
      { id: 'd', segment_id: 'seg_99' },
      { id: 'e' },
    ]
    const grouping = groupCandidatesBySegment(items, TOPICS)
    expect(grouping.groups.map((g) => g.segment_id)).toEqual(['seg_1', 'seg_2'])
    expect(grouping.groups[0]!.items.map((i) => i.id)).toEqual(['b', 'c'])
    expect(grouping.groups[0]!.topic?.topic_title).toBe('Budget')
    expect(grouping.groups[1]!.items.map((i) => i.id)).toEqual(['a'])
    expect(grouping.loose.map((i) => i.id)).toEqual(['d', 'e'])
  })

  it('returns no groups when there are no topics — everything is loose', () => {
    const grouping = groupCandidatesBySegment([{ id: 'a', segment_id: 'seg_1' }], [])
    expect(grouping.groups).toEqual([])
    expect(grouping.loose.map((i) => i.id)).toEqual(['a'])
  })
})
