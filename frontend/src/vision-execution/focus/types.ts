/**
 * Focus context for the Context Action Bar: field pointer (`core`) plus parallel graph lanes (`graphs`).
 * @see docs/02_ACTIVE_DESIGN/CONTEXT_ACTION_BAR_DESIGN.md
 */

import type { GraphFocusSlice } from './graphSliceTypes'

export type EntityType = 'idea' | 'initiative' | 'project' | 'task' | 'council' | 'core_profile' | 'app_field'

/** Where the focused control lives (drives registry keys + graph lanes). */
export type FocusSurface = 'vision_execution' | 'vision_map' | 'core_profile' | 'workspace' | 'shell'

/** Coarse grouping for future capability defaults */
export type FieldKind = 'long_form_strategy' | 'dependencies_scope' | 'evaluation_narrative' | 'idea_body'

export type ActionId =
  | 'transcribe'
  | 'rewrite'
  | 'distill'
  | 'expand_to_steps'
  | 'extract_constraints'
  | 'surface_tensions'
  | 'compare_with_evaluation'
  | 'summarize_for_council'
  | 'convert_to_task'

/** Payload registered from focused fields; `surface` defaults in the provider if omitted */
export type FocusDescriptor = {
  surface?: FocusSurface
  entity_type: EntityType
  entity_id: string
  field_key: string
  field_label: string
  field_kind: FieldKind
  parent?: { entity_type: EntityType; entity_id: string; label?: string }
  lineage_labels?: string[]
}

/** Stored focus (debounced) before graph slice resolution */
export type FocusContextCore = FocusDescriptor & {
  surface: FocusSurface
  /** Internal monotonic id for debounce coalescing */
  focus_version?: number
}

/** Separate graph lanes; do not merge into one structure */
export type FocusGraphSlices = {
  ve?: GraphFocusSlice | null
  profile?: GraphFocusSlice | null
  staging?: GraphFocusSlice | null
  intake?: GraphFocusSlice | null
  council?: GraphFocusSlice | null
}

/**
 * Field pointer plus parallel graph slices (VE, profile, …). Each resolver owns its lane.
 */
export type FocusContext = {
  core: FocusContextCore
  graphs: FocusGraphSlices
}
