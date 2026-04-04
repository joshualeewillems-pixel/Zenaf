/**
 * Actions write append-only prompt_signals for the Vision Map developmental guidance prompt only.
 *
 * - Discuss → engaged; UI expands the suggestion in-thread and uses a short reply starter (not full text in the input).
 * - Remind me later → deferred (revisit later; not endorsement).
 * - Dismiss → dismissed with NULL entity (suppress reinjection for this exact prompt_id; not permanent).
 */
import { useCallback, useState } from 'react'
import type { VESelection } from '../vision-execution/VisionExecutionView'
import {
  postPromptSignal,
  WORKSPACE_DEFER_ENTITY,
  type PromptSignalAction,
} from '../vision-execution/promptSignalsApi'

function objectRefFromVeSelection(sel: VESelection | null): { entity_type: string; entity_id: string } | null {
  if (!sel) return null
  if (sel.ideaId) return { entity_type: 'idea', entity_id: sel.ideaId }
  if (sel.initiativeId) return { entity_type: 'initiative', entity_id: sel.initiativeId }
  if (sel.projectId) return { entity_type: 'project', entity_id: sel.projectId }
  if (sel.taskId) return { entity_type: 'task', entity_id: sel.taskId }
  return null
}

function addHours(isoBase: Date, h: number): string {
  const d = new Date(isoBase.getTime() + h * 3600_000)
  return d.toISOString()
}

function addDays(isoBase: Date, days: number): string {
  const d = new Date(isoBase.getTime() + days * 86400_000)
  return d.toISOString()
}

type Props = {
  promptId: string
  summaryLine: string
  veSelection: VESelection | null
  /** Hide actions immediately (Discuss); message body may stay for context. */
  onDiscussUi?: () => void
  onDiscuss: () => void
  /** Remove prompt from thread immediately; server record follows. */
  onDismissUi: () => void
  /** Called when user commits a defer (before thread removal) — session resurfacing guard, etc. */
  onDeferUi?: () => void
  /**
   * Remove thread row after defer without clearing defer fingerprint (resurfacing skip uses stored snapshot).
   * Defaults to onDismissUi when omitted.
   */
  onDeferRemoveFromThreadUi?: () => void
}

const btn =
  'text-[10px] text-stone-500 hover:text-amber-200/90 underline-offset-2 hover:underline disabled:opacity-40'

export function SystemPromptActions({
  promptId,
  summaryLine,
  veSelection,
  onDiscussUi,
  onDiscuss,
  onDismissUi,
  onDeferUi,
  onDeferRemoveFromThreadUi,
}: Props) {
  const [deferOpen, setDeferOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [hoursStr, setHoursStr] = useState('4')
  const [daysStr, setDaysStr] = useState('1')

  const attachRef = objectRefFromVeSelection(veSelection) ?? WORKSPACE_DEFER_ENTITY

  const record = useCallback(
    async (action: PromptSignalAction, deferredUntil?: string | null) => {
      setBusy(true)
      try {
        await postPromptSignal({
          prompt_id: promptId,
          action,
          entity_type: action === 'dismissed' ? null : attachRef.entity_type,
          entity_id: action === 'dismissed' ? null : attachRef.entity_id,
          prompt_summary: summaryLine.slice(0, 400),
          deferred_until: deferredUntil ?? null,
        })
      } finally {
        setBusy(false)
      }
    },
    [attachRef, promptId, summaryLine],
  )

  const onEngage = () => {
    onDiscussUi?.()
    onDiscuss()
    setBusy(true)
    void record('engaged').finally(() => setBusy(false))
  }

  const onDismiss = () => {
    onDismissUi()
    void record('dismissed')
  }

  const onDefer = (until: string) => {
    setDeferOpen(false)
    onDeferUi?.()
    ;(onDeferRemoveFromThreadUi ?? onDismissUi)()
    void record('deferred', until)
  }

  return (
    <div data-testid="system-prompt-actions" className="mt-2 pt-2 border-t border-stone-700/50 space-y-1.5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <button
          type="button"
          className={btn}
          disabled={busy}
          title="Opens this suggestion in the thread and focuses your reply — the full text stays above."
          onClick={() => void onEngage()}
        >
          Discuss
        </button>
        <button type="button" className={btn} disabled={busy} onClick={() => setDeferOpen((v) => !v)}>
          Remind me later
        </button>
        <button type="button" className={btn} disabled={busy} onClick={() => onDismiss()}>
          Dismiss
        </button>
      </div>
      {deferOpen && (
        <div className="flex flex-wrap items-center gap-2 text-[10px] text-stone-500">
          <button
            type="button"
            className="px-1.5 py-0.5 rounded border border-stone-600 hover:bg-stone-800 text-stone-400"
            disabled={busy}
            onClick={() => onDefer(addHours(new Date(), 4))}
          >
            Later (~4h)
          </button>
          <span className="flex items-center gap-1">
            <input
              type="number"
              min={1}
              max={168}
              value={hoursStr}
              onChange={(e) => setHoursStr(e.target.value)}
              className="w-12 px-1 py-0.5 rounded bg-stone-950 border border-stone-600 text-stone-300 text-[10px]"
            />
            <span>h</span>
            <button
              type="button"
              className="px-1.5 py-0.5 rounded border border-stone-600 hover:bg-stone-800 text-stone-400"
              disabled={busy}
              onClick={() => {
                const n = Math.min(168, Math.max(1, parseInt(hoursStr, 10) || 1))
                onDefer(addHours(new Date(), n))
              }}
            >
              Set
            </button>
          </span>
          <span className="flex items-center gap-1">
            <input
              type="number"
              min={1}
              max={30}
              value={daysStr}
              onChange={(e) => setDaysStr(e.target.value)}
              className="w-10 px-1 py-0.5 rounded bg-stone-950 border border-stone-600 text-stone-300 text-[10px]"
            />
            <span>d</span>
            <button
              type="button"
              className="px-1.5 py-0.5 rounded border border-stone-600 hover:bg-stone-800 text-stone-400"
              disabled={busy}
              onClick={() => {
                const n = Math.min(30, Math.max(1, parseInt(daysStr, 10) || 1))
                onDefer(addDays(new Date(), n))
              }}
            >
              Set
            </button>
          </span>
        </div>
      )}
      {!objectRefFromVeSelection(veSelection) && deferOpen && (
        <p className="text-[9px] text-stone-600">No map row selected — reminder appears under Vision map until you pick a row.</p>
      )}
    </div>
  )
}
