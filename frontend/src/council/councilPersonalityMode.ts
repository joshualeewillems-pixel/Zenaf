/**
 * Council personality mode: which version of each council seat to use.
 *
 * Joshua's directive: the user chooses per purpose. "base" is the pure
 * aspirational seat, "mirror" is their trained version (published
 * PersonalityProfile only), "blend" is the weighted combination.
 *
 * Pure logic lives here (vitest-covered); the JSX selector component is in
 * CouncilPersonalityModeSelector.tsx.
 */

export type CouncilPersonalityMode = 'base' | 'mirror' | 'blend'

export const COUNCIL_PERSONALITY_MODES: CouncilPersonalityMode[] = ['base', 'mirror', 'blend']

export const COUNCIL_PERSONALITY_MODE_LABELS: Record<CouncilPersonalityMode, string> = {
  base: 'Base',
  mirror: 'Mirror',
  blend: 'Blend',
}

export const COUNCIL_PERSONALITY_MODE_HINTS: Record<CouncilPersonalityMode, string> = {
  base: 'Pure aspirational seats — the ideal of each faculty, no mirror',
  mirror: 'Your trained version — seats speak from your published profile',
  blend: 'Weighted mix of the aspirational ideal and your mirror',
}

export const DEFAULT_COUNCIL_PERSONALITY_MODE: CouncilPersonalityMode = 'blend'

export function isCouncilPersonalityMode(v: unknown): v is CouncilPersonalityMode {
  return v === 'base' || v === 'mirror' || v === 'blend'
}

async function personalityFetch(
  path: string,
  init?: RequestInit,
): Promise<{ ok: boolean; data: unknown }> {
  const res = await fetch(path, { credentials: 'include', ...init })
  let data: unknown = null
  try {
    data = await res.json()
  } catch {
    /* non-JSON: leave null */
  }
  return { ok: res.ok, data }
}

/** Load the user's saved default council mode; falls back to "blend". */
export async function fetchCouncilPersonalityMode(): Promise<CouncilPersonalityMode> {
  try {
    const { ok, data } = await personalityFetch('/personality/council-mode')
    const mode = (data as { council_mode?: unknown } | null)?.council_mode
    if (ok && isCouncilPersonalityMode(mode)) return mode
  } catch {
    /* offline / unreachable: default */
  }
  return DEFAULT_COUNCIL_PERSONALITY_MODE
}

/** Persist the user's default council mode. Resolves false on failure. */
export async function saveCouncilPersonalityMode(mode: CouncilPersonalityMode): Promise<boolean> {
  try {
    const { ok } = await personalityFetch('/personality/council-mode', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ council_mode: mode }),
    })
    return ok
  } catch {
    return false
  }
}
