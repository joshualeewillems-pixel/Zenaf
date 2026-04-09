import type { NodeInterpretation } from './unifiedNodeAssessmentTypes'

/** Heuristic: user-facing string is phrased as a question (clarify_first contract). */
export function interpretationTextLooksLikeQuestion(s: string): boolean {
  const t = s.trim()
  if (!t) return false
  if (t.endsWith('?')) return true
  return /^(what|who|which|whose|whom|how|when|where|why|is |are |am |was |were |do |does |did |can |could |would |should |will )\b/i.test(
    t,
  )
}

/** Pairs: [actionLine pattern, chatPrefill pattern that undermines it] */
const PROCEED_UNDERMINE: [RegExp, RegExp][] = [
  [/expand|executable steps|concrete steps|measurable outcomes/i, /\b(don'?t expand|avoid steps|stop planning|no steps|skip execution)\b/i],
  [/sharpen|definition|clarif/i, /\b(skip|avoid) (defin|clarif|scope)\b/i],
  [/summarize|decision-ready|council read/i, /\b(avoid|skip) (decid|summary|council)\b/i],
  [/tensions?|constraints/i, /\b(ignore|dismiss|no) (tension|conflict|tradeoff)\b/i],
]

/**
 * Product invariants for a single node interpretation (tests + optional dev assertions).
 * - clarify_first: chatPrefill must read as a question.
 * - proceed: chatPrefill must not obviously contradict actionLine.
 */
export function collectNodeInterpretationInvariantViolations(inv: NodeInterpretation): string[] {
  const out: string[] = []
  const summary = inv.summary.trim()
  const action = inv.actionLine.trim()
  const prefill = inv.chatPrefill.trim()
  if (!summary) out.push('summary must be non-empty')
  if (!action) out.push('actionLine must be non-empty')
  if (!prefill) out.push('chatPrefill must be non-empty')

  if (inv.stance === 'clarify_first') {
    if (!inv.clarificationQuestion?.trim()) {
      out.push('clarify_first requires clarificationQuestion')
    }
    if (!interpretationTextLooksLikeQuestion(prefill)) {
      out.push('clarify_first requires chatPrefill to be phrased as a question')
    }
    if (inv.clarificationQuestion && !interpretationTextLooksLikeQuestion(inv.clarificationQuestion)) {
      out.push('clarificationQuestion should be phrased as a question')
    }
  }

  if (inv.stance === 'proceed') {
    for (const [actPat, underPat] of PROCEED_UNDERMINE) {
      if (actPat.test(action) && underPat.test(prefill)) {
        out.push('proceed: chatPrefill undermines actionLine')
        break
      }
    }
  }

  return out
}

export function assertNodeInterpretationInvariants(inv: NodeInterpretation): void {
  const v = collectNodeInterpretationInvariantViolations(inv)
  if (v.length) {
    throw new Error(`NodeInterpretation invariant failed: ${v.join('; ')}`)
  }
}
