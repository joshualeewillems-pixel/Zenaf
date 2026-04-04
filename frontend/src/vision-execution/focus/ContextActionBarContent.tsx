import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react'
import type { ActionId } from './types'
import { ACTION_LABELS, actionsForField } from './fieldCapabilityRegistry'
import { useVisionExecutionFocus } from './VisionExecutionFocusContext'
import { useVeVoiceRecording } from './veVoiceRecordingContext'
import { VISION_EXECUTION_API } from '../types'
import { ATRIA_VE_FOCUS_APPLY_REWRITE, type VeFocusApplyRewriteDetail } from './applyRewriteEvent'
import type { AiActionTrace, AiUserOutcome } from '../../ai-actions'
import {
  actionIntentForFieldTextRewrite,
  AiActionResultPanel,
  createAiActionTrace,
  PROMPT_VERSION_FIELD_TEXT_REWRITE,
  pushAiActionTrace,
  withTraceOutcome,
  withTraceOutput,
} from '../../ai-actions'

const MAX_VISIBLE_ACTIONS = 6

type FocusRewriteResponse = {
  rewritten_text?: string
  error?: string | null
  source?: string
}

type ContextActionBarContentProps = {
  className?: string
  /** Where the shell is: affects copy when no field is focused */
  idleHint?: 've' | 'shell'
}

export function ContextActionBarContent({ className = '', idleHint = 've' }: ContextActionBarContentProps) {
  const { focus, onBarPointerDownCapture, onBarFocusCapture, getFocusedFieldText } = useVisionExecutionFocus()
  const { voicePhase, voiceError, startVoiceRecording, stopVoiceRecording } = useVeVoiceRecording()
  const [stubNotice, setStubNotice] = useState<string | null>(null)
  const [rewriteLoading, setRewriteLoading] = useState(false)
  const [rewriteError, setRewriteError] = useState<string | null>(null)
  const [rewrittenText, setRewrittenText] = useState<string | null>(null)
  const [rewriteSource, setRewriteSource] = useState<string | null>(null)
  const toolbarRef = useRef<HTMLDivElement>(null)
  const rewriteTraceRef = useRef<AiActionTrace | null>(null)
  const [rewritePanelOutcome, setRewritePanelOutcome] = useState<AiUserOutcome>('none')

  useEffect(() => {
    if (!stubNotice) return
    const t = setTimeout(() => setStubNotice(null), 4500)
    return () => clearTimeout(t)
  }, [stubNotice])

  useEffect(() => {
    setRewriteError(null)
    setRewrittenText(null)
    setRewriteSource(null)
    setRewriteLoading(false)
    setRewritePanelOutcome('none')
  }, [focus?.core.entity_id, focus?.core.field_key, focus?.core.focus_version])

  const onStubAction = useCallback((actionId: ActionId) => {
    if (!focus) return
    if (actionId === 'transcribe') return
    const c = focus.core
    setStubNotice(
      `${ACTION_LABELS[actionId]} — preview only (Phase 1). Field: ${c.field_label} · ${c.entity_type}/${c.field_key}. No request sent.`,
    )
  }, [focus])

  const runRewrite = useCallback(async () => {
    if (!focus) return
    const c = focus.core
    setStubNotice(null)
    setRewriteError(null)
    setRewrittenText(null)
    setRewriteSource(null)
    setRewritePanelOutcome('none')
    setRewriteLoading(true)
    try {
      const snap = getFocusedFieldText().trim()
      const res = await fetch(`${VISION_EXECUTION_API}/focus-actions/rewrite`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          entity_type: c.entity_type,
          entity_id: c.entity_id,
          field_key: c.field_key,
          field_label: c.field_label,
          text_override: snap.length > 0 ? snap : null,
        }),
      })
      const data = (await res.json().catch(() => ({}))) as FocusRewriteResponse
      if (!res.ok) {
        const msg = typeof data.error === 'string' ? data.error : `Request failed (${res.status})`
        setRewriteError(msg)
        return
      }
      if (data.error) {
        setRewriteError(data.error)
        return
      }
      const out = (data.rewritten_text ?? '').trim() || null
      setRewrittenText(out)
      setRewriteSource(typeof data.source === 'string' ? data.source : null)
      if (out && focus) {
        const fc = focus.core
        const base = createAiActionTrace({
          surface: 'vision_execution',
          action_kind: 'field_text_rewrite',
          subject_type: fc.entity_type,
          subject_id: fc.entity_id,
          field_key: fc.field_key,
          action_intent: actionIntentForFieldTextRewrite(fc.entity_type, fc.field_key),
          input_snapshot: snap.slice(0, 4000),
          prompt_version: PROMPT_VERSION_FIELD_TEXT_REWRITE,
          model_used: null,
          user_outcome: 'none',
        })
        rewriteTraceRef.current = withTraceOutput(base, out, null, PROMPT_VERSION_FIELD_TEXT_REWRITE)
      } else {
        rewriteTraceRef.current = null
      }
    } catch (e) {
      setRewriteError(e instanceof Error ? e.message : 'Rewrite failed')
    } finally {
      setRewriteLoading(false)
    }
  }, [focus, getFocusedFieldText])

  const applyRewrite = useCallback(() => {
    if (!focus || !rewrittenText?.trim()) return
    const c = focus.core
    const detail: VeFocusApplyRewriteDetail = {
      entity_type: c.entity_type,
      entity_id: c.entity_id,
      field_key: c.field_key,
      text: rewrittenText.trim(),
    }
    window.dispatchEvent(new CustomEvent(ATRIA_VE_FOCUS_APPLY_REWRITE, { detail }))
    const t = rewriteTraceRef.current
    if (t) pushAiActionTrace(withTraceOutcome(t, 'applied'))
    rewriteTraceRef.current = null
    setRewrittenText(null)
    setRewriteError(null)
    setRewriteSource(null)
    setRewritePanelOutcome('applied')
    setStubNotice('Applied to form — use Save to persist.')
  }, [focus, rewrittenText])

  const copyRewrite = useCallback(async () => {
    if (!rewrittenText?.trim()) return
    try {
      await navigator.clipboard.writeText(rewrittenText.trim())
      const t = rewriteTraceRef.current
      if (t) pushAiActionTrace(withTraceOutcome(t, 'copied'))
      rewriteTraceRef.current = null
      setRewritePanelOutcome('copied')
      setStubNotice('Copied to clipboard — recorded in your action log.')
    } catch {
      setStubNotice('Could not copy — select text manually.')
    }
  }, [rewrittenText])

  const onToolbarKeyDown = useCallback((e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
    const root = toolbarRef.current
    if (!root) return
    const buttons = Array.from(root.querySelectorAll<HTMLButtonElement>('button:not([disabled])'))
    const ae = document.activeElement
    const i = buttons.indexOf(ae as HTMLButtonElement)
    if (i < 0) return
    e.preventDefault()
    const next = e.key === 'ArrowRight' ? Math.min(i + 1, buttons.length - 1) : Math.max(i - 1, 0)
    buttons[next]?.focus()
  }, [])

  if (!focus) {
    const idle =
      idleHint === 'shell'
        ? 'No field focus — click into any text field to use voice transcription.'
        : 'No field focus — click into a text field in this view (create idea, detail panel, …).'
    return (
      <div className={`flex flex-wrap items-center gap-2 min-w-0 ${className}`}>
        <span className="text-slate-500 text-sm truncate" aria-live="polite">
          {idle}
        </span>
      </div>
    )
  }

  const c = focus.core
  const actions = actionsForField(c.entity_type, c.field_key)
  const visible = actions.slice(0, MAX_VISIBLE_ACTIONS)
  const overflow = actions.length - visible.length

  const lineage =
    c.lineage_labels && c.lineage_labels.length > 0
      ? c.lineage_labels.join(' · ')
      : null

  return (
    <div data-testid="ve-context-action-bar" className={`flex flex-col gap-1.5 min-w-0 ${className}`}>
      <div
        className="flex flex-wrap items-center gap-x-3 gap-y-1 min-w-0 text-sm"
        aria-live="polite"
        aria-atomic="true"
      >
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 min-w-0">
          <span className="text-slate-400 shrink-0 uppercase text-[10px] tracking-wide font-medium">Focused</span>
          <span className="text-slate-200 font-medium truncate" title={c.field_label}>
            {c.field_label}
          </span>
          {voicePhase === 'transcribing' && (
            <span className="text-sky-300/90 text-[10px] font-medium">Transcribing…</span>
          )}
          <span className="text-slate-500 text-xs truncate">
            {c.entity_type} <span className="font-mono text-slate-400">{c.entity_id.slice(0, 8)}…</span>
            {lineage ? <span className="text-slate-600"> · {lineage}</span> : null}
          </span>
          <span className="text-slate-600 text-[10px] uppercase tracking-wide hidden sm:inline">
            {c.field_kind}
          </span>
        </div>
      </div>
      {visible.length > 0 && (
        <div
          ref={toolbarRef}
          role="toolbar"
          aria-label="Context actions for focused field"
          className="flex flex-wrap items-center gap-1.5"
          onPointerDownCapture={onBarPointerDownCapture}
          onFocusCapture={onBarFocusCapture}
          onKeyDown={onToolbarKeyDown}
        >
          {visible.map((id) => (
            <button
              key={id}
              type="button"
              className="px-2 py-0.5 rounded border border-slate-600 bg-slate-800/80 text-slate-200 text-[11px] hover:bg-slate-700 hover:border-slate-500 disabled:opacity-50"
              disabled={
                (rewriteLoading && id === 'rewrite') ||
                (id === 'transcribe' && voicePhase === 'transcribing')
              }
              onClick={() => {
                if (id === 'transcribe') {
                  if (voicePhase === 'recording') stopVoiceRecording()
                  else if (voicePhase === 'idle') void startVoiceRecording()
                  return
                }
                if (id === 'rewrite') runRewrite()
                else onStubAction(id)
              }}
            >
              {id === 'transcribe' && voicePhase === 'recording'
                ? 'Stop recording'
                : id === 'transcribe' && voicePhase === 'transcribing'
                  ? 'Transcribing…'
                  : id === 'rewrite' && rewriteLoading
                    ? 'Rewriting…'
                    : ACTION_LABELS[id]}
            </button>
          ))}
          {overflow > 0 && (
            <span className="text-slate-500 text-[10px]">+{overflow} more (Phase 2)</span>
          )}
        </div>
      )}
      {visible.length === 0 && (
        <span className="text-slate-500 text-xs">No actions for this field (context only).</span>
      )}
      {voiceError && (
        <p className="text-red-300/90 text-[11px] border border-red-800/50 rounded px-2 py-1 bg-red-950/40 max-w-full" role="alert">
          {voiceError}
        </p>
      )}
      {rewriteError && (
        <p className="text-red-300/90 text-[11px] border border-red-800/50 rounded px-2 py-1 bg-red-950/40 max-w-full" role="alert">
          {rewriteError}
        </p>
      )}
      {rewrittenText != null && rewrittenText.length > 0 && (
        <AiActionResultPanel
          heading="Rewrite (review — not saved)"
          subheading={rewriteSource ?? undefined}
          recordedOutcome={rewritePanelOutcome}
          applyLabel="Apply to field"
          onApply={applyRewrite}
          onDismiss={() => {
            if (rewritePanelOutcome === 'none') {
              const t = rewriteTraceRef.current
              if (t) pushAiActionTrace(withTraceOutcome(t, 'dismissed'))
            }
            rewriteTraceRef.current = null
            setRewrittenText(null)
            setRewriteSource(null)
            setRewritePanelOutcome('dismissed')
          }}
          onCopy={() => copyRewrite()}
        >
          <textarea
            readOnly
            className="w-full min-h-[5rem] max-h-[14rem] text-xs text-slate-200 bg-slate-950/80 border border-slate-700 rounded px-2 py-1 resize-y"
            value={rewrittenText}
            aria-label="Rewritten text for review"
          />
        </AiActionResultPanel>
      )}
      {stubNotice && (
        <p className="text-amber-200/90 text-[11px] border border-amber-800/50 rounded px-2 py-1 bg-amber-950/40 max-w-full" role="status">
          {stubNotice}
        </p>
      )}
    </div>
  )
}
