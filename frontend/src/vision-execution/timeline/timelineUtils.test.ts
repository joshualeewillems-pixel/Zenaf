/**
 * Timeline row subline + row-height invariant.
 *
 * Regression coverage for the narrow-viewport refactor of the Vision →
 * Execution timeline: tree rows have a FIXED height (the grid aligns bars by
 * row index, so tree rows cannot grow), so a row must never need more than
 * label + ONE subline. timelineRowSubline is the single place that combines
 * the summary and waits-on note; these tests pin that contract and the
 * height budget it fits in.
 */
import { describe, expect, it } from 'vitest'
import {
  TIMELINE_ROW_HEIGHT_PX,
  timelineRowSubline,
} from './timelineUtils'

describe('timelineRowSubline', () => {
  it('returns null text/title when there is neither summary nor waits', () => {
    expect(timelineRowSubline(null, undefined)).toEqual({
      text: null,
      title: null,
      summary: null,
      waits: null,
    })
    expect(timelineRowSubline('   ', [])).toEqual({
      text: null,
      title: null,
      summary: null,
      waits: null,
    })
  })

  it('passes a summary through unchanged', () => {
    const sub = timelineRowSubline('Restless, allergic to lock-in', undefined)
    expect(sub.text).toBe('Restless, allergic to lock-in')
    expect(sub.title).toBe('Restless, allergic to lock-in')
    expect(sub.summary).toBe('Restless, allergic to lock-in')
    expect(sub.waits).toBeNull()
  })

  it('renders waits-on alone, truncated to two names with a remainder', () => {
    const sub = timelineRowSubline(null, ['Alpha', 'Beta', 'Gamma'])
    expect(sub.text).toBe('⏳ waits on Alpha, Beta +1')
    expect(sub.title).toBe('Waits on: Alpha, Beta, Gamma')
    expect(sub.summary).toBeNull()
    expect(sub.waits).toBe('⏳ waits on Alpha, Beta +1')
  })

  it('combines summary and waits into a single line, full list in the title', () => {
    const sub = timelineRowSubline('Ship the Fox intro', ['Alpha', 'Beta', 'Gamma'])
    expect(sub.text).toBe('Ship the Fox intro · ⏳ waits on Alpha, Beta +1')
    expect(sub.title).toBe('Ship the Fox intro · Waits on: Alpha, Beta, Gamma')
  })

  it('keeps the combined line to one logical line (no newlines)', () => {
    const sub = timelineRowSubline('A summary', ['X'])
    expect(sub.text).not.toContain('\n')
    expect(sub.text?.split(' · ')).toHaveLength(2)
  })
})

describe('timeline row height budget', () => {
  it('fits label + one subline + padding (regression: fixed-height rows collided)', () => {
    // Tailwind metrics for the tree row: text-sm label line-height 20px,
    // mt-0.5 gap 2px, 11px subline at default leading ~16.5px, py-1 padding 8px.
    const labelLinePx = 20
    const sublineGapPx = 2
    const sublineLinePx = 16.5
    const verticalPaddingPx = 8
    const requiredPx = labelLinePx + sublineGapPx + sublineLinePx + verticalPaddingPx
    expect(TIMELINE_ROW_HEIGHT_PX).toBeGreaterThanOrEqual(Math.ceil(requiredPx))
  })

  it('stays a single shared constant both sides of the timeline use', () => {
    // Tree and grid both receive this value; a drift between them would
    // misalign bars and rows. The constant must stay a positive integer.
    expect(Number.isInteger(TIMELINE_ROW_HEIGHT_PX)).toBe(true)
    expect(TIMELINE_ROW_HEIGHT_PX).toBeGreaterThan(0)
  })
})
