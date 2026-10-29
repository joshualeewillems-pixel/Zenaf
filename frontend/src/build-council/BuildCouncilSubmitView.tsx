import { useState } from 'react'
import type { CurrentUser } from '../auth/session'
import { validateMeetingRequestJson } from './validateMeetingRequest'

type Props = {
  user: CurrentUser | null
  onBack: () => void
}

type SubmitResult =
  | { kind: 'success'; status: number; meetingId: string; ok: boolean; text: string }
  | { kind: 'failure'; status: number; text: string }
  | { kind: 'ambiguous'; detail: string }

/**
 * Owner-only page: paste a full build-council meeting request (JSON)
 * and submit it to the existing R2 endpoint, same-origin, with the
 * app's own session cookie. This is a submission surface only — not
 * a general prompt runner and not a new execution path. The endpoint
 * itself remains the real owner enforcement, fail-closed.
 *
 * Submission safety (do not weaken):
 * - Validation runs before any POST; a failed validation posts nothing.
 * - Exactly one POST per click; the button is disabled while a
 *   request is in flight.
 * - No automatic retry, ever. On an ambiguous outcome (no clear
 *   200 + meeting id + ok flag) the button stays disabled until the
 *   pasted text is edited, so a second click cannot blindly
 *   double-submit a meeting whose first outcome is unknown.
 */
export function BuildCouncilSubmitView({ user, onBack }: Props) {
  const [text, setText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<SubmitResult | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [ambiguous, setAmbiguous] = useState(false)

  if (!user?.is_admin) {
    return (
      <div className="flex-1 overflow-auto p-6 max-w-3xl mx-auto space-y-6">
        <button
          type="button"
          onClick={onBack}
          className="min-h-[44px] px-4 py-2 rounded-lg text-sm bg-slate-600 text-slate-100 hover:bg-slate-500"
        >
          Back to Settings
        </button>
        <p className="text-sm text-slate-400">
          This page is available to the workspace owner only.
        </p>
      </div>
    )
  }

  const onTextChange = (next: string) => {
    setText(next)
    if (ambiguous) {
      // A deliberate edit re-arms submission after an ambiguous outcome.
      // Without an edit, the button stays disabled: never re-POST blind.
      setAmbiguous(false)
      setResult(null)
    }
  }

  const submit = async () => {
    if (submitting || ambiguous) return
    setError(null)
    setResult(null)
    const validated = validateMeetingRequestJson(text)
    if (!validated.ok) {
      setError(validated.error)
      return
    }
    setSubmitting(true)
    try {
      const res = await fetch('/build-room/meetings/r2', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(validated.body),
      })
      const raw = await res.text()
      let data: unknown = null
      try {
        data = JSON.parse(raw)
      } catch {
        data = null
      }
      const meetingId =
        data && typeof data === 'object' && !Array.isArray(data)
          ? (data as Record<string, unknown>).meeting_id
          : undefined
      const okFlag =
        data && typeof data === 'object' && !Array.isArray(data)
          ? (data as Record<string, unknown>).ok
          : undefined
      if (res.status === 200 && typeof meetingId === 'string' && typeof okFlag === 'boolean') {
        setResult({ kind: 'success', status: res.status, meetingId, ok: okFlag, text: raw })
      } else if (res.status !== 200) {
        // A non-200 with a readable body is a clear failure, not an
        // ambiguity: show the status and the body verbatim.
        setResult({ kind: 'failure', status: res.status, text: raw })
      } else {
        setResult({
          kind: 'ambiguous',
          detail:
            'The server answered 200 but the response has no meeting id or ok flag. ' +
            'It is unknown whether a meeting started. Do not resubmit blindly — ' +
            'edit the request text to re-enable Submit only once you have checked.',
        })
        setAmbiguous(true)
      }
    } catch (e) {
      setResult({
        kind: 'ambiguous',
        detail:
          `The request failed before a response arrived (${e instanceof Error ? e.message : 'network error'}). ` +
          'It is unknown whether a meeting started. Do not resubmit blindly — ' +
          'edit the request text to re-enable Submit only once you have checked.',
      })
      setAmbiguous(true)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex-1 overflow-auto p-6 max-w-3xl mx-auto space-y-6">
      <div>
        <button
          type="button"
          onClick={onBack}
          className="min-h-[44px] px-4 py-2 rounded-lg text-sm bg-slate-600 text-slate-100 hover:bg-slate-500"
        >
          Back to Settings
        </button>
      </div>
      <div>
        <h1 className="text-xl font-semibold text-slate-100">Submit a build-council meeting</h1>
        <p className="text-sm text-slate-400 mt-1">
          Paste the full meeting request JSON (work_item, question, constraints, context,
          nominated_paths, tools_enabled) and submit it to the existing R2 endpoint, same-origin,
          with this session. One POST per click. The request is validated before anything is
          sent — a failed validation posts nothing. There is no automatic retry: if the outcome
          is ambiguous, Submit stays disabled until you edit the text.
        </p>
      </div>
      <div>
        <label className="block text-slate-500 text-sm mb-1" htmlFor="build-council-request">
          Meeting request JSON
        </label>
        <textarea
          id="build-council-request"
          className="w-full min-h-[320px] bg-slate-800 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm font-mono"
          value={text}
          onChange={(e) => onTextChange(e.target.value)}
          placeholder='{"work_item": "...", "question": "...", "constraints": ["..."], "context": ["..."], "nominated_paths": [], "tools_enabled": false}'
          spellCheck={false}
        />
      </div>
      {error && <p className="text-red-400 text-sm">{error}</p>}
      <button
        type="button"
        disabled={submitting || ambiguous || text.trim().length === 0}
        onClick={submit}
        className="min-h-[44px] px-4 py-2 rounded-lg text-sm bg-amber-600 text-white hover:bg-amber-500 disabled:opacity-50"
      >
        {submitting ? 'Submitting…' : ambiguous ? 'Submit disabled — outcome unclear' : 'Submit meeting'}
      </button>
      {ambiguous && (
        <p className="text-amber-400 text-sm">
          Outcome unclear — see below. Edit the request text to re-enable Submit.
        </p>
      )}
      {result && result.kind === 'success' && (
        <div className="border border-slate-700 rounded-lg p-4 space-y-3">
          <h2 className="text-lg font-semibold text-slate-100">Meeting submitted</h2>
          <p className="text-sm text-slate-300">HTTP status: {result.status}</p>
          <p className="text-sm text-slate-300">Meeting id: {result.meetingId}</p>
          <p className="text-sm text-slate-300">ok: {result.ok ? 'true' : 'false'}</p>
          <pre className="w-full max-h-[480px] overflow-auto bg-slate-900 border border-slate-600 rounded px-3 py-2 text-slate-100 text-xs whitespace-pre-wrap break-words">
            {result.text}
          </pre>
        </div>
      )}
      {result && result.kind === 'failure' && (
        <div className="border border-slate-700 rounded-lg p-4 space-y-3">
          <h2 className="text-lg font-semibold text-slate-100">Submission failed</h2>
          <p className="text-sm text-slate-300">HTTP status: {result.status}</p>
          <pre className="w-full max-h-[480px] overflow-auto bg-slate-900 border border-slate-600 rounded px-3 py-2 text-slate-100 text-xs whitespace-pre-wrap break-words">
            {result.text}
          </pre>
        </div>
      )}
      {result && result.kind === 'ambiguous' && (
        <div className="border border-amber-600 rounded-lg p-4 space-y-3">
          <h2 className="text-lg font-semibold text-slate-100">Outcome unclear — no retry made</h2>
          <p className="text-sm text-slate-300">{result.detail}</p>
        </div>
      )}
    </div>
  )
}
