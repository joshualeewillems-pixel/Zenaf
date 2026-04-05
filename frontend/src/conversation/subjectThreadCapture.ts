/**
 * Session-only, lightweight extraction inspired by meeting/deliverable capture docs.
 * Heuristic — not a second chat center; feeds the single thread + subject handoff review.
 */

export type PendingThreadSuggestion = {
  id: string
  text: string
  subjectKey: string
}

/** Split on sentence boundaries (rough). */
function sentences(text: string): string[] {
  return text
    .split(/(?<=[.!?])\s+|\n+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 14)
}

/** Stronger signals: decisions / carry-forward, not generic planning tone. */
const ACTION_HINTS: RegExp[] = [
  /\bsave this\b/i,
  /\bremember this\b/i,
  /\bdon't forget\b/i,
  /\bkeep in mind\b/i,
  /\btodo:?\s/i,
  /\bnext step:?\s/i,
  /\bfollow[- ]?up:?\s/i,
  /\bmaybe split\b/i,
  /\bsplit (?:this|it) into\b/i,
  /\bsounds? like a blocker\b/i,
  /\b(?:make|create|add) (?:this |a |an )?task\b/i,
  /\bsave (?:this |that )?to notes?\b/i,
  /\bput (?:this |that )?in notes?\b/i,
  /\bbecome(?:s)? (?:a |an )?(?:project|initiative|task)s?\b/i,
  /\bthree projects\b/i,
  /\bbreak (?:this |it )?into\b/i,
]

/** Drop known assistant templates even if another hint accidentally matches. */
const BOILERPLATE_REJECT: RegExp[] = [
  /\btoday,?\s+we\s+should/i,
  /\bwe\s+should\s+focus\b/i,
  /\bactionable steps?\s+from\s+your\s+current\b/i,
  /\byour\s+current\s+inverse\s+risk\b/i,
]

const ASSISTANT_HANDOFF_TAGS = /\b(SAVE_CANDIDATE|HANDOFF_CANDIDATE)\b/i

export function normalizeSuggestionFingerprint(text: string): string {
  return text
    .toLowerCase()
    .trim()
    .replace(/\s+/g, ' ')
    .replace(/[^a-z0-9\s]/gi, '')
    .replace(/\s+/g, ' ')
    .trim()
}

/** User lines are scraped by default; agent lines only when explicitly tagged. */
export function shouldScrapeMessageForSuggestions(role: string, content: string): boolean {
  if (role === 'user') return true
  if (role !== 'agent') return false
  return ASSISTANT_HANDOFF_TAGS.test(content)
}

/** Strip tagging tokens before sentence matching (agent messages only). */
export function contentForSuggestionExtraction(role: string, content: string, maxChars = 8000): string {
  let t = content.slice(0, maxChars)
  if (role === 'agent') {
    t = t.replace(/\b(SAVE_CANDIDATE|HANDOFF_CANDIDATE)\s*:?\s*/gi, ' ').replace(/\s+/g, ' ').trim()
  }
  return t
}

function isBoilerplateSentence(s: string): boolean {
  return BOILERPLATE_REJECT.some((r) => r.test(s))
}

export function extractConversationSuggestions(text: string): string[] {
  const out: string[] = []
  for (const s of sentences(text)) {
    if (isBoilerplateSentence(s)) continue
    if (ACTION_HINTS.some((h) => h.test(s))) {
      const clipped = s.length > 320 ? `${s.slice(0, 317)}…` : s
      out.push(clipped)
    }
  }
  const bullets = text.split('\n').filter((l) => {
    const t = l.trim()
    if (!/^[-*]\s+/.test(t) || t.length <= 20) return false
    if (isBoilerplateSentence(t)) return false
    return ACTION_HINTS.some((h) => h.test(t))
  })
  for (const b of bullets) {
    const clipped = b.replace(/^[-*]\s+/, '').trim().slice(0, 320)
    if (clipped && !isBoilerplateSentence(clipped)) out.push(clipped)
  }
  const seen = new Set<string>()
  const deduped: string[] = []
  for (const x of out.map((raw) => raw.replace(/\s+/g, ' ').trim())) {
    const fp = normalizeSuggestionFingerprint(x)
    if (!fp || seen.has(fp)) continue
    seen.add(fp)
    deduped.push(x)
  }
  return deduped.slice(0, 6)
}

export function parseSubjectEntityRef(
  subjectKey: string,
): { entity_type: string; entity_id: string } | null {
  const i = subjectKey.indexOf(':')
  if (i <= 0) return null
  const entity_type = subjectKey.slice(0, i).toLowerCase()
  const entity_id = subjectKey.slice(i + 1)
  if (!entity_id || entity_type === 'workspace') return null
  if (!['idea', 'initiative', 'project', 'task'].includes(entity_type)) return null
  return { entity_type, entity_id }
}
