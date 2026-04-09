import { useCallback, useEffect, useMemo, useRef, type ReactNode, type SyntheticEvent } from 'react'
import type { EntityType, FieldKind, FocusDescriptor, FocusSurface } from './types'
import { useVisionExecutionFocusOptional } from './VisionExecutionFocusContext'
import { focusFieldRegistryKey } from './focusRegistryKey'

export type TranscribableFieldRegionProps = {
  /** App surface; defaults to `vision_execution` in {@link VeFocusRegion}. */
  surface: FocusSurface
  entity_type: EntityType
  entity_id: string
  field_key: string
  field_label: string
  field_kind: FieldKind
  parent?: FocusDescriptor['parent']
  lineage_labels?: string[]
  /** When false, skip focus registration (read-only display, etc.) */
  transcribe?: boolean
  /** Live value for Context Action Bar actions (e.g. Rewrite) */
  getCurrentText?: () => string
  children: ReactNode
}

/**
 * Registers an editable text control for universal focus + voice insert (transcribe).
 * Use for textareas and text inputs where user-authored content is expected.
 */
export function TranscribableFieldRegion({
  surface,
  entity_type,
  entity_id,
  field_key,
  field_label,
  field_kind,
  parent,
  lineage_labels,
  transcribe = true,
  getCurrentText,
  children,
}: TranscribableFieldRegionProps) {
  const ctx = useVisionExecutionFocusOptional()
  const getTextRef = useRef(getCurrentText)
  getTextRef.current = getCurrentText

  const desc = useMemo(
    (): FocusDescriptor => ({
      surface,
      entity_type,
      entity_id,
      field_key,
      field_label,
      field_kind,
      parent,
      lineage_labels,
    }),
    [surface, entity_type, entity_id, field_key, field_label, field_kind, parent, lineage_labels],
  )

  const k = useMemo(
    () => focusFieldRegistryKey({ surface, entity_type, entity_id, field_key }),
    [surface, entity_type, entity_id, field_key],
  )
  const hasGetter = Boolean(getCurrentText)

  useEffect(() => {
    if (!ctx || !transcribe) return
    if (!hasGetter) {
      ctx.unregisterFieldTextGetter(k)
      return
    }
    const getter = () => (getTextRef.current?.() ?? '') || ''
    ctx.registerFieldTextGetter(k, getter)
    return () => ctx.unregisterFieldTextGetter(k)
  }, [ctx, k, hasGetter, transcribe])

  if (!ctx || !transcribe) {
    return <>{children}</>
  }

  const { notifyFieldFocused, notifyFieldBlurred, recordFieldSelection } = ctx

  const syncSelection = useCallback(
    (e: SyntheticEvent) => {
      const t = e.target
      if (!(t instanceof HTMLTextAreaElement) && !(t instanceof HTMLInputElement)) return
      if (t instanceof HTMLInputElement && t.type !== 'text' && t.type !== 'search') return
      recordFieldSelection(k, t.selectionStart ?? 0, t.selectionEnd ?? 0)
    },
    [k, recordFieldSelection],
  )

  return (
    <div
      className="min-w-0"
      data-zenaf-transcribe-region=""
      onFocusCapture={() => notifyFieldFocused(desc)}
      onBlurCapture={() => notifyFieldBlurred()}
      onSelectCapture={syncSelection}
      onKeyUpCapture={syncSelection}
      onClickCapture={syncSelection}
    >
      {children}
    </div>
  )
}
