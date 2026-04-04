/**
 * Focus Context as a graph slice — not a curated field list.
 * @see docs/02_ACTIVE_DESIGN/CONTEXT_ACTION_BAR_DESIGN.md (when updated)
 */

import type { CoreProfile, Idea, Initiative, Project, Task, Person, Asset, CapacityProfile } from '../types'

/** VE entity kinds that can appear as graph nodes */
export type GraphNodeKind =
  | 'idea'
  | 'initiative'
  | 'project'
  | 'task'
  | 'person'
  | 'asset'
  | 'core_profile'
  | 'capacity_profile'
  | 'council'
  | 'draft'

/** One node: full row as data; relationships summarized separately */
export interface GraphNodeSnapshot {
  id: string
  kind: GraphNodeKind
  /** Entire entity/object — no field whitelist */
  data: Record<string, unknown>
  relationships: GraphNodeRelationships
  /**
   * Common mediation / extraction metadata (also present on `data` when applicable).
   * Lets consumers address these without re-scanning arbitrary keys.
   */
  system?: Record<string, unknown>
  /** Non-canonical user core row when multiple `core_profiles` exist (not a second identity). */
  hierarchyHint?: 'legacy_secondary_core'
}

export interface GraphNodeRelationships {
  parent?: { kind: GraphNodeKind; id: string } | null
  children: Array<{ kind: GraphNodeKind; id: string; relation?: string }>
  linked: Array<{ kind: GraphNodeKind; id: string; edge?: string }>
  matched: Array<{ kind: GraphNodeKind; id: string; source?: string }>
}

export interface GraphFocusSlice {
  /** Field the user is editing (pointer), not the whole node identity */
  anchor: { kind: GraphNodeKind; id: string; fieldKey: string }
  /** node id → snapshot (id uses raw entity ids; core profiles keyed as `core_profile:${id}`) */
  nodes: Record<string, GraphNodeSnapshot>
  edges: Array<{ from: string; to: string; relation: string }>
  /** ISO timestamp when slice was resolved */
  resolvedAt: string
  /** When graph data was not yet published (e.g. outside VE) */
  dataUnavailable?: boolean
}

/** Snapshot published from VisionExecutionView — full lists, no filtering */
export type VeGraphDataSnapshot = {
  coreProfiles: CoreProfile[]
  ideas: Idea[]
  initiatives: Initiative[]
  projects: Project[]
  tasks: Task[]
  persons: Person[]
  assets: Asset[]
  capacityProfiles: CapacityProfile[]
}

/**
 * Core Profile graph lane — independent of VE focus pointer.
 * Used by `resolveGraphSliceProfile`; typically driven by open profile panel + loaded list.
 */
export type ProfileGraphDataSnapshot = {
  profiles: CoreProfile[]
  /** When set (e.g. detail panel open), profile slice anchors here */
  activeProfileId: string | null
}
