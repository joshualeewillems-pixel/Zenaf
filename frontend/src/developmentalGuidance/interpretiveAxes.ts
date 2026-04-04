/**
 * Ephemeral interpretive axes — runtime language helpers only (developmental guidance read layer).
 * Not persisted, not traits, not a profile. Canonical tilt strings and names live in
 * interpretive_axis_copy.json (loaded via interpretiveAxisCopy.ts); Python reads the same JSON
 * from repo path local_ai → frontend/src/developmentalGuidance/interpretive_axis_copy.json.
 *
 * Future versioned judgment-profile artifacts = separate artifact design, not an extension of this.
 */
import { INTERPRETIVE_AXIS_NAMES, interpretiveAxisCopy } from './interpretiveAxisCopy'
import type { DevelopmentalGuidanceStyle } from './types'

export type InterpretiveAxis = {
  name: string
  tilt: string
}

export type CouncilTraceTally = {
  councilCount: number
  dismissed: number
  applied: number
  weakIntegrity: number
}

const T = () => interpretiveAxisCopy.tilts
const N = () => INTERPRETIVE_AXIS_NAMES

/**
 * Derive up to six axes from map gaps, optional style hint, and optional session council tally.
 * Omits trace-derived axes unless councilCount >= 2 (avoid filler from a single run).
 */
export function deriveInterpretiveAxes(input: {
  missingDimensions: readonly ('water' | 'soil' | 'fruit')[]
  suggestedGuidanceStyle?: DevelopmentalGuidanceStyle
  tally?: CouncilTraceTally | null
}): InterpretiveAxis[] {
  const axes: InterpretiveAxis[] = []
  const seen = new Set<string>()
  const push = (name: string, tilt: string) => {
    const raw = tilt.trim()
    if (!name.trim() || seen.has(name) || axes.length >= 6 || !raw) return
    const t = raw.length <= 200 ? raw : `${raw.slice(0, 197).trim()}…`
    seen.add(name)
    axes.push({ name, tilt: t })
  }

  const missing = new Set(input.missingDimensions)
  const multiGap =
    (missing.has('soil') ? 1 : 0) + (missing.has('water') ? 1 : 0) + (missing.has('fruit') ? 1 : 0) >= 2

  if (missing.has('soil')) {
    let clarity = T().soilClarity
    if (multiGap) clarity += T().soilClarityMultiGapSuffix
    push(N().clarityAmbiguity, clarity)
    push(N().structureExploration, T().structureExplorationSoil)
  }
  if (missing.has('water')) {
    push(N().followThroughDropoff, T().waterFollowThrough)
  }
  if (missing.has('fruit')) {
    push(N().actionIdeation, T().fruitActionIdeation)
  }

  const style = input.suggestedGuidanceStyle
  if (style === 'more_structure' && !missing.has('soil')) {
    push(N().structureExploration, T().structureFromStyle)
  }
  if (style === 'more_ambiguity_tolerance') {
    push(N().clarityAmbiguity, T().ambiguityToleranceStyle)
  }

  const t = input.tally
  const councilOk = t != null && t.councilCount >= 2
  if (councilOk) {
    if (t.dismissed >= 2 && t.dismissed >= t.applied) {
      push(N().integrationFragmentation, T().traceDismissed)
    }
    if (t.weakIntegrity >= 2) {
      push(N().integrationFragmentation, T().traceWeakIntegrity)
    }
  }

  return axes.slice(0, 6)
}

/** One optional sentence for map guide bubbles; empty if no axes (no filler). */
export function interpretiveAxesGuideSentence(axes: readonly InterpretiveAxis[]): string {
  if (axes.length === 0) return ''
  const lead = interpretiveAxisCopy.labels.guideSentenceLeadIn
  const bits = axes.slice(0, 3).map((a) => `${a.name} (${a.tilt})`)
  return `${lead} ${bits.join('; ')}.`
}
