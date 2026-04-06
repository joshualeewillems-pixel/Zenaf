import { describe, expect, it } from 'vitest'
import { enrichScopedDigressionLabel, isGenericScopedEntityLabel } from './enrichScopedDigressionLabel'
import type { EntityMentionOpenPayload } from '../components/EntityMentionText'

describe('enrichScopedDigressionLabel', () => {
  it('detects generic entity stub labels', () => {
    expect(isGenericScopedEntityLabel('Entity d4aca9c0…')).toBe(true)
    expect(isGenericScopedEntityLabel('Idea · Real title here')).toBe(false)
  })

  it('replaces stub with live idea title from snapshot', () => {
    const p: EntityMentionOpenPayload = {
      entityId: 'idea-1',
      entityType: 'idea',
      label: 'Entity d4aca9c0…',
    }
    const out = enrichScopedDigressionLabel(p, {
      ideaLabels: {
        entity_type: 'idea',
        entity_id: 'idea-1',
        ve_focus_title: 'Mailing list signup',
        ve_focus_brief: '',
        ve_focus_description: '',
      },
      bundle: null,
    })
    expect(out.label).toBe('Idea · Mailing list signup')
  })

  it('falls back to bundle list title', () => {
    const p: EntityMentionOpenPayload = {
      entityId: 'i2',
      entityType: 'idea',
      label: 'Entity d4aca9c0…',
    }
    const out = enrichScopedDigressionLabel(p, {
      ideaLabels: null,
      bundle: {
        ideas: [{ id: 'i2', title: 'From list' } as import('../vision-execution/types').Idea],
        initiatives: [],
        projects: [],
        tasks: [],
      },
    })
    expect(out.label).toBe('Idea · From list')
  })
})
