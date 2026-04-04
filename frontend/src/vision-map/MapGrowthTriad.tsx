import type { GrowthTriadMetrics } from './mapGrowthMetrics'

type Props = {
  metrics: GrowthTriadMetrics
  caption?: string
  /** Which segment is driving the in-map inspector (highlights the bar). */
  activeSegment?: 'water' | 'soil' | 'fruit' | null
  /** Toggle in-map inspector sections (Water / Soil / Fruit). */
  onSegmentClick?: (segment: 'water' | 'soil' | 'fruit') => void
}

function Bar({
  icon,
  title,
  hint,
  value,
  dry,
  soft,
  vivid,
  onClick,
  isActive,
}: {
  icon: string
  title: string
  hint: string
  value: number
  dry: boolean
  soft: boolean
  vivid: boolean
  onClick?: () => void
  isActive?: boolean
}) {
  const pct = Math.round(value * 100)
  const interactive = Boolean(onClick)
  const inner = (
    <>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-lg shrink-0" aria-hidden>
            {icon}
          </span>
          <div className="min-w-0">
            <div
              className={[
                'text-[11px] font-semibold leading-tight',
                dry && icon === '💧' ? 'text-slate-500' : soft && icon === '🪨' ? 'text-slate-400' : 'text-slate-200',
              ]
                .filter(Boolean)
                .join(' ')}
            >
              {title}
            </div>
            <div className="text-[9px] text-slate-500 leading-tight truncate">{hint}</div>
          </div>
        </div>
        <span className="text-[10px] tabular-nums text-slate-500 shrink-0">{pct}%</span>
      </div>
      <div
        className={(() => {
          if (icon === '💧' && dry) return 'h-2 rounded-full overflow-hidden border border-amber-900/35 bg-slate-900/80'
          if (icon === '🪨' && soft)
            return 'h-2 rounded-full overflow-hidden border border-dashed border-slate-600/50 bg-slate-900/60'
          return 'h-2 rounded-full overflow-hidden border border-slate-700/80 bg-slate-900/70'
        })()}
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${title}: ${pct} percent`}
      >
        <div
          className={[
            'h-full rounded-full transition-[width] duration-300 ease-out',
            icon === '💧' &&
              (dry
                ? 'bg-gradient-to-r from-amber-900/50 to-amber-800/35 opacity-70'
                : 'bg-gradient-to-r from-sky-600 to-cyan-500'),
            icon === '🪨' &&
              (soft
                ? 'bg-gradient-to-r from-slate-600/50 to-slate-500/35 opacity-75'
                : 'bg-gradient-to-r from-stone-500 to-amber-900/90'),
            icon === '🍎' &&
              (vivid
                ? 'bg-gradient-to-r from-lime-600 to-emerald-400 saturate-125'
                : 'bg-gradient-to-r from-emerald-800/80 to-emerald-600/60'),
          ]
            .filter(Boolean)
            .join(' ')}
          style={{ width: `${pct}%` }}
        />
      </div>
    </>
  )
  if (interactive) {
    return (
      <button
        type="button"
        onClick={onClick}
        className={[
          'space-y-1 w-full text-left rounded-lg p-1 -m-1 hover:bg-slate-900/40 focus:outline-none focus:ring-1 focus:ring-teal-600/50',
          isActive ? 'ring-1 ring-teal-500/55 bg-teal-950/25' : '',
        ]
          .filter(Boolean)
          .join(' ')}
      >
        {inner}
      </button>
    )
  }
  return <div className="space-y-1">{inner}</div>
}

export function MapGrowthTriad({ metrics, caption, activeSegment = null, onSegmentClick }: Props) {
  const { water, soil, fruit } = metrics
  const dry = water < 0.38
  const soft = soil < 0.38
  const vivid = fruit > 0.65

  const waterHint =
    water < 0.4 ? 'Needs attention' : water > 0.72 ? 'People & updates in place' : 'Moderate attention'
  const soilHint =
    soil < 0.4 ? 'Needs definition' : soil > 0.68 ? 'Clarity & structure strong' : 'Partly defined'
  const fruitHint =
    fruit < 0.38 ? 'Little output yet' : fruit > 0.68 ? 'Producing output' : 'Some progress'

  return (
    <div
      className={[
        'rounded-xl border px-3 py-3 space-y-3.5',
        vivid ? 'border-emerald-800/40 bg-gradient-to-br from-emerald-950/25 to-slate-950/70' : 'border-teal-900/40 bg-gradient-to-br from-teal-950/20 to-slate-950/65',
      ].join(' ')}
    >
      <div className="text-[9px] uppercase tracking-wider text-teal-500/90 font-medium">
        Growth shape — tap to inspect in this panel
      </div>

      <div className="space-y-3">
        <Bar
          icon="💧"
          title="Water"
          hint={waterHint}
          value={water}
          dry={dry}
          soft={soft}
          vivid={vivid}
          isActive={activeSegment === 'water'}
          onClick={onSegmentClick ? () => onSegmentClick('water') : undefined}
        />
        <Bar
          icon="🪨"
          title="Soil"
          hint={soilHint}
          value={soil}
          dry={dry}
          soft={soft}
          vivid={vivid}
          isActive={activeSegment === 'soil'}
          onClick={onSegmentClick ? () => onSegmentClick('soil') : undefined}
        />
        <Bar
          icon="🍎"
          title="Fruit"
          hint={fruitHint}
          value={fruit}
          dry={dry}
          soft={soft}
          vivid={vivid}
          isActive={activeSegment === 'fruit'}
          onClick={onSegmentClick ? () => onSegmentClick('fruit') : undefined}
        />
      </div>

      {caption ? <p className="text-[11px] text-slate-400 leading-snug pt-0.5 border-t border-slate-800/80">{caption}</p> : null}
    </div>
  )
}
