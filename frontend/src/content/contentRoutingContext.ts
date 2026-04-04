/**
 * Optional POST /run routing_context for Content brief generation (Phase 1 seam).
 *
 * **Contract:** Always use `surface: 'content'`, `action_kind: 'structured_evaluation'`, and an
 * `action_intent` from `CONTENT_ACTION_INTENTS` so server policy, `model_used` / `provider_used`,
 * and `emitContentBriefTraceFromRun` hints stay aligned.
 */

import { readPrivacyMode } from '../ai-actions/privacyModeBridge'

export const CONTENT_ACTION_INTENTS = {
  generate_script: 'content_brief_generate_script',
  generate_newsletter: 'content_brief_generate_newsletter',
  regenerate_script: 'content_brief_regenerate_script',
  regenerate_newsletter: 'content_brief_regenerate_newsletter',
} as const

export type ContentActionIntent = (typeof CONTENT_ACTION_INTENTS)[keyof typeof CONTENT_ACTION_INTENTS]

export function contentRunRoutingContext(actionIntent: string) {
  return {
    surface: 'content',
    action_kind: 'structured_evaluation',
    action_intent: actionIntent,
    streaming: false as const,
    privacy_mode: readPrivacyMode(),
  }
}

/** First generate vs regenerate/refine share routing bucket: regen when output already exists or refinement is set. */
export function contentActionIntentForRun(
  outputType: 'script' | 'newsletter',
  opts: { hadPriorOutput: boolean; refinement?: string },
): ContentActionIntent {
  const regen = opts.hadPriorOutput || Boolean(opts.refinement?.trim())
  if (outputType === 'script') {
    return regen ? CONTENT_ACTION_INTENTS.regenerate_script : CONTENT_ACTION_INTENTS.generate_script
  }
  return regen ? CONTENT_ACTION_INTENTS.regenerate_newsletter : CONTENT_ACTION_INTENTS.generate_newsletter
}
