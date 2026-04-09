import { describe, expect, it } from 'vitest'
import { buildDevelopmentalGuidanceContext } from './buildDevelopmentalGuidanceContext'
import type { ExecutionFlowReadingSummary } from './types'

function row(partial: Partial<ExecutionFlowReadingSummary> & Pick<ExecutionFlowReadingSummary, 'impact'>): ExecutionFlowReadingSummary {
  return {
    dimension: 'capacity',
    confidence: 0.5,
    pointer_kind: 'activity_event',
    coordination_evidence_source: 'zenaf-client-trace',
    judgment_row_id: 'j-test',
    ...partial,
  }
}

describe('buildDevelopmentalGuidanceContext execution_flow_reading hypotheses', () => {
  it('emits human_checkpoint strength from production-shaped applied-suggestion rows (confidence 0.6)', () => {
    const readings: ExecutionFlowReadingSummary[] = [
      {
        impact: 'positive',
        dimension: 'capacity',
        confidence: 0.6,
        pointer_kind: 'activity_event',
        coordination_evidence_source: 'zenaf-client-trace',
        judgment_row_id: 'j1',
        pointer: 'act-1',
      },
      {
        impact: 'positive',
        dimension: 'capacity',
        confidence: 0.6,
        pointer_kind: 'activity_event',
        coordination_evidence_source: 'zenaf-client-trace',
        judgment_row_id: 'j2',
        pointer: 'act-2',
      },
    ]
    const ctx = buildDevelopmentalGuidanceContext({
      mapTriad: null,
      recentTraces: [],
      executionFlowReadings: readings,
    })
    expect(ctx).not.toBeNull()
    const h = ctx!.hypotheses.find(
      (x) =>
        x.kind === 'strength' &&
        x.basis.includes('human_checkpoint') &&
        x.basis.includes('positive_cluster'),
    )
    expect(h).toBeDefined()
    expect(h!.statement).toContain('recent acknowledged execution on this focus may be building capacity')
    expect(h!.basis).toEqual(['execution_flow_reading', 'positive_cluster', 'human_checkpoint'])
  })

  it('emits human_checkpoint strength when 2 positive activity_event + zenaf-client-trace (0.5 confidence)', () => {
    const readings: ExecutionFlowReadingSummary[] = [
      row({ impact: 'positive', judgment_row_id: 'j1' }),
      row({ impact: 'positive', judgment_row_id: 'j2' }),
    ]
    const ctx = buildDevelopmentalGuidanceContext({
      mapTriad: null,
      recentTraces: [],
      executionFlowReadings: readings,
    })
    expect(ctx).not.toBeNull()
    const h = ctx!.hypotheses.find(
      (x) =>
        x.kind === 'strength' &&
        x.basis.includes('human_checkpoint') &&
        x.basis.includes('positive_cluster'),
    )
    expect(h).toBeDefined()
  })

  it('emits human_checkpoint friction when 2 negative activity_event + zenaf-client-trace with confidence floor', () => {
    const readings: ExecutionFlowReadingSummary[] = [
      row({ impact: 'negative', confidence: 0.5, judgment_row_id: 'j1' }),
      row({ impact: 'negative', confidence: 0.6, judgment_row_id: 'j2' }),
    ]
    const ctx = buildDevelopmentalGuidanceContext({
      mapTriad: null,
      recentTraces: [],
      executionFlowReadings: readings,
    })
    expect(ctx).not.toBeNull()
    const h = ctx!.hypotheses.find(
      (x) =>
        x.kind === 'friction' &&
        x.basis.includes('human_checkpoint') &&
        x.basis.includes('negative_cluster'),
    )
    expect(h).toBeDefined()
    expect(h!.statement).toContain('repeated checkpoint-backed reads suggest strain')
    expect(h!.basis).toEqual(['execution_flow_reading', 'negative_cluster', 'human_checkpoint'])
  })

  it('uses council_or_mixed when only council_stream_run positives meet threshold (not human)', () => {
    const readings: ExecutionFlowReadingSummary[] = [
      {
        impact: 'positive',
        dimension: 'clarity',
        confidence: 0.5,
        pointer_kind: 'council_stream_run',
        coordination_evidence_source: 'council_stream',
        judgment_row_id: 'c1',
      },
      {
        impact: 'positive',
        dimension: 'clarity',
        confidence: 0.5,
        pointer_kind: 'council_stream_run',
        coordination_evidence_source: 'council_stream',
        judgment_row_id: 'c2',
      },
    ]
    const ctx = buildDevelopmentalGuidanceContext({
      mapTriad: null,
      recentTraces: [],
      executionFlowReadings: readings,
    })
    expect(ctx).not.toBeNull()
    const h = ctx!.hypotheses.find(
      (x) =>
        x.kind === 'strength' &&
        x.basis.includes('council_or_mixed') &&
        x.basis.includes('positive_cluster'),
    )
    expect(h).toBeDefined()
    expect(h!.statement).toContain('momentum may be present')
    expect(h!.basis).toEqual(['execution_flow_reading', 'positive_cluster', 'council_or_mixed'])
    expect(ctx!.hypotheses.some((x) => x.basis.includes('human_checkpoint'))).toBe(false)
  })

  it('mixed negatives: one human + one council still yields council_or_mixed when human count < 2', () => {
    const readings: ExecutionFlowReadingSummary[] = [
      row({ impact: 'negative', confidence: 0.5, judgment_row_id: 'h1' }),
      {
        impact: 'negative',
        dimension: 'friction',
        confidence: 0.5,
        pointer_kind: 'council_stream_run',
        coordination_evidence_source: 'council_stream',
        judgment_row_id: 'c1',
      },
    ]
    const ctx = buildDevelopmentalGuidanceContext({
      mapTriad: null,
      recentTraces: [],
      executionFlowReadings: readings,
    })
    expect(ctx).not.toBeNull()
    const h = ctx!.hypotheses.find((x) => x.kind === 'friction' && x.basis.includes('negative_cluster'))
    expect(h).toBeDefined()
    expect(h!.basis).toContain('council_or_mixed')
    expect(h!.basis).not.toContain('human_checkpoint')
  })
})
