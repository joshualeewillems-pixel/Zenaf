import { describe, expect, it } from 'vitest'
import {
  parseArtifact,
  parseMeetingHistoryList,
  parseTranscript,
} from './meetingHistory'

describe('parseMeetingHistoryList', () => {
  it('parses a valid list with standalone and program entries', () => {
    const parsed = parseMeetingHistoryList({
      meetings: [
        {
          meeting_id: 'aaa111',
          work_item: 'fix the thing',
          question: 'what should change?',
          ok: true,
          claim_count: 2,
          has_transcript: true,
          has_artifact: true,
          has_capture: false,
        },
        {
          meeting_id: 'bbb222',
          work_item: null,
          question: null,
          ok: null,
          claim_count: null,
          has_transcript: true,
          has_artifact: false,
          has_capture: false,
          error: 'artifact unreadable: boom',
        },
      ],
      total: 2,
      offset: 0,
      limit: 50,
      order: 'mtime_desc',
    })
    expect(parsed.ok).toBe(true)
    if (!parsed.ok) return
    expect(parsed.list.total).toBe(2)
    expect(parsed.list.meetings[0].has_capture).toBe(false)
    expect(parsed.list.meetings[1].error).toBe('artifact unreadable: boom')
  })

  it('rejects non-objects, bad totals, and mistyped entries', () => {
    expect(parseMeetingHistoryList(null).ok).toBe(false)
    expect(parseMeetingHistoryList({ meetings: [], total: -1, offset: 0, limit: 50, order: 'mtime_desc' }).ok).toBe(false)
    expect(
      parseMeetingHistoryList({
        meetings: [{ meeting_id: 'aaa111', work_item: 42, question: null, ok: null, claim_count: null, has_transcript: true, has_artifact: true, has_capture: false }],
        total: 1,
        offset: 0,
        limit: 50,
        order: 'mtime_desc',
      }).ok,
    ).toBe(false)
    expect(
      parseMeetingHistoryList({
        meetings: [{ work_item: null, question: null, ok: null, claim_count: null, has_transcript: true, has_artifact: true, has_capture: false }],
        total: 1,
        offset: 0,
        limit: 50,
        order: 'mtime_desc',
      }).ok,
    ).toBe(false)
  })
})

describe('parseTranscript', () => {
  it('parses verbatim entries including null participants', () => {
    const parsed = parseTranscript({
      meeting_id: 'aaa111',
      entries: [
        { kind: 'convene', participant: null, text: 'convene text' },
        { kind: 'contribution', participant: 'Muse', text: 'claim text' },
      ],
    })
    expect(parsed.ok).toBe(true)
    if (!parsed.ok) return
    expect(parsed.transcript.entries).toHaveLength(2)
    expect(parsed.transcript.entries[0].participant).toBeNull()
  })

  it('rejects missing ids, non-array entries, and textless entries', () => {
    expect(parseTranscript({ entries: [] }).ok).toBe(false)
    expect(parseTranscript({ meeting_id: 'aaa111', entries: 'nope' }).ok).toBe(false)
    expect(parseTranscript({ meeting_id: 'aaa111', entries: [{ kind: 'contribution', participant: 'Muse' }] }).ok).toBe(false)
  })
})

describe('parseArtifact', () => {
  it('summarizes key fields and passes the raw object through', () => {
    const raw = {
      meeting_id: 'aaa111',
      work_item: 'fix the thing',
      question: 'what should change?',
      ok: true,
      claim_registry: [{ id: 'C1' }, { id: 'C2' }],
      transjective_record: { validation_phase: 'final', conformant: false },
      transjective_validation_reports: [{ phase: 'opening' }],
    }
    const parsed = parseArtifact(raw)
    expect(parsed.ok).toBe(true)
    if (!parsed.ok) return
    expect(parsed.summary.claim_count).toBe(2)
    expect(parsed.summary.transjective_conformant).toBe(false)
    expect(parsed.summary.interim_report_count).toBe(1)
    expect(parsed.raw).toBe(raw)
  })

  it('tolerates absent transjective sections as nulls', () => {
    const parsed = parseArtifact({ meeting_id: 'aaa111', work_item: null, question: null, ok: null })
    expect(parsed.ok).toBe(true)
    if (!parsed.ok) return
    expect(parsed.summary.claim_count).toBeNull()
    expect(parsed.summary.transjective_conformant).toBeNull()
    expect(parsed.summary.interim_report_count).toBeNull()
  })

  it('rejects non-objects and missing ids', () => {
    expect(parseArtifact(null).ok).toBe(false)
    expect(parseArtifact({ work_item: 'x' }).ok).toBe(false)
  })
})
