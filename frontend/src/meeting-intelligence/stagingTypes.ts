/**
 * Staging types: extracted items held for review before commit.
 * Users approve or reject; only approved items are committed into the domain.
 */

import type {
  ExtractedSummary,
  ExtractedInsight,
  ExtractedIdea,
  ExtractedInitiative,
  ExtractedProject,
  ExtractedTask,
  ExtractedAsset,
  ExtractedPersonReference,
  ExtractedSignal,
  GraphInterpretation,
} from './types'

export type StagedItemKind =
  | 'summary'
  | 'insight'
  | 'idea'
  | 'initiative'
  | 'project'
  | 'task'
  | 'asset'
  | 'person'
  | 'signal'

/** Kinds that can be committed as domain entities (used for type override and commit routing). */
export type CommitableStagedKind = 'idea' | 'initiative' | 'project' | 'task' | 'signal' | 'asset' | 'person'

/** Relationship types for link metadata (parent = hierarchy; others for future relationship layer). */
export type StagedRelationshipType = 'parent' | 'related' | 'depends_on' | 'supports' | 'informed_by'

/** User-chosen parent for hierarchy placement (create as child of existing entity). */
export interface StagedParentLink {
  parentType: 'idea' | 'initiative' | 'project' | 'task'
  parentId: string
  /** Default 'parent'. Only parent is used for FK resolution at commit; others stored as metadata. */
  relationshipType?: StagedRelationshipType
}

/** Coarse list-level presort (batch “Presort all”); not structural placement. */
export type PresortBucket = 'existing' | 'new' | 'unsure'

export type PresortEntityType = 'idea' | 'initiative' | 'project' | 'task'

/** Workspace catalog kind for a presort “existing” match (server sets from ENTITY_CATALOG). */
export type PresortExistingEntityType = 'idea' | 'initiative' | 'project' | 'task' | 'asset' | 'person'

export interface StagedItemBase {
  /** Stable id for the staged item (from extraction or generated). */
  id: string
  kind: StagedItemKind
  /** User has approved this item for commit. */
  approved: boolean
  /** Optional user edit before commit (e.g. corrected title). */
  edited?: boolean
  /** When set, commit will not create a new entity; use this existing id instead (user chose "Use existing"). */
  acceptedExistingId?: string | null
  /** User-chosen domain type before commit (not an extractor-assigned truth). */
  overrideType?: CommitableStagedKind | null
  /** When set, create this item as a child of the selected existing entity (e.g. project under initiative). */
  parentLink?: StagedParentLink | null
  /** Assigned people (owner_id / assignee_id resolved at commit). */
  assignedPersonIds?: string[]
  /** Assigned assets (required_assets / linked at commit where API supports). */
  assignedAssetIds?: string[]
  /** Batch coarse triage only; detailed placement uses per-card suggest. */
  presortBucket?: PresortBucket | null
  presortType?: PresortEntityType | null
  presortConfidence?: number | null
  presortExistingId?: string | null
  presortExistingTitle?: string | null
  /** Catalog entity kind for presortExistingId (POST presort-candidate-triage). */
  presortExistingType?: PresortExistingEntityType | null
  /** Short batch-triage note (e.g. matched existing / appears distinct / too vague). */
  presortReason?: string | null
  /**
   * Server rule-based graph interpretation (`interpret_against_graph`).
   * Includes `action` (proposed graph op) and optional `payload` to prefill review/commit.
   */
  interpretation?: GraphInterpretation
}

export interface StagedSummary extends StagedItemBase {
  kind: 'summary'
  data: ExtractedSummary
}

export interface StagedInsight extends StagedItemBase {
  kind: 'insight'
  data: ExtractedInsight
}

export interface StagedIdea extends StagedItemBase {
  kind: 'idea'
  data: ExtractedIdea
}

export interface StagedInitiative extends StagedItemBase {
  kind: 'initiative'
  data: ExtractedInitiative
}

export interface StagedProject extends StagedItemBase {
  kind: 'project'
  data: ExtractedProject
}

export interface StagedTask extends StagedItemBase {
  kind: 'task'
  data: ExtractedTask
}

export interface StagedAsset extends StagedItemBase {
  kind: 'asset'
  data: ExtractedAsset
}

export interface StagedPerson extends StagedItemBase {
  kind: 'person'
  data: ExtractedPersonReference
}

export interface StagedSignal extends StagedItemBase {
  kind: 'signal'
  data: ExtractedSignal
}

export type StagedItem =
  | StagedSummary
  | StagedInsight
  | StagedIdea
  | StagedInitiative
  | StagedProject
  | StagedTask
  | StagedAsset
  | StagedPerson
  | StagedSignal

/** Full staging area: one array per kind for review and commit. View over extraction only — not a domain entity. */
export interface StagingArea {
  summary: StagedSummary | null
  insights: StagedInsight[]
  ideas: StagedIdea[]
  initiatives: StagedInitiative[]
  projects: StagedProject[]
  tasks: StagedTask[]
  assets: StagedAsset[]
  people: StagedPerson[]
  signals: StagedSignal[]
}
