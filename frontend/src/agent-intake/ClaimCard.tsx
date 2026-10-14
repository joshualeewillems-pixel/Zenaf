import { useState } from 'react'
import { apiBase } from '../apiBase'

export type Claim = {
  id: string
  claim_type: string
  title: string
  evidence: string
  inference: string
  detail: string
  status: string
  user_note: string
}

type Props = {
  agentId: string
  claim: Claim
  onResolved: (claim: Claim) => void
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

const TYPE_LABEL: Record<string, string> = {
  strand: 'Strand',
  kind: 'Kind',
  initiative: 'Initiative',
  project: 'Project',
  task: 'Task',
  idea: 'Idea',
}

export default function ClaimCard({ agentId, claim, onResolved }: Props) {
  const [mode, setMode] = useState<'idle' | 'correct' | 'explain'>('idle')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function act(action: 'accept' | 'correct' | 'explain') {
    setBusy(true)
    setError('')
    try {
      const opts: RequestInit =
        action === 'accept'
          ? { method: 'POST' }
          : { method: 'POST', body: JSON.stringify({ note: note.trim() }) }
      const updated = await api(`/agents/${agentId}/claims/${claim.id}/${action}`, opts)
      setMode('idle')
      setNote('')
      onResolved(updated)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed')
    } finally {
      setBusy(false)
    }
  }

  const resolved = claim.status !== 'pending'
  const statusLabel =
    claim.status === 'accepted' ? 'Accepted' : claim.status === 'corrected' ? 'Corrected' : claim.status === 'explained' ? 'Explained' : ''

  return (
    <div className="rounded-2xl border border-stone-700 bg-stone-800/60 p-4 mb-3">
      <p className="text-stone-500 text-xs uppercase tracking-wide mb-2">
        {TYPE_LABEL[claim.claim_type] || claim.claim_type} · {claim.title}
      </p>

      {claim.evidence && (
        <blockquote className="border-l-2 border-yellow-500/60 pl-3 mb-3">
          <p className="text-stone-300 text-[15px] leading-relaxed whitespace-pre-wrap">“{claim.evidence}”</p>
          <p className="text-stone-500 text-xs mt-1">from the conversation</p>
        </blockquote>
      )}

      <p className="text-stone-100 text-[15px] leading-relaxed mb-1">{claim.inference}</p>
      {claim.detail && <p className="text-stone-500 text-sm mb-3">{claim.detail}</p>}

      {resolved ? (
        <div className="mt-2">
          <p className="text-yellow-500/90 text-sm font-semibold">✓ {statusLabel}</p>
          {claim.user_note && (
            <p className="text-stone-400 text-sm mt-1 whitespace-pre-wrap">“{claim.user_note}”</p>
          )}
        </div>
      ) : (
        <div className="mt-3">
          <p className="text-stone-300 text-[15px] mb-2">Is that right? Want to say more about why?</p>
          {error && <p className="text-red-300 text-sm mb-2">{error}</p>}

          {mode === 'idle' ? (
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => act('accept')}
                disabled={busy}
                className="min-h-[44px] px-5 rounded-xl bg-yellow-500/90 text-stone-900 font-semibold text-[15px] disabled:opacity-40"
              >
                Accept
              </button>
              <button
                onClick={() => setMode('correct')}
                disabled={busy}
                className="min-h-[44px] px-5 rounded-xl bg-stone-700 text-stone-100 font-semibold text-[15px] disabled:opacity-40"
              >
                Correct
              </button>
              <button
                onClick={() => setMode('explain')}
                disabled={busy}
                className="min-h-[44px] px-5 rounded-xl bg-stone-700 text-stone-100 font-semibold text-[15px] disabled:opacity-40"
              >
                Explain
              </button>
            </div>
          ) : (
            <div>
              <p className="text-stone-400 text-sm mb-2">
                {mode === 'correct'
                  ? 'What should it say instead? Your correction trains the sorter.'
                  : 'Why did you make that call? Your reasoning becomes training signal.'}
              </p>
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                rows={3}
                placeholder={mode === 'correct' ? 'It should be…' : 'I chose this because…'}
                className="w-full min-h-[44px] px-3 py-2.5 rounded-xl bg-stone-900 text-stone-100 text-[15px] border border-stone-700 focus:border-yellow-500/60 outline-none resize-y mb-2"
              />
              <div className="flex gap-2">
                <button
                  onClick={() => act(mode)}
                  disabled={busy || !note.trim()}
                  className="min-h-[44px] px-5 rounded-xl bg-yellow-500/90 text-stone-900 font-semibold text-[15px] disabled:opacity-40"
                >
                  {mode === 'correct' ? 'Submit correction' : 'Save explanation'}
                </button>
                <button
                  onClick={() => { setMode('idle'); setNote('') }}
                  className="min-h-[44px] px-4 rounded-xl text-stone-400 text-[15px]"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
