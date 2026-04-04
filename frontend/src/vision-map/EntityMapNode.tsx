import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'
import type { MapNodePayload } from './ontology'
import {
  compactNodeStatusSummary,
  conditionShapeOverlayClass,
  entityCompactStatusClass,
  entityLabelTextClass,
  entityOrganicClasses,
  entitySubtitleClass,
  hierarchyTitleClass,
  stoneTextTone,
  vitalityOuterClass,
  vitalityShapePulseClass,
} from './mapNodeAppearance'
import { stoneShapeMicroStyle } from './mapStoneShape'
import { StoneKindGlyph } from './StoneKindGlyph'

type EntityRfNode = Node<MapNodePayload, 'entityMap'>

const handleClass =
  '!z-[3] !bg-stone-600/75 !w-2.5 !h-2.5 !min-w-2.5 !min-h-2.5 !border-0 !rounded-full opacity-70 hover:opacity-100 !left-1/2 !-translate-x-1/2 shadow-sm'

export function EntityMapNode({ id, data, selected }: NodeProps<EntityRfNode>) {
  const organic = entityOrganicClasses(data.kind)
  const labelTone = stoneTextTone(data.kind)
  const stoneToneAttr = labelTone === 'on-light' ? 'light' : 'dark'
  const vitalityOuter = vitalityOuterClass(data.growth, data.condition)
  const condOverlay = conditionShapeOverlayClass(data.condition)
  const quiet =
    data.growth === 'pruned' ||
    data.growth === 'dormant' ||
    data.condition === 'blocked' ||
    data.condition === 'teacher-vetoed'
  const showShimmer = data.growth === 'growing' && !quiet
  const statusHint = compactNodeStatusSummary(data.growth, data.condition)
  const statusTitle = `${data.growth} · ${data.condition}`
  const water = data.water_level ?? 'medium'
  const waterClass = water === 'high' ? 'map-water-high' : water === 'medium' ? 'map-water-medium' : 'map-water-low'
  const shapePulse = vitalityShapePulseClass(data.growth, data.condition, water)

  return (
    <div
      className={[
        organic.outer,
        vitalityOuter,
        waterClass,
        'map-stone-surface text-center transition-transform duration-200 ease-out',
        data.dimmed ? 'map-node-dimmed' : '',
        data.focusLineage ? 'map-node-lineage' : '',
        selected ? 'map-stone-selected' : '',
      ]
        .filter(Boolean)
        .join(' ')}
      data-stone-tone={stoneToneAttr}
      title={statusTitle}
    >
      <div
        className={[organic.shape, shapePulse, data.fertilizer_pulse ? 'map-fertilizer-pulse' : '']
          .filter(Boolean)
          .join(' ')}
        style={stoneShapeMicroStyle(id, data.kind)}
        aria-hidden
      >        <div
          className={`pointer-events-none absolute inset-0 z-0 map-stone-clip ${organic.fill}`}
          aria-hidden
        />
        <div
          className="pointer-events-none absolute inset-0 z-0 map-stone-clip map-stone-rim-light opacity-[0.26]"
          aria-hidden
        />
        <div
          className="pointer-events-none absolute inset-0 z-0 map-stone-clip map-stone-rim-shadow opacity-70"
          aria-hidden
        />
        {showShimmer && (
          <div
            className="map-shimmer-layer pointer-events-none absolute inset-0 z-0 map-stone-clip opacity-[0.14]"
            aria-hidden
          />
        )}
        <div className={`pointer-events-none absolute inset-0 z-[4] map-stone-clip ${condOverlay}`} aria-hidden />
      </div>
      <div className="relative z-[2] flex min-h-0 w-full flex-col items-center px-1 pb-2 pt-0.5">
        <Handle type="target" position={Position.Top} className={`${handleClass} !top-0`} />
        <div
          className="flex w-full flex-shrink-0 flex-col items-center justify-center px-1 pt-1"
          aria-hidden
        >
          <StoneKindGlyph kind={data.kind} className={organic.glyph} />
        </div>
        <div className="mt-3.5 flex w-full min-w-0 max-w-full flex-col items-center gap-2.5 px-2.5 pb-2">
          {data.subtitle?.trim() ? (
            <div className={`w-full max-w-full ${entitySubtitleClass(labelTone)} ${entityLabelTextClass()}`}>
              {data.subtitle}
            </div>
          ) : null}
          <div
            className={`w-full max-w-full leading-snug ${hierarchyTitleClass(data.kind)} ${entityLabelTextClass()}`}
          >
            {data.label}
          </div>
          {statusHint ? (
            <div
              className={`mt-0.5 w-full max-w-full ${entityCompactStatusClass(labelTone)} ${entityLabelTextClass()}`}
            >
              {statusHint}
            </div>
          ) : null}
        </div>
        <Handle type="source" position={Position.Bottom} className={`${handleClass} !bottom-0`} />
      </div>
    </div>
  )
}
