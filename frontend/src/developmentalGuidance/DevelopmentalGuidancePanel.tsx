import { useState } from 'react'
import type { DevelopmentalGuidanceContext } from './types'
import { interpretiveAxisCopy } from './interpretiveAxisCopy'
import { InterpretiveAxisSlider } from './InterpretiveAxisSlider'
import { inferInterpretiveAxisSlider, parseInterpretiveAxisName } from './interpretiveAxisSliderInfer'

export function DevelopmentalGuidancePanel({ context }: { context: DevelopmentalGuidanceContext | null }) {
  const [open, setOpen] = useState(false)
  if (!context) return null

  return (
    <div className="rounded-lg border border-stone-600/80 bg-stone-900/40 text-left">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between gap-2 px-3 py-2 text-left text-xs text-stone-400 hover:text-stone-200 hover:bg-stone-800/50 rounded-lg"
      >
        <span className="font-medium text-stone-300">
          {interpretiveAxisCopy.labels.panelCollapsibleTitle}
        </span>
        <span className="text-stone-500 shrink-0">{open ? '▼' : '▶'}</span>
      </button>
      {open && (
        <div className="px-3 pb-3 pt-0 space-y-2 text-[11px] text-stone-400 leading-relaxed border-t border-stone-700/60">
          <p className="text-stone-500 italic">{interpretiveAxisCopy.labels.panelIntro}</p>
          <p className="text-stone-500 italic text-[10px]">
            Same hypotheses are appended (labeled) to the council context packet for this run — not saved as a profile.
          </p>
          {context.suggested_guidance_style !== 'neutral' && (
            <p>
              <span className="text-stone-500">Suggested tone: </span>
              <span className="text-stone-300">{context.suggested_guidance_style.replace(/_/g, ' ')}</span>
            </p>
          )}
          {context.axes && context.axes.length > 0 && (
            <div>
              <p className="text-stone-500 uppercase tracking-wide text-[10px] mb-2">
                {interpretiveAxisCopy.labels.panelSectionTitle}
              </p>
              <div className="space-y-4">
                {context.axes.map((a, i) => {
                  const parsed = parseInterpretiveAxisName(a.name)
                  if (!parsed) {
                    return (
                      <div key={i} className="text-[11px] text-stone-400">
                        <span className="text-stone-300">{a.name}</span>
                        <p className="text-stone-500 mt-1 text-[10px] leading-snug">{a.tilt}</p>
                      </div>
                    )
                  }
                  const { pct, emphasis } = inferInterpretiveAxisSlider(a.tilt, parsed.left, parsed.right)
                  return (
                    <InterpretiveAxisSlider
                      key={i}
                      leftLabel={parsed.left}
                      rightLabel={parsed.right}
                      tilt={a.tilt}
                      dotPct={pct}
                      emphasis={emphasis}
                    />
                  )
                })}
              </div>
            </div>
          )}
          {context.hypotheses.length > 0 && (
            <ul className="list-disc pl-4 space-y-1.5">
              {context.hypotheses.map((h, i) => (
                <li key={i}>
                  <span className="text-stone-500">
                    [{h.kind} · {h.confidence}]{' '}
                  </span>
                  {h.statement}
                </li>
              ))}
            </ul>
          )}
          {context.evidence_refs.length > 0 && (
            <div>
              <p className="text-stone-500 uppercase tracking-wide text-[10px] mb-1">Evidence pointers</p>
              <ul className="list-disc pl-4 space-y-0.5 text-stone-500">
                {context.evidence_refs.map((e, i) => (
                  <li key={i}>
                    {e.source_type}
                    {e.source_id_or_key ? ` — ${e.source_id_or_key}` : ''}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
