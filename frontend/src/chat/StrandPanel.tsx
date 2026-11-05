/**
 * Weaver strand interview panel (rev2, as accepted).
 *
 * Root (strand) tap opens a conversation with the WEAVER in the bottom
 * panel about source materials relevant to that strand. Conversation-
 * first: the thread resolves immediately — no upload prerequisite, no
 * model call on open (T1b). The opening orientation is a panel header,
 * never a message: a generated Weaver turn present on open, before any
 * user turn, would fail T1b.
 *
 * One question at a time, reciprocal contribution, continuity without
 * pressure. Uploads are optional and live BELOW the conversation:
 * pasted text (redacted at capture) or an uploaded file linked to the
 * strand. Explicit topic boundaries ("never ask me about this") are
 * listed here and can be reopened.
 *
 * The panel is a thin client over the strand endpoints: the server
 * owns strand identity, the mapping, validation, and redaction. This
 * component never invents a conversation id — on a failed resolve it
 * shows the error and a retry, never a fabricated thread.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { apiBase } from '../apiBase'
import CouncilChat from './CouncilChat'
import type { DesignStrandKey } from '../living-tree/strands'

export type StrandBoundary = {
  id: string
  topic: string
  created_at: string
}

export type StrandSource = {
  id: string
  kind: 'paste' | 'file'
  ref: string
  label: string
  excerpt: string
  created_at: string
}

export type StrandResolve = {
  strand_key: DesignStrandKey
  strand_name: string
  definition: string
  conversation_id: string
  is_fresh: boolean
  orientation: {
    strand_key: DesignStrandKey
    strand_name: string
    definition: string
    tagline: string
    is_fresh: boolean
    invitation: string
    opening_question: string | null
    resume: boolean | null
  }
  boundaries: StrandBoundary[]
  sources: StrandSource[]
}

async function readError(r: Response): Promise<string> {
  try {
    const j = await r.json()
    if (typeof j?.detail === 'string' && j.detail.trim()) return j.detail
  } catch {
    /* fall through to the status text */
  }
  return r.statusText || `Request failed (${r.status})`
}

export default function StrandPanel({
  strandKey,
  onClose,
}: {
  strandKey: DesignStrandKey
  onClose: () => void
}) {
  const base = apiBase()
  const [resolved, setResolved] = useState<StrandResolve | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [pasteText, setPasteText] = useState('')
  const [pasteBusy, setPasteBusy] = useState(false)
  const [uploadBusy, setUploadBusy] = useState(false)
  const [sourceError, setSourceError] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement | null>(null)

  const resolve = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const r = await fetch(`${base}/conversation/strand/${strandKey}`, {
        credentials: 'include',
      })
      if (!r.ok) throw new Error(await readError(r))
      const payload = (await r.json()) as StrandResolve
      setResolved(payload)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not open this strand.')
      setResolved(null)
    } finally {
      setLoading(false)
    }
  }, [base, strandKey])

  useEffect(() => {
    void resolve()
  }, [resolve])

  const refreshLists = useCallback(async () => {
    // Re-resolve for fresh boundaries/sources; the mapping is stable
    // and resolve makes no model call, so this is cheap and safe.
    try {
      const r = await fetch(`${base}/conversation/strand/${strandKey}`, {
        credentials: 'include',
      })
      if (!r.ok) return
      setResolved((await r.json()) as StrandResolve)
    } catch {
      /* keep the current lists on a failed refresh */
    }
  }, [base, strandKey])

  const linkPaste = async () => {
    const text = pasteText.trim()
    if (!text || pasteBusy) return
    setPasteBusy(true)
    setSourceError(null)
    try {
      const r = await fetch(`${base}/conversation/strand/${strandKey}/sources`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kind: 'paste', text, label: 'Pasted text' }),
      })
      if (!r.ok) throw new Error(await readError(r))
      setPasteText('')
      await refreshLists()
    } catch (e) {
      setSourceError(e instanceof Error ? e.message : 'Could not link the pasted text.')
    } finally {
      setPasteBusy(false)
    }
  }

  const linkFile = async (file: File) => {
    if (uploadBusy) return
    setUploadBusy(true)
    setSourceError(null)
    try {
      const form = new FormData()
      form.append('file', file)
      const up = await fetch(`${base}/ingest/upload`, {
        method: 'POST',
        credentials: 'include',
        body: form,
      })
      if (!up.ok) throw new Error(await readError(up))
      const session = (await up.json()) as { session_id?: string; file_name?: string }
      if (!session.session_id) throw new Error('Upload returned no session.')
      const link = await fetch(`${base}/conversation/strand/${strandKey}/sources`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          kind: 'file',
          ingest_session_id: session.session_id,
          label: session.file_name ?? file.name,
        }),
      })
      if (!link.ok) throw new Error(await readError(link))
      await refreshLists()
    } catch (e) {
      setSourceError(e instanceof Error ? e.message : 'Could not link the file.')
    } finally {
      setUploadBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const reopenBoundary = async (boundaryId: string) => {
    try {
      const r = await fetch(
        `${base}/conversation/strand/${strandKey}/boundaries/${boundaryId}`,
        { method: 'DELETE', credentials: 'include' },
      )
      if (!r.ok) throw new Error(await readError(r))
      setResolved((cur) =>
        cur ? { ...cur, boundaries: cur.boundaries.filter((b) => b.id !== boundaryId) } : cur,
      )
    } catch (e) {
      setSourceError(e instanceof Error ? e.message : 'Could not reopen that topic.')
    }
  }

  if (loading) {
    return (
      <div>
        <p className="lsub">Opening your conversation with Weaver…</p>
      </div>
    )
  }

  if (error || !resolved) {
    return (
      <div>
        <h3>Weaver</h3>
        <p className="lsub">{error ?? 'Could not open this strand.'}</p>
        <button type="button" className="lcta" onClick={() => void resolve()}>
          Try again ›
        </button>
        <button type="button" className="lcta" onClick={onClose}>
          Close
        </button>
      </div>
    )
  }

  const orientation = resolved.orientation
  return (
    <div>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3>
            {resolved.strand_name} — with Weaver
          </h3>
          <div className="ltag">{resolved.definition}</div>
        </div>
        <button
          type="button"
          aria-label="Close strand conversation"
          onClick={onClose}
          className="min-h-[44px] min-w-[44px] text-stone-400"
        >
          ✕
        </button>
      </div>

      {/* Orientation header — pattern copy, not a message. The first
          generated Weaver question arrives through the Talk path once
          the user sends a message; nothing here generates. */}
      <p className="lsub">{orientation.invitation}</p>
      {orientation.opening_question && (
        <p>“{orientation.opening_question}”</p>
      )}

      <CouncilChat
        environment="sheet"
        initialArchetypeId="conductor"
        lockArchetypeId="conductor"
        displayName="Weaver"
        conversationId={resolved.conversation_id}
        context={{ strand_key: resolved.strand_key }}
      />

      {/* Optional sources, below the conversation. Uploads are never a
          prerequisite: the conversation is already open above. */}
      <div className="mt-4">
        <h4 className="text-sm font-medium text-stone-300">Sources for this strand</h4>
        <p className="lsub">
          Optional. Paste text or upload a file Weaver can draw on — redacted
          at capture, linked to this strand only.
        </p>
        <textarea
          value={pasteText}
          onChange={(e) => setPasteText(e.target.value)}
          placeholder="Paste something Weaver can learn from — a note, a passage, a list…"
          rows={3}
          className="w-full rounded border border-stone-700 bg-stone-900 p-2 text-sm text-stone-200"
        />
        <div className="flex flex-wrap items-center gap-2 mt-2">
          <button
            type="button"
            className="lcta"
            disabled={!pasteText.trim() || pasteBusy}
            onClick={() => void linkPaste()}
          >
            {pasteBusy ? 'Linking…' : 'Link pasted text ›'}
          </button>
          <button
            type="button"
            className="lcta"
            disabled={uploadBusy}
            onClick={() => fileRef.current?.click()}
          >
            {uploadBusy ? 'Uploading…' : 'Upload a file ›'}
          </button>
          <input
            ref={fileRef}
            type="file"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) void linkFile(file)
            }}
          />
        </div>
        {sourceError && <p className="lsub text-red-300">{sourceError}</p>}
        {resolved.sources.length > 0 && (
          <ul className="mt-2 space-y-1">
            {resolved.sources.map((s) => (
              <li key={s.id} className="text-sm text-stone-300">
                {s.kind === 'file' ? '📄' : '📝'} {s.label}
                {s.excerpt && <span className="text-stone-500"> — {s.excerpt.slice(0, 120)}</span>}
              </li>
            ))}
          </ul>
        )}
      </div>

      {resolved.boundaries.length > 0 && (
        <div className="mt-4">
          <h4 className="text-sm font-medium text-stone-300">Topics you asked Weaver not to raise</h4>
          <ul className="mt-2 space-y-1">
            {resolved.boundaries.map((b) => (
              <li key={b.id} className="flex items-center gap-2 text-sm text-stone-300">
                <span>“{b.topic}”</span>
                <button
                  type="button"
                  className="text-stone-400 underline"
                  onClick={() => void reopenBoundary(b.id)}
                >
                  Reopen
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
