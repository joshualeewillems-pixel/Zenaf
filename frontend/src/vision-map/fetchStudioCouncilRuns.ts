import type { StudioCouncilRunRow } from './studioCouncilTypes'

/** Admin-only; returns [] on 401/403 or error (map stays usable). */
export async function fetchStudioCouncilRuns(limit = 50): Promise<StudioCouncilRunRow[]> {
  try {
    const res = await fetch(`/studio/council/recent-runs?limit=${limit}`, { credentials: 'include' })
    if (res.status === 401 || res.status === 403) return []
    if (!res.ok) return []
    const j = (await res.json()) as { items?: unknown }
    return Array.isArray(j.items) ? (j.items as StudioCouncilRunRow[]) : []
  } catch {
    return []
  }
}
