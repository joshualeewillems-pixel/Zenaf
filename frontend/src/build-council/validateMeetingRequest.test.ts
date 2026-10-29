import { describe, expect, it } from 'vitest'
import { validateMeetingRequestJson } from './validateMeetingRequest'

/**
 * Client-side validation for the build-council submit page: a failed
 * validation must never start a meeting, so every malformed shape the
 * owner might paste has to fail here, before any POST.
 */
describe('validateMeetingRequestJson', () => {
  const valid = {
    work_item: 'Zenaf build-council — example (single meeting, packet-only)',
    question: 'Is this example sound? Recommend only; do not authorize.',
    constraints: ['The room deliberates; it never decides.'],
    context: ['# Packet\n\nSome packet text.'],
    nominated_paths: [],
    tools_enabled: false,
  }

  it('accepts a full valid request and returns the known-schema body', () => {
    const result = validateMeetingRequestJson(JSON.stringify(valid))
    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.body).toEqual(valid)
    }
  })

  it('accepts a minimal request with only the required fields', () => {
    const result = validateMeetingRequestJson(
      JSON.stringify({
        work_item: 'Work item',
        question: 'Question?',
        context: ['Packet text.'],
      }),
    )
    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.body).toEqual({
        work_item: 'Work item',
        question: 'Question?',
        context: ['Packet text.'],
      })
    }
  })

  it('rejects text that is not valid JSON', () => {
    const result = validateMeetingRequestJson('{not json')
    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.error).toMatch(/Not valid JSON/)
    }
  })

  it('rejects a JSON array or primitive instead of an object', () => {
    expect(validateMeetingRequestJson('[]').ok).toBe(false)
    expect(validateMeetingRequestJson('"just a string"').ok).toBe(false)
    expect(validateMeetingRequestJson('42').ok).toBe(false)
  })

  it('rejects a missing or blank work_item', () => {
    const missing = validateMeetingRequestJson(
      JSON.stringify({ question: 'Q?', context: ['C.'] }),
    )
    expect(missing.ok).toBe(false)
    const blank = validateMeetingRequestJson(
      JSON.stringify({ work_item: '   ', question: 'Q?', context: ['C.'] }),
    )
    expect(blank.ok).toBe(false)
  })

  it('rejects a missing or blank question', () => {
    const missing = validateMeetingRequestJson(
      JSON.stringify({ work_item: 'W', context: ['C.'] }),
    )
    expect(missing.ok).toBe(false)
    const blank = validateMeetingRequestJson(
      JSON.stringify({ work_item: 'W', question: '', context: ['C.'] }),
    )
    expect(blank.ok).toBe(false)
  })

  it('rejects a missing, empty, or non-array context', () => {
    const missing = validateMeetingRequestJson(JSON.stringify({ work_item: 'W', question: 'Q?' }))
    expect(missing.ok).toBe(false)
    const empty = validateMeetingRequestJson(
      JSON.stringify({ work_item: 'W', question: 'Q?', context: [] }),
    )
    expect(empty.ok).toBe(false)
    const wrongType = validateMeetingRequestJson(
      JSON.stringify({ work_item: 'W', question: 'Q?', context: 'Packet text.' }),
    )
    expect(wrongType.ok).toBe(false)
  })

  it('rejects a context entry that is blank or not a string', () => {
    const blankEntry = validateMeetingRequestJson(
      JSON.stringify({ work_item: 'W', question: 'Q?', context: ['   '] }),
    )
    expect(blankEntry.ok).toBe(false)
    const nonStringEntry = validateMeetingRequestJson(
      JSON.stringify({ work_item: 'W', question: 'Q?', context: [42] }),
    )
    expect(nonStringEntry.ok).toBe(false)
  })

  it('rejects non-string entries in optional string arrays', () => {
    const result = validateMeetingRequestJson(
      JSON.stringify({
        work_item: 'W',
        question: 'Q?',
        context: ['C.'],
        constraints: ['fine', 7],
      }),
    )
    expect(result.ok).toBe(false)
  })

  it('rejects a non-boolean tools_enabled', () => {
    const result = validateMeetingRequestJson(
      JSON.stringify({
        work_item: 'W',
        question: 'Q?',
        context: ['C.'],
        tools_enabled: 'yes',
      }),
    )
    expect(result.ok).toBe(false)
  })

  it('drops unknown extra fields instead of failing on them', () => {
    const result = validateMeetingRequestJson(
      JSON.stringify({
        work_item: 'W',
        question: 'Q?',
        context: ['C.'],
        future_field: 'ignored by the server regardless',
      }),
    )
    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.body).toEqual({ work_item: 'W', question: 'Q?', context: ['C.'] })
    }
  })
})
