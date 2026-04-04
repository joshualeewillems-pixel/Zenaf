/**
 * One stacked notification bar per active entity, embedded in the main conversation thread.
 * Questions are grouped by origin (framing, risks, etc.); full guide body stays behind "Show in thread".
 */
import { useMemo } from 'react'
import type { VESelection } from '../vision-execution/VisionExecutionView'
import { SystemPromptActions } from '../developmentalGuidance/SystemPromptActions'
import { ephemeralGuidePromptIdFromContent } from '../vision-execution/promptSignalsApi'
import type { GuideThreadMessage } from '../developmentalGuidance/guideEntityStack'
import {
  GUIDE_QUESTION_ORIGIN_LABEL,
  GUIDE_QUESTION_ORIGIN_ORDER,
  resolveGuideQuestionMeta,
} from '../developmentalGuidance/guideQuestionDisplay'

type Props = {
  barSubtitle: string
  guides: GuideThreadMessage[]
  getPromptId: (m: GuideThreadMessage) => string
  seenPromptIds: string[]
  onMarkSeen: (promptId: string) => void
  listOpen: boolean
  onToggleList: () => void
  nestedExpandedPromptId: string | null
  onSetNestedExpandedPromptId: (id: string | null) => void
  veSelection: VESelection | null
  activeConversationalSuggestionPromptId: string | null
  onCollapseItem: (promptId: string) => void
  /** Focus council with question-specific prefill; does not hide actions or post engage signal. */
  onFocusQuestion: (stackRowId: string, questionText: string) => void
  onDiscussEngage: (stackRowId: string, questionText: string) => void
  onDiscussFromCollapsed: (stackRowId: string, questionText: string, canonicalPromptId: string) => void
  registerDeferContextForPrompt: (promptId: string) => void
  removeGuideRowsForPromptId: (stackRowId: string) => void
  dismissGuideFromThread: (stackRowId: string) => void
  markGuideInteracted: (promptId: string) => void
  hidePromptActionsForPromptId: (stackRowId: string) => void
  councilTextareaFocus: () => void
}

export function ThreadInlineGuideStack({
  barSubtitle,
  guides,
  getPromptId,
  seenPromptIds,
  onMarkSeen,
  listOpen,
  onToggleList,
  nestedExpandedPromptId,
  onSetNestedExpandedPromptId,
  veSelection,
  activeConversationalSuggestionPromptId,
  onCollapseItem,
  onFocusQuestion,
  onDiscussEngage,
  onDiscussFromCollapsed,
  registerDeferContextForPrompt,
  removeGuideRowsForPromptId,
  dismissGuideFromThread,
  markGuideInteracted,
  hidePromptActionsForPromptId,
  councilTextareaFocus,
}: Props) {
  const unreadCount = guides.filter((g) => !seenPromptIds.includes(getPromptId(g))).length
  const total = guides.length
  const hasUnread = unreadCount > 0

  const barLabel =
    hasUnread && unreadCount === 1
      ? `🔔 1 new question — ${barSubtitle}`
      : hasUnread
        ? `🔔 ${unreadCount} new questions — ${barSubtitle}`
        : total === 1
          ? `🔔 1 question — ${barSubtitle}`
          : `🔔 ${total} questions — ${barSubtitle}`

  const grouped = useMemo(() => {
    const byOrigin = new Map<string, GuideThreadMessage[]>()
    for (const g of guides) {
      const { origin } = resolveGuideQuestionMeta(g)
      const list = byOrigin.get(origin) ?? []
      list.push(g)
      byOrigin.set(origin, list)
    }
    return GUIDE_QUESTION_ORIGIN_ORDER.filter((o) => (byOrigin.get(o)?.length ?? 0) > 0).map((origin) => ({
      origin,
      label: GUIDE_QUESTION_ORIGIN_LABEL[origin],
      items: byOrigin.get(origin)!,
    }))
  }, [guides])

  const canonicalPromptId = (m: GuideThreadMessage) =>
    m.promptSignal?.promptId ?? ephemeralGuidePromptIdFromContent(m.content)

  if (total === 0) return null

  return (
    <div
      className="rounded-lg border border-stone-700/90 mx-1 overflow-hidden bg-stone-950/40"
      data-testid="guide-notification-stack"
    >
      <button
        type="button"
        data-testid="guide-notification-stack-bar"
        aria-expanded={listOpen}
        onClick={() => onToggleList()}
        className={[
          'w-full text-left px-3 py-2 text-xs font-medium transition-colors',
          hasUnread
            ? 'bg-amber-950/45 border-b border-amber-800/40 text-amber-100/95'
            : 'bg-stone-900/85 border-b border-stone-700/80 text-stone-300',
        ].join(' ')}
      >
        <span className="leading-snug">{barLabel}</span>
        <span className="block text-[10px] font-normal text-stone-500 mt-0.5">Click to view grouped questions</span>
      </button>

      {listOpen ? (
        <div className="divide-y divide-stone-800/90 bg-stone-950/55">
          {grouped.map((section) => (
            <div key={section.origin} className="px-3 py-2 space-y-2">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-amber-600/90">{section.label}</p>
              <ul className="space-y-0 divide-y divide-stone-800/80">
                {section.items.map((m) => {
                  const pid = getPromptId(m)
                  const { questionText } = resolveGuideQuestionMeta(m)
                  const nestedOpen = nestedExpandedPromptId === pid
                  const isActive = activeConversationalSuggestionPromptId === pid
                  return (
                    <li
                      key={pid}
                      className={[
                        'bg-stone-900/35 pt-2 first:pt-0 pb-2 last:pb-0',
                        isActive && nestedOpen ? 'ring-1 ring-amber-600/40 ring-inset rounded-sm' : '',
                      ].join(' ')}
                    >
                      {!nestedOpen ? (
                        <div className="space-y-2 pl-1 border-l border-stone-700/80">
                          <button
                            type="button"
                            data-testid="guide-notification-question"
                            className="text-left text-[11px] text-stone-200 leading-snug hover:text-amber-100/95 w-full"
                            onClick={() => {
                              onMarkSeen(pid)
                              onFocusQuestion(pid, questionText)
                            }}
                          >
                            <span className="text-stone-500 mr-1">•</span>
                            {questionText}
                          </button>
                          <div className="flex flex-wrap gap-x-3 gap-y-1">
                            <button
                              type="button"
                              data-testid="guide-notification-row"
                              className="text-[10px] text-amber-200/85 hover:underline"
                              onClick={() => {
                                onSetNestedExpandedPromptId(pid)
                                onMarkSeen(pid)
                              }}
                            >
                              Show in thread
                            </button>
                            {!m.promptUiHidden ? (
                              <button
                                type="button"
                                className="text-[10px] text-stone-500 hover:text-amber-200/90 hover:underline"
                                onClick={() => {
                                  onSetNestedExpandedPromptId(pid)
                                  onMarkSeen(pid)
                                  onDiscussFromCollapsed(pid, questionText, canonicalPromptId(m))
                                }}
                              >
                                Discuss
                              </button>
                            ) : null}
                          </div>
                        </div>
                      ) : (
                        <div className="pl-1 border-l border-stone-700/80">
                          <p className="text-[11px] font-medium text-stone-200 mb-1">{questionText}</p>
                          <pre className="whitespace-pre-wrap font-sans text-xs text-stone-400 mb-2">{m.content}</pre>
                          <button
                            type="button"
                            className="text-[10px] text-stone-500 hover:text-stone-300 mb-2"
                            onClick={() => onCollapseItem(pid)}
                          >
                            Collapse
                          </button>
                          {!m.promptUiHidden ? (
                            <SystemPromptActions
                              promptId={canonicalPromptId(m)}
                              summaryLine={questionText.slice(0, 400)}
                              veSelection={veSelection}
                              onDeferUi={() => registerDeferContextForPrompt(canonicalPromptId(m))}
                              onDeferRemoveFromThreadUi={() => removeGuideRowsForPromptId(pid)}
                              onDiscussUi={() => {
                                markGuideInteracted(pid)
                                hidePromptActionsForPromptId(pid)
                                onMarkSeen(pid)
                              }}
                              onDiscuss={() => {
                                onDiscussEngage(pid, questionText)
                                councilTextareaFocus()
                              }}
                              onDismissUi={() => {
                                markGuideInteracted(pid)
                                dismissGuideFromThread(pid)
                              }}
                            />
                          ) : null}
                        </div>
                      )}
                    </li>
                  )
                })}
              </ul>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}
