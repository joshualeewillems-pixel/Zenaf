import { useEffect, useRef, useState } from 'react'
import { apiBase } from '../apiBase'

type Phase =
  | { kind: 'idle' }
  | { kind: 'submitting' }
  | { kind: 'pending_render'; jobId: string; jobStatus: string; pendingCount: number }
  | { kind: 'done'; agentName: string; primaryStrand: string; projectCount: number }
  | { kind: 'error'; message: string }

const INSTALL_URL = `${apiBase()}/agents/bookmarklet/install`

function isIOS(): boolean {
  if (typeof navigator === 'undefined') return false
  return /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
}

export default function AgentIntakeView() {
  const [url, setUrl] = useState('')
  const [phase, setPhase] = useState<Phase>({ kind: 'idle' })
  const pollRef = useRef<number | null>(null)
  const ios = isIOS()

  useEffect(() => () => { if (pollRef.current) window.clearInterval(pollRef.current) }, [])

  async function pollJob(jobId: string) {
    try {
      const r = await fetch(`${apiBase()}/agents/render-jobs/${jobId}`)
      if (!r.ok) return
      const j = await r.json()
      if (j.status === 'claimed') {
        setPhase({ kind: 'pending_render', jobId, jobStatus: 'claimed', pendingCount: j.pending_count ?? 0 })
      } else if (j.status === 'failed' || j.status === 'expired') {
        if (pollRef.current) window.clearInterval(pollRef.current)
        setPhase({ kind: 'error', message: `Rendering ${j.status}. Try again or install a renderer below.` })
      }
      // completed is handled by the renderer's complete call returning the agent;
      // but if the user completed it elsewhere, we just note it.
      else if (j.status === 'completed') {
        if (pollRef.current) window.clearInterval(pollRef.current)
        setPhase({ kind: 'done', agentName: j.title || 'agent', primaryStrand: '', projectCount: 0 })
      }
    } catch { /* keep polling */ }
  }

  async function submit() {
    const u = url.trim()
    if (!u) return
    setPhase({ kind: 'submitting' })
    try {
      const r = await fetch(`${apiBase()}/agents/connect/share-link`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: u }),
      })
      const data = await r.json()
      if (!r.ok) throw new Error(data.detail || 'Request failed')
      if (data.status === 'pending_render') {
        setPhase({ kind: 'pending_render', jobId: data.job_id, jobStatus: 'pending', pendingCount: 0 })
        if (pollRef.current) window.clearInterval(pollRef.current)
        pollRef.current = window.setInterval(() => pollJob(data.job_id), 5000)
        pollJob(data.job_id)
      } else if (data.status === 'connected') {
        setPhase({
          kind: 'done',
          agentName: data.name || 'agent',
          primaryStrand: data.sort?.primary_strand || '',
          projectCount: 0,
        })
      } else {
        throw new Error('Unexpected response')
      }
    } catch (e) {
      setPhase({ kind: 'error', message: e instanceof Error ? e.message : 'Something went wrong' })
    }
  }

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-y-auto p-4 max-w-2xl mx-auto w-full">
      <h2 className="text-xl font-bold text-stone-100 mb-1">Connect an agent</h2>
      <p className="text-stone-400 text-sm mb-4">
        Paste a ChatGPT or Claude conversation link. Zenaf reads it, sorts it into your seven strands, and pulls out your projects.
      </p>

      <div className="flex gap-2 mb-6">
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://chatgpt.com/share/…"
          className="flex-1 min-h-[44px] px-3 rounded-xl bg-stone-800 text-stone-100 text-[15px] border border-stone-700 focus:border-yellow-500/60 outline-none"
          inputMode="url"
        />
        <button
          onClick={submit}
          disabled={phase.kind === 'submitting' || !url.trim()}
          className="min-h-[44px] px-5 rounded-xl bg-yellow-500/90 text-stone-900 font-semibold text-[15px] disabled:opacity-40"
        >
          {phase.kind === 'submitting' ? '…' : 'Connect'}
        </button>
      </div>

      {phase.kind === 'pending_render' && (
        <div className="rounded-2xl border border-stone-700 bg-stone-800/60 p-4 mb-4">
          <h3 className="font-semibold text-stone-100 mb-2">
            {phase.jobStatus === 'claimed' ? 'Rendering your conversation…' : 'Waiting for a renderer…'}
          </h3>
          <p className="text-stone-400 text-sm mb-3">
            This page needs JavaScript to render, and AI sites block servers from reading them.
            So Zenaf asks <em>your</em> browser to render it — the one place it always works.
            {phase.jobStatus !== 'claimed' && ' No renderer has picked this up yet.'}
          </p>

          {ios ? (
            <div>
              <p className="text-stone-200 text-sm font-semibold mb-1">On your iPhone:</p>
              <ol className="text-stone-300 text-sm list-decimal ml-5 space-y-1 mb-3">
                <li>Install the <b>Send to Zenaf</b> Shortcut (one-time, ~5 min).</li>
                <li>Open the conversation in Safari, tap <b>Share → Send to Zenaf</b>.</li>
                <li>Come back here — the agent appears below automatically.</li>
              </ol>
              <a
                href={INSTALL_URL}
                className="inline-block min-h-[44px] px-5 py-2.5 rounded-xl bg-stone-700 text-stone-100 font-semibold text-[15px]"
              >
                Set up the iPhone Shortcut
              </a>
            </div>
          ) : (
            <div>
              <p className="text-stone-200 text-sm font-semibold mb-1">On desktop:</p>
              <p className="text-stone-300 text-sm mb-3">
                Install the <b>Zenaf Renderer</b> extension — it picks up render jobs automatically
                in a background tab. Nothing to tap per conversation.
              </p>
              <p className="text-stone-400 text-sm">
                Extension source ships with Zenaf at <code className="bg-stone-900 px-1 rounded">local_ai/agent_intake/extension/</code> —
                load it via <code className="bg-stone-900 px-1 rounded">chrome://extensions</code> → Developer mode → Load unpacked.
              </p>
            </div>
          )}

          {phase.jobStatus === 'claimed' && (
            <p className="text-yellow-500/90 text-sm mt-3">A renderer is reading the page now…</p>
          )}
        </div>
      )}

      {phase.kind === 'done' && (
        <div className="rounded-2xl border border-green-800 bg-green-950/40 p-4 mb-4">
          <h3 className="font-semibold text-green-200 mb-1">Connected: {phase.agentName}</h3>
          <p className="text-stone-300 text-sm">
            {phase.primaryStrand ? <>Primary strand: <b>{phase.primaryStrand}</b>. </> : null}
            It's in your review queue — open it to accept, correct, or mine it for projects.
          </p>
        </div>
      )}

      {phase.kind === 'error' && (
        <div className="rounded-2xl border border-red-800 bg-red-950/40 p-4 mb-4">
          <p className="text-red-200 text-sm">{phase.message}</p>
          <button onClick={() => setPhase({ kind: 'idle' })} className="mt-2 text-stone-300 text-sm underline">
            Try again
          </button>
        </div>
      )}
    </div>
  )
}
