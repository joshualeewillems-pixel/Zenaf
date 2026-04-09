/**
 * Dispatched before {@link ZENAF_VE_FOCUS_INSERT_TEXT}. Listeners that insert into the
 * actual `document.activeElement` (e.g. council reply) must call `preventDefault()` so
 * the transcript is not routed to the last Vision Execution–registered field.
 */
export const ZENAF_VOICE_TRANSCRIPT_DOM_FIRST = 'zenaf-voice-transcript-dom-first'

export type VoiceTranscriptDomFirstDetail = { text: string }

/** Dispatched on `window` to insert text at the captured selection in the matching VE field */
export const ZENAF_VE_FOCUS_INSERT_TEXT = 'zenaf-ve-focus-insert-text'

export type VeFocusInsertTextDetail = {
  entity_type: string
  entity_id: string
  field_key: string
  text: string
  selectionStart: number
  selectionEnd: number
}

export function insertTextAtSelection(s: string, insert: string, start: number, end: number): string {
  const a = Math.max(0, Math.min(Math.floor(start), s.length))
  const b = Math.max(0, Math.min(Math.floor(end), s.length))
  const lo = Math.min(a, b)
  const hi = Math.max(a, b)
  return s.slice(0, lo) + insert + s.slice(hi)
}
