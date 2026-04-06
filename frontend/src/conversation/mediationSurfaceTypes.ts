/**
 * Shared workspace "Conversation" column — explicit mode + thread semantics.
 * See docs in repo root message / product spec; this file is the typed contract.
 */

/** High-level panel mode (which workflow owns the mediation surface). */
export type MediationPanelMode =
  | 'folder_review'
  | 'training_workout'
  | 'bounded_transform'
  | 'council_idle'
  | 'council_busy'
  | 'workspace_other'
  | 'thread_only'

/**
 * Transport + reconciliation lifecycle for POST /run/stream (council).
 * Distinguishes TLS/HTTP handshake vs open stream vs first SSE chunk vs finalize.
 */
export type CouncilStreamPhase =
  | 'idle'
  | 'connecting'
  | 'connected_waiting_first_chunk'
  | 'streaming'
  | 'finalizing'
  | 'completed'
  | 'aborted'
  | 'errored'

/** Optional dev-oriented timestamps (performance.now) for one council run. */
export type CouncilTransportTimings = {
  runStartedMs: number
  fetchResolvedMs?: number
  firstChunkMs?: number
  streamEndedMs?: number
}

/** Discriminant for thread rows (additive; legacy rows may omit). */
export type MediationThreadItemKind =
  | 'user_message'
  | 'assistant_message'
  | 'guide_card'
  | 'handoff_notice'
  | 'utility_result'
  | 'system_status'
  | 'streaming_placeholder'
  /** Folded scoped sub-thread (collapsed in main list; children kept for expand / context). */
  | 'scoped_thread_nest'

export function deriveMediationPanelMode(input: {
  showFolderReviewPanel: boolean
  workoutActive: boolean
  councilTransformLoading: boolean
  activeMode: string
  loading: boolean
  agentThreadLength: number
  /** When set, terminal stream phases keep "busy" headline after `loading` clears. */
  councilStreamPhase?: CouncilStreamPhase
}): MediationPanelMode {
  if (input.showFolderReviewPanel) return 'folder_review'
  if (input.workoutActive) return 'training_workout'
  if (input.councilTransformLoading) return 'bounded_transform'
  if (input.activeMode === 'council') {
    if (input.loading) return 'council_busy'
    if (input.councilStreamPhase === 'errored' || input.councilStreamPhase === 'aborted') {
      return 'council_busy'
    }
    return 'council_idle'
  }
  if (input.agentThreadLength > 0) return 'thread_only'
  return 'workspace_other'
}

export function mediationPanelHeadline(mode: MediationPanelMode, phase: CouncilStreamPhase): string {
  if (mode === 'folder_review') return 'Folder list review'
  if (mode === 'training_workout') return 'Perspective workout'
  if (mode === 'bounded_transform') return 'Bounded map transform'
  if (mode === 'council_busy') {
    switch (phase) {
      case 'connecting':
        return 'Council · connecting'
      case 'connected_waiting_first_chunk':
        return 'Council · connected (waiting for first chunk)'
      case 'streaming':
        return 'Council · streaming'
      case 'finalizing':
        return 'Council · finalizing'
      case 'errored':
        return 'Council · error'
      case 'aborted':
        return 'Council · stopped'
      default:
        return 'Council · running'
    }
  }
  if (mode === 'council_idle') {
    if (phase === 'completed') return 'Council · completed'
    return 'Council · ready'
  }
  if (mode === 'thread_only') return 'Thread (history)'
  return 'Workspace'
}

/** Human label for the workspace mode strip (keep in sync with App `MODES`). */
export function workspaceRunModeLabel(modeId: string): string {
  const m: Record<string, string> = {
    analyze: 'Analyze',
    recommend: 'Recommend',
    assess: 'Assess Uncertainty',
    simulate: 'Simulate',
    council: 'Council',
    web_research: 'Web Research',
    next_step: 'Next Step',
    email_intake: 'Email Intake',
    fax_intake: 'Fax Intake',
    ordering_queue: 'Ordering Queue',
  }
  return m[modeId] ?? modeId.replace(/_/g, ' ')
}

/** Main app shell view (Radar / workspace / map / …). */
export function mainViewLabel(mainView: string): string {
  const v: Record<string, string> = {
    home: 'Radar Home',
    workspace: 'Workspace',
    vision_map: 'Vision Map',
    perspectives: 'Perspectives',
    content: 'Content',
    vision_execution: 'Vision & Execution',
    settings: 'Settings',
  }
  return v[mainView] ?? mainView.replace(/_/g, ' ')
}

export function councilPhaseDetail(phase: CouncilStreamPhase): string {
  switch (phase) {
    case 'connecting':
      return 'Opening stream to server…'
    case 'connected_waiting_first_chunk':
      return 'Connected — waiting for the first response…'
    case 'streaming':
      return 'Streaming response…'
    case 'finalizing':
      return 'Finalizing response…'
    case 'completed':
      return 'Response saved to the thread.'
    case 'errored':
      return 'Run failed — see error above or below.'
    case 'aborted':
      return 'Run was cancelled or timed out.'
    default:
      return ''
  }
}
