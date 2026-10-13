import { useEffect, useState } from 'react'
import { apiBase } from '../apiBase'

const STRANDS = [
  { key: 'word', name: 'Storyteller' },
  { key: 'number', name: 'Patternist' },
  { key: 'image', name: 'Seer' },
  { key: 'sound', name: 'Songwriter' },
  { key: 'body', name: 'Maker' },
  { key: 'people', name: 'Mediator' },
  { key: 'self', name: 'Guide' },
]
const KINDS = ['skill', 'talent', 'project', 'undecided']

type Agent = {
  id: string
  name: string
  source_platform: string
  description: string
  examples: string[]
  status: string
  created_at: string
  sort: { primary_strand: string; strand_weights: Record<string, number>; kind: string } | null
}

type Mined = {
  initiatives: any[]
  projects: any[]
  standalone_tasks: any[]
  ideas: any[]
}

function strandName(key: string): string {
  return STRANDS.find((s) => s.key === key)?.name || key
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

export default function ReviewView() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [selected, setSelected] = useState<Agent | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [correcting, setCorrecting] = useState(false)
  const [newStrand, setNewStrand] = useState('')
  const [newKind, setNewKind] = useState('')
  const [mined, setMined] = useState<Mined | null>(null)
  const [mining, setMining] = useState(false)
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)

  async function load() {
    setLoading(true)
    setError('')
    try {
      setAgents(await api('/agents/pending'))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load the review queue')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  async function confirm(agentId: string, accepted: boolean, corrections?: Record<string, string>) {
    setBusy(true)
    try {
      await api(`/agents/${agentId}/confirm`, {
        method: 'POST',
        body: JSON.stringify({ accepted, corrections: corrections || {} }),
      })
      setSelected(null)
      setCorrecting(false)
      setMined(null)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Confirm failed')
    } finally {
      setBusy(false)
    }
  }

  async function mine(a: Agent) {
    setMining(true)
    setError('')
    try {
      const transcript = (a.examples || []).join('\n\n') || a.description
      const data = await api('/agents/mine-projects', {
        method: 'POST',
        body: JSON.stringify({ transcript }),
      })
      setMined(data)
      const all: string[] = [
        ...(data.initiatives || []).map((x: any) => 'i:' + x.title),
        ...(data.projects || []).map((x: any) => 'p:' + x.title),
        ...(data.standalone_tasks || []).map((x: any) => 't:' + x.title),
        ...(data.ideas || []).map((x: any) => 'd:' + x.title),
      ]
      setChecked(new Set(all))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Mining failed')
    } finally {
      setMining(false)
    }
  }

  async function createSelected() {
    if (!mined) return
    setBusy(true)
    try {
      const pick = (arr: any[], prefix: string) => arr.filter((x: any) => checked.has(prefix + x.title))
      await api('/agents/mined-projects/confirm', {
        method: 'POST',
        body: JSON.stringify({
          initiatives: pick(mined.initiatives, 'i:'),
          projects: pick(mined.projects, 'p:'),
          standalone_tasks: pick(mined.standalone_tasks, 't:'),
          ideas: pick(mined.ideas, 'd:'),
          selected_titles: null,
        }),
      })
      setMined(null)
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Create failed')
    } finally {
      setBusy(false)
    }
  }

  function toggle(key: string) {
    setChecked((c) => {
      const n = new Set(c)
      if (n.has(key)) n.delete(key)
      else n.add(key)
      return n
    })
  }

  if (selected) {
    const a = selected
    const weights = a.sort?.strand_weights || {}
    const sorted = Object.entries(weights).sort((x, y) => y[1] - x[1])
    return (
      <div className="flex-1 flex flex-col min-h-0 overflow-y-auto p-4 max-w-2xl mx-auto w-full">
        <button onClick={() => { setSelected(null); setCorrecting(false); setMined(null) }} className="self-start text-stone-400 text-[15px] min-h-[44px] mb-2">‹ Back</button>
        <h2 className="text-xl font-bold text-stone-100">{a.name}</h2>
        <p className="text-stone-500 text-sm mb-4">{a.source_platform} · {new Date(a.created_at).toLocaleDateString()}</p>

        <h3 className="text-stone-200 font-semibold text-[15px] mb-2">Strands</h3>
        <div className="space-y-1.5 mb-5">
          {sorted.length === 0 && <p className="text-stone-500 text-sm">No sort yet.</p>}
          {sorted.map(([k, v]) => (
            <div key={k} className="flex items-center gap-2">
              <span className="text-stone-300 text-sm w-28">{strandName(k)}</span>
              <div className="flex-1 h-2 rounded bg-stone-800 overflow-hidden">
                <div className="h-full bg-yellow-500/80 rounded" style={{ width: `${Math.round(v * 100)}%` }} />
              </div>
              <span className="text-stone-500 text-xs w-8 text-right">{v.toFixed(1)}</span>
            </div>
          ))}
        </div>

        {a.sort?.kind && <p className="text-stone-400 text-sm mb-4">Kind: <b className="text-stone-200">{a.sort.kind}</b></p>}
        <p className="text-stone-400 text-sm mb-6 whitespace-pre-wrap">{a.description}</p>

        {error && <p className="text-red-300 text-sm mb-3">{error}</p>}

        {!correcting ? (
          <div className="flex flex-wrap gap-2 mb-6">
            <button onClick={() => confirm(a.id, true)} disabled={busy} className="min-h-[44px] px-5 rounded-xl bg-yellow-500/90 text-stone-900 font-semibold text-[15px] disabled:opacity-40">Accept</button>
            <button onClick={() => setCorrecting(true)} disabled={busy} className="min-h-[44px] px-5 rounded-xl bg-stone-700 text-stone-100 font-semibold text-[15px] disabled:opacity-40">Correct</button>
            <button onClick={() => confirm(a.id, false)} disabled={busy} className="min-h-[44px] px-5 rounded-xl bg-stone-800 text-stone-400 text-[15px] disabled:opacity-40">Archive</button>
          </div>
        ) : (
          <div className="rounded-2xl border border-stone-700 bg-stone-800/60 p-4 mb-6">
            <p className="text-stone-300 text-sm mb-3">Your correction becomes training signal for the sorter.</p>
            <label className="block text-stone-400 text-sm mb-1">Primary strand</label>
            <select value={newStrand} onChange={(e) => setNewStrand(e.target.value)} className="w-full min-h-[44px] mb-3 px-3 rounded-xl bg-stone-900 text-stone-100 text-[15px] border border-stone-700">
              <option value="">— keep —</option>
              {STRANDS.map((s) => <option key={s.key} value={s.key}>{s.name}</option>)}
            </select>
            <label className="block text-stone-400 text-sm mb-1">Kind</label>
            <select value={newKind} onChange={(e) => setNewKind(e.target.value)} className="w-full min-h-[44px] mb-4 px-3 rounded-xl bg-stone-900 text-stone-100 text-[15px] border border-stone-700">
              <option value="">— keep —</option>
              {KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
            </select>
            <div className="flex gap-2">
              <button
                onClick={() => {
                  const c: Record<string, string> = {}
                  if (newStrand) c.primary_strand = newStrand
                  if (newKind) c.kind = newKind
                  confirm(a.id, false, c)
                }}
                disabled={busy || (!newStrand && !newKind)}
                className="min-h-[44px] px-5 rounded-xl bg-yellow-500/90 text-stone-900 font-semibold text-[15px] disabled:opacity-40"
              >
                Submit correction
              </button>
              <button onClick={() => setCorrecting(false)} className="min-h-[44px] px-4 rounded-xl text-stone-400 text-[15px]">Cancel</button>
            </div>
          </div>
        )}

        <h3 className="text-stone-200 font-semibold text-[15px] mb-2">Projects</h3>
        {!mined ? (
          <button onClick={() => mine(a)} disabled={mining} className="min-h-[44px] px-5 rounded-xl bg-stone-700 text-stone-100 font-semibold text-[15px] disabled:opacity-40 self-start">
            {mining ? 'Reading…' : 'Mine projects from this conversation'}
          </button>
        ) : (
          <div className="mb-6">
            {(['initiatives', 'projects', 'standalone_tasks', 'ideas'] as const).map((section) => {
              const items = mined[section] || []
              if (!items.length) return null
              const prefix = { initiatives: 'i:', projects: 'p:', standalone_tasks: 't:', ideas: 'd:' }[section]
              const label = { initiatives: 'Initiatives', projects: 'Projects', standalone_tasks: 'Tasks', ideas: 'Ideas' }[section]
              return (
                <div key={section} className="mb-3">
                  <p className="text-stone-500 text-xs uppercase tracking-wide mb-1">{label}</p>
                  {items.map((x: any) => {
                    const key = prefix + x.title
                    return (
                      <label key={key} className="flex items-start gap-3 py-2 min-h-[44px] cursor-pointer">
                        <input type="checkbox" checked={checked.has(key)} onChange={() => toggle(key)} className="mt-1 w-5 h-5 accent-yellow-500" />
                        <span>
                          <span className="block text-stone-200 text-[15px]">{x.title}</span>
                          {x.description && <span className="block text-stone-500 text-sm">{x.description}</span>}
                        </span>
                      </label>
                    )
                  })}
                </div>
              )
            })}
            <button onClick={createSelected} disabled={busy || checked.size === 0} className="min-h-[44px] px-5 rounded-xl bg-yellow-500/90 text-stone-900 font-semibold text-[15px] disabled:opacity-40 mt-2">
              Create {checked.size} selected
            </button>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-y-auto p-4 max-w-2xl mx-auto w-full">
      <h2 className="text-xl font-bold text-stone-100 mb-1">Review queue</h2>
      <p className="text-stone-400 text-sm mb-4">
        {agents.length === 0 ? 'Nothing waiting.' : `${agents.length} conversation${agents.length === 1 ? '' : 's'} to review.`} Nothing trains until you accept it.
      </p>
      {loading && <p className="text-stone-500 text-sm">Loading…</p>}
      {error && <p className="text-red-300 text-sm mb-3">{error}</p>}
      <div className="space-y-2">
        {agents.map((a) => (
          <button
            key={a.id}
            onClick={() => setSelected(a)}
            className="w-full text-left rounded-2xl border border-stone-700 bg-stone-800/60 p-4 min-h-[44px]"
          >
            <span className="block text-stone-100 font-semibold text-[15px]">{a.name}</span>
            <span className="block text-stone-500 text-sm mt-0.5">
              {a.sort ? strandName(a.sort.primary_strand) : 'unsorted'} · {new Date(a.created_at).toLocaleDateString()}
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}
