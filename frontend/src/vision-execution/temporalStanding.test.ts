/**
 * Temporal standing fold (S1) — the client mirror of the backend
 * fold in local_ai/vision_execution/temporal_standing.py. The two
 * folds must agree on the same records: same validation, same
 * assumption-set ids, same supersede/withdraw semantics.
 */
import { describe, expect, it } from 'vitest'
import {
  assumptionSetId,
  foldTemporalStanding,
  pickWindowSpan,
  sha256Hex,
  type TemporalDecisionRow,
} from './temporalStanding'

function row(partial: Partial<TemporalDecisionRow> & { id: string }): TemporalDecisionRow {
  return {
    entity_type: 'project',
    entity_id: 'proj-1',
    decision_type: 'temporal_span_recorded',
    final_values_snapshot: null,
    created_at: '2026-11-28T00:00:00',
    ...partial,
  }
}

function spanRow(
  id: string,
  snap: Record<string, unknown>,
  partial: Partial<TemporalDecisionRow> = {},
): TemporalDecisionRow {
  return row({ id, final_values_snapshot: snap, ...partial })
}

const ENVELOPE = {
  start: '2026-10-20',
  end: '2026-12-01',
  origin: 'evidence-recovered',
  standing: 'evidence-recovered envelope',
  role: 'window',
  effort: { kind: 'exact', hours: 12 },
  basis: ['recorded task due dates 2026-12-01'],
  method: 'evidence recovery over recorded task due dates',
}

describe('sha256Hex', () => {
  it('matches the published vectors', () => {
    expect(sha256Hex('')).toBe('e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855')
    expect(sha256Hex('abc')).toBe('ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')
  })

  it('derives the same assumption-set id as the backend fold', () => {
    // Pinned in tests/test_temporal_standing.py as well: sha256 of the
    // sorted ids joined by newlines.
    expect(assumptionSetId(['no-new-commitments', 'alloc-holds-tier1'])).toBe(
      '26a7c82c08b9411284435027591e266b5325053f96ede07a635151d612d99a23',
    )
  })
})

describe('foldTemporalStanding', () => {
  it('round-trips a span record with all five properties', () => {
    // API order is newest first; a single row folds as itself.
    const fold = foldTemporalStanding([spanRow('d1', ENVELOPE)])
    const standing = fold.byProject.get('proj-1')
    expect(standing?.spans).toHaveLength(1)
    const span = standing!.spans[0]
    expect(span.id).toBe('d1')
    expect(span.start).toBe('2026-10-20')
    expect(span.end).toBe('2026-12-01')
    expect(span.origin).toBe('evidence-recovered')
    expect(span.standing).toBe('evidence-recovered envelope')
    expect(span.role).toBe('window')
    expect(span.conditionality).toEqual({ kind: 'unconditional' })
    expect(span.effort).toEqual({ kind: 'exact', hours: 12 })
    expect(span.confidence_label).toBe('exact')
    expect(standing!.byRole.window).toEqual([span])
  })

  it('supersede replaces and withdrawal removes (input is newest-first)', () => {
    const rows = [
      row({
        id: 'd3',
        decision_type: 'temporal_span_withdrawn',
        final_values_snapshot: { span_id: 'd2' },
        created_at: '2026-11-28T03:00:00',
      }),
      spanRow('d2', { ...ENVELOPE, end: '2026-12-17', supersedes: 'd1' }, { created_at: '2026-11-28T02:00:00' }),
      spanRow('d1', { ...ENVELOPE, end: '2026-12-10' }, { created_at: '2026-11-28T01:00:00' }),
    ]
    const fold = foldTemporalStanding(rows)
    expect(fold.byProject.has('proj-1')).toBe(false)
  })

  it('keeps an open-ended span open-ended', () => {
    const fold = foldTemporalStanding([spanRow('d1', { ...ENVELOPE, end: null })])
    const span = fold.byProject.get('proj-1')!.spans[0]
    expect(span.start).toBe('2026-10-20')
    expect(span.end).toBeNull()
  })

  it('drops a conditional record whose assumption-set id does not recompute', () => {
    const forged = spanRow('d1', {
      ...ENVELOPE,
      conditionality: {
        kind: 'conditional',
        assumption_set_id: '0'.repeat(64),
        assumptions: [
          { id: 'alloc-holds-tier1', type: 'allocation', statement: 'Tier 1 keeps 5 h/week.' },
          { id: 'no-new-commitments', type: 'commitment', statement: 'Nothing new lands.' },
        ],
      },
    })
    expect(foldTemporalStanding([forged]).byProject.has('proj-1')).toBe(false)
  })

  it('carries a well-formed conditional record with its assumption set', () => {
    const conditional = spanRow('d1', {
      ...ENVELOPE,
      standing: 'derived forecast',
      origin: 'derived',
      conditionality: {
        kind: 'conditional',
        assumption_set_id: '26a7c82c08b9411284435027591e266b5325053f96ede07a635151d612d99a23',
        assumptions: [
          { id: 'alloc-holds-tier1', type: 'allocation', statement: 'Tier 1 keeps 5 h/week.' },
          { id: 'no-new-commitments', type: 'commitment', statement: 'Nothing new lands.' },
        ],
      },
    })
    const span = foldTemporalStanding([conditional]).byProject.get('proj-1')!.spans[0]
    expect(span.conditionality.kind).toBe('conditional')
    if (span.conditionality.kind === 'conditional') {
      expect(span.conditionality.assumptions.map((a) => a.id)).toEqual([
        'alloc-holds-tier1',
        'no-new-commitments',
      ])
    }
  })

  it('degrades malformed rows to nothing', () => {
    const rows = [
      spanRow('bad-1', { ...ENVELOPE, standing: 'whenever' }),
      spanRow('bad-2', { ...ENVELOPE, start: 'not-a-date' }),
      spanRow('bad-3', { ...ENVELOPE, effort: { kind: 'interval', low_hours: 9, high_hours: 2 } }),
      spanRow('good', ENVELOPE),
    ]
    const fold = foldTemporalStanding(rows)
    expect(fold.byProject.get('proj-1')!.spans.map((s) => s.id)).toEqual(['good'])
  })

  it('materializes the person-week allocation series, Monday-normalized', () => {
    const alloc = (id: string, week: string, hours: number, person = 'person-1') =>
      row({
        id,
        entity_type: 'person',
        entity_id: person,
        decision_type: 'temporal_allocation_recorded',
        final_values_snapshot: { week_start: week, hours },
      })
    const rows = [
      row({
        id: 'w1',
        entity_type: 'person',
        entity_id: 'person-1',
        decision_type: 'temporal_allocation_withdrawn',
        final_values_snapshot: { allocation_id: 'a3' },
        created_at: '2026-11-28T04:00:00',
      }),
      alloc('a3', '2026-11-30', 3),
      alloc('a2', '2026-12-02', 2.5), // Wednesday of the Nov 30 week
      alloc('a1', '2026-11-30', 5),
    ]
    const fold = foldTemporalStanding(rows)
    const weeks = fold.allocations.get('person-1')!
    expect(weeks.get('2026-11-30')!.established_hours).toBe(7.5)
    expect(weeks.get('2026-11-30')!.entries.map((e) => e.id)).toEqual(['a1', 'a2'])
  })
})

describe('pickWindowSpan', () => {
  it('prefers an established commitment over a forecast over a provisional hypothesis', () => {
    const mk = (standing: string, id: string, created: string) =>
      spanRow(id, { ...ENVELOPE, standing }, { created_at: created })
    const fold = foldTemporalStanding([
      mk('provisional', 'p1', '2026-11-28T03:00:00'),
      mk('derived forecast', 'f1', '2026-11-28T02:00:00'),
      mk('established commitment', 'e1', '2026-11-28T01:00:00'),
    ])
    const spans = fold.byProject.get('proj-1')!.spans
    expect(pickWindowSpan(spans)?.id).toBe('e1')
    expect(pickWindowSpan(spans.filter((s) => s.id !== 'e1'))?.id).toBe('f1')
    expect(pickWindowSpan(spans.filter((s) => s.standing === 'provisional'))?.id).toBe('p1')
  })

  it('ignores non-window roles', () => {
    const fold = foldTemporalStanding([
      spanRow('d1', { ...ENVELOPE, role: 'deadline', start: '2026-12-03', end: null }),
    ])
    expect(pickWindowSpan(fold.byProject.get('proj-1')!.spans)).toBeNull()
    expect(fold.byProject.get('proj-1')!.byRole.deadline).toHaveLength(1)
  })
})
