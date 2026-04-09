import { describe, expect, it } from 'vitest'
import { assessNodeFlowAndChannels } from './assessNodeFlowAndChannels'
import { collectNodeInterpretationInvariantViolations } from './nodeInterpretationInvariants'
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
  it('includes interpretation that passes invariant checks', () => {
    const u = assessNodeFlowAndChannels(minimalInitiativePayload(), {
      bundle: bundleWithInitiative(),
      councilRuns: [],
    })
    expect(u.interpretation.summary.length).toBeGreaterThan(10)
    expect(u.interpretation.actionLine.length).toBeGreaterThan(5)
    expect(u.interpretation.chatPrefill.length).toBeGreaterThan(5)
    expect(collectNodeInterpretationInvariantViolations(u.interpretation)).toEqual([])
  })

  it('is deterministic for same inputs', () => {
    const bundle = bundleWithInitiative()
    const councilRuns: import('../vision-map/studioCouncilTypes').StudioCouncilRunRow[] = []
    const p = minimalInitiativePayload()
    const a1 = assessNodeFlowAndChannels(p, { bundle, councilRuns })
    const a2 = assessNodeFlowAndChannels(p, { bundle, councilRuns })
    expect(a1.interpretation).toEqual(a2.interpretation)
  })
})
