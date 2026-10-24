/**
 * Journal → story → prompt packs → import/mint.
 *
 * The minting pipeline UI: save journal entries, get marker-driven nudges
 * ("this would make a hilarious comic" — never a generic nag), turn
 * entries into archetype stories, generate prompt packs for external tools,
 * render quote cards in-house, and mint standalone pieces with the one
 * anchoring question. Honest empty states throughout — no demo data.
 */
import { useCallback, useEffect, useState } from 'react'
import { apiBase } from '../apiBase'

const MODALITIES = [
  { id: 'comic', label: 'Comic' },
  { id: 'song', label: 'Song' },
  { id: 'film', label: 'Film' },
  { id: 'image', label: 'Image' },
] as const

type Entry = {
  entry_id: string
  user_id: string
  text: string
  created_at: string
  artifact_id: string | null
  suggested_at: string | null
  suggested_marker: string | null
  suggested_modality: string | null
  suggestion_copy: string | null
  dismissed: number
  storified: number
}

/* Key-line tiers (S4, F3 — mirror the backend tiers vocabulary).
   Only "certified" is a verbatim quotation from the journal entry and
   may carry quotation presentation. Every other tier renders without
   curly quotes and with an honest label; a null line renders nothing. */
type KeyLineTier =
  | 'certified'
  | 'user_authored'
  | 'adopted'
  | 'dramatization'
  | null

type StoryContent = {
  title: string
  narrative: string
  key_line: string | null
  key_line_tier: KeyLineTier
  key_line_candidates: string[]
  key_line_selection: {
    kind: string
    chosen: string
    alternatives: string[]
    attribution: string
  } | null
  key_line_source: { entry_id?: string; entry_artifact_id?: string }
  archetype_cast: string[]
  strand_weights: Record<string, number>
}

function keyLineLabel(tier: KeyLineTier): string | null {
  switch (tier) {
    case 'user_authored':
      return 'Written by you'
    case 'adopted':
      return 'Chosen by you from Zenaf\u2019s options'
    case 'dramatization':
      return 'A creative rendering \u2014 not your words'
    default:
      return null
  }
}

type Pack = {
  artifact: { artifact_id: string; title: string }
  pack: {
    modality: string
    pack_title: string
    prompts: string[]
    style_line: string
    negative_prompt: string
  }
}

type PlanQuestion = {
  id: string
  question: string
  suggestions: string[]
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
  }
}

function api(path: string, init?: RequestInit) {
  return fetch(`${apiBase()}${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
}

/* ------------------------------------------------------------------ */
/* Entry card: suggestion → story → packs → quote card                 */
/* ------------------------------------------------------------------ */

function EntryCard({
  entry,
  onChanged,
}: {
  entry: Entry
  onChanged: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const [story, setStory] = useState<{
    artifact: { artifact_id: string }
    content: StoryContent
  } | null>(null)
  const [plan, setPlan] = useState<{
    stage: string
    questions?: PlanQuestion[]
    proposal?: { copy: string; modality: string }
  } | null>(null)
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [tweak, setTweak] = useState('')
  const [modalities, setModalities] = useState<string[]>(['song'])
  const [packs, setPacks] = useState<Pack[]>([])
  const [quoteCard, setQuoteCard] = useState<{
    artifact: { artifact_id: string }
    image_base64: string
  } | null>(null)
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importingPackId, setImportingPackId] = useState<string | null>(null)
  const [badge, setBadge] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const showSuggestion =
    entry.suggestion_copy && !entry.dismissed && !entry.storified && !story

  const doStory = useCallback(async () => {
    setBusy(true)
    setError(null)
    try {
      const r = await api('/pipeline/story', {
        method: 'POST',
        body: JSON.stringify({ journal_entry_id: entry.entry_id }),
      })
      if (!r.ok) throw new Error((await r.json()).detail || 'Story failed.')
      setStory(await r.json())
      onChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Story failed.')
    } finally {
      setBusy(false)
    }
  }, [entry.entry_id, onChanged])

  const doDismiss = useCallback(async () => {
    try {
      await api(`/pipeline/journal/${entry.entry_id}/dismiss`, { method: 'POST' })
      onChanged()
    } catch {
      /* dismissal is best-effort */
    }
  }, [entry.entry_id, onChanged])

  const loadPlan = useCallback(async () => {
    if (!story) return
    setBusy(true)
    setError(null)
    try {
      const r = await api(
        `/pipeline/packs/plan?story_id=${story.artifact.artifact_id}`
      )
      if (!r.ok) throw new Error((await r.json()).detail || 'Plan failed.')
      const p = await r.json()
      setPlan(p)
      const initial: Record<string, string> = {}
      for (const q of p.questions ?? []) initial[q.id] = ''
      setAnswers(initial)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Plan failed.')
    } finally {
      setBusy(false)
    }
  }, [story])

  const doPacks = useCallback(async () => {
    if (!story) return
    setBusy(true)
    setError(null)
    try {
      const body: Record<string, unknown> = {
        story_id: story.artifact.artifact_id,
        modalities,
      }
      if (plan?.stage === 'propose') {
        if (tweak.trim()) body.tweak = tweak.trim()
        else body.confirmed = true
      } else {
        body.answers = answers
      }
      const r = await api('/pipeline/packs', {
        method: 'POST',
        body: JSON.stringify(body),
      })
      if (!r.ok) throw new Error((await r.json()).detail || 'Pack failed.')
      const data = await r.json()
      setPacks((prev) => [...prev, ...data.packs])
      setPlan(null)
      setNotice('Pack saved. Render it in your tool, then import the result below.')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Pack failed.')
    } finally {
      setBusy(false)
    }
  }, [story, modalities, plan, answers, tweak])

  const doRegen = useCallback(async (packId: string) => {
    setBusy(true)
    setError(null)
    try {
      const r = await api(`/pipeline/packs/${packId}/regen`, { method: 'POST' })
      if (!r.ok) throw new Error((await r.json()).detail || 'Regen failed.')
      const data = await r.json()
      setPacks((prev) => [...prev, data])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Regen failed.')
    } finally {
      setBusy(false)
    }
  }, [])

  const doQuoteCard = useCallback(async () => {
    if (!story) return
    setBusy(true)
    setError(null)
    try {
      const r = await api('/pipeline/quote-card', {
        method: 'POST',
        body: JSON.stringify({ story_id: story.artifact.artifact_id, badge }),
      })
      if (!r.ok) throw new Error((await r.json()).detail || 'Card failed.')
      setQuoteCard(await r.json())
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Card failed.')
    } finally {
      setBusy(false)
    }
  }, [story, badge])

  const doImport = useCallback(
    async (packId: string) => {
      if (!importFile) return
      setBusy(true)
      setError(null)
      setNotice(null)
      try {
        const image_base64 = await fileToBase64(importFile)
        const r = await api('/provenance/ingest', {
          method: 'POST',
          body: JSON.stringify({
            image_base64,
            title: `Rendered from pack`,
            declared_parent_ids: [packId],
          }),
        })
        if (!r.ok) throw new Error((await r.json()).detail || 'Import failed.')
        const data = await r.json()
        if (data.outcome === 'exact') {
          setNotice('Already registered — linked to the existing artifact.')
        } else {
          setNotice('Imported and grafted onto the pack. The chain is complete.')
        }
        setImportFile(null)
        setImportingPackId(null)
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Import failed.')
      } finally {
        setBusy(false)
      }
    },
    [importFile]
  )

  const text = entry.text
  const truncated = text.length > 220 && !expanded

  return (
    <div className="rounded-xl border border-stone-800 bg-stone-900/40 p-4">
      <p className="text-[10px] text-stone-600">
        {new Date(entry.created_at).toLocaleString()}
      </p>
      <p className="text-sm text-stone-300 mt-1 leading-relaxed whitespace-pre-wrap">
        {truncated ? text.slice(0, 220) + '…' : text}
      </p>
      {text.length > 220 && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="text-xs text-amber-500/90 mt-1 min-h-[44px]"
        >
          {expanded ? 'Show less' : 'Show more'}
        </button>
      )}

      {showSuggestion && (
        <div className="mt-3 rounded-lg border border-amber-700/50 bg-amber-950/30 p-3">
          <p className="text-sm text-amber-200/90">{entry.suggestion_copy}</p>
          <div className="flex gap-2 mt-2">
            <button
              type="button"
              disabled={busy}
              onClick={doStory}
              className="min-h-[44px] px-4 rounded-full bg-amber-600 text-amber-50 text-sm font-semibold disabled:opacity-50"
            >
              Make it a story
            </button>
            <button
              type="button"
              onClick={doDismiss}
              className="min-h-[44px] px-4 rounded-full text-sm text-stone-400 hover:text-stone-200"
            >
              Not this one
            </button>
          </div>
        </div>
      )}

      {!showSuggestion && !story && !entry.storified && (
        <button
          type="button"
          disabled={busy}
          onClick={doStory}
          className="mt-3 min-h-[44px] px-4 rounded-full border border-stone-700 text-sm text-stone-300 hover:text-stone-100 disabled:opacity-50"
        >
          Make this a story
        </button>
      )}

      {story && (
        <div className="mt-3 rounded-lg bg-stone-950/60 p-3">
          <p className="text-sm font-semibold text-stone-100">
            {story.content.title}
          </p>
          <p className="text-sm text-stone-300 mt-1 leading-relaxed whitespace-pre-wrap">
            {story.content.narrative}
          </p>
          {story.content.key_line && story.content.key_line_tier === 'certified' && (
            <p className="text-sm text-amber-200/80 italic mt-2">
              “{story.content.key_line}”
            </p>
          )}
          {story.content.key_line && story.content.key_line_tier !== 'certified' && (
            <p className="text-sm text-stone-300 mt-2">
              {story.content.key_line}
              {keyLineLabel(story.content.key_line_tier) && (
                <span className="block text-xs text-stone-500 mt-1">
                  {keyLineLabel(story.content.key_line_tier)}
                </span>
              )}
            </p>
          )}
          {!story.content.key_line && (
            <p className="text-xs text-stone-500 mt-2">
              No quotable passage in this entry — the quote was omitted
              rather than invented.
            </p>
          )}
          {story.content.archetype_cast.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-2">
              {story.content.archetype_cast.map((c) => (
                <span
                  key={c}
                  className="text-[10px] px-2 py-1 rounded-full bg-stone-800 text-stone-400"
                >
                  {c}
                </span>
              ))}
            </div>
          )}
          <div className="flex flex-wrap gap-2 mt-3">
            <button
              type="button"
              disabled={busy}
              onClick={loadPlan}
              className="min-h-[44px] px-4 rounded-full bg-amber-600 text-amber-50 text-sm font-semibold disabled:opacity-50"
            >
              Generate prompt packs
            </button>
            <button
              type="button"
              disabled={
                busy ||
                !story.content.key_line ||
                story.content.key_line_tier !== 'certified'
              }
              title={
                story.content.key_line &&
                story.content.key_line_tier === 'certified'
                  ? undefined
                  : 'Quote cards require a verified line from your journal'
              }
              onClick={doQuoteCard}
              className="min-h-[44px] px-4 rounded-full border border-stone-700 text-sm text-stone-300 disabled:opacity-50"
            >
              Make a quote card
            </button>
            <label className="flex items-center gap-2 text-xs text-stone-400 min-h-[44px]">
              <input
                type="checkbox"
                checked={badge}
                onChange={(e) => setBadge(e.target.checked)}
                className="w-4 h-4"
              />
              Share badge
            </label>
          </div>
        </div>
      )}

      {plan && (
        <div className="mt-3 rounded-lg border border-stone-700 p-3">
          {plan.stage === 'propose' && plan.proposal ? (
            <>
              <p className="text-sm text-stone-200">{plan.proposal.copy}</p>
              <input
                type="text"
                value={tweak}
                onChange={(e) => setTweak(e.target.value)}
                placeholder="Or tweak it: “make it more rock”"
                className="mt-2 w-full min-h-[44px] px-3 rounded-lg bg-stone-950 border border-stone-700 text-stone-200 text-sm"
              />
            </>
          ) : (
            <>
              <p className="text-xs text-stone-500 mb-2">
                Three quick questions — your answers shape the pack and teach
                your taste compass.
              </p>
              {(plan.questions ?? []).map((q) => (
                <div key={q.id} className="mb-2">
                  <p className="text-sm text-stone-300">{q.question}</p>
                  <div className="flex flex-wrap gap-1 mt-1 mb-1">
                    {q.suggestions.map((s) => (
                      <button
                        key={s}
                        type="button"
                        onClick={() =>
                          setAnswers((a) => ({ ...a, [q.id]: s }))
                        }
                        className={`text-xs px-2 py-1 rounded-full min-h-[44px] ${
                          answers[q.id] === s
                            ? 'bg-amber-700 text-amber-50'
                            : 'bg-stone-800 text-stone-400'
                        }`}
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                  <input
                    type="text"
                    value={answers[q.id] ?? ''}
                    onChange={(e) =>
                      setAnswers((a) => ({ ...a, [q.id]: e.target.value }))
                    }
                    placeholder="Or write your own"
                    className="w-full min-h-[44px] px-3 rounded-lg bg-stone-950 border border-stone-700 text-stone-200 text-sm"
                  />
                </div>
              ))}
            </>
          )}
          <p className="text-xs text-stone-500 mt-2 mb-1">Make it as:</p>
          <div className="flex flex-wrap gap-1 mb-2">
            {MODALITIES.map((m) => (
              <button
                key={m.id}
                type="button"
                onClick={() =>
                  setModalities((prev) =>
                    prev.includes(m.id)
                      ? prev.filter((x) => x !== m.id)
                      : [...prev, m.id]
                  )
                }
                className={`text-xs px-3 py-1 rounded-full min-h-[44px] ${
                  modalities.includes(m.id)
                    ? 'bg-amber-700 text-amber-50'
                    : 'bg-stone-800 text-stone-400'
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>
          <button
            type="button"
            disabled={busy || modalities.length === 0}
            onClick={doPacks}
            className="min-h-[44px] px-4 rounded-full bg-amber-600 text-amber-50 text-sm font-semibold disabled:opacity-50"
          >
            {plan.stage === 'propose' ? 'Write the pack' : 'Generate packs'}
          </button>
        </div>
      )}

      {packs.map((p) => (
        <div
          key={p.artifact.artifact_id}
          className="mt-3 rounded-lg border border-stone-700 p-3"
        >
          <p className="text-sm font-medium text-stone-200">{p.pack.pack_title}</p>
          {p.pack.prompts.map((prompt, i) => (
            <div key={i} className="mt-2">
              <p className="text-xs text-stone-500 mb-1">
                Prompt {i + 1}
                {p.pack.modality === 'song' &&
                  (i === 0 ? ' — lyrics' : ' — style')}
              </p>
              <p className="text-xs text-stone-400 whitespace-pre-wrap leading-relaxed">
                {prompt.length > 400 ? prompt.slice(0, 400) + '…' : prompt}
              </p>
              <button
                type="button"
                onClick={() => copyText(prompt)}
                className="text-xs text-amber-500/90 mt-1 min-h-[44px]"
              >
                Copy prompt
              </button>
            </div>
          ))}
          {p.pack.style_line && (
            <p className="text-xs text-stone-500 mt-1 italic">{p.pack.style_line}</p>
          )}
          <div className="flex flex-wrap gap-2 mt-2">
            <button
              type="button"
              onClick={() => doRegen(p.artifact.artifact_id)}
              disabled={busy}
              className="min-h-[44px] px-3 rounded-full border border-stone-700 text-xs text-stone-300 disabled:opacity-50"
            >
              Give me another take
            </button>
            <button
              type="button"
              onClick={() =>
                setImportingPackId(
                  importingPackId === p.artifact.artifact_id
                    ? null
                    : p.artifact.artifact_id
                )
              }
              className="min-h-[44px] px-3 rounded-full border border-stone-700 text-xs text-stone-300"
            >
              Import the result
            </button>
          </div>
          {importingPackId === p.artifact.artifact_id && (
            <div className="mt-2">
              <p className="text-xs text-stone-500 mb-1">
                Rendered it in your tool? Upload the file — it will be grafted
                onto this pack. Make sure you have the right to mint this.
              </p>
              <input
                type="file"
                accept="image/*"
                onChange={(e) => setImportFile(e.target.files?.[0] ?? null)}
                className="text-xs text-stone-400 file:mr-2 file:min-h-[44px] file:px-3 file:rounded-full file:border-0 file:bg-stone-800 file:text-stone-200"
              />
              {importFile && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => doImport(p.artifact.artifact_id)}
                  className="ml-2 min-h-[44px] px-4 rounded-full bg-amber-600 text-amber-50 text-xs font-semibold disabled:opacity-50"
                >
                  Mint it
                </button>
              )}
            </div>
          )}
        </div>
      ))}

      {quoteCard && (
        <div className="mt-3">
          <img
            src={`data:image/png;base64,${quoteCard.image_base64}`}
            alt="Quote card"
            className="rounded-xl w-full max-w-sm border border-stone-800"
          />
          <p className="text-xs text-stone-500 mt-1">
            Minted — no import needed. It lives in your lineage now.
          </p>
        </div>
      )}

      {error && <p className="text-red-400 text-xs mt-2">{error}</p>}
      {notice && <p className="text-emerald-400/90 text-xs mt-2">{notice}</p>}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Standalone mint                                                     */
/* ------------------------------------------------------------------ */

function StandaloneMint({ entries }: { entries: Entry[] }) {
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
        { method: 'POST', body: JSON.stringify(body) }
      )
      if (!r.ok) throw new Error((await r.json()).detail || 'Anchor failed.')
      const data = await r.json()
      setDone(
        data.anchored
          ? 'Grafted onto your journal. The funnel runs both ways.'
          : 'Minted standalone — no journal link.'
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

/* ------------------------------------------------------------------ */
/* Journal tab                                                         */
/* ------------------------------------------------------------------ */

export default function JournalTab() {
  const [entries, setEntries] = useState<Entry[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const r = await api('/pipeline/journal')
      if (r.ok) setEntries((await r.json()).entries)
    } catch {
      /* entries load is best-effort on first paint */
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const save = useCallback(async () => {
    if (!draft.trim()) return
    setBusy(true)
    setError(null)
    try {
      const r = await api('/pipeline/journal', {
        method: 'POST',
        body: JSON.stringify({ text: draft.trim() }),
      })
      if (!r.ok) throw new Error((await r.json()).detail || 'Save failed.')
      setDraft('')
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed.')
    } finally {
      setBusy(false)
    }
  }, [draft, load])

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-stone-800 bg-stone-900/40 p-4">
        <p className="text-sm font-medium text-stone-200">New entry</p>
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Write what's on your mind…"
          rows={3}
          className="mt-2 w-full px-3 py-2 rounded-lg bg-stone-950 border border-stone-700 text-stone-200 text-sm"
        />
        <button
          type="button"
          disabled={busy || !draft.trim()}
          onClick={save}
          className="mt-2 min-h-[44px] px-4 rounded-full bg-amber-600 text-amber-50 text-sm font-semibold disabled:opacity-50"
        >
          Save entry
        </button>
        {error && <p className="text-red-400 text-xs mt-2">{error}</p>}
      </div>

      <StandaloneMint entries={entries} />

      {entries.length === 0 ? (
        <div className="rounded-xl border border-dashed border-stone-700 p-8 text-center">
          <p className="text-sm text-stone-400">No entries yet.</p>
          <p className="text-xs text-stone-500 mt-1">
            Write your first entry above. Entries become stories, stories become
            prompt packs, packs become minted artifacts.
          </p>
        </div>
      ) : (
        entries.map((e) => (
          <EntryCard key={e.entry_id} entry={e} onChanged={load} />
        ))
      )}
    </div>
  )
}
