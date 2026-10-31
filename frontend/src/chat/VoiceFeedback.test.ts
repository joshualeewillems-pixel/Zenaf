import { describe, expect, it } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import VoiceFeedback, {
  FEEDBACK_PRESETS,
  NEUTRAL_SLIDER_VALUE,
  SLIDER_FACES,
  faceForValue,
} from './VoiceFeedback'

function renderWidget(expanded: boolean): string {
  return renderToStaticMarkup(
    createElement(VoiceFeedback, {
      messageId: 'm1',
      seat: 'mentor',
      conversationId: 'skeleton',
      defaultExpanded: expanded,
    }),
  )
}

describe('slider defaults', () => {
  it('defaults to the neutral middle stop', () => {
    expect(NEUTRAL_SLIDER_VALUE).toBe(4)
    expect(faceForValue(4)).toBe('😐')
  })

  it('renders the slider at neutral when expanded', () => {
    const html = renderWidget(true)
    expect(html).toContain('value="4"')
    expect(html).toContain('😐')
    expect(html).toContain('Sounds like me')
    expect(html).toContain('Say more in your own words')
  })

  it('renders collapsed with no slider and no submit', () => {
    // Untouched means no controls to submit from: nothing can be sent
    // until the user expands and explicitly submits.
    const html = renderWidget(false)
    expect(html).toContain('How did this land?')
    expect(html).not.toContain('type="range"')
    expect(html).not.toContain('Save feedback')
  })
})

describe('faces and presets', () => {
  it('has seven faces, neutral in the middle', () => {
    expect(SLIDER_FACES).toHaveLength(7)
    expect(SLIDER_FACES[3]).toBe('😐')
    expect(faceForValue(1)).toBe('😞')
    expect(faceForValue(7)).toBe('🤩')
    expect(faceForValue(0)).toBe('😞')
    expect(faceForValue(99)).toBe('🤩')
  })

  it('uses the design doc six presets', () => {
    expect([...FEEDBACK_PRESETS]).toEqual([
      'Sounds like me',
      'Sounds like the seat',
      'Helpful',
      'Missed the mark',
      'Tone feels off',
      'Want more of this',
    ])
  })
})
