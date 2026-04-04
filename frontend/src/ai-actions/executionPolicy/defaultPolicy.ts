/**
 * Embedded defaults — keep in sync with `config/ai_execution_policy.json` and
 * `local_ai/execution_policy/load.py` `_EMBEDDED_FALLBACK`.
 */
import type { ExecutionPolicyConfigJson } from './types'

export const EMBEDDED_EXECUTION_POLICY: ExecutionPolicyConfigJson = {
  schema_version: 1,
  global_priority: 'balanced',
  defaults: {
    local: { provider: 'ollama', model: null },
    cloud: { provider: 'ollama', model: null },
    allow_cloud_fallback: true,
    max_fallback_steps: 3,
  },
  priority_profiles: {
    balanced: {},
    quality: { prefer_cloud: true },
    speed: { prefer_cloud: false },
    cost: { prefer_cloud: false, prefer_smaller_model: true },
    privacy: { allow_cloud: false, require_local: true },
  },
  overrides_by_action_kind: {},
  overrides_by_action_intent: {},
}

/**
 * Hint-only: must match `local_ai/config.py` `OLLAMA_MODEL` for trace display parity.
 * Server remains authoritative for actual inference.
 */
export const CLIENT_HINT_DEFAULT_OLLAMA_MODEL = 'qwen3:8b'

/** Matches `local_ai/config.py` `OLLAMA_COUNCIL_MODEL` when env is unset (browser has no env). */
export const CLIENT_HINT_COUNCIL_OLLAMA_MODEL = 'qwen2:7b-instruct'
