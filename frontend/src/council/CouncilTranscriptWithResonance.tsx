import { useMemo } from 'react'
import { CouncilTranscript } from './CouncilTranscript'
import { sanitizeCouncilAssistantTextForDisplay } from './councilUserVisibleSanitize'
import { parseCouncilSeatSections } from './councilSeatSections'
import { ResonanceSlider } from '../components/ResonanceSlider'
import {
  formatPendingIntegrationUiPathLabel,
  type IntegrationCommitPayload,
  type PendingIntegrationPayload,
} from './synthesisIntegrity'
import type { EntityMentionOpenPayload } from '../components/EntityMentionText'

export type CouncilTranscriptWithResonanceProps = {
  text: string
  stripZenafSynthesis: boolean
  decorateSeatHeaders: boolean
  /** e.g. integrity run id or stable thread key */
  responseIdPrefix: string
  entityType: string
  entityId: string
  /**
   * When the transcript has no parsed multi-seat sections, still attach one slider
   * under the full message (single-voice / integrated replies).
   */
  integratedSeatId: string
  integratedContextKind: 'council_seat' | 'zenaf_training'
  /** When this turn wrote precision text to Vision & Execution (SSE `integration_commit`). */
  integrationCommit?: IntegrationCommitPayload | null
  /** Proposed VE write from this turn; cleared from thread when a later turn commits. */
  pendingIntegration?: PendingIntegrationPayload | null
  onOpenEntity?: (p: EntityMentionOpenPayload) => void
}

export function CouncilTranscriptWithResonance({
  text,
  stripZenafSynthesis,
  decorateSeatHeaders,
  responseIdPrefix,
  entityType,
  entityId,
  integratedSeatId,
  integratedContextKind,
  integrationCommit,
  pendingIntegration,
  onOpenEntity,
}: CouncilTranscriptWithResonanceProps) {
  const { preambleLines, sections } = useMemo(() => {
    const cleaned = sanitizeCouncilAssistantTextForDisplay(text)
    return parseCouncilSeatSections(cleaned, stripZenafSynthesis)
  }, [text, stripZenafSynthesis])

  const pendingPath =
    pendingIntegration?.integration_state === 'proposed'
      ? formatPendingIntegrationUiPathLabel(pendingIntegration)
      : ''
  const pendingStrip =
    integrationCommit?.status !== 'committed' &&
    pendingIntegration?.integration_state === 'proposed' &&
    pendingPath ? (
      <div
        className="mb-1.5 flex flex-wrap items-center gap-1.5 text-[10px] text-stone-400"
        title={`Will save to: ${pendingPath}`}
      >
        <span
          className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded border border-amber-800/50 text-[9px] text-amber-400/95"
          aria-hidden
        >
          ○
        </span>
        <span className="rounded border border-amber-900/45 bg-amber-950/20 px-1.5 py-0.5 font-medium text-amber-200/90">
          Pending save
        </span>
        <span className="max-w-[min(100%,18rem)] truncate text-stone-500">{pendingPath}</span>
      </div>
    ) : null

  const recordStrip =
    integrationCommit?.status === 'committed' ? (
      <>
        <div
          className="mb-1.5 flex flex-wrap items-center gap-1.5 text-[10px] text-stone-400"
          title={
            (integrationCommit.ui_path_label || '').trim()
              ? `Recorded to: ${integrationCommit.ui_path_label}`
              : 'Recorded to Vision & Execution'
          }
        >
          <span
            className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded border border-emerald-800/55 text-[9px] text-emerald-400/95"
            aria-hidden
          >
            ✓
          </span>
          <span className="rounded border border-stone-600/50 bg-stone-800/70 px-1.5 py-0.5 font-medium text-stone-300">
            Recorded
          </span>
          {(integrationCommit.ui_path_label || '').trim() ? (
            <span className="max-w-[min(100%,18rem)] truncate text-stone-500">{integrationCommit.ui_path_label}</span>
          ) : null}
        </div>
        {(integrationCommit.recorded_text || '').trim() ? (
          <div className="mb-2 rounded border border-emerald-900/40 bg-emerald-950/25 px-2 py-1.5 text-[11px] leading-snug text-emerald-100/90">
            {(integrationCommit.recorded_text || '').trim().slice(0, 800)}
            {(integrationCommit.recorded_text || '').trim().length > 800 ? '…' : ''}
          </div>
        ) : null}
      </>
    ) : null

  if (sections.length === 0) {
    const integratedResponseId = `${responseIdPrefix}-integrated`
    return (
      <div className="space-y-2">
        {pendingStrip}
        {recordStrip}
        <CouncilTranscript
          text={text}
          stripZenafSynthesis={stripZenafSynthesis}
          decorateSeatHeaders={decorateSeatHeaders}
          onOpenEntity={onOpenEntity}
        />
        <ResonanceSlider
          responseId={integratedResponseId}
          seatId={integratedSeatId}
          contextKind={integratedContextKind}
          entityType={entityType}
          entityId={entityId}
        />
      </div>
    )
  }

  const preambleText = preambleLines.join('\n')

  return (
    <div className="space-y-3">
      {pendingStrip}
      {recordStrip}
      {preambleText.trim() ? (
        <CouncilTranscript
          text={preambleText}
          stripZenafSynthesis={false}
          decorateSeatHeaders={decorateSeatHeaders}
          onOpenEntity={onOpenEntity}
        />
      ) : null}
      {sections.map((sec, idx) => {
        const block = `${sec.headerLine}\n${sec.bodyLines.join('\n')}`
        const responseId = `${responseIdPrefix}-${sec.mandateId}-${idx}`
        return (
          <div key={responseId} className="space-y-0">
            <CouncilTranscript
              text={block}
              stripZenafSynthesis={false}
              decorateSeatHeaders={decorateSeatHeaders}
              onOpenEntity={onOpenEntity}
            />
            <ResonanceSlider
              responseId={responseId}
              seatId={sec.mandateId}
              contextKind="council_seat"
              entityType={entityType}
              entityId={entityId}
            />
          </div>
        )
      })}
    </div>
  )
}
