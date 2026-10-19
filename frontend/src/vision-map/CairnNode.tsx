import { useCallback } from 'react'
import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'
import type { ConditionSeverity, MapNodePayload } from './ontology'
import {
  SymbolicStone,
  washColorFor,
  glyphForGrowth,
  type StoneGlyph,
} from './symbolicStone'
import { MEGA_CAIRN_ID, type CairnPreviewStone } from './cairn'
import { towerLayout, type TowerStone } from './cairnTower'
import { effectiveConditionSeverity } from './resolveConditionSeverity'
import { useLongPress } from './useLongPress'
import { useCairnInteraction } from './cairnContext'
import { hierarchyTitleClass, entitySubtitleClass, stoneTextTone, entityLabelTextClass } from './mapNodeAppearance'

type CairnRfNode = Node<MapNodePayload, 'cairn'>

const handleClass =
  '!z-[3] !bg-stone-600/75 !w-2.5 !h-2.5 !min-w-2.5 !min-h-2.5 !border-0 !rounded-full opacity-70 hover:opacity-100 !left-1/2 !-translate-x-1/2 shadow-sm'

/** Whole-pile ring tones — same signal as a single stone's ring. */
const URGENCY_RING = '#d9a441'
const PULSE_RING = '#86b89a'

/**
 * Trail-cairn tower geometry lives in ./cairnTower (pure, deterministic):
 * a rule-of-thirds procedural sculpture — each consecutive triple stays
 * balanced, so the tower can lean, cantilever and recover like a real
 * rock-balancing sculpture — with small accent pebbles perched precariously
 * on column rims as the count grows toward twelve.
 */

const NEUTRAL_PREVIEW: CairnPreviewStone = {
  growth: 'dormant',
  kind: 'branch',
  severity: 0,
  pulse: false,
}

/**
 * Cairn — a project's stones as one trail-cairn tower. The sub-stones are
 * purely decorative (aria-hidden, pointer-events-none): the cairn node is
 * the single hit target for tap (select/inspect), long-press (fan out — or
 * unstack for the whole-garden mega-cairn), and drag (move the pile).
 */
export function CairnNode({ id, data, selected }: NodeProps<CairnRfNode>) {
  const { onToggleCairn } = useCairnInteraction()
  const toggle = useCallback(() => onToggleCairn(id), [onToggleCairn, id])
  const lp = useLongPress(toggle)

  const isMega = id === MEGA_CAIRN_ID
  const preview = (data.cairnPreview ?? []) as CairnPreviewStone[]
  const count = (data.cairnCount as number) ?? preview.length
  const wash = washColorFor((data.cairnProjectId as string) ?? null)
  const severity: ConditionSeverity = effectiveConditionSeverity(data)
  const labelTone = stoneTextTone('branch')

  const { stones, height: towerH, width: towerW } = towerLayout(id, Math.max(count, 1))
  // Most urgent on top: preview arrives urgency-ordered. Accent pebbles
  // are neutral (a plain seed glyph reads cleanest at small scale).
  const stoneData = (st: TowerStone): CairnPreviewStone =>
    st.accent || st.previewIndex < 0
      ? NEUTRAL_PREVIEW
      : (preview[st.previewIndex] ?? preview[preview.length - 1] ?? NEUTRAL_PREVIEW)

  const ring =
    severity > 0
      ? { color: URGENCY_RING, opacity: 0.45 + 0.18 * severity }
      : data.fertilizer_pulse
        ? { color: PULSE_RING, opacity: 0.85 }
        : null

  const hint = isMega
    ? `${count} stones · long-press to unstack`
    : `${count} stones · long-press to fan out`
  const title = isMega
    ? `${data.label} — ${count} stones stacked. Long-press to unstack; tap to inspect.`
    : `${data.label} — ${count} stones stacked. Long-press to fan out; tap to inspect.`

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
      <div className="relative mx-auto" style={{ width: towerW, height: towerH + 10 }}>
        {/* Decorative pile only — no pointer affordances here; the node
            root above is the single tap/long-press/drag target. */}
        <div aria-hidden="true" className="pointer-events-none absolute inset-0">
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
          {stones.map((s, i) => {
            const p = stoneData(s)
            return (
              <div
                key={i}
                className="absolute"
                style={{
                  left: s.left,
                  top: s.top,
                  width: s.size,
                  height: s.size,
                  transform: `rotate(${s.rotation}deg)`,
                  // rotate around the stone body's center (viewbox 31.5,38)
                  transformOrigin: '49.2% 59.4%',
                }}
              >
                <SymbolicStone
                  growth={s.accent ? 'dormant' : p.growth}
                  kind={p.kind}
                  severity={0}
                  fertilizerPulse={false}
                  washColor={wash}
                  variantSeed={s.seed}
                  size={s.size}
                />
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
