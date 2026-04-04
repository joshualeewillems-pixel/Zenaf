import { useMemo, useState } from 'react'
import {
  buildCouncilIntegrityReviewExportJson,
  clearCouncilIntegrityReviewTraces,
  getCouncilIntegrityReviewBreakdown,
} from '../../ai-actions'

export function CouncilIntegrityReviewSection() {
  const [ringVersion, setRingVersion] = useState(0)
  const [copied, setCopied] = useState(false)

  const breakdown = useMemo(() => {
    void ringVersion
    return getCouncilIntegrityReviewBreakdown()
  }, [ringVersion])

  const total =
    breakdown.grounded +
    breakdown.grounded_but_interpretive +
    breakdown.weak_support +
    breakdown.unreliable

  const copyExport = async () => {
    const json = buildCouncilIntegrityReviewExportJson()
    try {
      await navigator.clipboard.writeText(json)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }

  const clearSamples = () => {
    clearCouncilIntegrityReviewTraces()
    setRingVersion((v) => v + 1)
  }

  return (
    <section className="rounded-xl border border-slate-700/80 bg-slate-900/40 p-4 space-y-3">
      <div>
        <h2 className="text-sm font-semibold text-slate-100">Council synthesis integrity (review)</h2>
        <p className="text-xs text-slate-400 mt-1 leading-relaxed">
          After council runs with <span className="text-slate-300">Include Atria synthesis</span>, a compact integrity row
          is attached to the in-memory AI trace ring (this browser only, max ~32 traces total). Use export to compare
          combined summary vs human judgment — not a full analytics pipeline.
        </p>
        <p className="text-[11px] text-slate-500 mt-1">
          Export includes a blank <span className="font-mono text-slate-400">human_assessment</span> template per sample
          (`classification`, `matches_system`, `notes`) for manual annotation.
        </p>
      </div>
      <p className="text-[11px] text-slate-500 leading-snug">
        By combined summary:{' '}
        <span className="text-slate-400 tabular-nums">
          grounded {breakdown.grounded} · interpretive {breakdown.grounded_but_interpretive} · weak {breakdown.weak_support}{' '}
          · unreliable {breakdown.unreliable}
        </span>
        {total === 0 ? <span className="text-slate-600"> (none)</span> : null}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => void copyExport()}
          className="px-3 py-1.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-100 text-xs font-medium"
        >
          Copy review samples (JSON)
        </button>
        <button
          type="button"
          onClick={clearSamples}
          className="px-3 py-1.5 rounded-lg border border-slate-600 bg-transparent hover:bg-slate-800/80 text-slate-400 hover:text-slate-200 text-xs"
        >
          Clear review samples
        </button>
        <span className="text-xs text-slate-500">
          In ring: <span className="text-slate-400 tabular-nums">{total}</span>
          {copied ? <span className="text-emerald-400/90 ml-2">Copied</span> : null}
        </span>
      </div>
    </section>
  )
}
