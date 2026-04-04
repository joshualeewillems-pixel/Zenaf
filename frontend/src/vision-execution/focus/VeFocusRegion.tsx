import type { ReactNode } from 'react'
import type { EntityType, FieldKind, FocusDescriptor } from './types'
import { TranscribableFieldRegion, type TranscribableFieldRegionProps } from './TranscribableFieldRegion'

type VeFocusRegionProps = {
  entity_type: EntityType
  entity_id: string
  field_key: string
  field_label: string
  field_kind: FieldKind
  parent?: FocusDescriptor['parent']
  lineage_labels?: string[]
  transcribe?: TranscribableFieldRegionProps['transcribe']
  getCurrentText?: () => string
  children: ReactNode
}

/** Vision Execution fields — same as {@link TranscribableFieldRegion} with `surface: vision_execution`. */
export function VeFocusRegion({
  entity_type,
  entity_id,
  field_key,
  field_label,
  field_kind,
  parent,
  lineage_labels,
  transcribe,
  getCurrentText,
  children,
}: VeFocusRegionProps) {
  return (
    <TranscribableFieldRegion
      surface="vision_execution"
      entity_type={entity_type}
      entity_id={entity_id}
      field_key={field_key}
      field_label={field_label}
      field_kind={field_kind}
      parent={parent}
      lineage_labels={lineage_labels}
      transcribe={transcribe}
      getCurrentText={getCurrentText}
    >
      {children}
    </TranscribableFieldRegion>
  )
}
