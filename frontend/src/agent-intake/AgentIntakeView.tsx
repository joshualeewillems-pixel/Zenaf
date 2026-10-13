import { useEffect, useRef, useState } from 'react'
import { apiBase } from '../apiBase'

type Phase =
  | { kind: 'idle' }
  | { kind: 'submitting' }
  | { kind: 'pending_render'; jobId: string; jobStatus: string; url: string }
  | { kind: 'done'; agentName: string; primaryStrand: string }
  | { kind: 'error'; message: string }

const INSTALL_URL = `${apiBase()}/agents/bookmarklet/install`

function isIOS(): boolean {
  if (typeof navigator === 'undefined') return false
  return /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
}

export default function AgentIntakeView() {
  const [mode, setMode] = useState<'link' | 'paste'>('link')
  const [url, setUrl] = useState('')
  const [text, setText] = useState('')
  const [phase, setPhase] = useState<Phase>({ kind: 'idle' })
  const pollRef = useRef<number | null>(null)
  const ios = isIOS()

  useEffect(() => () => { if (pollRef.current) window.clearInterval(pollRef.current) }, [])

  async function pollJob(jobId: string, submittedUrl: string) {
    try {
      const r = await fetch(`${apiBase()}/agents/render-jobs/${jobId}`)
      if (!r.ok) return
      const j = await r.json()
      if (j.status === 'claimed') {
        setPhase({ kind: 'pending_render', jobId, jobStatus: 'claimed', url: submittedUrl })
      } else if (j.status === 'failed' || j.status === 'expired') {
        if (pollRef.current) window.clearInterval(pollRef.current)
        setPhase({ kind: 'error', message: `Rendering ${j.status}. Try again, or paste the text instead.` })
      } else if (j.status === 'completed') {
        if (pollRef.current) window.clearInterval(pollRef.current)
        setPhase({ kind: 'done', agentName: j.title || 'agent', primaryStrand: '' })
      }
    } catch { /* keep polling */ }
  }

  function handleDone(data: any) {
    setPhase({
      kind: 'done',
      agentName: data.name || data.title || 'agent',
      primaryStrand: data.sort?.primary_strand || '',
    })
  }

  async function submitLink() {
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
        setPhase({ kind: 'pending_render', jobId: data.job_id, jobStatus: 'pending', url: u })
        if (pollRef.current) window.clearInterval(pollRef.current)
        pollRef.current = window.setInterval(() => pollJob(data.job_id, u), 5000)
        pollJob(data.job_id, u)
      } else if (data.status === 'connected') {
        handleDone(data)
      } else {
        throw new Error('Unexpected response')
      }
    } catch (e) {
      setPhase({ kind: 'error', message: e instanceof Error ? e.message : 'Something went wrong' })
    }
  }

  async function submitText() {
    const t = text.trim()
    if (!t) return
    setPhase({ kind: 'submitting' })
    try {
      const r = await fetch(`${apiBase()}/agents/connect/share-text`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: url.trim() || 'pasted-text', transcript: t }),
      })
      const data = await r.json()
      if (!r.ok) throw new Error(data.detail || 'Request failed')
      handleDone(data)
    } catch (e) {
      setPhase({ kind: 'error', message: e instanceof Error ? e.message : 'Something went wrong' })
    }
  }

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-y-auto p-4 max-w-2xl mx-auto w-full">
      <h2 className="text-xl font-bold text-stone-100 mb-1">Connect an agent</h2>
      <p className="text-stone-400 text-sm mb-4">
        Bring in a ChatGPT or Claude conversation. Zenaf sorts it into your seven strands and pulls out your projects.
      </p>

      <div className="flex gap-2 mb-4">
        {(['link', 'paste'] as const).map((m) => (
          <button
            key={m}
            onClick={() => { setMode(m); setPhase({ kind: 'idle' }) }}
            className={`min-h-[44px] px-4 rounded-xl text-[15px] font-semibold ${
              mode === m ? 'bg-stone-700 text-stone-100' : 'text-stone-400'
            }`}
          >
            {m === 'link' ? 'Paste link' : 'Paste text'}
          </button>
        ))}
      </div>

      {mode === 'link' ? (
        <div className="flex gap-2 mb-6">
          <input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://chatgpt.com/share/…"
            className="flex-1 min-h-[44px] px-3 rounded-xl bg-stone-800 text-stone-100 text-[15px] border border-stone-700 focus:border-yellow-500/60 outline-none"
            inputMode="url"
          />
          <button
            onClick={submitLink}
            disabled={phase.kind === 'submitting' || !url.trim()}
            className="min-h-[44px] px-5 rounded-xl bg-yellow-500/90 text-stone-900 font-semibold text-[15px] disabled:opacity-40"
          >
            {phase.kind === 'submitting' ? '…' : 'Connect'}
          </button>
        </div>
      ) : (
        <div className="mb-6">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Select all in the conversation, copy, and paste it here…"
            rows={8}
            className="w-full min-h-[160px] p-3 rounded-xl bg-stone-800 text-stone-100 text-[15px] border border-stone-700 focus:border-yellow-500/60 outline-none mb-2"
          />
          <button
            onClick={submitText}
            disabled={phase.kind === 'submitting' || !text.trim()}
            className="min-h-[44px] px-5 rounded-xl bg-yellow-500/90 text-stone-900 font-semibold text-[15px] disabled:opacity-40"
          >
            {phase.kind === 'submitting' ? '…' : 'Connect'}
          </button>
        </div>
      )}

      {phase.kind === 'pending_render' && (
        <div className="rounded-2xl border border-stone-700 bg-stone-800/60 p-4 mb-4">
          {ios ? (
            <>
              <h3 className="font-semibold text-stone-100 mb-2">Almost there</h3>
              <p className="text-stone-400 text-sm mb-3">
                Zenaf can't read that page from its server, but your iPhone can.
                Open the conversation, then send it over:
              </p>
              <ol className="text-stone-300 text-sm list-decimal ml-5 space-y-2 mb-4">
                <li>
                  <a
                    href={phase.url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-block min-h-[44px] px-5 py-2.5 rounded-xl bg-yellow-500/90 text-stone-900 font-semibold text-[15px]"
                  >
                    Open the conversation
                  </a>
                </li>
                <li>Tap <b>Share → Send to Zenaf</b> <span className="text-stone-500">(one-time Shortcut setup below)</span></li>
                <li>Come back here — the agent appears automatically.</li>
              </ol>
              <a href={INSTALL_URL} className="text-stone-300 text-sm underline">
                Set up the Send to Zenaf Shortcut (once, ~5 min)
              </a>
              {phase.jobStatus === 'claimed' && (
                <p className="text-yellow-500/90 text-sm mt-3">Reading the page now…</p>
              )}
            </>
          ) : (
            <>
              <h3 className="font-semibold text-stone-100 mb-2">
                {phase.jobStatus === 'claimed' ? 'Reading your conversation…' : 'Waiting for your browser…'}
              </h3>
              <p className="text-stone-400 text-sm mb-3">
                This page needs JavaScript to render, and AI sites block servers from reading them.
                The Zenaf Renderer extension opens it in a background tab and grabs the text automatically.
                {phase.jobStatus !== 'claimed' && ' It hasn\u2019t picked this up yet — is the extension installed?'}
              </p>
              <p className="text-stone-400 text-sm">
                Install it from <code className="bg-stone-900 px-1 rounded">local_ai/agent_intake/extension/</code> in the
                Zenaf repo: <code className="bg-stone-900 px-1 rounded">chrome://extensions</code> → Developer mode → Load unpacked.
                Or skip it and <button className="underline text-stone-300" onClick={() => setMode('paste')}>paste the text instead</button>.
              </p>
            </>
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
