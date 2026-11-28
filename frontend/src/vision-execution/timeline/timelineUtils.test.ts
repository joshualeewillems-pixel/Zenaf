/**
 * Timeline row subline + row-height invariant.
 *
 * Regression coverage for the narrow-viewport refactor of the Vision →
 * Execution timeline: tree rows have a FIXED height (the grid aligns bars by
 * row index, so tree rows cannot grow), so a row must never need more than
 * label + ONE subline. timelineRowSubline is the single place that combines
 * the summary and waits-on note; these tests pin that contract and the
 * height budget it fits in.
 */
import { describe, expect, it } from 'vitest'
import type { Project, Task } from '../types'
import type { TemporalDecisionRow } from '../temporalStanding'
import {
  TIMELINE_ROW_HEIGHT_PX,
  buildTimelineRows,
  resolveProjectSpan,
  timelineRowSubline,
} from './timelineUtils'

function project(partial: Partial<Project>): Project {
  return {
    id: 'p1',
    initiative_id: null,
    title: 'Project',
    brief: '',
    status: 'Active',
    owner_id: null,
    supporting_owner_ids: [],
    priority: '',
    start_date: null,
    end_date: null,
    estimated_weekly_hours: null,
    next_step_ai: '',
    notes: '',
    created_at: '2026-01-01T00:00:00',
    updated_at: '2026-01-01T00:00:00',
    ...partial,
  }
}

function task(partial: Partial<Task>): Task {
  return {
    id: 't1',
    project_id: 'p1',
    parent_task_id: null,
    title: 'Task',
    description: '',
    assignee_id: null,
    status: 'Todo',
    priority: '',
    estimated_hours: null,
    due_date: null,
    dependency_ids: [],
    completion_criteria: '',
    notes: '',
    created_at: '2026-01-01T00:00:00',
    updated_at: '2026-01-01T00:00:00',
    ...partial,
  }
}

describe('resolveProjectSpan — unified span resolution (S1)', () => {
  it('never invents a created_at + 28d window for an undated project', () => {
    // Regression: the Gantt used to manufacture a 4-week bar from the
    // creation date, unflagged. An undated project is unspanned.
    const span = resolveProjectSpan(project({ created_at: '2026-01-01T00:00:00' }), [])
    expect(span).toEqual({ start: null, end: null, source: 'none' })
  })

  it('uses the recorded project dates when both exist', () => {
    const span = resolveProjectSpan(
      project({ start_date: '2026-06-01', end_date: '2026-06-19' }),
      [],
    )
    expect(span).toEqual({ start: '2026-06-01', end: '2026-06-19', source: 'project' })
  })

  it('keeps the recorded end as a single-day bar when only the end exists', () => {
    const span = resolveProjectSpan(project({ end_date: '2026-06-19' }), [])
    expect(span).toEqual({ start: '2026-06-19', end: '2026-06-19', source: 'project' })
  })

  it('recovers the window from recorded task due dates (the board’s tasks semantics)', () => {
    const span = resolveProjectSpan(project({}), [
      task({ due_date: '2026-06-10' }),
      task({ id: 't2', due_date: '2026-06-03' }),
    ])
    expect(span).toEqual({ start: '2026-06-03', end: '2026-06-10', source: 'tasks' })
  })

  it('a standing record outranks recorded dates and carries its standing', () => {
    const decisions: TemporalDecisionRow[] = [
      {
        id: 'd1',
        entity_type: 'project',
        entity_id: 'p1',
        decision_type: 'temporal_span_recorded',
        final_values_snapshot: {
          start: '2026-10-20',
          end: '2026-12-01',
          origin: 'evidence-recovered',
          standing: 'evidence-recovered envelope',
          role: 'window',
          effort: { kind: 'exact', hours: 12 },
        },
        created_at: '2026-11-28T00:00:00',
      },
    ]
    const rows = buildTimelineRows({
      initiatives: [],
      projects: [project({ start_date: '2026-06-01', end_date: '2026-06-19' })],
      tasks: [],
      collapsedIds: new Set(),
      decisions,
    })
    const projectRow = rows.find((r) => r.kind === 'project')
    expect(projectRow?.start).toBe('2026-10-20')
    expect(projectRow?.end).toBe('2026-12-01')
    expect(projectRow?.spanSource).toBe('standing')
    expect(projectRow?.spanStanding).toBe('evidence-recovered envelope')
    expect(projectRow?.spanId).toBe('d1')
  })

  it('an open-ended standing window resolves start-only — no end is invented', () => {
    const decisions: TemporalDecisionRow[] = [
      {
        id: 'd1',
        entity_type: 'project',
        entity_id: 'p1',
        decision_type: 'temporal_span_recorded',
        final_values_snapshot: {
          start: '2026-10-19',
          end: null,
          origin: 'evidence-recovered',
          standing: 'evidence-recovered envelope',
          role: 'window',
          effort: { kind: 'unknown' },
        },
        created_at: '2026-11-28T00:00:00',
      },
    ]
    const rows = buildTimelineRows({
      initiatives: [],
      projects: [project({})],
      tasks: [],
      collapsedIds: new Set(),
      decisions,
    })
    const projectRow = rows.find((r) => r.kind === 'project')
    expect(projectRow?.start).toBe('2026-10-19')
    expect(projectRow?.end).toBeNull()
    expect(projectRow?.spanSource).toBe('standing')
  })

  it('without decisions, rows resolve from records alone (pre-S1 behaviour minus the invention)', () => {
    const rows = buildTimelineRows({
      initiatives: [],
      projects: [project({ created_at: '2026-01-01T00:00:00' })],
      tasks: [],
      collapsedIds: new Set(),
    })
    const projectRow = rows.find((r) => r.kind === 'project')
    expect(projectRow?.start).toBeNull()
    expect(projectRow?.end).toBeNull()
    expect(projectRow?.spanSource).toBe('none')
  })
})

describe('timelineRowSubline', () => {
  it('returns null text/title when there is neither summary nor waits', () => {
    expect(timelineRowSubline(null, undefined)).toEqual({
      text: null,
      title: null,
      summary: null,
      waits: null,
    })
    expect(timelineRowSubline('   ', [])).toEqual({
      text: null,
      title: null,
      summary: null,
      waits: null,
    })
  })

  it('passes a summary through unchanged', () => {
    const sub = timelineRowSubline('Restless, allergic to lock-in', undefined)
    expect(sub.text).toBe('Restless, allergic to lock-in')
    expect(sub.title).toBe('Restless, allergic to lock-in')
    expect(sub.summary).toBe('Restless, allergic to lock-in')
    expect(sub.waits).toBeNull()
  })

  it('renders waits-on alone, truncated to two names with a remainder', () => {
    const sub = timelineRowSubline(null, ['Alpha', 'Beta', 'Gamma'])
    expect(sub.text).toBe('⏳ waits on Alpha, Beta +1')
    expect(sub.title).toBe('Waits on: Alpha, Beta, Gamma')
    expect(sub.summary).toBeNull()
    expect(sub.waits).toBe('⏳ waits on Alpha, Beta +1')
  })

  it('combines summary and waits into a single line, full list in the title', () => {
    const sub = timelineRowSubline('Ship the Fox intro', ['Alpha', 'Beta', 'Gamma'])
    expect(sub.text).toBe('Ship the Fox intro · ⏳ waits on Alpha, Beta +1')
    expect(sub.title).toBe('Ship the Fox intro · Waits on: Alpha, Beta, Gamma')
  })

  it('keeps the combined line to one logical line (no newlines)', () => {
    const sub = timelineRowSubline('A summary', ['X'])
    expect(sub.text).not.toContain('\n')
    expect(sub.text?.split(' · ')).toHaveLength(2)
  })
})

describe('timeline row height budget', () => {
  it('fits label + one subline + padding (regression: fixed-height rows collided)', () => {
    // Tailwind metrics for the tree row: text-sm label line-height 20px,
    // mt-0.5 gap 2px, 11px subline at default leading ~16.5px, py-1 padding 8px.
    const labelLinePx = 20
    const sublineGapPx = 2
    const sublineLinePx = 16.5
    const verticalPaddingPx = 8
    const requiredPx = labelLinePx + sublineGapPx + sublineLinePx + verticalPaddingPx
    expect(TIMELINE_ROW_HEIGHT_PX).toBeGreaterThanOrEqual(Math.ceil(requiredPx))
  })

  it('stays a single shared constant both sides of the timeline use', () => {
    // Tree and grid both receive this value; a drift between them would
    // misalign bars and rows. The constant must stay a positive integer.
    expect(Number.isInteger(TIMELINE_ROW_HEIGHT_PX)).toBe(true)
    expect(TIMELINE_ROW_HEIGHT_PX).toBeGreaterThan(0)
  })
})
