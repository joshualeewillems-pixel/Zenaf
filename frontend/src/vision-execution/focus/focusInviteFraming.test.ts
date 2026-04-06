import { describe, expect, it } from 'vitest'
import {
  boundedTransformDisabledForQuestion,
  buildConversationalInviteDisplayLine,
  buildConversationalInvitePreface,
  buildScopedContextLabelFromCore,
  buildStructuredFillInvitePreface,
  CONVERSATIONAL_INVITE_MARKER,
  replaceStructuredFillComposerValue,
  STRUCTURED_FILL_INVITE_MARKER,
  threadDisplayLineForCouncilQuestion,
} from './focusInviteFraming'
import type { FocusInvite } from './focusInviteTypes'
import type { FocusContextCore } from './types'

const core = (partial: Partial<FocusContextCore>): FocusContextCore => ({
  surface: 'vision_execution',
  entity_type: 'idea',
  entity_id: 'e1',
  field_key: 'description',
  field_label: 'Expanded description',
  field_kind: 'idea_body',
  ...partial,
})

const fillInvite: FocusInvite = {
  id: 'x',
  kind: 'structured_fill',
  sourceAction: 'rewrite',
  label: 'Write description',
}

const convInvite: FocusInvite = {
  id: 'c',
  kind: 'conversational',
  sourceAction: 'surface_tensions',
  label: 'Explore tensions',
}

describe('focusInviteFraming helpers', () => {
  it('boundedTransformDisabledForQuestion detects invite payloads', () => {
    expect(boundedTransformDisabledForQuestion('break this into tasks')).toBe(false)
    expect(boundedTransformDisabledForQuestion(`prefix\n${CONVERSATIONAL_INVITE_MARKER}`)).toBe(true)
    expect(boundedTransformDisabledForQuestion(`x ${STRUCTURED_FILL_INVITE_MARKER}`)).toBe(true)
  })

  it('buildConversationalInviteDisplayLine is a short human header (no ids)', () => {
    const line = buildConversationalInviteDisplayLine(convInvite, core({}))
    expect(line).toContain('Thinking partner')
    expect(line).not.toContain('e1')
    expect(line).not.toContain('vision_execution')
  })

  it('buildScopedContextLabelFromCore strips internal idea: title prefix from lineage', () => {
    const label = buildScopedContextLabelFromCore(
      core({ lineage_labels: ['idea: Create a mailing list signup'] }),
    )
    expect(label).toBe('Idea · Create a mailing list signup')
    expect(label).not.toContain('idea:')
  })

  it('buildConversationalInvitePreface carries explicit per-intent rules', () => {
    const distill = buildConversationalInvitePreface(
      { id: 'd', kind: 'conversational', sourceAction: 'distill', label: 'Sharpen focus' },
      core({}),
    )
    expect(distill).toContain('Goal:')
    expect(distill).toContain('Prefer commitment over exploration')
    const expand = buildConversationalInvitePreface(
      { id: 'e', kind: 'conversational', sourceAction: 'expand_to_steps', label: 'Expand steps' },
      core({}),
    )
    expect(expand).toContain('mappable')
    const tensions = buildConversationalInvitePreface(
      { id: 't', kind: 'conversational', sourceAction: 'surface_tensions', label: 'Explore tensions' },
      core({}),
    )
    expect(tensions).toContain('Assumption audit')
    expect(tensions).toContain('Pre-mortem')
    const council = buildConversationalInvitePreface(
      { id: 's', kind: 'conversational', sourceAction: 'summarize_for_council', label: 'Summarize for council' },
      core({}),
    )
    expect(council).toContain('Stakeholders')
    expect(council).toContain('definition of done')
  })

  it('threadDisplayLineForCouncilQuestion maps stored preface to display line', () => {
    const preface = buildConversationalInvitePreface(convInvite, core({}))
    expect(threadDisplayLineForCouncilQuestion(preface)).toContain('Thinking partner')
    const structured = buildStructuredFillInvitePreface(fillInvite, core({ field_label: 'Brief' }))
    expect(threadDisplayLineForCouncilQuestion(structured)).toContain('Draft')
    expect(threadDisplayLineForCouncilQuestion(structured)).toContain('Brief')
  })

  it('replaceStructuredFillComposerValue resets composer to the new contract only (no append)', () => {
    const a = buildStructuredFillInvitePreface(fillInvite, core({}))
    const b = buildStructuredFillInvitePreface(
      fillInvite,
      core({ entity_id: 'e2', field_label: 'Other' }),
    )
    const merged = replaceStructuredFillComposerValue(`My notes\n\n${a}`, b)
    expect(merged).toBe(b)
    expect(merged).toContain(STRUCTURED_FILL_INVITE_MARKER)
    expect(merged).toContain('Other')
    expect(merged).not.toContain('My notes')
    expect(merged).not.toContain('e2')
  })

  it('buildStructuredFillInvitePreface has no entity id and names the field', () => {
    const s = buildStructuredFillInvitePreface(fillInvite, core({ field_label: 'Short note', entity_id: 'secret-id' }))
    expect(s).toContain('Short note')
    expect(s).toContain('idea')
    expect(s).not.toContain('secret-id')
  })
})
