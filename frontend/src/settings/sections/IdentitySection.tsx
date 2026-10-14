import { useCallback, useEffect, useState } from 'react'
import {
  changeIdentityScope,
  fetchIdentityScopes,
} from '../api'

/**
 * Settings → Identity: the consent-scope management UI for the identity
 * license layer. Every use of identity-derived data is default-deny; this
 * is where the owner grants or revokes scopes. The ledger is append-only
 * on the backend (grants/revokes are recorded, never edited).
 *
 * Phone-first: 44px+ touch targets, single column, no hover-dependent UI.
 */
export function IdentitySection() {
  const [active, setActive] = useState<string[]>([])
  const [known, setKnown] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [busyScope, setBusyScope] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const load = useCallback(async () => {
    const data = await fetchIdentityScopes()
    setActive(data.active)
    setKnown(data.known_scopes)
  }, [])

  useEffect(() => {
    ;(async () => {
      try {
        await load()
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to load identity scopes')
      } finally {
        setLoading(false)
      }
    })()
  }, [load])

  const toggle = async (scope: string, granted: boolean) => {
    setError(null)
    setMessage(null)
    setBusyScope(scope)
    try {
      const next = await changeIdentityScope(scope, granted ? 'revoke' : 'grant', 'Settings → Identity')
      setActive(next)
      setMessage(granted ? `Revoked ${scope}.` : `Granted ${scope}.`)
    } catch (e) {
      setError(e instanceof Error ? e.message : `Failed to update ${scope}`)
    } finally {
      setBusyScope(null)
    }
  }

  const scopeNames = Object.keys(known).sort()
  // train:self first — it's the gate for the whole training loop.
  scopeNames.sort((a, b) => {
    if (a === 'train:self') return -1
    if (b === 'train:self') return 1
    return a.localeCompare(b)
  })

  return (
    <section
      id="identity"
      aria-label="Identity consent scopes"
      className="rounded-xl border border-slate-600/80 bg-slate-800/40 p-5 space-y-3"
    >
      <div>
        <h2 className="text-lg font-medium text-slate-100">Identity</h2>
        <p className="text-sm text-slate-400 mt-1">
          Consent scopes for your identity license. Everything is denied by default —
          grant a scope to let Zenaf use your data that way. Revoking stops future use.
          Every change is written to an append-only ledger.
        </p>
      </div>
      {loading ? <p className="text-sm text-slate-400">Loading…</p> : null}
      {!loading && scopeNames.length === 0 && !error ? (
        <p className="text-sm text-slate-400">No consent scopes known.</p>
      ) : null}
      {!loading
        ? scopeNames.map((scope) => {
            const granted = active.includes(scope)
            const busy = busyScope === scope
            return (
              <div
                key={scope}
                className="rounded-lg border border-slate-700 bg-slate-900/40 p-3 flex items-start justify-between gap-3"
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium text-slate-200 font-mono">{scope}</p>
                  <p className="text-xs text-slate-500 mt-0.5 leading-relaxed">{known[scope]}</p>
                  <p className="text-xs mt-1">
                    <span
                      className={
                        granted ? 'text-emerald-400' : 'text-slate-500'
                      }
                    >
                      {granted ? 'Granted' : 'Not granted'}
                    </span>
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => void toggle(scope, granted)}
                  disabled={busy}
                  aria-pressed={granted}
                  aria-label={`${granted ? 'Revoke' : 'Grant'} ${scope}`}
                  className={`shrink-0 min-h-[44px] min-w-[88px] px-4 rounded-lg text-sm font-medium transition-colors disabled:opacity-50 ${
                    granted
                      ? 'bg-slate-700 text-slate-200 hover:bg-slate-600'
                      : 'bg-yellow-600/80 text-stone-950 hover:bg-yellow-500/80'
                  }`}
                >
                  {busy ? '…' : granted ? 'Revoke' : 'Grant'}
                </button>
              </div>
            )
          })
        : null}
      {message ? <p className="text-xs text-emerald-400">{message}</p> : null}
      {error ? <p className="text-xs text-red-300">{error}</p> : null}
    </section>
  )
}
