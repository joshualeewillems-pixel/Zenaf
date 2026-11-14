import { useCallback, useMemo } from 'react'
import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'
import type { ConditionSeverity, GrowthState, MapEntityKind, MapNodePayload } from './ontology'
import {
  StoneGlyphMark,
  washColorFor,
  glyphForGrowth,
  type StoneGlyph,
} from './symbolicStone'
import { isGardenStackData, type CairnPreviewStone } from './cairn'
import {
  towerLayoutForMembers,
  type CairnMemberInput,
  type PortedStone,
} from './cairnTower'
import { CairnStoneSprite } from './CairnStoneSprite'
import { effectiveConditionSeverity } from './resolveConditionSeverity'
import { useNodeHoldGestures } from './useLongPress'
import { useCairnInteraction } from './cairnContext'
import { hierarchyTitleClass, entitySubtitleClass, stoneTextTone, entityLabelTextClass } from './mapNodeAppearance'

type CairnRfNode = Node<MapNodePayload, 'cairn'>

const handleClass =
  '!z-[3] !bg-stone-600/75 !w-2.5 !h-2.5 !min-w-2.5 !min-h-2.5 !border-0 !rounded-full opacity-70 hover:opacity-100 !left-1/2 !-translate-x-1/2 shadow-sm'

/** Whole-pile ring tones — same signal as a single stone's ring. */
const URGENCY_RING = '#d9a441'
const PULSE_RING = '#86b89a'

/**
 * Cairn — a project's stones as one cairn pile, rendered by the ported
 * tower layout (./cairnTower): sumi-e sprite stones seated on a
 * structural slab by the settled layout law (April spine + October
 * triples + bearing segments + profile seating + growth law), tinted
 * per member through the post-mount mask construction
 * (./CairnStoneSprite), with raked garden rings anchored to the pile's
 * actual footprint. The sub-stones are purely decorative (aria-hidden,
 * pointer-events-none): the cairn node is the single hit target for
 * tap (select/inspect), double-tap or the longer hold (fan out — or
 * unstack for a garden stack), the first hold (arm drag), and drag.
 */

/** Garden rings (port spec §6): concentric, dash-broken, squashed to
    the garden plane, anchored to the pile's measured footprint. The
    first ring sits 6px beyond the footprint, spacing 10.5px, groove
    fading ~0.78 per ring — extent is a continuous function of the
    footprint, so the rings grow gradually with the pile. The global
    rake register is the sand bed itself (ZenSandCanvas); these local
    rings yield while the user rakes (cairnContext.rakeActive). */
function GardenRings({
  cx,
  groundY,
  halfWidth,
  yielding,
}: {
  cx: number
  groundY: number
  halfWidth: number
  yielding: boolean
}) {
  const rings = []
  for (let k = 0; k < 24; k++) {
    const rx = halfWidth + 6 + k * 10.5
    const grooveOpacity = 0.36 * Math.pow(0.78, k)
    if (grooveOpacity < 0.03) break
    const ry = rx * 0.3
    const dash = `${6 + (k % 3) * 2.5} ${4 + (k % 2) * 2}`
    rings.push(
      <g key={k}>
        <ellipse
          cx={cx}
          cy={groundY + 1.4}
          rx={rx}
          ry={ry}
          fill="none"
          stroke="#9c7a4c"
          strokeWidth={1.6}
          strokeDasharray={dash}
          opacity={0.13 * Math.pow(0.78, k)}
        />
        <ellipse
          cx={cx}
          cy={groundY}
          rx={rx}
          ry={ry}
          fill="none"
          stroke="#120b06"
          strokeWidth={1.6}
          strokeDasharray={dash}
          opacity={grooveOpacity}
        />
      </g>,
    )
  }
  return (
    <svg
      className={`cairn-garden-rings${yielding ? ' cairn-garden-rings--yielding' : ''}`}
      style={{ position: 'absolute', left: 0, top: 0, overflow: 'visible' }}
      width="100%"
      height="100%"
      aria-hidden="true"
    >
      {rings}
    </svg>
  )
}

export function CairnNode({ id, data, selected }: NodeProps<CairnRfNode>) {
  const { onToggleCairn, onDragArm, onPressSpent, rakeActive } = useCairnInteraction()
  const toggle = useCallback(() => onToggleCairn(id), [onToggleCairn, id])
  const lp = useNodeHoldGestures({
    onDragArm: (info) => onDragArm(id, info.pointerId, info.clientX, info.clientY),
    onToggle: toggle,
    onPressSpent,
  })

  const isMega = isGardenStackData(data)
  const preview = (data.cairnPreview ?? []) as CairnPreviewStone[]
  const count = (data.cairnCount as number) ?? preview.length
  const wash = washColorFor((data.cairnProjectId as string) ?? null)
  const severity: ConditionSeverity = effectiveConditionSeverity(data)
  const labelTone = stoneTextTone('branch')

  /* The pile's members: the cairn pass threads the real members
     (stable ids, arrival times, activity, growth) onto the node.
     Graphs and fixtures without member threading fall back to
     preview-shaped members — the same information the legacy renderer
     had — so the pile still builds. */
  const members = useMemo<CairnMemberInput[]>(() => {
    const raw = (data.cairnMembers ?? null) as CairnMemberInput[] | null
    if (Array.isArray(raw) && raw.length) return raw
    const out: CairnMemberInput[] = []
    for (let i = 0; i < Math.max(count, 1); i++) {
      const p = preview[i]
      out.push({
        id: `${id}:preview:${i}`,
        kind: p?.kind ?? 'branch',
        activity: 0.5,
        createdAt: null,
        growth: p?.growth ?? 'dormant',
      })
    }
    return out
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, count, JSON.stringify(data.cairnMembers ?? null), preview.length])

  const memberById = useMemo(() => new Map(members.map((m) => [m.id, m])), [members])
  const layoutKey = `${id}|${wash}|${members.map((m) => `${m.id}@${m.createdAt ?? ''}`).join(',')}`
  const layout = useMemo(
    () => towerLayoutForMembers(id, members, { wash }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [layoutKey],
  )

  const glyphOf = (st: PortedStone): StoneGlyph | null => {
    if (st.role !== 'column' || !st.memberId) return null
    const m = memberById.get(st.memberId)
    if (!m) return null
    return glyphForGrowth((m.growth ?? 'dormant') as GrowthState, (m.kind ?? 'branch') as MapEntityKind)
  }

  const ring =
    severity > 0
      ? { color: URGENCY_RING, opacity: 0.45 + 0.18 * severity }
      : data.fertilizer_pulse
        ? { color: PULSE_RING, opacity: 0.85 }
        : null

  const hint = isMega
    ? `${count} stones · double-tap to unstack`
    : `${count} stones · double-tap to fan out`
  const title = isMega
    ? `${data.label} — ${count} stones stacked. Double-tap or hold longer to unstack; tap to inspect.`
    : `${data.label} — ${count} stones stacked. Double-tap or hold longer to fan out; tap to inspect.`

  return (
    <div
      className={[
        'map-stone-surface text-center select-none',
        selected ? 'map-stone-selected' : '',
        data.dimmed ? 'map-node-dimmed' : '',
        data.focusLineage ? 'map-node-lineage' : '',
      ]
        .filter(Boolean)
        .join(' ')}
      data-map-entity-kind="cairn"
      data-map-condition-severity={String(severity)}
      title={title}
      {...lp}
    >
      <div className="relative mx-auto" style={{ width: layout.width, height: layout.height + 10 }}>
        {/* Decorative pile only — no pointer affordances here; the node
            root above is the single tap/hold/drag target. */}
        <div aria-hidden="true" className="pointer-events-none absolute inset-0">
          <GardenRings
            cx={layout.footprintCx}
            groundY={layout.groundY}
            halfWidth={layout.footprintHalfWidth}
            yielding={rakeActive}
          />
          <svg
            style={{ position: 'absolute', left: 0, top: 0, overflow: 'visible', filter: 'blur(3px)' }}
            width="100%"
            height="100%"
            aria-hidden="true"
          >
            <ellipse
              cx={layout.footprintCx}
              cy={layout.groundY + 2}
              rx={layout.footprintHalfWidth * 0.92}
              ry={layout.footprintHalfWidth * 0.92 * 0.3}
              fill="#000000"
              opacity={0.32}
            />
          </svg>
          {ring ? (
            <svg
              className="absolute -inset-1.5"
              style={{ width: 'calc(100% + 12px)', height: 'calc(100% + 12px)' }}
              viewBox="0 0 100 100"
              preserveAspectRatio="none"
            >
              <ellipse
                cx="50"
                cy="50"
                rx="46"
                ry="46"
                fill="none"
                stroke={ring.color}
                strokeWidth={3}
                vectorEffect="non-scaling-stroke"
                opacity={ring.opacity}
              />
            </svg>
          ) : null}
          {layout.stones.map((s) => {
            const glyph = glyphOf(s)
            const glyphSize = Math.min(s.bodyWidth, s.bodyHeight) * 0.6
            return (
              <div
                key={s.seed}
                className="absolute"
                style={{
                  left: s.left,
                  top: s.top,
                  width: s.width,
                  height: s.height,
                  transform: `rotate(${s.rotation}deg)`,
                  // Rotate around the stone body's centre — the layout
                  // reports it in frame-box coordinates.
                  transformOrigin: `${s.originX}px ${s.originY}px`,
                }}
              >
                <CairnStoneSprite src={s.spriteUrl} tint={s.tint} />
                {glyph ? (
                  <svg
                    viewBox="0 0 64 64"
                    style={{
                      position: 'absolute',
                      left: s.originX - glyphSize / 2,
                      top: s.originY - glyphSize / 2,
                      width: glyphSize,
                      height: glyphSize,
                    }}
                    aria-hidden="true"
                  >
                    <StoneGlyphMark glyph={glyph} />
                  </svg>
                ) : null}
              </div>
            )
          })}
        </div>
        <div
          className="absolute -right-0.5 -bottom-0.5 z-20 flex h-6 min-w-6 items-center justify-center rounded-full bg-stone-900 px-1 text-[11px] font-semibold text-stone-100 border border-stone-600"
          role="img"
          aria-label={`${count} stones`}
        >
          {count}
        </div>
      </div>
      <div className="relative z-[20] flex w-full flex-col items-center px-2 pb-2 pt-1">
        <Handle type="target" position={Position.Top} className={`${handleClass} !top-0`} />
        <div className={`w-full max-w-full ${entitySubtitleClass(labelTone)} ${entityLabelTextClass()}`}>
          {hint}
        </div>
        <div className={`w-full max-w-full leading-snug ${hierarchyTitleClass('branch')} ${entityLabelTextClass()}`}>
          {data.label}
        </div>
        <Handle type="source" position={Position.Bottom} className={`${handleClass} !bottom-0`} />
      </div>
    </div>
  )
}

/** Re-exported for the harness: glyph choice is part of the stone contract. */
export { glyphForGrowth, type StoneGlyph }
