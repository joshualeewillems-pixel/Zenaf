import { useState } from 'react'
import { apiBase } from '../apiBase'
import CouncilChat from '../chat/CouncilChat'

/**
 * Foundation tab voice console — Joshua's 2026-10-16 concept.
 *
 * Re-skinned onto the unified CouncilChat (environment="workspace"): the old
 * two-row voice card grid is now the shared SeatChips row (depth rides on
 * each chip), and the trained/base toggle lives in the chat. The conversation
 * is the same persistent 1:1 thread as the tree's Talk sheets — one voice at
 * a time, tap a chip to branch.
 *
 * Still hosts the demo claim-code entry: "continue the conversation" —
 * a landing-demo transcript pulled into the intake pipeline.
 */
export default function VoiceConsole() {
  const base = apiBase()
  const [claimCode, setClaimCode] = useState('')
  const [claimMsg, setClaimMsg] = useState<string | null>(null)
  const [claiming, setClaiming] = useState(false)

  const claim = async () => {
    const code = claimCode.trim().toUpperCase()
    if (!code || claiming) return
    setClaiming(true)
    setClaimMsg(null)
    try {
      // 1. Pull the demo transcript into this account.
      const rc = await fetch(`${base}/demo/claim`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ claim_code: code }),
      })
      if (!rc.ok) throw new Error(rc.status === 404 ? 'not-found' : `HTTP ${rc.status}`)
      const { transcript } = await rc.json()
      // 2. Run it through the standard intake pipeline (same as the bookmarklet).
      const rs = await fetch(`${base}/agents/connect/share-text`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: 'zenaf.ai/demo',
          transcript,
          title: 'Landing demo conversation',
          name: 'Landing demo conversation',
        }),
      })
      if (!rs.ok) throw new Error(`intake HTTP ${rs.status}`)
      setClaimMsg('Continued — your demo conversation is now in the review queue.')
      setClaimCode('')
    } catch (e: any) {
      setClaimMsg(
        e?.message === 'not-found'
          ? "That code didn't match anything — check it and try again."
          : 'Something went wrong pulling that conversation in. Try again.',
      )
    } finally {
      setClaiming(false)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <CouncilChat environment="workspace" />

      {/* Claim code — "continue the conversation" */}
      <div className="rounded-xl border border-dashed border-stone-700 p-3">
        <div className="text-xs font-semibold text-stone-400 uppercase tracking-wide mb-1">
          Continue the conversation
        </div>
        <p className="text-xs text-stone-500 mb-2">
          Talked to the voices on zenaf.ai? Enter your conversation code to pull it into your review queue.
        </p>
        <div className="flex gap-2">
          <input
            value={claimCode}
            onChange={(e) => setClaimCode(e.target.value.toUpperCase().replace(/[^A-Z2-9]/g, '').slice(0, 12))}
            placeholder="ABC123"
            maxLength={12}
            className="flex-1 min-w-0 bg-stone-950 border border-stone-700 rounded-lg px-3 py-2.5 text-sm tracking-[0.2em] text-stone-200 outline-none focus:border-amber-500/60 uppercase"
          />
          <button
            onClick={claim}
            disabled={claiming || !claimCode.trim()}
            className="min-h-[44px] px-4 rounded-lg border border-amber-500/50 text-amber-400 text-sm disabled:opacity-40"
          >
            {claiming ? '…' : 'Claim'}
          </button>
        </div>
        {claimMsg && <div className="text-xs text-stone-400 mt-2">{claimMsg}</div>}
      </div>
    </div>
  )
}
