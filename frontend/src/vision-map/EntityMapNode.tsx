import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'
import { useEffect, useRef, useState } from 'react'
import type { ConditionSeverity, MapEntityKind, MapNodePayload } from './ontology'
import {
  compactNodeStatusSummary,
  entityCompactStatusClass,
  entityLabelTextClass,
  entitySubtitleClass,
  hierarchyTitleClass,
  stoneTextTone,
} from './mapNodeAppearance'
import { mapEntityNodeLayoutPx } from './mapEntityNodeLayout'
import { effectiveConditionSeverity } from './resolveConditionSeverity'
import { SymbolicStone, washColorFor, washKeyForPayload } from './symbolicStone'
import { longPressTargetFor } from './cairn'
import { useLongPress } from './useLongPress'
import { useCairnInteraction } from './cairnContext'

type EntityRfNode = Node<MapNodePayload, 'entityMap'>

/** Symbolic stone px size per kind — the node box keeps today's dimensions. */
const STONE_SIZE_BY_KIND: Record<MapEntityKind, number> = {
  tree: 132,
  branch: 104,
  flower: 76,
  fruit: 88,
  seed: 76,
  landmark: 68,
  cairn: 64,
}

const handleClass =
  '!z-[3] !bg-stone-600/75 !w-2.5 !h-2.5 !min-w-2.5 !min-h-2.5 !border-0 !rounded-full opacity-70 hover:opacity-100 !left-1/2 !-translate-x-1/2 shadow-sm'

/**
 * One symbolic stone per node: a single SVG (river-stone silhouette +
 * growth glyph + urgency ring + project color wash) with the label block
 * beneath. Long-press collapses an expanded cairn member back into its
 * cairn; long-press on the initiative (tree) stone collapses every expanded
 * cairn at once; tap keeps the existing select/focus behavior.
 */
export function EntityMapNode({ id, data, selected }: NodeProps<EntityRfNode>) {
  const labelTone = stoneTextTone(data.kind)
  const conditionSeverity: ConditionSeverity = effectiveConditionSeverity(data)
  const statusHint = compactNodeStatusSummary(data.growth, conditionSeverity)
  const statusTitle =
    conditionSeverity > 0
      ? `${data.growth} · needs attention ${conditionSeverity}/3`
      : `${data.growth} · settled`
  const layoutPx = mapEntityNodeLayoutPx(data.kind)
  const wash = washColorFor(washKeyForPayload(data))

  const { onToggleCairn, onCollapseAllCairns } = useCairnInteraction()
  const expandedFromCairn = (data as { expandedFromCairn?: string }).expandedFromCairn ?? null
  const target = longPressTargetFor(data.kind, expandedFromCairn)

  // "Already stacked" hint: collapse-all with nothing expanded is a no-op,
  // and a silent gesture reads as broken. Brief transient pill, 44px-safe.
  const [stackedHint, setStackedHint] = useState(false)
  const stackedHintTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(
    () => () => {
      if (stackedHintTimer.current) clearTimeout(stackedHintTimer.current)
    },
    [],
  )
  const handleCollapseAll = () => {
    const didCollapse = onCollapseAllCairns()
    if (!didCollapse) {
      setStackedHint(true)
      if (stackedHintTimer.current) clearTimeout(stackedHintTimer.current)
      stackedHintTimer.current = setTimeout(() => setStackedHint(false), 1400)
    }
  }

  const lp = useLongPress(
    target.action === 'collapseCairn'
      ? () => onToggleCairn(target.cairnId)
      : target.action === 'collapseAll'
        ? handleCollapseAll
        : null,
  )

  return (
    <div
      className={[
        'map-stone-surface text-center select-none relative',
        data.dimmed ? 'map-node-dimmed' : '',
        data.focusLineage ? 'map-node-lineage' : '',
        selected ? 'map-stone-selected' : '',
      ]
        .filter(Boolean)
        .join(' ')}
      style={{ width: layoutPx.width, minHeight: layoutPx.height }}
      data-map-entity-kind={data.kind}
      data-map-condition-severity={String(conditionSeverity)}
      title={statusTitle}
      {...lp}
    >
      {stackedHint ? (
        <div
          role="status"
          className="pointer-events-none absolute -top-1 left-1/2 z-30 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-full border border-stone-600 bg-stone-900/95 px-3 py-1.5 text-[11px] font-medium text-stone-300 shadow-lg"
        >
          Already stacked
        </div>
      ) : null}
      <div className="flex w-full items-center justify-center pt-2" aria-hidden>
        <SymbolicStone
          growth={data.growth}
          kind={data.kind}
          severity={conditionSeverity}
          fertilizerPulse={!!data.fertilizer_pulse}
          washColor={wash}
          variantSeed={data.ref.id}
          size={STONE_SIZE_BY_KIND[data.kind] ?? 72}
        />
      </div>
      <div className="relative z-[20] flex w-full min-w-0 flex-col px-1 pb-2 pt-1">
        <Handle type="target" position={Position.Top} className={`${handleClass} !top-0`} />
        <div className="flex w-full min-w-0 max-w-full flex-col items-center gap-1 px-2.5">
          {data.subtitle?.trim() ? (
            <div className={`w-full max-w-full ${entitySubtitleClass(labelTone)} ${entityLabelTextClass()}`}>
              {data.subtitle}
            </div>
          ) : null}
          <div className={`w-full max-w-full leading-snug ${hierarchyTitleClass(data.kind)} ${entityLabelTextClass()}`}>
            {data.label}
          </div>
          {statusHint ? (
            <div className={`mt-0.5 w-full max-w-full ${entityCompactStatusClass(labelTone)} ${entityLabelTextClass()}`}>
              {statusHint}
            </div>
          ) : null}
        </div>
        <Handle type="source" position={Position.Bottom} className={`${handleClass} !bottom-0`} />
      </div>
    </div>
  )
}
