/**
 * Full AI trace policy (convergence): every AI-touching path must call pushAiActionTrace /
 * meeting extraction trace / workspace trace — or be listed here with a stable exempt id.
 *
 * Review when adding LLM calls or user-visible AI outcomes. Goal: no silent gaps.
 */
export type AiTraceExemptEntry = {
  /** Stable id referenced in code comments at the exempt call site. */
  id: string
  /** Why tracing is not required (or not yet wired). */
  reason: string
}

/** Declared exemptions only — not an exhaustive list of all AI surfaces. */
export const AI_ACTION_TRACE_EXEMPTS: readonly AiTraceExemptEntry[] = [
  {
    id: 'voice_transcribe_only',
    reason:
      'POST /api/transcribe is speech→text only; no model reasoning step in cockpit trace shape (optional future: separate transcribe trace).',
  },
  {
    id: 'heuristic_no_provider',
    reason:
      'Code paths that never call an LLM adapter (pure heuristics / parsing) are not AI actions; council integrity heuristics fall here when no provider call occurs.',
  },
  {
    id: 'studio_admin_surface',
    reason:
      'Studio (/studio) bakeoffs and prompt tooling are operator-only until aligned with the same trace contract as the main cockpit.',
  },
  {
    id: 'settings_llm_connectivity_test',
    reason:
      'POST /settings/llm/test is a minimal provider ping (or Ollama tags fetch) for credential validation, not a user-facing reasoning artifact.',
  },
]

export function aiTraceExemptIds(): Set<string> {
  return new Set(AI_ACTION_TRACE_EXEMPTS.map((e) => e.id))
}
