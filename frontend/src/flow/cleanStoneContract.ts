/** Clean stone / channel readiness thresholds — aligned with assessNodeFlowAndChannels `buildChannels`. */

export const CLEAN_STONE_THRESHOLDS = {
  water: { triad01Min: 0.45, disallowWaterLevel: 'low' as const },
  soil: { triad01Min: 0.38 },
  fruit: { triad01Min: 0.35 },
  condition: { maxSeverity: 0 as 0 | 1 | 2 | 3 },
}
