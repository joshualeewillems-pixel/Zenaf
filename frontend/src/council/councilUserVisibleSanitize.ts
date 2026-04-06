/**
 * Strip internal protocol / contract copy from council assistant text before UI display.
 * Server contract and integration_commit parsing are unchanged; this is display-only.
 */

const MISSING_DRAFT_NUDGE_RE =
  /\n{2}Thanks for your patience[\s\S]*?Please send your request again[^\n]*/gi

/** Replace backend missing-draft nudge with plain language. */
const FRIENDLY_SAVE_NUDGE =
  "\n\nI couldn't save that to the field yet. Want me to suggest wording you can confirm?"

/** Expand draft tags to visible prose; strip common parser-coaching tails on the same line. */
const DRAFT_VALUE_TAG_RE =
  /\[(?:DRAFT_VALUE):\s*([^\]]+)\](?:\s*(?:is\s+)?required\b[^\n]*|\s*required\s+to\s+(?:save|confirm|parse)[^\n]*)?/gi

/** Model echoes incomplete tags or tag + "required" without a normal payload shape. */
const DRAFT_PROTOCOL_LEAK_RE =
  /\[(?:DRAFT_VALUE)[^\]\n]*(?:\][^\n]{0,200}?(?:\brequired\b|\bmust\s+include\b|\bparser\b)[^\n]*)?/gi

/** Orphan / unclosed draft tag on one line (protocol leak). */
const DRAFT_ORPHAN_LINE_RE = /^\s*\[DRAFT_VALUE[^\]]*$/gim

/**
 * Sanitize assistant markdown/text for the conversation column.
 */
export function sanitizeCouncilAssistantTextForDisplay(raw: string): string {
  let t = raw.replace(MISSING_DRAFT_NUDGE_RE, FRIENDLY_SAVE_NUDGE)
  t = t.replace(DRAFT_VALUE_TAG_RE, (_m, inner: string) => {
    const body = String(inner ?? '').trim()
    return body ? `\n\n${body}\n` : ''
  })
  t = t.replace(DRAFT_PROTOCOL_LEAK_RE, '')
  t = t.replace(DRAFT_ORPHAN_LINE_RE, '')
  t = t.replace(/\n{3,}/g, '\n\n').trim()
  return t
}
