import { useCallback, useEffect, useState } from 'react'
import {
  fetchFrameworkPermissions,
  setFrameworkPause,
  type FrameworkState,
} from './api'

/**
 * The global-pause banner (Rev2 §2.4, C4.2–C4.5): mirrored in Settings
 * and in Review. It renders ONLY while the pause override is set.
 * Plain words, no guilt copy; Resume is one action, the same effort
 * as pausing.
 *
 * Two modes: fed by the surface's state (Settings — pass `state` and
 * `onResume`), or self-fetching (Review — mount bare and it loads its
 * own state). Both read the same record, so the two banners cannot
 * disagree.
 */
export function PauseBanner({
  state,
  onResume,
}: {
  state?: FrameworkState | null
  onResume?: () => void
}) {
  const [ownState, setOwnState] = useState<FrameworkState | null>(null)
  const [resuming, setResuming] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const selfFed = state === undefined

  useEffect(() => {
    if (!selfFed) return
    let cancelled = false
    ;(async () => {
      try {
        const loaded = await fetchFrameworkPermissions()
        if (!cancelled) setOwnState(loaded)
      } catch {
        if (!cancelled) setOwnState(null)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [selfFed])

  const effective = selfFed ? ownState : state
  const paused = effective?.paused ?? false

  const resume = useCallback(async () => {
    if (onResume) {
      onResume()
      return
    }
    setError(null)
    setResuming(true)
    try {
      const resp = await setFrameworkPause(false)
      setOwnState(resp.state)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to resume')
    } finally {
      setResuming(false)
    }
  }, [onResume])

  if (!paused) return null

  return (
    <div className="rounded-lg border border-amber-600/60 bg-amber-900/30 p-3">
      <p className="text-sm text-amber-100">
        Standing behavior is paused — nothing new should start. Work already underway finishes;
        pausing cancels nothing. Your stances are unchanged.
      </p>
      <button
        type="button"
        disabled={resuming}
        onClick={() => void resume()}
        className="mt-2 rounded-lg bg-amber-600 hover:bg-amber-500 disabled:bg-slate-600 px-3 py-1.5 text-sm font-medium text-white"
      >
        {resuming ? 'Resuming…' : 'Resume standing behavior'}
      </button>
      {error ? <p className="text-xs text-red-300 mt-1">{error}</p> : null}
    </div>
  )
}
