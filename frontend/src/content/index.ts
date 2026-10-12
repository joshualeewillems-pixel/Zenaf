/**
 * DEPRECATION NOTICE (2026-10-12, agent-economy refocus): the content product
 * surface (briefs, script/newsletter generation UI) is PARKED — deprioritized,
 * not maintained. See parked/PARKED.md.
 */
export { ContentNarrativeFrame } from './ContentNarrativeFrame'
export { ContentView } from './ContentView'
export type { ContentViewProps } from './ContentView'
export { ContentFrontDoor } from './ContentFrontDoor'
export type { ContentFrontDoorProps } from './ContentFrontDoor'
export type { ContentBrief, ContentConfig } from './types'
export { DEFAULT_BRIEF_PAYLOAD, VE_TASK_TEMPLATES, apiBriefToBrief } from './types'
export type { ContentBriefPayload, ContentBriefStatus } from './types'
export {
  CONTENT_ACTION_INTENTS,
  contentActionIntentForRun,
  contentRunRoutingContext,
} from './contentRoutingContext'
export type { ContentActionIntent } from './contentRoutingContext'
export {
  CONTENT_TRACE_SUBJECT_TYPE,
  buildContentBriefGenerationSnapshot,
  emitContentBriefDistillTrace,
  emitContentBriefTraceFromRun,
  recordContentTraceOutcome,
} from './contentRunWithTrace'
