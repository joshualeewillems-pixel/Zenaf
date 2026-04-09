import type {
  AiActionTrace,
  AiActionKind,
  AiUserOutcome,
  ZenafSurface,
  CouncilIntegrityReviewSample,
} from './types'

function randomId(): string {
  try {
    return crypto.randomUUID()
  } catch {
    return `tr_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 9)}`
  }
}

export function createAiActionTrace(partial: {
  surface: ZenafSurface
  action_kind: AiActionKind
  subject_type: string
  subject_id: string
  field_key?: string | null
  action_intent?: string | null
  input_snapshot: string
  model_used?: string | null
  provider_used?: string | null
  prompt_version?: string | null
  output?: string
  user_outcome?: AiUserOutcome
  council_integrity_review?: CouncilIntegrityReviewSample | null
}): AiActionTrace {
  const now = new Date().toISOString()
  const review = partial.council_integrity_review
  return {
    trace_id: randomId(),
    surface: partial.surface,
    action_kind: partial.action_kind,
    action_intent: partial.action_intent ?? null,
    subject_type: partial.subject_type,
    subject_id: partial.subject_id,
    field_key: partial.field_key ?? null,
    input_snapshot: partial.input_snapshot.slice(0, 8000),
    model_used: partial.model_used ?? null,
    provider_used: partial.provider_used ?? null,
    prompt_version: partial.prompt_version ?? null,
    output: (partial.output ?? '').slice(0, 12000),
    user_outcome: partial.user_outcome ?? 'none',
    created_at: now,
    ...(review
      ? {
          council_integrity_review: {
            ...review,
            synthesis_text: review.synthesis_text.slice(0, 8000),
          },
        }
      : {}),
  }
}

export function withTraceOutput(
  t: AiActionTrace,
  output: string,
  model_used?: string | null,
  prompt_version?: string | null,
): AiActionTrace {
  return {
    ...t,
    output: output.slice(0, 12000),
    model_used: model_used ?? t.model_used,
    prompt_version: prompt_version ?? t.prompt_version,
  }
}

export function withTraceOutcome(t: AiActionTrace, user_outcome: AiUserOutcome): AiActionTrace {
  return { ...t, user_outcome }
}
