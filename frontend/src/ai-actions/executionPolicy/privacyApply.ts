/**
 * Privacy constraints applied after base execution policy merge.
 * Deterministic; no silent fallback to disallowed providers.
 * @see docs/02_ACTIVE_DESIGN/PRIVACY_MODE_AND_EXECUTION_POLICY.md
 */

import type { ExecutionPolicyResolution, ProviderModelRef, PrivacyPolicyInput } from './types'

export type ExecutionPolicyResolutionResult =
  | { execution_blocked: false; resolution: ExecutionPolicyResolution }
  | { execution_blocked: true; reason: 'privacy_constraints'; detail: string }

/** Tier used for require_local and allow_cloud_fallback on fallbacks. */
export function providerExecutionTier(provider: string): 'local' | 'cloud' {
  const p = String(provider ?? '')
    .trim()
    .toLowerCase()
    .replace(/-/g, '_')
  if (p === 'ollama' || p === 'llamacpp' || p === 'lm_studio' || p === 'local') return 'local'
  return 'cloud'
}

/** Permissive defaults: no filtering until explicit privacy or profile require_local is merged at resolve time. */
export const DEFAULT_PRIVACY_POLICY_INPUT: PrivacyPolicyInput = {
  require_local: false,
  allow_cloud_fallback: true,
  approved_providers: undefined,
  approved_models: undefined,
}

function refPassesAllowlists(ref: ProviderModelRef, privacy: PrivacyPolicyInput): boolean {
  if (privacy.require_local && providerExecutionTier(ref.provider) !== 'local') return false

  const ap = privacy.approved_providers
  if (ap != null && ap.length > 0 && !ap.includes(ref.provider)) return false

  const am = privacy.approved_models
  if (am != null && Object.keys(am).length > 0) {
    const list = am[ref.provider]
    if (list != null && list.length > 0 && !list.includes(ref.model)) return false
  }
  return true
}

/**
 * Apply privacy to a resolved execution plan. Does not mutate the input resolution.
 */
export function applyPrivacyToExecutionResolution(
  res: ExecutionPolicyResolution,
  privacy: PrivacyPolicyInput,
): ExecutionPolicyResolutionResult {
  const ordered: ProviderModelRef[] = [res.primary, ...res.fallback_chain]

  const allowlisted = ordered.filter((r) => refPassesAllowlists(r, privacy))

  const afterCloudFallback: ProviderModelRef[] = []
  for (let i = 0; i < allowlisted.length; i++) {
    const r = allowlisted[i]!
    if (i > 0 && !privacy.allow_cloud_fallback && providerExecutionTier(r.provider) === 'cloud') {
      continue
    }
    afterCloudFallback.push(r)
  }

  if (afterCloudFallback.length === 0) {
    return {
      execution_blocked: true,
      reason: 'privacy_constraints',
      detail: 'No provider/model remains after privacy filtering (require_local, allowlists, or allow_cloud_fallback).',
    }
  }

  const primary = afterCloudFallback[0]!
  const fallback_chain = afterCloudFallback.slice(1)

  /** Policy permission for cloud (not “plan contains cloud”); align with merged allow_cloud_fallback. */
  let allow_cloud = Boolean(res.allow_cloud && privacy.allow_cloud_fallback)
  if (privacy.require_local) allow_cloud = false

  return {
    execution_blocked: false,
    resolution: {
      primary,
      fallback_chain,
      allow_cloud,
      flags: {
        ...res.flags,
        privacy_applied: true,
        privacy_require_local: privacy.require_local,
        privacy_allow_cloud_fallback: privacy.allow_cloud_fallback,
      },
    },
  }
}

/** Merge explicit privacy overrides with profile-driven require_local (explicit wins per field when provided). */
export function mergePrivacyPolicyInput(
  profileRequireLocal: boolean,
  explicit: Partial<PrivacyPolicyInput> | null | undefined,
): PrivacyPolicyInput {
  const e = explicit ?? {}
  return {
    require_local: e.require_local !== undefined ? Boolean(e.require_local) : profileRequireLocal,
    allow_cloud_fallback:
      e.allow_cloud_fallback !== undefined ? Boolean(e.allow_cloud_fallback) : DEFAULT_PRIVACY_POLICY_INPUT.allow_cloud_fallback,
    approved_providers: e.approved_providers !== undefined ? e.approved_providers : DEFAULT_PRIVACY_POLICY_INPUT.approved_providers,
    approved_models: e.approved_models !== undefined ? e.approved_models : DEFAULT_PRIVACY_POLICY_INPUT.approved_models,
  }
}

export function unwrapExecutionPolicyResolution(result: ExecutionPolicyResolutionResult): ExecutionPolicyResolution {
  if (result.execution_blocked) {
    throw new Error(result.detail || 'Execution blocked by privacy policy')
  }
  return result.resolution
}
