/**
 * Typed structures for extracted meeting content.
 * AI suggests; users review before committing into the domain.
 */

export type ExtractedConfidence = 'high' | 'medium' | 'low'

/** Rule-based graph interpretation (server interpret_against_graph); guides review/commit UX. */
export type GraphInterpretationType =
  | 'existing_enrichment'
  | 'existing_amendment'
  | 'child_of_existing'
  | 'genuinely_new'
  | 'signal_only'

/** Proposed graph operation derived from interpretation type (server + client default). */
export type GraphInterpretationAction =
  | 'update'
  | 'patch'
  | 'create_child'
  | 'create_new'
  | 'ignore'

/** Prefill for review/commit from the extracted row (rule-built; no extra LLM). */
export interface GraphInterpretationPayload {
  title?: string
  description?: string
  notes?: string
  parentId?: string
  fieldsToPatch?: Record<string, unknown>
}

export interface GraphInterpretation {
  type: GraphInterpretationType
  targetId?: string
  confidence?: number
  action: GraphInterpretationAction
  payload?: GraphInterpretationPayload
}

/** Set when deterministic consolidation merged multiple extract rows (UI may ignore). */
export interface ConsolidationMeta {
  mergedCount: number
  chunkCount: number
  mentionCount: number
}

export interface ExtractedSummary {
  id: string
  text: string
  confidence?: ExtractedConfidence | null
  segmentId?: string
  segmentTitle?: string
  interpretation?: GraphInterpretation
}

export interface ExtractedInsight {
  id: string
  statement: string
  sourceQuote?: string
  confidence?: ExtractedConfidence | null
  segmentId?: string
  segmentTitle?: string
  interpretation?: GraphInterpretation
}

export interface ExtractedIdea {
  id: string
  title: string
  description?: string
  summary?: string
  status?: string
  confidence?: ExtractedConfidence | null
  sourceExcerpt?: string | null
  segmentId?: string
  segmentTitle?: string
  /** Extractor provenance when row came from observation-only API (model | clause | lexical). */
  sourceStage?: string | null
  /** API candidate row kind when not default (e.g. workspace_hint raw mirror; promoted_literal = anchor → proposition). */
  candidateKind?: string | null
  consolidationMeta?: ConsolidationMeta
  /** Backend theme bucket so unrelated propositions are not merged in consolidation. */
  anchorRole?: string | null
  /** External single-shot extraction: suggested entity class for review (not committed until user maps). */
  proposedType?: import('../vision-execution/types').ExtractedCandidateProposedType | null
  interpretation?: GraphInterpretation
}

export interface ExtractedInitiative {
  id: string
  title: string
  description?: string
  brief?: string
  status?: string
  ownerName?: string | null
  notes?: string
  confidence?: ExtractedConfidence | null
  sourceExcerpt?: string | null
  /** Extractor-suggested existing entity (prefer link over creating duplicate). */
  existingInitiativeMatchId?: string | null
  matchConfidence?: number | null
  segmentId?: string
  segmentTitle?: string
  consolidationMeta?: ConsolidationMeta
  anchorRole?: string | null
  interpretation?: GraphInterpretation
}

export interface ExtractedProject {
  id: string
  title: string
  initiativeTitle?: string
  initiativeId?: string | null
  brief?: string
  status?: string
  confidence?: ExtractedConfidence | null
  sourceExcerpt?: string | null
  existingInitiativeMatchId?: string | null
  existingProjectMatchId?: string | null
  matchConfidence?: number | null
  segmentId?: string
  segmentTitle?: string
  consolidationMeta?: ConsolidationMeta
  anchorRole?: string | null
  interpretation?: GraphInterpretation
}

export interface ExtractedTask {
  id: string
  title: string
  projectTitle?: string
  projectId?: string | null
  initiativeTitle?: string
  initiativeId?: string | null
  description?: string
  status?: string
  suggestedOwner?: string | null
  assigneeName?: string | null
  notes?: string
  confidence?: ExtractedConfidence | null
  sourceExcerpt?: string | null
  existingProjectMatchId?: string | null
  existingTaskMatchId?: string | null
  existingPersonMatchId?: string | null
  matchConfidence?: number | null
  segmentId?: string
  segmentTitle?: string
  consolidationMeta?: ConsolidationMeta
  anchorRole?: string | null
  interpretation?: GraphInterpretation
}


export type ExtractedAssetKind = 'tool' | 'system' | 'document' | 'inventory' | 'other'

export interface ExtractedAsset {
  id: string
  name: string
  kind: ExtractedAssetKind
  description?: string
  confidence?: ExtractedConfidence | null
  sourceExcerpt?: string | null
  existingAssetMatchId?: string | null
  matchConfidence?: number | null
  segmentId?: string
  segmentTitle?: string
  consolidationMeta?: ConsolidationMeta
  anchorRole?: string | null
  interpretation?: GraphInterpretation
}

export interface ExtractedPersonReference {
  id: string
  name: string
  role?: string
  context?: string
  confidence?: ExtractedConfidence | null
  sourceExcerpt?: string | null
  existingPersonMatchId?: string | null
  matchConfidence?: number | null
  segmentId?: string
  segmentTitle?: string
  consolidationMeta?: ConsolidationMeta
  anchorRole?: string | null
  interpretation?: GraphInterpretation
}

export type ExtractedSignalKind = 'attention' | 'risk' | 'opportunity' | 'blocker'

export interface ExtractedSignal {
  id: string
  kind: ExtractedSignalKind
  label: string
  detail?: string
  confidence?: ExtractedConfidence | null
  sourceExcerpt?: string | null
  segmentId?: string
  segmentTitle?: string
  consolidationMeta?: ConsolidationMeta
  anchorRole?: string | null
  interpretation?: GraphInterpretation
}

/** Layer 1 canonical Signal status. */
export type CoreSignalStatus = 'new' | 'acknowledged' | 'linked' | 'resolved' | 'dismissed'

/** Layer 1 canonical Signal (single source of truth). Matches API snake_case. Radar and other views consume this. */
export interface CoreSignal {
  id: string
  kind: ExtractedSignalKind | 'info'
  title: string
  detail?: string | null
  source: string
  source_excerpt?: string | null
  source_ref?: { type: string; id: string } | null
  confidence?: ExtractedConfidence | null
  linked_initiative_id?: string | null
  linked_project_id?: string | null
  linked_task_id?: string | null
  status: CoreSignalStatus
  created_at: string
  updated_at: string
}

/** Full extraction result from a meeting transcript. */
export interface MeetingExtraction {
  summary?: ExtractedSummary | null
  insights: ExtractedInsight[]
  ideas: ExtractedIdea[]
  initiatives: ExtractedInitiative[]
  projects: ExtractedProject[]
  tasks: ExtractedTask[]
  assets: ExtractedAsset[]
  peopleReferences: ExtractedPersonReference[]
  signals: ExtractedSignal[]
  error?: string
}

// --- Pre-extraction entity context (passed to extractor to propose links to existing entities) ---

export interface ExtractionContextInitiative {
  id: string
  title: string
}

export interface ExtractionContextProject {
  id: string
  title: string
  initiativeId?: string
  initiativeTitle?: string
}

export interface ExtractionContextTask {
  id: string
  title: string
  projectId?: string
  projectTitle?: string
  initiativeId?: string
  initiativeTitle?: string
}

export interface ExtractionContextAsset {
  id: string
  name: string
  kind?: string
}

export interface ExtractionContextPerson {
  id: string
  name: string
  role?: string
}

export interface ExtractionContext {
  initiatives: ExtractionContextInitiative[]
  projects: ExtractionContextProject[]
  tasks: ExtractionContextTask[]
  assets: ExtractionContextAsset[]
  people: ExtractionContextPerson[]
}

// --- Topic segmentation (split transcript into coherent chunks before extraction) ---

export interface TranscriptSegment {
  id: string
  title?: string
  startOffset: number
  endOffset: number
  text: string
  speakerHints?: string[]
}

export interface SegmentedTranscript {
  segments: TranscriptSegment[]
}

/** Chunk for assisted chunk mode: preprocessed transcript split into 3–6 large chunks for reliable extraction. */
export interface ManualProcessingChunk {
  id: string
  title: string
  text: string
  startOffset: number
  endOffset: number
}

/** Configurable extraction profile for different domains (clinic, SaaS, etc.). Layer 2. */
export interface ExtractionProfile {
  id: string
  name: string
  description?: string
  initiativeGuidance: {
    preferredStyle?: string
    examples: string[]
    maxCount?: number
    breadth?: 'broad' | 'medium' | 'narrow'
  }
  /** Enabled entity type ids: e.g. "summary", "insights", "initiatives", "projects", "tasks", "assets", "people", "signals". */
  enabledEntityTypes: string[]
  signalGuidance?: {
    examples: string[]
    instructions?: string
  }
  assetGuidance?: {
    examples: string[]
    instructions?: string
  }
  peopleGuidance?: {
    examples: string[]
    instructions?: string
  }
  groupingConfig?: {
    mergeDuplicatesAggressively?: boolean
    preferCanonicalBuckets?: boolean
  }
  /** Layer 2 extraction quality (optional). Used by backend when building prompts / canonization. */
  initiativeNamingStyle?: string
  initiativeGranularityRule?: string
  projectDetectionRule?: string
  signalInferenceRule?: string
  assetSpecificityRule?: string
  personReferenceRule?: string
}

