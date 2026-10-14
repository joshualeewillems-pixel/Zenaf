import {
  useState,
  useEffect,
  useLayoutEffect,
  useMemo,
  useCallback,
  useRef,
  type ChangeEvent,
  type DragEvent,
  type KeyboardEvent,
  type ReactNode,
  type Ref,
  type SyntheticEvent,
} from 'react'
import type { PerspectiveAgent } from './perspectives/types'
import {
  BUILT_IN_PERSPECTIVES,
  normalizeStoredPerspectiveAgents,
  isFoundationSystemActor,
  isUserDefined,
  createAgent,
} from './perspectives/types'
import { apiBase } from './apiBase'; import { iconHintFor } from './perspectives/roleIcons'
import { AvatarDisplay } from './components/AvatarDisplay'
import {
  PerspectivesView,
  AgentDetailPanel,
  AgentCreatorForm,
  InfluencesLinksSection,
} from './perspectives'
import { PerspectiveWorkoutPanel } from './perspectives/PerspectiveWorkoutPanel'
import { LivingTreeView } from './living-tree/LivingTree'
import {
  formatWorkoutContextBlock,
  countWorkoutRatingsInStorage,
  newWorkoutMessageId,
  type WorkoutMessage,
} from './perspectives/workoutTypes'
import { streamWorkoutCouncilResponse } from './perspectives/workoutCouncilStream'
import {
  VisionExecutionView,
  type VESelection,
  type CouncilIdeaLabelsSnapshot,
  type VEWorkspaceTabId,
} from './vision-execution'
import { VisionMapView } from './vision-map'
import { veSelectionFromEntityRef, veSelectionFromMapPayload } from './vision-map/mapCouncilActions'
import { resolveInspectEntityRef } from './vision-map/mapTriadInspector'
import type { MapNodePayload } from './vision-map/ontology'
import type { VisionMapCouncilInteraction } from './vision-map/visionMapCouncilInteraction'
import { getRecentAiActionTraces } from './ai-actions/traceSink'
import {
  buildDevelopmentalGuidanceContext,
  developmentalGuidanceUserSummary,
} from './developmentalGuidance/buildDevelopmentalGuidanceContext'
import { buildVeMapTriadSnapshotFromFocus } from './developmentalGuidance/buildVeMapTriadSnapshot'
import type { ExecutionFlowReadingSummary, MapTriadDevelopmentalSnapshot } from './developmentalGuidance/types'
import { fetchExecutionFlowReadings } from './developmentalGuidance/fetchExecutionFlowReadings'
import { veEntityRefFromMapTriad } from './developmentalGuidance/mapTriadVeEntity'
import type { VisionMapEntityBundle } from './vision-map/blockersFromVe'
import {
  buildStackedGuidesForKey,
  effectiveGuideStackKey,
  formatGuideStackBarSubtitle,
  type GuideQuestionOrigin,
  type GuideThreadMessage,
} from './developmentalGuidance/guideEntityStack'
import {
  councilPrefillForGuideQuestion,
  deriveInjectPreviewQuestionText,
  inferInjectPreviewOrigin,
  metaForSeededGuideContent,
  resolveGuideQuestionMeta,
} from './developmentalGuidance/guideQuestionDisplay'
import { InlineThreadGuideCard } from './conversation/InlineThreadGuideCard'
import { ThreadInlineGuideStack } from './conversation/ThreadInlineGuideStack'
import { appendChatDroppedFiles, dataTransferHasFiles } from './conversation/chatFileDrop'
import { SubjectHandoffReview } from './conversation/SubjectHandoffReview'
import {
  councilPhaseDetail,
  deriveMediationPanelMode,
  mainViewLabel,
  mediationPanelHeadline,
  workspaceRunModeLabel,
  type CouncilStreamPhase,
  type CouncilTransportTimings,
  type MediationThreadItemKind,
} from './conversation/mediationSurfaceTypes'
import { MediationFlowHint } from './flow/MediationFlowHint'
import type { ConversationSubject } from './conversation/conversationTrunkTypes'
import {
  contentForSuggestionExtraction,
  extractConversationSuggestions,
  normalizeSuggestionFingerprint,
  parseSubjectEntityRef,
  shouldScrapeMessageForSuggestions,
  type PendingThreadSuggestion,
} from './conversation/subjectThreadCapture'
import { formatSystemPromptContextTitle } from './developmentalGuidance/systemPromptTitle'
import {
  buildDevelopmentalMapFingerprint,
  developmentalMapVisionMapPromptId,
  checkPromptShouldShow,
  fallbackMapGuidePromptId,
  ephemeralGuidePromptIdFromContent,
  postPromptSignal,
  WORKSPACE_DEFER_ENTITY,
} from './vision-execution/promptSignalsApi'
import { VISION_EXECUTION_API, type CoreProfile } from './vision-execution/types'
import { canonicalCoreProfileId, coreProfileInfluencePickLabel } from './vision-execution/canonicalCoreProfile'
import { ZenafPresence } from './components/ZenafPresence'
import { EntityMentionText, type EntityMentionOpenPayload } from './components/EntityMentionText'
import { enrichScopedDigressionLabel } from './council/enrichScopedDigressionLabel'
import { postCouncilInsightRecognition } from './vision-execution/recognitionDecisions'
import { BrandStructuredProfilePanel, CreateCoreProfileForm } from './vision-execution/coreProfilePanels'
import { AspirationsFoundationPanel } from './foundation/AspirationsFoundationPanel'
import {
  VisionExecutionGraphDataProvider,
  VisionExecutionProfileGraphDataProvider,
  VisionExecutionFocusProvider,
  VeVoiceRecordingProvider,
  ContextActionBarContent,
  FocusInviteRunProvider,
  buildConversationalInvitePreface,
  buildStructuredFillInvitePreface,
  buildConversationalInviteDisplayLine,
  buildScopedContextLabelFromCore,
  threadDisplayLineForCouncilQuestion,
  CONVERSATIONAL_INVITE_MARKER,
  FocusContextRecordButton,
  TranscribableFieldRegion,
  focusFieldRegistryKey,
  ZENAF_VOICE_TRANSCRIPT_DOM_FIRST,
  ZENAF_VE_FOCUS_INSERT_TEXT,
  ZENAF_VE_FOCUS_APPLY_REWRITE,
  insertTextAtSelection,
  type VeFocusInsertTextDetail,
  type VeFocusApplyRewriteDetail,
  type FocusInvite,
} from './vision-execution/focus'
import { useVisionExecutionFocusOptional } from './vision-execution/focus/VisionExecutionFocusContext'
import type { FocusContext, FocusContextCore } from './vision-execution/focus/types'
import { resolveGraphSliceVE } from './vision-execution/focus/graphSliceResolver'
import {
  veFocusCoreFromVeSelection,
  veGraphSnapshotFromBundle,
  veSelectedEntityPayloadFromSelection,
} from './vision-execution/focus/conversationEntityFocus'
import type { Mandate } from './mandates'
import { BUILT_IN_MANDATES } from './mandates'
import {
  mandateSeatIconAccentClass,
  mandateSeatOrbGlowClass,
  mandateOrbStrokeStyle,
  isKnownMandateId,
} from './mandateSeatAccent'
import { CouncilMandatePicker, CouncilPerspectivePicker } from './council/CouncilSeatPickers'
import { CouncilPersonalityModeSelector } from './council/CouncilPersonalityModeSelector'
import {
  fetchCouncilPersonalityMode,
  saveCouncilPersonalityMode,
  type CouncilPersonalityMode,
} from './council/councilPersonalityMode'
import { CouncilTranscript } from './council/CouncilTranscript'
import { CouncilTranscriptWithResonance } from './council/CouncilTranscriptWithResonance'
import { ResonanceSlider } from './components/ResonanceSlider'
import { ContentFrontDoor } from './content'
import AgentIntakeView from './agent-intake/AgentIntakeView'
import ReviewView from './agent-intake/ReviewView'
import SignalReviewView from './presence-review/SignalReviewView'
import type { VeRadarBucketId } from './vision-execution/veRadarAwareness'
import { DomainProvider } from './domain/DomainContext'
import { AuthGate } from './auth/AuthGate'
import { ConsentOnboardingGate } from './auth/ConsentOnboardingGate'
import {
  getCurrentUser,
  login as loginSession,
  logout as logoutSession,
  type CurrentUser,
} from './auth/session'
import { ProfileAvatarControl } from './components/ProfileAvatarControl'
import { SettingsView } from './settings/SettingsView'
import {
  fetchLLMSettings,
  fetchUserPermissionsSettings,
  saveCouncilSeatLlm,
  saveUserPermissionsSettings,
  type ProviderStatusRow,
  type UserPermissionFlags,
} from './settings/api'
import type { AiActionTrace, AiUserOutcome } from './ai-actions'
import {
  WORKSPACE_ACTION_INTENTS,
  buildWorkspaceRunRoutingContext,
  buildWorkspaceCouncilStreamSnapshot,
  buildWorkspaceFolderAdvisorSnapshot,
  buildWorkspaceJsonRunSnapshot,
  buildWorkspaceNextStepSnapshot,
  buildWorkspaceReassessSnapshot,
  buildWorkspaceWebResearchSnapshot,
  createAiActionTrace,
  emitWorkspaceTraceFromResult,
  emitWorkspaceTraceFromText,
  extractHttpDetailMessage,
  pushAiActionTrace,
  readPrivacyMode,
  recordWorkspaceTraceOutcome,
} from './ai-actions'
import type { CouncilSynthesisIntegrityState, WorkspaceRunRoutingContextPayload } from './ai-actions'
import {
  buildCouncilIntegrityReviewSample,
  councilSynthesisCombinedPresentation,
  councilSynthesisCombinedSummaryLine,
  councilSynthesisIntegrityClass,
  councilSynthesisWhyLine,
  deriveCouncilSynthesisCombinedSummary,
  explainSynthesisSupportStatus,
  ingestSynthesisEnvelopeFromPayload,
  labelCouncilSynthesisCombinedSummary,
  labelCouncilSynthesisIntegrity,
  shortIntegrityRunId,
  type CouncilIntegrityEnvelopePayload,
  type CouncilStreamSsePayload,
  type IntegrationCommitPayload,
  type LastIntegrationCommitPayload,
  type PendingIntegrationPayload,
  type PendingVeElicitationPayload,
} from './council/synthesisIntegrity'

/** Flat scan for proposed integration (walks into folded scoped threads). */
type AgentThreadScanRow = {
  role: string
  threadItemKind?: string
  pendingIntegration?: PendingIntegrationPayload | null
  nestedScopedThread?: { children: AgentThreadScanRow[] }
}

function findLastProposedPendingIntegrationInRows(rows: AgentThreadScanRow[]): PendingIntegrationPayload | null {
  for (let i = rows.length - 1; i >= 0; i--) {
    const row = rows[i]!
    if (row.threadItemKind === 'scoped_thread_nest' && row.nestedScopedThread) {
      const inner = findLastProposedPendingIntegrationInRows(row.nestedScopedThread.children)
      if (inner) return inner
    }
    if (row.role === 'agent' && row.pendingIntegration?.integration_state === 'proposed') {
      return row.pendingIntegration
    }
  }
  return null
}

type CouncilInsightScanRow = {
  role: string
  content: string
  agentLabel?: string
  threadItemKind?: string
  nestedScopedThread?: { children: CouncilInsightScanRow[] }
}

function findLastCouncilContentInRows(rows: CouncilInsightScanRow[]): string | null {
  for (let i = rows.length - 1; i >= 0; i--) {
    const m = rows[i]!
    if (m.threadItemKind === 'scoped_thread_nest' && m.nestedScopedThread) {
      const inner = findLastCouncilContentInRows(m.nestedScopedThread.children)
      if (inner) return inner
    }
    if (m.role === 'agent' && m.agentLabel === 'Council' && m.content.trim()) return m.content
  }
  return null
}

/** POST /vision-execution/learning-records/user-outcome when structured next_step returned a correlation id. */
function postWorkspaceLearningFromRef(
  w: { learning_record_id?: string | null } | null | undefined,
  outcome: 'applied' | 'edited' | 'dismissed' | 'copied',
) {
  const lid = w?.learning_record_id
  if (!lid || typeof lid !== 'string' || !lid.trim()) return
  void fetch(`${VISION_EXECUTION_API}/learning-records/user-outcome`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      learning_record_id: lid.trim(),
      user_outcome: outcome,
      privacy_mode: readPrivacyMode(),
    }),
  }).catch(() => {
    /* non-blocking */
  })
}

function CouncilSynthesisIntegrityNote({
  includeSynthesis,
  state,
  warning,
  envelope,
}: {
  includeSynthesis: boolean
  state: CouncilSynthesisIntegrityState | null
  warning: string | null
  envelope: CouncilIntegrityEnvelopePayload | null
}) {
  if (!includeSynthesis || !state) return null

  const primaryInPacket = state !== 'weak'
  let synthesisAnchorLabel: string
  if (state === 'weak') synthesisAnchorLabel = 'Not evaluated'
  else if (state === 'anchored') synthesisAnchorLabel = 'Detected (heuristic)'
  else synthesisAnchorLabel = 'Not detected (heuristic)'

  const policies = envelope?.policies_applied?.filter(Boolean) ?? []
  const runId = envelope?.provenance?.run_id
  const mode = (envelope?.integrity_mode ?? envelope?.default_mode ?? 'bounded').trim() || 'bounded'
  const synthesisType = (envelope?.synthesis_type ?? null)?.trim() || null
  const refs = envelope?.subject_refs ?? []
  const refsLine =
    refs.length === 0
      ? '—'
      : refs
          .map((r) => [r.entity_type, r.entity_id].filter(Boolean).join(' ') || '—')
          .slice(0, 4)
          .join(' · ')
  const supportExplain = explainSynthesisSupportStatus(envelope?.synthesis_support_status)
  const combined = deriveCouncilSynthesisCombinedSummary(state, warning, envelope?.synthesis_support_status)
  const combinedPresentation = councilSynthesisCombinedPresentation(combined)

  return (
    <div className="mt-2 pt-2 border-t border-stone-700/60 text-[11px] text-stone-500">
      <div className="mb-2 pb-2 border-b border-stone-700/40">
        <span className="text-stone-500">Combined reading: </span>
        <span className={combinedPresentation.labelClassName}>{labelCouncilSynthesisCombinedSummary(combined)}</span>
        <p className={`mt-1 text-[10px] leading-snug ${combinedPresentation.descriptionClassName}`}>
          {councilSynthesisCombinedSummaryLine(combined)}
        </p>
      </div>
      <div>
        <span>Synthesis integrity: </span>
        <span className={`font-medium ${councilSynthesisIntegrityClass(state)}`}>{labelCouncilSynthesisIntegrity(state)}</span>
        {warning === 'missing_primary_anchor' ? (
          <span className="block text-amber-400/85 mt-1">
            Note: the closing summary may not tie back clearly to your main topic. Ask for a tighter recap if that matters.
          </span>
        ) : warning === 'synthesis_failure_template' ? (
          <span className="block text-amber-300/85 mt-1">
            Note: the closing summary looked like a system message rather than a normal answer; treat anchor checks as approximate.
          </span>
        ) : null}
      </div>
      <details className="mt-1.5 group">
        <summary className="cursor-pointer text-stone-400 hover:text-stone-200 list-none flex items-center gap-1 select-none [&::-webkit-details-marker]:hidden">
          <span className="text-[10px] uppercase tracking-wide text-stone-500 group-open:text-stone-400">
            Why this rating?
          </span>
          <span aria-hidden className="text-stone-600 group-open:rotate-90 transition-transform inline-block">
            ›
          </span>
        </summary>
        <div className="mt-2 pl-2 border-l border-stone-600/80 space-y-2 text-stone-400">
          <p className="text-[10px] text-stone-500 leading-snug">
            The headline blends two checks: whether the summary stayed on your main topic, and how well different voices
            supported it. Technical details are below.
          </p>
          <p className="text-stone-400 leading-snug">{councilSynthesisWhyLine(state)}</p>
          <dl className="space-y-1.5">
            <div>
              <dt className="text-stone-500 text-[10px] uppercase tracking-wide">Combined summary (derived)</dt>
              <dd>
                <span className={combinedPresentation.labelClassName}>{labelCouncilSynthesisCombinedSummary(combined)}</span>
                <span className="block font-mono text-[10px] text-stone-500/75 mt-0.5">{combined}</span>
              </dd>
            </div>
            <div>
              <dt className="text-stone-500 text-[10px] uppercase tracking-wide">Integrity mode</dt>
              <dd className="text-stone-300 font-mono text-[10px]">{mode}</dd>
            </div>
            <div>
              <dt className="text-stone-500 text-[10px] uppercase tracking-wide">Synthesis type</dt>
              <dd className="text-stone-300 font-mono text-[10px]">{synthesisType ?? 'normal'}</dd>
            </div>
            <div>
              <dt className="text-stone-500 text-[10px] uppercase tracking-wide">Main topic in this run&apos;s context</dt>
              <dd className="text-stone-300">
                {primaryInPacket ? 'Included as the main focus' : 'Light context only — grounding is weaker'}
              </dd>
            </div>
            <div>
              <dt className="text-stone-500 text-[10px] uppercase tracking-wide">Main topic reflected in closing summary</dt>
              <dd className="text-stone-300">{synthesisAnchorLabel}</dd>
            </div>
            <div>
              <dt className="text-stone-500 text-[10px] uppercase tracking-wide">How voices supported the answer (heuristic)</dt>
              <dd className="text-stone-300">
                {supportExplain ? (
                  <>
                    <span className="font-medium text-[11px]">{supportExplain.label}</span>
                    <span className="block text-stone-400 mt-0.5 text-[10px] leading-snug">{supportExplain.body}</span>
                  </>
                ) : (
                  <span className="text-stone-500 font-mono text-[10px]">—</span>
                )}
              </dd>
            </div>
            <div>
              <dt className="text-stone-500 text-[10px] uppercase tracking-wide">Integrity warning</dt>
              <dd className="text-stone-300 font-mono text-[10px]">{warning ?? '—'}</dd>
            </div>
            <div>
              <dt className="text-stone-500 text-[10px] uppercase tracking-wide">Policies applied</dt>
              <dd className="text-stone-300">
                {policies.length > 0 ? (
                  <ul className="list-disc pl-4 space-y-0.5 font-mono text-[10px] text-stone-400">
                    {policies.map((p, idx) => (
                      <li key={`${idx}-${p}`}>{p}</li>
                    ))}
                  </ul>
                ) : (
                  <span className="text-stone-500">Not in stream payload</span>
                )}
              </dd>
            </div>
            <div>
              <dt className="text-stone-500 text-[10px] uppercase tracking-wide">Run id</dt>
              <dd className="text-stone-300 font-mono text-[10px]" title={runId ?? undefined}>
                {shortIntegrityRunId(runId)}
              </dd>
            </div>
            <div>
              <dt className="text-stone-500 text-[10px] uppercase tracking-wide">Related items (focus)</dt>
              <dd className="text-stone-300 text-[10px] leading-snug break-words">{refsLine}</dd>
            </div>
          </dl>
        </div>
      </details>
    </div>
  )
}

/** Map workflow JSON panel modes → trace intents for copy / outcome attribution. */
/** Syncs VE field focus into a ref for council preflight (must render under VisionExecutionFocusProvider). */
function CouncilFocusBridge({
  focusRef,
  focusBridgeActive,
}: {
  focusRef: { current: FocusContext | null }
  /** True on Vision & Execution and Vision Map so council preflight can read shared focus. */
  focusBridgeActive: boolean
}) {
  const ctx = useVisionExecutionFocusOptional()
  useEffect(() => {
    if (!focusBridgeActive || !ctx) {
      focusRef.current = null
      return
    }
    focusRef.current = ctx.focus
  }, [focusBridgeActive, ctx, ctx?.focus, focusRef])
  return null
}

/** Clear all focus when leaving VE surfaces so workspace does not keep stale entity context. */
function LeaveVisionSurfacesFocusClear({
  mainView,
}: {
  mainView:
    | 'living_tree'
    | 'workspace'
    | 'perspectives'
    | 'content'
    | 'vision_map'
    | 'vision_execution'
    | 'agent_intake'
    | 'review'
    | 'signal_review'
    | 'settings'
}) {
  const ctx = useVisionExecutionFocusOptional()
  const clearRef = useRef(ctx?.clearFocus)
  clearRef.current = ctx?.clearFocus
  useEffect(() => {
    if (mainView !== 'vision_map' && mainView !== 'vision_execution') {
      clearRef.current?.()
    }
  }, [mainView])
  return null
}

function workspaceFolderEntityId(folderPath: string, lastFolderPath: string): string {
  const p = (folderPath || lastFolderPath || '').trim() || 'default'
  let h = 5381
  for (let i = 0; i < p.length; i++) {
    h = Math.imul(h, 33) ^ p.charCodeAt(i)
  }
  return `ws-${(h >>> 0).toString(16)}`
}

type MainViewForResonance =
  | 'living_tree'
  | 'workspace'
  | 'perspectives'
  | 'content'
  | 'vision_map'
  | 'vision_execution'
  | 'agent_intake'
  | 'settings'

/** Map agent/run label → integrated-response resonance row (when transcript has no seat headers). */
function chatResonanceIntegration(
  agentLabel: string | undefined,
  opts?: { folderWorkflow?: boolean },
): { seatId: string; contextKind: 'council_seat' | 'zenaf_training' } {
  if (opts?.folderWorkflow || agentLabel === 'Folder review') {
    return { seatId: 'folder_review', contextKind: 'council_seat' }
  }
  if (
    agentLabel === 'Zenaf' ||
    agentLabel === 'Thinking Partner' ||
    agentLabel === 'Zenaf (Thinking Partner)'
  ) {
    return { seatId: 'zenaf', contextKind: 'zenaf_training' }
  }
  if (agentLabel === 'Council') {
    return { seatId: 'council', contextKind: 'council_seat' }
  }
  const slug = (agentLabel || 'assistant')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_|_$/g, '')
    .slice(0, 48)
  return { seatId: slug || 'agent', contextKind: 'council_seat' }
}

function useWorkspaceOrVeResonanceEntity(
  mainView: MainViewForResonance,
  folderPath: string,
  lastFolderPath: string,
) {
  const ve = useVisionExecutionFocusOptional()
  return useMemo(() => {
    if (
      (mainView === 'vision_execution' || mainView === 'vision_map') &&
      ve?.focus?.core?.entity_id?.trim()
    ) {
      return {
        entityType: ve.focus.core.entity_type,
        entityId: ve.focus.core.entity_id.trim(),
      }
    }
    return {
      entityType: 'workspace',
      entityId: workspaceFolderEntityId(folderPath, lastFolderPath),
    }
  }, [mainView, ve?.focus?.core?.entity_id, ve?.focus?.core?.entity_type, folderPath, lastFolderPath])
}

function AgentChatResonanceSlider({
  responseId,
  agentLabel,
  mainView,
  folderPath,
  lastFolderPath,
  folderWorkflow,
}: {
  responseId: string
  agentLabel: string | undefined
  mainView: MainViewForResonance
  folderPath: string
  lastFolderPath: string
  folderWorkflow?: boolean
}) {
  const { entityType, entityId } = useWorkspaceOrVeResonanceEntity(mainView, folderPath, lastFolderPath)
  const { seatId, contextKind } = chatResonanceIntegration(agentLabel, { folderWorkflow })
  return (
    <ResonanceSlider
      responseId={responseId}
      seatId={seatId}
      contextKind={contextKind}
      entityType={entityType}
      entityId={entityId}
    />
  )
}

/** Council thread: per-seat resonance sliders; VE field focus on Vision & Execution, else workspace + folder hash. */
function CouncilTranscriptResonanceBridge({
  text,
  stripZenafSynthesis,
  decorateSeatHeaders,
  responseIdPrefix,
  mainView,
  folderPath,
  lastFolderPath,
  agentLabelForResonance,
  folderWorkflowResonance,
  integrationCommit,
  pendingIntegration,
  onOpenEntity,
}: {
  text: string
  stripZenafSynthesis: boolean
  decorateSeatHeaders: boolean
  responseIdPrefix: string
  mainView: MainViewForResonance
  folderPath: string
  lastFolderPath: string
  agentLabelForResonance?: string
  folderWorkflowResonance?: boolean
  integrationCommit?: IntegrationCommitPayload | null
  pendingIntegration?: PendingIntegrationPayload | null
  onOpenEntity?: (p: EntityMentionOpenPayload) => void
}) {
  const { entityType, entityId } = useWorkspaceOrVeResonanceEntity(mainView, folderPath, lastFolderPath)
  const { seatId, contextKind } = chatResonanceIntegration(agentLabelForResonance, {
    folderWorkflow: folderWorkflowResonance,
  })

  return (
    <CouncilTranscriptWithResonance
      text={text}
      stripZenafSynthesis={stripZenafSynthesis}
      decorateSeatHeaders={decorateSeatHeaders}
      responseIdPrefix={responseIdPrefix}
      entityType={entityType}
      entityId={entityId}
      integratedSeatId={seatId}
      integratedContextKind={contextKind}
      integrationCommit={integrationCommit}
      pendingIntegration={pendingIntegration}
      onOpenEntity={onOpenEntity}
    />
  )
}

/** Single top strip: focus tools + (when idle) workspace “where” crumbs. Renders under VisionExecutionFocusProvider. */
function UniversalContextStrip({
  mainView,
  currentTopic,
  currentFocusHasResult,
  activeMode,
  useLastResultAsContext,
}: {
  mainView:
    | 'living_tree'
    | 'workspace'
    | 'perspectives'
    | 'content'
    | 'vision_map'
    | 'vision_execution'
    | 'agent_intake'
    | 'review'
    | 'signal_review'
    | 'settings'
  currentTopic: { label: string; modeLabel: string | null; summary: string; fullPath: string }
  currentFocusHasResult: boolean
  activeMode: string
  useLastResultAsContext: boolean
}) {
  const focusOpt = useVisionExecutionFocusOptional()
  const hasVeFieldFocus = Boolean(focusOpt?.focus)
  const idleHint =
    mainView === 'vision_map' ? 'map' : mainView === 'vision_execution' ? 've' : 'shell'

  return (
    <div className="shrink-0 z-10 border-b border-stone-700 px-6 py-2.5 bg-stone-800/95 backdrop-blur-sm">
      <VeVoiceRecordingProvider>
        <div className="flex flex-wrap items-start gap-3 text-sm">
          <span className="flex items-center gap-2 shrink-0 pt-0.5">
            <FocusContextRecordButton />
            <span className="text-stone-500 uppercase tracking-wide font-medium">Focus context</span>
          </span>
          <div className="flex-1 min-w-0 flex flex-wrap items-start gap-x-4 gap-y-2">
            <ContextActionBarContent className="flex-1 min-w-0 min-w-[10rem]" idleHint={idleHint} />
          {!hasVeFieldFocus && mainView !== 'vision_execution' && (
            <div className="flex flex-wrap items-center gap-2 border-t border-stone-700/80 pt-2 sm:border-t-0 sm:pt-0 sm:border-l sm:border-stone-700 sm:pl-4 w-full sm:w-auto">
              <span className="text-stone-500 uppercase text-[10px] tracking-wide font-medium">Where</span>
              {mainView === 'vision_map' ? (
                <span className="text-stone-300">Vision map</span>
              ) : (
                <>
                  <span className="text-stone-300 font-mono truncate max-w-[220px]" title={currentTopic.fullPath}>
                    {currentTopic.label}
                  </span>
                  {currentTopic.modeLabel && (
                    <span className="px-2 py-0.5 rounded bg-stone-700 text-stone-300">{currentTopic.modeLabel}</span>
                  )}
                  {currentTopic.summary && (
                    <span className="text-stone-400 truncate max-w-[320px]" title={currentTopic.summary}>
                      {currentTopic.summary}
                    </span>
                  )}
                </>
              )}
              {currentFocusHasResult && mainView === 'workspace' && (
                <span className="px-2 py-0.5 rounded bg-emerald-900/45 text-emerald-200 border border-emerald-800/55 text-xs">
                  Result ready
                </span>
              )}
              {(mainView === 'workspace' || mainView === 'vision_map') && activeMode === 'council' && (
                <span className={useLastResultAsContext ? 'text-yellow-500 text-xs' : 'text-stone-500 text-xs'}>
                  {useLastResultAsContext ? 'Using result as context' : 'Context off'}
                </span>
              )}
            </div>
          )}
          </div>
        </div>
      </VeVoiceRecordingProvider>
    </div>
  )
}

/** Synthetic focus for council reply — same registry path as other transcribable fields. */
const COUNCIL_REPLY_FOCUS_ID = '__council_reply__'
const COUNCIL_REPLY_FOCUS_FIELD_KEY = focusFieldRegistryKey({
  surface: 'workspace',
  entity_type: 'council',
  entity_id: COUNCIL_REPLY_FOCUS_ID,
  field_key: 'reply',
})

function focusTextareaRefEnd(textareaRef: Ref<HTMLTextAreaElement>) {
  requestAnimationFrame(() => {
    const el =
      textareaRef && typeof textareaRef === 'object' && 'current' in textareaRef
        ? textareaRef.current
        : null
    if (!(el instanceof HTMLTextAreaElement)) return
    el.focus()
    const len = el.value.length
    el.setSelectionRange(len, len)
  })
}

/** Council “Your reply” — registers focus/selection for record + insert; voice still uses DOM-first when the textarea stays active. Renders under VisionExecutionFocusProvider. */
function CouncilQuestionTextarea({
  value,
  onChange,
  textareaRef,
  onInput,
  onKeyDown,
  placeholder,
  className,
  onAfterFilesDropped,
}: {
  value: string
  onChange: (e: ChangeEvent<HTMLTextAreaElement>) => void
  textareaRef: Ref<HTMLTextAreaElement>
  onInput: () => void
  onKeyDown?: (e: KeyboardEvent<HTMLTextAreaElement>) => void
  placeholder: string
  className: string
  onAfterFilesDropped?: () => void
}) {
  const ctx = useVisionExecutionFocusOptional()
  const valueRef = useRef(value)
  valueRef.current = value
  const [dragActive, setDragActive] = useState(false)

  const onComposerDragOver = useCallback((e: DragEvent<HTMLDivElement>) => {
    if (!dataTransferHasFiles(e.dataTransfer)) return
    e.preventDefault()
    e.stopPropagation()
    e.dataTransfer.dropEffect = 'copy'
    setDragActive(true)
  }, [])

  const onComposerDragLeave = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.stopPropagation()
    const t = e.currentTarget
    const rel = e.relatedTarget as Node | null
    if (rel && t.contains(rel)) return
    setDragActive(false)
  }, [])

  const onComposerDrop = useCallback(
    async (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault()
      e.stopPropagation()
      setDragActive(false)
      const files = e.dataTransfer.files
      if (!files?.length) return
      const next = await appendChatDroppedFiles(valueRef.current, files)
      onChange({ target: { value: next } } as ChangeEvent<HTMLTextAreaElement>)
      focusTextareaRefEnd(textareaRef)
      onAfterFilesDropped?.()
    },
    [onChange, onAfterFilesDropped, textareaRef],
  )

  const dropZoneClass = dragActive
    ? 'ring-2 ring-amber-500/75 ring-offset-2 ring-offset-stone-900 rounded-lg'
    : ''

  const desc = useMemo(
    () =>
      ({
        surface: 'workspace' as const,
        entity_type: 'council' as const,
        entity_id: COUNCIL_REPLY_FOCUS_ID,
        field_key: 'reply',
        field_label: 'Council reply',
        field_kind: 'idea_body' as const,
      }) as const,
    [],
  )

  useEffect(() => {
    if (!ctx) return
    const getter = () => valueRef.current
    ctx.registerFieldTextGetter(COUNCIL_REPLY_FOCUS_FIELD_KEY, getter)
    return () => ctx.unregisterFieldTextGetter(COUNCIL_REPLY_FOCUS_FIELD_KEY)
  }, [ctx])

  const ta = (
    <textarea
      data-testid="council-question-input"
      data-zenaf-voice-insert="council-question"
      ref={textareaRef}
      value={value}
      onChange={onChange}
      onInput={onInput}
      onKeyDown={onKeyDown}
      placeholder={placeholder}
      rows={1}
      className={className}
    />
  )

  if (!ctx) {
    return (
      <div
        className={`min-w-0 ${dropZoneClass}`}
        onDragOver={onComposerDragOver}
        onDragLeave={onComposerDragLeave}
        onDrop={(e) => void onComposerDrop(e)}
      >
        {ta}
      </div>
    )
  }

  const { notifyFieldFocused, notifyFieldBlurred, recordFieldSelection } = ctx

  const syncSelection = useCallback(
    (e: SyntheticEvent) => {
      const t = e.target
      if (!(t instanceof HTMLTextAreaElement)) return
      recordFieldSelection(COUNCIL_REPLY_FOCUS_FIELD_KEY, t.selectionStart ?? 0, t.selectionEnd ?? 0)
    },
    [recordFieldSelection],
  )

  return (
    <div
      className={`min-w-0 ${dropZoneClass}`}
      onFocusCapture={() => notifyFieldFocused(desc)}
      onBlurCapture={() => notifyFieldBlurred()}
      onSelectCapture={syncSelection}
      onKeyUpCapture={syncSelection}
      onClickCapture={syncSelection}
      onDragOver={onComposerDragOver}
      onDragLeave={onComposerDragLeave}
      onDrop={(e) => void onComposerDrop(e)}
    >
      {ta}
    </div>
  )
}

const WORKFLOW_JSON_INTENT_BY_MODE: Record<'analyze' | 'simulate' | 'assess' | 'recommend', string> = {
  analyze: WORKSPACE_ACTION_INTENTS.analyze,
  simulate: WORKSPACE_ACTION_INTENTS.simulate,
  assess: WORKSPACE_ACTION_INTENTS.assess,
  recommend: WORKSPACE_ACTION_INTENTS.recommend,
}

/** Parse folder advisor strict output: "Suggested parent folders..." then "- <folder> — <reason>" lines. Returns empty array on failure. */
function parseFolderAdvisorResult(text: string): { folder: string; reason?: string }[] {
  if (!text || !text.trim()) return []
  const lines = text.split(/\r?\n/)
  const out: { folder: string; reason?: string }[] = []
  let inBlock = false
  const bulletRe = /^\s*-\s*(.+?)\s+[—–-]\s+(.*)$/
  for (const line of lines) {
    if (/Suggested parent folders/i.test(line)) {
      inBlock = true
      continue
    }
    if (inBlock) {
      const trimmed = line.trim()
      if (!trimmed || /^Add to my recommendations/i.test(trimmed)) break
      const m = line.match(bulletRe)
      if (m) {
        out.push({ folder: m[1].trim(), reason: m[2].trim() || undefined })
      }
    }
  }
  return out
}

/** Normalize folder name for comparison: trim, lowercase, treat underscores as spaces. */
function normalizeFolderKey(name: string): string {
  return name.trim().toLowerCase().replace(/_/g, ' ')
}

/** Two keys match if equal or one is the other + trailing "s" (simple singular/plural). */
function folderKeysMatch(a: string, b: string): boolean {
  if (a === b) return true
  if (a.endsWith('s') && a.length > 1 && a.slice(0, -1) === b) return true
  if (b.endsWith('s') && b.length > 1 && b.slice(0, -1) === a) return true
  return false
}

/** Find an existing folder in the list that matches the given name (normalized + singular/plural). Returns the display name from the list, or null. */
function findExistingFolderMatch(name: string, list: string[]): string | null {
  const key = normalizeFolderKey(name)
  const found = list.find((f) => folderKeysMatch(normalizeFolderKey(f), key))
  return found ?? null
}

const PERSPECTIVE_STORAGE_KEY = 'zenaf-perspective-agents'

const API_BASE = apiBase()

/** Intake uses absolute `API_BASE` (see `apiBase.ts`). Local dev: the SPA must load from **127.0.0.1:5173** (see `vite.config.ts`) so the session cookie host matches; `localhost:5173` is a different host and cookies are not sent to 127.0.0.1:8010. Hosted builds set VITE_API_BASE="" (same origin). `/run` uses relative `RUN_API_BASE` (proxied in dev). */
const RUN_API_BASE = ''

async function visionExecutionApiErrorText(res: Response): Promise<string> {
  const text = await res.text().catch(() => res.statusText)
  try {
    const j = JSON.parse(text) as { detail?: unknown }
    if (j?.detail != null) {
      if (typeof j.detail === 'string') return j.detail
      if (Array.isArray(j.detail)) {
        const parts = j.detail
          .map((x) => (x && typeof x === 'object' && 'msg' in x ? String((x as { msg?: string }).msg ?? '') : ''))
          .filter(Boolean)
        if (parts.length) return parts.join('; ')
      }
    }
  } catch {
    /* ignore */
  }
  return text || res.statusText
}

async function veApiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${VISION_EXECUTION_API}${path}`, { credentials: 'include' })
  if (!res.ok) throw new Error(await visionExecutionApiErrorText(res))
  return res.json()
}

async function veApiPatch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${VISION_EXECUTION_API}${path}`, {
    method: 'PATCH',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await visionExecutionApiErrorText(res))
  return res.json()
}

async function veApiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${VISION_EXECUTION_API}${path}`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await visionExecutionApiErrorText(res))
  return res.json()
}

async function veApiPut<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${VISION_EXECUTION_API}${path}`, {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await visionExecutionApiErrorText(res))
  return res.json()
}

type CouncilWorkspacePerspectivesResponse = {
  row_exists: boolean
  perspectives: PerspectiveAgent[]
  updated_at: string | null
}

const MODES = [
  { id: 'analyze', label: 'Analyze', description: 'Folder structure, tokens, extensions, domain' },
  { id: 'recommend', label: 'Recommend', description: 'Suggested child folders' },
  { id: 'assess', label: 'Assess Uncertainty', description: 'Plan strength and weak suggestions' },
  { id: 'simulate', label: 'Simulate', description: 'Preview folder plan' },
  { id: 'council', label: 'Council', description: 'Storyteller, Patternist, Seer, Songwriter, Maker, Mediator, Guide, Skeptic, Zenaf, …' },
  { id: 'web_research', label: 'Web Research', description: 'Lightweight web lookup' },
  { id: 'next_step', label: 'Next Step', description: 'One concrete action' },
  { id: 'email_intake', label: 'Email Intake', description: 'Ingest email into the intake queue' },
  { id: 'fax_intake', label: 'Fax Intake', description: 'Ingest fax/OCR into the intake queue' },
  { id: 'ordering_queue', label: 'Ordering Queue', description: 'View intake queue items' },
] as const

// Fast council: default and max seats (UI and backend aligned).
const MAX_COUNCIL_SEATS = 3
const EXPANDED_MAX_SEATS = 7
/** Hard cap so the UI never stays on “Running…” if the SSE stream hangs without closing. */
const COUNCIL_STREAM_MAX_MS = 15 * 60 * 1000
/**
 * If the connection stays open but no bytes / SSE events arrive for this long, abort.
 * Covers “hung” runs where the server never sends the first chunk (distinct from total wall time).
 */
const COUNCIL_STREAM_IDLE_MS = 3 * 60 * 1000
/** Non-council agent bubbles stay short; council + folder advisor can be long (many seats + synthesis). */
const AGENT_THREAD_DISPLAY_MAX_CHARS = 2000

function newScopedThreadNestId(): string {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `nest-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
}

type DigressionBackgroundThreadRow = {
  role: string
  content: string
  threadItemKind?: string
  nestedScopedThread?: { children: DigressionBackgroundThreadRow[] }
}

function formatDigressionBackgroundBlock(thread: DigressionBackgroundThreadRow[]): string {
  function* walkReverse(rows: DigressionBackgroundThreadRow[]): Generator<DigressionBackgroundThreadRow> {
    for (let i = rows.length - 1; i >= 0; i--) {
      const m = rows[i]!
      if (m.threadItemKind === 'scoped_thread_nest' && m.nestedScopedThread) {
        yield* walkReverse(m.nestedScopedThread.children)
      } else {
        yield m
      }
    }
  }
  const lines: string[] = []
  for (const m of walkReverse(thread)) {
    if (lines.length >= 4) break
    if (m.role !== 'user' && m.role !== 'agent') continue
    if (m.threadItemKind === 'streaming_placeholder') continue
    const role = m.role === 'user' ? 'User' : 'Assistant'
    const body = (m.content || '').trim().slice(0, 800)
    if (!body) continue
    lines.unshift(`${role}: ${body}`)
  }
  return lines.join('\n\n')
}

/** Reply starter only — full system suggestion stays expanded in the thread above. */
const DISCUSS_REPLY_STARTER = 'Regarding the suggestion above: '
const HANDOFF_COMMIT_STARTER = 'Following up from the previous topic: '

/**
 * One council seat. `actorId` is the selected **actor** (saved agent) id; API still uses `perspective_agent_id`.
 * Seat **roles** (UI; payload `mandate`) live in `mandatesBySeatId[slot.id]`.
 */
type CouncilSeatSlot = { id: string; actorId: string | null }

type ModeId = (typeof MODES)[number]['id']

type RunRoutingContextPayload = WorkspaceRunRoutingContextPayload

interface RunResponse {
  ok: boolean
  result?: unknown
  error?: string
  model_used?: string | null
  provider_used?: string | null
  routing_override_active?: boolean | null
  execution_blocked?: boolean | null
  privacy_block_reason?: string | null
  /** Server trace when structured cloud delegation ran (e.g. workspace Next Step + OpenAI). */
  delegation_path?: string | null
  /** Why structured delegation was skipped (e.g. empty next-step context with OpenAI routing). */
  delegation_skip_reason?: string | null
  /** In-memory learning buffer id; correlate with POST /vision-execution/learning-records/user-outcome. */
  learning_record_id?: string | null
  /** When OpenAI primary: env vs saved Settings key (no secrets). */
  openai_key_source?: string | null
  /** Two-plane execution: `account` | `system` when seam ran. */
  execution_scope?: string | null
  execution_principal_ref?: string | null
  credential_namespace?: string | null
  policy_namespace?: string | null
}

/** When the API blocks a run, avoid implying a cloud model was used. */
function workspaceExecutionBlockedMessage(data: RunResponse): string {
  return (
    data.error ||
    'This run was blocked by your privacy settings. No provider or model was used. Try a local model (e.g. Ollama), or change Privacy mode in Settings.'
  )
}

// Lightweight session state
interface AnalyzeResult {
  folder_path?: string
  inferred_context_domain?: string
  suggested_child_folders?: string[]
  item_count?: number
  file_count?: number
  folder_count?: number
  extension_breakdown?: Record<string, number>
  repeated_tokens?: string[]
  error?: string
}

interface SimulateResult {
  folder_path?: string
  inferred_context_domain?: string
  suggested_child_folders?: string[]
  proposed_assignments?: unknown[]
  blocked_items?: unknown[]
  notes?: string[]
  error?: string
}

interface AssessItem {
  item_name?: string
  confidence?: number
  suggested_child?: string
  reason?: string
}

interface SimulateTreeData {
  folder_path?: string
  inferred_context_domain?: string
  suggested_child_folders?: string[]
  proposed_assignments?: { item_name?: string; suggested_child?: string; confidence?: number; reason?: string }[]
}

interface AssessResult {
  low_confidence_count?: number
  items?: AssessItem[]
  recommended_actions?: string[]
  simulate_tree?: SimulateTreeData
  error?: string
}

/** One reassessment result from perspective-driven second pass */
interface ReassessItemResult {
  item_name: string
  suggested_folder: string
  rationale: string
  status: string
  confidence?: number
}

interface RecommendResult {
  folder_path?: string
  inferred_context_domain?: string
  suggested_child_folders?: string[]
  notes?: string[]
  error?: string
}

// Council returns a single string (seat-labeled sections, e.g. Strategist:\n...\nOperator:\n... etc.)
type CouncilResult = string

interface WebResearchResult {
  query?: string
  top_findings?: string[]
  sources?: { title?: string; link?: string }[]
  notes?: string
  error?: string
}

interface NextStepResult {
  recommendation?: string
  rationale?: string
  alternatives?: string[]
  caution?: string | null
  error?: string
}

interface IntakeQueueItem {
  id: string
  category: string
  priority: string
  summary: string
  suggested_action: string
  source: string
  has_phi?: boolean
  created_at?: string
  status?: string
  notes?: string
  assigned_to?: string
  subject?: string
  source_label?: string
  lane?: string
  lane_override?: string  // staff correction; display this instead of lane when set
  judgment_id?: string   // judgment layer: one reasoning event per item
  confidence?: number
  confidence_display?: 'high' | 'medium' | 'low'
  archived?: boolean   // internal hide in Zenaf queue only
}

interface JudgmentRecordInUI {
  id: string
  interpretation?: Record<string, unknown>
  proposed_action?: Record<string, unknown>
  confidence?: number
  signal_codes?: string[]
  interpretation_codes?: string[]
  policy_codes?: string[]
  reason_codes?: string[]
  created_at?: string
  observation_ref?: { subject_preview?: string; body_length?: number; matched_signals?: string[] }
  superseded_by?: string | null
  correction_note?: string | null
}

const INTAKE_LANE_ORDER = ['needs_attention', 'insurance_medical', 'ordering_supplies', 'waiting_fyi', 'likely_junk'] as const
const INTAKE_LANE_LABELS: Record<string, string> = {
  needs_attention: 'Needs attention',
  insurance_medical: 'Insurance / MediCal',
  ordering_supplies: 'Ordering / Supplies',
  waiting_fyi: 'Waiting / FYI',
  likely_junk: 'Likely junk / noise',
}
const INTAKE_LANE_SHORT: Record<string, string> = {
  needs_attention: 'Needs',
  insurance_medical: 'Insurance',
  ordering_supplies: 'Ordering',
  waiting_fyi: 'FYI',
  likely_junk: 'Junk',
}

function intakeQueueRelativeTime(createdAt: string | undefined): string {
  if (!createdAt) return '—'
  try {
    const d = new Date(createdAt)
    if (Number.isNaN(d.getTime())) return '—'
    const now = Date.now()
    const sec = Math.floor((now - d.getTime()) / 1000)
    if (sec < 60) return 'Just now'
    if (sec < 3600) return `${Math.floor(sec / 60)}m ago`
    if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`
    if (sec < 604800) return `${Math.floor(sec / 86400)}d ago`
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: d.getFullYear() !== new Date().getFullYear() ? 'numeric' : undefined })
  } catch {
    return '—'
  }
}

type WorkflowStepState = 'not_started' | 'ready' | 'running' | 'completed' | 'error'

// --- Reusable UI components for guided workflow ---

function FolderSelector({
  value,
  onChange,
  recentFolders,
  onUseCurrentFocus,
  onClear,
  currentFocusPath,
  disabled,
  showUseCurrentFocus,
  apiBase,
}: {
  value: string
  onChange: (path: string) => void
  recentFolders: string[]
  onUseCurrentFocus: () => void
  onClear: () => void
  currentFocusPath: string
  disabled?: boolean
  showUseCurrentFocus?: boolean
  /** When set, show a Browse button that opens the native folder picker via the API. */
  apiBase?: string
}) {
  const [browseLoading, setBrowseLoading] = useState(false)
  const [browseError, setBrowseError] = useState<string | null>(null)
  const showUse = showUseCurrentFocus !== false

  const onBrowse = useCallback(async () => {
    if (!apiBase) return
    setBrowseError(null)
    setBrowseLoading(true)
    try {
      const url = value.trim()
        ? `${apiBase}/folder-picker?initial_dir=${encodeURIComponent(value.trim())}`
        : `${apiBase}/folder-picker`
      const res = await fetch(url, { method: 'POST' })
      const data = await res.json().catch(() => ({}))
      if (data.error) {
        setBrowseError(data.error)
        return
      }
      if (data.folder_path != null) {
        onChange(data.folder_path)
      }
    } catch (e) {
      setBrowseError(e instanceof Error ? e.message : 'Failed to open folder picker')
    } finally {
      setBrowseLoading(false)
    }
  }, [apiBase, value, onChange])

  return (
    <div className="space-y-3">
      <label className="block text-sm font-medium text-slate-300">Folder path</label>
      <div className="flex gap-2">
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="e.g. C:\Users\me\Desktop\Downloads"
          disabled={disabled}
          className="flex-1 min-w-0 px-4 py-2.5 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-amber-500 focus:border-transparent"
        />
        {apiBase && (
          <button
            type="button"
            onClick={onBrowse}
            disabled={disabled || browseLoading}
            className="px-4 py-2.5 rounded-lg border border-slate-600 bg-slate-800 text-slate-300 text-sm font-medium hover:bg-slate-700 disabled:opacity-50 whitespace-nowrap"
            title="Choose folder from your computer"
          >
            {browseLoading ? 'Opening…' : 'Browse'}
          </button>
        )}
      </div>
      {browseError && <p className="text-amber-400 text-sm">{browseError}</p>}
      <div className="flex flex-wrap items-center gap-2">
        {recentFolders.length > 0 && (
          <select
            className="rounded-lg bg-slate-800 border border-slate-600 text-slate-300 text-sm px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-amber-500"
            value=""
            onChange={(e) => e.target.value && onChange(e.target.value)}
          >
            <option value="">Recent folders…</option>
            {recentFolders.map((p) => (
              <option key={p} value={p}>{p.length > 50 ? p.slice(0, 47) + '…' : p}</option>
            ))}
          </select>
        )}
        {showUse && (
          <button
            type="button"
            onClick={onUseCurrentFocus}
            disabled={!currentFocusPath || disabled}
            className="px-3 py-1.5 rounded-lg border border-slate-600 bg-slate-800 text-slate-300 text-sm hover:bg-slate-700 disabled:opacity-50"
          >
            Use current focus
          </button>
        )}
        <button
          type="button"
          onClick={onClear}
          className="px-3 py-1.5 rounded-lg border border-slate-600 text-slate-400 text-sm hover:bg-slate-800"
        >
          {showUse ? 'Clear' : 'Change'}
        </button>
      </div>
    </div>
  )
}

function WorkflowStepCard({
  stepNumber,
  title,
  state,
  children,
  primaryAction,
}: {
  stepNumber: number
  title: string
  state: WorkflowStepState
  children: React.ReactNode
  primaryAction?: React.ReactNode
}) {
  const stateStyles: Record<WorkflowStepState, string> = {
    not_started: 'border-slate-600 bg-slate-800/50',
    ready: 'border-slate-500 bg-slate-800',
    running: 'border-amber-600/50 bg-amber-900/10',
    completed: 'border-emerald-700/50 bg-emerald-900/10',
    error: 'border-red-800 bg-red-900/20',
  }
  const stateLabel: Record<WorkflowStepState, string> = {
    not_started: 'Not started',
    ready: 'Ready',
    running: 'Running…',
    completed: 'Done',
    error: 'Error',
  }
  return (
    <div className={`rounded-xl border p-5 ${stateStyles[state]}`}>
      <div className="flex items-center justify-between gap-4 mb-3">
        <div className="flex items-center gap-3">
          <span className="flex items-center justify-center w-8 h-8 rounded-full bg-slate-700 text-slate-300 text-sm font-medium">
            {stepNumber}
          </span>
          <h3 className="text-base font-medium text-slate-200">{title}</h3>
          <span className="text-xs text-slate-500 uppercase tracking-wide">{stateLabel[state]}</span>
        </div>
        {primaryAction}
      </div>
      {children}
    </div>
  )
}

function SummaryCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg bg-slate-800/80 border border-slate-600 p-4 text-sm space-y-2">
      <h4 className="text-slate-400 font-medium uppercase tracking-wide">{title}</h4>
      {children}
    </div>
  )
}

function SuggestedFoldersPills({ folders, label = 'Suggested folders' }: { folders: string[]; label?: string }) {
  if (!folders.length) return null
  return (
    <div>
      <p className="text-slate-500 mb-2">{label}</p>
      <div className="flex flex-wrap gap-2">
        {folders.map((name, i) => (
          <span
            key={i}
            className="inline-block px-3 py-1.5 rounded-lg bg-slate-700 text-slate-200 text-sm font-medium"
          >
            {name}
          </span>
        ))}
      </div>
    </div>
  )
}

/** Nested tree: folder → suggested_child_folders → items assigned to each. */
function SimulateTree({ data }: { data: SimulateTreeData | SimulateResult | null }) {
  if (!data?.suggested_child_folders?.length && !(data as SimulateTreeData)?.proposed_assignments?.length) return null
  const assignments = ((data as SimulateTreeData).proposed_assignments ?? (data as SimulateResult).proposed_assignments ?? []) as { item_name?: string; suggested_child?: string; confidence?: number }[]
  const folders = (data as SimulateTreeData).suggested_child_folders ?? (data as SimulateResult).suggested_child_folders ?? []
  const root = (data as SimulateTreeData).folder_path ?? (data as SimulateResult).folder_path ?? 'Folder'
  const byFolder: Record<string, typeof assignments> = {}
  for (const a of assignments) {
    const child = (a.suggested_child || 'Unsorted').trim() || 'Unsorted'
    if (!byFolder[child]) byFolder[child] = []
    byFolder[child].push(a)
  }
  const order = [...new Set([...folders, ...Object.keys(byFolder)])]
  return (
    <div className="mt-3 rounded-lg border border-slate-600 bg-slate-900/50 p-3">
      <p className="text-xs text-slate-500 uppercase tracking-wide mb-2">Simulate tree</p>
      <div className="font-mono text-sm text-slate-300">
        <div className="font-medium text-amber-400/90">{root}</div>
        <ul className="list-none pl-4 mt-1 space-y-2">
          {order.map((folder) => (
            <li key={folder}>
              <span className="text-slate-400">↳ {folder}</span>
              {(byFolder[folder] ?? []).length > 0 && (
                <ul className="list-none pl-4 mt-0.5 text-xs text-slate-500 space-y-0.5">
                  {(byFolder[folder] ?? []).slice(0, 25).map((a, i) => (
                    <li key={i} title={String(a.confidence)}>{a.item_name ?? '—'}</li>
                  ))}
                  {(byFolder[folder] ?? []).length > 25 && <li>… +{(byFolder[folder]!.length - 25)} more</li>}
                </ul>
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

/** Graphical tree: expandable folder rows with icons, items as file rows with confidence.
 * When editable + targetFolders + onOverride are provided, each item has a "Move to" dropdown to reassign before accepting. */
function SimulateTreeGraphical({
  data,
  editable = false,
  targetFolders = [],
  overrides = {},
  onOverride,
}: {
  data: SimulateTreeData | SimulateResult | null
  editable?: boolean
  targetFolders?: string[]
  overrides?: Record<string, string>
  onOverride?: (itemName: string, folder: string) => void
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  if (!data?.suggested_child_folders?.length && !(data as SimulateTreeData)?.proposed_assignments?.length) {
    return (
      <div className="rounded-xl border border-slate-600 bg-slate-800/50 p-8 text-center text-slate-500 text-sm">
        Run Analyze then Assess to see the folder tree simulation here.
      </div>
    )
  }
  const assignments = ((data as SimulateTreeData).proposed_assignments ?? (data as SimulateResult).proposed_assignments ?? []) as { item_name?: string; suggested_child?: string; confidence?: number }[]
  const folders = (data as SimulateTreeData).suggested_child_folders ?? (data as SimulateResult).suggested_child_folders ?? []
  const root = (data as SimulateTreeData).folder_path ?? (data as SimulateResult).folder_path ?? 'Folder'
  const targetSet = targetFolders.length > 0 ? new Set(targetFolders) : null
  const fallbackFolder = targetSet ? (targetFolders.includes('Unsorted') ? 'Unsorted' : targetFolders[0]) : 'Unsorted'
  const effectiveFolder = (a: { item_name?: string; suggested_child?: string }) => {
    const name = (a.item_name ?? '').trim()
    const raw = overrides[name] ?? ((a.suggested_child || 'Unsorted').trim() || 'Unsorted')
    if (targetSet && !targetSet.has(raw)) return fallbackFolder
    return raw
  }
  const byFolder: Record<string, typeof assignments> = {}
  for (const a of assignments) {
    const child = effectiveFolder(a)
    if (!byFolder[child]) byFolder[child] = []
    byFolder[child].push(a)
  }
  const order = editable && targetFolders.length > 0
    ? [...targetFolders]
    : [...new Set([...folders, ...Object.keys(byFolder)])]
  const toggle = (folder: string) => setExpanded((prev) => {
    const next = new Set(prev)
    if (next.has(folder)) next.delete(folder)
    else next.add(folder)
    return next
  })
  return (
    <div className="rounded-xl border border-slate-600 bg-slate-800/50 overflow-hidden">
      <div className="p-3 border-b border-slate-700 bg-slate-900/50">
        <div className="flex items-center gap-2 text-slate-200 font-medium">
          <span className="text-amber-400" aria-hidden>📁</span>
          <span className="truncate" title={root}>{root.replace(/^.*[\\/]/, '') || root}</span>
          {editable && <span className="text-slate-500 text-xs font-normal">— Move items with the dropdown</span>}
        </div>
      </div>
      <div className="p-2 max-h-[420px] overflow-y-auto">
        {order.map((folder) => {
          const items = byFolder[folder] ?? []
          const isExpanded = expanded.has(folder) || (editable && items.length > 0)
          return (
            <div key={folder} className="rounded-lg border border-slate-600/80 bg-slate-900/30 overflow-hidden mb-2">
              <button
                type="button"
                onClick={() => toggle(folder)}
                className="w-full flex items-center gap-2 px-3 py-2.5 text-left hover:bg-slate-700/40 transition-colors"
              >
                <span className="text-slate-400 w-4">{isExpanded ? '▼' : '▶'}</span>
                <span className="text-amber-400/90" aria-hidden>📂</span>
                <span className="text-slate-200 font-medium flex-1 truncate">{folder}</span>
                <span className="text-slate-500 text-xs shrink-0">{items.length} item{items.length !== 1 ? 's' : ''}</span>
              </button>
              {isExpanded && items.length > 0 && (
                <div className="border-t border-slate-700 bg-slate-900/20 pl-6 pr-2 py-2 space-y-1">
                  {items.slice(0, 50).map((a, i) => (
                    <div key={i} className="flex items-center gap-2 py-1.5 text-sm text-slate-300">
                      <span className="text-slate-500 shrink-0" aria-hidden>📄</span>
                      <span className="truncate flex-1 min-w-0" title={a.item_name}>{a.item_name ?? '—'}</span>
                      {a.confidence != null && !editable && (
                        <span className={`shrink-0 text-xs px-1.5 py-0.5 rounded ${a.confidence >= 0.6 ? 'bg-emerald-900/40 text-emerald-300' : a.confidence >= 0.4 ? 'bg-amber-900/40 text-amber-300' : 'bg-slate-600 text-slate-400'}`}>
                          {Math.round(a.confidence * 100)}%
                        </span>
                      )}
                      {editable && targetFolders.length > 0 && onOverride && (
                        <select
                          className="shrink-0 rounded border border-slate-600 bg-slate-800 text-slate-200 text-xs py-1 px-2 focus:outline-none focus:ring-1 focus:ring-amber-500"
                          value={effectiveFolder(a)}
                          onChange={(e) => onOverride(a.item_name ?? '', e.target.value)}
                          aria-label={`Move ${a.item_name} to`}
                        >
                          {targetFolders.map((f) => (
                            <option key={f} value={f}>{f}</option>
                          ))}
                        </select>
                      )}
                    </div>
                  ))}
                  {items.length > 50 && <p className="text-slate-500 text-xs py-1">… +{items.length - 50} more</p>}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

/** Editable suggested folders: reject (×) or add custom. Optional Refine Categories (AI). Web Research is optional and hidden when not provided. */
function SuggestedFoldersEditor({
  suggested,
  rejected,
  onReject,
  customFolders,
  onAddCustom,
  onRemoveCustom,
  onRefineCategories,
  folderAdvisorLoading,
  highlightedFolders,
  onWebResearch,
}: {
  suggested: string[]
  rejected: Set<string>
  onReject: (name: string) => void
  customFolders: string[]
  onAddCustom: (name: string) => void
  onRemoveCustom: (name: string) => void
  onRefineCategories: () => void
  folderAdvisorLoading?: boolean
  highlightedFolders?: string[]
  onWebResearch?: () => void
}) {
  const [newFolder, setNewFolder] = useState('')
  const accepted = suggested.filter((s) => !rejected.has(s))
  const allFolders = [...accepted, ...customFolders]
  const highlightSet = useMemo(() => new Set(highlightedFolders ?? []), [highlightedFolders])

  return (
    <div className="space-y-3">
      <p className="text-slate-500 text-sm">Suggested folders — remove any you don’t want, then add your own if needed.</p>
      {allFolders.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {accepted.map((name) => (
            <span
              key={name}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium ${
                highlightSet.has(name) ? 'bg-slate-700 text-slate-200 border border-amber-400/70' : 'bg-slate-700 text-slate-200'
              }`}
            >
              {name}
              {highlightSet.has(name) && <span className="text-[10px] text-amber-400/90 uppercase">AI</span>}
              <button
                type="button"
                onClick={() => onReject(name)}
                className="text-slate-400 hover:text-red-400 focus:outline-none"
                aria-label={`Reject ${name}`}
              >
                ×
              </button>
            </span>
          ))}
          {customFolders.map((name) => (
            <span
              key={`custom-${name}`}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium ${
                highlightSet.has(name) ? 'bg-amber-900/30 border border-amber-400/70 text-amber-200' : 'bg-amber-900/30 border border-amber-700/50 text-amber-200'
              }`}
            >
              {name}
              {highlightSet.has(name) && <span className="text-[10px] text-amber-400/90 uppercase">AI</span>}
              <button
                type="button"
                onClick={() => onRemoveCustom(name)}
                className="text-amber-400/80 hover:text-red-400 focus:outline-none"
                aria-label={`Remove ${name}`}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}
      {rejected.size > 0 && (
        <p className="text-slate-500 text-xs">
          Rejected: {[...rejected].join(', ')}.
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="text"
          value={newFolder}
          onChange={(e) => setNewFolder(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              const v = newFolder.trim()
              if (v && !allFolders.includes(v)) {
                onAddCustom(v)
                setNewFolder('')
              }
            }
          }}
          placeholder="Add folder name"
          className="px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-amber-500 w-40"
        />
        <button
          type="button"
          onClick={() => {
            const v = newFolder.trim()
            if (v && !allFolders.includes(v)) {
              onAddCustom(v)
              setNewFolder('')
            }
          }}
          className="px-3 py-1.5 rounded-lg border border-slate-600 bg-slate-800 text-slate-300 text-sm hover:bg-slate-700"
        >
          Add folder
        </button>
      </div>
      <div className="flex flex-wrap gap-2 pt-2 border-t border-slate-600">
        <span className="text-slate-500 text-xs self-center">Assess recommendations:</span>
        <button
          type="button"
          onClick={onRefineCategories}
          disabled={folderAdvisorLoading}
          className="px-3 py-1.5 rounded-lg border border-amber-700/50 bg-amber-900/20 text-amber-200 text-sm hover:bg-amber-900/40 disabled:opacity-50"
        >
          {folderAdvisorLoading ? 'Refining…' : 'Refine Categories'}
        </button>
        {onWebResearch && (
          <button
            type="button"
            onClick={onWebResearch}
            className="px-3 py-1.5 rounded-lg border border-slate-600 bg-slate-800 text-slate-300 text-sm hover:bg-slate-700"
          >
            Web Research
          </button>
        )}
      </div>
    </div>
  )
}

function DeveloperDetailsCollapse({
  result,
  label = 'Result (JSON)',
  workflowMode,
  onJsonCopySuccess,
}: {
  result: string | null
  label?: string
  workflowMode?: 'analyze' | 'simulate' | 'assess' | 'recommend'
  onJsonCopySuccess?: (mode: 'analyze' | 'simulate' | 'assess' | 'recommend') => void
}) {
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  if (!result) return null
  const copyJson = async () => {
    try {
      await navigator.clipboard.writeText(result)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
      if (workflowMode) onJsonCopySuccess?.(workflowMode)
    } catch {
      /* clipboard may be denied */
    }
  }
  return (
    <div className="rounded-lg border border-slate-600 overflow-hidden">
      <div className="flex items-stretch gap-1 bg-slate-800/80 border-b border-slate-600/80">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="flex-1 px-4 py-2 text-left text-sm text-slate-400 hover:bg-slate-800 flex items-center justify-between min-w-0"
        >
          <span className="truncate">{label} · Developer details</span>
          <span className="text-slate-500 shrink-0 ml-2">{open ? '▼' : '▶'}</span>
        </button>
        <button
          type="button"
          onClick={() => void copyJson()}
          className="shrink-0 px-3 py-2 text-xs text-slate-400 hover:text-slate-200 border-l border-slate-600"
        >
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      {open && (
        <pre className="p-4 bg-slate-900 text-xs text-slate-300 overflow-auto max-h-96 border-t border-slate-600">
          {result}
        </pre>
      )}
    </div>
  )
}

function App() {
  const [authLoading, setAuthLoading] = useState(true)
  const [authSubmitting, setAuthSubmitting] = useState(false)
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null)
  const [consentRequired, setConsentRequired] = useState(false)
  const [consentSubmitting, setConsentSubmitting] = useState(false)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const me = await getCurrentUser()
        if (!cancelled) {
          setCurrentUser(me)
          if (me) {
            try {
              const perms = await fetchUserPermissionsSettings()
              if (!cancelled) setConsentRequired(!perms.consent_given)
            } catch {
              if (!cancelled) setConsentRequired(true)
            }
          } else {
            setConsentRequired(false)
          }
        }
      } catch {
        if (!cancelled) setCurrentUser(null)
      } finally {
        if (!cancelled) setAuthLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [])

  const handleLogin = useCallback(async (email: string, password: string) => {
    setAuthSubmitting(true)
    try {
      const user = await loginSession(email, password)
      setCurrentUser(user)
      try {
        const perms = await fetchUserPermissionsSettings()
        setConsentRequired(!perms.consent_given)
      } catch {
        setConsentRequired(true)
      }
    } finally {
      setAuthSubmitting(false)
    }
  }, [])

  const handleLogout = useCallback(async () => {
    await logoutSession()
    setCurrentUser(null)
    setConsentRequired(false)
  }, [])

  const handleConsentSubmit = useCallback(
    async (payload: { consent_acknowledged: boolean; consent_version: string; permissions: UserPermissionFlags }) => {
      setConsentSubmitting(true)
      try {
        const res = await saveUserPermissionsSettings({
          consent_acknowledged: payload.consent_acknowledged,
          consent_version: payload.consent_version,
          permissions: payload.permissions,
        })
        setConsentRequired(!res.consent_given)
      } finally {
        setConsentSubmitting(false)
      }
    },
    [],
  )

  const [activeMode, setActiveMode] = useState<ModeId>('analyze')
  const [folderPath, setFolderPath] = useState('')
  const [question, setQuestion] = useState('')
  const questionRef = useRef(question)
  questionRef.current = question
  /** Bumped when council appends a new user turn so the conversation panel scrolls to the active reply. */
  const [agentConversationScrollNonce, setAgentConversationScrollNonce] = useState(0)
  const councilQuestionTextareaRef = useRef<HTMLTextAreaElement | null>(null)
  const agentConversationEndRef = useRef<HTMLDivElement | null>(null)
  const agentConversationScrollRef = useRef<HTMLDivElement | null>(null)
  const adjustCouncilQuestionTextareaHeight = useCallback(() => {
    const el = councilQuestionTextareaRef.current
    if (!el) return
    const cs = window.getComputedStyle(el)
    const lh = parseFloat(cs.lineHeight)
    const pt = parseFloat(cs.paddingTop) || 0
    const pb = parseFloat(cs.paddingBottom) || 0
    const maxLines = 10
    const lineHeightPx = Number.isFinite(lh) && lh > 0 ? lh : 22
    const maxH = lineHeightPx * maxLines + pt + pb
    el.style.maxHeight = `${maxH}px`
    el.style.height = 'auto'
    const fullScroll = el.scrollHeight
    const next = Math.min(fullScroll, maxH)
    el.style.height = `${next}px`
    el.style.overflowY = fullScroll > maxH ? 'auto' : 'hidden'
  }, [])

  const appendFilesToCouncilQuestion = useCallback(async (files: FileList | null) => {
    if (!files?.length) return
    const next = await appendChatDroppedFiles(questionRef.current, files)
    setQuestion(next)
    requestAnimationFrame(() => {
      adjustCouncilQuestionTextareaHeight()
      councilQuestionTextareaRef.current?.focus()
      const ta = councilQuestionTextareaRef.current
      if (ta) {
        const len = ta.value.length
        ta.setSelectionRange(len, len)
      }
    })
  }, [adjustCouncilQuestionTextareaHeight])

  useLayoutEffect(() => {
    adjustCouncilQuestionTextareaHeight()
  }, [question, adjustCouncilQuestionTextareaHeight])

  useEffect(() => {
    const onDomFirstTranscript = (e: Event) => {
      if (!(e instanceof CustomEvent)) return
      const d = e.detail as { text?: string } | undefined
      const text = typeof d?.text === 'string' ? d.text : ''
      if (!text) return
      const el = document.activeElement
      if (
        !(el instanceof HTMLTextAreaElement) ||
        el.dataset.zenafVoiceInsert !== 'council-question' ||
        el !== councilQuestionTextareaRef.current
      ) {
        return
      }
      const start = el.selectionStart ?? 0
      const end = el.selectionEnd ?? 0
      setQuestion((q) => insertTextAtSelection(q, text, start, end))
      e.preventDefault()
      requestAnimationFrame(() => {
        const ta = councilQuestionTextareaRef.current
        if (!ta) return
        ta.focus()
        const pos = start + text.length
        ta.setSelectionRange(pos, pos)
        adjustCouncilQuestionTextareaHeight()
      })
    }
    window.addEventListener(ZENAF_VOICE_TRANSCRIPT_DOM_FIRST, onDomFirstTranscript)
    return () => window.removeEventListener(ZENAF_VOICE_TRANSCRIPT_DOM_FIRST, onDomFirstTranscript)
  }, [adjustCouncilQuestionTextareaHeight])

  useEffect(() => {
    const onInsert = (e: Event) => {
      const d = (e as CustomEvent<VeFocusInsertTextDetail>).detail
      if (
        !d ||
        d.entity_type !== 'council' ||
        d.entity_id !== COUNCIL_REPLY_FOCUS_ID ||
        d.field_key !== 'reply' ||
        !d.text
      ) {
        return
      }
      const start = d.selectionStart ?? 0
      const end = d.selectionEnd ?? 0
      setQuestion((q) => insertTextAtSelection(q, d.text, start, end))
      requestAnimationFrame(() => {
        const ta = councilQuestionTextareaRef.current
        if (!ta) return
        ta.focus()
        const pos = start + d.text.length
        ta.setSelectionRange(pos, pos)
        adjustCouncilQuestionTextareaHeight()
      })
    }
    const onRewrite = (e: Event) => {
      const d = (e as CustomEvent<VeFocusApplyRewriteDetail>).detail
      if (
        !d ||
        d.entity_type !== 'council' ||
        d.entity_id !== COUNCIL_REPLY_FOCUS_ID ||
        d.field_key !== 'reply' ||
        d.text == null
      ) {
        return
      }
      setQuestion(d.text)
    }
    window.addEventListener(ZENAF_VE_FOCUS_INSERT_TEXT, onInsert)
    window.addEventListener(ZENAF_VE_FOCUS_APPLY_REWRITE, onRewrite)
    return () => {
      window.removeEventListener(ZENAF_VE_FOCUS_INSERT_TEXT, onInsert)
      window.removeEventListener(ZENAF_VE_FOCUS_APPLY_REWRITE, onRewrite)
    }
  }, [adjustCouncilQuestionTextareaHeight])

  const [query, setQuery] = useState('')
  const [result, setResult] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  /** Short non-streaming node transform (VE); avoids council “Running…” for bounded asks. */
  const [councilTransformLoading, setCouncilTransformLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Session state: one source of truth per stage (do not reuse across steps).
  // analysisResult: step 2 analysis summary
  const [lastAnalyzeResult, setLastAnalyzeResult] = useState<AnalyzeResult | null>(null)
  // assessPreviewResult: step 2 optional assess; tree preview lives in lastAssessResult.simulate_tree only (not in lastSimulateResult)
  const [lastAssessResult, setLastAssessResult] = useState<AssessResult | null>(null)
  // folderRecommendations: step 3 raw recommend result; user edits via rejectedRecommendations + customRecommendations
  const [lastRecommendResult, setLastRecommendResult] = useState<RecommendResult | null>(null)
  // simulationPlan: step 4/5 tree; set ONLY by explicit "Run simulation" (never by assess)
  const [lastSimulateResult, setLastSimulateResult] = useState<SimulateResult | null>(null)
  const [lastFolderPath, setLastFolderPath] = useState('')
  const [lastMode, setLastMode] = useState<ModeId | null>(null)
  const [lastCouncilResult, setLastCouncilResult] = useState<CouncilResult | null>(null)
  const [lastWebResearchResult, setLastWebResearchResult] = useState<WebResearchResult | null>(null)
  const [lastNextStepResult, setLastNextStepResult] = useState<NextStepResult | null>(null)
  const [nextStepQuestion, setNextStepQuestion] = useState('')
  const [useLastResultAsContext, setUseLastResultAsContext] = useState(false)
  // Reassess with perspective: modal to pick one personality, results, approve/deny
  const [reassessModalOpen, setReassessModalOpen] = useState(false)
  const [reassessSelectedId, setReassessSelectedId] = useState<string | null>(null)
  const [reassessResults, setReassessResults] = useState<ReassessItemResult[] | null>(null)
  const [reassessReviewerName, setReassessReviewerName] = useState<string | null>(null)
  const [reassessApproved, setReassessApproved] = useState<Set<string>>(new Set())
  const [reassessDenied, setReassessDenied] = useState<Set<string>>(new Set())

  const [intakeQueue, setIntakeQueue] = useState<IntakeQueueItem[]>([])
  const [emailIntakeBody, setEmailIntakeBody] = useState('')
  const [faxIntakeBody, setFaxIntakeBody] = useState('')
  const [intakeLoading, setIntakeLoading] = useState(false)
  const [intakeQueuePanelHeight, setIntakeQueuePanelHeight] = useState(360)
  const [intakeQueueStatusFilter, setIntakeQueueStatusFilter] = useState<string>('')
  const [intakeLaneExpanded, setIntakeLaneExpanded] = useState<Record<string, boolean>>(() => ({
    needs_attention: true,
    insurance_medical: false,
    ordering_supplies: false,
    waiting_fyi: true,
    likely_junk: false,
  }))
  const [intakeQueueSearch, setIntakeQueueSearch] = useState('')
  const [intakeQueueSearchDebounced, setIntakeQueueSearchDebounced] = useState('')
  const [intakeQueueSort, setIntakeQueueSort] = useState<'created_desc' | 'created_asc'>('created_desc')
  const [intakeQueueShowArchived, setIntakeQueueShowArchived] = useState(false)
  const [emailConnectionExpanded, setEmailConnectionExpanded] = useState(false)
  const [intakeWhyItemId, setIntakeWhyItemId] = useState<string | null>(null)
  const [intakeJudgmentChain, setIntakeJudgmentChain] = useState<{ item_id: string; chain: JudgmentRecordInUI[] } | null>(null)
  const [intakeJudgmentError, setIntakeJudgmentError] = useState<string | null>(null)
  const intakeQueueResizeRef = useRef<{ startY: number; startH: number } | null>(null)
  /** Synced after `currentTopic` / `mainView` / `veSelection` each render — used by council preflight. */
  const councilVeFocusRef = useRef<FocusContext | null>(null)
  const runCouncilRef = useRef<
    | ((
        overrideQuestion?: string,
        options?: {
          preserveComposer?: boolean
          threadDisplayHint?: string
          /** Thread snapshot for digression background / pending scan when state has not flushed yet (invite trim). */
          councilContextThreadOverride?: DigressionBackgroundThreadRow[]
        },
      ) => Promise<void>)
    | null
  >(null)
  const councilIdeaLabelsRef = useRef<CouncilIdeaLabelsSnapshot | null>(null)
  /** Last Zenaf `conversation_subject` from council stream `done` — echoed on the next POST /run/stream. */
  const councilConversationSubjectRef = useRef<ConversationSubject | null>(null)
  /** Proposed VE field update from Zenaf; echoed until commit or cleared when absent on `done`. */
  const councilPendingIntegrationRef = useRef<PendingIntegrationPayload | null>(null)
  /** Server-seeded owner/assignee elicitation; echo until Lane A confirm or explicit clear. */
  const councilPendingVeElicitationRef = useRef<PendingVeElicitationPayload | null>(null)
  /** Last committed integration from stream `done` — sticky for “where does this live?”. */
  const councilLastIntegrationCommitRef = useRef<LastIntegrationCommitPayload | null>(null)
  /** Echo `last_created_project_id` for Lane A follow-up task batches (`context.ve_direct_session`). */
  const councilVeDirectSessionRef = useRef<{ last_created_project_id?: string } | null>(null)
  /** Matches `councilRunId` for the in-flight / last council reply — keeps resonance slider key stable stream → final message. */
  const councilResonanceRunIdRef = useRef<string | null>(null)
  /** Stable id for the orphan “agent response” strip when `agentThread` is empty (avoids shared `thread-fallback` key). */
  const threadAgentStripResonanceIdRef = useRef<string>(
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `agent-strip-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
  )
  const councilVeEntityBundleRef = useRef<VisionMapEntityBundle | null>(null)
  const councilRuntimeRef = useRef<{
    mainView: string
    currentTopic: { label: string; modeLabel: string | null; summary: string }
    ve_selection: VESelection | null
  }>({
    mainView: 'vision_map',
    currentTopic: { label: '', modeLabel: null, summary: '' },
    ve_selection: null,
  })
  const [councilExpandedMode, setCouncilExpandedMode] = useState(false)
  /** Bumps after server-side VE writes (integration commit or Lane A) so Vision Execution detail panels refetch. */
  const [councilVeServerWriteNonce, setCouncilVeServerWriteNonce] = useState(0)
  /** Scoped sub-thread: Zenaf sees only this entity + short parent background (server: is_scoped_digression). */
  const [councilScopedDigression, setCouncilScopedDigression] = useState<EntityMentionOpenPayload | null>(null)
  /** When set, conversation list shows only rows from this index (scoped context replaces full thread view). */
  const [councilScopeThreadStartIndex, setCouncilScopeThreadStartIndex] = useState<number | null>(null)
  const councilScopeThreadStartIndexRef = useRef<number | null>(null)
  const councilScopedDigressionRef = useRef<EntityMentionOpenPayload | null>(null)
  useEffect(() => {
    councilScopeThreadStartIndexRef.current = councilScopeThreadStartIndex
  }, [councilScopeThreadStartIndex])
  useEffect(() => {
    councilScopedDigressionRef.current = councilScopedDigression
  }, [councilScopedDigression])
  /** Bumped when the open idea editor refreshes council snapshot — re-resolve scoped banner label. */
  const [councilIdeaLiveLabelsSeq, setCouncilIdeaLiveLabelsSeq] = useState(0)
  const bumpCouncilIdeaLiveLabelsSeq = useCallback(() => {
    setCouncilIdeaLiveLabelsSeq((n) => n + 1)
  }, [])
  const scopedDigressionKey = councilScopedDigression
    ? `${councilScopedDigression.entityType}:${councilScopedDigression.entityId}`
    : ''
  useEffect(() => {
    if (!scopedDigressionKey) return
    setCouncilScopedDigression((prev) => {
      if (!prev) return prev
      const next = enrichScopedDigressionLabel(prev, {
        ideaLabels: councilIdeaLabelsRef.current,
        bundle: councilVeEntityBundleRef.current,
      })
      return next.label === prev.label ? prev : next
    })
  }, [scopedDigressionKey, councilIdeaLiveLabelsSeq])
  /** Expanded `scoped_thread_nest` rows in the council transcript (collapsed by default). */
  const [councilExpandedNestIds, setCouncilExpandedNestIds] = useState<Set<string>>(() => new Set())
  const [councilSeatSlots, setCouncilSeatSlots] = useState<CouncilSeatSlot[]>(() =>
    Array.from({ length: EXPANDED_MAX_SEATS }, (_, i) => ({
      id: `cs-${i}`,
      actorId: (i === 0 ? 'zenaf' : null) as string | null,
    })),
  )
  const [mandatesBySeatId, setMandatesBySeatId] = useState<Record<string, string>>(() => ({
    'cs-0': 'thinking_partner',
  }))
  const [selectedCouncilSlotId, setSelectedCouncilSlotId] = useState<string | null>('cs-0')
  /** Next council run: seat-based by default; map / "Ask full council" sets full_multiseat (preset multi-seat council). */
  const councilInvocationNextRef = useRef<'default' | 'full_multiseat'>('default')
  /** When map triggers council, stash payload so bounded transforms resolve anchor + title without re-streaming. */
  const councilRunMapPayloadRef = useRef<MapNodePayload | null>(null)
  const [expandedThreadGuidePromptId, setExpandedThreadGuidePromptId] = useState<string | null>(null)
  const [activeConversationalSuggestionPromptId, setActiveConversationalSuggestionPromptId] =
    useState<string | null>(null)
  const [guideStackListOpen, setGuideStackListOpen] = useState(false)
  const [nestedStackGuidePromptId, setNestedStackGuidePromptId] = useState<string | null>(null)
  const [seenStackGuidePromptIds, setSeenStackGuidePromptIds] = useState<string[]>([])
  const [councilAdvancedOptions, setCouncilAdvancedOptions] = useState(false)
  // Council personality mode: which version of each seat to use (user's choice, per purpose).
  const [councilPersonalityMode, setCouncilPersonalityMode] =
    useState<CouncilPersonalityMode>('blend')
  const [mirrorNotice, setMirrorNotice] = useState<string | null>(null)
  useEffect(() => {
    const t = setTimeout(() => setIntakeQueueSearchDebounced(intakeQueueSearch), 300)
    return () => clearTimeout(t)
  }, [intakeQueueSearch])
  const [intakeJudgmentLoadingId, setIntakeJudgmentLoadingId] = useState<string | null>(null)
  const fetchIntakeJudgment = useCallback(async (itemId: string) => {
    const itemIdStr = String(itemId)
    setIntakeJudgmentError(null)
    setIntakeJudgmentLoadingId(itemIdStr)
    try {
      const res = await fetch(`${API_BASE}/intake/queue/${encodeURIComponent(itemId)}/judgment`)
      const data = res.ok ? await res.json().catch(() => ({})) : null
      if (!res.ok) {
        setIntakeJudgmentChain({ item_id: itemIdStr, chain: [] })
        setIntakeJudgmentError(typeof data?.detail === 'string' ? data.detail : `Failed to load (${res.status})`)
        return
      }
      setIntakeJudgmentChain({
        item_id: data?.item_id != null ? String(data.item_id) : itemIdStr,
        chain: Array.isArray(data?.chain) ? data.chain : [],
      })
    } catch (e) {
      setIntakeJudgmentChain({ item_id: itemIdStr, chain: [] })
      setIntakeJudgmentError(e instanceof Error ? e.message : 'Could not load judgment')
    } finally {
      setIntakeJudgmentLoadingId(null)
    }
  }, [])
  const [imapHost, setImapHost] = useState('')
  const [imapUser, setImapUser] = useState('')
  const [imapPassword, setImapPassword] = useState('')
  const [imapMailbox, setImapMailbox] = useState('INBOX')
  const [imapLabel, setImapLabel] = useState('')
  const [imapConfigSaved, setImapConfigSaved] = useState<string | null>(null)
  const [gmailOAuthEmail, setGmailOAuthEmail] = useState<string | null>(null)
  const [gmailOAuthConfigured, setGmailOAuthConfigured] = useState<boolean>(true)
  const [googleClientId, setGoogleClientId] = useState('')
  const [googleClientSecret, setGoogleClientSecret] = useState('')
  const [googleOAuthConfigSaved, setGoogleOAuthConfigSaved] = useState<string | null>(null)
  const [gmailOAuthError, setGmailOAuthError] = useState<string | null>(null)
  const [gmailOAuthConfigPath, setGmailOAuthConfigPath] = useState<string | null>(null)

  // Current focus (guided workflow)
  const [currentFocusPath, setCurrentFocusPath] = useState('')
  const [currentFocusMode, setCurrentFocusMode] = useState<ModeId | null>(null)
  const [currentFocusHasResult, setCurrentFocusHasResult] = useState(false)

  // Workspace Organizer collapse (nest when not in active use)
  const [workspaceCollapsed, setWorkspaceCollapsed] = useState(false)

  // Workspace Organizer: which step is running; recent folders for quick-pick
  const [workflowRunningStep, setWorkflowRunningStep] = useState<'analyze' | 'simulate' | 'assess' | 'recommend' | null>(null)
  const [recentFolders, setRecentFolders] = useState<string[]>([])
  const [workflowStep3Tab, setWorkflowStep3Tab] = useState<'summary' | 'tree'>('summary')
  // Single-step workflow: only one step visible at a time (1–5)
  const [workspaceOrganizerStep, setWorkspaceOrganizerStep] = useState<1 | 2 | 3 | 4 | 5>(1)

  // Step 5: editable recommendations (reject suggested, add custom)
  const [rejectedRecommendations, setRejectedRecommendations] = useState<Set<string>>(new Set())
  const [customRecommendations, setCustomRecommendations] = useState<string[]>([])

  /** Latest workspace AI trace for low-friction outcome capture (copy / dismiss / apply). */
  const workspaceOutcomeTargetRef = useRef<{
    trace: AiActionTrace
    action_intent: string
    learning_record_id?: string | null
  } | null>(null)

  const [workspaceTraceOutcomeBanner, setWorkspaceTraceOutcomeBanner] = useState<string | null>(null)

  const recordWorkspaceTraceUserOutcome = useCallback((trace: AiActionTrace, outcome: AiUserOutcome) => {
    recordWorkspaceTraceOutcome(trace, outcome)
    if (outcome === 'none') return
    const labels: Record<Exclude<AiUserOutcome, 'none'>, string> = {
      applied:
        'Workspace Organizer: recorded in your in-memory action log — applied. (Not persisted; same ring as Vision & Execution traces.)',
      dismissed:
        'Workspace Organizer: recorded in your in-memory action log — dismissed. (Not persisted.)',
      edited:
        'Workspace Organizer: recorded in your in-memory action log — edited. (Not persisted.)',
      copied:
        'Workspace Organizer: recorded in your in-memory action log — copied. (Not persisted.)',
    }
    setWorkspaceTraceOutcomeBanner(labels[outcome])
  }, [])

  const onWorkspaceJsonCopied = useCallback((mode: 'analyze' | 'simulate' | 'assess' | 'recommend') => {
    const w = workspaceOutcomeTargetRef.current
    const expected = WORKFLOW_JSON_INTENT_BY_MODE[mode]
    if (w?.action_intent === expected) {
      try {
        recordWorkspaceTraceUserOutcome(w.trace, 'copied')
      } catch {
        /* ignore */
      }
      postWorkspaceLearningFromRef(w, 'copied')
    }
  }, [recordWorkspaceTraceUserOutcome])

  const rejectRecommendation = (name: string) => {
    setRejectedRecommendations((prev) => new Set(prev).add(name))
    const w = workspaceOutcomeTargetRef.current
    if (w?.action_intent === WORKSPACE_ACTION_INTENTS.recommend) {
      try {
        // Curating the list (one fewer AI-suggested folder) — not rejecting the whole recommend run.
        recordWorkspaceTraceUserOutcome(w.trace, 'edited')
      } catch {
        /* ignore */
      }
      postWorkspaceLearningFromRef(w, 'edited')
    }
  }
  const addCustomRecommendation = (name: string) => {
    const n = name.trim()
    if (!n) return
    const suggested = lastRecommendResult?.suggested_child_folders ?? []
    const currentList = [...suggested.filter((s) => !rejectedRecommendations.has(s)), ...customRecommendations]
    if (findExistingFolderMatch(n, currentList)) return
    setCustomRecommendations((prev) => (prev.includes(n) ? prev : [...prev, n]))
    const w = workspaceOutcomeTargetRef.current
    if (w?.action_intent === WORKSPACE_ACTION_INTENTS.recommend) {
      try {
        recordWorkspaceTraceUserOutcome(w.trace, 'edited')
      } catch {
        /* ignore */
      }
      postWorkspaceLearningFromRef(w, 'edited')
    }
  }
  const removeCustomRecommendation = (name: string) => {
    setCustomRecommendations((prev) => prev.filter((x) => x !== name))
    const w = workspaceOutcomeTargetRef.current
    if (w?.action_intent === WORKSPACE_ACTION_INTENTS.recommend) {
      try {
        recordWorkspaceTraceUserOutcome(w.trace, 'edited')
      } catch {
        /* ignore */
      }
      postWorkspaceLearningFromRef(w, 'edited')
    }
  }

  // Step 3: track which AI suggestions have been applied (by normalized key) and which existing pills to show as "matched by AI"
  const [appliedFolderSuggestions, setAppliedFolderSuggestions] = useState<Set<string>>(new Set())
  const [appliedAiMatchedFolders, setAppliedAiMatchedFolders] = useState<string[]>([])
  const [replaceListConfirmOpen, setReplaceListConfirmOpen] = useState(false)

  // Step 4: user can move items to a different folder before accepting; key = item_name, value = suggested_child
  const [simulationOverrides, setSimulationOverrides] = useState<Record<string, string>>({})

  // Single source of truth for "approved folder list": recommended minus rejected plus custom. Used by Run simulation and by Council/Next Step context.
  const approvedFolders = useMemo(() => {
    const suggested = lastRecommendResult?.suggested_child_folders ?? []
    return [...suggested.filter((s) => !rejectedRecommendations.has(s)), ...customRecommendations]
  }, [lastRecommendResult?.suggested_child_folders, rejectedRecommendations, customRecommendations])

  // Effective folder list for simulation tree: approved + Unsorted so deleted folders are never valid targets.
  const effectiveSimulateTargetFolders = useMemo(() => {
    if (approvedFolders.length === 0) return []
    return approvedFolders.includes('Unsorted') ? [...approvedFolders] : [...approvedFolders, 'Unsorted']
  }, [approvedFolders])

  // Drop overrides that point to folders no longer in the effective list (e.g. after user deleted a folder).
  const filteredSimulationOverrides = useMemo(() => {
    const set = new Set(effectiveSimulateTargetFolders)
    return Object.fromEntries(Object.entries(simulationOverrides).filter(([, folder]) => set.has(folder)))
  }, [simulationOverrides, effectiveSimulateTargetFolders])

  // Folder workflow: Refine Categories result (separate from council; declared here so folderAdvisorParsedSuggestions can use it)
  const [folderAdvisorResult, setFolderAdvisorResult] = useState<string | null>(null)
  const [folderAdvisorStreaming, setFolderAdvisorStreaming] = useState('')
  const [folderAdvisorLoading, setFolderAdvisorLoading] = useState(false)

  const folderAdvisorParsedSuggestions = useMemo(
    () => (folderAdvisorResult ? parseFolderAdvisorResult(folderAdvisorResult) : []),
    [folderAdvisorResult]
  )

  useEffect(() => {
    setAppliedFolderSuggestions(new Set())
    setAppliedAiMatchedFolders([])
  }, [folderAdvisorResult])

  const folderHighlightForEditor = useMemo(
    () => [...new Set([...folderAdvisorParsedSuggestions.map((s) => s.folder), ...appliedAiMatchedFolders])],
    [folderAdvisorParsedSuggestions, appliedAiMatchedFolders]
  )

  const addRecentFolder = (path: string) => {
    const p = path.trim()
    if (!p) return
    setRecentFolders((prev) => [p, ...prev.filter((x) => x !== p)].slice(0, 10))
  }

  const fetchIntakeQueue = async () => {
    setIntakeLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      params.set('limit', '200')
      if (intakeQueueStatusFilter) params.set('status', intakeQueueStatusFilter)
      if (intakeQueueSearchDebounced.trim()) params.set('search', intakeQueueSearchDebounced.trim())
      params.set('sort', intakeQueueSort)
      if (intakeQueueShowArchived) params.set('include_archived', 'true')
      const res = await fetch(`${API_BASE}/intake/queue?${params.toString()}`)
      if (!res.ok) throw new Error(await res.text())
      const data = await res.json()
      setIntakeQueue(Array.isArray(data) ? data : [])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load queue')
    } finally {
      setIntakeLoading(false)
    }
  }
  useEffect(() => {
    if (activeMode !== 'ordering_queue') return
    fetchIntakeQueue()
  }, [activeMode, intakeQueueStatusFilter, intakeQueueSearchDebounced, intakeQueueSort, intakeQueueShowArchived])

  const onIntakeQueueResizeMove = useCallback((e: MouseEvent) => {
    const r = intakeQueueResizeRef.current
    if (!r) return
    const delta = e.clientY - r.startY
    const newH = Math.min(Math.max(200, r.startH + delta), typeof window !== 'undefined' ? window.innerHeight * 0.8 : 800)
    setIntakeQueuePanelHeight(newH)
  }, [])
  const onIntakeQueueResizeEnd = useCallback(() => {
    intakeQueueResizeRef.current = null
  }, [])
  useEffect(() => {
    document.addEventListener('mousemove', onIntakeQueueResizeMove)
    document.addEventListener('mouseup', onIntakeQueueResizeEnd)
    return () => {
      document.removeEventListener('mousemove', onIntakeQueueResizeMove)
      document.removeEventListener('mouseup', onIntakeQueueResizeEnd)
    }
  }, [onIntakeQueueResizeMove, onIntakeQueueResizeEnd])

  const submitEmailIntake = async () => {
    if (!emailIntakeBody.trim()) return
    setIntakeLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/intake/email`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ raw_body: emailIntakeBody }),
      })
      if (!res.ok) throw new Error(await res.text())
      setEmailIntakeBody('')
      await fetchIntakeQueue()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Email intake failed')
    } finally {
      setIntakeLoading(false)
    }
  }

  const updateIntakeItemStatus = async (itemId: string, status: string) => {
    try {
      const res = await fetch(`${API_BASE}/intake/queue/${encodeURIComponent(itemId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      })
      if (!res.ok) throw new Error(await res.text())
      await fetchIntakeQueue()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Update failed')
    }
  }

  const archiveIntakeItem = async (itemId: string) => {
    try {
      const res = await fetch(`${API_BASE}/intake/queue/${encodeURIComponent(itemId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ archived: true }),
      })
      if (!res.ok) throw new Error(await res.text())
      if (intakeDetailItemId === itemId) setIntakeDetailItemId(null)
      await fetchIntakeQueue()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Archive failed')
    }
  }

  const [intakeDetailItemId, setIntakeDetailItemId] = useState<string | null>(null)
  const [intakeLaneOverrideDraft, setIntakeLaneOverrideDraft] = useState<string>('')
  const [intakeCorrectionNoteDraft, setIntakeCorrectionNoteDraft] = useState<string>('')
  const [intakeLaneSaveError, setIntakeLaneSaveError] = useState<string | null>(null)
  const [createTaskProjectId, setCreateTaskProjectId] = useState<string>('')
  const [createTaskTitle, setCreateTaskTitle] = useState<string>('')
  const [createTaskSummary, setCreateTaskSummary] = useState<string>('')
  const [createTaskNotes, setCreateTaskNotes] = useState<string>('')
  const [createTaskLoadingId, setCreateTaskLoadingId] = useState<string | null>(null)
  const [createTaskResult, setCreateTaskResult] = useState<{ taskId: string; decisionId?: string } | null>(null)
  const [createTaskError, setCreateTaskError] = useState<string | null>(null)
  const saveIntakeLaneCorrection = async (itemId: string) => {
    setIntakeLaneSaveError(null)
    const laneOverride = (intakeLaneOverrideDraft || '').trim()
    const note = (intakeCorrectionNoteDraft || '').trim()
    const isSettingOverride = laneOverride !== ''
    if (isSettingOverride && !note) {
      setIntakeLaneSaveError('Correction note is required when changing lane')
      return
    }
    const body: { lane_override?: string; correction_note?: string } = {}
    if (laneOverride !== '') {
      body.lane_override = laneOverride
      body.correction_note = note || 'Manual lane change'
    } else {
      body.lane_override = ''
      body.correction_note = note || 'Cleared manual lane'
    }
    try {
      const res = await fetch(`${API_BASE}/intake/queue/${encodeURIComponent(itemId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || res.statusText)
      }
      await fetchIntakeQueue()
      setIntakeCorrectionNoteDraft('')
      if (intakeDetailItemId === itemId) fetchIntakeJudgment(itemId)
    } catch (e) {
      setIntakeLaneSaveError(e instanceof Error ? e.message : 'Save failed')
    }
  }

  const createTaskFromIntake = async (itemId: string, subject: string, previewSummary: string) => {
    const projectId = createTaskProjectId.trim()
    if (!projectId) {
      setCreateTaskError('Project ID is required')
      return
    }
    setCreateTaskError(null)
    setCreateTaskResult(null)
    setCreateTaskLoadingId(itemId)
    try {
      const effectiveSubject = subject || '(No subject)'
      const bodyTitle = (createTaskTitle || '').trim() || effectiveSubject
      const bodySummary = (createTaskSummary || '').trim() || previewSummary || ''
      const sourceJudgmentId =
        intakeJudgmentChain?.item_id === itemId && intakeJudgmentChain.chain.length > 0
          ? String(intakeJudgmentChain.chain[intakeJudgmentChain.chain.length - 1].id || '')
          : undefined
      const res = await fetch(`${API_BASE}/intake/queue/${encodeURIComponent(itemId)}/create-task`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: projectId,
          title: bodyTitle,
          summary: bodySummary,
          notes: createTaskNotes,
          source_judgment_id: sourceJudgmentId,
        }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        throw new Error((data && (data.detail || data.error)) || res.statusText || 'Create task failed')
      }
      const taskId = data?.task?.id ? String(data.task.id) : ''
      const decisionId = data?.decision_id ? String(data.decision_id) : undefined
      if (!taskId) {
        throw new Error('Create task succeeded but no task id was returned')
      }
      setCreateTaskResult({ taskId, decisionId })
      // Optionally refresh queue so status reflects any downstream changes later
      await fetchIntakeQueue()
    } catch (e) {
      setCreateTaskError(e instanceof Error ? e.message : 'Create task failed')
    } finally {
      setCreateTaskLoadingId(null)
    }
  }

  const [intakePollResult, setIntakePollResult] = useState<
    | { added: number; skipped_duplicates: number; errors: string[] }
    | { detail: string }
    | null
  >(null)
  const fetchIntakeEmailConfig = async () => {
    try {
      const res = await fetch(`${API_BASE}/intake/config/email`)
      const data = await res.json().catch(() => ({}))
      setImapHost(data.host ?? '')
      setImapUser(data.user ?? '')
      setImapMailbox(data.mailbox ?? 'INBOX')
      setImapLabel(data.label ?? '')
      // password never returned by API; leave local state as-is
    } catch {
      // ignore
    }
  }

  const saveIntakeEmailConfig = async () => {
    setImapConfigSaved(null)
    if (!imapHost.trim() || !imapUser.trim()) {
      setImapConfigSaved('Host and user are required')
      return
    }
    if (!imapPassword.trim()) {
      setImapConfigSaved('Password is required (use an app password for Gmail)')
      return
    }
    try {
      const res = await fetch(`${API_BASE}/intake/config/email`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          host: imapHost.trim(),
          user: imapUser.trim(),
          password: imapPassword.trim(),
          mailbox: imapMailbox.trim() || 'INBOX',
          label: imapLabel.trim(),
        }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        const msg = data.detail || res.statusText || 'Save failed'
        const hint = res.status === 404 ? ` — Is the API running at ${API_BASE}?` : ''
        setImapConfigSaved(`${res.status} ${msg}${hint}`)
        return
      }
      setImapConfigSaved('Saved. You can use Poll email now.')
      setImapPassword('')
    } catch (e) {
      setImapConfigSaved((e instanceof Error ? e.message : 'Save failed') + ` — Is the API running at ${API_BASE}?`)
    }
  }

  const pollEmailIntake = async () => {
    setIntakePollResult(null)
    try {
      const res = await fetch(`${API_BASE}/intake/email/poll`, { method: 'POST' })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setIntakePollResult({ detail: data.detail || res.statusText })
        return
      }
      setIntakePollResult({
        added: data.added ?? 0,
        skipped_duplicates: data.skipped_duplicates ?? 0,
        errors: Array.isArray(data.errors) ? data.errors : [],
      })
      await fetchIntakeQueue()
    } catch (e) {
      setIntakePollResult({ detail: e instanceof Error ? e.message : 'Poll failed' })
    }
  }

  const submitFaxIntake = async () => {
    if (!faxIntakeBody.trim()) return
    setIntakeLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/intake/fax`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ raw_content: faxIntakeBody }),
      })
      if (!res.ok) throw new Error(await res.text())
      setFaxIntakeBody('')
      await fetchIntakeQueue()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Fax intake failed')
    } finally {
      setIntakeLoading(false)
    }
  }

  const runMode = async (
    mode: 'analyze' | 'simulate' | 'assess' | 'recommend',
    path: string,
    extraParams?: { suggested_folders?: string[] }
  ): Promise<boolean> => {
    const apiMode = mode === 'assess' ? 'assess_uncertainty' : mode
    setError(null)
    setWorkspaceTraceOutcomeBanner(null)
    setResult(null)
    setLoading(true)
    setWorkflowRunningStep(mode)
    const params: { folder_path?: string; suggested_folders?: string[] } = { folder_path: path || undefined }
    if (mode === 'simulate' && extraParams?.suggested_folders?.length) params.suggested_folders = extraParams.suggested_folders
    const intentByMode: Record<typeof mode, string> = {
      analyze: WORKSPACE_ACTION_INTENTS.analyze,
      simulate: WORKSPACE_ACTION_INTENTS.simulate,
      assess: WORKSPACE_ACTION_INTENTS.assess,
      recommend: WORKSPACE_ACTION_INTENTS.recommend,
    }
    try {
      const res = await fetch(`${RUN_API_BASE}/run`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mode: apiMode,
          params,
          routing_context: buildWorkspaceRunRoutingContext(intentByMode[mode], false),
        }),
      })
      const data: RunResponse & { detail?: string } = await res.json()
      if (!res.ok) {
        setError(data.error || data.detail || res.statusText || `HTTP ${res.status}`)
        return false
      }
      if (data.execution_blocked) {
        setError(workspaceExecutionBlockedMessage(data))
        return false
      }
      if (!data.ok || data.result == null) {
        setError(data.error || 'No result')
        return false
      }
      const raw = data.result as Record<string, unknown>
      try {
        const tr = emitWorkspaceTraceFromResult({
          action_intent: intentByMode[mode],
          folder_path: path || null,
          input_snapshot: buildWorkspaceJsonRunSnapshot(apiMode, path, mode === 'simulate' ? extraParams : undefined),
          result: raw,
          resolved_model_used: data.model_used ?? undefined,
        })
        workspaceOutcomeTargetRef.current = { trace: tr, action_intent: intentByMode[mode] }
      } catch {
        /* substrate must not affect workspace UX */
      }
      setResult(JSON.stringify(data.result, null, 2))
      setLastFolderPath(path)
      addRecentFolder(path)
      setLastMode(mode)
      setCurrentFocusPath(path)
      setCurrentFocusMode(mode)
      setCurrentFocusHasResult(true)
      if (mode === 'analyze') {
        setLastAnalyzeResult(raw as AnalyzeResult)
      } else if (mode === 'simulate') {
        setLastSimulateResult(raw as SimulateResult)
        setSimulationOverrides({})
      } else if (mode === 'assess') {
        setLastAssessResult(raw as AssessResult)
        setReassessResults(null)
        setReassessReviewerName(null)
        setReassessApproved(new Set())
        setReassessDenied(new Set())
        // Do NOT set lastSimulateResult here. Assess preview tree lives only in lastAssessResult.simulate_tree.
        // lastSimulateResult is the source of truth for step 4/5 and is set ONLY by explicit "Run simulation".
      } else {
        setLastRecommendResult(raw as RecommendResult)
        setRejectedRecommendations(new Set())
        setCustomRecommendations([])
        setLastSimulateResult(null)
        // New recommendations invalidate any previous simulation (different folder list).
      }
      return true
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Request failed')
      return false
    } finally {
      setLoading(false)
      setWorkflowRunningStep(null)
    }
  }

  /** Workspace Organizer: one action to fetch analyze + recommend for the selected folder. */
  const getSuggestions = async () => {
    const path = (folderPath || lastFolderPath).trim()
    if (!path) return
    setLastFolderPath(path)
    const ok = await runMode('analyze', path)
    if (ok) await runMode('recommend', path)
  }

  const buildContextBlock = (approvedFoldersForContext?: string[]): string => {
    if (!useLastResultAsContext) return ''
    const lines: string[] = []
    if (lastFolderPath) lines.push(`Folder: ${lastFolderPath}`)
    if (lastMode === 'analyze' && lastAnalyzeResult && !lastAnalyzeResult.error) {
      lines.push(`Mode: Analyze. Context: ${lastAnalyzeResult.inferred_context_domain ?? '—'}. Items: ${lastAnalyzeResult.item_count ?? 0}.`)
    } else if (lastMode === 'simulate' && lastSimulateResult && !lastSimulateResult.error) {
      lines.push(`Mode: Simulate. Assignments: ${lastSimulateResult.proposed_assignments?.length ?? 0}. Context: ${lastSimulateResult.inferred_context_domain ?? '—'}.`)
    } else if (lastMode === 'assess' && lastAssessResult && !lastAssessResult.error) {
      lines.push(`Mode: Assess. Low-confidence items: ${lastAssessResult.low_confidence_count ?? 0}.`)
      if (lastAssessResult.items?.length) {
        const preview = lastAssessResult.items.slice(0, 40).map((i) => `${i.item_name ?? '?'} → ${i.suggested_child ?? '?'}`).join('; ')
        lines.push(`Items (item → suggested): ${preview}${(lastAssessResult.items?.length ?? 0) > 40 ? '…' : ''}`)
      }
    } else if (lastMode === 'recommend' && lastRecommendResult && !lastRecommendResult.error) {
      lines.push(`Mode: Recommend. Context: ${lastRecommendResult.inferred_context_domain ?? '—'}. Suggested folders: ${lastRecommendResult.suggested_child_folders?.length ?? 0}.`)
      const folderList = approvedFoldersForContext ?? lastRecommendResult.suggested_child_folders ?? []
      if (folderList.length > 0) lines.push(`Suggested parent folders: ${folderList.join(', ')}`)
      if (lastAnalyzeResult && !lastAnalyzeResult.error) {
        const tokens = (lastAnalyzeResult.repeated_tokens ?? []).slice(0, 15)
        if (tokens.length > 0) lines.push(`Repeated tokens: ${tokens.join(', ')}`)
        const ext = lastAnalyzeResult.extension_breakdown
        if (ext && Object.keys(ext).length > 0) {
          const extLine = Object.entries(ext)
            .slice(0, 10)
            .map(([e, n]) => `${e} (${n})`)
            .join(', ')
          lines.push(`File types: ${extLine}`)
        }
        if (lastAnalyzeResult.folder_count != null) lines.push(`Subfolders (count): ${lastAnalyzeResult.folder_count}`)
      }
    }
    return lines.join('\n')
  }

  const buildNextStepContextBlock = (): string => {
    const lines: string[] = []
    if (lastFolderPath) lines.push(`Folder: ${lastFolderPath}`)
    if (lastMode === 'analyze' && lastAnalyzeResult && !lastAnalyzeResult.error) {
      lines.push(`Mode: Analyze. Context: ${lastAnalyzeResult.inferred_context_domain ?? '—'}. Items: ${lastAnalyzeResult.item_count ?? 0}.`)
    } else if (lastMode === 'simulate' && lastSimulateResult && !lastSimulateResult.error) {
      lines.push(`Mode: Simulate. Assignments: ${lastSimulateResult.proposed_assignments?.length ?? 0}. Context: ${lastSimulateResult.inferred_context_domain ?? '—'}.`)
    } else if (lastMode === 'assess' && lastAssessResult && !lastAssessResult.error) {
      lines.push(`Mode: Assess. Low-confidence items: ${lastAssessResult.low_confidence_count ?? 0}.`)
    } else if (lastMode === 'recommend' && lastRecommendResult && !lastRecommendResult.error) {
      lines.push(`Mode: Recommend. Context: ${lastRecommendResult.inferred_context_domain ?? '—'}. Suggested folders: ${lastRecommendResult.suggested_child_folders?.length ?? 0}.`)
    } else if (lastMode === 'council' && lastCouncilResult) {
      lines.push(`Mode: Council. Synthesis (excerpt): ${lastCouncilResult.slice(0, 400)}${lastCouncilResult.length > 400 ? '…' : ''}.`)
    } else if (lastMode === 'web_research' && lastWebResearchResult && !lastWebResearchResult.error) {
      lines.push(`Mode: Web Research. Query: ${lastWebResearchResult.query ?? '—'}. Findings: ${(lastWebResearchResult.top_findings ?? []).slice(0, 2).join('; ')}.`)
    }
    return lines.join('\n')
  }

  const runCouncil = async (
    overrideQuestion?: string,
    options?: {
      preserveComposer?: boolean
      threadDisplayHint?: string
      councilContextThreadOverride?: DigressionBackgroundThreadRow[]
    },
  ) => {
    const invocationKind = councilInvocationNextRef.current
    councilInvocationNextRef.current = 'default'
    const q = (overrideQuestion ?? question)?.trim() || 'What should we consider?'
    const isFolderWorkflowEarly = lastMode === 'recommend' && !!lastFolderPath
    councilRunMapPayloadRef.current = null
    // Bounded node transform (suggest-only) previously ran before POST /run; Lane A direct VE runs on the server
    // first, so council/stream is always attempted here — no pre-council transform hijack.

    const cxMax = councilExpandedMode ? EXPANDED_MAX_SEATS : MAX_COUNCIL_SEATS
    let filledSlots = councilSeatSlots.slice(0, cxMax).filter((s) => s.actorId != null)
    if (filledSlots.length === 0) {
      filledSlots = [{ id: 'cs-0', actorId: 'zenaf' }]
    }
    const useBuiltinFullCouncil = invocationKind === 'full_multiseat'
    const includedAgentsForApi = filledSlots.map((s) => s.id)
    console.debug('[Zenaf council] runCouncil start', {
      questionLen: q.length,
      seatsFilled: filledSlots.length,
      useBuiltinFullCouncil,
    })
    setError(null)
    setWorkspaceTraceOutcomeBanner(null)
    setResult(null)
    setStreamingCouncilText('')
    setMirrorNotice(null)
    setStreamingCouncilRunLabel('Council')
    setCouncilSynthesisIntegrity(null)
    setCouncilIntegrityWarning(null)
    setCouncilSynthesisIntegrityEnvelope(null)
    setLoading(true)
    const isFolderWorkflow = isFolderWorkflowEarly
    setLastCouncilWasFolderWorkflow(isFolderWorkflow)
    const singleActor =
      filledSlots.length === 1 ? councilAgentList.find((a) => a.id === filledSlots[0]!.actorId) : null
    const singleSeatMandate =
      filledSlots.length === 1 ? mandatesBySeatId[filledSlots[0]!.id] ?? '' : ''
    const runLabel = isFolderWorkflow
      ? 'Folder review'
      : useBuiltinFullCouncil
        ? 'Council'
        : filledSlots.length === 1 && singleActor
          ? singleActor.name
          : 'Council'
    setStreamingCouncilRunLabel(runLabel)
    const streamAbort = new AbortController()
    let councilStreamAbortKind: 'idle' | 'max' | null = null
    let streamReader: ReadableStreamDefaultReader<Uint8Array> | null = null
    let idleIntervalId: ReturnType<typeof setInterval> | null = null
    streamAbort.signal.addEventListener('abort', () => {
      void streamReader?.cancel().catch(() => {})
    })
    const streamAbortTimer = window.setTimeout(() => {
      councilStreamAbortKind = 'max'
      streamAbort.abort()
    }, COUNCIL_STREAM_MAX_MS)
    let councilRunId: string | null = null
    let perfLog: ((stage: string, extra?: Record<string, unknown>) => void) | null = null
    try {
      const threadForCouncilContext = options?.councilContextThreadOverride ?? agentThread
      const workflowContext = useLastResultAsContext ? buildContextBlock(isFolderWorkflow ? approvedFolders : undefined) : ''
      const inCouncilDigression = Boolean(councilScopedDigression)
      const threadContext = inCouncilDigression ? '' : buildAgentThreadContext()
      const contextBlock = inCouncilDigression
        ? ''
        : [workflowContext, threadContext].filter(Boolean).join('\n\n')
      councilRunId =
        typeof crypto !== 'undefined' && 'randomUUID' in crypto
          ? crypto.randomUUID()
          : `council-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
      councilResonanceRunIdRef.current = councilRunId
      const timing: CouncilTransportTimings = { runStartedMs: performance.now() }
      councilTransportTimingRef.current = timing
      let perfCorrelationId = ''
      perfLog = (stage: string, extra?: Record<string, unknown>) => {
        const msSinceCouncilRunT0 = Math.round(performance.now() - timing.runStartedMs)
        console.info('[Zenaf perf]', { stage, msSinceCouncilRunT0, perfRunId: perfCorrelationId || null, ...extra })
      }
      perfLog?.('runCouncil_try_start', { questionLen: q.length })
      setCouncilStreamPhase('connecting')
      const threadDisplayLine =
        options?.threadDisplayHint ?? threadDisplayLineForCouncilQuestion(q)
      setAgentThread((prev) => {
        const stripped = prev.filter(
          (m) =>
            !(
              m.ephemeralRunId &&
              (m.threadItemKind === 'system_status' || m.threadItemKind === 'streaming_placeholder')
            ),
        )
        const userRow: AgentThreadMessage = {
          role: 'user',
          content: q,
          threadItemKind: 'user_message',
          ...(threadDisplayLine ? { councilThreadDisplayContent: threadDisplayLine } : {}),
        }
        return [
          ...stripped,
          userRow,
          {
            role: 'system',
            content: councilPhaseDetail('connecting'),
            threadItemKind: 'system_status',
            ephemeralRunId: councilRunId!,
          },
          {
            role: 'agent',
            content: '',
            agentLabel: runLabel,
            threadItemKind: 'streaming_placeholder',
            ephemeralRunId: councilRunId!,
          },
        ]
      })
      if (!options?.preserveComposer) {
        setQuestion('')
      }
      setAgentConversationScrollNonce((n) => n + 1)
      const snap = councilRuntimeRef.current
      const vf = councilVeFocusRef.current
      const entityBundle = councilVeEntityBundleRef.current
      const fallbackCore = veFocusCoreFromVeSelection(snap.ve_selection, entityBundle)
      const effectiveCore = vf?.core ?? fallbackCore
      const council_preflight: Record<string, unknown> = {
        active_surface: snap.mainView,
        workspace_topic_label: snap.currentTopic.label,
        workspace_topic_summary: snap.currentTopic.summary,
        workspace_mode_label: snap.currentTopic.modeLabel,
        home_strip_label: undefined,
        breadcrumb:
          [snap.currentTopic.label, snap.currentTopic.modeLabel].filter(Boolean).join(' · ') || undefined,
        folder_path: lastFolderPath || undefined,
      }
      if (effectiveCore) {
        council_preflight.ve_focus = {
          entity_type: effectiveCore.entity_type,
          entity_id: effectiveCore.entity_id,
          field_label: effectiveCore.field_label,
          field_key: effectiveCore.field_key,
          parent: effectiveCore.parent,
          lineage_labels: effectiveCore.lineage_labels,
        }
        if (vf?.graphs.ve) {
          council_preflight.ve_focus_graph = vf.graphs.ve
        } else {
          const graphSnap = veGraphSnapshotFromBundle(entityBundle)
          const slice = graphSnap ? resolveGraphSliceVE(effectiveCore, graphSnap) : null
          if (slice) council_preflight.ve_focus_graph = slice
        }
      }
      if (snap.ve_selection && Object.keys(snap.ve_selection).length > 0) {
        council_preflight.ve_selection = snap.ve_selection
      }
      const veSelectedPayload = veSelectedEntityPayloadFromSelection(snap.ve_selection, entityBundle)
      if (veSelectedPayload) {
        council_preflight.ve_selected_entity = veSelectedPayload
      }
      if (
        effectiveCore &&
        (snap.mainView === 'vision_execution' || snap.mainView === 'vision_map')
      ) {
        council_preflight.grounding_explicit = true
      }
      const ideaLabels = councilIdeaLabelsRef.current
      if (
        effectiveCore?.entity_type === 'idea' &&
        ideaLabels &&
        effectiveCore.entity_id === ideaLabels.entity_id
      ) {
        council_preflight.ve_focus_title = ideaLabels.ve_focus_title
        council_preflight.ve_focus_brief = ideaLabels.ve_focus_brief
        council_preflight.ve_focus_description = ideaLabels.ve_focus_description
        const st = ideaLabels.ve_focus_status?.trim()
        if (st) council_preflight.ve_focus_status = st
      }
      if (effectiveCore?.entity_type === 'task') {
        const graphSnap = veGraphSnapshotFromBundle(entityBundle)
        const slice =
          vf?.graphs?.ve ??
          (graphSnap ? resolveGraphSliceVE(effectiveCore, graphSnap) : null)
        const tid = (effectiveCore.entity_id || '').trim()
        const taskNode =
          slice && !slice.dataUnavailable && tid ? slice.nodes[tid] : undefined
        const raw =
          taskNode?.kind === 'task' && taskNode.data && typeof taskNode.data === 'object'
            ? (taskNode.data as Record<string, unknown>)
            : undefined
        const rowTitle = raw ? String(raw.title ?? '').trim() : ''
        const rowDescription = raw ? String(raw.description ?? '').trim() : ''
        const rowNotes = raw ? String(raw.notes ?? '').trim() : ''
        const rowCriteria = raw ? String(raw.completion_criteria ?? '').trim() : ''
        const sq = raw?.source_quotes
        const rowQuotes =
          typeof sq === 'string'
            ? sq.trim()
            : Array.isArray(sq)
              ? sq.map((x) => String(x ?? '').trim()).filter(Boolean).join('\n')
              : ''
        const lineageFallback =
          Array.isArray(effectiveCore.lineage_labels) && effectiveCore.lineage_labels.length > 0
            ? String(effectiveCore.lineage_labels[effectiveCore.lineage_labels.length - 1] ?? '').trim()
            : ''
        council_preflight.ve_focus_title = rowTitle || lineageFallback || '(task)'
        council_preflight.ve_focus_brief = rowDescription || 'No description provided.'
        const descParts: string[] = []
        if (rowNotes) descParts.push(`Notes:\n${rowNotes}`)
        if (rowQuotes) descParts.push(`Source quotes:\n${rowQuotes}`)
        if (rowCriteria) descParts.push(`Completion criteria:\n${rowCriteria}`)
        council_preflight.ve_focus_description = descParts.length > 0 ? descParts.join('\n\n') : '—'
      }
      const mapTriadForGuidance =
        snap.mainView === 'vision_map'
          ? mapDevelopmentalSnapshot
          : buildVeMapTriadSnapshotFromFocus(effectiveCore ?? null, entityBundle)
      let councilFlowReadings: ExecutionFlowReadingSummary[] = []
      const flowRef = veEntityRefFromMapTriad(mapTriadForGuidance ?? null)
      if (flowRef) {
        try {
          councilFlowReadings = await fetchExecutionFlowReadings(flowRef.entity_type, flowRef.entity_id, 12)
        } catch {
          councilFlowReadings = []
        }
      }
      const developmentalGuidance = buildDevelopmentalGuidanceContext({
        mapTriad: mapTriadForGuidance,
        recentTraces: getRecentAiActionTraces(),
        executionFlowReadings: councilFlowReadings,
      })
      if (developmentalGuidance && !councilScopedDigression) {
        council_preflight.developmental_guidance = developmentalGuidance
      }
      const mapInterp = mapTriadForGuidance && 'node_interpretation' in mapTriadForGuidance ? mapTriadForGuidance.node_interpretation : null
      if (mapInterp) {
        council_preflight.node_interpretation = mapInterp
      }

      if (councilScopedDigression) {
        const dig = councilScopedDigression
        const matchesVf =
          Boolean(effectiveCore) &&
          effectiveCore!.entity_type === dig.entityType &&
          (effectiveCore!.entity_id || '').trim() === dig.entityId.trim()
        if (!matchesVf) {
          council_preflight.ve_focus = {
            entity_type: dig.entityType,
            entity_id: dig.entityId,
            lineage_labels: [] as string[],
          }
          council_preflight.ve_focus_title = dig.label
          council_preflight.ve_focus_brief = '—'
          council_preflight.ve_focus_description =
            'Scoped sub-thread — open this record in Vision & Execution for the full snapshot.'
          delete council_preflight.ve_focus_graph
        }
        council_preflight.is_scoped_digression = true
        delete council_preflight.developmental_guidance
        delete council_preflight.node_interpretation
      }

      console.debug('[Zenaf council] council_preflight snapshot', {
        ve_focus_entity: effectiveCore?.entity_type,
        ve_focus_id: effectiveCore?.entity_id,
        ve_focus_title: council_preflight.ve_focus_title,
        ve_focus_brief_len: String(council_preflight.ve_focus_brief ?? '').length,
        ve_focus_description_len: String(council_preflight.ve_focus_description ?? '').length,
        use_last_result: useLastResultAsContext,
        context_block_len: contextBlock.length,
        thread_included: Boolean(threadContext),
        developmental_guidance: Boolean(developmentalGuidance),
      })
      // Transaction integrity: final SSE often omits `pending_integration` when unchanged, which previously cleared the
      // ref and dropped the echo on the next POST. Recover from the last assistant row that still shows a pending chip.
      if (!councilPendingIntegrationRef.current) {
        const recovered = findLastProposedPendingIntegrationInRows(threadForCouncilContext as AgentThreadScanRow[])
        if (recovered) councilPendingIntegrationRef.current = recovered
      }
      const body: {
        mode: string
        params: {
          question: string
          include_synthesis?: boolean
          included_agents?: string[]
          perspective_definitions?: Record<string, unknown>[]
          force_full_council?: boolean
          council_personality_mode?: string
        }
        context?: {
          folder_path?: string
          use_last_result?: boolean
          context_block?: string
          workflow_kind?: string
          council_preflight?: Record<string, unknown>
          conversation_subject?: ConversationSubject
          pending_integration?: PendingIntegrationPayload
          pending_ve_elicitation?: PendingVeElicitationPayload
          last_integration_commit?: LastIntegrationCommitPayload
          ve_direct_session?: { last_created_project_id?: string }
          is_scoped_digression?: boolean
          digression_background?: string
        }
        routing_context: RunRoutingContextPayload
      } = {
        mode: 'council',
        params: {
          question: q,
          ...(includeCouncilSynthesis ? { include_synthesis: true } : {}),
          council_personality_mode: councilPersonalityMode,
        },
        routing_context: buildWorkspaceRunRoutingContext(WORKSPACE_ACTION_INTENTS.council, true),
        context: {
          folder_path: lastFolderPath || undefined,
          use_last_result: useLastResultAsContext,
          ...(contextBlock ? { context_block: contextBlock } : {}),
          ...(isFolderWorkflow ? { workflow_kind: 'folder' as const } : {}),
          council_preflight,
          ...(councilConversationSubjectRef.current
            ? { conversation_subject: councilConversationSubjectRef.current }
            : {}),
          ...(councilPendingIntegrationRef.current
            ? { pending_integration: councilPendingIntegrationRef.current }
            : {}),
          ...(councilPendingVeElicitationRef.current
            ? { pending_ve_elicitation: councilPendingVeElicitationRef.current }
            : {}),
          ...(councilLastIntegrationCommitRef.current
            ? { last_integration_commit: councilLastIntegrationCommitRef.current }
            : {}),
          ...(councilVeDirectSessionRef.current?.last_created_project_id
            ? {
                ve_direct_session: {
                  last_created_project_id: councilVeDirectSessionRef.current.last_created_project_id,
                },
              }
            : {}),
          ...(councilScopedDigression
            ? {
                is_scoped_digression: true,
                digression_background: formatDigressionBackgroundBlock(threadForCouncilContext),
              }
            : {}),
        },
      }
      if (useBuiltinFullCouncil) {
        body.params.force_full_council = true
      } else {
        body.params.included_agents = includedAgentsForApi
        const focusInviteForceThinkingPartner = q.includes(CONVERSATIONAL_INVITE_MARKER)
        const definitions = filledSlots
          .map((slot, idx) => {
            const a = councilAgentList.find((x) => x.id === slot.actorId)
            if (!a) return null
            const dupTotal = filledSlots.filter((s) => s.actorId === slot.actorId).length
            const dupIndex = filledSlots.slice(0, idx + 1).filter((s) => s.actorId === slot.actorId).length
            const displayName = dupTotal > 1 ? `${a.name} (${dupIndex})` : a.name
            const def: Record<string, unknown> = {
              id: slot.id,
              perspective_agent_id: a.id,
              strand: a.strand,
              name: displayName,
              role: a.role,
              purpose: a.purpose,
              values: a.values,
              aversions: a.aversions,
              reasoningStyle: a.reasoningStyle,
              tone: a.tone,
              domain: a.domain,
              decisionRule: a.decisionRule,
              worldview: a.worldview,
              constraints: a.constraints,
              examplePhrases: a.examplePhrases,
              promptNotes: a.promptNotes,
            }
            if (a.context?.trim()) def.context = a.context.trim()
            const mandateId = focusInviteForceThinkingPartner
              ? 'thinking_partner'
              : (mandatesBySeatId[slot.id] ?? '')
            const mandate: Mandate | undefined = mandateId
              ? BUILT_IN_MANDATES.find((m) => m.id === mandateId)
              : undefined
            if (mandate) {
              def.mandate = {
                id: mandate.id,
                name: mandate.name,
                coreQuestion: mandate.core_question,
                optimizeFor: mandate.optimize_for,
                watchFor: mandate.watch_for,
                failureMode: mandate.failure_mode,
                outputStyle: mandate.output_style,
              }
            }
            const seatPv = councilSeatLlmById[slot.id]
            if (seatPv && seatPv !== 'auto') {
              def.llm_provider = seatPv
            }
            return def
          })
          .filter((d): d is Record<string, unknown> => d != null)
        if (definitions.length > 0) body.params.perspective_definitions = definitions
      }
      console.debug('[Zenaf council] POST /run/stream body', {
        mode: body.mode,
        hasRoutingContext: !!body.routing_context,
        hasIncludedAgents: !!(body.params.included_agents && body.params.included_agents.length > 0),
        hasPerspectiveDefinitions: !!body.params.perspective_definitions?.length,
      })
      perfLog?.('fetch_start')
      const res = await fetch(`${RUN_API_BASE}/run/stream`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: streamAbort.signal,
      })
      timing.fetchResolvedMs = performance.now()
      perfCorrelationId = res.headers.get('X-Zenaf-Perf-Run-Id')?.trim() || ''
      const streamModelUsed = res.headers.get('X-Zenaf-Model-Used')
      perfLog?.('fetch_resolved', {
        ok: res.ok,
        status: res.status,
        perfRunId: perfCorrelationId || null,
        providerUsed: res.headers.get('X-Zenaf-Provider-Used'),
        modelUsed: streamModelUsed,
        handshakeMs: Math.round(timing.fetchResolvedMs - timing.runStartedMs),
      })
      console.debug('[Zenaf council] response', { ok: res.ok, status: res.status })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        const msg = extractHttpDetailMessage(err) || res.statusText
        console.debug('[Zenaf council] HTTP error', msg)
        setCouncilStreamPhase('errored')
        if (councilRunId) {
          setAgentThread((prev) => prev.filter((m) => m.ephemeralRunId !== councilRunId))
        }
        setError(msg)
        if (import.meta.env.DEV && councilTransportTimingRef.current) {
          const t = councilTransportTimingRef.current
          console.debug('[Zenaf council] transport (failed at HTTP)', {
            handshakeMs: Math.round((t.fetchResolvedMs ?? 0) - t.runStartedMs),
          })
        }
        return
      }
      const reader = res.body?.getReader()
      if (!reader) {
        const msg = 'No response body stream (cannot read council output).'
        console.debug('[Zenaf council]', msg)
        setCouncilStreamPhase('errored')
        if (councilRunId) {
          setAgentThread((prev) => prev.filter((m) => m.ephemeralRunId !== councilRunId))
        }
        setError(msg)
        if (import.meta.env.DEV && councilTransportTimingRef.current) {
          const t = councilTransportTimingRef.current
          console.debug('[Zenaf council] transport (failed: no reader)', {
            handshakeMs: Math.round((t.fetchResolvedMs ?? 0) - t.runStartedMs),
          })
        }
        return
      }
      streamReader = reader
      setCouncilStreamPhase('connected_waiting_first_chunk')
      if (councilRunId) {
        setAgentThread((prev) =>
          prev.map((m) =>
            m.ephemeralRunId === councilRunId && m.role === 'system'
              ? { ...m, content: councilPhaseDetail('connected_waiting_first_chunk') }
              : m,
          ),
        )
      }
      let lastStreamActivityAt = Date.now()
      idleIntervalId = window.setInterval(() => {
        if (streamDone) {
          if (idleIntervalId != null) window.clearInterval(idleIntervalId)
          idleIntervalId = null
          return
        }
        if (Date.now() - lastStreamActivityAt >= COUNCIL_STREAM_IDLE_MS) {
          if (idleIntervalId != null) window.clearInterval(idleIntervalId)
          idleIntervalId = null
          councilStreamAbortKind = 'idle'
          streamAbort.abort()
        }
      }, 4000)
      const decoder = new TextDecoder()
      let fullText = ''
      let streamDone = false
      let sawFirstChunk = false
      let integrationCommitFromDone: IntegrationCommitPayload | null = null
      let pendingIntegrationFromDone: PendingIntegrationPayload | null = null
      let loggedFirstSsePayload = false
      let loggedFirstContentChunk = false
      const processLine = (line: string) => {
        if (!line.startsWith('data: ')) return
        lastStreamActivityAt = Date.now()
        try {
          const payload = JSON.parse(line.slice(6)) as CouncilStreamSsePayload
          if (payload.stream_open === true) {
            if (!loggedFirstSsePayload) {
              loggedFirstSsePayload = true
              perfLog?.('sse_first_event_stream_open', {
                sinceFetchResolvedMs: timing.fetchResolvedMs
                  ? Math.round(performance.now() - timing.fetchResolvedMs)
                  : null,
              })
            }
            setCouncilStreamPhase((prev) =>
              prev === 'connecting' ? 'connected_waiting_first_chunk' : prev,
            )
            if (councilRunId) {
              setAgentThread((prev) =>
                prev.map((m) =>
                  m.ephemeralRunId === councilRunId && m.role === 'system'
                    ? { ...m, content: councilPhaseDetail('connected_waiting_first_chunk') }
                    : m,
                ),
              )
            }
            return
          }
          if ('synthesis_integrity_state' in payload && payload.synthesis_integrity_state !== undefined) {
            setCouncilSynthesisIntegrity(payload.synthesis_integrity_state ?? null)
          }
          if ('integrity_warning' in payload) {
            setCouncilIntegrityWarning(payload.integrity_warning ?? null)
          }
          const synEnv = ingestSynthesisEnvelopeFromPayload(payload)
          if (synEnv) setCouncilSynthesisIntegrityEnvelope(synEnv)
          if (payload.error) {
            console.debug('[Zenaf council] stream payload error', payload.error)
            setCouncilStreamPhase('errored')
            if (councilRunId) {
              setAgentThread((prev) => prev.filter((m) => m.ephemeralRunId !== councilRunId))
            }
            setError(payload.error)
            streamDone = true
            return
          }
          if (payload.done) {
            perfLog?.('sse_payload_done', {
              fullTextLen: fullText.length,
              doneChunkLen: payload.chunk ? String(payload.chunk).length : 0,
            })
            setCouncilStreamPhase('finalizing')
            if (councilRunId) {
              setAgentThread((prev) =>
                prev.map((m) =>
                  m.ephemeralRunId === councilRunId && m.role === 'system'
                    ? { ...m, content: councilPhaseDetail('finalizing') }
                    : m,
                ),
              )
            }
            // Final SSE may repeat the full document; never replace accumulated seat text with a shorter chunk.
            if (payload.chunk) {
              const c = payload.chunk
              if (!fullText.trim() || c.length > fullText.length) fullText = c
            }
            if (
              payload.conversation_subject != null &&
              typeof payload.conversation_subject === 'object' &&
              !Array.isArray(payload.conversation_subject)
            ) {
              councilConversationSubjectRef.current = payload.conversation_subject as ConversationSubject
            }
            if (
              payload.integration_commit != null &&
              typeof payload.integration_commit === 'object' &&
              !Array.isArray(payload.integration_commit)
            ) {
              integrationCommitFromDone = payload.integration_commit as IntegrationCommitPayload
            } else {
              integrationCommitFromDone = null
            }
            // Mirror mode: surface the fallback notice when some seats had no
            // published mirror content (machine-readable strands + human text).
            if (typeof payload.mirror_notice === 'string' && payload.mirror_notice.trim()) {
              setMirrorNotice(payload.mirror_notice)
            } else {
              setMirrorNotice(null)
            }
            const committedThisStream =
              integrationCommitFromDone?.status === 'committed'
            if (committedThisStream) {
              councilPendingIntegrationRef.current = null
              setCouncilVeServerWriteNonce((n) => n + 1)
            } else if ('pending_integration' in payload) {
              if (
                payload.pending_integration != null &&
                typeof payload.pending_integration === 'object' &&
                !Array.isArray(payload.pending_integration)
              ) {
                councilPendingIntegrationRef.current = payload.pending_integration as PendingIntegrationPayload
              } else {
                councilPendingIntegrationRef.current = null
              }
            }
            if ('pending_ve_elicitation' in payload) {
              if (
                payload.pending_ve_elicitation != null &&
                typeof payload.pending_ve_elicitation === 'object' &&
                !Array.isArray(payload.pending_ve_elicitation)
              ) {
                councilPendingVeElicitationRef.current =
                  payload.pending_ve_elicitation as PendingVeElicitationPayload
              } else {
                councilPendingVeElicitationRef.current = null
              }
            }
            if (
              payload.last_integration_commit != null &&
              typeof payload.last_integration_commit === 'object' &&
              !Array.isArray(payload.last_integration_commit)
            ) {
              councilLastIntegrationCommitRef.current = payload.last_integration_commit as LastIntegrationCommitPayload
            }
            if (
              payload.direct_ve_action != null &&
              typeof payload.direct_ve_action === 'object' &&
              !Array.isArray(payload.direct_ve_action)
            ) {
              const dva = payload.direct_ve_action
              if ('pending_ve_elicitation' in dva) {
                if (
                  dva.pending_ve_elicitation != null &&
                  typeof dva.pending_ve_elicitation === 'object' &&
                  !Array.isArray(dva.pending_ve_elicitation)
                ) {
                  councilPendingVeElicitationRef.current =
                    dva.pending_ve_elicitation as PendingVeElicitationPayload
                } else {
                  councilPendingVeElicitationRef.current = null
                }
              }
              if (dva.status === 'handled') {
                setCouncilVeServerWriteNonce((n) => n + 1)
                const ents = dva.created_entities
                if (Array.isArray(ents)) {
                  const proj = ents.find(
                    (e) => e && e.entity_type === 'project' && String(e.entity_id ?? '').trim(),
                  )
                  if (proj?.entity_id) {
                    councilVeDirectSessionRef.current = {
                      last_created_project_id: String(proj.entity_id).trim(),
                    }
                  }
                }
              }
            }
            if (
              !integrationCommitFromDone &&
              payload.pending_integration != null &&
              typeof payload.pending_integration === 'object' &&
              !Array.isArray(payload.pending_integration)
            ) {
              pendingIntegrationFromDone = payload.pending_integration as PendingIntegrationPayload
            } else {
              pendingIntegrationFromDone = null
            }
            if (
              typeof payload.digression_summary === 'string' &&
              payload.digression_summary.trim()
            ) {
              const note = payload.digression_summary.trim()
              const foldStart = councilScopeThreadStartIndexRef.current
              const foldLabel = councilScopedDigressionRef.current?.label ?? 'Focused thread'
              setCouncilScopedDigression(null)
              setCouncilScopeThreadStartIndex(null)
              setAgentThread((prev) => {
                let base = prev
                if (foldStart != null && foldStart < base.length) {
                  const nestId = newScopedThreadNestId()
                  const children = base.slice(foldStart).map((row) => ({ ...row }))
                  base = [
                    ...base.slice(0, foldStart),
                    {
                      role: 'system' as const,
                      content: '',
                      threadItemKind: 'scoped_thread_nest' as const,
                      nestedScopedThread: { id: nestId, label: foldLabel, children },
                    },
                  ]
                }
                return [
                  ...base,
                  {
                    role: 'system',
                    content: `System note: ${note}\n\nResume the main discussion when you are ready.`,
                    threadItemKind: 'system_status',
                  },
                ]
              })
            }
            setStreamingCouncilText(fullText)
            streamDone = true
            return
          }
          if (payload.chunk) {
            if (!loggedFirstContentChunk && String(payload.chunk).length > 0) {
              loggedFirstContentChunk = true
              perfLog?.('sse_first_content_chunk', {
                chunkLen: String(payload.chunk).length,
                sinceFetchResolvedMs: timing.fetchResolvedMs
                  ? Math.round(performance.now() - timing.fetchResolvedMs)
                  : null,
              })
            }
            if (!sawFirstChunk) {
              sawFirstChunk = true
              if (councilTransportTimingRef.current) {
                councilTransportTimingRef.current.firstChunkMs = performance.now()
              }
              setCouncilStreamPhase('streaming')
              if (councilRunId) {
                setAgentThread((prev) =>
                  prev.filter(
                    (m) =>
                      !(
                        m.ephemeralRunId === councilRunId &&
                        (m.role === 'system' || m.threadItemKind === 'streaming_placeholder')
                      ),
                  ),
                )
              }
            }
            fullText += payload.chunk
            setStreamingCouncilText(fullText)
          }
          // Thinking-partner stream: first event often carries `pending_integration` in meta; final `done` may omit it.
          if (
            !payload.done &&
            'pending_integration' in payload &&
            payload.pending_integration != null &&
            typeof payload.pending_integration === 'object' &&
            !Array.isArray(payload.pending_integration)
          ) {
            councilPendingIntegrationRef.current = payload.pending_integration as PendingIntegrationPayload
          }
        } catch (_) {}
      }
      if (reader) {
        let buffer = ''
        while (!streamDone) {
          const { done, value } = await reader.read()
          if (value?.byteLength) lastStreamActivityAt = Date.now()
          buffer += decoder.decode(value ?? new Uint8Array(0), { stream: !done })
          const lines = buffer.split('\n')
          buffer = lines.pop() ?? ''
          for (const line of lines) processLine(line)
          if (done) {
            if (buffer.trim().startsWith('data: ')) processLine(buffer.trim())
            break
          }
        }
      }
      perfLog?.('sse_reader_loop_exit', { streamDone, fullTextLen: fullText.length })
      if (councilTransportTimingRef.current) {
        councilTransportTimingRef.current.streamEndedMs = performance.now()
      }
      const councilText = fullText || ''
      try {
        const integrityReview = buildCouncilIntegrityReviewSample({
          includeSynthesis: includeCouncilSynthesis,
          synthesisIntegrityState: councilSynthesisIntegrity,
          integrityWarning: councilIntegrityWarning,
          envelope: councilSynthesisIntegrityEnvelope,
          fullCouncilOutput: councilText,
        })
        const tr = emitWorkspaceTraceFromText({
          action_intent: WORKSPACE_ACTION_INTENTS.council,
          folder_path: lastFolderPath || null,
          input_snapshot: buildWorkspaceCouncilStreamSnapshot({
            question: q,
            included_agent_ids: filledSlots.map((s) => s.actorId).filter(Boolean) as string[],
            folder_workflow: isFolderWorkflow,
            folder_path: lastFolderPath,
          }),
          output_text: councilText,
          resolved_model_used: streamModelUsed,
          council_integrity_review: integrityReview,
        })
        workspaceOutcomeTargetRef.current = { trace: tr, action_intent: WORKSPACE_ACTION_INTENTS.council }
      } catch {
        /* ignore trace errors */
      }
      setResult(councilText)
      setStreamingCouncilText('')
      setLastMode('council')
      setLastCouncilResult(councilText)
      setLastCouncilPresentationKind(
        isFolderWorkflow
          ? 'folder'
          : !useBuiltinFullCouncil &&
              filledSlots.length === 1 &&
              (singleSeatMandate === 'thinking_partner' ||
                (!singleSeatMandate &&
                  (singleActor?.id === 'zenaf' || singleActor?.id === 'thinking_partner')))
            ? 'thinking'
            : 'multiseat',
      )
      setCurrentFocusMode('council')
      setCurrentFocusHasResult(true)
      if (lastFolderPath) setCurrentFocusPath(lastFolderPath)
      // If the final `done` payload omits `pending_integration`, `pendingIntegrationFromDone` stays null but
      // `councilPendingIntegrationRef` may still hold the proposed write (key absent → ref not cleared).
      // Attach that ref to the row so the next POST echoes `context.pending_integration` and deterministic commit runs.
      let pendingAttach: PendingIntegrationPayload | undefined
      if (!integrationCommitFromDone) {
        if (
          pendingIntegrationFromDone &&
          typeof pendingIntegrationFromDone === 'object' &&
          !Array.isArray(pendingIntegrationFromDone)
        ) {
          pendingAttach = pendingIntegrationFromDone
        } else {
          const r = councilPendingIntegrationRef.current
          if (
            r &&
            typeof r === 'object' &&
            !Array.isArray(r) &&
            r.integration_state === 'proposed'
          ) {
            pendingAttach = r
          }
        }
      }
      if (pendingAttach) {
        councilPendingIntegrationRef.current = pendingAttach
      }
      setAgentThread((t) => {
        const cleaned = councilRunId ? t.filter((m) => m.ephemeralRunId !== councilRunId) : t
        const withoutStalePending =
          integrationCommitFromDone != null
            ? cleaned.map((m) =>
                m.role === 'agent' && m.pendingIntegration
                  ? { ...m, pendingIntegration: undefined }
                  : m,
              )
            : cleaned
        return [
          ...withoutStalePending,
          {
            role: 'agent',
            content: councilText,
            agentLabel: runLabel,
            threadItemKind: 'assistant_message',
            resonanceResponseId: councilRunId ?? undefined,
            ...(integrationCommitFromDone ? { integrationCommit: integrationCommitFromDone } : {}),
            ...(pendingAttach ? { pendingIntegration: pendingAttach } : {}),
          },
        ]
      })
      setAgentConversationScrollNonce((n) => n + 1)
      setCouncilStreamPhase('completed')
      if (import.meta.env.DEV && councilTransportTimingRef.current) {
        const t = councilTransportTimingRef.current
        const handshakeMs = Math.round((t.fetchResolvedMs ?? t.runStartedMs) - t.runStartedMs)
        const firstTokenMs =
          t.fetchResolvedMs != null && t.firstChunkMs != null
            ? Math.round(t.firstChunkMs - t.fetchResolvedMs)
            : null
        const totalMs = t.streamEndedMs != null ? Math.round(t.streamEndedMs - t.runStartedMs) : null
        console.debug('[Zenaf council] transport timings (success)', {
          handshakeMs,
          firstTokenMs,
          totalMs,
          outLen: councilText.length,
        })
      }
      perfLog?.('runCouncil_success', {
        outLen: councilText.length,
        handshakeMs:
          councilTransportTimingRef.current?.fetchResolvedMs != null
            ? Math.round(
                councilTransportTimingRef.current.fetchResolvedMs! -
                  councilTransportTimingRef.current.runStartedMs,
              )
            : null,
        firstTokenMs:
          councilTransportTimingRef.current?.fetchResolvedMs != null &&
          councilTransportTimingRef.current?.firstChunkMs != null
            ? Math.round(
                councilTransportTimingRef.current.firstChunkMs! -
                  councilTransportTimingRef.current.fetchResolvedMs!,
              )
            : null,
        totalMs:
          councilTransportTimingRef.current?.streamEndedMs != null
            ? Math.round(
                councilTransportTimingRef.current.streamEndedMs! -
                  councilTransportTimingRef.current.runStartedMs,
              )
            : null,
      })
      console.debug('[Zenaf council] runCouncil done', { outLen: councilText.length })
    } catch (e) {
      const aborted =
        (typeof DOMException !== 'undefined' && e instanceof DOMException && e.name === 'AbortError') ||
        (e instanceof Error && e.name === 'AbortError')
      const msg = aborted
        ? councilStreamAbortKind === 'idle'
          ? `Council stalled: no data for ${Math.round(COUNCIL_STREAM_IDLE_MS / 60000)} minutes (stream may be hung). Check that /run/stream and your LLM provider are responding, then try again.`
          : `Council run timed out or was interrupted (no response after ${Math.round(COUNCIL_STREAM_MAX_MS / 60000)} min). Try again with fewer seats or a shorter question.`
        : e instanceof Error
          ? e.message
          : 'Request failed'
      console.debug('[Zenaf council] runCouncil catch', msg)
      const tRef = councilTransportTimingRef.current
      const t0 = tRef?.runStartedMs ?? performance.now()
      ;(perfLog ?? ((stage, extra) => console.info('[Zenaf perf]', { stage, ...extra })))('runCouncil_catch', {
        aborted,
        message: msg.slice(0, 200),
        msSinceCouncilRunT0: Math.round(performance.now() - t0),
        hadFetchResolved: tRef?.fetchResolvedMs != null,
        hadFirstChunk: tRef?.firstChunkMs != null,
      })
      setCouncilStreamPhase(aborted ? 'aborted' : 'errored')
      if (councilRunId) {
        setAgentThread((prev) => prev.filter((m) => m.ephemeralRunId !== councilRunId))
      }
      setError(msg)
      setStreamingCouncilText('')
      if (import.meta.env.DEV && councilTransportTimingRef.current) {
        const t = councilTransportTimingRef.current
        const handshakeMs =
          t.fetchResolvedMs != null ? Math.round(t.fetchResolvedMs - t.runStartedMs) : null
        const firstTokenMs =
          t.fetchResolvedMs != null && t.firstChunkMs != null
            ? Math.round(t.firstChunkMs - t.fetchResolvedMs)
            : null
        const totalMs = t.streamEndedMs != null ? Math.round(t.streamEndedMs - t.runStartedMs) : null
        console.debug('[Zenaf council] transport timings (terminal error)', {
          handshakeMs,
          firstTokenMs,
          totalMs,
          aborted,
        })
      }
    } finally {
      window.clearTimeout(streamAbortTimer)
      if (idleIntervalId != null) window.clearInterval(idleIntervalId)
      void streamReader?.cancel().catch(() => {})
      streamReader = null
      setLoading(false)
    }
  }

  runCouncilRef.current = runCouncil

  /** Folder workflow only: call folder advisor directly. Does not update activeMode, question, lastCouncilResult, or agentThread. */
  const runFolderAdvisor = async () => {
    const q =
      approvedFolders.length > 0
        ? `From this list of candidate parent folders — ${approvedFolders.join(', ')} — which would you keep or prioritize for this folder's contents? One short reason per suggestion.`
        : 'Which folder structure fits this content best? One short reason per suggestion.'
    setError(null)
    setWorkspaceTraceOutcomeBanner(null)
    setFolderAdvisorResult(null)
    setFolderAdvisorStreaming('')
    setFolderAdvisorLoading(true)
    try {
      const workflowContext = buildContextBlock(approvedFolders)
      const contextBlock = workflowContext || (lastFolderPath ? `Folder: ${lastFolderPath}` : '')
      const body = {
        mode: 'council',
        params: { question: q },
        context: {
          folder_path: lastFolderPath || undefined,
          context_block: contextBlock,
          workflow_kind: 'folder' as const,
          ambiguity_signals:
            lastAnalyzeResult || lastAssessResult || lastRecommendResult
              ? {
                  repeated_tokens: lastAnalyzeResult?.repeated_tokens ?? [],
                  low_confidence_count: lastAssessResult?.low_confidence_count ?? 0,
                  inferred_context_domain:
                    (lastRecommendResult?.inferred_context_domain ?? lastAnalyzeResult?.inferred_context_domain ?? '').trim(),
                }
              : undefined,
        },
        routing_context: buildWorkspaceRunRoutingContext(WORKSPACE_ACTION_INTENTS.folder_advisor, true),
      }
      const res = await fetch(`${RUN_API_BASE}/run/stream`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const folderAdvisorModelUsed = res.headers.get('X-Zenaf-Model-Used')
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        setError(extractHttpDetailMessage(err) || res.statusText)
        setFolderAdvisorLoading(false)
        return
      }
      const reader = res.body?.getReader()
      const decoder = new TextDecoder()
      let fullText = ''
      let streamDone = false
      const processLine = (line: string) => {
        if (!line.startsWith('data: ')) return
        try {
          const payload = JSON.parse(line.slice(6)) as { chunk?: string; done?: boolean; error?: string }
          if (payload.error) {
            setError(payload.error)
            streamDone = true
            return
          }
          if (payload.done) {
            if (payload.chunk) fullText = payload.chunk
            setFolderAdvisorResult(fullText)
            setFolderAdvisorStreaming('')
            streamDone = true
            return
          }
          if (payload.chunk) {
            fullText += payload.chunk
            setFolderAdvisorStreaming(fullText)
          }
        } catch (_) {}
      }
      if (reader) {
        let buffer = ''
        while (!streamDone) {
          const { done, value } = await reader.read()
          buffer += decoder.decode(value ?? new Uint8Array(0), { stream: !done })
          const lines = buffer.split('\n')
          buffer = lines.pop() ?? ''
          for (const line of lines) processLine(line)
          if (done) {
            if (buffer.trim().startsWith('data: ')) processLine(buffer.trim())
            break
          }
        }
      }
      const final = fullText || ''
      try {
        const tr = emitWorkspaceTraceFromText({
          action_intent: WORKSPACE_ACTION_INTENTS.folder_advisor,
          folder_path: lastFolderPath || null,
          input_snapshot: buildWorkspaceFolderAdvisorSnapshot({ question: q, folder_path: lastFolderPath }),
          output_text: final,
          resolved_model_used: folderAdvisorModelUsed,
        })
        workspaceOutcomeTargetRef.current = { trace: tr, action_intent: WORKSPACE_ACTION_INTENTS.folder_advisor }
      } catch {
        /* ignore trace errors */
      }
      setFolderAdvisorResult(final)
      setFolderAdvisorStreaming('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Request failed')
      setFolderAdvisorResult(null)
      setFolderAdvisorStreaming('')
    } finally {
      setFolderAdvisorLoading(false)
    }
  }

  const runWebResearch = async (overrideQuery?: string) => {
    const q = (overrideQuery ?? query)?.trim() || ''
    if (overrideQuery) setQuery(overrideQuery)
    setError(null)
    setWorkspaceTraceOutcomeBanner(null)
    setResult(null)
    setLoading(true)
    try {
      const res = await fetch(`${RUN_API_BASE}/run`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mode: 'web_research',
          params: { query: q },
          routing_context: buildWorkspaceRunRoutingContext(WORKSPACE_ACTION_INTENTS.web_research, false),
        }),
      })
      const data: RunResponse & { detail?: string } = await res.json()
      if (!res.ok) {
        setError(data.error || data.detail || res.statusText || `HTTP ${res.status}`)
        return
      }
      if (data.execution_blocked) {
        setError(workspaceExecutionBlockedMessage(data))
        return
      }
      if (!data.ok || data.result == null) {
        setError(data.error || 'No result')
        return
      }
      const raw = data.result as WebResearchResult
      try {
        const tr = emitWorkspaceTraceFromResult({
          action_intent: WORKSPACE_ACTION_INTENTS.web_research,
          folder_path: lastFolderPath || folderPath || null,
          input_snapshot: buildWorkspaceWebResearchSnapshot(q),
          result: raw,
          resolved_model_used: data.model_used ?? undefined,
        })
        workspaceOutcomeTargetRef.current = { trace: tr, action_intent: WORKSPACE_ACTION_INTENTS.web_research }
      } catch {
        /* ignore trace errors */
      }
      const summary = raw.top_findings?.length ? raw.top_findings.join('\n• ') : (raw.query ?? '')
      setResult(JSON.stringify(data.result, null, 2))
      setLastMode('web_research')
      setLastWebResearchResult(raw)
      setCurrentFocusMode('web_research')
      setCurrentFocusHasResult(true)
      setAgentThread((t) => [...t, { role: 'user', content: `Web search: ${q}` }, { role: 'agent', content: summary, agentLabel: 'Web' }])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Request failed')
    } finally {
      setLoading(false)
    }
  }

  const runNextStep = async () => {
    setError(null)
    setWorkspaceTraceOutcomeBanner(null)
    setResult(null)
    setLoading(true)
    const goal = nextStepQuestion?.trim() || ''
    try {
      const workflowContext = buildNextStepContextBlock()
      const threadContext = buildAgentThreadContext()
      const contextBlock = [workflowContext, threadContext].filter(Boolean).join('\n\n')
      const path = folderPath?.trim() || lastFolderPath || ''
      const body: {
        mode: string
        params: { question?: string }
        context?: { folder_path?: string; use_last_result?: boolean; context_block?: string }
      } = {
        mode: 'next_step',
        params: { question: goal || undefined },
      }
      if (path || contextBlock) {
        body.context = {
          folder_path: path || undefined,
          use_last_result: !!contextBlock,
        }
        if (contextBlock) body.context!.context_block = contextBlock
      }
      const res = await fetch(`${RUN_API_BASE}/run`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...body,
          routing_context: buildWorkspaceRunRoutingContext(WORKSPACE_ACTION_INTENTS.next_step, false),
        }),
      })
      const data: RunResponse & { detail?: string } = await res.json()
      if (!res.ok) {
        setError(data.error || data.detail || res.statusText || `HTTP ${res.status}`)
        return
      }
      if (data.execution_blocked) {
        setError(workspaceExecutionBlockedMessage(data))
        return
      }
      if (!data.ok || data.result == null) {
        setError(data.error || 'No result')
        return
      }
      const raw = data.result as NextStepResult
      try {
        const tr = emitWorkspaceTraceFromResult({
          action_intent: WORKSPACE_ACTION_INTENTS.next_step,
          folder_path: path || null,
          input_snapshot: buildWorkspaceNextStepSnapshot({
            folder_path: path,
            has_context_block: !!contextBlock,
            question: goal,
          }),
          result: raw,
          resolved_model_used: data.model_used ?? undefined,
        })
        workspaceOutcomeTargetRef.current = {
          trace: tr,
          action_intent: WORKSPACE_ACTION_INTENTS.next_step,
          learning_record_id:
            typeof data.learning_record_id === 'string' && data.learning_record_id.trim()
              ? data.learning_record_id.trim()
              : null,
        }
      } catch {
        /* ignore trace errors */
      }
      const reply = [raw.recommendation, raw.rationale].filter(Boolean).join('\n\n')
      setResult(JSON.stringify(data.result, null, 2))
      setLastMode('next_step')
      setLastNextStepResult(raw)
      setCurrentFocusMode('next_step')
      setCurrentFocusHasResult(true)
      setAgentThread((t) => [...t, { role: 'user', content: goal || 'Suggest next step' }, { role: 'agent', content: reply, agentLabel: 'Next Step' }])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Request failed')
    } finally {
      setLoading(false)
    }
  }

  const goToModeWithPath = (mode: ModeId, path: string) => {
    setActiveMode(mode)
    setFolderPath(path)
  }
  const useResultAsFocus = () => {
    const w = workspaceOutcomeTargetRef.current
    if (w) {
      try {
        recordWorkspaceTraceUserOutcome(w.trace, 'applied')
      } catch {
        /* ignore */
      }
      postWorkspaceLearningFromRef(w, 'applied')
    }
    setCurrentFocusPath(lastFolderPath)
    setCurrentFocusMode(lastMode)
    setCurrentFocusHasResult(true)
    setFolderPath(lastFolderPath)
  }
  const useWebResearchAsFocus = () => {
    setCurrentFocusMode('web_research')
    setCurrentFocusHasResult(true)
  }
  const goToCouncilWithQuery = (q: string) => {
    setActiveMode('council')
    setQuestion(q || lastWebResearchResult?.query || '')
  }
  const goToNextStep = () => {
    setActiveMode('next_step')
    setFolderPath(lastFolderPath || folderPath)
  }

  const handleRun = () => {
    const path = folderPath?.trim() || ''
    if (activeMode === 'analyze') {
      runMode('analyze', path)
    } else if (activeMode === 'simulate') {
      runMode('simulate', path)
    } else if (activeMode === 'assess') {
      runMode('assess', path)
    } else if (activeMode === 'recommend') {
      runMode('recommend', path)
    } else if (activeMode === 'council') {
      void runCouncil(undefined)
    } else if (activeMode === 'web_research') {
      runWebResearch()
    } else if (activeMode === 'next_step') {
      runNextStep()
    } else if (activeMode === 'ordering_queue') {
      fetchIntakeQueue()
    } else if (activeMode === 'email_intake' || activeMode === 'fax_intake') {
      setResult('Use the Clinic Intake section below to paste and submit email or fax.')
    } else {
      setResult(`"${activeMode}" is not wired.`)
    }
  }

  const isAnalyze = activeMode === 'analyze'
  const isSimulate = activeMode === 'simulate'
  const isAssess = activeMode === 'assess'
  const isRecommend = activeMode === 'recommend'
  const isCouncil = activeMode === 'council'
  const isWebResearch = activeMode === 'web_research'
  const isNextStep = activeMode === 'next_step'
  const showFolderInput = ['analyze', 'recommend', 'assess', 'simulate', 'next_step'].includes(activeMode)
  const showQuestionInput = activeMode === 'council'
  const showQueryInput = activeMode === 'web_research'
  const showNextStepQuestionInput = activeMode === 'next_step'
  const canRunNextStep =
    !!nextStepQuestion?.trim() || !!buildNextStepContextBlock() || !!folderPath?.trim() || !!lastFolderPath

  const [councilSeatLlmById, setCouncilSeatLlmById] = useState<Record<string, string>>({})
  const [llmProviderRows, setLlmProviderRows] = useState<ProviderStatusRow[]>([])
  // Perspective agents: signed-in users sync from server (`/vision-execution/council-workspace/perspectives`); anonymous uses localStorage only.
  const [perspectiveAgents, setPerspectiveAgents] = useState<PerspectiveAgent[]>([])
  const [perspectivesRemoteReady, setPerspectivesRemoteReady] = useState(false)
  const fetchGmailOAuthStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/intake/oauth/google/status`)
      const data = await res.json().catch(() => ({}))
      setGmailOAuthEmail(data.connected && data.email ? data.email : null)
    } catch {
      setGmailOAuthEmail(null)
    }
  }, [])

  const fetchGmailOAuthConfig = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/intake/oauth/google/config`)
      const data = await res.json().catch(() => ({}))
      setGmailOAuthConfigured(!!data.configured)
      setGmailOAuthConfigPath(data.config_path || null)
    } catch {
      setGmailOAuthConfigured(false)
    }
  }, [])

  const saveGoogleOAuthConfig = async () => {
    setGoogleOAuthConfigSaved(null)
    if (!googleClientId.trim() || !googleClientSecret.trim()) {
      setGoogleOAuthConfigSaved('Client ID and Client secret are required')
      return
    }
    try {
      const res = await fetch(`${API_BASE}/intake/oauth/google/config`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ client_id: googleClientId.trim(), client_secret: googleClientSecret.trim() }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setGoogleOAuthConfigSaved(data.detail || res.statusText || 'Save failed')
        return
      }
      setGoogleOAuthConfigSaved('Saved. You can now click Connect Gmail.')
      setGmailOAuthConfigured(true)
      setGoogleClientSecret('')
    } catch (e) {
      setGoogleOAuthConfigSaved(e instanceof Error ? e.message : 'Save failed')
    }
  }

  useEffect(() => {
    fetchIntakeEmailConfig()
    fetchGmailOAuthStatus()
    fetchGmailOAuthConfig()
  }, [fetchGmailOAuthStatus, fetchGmailOAuthConfig])

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const oauth = params.get('gmail_oauth')
    if (oauth === 'success' || oauth === 'error') {
      if (oauth === 'success') {
        fetchGmailOAuthStatus()
        setGmailOAuthError(null)
      } else {
        const msg = params.get('message')
        if (msg) {
          try {
            const decoded = decodeURIComponent(msg)
            const e = decoded.startsWith('e=') ? decoded.slice(2) : decoded
            setGmailOAuthError(e.replace(/^e=/, ''))
          } catch {
            setGmailOAuthError(msg)
          }
        } else {
          setGmailOAuthError('OAuth failed')
        }
      }
      window.history.replaceState({}, '', window.location.pathname + window.location.hash)
    }
  }, [fetchGmailOAuthStatus])

  useEffect(() => {
    if (!currentUser) {
      setPerspectivesRemoteReady(false)
      try {
        const raw = localStorage.getItem(PERSPECTIVE_STORAGE_KEY)
        if (raw) {
          const parsed = JSON.parse(raw) as unknown
          if (Array.isArray(parsed) && parsed.length > 0) {
            const normalized = normalizeStoredPerspectiveAgents(parsed as PerspectiveAgent[])
            setPerspectiveAgents(normalized)
            try {
              localStorage.setItem(PERSPECTIVE_STORAGE_KEY, JSON.stringify(normalized))
            } catch {
              /* ignore */
            }
            setPerspectivesRemoteReady(true)
            return
          }
        }
        setPerspectiveAgents(BUILT_IN_PERSPECTIVES)
      } catch {
        setPerspectiveAgents(BUILT_IN_PERSPECTIVES)
      }
      setPerspectivesRemoteReady(true)
      return
    }

    let cancelled = false
    setPerspectivesRemoteReady(false)
    ;(async () => {
      try {
        const r = await veApiGet<CouncilWorkspacePerspectivesResponse>('/council-workspace/perspectives')
        if (cancelled) return
        if (r.row_exists) {
          const list = Array.isArray(r.perspectives) ? r.perspectives : []
          setPerspectiveAgents(normalizeStoredPerspectiveAgents(list as PerspectiveAgent[]))
          setPerspectivesRemoteReady(true)
          return
        }
        let next: PerspectiveAgent[]
        try {
          const ls = localStorage.getItem(PERSPECTIVE_STORAGE_KEY)
          if (ls) {
            const parsed = JSON.parse(ls) as unknown
            if (Array.isArray(parsed) && parsed.length > 0) {
              next = normalizeStoredPerspectiveAgents(parsed as PerspectiveAgent[])
            } else {
              next = BUILT_IN_PERSPECTIVES
            }
          } else {
            next = BUILT_IN_PERSPECTIVES
          }
        } catch {
          next = BUILT_IN_PERSPECTIVES
        }
        setPerspectiveAgents(next)
        await veApiPut('/council-workspace/perspectives', { perspectives: next })
        if (!cancelled) setPerspectivesRemoteReady(true)
      } catch {
        if (cancelled) return
        try {
          const raw = localStorage.getItem(PERSPECTIVE_STORAGE_KEY)
          if (raw) {
            const parsed = JSON.parse(raw) as unknown
            if (Array.isArray(parsed) && parsed.length > 0) {
              setPerspectiveAgents(normalizeStoredPerspectiveAgents(parsed as PerspectiveAgent[]))
            } else {
              setPerspectiveAgents(BUILT_IN_PERSPECTIVES)
            }
          } else {
            setPerspectiveAgents(BUILT_IN_PERSPECTIVES)
          }
        } catch {
          setPerspectiveAgents(BUILT_IN_PERSPECTIVES)
        }
        setPerspectivesRemoteReady(true)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [currentUser])

  useEffect(() => {
    if (!currentUser) {
      setLlmProviderRows([])
      setCouncilSeatLlmById({})
      return
    }
    let cancelled = false
    ;(async () => {
      try {
        const d = await fetchLLMSettings()
        if (cancelled) return
        setLlmProviderRows(d.providers ?? [])
        setCouncilSeatLlmById(d.council_seat_providers ?? {})
      } catch {
        if (!cancelled) setLlmProviderRows([])
      }
    })()
    return () => {
      cancelled = true
    }
  }, [currentUser])

  // Council personality mode: the user's saved default (their choice of seat version).
  useEffect(() => {
    if (!currentUser) {
      setCouncilPersonalityMode('blend')
      return
    }
    let cancelled = false
    ;(async () => {
      const mode = await fetchCouncilPersonalityMode()
      if (!cancelled) setCouncilPersonalityMode(mode)
    })()
    return () => {
      cancelled = true
    }
  }, [currentUser])

  const handleCouncilPersonalityModeChange = useCallback(
    (mode: CouncilPersonalityMode) => {
      const prev = councilPersonalityMode
      setCouncilPersonalityMode(mode)
      void saveCouncilPersonalityMode(mode).then((ok) => {
        if (!ok) setCouncilPersonalityMode(prev) // revert: the default didn't persist
      })
    },
    [councilPersonalityMode],
  )

  const councilAgentList = useMemo(() => {
    const base = perspectiveAgents.length > 0 ? perspectiveAgents : BUILT_IN_PERSPECTIVES
    if (base.some((a) => a.id === 'zenaf' || a.id === 'thinking_partner')) return base
    const z = BUILT_IN_PERSPECTIVES.find((a) => a.id === 'zenaf')
    return z ? [z, ...base] : base
  }, [perspectiveAgents])

  const buildWorkoutPerspectiveDefinition = useCallback((agent: PerspectiveAgent, seatSlotId: string) => {
    const def: Record<string, unknown> = {
      id: seatSlotId,
      perspective_agent_id: agent.id,
      name: agent.name,
      role: agent.role,
      purpose: agent.purpose,
      values: agent.values,
      aversions: agent.aversions,
      reasoningStyle: agent.reasoningStyle,
      tone: agent.tone,
      domain: agent.domain,
      decisionRule: agent.decisionRule,
      worldview: agent.worldview,
      constraints: agent.constraints,
      examplePhrases: agent.examplePhrases,
      promptNotes: agent.promptNotes,
    }
    if (agent.context?.trim()) def.context = agent.context.trim()
    return def
  }, [])

  const runWorkoutCouncilSingle = useCallback(
    async (opts: {
      question: string
      agent: PerspectiveAgent
      seatSlotId: string
      threadForContext: WorkoutMessage[]
      perspectiveLabel: string
    }) => {
      const streamAbort = new AbortController()
      const t = window.setTimeout(() => streamAbort.abort(), COUNCIL_STREAM_MAX_MS)
      try {
        const def = buildWorkoutPerspectiveDefinition(opts.agent, opts.seatSlotId)
        const contextBlock = formatWorkoutContextBlock(opts.threadForContext, opts.perspectiveLabel)
        const reply = await streamWorkoutCouncilResponse({
          runApiBase: RUN_API_BASE,
          question: opts.question,
          contextBlock,
          slotIds: [opts.seatSlotId],
          perspectiveDefinitions: [def],
          buildRoutingContext: () => buildWorkspaceRunRoutingContext(WORKSPACE_ACTION_INTENTS.council, true),
          signal: streamAbort.signal,
        })
        try {
          const agentId = String(opts.agent.id ?? '').trim().slice(0, 512) || 'perspective'
          const tr = createAiActionTrace({
            surface: 'perspectives',
            action_kind: 'structured_evaluation',
            action_intent: 'perspective_workout_council_stream',
            subject_type: 'perspective_agent',
            subject_id: agentId,
            field_key: null,
            input_snapshot: [
              'POST /run/stream | mode=council | perspective_workout',
              `seat_slot_id:${opts.seatSlotId}`,
              `question_char_len:${opts.question.length}`,
              `thread_context_msgs:${opts.threadForContext.length}`,
            ]
              .join('\n')
              .slice(0, 8000),
            model_used: null,
            prompt_version: 'perspective_workout_stream_v1',
            output: reply.slice(0, 12000),
            user_outcome: 'none',
          })
          pushAiActionTrace(tr)
        } catch {
          /* ignore trace errors */
        }
        return reply
      } finally {
        window.clearTimeout(t)
      }
    },
    [buildWorkoutPerspectiveDefinition],
  )

  const councilLlmSelectOptions = useMemo(() => {
    const auto = { value: 'auto', label: 'Auto (policy)' }
    const staticOrder: { value: string; label: string }[] = [
      auto,
      { value: 'ollama', label: 'Ollama (local)' },
      { value: 'openai', label: 'OpenAI' },
      { value: 'anthropic', label: 'Anthropic' },
      { value: 'google', label: 'Google (Gemini)' },
      { value: 'xai', label: 'xAI (Grok)' },
    ]
    if (!currentUser || llmProviderRows.length === 0) return staticOrder
    const rowById = new Map(llmProviderRows.map((p) => [p.id, p]))
    return staticOrder.map((o) => {
      if (o.value === 'auto') return o
      const r = rowById.get(o.value)
      if (!r) return o
      if (r.available) return { value: o.value, label: r.display_name }
      if (!r.enabled) return { value: o.value, label: `${r.display_name} (off in Settings)` }
      return { value: o.value, label: `${r.display_name} (add key in Settings)` }
    })
  }, [currentUser, llmProviderRows])
  const councilMaxSeats = councilExpandedMode ? EXPANDED_MAX_SEATS : MAX_COUNCIL_SEATS
  const councilSelectedCount = councilSeatSlots.slice(0, councilMaxSeats).filter((s) => s.actorId).length
  useEffect(() => {
    const visibleIds = councilSeatSlots.slice(0, councilMaxSeats).map((s) => s.id)
    if (visibleIds.length === 0) return
    if (!selectedCouncilSlotId || !visibleIds.includes(selectedCouncilSlotId)) {
      setSelectedCouncilSlotId(visibleIds[0] ?? 'cs-0')
    }
  }, [councilSeatSlots, councilMaxSeats, selectedCouncilSlotId])

  const applyCouncilSeatClear = useCallback((slotId: string) => {
    setCouncilSeatSlots((prev) => {
      const vis = prev.slice(0, councilMaxSeats)
      const othersFilled = vis.filter((s) => s.id !== slotId && s.actorId != null).length
      if (othersFilled === 0) {
        setMandatesBySeatId((m) => ({ ...m, [slotId]: 'thinking_partner' }))
        return prev.map((s) => (s.id === slotId ? { ...s, actorId: 'zenaf' } : s))
      }
      return prev.map((s) => (s.id === slotId ? { ...s, actorId: null } : s))
    })
  }, [councilMaxSeats])

  // Conversational thread: last agent output / user input so next run can continue the thread
  type AgentThreadMessage = {
    role: 'user' | 'agent' | 'guide' | 'system'
    content: string
    /** Explicit row kind for mediation surface (optional on legacy rows). */
    threadItemKind?: MediationThreadItemKind
    /** Rows tied to an in-flight council run (stripped on completion / error). */
    ephemeralRunId?: string
    agentLabel?: string
    promptSignal?: {
      kind: 'developmental_map'
      promptId: string
      stackRowId?: string
      summaryLine: string
      questionOrigin?: GuideQuestionOrigin
      questionText?: string
      vm_entity_type?: string
      vm_entity_id?: string
    }
    /** After Discuss — hide actions; body may remain for context */
    promptUiHidden?: boolean
    /** "{EntityType} — {Name}" for orientation */
    promptContextTitle?: string
    /** Single-thread subject change: review captured suggestions from the prior subject */
    threadHandoffReview?: {
      reviewId: string
      forSubjectLabel: string
      previousSubjectKey: string
      items: { id: string; text: string }[]
    }
    /** Client id for ResonanceSlider sessionStorage — same as council run id for council/Zenaf replies. */
    resonanceResponseId?: string
    /** Present when this assistant turn committed precision text to Vision & Execution. */
    integrationCommit?: IntegrationCommitPayload | null
    /** Proposed save from this turn; stripped when a later turn commits. */
    pendingIntegration?: PendingIntegrationPayload | null
    /** Human-visible council question line when `content` carries internal invite preface. */
    councilThreadDisplayContent?: string
    /** Folded scoped sub-thread after Return (single row; expand to see messages). */
    nestedScopedThread?: {
      id: string
      label: string
      children: AgentThreadMessage[]
    }
  }
  const [agentThread, setAgentThread] = useState<AgentThreadMessage[]>([])
  const agentThreadRef = useRef(agentThread)
  agentThreadRef.current = agentThread

  const handleCouncilEntityMentionOpen = useCallback((p: EntityMentionOpenPayload) => {
    const enriched = enrichScopedDigressionLabel(p, {
      ideaLabels: councilIdeaLabelsRef.current,
      bundle: councilVeEntityBundleRef.current,
    })
    setCouncilScopeThreadStartIndex(agentThreadRef.current.length)
    setCouncilScopedDigression(enriched)
  }, [])

  const foldScopedThreadIntoNest = useCallback(() => {
    const start = councilScopeThreadStartIndexRef.current
    const label = councilScopedDigressionRef.current?.label ?? 'Focused thread'
    setCouncilScopedDigression(null)
    setCouncilScopeThreadStartIndex(null)
    setAgentThread((prev) => {
      if (start == null || start >= prev.length) return prev
      const nestId = newScopedThreadNestId()
      const children = prev.slice(start).map((row) => ({ ...row }))
      const before = prev.slice(0, start)
      const nest: AgentThreadMessage = {
        role: 'system',
        content: '',
        threadItemKind: 'scoped_thread_nest',
        nestedScopedThread: { id: nestId, label, children },
      }
      return [...before, nest]
    })
  }, [])

  const lastConversationalFocusInviteRef = useRef<{ key: string; t: number } | null>(null)

  const mapSeedGenRef = useRef(0)
  const deferResurfaceFingerprintRef = useRef<Map<string, string>>(new Map())
  const guideRowPromptId = useCallback((row: AgentThreadMessage) => {
    if (row.role !== 'guide') return ''
    const sig = row.promptSignal
    if (sig?.stackRowId) return sig.stackRowId
    return sig?.promptId ?? ephemeralGuidePromptIdFromContent(row.content)
  }, [])
  const removeGuideRowsForPromptId = useCallback(
    (promptId: string) => {
      setExpandedThreadGuidePromptId((e) => (e === promptId ? null : e))
      setNestedStackGuidePromptId((n) => (n === promptId ? null : n))
      setActiveConversationalSuggestionPromptId((a) => (a === promptId ? null : a))
      setAgentThread((prev) =>
        prev.filter((row) => !(row.role === 'guide' && guideRowPromptId(row) === promptId)),
      )
    },
    [guideRowPromptId],
  )

  const dismissGuideFromThread = useCallback(
    (stackRowOrPromptId: string) => {
      setAgentThread((prev) => {
        const victim = prev.find((r) => r.role === 'guide' && guideRowPromptId(r) === stackRowOrPromptId)
        if (victim?.role === 'guide') {
          const canonical =
            victim.promptSignal?.promptId ?? ephemeralGuidePromptIdFromContent(victim.content)
          deferResurfaceFingerprintRef.current.delete(canonical)
        }
        return prev.filter((row) => !(row.role === 'guide' && guideRowPromptId(row) === stackRowOrPromptId))
      })
      setExpandedThreadGuidePromptId((e) => (e === stackRowOrPromptId ? null : e))
      setNestedStackGuidePromptId((n) => (n === stackRowOrPromptId ? null : n))
      setActiveConversationalSuggestionPromptId((a) => (a === stackRowOrPromptId ? null : a))
    },
    [guideRowPromptId],
  )

  const removeAgentThreadGuidesForPromptId = dismissGuideFromThread
  const hidePromptActionsForPromptId = useCallback(
    (promptId: string) => {
      setAgentThread((prev) =>
        prev.map((row) =>
          row.role === 'guide' && guideRowPromptId(row) === promptId
            ? { ...row, promptUiHidden: true }
            : row,
        ),
      )
    },
    [guideRowPromptId],
  )
  const [streamingCouncilText, setStreamingCouncilText] = useState('')
  const [streamingCouncilRunLabel, setStreamingCouncilRunLabel] = useState('Council')
  const [councilStreamPhase, setCouncilStreamPhase] = useState<CouncilStreamPhase>('idle')
  const councilTransportTimingRef = useRef<CouncilTransportTimings | null>(null)
  /** How to render last completed council output when thread is empty (transcript vs plain). */
  const [lastCouncilPresentationKind, setLastCouncilPresentationKind] = useState<
    'thinking' | 'multiseat' | 'folder'
  >('multiseat')
  const [lastCouncilWasFolderWorkflow, setLastCouncilWasFolderWorkflow] = useState(false)
  /** When true, server runs integrator pass and UI shows “Zenaf synthesis”; default off. */
  const [includeCouncilSynthesis, setIncludeCouncilSynthesis] = useState(false)
  const [councilSynthesisIntegrity, setCouncilSynthesisIntegrity] = useState<CouncilSynthesisIntegrityState | null>(null)
  const [councilIntegrityWarning, setCouncilIntegrityWarning] = useState<string | null>(null)
  const [councilSynthesisIntegrityEnvelope, setCouncilSynthesisIntegrityEnvelope] =
    useState<CouncilIntegrityEnvelopePayload | null>(null)
  const streamingCouncilResonanceKeyRef = useRef(`stream-${Date.now()}`)
  useEffect(() => {
    if (!streamingCouncilText.trim()) {
      streamingCouncilResonanceKeyRef.current = `stream-${Date.now()}`
    }
  }, [streamingCouncilText])
  useLayoutEffect(() => {
    if (agentConversationScrollNonce === 0) return
    const pane = agentConversationScrollRef.current
    if (pane) {
      pane.scrollTop = pane.scrollHeight
    } else {
      agentConversationEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
    }
  }, [agentConversationScrollNonce])
  useLayoutEffect(() => {
    if (!loading || !streamingCouncilText) return
    const pane = agentConversationScrollRef.current
    if (pane) {
      pane.scrollTop = pane.scrollHeight
    } else {
      agentConversationEndRef.current?.scrollIntoView({ block: 'end', behavior: 'auto' })
    }
  }, [streamingCouncilText, loading])
  const [councilInsightSaving, setCouncilInsightSaving] = useState(false)
  const [councilInsightNotice, setCouncilInsightNotice] = useState<string | null>(null)
  useEffect(() => {
    if (activeMode !== 'council' && councilStreamPhase === 'completed') {
      setCouncilStreamPhase('idle')
    }
  }, [activeMode, councilStreamPhase])

  const COUNCIL_STREAM_BUSY_PHASES: ReadonlySet<CouncilStreamPhase> = new Set([
    'connecting',
    'connected_waiting_first_chunk',
    'streaming',
    'finalizing',
  ])

  const handleFocusInvite = useCallback((invite: FocusInvite, core: FocusContextCore) => {
    if (invite.kind === 'conversational') {
      if (COUNCIL_STREAM_BUSY_PHASES.has(councilStreamPhase)) return
      const dedupeKey = `${invite.id}:${core.entity_id}`
      const now = Date.now()
      const prevRun = lastConversationalFocusInviteRef.current
      if (prevRun && prevRun.key === dedupeKey && now - prevRun.t < 4000) return
      lastConversationalFocusInviteRef.current = { key: dedupeKey, t: now }

      const prevThread = agentThreadRef.current
      const dig = councilScopedDigressionRef.current
      const scopeStart = councilScopeThreadStartIndexRef.current
      const sameEntityScoped =
        Boolean(dig) &&
        dig!.entityId === core.entity_id &&
        dig!.entityType === core.entity_type &&
        scopeStart != null &&
        scopeStart <= prevThread.length
      const trimmed =
        sameEntityScoped && scopeStart != null
          ? prevThread.slice(0, scopeStart)
          : prevThread.slice()

      setActiveMode('council')
      setAgentThread(trimmed)
      const nextScopeStart = trimmed.length
      setCouncilScopeThreadStartIndex(nextScopeStart)
      setCouncilScopedDigression({
        entityId: core.entity_id,
        entityType: core.entity_type,
        label: buildScopedContextLabelFromCore(core),
      })
      const preface = buildConversationalInvitePreface(invite, core)
      const hint = buildConversationalInviteDisplayLine(invite, core)
      void runCouncilRef.current?.(preface, {
        preserveComposer: false,
        threadDisplayHint: hint,
        councilContextThreadOverride: trimmed,
      })
      return
    }
    setActiveMode('council')
    setQuestion(buildStructuredFillInvitePreface(invite, core))
  }, [councilStreamPhase])

  const buildAgentThreadContext = (): string => {
    if (agentThread.length === 0) return ''
    const formatOne = (m: AgentThreadMessage): string | null => {
      if (m.threadItemKind === 'scoped_thread_nest' && m.nestedScopedThread) {
        const inner = m.nestedScopedThread.children
          .map(formatOne)
          .filter((x): x is string => x != null)
        if (inner.length === 0) return `[Scoped thread — ${m.nestedScopedThread.label}]`
        return `[Scoped thread — ${m.nestedScopedThread.label}]\n${inner.join('\n\n')}`
      }
      if (
        m.role === 'system' ||
        m.threadItemKind === 'system_status' ||
        m.threadItemKind === 'streaming_placeholder'
      ) {
        return null
      }
      if (m.role === 'user') return `User: ${m.councilThreadDisplayContent ?? m.content}`
      if (m.role === 'guide') return `Guide: ${m.content}`
      if (m.threadHandoffReview) {
        const bits = m.threadHandoffReview.items.map((x) => x.text).join(' | ')
        return `Agent (${m.agentLabel ?? 'handoff'}): unresolved from ${m.threadHandoffReview.forSubjectLabel}: ${bits}`
      }
      return `Agent${m.agentLabel ? ` (${m.agentLabel})` : ''}: ${m.content}`
    }
    const lines = agentThread.slice(-12).map(formatOne).filter((x): x is string => x != null)
    return 'Recent conversation:\n' + lines.join('\n\n')
  }

  const handleVisionMapCouncilInteraction = (action: VisionMapCouncilInteraction) => {
    if (action.type === 'seed') {
      const sel = veSelectionFromMapPayload(action.payload)
      if (sel) setVeSelection(sel)
      else setVeSelection(null)
      setActiveMode('council')
      setError(null)
      setQuestion('')
      const g = ++mapSeedGenRef.current
      void (async () => {
        let seedFlowReadings: ExecutionFlowReadingSummary[] = []
        const seedRef = veEntityRefFromMapTriad(action.developmentalSnapshotForPrompt ?? null)
        if (seedRef) {
          try {
            seedFlowReadings = await fetchExecutionFlowReadings(seedRef.entity_type, seedRef.entity_id, 12)
          } catch {
            seedFlowReadings = []
          }
        }
        const ctxFromSeed =
          action.developmentalSnapshotForPrompt != null
            ? buildDevelopmentalGuidanceContext({
                mapTriad: action.developmentalSnapshotForPrompt,
                recentTraces: getRecentAiActionTraces(),
                executionFlowReadings: seedFlowReadings,
              })
            : null
        const preview = developmentalGuidancePreview
        const mergedCtx = ctxFromSeed ?? preview
        let pid = mergedCtx ? developmentalMapVisionMapPromptId(mergedCtx) : null
        const ref = action.payload.ref
        if (!pid) {
          pid = fallbackMapGuidePromptId(
            ref.veType,
            ref.id,
            action.payload.kind,
            action.guideTexts.join('\n\n'),
          )
        }
        const show = await checkPromptShouldShow(pid)
        if (mapSeedGenRef.current !== g) return
        if (!show) {
          setAgentThread((prev) => (action.resetThread ? [] : prev))
          window.setTimeout(() => councilQuestionTextareaRef.current?.focus(), 0)
          return
        }
        if (mapSeedGenRef.current !== g) return
        const seedFp = buildDevelopmentalMapFingerprint(mergedCtx)
        const seedDeferredFp = deferResurfaceFingerprintRef.current.get(pid!)
        if (seedDeferredFp != null && seedDeferredFp !== seedFp) {
          deferResurfaceFingerprintRef.current.delete(pid!)
          setAgentThread((prev) => (action.resetThread ? [] : prev))
          window.setTimeout(() => councilQuestionTextareaRef.current?.focus(), 0)
          return
        }
        if (seedDeferredFp != null && seedDeferredFp === seedFp) {
          deferResurfaceFingerprintRef.current.delete(pid!)
        }
        const vmExtra =
          mergedCtx?.vm_entity_type && mergedCtx?.vm_entity_id
            ? { vm_entity_type: mergedCtx.vm_entity_type, vm_entity_id: mergedCtx.vm_entity_id }
            : { vm_entity_type: ref.veType, vm_entity_id: ref.id }
        const promptContextTitle = formatSystemPromptContextTitle({
          mainView: councilRuntimeRef.current.mainView,
          mapNodeKind: action.payload.kind,
          veType: ref.veType,
          nodeLabel: action.developmentalSnapshotForPrompt?.node_label ?? action.payload.label,
          nestAggregate: action.developmentalSnapshotForPrompt?.node_kind === 'nest',
        })
        const guides = action.guideTexts.map((content, idx) => {
          const meta = metaForSeededGuideContent(content, idx, pid!)
          return {
            role: 'guide' as const,
            content,
            promptContextTitle,
            promptSignal: {
              kind: 'developmental_map' as const,
              promptId: pid!,
              stackRowId: meta.stackRowId,
              summaryLine: meta.questionText.slice(0, 200),
              questionOrigin: meta.origin,
              questionText: meta.questionText,
              ...vmExtra,
            },
          }
        })
        setAgentThread((prev) => {
          const base = action.resetThread ? [] : prev
          return [...base, ...guides]
        })
        window.setTimeout(() => councilQuestionTextareaRef.current?.focus(), 0)
      })()
      return
    }
    if (action.type === 'focus_council_input') {
      setActiveMode('council')
      window.setTimeout(() => councilQuestionTextareaRef.current?.focus(), 0)
      return
    }
    if (action.type === 'suggest_council_prefill') {
      setActiveMode('council')
      setQuestion(action.text)
      window.setTimeout(() => councilQuestionTextareaRef.current?.focus(), 0)
      return
    }
    if (action.type === 'run_council') {
      const sel = veSelectionFromMapPayload(action.payload)
      if (sel) setVeSelection(sel)
      else setVeSelection(null)
      setActiveMode('council')
      setError(null)
      councilRunMapPayloadRef.current = action.payload
      councilInvocationNextRef.current = 'full_multiseat'
      void runCouncil(action.question)
      return
    }
    if (action.type === 'open_execution_tab') {
      setMainView('vision_execution')
      setVeFocusTabRequest(action.tab)
      return
    }
    if (action.type === 'open_inspected_in_ve') {
      const sel = veSelectionFromEntityRef(resolveInspectEntityRef(action.node))
      if (sel) setVeSelection(sel)
      setMainView('vision_execution')
      return
    }
  }

  const onMapEntitySelectionChange = useCallback((payload: MapNodePayload | null) => {
    setVeSelection(payload ? veSelectionFromMapPayload(payload) ?? null : null)
  }, [])

  const runReassessWithPerspective = async (reviewer: PerspectiveAgent) => {
    const items = lastAssessResult?.items ?? []
    if (items.length === 0) return
    setError(null)
    setReassessResults(null)
    setReassessReviewerName(null)
    setReassessApproved(new Set())
    setReassessDenied(new Set())
    setReassessModalOpen(false)
    setWorkspaceTraceOutcomeBanner(null)
    setLoading(true)
    const folder_path = lastAssessResult?.simulate_tree?.folder_path ?? lastFolderPath ?? ''
    const suggested_folders = lastAssessResult?.simulate_tree?.suggested_child_folders ?? lastSimulateResult?.suggested_child_folders ?? []
    const perspective_definition = {
      name: reviewer.name,
      role: reviewer.role,
      purpose: reviewer.purpose,
      values: reviewer.values,
      decisionRule: reviewer.decisionRule,
      tone: reviewer.tone,
    }
    try {
      const res = await fetch(`${RUN_API_BASE}/run`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mode: 'reassess_low_confidence',
          params: {
            low_confidence_items: items,
            perspective_definition,
            suggested_folders: suggested_folders.length > 0 ? suggested_folders : undefined,
            folder_path: folder_path || undefined,
          },
          routing_context: buildWorkspaceRunRoutingContext(WORKSPACE_ACTION_INTENTS.reassess, false),
        }),
      })
      const data: RunResponse & { detail?: string } = await res.json()
      if (!res.ok) {
        setError(data.error || data.detail || res.statusText || 'Reassess failed')
        return
      }
      if (data.execution_blocked) {
        setError(workspaceExecutionBlockedMessage(data))
        return
      }
      if (!data.ok || data.result == null) {
        setError(data.error || 'No result')
        return
      }
      const list = Array.isArray(data.result) ? (data.result as ReassessItemResult[]) : []
      try {
        const tr = emitWorkspaceTraceFromResult({
          action_intent: WORKSPACE_ACTION_INTENTS.reassess,
          folder_path: folder_path || null,
          input_snapshot: buildWorkspaceReassessSnapshot({
            folder_path,
            items_n: items.length,
            reviewer_name: reviewer.name,
          }),
          result: list,
          resolved_model_used: data.model_used ?? undefined,
        })
        workspaceOutcomeTargetRef.current = { trace: tr, action_intent: WORKSPACE_ACTION_INTENTS.reassess }
      } catch {
        /* ignore trace errors */
      }
      setReassessResults(list)
      setReassessReviewerName(reviewer.name)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Reassess request failed')
    } finally {
      setLoading(false)
    }
  }
  const openReassessModal = () => {
    const items = lastAssessResult?.items ?? []
    if (items.length === 0) return
    setReassessSelectedId(councilAgentList[0]?.id ?? null)
    setReassessModalOpen(true)
  }
  const handleReassessApprove = (itemName: string) => {
    setReassessApproved((prev) => new Set(prev).add(itemName))
    setReassessDenied((prev) => {
      const next = new Set(prev)
      next.delete(itemName)
      return next
    })
    const w = workspaceOutcomeTargetRef.current
    if (w?.action_intent === WORKSPACE_ACTION_INTENTS.reassess) {
      try {
        recordWorkspaceTraceUserOutcome(w.trace, 'applied')
      } catch {
        /* ignore */
      }
      postWorkspaceLearningFromRef(w, 'applied')
    }
  }
  const handleReassessDeny = (itemName: string) => {
    setReassessDenied((prev) => new Set(prev).add(itemName))
    setReassessApproved((prev) => {
      const next = new Set(prev)
      next.delete(itemName)
      return next
    })
    const w = workspaceOutcomeTargetRef.current
    if (w?.action_intent === WORKSPACE_ACTION_INTENTS.reassess) {
      try {
        // Per-item deny: user triaged output without accepting that line — use edited, not dismissed (not rejecting the whole run).
        recordWorkspaceTraceUserOutcome(w.trace, 'edited')
      } catch {
        /* ignore */
      }
      postWorkspaceLearningFromRef(w, 'edited')
    }
  }
  const runWebSearchForContext = () => {
    const ctx = lastAnalyzeResult?.inferred_context_domain || lastFolderPath || 'desktop files'
    const q = `folder organization best practices ${ctx}`
    setQuery(q)
    runWebResearch(q)
  }
  const runSelectedAgent = () => {
    void runCouncil(undefined)
  }
  // Only block while a run is in flight. Empty question is OK (runCouncil defaults). At least one seat is always implied (default Zenaf thinking partner).
  const agentRunDisabled = loading || councilTransformLoading
  const agentResponse: string | null =
    lastMode === 'council' && lastCouncilResult ? lastCouncilResult
    : lastMode === 'web_research' && lastWebResearchResult
      ? lastWebResearchResult.error
        ? lastWebResearchResult.error
        : (lastWebResearchResult.top_findings ?? []).join('\n• ') || lastWebResearchResult.query || ''
    : lastMode === 'next_step' && lastNextStepResult
      ? lastNextStepResult.error
        ? lastNextStepResult.error
        : (lastNextStepResult.recommendation ?? '') + (lastNextStepResult.rationale ? '\n\n' + lastNextStepResult.rationale : '')
    : null

  const resolveCouncilInsightText = useCallback((): string | null => {
    if (streamingCouncilText.trim()) return streamingCouncilText
    const fromThread = findLastCouncilContentInRows(agentThread as CouncilInsightScanRow[])
    if (fromThread) return fromThread
    if (lastMode === 'council' && (agentResponse?.trim() ?? '')) return agentResponse!.trim()
    return null
  }, [streamingCouncilText, agentThread, lastMode, agentResponse])

  const handleRecordCouncilInsight = useCallback(async () => {
    const text = resolveCouncilInsightText()
    if (!text?.trim()) return
    setCouncilInsightSaving(true)
    setCouncilInsightNotice(null)
    try {
      await postCouncilInsightRecognition(veApiPost, {
        bodyText: text,
        label: streamingCouncilRunLabel || undefined,
        userId: currentUser?.id ?? null,
      })
      setCouncilInsightNotice('Recorded as decision (meaning-only recognition).')
    } catch (e) {
      setCouncilInsightNotice(e instanceof Error ? e.message : 'Could not record insight')
    } finally {
      setCouncilInsightSaving(false)
    }
  }, [resolveCouncilInsightText, currentUser?.id, streamingCouncilRunLabel])

  // Top-level view: Living Tree (default), Vision map, Workspace Organizer, Perspectives, Content, Vision → Execution
  type MainView =
    | 'living_tree'
    | 'workspace'
    | 'perspectives'
    | 'content'
    | 'vision_map'
    | 'vision_execution'
    | 'agent_intake'
    | 'review'
    | 'signal_review'
    | 'settings'
  const [mainView, setMainView] = useState<MainView>('living_tree')
  const [navOpen, setNavOpen] = useState(false)
  // Mobile: the conversation panel starts collapsed so the view's content owns
  // the screen; expand on demand. Desktop (lg+) always shows it.
  const [chatPanelCollapsed, setChatPanelCollapsed] = useState(
    () => typeof window !== 'undefined' && window.matchMedia('(max-width: 1023.98px)').matches,
  )
  const [veSelection, setVeSelection] = useState<VESelection | null>(null)
  /** Avoid new object identity on every VisionExecutionView `bundleForFocus` refresh when ids are unchanged. */
  const stableVeSelectionForExecutionView = useMemo(
    () => veSelection,
    [
      veSelection?.tab,
      veSelection?.ideaId,
      veSelection?.initiativeId,
      veSelection?.projectId,
      veSelection?.taskId,
      veSelection?.assetId,
    ],
  )
  const [veFocusTabRequest, setVeFocusTabRequest] = useState<VEWorkspaceTabId | null>(null)
  const consumeVeFocusTabRequest = useCallback(() => setVeFocusTabRequest(null), [])
  const [veRadarScrollBucket, setVeRadarScrollBucket] = useState<VeRadarBucketId | null>(null)
  const clearVeRadarScrollBucket = useCallback(() => setVeRadarScrollBucket(null), [])
  const handleOpenVeRadar = useCallback((bucket?: VeRadarBucketId) => {
    setMainView('vision_execution')
    setVeFocusTabRequest('radar')
    setVeRadarScrollBucket(bucket ?? null)
  }, [])
  const [mapDevelopmentalSnapshot, setMapDevelopmentalSnapshot] = useState<MapTriadDevelopmentalSnapshot | null>(null)
  const [mapExecutionFlowReadings, setMapExecutionFlowReadings] = useState<ExecutionFlowReadingSummary[]>([])
  const [perspectivesCoreProfiles, setPerspectivesCoreProfiles] = useState<CoreProfile[]>([])
  const [perspectivesLinksLoading, setPerspectivesLinksLoading] = useState(false)
  const [perspectivesPageError, setPerspectivesPageError] = useState<string | null>(null)
  const [foundationSelectedActorId, setFoundationSelectedActorId] = useState<string | null>('storyteller')
  const [foundationActorUi, setFoundationActorUi] = useState<'browse' | 'create_actor' | 'edit_actor'>('browse')
  const [foundationEditAgent, setFoundationEditAgent] = useState<PerspectiveAgent | null>(null)
  /** Foundation "Train AI" enters shared council shell with a Zenaf preset. */
  const [foundationTrainingMode, setFoundationTrainingMode] = useState(false)
  /** Core profile `name` field — drives the Foundation core-voice card title. */
  const [foundationCoreProfileCardTitle, setFoundationCoreProfileCardTitle] = useState('')
  /** Perspective Workout: ephemeral directed training in the aside (replaces council UI while active). */
  const [workoutActive, setWorkoutActive] = useState(false)
  const [workoutPerspective, setWorkoutPerspective] = useState<PerspectiveAgent | null>(null)
  const [workoutThread, setWorkoutThread] = useState<WorkoutMessage[]>([])
  const [workoutScenario, setWorkoutScenario] = useState('')
  const [workoutInvokingSeat, setWorkoutInvokingSeat] = useState<string | null>(null)
  const [workoutInput, setWorkoutInput] = useState('')
  const [workoutExitToast, setWorkoutExitToast] = useState<string | null>(null)
  const showFolderReviewPanel = mainView === 'workspace' && lastRecommendResult != null && !lastRecommendResult.error

  const mediationPanelMode = useMemo(
    () =>
      deriveMediationPanelMode({
        showFolderReviewPanel,
        workoutActive,
        councilTransformLoading,
        activeMode,
        loading,
        agentThreadLength: agentThread.length,
        councilStreamPhase,
      }),
    [
      showFolderReviewPanel,
      workoutActive,
      councilTransformLoading,
      activeMode,
      loading,
      agentThread.length,
      councilStreamPhase,
    ],
  )

  useEffect(() => {
    if (!workoutExitToast) return
    const t = window.setTimeout(() => setWorkoutExitToast(null), 2000)
    return () => window.clearTimeout(t)
  }, [workoutExitToast])

  const handleStartWorkout = useCallback((agent: PerspectiveAgent) => {
    setFoundationTrainingMode(false)
    setWorkoutPerspective(agent)
    setWorkoutThread([])
    setWorkoutScenario('')
    setWorkoutInvokingSeat(null)
    setWorkoutInput('')
    setWorkoutExitToast(null)
    setWorkoutActive(true)
    setMainView('workspace')
    setError(null)
  }, [])

  const handleEnterFoundationTrainingMode = useCallback(() => {
    setFoundationTrainingMode(true)
    setWorkoutActive(false)
    setMainView('perspectives')
    setError(null)
    setLastMode('council')
    setCouncilExpandedMode(false)
    setCouncilAdvancedOptions(false)
    setIncludeCouncilSynthesis(true)
    setSelectedCouncilSlotId('cs-0')
    setMandatesBySeatId((prev) => ({
      ...prev,
      'cs-0': 'thinking_partner',
    }))
    setCouncilSeatSlots((prev) =>
      prev.map((s, i) => ({
        ...s,
        actorId: i === 0 ? 'zenaf' : null,
      })),
    )
    window.setTimeout(() => councilQuestionTextareaRef.current?.focus(), 0)
  }, [])

  useEffect(() => {
    if (mainView !== 'perspectives') {
      setFoundationTrainingMode(false)
    }
  }, [mainView])

  const handleWorkoutSendSeat1 = useCallback(async () => {
    const p = workoutPerspective
    if (!p || workoutInvokingSeat != null) return
    const text = workoutInput.trim()
    if (!text) return
    setWorkoutInput('')
    setWorkoutScenario((s) => s || text.slice(0, 500))
    const prior = workoutThread
    const userMsg: WorkoutMessage = {
      id: newWorkoutMessageId(),
      kind: 'user',
      content: text,
      timestamp: new Date().toISOString(),
      responseId: '',
    }
    const withUser = [...prior, userMsg]
    setWorkoutThread(withUser)
    setWorkoutInvokingSeat('__seat1__')
    setError(null)
    try {
      const reply = await runWorkoutCouncilSingle({
        question: text,
        agent: p,
        seatSlotId: 'workout-s1',
        threadForContext: prior,
        perspectiveLabel: p.name.trim() || 'Perspective',
      })
      const responseId = newWorkoutMessageId()
      const respMsg: WorkoutMessage = {
        id: newWorkoutMessageId(),
        kind: 'perspective',
        content: reply,
        timestamp: new Date().toISOString(),
        responseId,
      }
      setWorkoutThread([...withUser, respMsg])
    } catch (e) {
      setWorkoutThread(prior)
      setError(e instanceof Error ? e.message : 'Workout failed')
    } finally {
      setWorkoutInvokingSeat(null)
    }
  }, [workoutInput, workoutInvokingSeat, workoutPerspective, workoutThread, runWorkoutCouncilSingle])

  const handleWorkoutInvokeSeat = useCallback(
    async (invoked: PerspectiveAgent) => {
      const p = workoutPerspective
      if (!p || workoutInvokingSeat != null) return
      const lastPerspective = [...workoutThread].reverse().find((m) => m.kind === 'perspective')
      const anchor =
        lastPerspective?.content?.trim() ||
        [...workoutThread].reverse().find((m) => m.kind === 'user')?.content?.trim()
      if (!anchor) {
        setError('Have a conversation with the perspective first, then tap another seat.')
        return
      }
      const q = `Respond to ${(p.name || 'the perspective').trim()}'s position: ${anchor}`
      setWorkoutInvokingSeat(invoked.id)
      setError(null)
      try {
        const slotId = `workout-invoke-${invoked.id}`
        const reply = await runWorkoutCouncilSingle({
          question: q,
          agent: invoked,
          seatSlotId: slotId,
          threadForContext: workoutThread,
          perspectiveLabel: p.name.trim() || 'Perspective',
        })
        const responseId = newWorkoutMessageId()
        setWorkoutThread((prev) => [
          ...prev,
          {
            id: newWorkoutMessageId(),
            kind: 'seat',
            seatId: invoked.id,
            seatName: invoked.name,
            content: reply,
            timestamp: new Date().toISOString(),
            responseId,
          },
        ])
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Seat invocation failed')
      } finally {
        setWorkoutInvokingSeat(null)
      }
    },
    [workoutPerspective, workoutInvokingSeat, workoutThread, runWorkoutCouncilSingle],
  )

  const handleWorkoutExitRequest = useCallback(() => {
    if (workoutThread.length > 0) {
      if (!window.confirm('End workout? Your thread in this panel will be cleared.')) return
    }
    const exchanges = workoutThread.filter((m) => m.kind !== 'user').length
    const ratings = countWorkoutRatingsInStorage(workoutThread)
    if (workoutThread.length > 0) {
      setWorkoutExitToast(`Session saved. ${exchanges} exchanges, ${ratings} ratings.`)
    }
    setWorkoutThread([])
    setWorkoutPerspective(null)
    setWorkoutScenario('')
    setWorkoutInvokingSeat(null)
    setWorkoutInput('')
    setWorkoutActive(false)
    setMainView('perspectives')
  }, [workoutThread])

  const refetchPerspectivesLinkData = useCallback(async () => {
    setPerspectivesLinksLoading(true)
    setPerspectivesPageError(null)
    try {
      const cp = await veApiGet<CoreProfile[]>('/core-profiles')
      setPerspectivesCoreProfiles(Array.isArray(cp) ? cp : [])
    } catch (e) {
      setPerspectivesPageError(e instanceof Error ? e.message : 'Failed to load')
      setPerspectivesCoreProfiles([])
    } finally {
      setPerspectivesLinksLoading(false)
    }
  }, [])

  useEffect(() => {
    if (mainView !== 'perspectives') return
    void refetchPerspectivesLinkData()
  }, [mainView, refetchPerspectivesLinkData])

  /** Anonymous: re-merge perspective actors from localStorage when opening Foundation. Signed-in: server is source of truth. */
  useEffect(() => {
    if (mainView !== 'perspectives') return
    if (currentUser) return
    try {
      const raw = localStorage.getItem(PERSPECTIVE_STORAGE_KEY)
      if (!raw) return
      const parsed = JSON.parse(raw) as unknown
      if (!Array.isArray(parsed)) return
      const normalized = normalizeStoredPerspectiveAgents(parsed as PerspectiveAgent[])
      setPerspectiveAgents(normalized)
      try {
        localStorage.setItem(PERSPECTIVE_STORAGE_KEY, JSON.stringify(normalized))
      } catch {
        /* ignore */
      }
    } catch {
      /* ignore */
    }
  }, [mainView, currentUser])

  const perspectiveInfluenceLinkLists = useMemo(() => {
    const multi = perspectivesCoreProfiles.length > 1
    const cid = canonicalCoreProfileId(perspectivesCoreProfiles)
    return {
      coreProfiles: perspectivesCoreProfiles.map((p) => ({
        id: p.id,
        label: coreProfileInfluencePickLabel(p, cid, multi),
      })),
    }
  }, [perspectivesCoreProfiles])

  const brandCoreProfileId = useMemo(
    () => canonicalCoreProfileId(perspectivesCoreProfiles),
    [perspectivesCoreProfiles],
  )

  const profileGraphSnapshot = useMemo(
    () => ({ profiles: perspectivesCoreProfiles, activeProfileId: brandCoreProfileId }),
    [perspectivesCoreProfiles, brandCoreProfileId],
  )

  useEffect(() => {
    if (mainView !== 'perspectives') return
    if (!brandCoreProfileId) {
      setFoundationCoreProfileCardTitle('')
      return
    }
    const row = perspectivesCoreProfiles.find((p) => p.id === brandCoreProfileId)
    setFoundationCoreProfileCardTitle((row?.name ?? '').trim())
  }, [mainView, brandCoreProfileId, perspectivesCoreProfiles])

  useEffect(() => {
    if (!perspectivesRemoteReady) return
    if (perspectiveAgents.length === 0) return
    try {
      localStorage.setItem(PERSPECTIVE_STORAGE_KEY, JSON.stringify(perspectiveAgents))
    } catch {
      /* ignore */
    }
    if (!currentUser) return
    const t = window.setTimeout(() => {
      void veApiPut('/council-workspace/perspectives', { perspectives: perspectiveAgents }).catch(() => {})
    }, 450)
    return () => window.clearTimeout(t)
  }, [perspectiveAgents, currentUser, perspectivesRemoteReady])

  const foundationSelectedAgent = useMemo(() => {
    if (!foundationSelectedActorId) return null
    return perspectiveAgents.find((a) => a.id === foundationSelectedActorId) ?? null
  }, [foundationSelectedActorId, perspectiveAgents])

  const handleCreateCoreProfile = async (payload: {
    name: string
    core_definition?: string
    current_goals?: string
    growth_focus_12_months?: string
    economic_engine?: string
    non_negotiables?: string
    strategic_filter?: string
    current_constraints?: string
    capacity_limit?: string
    kill_philosophy?: string
    strength_positioning?: string
  }) => {
    setPerspectivesPageError(null)
    try {
      await veApiPost<CoreProfile>('/core-profiles', {
        name: payload.name || 'Core Profile',
        core_definition: payload.core_definition ?? '',
        current_goals: payload.current_goals ?? '',
        growth_focus_12_months: payload.growth_focus_12_months ?? '',
        economic_engine: payload.economic_engine ?? '',
        non_negotiables: payload.non_negotiables ?? '',
        strategic_filter: payload.strategic_filter ?? '',
        current_constraints: payload.current_constraints ?? '',
        capacity_limit: payload.capacity_limit ?? '',
        kill_philosophy: payload.kill_philosophy ?? '',
        strength_positioning: payload.strength_positioning ?? '',
      })
      await refetchPerspectivesLinkData()
    } catch (e) {
      setPerspectivesPageError(e instanceof Error ? e.message : 'Create failed')
    }
  }

  // Current topic: what the system is pointed at (dynamic for context window + perspective suggestions)
  const currentTopicLabel =
    currentFocusPath || lastFolderPath
      ? (currentFocusPath || lastFolderPath).replace(/^.*[\\/]/, '') || currentFocusPath || lastFolderPath
      : 'No folder'
  const currentTopicMode = currentFocusMode ?? lastMode
  const currentTopicSummary =
    lastMode === 'analyze' && lastAnalyzeResult && !lastAnalyzeResult.error
      ? lastAnalyzeResult.inferred_context_domain ?? `${lastAnalyzeResult.item_count ?? 0} items`
      : lastMode === 'council' && question?.trim()
        ? question.slice(0, 60) + (question.length > 60 ? '…' : '')
        : lastMode === 'web_research' && lastWebResearchResult?.query
          ? lastWebResearchResult.query
          : lastMode === 'recommend' && lastRecommendResult && !lastRecommendResult.error
            ? lastRecommendResult.inferred_context_domain ?? 'recommendations'
            : currentTopicMode
              ? `${MODES.find((m) => m.id === currentTopicMode)?.label ?? currentTopicMode}`
              : ''
  const currentTopic = {
    label: currentTopicLabel,
    mode: currentTopicMode,
    modeLabel: currentTopicMode ? MODES.find((m) => m.id === currentTopicMode)?.label ?? currentTopicMode : null,
    summary: currentTopicSummary,
    fullPath: currentFocusPath || lastFolderPath || '',
  }

  councilRuntimeRef.current = {
    mainView,
    currentTopic: {
      label: currentTopic.label,
      modeLabel: currentTopic.modeLabel,
      summary: currentTopic.summary,
    },
    ve_selection: veSelection,
  }

  useEffect(() => {
    if (mainView !== 'vision_map') {
      setMapDevelopmentalSnapshot(null)
    }
  }, [mainView])

  useEffect(() => {
    if (mainView !== 'vision_map' || !mapDevelopmentalSnapshot) {
      setMapExecutionFlowReadings([])
      return
    }
    const ref = veEntityRefFromMapTriad(mapDevelopmentalSnapshot)
    if (!ref) {
      setMapExecutionFlowReadings([])
      return
    }
    let cancelled = false
    void fetchExecutionFlowReadings(ref.entity_type, ref.entity_id, 12).then((rows) => {
      if (!cancelled) setMapExecutionFlowReadings(rows)
    })
    return () => {
      cancelled = true
    }
  }, [mainView, mapDevelopmentalSnapshot])

  const developmentalGuidancePreview = useMemo(
    () =>
      buildDevelopmentalGuidanceContext({
        mapTriad: mainView === 'vision_map' ? mapDevelopmentalSnapshot : null,
        recentTraces: getRecentAiActionTraces(),
        executionFlowReadings: mapExecutionFlowReadings,
      }),
    [mainView, mapDevelopmentalSnapshot, mapExecutionFlowReadings, lastCouncilResult],
  )

  const developmentalGuideChatKeyRef = useRef<string | null>(null)
  const developmentalInjectGenRef = useRef(0)
  useEffect(() => {
    if (mainView !== 'vision_map' || !developmentalGuidancePreview) return
    const key = buildDevelopmentalMapFingerprint(developmentalGuidancePreview)
    const content = developmentalGuidanceUserSummary(developmentalGuidancePreview)
    if (!content.trim()) return
    const promptId = developmentalMapVisionMapPromptId(developmentalGuidancePreview)
    if (!promptId) return
    const myGen = ++developmentalInjectGenRef.current
    void (async () => {
      const show = await checkPromptShouldShow(promptId)
      if (developmentalInjectGenRef.current !== myGen) return
      developmentalGuideChatKeyRef.current = key
      if (!show) return
      const currentFp = buildDevelopmentalMapFingerprint(developmentalGuidancePreview)
      const deferredFp = deferResurfaceFingerprintRef.current.get(promptId)
      if (deferredFp != null && deferredFp !== currentFp) {
        deferResurfaceFingerprintRef.current.delete(promptId)
        return
      }
      if (deferredFp != null && deferredFp === currentFp) {
        deferResurfaceFingerprintRef.current.delete(promptId)
      }
      const vmExtra =
        developmentalGuidancePreview.vm_entity_type && developmentalGuidancePreview.vm_entity_id
          ? {
              vm_entity_type: developmentalGuidancePreview.vm_entity_type,
              vm_entity_id: developmentalGuidancePreview.vm_entity_id,
            }
          : {}
      const promptContextTitle = formatSystemPromptContextTitle({
        mainView,
        mapNodeKind: mapDevelopmentalSnapshot?.node_kind ?? developmentalGuidancePreview.vm_entity_type ?? null,
        veType: developmentalGuidancePreview.vm_entity_type ?? null,
        nodeLabel: mapDevelopmentalSnapshot?.node_label ?? null,
        nestAggregate: mapDevelopmentalSnapshot?.node_kind === 'nest',
      })
      const qText = deriveInjectPreviewQuestionText(content)
      const qOrigin = inferInjectPreviewOrigin(content)
      setAgentThread((prev) => {
        if (prev.some((m) => m.role === 'guide' && m.promptSignal?.promptId === promptId)) {
          return prev
        }
        return [
          ...prev,
          {
            role: 'guide',
            content,
            promptContextTitle,
            promptSignal: {
              kind: 'developmental_map',
              promptId,
              summaryLine: qText.slice(0, 200),
              questionOrigin: qOrigin,
              questionText: qText,
              ...vmExtra,
            },
          },
        ]
      })
    })()
  }, [mainView, developmentalGuidancePreview, mapDevelopmentalSnapshot])

  const guideStackKey = useMemo(() => effectiveGuideStackKey(veSelection, mainView), [veSelection, mainView])
  const mapSnapForGuideStack = mainView === 'vision_map' ? mapDevelopmentalSnapshot : null
  /** Guide stack helpers use GuideThreadMessage; omit ephemeral system status rows. */
  const agentThreadForGuideStack = useMemo(
    () =>
      agentThread.filter(
        (m) => m.role !== 'system' && m.threadItemKind !== 'streaming_placeholder',
      ) as GuideThreadMessage[],
    [agentThread],
  )
  const stackedGuides = useMemo(
    () =>
      buildStackedGuidesForKey(agentThreadForGuideStack, guideStackKey, guideRowPromptId, mapSnapForGuideStack),
    [agentThreadForGuideStack, guideStackKey, guideRowPromptId, mapSnapForGuideStack],
  )
  const stackedPromptIdSet = useMemo(
    () => new Set(stackedGuides.map((g) => guideRowPromptId(g))),
    [stackedGuides, guideRowPromptId],
  )
  const firstStackedGuideIndex = useMemo(() => {
    for (let i = 0; i < agentThread.length; i++) {
      const m = agentThread[i]
      if (m?.role === 'guide' && stackedPromptIdSet.has(guideRowPromptId(m))) return i
    }
    return -1
  }, [agentThread, stackedPromptIdSet, guideRowPromptId])

  /** Prune seen ids to current stack; collapse nested UI when stack becomes empty (same node). */
  useEffect(() => {
    const valid = new Set(stackedGuides.map((g) => guideRowPromptId(g)))
    setSeenStackGuidePromptIds((prev) => {
      const next = prev.filter((id) => valid.has(id))
      return next.length === prev.length ? prev : next
    })
    if (stackedGuides.length === 0) {
      setGuideStackListOpen(false)
      setNestedStackGuidePromptId(null)
    }
  }, [stackedGuides, guideRowPromptId])

  const guideStackBarSubtitle = useMemo(
    () =>
      stackedGuides[0]?.promptContextTitle ??
      formatGuideStackBarSubtitle(guideStackKey, mapDevelopmentalSnapshot, mainView),
    [stackedGuides, guideStackKey, mapDevelopmentalSnapshot, mainView],
  )

  const guideStackKeyFingerprint = `${guideStackKey.type}:${guideStackKey.id}`

  /**
   * Session-only resurfacing guard: matches `buildDevelopmentalMapFingerprint` used on inject (preview)
   * and on map seed (`mergedCtx`). Entity/triad/evidence text changes alter the string → deferred prompt
   * does not reappear in-thread until context stabilizes; server still owns schedule via check API.
   */
  const registerDeferContextForPrompt = useCallback(
    (promptId: string) => {
      const fp = buildDevelopmentalMapFingerprint(developmentalGuidancePreview)
      deferResurfaceFingerprintRef.current.set(promptId, fp)
    },
    [developmentalGuidancePreview],
  )

  const markGuideInteracted = useCallback((_promptId: string) => {
    /* session hook reserved; prompt-signal actions already post to server */
  }, [])

  const [pendingThreadSuggestions, setPendingThreadSuggestions] = useState<PendingThreadSuggestion[]>([])
  const pendingThreadSuggestionsRef = useRef(pendingThreadSuggestions)
  pendingThreadSuggestionsRef.current = pendingThreadSuggestions

  const lastConversationSubjectKeyRef = useRef<string | null>(null)
  const lastConversationSubjectLabelRef = useRef<string>('')

  const [resolvedHandoffItemIds, setResolvedHandoffItemIds] = useState<string[]>([])
  const resolvedHandoffSet = useMemo(() => new Set(resolvedHandoffItemIds), [resolvedHandoffItemIds])
  const [handoffNotesBusyId, setHandoffNotesBusyId] = useState<string | null>(null)

  useEffect(() => {
    if (agentThread.length === 0) return
    const last = agentThread[agentThread.length - 1]!
    if (last.role === 'guide' || last.threadHandoffReview) return
    if (!shouldScrapeMessageForSuggestions(last.role, last.content)) return
    const slice = contentForSuggestionExtraction(last.role, last.content)
    const found = extractConversationSuggestions(slice)
    if (found.length === 0) return
    const sk = guideStackKeyFingerprint
    setPendingThreadSuggestions((prev) => {
      const next = [...prev]
      for (const text of found) {
        const fp = normalizeSuggestionFingerprint(text)
        if (next.some((x) => normalizeSuggestionFingerprint(x.text) === fp)) continue
        next.push({
          id: `sug-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
          text,
          subjectKey: sk,
        })
      }
      return next.length > 24 ? next.slice(-24) : next
    })
  }, [agentThread, guideStackKeyFingerprint])

  useEffect(() => {
    const key = guideStackKeyFingerprint
    const label = guideStackBarSubtitle
    const prevKey = lastConversationSubjectKeyRef.current
    const prevLabel = lastConversationSubjectLabelRef.current
    if (prevKey === null) {
      lastConversationSubjectKeyRef.current = key
      lastConversationSubjectLabelRef.current = label
      return
    }
    if (prevKey === key) {
      lastConversationSubjectLabelRef.current = label
      return
    }
    const pool = pendingThreadSuggestionsRef.current.filter((p) => p.subjectKey === prevKey)
    if (pool.length > 0) {
      const reviewId = `handoff-${Date.now()}`
      setAgentThread((t) => [
        ...t,
        {
          role: 'agent',
          agentLabel: 'Conversation handoff',
          content: `You moved away from **${prevLabel}**. Here are conversational suggestions captured from that thread — choose what to do with each.`,
          threadHandoffReview: {
            reviewId,
            forSubjectLabel: prevLabel,
            previousSubjectKey: prevKey,
            items: pool.map((p) => ({ id: p.id, text: p.text })),
          },
        },
      ])
    }
    setPendingThreadSuggestions((p) => p.filter((x) => x.subjectKey !== prevKey))
    lastConversationSubjectKeyRef.current = key
    lastConversationSubjectLabelRef.current = label
  }, [guideStackKeyFingerprint, guideStackBarSubtitle])

  useEffect(() => {
    setGuideStackListOpen(false)
    setNestedStackGuidePromptId(null)
    setSeenStackGuidePromptIds([])
    setExpandedThreadGuidePromptId(null)
    setActiveConversationalSuggestionPromptId(null)
  }, [guideStackKeyFingerprint])

  const appendEntityNotesLine = useCallback(async (previousSubjectKey: string, line: string) => {
    const ref = parseSubjectEntityRef(previousSubjectKey)
    if (!ref) return
    const path =
      ref.entity_type === 'idea'
        ? `/ideas/${ref.entity_id}`
        : ref.entity_type === 'initiative'
          ? `/initiatives/${ref.entity_id}`
          : ref.entity_type === 'project'
            ? `/projects/${ref.entity_id}`
            : `/tasks/${ref.entity_id}`
    const cur = await veApiGet<{ notes?: string | null }>(path)
    const prev = (cur.notes ?? '').trim()
    const stamp = `- [from conversation] ${line}`
    const next = prev ? `${prev}\n\n${stamp}` : stamp
    await veApiPatch(path, { notes: next })
  }, [])

  const engageGuideDiscussion = useCallback(
    (stackRowOrPromptId: string, opts?: { councilPrefill?: string }) => {
      if (stackedPromptIdSet.has(stackRowOrPromptId)) {
        setNestedStackGuidePromptId(stackRowOrPromptId)
        setGuideStackListOpen(true)
        setExpandedThreadGuidePromptId(null)
      } else {
        setExpandedThreadGuidePromptId(stackRowOrPromptId)
        setNestedStackGuidePromptId(null)
      }
      setActiveConversationalSuggestionPromptId(stackRowOrPromptId)
      setQuestion(opts?.councilPrefill ?? DISCUSS_REPLY_STARTER)
      setActiveMode('council')
      window.setTimeout(() => {
        const el = councilQuestionTextareaRef.current
        el?.focus()
        const len = el?.value.length ?? 0
        el?.setSelectionRange(len, len)
      }, 0)
    },
    [stackedPromptIdSet],
  )

  const promptSignalAttachRef = useMemo(() => {
    if (veSelection?.ideaId) return { entity_type: 'idea', entity_id: veSelection.ideaId }
    if (veSelection?.initiativeId) return { entity_type: 'initiative', entity_id: veSelection.initiativeId }
    if (veSelection?.projectId) return { entity_type: 'project', entity_id: veSelection.projectId }
    if (veSelection?.taskId) return { entity_type: 'task', entity_id: veSelection.taskId }
    return WORKSPACE_DEFER_ENTITY
  }, [veSelection])

  const runGuideDiscussFromCollapsed = useCallback(
    (stackRowId: string, questionText: string, canonicalPromptId: string) => {
      engageGuideDiscussion(stackRowId, { councilPrefill: councilPrefillForGuideQuestion(questionText) })
      hidePromptActionsForPromptId(stackRowId)
      void postPromptSignal({
        prompt_id: canonicalPromptId,
        action: 'engaged',
        entity_type: promptSignalAttachRef.entity_type,
        entity_id: promptSignalAttachRef.entity_id,
        prompt_summary: questionText.slice(0, 400),
        deferred_until: null,
      })
    },
    [engageGuideDiscussion, hidePromptActionsForPromptId, promptSignalAttachRef],
  )

  const markStackGuideSeen = useCallback((promptId: string) => {
    if (!promptId) return
    setSeenStackGuidePromptIds((prev) => (prev.includes(promptId) ? prev : [...prev, promptId]))
  }, [])

  const toggleGuideStackList = useCallback(() => {
    setGuideStackListOpen((o) => !o)
    setNestedStackGuidePromptId(null)
  }, [])

  const handleHandoffCommitNow = useCallback(
    (item: { id: string; text: string }) => {
      setResolvedHandoffItemIds((r) => [...r, item.id])
      setActiveMode('council')
      setQuestion(HANDOFF_COMMIT_STARTER)
      window.setTimeout(() => {
        const el = councilQuestionTextareaRef.current
        el?.focus()
        const len = el?.value.length ?? 0
        el?.setSelectionRange(len, len)
      }, 0)
    },
    [],
  )

  const handleHandoffSaveNotes = useCallback(
    async (item: { id: string; text: string }, previousSubjectKey: string) => {
      setHandoffNotesBusyId(item.id)
      try {
        await appendEntityNotesLine(previousSubjectKey, item.text)
        setResolvedHandoffItemIds((r) => [...r, item.id])
      } catch {
        /* non-blocking; user can copy from thread */
      } finally {
        setHandoffNotesBusyId(null)
      }
    },
    [appendEntityNotesLine],
  )

  const handleHandoffDismissItem = useCallback((item: { id: string; text: string }) => {
    setResolvedHandoffItemIds((r) => [...r, item.id])
  }, [])

  if (authLoading) {
    return (
      <div className="min-h-screen bg-slate-900 text-slate-100 flex items-center justify-center">
        <div className="text-slate-400 text-sm">Checking session…</div>
      </div>
    )
  }

  if (!currentUser) {
    return <AuthGate onLogin={handleLogin} loading={authSubmitting} />
  }

  if (consentRequired) {
    return <ConsentOnboardingGate submitting={consentSubmitting} onSubmit={handleConsentSubmit} />
  }

  return (
    <DomainProvider>
    <VisionExecutionProfileGraphDataProvider snapshot={profileGraphSnapshot}>
    <VisionExecutionGraphDataProvider>
    <VisionExecutionFocusProvider focusHostActive>
    <FocusInviteRunProvider value={handleFocusInvite}>
    <CouncilFocusBridge
      focusRef={councilVeFocusRef}
      focusBridgeActive={mainView === 'vision_execution' || mainView === 'vision_map'}
    />
    <LeaveVisionSurfacesFocusClear mainView={mainView} />
    <div className="h-dvh min-h-0 overflow-hidden bg-stone-900 text-stone-100 flex flex-col pb-[env(safe-area-inset-bottom,0px)]">
      <header className="shrink-0 border-b border-stone-700 px-3 pb-3 lg:px-6 lg:pb-4 pt-[calc(0.75rem+env(safe-area-inset-top,0px))] lg:pt-[calc(1rem+env(safe-area-inset-top,0px))] flex items-center justify-between gap-2 bg-stone-900 z-20">
        <div className="flex items-center gap-3 min-w-0">
          <ProfileAvatarControl user={currentUser} onUserUpdated={setCurrentUser} />
          <div className="flex items-center gap-4 min-w-0">
            <h1 className="text-base lg:text-xl font-semibold truncate">Zenaf · Local-first workflow cockpit</h1>
            <span className="text-xs text-stone-400 shrink-0 hidden sm:inline">{currentUser.email}</span>
          </div>
        </div>
        <nav
          className="hidden lg:flex min-w-0 items-center gap-1 overflow-x-auto"
          aria-label="Primary"
        >
          {/* Home: Living Tree */}
          <button
            type="button"
            onClick={() => setMainView('living_tree')}
            className={`px-3 py-2 lg:py-1.5 min-h-[44px] lg:min-h-0 rounded-lg text-sm font-semibold transition-colors ${
              mainView === 'living_tree'
                ? 'bg-stone-700 text-stone-100 ring-1 ring-yellow-600/35'
                : 'text-stone-200 hover:text-white border border-transparent hover:border-yellow-700/30 hover:bg-stone-800/80'
            }`}
          >
            Tree
          </button>
          {/* Core: Foundation (actors / profiles) + Vision & Execution */}
          <button
            type="button"
            onClick={() => setMainView('perspectives')}
            className={`px-3 py-2 lg:py-1.5 min-h-[44px] lg:min-h-0 rounded-lg text-sm font-semibold transition-colors ${
              mainView === 'perspectives'
                ? 'bg-stone-700 text-stone-100 ring-1 ring-yellow-600/35'
                : 'text-stone-200 hover:text-white border border-transparent hover:border-yellow-700/30 hover:bg-stone-800/80'
            }`}
          >
            Foundation
          </button>
          <button
            type="button"
            onClick={() => {
              setVeSelection(null)
              setMainView('vision_map')
            }}
            className={`px-3 py-2 lg:py-1.5 min-h-[44px] lg:min-h-0 rounded-lg text-sm font-semibold transition-colors ${
              mainView === 'vision_map'
                ? 'bg-stone-700 text-stone-100 ring-1 ring-emerald-700/35'
                : 'text-stone-200 hover:text-white border border-transparent hover:border-emerald-700/25 hover:bg-stone-800/80'
            }`}
          >
            Vision map
          </button>
          <button
            type="button"
            onClick={() => {
              setVeSelection(null)
              setMainView('vision_execution')
            }}
            className={`px-3 py-2 lg:py-1.5 min-h-[44px] lg:min-h-0 rounded-lg text-sm font-medium transition-colors ${
              mainView === 'vision_execution'
                ? 'bg-stone-700 text-stone-100'
                : 'text-stone-300 hover:text-stone-100'
            }`}
          >
            Vision (tables)
          </button>

          <div
            className="mx-2 h-6 w-px shrink-0 bg-stone-600/90"
            role="separator"
            aria-orientation="vertical"
            aria-hidden="true"
          />

          {/* Supporting: Workspace + Content */}
          <button
            type="button"
            onClick={() => setMainView('workspace')}
            className={`px-3 py-2 lg:py-1.5 min-h-[44px] lg:min-h-0 rounded-lg text-sm font-medium transition-colors ${
              mainView === 'workspace' ? 'bg-stone-700 text-stone-100' : 'text-stone-400 hover:text-stone-300'
            }`}
          >
            Workspace Organizer
          </button>
          <button
            type="button"
            onClick={() => setMainView('content')}
            className={`px-3 py-2 lg:py-1.5 min-h-[44px] lg:min-h-0 rounded-lg text-sm font-medium transition-colors ${
              mainView === 'content' ? 'bg-stone-700 text-stone-100' : 'text-stone-400 hover:text-stone-300'
            }`}
          >
            Content
          </button>

          <div
            className="mx-2 h-6 w-px shrink-0 bg-stone-600/90"
            role="separator"
            aria-orientation="vertical"
            aria-hidden="true"
          />

          {/* Utility: Settings + Logout */}
          <button
            type="button"
            onClick={() => setMainView('settings')}
            className={`px-3 py-2 lg:py-1.5 min-h-[44px] lg:min-h-0 rounded-lg text-sm font-medium transition-colors ${
              mainView === 'settings' ? 'bg-stone-700 text-stone-100' : 'text-stone-400 hover:text-stone-300'
            }`}
          >
            Settings
          </button>
          <button
            type="button"
            onClick={handleLogout}
            className="px-3 py-2 lg:py-1.5 min-h-[44px] lg:min-h-0 rounded-lg text-sm font-medium text-stone-300 hover:text-stone-100 border border-stone-700 hover:border-stone-600 transition-colors"
          >
            Logout
          </button>
        </nav>
        {/* Hamburger menu below lg — nav items don't fit a phone row, portrait or landscape */}
        <div className="lg:hidden relative shrink-0">
          <button
            type="button"
            onClick={() => setNavOpen((o) => !o)}
            className="flex items-center justify-center min-h-[44px] min-w-[44px] rounded-lg text-stone-200 hover:text-white hover:bg-stone-800/80"
            aria-label="Open menu"
            aria-expanded={navOpen}
          >
            <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden>
              <path d="M4 7h16M4 12h16M4 17h16" strokeLinecap="round" />
            </svg>
          </button>
          {navOpen && (
            <>
              <div className="fixed inset-0 z-20" onClick={() => setNavOpen(false)} aria-hidden />
              <div className="absolute right-0 top-full mt-1 w-60 rounded-xl border border-stone-700 bg-stone-900 shadow-2xl z-30 py-1.5" role="menu">
                {(
                  [
                    { view: 'living_tree', label: 'Tree' },
                    { view: 'perspectives', label: 'Foundation' },
                    { view: 'vision_map', label: 'Vision map' },
                    { view: 'vision_execution', label: 'Vision (tables)' },
                    { view: 'agent_intake', label: 'Connect' },
                    { view: 'review', label: 'Review' },
                    { view: 'signal_review', label: 'Signal review' },
                    { view: 'workspace', label: 'Workspace Organizer' },
                    { view: 'content', label: 'Content' },
                    { view: 'settings', label: 'Settings' },
                  ] as Array<{ view: MainView; label: string }>
                ).map((item) => (
                  <button
                    key={item.view}
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      if (item.view === 'vision_map' || item.view === 'vision_execution') setVeSelection(null)
                      setMainView(item.view)
                      setNavOpen(false)
                    }}
                    className={`block w-full text-left px-4 py-3 min-h-[44px] text-[15px] font-semibold ${
                      mainView === item.view ? 'text-yellow-500/90 bg-stone-800/60' : 'text-stone-200'
                    }`}
                  >
                    {item.label}
                  </button>
                ))}
                <div className="border-t border-stone-800 mt-1.5 pt-1.5">
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      setNavOpen(false)
                      handleLogout()
                    }}
                    className="block w-full text-left px-4 py-3 min-h-[44px] text-[15px] font-medium text-stone-400"
                  >
                    Logout
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </header>

      {mainView !== 'living_tree' && (
        <UniversalContextStrip
          mainView={mainView}
          currentTopic={currentTopic}
          currentFocusHasResult={currentFocusHasResult}
          activeMode={activeMode}
          useLastResultAsContext={useLastResultAsContext}
        />
      )}

      <div className="flex-1 flex flex-col lg:flex-row min-h-0 min-w-0">
        {/* Left: main content (changes by tab) */}
        {mainView === 'living_tree' ? (
          <div className="flex-1 flex flex-col min-h-0 overflow-y-auto overflow-x-hidden">
            <LivingTreeView onNavigate={(view) => setMainView(view)} />
          </div>
        ) : mainView === 'perspectives' ? (
          <div className="flex-1 flex flex-col lg:flex-row lg:min-h-0 lg:overflow-hidden bg-surface/20">
            <div className="flex-1 flex flex-col lg:min-h-0 lg:overflow-hidden min-w-0">
              <div className="shrink-0 border-b border-[color:var(--color-border)] px-4 py-3 bg-surface/40">
                <p className="text-[10px] font-medium text-warm-white/50 uppercase tracking-wide">Foundation</p>
                <h1 className="text-lg font-semibold text-warm-white mt-0.5">Actors</h1>
                <p className="text-[11px] text-warm-white/50 mt-1 max-w-3xl leading-relaxed">
                  System archetypes are read-only. <span className="text-warm-white/65">Your Storyteller is your core voice</span>
                  ; other actors are lenses and collaborators, not alternate yous.
                </p>
                {perspectivesPageError && <p className="text-flare text-xs mt-2">{perspectivesPageError}</p>}
              </div>
              <div className="flex-1 min-h-0 overflow-hidden">
                <PerspectivesView
                  agents={perspectiveAgents}
                  onAgentsChange={setPerspectiveAgents}
                  useStorage
                  selectedActorId={foundationSelectedActorId}
                  onSelectActorId={(id) => {
                    setFoundationTrainingMode(false)
                    setFoundationActorUi('browse')
                    setFoundationEditAgent(null)
                    setFoundationSelectedActorId(id)
                  }}
                  onRequestNewActor={() => {
                    setFoundationTrainingMode(false)
                    setFoundationActorUi('create_actor')
                    setFoundationEditAgent(null)
                    setFoundationSelectedActorId(null)
                  }}
                  coreProfileDisplayName={foundationCoreProfileCardTitle}
                />
              </div>
            </div>
            <aside className="w-full lg:w-[380px] lg:shrink-0 border-t lg:border-t-0 lg:border-l border-[color:var(--color-border)] bg-surface/40 lg:min-h-0 lg:max-h-none flex flex-col">
              <div className="shrink-0 p-4 border-b border-stone-700">
                <h2 className="text-base font-semibold text-stone-100">Foundation</h2>
                <p className="text-stone-400 text-xs mt-1">Detail, training, and actor editor.</p>
              </div>
              <div className="lg:flex-1 lg:basis-0 lg:min-h-0 lg:overflow-y-auto overflow-x-hidden p-3 space-y-4 lg:overscroll-contain">
                {foundationActorUi === 'create_actor' ? (
                  <AgentCreatorForm
                    onSubmit={(agent) => {
                      const withId = agent.id ? agent : createAgent(agent)
                      setPerspectiveAgents((prev) => [...prev, withId])
                      setFoundationActorUi('browse')
                      setFoundationSelectedActorId(withId.id)
                    }}
                    onCancel={() => {
                      setFoundationActorUi('browse')
                      setFoundationSelectedActorId('storyteller')
                    }}
                  />
                ) : foundationActorUi === 'edit_actor' && foundationEditAgent ? (
                  <AgentCreatorForm
                    initial={foundationEditAgent}
                    onSubmit={(agent) => {
                      setPerspectiveAgents((prev) => prev.map((a) => (a.id === agent.id ? agent : a)))
                      setFoundationActorUi('browse')
                      setFoundationEditAgent(null)
                      setFoundationSelectedActorId(agent.id)
                    }}
                    onCancel={() => {
                      setFoundationActorUi('browse')
                      setFoundationEditAgent(null)
                    }}
                  />
                ) : foundationSelectedActorId === 'storyteller' ? (
                  perspectivesLinksLoading ? (
                    <p className="text-stone-500 text-sm">Loading profile…</p>
                  ) : !brandCoreProfileId ? (
                    <div className="space-y-2">
                      <p className="text-stone-400 text-xs">
                        Create your <span className="text-stone-300">core profile</span> once — one identity for structured
                        fields, training, and how Zenaf represents you. Extra rows on the server, if any, are legacy
                        duplicates, not additional selves.
                      </p>
                      <CreateCoreProfileForm
                        onSave={(v) => void handleCreateCoreProfile(v)}
                        onCancel={() => {
                          setPerspectivesPageError(null)
                        }}
                      />
                    </div>
                  ) : (
                    (() => {
                      const storytellerActor = perspectiveAgents.find((a) => a.id === 'storyteller')
                      if (!storytellerActor) {
                        return <p className="text-stone-500 text-sm">Storyteller actor missing.</p>
                      }
                      return (
                        <>
                          <BrandStructuredProfilePanel
                            key={brandCoreProfileId}
                            profileId={brandCoreProfileId}
                            brandActor={storytellerActor}
                            displayName={foundationCoreProfileCardTitle.trim() || storytellerActor.name || 'Storyteller'}
                            apiGet={veApiGet}
                            onTrainWithZenaf={() => {
                              handleEnterFoundationTrainingMode()
                            }}
                            onWorkout={() => handleStartWorkout(storytellerActor)}
                          />
                          <AspirationsFoundationPanel apiGet={veApiGet} apiPatch={veApiPatch} apiPost={veApiPost} />
                        </>
                      )
                    })()
                  )
                ) : foundationSelectedAgent ? (
                  <AgentDetailPanel
                    agent={foundationSelectedAgent}
                    readOnlyActions={isFoundationSystemActor(foundationSelectedAgent)}
                    onEdit={() => {
                      if (!isUserDefined(foundationSelectedAgent)) return
                      setFoundationEditAgent(foundationSelectedAgent)
                      setFoundationActorUi('edit_actor')
                    }}
                    onChat={() => {}}
                    onUseInWorkspace={() => {}}
                    onDelete={
                      isUserDefined(foundationSelectedAgent)
                        ? (ag) => {
                            if (!window.confirm(`Delete the actor “${ag.name}”? This cannot be undone.`)) return
                            setPerspectiveAgents((prev) => prev.filter((a) => a.id !== ag.id))
                            setFoundationSelectedActorId('storyteller')
                          }
                        : undefined
                    }
                    isUserDefined={isUserDefined(foundationSelectedAgent)}
                    showWorkout={isUserDefined(foundationSelectedAgent)}
                    onStartWorkout={
                      isUserDefined(foundationSelectedAgent)
                        ? () => handleStartWorkout(foundationSelectedAgent)
                        : undefined
                    }
                    footerExtra={
                      isUserDefined(foundationSelectedAgent) ? (
                        <div className="p-3 border-t border-[color:var(--color-border)]">
                          <InfluencesLinksSection
                            sourceKind="perspective"
                            sourceId={foundationSelectedAgent.id}
                            coreProfiles={perspectiveInfluenceLinkLists.coreProfiles}
                            perspectiveAgents={perspectiveAgents.map((a) => ({ id: a.id, label: a.name }))}
                            canonicalCoreProfileId={brandCoreProfileId}
                          />
                        </div>
                      ) : undefined
                    }
                  />
                ) : (
                  <p className="text-stone-500 text-sm">Select an actor from Foundation.</p>
                )}
              </div>
            </aside>
          </div>
        ) : mainView === 'content' ? (
          <div className="flex-1 flex flex-col min-h-0">
            <ContentFrontDoor apiBase={API_BASE} />
          </div>
        ) : mainView === 'agent_intake' ? (
          <div className="flex-1 flex flex-col min-h-0">
            <AgentIntakeView onOpenSettings={() => setMainView('settings')} />
          </div>
        ) : mainView === 'review' ? (
          <div className="flex-1 flex flex-col min-h-0">
            <ReviewView />
          </div>
        ) : mainView === 'signal_review' ? (
          <div className="flex-1 flex flex-col min-h-0 overflow-y-auto">
            <SignalReviewView />
          </div>
        ) : mainView === 'settings' ? (
          <SettingsView
            user={currentUser}
            onLogout={handleLogout}
            onUserUpdated={setCurrentUser}
          />
        ) : mainView === 'vision_map' ? (
          <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
            <VisionMapView
              onOpenOperatorMode={() => {
                setMainView('vision_execution')
              }}
              onOpenVeRadar={handleOpenVeRadar}
              councilQuestionDraft={question}
              onVisionMapCouncilInteraction={handleVisionMapCouncilInteraction}
              onDevelopmentalSignalsChange={setMapDevelopmentalSnapshot}
              onCouncilEntityBundleSnapshot={(bundle) => {
                councilVeEntityBundleRef.current = bundle
              }}
              onMapEntitySelectionChange={onMapEntitySelectionChange}
              layoutPersistenceContext={currentUser ? String(currentUser.id) : 'anonymous'}
            />
          </div>
        ) : mainView === 'vision_execution' ? (
          <div className="flex-1 flex flex-col min-h-0 overflow-auto">
            <VisionExecutionView
              initialSelection={stableVeSelectionForExecutionView}
              councilIdeaLabelsRef={councilIdeaLabelsRef}
              councilVeEntityBundleRef={councilVeEntityBundleRef}
              onCouncilIdeaLiveLabelsUpdated={bumpCouncilIdeaLiveLabelsSeq}
              focusTabRequest={veFocusTabRequest}
              onFocusTabRequestConsumed={consumeVeFocusTabRequest}
              onVeSelectionChange={setVeSelection}
              recognitionUserId={currentUser?.id ?? null}
              councilServerWriteNonce={councilVeServerWriteNonce}
              radarScrollBucketRequest={veRadarScrollBucket}
              onRadarScrollBucketConsumed={clearVeRadarScrollBucket}
            />
          </div>
        ) : (
          /* Workspace Organizer */
          <main className="flex-1 min-w-0 min-h-0 overflow-auto p-4 lg:p-6 max-w-3xl mx-auto space-y-10">
            {error && (
              <div className="rounded-lg bg-red-900/30 border border-red-700 text-red-200 text-sm p-3">
                {error}
              </div>
            )}
            {workspaceTraceOutcomeBanner && (
              <div
                className="rounded-lg border border-emerald-800/45 bg-emerald-950/25 text-emerald-100/90 text-xs p-3 leading-relaxed"
                role="status"
              >
                {workspaceTraceOutcomeBanner}
              </div>
            )}
            {/* ----- Workspace Organizer: vertical workflow (collapsible) ----- */}
            <section>
          <div className="flex items-center justify-between mb-1">
            <h2 className="text-xl font-semibold text-slate-100">Workspace Organizer</h2>
            <button
              type="button"
              onClick={() => setWorkspaceCollapsed((v) => !v)}
              className="text-xs text-slate-400 hover:text-slate-200 px-2 py-1 rounded-lg border border-slate-600 bg-slate-800"
            >
              {workspaceCollapsed ? 'Show' : 'Hide'}
            </button>
          </div>
          <p className="text-slate-400 text-sm mb-6">
            Select a folder, get suggestions, edit the list, run simulation, then accept or save the plan.
          </p>

          {!workspaceCollapsed && (
          <div className="rounded-xl border border-slate-600 bg-slate-800/50 p-5 space-y-6">
            {/* 1. Selected folder */}
            <div>
              <h3 className="text-sm font-medium text-slate-300 mb-2">Selected folder</h3>
              <FolderSelector
                value={folderPath}
                onChange={setFolderPath}
                recentFolders={recentFolders}
                onUseCurrentFocus={useResultAsFocus}
                onClear={() => setFolderPath('')}
                currentFocusPath={currentFocusPath}
                showUseCurrentFocus={false}
                apiBase={API_BASE}
              />
              <div className="mt-2">
                <button
                  type="button"
                  onClick={getSuggestions}
                  disabled={loading || !(folderPath || lastFolderPath).trim()}
                  className="px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white text-sm font-medium"
                >
                  {loading && (workflowRunningStep === 'analyze' || workflowRunningStep === 'recommend') ? 'Getting suggestions…' : 'Get suggestions'}
                </button>
              </div>
            </div>

            {/* 2. Suggested folders */}
            <div>
              <h3 className="text-sm font-medium text-slate-300 mb-2">Suggested folders</h3>
              {lastRecommendResult && !lastRecommendResult.error ? (
                <>
                  <SuggestedFoldersEditor
                    suggested={lastRecommendResult.suggested_child_folders ?? []}
                    rejected={rejectedRecommendations}
                    onReject={rejectRecommendation}
                    customFolders={customRecommendations}
                    onAddCustom={addCustomRecommendation}
                    onRemoveCustom={removeCustomRecommendation}
                    onRefineCategories={runFolderAdvisor}
                    folderAdvisorLoading={folderAdvisorLoading}
                    highlightedFolders={folderHighlightForEditor}
                  />
                  {lastRecommendResult.notes && lastRecommendResult.notes.length > 0 && (
                    <p className="mt-2 text-slate-500 text-xs">Notes: {lastRecommendResult.notes.join(' ')}</p>
                  )}
                </>
              ) : (
                <p className="text-slate-500 text-sm">Select a folder and click Get suggestions to see recommended folders.</p>
              )}
              {lastRecommendResult?.error && <p className="text-red-300 text-sm mt-2">{lastRecommendResult.error}</p>}
            </div>

            {/* 3. Preview file moves */}
            <div>
              <h3 className="text-sm font-medium text-slate-300 mb-2">Preview file moves</h3>
              {lastSimulateResult ? (
                <>
                  <p className="text-slate-500 text-sm mb-2">Edit folders above and re-run to refresh. Use dropdowns to override moves.</p>
                  <SimulateTreeGraphical
                    data={lastSimulateResult}
                    editable
                    targetFolders={effectiveSimulateTargetFolders}
                    overrides={filteredSimulationOverrides}
                    onOverride={(itemName, folder) => {
                      setSimulationOverrides((prev) => ({ ...prev, [itemName]: folder }))
                      const w = workspaceOutcomeTargetRef.current
                      if (w?.action_intent === WORKSPACE_ACTION_INTENTS.simulate) {
                        try {
                          recordWorkspaceTraceUserOutcome(w.trace, 'edited')
                        } catch {
                          /* ignore */
                        }
                        postWorkspaceLearningFromRef(w, 'edited')
                      }
                    }}
                  />
                  <button
                    type="button"
                    onClick={() => runMode('simulate', lastFolderPath, approvedFolders.length > 0 ? { suggested_folders: approvedFolders } : undefined)}
                    disabled={workflowRunningStep === 'simulate'}
                    className="mt-2 px-4 py-2 rounded-lg border border-slate-600 bg-slate-800 text-slate-300 text-sm hover:bg-slate-700 disabled:opacity-50"
                  >
                    Re-run simulation
                  </button>
                </>
              ) : (
                <>
                  <p className="text-slate-500 text-sm mb-2">Run simulation to preview moves with your approved folder list.</p>
                  <button
                    type="button"
                    onClick={() => runMode('simulate', lastFolderPath, approvedFolders.length > 0 ? { suggested_folders: approvedFolders } : undefined)}
                    disabled={workflowRunningStep === 'simulate' || !lastRecommendResult || Boolean(lastRecommendResult.error)}
                    className="px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white text-sm font-medium"
                  >
                    Run simulation
                  </button>
                </>
              )}
            </div>

            {/* 4. Final actions */}
            <div>
              <h3 className="text-sm font-medium text-slate-300 mb-2">Final actions</h3>
              {lastSimulateResult ? (
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium"
                    onClick={() => { /* TODO: execute plan */ alert('Accept plan: execute moves (not implemented yet).') }}
                  >
                    Accept plan
                  </button>
                  <button
                    type="button"
                    className="px-4 py-2 rounded-lg border border-slate-500 bg-slate-800 text-slate-300 text-sm hover:bg-slate-700"
                    onClick={() => { /* TODO: persist plan */ alert('Save for later (not implemented yet).') }}
                  >
                    Save for later
                  </button>
                </div>
              ) : (
                <p className="text-slate-500 text-sm">Run simulation above, then accept or save the plan.</p>
              )}
            </div>
          </div>
          )}

          </section>

          {/* Clinic Intake: email/fax ingestion → queue (read-only display) */}
          <section className="mt-10 pt-8 border-t border-slate-700">
            <h2 className="text-lg font-semibold text-slate-100 mb-2">Clinic Intake</h2>
            <p className="text-slate-400 text-sm mb-4">Ingest email or fax into the queue. Raw content is classified and PHI-redacted; only sanitized summary is stored. View queue below.</p>
            <div className="rounded-xl border border-slate-600 bg-slate-800/50 mb-6 overflow-hidden">
              <button
                type="button"
                onClick={() => setEmailConnectionExpanded((e) => !e)}
                className="w-full flex items-center justify-between gap-2 px-4 py-3 text-left hover:bg-slate-700/40 transition-colors"
                aria-expanded={emailConnectionExpanded}
              >
                <span className="text-sm font-medium text-slate-200">Email connection</span>
                <span className="text-slate-500 text-xs truncate flex-1 min-w-0">
                  {gmailOAuthEmail ? `Connected as ${gmailOAuthEmail}` : 'Configure connection'}
                </span>
                <span className="text-slate-400 text-xs flex-shrink-0" aria-hidden>{emailConnectionExpanded ? '▼' : '▶'}</span>
              </button>
              {emailConnectionExpanded && (
              <div className="px-4 pb-4 pt-0">
              <p className="text-slate-500 text-xs mb-3">Add IMAP credentials so the system can connect and mirror your mailbox (read-only). Saved locally; use Poll email after saving. If you see 404, start the API: run <strong>open-cockpit.bat</strong> from the Zenaf folder (or in a terminal from repo root: <code className="text-slate-400">uvicorn api.main:app --reload --host 127.0.0.1 --port 8010</code>).</p>
              <p className="text-slate-500 text-xs mb-3">
                <span className="text-slate-400">Identity vs mailbox access:</span> App login is for <em>who you are</em> only. Gmail connection below uses <strong>Google OAuth</strong> (mailbox access, no app password). Or use the IMAP form as fallback.
              </p>
              {gmailOAuthError && (
                <div className="mb-3 p-3 rounded-lg bg-amber-900/30 border border-amber-600">
                  <p className="text-amber-200 text-xs font-medium mb-1">Gmail OAuth error</p>
                  <p className="text-amber-100/90 text-xs break-all">{gmailOAuthError}</p>
                  <p className="text-slate-400 text-xs mt-2">Check: (1) In Google Cloud, add redirect URI exactly <code className="text-slate-300">http://127.0.0.1:8010/intake/oauth/google/callback</code> (2) OAuth consent screen → add your Gmail as a test user.</p>
                </div>
              )}
              {!gmailOAuthConfigured && (
                <div className="mb-3 p-3 rounded-lg bg-slate-900/80 border border-slate-600">
                  <p className="text-slate-300 text-xs mb-2">Add Google OAuth credentials so Connect Gmail works. Get them from Google Cloud Console → Credentials → OAuth client ID (Web application).</p>
                  <p className="text-slate-400 text-xs mb-2">In the OAuth client, add this <strong>exact</strong> redirect URI: <code className="text-slate-300 break-all">{API_BASE}/intake/oauth/google/callback</code></p>
                  {gmailOAuthConfigPath && <p className="text-slate-500 text-xs mb-2">Credentials are saved to: <code className="text-slate-400 break-all">{gmailOAuthConfigPath}</code></p>}
                  <div className="grid gap-2 sm:grid-cols-2 mb-2">
                    <div>
                      <label className="block text-slate-400 text-xs mb-0.5">Client ID</label>
                      <input
                        type="text"
                        value={googleClientId}
                        onChange={(e) => setGoogleClientId(e.target.value)}
                        placeholder="xxx.apps.googleusercontent.com"
                        className="w-full px-2 py-1.5 rounded bg-slate-800 border border-slate-600 text-slate-100 text-xs"
                      />
                    </div>
                    <div>
                      <label className="block text-slate-400 text-xs mb-0.5">Client secret</label>
                      <input
                        type="password"
                        value={googleClientSecret}
                        onChange={(e) => setGoogleClientSecret(e.target.value)}
                        placeholder="GOCSPX-..."
                        className="w-full px-2 py-1.5 rounded bg-slate-800 border border-slate-600 text-slate-100 text-xs"
                      />
                    </div>
                  </div>
                  <button type="button" onClick={saveGoogleOAuthConfig} className="px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium">
                    Save OAuth credentials
                  </button>
                  {googleOAuthConfigSaved && <span className={`ml-2 text-xs ${googleOAuthConfigSaved.startsWith('Saved') ? 'text-emerald-400' : 'text-amber-400'}`}>{googleOAuthConfigSaved}</span>}
                </div>
              )}
              <div className="mb-3 flex flex-wrap items-center gap-2">
                {gmailOAuthEmail ? (
                  <span className="text-emerald-400 text-sm">Connected as {gmailOAuthEmail}. Use Poll email to sync.</span>
                ) : gmailOAuthConfigured ? (
                  <a
                    href={`${API_BASE}/intake/oauth/google/start`}
                    className="inline-flex items-center px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium"
                  >
                    Connect Gmail (no app password)
                  </a>
                ) : null}
              </div>
              <p className="text-slate-500 text-xs mb-3">Or use IMAP + app password (fallback):</p>
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className="block text-slate-400 text-xs mb-1">Host</label>
                  <input
                    type="text"
                    value={imapHost}
                    onChange={(e) => setImapHost(e.target.value)}
                    placeholder="imap.gmail.com"
                    className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm placeholder-slate-500"
                  />
                  <p className="text-slate-500 text-xs mt-0.5">Gmail: use imap.gmail.com (not accounts.google.com)</p>
                </div>
                <div>
                  <label className="block text-slate-400 text-xs mb-1">User (email)</label>
                  <input
                    type="text"
                    value={imapUser}
                    onChange={(e) => setImapUser(e.target.value)}
                    placeholder="you@example.com"
                    className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm placeholder-slate-500"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 text-xs mb-1">Password (app password)</label>
                  <input
                    type="password"
                    value={imapPassword}
                    onChange={(e) => setImapPassword(e.target.value)}
                    placeholder="Gmail: use an App Password from your Google account"
                    className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm placeholder-slate-500"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 text-xs mb-1">Mailbox</label>
                  <input
                    type="text"
                    value={imapMailbox}
                    onChange={(e) => setImapMailbox(e.target.value)}
                    placeholder="INBOX"
                    className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm placeholder-slate-500"
                  />
                </div>
                <div className="sm:col-span-2">
                  <label className="block text-slate-400 text-xs mb-1">Label (optional, e.g. Main)</label>
                  <input
                    type="text"
                    value={imapLabel}
                    onChange={(e) => setImapLabel(e.target.value)}
                    placeholder="Shown on queue items"
                    className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm placeholder-slate-500"
                  />
                </div>
              </div>
              <div className="mt-3 flex items-center gap-2">
                <button
                  type="button"
                  onClick={saveIntakeEmailConfig}
                  className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium"
                >
                  Save connection
                </button>
                {imapConfigSaved && (
                  <span className={imapConfigSaved.startsWith('Saved') ? 'text-emerald-400 text-sm' : 'text-amber-400 text-sm'}>
                    {imapConfigSaved}
                  </span>
                )}
              </div>
              </div>
              )}
            </div>
            <div
              className="mt-6 rounded-xl border border-slate-600 bg-slate-800/50 flex flex-col overflow-hidden"
              style={{ height: intakeQueuePanelHeight, minHeight: 200, maxHeight: '80vh' }}
            >
              <div className="flex-1 min-h-0 flex flex-col p-4 pt-2">
              <div className="flex items-center justify-between mb-2 flex-wrap gap-2 flex-shrink-0">
                <div>
                  <h3 className="text-sm font-medium text-slate-200">Ordering queue</h3>
                  <p className="text-slate-500 text-[10px] mt-0.5">
                    Lanes are derived from classification (first-pass taxonomy). Classifier confidence is match strength—not certainty.
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={pollEmailIntake}
                    disabled={intakeLoading}
                    className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-xs font-medium"
                  >
                    Poll email
                  </button>
                  <button
                    type="button"
                    onClick={fetchIntakeQueue}
                    disabled={intakeLoading}
                    className="px-3 py-1.5 rounded-lg bg-slate-600 hover:bg-slate-500 disabled:opacity-50 text-slate-200 text-xs font-medium"
                  >
                    {intakeLoading ? 'Loading…' : 'Refresh'}
                  </button>
                </div>
              </div>
              {intakePollResult && (
                <div className="text-slate-400 text-xs mb-2 space-y-0.5">
                  {'detail' in intakePollResult ? (
                    <p>Poll: {intakePollResult.detail}</p>
                  ) : (
                    <>
                      <p>
                        {intakePollResult.added} added, {intakePollResult.skipped_duplicates} skipped (duplicate).
                      </p>
                      {intakePollResult.errors.length > 0 && (
                        <p className="text-amber-400/90">
                          {intakePollResult.errors.length} error(s): {intakePollResult.errors.slice(0, 2).join('; ')}
                          {intakePollResult.errors.length > 2 ? ` (+${intakePollResult.errors.length - 2} more)` : ''}
                        </p>
                      )}
                    </>
                  )}
                </div>
              )}
              <div className="flex flex-wrap items-center gap-2 mb-2">
                <select
                  value={intakeQueueStatusFilter}
                  onChange={(e) => setIntakeQueueStatusFilter(e.target.value)}
                  className="rounded border border-slate-600 bg-slate-800 text-slate-200 text-xs py-1.5 px-2"
                  aria-label="Filter by status"
                >
                  <option value="">All statuses</option>
                  <option value="new">New</option>
                  <option value="reviewed">Reviewed</option>
                  <option value="done">Done</option>
                </select>
                <input
                  type="text"
                  placeholder="Search subject/summary..."
                  value={intakeQueueSearch}
                  onChange={(e) => setIntakeQueueSearch(e.target.value)}
                  className="rounded border border-slate-600 bg-slate-800 text-slate-200 text-xs py-1.5 px-2 w-40"
                  aria-label="Search queue"
                />
                <select
                  value={intakeQueueSort}
                  onChange={(e) => setIntakeQueueSort(e.target.value as 'created_desc' | 'created_asc')}
                  className="rounded border border-slate-600 bg-slate-800 text-slate-200 text-xs py-1.5 px-2"
                  aria-label="Sort order"
                >
                  <option value="created_desc">Newest first</option>
                  <option value="created_asc">Oldest first</option>
                </select>
                <label className="flex items-center gap-1.5 text-slate-400 text-xs cursor-pointer">
                  <input type="checkbox" checked={intakeQueueShowArchived} onChange={(e) => setIntakeQueueShowArchived(e.target.checked)} className="rounded" />
                  Show archived
                </label>
              </div>
              {intakeQueue.length === 0 ? (
                <p className="text-slate-500 text-sm">No queue items. Use Poll email to sync, then Refresh.</p>
              ) : (
                <div className="flex-1 min-h-0 overflow-x-auto overflow-y-auto flex gap-2 pb-2">
                  {INTAKE_LANE_ORDER.map((laneId) => {
                    const effectiveLane = (item: IntakeQueueItem) => (item.lane_override || item.lane || 'waiting_fyi')
                    const laneItems = intakeQueue.filter((item) => effectiveLane(item) === laneId)
                    const label = INTAKE_LANE_LABELS[laneId] ?? laneId
                    const expanded = intakeLaneExpanded[laneId] !== false
                    const toggleLane = () => setIntakeLaneExpanded((prev) => ({ ...prev, [laneId]: !expanded }))
                    return (
                      <div
                        key={laneId}
                        className={`flex-shrink-0 flex flex-col rounded-lg border border-slate-600 bg-slate-800/40 ${expanded ? 'w-full lg:w-[450px] lg:min-w-[450px]' : 'w-[4.5rem] min-w-[4.5rem]'}`}
                      >
                        <button
                          type="button"
                          onClick={toggleLane}
                          className={`flex-shrink-0 flex items-center gap-1.5 border-b border-slate-600 hover:bg-slate-700/50 rounded-t-lg text-left w-full ${expanded ? 'px-2 py-1.5' : 'flex-col px-1.5 py-2 min-h-[4rem]'}`}
                          aria-expanded={expanded}
                          aria-label={expanded ? `Collapse ${label}` : `Expand ${label} (${laneItems.length} items)`}
                        >
                          <span className="flex-shrink-0 w-4 flex items-center justify-center text-slate-400 text-xs" aria-hidden>
                            {expanded ? '◀' : '▶'}
                          </span>
                          {expanded ? (
                            <>
                              <span className="text-slate-300 text-xs font-medium truncate">{label}</span>
                              <span className="ml-auto text-slate-500 text-xs flex-shrink-0">({laneItems.length})</span>
                            </>
                          ) : (
                            <span className="flex flex-col items-center justify-center gap-0.5 min-w-0 flex-1">
                              <span className="text-slate-300 text-xs font-semibold uppercase tracking-wide truncate w-full text-center">
                                {INTAKE_LANE_SHORT[laneId] ?? label}
                              </span>
                              <span className="text-amber-400 font-bold text-base tabular-nums">
                                {laneItems.length}
                              </span>
                            </span>
                          )}
                        </button>
                        {expanded && (
                        <ul className="flex-1 min-h-0 overflow-y-auto space-y-2 p-2">
                          {laneItems.map((item) => (
                            <li key={item.id} className="rounded-lg border border-slate-600 bg-slate-900/60 p-2.5 text-sm">
                              <div className="flex items-start justify-between gap-2 mb-1">
                                <button
                                  type="button"
                                  onClick={() => {
                                    setIntakeDetailItemId(item.id)
                                    // Reset create-task form when switching items and prefill from this item
                                    setCreateTaskError(null)
                                    setCreateTaskResult(null)
                                    setCreateTaskLoadingId(null)
                                    setCreateTaskTitle(item.subject || '')
                                    setCreateTaskSummary(item.summary || '')
                                    setCreateTaskNotes('')
                                    setIntakeLaneOverrideDraft(item.lane_override ?? '')
                                    setIntakeCorrectionNoteDraft('')
                                    setIntakeLaneSaveError(null)
                                    fetchIntakeJudgment(item.id)
                                  }}
                                  className="text-left flex-1 min-w-0"
                                >
                                  <p className="text-slate-200 text-base font-semibold mb-1.5 truncate" title={item.subject || ''}>
                                    {item.subject || '(No subject)'}
                                  </p>
                                </button>
                                <span className="flex items-center gap-1 flex-shrink-0">
                                  <select
                                    value={item.status ?? 'new'}
                                    onChange={(e) => updateIntakeItemStatus(item.id, e.target.value)}
                                    className="rounded border border-slate-600 bg-slate-800 text-slate-200 text-[10px] py-0.5 px-1"
                                  >
                                    <option value="new">New</option>
                                    <option value="reviewed">Reviewed</option>
                                    <option value="done">Done</option>
                                  </select>
                                  <button
                                    type="button"
                                    onClick={(e) => { e.stopPropagation(); archiveIntakeItem(item.id) }}
                                    className="text-slate-500 hover:text-slate-300 text-[10px]"
                                    title="Hide in Zenaf queue only (no mailbox change)"
                                  >
                                    Archive
                                  </button>
                                </span>
                              </div>
                              <p className="text-slate-500 text-[10px] mb-0.5">
                                {[item.source_label, intakeQueueRelativeTime(item.created_at)].filter(Boolean).join(' · ')}
                              </p>
                              <p className="text-slate-300 text-[11px] mb-0.5 line-clamp-2">{item.summary || '—'}</p>
                              <p className="text-slate-500 text-[10px]">Suggested: {item.suggested_action}</p>
                              {(item.notes || item.assigned_to) && (
                                <p className="text-slate-500 text-[10px] mt-0.5">
                                  {item.assigned_to && <span>Assigned: {item.assigned_to}</span>}
                                  {item.assigned_to && item.notes && ' · '}
                                  {item.notes && <span>Notes: {item.notes}</span>}
                                </p>
                              )}
                              <div className="mt-1.5 pt-1.5 border-t border-slate-600">
                                <button
                                  type="button"
                                  onClick={() => {
                                    if (intakeWhyItemId === item.id) {
                                      setIntakeWhyItemId(null)
                                    } else {
                                      setIntakeWhyItemId(item.id)
                                      fetchIntakeJudgment(item.id)
                                    }
                                  }}
                                  className="text-slate-500 hover:text-slate-300 text-[10px]"
                                >
                                  {intakeWhyItemId === item.id ? 'Hide Why' : 'Why?'}
                                </button>
                                {intakeWhyItemId === item.id && intakeJudgmentLoadingId === item.id && (
                                  <p className="text-slate-500 text-[10px] mt-1">Loading…</p>
                                )}
                                {intakeWhyItemId === item.id && intakeJudgmentChain?.item_id === item.id && !intakeJudgmentLoadingId && (
                                  <div className="mt-1.5 rounded bg-slate-800/80 p-2 text-[10px] space-y-1.5 max-h-48 overflow-y-auto">
                                    <p className="text-slate-500 border-b border-slate-600 pb-1 mb-1">
                                      Category: {item.category} · Priority: {item.priority} · Confidence: {((item.confidence_display ?? 'low') as string).replace(/^./, (c) => c.toUpperCase())}
                                      {item.has_phi && ' · PHI'}
                                    </p>
                                    {intakeJudgmentError && (
                                      <p className="text-amber-300/90">{intakeJudgmentError}</p>
                                    )}
                                    {!intakeJudgmentError && intakeJudgmentChain.chain.length === 0 && (
                                      <p className="text-slate-500">No judgment record for this item.</p>
                                    )}
                                    {!intakeJudgmentError && intakeJudgmentChain.chain.length > 0 && intakeJudgmentChain.chain.map((rec, idx) => (
                                      <div key={rec.id} className="space-y-0.5">
                                        <span className="text-slate-400 font-medium">
                                          {idx === 0 && intakeJudgmentChain.chain.length > 1 ? 'Original' : intakeJudgmentChain.chain.length > 1 ? 'Correction' : 'Judgment'}
                                          {rec.proposed_action?.lane != null && rec.proposed_action.lane !== ''
                                            ? ` → ${String(rec.proposed_action.lane)}`
                                            : null}
                                        </span>
                                        {rec.correction_note && (
                                          <p className="text-amber-300/90">Note: {rec.correction_note}</p>
                                        )}
                                        {(rec.signal_codes?.length ?? 0) > 0 && (
                                          <p><span className="text-slate-500">Signals:</span> {(rec.signal_codes ?? []).join(', ')}</p>
                                        )}
                                        {(rec.interpretation_codes?.length ?? 0) > 0 && (
                                          <p><span className="text-slate-500">Interpretation:</span> {(rec.interpretation_codes ?? []).join(', ')}</p>
                                        )}
                                        {(rec.policy_codes?.length ?? 0) > 0 && (
                                          <p><span className="text-slate-500">Policy:</span> {(rec.policy_codes ?? []).join(', ')}</p>
                                        )}
                                        {rec.observation_ref && (
                                          <p className="text-slate-500">
                                            Evidence: subject_preview &apos;{String(rec.observation_ref.subject_preview ?? '').slice(0, 40)}{(rec.observation_ref.subject_preview?.length ?? 0) > 40 ? '…' : ''}&apos;, body_length={rec.observation_ref.body_length ?? 0}
                                            {Array.isArray(rec.observation_ref.matched_signals) && rec.observation_ref.matched_signals.length > 0
                                              ? `, matched: ${rec.observation_ref.matched_signals.join(', ')}` : ''}
                                          </p>
                                        )}
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </div>
                            </li>
                          ))}
                        </ul>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
              </div>
              <div
                role="separator"
                aria-label="Resize ordering queue"
                className="h-2 flex-shrink-0 cursor-s-resize border-t border-slate-600 bg-slate-700/40 hover:bg-slate-600/50 flex items-center justify-center touch-none"
                onMouseDown={(e) => {
                  if (e.button !== 0) return
                  e.preventDefault()
                  intakeQueueResizeRef.current = { startY: e.clientY, startH: intakeQueuePanelHeight }
                }}
              >
                <span className="text-slate-500 text-xs select-none">⋮</span>
              </div>
            </div>

            {intakeDetailItemId && (() => {
              const detailItem = intakeQueue.find((i) => i.id === intakeDetailItemId)
              if (!detailItem) return null
              const effectiveLane = detailItem.lane_override || detailItem.lane || 'waiting_fyi'
              return (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={() => setIntakeDetailItemId(null)}>
                  <div className="bg-slate-800 border border-slate-600 rounded-xl shadow-xl max-w-lg w-full max-h-[90vh] overflow-hidden flex flex-col" onClick={(e) => e.stopPropagation()}>
                    <div className="flex-shrink-0 flex items-center justify-between p-4 border-b border-slate-600">
                      <h3 className="text-sm font-medium text-slate-200">Queue item</h3>
                      <button type="button" onClick={() => setIntakeDetailItemId(null)} className="text-slate-400 hover:text-slate-200">Close</button>
                    </div>
                    <div className="flex-1 overflow-y-auto p-4 space-y-3 text-sm">
                      <div>
                        <p className="text-slate-500 text-xs uppercase tracking-wide mb-0.5">Subject</p>
                        <p className="text-slate-200 break-words">{detailItem.subject || '(No subject)'}</p>
                      </div>
                      <div className="grid grid-cols-1 lg:grid-cols-2 gap-2 text-xs">
                        <div><span className="text-slate-500">Source</span> {detailItem.source_label || '—'}</div>
                        <div><span className="text-slate-500">Received</span> {detailItem.created_at ? intakeQueueRelativeTime(detailItem.created_at) : '—'}</div>
                        <div><span className="text-slate-500">Category</span> {detailItem.category}</div>
                        <div><span className="text-slate-500">Priority</span> {detailItem.priority}</div>
                        <div><span className="text-slate-500">Lane</span> {INTAKE_LANE_LABELS[effectiveLane] ?? effectiveLane}{detailItem.lane_override ? ' (overridden)' : ''}</div>
                        <div><span className="text-slate-500">Status</span> {detailItem.status ?? 'new'}</div>
                      </div>
                      <div>
                        <p className="text-slate-500 text-xs uppercase tracking-wide mb-0.5">Summary / preview</p>
                        <p className="text-slate-300 whitespace-pre-wrap break-words">{detailItem.summary || '—'}</p>
                      </div>
                      <div>
                        <p className="text-slate-500 text-xs uppercase tracking-wide mb-0.5">Suggested action</p>
                        <p className="text-slate-300">{detailItem.suggested_action || '—'}</p>
                      </div>
                      {(detailItem.notes || detailItem.assigned_to) && (
                        <div className="text-xs">
                          {detailItem.assigned_to && <p><span className="text-slate-500">Assigned to</span> {detailItem.assigned_to}</p>}
                          {detailItem.notes && <p><span className="text-slate-500">Notes</span> {detailItem.notes}</p>}
                        </div>
                      )}
                      <div>
                        <p className="text-slate-500 text-xs uppercase tracking-wide mb-1">Why? (judgment)</p>
                        {intakeJudgmentChain?.item_id === intakeDetailItemId && !intakeJudgmentLoadingId && (
                          <>
                            {intakeJudgmentError && <p className="text-amber-300/90 text-xs">{intakeJudgmentError}</p>}
                            {!intakeJudgmentError && intakeJudgmentChain.chain.length === 0 && <p className="text-slate-500 text-xs">No judgment record.</p>}
                            {!intakeJudgmentError && intakeJudgmentChain.chain.length > 0 && (
                              <div className="space-y-2 text-xs">
                                {intakeJudgmentChain.chain.map((rec, idx) => (
                                  <div key={rec.id} className="rounded bg-slate-900/60 p-2">
                                    <span className="text-slate-400 font-medium">{idx === 0 && intakeJudgmentChain.chain.length > 1 ? 'Original' : intakeJudgmentChain.chain.length > 1 ? 'Correction' : 'Judgment'}{rec.proposed_action?.lane ? ` → ${String(rec.proposed_action.lane)}` : ''}</span>
                                    {rec.correction_note && <p className="text-amber-300/90 mt-0.5">Note: {rec.correction_note}</p>}
                                    {(rec.signal_codes?.length ?? 0) > 0 && <p className="text-slate-500 mt-0.5">Signals: {(rec.signal_codes ?? []).join(', ')}</p>}
                                    {(rec.interpretation_codes?.length ?? 0) > 0 && <p className="text-slate-500">Interpretation: {(rec.interpretation_codes ?? []).join(', ')}</p>}
                                    {(rec.policy_codes?.length ?? 0) > 0 && <p className="text-slate-500">Policy: {(rec.policy_codes ?? []).join(', ')}</p>}
                                    {rec.observation_ref && <p className="text-slate-500">Evidence: subject_preview &apos;{String(rec.observation_ref.subject_preview ?? '').slice(0, 50)}…&apos;, body_length={rec.observation_ref.body_length ?? 0}</p>}
                                  </div>
                                ))}
                              </div>
                            )}
                          </>
                        )}
                        {intakeJudgmentLoadingId === intakeDetailItemId && <p className="text-slate-500 text-xs">Loading…</p>}
                      </div>
                      <div className="pt-2 border-t border-slate-600">
                        <p className="text-slate-500 text-xs uppercase tracking-wide mb-2">Change lane (manual correction)</p>
                        <select
                          value={intakeLaneOverrideDraft}
                          onChange={(e) => setIntakeLaneOverrideDraft(e.target.value)}
                          className="w-full rounded border border-slate-600 bg-slate-900 text-slate-200 text-xs py-2 px-2 mb-2"
                        >
                          <option value="">Use system lane</option>
                          {INTAKE_LANE_ORDER.map((lid) => (
                            <option key={lid} value={lid}>{INTAKE_LANE_LABELS[lid] ?? lid}</option>
                          ))}
                        </select>
                        <textarea
                          placeholder="Correction note (required when changing lane)"
                          value={intakeCorrectionNoteDraft}
                          onChange={(e) => setIntakeCorrectionNoteDraft(e.target.value)}
                          className="w-full rounded border border-slate-600 bg-slate-900 text-slate-200 text-xs py-2 px-2 mb-2 min-h-[60px]"
                          rows={2}
                        />
                        {intakeLaneSaveError && <p className="text-amber-300/90 text-xs mb-2">{intakeLaneSaveError}</p>}
                        <button
                          type="button"
                          onClick={() => saveIntakeLaneCorrection(detailItem.id)}
                          className="rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-medium px-3 py-2"
                        >
                          Save lane correction
                        </button>
                        <div className="pt-3 mt-3 border-t border-slate-600 space-y-2">
                          <p className="text-slate-500 text-xs uppercase tracking-wide">Create task in Vision Execution</p>
                          <p className="text-slate-500 text-[10px]">
                            Creates a task in the Vision Execution core and records a minimal lifecycle link (intake item → judgment → task).
                          </p>
                          <div className="grid grid-cols-1 lg:grid-cols-2 gap-2 mb-1">
                            <div>
                              <label className="block text-slate-500 text-[10px] mb-0.5">Project ID</label>
                              <input
                                type="text"
                                value={createTaskProjectId}
                                onChange={(e) => setCreateTaskProjectId(e.target.value)}
                                className="w-full rounded border border-slate-600 bg-slate-900 text-slate-200 text-[11px] py-1 px-2"
                                placeholder="Vision Execution project id"
                              />
                            </div>
                            <div>
                              <label className="block text-slate-500 text-[10px] mb-0.5">Task title</label>
                              <input
                                type="text"
                                value={createTaskTitle}
                                onChange={(e) => setCreateTaskTitle(e.target.value)}
                                className="w-full rounded border border-slate-600 bg-slate-900 text-slate-200 text-[11px] py-1 px-2"
                                placeholder={detailItem.subject || 'Task from intake'}
                              />
                            </div>
                          </div>
                          <div className="grid grid-cols-1 lg:grid-cols-2 gap-2 mb-1">
                            <div>
                              <label className="block text-slate-500 text-[10px] mb-0.5">Summary (optional)</label>
                              <textarea
                                value={createTaskSummary}
                                onChange={(e) => setCreateTaskSummary(e.target.value)}
                                className="w-full rounded border border-slate-600 bg-slate-900 text-slate-200 text-[11px] py-1 px-2 min-h-[48px]"
                                placeholder={detailItem.summary || 'Use queue summary'}
                              />
                            </div>
                            <div>
                              <label className="block text-slate-500 text-[10px] mb-0.5">Notes (optional)</label>
                              <textarea
                                value={createTaskNotes}
                                onChange={(e) => setCreateTaskNotes(e.target.value)}
                                className="w-full rounded border border-slate-600 bg-slate-900 text-slate-200 text-[11px] py-1 px-2 min-h-[48px]"
                                placeholder="Visible on task, plus lifecycle link"
                              />
                            </div>
                          </div>
                          <p className="text-slate-500 text-[10px]">
                            Source judgment id:{' '}
                            {intakeJudgmentChain?.item_id === detailItem.id && intakeJudgmentChain.chain.length > 0
                              ? String(intakeJudgmentChain.chain[intakeJudgmentChain.chain.length - 1].id || '')
                              : '—'}
                          </p>
                          {createTaskError && <p className="text-amber-300/90 text-xs">{createTaskError}</p>}
                          {createTaskResult && (
                            <div className="flex flex-wrap items-center gap-2 text-emerald-300/90 text-xs">
                              <span>
                                Created task <span className="font-mono">{createTaskResult.taskId}</span>
                                {createTaskResult.decisionId && (
                                  <>
                                    {' · '}Decision <span className="font-mono">{createTaskResult.decisionId}</span>
                                  </>
                                )}
                              </span>
                              <button
                                type="button"
                                onClick={() => setMainView('vision_execution')}
                                className="px-2 py-0.5 rounded border border-emerald-500/70 text-emerald-200 hover:bg-emerald-900/40"
                              >
                                View in Vision &amp; Execution
                              </button>
                            </div>
                          )}
                          <button
                            type="button"
                            onClick={() => createTaskFromIntake(detailItem.id, detailItem.subject || '', detailItem.summary || '')}
                            className="rounded-lg bg-amber-600 hover:bg-amber-500 text-white text-xs font-medium px-3 py-1.5 disabled:opacity-50"
                            disabled={!!createTaskLoadingId}
                          >
                            {createTaskLoadingId === detailItem.id ? 'Creating…' : 'Create task'}
                          </button>
                        </div>
                        <div className="pt-2 mt-2 border-t border-slate-600">
                          <button
                            type="button"
                            onClick={() => archiveIntakeItem(detailItem.id)}
                            className="text-slate-500 hover:text-slate-300 text-xs"
                            title="Hide in Zenaf queue only"
                          >
                            Archive (hide from queue)
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              )
            })()}
          </section>

          {error && (lastMode === 'analyze' || lastMode === 'simulate' || lastMode === 'assess' || lastMode === 'recommend') && (
            <div className="mt-4 rounded-lg bg-red-900/30 border border-red-700 text-red-200 text-sm p-3">
              {error}
            </div>
          )}

          {(lastMode === 'analyze' || lastMode === 'simulate' || lastMode === 'assess' || lastMode === 'recommend') && result && (
            <div className="mt-6">
              <DeveloperDetailsCollapse
                result={result}
                label="Workflow result (JSON)"
                workflowMode={lastMode}
                onJsonCopySuccess={onWorkspaceJsonCopied}
              />
            </div>
          )}
          </main>
        )}

        {/* Right: Folder review result (when in folder workflow) or conversation panel.
            Hidden on the Living Tree home view so the tree owns the screen. */}
        {mainView !== 'living_tree' && (
        <aside
          className={`w-full lg:w-[380px] lg:shrink-0 lg:sticky lg:top-0 flex flex-col min-h-0 h-auto lg:h-[calc(100vh-8rem)] max-h-[78vh] lg:max-h-[calc(100vh-4.5rem)] bg-stone-800/60 overflow-x-hidden shadow-lg ${
            mainView === 'vision_map'
              ? 'order-first border-t lg:border-t-0 lg:border-r border-stone-700 rounded-t-lg lg:rounded-t-none lg:rounded-r-lg'
              : 'border-t lg:border-t-0 lg:border-l border-stone-700 rounded-t-lg lg:rounded-t-none lg:rounded-l-lg'
          }`}
        >
          <button
            type="button"
            onClick={() => setChatPanelCollapsed((v) => !v)}
            aria-expanded={!chatPanelCollapsed}
            aria-label={chatPanelCollapsed ? 'Show conversation panel' : 'Hide conversation panel'}
            className="lg:hidden flex items-center justify-between w-full px-4 min-h-[48px] text-sm font-semibold text-stone-200 shrink-0"
          >
            <span>Conversation</span>
            <svg
              viewBox="0 0 24 24"
              className={`h-5 w-5 transition-transform ${chatPanelCollapsed ? '' : 'rotate-180'}`}
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              aria-hidden
            >
              <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
          <div
            className={`${
              chatPanelCollapsed ? 'hidden' : 'flex'
            } lg:flex flex-col flex-1 min-h-0 min-w-0 overflow-hidden`}
          >
          {error && (mainView !== 'workspace' || workoutActive) && (
            <div
              className="shrink-0 p-3 border-b border-red-800/50 bg-red-900/25 text-red-200 text-xs"
              role="alert"
            >
              {error}
            </div>
          )}
          <div className="flex flex-col flex-1 min-h-0 overflow-hidden overflow-x-hidden overscroll-contain">
          <div
            className="shrink-0 px-3 py-2.5 border-b border-amber-900/35 bg-gradient-to-r from-stone-900/95 via-stone-900/85 to-stone-800/80"
            role="region"
            aria-label="Current chat mode"
          >
            <p className="text-[10px] uppercase tracking-wider text-amber-500/90 font-semibold mb-1">
              Chat mode
            </p>
            <p className="text-sm font-medium text-stone-100 leading-snug">
              {mediationPanelHeadline(mediationPanelMode, councilStreamPhase)}
            </p>
            <p className="text-[11px] text-stone-500 mt-1.5 font-mono">
              {mediationPanelMode}
            </p>
            <p className="text-xs text-stone-400 mt-1">
              Workspace:{' '}
              <span className="text-stone-200">{workspaceRunModeLabel(activeMode)}</span>
              {foundationTrainingMode ? (
                <span className="text-stone-500"> · Foundation training</span>
              ) : null}
            </p>
            <p className="text-xs text-stone-500 mt-0.5">
              Surface: <span className="text-stone-400">{mainViewLabel(mainView)}</span>
            </p>
            <MediationFlowHint veSelection={veSelection} />
          </div>
          {showFolderReviewPanel ? (
            <>
              <div className="shrink-0 p-4 border-b border-stone-700">
                <h2 className="text-base font-semibold text-stone-100">Folder review result</h2>
                <p className="text-stone-400 text-xs mt-1">AI suggestions for your folder list. Use Refine Categories in step 3 to run.</p>
              </div>
              <div className="flex-1 min-h-0 basis-0 overflow-y-auto overflow-x-hidden p-3 space-y-3 overscroll-contain">
                {folderAdvisorLoading || folderAdvisorStreaming ? (
                  <div className="rounded-lg px-3 py-2 text-sm bg-stone-900/90 text-stone-300 border border-yellow-700/50">
                    <p className="text-xs text-yellow-500/90 font-medium mb-1">Refine Categories (AI)</p>
                    <CouncilTranscript text={folderAdvisorStreaming} decorateSeatHeaders={false} stripZenafSynthesis={false} />
                    <span className="inline-block w-2 h-4 ml-0.5 bg-yellow-500 animate-pulse" aria-hidden />
                  </div>
                ) : folderAdvisorResult ? (
                  folderAdvisorParsedSuggestions.length > 0 ? (
                    <>
                      <div className="space-y-2">
                        {folderAdvisorParsedSuggestions.map((s, i) => {
                          const applied = appliedFolderSuggestions.has(normalizeFolderKey(s.folder))
                          return (
                            <div
                              key={i}
                              className={`rounded-lg border px-3 py-2 text-xs ${applied ? 'border-stone-600 bg-stone-800/50 text-stone-500' : 'border-stone-600 bg-stone-900/50'}`}
                            >
                              <span className="font-medium text-stone-200">{s.folder}</span>
                              {applied && <span className="ml-2 text-[10px] text-emerald-400/90 uppercase">Added</span>}
                              {s.reason && <p className="text-stone-500 mt-0.5">{s.reason}</p>}
                            </div>
                          )
                        })}
                      </div>
                      <div className="flex flex-col gap-2 pt-2 border-t border-stone-700">
                        <button
                          type="button"
                          onClick={() => {
                            folderAdvisorParsedSuggestions.forEach((s) => {
                              const key = normalizeFolderKey(s.folder)
                              if (appliedFolderSuggestions.has(key)) return
                              const existing = findExistingFolderMatch(s.folder, approvedFolders)
                              if (existing) {
                                setAppliedAiMatchedFolders((prev) => (prev.includes(existing) ? prev : [...prev, existing]))
                                setAppliedFolderSuggestions((prev) => new Set(prev).add(key))
                              } else {
                                addCustomRecommendation(s.folder)
                                setAppliedFolderSuggestions((prev) => new Set(prev).add(key))
                              }
                            })
                            const w = workspaceOutcomeTargetRef.current
                            if (w?.action_intent === WORKSPACE_ACTION_INTENTS.folder_advisor) {
                              try {
                                recordWorkspaceTraceUserOutcome(w.trace, 'applied')
                              } catch {
                                /* ignore */
                              }
                              postWorkspaceLearningFromRef(w, 'applied')
                            }
                          }}
                          className="w-full px-4 py-2 rounded-lg bg-yellow-700 hover:bg-yellow-600 text-stone-50 text-sm font-medium"
                        >
                          Add suggestion
                        </button>
                        <button
                          type="button"
                          onClick={() => setReplaceListConfirmOpen(true)}
                          className="w-full px-4 py-2 rounded-lg border border-stone-500 bg-stone-800 text-stone-300 text-sm hover:bg-stone-700"
                        >
                          Replace list
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            const w = workspaceOutcomeTargetRef.current
                            if (w?.action_intent === WORKSPACE_ACTION_INTENTS.folder_advisor) {
                              try {
                                // Declining suggestions without adding — triage, same spirit as rejectRecommendation.
                                recordWorkspaceTraceUserOutcome(w.trace, 'edited')
                              } catch {
                                /* ignore */
                              }
                              postWorkspaceLearningFromRef(w, 'edited')
                            }
                            setFolderAdvisorResult(null)
                          }}
                          className="w-full px-4 py-2 rounded-lg border border-stone-600 text-stone-400 text-sm hover:text-stone-300"
                        >
                          Ignore
                        </button>
                      </div>
                      {replaceListConfirmOpen && (
                        <div className="fixed inset-0 z-20 flex items-center justify-center p-4 bg-black/60" onClick={() => setReplaceListConfirmOpen(false)}>
                          <div className="bg-stone-800 border border-stone-600 rounded-xl shadow-xl max-w-sm w-full p-4" onClick={(e) => e.stopPropagation()}>
                            <p className="text-stone-200 text-sm mb-4">
                              Replace current folder list with these {folderAdvisorParsedSuggestions.length} suggestions? This will reject all current suggested folders and set the list to the AI suggestions.
                            </p>
                            <div className="flex justify-end gap-2">
                              <button type="button" onClick={() => setReplaceListConfirmOpen(false)} className="px-4 py-2 rounded-lg border border-stone-600 text-stone-400 hover:text-stone-300 text-sm">
                                Cancel
                              </button>
                              <button
                                type="button"
                                onClick={() => {
                                  const suggested = lastRecommendResult?.suggested_child_folders ?? []
                                  setRejectedRecommendations(new Set(suggested))
                                  const deduped = folderAdvisorParsedSuggestions.reduce<string[]>((acc, s) => {
                                    const name = s.folder.trim()
                                    if (findExistingFolderMatch(name, acc)) return acc
                                    return [...acc, name]
                                  }, [])
                                  setCustomRecommendations(deduped)
                                  setReplaceListConfirmOpen(false)
                                  const w = workspaceOutcomeTargetRef.current
                                  if (w?.action_intent === WORKSPACE_ACTION_INTENTS.folder_advisor) {
                                    try {
                                      recordWorkspaceTraceUserOutcome(w.trace, 'applied')
                                    } catch {
                                      /* ignore */
                                    }
                                    postWorkspaceLearningFromRef(w, 'applied')
                                  }
                                }}
                                className="px-4 py-2 rounded-lg bg-yellow-700 hover:bg-yellow-600 text-stone-50 text-sm font-medium"
                              >
                                Replace
                              </button>
                            </div>
                          </div>
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="rounded-lg px-3 py-2 text-sm bg-stone-900/90 text-stone-300 border border-stone-600">
                      <p className="text-xs text-stone-500 mb-2">Could not parse suggestions. Full response:</p>
                      <CouncilTranscript text={folderAdvisorResult} decorateSeatHeaders={false} stripZenafSynthesis={false} />
                    </div>
                  )
                ) : (
                  <p className="text-stone-500 text-sm">Use <strong>Refine Categories</strong> in step 3 to get AI suggestions for your folder list.</p>
                )}
              </div>
            </>
          ) : workoutActive && workoutPerspective ? (
            <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
              <PerspectiveWorkoutPanel
                perspective={workoutPerspective}
                thread={workoutThread}
                input={workoutInput}
                onInputChange={setWorkoutInput}
                onSendSeat1={() => void handleWorkoutSendSeat1()}
                onInvokeSeat={(a) => void handleWorkoutInvokeSeat(a)}
                invokingSeatId={workoutInvokingSeat}
                availableSeats={perspectiveAgents.filter((a) => a.id !== workoutPerspective.id)}
                onRequestExit={handleWorkoutExitRequest}
              />
            </div>
          ) : (
            <div className="flex flex-col flex-1 min-h-0 min-w-0">
              {councilScopedDigression && activeMode === 'council' ? (
                <div
                  className="shrink-0 mx-3 mt-3 mb-1 rounded-lg border border-cyan-500/45 bg-cyan-950/35 shadow-[0_0_20px_rgba(34,211,238,0.12)] px-3 py-2.5 flex items-start justify-between gap-3"
                  role="status"
                >
                  <div className="min-w-0">
                    <p className="text-[10px] uppercase tracking-wide text-cyan-400/95 font-semibold">
                      Scoped sub-thread
                    </p>
                    <p className="text-sm text-cyan-100/95 font-medium truncate" title={councilScopedDigression.label}>
                      Focus: {councilScopedDigression.label}
                    </p>
                    <p className="text-[11px] text-cyan-200/60 mt-0.5">
                      Replies use a narrow context until you return or finalize a save.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => foldScopedThreadIntoNest()}
                    className="shrink-0 px-3 py-1.5 rounded-md text-xs font-medium bg-stone-900/90 text-cyan-100 border border-cyan-600/50 hover:bg-stone-800"
                  >
                    Return
                  </button>
                </div>
              ) : null}
              {/* Split ~50/50: transcript vs composer+seats so the thread is not starved by tall seat controls */}
              <div className="grid min-h-0 min-w-0 flex-1 grid-rows-[minmax(0,1fr)_minmax(0,1fr)]">
                <div className="flex min-h-0 min-w-0 flex-col overflow-hidden">
                  <div className="shrink-0 border-b border-stone-700 p-4">
                    <h2 className="text-base font-semibold text-stone-100">Conversation</h2>
                  </div>
                  <div
                    ref={agentConversationScrollRef}
                    className={`min-h-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-contain p-3 space-y-3 ${
                      councilScopedDigression && activeMode === 'council'
                        ? 'rounded-b-lg mx-1 mb-1 ring-1 ring-cyan-600/25 bg-cyan-950/[0.07]'
                        : ''
                    }`}
                    onDragOver={(e) => {
                      if (!dataTransferHasFiles(e.dataTransfer)) return
                      e.preventDefault()
                      e.dataTransfer.dropEffect = 'copy'
                    }}
                    onDrop={(e) => {
                      if (!dataTransferHasFiles(e.dataTransfer)) return
                      e.preventDefault()
                      void appendFilesToCouncilQuestion(e.dataTransfer.files)
                    }}
                  >
                {agentThread.length === 0 &&
                  !agentResponse &&
                  !streamingCouncilText &&
                  !(loading && activeMode === 'council') &&
                  councilStreamPhase === 'idle' && (
                  <p className="text-stone-500 text-xs">Ask a question or run an agent to start the thread.</p>
                )}
                {/* One ThreadInlineGuideStack per render: only at first stacked guide index; other stacked rows are skipped (return null). */}
                {(() => {
                  const renderRow = (
                    m: AgentThreadMessage,
                    i: number,
                    keyPrefix: string,
                    insideNest: boolean,
                  ): ReactNode => {
                  if (m.threadItemKind === 'scoped_thread_nest' && m.nestedScopedThread) {
                    const { id, label, children } = m.nestedScopedThread
                    const expanded = councilExpandedNestIds.has(id)
                    const count = children.length
                    return (
                      <div
                        key={keyPrefix}
                        className="rounded-lg border border-cyan-700/35 bg-stone-950/55 mx-2 overflow-hidden"
                      >
                        <button
                          type="button"
                          onClick={() =>
                            setCouncilExpandedNestIds((prev) => {
                              const next = new Set(prev)
                              if (next.has(id)) next.delete(id)
                              else next.add(id)
                              return next
                            })
                          }
                          className="w-full text-left px-3 py-2.5 flex items-start gap-2 text-sm hover:bg-stone-900/50"
                        >
                          <span className="text-cyan-400/90 shrink-0 font-mono text-xs mt-0.5" aria-hidden>
                            {expanded ? '▼' : '▶'}
                          </span>
                          <span className="min-w-0">
                            <span className="text-[10px] uppercase tracking-wide text-cyan-500/85 font-semibold block">
                              Scoped thread
                            </span>
                            <span className="block truncate text-stone-100 font-medium" title={label}>
                              {label}
                            </span>
                            <span className="text-[11px] text-stone-500">
                              {count} message{count === 1 ? '' : 's'} · {expanded ? 'Collapse' : 'Expand'}
                            </span>
                          </span>
                        </button>
                        {expanded ? (
                          <div className="px-2 pb-2 pt-1 space-y-2 border-t border-cyan-900/25 bg-stone-950/40">
                            {children.map((c, j) => renderRow(c, j, `${keyPrefix}-c${j}`, true))}
                          </div>
                        ) : null}
                      </div>
                    )
                  }
                  if (m.role === 'system') {
                    return (
                      <div
                        key={m.ephemeralRunId ? `session-${m.ephemeralRunId}` : keyPrefix}
                        className="rounded-lg px-3 py-2 text-xs text-stone-400 bg-stone-900/40 border border-stone-700/60 mx-2"
                        role="status"
                        aria-live="polite"
                      >
                        <p className="text-[10px] uppercase tracking-wide text-stone-500 mb-1">Session</p>
                        <p className="whitespace-pre-wrap font-sans">{m.content}</p>
                      </div>
                    )
                  }
                  if (m.threadItemKind === 'streaming_placeholder') {
                    const statusLine =
                      councilPhaseDetail(councilStreamPhase) || 'Preparing response…'
                    return (
                      <div
                        key={m.ephemeralRunId ? `placeholder-${m.ephemeralRunId}` : keyPrefix}
                        className="rounded-lg px-3 py-2 text-sm bg-stone-900/90 text-stone-300 mr-4 border border-yellow-700/40"
                        role="status"
                        aria-live="polite"
                      >
                        {m.agentLabel ? (
                          <p className="text-xs text-yellow-500/90 font-medium mb-1">{m.agentLabel}</p>
                        ) : null}
                        <p className="text-xs text-stone-400 whitespace-pre-wrap">{statusLine}</p>
                        <span
                          className="inline-block w-2 h-4 mt-2 bg-yellow-500/60 animate-pulse"
                          aria-hidden
                        />
                      </div>
                    )
                  }
                  if (m.role === 'guide') {
                    const gid = guideRowPromptId(m)
                    if (!insideNest && stackedPromptIdSet.has(gid)) {
                      if (i === firstStackedGuideIndex && stackedGuides.length > 0) {
                        return (
                          <ThreadInlineGuideStack
                            key={`inline-guide-stack-${guideStackKeyFingerprint}`}
                            barSubtitle={guideStackBarSubtitle}
                            guides={stackedGuides}
                            getPromptId={guideRowPromptId}
                            seenPromptIds={seenStackGuidePromptIds}
                            onMarkSeen={markStackGuideSeen}
                            listOpen={guideStackListOpen}
                            onToggleList={toggleGuideStackList}
                            nestedExpandedPromptId={nestedStackGuidePromptId}
                            onSetNestedExpandedPromptId={setNestedStackGuidePromptId}
                            veSelection={veSelection}
                            activeConversationalSuggestionPromptId={activeConversationalSuggestionPromptId}
                            onCollapseItem={(pid) => {
                              setNestedStackGuidePromptId((e) => (e === pid ? null : e))
                              setActiveConversationalSuggestionPromptId((a) => (a === pid ? null : a))
                            }}
                            onFocusQuestion={(rowId, q) => {
                              markStackGuideSeen(rowId)
                              engageGuideDiscussion(rowId, { councilPrefill: councilPrefillForGuideQuestion(q) })
                            }}
                            onDiscussEngage={(rowId, q) =>
                              engageGuideDiscussion(rowId, { councilPrefill: councilPrefillForGuideQuestion(q) })
                            }
                            onDiscussFromCollapsed={runGuideDiscussFromCollapsed}
                            registerDeferContextForPrompt={registerDeferContextForPrompt}
                            removeGuideRowsForPromptId={removeGuideRowsForPromptId}
                            dismissGuideFromThread={dismissGuideFromThread}
                            markGuideInteracted={markGuideInteracted}
                            hidePromptActionsForPromptId={hidePromptActionsForPromptId}
                            councilTextareaFocus={() => {
                              window.setTimeout(() => councilQuestionTextareaRef.current?.focus(), 0)
                            }}
                          />
                        )
                      }
                      return null
                    }
                    const gm = m as GuideThreadMessage
                    const guideQuestionText = resolveGuideQuestionMeta(gm).questionText
                    const guideCanonicalPromptId =
                      gm.promptSignal?.promptId ?? ephemeralGuidePromptIdFromContent(gm.content)
                    return (
                      <InlineThreadGuideCard
                        key={keyPrefix}
                        message={gm}
                        mainView={mainView}
                        mapNodeKind={mapDevelopmentalSnapshot?.node_kind ?? null}
                        veTypeHint={developmentalGuidancePreview?.vm_entity_type ?? null}
                        mapNodeLabel={mapDevelopmentalSnapshot?.node_label ?? null}
                        nestAggregate={mapDevelopmentalSnapshot?.node_kind === 'nest'}
                        formatSystemPromptContextTitle={formatSystemPromptContextTitle}
                        veSelection={veSelection}
                        registerDeferContextForPrompt={registerDeferContextForPrompt}
                        removeGuideRowsForPromptId={removeGuideRowsForPromptId}
                        dismissGuideFromThread={dismissGuideFromThread}
                        markGuideInteracted={markGuideInteracted}
                        hidePromptActionsForPromptId={hidePromptActionsForPromptId}
                        isExpanded={expandedThreadGuidePromptId === gid}
                        isActiveConversationalSuggestion={activeConversationalSuggestionPromptId === gid}
                        onShowInThread={() => {
                          setExpandedThreadGuidePromptId(gid)
                          setActiveConversationalSuggestionPromptId(null)
                        }}
                        onCollapse={() => {
                          setExpandedThreadGuidePromptId((e) => (e === gid ? null : e))
                          setActiveConversationalSuggestionPromptId((a) => (a === gid ? null : a))
                        }}
                        onDiscussEngage={() =>
                          engageGuideDiscussion(gid, {
                            councilPrefill: councilPrefillForGuideQuestion(guideQuestionText),
                          })
                        }
                        onDiscussFromCollapsed={() =>
                          runGuideDiscussFromCollapsed(gid, guideQuestionText, guideCanonicalPromptId)
                        }
                        councilTextareaFocus={() => {
                          window.setTimeout(() => councilQuestionTextareaRef.current?.focus(), 0)
                        }}
                      />
                    )
                  }
                  return (
                    <div
                      key={keyPrefix}
                      className={`rounded-lg px-3 py-2 text-sm ${
                        m.role === 'user'
                          ? 'bg-stone-700/80 text-stone-200 ml-4'
                          : 'bg-stone-900/90 text-stone-300 mr-4 border border-stone-600'
                      }`}
                    >
                      {m.role === 'agent' && m.agentLabel && (
                        <p className="text-xs text-yellow-500/90 font-medium mb-1">{m.agentLabel}</p>
                      )}
                      {m.role === 'agent' && m.threadHandoffReview ? (
                        <>
                          <pre className="whitespace-pre-wrap font-sans text-xs text-stone-300 mb-2">
                            {m.content.slice(0, AGENT_THREAD_DISPLAY_MAX_CHARS)}
                            {m.content.length > AGENT_THREAD_DISPLAY_MAX_CHARS ? '\n…' : ''}
                          </pre>
                          <SubjectHandoffReview
                            reviewId={m.threadHandoffReview.reviewId}
                            forSubjectLabel={m.threadHandoffReview.forSubjectLabel}
                            items={m.threadHandoffReview.items}
                            resolvedIds={resolvedHandoffSet}
                            showSaveInNotes={Boolean(
                              parseSubjectEntityRef(m.threadHandoffReview.previousSubjectKey),
                            )}
                            busyId={handoffNotesBusyId}
                            onCommitNow={handleHandoffCommitNow}
                            onSaveNotes={(item) =>
                              void handleHandoffSaveNotes(item, m.threadHandoffReview!.previousSubjectKey)
                            }
                            onDismissItem={handleHandoffDismissItem}
                          />
                          <AgentChatResonanceSlider
                            responseId={`handoff-${m.threadHandoffReview.reviewId}`}
                            agentLabel={m.agentLabel || 'Handoff'}
                            mainView={mainView}
                            folderPath={folderPath}
                            lastFolderPath={lastFolderPath}
                          />
                        </>
                      ) : m.role === 'agent' &&
                        (m.agentLabel === 'Council' ||
                          m.agentLabel === 'Folder review' ||
                          m.agentLabel === 'Zenaf' ||
                          m.agentLabel === 'Thinking Partner' ||
                          m.agentLabel === 'Zenaf (Thinking Partner)') ? (
                        <>
                          <CouncilTranscriptResonanceBridge
                            text={m.content}
                            decorateSeatHeaders={m.agentLabel === 'Council'}
                            stripZenafSynthesis={
                              m.agentLabel === 'Council' ? !includeCouncilSynthesis : true
                            }
                            responseIdPrefix={
                              m.resonanceResponseId ??
                              councilSynthesisIntegrityEnvelope?.provenance?.run_id ??
                              `${keyPrefix}-msg`
                            }
                            mainView={mainView}
                            folderPath={folderPath}
                            lastFolderPath={lastFolderPath}
                            agentLabelForResonance={m.agentLabel}
                            folderWorkflowResonance={m.agentLabel === 'Folder review'}
                            integrationCommit={m.integrationCommit}
                            pendingIntegration={m.pendingIntegration}
                            onOpenEntity={handleCouncilEntityMentionOpen}
                          />
                          {!insideNest && i === agentThread.length - 1 &&
                            m.role === 'agent' &&
                            m.agentLabel === 'Council' &&
                            includeCouncilSynthesis &&
                            /\bZenaf synthesis:/i.test(m.content) && (
                              <CouncilSynthesisIntegrityNote
                                includeSynthesis
                                state={councilSynthesisIntegrity}
                                warning={councilIntegrityWarning}
                                envelope={councilSynthesisIntegrityEnvelope}
                              />
                            )}
                        </>
                      ) : (
                        <>
                          {m.role === 'user' && activeMode === 'council' ? (
                            <div className="whitespace-pre-wrap font-sans text-xs text-stone-200">
                              <EntityMentionText
                                text={m.councilThreadDisplayContent ?? m.content}
                                maxChars={AGENT_THREAD_DISPLAY_MAX_CHARS}
                                onOpenEntity={handleCouncilEntityMentionOpen}
                              />
                            </div>
                          ) : (
                            <pre className="whitespace-pre-wrap font-sans text-xs">
                              {(m.councilThreadDisplayContent ?? m.content).slice(
                                0,
                                AGENT_THREAD_DISPLAY_MAX_CHARS,
                              )}
                              {(m.councilThreadDisplayContent ?? m.content).length >
                              AGENT_THREAD_DISPLAY_MAX_CHARS
                                ? '\n…'
                                : ''}
                            </pre>
                          )}
                          {m.role === 'agent' ? (
                            <AgentChatResonanceSlider
                              responseId={m.resonanceResponseId ?? `${keyPrefix}-integrated`}
                              agentLabel={m.agentLabel}
                              mainView={mainView}
                              folderPath={folderPath}
                              lastFolderPath={lastFolderPath}
                            />
                          ) : null}
                        </>
                      )}
                    </div>
                  )
                }
                  return agentThread.map((m, i) => {
                    if (councilScopeThreadStartIndex != null) {
                      const start = Math.min(councilScopeThreadStartIndex, agentThread.length)
                      if (i < start) return null
                    }
                    return renderRow(m, i, `row-${i}`, false)
                  })
                })()}
                {streamingCouncilText && (
                  <div className="rounded-lg px-3 py-2 text-sm bg-stone-900/90 text-stone-300 mr-4 border border-yellow-700/50">
                    <p className="text-xs text-yellow-500/90 font-medium mb-1">
                      {lastCouncilWasFolderWorkflow ? 'Folder review' : streamingCouncilRunLabel}
                    </p>
                    <CouncilTranscriptResonanceBridge
                      text={streamingCouncilText}
                      decorateSeatHeaders={
                        !lastCouncilWasFolderWorkflow && streamingCouncilRunLabel === 'Council'
                      }
                      stripZenafSynthesis={
                        lastCouncilWasFolderWorkflow ||
                        streamingCouncilRunLabel === 'Zenaf' ||
                        streamingCouncilRunLabel === 'Thinking Partner' ||
                        streamingCouncilRunLabel === 'Zenaf (Thinking Partner)' ||
                        !includeCouncilSynthesis
                      }
                      responseIdPrefix={
                        councilResonanceRunIdRef.current ??
                        councilSynthesisIntegrityEnvelope?.provenance?.run_id ??
                        streamingCouncilResonanceKeyRef.current
                      }
                      mainView={mainView}
                      folderPath={folderPath}
                      lastFolderPath={lastFolderPath}
                      agentLabelForResonance={
                        lastCouncilWasFolderWorkflow ? 'Folder review' : streamingCouncilRunLabel
                      }
                      folderWorkflowResonance={lastCouncilWasFolderWorkflow}
                      onOpenEntity={handleCouncilEntityMentionOpen}
                    />
                    {!lastCouncilWasFolderWorkflow && streamingCouncilRunLabel === 'Council' && (
                      <CouncilSynthesisIntegrityNote
                        includeSynthesis={includeCouncilSynthesis}
                        state={councilSynthesisIntegrity}
                        warning={councilIntegrityWarning}
                        envelope={councilSynthesisIntegrityEnvelope}
                      />
                    )}
                    <span className="inline-block w-2 h-4 ml-0.5 bg-yellow-500 animate-pulse" aria-hidden />
                  </div>
                )}
                {agentResponse && agentThread.length === 0 && !streamingCouncilText && (
                  <div className="rounded-lg px-3 py-2 text-sm bg-stone-900/90 text-stone-300 border border-stone-600">
                    {lastMode === 'council' ? (
                      <>
                        <CouncilTranscriptResonanceBridge
                          text={agentResponse}
                          decorateSeatHeaders={
                            lastCouncilPresentationKind === 'multiseat' && !lastCouncilWasFolderWorkflow
                          }
                          stripZenafSynthesis={
                            lastCouncilPresentationKind !== 'multiseat' ||
                            lastCouncilWasFolderWorkflow ||
                            !includeCouncilSynthesis
                          }
                          responseIdPrefix={threadAgentStripResonanceIdRef.current}
                          mainView={mainView}
                          folderPath={folderPath}
                          lastFolderPath={lastFolderPath}
                          agentLabelForResonance={
                            lastCouncilWasFolderWorkflow ? 'Folder review' : streamingCouncilRunLabel || 'Council'
                          }
                          folderWorkflowResonance={lastCouncilWasFolderWorkflow}
                          onOpenEntity={handleCouncilEntityMentionOpen}
                        />
                        {lastCouncilPresentationKind === 'multiseat' &&
                          !lastCouncilWasFolderWorkflow &&
                          includeCouncilSynthesis &&
                          /\bZenaf synthesis:/i.test(agentResponse) && (
                            <CouncilSynthesisIntegrityNote
                              includeSynthesis={includeCouncilSynthesis}
                              state={councilSynthesisIntegrity}
                              warning={councilIntegrityWarning}
                              envelope={councilSynthesisIntegrityEnvelope}
                            />
                          )}
                      </>
                    ) : (
                      <>
                        <pre className="whitespace-pre-wrap font-sans text-xs">
                          {agentResponse.slice(0, AGENT_THREAD_DISPLAY_MAX_CHARS)}
                          {agentResponse.length > AGENT_THREAD_DISPLAY_MAX_CHARS ? '\n…' : ''}
                        </pre>
                        <AgentChatResonanceSlider
                          responseId={`${threadAgentStripResonanceIdRef.current}-other`}
                          agentLabel={
                            lastMode === 'web_research'
                              ? 'Web'
                              : lastMode === 'next_step'
                                ? 'Next Step'
                                : 'Assistant'
                          }
                          mainView={mainView}
                          folderPath={folderPath}
                          lastFolderPath={lastFolderPath}
                        />
                      </>
                    )}
                  </div>
                )}
                    <div ref={agentConversationEndRef} className="h-px w-full shrink-0 scroll-mt-2" aria-hidden />
                  </div>
                </div>
                <div className="min-h-0 overflow-x-hidden overflow-y-auto overscroll-contain border-t border-stone-700 bg-stone-800/80">
                  <div className="space-y-3 p-4">
                <div>
                  <label className="block text-xs text-stone-500 mb-1">Your reply</label>
                  <CouncilQuestionTextarea
                    textareaRef={councilQuestionTextareaRef}
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    onInput={() => {
                      adjustCouncilQuestionTextareaHeight()
                    }}
                    onKeyDown={(e) => {
                      if (e.key !== 'Enter' || e.shiftKey) return
                      e.preventDefault()
                      if (!agentRunDisabled) runSelectedAgent()
                    }}
                    placeholder="Type your question or response for the council…"
                    className="w-full px-3 py-2.5 rounded-lg bg-stone-900 border border-stone-600 text-stone-100 text-sm placeholder-stone-500 focus:outline-none focus:ring-1 focus:ring-yellow-700 resize-none leading-relaxed"
                  />
                  <button
                    type="button"
                    className="mt-2 text-[10px] text-stone-500 hover:text-stone-300 underline-offset-2 hover:underline"
                    onClick={() => setCouncilAdvancedOptions((v) => !v)}
                  >
                    {councilAdvancedOptions ? 'Hide advanced options' : 'Advanced options'}
                  </button>
                  {councilAdvancedOptions ? (
                    <div className="mt-2 space-y-2 border-l border-stone-700/80 pl-2">
                      <label className="flex items-center gap-2 text-xs text-stone-400 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={useLastResultAsContext}
                          onChange={(e) => setUseLastResultAsContext(e.target.checked)}
                          className="rounded border-stone-600 bg-stone-900 text-yellow-700"
                        />
                        Use current result as context
                      </label>
                      <label className="flex items-center gap-2 text-xs text-stone-400 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={includeCouncilSynthesis}
                          onChange={(e) => setIncludeCouncilSynthesis(e.target.checked)}
                          className="rounded border-stone-600 bg-stone-900 text-yellow-700"
                        />
                        Include Zenaf synthesis (final integrator pass)
                      </label>
                    </div>
                  ) : null}
                </div>
                <button
                  onClick={runSelectedAgent}
                  disabled={agentRunDisabled}
                  className="w-full px-4 py-2.5 rounded-lg bg-yellow-700 hover:bg-yellow-600 disabled:opacity-50 text-stone-50 text-sm font-medium"
                >
                  {councilTransformLoading ? 'Working…' : loading ? 'Running…' : 'Ask council'}
                </button>
                <CouncilPersonalityModeSelector
                  value={councilPersonalityMode}
                  onChange={handleCouncilPersonalityModeChange}
                  disabled={agentRunDisabled}
                />
                {mirrorNotice ? (
                  <p
                    role="status"
                    className="rounded-lg border border-amber-700/50 bg-amber-950/40 px-3 py-2 text-[11px] text-amber-200/90 leading-snug"
                  >
                    {mirrorNotice}
                  </p>
                ) : null}
                {lastMode === 'council' ? (
                  <div className="space-y-1">
                    <button
                      type="button"
                      onClick={() => void handleRecordCouncilInsight()}
                      disabled={
                        councilInsightSaving ||
                        !(resolveCouncilInsightText()?.trim() ?? '')
                      }
                      className="w-full px-3 py-2 rounded-lg border border-stone-600 text-stone-200 hover:bg-stone-700/80 disabled:opacity-40 text-xs font-medium"
                      title="Persist council output as an append-only decision (no new VE entity row)"
                    >
                      {councilInsightSaving ? 'Recording…' : 'Record council insight'}
                    </button>
                    {councilInsightNotice ? (
                      <p className="text-[11px] text-stone-400">{councilInsightNotice}</p>
                    ) : null}
                  </div>
                ) : null}
                <div>
                  <div className="flex items-center justify-between gap-2 mb-2">
                    <label className="block text-xs text-stone-500 uppercase tracking-wide">
                      Seats <span className="text-stone-500 font-normal normal-case">({councilSelectedCount} / {councilMaxSeats})</span>
                    </label>
                  </div>
                  <div className="space-y-3">
                    <div className="rounded-xl border border-stone-700/80 bg-stone-900/45 p-3 min-w-0 overflow-x-auto">
                      <div className="flex flex-nowrap items-center justify-center gap-2.5 min-w-min px-0.5">
                        {councilSeatSlots.slice(0, councilMaxSeats).map((slot) => {
                          const perspective = slot.actorId
                            ? councilAgentList.find((x) => x.id === slot.actorId)
                            : null
                          const isFilled = slot.actorId != null
                          const isSelectedSeat = selectedCouncilSlotId === slot.id
                          const seatMandateForOrb = mandatesBySeatId[slot.id] ?? ''
                          const hasSeatMandate =
                            seatMandateForOrb !== '' && isKnownMandateId(seatMandateForOrb)
                          const orbStroke = mandateOrbStrokeStyle(hasSeatMandate ? seatMandateForOrb : null)
                          const mandateOrbGlow = mandateSeatOrbGlowClass(seatMandateForOrb || null)
                          return (
                            <button
                              key={slot.id}
                              type="button"
                              onClick={() => setSelectedCouncilSlotId(slot.id)}
                              onDoubleClick={() => applyCouncilSeatClear(slot.id)}
                              title={
                                perspective
                                  ? `${perspective.name} — ${perspective.role || iconHintFor(perspective)}. Double-click to clear this seat.`
                                  : 'Empty seat — choose an actor in the panel below (double-click to clear).'
                              }
                              style={orbStroke ?? undefined}
                              className={`relative inline-flex h-12 w-12 items-center justify-center rounded-full border transition-all ${
                                isSelectedSeat
                                  ? 'ring-2 ring-yellow-700/75 ring-offset-2 ring-offset-stone-900'
                                  : ''
                              } ${
                                isFilled
                                  ? `bg-stone-700${hasSeatMandate ? '' : ' text-stone-100'}`
                                  : `bg-stone-900/45${hasSeatMandate ? '' : ' text-stone-500'}`
                              } ${
                                hasSeatMandate
                                  ? 'border border-solid'
                                  : isFilled
                                    ? 'border-stone-400/75'
                                    : 'border-stone-600/70'
                              } ${
                                mandateOrbGlow ||
                                (!hasSeatMandate && isFilled
                                  ? 'shadow-[0_0_16px_rgba(164,132,74,0.18)]'
                                  : '')
                              } ${hasSeatMandate ? '' : 'hover:border-stone-300/70'}`}
                            >
                              {perspective ? (
                                <AvatarDisplay agent={perspective} size="sm" className="text-stone-200" />
                              ) : (
                                <span
                                  className={`text-[10px] font-medium ${hasSeatMandate ? '' : 'text-stone-500'}`}
                                  aria-hidden
                                >
                                  —
                                </span>
                              )}
                            </button>
                          )
                        })}
                        {!councilExpandedMode && (
                          <button
                            type="button"
                            className="inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-full border border-stone-600/70 bg-stone-900/45 text-stone-400 hover:text-stone-200 hover:border-stone-300/70 transition-colors"
                            title="Add more council seats (up to 7). May slow the system — longer runs and timeouts."
                            onClick={() => {
                              const ok = window.confirm(
                                'Expanding council seats may slow the system and cause longer runs/timeouts.\n\nContinue?',
                              )
                              if (ok) setCouncilExpandedMode(true)
                            }}
                          >
                            <span className="text-xl leading-none font-medium">+</span>
                          </button>
                        )}
                      </div>
                    </div>
                    {(() => {
                      const slot = councilSeatSlots.find((s) => s.id === selectedCouncilSlotId) ?? null
                      if (!slot) return null
                      const seatFilled = slot.actorId != null
                      const seatMandateId = mandatesBySeatId[slot.id] ?? ''
                      return (
                        <div className="rounded-xl border border-stone-700 bg-stone-900/55 p-3 space-y-3">
                          <div className="flex items-center justify-between gap-2">
                            <p className="text-[10px] uppercase tracking-wide text-stone-500">
                              Seat {councilSeatSlots.slice(0, councilMaxSeats).findIndex((s) => s.id === slot.id) + 1}
                            </p>
                            <button
                              type="button"
                              onClick={() => applyCouncilSeatClear(slot.id)}
                              className={`text-[10px] px-2 py-0.5 rounded border ${
                                seatFilled
                                  ? 'border-yellow-700/60 bg-yellow-900/30 text-yellow-200'
                                  : 'border-stone-600 text-stone-300 hover:text-stone-200'
                              }`}
                            >
                              {seatFilled ? 'Clear seat' : 'Empty'}
                            </button>
                          </div>

                          <div className="space-y-1.5">
                            <p className="text-[11px] uppercase tracking-wide text-stone-400">Role</p>
                            <p className="text-[10px] text-stone-500 leading-snug">
                              Seat job on the council — what question this seat answers (separate from actor).
                            </p>
                            <div className="flex items-center gap-2">
                              <span
                                className={`inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-transparent bg-stone-800/90 text-stone-400 ${mandateSeatIconAccentClass(seatMandateId || null)}`}
                                title="Seat role"
                              >
                                <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden>
                                  <path d="M6 20h12M8 17h8M7 17l-1.6-8 3.2 2.2L12 5l3.4 6.2L18.6 9 17 17" />
                                </svg>
                              </span>
                              <CouncilMandatePicker
                                idPrefix={`council-seat-${slot.id}`}
                                value={seatMandateId}
                                onChange={(id) =>
                                  setMandatesBySeatId((prev) => ({
                                    ...prev,
                                    [slot.id]: id,
                                  }))
                                }
                                mandates={BUILT_IN_MANDATES}
                              />
                            </div>
                          </div>

                          <div className="space-y-1.5 pb-1">
                            <p className="text-[11px] uppercase tracking-wide text-stone-400">Actor</p>
                            <p className="text-[10px] text-stone-500 leading-snug">
                              Saved actor that speaks from this seat (identity, values, style).
                            </p>
                            <CouncilPerspectivePicker
                              idPrefix={`council-perspective-${slot.id}`}
                              value={slot.actorId}
                              onChange={(perspectiveId) =>
                                setCouncilSeatSlots((prev) =>
                                  prev.map((s) => (s.id === slot.id ? { ...s, actorId: perspectiveId } : s)),
                                )
                              }
                              agents={councilAgentList}
                            />
                          </div>

                          <div className="space-y-1.5">
                            <p className="text-[11px] uppercase tracking-wide text-stone-400">Voiced by</p>
                            <div className="flex flex-wrap gap-1.5">
                              {councilLlmSelectOptions.map((o) => {
                                const selectedProvider = (councilSeatLlmById[slot.id] ?? 'ollama') === o.value
                                return (
                                  <button
                                    key={o.value}
                                    type="button"
                                    onClick={() => {
                                      setCouncilSeatLlmById((prev) => ({ ...prev, [slot.id]: o.value }))
                                      if (currentUser) {
                                        void saveCouncilSeatLlm(slot.id, o.value)
                                          .then((map) => setCouncilSeatLlmById(map))
                                          .catch(() => {})
                                      }
                                    }}
                                    className={`px-2.5 py-1 rounded-full text-[11px] border transition-colors ${
                                      selectedProvider
                                        ? 'border-yellow-700/65 bg-yellow-900/30 text-yellow-200'
                                        : 'border-stone-600 bg-stone-900 text-stone-300 hover:text-stone-200'
                                    }`}
                                    title={o.label}
                                  >
                                    {o.label}
                                  </button>
                                )
                              })}
                            </div>
                          </div>
                        </div>
                      )
                    })()}
                  </div>
                </div>
                  </div>
                </div>
              </div>
            </div>
          )}
          </div>
          {workoutExitToast ? (
            <div className="shrink-0 px-3 py-2 text-center text-xs text-stone-500 border-t border-stone-700 bg-stone-900/50">
              {workoutExitToast}
            </div>
          ) : null}
          <ZenafPresence brandCoreProfileId={brandCoreProfileId} onOpen={() => setMainView('perspectives')} />
          </div>
        </aside>
        )}
      </div>
    </div>
    </FocusInviteRunProvider>
    </VisionExecutionFocusProvider>
    </VisionExecutionGraphDataProvider>
    </VisionExecutionProfileGraphDataProvider>
    </DomainProvider>
  )
}

export default App
