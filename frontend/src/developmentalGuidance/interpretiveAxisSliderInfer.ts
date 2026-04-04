/**
 * Maps existing natural-language axis tilt strings to slider dot positions — UI only.
 * No scores persisted; heuristic read of copy already emitted by deriveInterpretiveAxes.
 */

export type AxisVisualEmphasis = 'neutral' | 'soft' | 'strong'

/** Parse canonical names like "clarity ↔ ambiguity". */
export function parseInterpretiveAxisName(name: string): { left: string; right: string } | null {
  const trimmed = name.trim()
  const parts = trimmed.split(/\s*↔\s*/)
  if (parts.length !== 2) return null
  const left = parts[0]!.trim()
  const right = parts[1]!.trim()
  if (!left || !right) return null
  return { left, right }
}

function tokensForPole(label: string): string[] {
  return label
    .toLowerCase()
    .split(/[\s/]+/)
    .map((s) => s.replace(/-+$/g, ''))
    .filter((s) => s.length >= 3)
}

/** Which pole the tilt language favors: -1 left, 0 unclear, 1 right. */
export function inferAxisDirection(tilt: string, leftLabel: string, rightLabel: string): -1 | 0 | 1 {
  const t = tilt.toLowerCase()
  const l = leftLabel.toLowerCase()
  const r = rightLabel.toLowerCase()

  // Phrase-level hints (avoid short-token false positives)
  if (t.includes('explorat')) return 1
  if (t.includes('more structure') || /\bstructure might reduce\b/.test(t)) return -1
  if (t.includes('drop-off') || t.includes('drop off')) return 1
  if (t.includes('holding ambiguity') || /\bleaning toward ambiguity\b/.test(t) || /\btoward ambiguity\b/.test(t))
    return 1
  if (r.includes('fragmentation') && (t.includes('pulled apart') || t.includes('looked uneven'))) return 1

  let score = 0
  for (const tok of tokensForPole(rightLabel)) {
    if (tok.length >= 4 && t.includes(tok)) score += 1
  }
  for (const tok of tokensForPole(leftLabel)) {
    if (tok.length >= 4 && t.includes(tok)) score -= 1
  }

  // Hyphenated left label: "follow-through"
  if (l.includes('follow') && t.includes('follow-through')) score -= 1
  if (l.includes('follow') && /\bfollow[-\s]?through\b/.test(t)) score -= 1

  if (score > 0) return 1
  if (score < 0) return -1

  const toward = t.match(/(?:toward|leaning toward)\s+([a-z][a-z\s-]{2,32})/i)
  if (toward) {
    const phrase = toward[1]!.trim().toLowerCase()
    if (phrase.length >= 3 && (r.includes(phrase) || tokensForPole(rightLabel).some((x) => phrase.startsWith(x) || x.startsWith(phrase))))
      return 1
    if (phrase.length >= 3 && (l.includes(phrase) || tokensForPole(leftLabel).some((x) => phrase.startsWith(x) || x.startsWith(phrase))))
      return -1
  }

  return 0
}

export function inferAxisVisualEmphasis(tilt: string): AxisVisualEmphasis {
  const t = tilt.toLowerCase()
  if (
    /\b(several|uneven|looked uneven|not lining up|may not be lining up|weak integrity|pulled apart)\b/.test(t)
  ) {
    return 'strong'
  }
  if (
    /\b(tentative|a little longer|a bit\b|advisory only|possible read|hypothesis,|may match|might reduce)\b/.test(t)
  ) {
    return 'soft'
  }
  return 'soft'
}

/**
 * Dot position as % from left (0 = left pole, 100 = right pole).
 * slight ≈ 40/60, strong ≈ 25/75; center = 50.
 */
export function inferInterpretiveAxisSlider(
  tilt: string,
  leftLabel: string,
  rightLabel: string,
): { pct: number; emphasis: AxisVisualEmphasis } {
  const dir = inferAxisDirection(tilt, leftLabel, rightLabel)
  if (dir === 0) return { pct: 50, emphasis: 'neutral' }

  const emphasis = inferAxisVisualEmphasis(tilt)
  const strong = emphasis === 'strong'

  if (dir === 1) {
    return { pct: strong ? 75 : 60, emphasis: strong ? 'strong' : 'soft' }
  }
  return { pct: strong ? 25 : 40, emphasis: strong ? 'strong' : 'soft' }
}
