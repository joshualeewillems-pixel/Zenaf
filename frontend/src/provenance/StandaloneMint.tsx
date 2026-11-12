/**
 * Standalone mint (moved verbatim from JournalTab, 2026-11-12 — the
 * Fox's sheet mounts the same flow, so it lives here now instead of
 * inside the journal tab).
 *
 * POST /pipeline/mint-standalone (image_base64 + title → artifact +
 * anchoring_question) then POST
 * /pipeline/mint-standalone/{artifact_id}/anchor (journal_entry_id or
 * micro_reflection → grafted onto the journal, or minted standalone).
 * The mint is expressive, not authoritative: it does not touch the
 * project record, and no seat is attributed to the artifact — the
 * standalone endpoints take no seat (open question, 2026-11-12).
 *
 * `entries` is optional: the journal tab passes its own list; any
 * other mount (the Maverick sheet) omits it and the component loads
 * GET /pipeline/journal itself, best-effort, so the anchor step's
 * "point at an entry" select works identically.
 */
import { useCallback, useEffect, useState } from 'react'
import { apiBase } from '../apiBase'

export type MintJournalEntry = {
  entry_id: string
  text: string
  created_at: string
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

function api(path: string, init?: RequestInit) {
  return fetch(`${apiBase()}${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
}

export default function StandaloneMint({ entries: entriesProp }: { entries?: MintJournalEntry[] }) {
  const [entries, setEntries] = useState<MintJournalEntry[]>(entriesProp ?? [])
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [result, setResult] = useState<{
    artifact: { artifact_id: string }
    anchoring_question: string
  } | null>(null)
  const [entryId, setEntryId] = useState('')
  const [reflection, setReflection] = useState('')
  const [done, setDone] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (entriesProp) return
    let cancelled = false
    api('/pipeline/journal')
      .then(async (r) => {
        if (!r.ok) return
        const data = (await r.json()) as { entries?: MintJournalEntry[] }
        if (!cancelled && Array.isArray(data.entries)) setEntries(data.entries)
      })
      .catch(() => {
        /* entries load is best-effort — the mint still works, and the
           anchor step falls back to a reflection or Skip. */
      })
    return () => {
      cancelled = true
    }
  }, [entriesProp])

  const doMint = useCallback(async () => {
    if (!file) return
    setBusy(true)
    setError(null)
    try {
      const image_base64 = await fileToBase64(file)
      const r = await api('/pipeline/mint-standalone', {
        method: 'POST',
        body: JSON.stringify({ image_base64, title }),
      })
      if (!r.ok) throw new Error((await r.json()).detail || 'Mint failed.')
      setResult(await r.json())
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Mint failed.')
    } finally {
      setBusy(false)
    }
  }, [file, title])

  const doAnchor = useCallback(async () => {
    if (!result) return
    setBusy(true)
    setError(null)
    try {
      const body: Record<string, string> = {}
      if (entryId) body.journal_entry_id = entryId
      else if (reflection.trim()) body.micro_reflection = reflection.trim()
      const r = await api(
        `/pipeline/mint-standalone/${result.artifact.artifact_id}/anchor`,
        { method: 'POST', body: JSON.stringify(body) },
      )
      if (!r.ok) throw new Error((await r.json()).detail || 'Anchor failed.')
      const data = await r.json()
      setDone(
        data.anchored
          ? 'Grafted onto your journal. The funnel runs both ways.'
          : 'Minted standalone — no journal link.',
      )
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Anchor failed.')
    } finally {
      setBusy(false)
    }
  }, [result, entryId, reflection])

  if (done) {
    return (
      <div className="rounded-xl border border-stone-800 bg-stone-900/40 p-4">
        <p className="text-sm text-stone-300">{done}</p>
        <button
          type="button"
          onClick={() => {
            setFile(null)
            setTitle('')
            setResult(null)
            setEntryId('')
            setReflection('')
            setDone(null)
          }}
          className="mt-2 text-xs text-amber-500/90 min-h-[44px]"
        >
          Mint another
        </button>
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-stone-800 bg-stone-900/40 p-4">
      <p className="text-sm font-medium text-stone-200">Mint something standalone</p>
      <p className="text-xs text-stone-500 mt-1">
        A photo you took, a song you wrote elsewhere — no journal entry needed.
      </p>
      {!result ? (
        <div className="mt-2">
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Title (optional)"
            className="w-full min-h-[44px] px-3 rounded-lg bg-stone-950 border border-stone-700 text-stone-200 text-sm mb-2"
          />
          <input
            type="file"
            accept="image/*"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="text-xs text-stone-400 file:mr-2 file:min-h-[44px] file:px-3 file:rounded-full file:border-0 file:bg-stone-800 file:text-stone-200"
          />
          {file && (
            <button
              type="button"
              disabled={busy}
              onClick={doMint}
              className="ml-2 min-h-[44px] px-4 rounded-full bg-amber-600 text-amber-50 text-sm font-semibold disabled:opacity-50"
            >
              Mint it
            </button>
          )}
        </div>
      ) : (
        <div className="mt-2">
          <p className="text-sm text-amber-200/90">{result.anchoring_question}</p>
          <p className="text-xs text-stone-500 mt-1">
            Optional — answer once, or skip. Answering links this piece to a moment.
          </p>
          {entries.length > 0 && (
            <select
              value={entryId}
              onChange={(e) => setEntryId(e.target.value)}
              className="mt-2 w-full min-h-[44px] px-3 rounded-lg bg-stone-950 border border-stone-700 text-stone-200 text-sm"
            >
              <option value="">Point at an entry…</option>
              {entries.map((e) => (
                <option key={e.entry_id} value={e.entry_id}>
                  {new Date(e.created_at).toLocaleDateString()} —{' '}
                  {e.text.slice(0, 60)}
                </option>
              ))}
            </select>
          )}
          <textarea
            value={reflection}
            onChange={(e) => setReflection(e.target.value)}
            placeholder="Or write a line about the moment — it becomes a journal entry."
            rows={2}
            className="mt-2 w-full px-3 py-2 rounded-lg bg-stone-950 border border-stone-700 text-stone-200 text-sm"
          />
          <div className="flex gap-2 mt-2">
            <button
              type="button"
              disabled={busy}
              onClick={doAnchor}
              className="min-h-[44px] px-4 rounded-full bg-amber-600 text-amber-50 text-sm font-semibold disabled:opacity-50"
            >
              {entryId || reflection.trim() ? 'Link it' : 'Skip'}
            </button>
          </div>
        </div>
      )}
      {error && <p className="text-red-400 text-xs mt-2">{error}</p>}
    </div>
  )
}
