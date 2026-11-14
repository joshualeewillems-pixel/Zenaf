import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'
import type { ConditionSeverity, MapEntityKind, MapNodePayload } from './ontology'
import {
  compactNodeStatusSummary,
  entityCompactStatusClass,
  entityLabelTextClass,
  hierarchyTitleClass,
  stoneTextTone,
} from './mapNodeAppearance'
import { mapEntityNodeLayoutPx } from './mapEntityNodeLayout'
import { effectiveConditionSeverity } from './resolveConditionSeverity'
import { SymbolicStone, washColorFor, washKeyForPayload } from './symbolicStone'
import { CairnStoneSprite } from './CairnStoneSprite'
import type { PortedStone } from './cairnTower'
import { longPressTargetFor } from './cairn'
import { useNodeHoldGestures } from './useLongPress'
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

/** Ring tones for a fanned member's painted stone — the same signal
    SymbolicStone draws on a plain stone (amber = needs attention by
    severity, green = recently updated), kept when the stone paints. */
const URGENCY_RING = '#d9a441'
const PULSE_RING = '#86b89a'

/**
 * One stone per node, with the label block beneath. A plain node wears
 * the symbolic stone (silhouette + wash + urgency ring — no on-stone
 * marks; the label block carries the stone's name and status, never
 * its type). A member of a
 * fanned cairn wears its painted pile stone instead — the exact sprite
 * and tint the pile's layout gave it, threaded onto the node as
 * `fannedStone` by expandCairn — over the same label block, with the
 * same ring channel around the painted stone. Holds run the ladder:
 * hold still to arm drag for the stone; keep holding (tier 2) and a
 * member of an already-fanned cairn stacks its cairn back, while the
 * initiative (tree) stone toggles the whole-garden stack — the pile
 * on its own stone vs the full garden. Double-tap opens: a stone's
 * data sheet, a cairn's fan. Tap keeps the existing select/focus
 * behavior.
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
  const fannedStone = (data as { fannedStone?: PortedStone }).fannedStone ?? null
  const fannedRing = fannedStone
    ? conditionSeverity > 0
      ? { color: URGENCY_RING, opacity: 0.45 + 0.18 * conditionSeverity }
      : data.fertilizer_pulse
        ? { color: PULSE_RING, opacity: 0.85 }
        : null
    : null

  const { onToggleCairn, onToggleGardenStack, onDragArm, onPressSpent } = useCairnInteraction()
  const expandedFromCairn = (data as { expandedFromCairn?: string }).expandedFromCairn ?? null
  const target = longPressTargetFor(data.kind, expandedFromCairn, id)

  const lp = useNodeHoldGestures({
    onDragArm: (info) => onDragArm(id, info.pointerId, info.clientX, info.clientY),
    onToggle:
      target.action === 'collapseCairn'
        ? () => onToggleCairn(target.cairnId)
        : target.action === 'toggleGardenStack'
          ? () => onToggleGardenStack(target.treeId)
          : undefined,
    onPressSpent,
  })

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
      <div className="flex w-full items-center justify-center pt-2" aria-hidden>
        {fannedStone ? (
          <div className="relative" style={{ width: fannedStone.width, height: fannedStone.height }}>
            <div
              className="absolute"
              style={{
                left: 0,
                top: 0,
                width: fannedStone.width,
                height: fannedStone.height,
                transform: `rotate(${fannedStone.rotation}deg)`,
                // Rotate around the stone body's centre — the layout
                // reports it in frame-box coordinates.
                transformOrigin: `${fannedStone.originX}px ${fannedStone.originY}px`,
              }}
            >
              <CairnStoneSprite src={fannedStone.spriteUrl} tint={fannedStone.tint} />
            </div>
            {fannedRing ? (
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
                  stroke={fannedRing.color}
                  strokeWidth={3}
                  vectorEffect="non-scaling-stroke"
                  opacity={fannedRing.opacity}
                />
              </svg>
            ) : null}
          </div>
        ) : (
          <SymbolicStone
            growth={data.growth}
            kind={data.kind}
            severity={conditionSeverity}
            fertilizerPulse={!!data.fertilizer_pulse}
            washColor={wash}
            variantSeed={data.ref.id}
            size={STONE_SIZE_BY_KIND[data.kind] ?? 72}
          />
        )}
      </div>
      <div className="relative z-[20] flex w-full min-w-0 flex-col px-1 pb-2 pt-1">
        <Handle type="target" position={Position.Top} className={`${handleClass} !top-0`} />
        <div className="flex w-full min-w-0 max-w-full flex-col items-center gap-1 px-2.5">
          {/* No kind subtitle line (founder ruling, 2026-11-13): a
              stone shows its name and its status — its type is not
              displayed, and producers no longer compose one. */}
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
