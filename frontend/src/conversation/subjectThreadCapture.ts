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

const ACTION_HINTS: RegExp[] = [
  /\bwe should\b/i,
  /\bI should\b/i,
  /\bneed to\b/i,
  /\bmaybe split\b/i,
  /\bsplit (?:this|it) into\b/i,
  /\bsounds? like a blocker\b/i,
  /\bblocker\b/i,
  /\b(?:make|create|add) (?:this |a |an )?task\b/i,
  /\bsave (?:this |that )?to notes?\b/i,
  /\bput (?:this |that )?in notes?\b/i,
  /\bbecome(?:s)? (?:a |an )?(?:project|initiative|task)s?\b/i,
  /\bthree projects\b/i,
  /\bbreak (?:this |it )?into\b/i,
]

export function extractConversationSuggestions(text: string): string[] {
  const out: string[] = []
  for (const s of sentences(text)) {
    if (ACTION_HINTS.some((h) => h.test(s))) {
      const clipped = s.length > 320 ? `${s.slice(0, 317)}…` : s
      out.push(clipped)
    }
  }
  const bullets = text.split('\n').filter((l) => {
    const t = l.trim()
    return /^[-*]\s+/.test(t) && t.length > 20 && ACTION_HINTS.some((h) => h.test(t))
  })
  for (const b of bullets) {
    const clipped = b.replace(/^[-*]\s+/, '').trim().slice(0, 320)
    if (clipped) out.push(clipped)
  }
  return [...new Set(out.map((x) => x.replace(/\s+/g, ' ').trim()))].slice(0, 6)
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
