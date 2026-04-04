/**
 * Lightweight heuristic topic segmentation for meeting transcripts.
 * Splits on paragraph breaks, speaker labels, and length to keep chunks manageable.
 */

import type { SegmentedTranscript, TranscriptSegment } from './types'

const nanoid = () => `seg-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 9)}`

/** Max chars per segment when splitting by length (target; may be exceeded for a single paragraph). */
const MAX_SEGMENT_CHARS = 4000

/**
 * Extract speaker hints from a chunk of text (lines that look like "Name:" or "Name -").
 */
function detectSpeakerHints(text: string): string[] {
  const seen = new Set<string>()
  const hints: string[] = []
  for (const line of text.split(/\r?\n/)) {
    const m = line.trim().match(/^([A-Za-z][A-Za-z0-9_\s\-\.]+)\s*[\:\-]/)
    if (m) {
      const name = m[1].trim()
      if (name.length > 0 && name.length < 80 && !seen.has(name)) {
        seen.add(name)
        hints.push(name)
      }
    }
  }
  return hints
}

/**
 * Best-effort title from first line or first sentence (trimmed, capped).
 */
function firstLineOrSentence(text: string, maxLen = 80): string {
  const t = text.trim()
  if (!t) return ''
  const firstLine = t.split(/\r?\n/)[0]?.trim() ?? ''
  const firstSentence = firstLine.split(/[.!?]\s+/)[0]?.trim() ?? firstLine
  const candidate = firstSentence || firstLine
  return candidate.length > maxLen ? candidate.slice(0, maxLen) + '…' : candidate
}

/**
 * Segment transcript using simple heuristics:
 * - Split on large paragraph breaks (double newline or more)
 * - Split on length so huge transcripts become manageable chunks
 * - Preserve startOffset/endOffset into the original transcript
 */
export function segmentTranscript(notes: string): SegmentedTranscript {
  const text = (notes ?? '').trim()
  if (!text) {
    return { segments: [] }
  }

  // Find paragraph boundaries (start index of each paragraph) by scanning for \n\s*\n+
  const paraStarts: number[] = [0]
  const re = /\n\s*\n+/g
  let m: RegExpExecArray | null
  while ((m = re.exec(text)) !== null) {
    paraStarts.push(m.index + m[0].length)
  }

  const segments: TranscriptSegment[] = []
  let bufferStart = paraStarts[0]!
  let bufferEnd = bufferStart
  let combined = ''

  for (let i = 0; i < paraStarts.length; i++) {
    const pStart = paraStarts[i]!
    const pEndExcl = i + 1 < paraStarts.length ? paraStarts[i + 1]! : text.length
    const paraText = text.slice(pStart, pEndExcl).trim()
    if (!paraText) continue
    const nextCombined = combined ? combined + '\n\n' + paraText : paraText
    if (combined.length > 0 && nextCombined.length > MAX_SEGMENT_CHARS) {
      const segmentText = text.slice(bufferStart, bufferEnd).trim()
      if (segmentText) {
        segments.push({
          id: nanoid(),
          title: firstLineOrSentence(segmentText),
          startOffset: bufferStart,
          endOffset: bufferEnd,
          text: segmentText,
          speakerHints: detectSpeakerHints(segmentText).length > 0 ? detectSpeakerHints(segmentText) : undefined,
        })
      }
      bufferStart = pStart
      combined = paraText
    } else {
      combined = nextCombined
    }
    bufferEnd = pEndExcl
  }

  if (combined) {
    const segmentText = text.slice(bufferStart, bufferEnd).trim()
    if (segmentText) {
      segments.push({
        id: nanoid(),
        title: firstLineOrSentence(segmentText),
        startOffset: bufferStart,
        endOffset: bufferEnd,
        text: segmentText,
        speakerHints: detectSpeakerHints(segmentText).length > 0 ? detectSpeakerHints(segmentText) : undefined,
      })
    }
  }

  if (segments.length === 0) {
    segments.push({
      id: nanoid(),
      title: firstLineOrSentence(text),
      startOffset: 0,
      endOffset: text.length,
      text,
      speakerHints: detectSpeakerHints(text).length > 0 ? detectSpeakerHints(text) : undefined,
    })
  }

  return { segments }
}
