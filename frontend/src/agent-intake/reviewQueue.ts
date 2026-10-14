/**
 * Review-queue badge: how many connected agents await review.
 * Returns the count, or null when the queue can't be read (signed out,
 * offline, server error) — the badge simply hides instead of erroring.
 */
export async function fetchPendingReviewCount(apiBase: string): Promise<number | null> {
  try {
    const r = await fetch(`${apiBase}/agents/pending`)
    if (!r.ok) return null
    const data = await r.json().catch(() => null)
    return Array.isArray(data) ? data.length : null
  } catch {
    return null
  }
}
