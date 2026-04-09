/**
 * Dev-only: append interpretive soil for the focused task via POST /vision-execution/soil/append.
 * Parent should render only when import.meta.env.DEV.
 */

import { useEffect, useState } from 'react'

/** Matches API Pydantic `SoilAppendRequest.body` max_length. */
const SOIL_APPEND_BODY_MAX = 262_144

const SOIL_TYPE_OPTIONS = [
  { value: 'tension', label: 'tension' },
  { value: 'hypothesis', label: 'hypothesis' },
  { value: 'excerpt', label: 'excerpt' },
  { value: 'inbox', label: 'inbox' },
  { value: 'recurring_pattern', label: 'recurring_pattern' },
  { value: 'mediation', label: 'mediation' },
  { value: 'entity_shadow', label: 'entity_shadow' },
  { value: 'route_observation', label: 'route_observation' },
  { value: 'candidate_truth', label: 'candidate_truth' },
] as const

type SoilAppendResponse = {
  ok?: boolean
  soil_id?: string
  relative_path?: string
}

export function TaskSoilDevAppend({
  taskId,
  taskTitle,
  apiPost,
}: {
  taskId: string
  taskTitle: string
  apiPost: <T>(path: string, body: unknown) => Promise<T>
}) {
  const [soilType, setSoilType] = useState<string>('tension')
  const [bodyText, setBodyText] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [last, setLast] = useState<{
    soil_id: string
    relative_path: string
    resolved_node_id: string
  } | null>(null)

  useEffect(() => {
    setBodyText('')
    setErr(null)
    setLast(null)
    setSoilType('tension')
  }, [taskId])

  const submit = async () => {
    const body = bodyText.trim()
    if (!body) {
      setErr('Body is required.')
      return
    }
    setErr(null)
    setBusy(true)
    try {
      const out = await apiPost<SoilAppendResponse>('/soil/append', {
        entity_type: 'task',
        entity_id: taskId,
        soil_type: soilType,
        body,
        capture_source: 'user_action',
        title: (taskTitle || 'Task').slice(0, 512),
      })
      if (!out.soil_id || !out.relative_path) {
        setErr('Unexpected response (missing soil_id or relative_path).')
        setLast(null)
        return
      }
      setLast({
        soil_id: out.soil_id,
        relative_path: out.relative_path,
        resolved_node_id: `task:${taskId}`,
      })
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Append failed')
      setLast(null)
    } finally {
      setBusy(false)
    }
  }

  const inputCls =
    'w-full px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-sm placeholder:text-slate-500'

  return (
    <div className="rounded-lg border border-amber-700/50 bg-amber-950/20 p-3 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-amber-200/90">Soil (dev)</h4>
        <span className="text-[10px] text-amber-200/50">user_action · this task only</span>
      </div>
      <p className="text-[11px] text-slate-500">
        Writes under your soil root (<code className="text-slate-400">ZENAF_SOIL_ROOT</code> or{' '}
        <code className="text-slate-400">~/.zenaf/soil/v1</code>). Requires signed-in session and a task id you own
        (others → 404). Body max {SOIL_APPEND_BODY_MAX.toLocaleString()} chars; title capped at 512 in{' '}
        <code className="text-slate-400">node.json</code>.
      </p>
      <label className="block text-[11px] text-slate-400">
        soil_type
        <select
          className={`${inputCls} mt-0.5`}
          value={soilType}
          onChange={(e) => setSoilType(e.target.value)}
        >
          {SOIL_TYPE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
      <label className="block text-[11px] text-slate-400">
        Body (markdown)
        <textarea
          className={`${inputCls} mt-0.5 font-mono text-[12px]`}
          rows={4}
          value={bodyText}
          maxLength={SOIL_APPEND_BODY_MAX}
          onChange={(e) => setBodyText(e.target.value)}
          placeholder="e.g. Scope approval is still ambiguous…"
        />
      </label>
      {err && <p className="text-xs text-red-400">{err}</p>}
      {last && (
        <div className="rounded border border-slate-600 bg-slate-950/50 p-2 text-[11px] text-slate-300 space-y-1 font-mono break-all">
          <div>
            <span className="text-slate-500">soil_id</span> {last.soil_id}
          </div>
          <div>
            <span className="text-slate-500">resolved_node</span> {last.resolved_node_id}
          </div>
          <div>
            <span className="text-slate-500">relative_path</span> {last.relative_path}
          </div>
        </div>
      )}
      <button
        type="button"
        disabled={busy}
        onClick={() => void submit()}
        className="px-3 py-1.5 rounded-lg bg-amber-700/80 hover:bg-amber-600 disabled:opacity-50 text-white text-xs font-medium"
      >
        {busy ? 'Appending…' : 'Append to soil'}
      </button>
    </div>
  )
}
