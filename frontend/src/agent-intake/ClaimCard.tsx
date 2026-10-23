import { useState } from 'react'
import { apiBase } from '../apiBase'
import { defaultCardExpanded } from './reviewStages'

export type Claim = {
  id: string
  claim_type: string
  title: string
  evidence: string
  inference: string
  detail: string
  status: string
  user_note: string
  question: string
  scope: string
  turn_ref: string
}

type Props = {
  agentId: string
  claim: Claim
  alternatives?: Claim[]
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
  value_inference: 'Value read',
  decision_pattern: 'Decision pattern',
  stance: 'Stance',
  preference: 'Preference',
  alternative: 'Alternative',
  recurrence: 'Recurrence',
  meeting_impression: 'First impression',
}

const SCOPE_LABEL: Record<string, string> = {
  moment: 'About this moment',
  subject: 'About this topic',
  pattern: 'Possible pattern',
}

const DEFAULT_QUESTION = 'Is that right? Want to say more about why?'

type Action = 'accept' | 'correct' | 'explain' | 'reject' | 'unresolve'

function ResponseButtons({
  onAct,
  busy,
  compact,
}: {
  onAct: (a: Action) => void
  busy: boolean
  compact?: boolean
}) {
  const main = 'min-h-[44px] rounded-xl font-semibold text-[15px] disabled:opacity-40'
  const quiet = 'min-h-[44px] rounded-xl text-[15px] disabled:opacity-40'
  if (compact) {
    return (
      <div className="grid grid-cols-2 gap-2">
        <button onClick={() => onAct('accept')} disabled={busy} className={`${main} px-3 bg-yellow-500/90 text-stone-900`}>
          Confirm
        </button>
        <button onClick={() => onAct('correct')} disabled={busy} className={`${main} px-3 bg-stone-700 text-stone-100`}>
          Qualify
        </button>
        <button onClick={() => onAct('reject')} disabled={busy} className={`${main} px-3 bg-stone-700 text-stone-100`}>
          Reject
        </button>
        <button onClick={() => onAct('unresolve')} disabled={busy} className={`${quiet} px-3 text-stone-400`}>
          Leave unresolved
        </button>
      </div>
    )
  }
  return (
    <div>
      <div className="flex flex-wrap gap-2">
        <button onClick={() => onAct('accept')} disabled={busy} className={`${main} px-5 bg-yellow-500/90 text-stone-900`}>
          Confirm
        </button>
        <button onClick={() => onAct('correct')} disabled={busy} className={`${main} px-5 bg-stone-700 text-stone-100`}>
          Qualify
        </button>
        <button onClick={() => onAct('reject')} disabled={busy} className={`${main} px-5 bg-stone-700 text-stone-100`}>
          Reject
        </button>
      </div>
      <div className="flex flex-wrap gap-2 mt-2">
        <button onClick={() => onAct('unresolve')} disabled={busy} className={`${quiet} px-4 text-stone-400`}>
          Leave unresolved
        </button>
        <button onClick={() => onAct('explain')} disabled={busy} className={`${quiet} px-4 text-stone-400`}>
          Say more about why
        </button>
      </div>
    </div>
  )
}

function ClaimBody({
  agentId,
  claim,
  onResolved,
  compact,
}: {
  agentId: string
  claim: Claim
  onResolved: (c: Claim) => void
  compact?: boolean
}) {
  const [mode, setMode] = useState<'idle' | 'correct' | 'explain'>('idle')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function act(action: Action) {
    if (action === 'correct' || action === 'explain') {
      setMode(action)
      return
    }
    setBusy(true)
    setError('')
    try {
      const updated = await api(`/agents/${agentId}/claims/${claim.id}/${action}`, { method: 'POST' })
      onResolved(updated)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed')
    } finally {
      setBusy(false)
    }
  }

  async function submitNote() {
    setBusy(true)
    setError('')
    try {
      const updated = await api(`/agents/${agentId}/claims/${claim.id}/${mode}`, {
        method: 'POST',
        body: JSON.stringify({ note: note.trim() }),
      })
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
    claim.status === 'accepted'
      ? 'Confirmed'
      : claim.status === 'corrected'
        ? 'Qualified'
        : claim.status === 'explained'
          ? 'Explained'
          : claim.status === 'rejected'
            ? 'Rejected'
            : claim.status === 'unresolved'
              ? 'Left unresolved'
              : ''

  return (
    <div>
      {/* 1. Evidence — verbatim quote + turn ref */}
      {claim.evidence && (
        <blockquote className="border-l-2 border-yellow-500/60 pl-3 mb-3">
          <p className="text-stone-300 text-[15px] leading-relaxed whitespace-pre-wrap">“{claim.evidence}”</p>
          <p className="text-stone-500 text-xs mt-1">
            from the conversation{claim.turn_ref ? ` · ${claim.turn_ref}` : ''}
          </p>
        </blockquote>
      )}

      {/* 2. Interpretation — one specific claim */}
      <p className="text-stone-100 text-[15px] leading-relaxed mb-1">{claim.inference}</p>
      {claim.detail && !claim.turn_ref && <p className="text-stone-500 text-sm mb-3 whitespace-pre-wrap">{claim.detail}</p>}

      {/* 5. Your response */}
      {resolved ? (
        <div className="mt-2">
          <p className="text-yellow-500/90 text-sm font-semibold">✓ {statusLabel}</p>
          {claim.user_note && (
            <p className="text-stone-400 text-sm mt-1 whitespace-pre-wrap">“{claim.user_note}”</p>
          )}
        </div>
      ) : (
        <div className="mt-3">
          <p className="text-stone-300 text-[15px] mb-2">{claim.question || DEFAULT_QUESTION}</p>
          {error && <p className="text-red-300 text-sm mb-2">{error}</p>}

          {mode === 'idle' ? (
            <ResponseButtons onAct={act} busy={busy} compact={compact} />
          ) : (
            <div>
              <p className="text-stone-400 text-sm mb-2">
                {mode === 'correct'
                  ? 'How would you qualify it? Your refinement teaches the system.'
                  : 'Why did you make that call? Your reasoning becomes training signal.'}
              </p>
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                rows={3}
                placeholder={mode === 'correct' ? 'More precisely…' : 'I chose this because…'}
                className="w-full min-h-[44px] px-3 py-2.5 rounded-xl bg-stone-900 text-stone-100 text-[15px] border border-stone-700 focus:border-yellow-500/60 outline-none resize-y mb-2"
              />
              <div className="flex gap-2">
                <button
                  onClick={submitNote}
                  disabled={busy || !note.trim()}
                  className="min-h-[44px] px-5 rounded-xl bg-yellow-500/90 text-stone-900 font-semibold text-[15px] disabled:opacity-40"
                >
                  {mode === 'correct' ? 'Submit qualification' : 'Save explanation'}
                </button>
                <button
                  onClick={() => {
                    setMode('idle')
                    setNote('')
                  }}
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

export default function ClaimCard({ agentId, claim, alternatives, onResolved }: Props) {
  // Accordion: pending cards start open (action needed); resolved cards start
  // collapsed to save vertical space. Header always shows claim + scope.
  const [expanded, setExpanded] = useState(() => defaultCardExpanded(claim.status))
  const scopeLabel = SCOPE_LABEL[claim.scope] || SCOPE_LABEL.moment

  return (
    <div className="rounded-2xl border border-stone-700 bg-stone-800/60 mb-3 overflow-hidden">
      <button
        onClick={() => setExpanded((e) => !e)}
        aria-expanded={expanded}
        className="w-full text-left p-4 min-h-[44px] flex items-start gap-2"
      >
        <span className="flex-1 min-w-0">
          <span className="block text-stone-500 text-xs uppercase tracking-wide mb-1">
            {TYPE_LABEL[claim.claim_type] || claim.claim_type} · {claim.title}
          </span>
          <span className="block text-stone-200 text-[15px] leading-snug">{claim.inference}</span>
          <span className="inline-block text-xs font-medium text-stone-400 bg-stone-700/60 rounded-full px-2.5 py-1 mt-2">
            {scopeLabel}
          </span>
          {claim.status !== 'pending' && (
            <span className="inline-block text-xs font-medium text-yellow-500/90 ml-2">
              ✓ {claim.status === 'accepted' ? 'Confirmed' : claim.status === 'corrected' ? 'Qualified' : claim.status === 'explained' ? 'Explained' : claim.status === 'rejected' ? 'Rejected' : 'Left unresolved'}
            </span>
          )}
        </span>
        <span className="text-stone-500 text-lg leading-none mt-1 shrink-0" aria-hidden>
          {expanded ? '▾' : '▸'}
        </span>
      </button>

      {expanded && (
        <div className="px-4 pb-4">
          <ClaimBody agentId={agentId} claim={claim} onResolved={onResolved} />

          {/* 3. Alternatives — shown explicitly, each individually respondable.
              Confirming the interpretation never touches these. */}
          {alternatives && alternatives.length > 0 && (
            <div className="mt-4 pt-3 border-t border-stone-700/60">
              <p className="text-stone-400 text-sm font-medium mb-2">Other ways to read it</p>
              {alternatives.map((alt) => (
                <div key={alt.id} className="rounded-xl bg-stone-900/60 p-3 mb-2">
                  <p className="text-stone-500 text-xs uppercase tracking-wide mb-1.5">
                    {TYPE_LABEL[alt.claim_type] || alt.claim_type}
                  </p>
                  <ClaimBody agentId={agentId} claim={alt} onResolved={onResolved} compact />
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
