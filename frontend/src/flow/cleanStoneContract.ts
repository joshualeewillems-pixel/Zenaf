/**
 * Clean stone / channel readiness thresholds — mirrors logic in assessNodeFlowAndChannels `buildChannels`.
 * Change UNIFIED_NODE_ASSESSMENT_RULES_VERSION when tightening these.
 */
import { MAP_SOIL_TIER_MEDIUM_BELOW } from '../vision-map/mapNodeAppearance'

export const CLEAN_STONE_THRESHOLDS = {
  water: {
    triad01Min: 0.45,
    disallowWaterLevel: 'low' as const,
  },
  soil: {
    triad01Min: MAP_SOIL_TIER_MEDIUM_BELOW,
  },
  condition: {
    maxSeverity: 0,
  },
  fruit: {
    triad01Min: 0.38,
  },
} as const
