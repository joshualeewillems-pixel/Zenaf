import { describe, expect, it } from 'vitest'
import { deriveNodeInterpretation } from './deriveNodeInterpretation'
import { collectNodeInterpretationInvariantViolations } from './nodeInterpretationInvariants'
import type { FlowAssessment } from './flowAssessment'
import type { ChannelId } from './unifiedNodeAssessmentTypes'

function makeInput(flow: FlowAssessment, low: ChannelId, sev: 0 | 1 | 2 | 3) {
  return {
    flow,
    lowest_channel: low,
    derived: { condition_severity: sev },
  }
}

describe('deriveNodeInterpretation', () => {
  it('every derived interpretation satisfies invariants for sample flow matrix', () => {
    const issues: FlowAssessment['dominantIssue'][] = ['clarify', 'structure', 'tension', 'decide']
    const lows: ChannelId[] = ['water', 'soil', 'fruit', 'condition']
    for (const issue of issues) {
      const ranked = issue === 'clarify' ? ['distill'] : issue === 'structure' ? ['expand_to_steps'] : ['surface_tensions']
      const flow: FlowAssessment = {
        axes: {} as FlowAssessment['axes'],
        dominantIssue: issue,
        primaryAction: ranked[0] as FlowAssessment['primaryAction'],
        rankedActions: ranked as FlowAssessment['rankedActions'],
        trunkSummary: 'Test summary for invariant sweep.',
        bestNextLabel: 'Next',
      }
      for (const low of lows) {
        for (const sev of [0, 1, 2, 3] as const) {
          const interp = deriveNodeInterpretation(makeInput(flow, low, sev), {
            kind: 'tree',
            bundle: {
              ideas: [],
              initiatives: [
                {
                  id: 'i1',
                  source_idea_id: null,
                  title: 'T',
                  brief: 'y'.repeat(80),
                  status: 'Draft',
                  owner_id: 'p',
                  priority_rank_manual: 1,
                  strategic_value_manual: 1,
                  energy_impact_manual: 1,
                  evaluation_priority: 1,
                  estimated_cost_ai: 'low',
                  estimated_timeframe_ai: 'Q1',
                  philosophical_alignment_ai: 'x',
                  next_step_ai: 'step',
                  required_people: [],
                  required_assets: [],
                  dependencies: 'd',
                  risks: 'r',
                  recommendation: 'go',
                  counts_toward_capacity: 1,
                  manual_override: '',
                  kill_criteria: '',
                  notes: '',
                  created_at: '',
                  updated_at: '',
                },
              ],
              projects: [],
              tasks: [],
            },
            ref: { veType: 'initiative', id: 'i1' },
          })
          const viol = collectNodeInterpretationInvariantViolations(interp)
          expect(viol, `violations for ${issue}/${low}/sev${sev}: ${viol.join('; ')}`).toEqual([])
        }
      }
    }
  })

  it('clarify_first when dominant clarify and missing brief', () => {
    const flow: FlowAssessment = {
      axes: {} as FlowAssessment['axes'],
      dominantIssue: 'clarify',
      primaryAction: 'distill',
      rankedActions: ['distill', 'expand_to_steps', 'surface_tensions', 'summarize_for_council'],
      trunkSummary: 'This work is not yet clearly articulated.',
      bestNextLabel: 'Sharpen focus',
    }
    const interp = deriveNodeInterpretation(makeInput(flow, 'soil', 0), {
      kind: 'tree',
      bundle: {
        ideas: [],
        initiatives: [
          {
            id: 'x',
            source_idea_id: null,
            title: 'T',
            brief: 'short',
            status: 'Draft',
            owner_id: null,
            priority_rank_manual: 1,
            strategic_value_manual: 1,
            energy_impact_manual: 1,
            evaluation_priority: 1,
            estimated_cost_ai: 'low',
            estimated_timeframe_ai: 'Q1',
            philosophical_alignment_ai: 'x',
            next_step_ai: '',
            required_people: [],
            required_assets: [],
            dependencies: '',
            risks: '',
            recommendation: '',
            counts_toward_capacity: 1,
            manual_override: '',
            kill_criteria: '',
            notes: '',
            created_at: '',
            updated_at: '',
          },
        ],
        projects: [],
        tasks: [],
      },
      ref: { veType: 'initiative', id: 'x' },
    })
    expect(interp.stance).toBe('clarify_first')
    expect(interp.clarificationQuestion).toBeTruthy()
    expect(collectNodeInterpretationInvariantViolations(interp)).toEqual([])
  })
})
