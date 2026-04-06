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
  it('returns [] for entity types outside invite pass', () => {
    expect(
      deriveFocusInvites(
        core({
          entity_type: 'council',
          entity_id: 'c1',
          field_key: 'description',
          field_label: 'Description',
        }),
      ),
    ).toEqual([])
  })

  it('does not duplicate brief rewrite as an invite chip (context bar only)', () => {
    for (const et of ['initiative', 'project'] as const) {
      const inv = deriveFocusInvites(
        core({
          entity_type: et,
          entity_id: 'x1',
          field_key: 'brief',
          field_label: 'Brief',
        }),
      )
      expect(inv.some((x) => x.kind === 'structured_fill')).toBe(false)
    }
  })

  it('returns invites for project brief and task description', () => {
    const p = deriveFocusInvites(
      core({
        entity_type: 'project',
        entity_id: 'p1',
        field_key: 'brief',
        field_label: 'Brief',
      }),
    )
    expect(p.some((x) => x.label === 'Sharpen focus')).toBe(true)
    const t = deriveFocusInvites(
      core({
        entity_type: 'task',
        entity_id: 't1',
        field_key: 'description',
        field_label: 'Description',
      }),
    )
    expect(t.some((x) => x.label === 'Sharpen focus')).toBe(true)
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
    expect(invites.some((x) => x.kind === 'conversational')).toBe(true)
    // Surrogate uses idea `description` row: four conversational + rewrite (structured_fill), all within cap.
    expect(invites.length).toBeLessThanOrEqual(5)
    expect(invites.some((x) => x.kind === 'structured_fill')).toBe(true)
  })

  it('orders conversational before structured_fill, then by Appendix B registry index', () => {
    const invites = deriveFocusInvites(
      core({
        entity_type: 'idea',
        entity_id: 'i1',
        field_key: 'title',
        field_label: 'Title',
      }),
    )
    expect(invites.length).toBe(1)
    expect(invites[0]?.kind).toBe('structured_fill')
    expect(invites[0]?.label).toBe('Set idea title')

    const briefInvites = deriveFocusInvites(
      core({
        entity_type: 'project',
        entity_id: 'p1',
        field_key: 'brief',
        field_label: 'Brief',
      }),
    )
    const idxConv = briefInvites.findIndex((x) => x.kind === 'conversational')
    const idxStruct = briefInvites.findIndex((x) => x.kind === 'structured_fill')
    if (idxStruct >= 0 && idxConv >= 0) {
      expect(idxConv).toBeLessThan(idxStruct)
    }
  })
})
