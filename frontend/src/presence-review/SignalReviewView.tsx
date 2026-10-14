/**
 * SignalReviewView — review distilled training-signal candidates, with
 * decision-context confirm/correct.
 *
 * Presence-ingest flow: pick an import session -> run distillation ->
 * review pending candidates. Decision-layer signals show their derived
 * context envelope as six small selectors; the user confirms or corrects
 * each dimension as part of approval. Approving a signal means "this
 * signal and its context are correct."
 *
 * Phone-first: stacked cards, 44px touch targets, no dense tables.
 */
import { useCallback, useEffect, useState } from 'react'
import { apiBase } from '../apiBase'
import {
  DIMENSION_LABELS,
  DIMENSION_ORDER,
  FALLBACK_DIMENSIONS,
  fetchContextDimensions,
  levelLabel,
  normalizeLevel,
  type ContextDimensions,
} from './contextDimensions'

interface ImportSession {
  session_id: string
  source: string
  file_name: string
  status: string
  counts: Record<string, number>
}

interface TrainingSignal {
  signal_id: string
  layer: string
  zone: string
  valence: string
  summary: string
  payload_redacted: string
  status: string
  context_ref: Record<string, any>
}

function derivedContext(signal: TrainingSignal): Record<string, string> {
  const raw = signal.context_ref?.decision_context
  const out: Record<string, string> = {}
  for (const dim of DIMENSION_ORDER) {
    out[dim] = normalizeLevel(dim, raw?.[dim])
  }
  return out
}

async function api(path: string, opts: RequestInit = {}) {
  const r = await fetch(`${apiBase()}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  })
  if (r.status === 401) throw new Error('Please sign in.')
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data.detail || 'Request failed')
  return data
}

function ContextSelectors({
  signalId,
  initial,
  dimensions,
  onChange,
  disabled,
}: {
  signalId: string
  initial: Record<string, string>
  dimensions: ContextDimensions
  onChange: (signalId: string, envelope: Record<string, string>) => void
  disabled?: boolean
}) {
  const [values, setValues] = useState<Record<string, string>>(initial)
  useEffect(() => setValues(initial), [signalId]) // eslint-disable-line react-hooks/exhaustive-deps

  function set(dim: string, level: string) {
    const next = { ...values, [dim]: level }
    setValues(next)
    onChange(signalId, next)
  }

  return (
    <fieldset className="mt-3 rounded-lg border border-stone-700 bg-stone-900/60 p-2">
      <legend className="px-1 text-xs text-stone-400">
        Decision context — confirm or correct
      </legend>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {DIMENSION_ORDER.map((dim) => {
          const levels = dimensions.dimensions[dim] ?? FALLBACK_DIMENSIONS.dimensions[dim]
          return (
            <label key={dim} className="block">
              <span className="mb-1 block text-xs text-stone-400">
                {DIMENSION_LABELS[dim] ?? dim}
              </span>
              <select
                value={values[dim] ?? 'unknown'}
                disabled={disabled}
                onChange={(e) => set(dim, e.target.value)}
                aria-label={`${DIMENSION_LABELS[dim] ?? dim} for this decision`}
                className="min-h-[44px] w-full rounded-md border border-stone-700 bg-stone-800 px-2 text-sm text-stone-100 disabled:opacity-50"
              >
                {levels.map((lv) => (
                  <option key={lv} value={lv}>
                    {levelLabel(lv)}
                  </option>
                ))}
              </select>
            </label>
          )
        })}
      </div>
      <p className="mt-2 text-[11px] leading-snug text-stone-500">
        Derived from the source material where shown — “unknown” means it
        wasn’t evidenced. Describes the situation, never the person.
      </p>
    </fieldset>
  )
}

export default function SignalReviewView() {
  const [sessions, setSessions] = useState<ImportSession[]>([])
  const [sessionId, setSessionId] = useState('')
  const [candidates, setCandidates] = useState<TrainingSignal[]>([])
  const [dimensions, setDimensions] = useState<ContextDimensions>(FALLBACK_DIMENSIONS)
  const [edits, setEdits] = useState<Record<string, Record<string, string>>>({})
  const [decided, setDecided] = useState<Record<string, boolean>>({})
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [distilling, setDistilling] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState('')

  const loadSessions = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const list = await api('/ingest/sessions')
      setSessions(Array.isArray(list) ? list : [])
      if (list?.length && !sessionId) setSessionId(list[0].session_id)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load sessions')
    } finally {
      setLoading(false)
    }
  }, [sessionId])

  const loadCandidates = useCallback(async (sid: string) => {
    if (!sid) return
    setError('')
    setResult('')
    try {
      const list = await api(`/ingest/sessions/${sid}/candidates`)
      const arr = Array.isArray(list) ? list : []
      setCandidates(arr)
      const seed: Record<string, Record<string, string>> = {}
      for (const s of arr) seed[s.signal_id] = derivedContext(s)
      setEdits(seed)
      setDecided({})
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load candidates')
    }
  }, [])

  useEffect(() => {
    loadSessions()
    fetchContextDimensions(apiBase()).then(setDimensions).catch(() => {})
  }, [loadSessions])

  useEffect(() => {
    if (sessionId) loadCandidates(sessionId)
  }, [sessionId, loadCandidates])

  async function runDistill() {
    if (!sessionId) return
    setDistilling(true)
    setError('')
    try {
      const r = await api(`/ingest/sessions/${sessionId}/distill`, { method: 'POST' })
      setResult(`Distilled ${r.candidates ?? 0} candidate signals.`)
      await loadCandidates(sessionId)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Distillation failed')
    } finally {
      setDistilling(false)
    }
  }

  function onContextChange(signalId: string, envelope: Record<string, string>) {
    setEdits((prev) => ({ ...prev, [signalId]: envelope }))
  }

  async function submitReview() {
    const approvals: Record<string, boolean> = {}
    const contexts: Record<string, Record<string, string>> = {}
    for (const s of candidates) {
      if (!(s.signal_id in decided)) continue
      approvals[s.signal_id] = decided[s.signal_id]
      if (s.layer === 'decision' && edits[s.signal_id]) {
        contexts[s.signal_id] = edits[s.signal_id]
      }
    }
    if (!Object.keys(approvals).length) {
      setError('Approve or reject at least one signal first.')
      return
    }
    setBusy(true)
    setError('')
    try {
      const r = await api(`/ingest/sessions/${sessionId}/review`, {
        method: 'POST',
        body: JSON.stringify({ approvals, contexts }),
      })
      setResult(
        `Reviewed: ${r.approved ?? 0} approved, ${r.rejected ?? 0} rejected` +
          (r.contexts_updated ? `, ${r.contexts_updated} context envelopes saved` : '') +
          '.',
      )
      await loadCandidates(sessionId)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Review failed')
    } finally {
      setBusy(false)
    }
  }

  const pending = candidates.filter((c) => c.status === 'pending')

  return (
    <div className="mx-auto w-full max-w-2xl px-3 py-4">
      <h2 className="text-lg font-semibold text-stone-100">Signal review</h2>
      <p className="mt-1 text-sm text-stone-400">
        Review distilled training signals. For decisions, confirm or correct
        the situation they were made in — approving means the signal and its
        context are correct.
      </p>

      {error && (
        <p role="alert" className="mt-3 rounded-md border border-red-800 bg-red-950/60 px-3 py-2 text-sm text-red-200">
          {error}
        </p>
      )}
      {result && (
        <p role="status" className="mt-3 rounded-md border border-emerald-800 bg-emerald-950/60 px-3 py-2 text-sm text-emerald-200">
          {result}
        </p>
      )}

      <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-end">
        <label className="block flex-1">
          <span className="mb-1 block text-xs text-stone-400">Import session</span>
          <select
            value={sessionId}
            onChange={(e) => setSessionId(e.target.value)}
            className="min-h-[44px] w-full rounded-md border border-stone-700 bg-stone-800 px-2 text-sm text-stone-100"
          >
            {sessions.map((s) => (
              <option key={s.session_id} value={s.session_id}>
                {s.file_name || s.session_id} ({s.status})
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          onClick={runDistill}
          disabled={!sessionId || distilling}
          className="min-h-[44px] rounded-md border border-stone-600 bg-stone-800 px-4 text-sm font-medium text-stone-100 disabled:opacity-50"
        >
          {distilling ? 'Distilling…' : 'Run distillation'}
        </button>
      </div>

      {loading ? (
        <p className="mt-6 text-sm text-stone-500">Loading…</p>
      ) : pending.length === 0 ? (
        <p className="mt-6 text-sm text-stone-500">
          No pending candidates. Run distillation on an import session to create some.
        </p>
      ) : (
        <div className="mt-4 flex flex-col gap-3">
          {pending.map((s) => {
            const decision = s.layer === 'decision'
            const choice = decided[s.signal_id]
            return (
              <article
                key={s.signal_id}
                className="rounded-xl border border-stone-700 bg-stone-900 p-3"
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="text-sm font-medium text-stone-100">{s.summary}</p>
                    <p className="mt-1 text-xs text-stone-500">
                      {s.layer} · {s.zone} · {s.valence}
                    </p>
                  </div>
                </div>
                {s.payload_redacted && (
                  <p className="mt-2 text-sm leading-snug text-stone-300">{s.payload_redacted}</p>
                )}
                {decision && (
                  <ContextSelectors
                    signalId={s.signal_id}
                    initial={edits[s.signal_id] ?? derivedContext(s)}
                    dimensions={dimensions}
                    onChange={onContextChange}
                    disabled={busy}
                  />
                )}
                <div className="mt-3 grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => setDecided((d) => ({ ...d, [s.signal_id]: true }))}
                    aria-pressed={choice === true}
                    className={`min-h-[44px] rounded-md px-3 text-sm font-medium disabled:opacity-50 ${
                      choice === true
                        ? 'bg-emerald-700 text-stone-50'
                        : 'border border-stone-600 bg-stone-800 text-stone-200'
                    }`}
                  >
                    Approve{decision ? ' signal + context' : ''}
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => setDecided((d) => ({ ...d, [s.signal_id]: false }))}
                    aria-pressed={choice === false}
                    className={`min-h-[44px] rounded-md px-3 text-sm font-medium disabled:opacity-50 ${
                      choice === false
                        ? 'bg-red-800 text-stone-50'
                        : 'border border-stone-600 bg-stone-800 text-stone-200'
                    }`}
                  >
                    Reject
                  </button>
                </div>
              </article>
            )
          })}
          <button
            type="button"
            onClick={submitReview}
            disabled={busy || !Object.keys(decided).length}
            className="min-h-[48px] rounded-md bg-yellow-700 px-4 text-sm font-semibold text-stone-50 disabled:opacity-50"
          >
            {busy ? 'Saving…' : `Submit review (${Object.keys(decided).length})`}
          </button>
        </div>
      )}
    </div>
  )
}
