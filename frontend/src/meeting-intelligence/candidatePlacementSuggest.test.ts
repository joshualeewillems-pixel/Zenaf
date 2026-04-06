import { describe, expect, it } from 'vitest'
import { buildStagingPatchFromPlacementSuggestion } from './candidatePlacementSuggest'

describe('buildStagingPatchFromPlacementSuggestion', () => {
  it('does not assume proposed_type is a string (malformed API / nested JSON)', () => {
    const capsule = { themes: [], namedPrograms: [], tags: [] }
    const out = buildStagingPatchFromPlacementSuggestion({
      proposed_type: capsule as unknown as string,
      placement_mode: 'new',
    })
    expect(out.overrideType).toBe('idea')
    expect(out.acceptedExistingId).toBeNull()
  })
})
