import { describe, expect, it } from 'vitest'
import { sanitizeCouncilAssistantTextForDisplay } from './councilUserVisibleSanitize'

describe('sanitizeCouncilAssistantTextForDisplay', () => {
  it('expands draft tags and strips same-line required coaching', () => {
    const raw = 'Here is wording:\n[DRAFT_VALUE: Convert readers into subscribers] is required to save.'
    const out = sanitizeCouncilAssistantTextForDisplay(raw)
    expect(out).toContain('Convert readers into subscribers')
    expect(out.toLowerCase()).not.toContain('required')
    expect(out).not.toContain('[DRAFT_VALUE')
  })

  it('removes orphan draft tag lines', () => {
    const raw = 'Try this.\n[DRAFT_VALUE: incomplete'
    const out = sanitizeCouncilAssistantTextForDisplay(raw)
    expect(out).not.toContain('[DRAFT_VALUE')
    expect(out).toContain('Try this')
  })

  it('still replaces standard draft tags', () => {
    const raw = 'Done.\n[DRAFT_VALUE: short note text]'
    const out = sanitizeCouncilAssistantTextForDisplay(raw)
    expect(out).toContain('short note text')
    expect(out).not.toContain('[DRAFT_VALUE')
  })
})
