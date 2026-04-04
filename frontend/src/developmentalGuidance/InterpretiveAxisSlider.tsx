import type { AxisVisualEmphasis } from './interpretiveAxisSliderInfer'

export type InterpretiveAxisSliderProps = {
  leftLabel: string
  rightLabel: string
  /** Natural-language tilt from the read layer (not shown as a raw score). */
  tilt: string
  emphasis: AxisVisualEmphasis
  /** 0–100, dot anchored from left. */
  dotPct: number
  /** Optional caption below the track; defaults to `tilt` when omitted. */
  description?: string
}

/**
 * Minimal dialectic axis: two poles, track, dot — no numbers, no percentages shown.
 */
export function InterpretiveAxisSlider({
  leftLabel,
  rightLabel,
  tilt,
  emphasis,
  dotPct,
  description,
}: InterpretiveAxisSliderProps) {
  const clamped = Math.min(100, Math.max(0, dotPct))
  const caption = (description ?? tilt).trim() || undefined
  const isStrong = emphasis === 'strong'
  const isNeutral = emphasis === 'neutral'

  const trackGradient =
    isNeutral || !isStrong
      ? 'linear-gradient(90deg, rgb(41 37 36) 0%, rgb(55 48 42) 50%, rgb(41 37 36) 100%)'
      : clamped >= 55
        ? `linear-gradient(90deg, rgb(41 37 36) 0%, rgb(62 55 50) ${Math.max(35, clamped - 18)}%, rgb(80 72 66) 100%)`
        : `linear-gradient(90deg, rgb(80 72 66) 0%, rgb(62 55 50) ${Math.min(65, clamped + 18)}%, rgb(41 37 36) 100%)`

  return (
    <div className="space-y-1.5">
      <div className="flex justify-between gap-3 text-[10px] leading-snug">
        <span className="text-left text-stone-400">{leftLabel}</span>
        <span className="text-right text-stone-400">{rightLabel}</span>
      </div>
      <div
        className={[
          'relative h-2 w-full rounded-full',
          isStrong ? 'ring-1 ring-amber-900/30' : 'ring-1 ring-stone-700/45',
        ].join(' ')}
        role="img"
        aria-label={`Interpretive tension between ${leftLabel} and ${rightLabel}. No numeric score.`}
      >
        <div
          className="absolute inset-0 rounded-full"
          style={{ background: trackGradient }}
        />
        <div
          className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border transition-[left,background-color,border-color] duration-150 ease-out"
          style={{
            left: `${clamped}%`,
            borderColor: isStrong ? 'rgb(214 211 209 / 0.4)' : 'rgb(120 113 108 / 0.45)',
            backgroundColor: isStrong ? 'rgb(231 229 228)' : isNeutral ? 'rgb(120 113 108)' : 'rgb(168 162 158)',
            boxShadow: isStrong ? '0 0 0 1px rgb(28 25 23 / 0.45)' : undefined,
          }}
        />
      </div>
      {caption ? (
        <p className="text-[10px] text-stone-500 leading-snug pt-0.5">{caption}</p>
      ) : null}
    </div>
  )
}
