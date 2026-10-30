import { describe, expect, it } from 'vitest'
import {
  buildProgramRunBody,
  canStartProgram,
  isTerminalProgramState,
  parseProgramRunStarted,
  parseProgramStatus,
  type ProgramStatus,
} from './programRun'

/**
 * Client-side gates for the Moneyball program-run control: a failed
 * gate must never start a program, so every rule the button depends
 * on is pinned here — start eligibility, the exact POST body, and
 * strict response parsing — before any request is sent.
 */
function baseStatus(overrides: Partial<ProgramStatus> = {}): ProgramStatus {
  return {
    state: 'not_started',
    run_id: null,
    cap_usd: null,
    cumulative_reserved_usd: 0,
    remaining_usd: null,
    meetings_completed: 0,
    meetings: [],
    result_status: null,
    reason: null,
    error: null,
    ...overrides,
  }
}

describe('canStartProgram', () => {
  it('allows start only for not_started', () => {
    expect(canStartProgram(baseStatus())).toBe(true)
    expect(canStartProgram(null)).toBe(false)
    for (const state of [
      'running',
      'completed',
      'stopped',
      'interrupted',
      'error',
      'refused',
      'finished',
    ] as const) {
      expect(canStartProgram(baseStatus({ state }))).toBe(false)
    }
  })
})

describe('isTerminalProgramState', () => {
  it('treats running and not_started as non-terminal', () => {
    expect(isTerminalProgramState('running')).toBe(false)
    expect(isTerminalProgramState('not_started')).toBe(false)
  })

  it('treats finished outcomes as terminal', () => {
    for (const state of [
      'completed',
      'stopped',
      'interrupted',
      'error',
      'refused',
      'finished',
    ] as const) {
      expect(isTerminalProgramState(state)).toBe(true)
    }
  })
})

describe('buildProgramRunBody', () => {
  it('accepts a positive cap with confirmation and returns exactly two keys', () => {
    const result = buildProgramRunBody('2', true)
    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.body).toEqual({ cap_usd: 2, confirm: true })
      expect(Object.keys(result.body).sort()).toEqual(['cap_usd', 'confirm'])
    }
  })

  it('accepts decimal caps and trims whitespace', () => {
    const result = buildProgramRunBody('  2.5  ', true)
    expect(result.ok).toBe(true)
    if (result.ok) expect(result.body.cap_usd).toBe(2.5)
  })

  it('rejects an empty cap', () => {
    expect(buildProgramRunBody('', true).ok).toBe(false)
    expect(buildProgramRunBody('   ', true).ok).toBe(false)
  })

  it('rejects non-numeric and non-positive caps', () => {
    for (const bad of ['abc', '2x', '0', '-1', 'NaN', 'Infinity']) {
      expect(buildProgramRunBody(bad, true).ok).toBe(false)
    }
  })

  it('rejects a missing confirmation', () => {
    expect(buildProgramRunBody('2', false).ok).toBe(false)
  })
})

describe('parseProgramStatus', () => {
  const valid = {
    state: 'running',
    run_id: 'run-1',
    cap_usd: 2,
    cumulative_reserved_usd: 0.224,
    remaining_usd: 1.776,
    meetings_completed: 1,
    meetings: [
      {
        meeting_id: 'm-1',
        packet_work_item: 'Packet title',
        condition: 'A',
        ok: true,
        allocation_usd: 0.5,
        committed_usd: 0.224,
      },
    ],
    result_status: null,
    reason: null,
    error: null,
  }

  it('accepts a full valid status response', () => {
    const result = parseProgramStatus(valid)
    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.status.state).toBe('running')
      expect(result.status.meetings).toHaveLength(1)
    }
  })

  it('accepts a not_started response with nulls', () => {
    const result = parseProgramStatus({
      state: 'not_started',
      run_id: null,
      cap_usd: null,
      cumulative_reserved_usd: 0,
      remaining_usd: null,
      meetings_completed: 0,
      meetings: [],
      result_status: null,
      reason: null,
      error: null,
    })
    expect(result.ok).toBe(true)
  })

  it('rejects unknown states instead of guessing', () => {
    expect(parseProgramStatus({ ...valid, state: 'started' }).ok).toBe(false)
    expect(parseProgramStatus({ ...valid, state: 'mystery' }).ok).toBe(false)
  })

  it('rejects mistyped fields and non-objects', () => {
    expect(parseProgramStatus({ ...valid, cumulative_reserved_usd: '0.224' }).ok).toBe(false)
    expect(parseProgramStatus({ ...valid, meetings_completed: 1.5 }).ok).toBe(false)
    expect(parseProgramStatus({ ...valid, meetings: {} }).ok).toBe(false)
    expect(parseProgramStatus({ ...valid, meetings: [{ meeting_id: 7 }] }).ok).toBe(false)
    expect(parseProgramStatus(null).ok).toBe(false)
    expect(parseProgramStatus('running').ok).toBe(false)
  })
})

describe('parseProgramRunStarted', () => {
  const valid = {
    run_id: 'run-1',
    state: 'started',
    cap_usd: 2,
    meetings: [
      { packet: 'Packet title', condition: 'A' },
      { packet: 'Packet title', condition: 'B' },
    ],
  }

  it('accepts a 202 start response', () => {
    const result = parseProgramRunStarted(valid)
    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.started.run_id).toBe('run-1')
      expect(result.started.meetings).toHaveLength(2)
    }
  })

  it('rejects a 202 without a run id as ambiguous, not success', () => {
    expect(parseProgramRunStarted({ ...valid, run_id: '' }).ok).toBe(false)
    expect(parseProgramRunStarted({ ...valid, run_id: undefined }).ok).toBe(false)
    expect(parseProgramRunStarted({ ...valid, meetings: 'x' }).ok).toBe(false)
    expect(parseProgramRunStarted({ ...valid, cap_usd: '2' }).ok).toBe(false)
  })
})
