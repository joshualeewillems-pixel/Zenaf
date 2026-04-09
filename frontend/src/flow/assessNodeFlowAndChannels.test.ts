import { describe, expect, it } from 'vitest'
import { assessFlow } from './flowAssessment'
import { assessNodeFlowAndChannels } from './assessNodeFlowAndChannels'
import { buildFlowInputFromMapPayload } from './flowInputAdapter'
import type { MapNodePayload } from '../vision-map/ontology'
import type { VisionMapEntityBundle } from '../vision-map/blockersFromVe'

function minimalInitiativePayload(): MapNodePayload {
  return {
    kind: 'tree',
    label: 'Test initiative',
    subtitle: 'Initiative (tree)',
    growth: 'growing',
    condition: 'healthy',
    ref: { veType: 'initiative', id: 'ini-1' },
    summaryLines: ['Brief line', 'Status: Draft'],
    water_level: 'medium',
    fertilizer_pulse: false,
  }
}

function bundleWithInitiative(): VisionMapEntityBundle {
  return {
    ideas: [],
    initiatives: [
      {
        id: 'ini-1',
        source_idea_id: null,
        title: 'Test initiative',
        brief: 'x'.repeat(80),
        status: 'Draft',
        owner_id: 'p1',
        priority_rank_manual: 3,
        strategic_value_manual: 3,
        energy_impact_manual: 3,
        evaluation_priority: 2,
        estimated_cost_ai: 'low',
        estimated_timeframe_ai: 'Q1',
        philosophical_alignment_ai: 'aligned',
        next_step_ai: 'Do the thing',
        required_people: [],
        required_assets: [],
        dependencies: 'dep a',
        risks: 'risk b',
        recommendation: 'go',
        counts_toward_capacity: 1,
        manual_override: '',
        kill_criteria: '',
        notes: '',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    ],
    projects: [],
    tasks: [],
  }
}

describe('assessNodeFlowAndChannels', () => {
  it('Phase A parity: flow matches assessFlow(buildFlowInputFromMapPayload) for same payload', () => {
    const payload = minimalInitiativePayload()
    const bundle = bundleWithInitiative()
    const councilRuns: import('../vision-map/studioCouncilTypes').StudioCouncilRunRow[] = []
    const u = assessNodeFlowAndChannels(payload, { bundle, councilRuns })
    const input = buildFlowInputFromMapPayload(payload, bundle, councilRuns)
    const legacy = assessFlow(input)
    expect(u.flow.dominantIssue).toBe(legacy.dominantIssue)
    expect(u.flow.rankedActions).toEqual(legacy.rankedActions)
    expect(u.flow.primaryAction).toBe(legacy.primaryAction)
    expect(u.derived.map_visual_triad.water).toBeGreaterThanOrEqual(0)
    expect(u.derived.map_visual_triad.water).toBeLessThanOrEqual(1)
    expect(u.lowest_channel).toMatch(/water|soil|condition|fruit/)
    expect(typeof u.clean_stone_ready).toBe('boolean')
    expect(u.rules_version).toBeTruthy()
  })

  it('is deterministic for same inputs', () => {
    const bundle = bundleWithInitiative()
    const councilRuns: import('../vision-map/studioCouncilTypes').StudioCouncilRunRow[] = []
    const p = minimalInitiativePayload()
    const a1 = assessNodeFlowAndChannels(p, { bundle, councilRuns })
    const a2 = assessNodeFlowAndChannels(p, { bundle, councilRuns })
    expect(a1.lowest_channel).toBe(a2.lowest_channel)
    expect(a1.clean_stone_ready).toBe(a2.clean_stone_ready)
    expect(a1.flow.dominantIssue).toBe(a2.flow.dominantIssue)
    expect(a1.derived.condition_severity).toBe(a2.derived.condition_severity)
  })

  it('first_repair_path is unset during migration (Phase B will require it with primary CTA)', () => {
    const u = assessNodeFlowAndChannels(minimalInitiativePayload(), {
      bundle: bundleWithInitiative(),
      councilRuns: [],
    })
    expect(u.first_repair_path).toBeUndefined()
  })
})
