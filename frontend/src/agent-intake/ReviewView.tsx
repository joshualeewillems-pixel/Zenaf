import { useEffect, useState } from 'react'
import { apiBase } from '../apiBase'
import ClaimCard, { Claim } from './ClaimCard'

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
  const [claims, setClaims] = useState<Claim[]>([])
  const [claimsLoading, setClaimsLoading] = useState(false)

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
      setClaims([])
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Confirm failed')
    } finally {
      setBusy(false)
    }
  }

  async function loadClaims(agentId: string) {
    setClaimsLoading(true)
    try {
      setClaims(await api(`/agents/${agentId}/claims`))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load claims')
    } finally {
      setClaimsLoading(false)
    }
  }

  function onClaimResolved(updated: Claim) {
    setClaims((cs) => cs.map((c) => (c.id === updated.id ? updated : c)))
  }

  async function mine(a: Agent) {
    setMining(true)
    setError('')
    try {
      const transcript = (a.examples || []).join('\n\n') || a.description
      const data = await api('/agents/mine-projects', {
        method: 'POST',
        body: JSON.stringify({ transcript, agent_id: a.id }),
      })
      setMined(data)
      const all: string[] = [
        ...(data.initiatives || []).map((x: any) => 'i:' + x.title),
        ...(data.projects || []).map((x: any) => 'p:' + x.title),
        ...(data.standalone_tasks || []).map((x: any) => 't:' + x.title),
        ...(data.ideas || []).map((x: any) => 'd:' + x.title),
      ]
      setChecked(new Set(all))
      // Refresh claims so the mined proposals appear as review cards.
      await loadClaims(a.id)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Mining failed')
    } finally {
      setMining(false)
    }
  }

  async function createSelected() {
    setBusy(true)
    try {
      // Primary path: create from accepted claim cards.
      const minedClaims = claims.filter((c) =>
        ['initiative', 'project', 'task', 'idea'].includes(c.claim_type) && c.status === 'accepted'
      )
      if (minedClaims.length > 0 && mined) {
        const byType = (t: string) => minedClaims.filter((c) => c.claim_type === t).map((c) => c.title)
        const find = (arr: any[], title: string) => arr.find((x: any) => x.title === title)
        await api('/agents/mined-projects/confirm', {
          method: 'POST',
          body: JSON.stringify({
            initiatives: byType('initiative').map((t) => find(mined.initiatives, t)).filter(Boolean),
            projects: byType('project').map((t) => find(mined.projects, t)).filter(Boolean),
            standalone_tasks: byType('task').map((t) => find(mined.standalone_tasks, t)).filter(Boolean),
            ideas: byType('idea').map((t) => find(mined.ideas, t)).filter(Boolean),
            selected_titles: null,
          }),
        })
      } else if (mined) {
        // Secondary fast path: the checkbox bulk selection.
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
      }
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
    const strandClaims = claims.filter((c) => c.claim_type === 'strand' || c.claim_type === 'kind')
    const minedClaims = claims.filter((c) => ['initiative', 'project', 'task', 'idea'].includes(c.claim_type))
    const acceptedMined = minedClaims.filter((c) => c.status === 'accepted')
    return (
      <div className="flex-1 flex flex-col min-h-0 overflow-y-auto p-4 max-w-2xl mx-auto w-full">
        <button onClick={() => { setSelected(null); setCorrecting(false); setMined(null); setClaims([]) }} className="self-start text-stone-400 text-[15px] min-h-[44px] mb-2">‹ Back</button>
        <h2 className="text-xl font-bold text-stone-100">{a.name}</h2>
        <p className="text-stone-500 text-sm mb-4">{a.source_platform} · {new Date(a.created_at).toLocaleDateString()}</p>

        <h3 className="text-stone-200 font-semibold text-[15px] mb-2">What's being assimilated</h3>
        <p className="text-stone-500 text-sm mb-3">Each card is one thing I'd take from this conversation. Say what you think — your answers train the sorter.</p>
        {claimsLoading && <p className="text-stone-500 text-sm mb-3">Reading the conversation…</p>}
        {!claimsLoading && strandClaims.length === 0 && (
          <p className="text-stone-500 text-sm mb-4">No strand placements yet.</p>
        )}
        {strandClaims.map((c) => (
          <ClaimCard key={c.id} agentId={a.id} claim={c} onResolved={onClaimResolved} />
        ))}

        {error && <p className="text-red-300 text-sm mb-3">{error}</p>}

        {!correcting ? (
          <div className="flex flex-wrap gap-2 mb-6 mt-2">
            <button onClick={() => confirm(a.id, true)} disabled={busy} className="min-h-[44px] px-5 rounded-xl bg-yellow-500/90 text-stone-900 font-semibold text-[15px] disabled:opacity-40">Accept all</button>
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
        {minedClaims.length > 0 ? (
          <div className="mb-4">
            {minedClaims.map((c) => (
              <ClaimCard key={c.id} agentId={a.id} claim={c} onResolved={onClaimResolved} />
            ))}
            {acceptedMined.length > 0 && (
              <button onClick={createSelected} disabled={busy} className="min-h-[44px] px-5 rounded-xl bg-yellow-500/90 text-stone-900 font-semibold text-[15px] disabled:opacity-40 mt-1">
                Create {acceptedMined.length} accepted
              </button>
            )}
          </div>
        ) : !mined ? (
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
            onClick={() => { setSelected(a); setClaims([]); loadClaims(a.id) }}
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
