/**
 * Optional `routing_context` on Vision Execution evaluate routes — same execution-policy seam as `POST /run`.
 * Intents align with `config/ai_execution_policy.json` `overrides_by_action_intent`.
 */

import { readPrivacyMode } from '../ai-actions/privacyModeBridge'

export const VE_EVALUATE_ACTION_INTENTS = {
  idea_evaluate: 'idea_evaluate',
  initiative_evaluate: 'initiative_evaluate',
} as const

export type VeEvaluateActionIntent = (typeof VE_EVALUATE_ACTION_INTENTS)[keyof typeof VE_EVALUATE_ACTION_INTENTS]

/** Stable substrate: `surface` must stay `vision_execution` for policy + traces. */
export function visionExecutionEvaluateRouting(actionIntent: VeEvaluateActionIntent) {
  return {
    surface: 'vision_execution' as const,
    action_kind: 'structured_evaluation' as const,
    action_intent: actionIntent,
    streaming: false as const,
    privacy_mode: readPrivacyMode(),
  }
}
