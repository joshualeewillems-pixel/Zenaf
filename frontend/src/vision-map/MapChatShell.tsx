import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { MapNodePayload } from './ontology'
import { deriveBlockersMarkdown } from './blockersFromVe'
import type { ExecutionStep } from '../vision-execution/types'
import type { VisionMapEntityBundle } from './blockersFromVe'
import { explainTeacherMarkdown } from './mapCouncilActions'
import { assessNodeFlowAndChannels } from '../flow/assessNodeFlowAndChannels'
import { growthTriadCaption } from './mapGrowthMetrics'
import { MapGrowthTriad } from './MapGrowthTriad'
import type { GrowthTriadMetrics } from './mapGrowthMetrics'
import type { NestVitality } from './nesting'
import {
  buildGuidanceScriptForNode,
  buildStructureProposalFromAnswer,
  STRUCTURE_PROPOSAL_TARGET_FIELDS,
  type StructureProposal,
} from './guidanceScripts'
import { buildGuideOpeningMessage } from './guidanceConversationalSeed'
import type { VisionMapCouncilInteraction } from './visionMapCouncilInteraction'
import type { MapTriadDevelopmentalSnapshot } from '../developmentalGuidance/types'
import { MapTriadInspectorContent, type TriadInspectorSection } from './mapTriadInspector'
import { DeferredPromptTodosSection } from '../vision-execution/DeferredPromptTodosSection'
import { mapWorkspaceRemindersTitle } from '../developmentalGuidance/systemPromptTitle'
import { buildTriadSuggestedQuestion } from './triadConversationPrompts'
import { effectiveGrowthTriad } from './effectiveGrowthTriad'

type Props = {
  selected: MapNodePayload | null
  entityBundle: VisionMapEntityBundle | null
  /** Matches App council_preflight map triad — forwarded on seed for stable prompt_id. */
  developmentalSnapshotForPrompt?: MapTriadDevelopmentalSnapshot | null
  onClearSelection: () => void
  /** Current text in the left council question box — used for commit / continuity */
  councilQuestionDraft: string
  onVisionMapCouncilInteraction: (action: VisionMapCouncilInteraction) => void
  canNestSelected?: boolean
  canExpandSelected?: boolean
  onNestSelected?: () => void
  onExpandSelected?: () => void
  selectedNestMeta?: {
    memberCount: number
    kindCounts?: Partial<Record<MapNodePayload['kind'], number>>
    vitality?: NestVitality
  } | null
  growthTriadOverride?: GrowthTriadMetrics | null
  growthCaptionOverride?: string
  onGuidanceHarvestFeedback?: (nodeId: string) => void
  initiativeExecutionSteps?: ExecutionStep[] | null
  initiativeExecutionStepsLoading?: boolean
}

function growthKindLabel(kind: MapNodePayload['kind']): string {
  switch (kind) {
    case 'seed':
      return 'This seed'
    case 'tree':
      return 'This tree'
    case 'branch':
      return 'This branch'
    case 'flower':
      return 'This task'
    case 'fruit':
      return 'This outcome'
    default:
      return 'This item'
  }
}

type HarvestFieldKey =
  | 'outcome'
  | 'brief_summary'
  | 'blocker_risk'
  | 'next_step'
  | 'possible_project_task_split'

type HarvestFieldStatus = Record<HarvestFieldKey, boolean>

function computeStageFieldStatus(selected: MapNodePayload, proposal: StructureProposal | null): HarvestFieldStatus {
  const summary = selected.summaryLines.join(' ').toLowerCase()
  const subtitle = (selected.subtitle ?? '').toLowerCase()
  const text = `${subtitle} ${summary}`
  const fromExisting: HarvestFieldStatus = {
    outcome: /outcome|result|impact|deliver|ship/.test(text),
    brief_summary: subtitle.trim().length > 0 || selected.summaryLines.length > 0,
    blocker_risk: /risk|block|depend|constraint|unknown|warning/.test(text),
    next_step: /next|plan|start|ship|owner|check/.test(text),
    possible_project_task_split: /project|task|split|initiative|milestone/.test(text),
  }
  if (!proposal) return fromExisting
  return {
    outcome: fromExisting.outcome || proposal.outcome.trim().length > 0,
    brief_summary: fromExisting.brief_summary || proposal.brief_summary.trim().length > 0,
    blocker_risk: fromExisting.blocker_risk || proposal.blocker_risk.trim().length > 0,
    next_step: fromExisting.next_step || proposal.next_step.trim().length > 0,
    possible_project_task_split:
      fromExisting.possible_project_task_split || proposal.possible_project_task_split.some((item) => item.trim().length > 0),
  }
}

function completenessPct(status: HarvestFieldStatus): number {
  const values = Object.values(status)
  const completed = values.filter(Boolean).length
  return Math.round((completed / values.length) * 100)
}

function stageWeakAreaCopy(kind: MapNodePayload['kind'], dimension: 'water' | 'soil' | 'fruit'): string {
  if (kind === 'seed') {
    if (dimension === 'water') return 'Next: strengthen this seed with active stewardship and a near-term attention cadence.'
    if (dimension === 'soil') return 'To make this viable: tighten problem framing and boundaries for this seed.'
    return 'To strengthen this: produce a tiny proof artifact to test seed value.'
  }
  if (kind === 'tree') {
    if (dimension === 'water') return 'Next: strengthen this initiative with a clear ownership cadence across stakeholders.'
    if (dimension === 'soil') return 'To make this viable: sharpen initiative scope and dependency definition.'
    return 'To strengthen this: land a measurable milestone output this cycle.'
  }
  if (kind === 'branch') {
    if (dimension === 'water') return 'Next: reinforce this project with sustained week-to-week execution attention.'
    if (dimension === 'soil') return 'To make this viable: clarify acceptance criteria and key constraints.'
    return 'To strengthen this: ship a user-visible increment.'
  }
  return `Next: strengthen ${dimension} for this node.`
}

function clarifiedDimensionsFromProposal(proposal: StructureProposal | null): Array<'water' | 'soil' | 'fruit'> {
  if (!proposal) return []
  const set = new Set<'water' | 'soil' | 'fruit'>()
  if (proposal.brief_summary.trim()) set.add('soil')
  if (proposal.blocker_risk.trim()) set.add('soil')
  if (proposal.outcome.trim()) set.add('fruit')
  if (proposal.next_step.trim()) set.add('fruit')
  if (proposal.possible_project_task_split.some((item) => item.trim().length > 0)) set.add('fruit')
  return Array.from(set)
}

export function MapChatShell({
  selected,
  entityBundle,
  developmentalSnapshotForPrompt = null,
  onClearSelection,
  councilQuestionDraft,
  onVisionMapCouncilInteraction,
  canNestSelected = false,
  canExpandSelected = false,
  onNestSelected,
  onExpandSelected,
  selectedNestMeta,
  growthTriadOverride = null,
  growthCaptionOverride,
  onGuidanceHarvestFeedback,
  initiativeExecutionSteps = null,
  initiativeExecutionStepsLoading = false,
}: Props) {
  const [commitStructureNote, setCommitStructureNote] = useState<string | null>(null)
  const [structureProposal, setStructureProposal] = useState<StructureProposal | null>(null)
  const [proposalEditMode, setProposalEditMode] = useState(false)
  const [showHarvestSummary, setShowHarvestSummary] = useState(false)
  const [harvestBeforePct, setHarvestBeforePct] = useState(0)
  const [harvestAfterPct, setHarvestAfterPct] = useState(0)
  const [harvestDisplayPct, setHarvestDisplayPct] = useState(0)
  const [triadSection, setTriadSection] = useState<TriadInspectorSection>('soil')

  const lastSeededSelectionIdRef = useRef<string | null>(null)
  const lastTriadPromptKeyRef = useRef<string | null>(null)
  const triadSameKeyClicksRef = useRef(0)
  const lastTriadPrefillRef = useRef<string | null>(null)
  const councilInteractRef = useRef(onVisionMapCouncilInteraction)
  councilInteractRef.current = onVisionMapCouncilInteraction
  const devSnapshotRef = useRef(developmentalSnapshotForPrompt)
  devSnapshotRef.current = developmentalSnapshotForPrompt

  useEffect(() => {
    lastSeededSelectionIdRef.current = null
    lastTriadPromptKeyRef.current = null
    triadSameKeyClicksRef.current = 0
    lastTriadPrefillRef.current = null
    setCommitStructureNote(null)
    setStructureProposal(null)
    setProposalEditMode(false)
    setShowHarvestSummary(false)
    setHarvestBeforePct(0)
    setHarvestAfterPct(0)
    setHarvestDisplayPct(0)
    setTriadSection('soil')
  }, [selected?.ref.id, selected?.ref.veType])

  const unifiedAssessment = useMemo(() => {
    if (!selected) return null
    return assessNodeFlowAndChannels(selected, { bundle: entityBundle, councilRuns: [] })
  }, [selected, entityBundle])

  const interpretation = unifiedAssessment?.interpretation ?? null

  const growthTriad = useMemo(() => {
    if (growthTriadOverride) return growthTriadOverride
    if (unifiedAssessment) return unifiedAssessment.derived.map_visual_triad
    return selected ? effectiveGrowthTriad(selected, entityBundle) : null
  }, [growthTriadOverride, unifiedAssessment, selected, entityBundle])

  /** Map-side flow read — same path as invite ranking (`deriveFocusInvites`). */
  const flowRead = unifiedAssessment?.flow ?? null

  const growthCaption = useMemo(
    () =>
      growthCaptionOverride ??
      (flowRead?.trunkSummary ??
        interpretation?.summary ??
        (selected && growthTriad ? growthTriadCaption(growthTriad, growthKindLabel(selected.kind)) : '')),
    [growthCaptionOverride, flowRead?.trunkSummary, interpretation?.summary, selected, growthTriad],
  )
  const guidanceScript = useMemo(
    () => (selected && growthTriad ? buildGuidanceScriptForNode(selected, growthTriad) : null),
    [selected, growthTriad],
  )

  const onTriadSegmentClick = useCallback(
    (section: TriadInspectorSection) => {
      if (!selected) return
      const key = `${selected.ref.veType}:${selected.ref.id}:${section}`
      if (lastTriadPromptKeyRef.current !== key) {
        lastTriadPromptKeyRef.current = key
        triadSameKeyClicksRef.current = 0
      } else {
        triadSameKeyClicksRef.current += 1
      }
      setTriadSection(section)
      const text = buildTriadSuggestedQuestion(
        selected,
        entityBundle,
        growthTriad,
        section,
        triadSameKeyClicksRef.current,
      )
      const draft = councilQuestionDraft.trim()
      if (!draft || draft === lastTriadPrefillRef.current?.trim()) {
        lastTriadPrefillRef.current = text
        onVisionMapCouncilInteraction({ type: 'suggest_council_prefill', text })
      } else {
        onVisionMapCouncilInteraction({ type: 'focus_council_input' })
      }
    },
    [selected, entityBundle, growthTriad, councilQuestionDraft, onVisionMapCouncilInteraction],
  )

  useEffect(() => {
    if (!selected) {
      lastSeededSelectionIdRef.current = null
      return
    }
    const id = selected.ref.id
    if (lastSeededSelectionIdRef.current === id) return
    lastSeededSelectionIdRef.current = id
    const triad = growthTriad
    const script = triad ? buildGuidanceScriptForNode(selected, triad) : null
    const guide = buildGuideOpeningMessage(selected, triad, script)
    const blockersExtra = deriveBlockersMarkdown(selected.ref, entityBundle).trim()
    const teacherExtra = explainTeacherMarkdown(selected).trim()
    const extras: string[] = []
    if (blockersExtra) {
      extras.push(['**Possible sticking points** (from your plan data)', '', blockersExtra].join('\n'))
    }
    if (teacherExtra) {
      extras.push(
        [
          '**If a recent review pass changed the answer**',
          '',
          teacherExtra,
          '',
          'Ask in chat if you want help interpreting this.',
        ].join('\n'),
      )
    }
    councilInteractRef.current({
      type: 'seed',
      payload: selected,
      guideTexts: [guide, ...extras],
      resetThread: true,
      developmentalSnapshotForPrompt: devSnapshotRef.current,
    })
    const u = assessNodeFlowAndChannels(selected, { bundle: entityBundle, councilRuns: [] })
    if (u.interpretation?.stance === 'clarify_first' && u.interpretation.chatPrefill.trim()) {
      councilInteractRef.current({
        type: 'suggest_council_prefill',
        text: u.interpretation.chatPrefill,
      })
    }
  }, [selected, growthTriad, entityBundle])

  const runGuidanceAction = (action: NonNullable<typeof guidanceScript>['suggested_actions'][number]) => {
    if (!selected || !guidanceScript) return
    if (action.kind === 'ask_user') {
      setCommitStructureNote(null)
      setStructureProposal(null)
      setProposalEditMode(false)
      onVisionMapCouncilInteraction({ type: 'focus_council_input' })
      return
    }
    if (action.kind === 'ask_council') {
      const sharedQuestion = guidanceScript.next_best_question || action.question || ''
      const councilQuestion = [
        "Let's get a second perspective on this.",
        '',
        'Use the guide and any replies in the thread for context.',
        '',
        `Focus question: ${sharedQuestion}`,
        '',
        action.councilPrompt ?? 'Offer concrete recommendations and tradeoffs we can execute this week.',
      ].join('\n')
      onVisionMapCouncilInteraction({ type: 'run_council', payload: selected, question: councilQuestion })
      return
    }
    const sharedQuestion = guidanceScript.next_best_question || ''
    const answer = councilQuestionDraft.trim()
    if (!answer) {
      setCommitStructureNote('Add your answer in the conversation on the left, then commit to structure.')
      onVisionMapCouncilInteraction({ type: 'focus_council_input' })
      return
    }
    const proposal = buildStructureProposalFromAnswer(
      selected,
      sharedQuestion || guidanceScript?.next_best_question || '',
      answer,
    )
    setStructureProposal(proposal)
    setProposalEditMode(false)
    if (selected.kind === 'seed' || selected.kind === 'tree' || selected.kind === 'branch') {
      const beforeStatus = computeStageFieldStatus(selected, null)
      const afterStatus = computeStageFieldStatus(selected, proposal)
      const beforePct = completenessPct(beforeStatus)
      const afterPct = completenessPct(afterStatus)
      setHarvestBeforePct(beforePct)
      setHarvestAfterPct(afterPct)
      setHarvestDisplayPct(beforePct)
      setShowHarvestSummary(true)
      if (onGuidanceHarvestFeedback) onGuidanceHarvestFeedback(selected.ref.id)
    }
    setCommitStructureNote(
      'Structured proposal ready. Review, edit if needed, then apply.',
    )
  }

  const updateStructureProposalField = (field: keyof StructureProposal, value: string) => {
    setStructureProposal((prev) => {
      if (!prev) return prev
      if (field === 'possible_project_task_split') {
        const nextSplit = value
          .split('\n')
          .map((line) => line.trim())
          .filter(Boolean)
          .slice(0, 5)
        return { ...prev, possible_project_task_split: nextSplit }
      }
      return { ...prev, [field]: value }
    })
  }

  const applyStructureProposal = () => {
    if (!selected || !structureProposal) return
    const sharedQuestion = guidanceScript?.next_best_question || ''
    const structurePrompt = [
      'Use this structured proposal as the mapping draft for VE fields. Do not auto-commit; just validate and refine.',
      sharedQuestion ? `Question: ${sharedQuestion}` : '',
      councilQuestionDraft.trim() ? `Answer draft: ${councilQuestionDraft.trim()}` : '',
      `Outcome: ${structureProposal.outcome}`,
      `Brief/Summary: ${structureProposal.brief_summary}`,
      `Blocker/Risk: ${structureProposal.blocker_risk}`,
      `Next step: ${structureProposal.next_step}`,
      `Possible project/task split: ${structureProposal.possible_project_task_split.join(' | ')}`,
    ].join('\n')
    onVisionMapCouncilInteraction({ type: 'run_council', payload: selected, question: structurePrompt })
    setCommitStructureNote('Proposal applied to council context. Tables remain unchanged until explicit manual updates.')
    if (onGuidanceHarvestFeedback) onGuidanceHarvestFeedback(selected.ref.id)
  }

  useEffect(() => {
    if (!showHarvestSummary) return
    const from = harvestBeforePct
    const to = harvestAfterPct
    if (to === from) {
      setHarvestDisplayPct(to)
      return
    }
    const durationMs = 600
    const start = performance.now()
    let raf = 0
    const step = (now: number) => {
      const progress = Math.min(1, (now - start) / durationMs)
      const eased = 1 - Math.pow(1 - progress, 2)
      const next = Math.round(from + (to - from) * eased)
      setHarvestDisplayPct(next)
      if (progress < 1) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [showHarvestSummary, harvestBeforePct, harvestAfterPct])

  const commitStructureAction = useMemo(
    () => guidanceScript?.suggested_actions.find((a) => a.kind === 'commit_structure'),
    [guidanceScript],
  )

  const harvestWeakAreasBlock = useMemo(() => {
    if (!selected || !structureProposal || !guidanceScript?.missing_dimensions.length) return null
    const clarified = clarifiedDimensionsFromProposal(structureProposal)
    const missing = [...guidanceScript.missing_dimensions]
    const primary = missing.find((dimension) => clarified.includes(dimension)) ?? missing[0]
    const secondary = missing.filter((dimension) => dimension !== primary)
    const emphasizedByClarified = Boolean(
      primary && clarified.includes(primary) && missing.includes(primary),
    )
    const transitionLead = emphasizedByClarified
      ? ['Now that this is clearer, next', 'With that clarified, next', 'To build on this, next'][
          (selected.ref.id.length + (primary?.length ?? 0)) % 3
        ]
      : 'Next'
    return (
      <div className="space-y-1 text-xs">
        <div className="text-[10px] uppercase text-stone-500">Remaining weak areas</div>
        <div className="space-y-1">
          {primary ? (
            <div
              key={`harvest-primary-${primary}`}
              className="text-[11px] px-2 py-1 rounded-md border border-stone-500/90 bg-stone-900/85 text-stone-100 font-medium"
            >
              <span className="text-stone-300">{transitionLead}: </span>
              {stageWeakAreaCopy(selected.kind, primary).replace(/^Next:\s*/i, '')}
            </div>
          ) : null}
          {secondary.map((dimension) => (
            <div
              key={`harvest-secondary-${dimension}`}
              className="text-[10px] px-2 py-1 rounded-md border border-stone-700/70 bg-stone-900/50 text-stone-400"
            >
              {stageWeakAreaCopy(selected.kind, dimension)}
            </div>
          ))}
        </div>
      </div>
    )
  }, [structureProposal, guidanceScript, selected])

  return (
    <aside
      data-testid="vision-map-inspector"
      className="map-ui-panel flex flex-col h-full min-h-0 w-full lg:w-[360px] lg:shrink-0 border-t lg:border-t-0 lg:border-l border-stone-800/90 bg-stone-950/85 backdrop-blur-md shadow-[-12px_0_40px_rgba(39,36,31,0.35)]"
    >
      <div className="px-4 py-3 border-b border-stone-700 flex items-start justify-between gap-2 min-w-0">
        <div className="min-w-0 flex-1 pr-2">
          <h2
            data-testid="vision-map-selected-title"
            className="text-sm font-semibold text-stone-100 truncate"
            title={selected?.label}
          >
            {selected?.label?.trim() || 'Vision map'}
          </h2>
          {selected ? (
            <p className="text-[10px] text-stone-500 truncate mt-0.5" title={selected.subtitle}>
              {growthKindLabel(selected.kind)}
              {selected.subtitle?.trim() ? ` · ${selected.subtitle.trim()}` : ''}
            </p>
          ) : (
            <p className="text-[10px] text-stone-500 mt-0.5">Select a node to open its workspace here</p>
          )}
        </div>
        {selected && (
          <button
            type="button"
            onClick={onClearSelection}
            className="shrink-0 h-8 w-8 flex items-center justify-center rounded-lg border border-stone-600 text-stone-400 hover:text-stone-100 hover:bg-stone-800 text-lg leading-none"
            aria-label="Clear map selection"
          >
            ×
          </button>
        )}
      </div>

      {!selected ? (
        <div className="p-4 text-sm text-stone-500 flex-1">
          Select something on the map. Your conversation stays in the main chat.
        </div>
      ) : (
        <div className="flex-1 min-h-0 flex flex-col">
          <div className="px-3 py-2 flex flex-wrap gap-1.5 border-b border-stone-800">
            <button
              type="button"
              onClick={() => onVisionMapCouncilInteraction({ type: 'focus_council_input' })}
              className="text-[11px] px-2 py-1 rounded bg-yellow-800/80 hover:bg-yellow-700 text-stone-50 font-medium"
            >
              Open chat
            </button>
            {canNestSelected && onNestSelected ? (
              <button
                type="button"
                onClick={onNestSelected}
                className="text-[11px] px-2 py-1 rounded bg-stone-800 border border-stone-600 hover:bg-stone-700"
              >
                Nest group
              </button>
            ) : null}
            {canExpandSelected && onExpandSelected ? (
              <button
                type="button"
                onClick={onExpandSelected}
                className="text-[11px] px-2 py-1 rounded bg-stone-800 border border-stone-600 hover:bg-stone-700"
              >
                Expand group
              </button>
            ) : null}
          </div>

          <div className="flex-1 min-h-0 overflow-auto p-4 space-y-4 text-sm">
            <>
                {growthTriad ? (
                  <MapGrowthTriad
                    metrics={growthTriad}
                    caption={growthCaption}
                    activeSegment={triadSection}
                    onSegmentClick={onTriadSegmentClick}
                  />
                ) : null}
                {unifiedAssessment ? (
                  <div
                    data-testid="map-maintenance-readout"
                    className="rounded-lg border border-stone-800 bg-stone-900/50 px-3 py-2 space-y-1"
                  >
                    <div className="text-[10px] uppercase tracking-wide text-stone-500">Maintenance readout</div>
                    <p className="text-[11px] text-stone-400 leading-snug">
                      <span className="text-stone-500">Weakest channel:</span>{' '}
                      <span data-testid="map-lowest-channel" className="text-stone-200">
                        {unifiedAssessment.lowest_channel}
                      </span>
                      <span className="text-stone-600"> · </span>
                      <span className="text-stone-500">Dominant issue:</span>{' '}
                      <span data-testid="map-dominant-issue" className="text-stone-200">
                        {unifiedAssessment.flow.dominantIssue}
                      </span>
                      <span className="text-stone-600"> · </span>
                      <span className="text-stone-500">Clean stone:</span>{' '}
                      <span data-testid="map-clean-stone-ready" className="text-stone-200">
                        {unifiedAssessment.clean_stone_ready ? 'yes' : 'no'}
                      </span>
                    </p>
                    <p className="text-[10px] text-stone-600 leading-snug">
                      Aligns map chrome, this panel, and invite ranking via <code className="text-stone-500">assessNodeFlowAndChannels</code>
                      (rules v{unifiedAssessment.rules_version}).
                    </p>
                  </div>
                ) : null}
                <MapTriadInspectorContent
                  selected={selected}
                  bundle={entityBundle}
                  section={triadSection}
                  onOpenInVisionExecution={() =>
                    onVisionMapCouncilInteraction({ type: 'open_inspected_in_ve', node: selected })
                  }
                  initiativeExecutionSteps={initiativeExecutionSteps}
                  initiativeExecutionStepsLoading={initiativeExecutionStepsLoading}
                />
                {interpretation || guidanceScript ? (
                  <div className="rounded-lg border border-stone-700/70 bg-stone-900/25 px-3 py-2.5 space-y-2">
                    <div className="text-[10px] uppercase tracking-wide text-stone-500">
                      {interpretation?.stance === 'clarify_first' ? 'Clarify first' : 'Best next step'}
                    </div>
                    {interpretation?.stance === 'clarify_first' && interpretation.clarificationQuestion ? (
                      <p data-testid="map-clarification-question" className="text-xs text-stone-200 leading-relaxed">
                        {interpretation.clarificationQuestion}
                      </p>
                    ) : interpretation ? (
                      <div className="space-y-1.5">
                        <p data-testid="map-interpretation-action-line" className="text-xs text-stone-200 leading-relaxed">
                          {interpretation.actionLine}
                        </p>
                        <p
                          data-testid="map-interpretation-chat-prefill"
                          className="text-[11px] text-stone-500 leading-relaxed"
                        >
                          Suggested in chat: {interpretation.chatPrefill}
                        </p>
                      </div>
                    ) : guidanceScript ? (
                      <p data-testid="map-best-next-step" className="text-xs text-stone-200 leading-relaxed">
                        {guidanceScript.next_best_question}
                      </p>
                    ) : null}
                    <div className="flex flex-wrap gap-1.5">
                      <button
                        type="button"
                        onClick={() => onVisionMapCouncilInteraction({ type: 'focus_council_input' })}
                        className="text-[11px] px-2 py-1 rounded-md border border-stone-600 bg-stone-800/80 hover:bg-stone-700 text-stone-200"
                      >
                        Discuss in chat
                      </button>
                      {commitStructureAction && councilQuestionDraft.trim() ? (
                        <button
                          type="button"
                          onClick={() => runGuidanceAction(commitStructureAction)}
                          className="text-[11px] px-2 py-1 rounded-md border border-stone-600/90 bg-stone-900/60 hover:bg-stone-800 text-stone-300"
                        >
                          Draft structure from chat answer
                        </button>
                      ) : null}
                    </div>
                    {guidanceScript?.optional_assessment ? (
                      <p className="text-[10px] text-stone-500 leading-snug">{guidanceScript.optional_assessment}</p>
                    ) : null}
                    {commitStructureNote ? <p className="text-[11px] text-stone-400">{commitStructureNote}</p> : null}
                    {structureProposal ? (
                      <div className="rounded-lg border border-stone-700 bg-stone-900/70 p-3 space-y-2.5">
                        <div className="flex items-center justify-between gap-2">
                          <div className="text-[10px] uppercase text-stone-500">Structure proposal preview</div>
                          <div className="flex items-center gap-1.5">
                            <button
                              type="button"
                              onClick={applyStructureProposal}
                              className="text-[10px] px-2 py-1 rounded border border-emerald-700/70 bg-emerald-900/30 hover:bg-emerald-800/35 text-emerald-100"
                            >
                              Apply
                            </button>
                            <button
                              type="button"
                              onClick={() => setProposalEditMode((prev) => !prev)}
                              className="text-[10px] px-2 py-1 rounded border border-stone-600 bg-stone-800 hover:bg-stone-700 text-stone-200"
                            >
                              {proposalEditMode ? 'Done' : 'Edit'}
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                setStructureProposal(null)
                                setProposalEditMode(false)
                                setCommitStructureNote('Proposal dismissed.')
                              }}
                              className="text-[10px] px-2 py-1 rounded border border-stone-700 bg-stone-900 hover:bg-stone-800 text-stone-300"
                            >
                              Dismiss
                            </button>
                          </div>
                        </div>

                        <div className="space-y-2 text-xs text-stone-300">
                          <label className="block">
                            <div className="flex items-center justify-between gap-2 mb-1">
                              <div className="text-[10px] uppercase text-stone-500">Outcome</div>
                              <code className="text-[10px] text-yellow-200/85">
                                {STRUCTURE_PROPOSAL_TARGET_FIELDS.outcome}
                              </code>
                            </div>
                            {proposalEditMode ? (
                              <input
                                value={structureProposal.outcome}
                                onChange={(event) => updateStructureProposalField('outcome', event.target.value)}
                                className="w-full rounded bg-stone-950 border border-stone-700 px-2 py-1.5 text-xs text-stone-200"
                              />
                            ) : (
                              <p>{structureProposal.outcome}</p>
                            )}
                          </label>

                          <label className="block">
                            <div className="flex items-center justify-between gap-2 mb-1">
                              <div className="text-[10px] uppercase text-stone-500">Brief/Summary</div>
                              <code className="text-[10px] text-yellow-200/85">
                                {STRUCTURE_PROPOSAL_TARGET_FIELDS.brief_summary}
                              </code>
                            </div>
                            {proposalEditMode ? (
                              <textarea
                                rows={2}
                                value={structureProposal.brief_summary}
                                onChange={(event) => updateStructureProposalField('brief_summary', event.target.value)}
                                className="w-full rounded bg-stone-950 border border-stone-700 px-2 py-1.5 text-xs text-stone-200 resize-y"
                              />
                            ) : (
                              <p>{structureProposal.brief_summary}</p>
                            )}
                          </label>

                          <label className="block">
                            <div className="flex items-center justify-between gap-2 mb-1">
                              <div className="text-[10px] uppercase text-stone-500">Blocker/Risk</div>
                              <code className="text-[10px] text-yellow-200/85">
                                {STRUCTURE_PROPOSAL_TARGET_FIELDS.blocker_risk}
                              </code>
                            </div>
                            {proposalEditMode ? (
                              <textarea
                                rows={2}
                                value={structureProposal.blocker_risk}
                                onChange={(event) => updateStructureProposalField('blocker_risk', event.target.value)}
                                className="w-full rounded bg-stone-950 border border-stone-700 px-2 py-1.5 text-xs text-stone-200 resize-y"
                              />
                            ) : (
                              <p>{structureProposal.blocker_risk}</p>
                            )}
                          </label>

                          <label className="block">
                            <div className="flex items-center justify-between gap-2 mb-1">
                              <div className="text-[10px] uppercase text-stone-500">Next step</div>
                              <code className="text-[10px] text-yellow-200/85">
                                {STRUCTURE_PROPOSAL_TARGET_FIELDS.next_step}
                              </code>
                            </div>
                            {proposalEditMode ? (
                              <input
                                value={structureProposal.next_step}
                                onChange={(event) => updateStructureProposalField('next_step', event.target.value)}
                                className="w-full rounded bg-stone-950 border border-stone-700 px-2 py-1.5 text-xs text-stone-200"
                              />
                            ) : (
                              <p>{structureProposal.next_step}</p>
                            )}
                          </label>

                          <label className="block">
                            <div className="flex items-center justify-between gap-2 mb-1">
                              <div className="text-[10px] uppercase text-stone-500">Possible project/task split</div>
                              <code className="text-[10px] text-yellow-200/85">
                                {STRUCTURE_PROPOSAL_TARGET_FIELDS.possible_project_task_split}
                              </code>
                            </div>
                            {proposalEditMode ? (
                              <textarea
                                rows={3}
                                value={structureProposal.possible_project_task_split.join('\n')}
                                onChange={(event) =>
                                  updateStructureProposalField('possible_project_task_split', event.target.value)
                                }
                                className="w-full rounded bg-stone-950 border border-stone-700 px-2 py-1.5 text-xs text-stone-200 resize-y"
                              />
                            ) : (
                              <ul className="list-disc pl-4 space-y-0.5">
                                {structureProposal.possible_project_task_split.map((item, index) => (
                                  <li key={`${item}-${index}`}>{item}</li>
                                ))}
                              </ul>
                            )}
                          </label>
                        </div>
                      </div>
                    ) : null}
                    {structureProposal && showHarvestSummary ? (
                      <div className="rounded-lg border border-emerald-800/45 bg-emerald-950/15 p-3 space-y-2.5">
                        <div className="text-[10px] uppercase text-emerald-300/85 tracking-wide">
                          Conversation harvest
                        </div>
                        <div className="flex items-center gap-3">
                          <div
                            className="h-12 w-12 rounded-full grid place-items-center text-[11px] font-semibold text-emerald-100 border border-emerald-700/60"
                            style={{
                              background: `conic-gradient(rgba(52,211,153,0.65) ${harvestDisplayPct * 3.6}deg, rgba(51,65,85,0.45) 0deg)`,
                            }}
                          >
                            {harvestDisplayPct}%
                          </div>
                          <div className="text-xs text-stone-300 leading-relaxed">
                            <div>
                              Completed before this conversation: <span className="text-stone-200">{harvestBeforePct}%</span>
                            </div>
                            <div>
                              Completed after this conversation: <span className="text-emerald-200">{harvestAfterPct}%</span>
                            </div>
                          </div>
                        </div>

                        <div className="space-y-1 text-xs">
                          <div className="text-[10px] uppercase text-stone-500">What was clarified</div>
                          <ul className="list-disc pl-4 text-stone-300 space-y-0.5">
                            {structureProposal.outcome ? <li>Outcome</li> : null}
                            {structureProposal.brief_summary ? <li>Brief summary</li> : null}
                            {structureProposal.blocker_risk ? <li>Blocker/risk</li> : null}
                            {structureProposal.next_step ? <li>Next step</li> : null}
                            {structureProposal.possible_project_task_split.length > 0 ? <li>Possible split</li> : null}
                          </ul>
                        </div>

                        <div className="space-y-1 text-xs">
                          <div className="text-[10px] uppercase text-stone-500">Where it would go</div>
                          <ul className="list-disc pl-4 text-stone-300 space-y-0.5">
                            <li>Outcome → <code>{STRUCTURE_PROPOSAL_TARGET_FIELDS.outcome}</code></li>
                            <li>Brief summary → <code>{STRUCTURE_PROPOSAL_TARGET_FIELDS.brief_summary}</code></li>
                            <li>Blocker/risk → <code>{STRUCTURE_PROPOSAL_TARGET_FIELDS.blocker_risk}</code></li>
                            <li>Next step → <code>{STRUCTURE_PROPOSAL_TARGET_FIELDS.next_step}</code></li>
                            <li>Possible split → <code>{STRUCTURE_PROPOSAL_TARGET_FIELDS.possible_project_task_split}</code></li>
                          </ul>
                        </div>

                        {guidanceScript?.missing_dimensions.length ? harvestWeakAreasBlock : null}

                        <div className="flex flex-wrap gap-1.5 pt-1">
                          <button
                            type="button"
                            onClick={applyStructureProposal}
                            className="text-[10px] px-2 py-1 rounded border border-emerald-700/70 bg-emerald-900/30 hover:bg-emerald-800/35 text-emerald-100"
                          >
                            Apply changes
                          </button>
                          <button
                            type="button"
                            onClick={() => setCommitStructureNote('Harvest kept as draft. Nothing committed.')}
                            className="text-[10px] px-2 py-1 rounded border border-stone-600 bg-stone-800 hover:bg-stone-700 text-stone-200"
                          >
                            Keep as draft
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              setCommitStructureNote('Continuing conversation. Refine your answer in the chat on the left, then re-harvest when ready.')
                              onVisionMapCouncilInteraction({ type: 'focus_council_input' })
                            }}
                            className="text-[10px] px-2 py-1 rounded border border-stone-700 bg-stone-900 hover:bg-stone-800 text-stone-300"
                          >
                            Continue conversation
                          </button>
                        </div>
                      </div>
                    ) : null}
                  </div>
                ) : null}

                {selectedNestMeta ? (
                  <div
                    className={[
                      'text-[11px] text-stone-400 border-l-2 pl-2',
                      selectedNestMeta.vitality?.dry
                        ? 'border-red-900/50 text-stone-500'
                        : selectedNestMeta.vitality?.lush
                          ? 'border-emerald-800/50 text-stone-300'
                          : 'border-stone-700/80',
                    ]
                      .filter(Boolean)
                      .join(' ')}
                  >
                    Group:{' '}
                    <span className="text-stone-300">
                      {selectedNestMeta.kindCounts?.branch ?? 0} projects ·{' '}
                      {selectedNestMeta.kindCounts?.flower ?? 0} tasks ·{' '}
                      {selectedNestMeta.kindCounts?.fruit ?? 0} outcomes
                    </span>{' '}
                    <span className="text-stone-500">({selectedNestMeta.memberCount} total)</span>
                  </div>
                ) : null}
                <DeferredPromptTodosSection
                  entityType="workspace"
                  entityId="vision_map"
                  contextTitle={mapWorkspaceRemindersTitle(selected?.label)}
                />
            </>
          </div>
        </div>
      )}
    </aside>
  )
}
