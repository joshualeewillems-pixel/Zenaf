/**
 * contextDimensions — the six canonical decision-context dimensions.
 *
 * The backend is the source of truth (GET /personality/context-dimensions);
 * this module carries a local copy as fallback so the review UI works even
 * when the backend is unreachable. Refresh via fetchContextDimensions()
 * when online.
 */

export interface ContextDimensions {
  dimensions: Record<string, string[]>
}

/** Local fallback — mirrors local_ai/personality/context.py LEVELS. */
export const FALLBACK_DIMENSIONS: ContextDimensions = {
  dimensions: {
    stakes: ['unknown', 'low', 'significant', 'life-altering'],
    reversibility: ['unknown', 'easily', 'costly', 'irreversible'],
    time_pressure: ['unknown', 'urgent', 'deliberative', 'open-ended'],
    information: ['unknown', 'thin', 'adequate', 'rich'],
    social_field: ['unknown', 'solo', 'interpersonal', 'publicly_accountable'],
    resource_climate: ['unknown', 'scarcity', 'sufficiency', 'abundance'],
  },
}

export const DIMENSION_LABELS: Record<string, string> = {
  stakes: 'Stakes',
  reversibility: 'Reversibility',
  time_pressure: 'Time pressure',
  information: 'Information',
  social_field: 'Social field',
  resource_climate: 'Resources',
}

export const DIMENSION_ORDER = Object.keys(FALLBACK_DIMENSIONS.dimensions)

export function levelLabel(level: string): string {
  return level.replace(/_/g, ' ')
}

/** Normalize any raw value to a known level for the dimension, else 'unknown'.
 * Mirrors local_ai/personality/context.py::normalize_level. */
export function normalizeLevel(dimension: string, raw: unknown): string {
  const levels = FALLBACK_DIMENSIONS.dimensions[dimension]
  if (!levels) return 'unknown'
  if (typeof raw !== 'string') return 'unknown'
  const cand = raw.trim().toLowerCase().replace(/-/g, '_').replace(/ /g, '_')
  if (cand === '' || cand === 'unknown' || cand === 'none') return 'unknown'
  for (const level of levels) {
    if (level.replace(/-/g, '_') === cand) return level
  }
  return 'unknown'
}

export async function fetchContextDimensions(
  apiBase: string,
  init?: RequestInit,
): Promise<ContextDimensions> {
  const r = await fetch(`${apiBase}/personality/context-dimensions`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!r.ok) throw new Error(`context-dimensions failed: ${r.status}`)
  const data = await r.json()
  if (!data || typeof data.dimensions !== 'object') throw new Error('bad shape')
  return data as ContextDimensions
}
