import { describe, expect, it } from 'vitest'
import {
  boundedTransformDisabledForQuestion,
  buildStructuredFillInvitePreface,
  CONVERSATIONAL_INVITE_MARKER,
  replaceStructuredFillComposerValue,
  STRUCTURED_FILL_INVITE_MARKER,
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
  label: 'Draft for field',
}

describe('focusInviteFraming helpers', () => {
  it('boundedTransformDisabledForQuestion detects invite payloads', () => {
    expect(boundedTransformDisabledForQuestion('break this into tasks')).toBe(false)
    expect(boundedTransformDisabledForQuestion(`prefix\n${CONVERSATIONAL_INVITE_MARKER}`)).toBe(true)
    expect(boundedTransformDisabledForQuestion(`x ${STRUCTURED_FILL_INVITE_MARKER}`)).toBe(true)
  })

  it('replaceStructuredFillComposerValue replaces block without stacking prefaces', () => {
    const a = buildStructuredFillInvitePreface(fillInvite, core({}))
    const b = buildStructuredFillInvitePreface(
      fillInvite,
      core({ entity_id: 'e2', field_label: 'Other' }),
    )
    const merged = replaceStructuredFillComposerValue(`My notes\n\n${a}`, b)
    expect(merged.startsWith('My notes')).toBe(true)
    expect(merged).toContain(STRUCTURED_FILL_INVITE_MARKER)
    expect(merged).toContain('e2')
    expect(merged.indexOf(STRUCTURED_FILL_INVITE_MARKER)).toBe(merged.lastIndexOf(STRUCTURED_FILL_INVITE_MARKER))
  })
})
