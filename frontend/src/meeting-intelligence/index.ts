/**
 * Meeting → Structure pipeline.
 * Extract structured operational entities from a meeting transcript,
 * stage for review, then commit into the existing domain (Vision Execution API).
 */

export type {
  GraphInterpretationType,
  GraphInterpretationAction,
  GraphInterpretationPayload,
  GraphInterpretation,
  ExtractedConfidence,
  ExtractedSummary,
  ExtractedInsight,
  ExtractedIdea,
  ExtractedInitiative,
  ExtractedProject,
  ExtractedTask,
  ExtractedAsset,
  ExtractedAssetKind,
  ExtractedPersonReference,
  ExtractedSignal,
  ExtractedSignalKind,
  MeetingExtraction,
  ExtractionContextInitiative,
  ExtractionContextProject,
  ExtractionContextTask,
  ExtractionContextAsset,
  ExtractionContextPerson,
  ExtractionContext,
  TranscriptSegment,
  SegmentedTranscript,
  ManualProcessingChunk,
  ConsolidationMeta,
} from './types'

export { segmentTranscript } from './segmentation'
export { preprocessTranscript, buildManualProcessingChunks, buildExternalBudgetChunks } from './chunkBuilder'
export type { BuildManualChunksOptions } from './chunkBuilder'
export { EXTERNAL_EXTRACT_SINGLE_CALL_MAX_CHARS } from './extractConstants'
export { applyDocumentLevelExtractionBudget } from './extractionBudget'
export { sortSegmentsByTopic, getSegmentsToExtract } from './segmentSorter'
export type { SegmentTopic, SortedSegments } from './segmentSorter'
export {
  parseLegacyExtractResponse,
  parseMeetingExtraction,
  mergeSegmentExtractionResults,
  toLegacyExtractMeetingResponse,
} from './extractionParser'
export { consolidateMeetingExtraction, normalizeCandidateText, shouldClusterByTitle } from './consolidation'
export {
  getSignalPriority,
  getItemPriority,
  sortStagedItems,
  getSectionSummary,
  compareSignals,
} from './reviewPriority'
export type { SectionSummaryCounts } from './reviewPriority'
export {
  acceptHighConfidence,
  acceptExtractorMatches,
  rejectLowConfidence,
  acceptSegment,
  acceptSection,
  rejectSection,
  getSegmentIdsFromItems,
  useExtractorMatches,
  useHeuristicMatches,
  useSegmentMatches,
  clearAcceptedExisting,
} from './reviewBatchActions'
export type { ExistingEntitiesLike } from './reviewBatchActions'
export type { LegacyExtractMeetingResponse } from './extractionParser'

export { buildStagingArea, emptyStagingArea, mergeForwardedCandidateIntoStaging } from './stagingHelpers'
export type { ForwardableStagingSectionKey } from './stagingHelpers'
export { buildExtractionContext } from './contextBuilder'
export type { DomainInitiatives, DomainProjects, DomainTasks, DomainAssets, DomainPersons } from './contextBuilder'
export { commitStagedItems, buildCommitPreview, stagingForSingleItemCommit } from './commitStaged'
export type { CommitContext, CommitResult, CommitPreviewLine, StagingArraySectionKey } from './commitStaged'
export { ReviewExtractionScreen, formatStagedItemForTaskNotes } from './ReviewExtractionScreen'
export type { ReviewExtractionScreenProps, ExistingEntities } from './ReviewExtractionScreen'

export type {
  StagedItemKind,
  CommitableStagedKind,
  StagedItemBase,
  StagedParentLink,
  StagedSummary,
  StagedInsight,
  StagedIdea,
  StagedInitiative,
  StagedProject,
  StagedTask,
  StagedAsset,
  StagedPerson,
  StagedSignal,
  StagedItem,
  StagingArea,
} from './stagingTypes'

export {
  toCreateIdeaPayload,
  toCreateInitiativePayload,
  toCreateProjectPayload,
  toCreateTaskPayload,
  toCreateAssetPayload,
  toCreatePersonPayload,
  withTraceability,
  parseTraceabilityFromNotes,
} from './stagingMappers'
export type {
  CreateIdeaPayload,
  CreateInitiativePayload,
  CreateProjectPayload,
  CreateTaskPayload,
  CreateAssetPayload,
  CreatePersonPayload,
  ResolveInitiativeId,
  ResolveProjectId,
  ResolvePersonId,
  ParsedTraceability,
} from './stagingMappers'
