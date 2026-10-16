import { useEffect, useState } from 'react'
import { apiBase } from '../apiBase'
import ClaimCard, { Claim } from './ClaimCard'
import ReviewChat from './ReviewChat'
import MiningChat from './MiningChat'
import {
  MINED_CLAIM_TYPES,
  MiningState,
  PLACEMENT_CLAIM_TYPES,
  canFinishReview,
  insightGroups,
  miningStateOf,
  miningStatusLabel,
  reviewedList,
  strandGroups,
  whatsLeft,
} from './reviewStages'

const STRANDS = [
  { key: 'word', name: 'Voice' },
  { key: 'number', name: 'Logic' },
  { key: 'image', name: 'Eye' },
  { key: 'sound', name: 'Ear' },
  { key: 'body', name: 'Hands' },
  { key: 'people', name: 'Heart' },
  { key: 'self', name: 'Compass' },
]

type Agent = {
  id: string
  name: string
  source_platform: string
  description: string
  examples: string[]
  status: string
  created_at: string
  mining_state?: string | null
  mined_payload?: Mined | null
  sort: { primary_strand: string; strand_weights: Record<string, number>; kind: string } | null
}

type Mined = {
  engine?: string
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
  const [reviewed, setReviewed] = useState<Agent[]>([])
  const [selected, setSelected] = useState<Agent | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [minedPayload, setMinedPayload] = useState<Mined | null>(null)
  const [miningBusy, setMiningBusy] = useState(false)
  const [busy, setBusy] = useState(false)
  const [acceptingPlacements, setAcceptingPlacements] = useState(false)
  const [claims, setClaims] = useState<Claim[]>([])
  const [claimsLoading, setClaimsLoading] = useState(false)
  const [regenerating, setRegenerating] = useState(false)
  const [reviewTab, setReviewTab] = useState<'chat' | 'cards' | 'mining'>('chat')

  async function load() {
    setLoading(true)
    setError('')
    try {
      const [pending, all] = await Promise.all([api('/agents/pending'), api('/agents')])
      setAgents(pending)
      setReviewed(reviewedList(all))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load the review queue')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  function select(a: Agent) {
    setSelected(a)
    setClaims([])
    setMinedPayload(a.mined_payload || null)
    setCreatedSummary('')
    setError('')
    loadClaims(a.id)
  }

  function deselect() {
    setSelected(null)
    setMinedPayload(null)
    setClaims([])
    setError('')
  }

  async function confirmAgent(agentId: string, accepted: boolean) {
    setBusy(true)
    try {
      await api(`/agents/${agentId}/confirm`, {
        method: 'POST',
        body: JSON.stringify({ accepted }),
      })
      deselect()
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

  /** Re-read the conversation for atomic insights — rebuilds strand/kind/
      insight claims from the stored transcript, keeping your existing
      verdicts. Mined project claims are untouched. */
  async function regenerateInsights(a: Agent) {
    setRegenerating(true)
    setError('')
    try {
      const data = await api(`/agents/${a.id}/claims/regenerate`, { method: 'POST' })
      if (Array.isArray(data.claims)) setClaims(data.claims)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Re-read failed')
    } finally {
      setRegenerating(false)
    }
  }

  /** Accept every open strand/kind placement at once — resolves claims, does NOT file the agent. */
  async function acceptAllPlacements(a: Agent, pending: Claim[]) {
    setAcceptingPlacements(true)
    setError('')
    try {
      const updated: Claim[] = await Promise.all(
        pending.map((c) => api(`/agents/${a.id}/claims/${c.id}/accept`, { method: 'POST' })),
      )
      const byId = new Map(updated.map((u) => [u.id, u]))
      setClaims((cs) => cs.map((c) => byId.get(c.id) || c))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Accept failed')
    } finally {
      setAcceptingPlacements(false)
    }
  }

  async function mine(a: Agent) {
    setMiningBusy(true)
    setError('')
    try {
      const transcript = (a.examples || []).join('\n\n') || a.description
      const data: Mined = await api('/agents/mine-projects', {
        method: 'POST',
        body: JSON.stringify({ transcript, agent_id: a.id }),
      })
      setMinedPayload(data)
      setSelected({ ...a, mining_state: 'mined', mined_payload: data })
      await loadClaims(a.id)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Mining failed')
    } finally {
      setMiningBusy(false)
    }
  }

  async function skipMining(a: Agent) {
    setBusy(true)
    setError('')
    try {
      const updated: Agent = await api(`/agents/${a.id}/skip-mining`, { method: 'POST' })
      setSelected(updated)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Skip failed')
    } finally {
      setBusy(false)
    }
  }

  /** Create Vision Execution entities from the accepted mined claim cards.
      Sends agent_id so the server resolves from the stored mined_payload —
      robust against stale client data. Returns created counts for feedback. */
  async function createAccepted(
    agentId: string,
    accepted: Claim[],
    payload: Mined,
  ): Promise<{ initiative_ids: string[]; project_ids: string[]; task_ids: string[]; idea_ids: string[] }> {
    const byType = (t: string) => accepted.filter((c) => c.claim_type === t).map((c) => c.title)
    const find = (arr: any[], title: string) => arr.find((x: any) => x.title === title)
    return api('/agents/mined-projects/confirm', {
      method: 'POST',
      body: JSON.stringify({
        agent_id: agentId,
        initiatives: byType('initiative').map((t) => find(payload.initiatives, t)).filter(Boolean),
        projects: byType('project').map((t) => find(payload.projects, t)).filter(Boolean),
        standalone_tasks: byType('task').map((t) => find(payload.standalone_tasks, t)).filter(Boolean),
        ideas: byType('idea').map((t) => find(payload.ideas, t)).filter(Boolean),
        selected_titles: byType('initiative')
          .concat(byType('project'), byType('task'), byType('idea')),
      }),
    })
  }

  const [createdSummary, setCreatedSummary] = useState('')

  async function createSelected(a: Agent, accepted: Claim[]) {
    if (!minedPayload || accepted.length === 0) return
    setBusy(true)
    setCreatedSummary('')
    try {
      const out = await createAccepted(a.id, accepted, minedPayload)
      const n = (out.initiative_ids?.length || 0) + (out.project_ids?.length || 0) +
        (out.task_ids?.length || 0) + (out.idea_ids?.length || 0)
      if (n === 0) {
        setError('Nothing was created — the proposals may not have matched. Try mining again.')
      } else {
        const parts: string[] = []
        if (out.initiative_ids?.length) parts.push(`${out.initiative_ids.length} initiative${out.initiative_ids.length === 1 ? '' : 's'}`)
        if (out.project_ids?.length) parts.push(`${out.project_ids.length} project${out.project_ids.length === 1 ? '' : 's'}`)
        if (out.task_ids?.length) parts.push(`${out.task_ids.length} task${out.task_ids.length === 1 ? '' : 's'}`)
        if (out.idea_ids?.length) parts.push(`${out.idea_ids.length} idea${out.idea_ids.length === 1 ? '' : 's'}`)
        setCreatedSummary(`Created ${parts.join(', ')} — they should now appear in your Vision map.`)
      }
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Create failed')
    } finally {
      setBusy(false)
    }
  }

  /** Final step: create accepted projects first (nothing lost), then file the agent. */
  async function finishReview(a: Agent, accepted: Claim[]) {
    setBusy(true)
    setError('')
    try {
      if (accepted.length > 0 && minedPayload) {
        await createAccepted(a.id, accepted, minedPayload)
      }
      await api(`/agents/${a.id}/confirm`, {
        method: 'POST',
        body: JSON.stringify({ accepted: true }),
      })
      deselect()
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Finish failed')
    } finally {
      setBusy(false)
    }
  }

  if (selected) {
    const a = selected
    const isPending = a.status === 'pending_review'
    const strandClaims = claims.filter((c) => PLACEMENT_CLAIM_TYPES.includes(c.claim_type))
    const kindClaim = claims.find((c) => c.claim_type === 'kind')
    const minedClaims = claims.filter((c) => MINED_CLAIM_TYPES.includes(c.claim_type))
    const groups = insightGroups(claims)
    const placementGroups = strandGroups(claims)
    const pendingPlacements = strandClaims.filter((c) => c.status === 'pending')
    const acceptedMined = minedClaims.filter((c) => c.status === 'accepted')
    const miningStage: MiningState = miningStateOf(a.mining_state, claims)
    const finishable = canFinishReview(claims, miningStage)
    const left = whatsLeft(claims, miningStage)

    return (
      <div className="flex-1 flex flex-col min-h-0 overflow-y-auto p-4 max-w-2xl mx-auto w-full">
        <button onClick={deselect} className="self-start text-stone-400 text-[15px] min-h-[44px] mb-2">‹ Back</button>
        <h2 className="text-xl font-bold text-stone-100">{a.name}</h2>
        <p className="text-stone-500 text-sm mb-4">
          {a.source_platform} · {new Date(a.created_at).toLocaleDateString()}
          {!isPending && ' · filed'}
        </p>

        {/* Two modes: strand training vs practical extraction */}
        <div className="flex gap-2 mb-4">
          <button
            onClick={() => setReviewTab('chat')}
            className={`flex-1 min-h-[44px] px-4 rounded-xl font-semibold text-[15px] ${
              reviewTab === 'chat'
                ? 'bg-stone-700 text-stone-100'
                : 'bg-stone-800/60 text-stone-400 border border-stone-700'
            }`}
          >
            Work on strands
          </button>
          <button
            onClick={() => setReviewTab('mining')}
            className={`flex-1 min-h-[44px] px-4 rounded-xl font-semibold text-[15px] ${
              reviewTab === 'mining'
                ? 'bg-amber-700 text-amber-50'
                : 'bg-stone-800/60 text-stone-400 border border-stone-700'
            }`}
          >
            Pull tasks & stuff
          </button>
        </div>

        {reviewTab === 'chat' ? (
          <ReviewChat agentId={a.id} agentName={a.name} />
        ) : reviewTab === 'mining' ? (
          <MiningChat agentId={a.id} agentName={a.name} />
        ) : (
          <>
            <h3 className="text-stone-200 font-semibold text-[15px] mb-2">What's being assimilated</h3>
            <p className="text-stone-500 text-sm mb-3">Each card is one thing I'd take from this conversation. Say what you think — your answers train the sorter.</p>
          </>
        )}
        {reviewTab === 'cards' && claimsLoading && <p className="text-stone-500 text-sm mb-3">Reading the conversation…</p>}
        {reviewTab === 'cards' && !claimsLoading && strandClaims.length === 0 && (
          <p className="text-stone-500 text-sm mb-4">No strand placements yet.</p>
        )}
        {reviewTab === 'cards' && placementGroups.map((g) => (
          <div key={g.insight.id}>
            <ClaimCard
              agentId={a.id}
              claim={g.insight}
              alternatives={g.alternatives}
              onResolved={onClaimResolved}
            />
          </div>
        ))}
        {reviewTab === 'cards' && kindClaim && (
          <ClaimCard key={kindClaim.id} agentId={a.id} claim={kindClaim} onResolved={onClaimResolved} />
        )}
        {reviewTab === 'cards' && isPending && pendingPlacements.length > 0 && (
          <button
            onClick={() => acceptAllPlacements(a, pendingPlacements)}
            disabled={acceptingPlacements || busy}
            className="min-h-[44px] px-5 rounded-xl bg-stone-700 text-stone-100 font-semibold text-[15px] disabled:opacity-40 self-start mb-6"
          >
            {acceptingPlacements ? 'Confirming…' : `Confirm all ${pendingPlacements.length} placements`}
          </button>
        )}

        <div className="flex items-baseline justify-between mb-2">
          <h3 className="text-stone-200 font-semibold text-[15px]">Insights</h3>
          <button
            onClick={() => regenerateInsights(a)}
            disabled={regenerating || claimsLoading}
            className="min-h-[44px] px-3 rounded-xl text-stone-400 text-sm underline underline-offset-4 disabled:opacity-40"
          >
            {regenerating ? 'Re-reading…' : 'Re-read for insights'}
          </button>
        </div>
        <p className="text-stone-500 text-sm mb-3">
          One specific moment, one claim about what it suggests — each with other ways to read it.
        </p>
        {claimsLoading && <p className="text-stone-500 text-sm mb-3">Reading the conversation…</p>}
        {!claimsLoading && groups.length === 0 && (
          <p className="text-stone-500 text-sm mb-4">
            No specific insights found — the conversation may not have had contestable moments.
          </p>
        )}
        {groups.map((g) => (
          <ClaimCard
            key={g.insight.id}
            agentId={a.id}
            claim={g.insight}
            alternatives={g.alternatives}
            onResolved={onClaimResolved}
          />
        ))}

        {error && <p className="text-red-300 text-sm mb-3">{error}</p>}

        {/* Project mining cards removed — use "Pull tasks & stuff" above for conversational mining */}

        {isPending && (
          <div className="mt-2 mb-6">
            <button
              onClick={() => finishReview(a, acceptedMined)}
              disabled={!finishable || busy}
              className="min-h-[44px] px-5 rounded-xl bg-yellow-500/90 text-stone-900 font-semibold text-[15px] disabled:opacity-40"
            >
              Done — file it
            </button>
            {!finishable && left.length > 0 && (
              <p className="text-stone-500 text-sm mt-2">Still to do: {left.join(' · ')}</p>
            )}
            {finishable && (
              <p className="text-stone-500 text-sm mt-2">Everything's resolved — filing moves it out of the queue. Accepted projects are created first.</p>
            )}
            <div className="mt-3">
              <button onClick={() => confirmAgent(a.id, false)} disabled={busy} className="min-h-[44px] px-4 rounded-xl text-stone-500 text-[15px] disabled:opacity-40">
                Archive
              </button>
            </div>
          </div>
        )}
      </div>
    )
  }

  const queueLabel =
    agents.length === 0 ? 'Nothing waiting for review.' : `${agents.length} conversation${agents.length === 1 ? '' : 's'} to review.`

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-y-auto p-4 max-w-2xl mx-auto w-full">
      <h2 className="text-xl font-bold text-stone-100 mb-1">Review queue</h2>
      <p className="text-stone-400 text-sm mb-4">{queueLabel} Nothing trains until you accept it.</p>
      {loading && <p className="text-stone-500 text-sm">Loading…</p>}
      {error && <p className="text-red-300 text-sm mb-3">{error}</p>}
      <div className="space-y-2 mb-8">
        {agents.map((a) => (
          <button
            key={a.id}
            onClick={() => select(a)}
            className="w-full text-left rounded-2xl border border-stone-700 bg-stone-800/60 p-4 min-h-[44px]"
          >
            <span className="block text-stone-100 font-semibold text-[15px]">{a.name}</span>
            <span className="block text-stone-500 text-sm mt-0.5">
              {a.sort ? strandName(a.sort.primary_strand) : 'unsorted'} · {new Date(a.created_at).toLocaleDateString()}
            </span>
          </button>
        ))}
      </div>

      <h2 className="text-xl font-bold text-stone-100 mb-1">Reviewed</h2>
      <p className="text-stone-400 text-sm mb-4">
        {reviewed.length === 0 ? 'Nothing reviewed yet.' : 'Filed agents — you can still mine projects from them.'}
      </p>
      <div className="space-y-2">
        {reviewed.map((a) => (
          <button
            key={a.id}
            onClick={() => select(a)}
            className="w-full text-left rounded-2xl border border-stone-800 bg-stone-900/60 p-4 min-h-[44px]"
          >
            <span className="block text-stone-200 font-semibold text-[15px]">{a.name}</span>
            <span className="block text-stone-500 text-sm mt-0.5">
              {new Date(a.created_at).toLocaleDateString()} · {miningStatusLabel((a.mining_state as MiningState) || 'pending')}
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}
