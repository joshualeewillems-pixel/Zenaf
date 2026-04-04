import { useCallback, useEffect, useState } from 'react'
import { VISION_EXECUTION_API } from '../vision-execution/types'

export type AspirationProfile = {
  user_id?: string
  core_aim: string
  growth_domains: string[]
  current_edge: string
  current_obstacles: string
  near_term_aspirations: string
  long_term_aspirations: string
  guidance_preferences: Record<string, unknown>
  anti_goals: string
  use_in_guidance: boolean
  allow_inference: boolean
  updated_at?: string
}

type AspirationProposal = {
  id: string
  theme: string
  detail: string
  basis: string[]
  status: string
}

async function aspirationApiErrorText(res: Response): Promise<string> {
  const text = await res.text().catch(() => res.statusText)
  try {
    const j = JSON.parse(text) as { detail?: unknown }
    if (typeof j.detail === 'string') return j.detail
  } catch {
    /* ignore */
  }
  return text || res.statusText
}

export function AspirationsFoundationPanel({
  apiGet,
  apiPatch,
  apiPost,
}: {
  apiGet: <T>(path: string) => Promise<T>
  apiPatch: <T>(path: string, body: unknown) => Promise<T>
  apiPost: <T>(path: string, body?: unknown) => Promise<T>
}) {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [profile, setProfile] = useState<AspirationProfile | null>(null)
  const [proposals, setProposals] = useState<AspirationProposal[]>([])
  const [proposalError, setProposalError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      const data = await apiGet<{ profile: AspirationProfile | null }>('/aspiration-profile')
      setProfile(
        data.profile ?? {
          core_aim: '',
          growth_domains: [],
          current_edge: '',
          current_obstacles: '',
          near_term_aspirations: '',
          long_term_aspirations: '',
          guidance_preferences: {},
          anti_goals: '',
          use_in_guidance: false,
          allow_inference: false,
        },
      )
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load aspirations')
    } finally {
      setLoading(false)
    }
  }, [apiGet])

  useEffect(() => {
    void load()
  }, [load])

  const loadProposals = useCallback(async () => {
    setProposalError(null)
    try {
      // ai-trace-exempt: heuristic_no_provider — sync uses resonance heuristics only (no LLM; see local_ai/aspiration_layer.py).
      const res = await fetch(`${VISION_EXECUTION_API}/aspiration-proposals`, { credentials: 'include' })
      if (!res.ok) {
        setProposals([])
        setProposalError(await aspirationApiErrorText(res))
        return
      }
      const data = (await res.json()) as { proposals?: AspirationProposal[] }
      setProposals(data.proposals ?? [])
    } catch (e) {
      setProposalError(e instanceof Error ? e.message : 'Failed to load proposals')
    }
  }, [])

  useEffect(() => {
    void loadProposals()
  }, [loadProposals])

  const saveField = async (partial: Partial<AspirationProfile>) => {
    setSaving(true)
    setMessage(null)
    setError(null)
    try {
      const data = await apiPatch<{ profile: AspirationProfile }>('/aspiration-profile', partial)
      setProfile(data.profile)
      setMessage('Saved.')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="rounded-lg border border-stone-700 bg-stone-900/55 p-4">
        <p className="text-stone-500 text-sm">Loading aspirations…</p>
      </div>
    )
  }

  if (error && !profile) {
    return (
      <div className="rounded-lg border border-stone-700 bg-stone-900/55 p-4 space-y-2">
        <p className="text-stone-200 text-sm font-medium">Aspirations</p>
        <p className="text-red-400 text-xs">{error}</p>
        <p className="text-stone-500 text-xs">
          Enable &quot;Store explicit aspirations&quot; under Settings → Data permissions if save/load is blocked.
        </p>
      </div>
    )
  }

  const p = profile!

  return (
    <div className="rounded-lg border border-stone-700 bg-stone-900/55 p-4 space-y-3">
      <div>
        <h3 className="text-sm font-semibold text-stone-100 inline-flex items-center gap-2">
          Aspirations
          {proposals.length > 0 ? (
            <span
              className="inline-block h-2 w-2 rounded-full bg-amber-400"
              title="New aspiration proposals available"
            />
          ) : null}
        </h3>
        <p className="text-[11px] text-stone-500 mt-1 leading-relaxed">
          User-authored orientation for developmental guidance. Inference never overwrites this without your
          confirmation.
        </p>
      </div>

      {error ? <p className="text-red-400 text-xs">{error}</p> : null}
      {message ? <p className="text-emerald-400 text-xs">{message}</p> : null}

      <label className="block text-[11px] font-medium text-stone-400">Core aim</label>
      <textarea
        value={p.core_aim}
        disabled={saving}
        onChange={(e) => setProfile({ ...p, core_aim: e.target.value })}
        onBlur={() => void saveField({ core_aim: p.core_aim })}
        rows={2}
        className="w-full px-3 py-2 rounded-lg bg-stone-950 border border-stone-600 text-stone-100 text-sm"
      />

      <label className="block text-[11px] font-medium text-stone-400">What I&apos;m growing toward (domains)</label>
      <input
        type="text"
        value={p.growth_domains.join(', ')}
        disabled={saving}
        onChange={(e) =>
          setProfile({
            ...p,
            growth_domains: e.target.value
              .split(',')
              .map((s) => s.trim())
              .filter(Boolean),
          })
        }
        onBlur={() => void saveField({ growth_domains: p.growth_domains })}
        placeholder="Comma-separated, e.g. craft, leadership, health"
        className="w-full px-3 py-2 rounded-lg bg-stone-950 border border-stone-600 text-stone-100 text-sm"
      />

      <label className="block text-[11px] font-medium text-stone-400">Current edge</label>
      <textarea
        value={p.current_edge}
        disabled={saving}
        onChange={(e) => setProfile({ ...p, current_edge: e.target.value })}
        onBlur={() => void saveField({ current_edge: p.current_edge })}
        rows={2}
        className="w-full px-3 py-2 rounded-lg bg-stone-950 border border-stone-600 text-stone-100 text-sm"
      />

      <label className="block text-[11px] font-medium text-stone-400">Current obstacles</label>
      <textarea
        value={p.current_obstacles}
        disabled={saving}
        onChange={(e) => setProfile({ ...p, current_obstacles: e.target.value })}
        onBlur={() => void saveField({ current_obstacles: p.current_obstacles })}
        rows={2}
        className="w-full px-3 py-2 rounded-lg bg-stone-950 border border-stone-600 text-stone-100 text-sm"
      />

      <label className="block text-[11px] font-medium text-stone-400">Near-term aspirations</label>
      <textarea
        value={p.near_term_aspirations}
        disabled={saving}
        onChange={(e) => setProfile({ ...p, near_term_aspirations: e.target.value })}
        onBlur={() => void saveField({ near_term_aspirations: p.near_term_aspirations })}
        rows={2}
        className="w-full px-3 py-2 rounded-lg bg-stone-950 border border-stone-600 text-stone-100 text-sm"
      />

      <label className="block text-[11px] font-medium text-stone-400">Long-term aspirations</label>
      <textarea
        value={p.long_term_aspirations}
        disabled={saving}
        onChange={(e) => setProfile({ ...p, long_term_aspirations: e.target.value })}
        onBlur={() => void saveField({ long_term_aspirations: p.long_term_aspirations })}
        rows={2}
        className="w-full px-3 py-2 rounded-lg bg-stone-950 border border-stone-600 text-stone-100 text-sm"
      />

      <label className="block text-[11px] font-medium text-stone-400">Guidance style preference</label>
      <input
        type="text"
        value={String((p.guidance_preferences as { style?: string }).style ?? '')}
        disabled={saving}
        onChange={(e) =>
          setProfile({
            ...p,
            guidance_preferences: { ...p.guidance_preferences, style: e.target.value },
          })
        }
        onBlur={() =>
          void saveField({
            guidance_preferences: {
              ...p.guidance_preferences,
              style: String((p.guidance_preferences as { style?: string }).style ?? ''),
            },
          })
        }
        placeholder="e.g. direct, gentle, structured"
        className="w-full px-3 py-2 rounded-lg bg-stone-950 border border-stone-600 text-stone-100 text-sm"
      />

      <label className="block text-[11px] font-medium text-stone-400">Anti-goals</label>
      <textarea
        value={p.anti_goals}
        disabled={saving}
        onChange={(e) => setProfile({ ...p, anti_goals: e.target.value })}
        onBlur={() => void saveField({ anti_goals: p.anti_goals })}
        rows={2}
        className="w-full px-3 py-2 rounded-lg bg-stone-950 border border-stone-600 text-stone-100 text-sm"
      />

      <div className="space-y-2 pt-1 border-t border-stone-700">
        <label className="flex items-start gap-2 cursor-pointer">
          <input
            type="checkbox"
            className="mt-0.5 rounded border-stone-600"
            checked={p.use_in_guidance}
            disabled={saving}
            onChange={(e) => {
              const next = e.target.checked
              setProfile({ ...p, use_in_guidance: next })
              void saveField({ use_in_guidance: next })
            }}
          />
          <span className="text-xs text-stone-300">
            Use this to shape developmental guidance
            <span className="block text-[11px] text-stone-500 mt-0.5">
              Requires consent: “Use aspirations in guidance” in Settings.
            </span>
          </span>
        </label>
        <label className="flex items-start gap-2 cursor-pointer">
          <input
            type="checkbox"
            className="mt-0.5 rounded border-stone-600"
            checked={p.allow_inference}
            disabled={saving}
            onChange={(e) => {
              const next = e.target.checked
              setProfile({ ...p, allow_inference: next })
              void saveField({ allow_inference: next })
            }}
          />
          <span className="text-xs text-stone-300">
            Allow inferred aspiration suggestions
            <span className="block text-[11px] text-stone-500 mt-0.5">
              Requires consent: “Infer aspiration suggestions” in Settings.
            </span>
          </span>
        </label>
      </div>

      <div className="pt-2 border-t border-stone-700 space-y-2">
        <p className="text-[11px] font-medium text-stone-400">Suggested aspiration themes</p>
        {proposalError ? (
          <p className="text-[11px] text-stone-500">{proposalError}</p>
        ) : proposals.length === 0 ? (
          <p className="text-[11px] text-stone-500">No pending proposals.</p>
        ) : (
          <ul className="space-y-2">
            {proposals.map((pr) => (
              <li key={pr.id} className="rounded border border-stone-600 p-2 text-xs text-stone-300">
                <p className="font-medium text-stone-200">{pr.theme}</p>
                <p className="text-stone-400 mt-1">{pr.detail}</p>
                <div className="flex gap-2 mt-2">
                  <button
                    type="button"
                    disabled={saving}
                    className="px-2 py-1 rounded bg-emerald-900/50 text-emerald-200 text-[11px]"
                    onClick={() =>
                      void (async () => {
                        try {
                          await apiPost(`/aspiration-proposals/${pr.id}/accept`)
                          const nextNear = [
                            p.near_term_aspirations?.trim(),
                            `• ${pr.theme}${pr.detail ? ` — ${pr.detail}` : ''}`,
                          ]
                            .filter(Boolean)
                            .join('\n')
                            .slice(0, 12000)
                          await apiPatch('/aspiration-profile', { near_term_aspirations: nextNear })
                          await load()
                          await loadProposals()
                        } catch (e) {
                          setProposalError(e instanceof Error ? e.message : 'Accept failed')
                        }
                      })()
                    }
                  >
                    Accept
                  </button>
                  <button
                    type="button"
                    disabled={saving}
                    className="px-2 py-1 rounded bg-stone-800 text-stone-300 text-[11px]"
                    onClick={() =>
                      void (async () => {
                        try {
                          await apiPost(`/aspiration-proposals/${pr.id}/dismiss`)
                          await loadProposals()
                        } catch (e) {
                          setProposalError(e instanceof Error ? e.message : 'Dismiss failed')
                        }
                      })()
                    }
                  >
                    Dismiss
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
