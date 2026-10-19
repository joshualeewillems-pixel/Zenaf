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
 * Trail-cairn tower geometry. Stones shrink toward the top and each one
 * sits INTO the one below (the vertical step is well under a stone's
 * height), with small deterministic horizontal offsets for a hand-balanced
 * feel — one pile, not separate pebbles and not a pyramid.
 */
const TOWER_BASE = 50
const TOWER_SHRINK = 0.86
/** Vertical step between stones, as a fraction of the lower stone's size. */
const TOWER_STEP = 0.34
const TOWER_MAX_DX = 4
const TOWER_W = TOWER_BASE + TOWER_MAX_DX * 2 + 16

/** 3–5 tower stones depending on the count — the mega-cairn gets the full five. */
export function towerStoneCount(count: number): number {
  if (count >= 20) return 5
  if (count >= 8) return 4
  return 3
}

function hash32(s: string): number {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

export type TowerStone = {
  /** px size of the stone's svg box */
  size: number
  /** px from the tower container's left edge to the stone's left edge */
  left: number
  /** px from the tower container's top edge to the stone's top edge */
  top: number
  /** preview index (0 = most urgent, sits highest) driving glyph + variant */
  previewIndex: number
}

/**
 * Pure tower layout: bottom-up, shrinking, overlapping, slightly offset.
 * Exported for the harness — the visual contract lives here.
 */
export function towerLayout(cairnId: string, count: number): { stones: TowerStone[]; height: number; width: number } {
  const n = towerStoneCount(count)
  const sizes: number[] = []
  for (let i = 0; i < n; i++) sizes.push(Math.round(TOWER_BASE * Math.pow(TOWER_SHRINK, i)))
  const steps = sizes.slice(0, n - 1).map((s) => s * TOWER_STEP)
  const totalH = sizes[0]! + steps.reduce((a, b) => a + b, 0)
  const cx = TOWER_W / 2
  const stones: TowerStone[] = []
  let bottomEdge = totalH
  for (let i = 0; i < n; i++) {
    if (i > 0) bottomEdge -= steps[i - 1]!
    const size = sizes[i]!
    const dx = (hash32(`${cairnId}:${n - 1 - i}`) % 9) - 4 // -4..+4, stable
    stones.push({
      size,
      left: cx + dx - size / 2,
      top: bottomEdge - size,
      previewIndex: n - 1 - i,
    })
  }
  return { stones, height: totalH, width: TOWER_W }
}

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
  // Most urgent on top: preview arrives urgency-ordered.
  const stoneData = (previewIndex: number): CairnPreviewStone =>
    preview[previewIndex] ?? preview[preview.length - 1] ?? NEUTRAL_PREVIEW

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
            const p = stoneData(s.previewIndex)
            return (
              <div
                key={i}
                className="absolute"
                style={{ left: s.left, top: s.top, width: s.size, height: s.size }}
              >
                <SymbolicStone
                  growth={p.growth}
                  kind={p.kind}
                  severity={0}
                  fertilizerPulse={false}
                  washColor={wash}
                  variantSeed={`${id}:${s.previewIndex}`}
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
