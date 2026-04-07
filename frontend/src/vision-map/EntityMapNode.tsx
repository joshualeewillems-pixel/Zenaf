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
  mapFruitMassClass,
  mapSurfaceWaterClass,
  mapSurfaceWaterTier,
  resolveMapVisualTriadScalars,
  stoneTextTone,
  surfaceWater01ForMap,
  vitalityOuterClass,
} from './mapNodeAppearance'
import { stoneShapeMicroStyle } from './mapStoneShape'
import { StoneConditionOverlay } from './StoneConditionOverlay'
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
  const statusHint = compactNodeStatusSummary(data.growth, data.condition)
  const statusTitle = `${data.growth} · ${data.condition}`

  const triad = resolveMapVisualTriadScalars(data)
  const surfaceW01 = surfaceWater01ForMap(data)
  const surfaceWater = mapSurfaceWaterClass(surfaceW01)
  const surfaceTier = mapSurfaceWaterTier(surfaceW01)
  const fruitMass = mapFruitMassClass(triad.fruit)
  const staleWash = data.condition === 'stale' ? 'map-surface-stale-wash' : ''

  return (
    <div
      className={[
        organic.outer,
        vitalityOuter,
        surfaceWater,
        staleWash,
        fruitMass,
        'map-stone-surface text-center transition-transform duration-200 ease-out',
        data.dimmed ? 'map-node-dimmed' : '',
        data.focusLineage ? 'map-node-lineage' : '',
        selected ? 'map-stone-selected' : '',
      ]
        .filter(Boolean)
        .join(' ')}
      data-stone-tone={stoneToneAttr}
      data-map-surface={surfaceTier}
      data-map-soil={triad.soil.toFixed(2)}
      data-map-fruit-scalar={triad.fruit.toFixed(2)}
      data-map-condition={data.condition}
      title={statusTitle}
    >
      <div
        className={[organic.shape, data.fertilizer_pulse ? 'map-fertilizer-pulse' : ''].filter(Boolean).join(' ')}
        style={stoneShapeMicroStyle(id, data.kind, triad.soil)}
        aria-hidden
      >
        <div
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
        <div className="pointer-events-none absolute inset-0 z-[3] map-stone-clip map-stone-mineral-grain" aria-hidden />
        <div className={`pointer-events-none absolute inset-0 z-[4] map-stone-clip ${condOverlay}`} aria-hidden />
        <StoneConditionOverlay condition={data.condition} />
      </div>
      <div className="relative z-[2] flex min-h-0 w-full flex-col items-center px-1 pb-2 pt-0.5">
        <Handle type="target" position={Position.Top} className={`${handleClass} !top-0`} />
        <div
          className="flex w-full flex-shrink-0 flex-col items-center justify-center px-1 pt-1"
          aria-hidden
        >
          <StoneKindGlyph
            kind={data.kind}
            className={[
              organic.glyph,
              data.kind === 'tree' ? 'map-stone-glyph--initiative-tree' : '',
              data.kind === 'branch' ? 'map-stone-glyph--project-branch' : '',
              data.kind === 'flower' ? 'map-stone-glyph--task-flower' : '',
              data.kind === 'seed' ? 'map-stone-glyph--idea-seed' : '',
            ]
              .filter(Boolean)
              .join(' ')}
            growth={data.growth}
            soil01={triad.soil}
            fruit01={triad.fruit}
            condition={data.condition}
          />
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
