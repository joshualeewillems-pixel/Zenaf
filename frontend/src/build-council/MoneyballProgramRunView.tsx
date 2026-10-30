import { useCallback, useEffect, useState } from 'react'
import type { CurrentUser } from '../auth/session'
import {
  buildProgramRunBody,
  canStartProgram,
  isTerminalProgramState,
  parseProgramRunStarted,
  parseProgramStatus,
  type ProgramRunStarted,
  type ProgramStatus,
} from './programRun'

type Props = {
  user: CurrentUser | null
}

/**
 * Owner-only Moneyball program-run control, embedded in the
 * build-council submit page (which itself gates on is_admin, and this
 * component gates again). The backend endpoints remain the real owner
 * enforcement, fail-closed.
 *
 * Start safety (do not weaken — mirrors the submit page's rules):
 * - The status is fetched on mount and shown; the start control
 *   renders ONLY while status is not_started. Any other status hides
 *   it entirely, so the UI cannot double-fire a program. The backend
 *   409 is a second line of defense, never the first.
 * - The cap input starts EMPTY: no default, no hardcoded figure. The
 *   owner types the cap, and an explicit confirmation checkbox must
 *   be checked. The POST body is exactly { cap_usd, confirm: true }.
 * - Exactly one POST per click; the button is disabled while a
 *   request is in flight. No automatic retry, ever. On an ambiguous
 *   outcome (no clear 202 + run id) the start control stays disabled
 *   until the cap text is edited, so a second click cannot blindly
 *   double-submit a program whose first outcome is unknown.
 * - NEVER auto-runs: mounting, rendering, and status polling only
 *   ever GET. The only POST comes from the start button's onClick.
 * - Progress polling only reads status (every 15s while running)
 *   and stops at terminal states.
 */
export function MoneyballProgramRunView({ user }: Props) {
  const [status, setStatus] = useState<ProgramStatus | null>(null)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [loadingStatus, setLoadingStatus] = useState(true)
  const [capText, setCapText] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [starting, setStarting] = useState(false)
  const [started, setStarted] = useState<ProgramRunStarted | null>(null)
  const [startError, setStartError] = useState<string | null>(null)
  const [ambiguous, setAmbiguous] = useState(false)

  // Non-owner: render nothing. The parent page already gates, and the
  // backend endpoints enforce ownership regardless.
  const isOwner = user?.is_admin === true

  const refreshStatus = useCallback(async () => {
    try {
      const res = await fetch('/build-room/program/status', {
        method: 'GET',
        credentials: 'include',
      })
      const raw = await res.text()
      if (!res.ok) {
        setStatusError(`Status check failed (HTTP ${res.status}): ${raw}`)
        return
      }
      let data: unknown = null
      try {
        data = JSON.parse(raw)
      } catch {
        setStatusError('Status check returned a non-JSON response.')
        return
      }
      const parsed = parseProgramStatus(data)
      if (!parsed.ok) {
        setStatusError(parsed.error)
        return
      }
      setStatus(parsed.status)
      setStatusError(null)
    } catch (e) {
      setStatusError(
        `Status check failed before a response arrived (${e instanceof Error ? e.message : 'network error'}).`,
      )
    }
  }, [])

  useEffect(() => {
    if (!isOwner) {
      setLoadingStatus(false)
      return
    }
    setLoadingStatus(true)
    void refreshStatus().finally(() => setLoadingStatus(false))
  }, [isOwner, refreshStatus])

  useEffect(() => {
    if (status?.state !== 'running') return undefined
    const id = setInterval(() => {
      void refreshStatus()
    }, 15000)
    return () => clearInterval(id)
  }, [status?.state, refreshStatus])

  if (!isOwner) return null

  const showStart =
    status !== null && canStartProgram(status) && started === null && !ambiguous
  const bodyCheck = buildProgramRunBody(capText, confirmed)

  const onCapChange = (next: string) => {
    setCapText(next)
    if (ambiguous) {
      // A deliberate edit re-arms the start control after an
      // ambiguous outcome, mirroring the submit page. Without an
      // edit, start stays disabled: never re-POST blind.
      setAmbiguous(false)
      setStartError(null)
    }
  }

  const start = async () => {
    if (starting || ambiguous || !showStart) return
    const built = buildProgramRunBody(capText, confirmed)
    if (!built.ok) {
      setStartError(built.error)
      return
    }
    setStartError(null)
    setStarting(true)
    try {
      const res = await fetch('/build-room/program/run', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(built.body),
      })
      const raw = await res.text()
      let data: unknown = null
      try {
        data = JSON.parse(raw)
      } catch {
        data = null
      }
      if (res.status === 202) {
        const parsed = parseProgramRunStarted(data)
        if (parsed.ok) {
          setStarted(parsed.started)
          await refreshStatus()
        } else {
          setStartError(
            `Outcome unclear — the server answered 202 but the response has no run id (${parsed.error}). ` +
              'It is unknown whether a program started. Do not resubmit blindly — ' +
              'edit the cap to re-enable Start only once you have checked the status.',
          )
          setAmbiguous(true)
        }
      } else {
        // A non-202 with a readable body is a clear failure, not an
        // ambiguity: show the status and the body verbatim.
        setStartError(`Start failed (HTTP ${res.status}): ${raw}`)
        await refreshStatus()
      }
    } catch (e) {
      setStartError(
        `Outcome unclear — the request failed before a response arrived (${e instanceof Error ? e.message : 'network error'}). ` +
          'It is unknown whether a program started. Do not resubmit blindly — ' +
          'edit the cap to re-enable Start only once you have checked the status.',
      )
      setAmbiguous(true)
    } finally {
      setStarting(false)
    }
  }

  const terminal = status !== null && isTerminalProgramState(status.state)

  return (
    <div className="border border-slate-700 rounded-lg p-4 space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-slate-100">Moneyball program run</h2>
        <p className="text-sm text-slate-400 mt-1">
          Start the fixed six-meeting Moneyball comparison program (three packets, conditions A
          then B each, sequential) under a cap you type. This control never starts anything on
          its own: it only reads status until you click Start, and Start appears only while the
          program has never started. One POST per click, no automatic retries.
        </p>
      </div>

      <div id="moneyball-program-status" className="space-y-2">
        {loadingStatus && <p className="text-sm text-slate-400">Loading program status…</p>}
        {statusError && <p className="text-red-400 text-sm">{statusError}</p>}
        {status && (
          <>
            <p className="text-sm text-slate-300">State: {status.state}</p>
            {status.run_id && <p className="text-sm text-slate-300">Run id: {status.run_id}</p>}
            {status.cap_usd !== null && (
              <p className="text-sm text-slate-300">Cap: ${status.cap_usd}</p>
            )}
            <p className="text-sm text-slate-300">
              Cumulative reserved: ${status.cumulative_reserved_usd}
            </p>
            {status.remaining_usd !== null && (
              <p className="text-sm text-slate-300">Remaining: ${status.remaining_usd}</p>
            )}
            <p className="text-sm text-slate-300">
              Meetings completed: {status.meetings_completed} / 6
            </p>
            {status.result_status && (
              <p className="text-sm text-slate-300">Result: {status.result_status}</p>
            )}
            {status.reason && <p className="text-sm text-slate-300">Reason: {status.reason}</p>}
            {status.error && <p className="text-red-400 text-sm">Error: {status.error}</p>}
            {status.meetings.length > 0 && (
              <ul className="space-y-1">
                {status.meetings.map((m, i) => (
                  <li key={`${m.meeting_id ?? 'pending'}-${i}`} className="text-sm text-slate-300">
                    {m.packet_work_item ?? 'Unknown packet'} — condition {m.condition ?? '?'} —{' '}
                    {m.ok === null ? 'pending' : m.ok ? 'ok' : 'failed'}
                    {m.allocation_usd !== null && ` — allocated $${m.allocation_usd}`}
                    {m.committed_usd !== null && ` — committed $${m.committed_usd}`}
                  </li>
                ))}
              </ul>
            )}
            {terminal && (
              <p className="text-sm text-slate-400">
                This program has reached a terminal state; it cannot be started again from this
                control.
              </p>
            )}
          </>
        )}
        <button
          type="button"
          onClick={() => void refreshStatus()}
          className="min-h-[44px] px-4 py-2 rounded-lg text-sm bg-slate-600 text-slate-100 hover:bg-slate-500"
        >
          Refresh status
        </button>
      </div>

      {showStart && (
        <div className="space-y-3">
          <div>
            <label className="block text-slate-500 text-sm mb-1" htmlFor="moneyball-program-cap">
              Program cap (USD)
            </label>
            <input
              id="moneyball-program-cap"
              type="number"
              min="0"
              step="any"
              className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
              value={capText}
              onChange={(e) => onCapChange(e.target.value)}
              placeholder="Enter cap in USD"
            />
          </div>
          <div className="flex items-start gap-2">
            <input
              id="moneyball-program-confirm"
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
              className="mt-1"
            />
            <label className="text-sm text-slate-300" htmlFor="moneyball-program-confirm">
              I confirm starting the six-meeting Moneyball program under this cap.
            </label>
          </div>
          <button
            type="button"
            disabled={starting || ambiguous || !bodyCheck.ok}
            onClick={() => void start()}
            className="min-h-[44px] px-4 py-2 rounded-lg text-sm bg-amber-600 text-white hover:bg-amber-500 disabled:opacity-50"
          >
            {starting ? 'Starting…' : 'Start Moneyball program run'}
          </button>
          {ambiguous && (
            <p className="text-amber-400 text-sm">
              Outcome unclear — see below. Edit the cap to re-enable Start.
            </p>
          )}
        </div>
      )}

      {startError && <p className="text-red-400 text-sm">{startError}</p>}
      {started && (
        <div className="border border-slate-700 rounded-lg p-4 space-y-2" id="moneyball-program-started">
          <h3 className="text-base font-semibold text-slate-100">Program started</h3>
          <p className="text-sm text-slate-300">Run id: {started.run_id}</p>
          <p className="text-sm text-slate-300">State: {started.state}</p>
          <p className="text-sm text-slate-300">Cap: ${started.cap_usd}</p>
          <ul className="space-y-1">
            {started.meetings.map((m, i) => (
              <li key={`${m.packet}-${m.condition}-${i}`} className="text-sm text-slate-300">
                {m.packet} — condition {m.condition}
              </li>
            ))}
          </ul>
          <p className="text-sm text-slate-400">
            Progress updates above as status is polled while the program runs.
          </p>
        </div>
      )}
    </div>
  )
}
