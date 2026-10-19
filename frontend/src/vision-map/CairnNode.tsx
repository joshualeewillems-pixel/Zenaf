import { useCallback } from 'react'
import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'
import type { ConditionSeverity, MapNodePayload } from './ontology'
import { SymbolicStone, washColorFor, glyphForGrowth, type StoneGlyph } from './symbolicStone'
import { effectiveConditionSeverity } from './resolveConditionSeverity'
import { useLongPress } from './useLongPress'
import { useCairnInteraction } from './cairnContext'
import { hierarchyTitleClass, entitySubtitleClass, stoneTextTone, entityLabelTextClass } from './mapNodeAppearance'

type CairnRfNode = Node<MapNodePayload, 'cairn'>

type CairnPreviewStone = {
  growth: MapNodePayload['growth']
  kind: MapNodePayload['kind']
  severity: number
  pulse: boolean
}

const MINI_STONE = 40
const STACK_LIFT = 24
const MAX_STACK_GLYPHS = 3

const handleClass =
  '!z-[3] !bg-stone-600/75 !w-2.5 !h-2.5 !min-w-2.5 !min-h-2.5 !border-0 !rounded-full opacity-70 hover:opacity-100 !left-1/2 !-translate-x-1/2 shadow-sm'

/**
 * Cairn — a project's stones stacked into one node. Renders a vertical
 * stack of 2–4 symbolic stones (most urgent on top) plus a count badge.
 * Tap selects (existing inspector behavior); long-press fans the members out.
 */
export function CairnNode({ id, data, selected }: NodeProps<CairnRfNode>) {
  const { onToggleCairn } = useCairnInteraction()
  const toggle = useCallback(() => onToggleCairn(id), [onToggleCairn, id])
  const lp = useLongPress(toggle)

  const preview = ((data.cairnPreview ?? []) as CairnPreviewStone[]).slice(0, MAX_STACK_GLYPHS)
  const count = (data.cairnCount as number) ?? preview.length
  const wash = washColorFor((data.cairnProjectId as string) ?? null)
  const severity: ConditionSeverity = effectiveConditionSeverity(data)
  const labelTone = stoneTextTone('branch')
  // Render top = most urgent: preview arrives urgency-ordered, so the
  // first stone sits highest in the stack.
  const stackH = MINI_STONE + Math.max(0, preview.length - 1) * STACK_LIFT

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
      title={`${data.label} — ${count} stones stacked. Long-press to fan out; tap to inspect.`}
      {...lp}
    >
      <div className="relative mx-auto" style={{ width: MINI_STONE + 20, height: stackH + 10 }} aria-hidden>
        {preview.map((p, i) => {
          const lift = (preview.length - 1 - i) * STACK_LIFT
          return (
            <div
              key={i}
              className="absolute left-1/2"
              style={{ bottom: lift, transform: 'translateX(-50%)', zIndex: preview.length - i }}
            >
              <SymbolicStone
                growth={p.growth}
                kind={p.kind}
                severity={p.severity as ConditionSeverity}
                fertilizerPulse={p.pulse}
                washColor={wash}
                size={MINI_STONE}
              />
            </div>
          )
        })}
        <div
          className="absolute -right-0.5 -bottom-0.5 z-20 flex h-6 min-w-6 items-center justify-center rounded-full bg-stone-900 px-1 text-[11px] font-semibold text-stone-100 border border-stone-600"
          aria-label={`${count} stones`}
        >
          {count}
        </div>
      </div>
      <div className="relative z-[20] flex w-full flex-col items-center px-2 pb-2 pt-1">
        <Handle type="target" position={Position.Top} className={`${handleClass} !top-0`} />
        <div className={`w-full max-w-full ${entitySubtitleClass(labelTone)} ${entityLabelTextClass()}`}>
          {count} stones · long-press to fan out
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
