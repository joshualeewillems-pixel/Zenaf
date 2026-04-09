import { describe, expect, it } from 'vitest'
import type { Initiative } from '../vision-execution/types'
import type { VisionMapEntityBundle } from './blockersFromVe'
import type { MapNodePayload } from './ontology'
import {
  conditionSeverityFallback,
  effectiveConditionSeverity,
  resolveConditionSeverity,
} from './resolveConditionSeverity'

function treePayload(over: Partial<MapNodePayload> = {}): MapNodePayload {
  return {
    kind: 'tree',
    label: 'L',
    growth: 'growing',
    condition: 'healthy',
    ref: { veType: 'initiative', id: 'i1' },
    summaryLines: [],
    water_level: 'medium',
    fertilizer_pulse: false,
    ...over,
  } as MapNodePayload
}

const recent = new Date().toISOString()

function minimalInitiative(over: Partial<Initiative> = {}): Initiative {
  return {
    id: 'i1',
    source_idea_id: null,
    title: 'T',
    brief: 'Enough brief text for tests',
    status: 'active',
    owner_id: 'o',
    priority_rank_manual: null,
    strategic_value_manual: null,
    energy_impact_manual: null,
    evaluation_priority: 1,
    estimated_cost_ai: '',
    estimated_timeframe_ai: '',
    philosophical_alignment_ai: '',
    next_step_ai: 'Next',
    required_people: [],
    required_assets: [],
    dependencies: '',
    risks: '',
    recommendation: '',
    counts_toward_capacity: 0,
    manual_override: '',
    kill_criteria: '',
    notes: '',
    created_at: recent,
    updated_at: recent,
    ...over,
  } as Initiative
}

function iniBundle(ini: Initiative): VisionMapEntityBundle {
  return { ideas: [], initiatives: [ini], projects: [], tasks: [] }
}

describe('resolveConditionSeverity', () => {
  it('teacher veto forces critical', () => {
    expect(resolveConditionSeverity(treePayload({ condition: 'teacher-vetoed' }), null)).toBe(3)
  })

  it('blocked floors to at least fractured', () => {
    expect(resolveConditionSeverity(treePayload({ condition: 'blocked' }), null)).toBeGreaterThanOrEqual(2)
  })

  it('healthy recent initiative with bundle is none', () => {
    expect(resolveConditionSeverity(treePayload(), iniBundle(minimalInitiative()))).toBe(0)
  })

  it('non-empty kill_criteria forces critical', () => {
    const sev = resolveConditionSeverity(
      treePayload(),
      iniBundle(minimalInitiative({ kill_criteria: 'abcdefghijklmn' })),
    )
    expect(sev).toBe(3)
  })

  it('missing bundle does not invent infinite staleness', () => {
    expect(resolveConditionSeverity(treePayload({ condition: 'healthy' }), null)).toBe(0)
  })
})

describe('effectiveConditionSeverity', () => {
  it('uses stored condition_severity when present', () => {
    expect(effectiveConditionSeverity(treePayload({ condition_severity: 2, condition: 'healthy' }))).toBe(2)
  })

  it('falls back to legacy condition mapping', () => {
    expect(effectiveConditionSeverity(treePayload({ condition: 'stale' }))).toBe(1)
  })
})

describe('conditionSeverityFallback', () => {
  it('maps legacy condition when severity omitted', () => {
    expect(conditionSeverityFallback(treePayload({ condition: 'healthy' }))).toBe(0)
    expect(conditionSeverityFallback(treePayload({ condition: 'stale' }))).toBe(1)
    expect(conditionSeverityFallback(treePayload({ condition: 'teacher-warned' }))).toBe(2)
    expect(conditionSeverityFallback(treePayload({ condition: 'blocked' }))).toBe(2)
    expect(conditionSeverityFallback(treePayload({ condition: 'teacher-vetoed' }))).toBe(3)
  })
})
