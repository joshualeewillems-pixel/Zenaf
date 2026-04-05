import { describe, expect, it } from 'vitest'
import { CONVERSATION_ENTITY_FIELD_KEY } from './conversationEntityFocus'
import { deriveFocusInvites } from './deriveFocusInvites'
import type { FocusContextCore } from './types'

function core(partial: Partial<FocusContextCore> & Pick<FocusContextCore, 'entity_type' | 'entity_id' | 'field_key' | 'field_label'>): FocusContextCore {
  return {
    surface: 'vision_execution',
    field_kind: 'idea_body',
    ...partial,
  }
}

describe('deriveFocusInvites', () => {
  it('returns [] for non idea/initiative', () => {
    expect(
      deriveFocusInvites(
        core({
          entity_type: 'task',
          entity_id: 't1',
          field_key: 'description',
          field_label: 'Description',
        }),
      ),
    ).toEqual([])
  })

  it('uses surrogate registry field for conversation-entity sentinel', () => {
    const invites = deriveFocusInvites(
      core({
        entity_type: 'idea',
        entity_id: 'i1',
        field_key: CONVERSATION_ENTITY_FIELD_KEY,
        field_label: 'idea: X',
      }),
    )
    const kinds = invites.map((x) => x.kind)
    expect(kinds.filter((k) => k === 'conversational').length).toBeGreaterThan(0)
    expect(invites.some((x) => x.sourceAction === 'rewrite' && x.kind === 'structured_fill')).toBe(true)
  })

  it('orders conversational before structured_fill, then by Appendix B registry index', () => {
    const invites = deriveFocusInvites(
      core({
        entity_type: 'idea',
        entity_id: 'i1',
        field_key: 'description',
        field_label: 'Expanded description',
      }),
    )
    const labels = invites.map((x) => x.label)
    const firstStructured = invites.findIndex((x) => x.kind === 'structured_fill')
    const lastConversational = invites.map((x) => x.kind).lastIndexOf('conversational')
    expect(firstStructured).toBeGreaterThan(-1)
    expect(lastConversational).toBeLessThan(firstStructured)
    expect(labels[0]).not.toBe('Draft for field')
  })
})
