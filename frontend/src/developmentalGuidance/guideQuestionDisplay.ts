/**
 * Structured question copy + origin grouping for in-thread guide stacks.
 * Derives user-facing questions from existing guide bodies when not set on promptSignal.
 */
import type { GuideQuestionOrigin, GuideThreadMessage } from './guideEntityStack'

export type { GuideQuestionOrigin } from './guideEntityStack'

/** Display order for grouped sections in the stack panel. */
export const GUIDE_QUESTION_ORIGIN_ORDER: GuideQuestionOrigin[] = [
  'framing',
  'clarification',
  'risks',
  'drift_change',
  'execution',
]

export const GUIDE_QUESTION_ORIGIN_LABEL: Record<GuideQuestionOrigin, string> = {
  framing: 'Framing',
  clarification: 'Clarification',
  risks: 'Risks',
  drift_change: 'Change / drift',
  execution: 'Execution',
}

const CANNED: Record<GuideQuestionOrigin, string> = {
  framing: 'What one-sentence problem and boundary will keep this from staying vague?',
  clarification: 'What do you want to figure out or decide next?',
  risks: 'Where might this stall or break down?',
  drift_change: 'Has anything recently shifted that changes the approach?',
  execution: 'What is the smallest next move that would make progress?',
}

function normalizeLine(s: string): string {
  return s.replace(/\*\*/g, '').replace(/^[\-*•]\s*/, '').trim()
}

/** Last non-empty line that contains a question mark (guide bodies often end with the ask). */
function extractLastQuestionLine(text: string): string | null {
  const lines = text.split('\n').map((l) => l.trim()).filter((l) => l.length > 0)
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i]!
    if (line.includes('?')) {
      const n = normalizeLine(line)
      if (n.length > 0) return n.endsWith('?') ? n : `${n}?`
    }
  }
  const q = text.lastIndexOf('?')
  if (q < 0) return null
  const slice = text.slice(Math.max(0, q - 220), q + 1).trim()
  const oneLine = slice.split('\n').pop() ?? slice
  const n = normalizeLine(oneLine)
  return n.length > 0 ? n : null
}

/** Heuristic origin from body text + optional position in a multi-part seed. */
export function inferGuideQuestionOrigin(content: string, seedIndex: number): GuideQuestionOrigin {
  const head = content.slice(0, 1200).toLowerCase()
  if (head.includes('possible sticking') || head.includes('sticking points')) return 'risks'
  if (
    head.includes('review pass') ||
    head.includes('recent review') ||
    head.includes('changed the answer') ||
    head.includes('teacher') && head.includes('review')
  ) {
    return 'drift_change'
  }
  if (
    head.includes('next step') ||
    head.includes('deliverable') ||
    head.includes('execution') ||
    head.includes('ship') ||
    head.includes('timeline')
  ) {
    return 'execution'
  }
  if (head.includes('what do you want') || head.includes('figure out') || head.includes('decide while')) {
    return 'clarification'
  }
  if (seedIndex === 0) return 'framing'
  return 'clarification'
}

export function deriveGuideQuestionText(content: string, origin: GuideQuestionOrigin): string {
  const lastQ = extractLastQuestionLine(content)
  if (lastQ && lastQ.length <= 220 && !looksLikeInternalHeading(lastQ)) {
    return lastQ
  }
  if (origin === 'risks') return CANNED.risks
  if (origin === 'drift_change') return CANNED.drift_change
  if (origin === 'execution') return CANNED.execution
  if (origin === 'clarification') {
    const q = extractLastQuestionLine(content)
    if (q && q.length <= 220) return q
    return CANNED.clarification
  }
  const q = extractLastQuestionLine(content)
  if (q && q.length <= 220) return q
  return CANNED.framing
}

function looksLikeInternalHeading(s: string): boolean {
  const t = s.toLowerCase()
  return t.includes('possible sticking') || t.includes('review pass') || t.includes('from your plan data')
}

/** Map inject / preview copy to a single conversational question. */
export function deriveInjectPreviewQuestionText(content: string): string {
  const lower = content.slice(0, 2000).toLowerCase()
  if (lower.includes('what might deserve attention')) {
    return 'What might deserve your attention on this view right now?'
  }
  if (lower.includes('angles to consider')) {
    return 'Which angle is most useful to examine first?'
  }
  const q = extractLastQuestionLine(content)
  if (q && q.length <= 220 && !looksLikeInternalHeading(q)) return q
  return 'What is the most important thing to clarify before you move on?'
}

export function inferInjectPreviewOrigin(content: string): GuideQuestionOrigin {
  const lower = content.slice(0, 1500).toLowerCase()
  if (lower.includes('angles to consider') || lower.includes('hypotheses')) return 'risks'
  if (lower.includes('what might deserve')) return 'framing'
  return 'framing'
}

export function resolveGuideQuestionMeta(
  m: GuideThreadMessage,
  seedIndexFallback = 0,
): { origin: GuideQuestionOrigin; questionText: string } {
  const origin =
    m.promptSignal?.questionOrigin ??
    inferGuideQuestionOrigin(m.content, seedIndexFallback)
  const questionText =
    m.promptSignal?.questionText ?? deriveGuideQuestionText(m.content, origin)
  return { origin, questionText }
}

/** Short council input prefill when the user focuses a structured question. */
export function councilPrefillForGuideQuestion(questionText: string): string {
  const q = questionText.trim()
  if (!q) return 'Exploring: '
  return q.endsWith('?') ? `Exploring: ${q}\n\n` : `Exploring: ${q} —\n\n`
}

/** Per-row metadata when map seed emits multiple guide bodies under one canonical prompt id. */
export function metaForSeededGuideContent(content: string, index: number, canonicalPromptId: string) {
  const origin = inferGuideQuestionOrigin(content, index)
  const questionText = deriveGuideQuestionText(content, origin)
  return {
    origin,
    questionText,
    stackRowId: `${canonicalPromptId}:row:${index}`,
  }
}
