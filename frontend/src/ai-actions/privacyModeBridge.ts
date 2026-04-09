/**
 * Client privacy mode: localStorage → execution policy hints + trace redaction defaults.
 * Must stay aligned with `privacy_mode_to_partial` in `local_ai/execution_policy/privacy_apply.py`.
 */

import type { PrivacyPolicyInput } from './executionPolicy/types'
import { DEFAULT_TRACE_PRIVACY_FLAGS, type TracePrivacyFlags } from './tracePrivacy'

export const ZENAF_PRIVACY_MODE_STORAGE_KEY = 'zenaf_privacy_mode'

export type ZenafPrivacyMode = 'normal' | 'protected' | 'restricted' | 'local_only'

const VALID_MODES = new Set<string>(['normal', 'protected', 'restricted', 'local_only'])

export function readPrivacyMode(): ZenafPrivacyMode {
  if (typeof localStorage === 'undefined') return 'normal'
  try {
    const v = localStorage.getItem(ZENAF_PRIVACY_MODE_STORAGE_KEY)?.trim().toLowerCase()
    if (v && VALID_MODES.has(v)) return v as ZenafPrivacyMode
  } catch {
    /* ignore */
  }
  return 'normal'
}

export function writePrivacyMode(mode: ZenafPrivacyMode): void {
  if (typeof localStorage === 'undefined') return
  if (!VALID_MODES.has(mode)) return
  try {
    localStorage.setItem(ZENAF_PRIVACY_MODE_STORAGE_KEY, mode)
  } catch {
    /* ignore */
  }
}

/** Partial merged after profile `require_local`; `undefined` fields use defaults in merge. */
export function privacyModeToPartialPrivacyPolicy(mode: ZenafPrivacyMode): Partial<PrivacyPolicyInput> | undefined {
  switch (mode) {
    case 'normal':
      return undefined
    case 'protected':
      return { approved_providers: ['ollama', 'openai', 'anthropic'] }
    case 'restricted':
      return { allow_cloud_fallback: false, approved_providers: ['ollama', 'openai'] }
    case 'local_only':
      return { require_local: true, allow_cloud_fallback: false }
    default:
      return undefined
  }
}

export function getTracePrivacyFlagsForCurrentMode(): TracePrivacyFlags {
  const mode = readPrivacyMode()
  switch (mode) {
    case 'normal':
      return DEFAULT_TRACE_PRIVACY_FLAGS
    case 'protected':
      return { redact_trace_snapshot: true, suppress_trace_output: false }
    case 'restricted':
    case 'local_only':
      return { redact_trace_snapshot: true, suppress_trace_output: true }
    default:
      return DEFAULT_TRACE_PRIVACY_FLAGS
  }
}

/** Parse FastAPI HTTPException body: detail may be string or { message, ... }. */
export function extractHttpDetailMessage(body: unknown): string | undefined {
  if (!body || typeof body !== 'object') return undefined
  const o = body as Record<string, unknown>
  const d = o.detail
  if (typeof d === 'string') return d
  if (d && typeof d === 'object' && 'message' in d && typeof (d as { message: unknown }).message === 'string') {
    return (d as { message: string }).message
  }
  if (typeof o.error === 'string') return o.error
  return undefined
}
