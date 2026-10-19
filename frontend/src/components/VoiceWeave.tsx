import { useEffect, useState } from 'react'

/**
 * Shared voice-color + user-weave rendering for council voices.
 *
 * - VOICE_COLORS mirrors local_ai/council/archetypes.py VOICE_COLORS.
 *   The backend /demo/voices endpoint is the source of truth at runtime;
 *   this map is the offline fallback.
 * - WeaveText renders [[u]]...[[/u]] markers (visitor/user words woven into
 *   a voice's reply) as spans in USER_WEAVE_COLOR.
 */

export const VOICE_COLORS: Record<string, string> = {
  mentor: '#c9a86a',
  champion: '#c96a5a',
  guardian: '#7ba889',
  maverick: '#9a7bc9',
  ambassador: '#7aa3b8',
  conductor: '#8a8a93',
  skeptic: '#6b6b76',
}

export const USER_WEAVE_COLOR = '#e8a33d'

export function voiceColor(id: string): string {
  return VOICE_COLORS[(id || '').trim().toLowerCase()] ?? '#8a8a93'
}

export type DemoVoice = {
  id: string
  name: string
  color: string
  frame: string
}

/** Fetch the 7 base voices (id, name, color, frame) from the backend. */
export function useDemoVoices(apiBase: string): DemoVoice[] {
  const [voices, setVoices] = useState<DemoVoice[]>([])
  useEffect(() => {
    let cancelled = false
    fetch(`${apiBase}/demo/voices`)
      .then((r) => (r.ok ? r.json() : []))
      .then((data: DemoVoice[]) => {
        if (!cancelled && Array.isArray(data) && data.length > 0) setVoices(data)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [apiBase])
  return voices
}

const WEAVE_RE = /\[\[u\]\]([\s\S]*?)\[\[\/u\]\]/g
/**
 * Model-emitted malformed closings ([/u]], [/[/u]]). The canonical close is
 * a third alternative so it matches at its earlier position and passes
 * through untouched — mirroring local_ai/conversation/weave.py.
 */
const WEAVE_CLOSE_RE = /\[\/\[\/u\]\]|\[\/u\]\]|\[\[\/u\]\]/g

/** Replace malformed closing markers with the canonical [[/u]]. */
export function normalizeWeave(text: string): string {
  return text.replace(WEAVE_CLOSE_RE, '[[/u]]')
}

/**
 * Render text with [[u]]...[[/u]] spans highlighted as the user's woven words.
 * Malformed closings the model emits ([/u]], [/[/u]]) are normalized first;
 * a marker with no recognizable close is left literal (truly malformed).
 */
export function WeaveText({ text, className }: { text: string; className?: string }) {
  const src = normalizeWeave(text)
  const parts: { key: number; weave: boolean; content: string }[] = []
  let last = 0
  let m: RegExpExecArray | null
  let k = 0
  WEAVE_RE.lastIndex = 0
  while ((m = WEAVE_RE.exec(src)) !== null) {
    if (m.index > last) parts.push({ key: k++, weave: false, content: src.slice(last, m.index) })
    parts.push({ key: k++, weave: true, content: m[1] })
    last = m.index + m[0].length
  }
  if (last < src.length) parts.push({ key: k++, weave: false, content: src.slice(last) })

  return (
    <span className={className} style={{ whiteSpace: 'pre-wrap' }}>
      {parts.map((p) =>
        p.weave ? (
          <span key={p.key} style={{ color: USER_WEAVE_COLOR, fontWeight: 600 }}>
            {p.content}
          </span>
        ) : (
          <span key={p.key}>{p.content}</span>
        ),
      )}
    </span>
  )
}
