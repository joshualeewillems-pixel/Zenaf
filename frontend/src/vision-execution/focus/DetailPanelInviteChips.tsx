import { useMemo } from 'react'
import { CONVERSATION_ENTITY_FIELD_KEY } from './conversationEntityFocus'
import { deriveFocusInvites } from './deriveFocusInvites'
import { useFocusInviteRunOptional } from './FocusInviteRunContext'
import type { FocusContextCore } from './types'

export type DetailPanelInviteEntity = 'idea' | 'project' | 'task'

type DetailPanelInviteChipsProps = {
  entityType: DetailPanelInviteEntity
  entityId: string
  /** Shown in focus label / council scope (usually current title). */
  titleLine: string
  className?: string
}

/** In-panel invite row — same actions as the context bar, anchored to the open entity (no text field focus required). */
export function DetailPanelInviteChips({
  entityType,
  entityId,
  titleLine,
  className = '',
}: DetailPanelInviteChipsProps) {
  const onRun = useFocusInviteRunOptional()

  const core = useMemo((): FocusContextCore => {
    const label = titleLine.trim() || entityType
    return {
      surface: 'vision_execution',
      entity_type: entityType,
      entity_id: entityId,
      field_key: CONVERSATION_ENTITY_FIELD_KEY,
      field_label: `${entityType}: ${label}`,
      field_kind: 'idea_body',
    }
  }, [entityType, entityId, titleLine])

  const invites = deriveFocusInvites(core)
  if (invites.length === 0 || !onRun) return null

  return (
    <div
      className={`flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border border-slate-700/80 bg-slate-900/35 px-2.5 py-2 ${className}`}
      data-testid="ve-detail-panel-invite-chips"
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
