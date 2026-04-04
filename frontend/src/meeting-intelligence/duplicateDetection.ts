/**
 * Simple string similarity for duplicate detection during review.
 * Used to suggest "Possible match" when a staged item resembles an existing entity.
 */

function normalize(s: string): string {
  return s
    .toLowerCase()
    .trim()
    .replace(/\s+/g, ' ')
}

/** Dice coefficient on word tokens (0–1). Exact match returns 1. */
export function titleSimilarity(a: string, b: string): number {
  const na = normalize(a)
  const nb = normalize(b)
  if (na === nb) return 1
  if (!na || !nb) return 0
  const wordsA = new Set(na.split(/\s+/).filter(Boolean))
  const wordsB = new Set(nb.split(/\s+/).filter(Boolean))
  let intersection = 0
  for (const w of wordsA) {
    if (wordsB.has(w)) intersection++
  }
  const total = wordsA.size + wordsB.size
  if (total === 0) return 0
  return (2 * intersection) / total
}

export interface CandidateWithTitle {
  id: string
  title: string
}

/** Find the best matching candidate by title similarity, if above threshold. */
export function findBestMatch(
  title: string,
  candidates: CandidateWithTitle[],
  threshold: number = 0.5
): { id: string; title: string; score: number } | null {
  if (!title?.trim() || candidates.length === 0) return null
  let best: { id: string; title: string; score: number } | null = null
  for (const c of candidates) {
    const score = titleSimilarity(title, c.title)
    if (score >= threshold && (!best || score > best.score)) {
      best = { id: c.id, title: c.title, score }
    }
  }
  return best
}
