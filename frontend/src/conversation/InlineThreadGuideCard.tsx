/**
 * Developmental / system guide in the main conversation thread — expand/collapse and actions stay inline.
 */
import type { VESelection } from '../vision-execution/VisionExecutionView'
import { SystemPromptActions } from '../developmentalGuidance/SystemPromptActions'
import { ephemeralGuidePromptIdFromContent } from '../vision-execution/promptSignalsApi'
import type { GuideThreadMessage } from '../developmentalGuidance/guideEntityStack'
import { resolveGuideQuestionMeta } from '../developmentalGuidance/guideQuestionDisplay'

type Props = {
  message: GuideThreadMessage
  mainView: string
  mapNodeKind: string | null
  veTypeHint: string | null
  mapNodeLabel: string | null
  nestAggregate: boolean
  formatSystemPromptContextTitle: (o: {
    mainView: string
    mapNodeKind: string | null
    veType: string | null
    nodeLabel: string | null
    nestAggregate: boolean
  }) => string
  veSelection: VESelection | null
  registerDeferContextForPrompt: (promptId: string) => void
  removeGuideRowsForPromptId: (promptId: string) => void
  dismissGuideFromThread: (promptId: string) => void
  markGuideInteracted: (promptId: string) => void
  hidePromptActionsForPromptId: (promptId: string) => void
  isExpanded: boolean
  isActiveConversationalSuggestion: boolean
  onShowInThread: () => void
  onCollapse: () => void
  onDiscussEngage: () => void
  /** Collapsed Discuss: same outcome as expanded (engage signal + hide strip) — parent supplies server call. */
  onDiscussFromCollapsed: () => void
  councilTextareaFocus: () => void
}

export function InlineThreadGuideCard({
  message: m,
  mainView,
  mapNodeKind,
  veTypeHint,
  mapNodeLabel,
  nestAggregate,
  formatSystemPromptContextTitle,
  veSelection,
  registerDeferContextForPrompt,
  removeGuideRowsForPromptId,
  dismissGuideFromThread,
  markGuideInteracted,
  hidePromptActionsForPromptId,
  isExpanded,
  isActiveConversationalSuggestion,
  onShowInThread,
  onCollapse,
  onDiscussEngage,
  onDiscussFromCollapsed,
  councilTextareaFocus,
}: Props) {
  const promptId = m.promptSignal?.promptId ?? ephemeralGuidePromptIdFromContent(m.content)
  const questionText = resolveGuideQuestionMeta(m).questionText
  const summary = questionText.length > 160 ? `${questionText.slice(0, 160)}…` : questionText

  const title =
    m.promptContextTitle ??
    formatSystemPromptContextTitle({
      mainView,
      mapNodeKind,
      veType: veTypeHint,
      nodeLabel: mapNodeLabel,
      nestAggregate,
    })

  return (
    <div
      className={[
        'rounded-lg px-3 py-2 text-sm bg-stone-900/70 text-stone-300 mx-1 border border-yellow-800/35 border-l-2 border-l-yellow-600/55',
        m.promptUiHidden ? ' opacity-50' : '',
        isActiveConversationalSuggestion && isExpanded ? ' ring-1 ring-amber-600/45 ring-offset-2 ring-offset-stone-900' : '',
      ].join('')}
      data-testid="inline-thread-guide"
    >
      <div className="mb-1">
        <p className="text-[10px] uppercase tracking-wide text-yellow-500/80 font-medium mb-0.5">Atria</p>
        <p className="text-xs font-semibold text-stone-100 leading-snug" data-testid="system-prompt-context-title">
          {title}
        </p>
      </div>
      {!isExpanded ? (
        <div className="space-y-1">
          <p className="text-xs text-stone-400 line-clamp-2">{summary}</p>
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            <button
              type="button"
              data-testid="inline-thread-guide-expand"
              className="text-[10px] text-amber-200/85 hover:underline"
              onClick={onShowInThread}
            >
              Show in thread
            </button>
            {!m.promptUiHidden ? (
              <button
                type="button"
                data-testid="inline-thread-guide-discuss"
                className="text-[10px] text-stone-500 hover:text-amber-200/90 hover:underline"
                onClick={onDiscussFromCollapsed}
              >
                Discuss
              </button>
            ) : null}
          </div>
        </div>
      ) : (
        <>
          <pre className="whitespace-pre-wrap font-sans text-xs text-stone-300 mb-2">{m.content}</pre>
          <button
            type="button"
            className="text-[10px] text-stone-500 hover:text-stone-300 mb-2"
            onClick={onCollapse}
          >
            Collapse
          </button>
          {!m.promptUiHidden ? (
            <SystemPromptActions
              promptId={promptId}
              summaryLine={questionText.slice(0, 400)}
              veSelection={veSelection}
              onDeferUi={() => registerDeferContextForPrompt(promptId)}
              onDeferRemoveFromThreadUi={() => removeGuideRowsForPromptId(promptId)}
              onDiscussUi={() => {
                markGuideInteracted(promptId)
                hidePromptActionsForPromptId(promptId)
              }}
              onDiscuss={() => {
                onDiscussEngage()
                councilTextareaFocus()
              }}
              onDismissUi={() => {
                markGuideInteracted(promptId)
                dismissGuideFromThread(promptId)
              }}
            />
          ) : null}
        </>
      )}
    </div>
  )
}
