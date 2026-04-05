/**
 * Canonical funnel for **trace emission** and **POST /run routing_context** assembly (Sprint 1 scaffold).
 *
 * Governed by: docs/01_TRUTH/UTILITY_INFRASTRUCTURE_LAWS.md (Law 2).
 *
 * **Cautious scope:** Delegates to existing builders where they already exist. No blind refactors.
 * Extend the `SystemRunRoutingSpec` union as Map / Radar / other seams get first-class builders.
 */

import { contentRunRoutingContext } from '../content/contentRoutingContext'
import type { VeEvaluateActionIntent } from '../vision-execution/veRunRoutingContext'
import { visionExecutionEvaluateRouting } from '../vision-execution/veRunRoutingContext'
import { createAiActionTrace } from './traceHelpers'
import type { AiActionTrace } from './types'
import { pushAiActionTrace } from './traceSink'
import { buildWorkspaceRunRoutingContext, type WorkspaceRunRoutingContextPayload } from './workspaceRunWithTrace'

/** Discriminated specs for routing payloads that already have dedicated builders. */
export type SystemRunRoutingSpec =
  | { channel: 'workspace'; actionIntent: string; streaming: boolean }
  | { channel: 'content'; actionIntent: string }
  | { channel: 'vision_execution_evaluate'; actionIntent: VeEvaluateActionIntent }

export type SystemRunRoutingPayload =
  | WorkspaceRunRoutingContextPayload
  | ReturnType<typeof contentRunRoutingContext>
  | ReturnType<typeof visionExecutionEvaluateRouting>

/**
 * Build a `routing_context`-shaped payload for the workspace/content/VE evaluate seams.
 * TODO (sprint follow-up): vision-map council seed, radar drill-down, intake, settings test routes.
 */
export function buildSystemRoutingContext(spec: SystemRunRoutingSpec): SystemRunRoutingPayload {
  switch (spec.channel) {
    case 'workspace':
      return buildWorkspaceRunRoutingContext(spec.actionIntent, spec.streaming)
    case 'content':
      return contentRunRoutingContext(spec.actionIntent)
    case 'vision_execution_evaluate':
      return visionExecutionEvaluateRouting(spec.actionIntent)
    default: {
      const _exhaustive: never = spec
      return _exhaustive
    }
  }
}

/**
 * Single entry point for **new** call sites: `createAiActionTrace` + `pushAiActionTrace`.
 * Pass the **full** `createAiActionTrace` partial (surface, action_kind, subject_*, input_snapshot, …).
 * No fake trace shapes — this keeps the build honest.
 */
export function emitSystemTrace(partial: Parameters<typeof createAiActionTrace>[0]): AiActionTrace {
  const trace = createAiActionTrace(partial)
  pushAiActionTrace(trace)
  return trace
}
