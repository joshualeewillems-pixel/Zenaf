import { describe, expect, it } from 'vitest'
import { assessFlow, clamp01, rankActions, resolveDominantIssue, severityTo01, type FlowAxes, type FlowInput } from './flowAssessment'

describe('severityTo01', () => {
  it('maps 0–3 to thirds', () => {
    expect(severityTo01(0)).toBe(0)
    expect(severityTo01(3)).toBe(1)
  })
})

describe('resolveDominantIssue', () => {
  const base = (): FlowAxes => ({
    focus: 0.6,
    structure: 0.6,
    tension: 0.3,
    decisionReadiness: 0.5,
    vitality: 0.6,
    grounding: 0.6,
    condition: 0.2,
    maturity: 0.5,
  })

  it('picks tension when tension > 0.7', () => {
    const a = base()
    a.tension = 0.71
    expect(resolveDominantIssue(a)).toBe('tension')
  })

  it('does not pick tension at exactly 0.7 (strict >)', () => {
    const a = base()
    a.tension = 0.7
    a.structure = 0.44
    expect(resolveDominantIssue(a)).toBe('structure')
  })

  it('picks structure when structure < 0.45 (after tension gate)', () => {
    const a = base()
    a.tension = 0.5
    a.structure = 0.44
    expect(resolveDominantIssue(a)).toBe('structure')
  })

  it('picks clarify when focus < 0.45', () => {
    const a = base()
    a.tension = 0.5
    a.structure = 0.5
    a.focus = 0.44
    expect(resolveDominantIssue(a)).toBe('clarify')
  })

  it('does not pick clarify at focus exactly 0.45 (strict <)', () => {
    const a = base()
    a.tension = 0.5
    a.structure = 0.5
    a.focus = 0.45
    a.decisionReadiness = 0.71
    expect(resolveDominantIssue(a)).toBe('decide')
  })

  it('picks decide when decisionReadiness > 0.7', () => {
    const a = base()
    a.tension = 0.5
    a.structure = 0.5
    a.focus = 0.5
    a.decisionReadiness = 0.71
    expect(resolveDominantIssue(a)).toBe('decide')
  })

  it('fallback structure', () => {
    const a = base()
    a.tension = 0.5
    a.structure = 0.5
    a.focus = 0.5
    a.decisionReadiness = 0.5
    expect(resolveDominantIssue(a)).toBe('structure')
  })
})

describe('rankActions', () => {
  it('tension leads with surface_tensions', () => {
    expect(rankActions('tension')[0]).toBe('surface_tensions')
  })
  it('decide leads with summarize', () => {
    expect(rankActions('decide')[0]).toBe('summarize_for_council')
  })
})

describe('assessFlow', () => {
  it('high severity + low soil → tension primary and explore tensions copy', () => {
    const input: FlowInput = {
      water: 0.6,
      soil: 0.35,
      fruit: 0.4,
      conditionSeverity: 3,
    }
    const r = assessFlow(input)
    expect(r.dominantIssue).toBe('tension')
    expect(r.primaryAction).toBe('surface_tensions')
    expect(r.trunkSummary).toContain('unresolved tensions')
    expect(r.bestNextLabel).toBe('Explore tensions')
  })

  it('healthy condition + low structure → expand steps', () => {
    const input: FlowInput = {
      water: 0.65,
      soil: 0.38,
      fruit: 0.35,
      conditionSeverity: 0,
      hasBrief: true,
    }
    const r = assessFlow(input)
    expect(r.dominantIssue).toBe('structure')
    expect(r.primaryAction).toBe('expand_to_steps')
    expect(r.trunkSummary).toContain('not enough grounding')
    expect(r.bestNextLabel).toBe('Expand steps')
  })

  it('very low focus → clarify / distill', () => {
    const input: FlowInput = {
      water: 0.5,
      soil: 0.55,
      fruit: 0.4,
      conditionSeverity: 0,
      hasBrief: false,
      hasNextStep: false,
      hasDeps: false,
    }
    const r = assessFlow(input)
    expect(r.axes.focus).toBe(0.4)
    expect(r.dominantIssue).toBe('clarify')
    expect(r.primaryAction).toBe('distill')
    expect(r.bestNextLabel).toBe('Sharpen focus')
  })
})

describe('clamp01', () => {
  it('clamps', () => {
    expect(clamp01(-1)).toBe(0)
    expect(clamp01(2)).toBe(1)
  })
})
