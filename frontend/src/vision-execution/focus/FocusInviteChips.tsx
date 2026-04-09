/**
 * FLOW_RECEPTION (context bar invite row)
 * (1) Reads: `useFlowAssessmentFromCore` → `dominantIssue`, `trunkSummary`, `rankedActions` (via deriveFocusInvites).
 * (2) Behavior: shows `trunkSummary`; chips ranked/tiered by deriveFocusInvites when assessment non-null.
 * (3) Hard vs productive: primary chip emphasized; demoted tertiary; all allowed actions remain clickable.
 */
import type { FocusInvite } from './focusInviteTypes'
import { deriveFocusInvites } from './deriveFocusInvites'
import { useFocusInviteRunOptional } from './FocusInviteRunContext'
import { useVisionExecutionFocusOptional } from './VisionExecutionFocusContext'
import { useFlowAssessmentFromCore } from './useFlowAssessmentFromCore'

type FocusInviteChipsProps = {
  className?: string
}

function inviteChipClass(inv: FocusInvite): string {
  if (inv.kind === 'structured_fill') {
    return 'px-2 py-0.5 rounded border border-amber-800/70 bg-amber-950/35 text-amber-100/95 text-[10px] hover:bg-amber-900/40'
  }
  if (inv.flowTier === 'primary') {
    return 'px-2 py-0.5 rounded border border-sky-500/55 bg-slate-900/90 text-sky-50 text-[10px] hover:bg-slate-800/95 ring-1 ring-sky-600/35'
  }
  if (inv.flowTier === 'tertiary') {
    return 'px-2 py-0.5 rounded border border-slate-800/90 bg-slate-950/50 text-sky-100/55 text-[10px] hover:bg-slate-900/60'
  }
  return 'px-2 py-0.5 rounded border border-sky-900/60 bg-slate-900/80 text-sky-100/90 text-[10px] hover:bg-slate-800/90'
}

/** Compact starters for council; hidden when focus clears (no stale chips). */
export function FocusInviteChips({ className = '' }: FocusInviteChipsProps) {
  const fo = useVisionExecutionFocusOptional()
  const onRun = useFocusInviteRunOptional()
  const core = fo?.focus?.core ?? null
  const flowAssessment = useFlowAssessmentFromCore(core)
  const invites = deriveFocusInvites(core, flowAssessment)
  if (!core || invites.length === 0 || !onRun) return null

  return (
    <div
      className={`flex flex-col gap-1 min-w-0 ${className}`}
      data-testid="ve-focus-invite-chips"
    >
      {flowAssessment ? (
        <p className="text-[10px] text-slate-500 leading-snug max-w-prose" data-testid="ve-focus-flow-trunk">
          {flowAssessment.trunkSummary}
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="text-slate-500 text-[10px] uppercase tracking-wide font-medium shrink-0">Invites</span>
        <div className="flex flex-wrap gap-1 min-w-0">
          {invites.map((inv) => (
            <button
              key={inv.id}
              type="button"
              className={inviteChipClass(inv)}
              aria-label={`${inv.kind === 'structured_fill' ? 'Structured fill' : 'Conversational'} invite: ${inv.label}`}
              onClick={() => onRun(inv, core)}
            >
              {inv.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
