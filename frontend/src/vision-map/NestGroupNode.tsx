import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'
import type { NestGroupNodeData } from './nesting'
import { entityLabelTextClass, hierarchyTitleClass } from './mapNodeAppearance'
import { hash01, organicEllipticalBorderRadiusPct } from './organicBorderRadius'
import type { MapNodePayload } from './ontology'

type NestRfNode = Node<NestGroupNodeData, 'nestGroup'>

/**
 * Title size matches initiative (tree) main label — see `hierarchyTitleClass('tree')` in mapNodeAppearance.
 * Geometry scales from the former 15px baseline so the cairn grows with the type.
 */
const NEST_TITLE_BASELINE_PX = 15
export const NEST_TITLE_FONT_PX = 23
const NEST_GEOMETRY_SCALE = NEST_TITLE_FONT_PX / NEST_TITLE_BASELINE_PX

function nestScalePx(n: number): number {
  return Math.round(n * NEST_GEOMETRY_SCALE)
}

const NEST_DEFAULT_LAYER_LIFT_PX = nestScalePx(12)

/** Base slab — scaled with nest title (tree parity). */
export const NEST_CAIRN_BASE_WIDTH_PX = nestScalePx(276)
export const NEST_CAIRN_BASE_HEIGHT_PX = nestScalePx(132)
/** React Flow layout box — keep in sync with `.map-nest-node` rules in mapAesthetics.css */
export const NEST_NODE_LAYOUT_WIDTH_PX = nestScalePx(352)
export const NEST_NODE_LAYOUT_HEIGHT_PX = nestScalePx(336)

const kindColor: Record<MapNodePayload['kind'], string> = {
  tree: '#5f6f66',
  branch: '#59606f',
  flower: '#d7d3cb',
  fruit: '#5f4e3e',
  seed: '#6f5b4a',
}

function stoneFaceBackground(hex: string, hA: number, hB: number): string {
  const cx = 42 + Math.round(hA * 16)
  const cy = 28 + Math.round(hB * 22)
  const rx = 88 + Math.round(hA * 10)
  const ry = 72 + Math.round(hB * 18)
  return `radial-gradient(ellipse 108% 62% at 50% 0%, rgba(255,255,255,0.1) 0%, transparent 38%), radial-gradient(ellipse ${rx}% ${ry}% at ${cx}% ${cy}%, rgba(255,255,255,0.13) 0%, transparent 58%), linear-gradient(180deg, ${hex}f2 0%, ${hex} 64%, #151b26 100%)`
}

export function NestGroupNode({ data }: NodeProps<NestRfNode>) {
  const layers: MapNodePayload['kind'][] =
    data.stoneKinds.length > 0 ? data.stoneKinds : data.strataKinds.length > 0 ? data.strataKinds : (['branch'] as MapNodePayload['kind'][])
  const visibleCount = Math.min(12, layers.length)
  const layerStyles = (() => {
    const out: Array<{
      widthPx: number
      offsetPx: number
      rotateDeg: number
      heightPx: number
      radius: string
      yLiftPx: number
      scaleX: number
      skewDeg: number
    }> = []
    const bottomStoneWidthPx = NEST_CAIRN_BASE_WIDTH_PX
    const bottomStoneHeightPx = NEST_CAIRN_BASE_HEIGHT_PX
    const minUpperW = nestScalePx(28)
    const minUpperH = nestScalePx(18)
    const maxUpperH = nestScalePx(48)
    /** Keep lateral drift proportional to base width. */
    const MAX_CENTER_DRIFT_PX = bottomStoneWidthPx * 0.24
    const bottomCenterX = bottomStoneWidthPx / 2
    /** 0 = first stone above base, 1 = top cap (when multiple uppers). */
    const upperSpan = Math.max(1, visibleCount - 2)

    let prevWidthPx = bottomStoneWidthPx
    let prevCenterX = bottomCenterX
    let prevHeightPx = bottomStoneHeightPx
    let cumulativeLift = 0
    /** Deterministic 50/50: alternate L/R starting with right vs starting with left (same nest = stable). */
    const leadDriftRight = hash01(`${data.nestId}:cairn-drift-phase`) >= 0.5
    for (let i = 1; i < visibleCount; i++) {
      const s = `${data.nestId}:${layers[i]}:${i}`
      const hA = hash01(`${s}:a`)
      const hB = hash01(`${s}:b`)
      const hC = hash01(`${s}:c`)
      const hD = hash01(`${s}:d`)
      const hE = hash01(`${s}:e`)
      const hF = hash01(`${s}:f`)
      const stackT = (i - 1) / upperSpan

      // Taper without huge mid-stack flare (was reading as one wildly offset slab).
      const widthDelta = (hA - 0.5) * 0.34
      const depthBias = -0.04 - stackT * 0.26
      const midFlare = hF > 0.86 ? 0.02 + (hF - 0.86) * 0.14 : 0
      let widthFactor = 1 + widthDelta + depthBias + midFlare
      widthFactor = Math.max(0.58, Math.min(1.14, widthFactor))
      let widthPx = prevWidthPx * widthFactor
      // Top of stack: push toward 50–70% of a “typical” mid stone for miniature cap stones.
      const topShrink = stackT > 0.65 ? 0.55 + (1 - stackT) * 0.35 + hD * 0.12 : 1
      if (stackT > 0.55) widthPx *= topShrink
      widthPx = Math.max(minUpperW, Math.min(bottomStoneWidthPx * 1.12, widthPx))

      // Height: thicker bases, thinner caps; uneven rhythm.
      const heightFactor = Math.max(0.72, Math.min(1.28, 0.88 + hD * 0.38))
      let heightPx = Math.max(minUpperH, Math.min(maxUpperH, prevHeightPx * heightFactor))
      if (stackT > 0.7) heightPx *= 0.78 + hE * 0.12

      // Controlled oscillation: L/R/L/R or R/L/R/L depending on leadDriftRight.
      const direction = leadDriftRight
        ? i % 2 === 0
          ? -1
          : 1
        : i % 2 === 0
          ? 1
          : -1
      const driftScale = i <= 2 ? 0.52 : i === 3 ? 0.72 : 1
      const driftMagnitude = widthPx * (0.1 + hE * 0.07) * driftScale
      const localBias = widthPx * (0.018 + hC * 0.032)
      let centerX = prevCenterX + direction * (driftMagnitude + localBias)
      const shouldResetNearCenter = i > 0 && i % 4 === 0
      if (shouldResetNearCenter) {
        const resetBand = widthPx * (0.05 + hB * 0.05)
        centerX = bottomCenterX + (hF - 0.5) * 2 * resetBand
      }
      centerX = Math.max(
        bottomCenterX - MAX_CENTER_DRIFT_PX,
        Math.min(bottomCenterX + MAX_CENTER_DRIFT_PX, centerX),
      )
      const offsetPx = centerX - widthPx / 2
      const rotateDeg = (hC - 0.5) * 4.2

      // Strong overlap vs lower stone so layers don’t visually float; cap uses prev height.
      const tight = hash01(`${s}:stack`) > 0.38
      const overlapRatio = tight ? 0.5 + hE * 0.14 : 0.4 + hE * 0.12
      let overlap = Math.max(heightPx * overlapRatio, prevHeightPx * 0.36)
      overlap = Math.min(overlap, prevHeightPx * 0.68)
      const yLiftPx = cumulativeLift + (prevHeightPx - overlap)
      cumulativeLift = yLiftPx

      const radius = organicEllipticalBorderRadiusPct(hA, hB, hC, hD, hE, hF)
      const scaleX = 0.97 + (hF - 0.5) * 0.06
      const skewDeg = (hE - 0.5) * 2
      out.push({ widthPx, offsetPx, rotateDeg, heightPx, radius, yLiftPx, scaleX, skewDeg })
      prevWidthPx = widthPx
      prevCenterX = centerX
      prevHeightPx = heightPx
    }
    return out
  })()
  const upperLayers = layers.slice(1, visibleCount)
  const baseRadius = organicEllipticalBorderRadiusPct(
    hash01(`${data.nestId}:brx1`),
    hash01(`${data.nestId}:brx2`),
    hash01(`${data.nestId}:brx3`),
    hash01(`${data.nestId}:brx4`),
    hash01(`${data.nestId}:bry1`),
    hash01(`${data.nestId}:bry2`),
  )
  const baseFace = (() => {
    const hx = hash01(`${data.nestId}:bf1`)
    const hy = hash01(`${data.nestId}:bf2`)
    const cx = 40 + Math.round(hx * 18)
    const cy = 26 + Math.round(hy * 20)
    const rx = 90 + Math.round(hx * 8)
    const ry = 70 + Math.round(hy * 16)
    const c = kindColor[layers[0] ?? 'branch']
    return `radial-gradient(ellipse 108% 62% at 50% 0%, rgba(255,255,255,0.11) 0%, transparent 38%), radial-gradient(ellipse ${rx}% ${ry}% at ${cx}% ${cy}%, rgba(255,255,255,0.16) 0%, transparent 55%), linear-gradient(180deg, ${c}e8 0%, ${c} 58%, #141c28 100%)`
  })()

  return (
    <div
      className={[
        'map-nest-node',
        data.vitality.soft ? 'map-nest--soft' : '',
        data.selected ? 'map-nest--selected' : 'map-nest--idle',
        data.dimmed ? 'map-node-dimmed' : '',
        data.focusLineage ? 'map-node-lineage' : '',
      ]
        .filter(Boolean)
        .join(' ')}
      style={{ width: NEST_NODE_LAYOUT_WIDTH_PX, height: NEST_NODE_LAYOUT_HEIGHT_PX }}
      title={`Nested group (${data.memberCount} nodes)`}
    >
      <Handle type="target" position={Position.Top} className="map-nest-handle !top-0" />
      <div className="map-nest-cairn">
        <div
          className={[
            'map-nest-stone-stack',
            data.vitality.lush
              ? 'map-nest-stone-stack--lush'
              : data.vitality.dry
                ? 'map-nest-stone-stack--dry'
                : '',
          ]
            .filter(Boolean)
            .join(' ')}
        >
        <div className="map-nest-base-shell">
          <span
            className="map-nest-layer map-nest-base-layer"
            style={{
              background: baseFace,
              width: `${NEST_CAIRN_BASE_WIDTH_PX}px`,
              marginLeft: '0px',
              height: `${NEST_CAIRN_BASE_HEIGHT_PX}px`,
              borderRadius: baseRadius,
              transform: 'translateY(0px) rotate(0deg) scaleX(1) skewX(0deg)',
              boxShadow: [
                `inset 0 ${nestScalePx(2)}px 0 rgba(255,255,255,0.26)`,
                `inset 0 ${-nestScalePx(4)}px 0 rgba(0,0,0,0.42)`,
                `0 ${nestScalePx(10)}px ${nestScalePx(22)}px rgba(15,23,42,0.45)`,
                `0 ${nestScalePx(22)}px ${nestScalePx(38)}px rgba(15,23,42,0.32)`,
                '0 0 0 1px rgba(0,0,0,0.12)',
              ].join(', '),
              zIndex: 1,
            }}
          />
        </div>
        <div className="map-nest-upper-stack" aria-hidden>
        {upperLayers.map((k, i) => (
          <span
            key={`${k}-${i + 1}`}
            className="map-nest-layer"
            style={{
              background: stoneFaceBackground(
                kindColor[k],
                hash01(`${data.nestId}:${k}:${i + 1}:sf1`),
                hash01(`${data.nestId}:${k}:${i + 1}:sf2`),
              ),
              width: `${Math.round(layerStyles[i]?.widthPx ?? nestScalePx(88))}px`,
              marginLeft: `${layerStyles[i]?.offsetPx ?? 0}px`,
              height: `${Math.round(layerStyles[i]?.heightPx ?? nestScalePx(26))}px`,
              borderRadius: layerStyles[i]?.radius,
              transform: `translateY(${-Math.round(layerStyles[i]?.yLiftPx ?? i * NEST_DEFAULT_LAYER_LIFT_PX)}px) rotate(${layerStyles[i]?.rotateDeg ?? 0}deg) scaleX(${layerStyles[i]?.scaleX ?? 1}) skewX(${layerStyles[i]?.skewDeg ?? 0}deg)`,
              boxShadow: (() => {
                const t = (i + 1) / Math.max(1, upperLayers.length)
                const hi = 0.2 + (1 - t) * 0.12
                const lo = 0.28 + (1 - t) * 0.18
                const castA = 0.26 + (1 - t) * 0.2
                const castB = 0.16 + (1 - t) * 0.16
                const contact = 0.35 + (1 - t) * 0.25
                const s = nestScalePx
                return [
                  `inset 0 ${s(2)}px 1px rgba(255,255,255,${hi.toFixed(3)})`,
                  `inset 0 ${-s(3)}px ${s(2)}px rgba(0,0,0,${lo.toFixed(3)})`,
                  `0 ${s(Math.round(2 + (1 - t) * 2))}px ${s(Math.round(4 + (1 - t) * 3))}px rgba(0,0,0,${contact.toFixed(3)})`,
                  `0 ${s(Math.round(5 + (1 - t) * 5))}px ${s(Math.round(12 + (1 - t) * 8))}px rgba(15,23,42,${castA.toFixed(3)})`,
                  `0 ${s(Math.round(10 + (1 - t) * 6))}px ${s(Math.round(22 + (1 - t) * 14))}px rgba(15,23,42,${castB.toFixed(3)})`,
                ].join(', ')
              })(),
              // Strict physical layering: higher stones always in front of lower stones.
              zIndex: 11 + i,
            }}
          />
        ))}
        </div>
        </div>
        <div className="map-nest-base-chrome">
          <div className="map-nest-base-inner">
            <button
              type="button"
              className="map-nest-expand-cue"
              onPointerDown={(e) => {
                e.stopPropagation()
              }}
              onClick={(e) => {
                e.stopPropagation()
                data.onExpand?.()
              }}
              title="Expand nested cluster"
              aria-label="Expand nested cluster"
            >
              unfold
            </button>
            <div className="map-nest-badge" title={`${data.memberCount} hidden nodes`}>
              {data.memberCount}
            </div>
            <div
              className={[
                'map-nest-label--in-base',
                hierarchyTitleClass('tree'),
                entityLabelTextClass(),
              ].join(' ')}
            >
              {data.dominantLabel}
            </div>
          </div>
        </div>
      </div>
      <Handle type="source" position={Position.Bottom} className="map-nest-handle !bottom-0" />
    </div>
  )
}

