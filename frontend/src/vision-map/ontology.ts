/**
 * Visual ontology (projection layer; no backend schema).
 * ideas → seeds, initiatives → trees, projects → branches, tasks → flowers, outcomes → fruit.
 */

export type MapEntityKind = 'seed' | 'tree' | 'branch' | 'flower' | 'fruit' | 'landmark'

/** Stewardship / attention (simple tiered; projection-only). */
export type WaterLevel = 'high' | 'medium' | 'low'

/** Lifecycle / growth channel */
export type GrowthState =
  | 'dormant'
  | 'germinating'
  | 'growing'
  | 'fruiting'
  | 'decaying'
  | 'pruned'

/**
 * Legacy merged signal for resolver input, edges, and prose — **not** a node paint channel.
 * Map stone condition is only `condition_severity` (cracks).
 */
export type ConditionState = 'healthy' | 'blocked' | 'teacher-warned' | 'teacher-vetoed' | 'stale'

/** Unified structural damage for map chrome (0 smooth → 3 critical). Set in graph finalize. */
export type ConditionSeverity = 0 | 1 | 2 | 3

export type VeEntityType = 'idea' | 'initiative' | 'project' | 'task' | 'outcome' | 'person' | 'asset'

export type MapEntityRef = {
  veType: VeEntityType
  id: string
  /** Tasks: parent project for operator / council navigation */
  projectId?: string | null
}

export type CouncilTeacherPreview = {
  teacher_mode?: string
  teacher_enforcement_mode?: string
  teacher_vetoed?: boolean
  teacher_warning?: boolean
  teacher_final_source?: string
  teacher_reason_codes?: string[]
  last_run_at?: string
  summary?: string
}

export type MapNodePayload = {
  kind: MapEntityKind
  label: string
  subtitle?: string
  growth: GrowthState
  /** Feeds `resolveConditionSeverity` and edge vitality; node chrome must not branch on this. */
  condition: ConditionState
  /** Cracked-stone severity — **only** map structural paint channel; set in graph finalize. */
  condition_severity?: ConditionSeverity
  ref: MapEntityRef
  /** Outcome (fruit): VE entity to anchor council / operator context */
  parentRef?: MapEntityRef
  summaryLines: string[]
  councilTeacher?: CouncilTeacherPreview
  /** Owner → high; recent update → medium; else low */
  water_level: WaterLevel
  /** Short UI pulse: recent meaningful update or recent council run for this ref */
  fertilizer_pulse: boolean
  /** Focus mode: non-focused nodes dim */
  dimmed?: boolean
  /** Focus mode: in lineage of selection but not the selected node */
  focusLineage?: boolean
  /** Precomputed water/soil/fruit when vitality_source === 'server' (node_vitality API). */
  growth_triad?: { water: number; soil: number; fruit: number }
  vitality_source?: 'server' | 'client'
  /**
   * Unified triad for map + panel — from `mapVisualTriad` (includes council formation bump on soil when server vitality is used).
   * Set in `buildLiveVisionMapGraph`; optional on older/sample graphs.
   */
  map_visual_triad?: { water: number; soil: number; fruit: number }
} & Record<string, unknown>
