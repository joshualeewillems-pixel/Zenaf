import { useLayoutEffect, useRef, useState } from 'react'
import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'
import type { ConditionSeverity, MapNodePayload } from './ontology'
import {
  compactNodeStatusSummary,
  conditionShapeOverlayClass,
  entityCompactStatusClass,
  entityLabelTextClass,
  entityOrganicClasses,
  entitySubtitleClass,
  hierarchyTitleClass,
  mapFruitMassClass,
  mapSoilEdgeTier,
  mapWaterLevelSurfaceClass,
  resolveMapVisualTriadScalars,
  stoneTextTone,
  vitalityOuterClass,
} from './mapNodeAppearance'
import { mapEntityNodeLayoutPx } from './mapEntityNodeLayout'
import { stoneShapeMicroStyle } from './mapStoneShape'
import { effectiveConditionSeverity } from './resolveConditionSeverity'
import { MapStoneSoilRim } from './MapStoneSoilRim'
import { StoneCrackOverlay } from './StoneCrackOverlay'
import { StoneKindGlyph } from './StoneKindGlyph'

type EntityRfNode = Node<MapNodePayload, 'entityMap'>

const handleClass =
  '!z-[3] !bg-stone-600/75 !w-2.5 !h-2.5 !min-w-2.5 !min-h-2.5 !border-0 !rounded-full opacity-70 hover:opacity-100 !left-1/2 !-translate-x-1/2 shadow-sm'

export function EntityMapNode({ id, data, selected }: NodeProps<EntityRfNode>) {
  const organic = entityOrganicClasses(data.kind)
  const labelTone = stoneTextTone(data.kind)
  const stoneToneAttr = labelTone === 'on-light' ? 'light' : 'dark'
  const conditionSeverity: ConditionSeverity = effectiveConditionSeverity(data)
  const vitalityOuter = vitalityOuterClass(data.growth, conditionSeverity)
  const condOverlay = conditionShapeOverlayClass()
  const statusHint = compactNodeStatusSummary(data.growth, conditionSeverity)
  const statusTitle = `${data.growth} · structural severity ${conditionSeverity}/3 (map stone cracks)`

  const triad = resolveMapVisualTriadScalars(data)
  const soilTier = mapSoilEdgeTier(triad.soil)
  const waterSurfaceClass = mapWaterLevelSurfaceClass(data.water_level)
  const fruitMass = mapFruitMassClass(triad.fruit)
  const glyphEmphasis = selected ? 'selected' : data.focusLineage ? 'focused' : 'normal'

  const shapeRef = useRef<HTMLDivElement>(null)
  const layoutPx = mapEntityNodeLayoutPx(data.kind)
  const [stoneShapePx, setStoneShapePx] = useState(() => ({ w: layoutPx.width, h: layoutPx.height }))

  useLayoutEffect(() => {
    const el = shapeRef.current
    const fallback = mapEntityNodeLayoutPx(data.kind)
    setStoneShapePx({ w: fallback.width, h: fallback.height })
    if (!el) return
    const apply = (w: number, h: number) => {
      if (w > 0 && h > 0) setStoneShapePx({ w, h })
    }
    const r = el.getBoundingClientRect()
    apply(r.width, r.height)
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver((entries) => {
      const cr = entries[0]?.contentRect
      if (cr) apply(cr.width, cr.height)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [data.kind, id])

  return (
    <div
      className={[
        organic.outer,
        'flex min-h-0 flex-col',
        vitalityOuter,
        waterSurfaceClass,
        fruitMass,
        'map-stone-surface text-center transition-transform duration-200 ease-out',
        data.dimmed ? 'map-node-dimmed' : '',
        data.focusLineage ? 'map-node-lineage' : '',
        selected ? 'map-stone-selected' : '',
      ]
        .filter(Boolean)
        .join(' ')}
      style={{ ['--map-soil-01' as string]: triad.soil }}
      data-glyph-emphasis={glyphEmphasis}
      data-map-entity-kind={data.kind}
      data-stone-tone={stoneToneAttr}
      data-map-water-level={data.water_level ?? 'medium'}
      data-map-soil={triad.soil.toFixed(2)}
      data-map-soil-tier={soilTier}
      data-map-fruit-scalar={triad.fruit.toFixed(2)}
      data-map-condition-severity={String(conditionSeverity)}
      title={statusTitle}
    >
      <div
        ref={shapeRef}
        className={[organic.shape, data.fertilizer_pulse ? 'map-fertilizer-pulse' : ''].filter(Boolean).join(' ')}
        style={stoneShapeMicroStyle(id, data.kind)}
        aria-hidden
      >
        {/* Soil rim = visible grounding deficit (1 − triad.soil); triad.soil = grounding present */}
        <MapStoneSoilRim
          nodeId={id}
          stoneTone={stoneToneAttr}
          entityKind={data.kind}
          stoneShapeWidthPx={stoneShapePx.w}
          stoneShapeHeightPx={stoneShapePx.h}
          soil01={triad.soil}
        />
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
        {/* Gloss = water (stewardship); driven by `water_level` → `.map-water-*` on `.map-stone-surface` */}
        <div className="pointer-events-none absolute inset-0 z-[3] map-stone-clip map-stone-water-gloss" aria-hidden />
        <div className={`pointer-events-none absolute inset-0 z-[4] map-stone-clip ${condOverlay}`} aria-hidden />
        {/* Cracks = structural condition (severity); not triad soil */}
        <StoneCrackOverlay
          severity={conditionSeverity}
          nodeId={id}
          stoneTone={stoneToneAttr === 'light' ? 'light' : 'dark'}
        />
      </div>
      <div className="relative z-[20] flex min-h-0 w-full flex-1 flex-col px-1 pb-2 pt-1">
        <Handle type="target" position={Position.Top} className={`${handleClass} !top-0`} />
        <div className="grid min-h-0 w-full min-w-0 flex-1 grid-rows-[minmax(0,1fr)_auto] gap-y-2">
          <div className="flex w-full min-h-0 min-w-0 items-center justify-center px-1 pt-0.5" aria-hidden>
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
              conditionSeverity={conditionSeverity}
            />
          </div>
          <div className="flex w-full min-w-0 max-w-full flex-col items-center gap-2.5 px-2.5 pb-2">
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
        </div>
        <Handle type="source" position={Position.Bottom} className={`${handleClass} !bottom-0`} />
      </div>
    </div>
  )
}
