/**
 * Execution policy (Phase 0) — mirrors `local_ai/execution_policy/types.py` conceptually.
 * Client cannot read `local_ai.config` or env; legacy council env is server-only.
 */

import type { AiActionKind, ZenafSurface } from '../types'

export type LegacyProviderRoute = 'default' | 'council'

export type ActionRoutingContext = {
  surface: ZenafSurface
  action_kind: AiActionKind
  action_intent?: string | null
  streaming?: boolean | null
  sensitivity?: string | null
}

export type ProviderModelRef = {
  provider: string
  model: string
}

export type ExecutionPolicyResolution = {
  primary: ProviderModelRef
  fallback_chain: ProviderModelRef[]
  allow_cloud: boolean
  flags: Record<string, unknown>
}

/**
 * Optional privacy layer merged after policy JSON (no persistence in Phase 1).
 * Omit or use defaults for permissive behavior.
 */
export type PrivacyPolicyInput = {
  require_local: boolean
  allow_cloud_fallback: boolean
  /** If non-empty, only these provider ids are allowed. */
  approved_providers?: string[] | undefined
  /** Per-provider model allowlist; if a provider key has a non-empty list, model must be included. */
  approved_models?: Record<string, string[]> | undefined
}

/** JSON policy document (subset used by resolver). */
export type ExecutionPolicyConfigJson = {
  schema_version?: number
  global_priority?: string
  defaults?: Record<string, unknown>
  priority_profiles?: Record<string, Record<string, unknown>>
  overrides_by_action_kind?: Record<string, Record<string, unknown>>
  overrides_by_action_intent?: Record<string, Record<string, unknown>>
}
