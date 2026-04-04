import type { ReactNode } from 'react'
import type { AiUserOutcome } from './types'

function recordedOutcomeLine(outcome: AiUserOutcome): string | null {
  switch (outcome) {
    case 'applied':
      return 'Recorded in your action log: you applied this suggestion.'
    case 'dismissed':
      return 'Recorded in your action log: you dismissed this batch.'
    case 'edited':
      return 'Recorded in your action log: you kept your own version (edited).'
    case 'copied':
      return 'Recorded in your action log: you copied this output.'
    default:
      return null
  }
}

/**
 * Shared AI output chrome: result region + Apply / Dismiss / Copy.
 * Product-wide; first used from Vision & Execution, reusable from Perspectives, Content, etc.
 */
export type AiActionResultPanelProps = {
  className?: string
  heading: string
  subheading?: string
  error?: string | null
  children?: ReactNode
  applyLabel?: string
  dismissLabel?: string
  copyLabel?: string
  onApply?: () => void
  onDismiss?: () => void
  onCopy?: () => void | Promise<void>
  applyDisabled?: boolean
  /** When set (not `none`), shows a short line so the user sees their choice was traced. */
  recordedOutcome?: AiUserOutcome
}

export function AiActionResultPanel({
  className = '',
  heading,
  subheading,
  error,
  children,
  applyLabel = 'Apply',
  dismissLabel = 'Dismiss',
  copyLabel = 'Copy',
  onApply,
  onDismiss,
  onCopy,
  applyDisabled,
  recordedOutcome = 'none',
}: AiActionResultPanelProps) {
  const showApply = Boolean(onApply)
  const showDismiss = Boolean(onDismiss)
  const showCopy = Boolean(onCopy)

  return (
    <div className={`rounded border border-slate-600 bg-slate-900/80 p-2 space-y-2 max-w-full ${className}`.trim()}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-[10px] uppercase tracking-wide text-slate-500">
          {heading}
          {subheading ? <span className="text-slate-600 normal-case"> · {subheading}</span> : null}
        </span>
        {(showApply || showCopy || showDismiss) && (
          <div className="flex flex-wrap gap-1">
            {showApply && (
              <button
                type="button"
                className="px-2 py-0.5 rounded bg-emerald-800/90 text-emerald-100 text-[11px] hover:bg-emerald-700 disabled:opacity-50"
                onClick={() => onApply?.()}
                disabled={applyDisabled}
              >
                {applyLabel}
              </button>
            )}
            {showCopy && (
              <button
                type="button"
                className="px-2 py-0.5 rounded border border-slate-600 text-slate-300 text-[11px] hover:bg-slate-800"
                onClick={() => void onCopy?.()}
              >
                {copyLabel}
              </button>
            )}
            {showDismiss && (
              <button
                type="button"
                className="px-2 py-0.5 rounded border border-slate-600 text-slate-400 text-[11px] hover:bg-slate-800"
                onClick={() => onDismiss?.()}
              >
                {dismissLabel}
              </button>
            )}
          </div>
        )}
      </div>
      {error && (
        <p className="text-red-300/90 text-[11px] border border-red-800/50 rounded px-2 py-1 bg-red-950/40 max-w-full" role="alert">
          {error}
        </p>
      )}
      {recordedOutcome !== 'none' ? (
        <p className="text-emerald-200/85 text-[11px] border border-emerald-800/40 rounded px-2 py-1 bg-emerald-950/30" role="status">
          {recordedOutcomeLine(recordedOutcome)}
        </p>
      ) : null}
      {children}
    </div>
  )
}
