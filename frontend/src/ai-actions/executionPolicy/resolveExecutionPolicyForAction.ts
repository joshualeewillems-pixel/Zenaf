/**
 * Resolve execution policy for substrate metadata (Phase 0).
 * No I/O; same merge rules as Python `resolve_execution_policy_for_action` (subset).
 * Privacy constraints apply after base merge via `applyPrivacyToExecutionResolution`.
 */
import { EMBEDDED_EXECUTION_POLICY, CLIENT_HINT_COUNCIL_OLLAMA_MODEL, CLIENT_HINT_DEFAULT_OLLAMA_MODEL } from './defaultPolicy'
import {
  applyPrivacyToExecutionResolution,
  mergePrivacyPolicyInput,
  type ExecutionPolicyResolutionResult,
} from './privacyApply'
import { privacyModeToPartialPrivacyPolicy, readPrivacyMode } from '../privacyModeBridge'
import type {
  ActionRoutingContext,
  ExecutionPolicyConfigJson,
  ExecutionPolicyResolution,
  LegacyProviderRoute,
  PrivacyPolicyInput,
  ProviderModelRef,
} from './types'

function asMap(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {}
}

function resolveNullModel(
  model: unknown,
  legacyRoute: LegacyProviderRoute,
  _contextPresent: boolean,
): string {
  if (model != null && model !== '') return String(model)
  if (legacyRoute === 'council') return CLIENT_HINT_COUNCIL_OLLAMA_MODEL
  return CLIENT_HINT_DEFAULT_OLLAMA_MODEL
}

function coerceRef(
  d: Record<string, unknown> | null | undefined,
  legacyRoute: LegacyProviderRoute,
  contextPresent: boolean,
  defaultProvider: string,
): ProviderModelRef {
  if (!d || Object.keys(d).length === 0) {
    return { provider: defaultProvider, model: resolveNullModel(null, legacyRoute, contextPresent) }
  }
  const prov = String(d.provider ?? defaultProvider)
  const mod = d.model
  const modStr = mod != null && mod !== '' ? String(mod) : null
  return { provider: prov, model: resolveNullModel(modStr, legacyRoute, contextPresent) }
}

function parseFallback(
  raw: unknown,
  legacyRoute: LegacyProviderRoute,
  contextPresent: boolean,
): ProviderModelRef[] {
  if (!Array.isArray(raw)) return []
  const out: ProviderModelRef[] = []
  for (const item of raw) {
    if (item && typeof item === 'object' && !Array.isArray(item)) {
      out.push(coerceRef(item as Record<string, unknown>, legacyRoute, contextPresent, 'ollama'))
    }
  }
  return out
}

function applyProfile(
  builder: { allow_cloud: boolean; require_local: boolean },
  prof: Record<string, unknown>,
): void {
  if (!prof || Object.keys(prof).length === 0) return
  if ('allow_cloud' in prof) builder.allow_cloud = Boolean(prof.allow_cloud)
  if (prof.require_local) builder.require_local = true
  if (prof.prefer_cloud === false) builder.allow_cloud = false
}

function applyOverrideBlock(
  block: Record<string, unknown>,
  builder: {
    primary: ProviderModelRef
    fallback: ProviderModelRef[]
    allow_cloud: boolean
  },
  defaults: Record<string, unknown>,
  legacyRoute: LegacyProviderRoute,
  contextPresent: boolean,
): void {
  if ('allow_cloud_fallback' in block) builder.allow_cloud = Boolean(block.allow_cloud_fallback)
  const localDef = asMap(defaults.local)
  const dp = String(localDef.provider || 'ollama')
  if ('primary' in block && block.primary && typeof block.primary === 'object') {
    builder.primary = coerceRef(block.primary as Record<string, unknown>, legacyRoute, contextPresent, dp)
  }
  if ('fallback_chain' in block) {
    builder.fallback = parseFallback(block.fallback_chain, legacyRoute, contextPresent)
  }
}

export type ExecutionPolicyRawResult = {
  resolution: ExecutionPolicyResolution
  /** True if any applied priority profile set require_local (feeds privacy merge). */
  profileRequireLocal: boolean
}

/**
 * Base resolution from policy JSON only (no privacy filter).
 */
export function resolveExecutionPolicyRaw(
  context: ActionRoutingContext | null,
  options: ResolveExecutionPolicyOptions = {},
): ExecutionPolicyRawResult {
  const cfg: ExecutionPolicyConfigJson = options.policy ?? EMBEDDED_EXECUTION_POLICY
  const legacyRoute = options.legacyRoute ?? 'default'
  const defaults = asMap(cfg.defaults)
  const localDefaults = asMap(defaults.local)
  const defaultProvider = String(localDefaults.provider || 'ollama')
  const allowCloudDefault = Boolean(defaults.allow_cloud_fallback !== false)

  if (context == null) {
    const primary = coerceRef(localDefaults, legacyRoute, false, defaultProvider)
    return {
      resolution: {
        primary,
        fallback_chain: [],
        allow_cloud: allowCloudDefault,
        flags: { legacy_route: legacyRoute, routing_context_absent: true },
      },
      profileRequireLocal: false,
    }
  }

  const profiles = cfg.priority_profiles ?? {}
  const globalPri = String(cfg.global_priority ?? 'balanced')

  const builder: {
    primary: ProviderModelRef
    fallback: ProviderModelRef[]
    allow_cloud: boolean
    require_local: boolean
  } = {
    primary: coerceRef(localDefaults, legacyRoute, true, defaultProvider),
    fallback: [],
    allow_cloud: allowCloudDefault,
    require_local: false,
  }

  applyProfile(builder, asMap(profiles[globalPri]))

  const kindOv = asMap(cfg.overrides_by_action_kind?.[context.action_kind])
  const intentKey = (context.action_intent ?? '').trim()
  const intentOv = intentKey ? asMap(cfg.overrides_by_action_intent?.[intentKey]) : {}

  if (Object.keys(kindOv).length > 0) {
    const inh = kindOv.inherit_priority
    if (typeof inh === 'string' && profiles[inh]) applyProfile(builder, asMap(profiles[inh]))
    applyOverrideBlock(kindOv, builder, defaults, legacyRoute, true)
  }
  if (Object.keys(intentOv).length > 0) {
    const inh = intentOv.inherit_priority
    if (typeof inh === 'string' && profiles[inh]) applyProfile(builder, asMap(profiles[inh]))
    applyOverrideBlock(intentOv, builder, defaults, legacyRoute, true)
  }

  const flags: Record<string, unknown> = {
    routing_context_absent: false,
    surface: context.surface,
    action_kind: context.action_kind,
    action_intent: context.action_intent ?? null,
  }
  if (context.streaming != null) flags.streaming = context.streaming
  if (context.sensitivity) flags.sensitivity = context.sensitivity

  return {
    resolution: {
      primary: builder.primary,
      fallback_chain: builder.fallback,
      allow_cloud: builder.allow_cloud,
      flags,
    },
    profileRequireLocal: Boolean(builder.require_local),
  }
}

export type ResolveExecutionPolicyOptions = {
  legacyRoute?: LegacyProviderRoute
  /** Override embedded/shipped policy (tests / future settings sync). */
  policy?: ExecutionPolicyConfigJson
  /** Explicit privacy; merged with `require_local` from priority profile when set. */
  privacy?: Partial<PrivacyPolicyInput> | null
}

/**
 * Full pipeline: policy merge → privacy filter.
 * Default privacy is permissive; profile `require_local` still applies unless overridden.
 */
export function resolveExecutionPolicyForAction(
  context: ActionRoutingContext | null,
  options: ResolveExecutionPolicyOptions = {},
): ExecutionPolicyResolutionResult {
  const { resolution: raw, profileRequireLocal } = resolveExecutionPolicyRaw(context, options)
  const explicitPrivacy =
    options.privacy !== undefined
      ? options.privacy
      : privacyModeToPartialPrivacyPolicy(readPrivacyMode())
  const privacyMerged = mergePrivacyPolicyInput(profileRequireLocal, explicitPrivacy ?? {})
  return applyPrivacyToExecutionResolution(raw, privacyMerged)
}

/** Model hint for traces when resolution is not blocked; otherwise null. */
export function resolveExecutionPolicyPrimaryModelHint(
  context: ActionRoutingContext | null,
  options: ResolveExecutionPolicyOptions = {},
): string | null {
  const r = resolveExecutionPolicyForAction(context, options)
  if (r.execution_blocked) return null
  return r.resolution.primary.model
}

/** Provider hint for traces when resolution is not blocked; otherwise null. */
export function resolveExecutionPolicyPrimaryProviderHint(
  context: ActionRoutingContext | null,
  options: ResolveExecutionPolicyOptions = {},
): string | null {
  const r = resolveExecutionPolicyForAction(context, options)
  if (r.execution_blocked) return null
  return r.resolution.primary.provider
}
