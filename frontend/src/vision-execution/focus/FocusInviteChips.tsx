import { deriveFocusInvites } from './deriveFocusInvites'
import { useFocusInviteRunOptional } from './FocusInviteRunContext'
import { useVisionExecutionFocusOptional } from './VisionExecutionFocusContext'

type FocusInviteChipsProps = {
  className?: string
}

/** Compact starters for council; hidden when focus clears (no stale chips). */
export function FocusInviteChips({ className = '' }: FocusInviteChipsProps) {
  const fo = useVisionExecutionFocusOptional()
  const onRun = useFocusInviteRunOptional()
  const core = fo?.focus?.core ?? null
  const invites = deriveFocusInvites(core)
  if (!core || invites.length === 0 || !onRun) return null

  return (
    <div
      className={`flex flex-wrap items-center gap-x-2 gap-y-1 ${className}`}
      data-testid="ve-focus-invite-chips"
    >
      <span className="text-slate-500 text-[10px] uppercase tracking-wide font-medium shrink-0">Invites</span>
      <div className="flex flex-wrap gap-1 min-w-0">
        {invites.map((inv) => (
          <button
            key={inv.id}
            type="button"
            className={
              inv.kind === 'structured_fill'
                ? 'px-2 py-0.5 rounded border border-amber-800/70 bg-amber-950/35 text-amber-100/95 text-[10px] hover:bg-amber-900/40'
                : 'px-2 py-0.5 rounded border border-sky-900/60 bg-slate-900/80 text-sky-100/90 text-[10px] hover:bg-slate-800/90'
            }
            aria-label={`${inv.kind === 'structured_fill' ? 'Structured fill' : 'Conversational'} invite: ${inv.label}`}
            onClick={() => onRun(inv, core)}
          >
            {inv.label}
          </button>
        ))}
      </div>
    </div>
  )
}
