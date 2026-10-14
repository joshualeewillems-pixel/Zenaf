import { describe, expect, it } from 'vitest'
import {
  DIMENSION_ORDER,
  FALLBACK_DIMENSIONS,
  levelLabel,
  normalizeLevel,
} from './contextDimensions'

describe('contextDimensions', () => {
  it('has the six canonical dimensions', () => {
    expect(DIMENSION_ORDER).toEqual([
      'stakes',
      'reversibility',
      'time_pressure',
      'information',
      'social_field',
      'resource_climate',
    ])
  })

  it('every dimension offers unknown first', () => {
    for (const dim of DIMENSION_ORDER) {
      expect(FALLBACK_DIMENSIONS.dimensions[dim][0]).toBe('unknown')
    }
  })

  it('normalizes case and separators, unknowns garbage', () => {
    expect(normalizeLevel('stakes', 'Life-Altering')).toBe('life-altering')
    expect(normalizeLevel('social_field', 'publicly accountable')).toBe(
      'publicly_accountable',
    )
    expect(normalizeLevel('stakes', 'enormous')).toBe('unknown')
    expect(normalizeLevel('stakes', null)).toBe('unknown')
    expect(normalizeLevel('nope', 'low')).toBe('unknown')
  })

  it('labels levels human-readably', () => {
    expect(levelLabel('publicly_accountable')).toBe('publicly accountable')
    expect(levelLabel('unknown')).toBe('unknown')
  })
})
