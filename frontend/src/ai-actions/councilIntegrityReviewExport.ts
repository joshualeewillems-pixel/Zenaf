/**
 * Export recent council runs that include integrity review samples (in-memory ring only).
 */

import type { AiActionTrace, CouncilSynthesisCombinedSummary } from './types'
import { WORKSPACE_ACTION_INTENTS } from './workspaceRunWithTrace'
import { getRecentAiActionTraces } from './traceSink'

export type HumanAssessmentClassification = 'grounded' | 'interpretive' | 'weak' | 'unreliable'

export type CouncilIntegrityHumanAssessment = {
  classification: HumanAssessmentClassification | null
  matches_system: boolean | null
  notes: string
}

export type CouncilIntegrityReviewExportV1 = {
  export_schema: 'council_integrity_review_export_v1'
  exported_at: string
  /** Max ~32 traces total in ring; only a subset are council + review. */
  notes: string
  sample_count: number
  samples: Array<{
    trace_id: string
    created_at: string
    model_used: string | null
    input_snapshot: string
    /** Full council transcript (trimmed by trace cap). */
    output: string
    review: NonNullable<AiActionTrace['council_integrity_review']>
    /** Reviewer-filled field; exported as blank template for lightweight manual comparison. */
    human_assessment: CouncilIntegrityHumanAssessment
  }>
}

const COMBINED_SUMMARY_KEYS: CouncilSynthesisCombinedSummary[] = [
  'grounded',
  'grounded_but_interpretive',
  'weak_support',
  'unreliable',
]

/** In-memory counts by `combined_summary` for the settings review strip. */
export function getCouncilIntegrityReviewBreakdown(): Record<CouncilSynthesisCombinedSummary, number> {
  const traces = collectCouncilIntegrityReviewTraces()
  const out: Record<CouncilSynthesisCombinedSummary, number> = {
    grounded: 0,
    grounded_but_interpretive: 0,
    weak_support: 0,
    unreliable: 0,
  }
  for (const t of traces) {
    const s = t.council_integrity_review?.combined_summary
    if (s && COMBINED_SUMMARY_KEYS.includes(s)) out[s]++
  }
  return out
}

export function collectCouncilIntegrityReviewTraces(): AiActionTrace[] {
  return getRecentAiActionTraces().filter((t): t is AiActionTrace & { council_integrity_review: NonNullable<AiActionTrace['council_integrity_review']> } => {
    const r = t.council_integrity_review
    return (
      t.action_intent === WORKSPACE_ACTION_INTENTS.council &&
      r != null &&
      r.schema === 'council_integrity_review_v1'
    )
  })
}

export function buildCouncilIntegrityReviewExportJson(): string {
  const traces = collectCouncilIntegrityReviewTraces()
  const payload: CouncilIntegrityReviewExportV1 = {
    export_schema: 'council_integrity_review_export_v1',
    exported_at: new Date().toISOString(),
    notes:
      'Client-local only: AI action trace ring (max ~32). Privacy modes may redact output/review text when traces are pushed.',
    sample_count: traces.length,
    samples: traces.map((t) => ({
      trace_id: t.trace_id,
      created_at: t.created_at,
      model_used: t.model_used,
      input_snapshot: t.input_snapshot,
      output: t.output,
      review: t.council_integrity_review!,
      human_assessment: {
        classification: null,
        matches_system: null,
        notes: '',
      },
    })),
  }
  return JSON.stringify(payload, null, 2)
}
