import { describe, expect, it } from 'vitest'
import {
  collectNodeInterpretationInvariantViolations,
  interpretationTextLooksLikeQuestion,
} from './nodeInterpretationInvariants'
import type { NodeInterpretation } from './unifiedNodeAssessmentTypes'

describe('interpretationTextLooksLikeQuestion', () => {
  it('detects trailing question mark', () => {
    expect(interpretationTextLooksLikeQuestion('What is the scope?')).toBe(true)
  })
  it('detects leading question words', () => {
    expect(interpretationTextLooksLikeQuestion('Who owns the next move?')).toBe(true)
    expect(interpretationTextLooksLikeQuestion('How should we sequence this?')).toBe(true)
  })
  it('rejects flat statements', () => {
    expect(interpretationTextLooksLikeQuestion('Expand into concrete steps.')).toBe(false)
  })
})

describe('collectNodeInterpretationInvariantViolations', () => {
  it('clarify_first requires question-shaped chatPrefill', () => {
    const bad: NodeInterpretation = {
      stance: 'clarify_first',
      blockingClarification: true,
      summary: 'Summary here.',
      actionLine: 'One clarification is needed before choosing the next move.',
      chatPrefill: 'Not a question sentence.',
      clarificationQuestion: 'Not a question sentence.',
      ambiguityType: 'missing_definition',
    }
    const v = collectNodeInterpretationInvariantViolations(bad)
    expect(v.some((x) => x.includes('chatPrefill'))).toBe(true)
  })

  it('clarify_first passes when chatPrefill is a question', () => {
    const good: NodeInterpretation = {
      stance: 'clarify_first',
      blockingClarification: true,
      summary: 'Summary here.',
      actionLine: 'One clarification is needed before choosing the next move.',
      chatPrefill: 'What is the one-sentence problem statement for this work?',
      clarificationQuestion: 'What is the one-sentence problem statement for this work?',
      ambiguityType: 'missing_definition',
    }
    expect(collectNodeInterpretationInvariantViolations(good)).toEqual([])
  })

  it('proceed flags undermine when chatPrefill contradicts expand intent', () => {
    const inv: NodeInterpretation = {
      stance: 'proceed',
      summary: 'S',
      actionLine: 'Expand into concrete steps tied to measurable outcomes.',
      chatPrefill: "don't expand the scope yet",
    }
    const v = collectNodeInterpretationInvariantViolations(inv)
    expect(v.some((x) => x.includes('undermine'))).toBe(true)
  })

  it('proceed passes when chatPrefill aligns with expansion', () => {
    const inv: NodeInterpretation = {
      stance: 'proceed',
      summary: 'S',
      actionLine: 'Expand into concrete steps tied to measurable outcomes.',
      chatPrefill: 'What measurable milestone will prove this initiative is converting effort into outcomes?',
    }
    expect(collectNodeInterpretationInvariantViolations(inv)).toEqual([])
  })
})
