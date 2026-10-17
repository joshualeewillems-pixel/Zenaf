/**
 * Provenance ledger + lineage view — the butterfly-effect UI.
 *
 * Ledger tab: the user's minted/imported artifacts, per-artifact cached
 * reach, and perspective_reach (the long-term marketplace pricing input).
 * Lineage tab: per-artifact derivation tree + downstream engagement timeline.
 *
 * Visibility is enforced server-side; private remixes arrive here as
 * anonymized stubs ("private remix") and render as such. Honest empty
 * states throughout — no demo or seed data.
 */
import { useCallback, useEffect, useState } from 'react'
import { apiBase } from '../apiBase'
import JournalTab from './JournalTab'

type Artifact = {
  artifact_id: string
  creator_user_id: string | null
  custodian_user_id: string | null
  created_at: string
  title: string
  description: string
  archetype_cast: string[]
  visibility: 'private' | 'unlisted' | 'public'
  remix_policy: 'open' | 'approval'
  minted: boolean
  imported: boolean
  disputed: boolean
  reach_cached: number
  engagement?: Record<string, number>
  children_count?: number
}

type TreeNode = Artifact & {
  stub?: boolean
  label?: string
  children: TreeNode[]
  engagement?: Record<string, number>
}

type TimelineEvent = {
  event_id: string
  artifact_id: string
  type: string
  actor_user_id: string | null
  at: string
  context: Record<string, unknown>
  artifact_label: string
  artifact_stub: boolean
}

const EVENT_LABELS: Record<string, string> = {
  minted: 'minted',
  viewed: 'viewed',
  saved: 'saved',
  shared: 'shared',
  remixed: 'remixed into a new artifact',
  response_minted: 'inspired a minted response',
  journal_sparked: 'sparked a journal entry',
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

function Tree({ node, depth }: { node: TreeNode; depth: number }) {
  if (node.stub) {
    return (
      <div className="flex items-center gap-2 py-1.5 text-stone-500">
        <span className="text-xs italic">◌ private remix</span>
      </div>
    )
  }
  return (
    <div className={depth > 0 ? 'ml-4 border-l border-stone-700/70 pl-3' : ''}>
      <div className="py-1.5">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-medium text-stone-200">
            {node.title || node.artifact_id.slice(0, 8)}
          </span>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-stone-800 text-stone-400">
            {node.visibility}
          </span>
          {node.disputed && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-900/60 text-red-300">
              disputed
            </span>
          )}
          <span className="text-xs text-amber-500/90">
            reach {node.reach_cached.toFixed(1)}
          </span>
        </div>
        {node.engagement && Object.keys(node.engagement).length > 0 && (
          <div className="text-[11px] text-stone-500 mt-0.5">
            {Object.entries(node.engagement)
              .map(([t, n]) => `${n}× ${EVENT_LABELS[t] ?? t}`)
              .join(' · ')}
          </div>
        )}
      </div>
      {node.children.map((c) => (
        <Tree key={c.artifact_id} node={c} depth={depth + 1} />
      ))}
    </div>
  )
}

export default function ProvenanceView() {
  const [tab, setTab] = useState<'ledger' | 'lineage' | 'journal'>('ledger')
  const [ledger, setLedger] = useState<{
    perspective_reach: number
    artifacts: Artifact[]
    reputation: { false_claims: number; frivolous_challenges: number }
  } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string>('')
  const [lineage, setLineage] = useState<{ tree: TreeNode; timeline: TimelineEvent[] } | null>(null)

  // Register form
  const [regTitle, setRegTitle] = useState('')
  const [regPolicy, setRegPolicy] = useState('open')
  const [regFile, setRegFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)

  const base = apiBase()

  const loadLedger = useCallback(async () => {
    setError(null)
    try {
      const r = await fetch(`${base}/provenance/ledger`, { credentials: 'include' })
      if (!r.ok) throw new Error(`ledger failed: ${r.status}`)
      setLedger(await r.json())
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed to load ledger')
    }
  }, [base])

  useEffect(() => {
    loadLedger()
  }, [loadLedger])

  const loadLineage = useCallback(
    async (id: string) => {
      if (!id) return
      setError(null)
      setLineage(null)
      try {
        const r = await fetch(`${base}/provenance/artifacts/${id}/lineage`, {
          credentials: 'include',
        })
        if (!r.ok) throw new Error(`lineage failed: ${r.status}`)
        setLineage(await r.json())
        setSelectedId(id)
        setTab('lineage')
      } catch (e) {
        setError(e instanceof Error ? e.message : 'failed to load lineage')
      }
    },
    [base],
  )

  async function handleRegister() {
    if (!regFile) return
    setBusy(true)
    setError(null)
    try {
      const image_base64 = await fileToBase64(regFile)
      const r = await fetch(`${base}/provenance/register`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          image_base64,
          title: regTitle || regFile.name,
          remix_policy: regPolicy,
        }),
      })
      if (!r.ok) throw new Error(`register failed: ${r.status}`)
      setRegTitle('')
      setRegFile(null)
      await loadLedger()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'register failed')
    } finally {
      setBusy(false)
    }
  }

  async function handleMintPublish(id: string, action: 'mint' | 'publish') {
    setError(null)
    try {
      const r = await fetch(`${base}/provenance/${id}/${action}`, {
        method: 'POST',
        credentials: 'include',
      })
      if (!r.ok) throw new Error(`${action} failed: ${r.status}`)
      await loadLedger()
    } catch (e) {
      setError(e instanceof Error ? e.message : `${action} failed`)
    }
  }

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-y-auto">
      <div className="shrink-0 border-b border-stone-800 px-4 py-3">
        <p className="text-[10px] font-medium text-stone-500 uppercase tracking-wide">
          Provenance
        </p>
        <h1 className="text-lg font-semibold text-stone-100 mt-0.5">Minting ledger</h1>
        <p className="text-[11px] text-stone-500 mt-1 max-w-3xl leading-relaxed">
          Fingerprint the file, ledger in the registry. Watch what your artifacts
          become downstream — reach accumulates on resonance, not views.
        </p>
        <div className="flex gap-1 bg-stone-900/60 rounded-full p-1 mt-3 w-fit">
          {(['ledger', 'lineage', 'journal'] as const).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTab(t)}
              className={`min-h-[44px] px-4 rounded-full text-sm font-medium transition-colors ${
                tab === t ? 'bg-stone-700 text-stone-100' : 'text-stone-400 hover:text-stone-300'
              }`}
            >
              {t === 'ledger' ? 'Ledger' : t === 'lineage' ? 'Lineage' : 'Journal'}
            </button>
          ))}
        </div>
        {error && <p className="text-red-400 text-xs mt-2">{error}</p>}
      </div>

      <div className="flex-1 min-h-0 p-4 max-w-3xl w-full mx-auto">
        {tab === 'ledger' && (
          <>
            {ledger && (
              <div className="rounded-xl border border-stone-800 bg-stone-900/40 p-4 mb-4">
                <p className="text-[10px] uppercase tracking-wide text-stone-500">
                  Perspective reach
                </p>
                <p className="text-3xl font-semibold text-amber-500/90 mt-1">
                  {ledger.perspective_reach.toFixed(1)}
                </p>
                <p className="text-[11px] text-stone-500 mt-1">
                  Accumulated downstream resonance across everything you've created.
                </p>
              </div>
            )}

            <div className="rounded-xl border border-stone-800 bg-stone-900/40 p-4 mb-4">
              <h2 className="text-sm font-semibold text-stone-200 mb-3">Register an artifact</h2>
              <input
                type="text"
                value={regTitle}
                onChange={(e) => setRegTitle(e.target.value)}
                placeholder="Title"
                className="w-full min-h-[44px] px-3 rounded-lg bg-stone-950 border border-stone-700 text-stone-200 text-sm mb-2"
              />
              <div className="flex gap-2 mb-2 flex-wrap">
                <input
                  type="file"
                  accept="image/*"
                  onChange={(e) => setRegFile(e.target.files?.[0] ?? null)}
                  className="text-xs text-stone-400 file:mr-2 file:min-h-[44px] file:px-3 file:rounded-lg file:border file:border-stone-700 file:bg-stone-800 file:text-stone-200"
                />
                <select
                  value={regPolicy}
                  onChange={(e) => setRegPolicy(e.target.value)}
                  className="min-h-[44px] px-3 rounded-lg bg-stone-950 border border-stone-700 text-stone-200 text-sm"
                  aria-label="Remix policy"
                >
                  <option value="open">Remix: open</option>
                  <option value="approval">Remix: approval</option>
                </select>
              </div>
              <button
                type="button"
                onClick={handleRegister}
                disabled={!regFile || busy}
                className="min-h-[44px] px-4 rounded-full bg-amber-600 text-amber-50 text-sm font-semibold disabled:opacity-40"
              >
                {busy ? 'Registering…' : 'Register'}
              </button>
            </div>

            {!ledger ? (
              <p className="text-sm text-stone-500">Loading…</p>
            ) : ledger.artifacts.length === 0 ? (
              <div className="rounded-xl border border-dashed border-stone-700 p-8 text-center">
                <p className="text-sm text-stone-400">No artifacts yet.</p>
                <p className="text-xs text-stone-500 mt-1">
                  Register your first image above — it enters the ledger unlisted,
                  and minting makes it private until you choose to share it.
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                {ledger.artifacts.map((a) => (
                  <div
                    key={a.artifact_id}
                    className="rounded-xl border border-stone-800 bg-stone-900/40 p-4"
                  >
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-medium text-stone-100">
                        {a.title || a.artifact_id.slice(0, 8)}
                      </span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-stone-800 text-stone-400">
                        {a.visibility}
                      </span>
                      {a.imported && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-stone-800 text-stone-400">
                          imported
                        </span>
                      )}
                      {a.disputed && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-900/60 text-red-300">
                          disputed — reach frozen
                        </span>
                      )}
                      <span className="text-xs text-amber-500/90 ml-auto">
                        reach {a.reach_cached.toFixed(1)}
                      </span>
                    </div>
                    <div className="flex gap-2 mt-3 flex-wrap">
                      <button
                        type="button"
                        onClick={() => loadLineage(a.artifact_id)}
                        className="min-h-[44px] px-3 rounded-lg border border-stone-700 text-stone-300 text-xs font-medium"
                      >
                        View lineage
                      </button>
                      {!a.minted && (
                        <button
                          type="button"
                          onClick={() => handleMintPublish(a.artifact_id, 'mint')}
                          className="min-h-[44px] px-3 rounded-lg border border-stone-700 text-stone-300 text-xs font-medium"
                        >
                          Mint (make private)
                        </button>
                      )}
                      {a.visibility !== 'public' && (
                        <button
                          type="button"
                          onClick={() => handleMintPublish(a.artifact_id, 'publish')}
                          className="min-h-[44px] px-3 rounded-lg border border-stone-700 text-stone-300 text-xs font-medium"
                        >
                          Make public
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {tab === 'journal' && <JournalTab />}

        {tab === 'lineage' && (
          <>
            <div className="flex gap-2 mb-4">
              <input
                type="text"
                value={selectedId}
                onChange={(e) => setSelectedId(e.target.value)}
                placeholder="Artifact ID"
                className="flex-1 min-h-[44px] px-3 rounded-lg bg-stone-950 border border-stone-700 text-stone-200 text-sm font-mono"
              />
              <button
                type="button"
                onClick={() => loadLineage(selectedId)}
                className="min-h-[44px] px-4 rounded-full bg-amber-600 text-amber-50 text-sm font-semibold"
              >
                Load
              </button>
            </div>
            {!lineage ? (
              <div className="rounded-xl border border-dashed border-stone-700 p-8 text-center">
                <p className="text-sm text-stone-400">No artifact selected.</p>
                <p className="text-xs text-stone-500 mt-1">
                  Pick “View lineage” on any artifact in your ledger, or paste an artifact ID.
                </p>
              </div>
            ) : (
              <>
                <h2 className="text-sm font-semibold text-stone-200 mb-2">
                  Derivation tree
                </h2>
                <div className="rounded-xl border border-stone-800 bg-stone-900/40 p-4 mb-4">
                  <Tree node={lineage.tree} depth={0} />
                </div>
                <h2 className="text-sm font-semibold text-stone-200 mb-2">
                  Downstream timeline
                </h2>
                {lineage.timeline.length === 0 ? (
                  <p className="text-xs text-stone-500">No engagement recorded yet.</p>
                ) : (
                  <div className="space-y-2">
                    {lineage.timeline.map((e) => (
                      <div
                        key={e.event_id}
                        className="rounded-lg border border-stone-800 bg-stone-900/40 px-3 py-2"
                      >
                        <p className="text-xs text-stone-300">
                          <span className="font-medium">
                            {e.artifact_stub ? 'private remix' : e.artifact_label}
                          </span>{' '}
                          <span className="text-stone-500">
                            {EVENT_LABELS[e.type] ?? e.type}
                          </span>
                        </p>
                        <p className="text-[10px] text-stone-600 mt-0.5">
                          {new Date(e.at).toLocaleString()}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </>
        )}
      </div>
    </div>
  )
}
