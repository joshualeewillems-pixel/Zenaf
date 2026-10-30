/**
 * Pure client logic for the Moneyball program-run control (owner-only
 * build-council surface). Kept free of React so it is testable under
 * the repo's existing vitest setup (node environment, *.test.ts):
 * no rendering harness exists here, so every rule the button depends
 * on lives in this module and is covered by programRun.test.ts.
 *
 * Safety rules encoded here (the backend enforces them again — this
 * module is the UI's first line of defense, never the only one):
 * - The start control exists ONLY for a not_started program. Any
 *   other status hides it entirely, so the UI cannot double-fire.
 * - The cap input starts EMPTY: there is no default and no hardcoded
 *   figure anywhere in this module or the view. The owner types it.
 * - The POST body is exactly { cap_usd, confirm: true } — nothing
 *   else is ever sent to /build-room/program/run.
 * - Nothing here POSTs anything. Only the view's button onClick
 *   sends a request, exactly once per click, with no retry.
 */

export const PROGRAM_RUN_STATES = [
  'not_started',
  'running',
  'completed',
  'stopped',
  'interrupted',
  'error',
  'refused',
  'finished',
] as const

export type ProgramRunState = (typeof PROGRAM_RUN_STATES)[number]

export type ProgramStatusMeeting = {
  meeting_id: string | null
  packet_work_item: string | null
  condition: string | null
  ok: boolean | null
  allocation_usd: number | null
  committed_usd: number | null
}

export type ProgramStatus = {
  state: ProgramRunState
  run_id: string | null
  cap_usd: number | null
  cumulative_reserved_usd: number
  remaining_usd: number | null
  meetings_completed: number
  meetings: ProgramStatusMeeting[]
  result_status: string | null
  reason: string | null
  error: string | null
}

export type ProgramPlanMeeting = {
  packet: string
  condition: string
}

export type ProgramRunStarted = {
  run_id: string
  state: string
  cap_usd: number
  meetings: ProgramPlanMeeting[]
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function nullableString(value: unknown): string | null | undefined {
  if (value === null || value === undefined) return null
  return typeof value === 'string' ? value : undefined
}

function nullableNumber(value: unknown): number | null | undefined {
  if (value === null || value === undefined) return null
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function nullableBoolean(value: unknown): boolean | null | undefined {
  if (value === null || value === undefined) return null
  return typeof value === 'boolean' ? value : undefined
}

/**
 * Strictly parse a GET /build-room/program/status response. Any shape
 * deviation is an error, never a guess: the view shows the error and
 * offers no start button rather than acting on an unknown state.
 */
export function parseProgramStatus(
  data: unknown,
): { ok: true; status: ProgramStatus } | { ok: false; error: string } {
  if (!isRecord(data)) return { ok: false, error: 'Status response is not an object.' }
  const state = data.state
  if (
    typeof state !== 'string' ||
    !(PROGRAM_RUN_STATES as readonly string[]).includes(state)
  ) {
    return { ok: false, error: `Unknown program state: ${String(state)}.` }
  }
  const run_id = nullableString(data.run_id)
  const cap_usd = nullableNumber(data.cap_usd)
  const remaining_usd = nullableNumber(data.remaining_usd)
  const result_status = nullableString(data.result_status)
  const reason = nullableString(data.reason)
  const error = nullableString(data.error)
  if (
    run_id === undefined ||
    cap_usd === undefined ||
    remaining_usd === undefined ||
    result_status === undefined ||
    reason === undefined ||
    error === undefined
  ) {
    return { ok: false, error: 'Status response has mistyped nullable fields.' }
  }
  if (
    typeof data.cumulative_reserved_usd !== 'number' ||
    !Number.isFinite(data.cumulative_reserved_usd)
  ) {
    return { ok: false, error: 'Status response has no numeric cumulative_reserved_usd.' }
  }
  if (
    typeof data.meetings_completed !== 'number' ||
    !Number.isInteger(data.meetings_completed) ||
    data.meetings_completed < 0
  ) {
    return { ok: false, error: 'Status response has no valid meetings_completed.' }
  }
  if (!Array.isArray(data.meetings)) {
    return { ok: false, error: 'Status response meetings is not an array.' }
  }
  const meetings: ProgramStatusMeeting[] = []
  for (const entry of data.meetings) {
    if (!isRecord(entry)) {
      return { ok: false, error: 'Status response has a non-object meeting entry.' }
    }
    const meeting_id = nullableString(entry.meeting_id)
    const packet_work_item = nullableString(entry.packet_work_item)
    const condition = nullableString(entry.condition)
    const ok = nullableBoolean(entry.ok)
    const allocation_usd = nullableNumber(entry.allocation_usd)
    const committed_usd = nullableNumber(entry.committed_usd)
    if (
      meeting_id === undefined ||
      packet_work_item === undefined ||
      condition === undefined ||
      ok === undefined ||
      allocation_usd === undefined ||
      committed_usd === undefined
    ) {
      return { ok: false, error: 'Status response has a mistyped meeting entry.' }
    }
    meetings.push({
      meeting_id,
      packet_work_item,
      condition,
      ok,
      allocation_usd,
      committed_usd,
    })
  }
  return {
    ok: true,
    status: {
      state: state as ProgramRunState,
      run_id,
      cap_usd,
      cumulative_reserved_usd: data.cumulative_reserved_usd,
      remaining_usd,
      meetings_completed: data.meetings_completed,
      meetings,
      result_status,
      reason,
      error,
    },
  }
}

/** The start control exists only for a program that has never started. */
export function canStartProgram(status: ProgramStatus | null): boolean {
  return status !== null && status.state === 'not_started'
}

/** States after which status polling may stop (no further change expected). */
export function isTerminalProgramState(state: ProgramRunState): boolean {
  return (
    state === 'completed' ||
    state === 'stopped' ||
    state === 'interrupted' ||
    state === 'error' ||
    state === 'refused' ||
    state === 'finished'
  )
}

/**
 * Build the exact POST body for /build-room/program/run from the
 * owner's typed cap and explicit confirmation. Anything invalid fails
 * here, before any request: an empty, non-numeric, non-finite, or
 * non-positive cap, or a missing confirmation, posts nothing.
 * The returned body has exactly two keys — never more.
 */
export function buildProgramRunBody(
  capText: string,
  confirmed: boolean,
): { ok: true; body: { cap_usd: number; confirm: true } } | { ok: false; error: string } {
  const trimmed = capText.trim()
  if (trimmed.length === 0) {
    return { ok: false, error: 'Enter a cap amount first.' }
  }
  const cap_usd = Number(trimmed)
  if (!Number.isFinite(cap_usd) || cap_usd <= 0) {
    return { ok: false, error: 'The cap must be a positive number.' }
  }
  if (!confirmed) {
    return { ok: false, error: 'Confirm the run first.' }
  }
  return { ok: true, body: { cap_usd, confirm: true } }
}

/**
 * Strictly parse a 202 POST /build-room/program/run response. A 202
 * without a run id is ambiguous, not a success — the view treats it
 * that way and never re-POSTs blindly.
 */
export function parseProgramRunStarted(
  data: unknown,
): { ok: true; started: ProgramRunStarted } | { ok: false; error: string } {
  if (!isRecord(data)) return { ok: false, error: 'Run response is not an object.' }
  if (typeof data.run_id !== 'string' || data.run_id.length === 0) {
    return { ok: false, error: 'Run response has no run id.' }
  }
  if (typeof data.state !== 'string' || data.state.length === 0) {
    return { ok: false, error: 'Run response has no state.' }
  }
  if (typeof data.cap_usd !== 'number' || !Number.isFinite(data.cap_usd)) {
    return { ok: false, error: 'Run response has no numeric cap_usd.' }
  }
  if (!Array.isArray(data.meetings)) {
    return { ok: false, error: 'Run response meetings is not an array.' }
  }
  const meetings: ProgramPlanMeeting[] = []
  for (const entry of data.meetings) {
    if (!isRecord(entry) || typeof entry.packet !== 'string' || typeof entry.condition !== 'string') {
      return { ok: false, error: 'Run response has a malformed planned meeting entry.' }
    }
    meetings.push({ packet: entry.packet, condition: entry.condition })
  }
  return {
    ok: true,
    started: { run_id: data.run_id, state: data.state, cap_usd: data.cap_usd, meetings },
  }
}
