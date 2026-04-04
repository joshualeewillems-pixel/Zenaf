import { useState } from 'react'

export type OutputTabId = 'script' | 'newsletter'
export type RefinementOption = '' | 'shorten' | 'more_direct'

export function ContentOutputsPane({
  activeTab,
  onTabChange,
  scriptText,
  newsletterText,
  onGenerateScript,
  onGenerateNewsletter,
  onRegenerateScript,
  onRegenerateNewsletter,
  onRegenerateWithRefinement,
  onBeforeRunOutput,
  generating,
  hasOutput,
}: {
  activeTab: OutputTabId
  onTabChange: (tab: OutputTabId) => void
  scriptText: string
  newsletterText: string
  onGenerateScript: () => void
  onGenerateNewsletter: () => void
  onRegenerateScript: () => void
  onRegenerateNewsletter: () => void
  onRegenerateWithRefinement?: (tab: OutputTabId, refinement: RefinementOption) => void
  /** Called immediately before generate/regenerate (e.g. trace outcome: user requested a new pass). */
  onBeforeRunOutput?: (tab: OutputTabId) => void
  generating: boolean
  hasOutput: boolean
}) {
  const [refinement, setRefinement] = useState<RefinementOption>('')
  const tabs: { id: OutputTabId; label: string; value: string; onGenerate: () => void; onRegenerate: () => void }[] = [
    { id: 'script', label: 'Script', value: scriptText, onGenerate: onGenerateScript, onRegenerate: onRegenerateScript },
    { id: 'newsletter', label: 'Newsletter', value: newsletterText, onGenerate: onGenerateNewsletter, onRegenerate: onRegenerateNewsletter },
  ]
  const current = tabs.find((t) => t.id === activeTab)!

  return (
    <div className="flex flex-col h-full min-h-0 rounded-xl border border-slate-600 bg-slate-800/80 overflow-hidden">
      <div className="shrink-0 flex border-b border-slate-700">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => onTabChange(t.id)}
            className={`px-4 py-3 text-sm font-medium transition-colors ${
              activeTab === t.id ? 'bg-slate-700 text-slate-100 border-b-2 border-amber-500' : 'text-slate-400 hover:text-slate-300'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="shrink-0 p-3 border-b border-slate-700 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => {
            onBeforeRunOutput?.(activeTab)
            current.onGenerate()
          }}
          disabled={generating}
          className="px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white text-sm font-medium"
        >
          {generating ? 'Generating…' : hasOutput && current.value ? 'Regenerate' : `Generate ${current.label}`}
        </button>
        {hasOutput && current.value && (
          <>
            <span className="text-slate-500 text-xs">Refinement:</span>
            <select
              value={refinement}
              onChange={(e) => setRefinement(e.target.value as RefinementOption)}
              className="px-2 py-1.5 rounded-lg bg-slate-900 border border-slate-600 text-slate-200 text-xs"
            >
              <option value="">None</option>
              <option value="shorten">Shorten</option>
              <option value="more_direct">More direct</option>
            </select>
            {refinement && (
              <button
                type="button"
                onClick={() => {
                  onBeforeRunOutput?.(activeTab)
                  onRegenerateWithRefinement?.(activeTab, refinement)
                  setRefinement('')
                }}
                disabled={generating}
                className="px-3 py-1.5 rounded-lg bg-slate-600 hover:bg-slate-500 disabled:opacity-50 text-slate-200 text-xs"
              >
                Apply & regenerate
              </button>
            )}
          </>
        )}
      </div>
      <div className="flex-1 min-h-0 overflow-auto p-4">
        {current.value ? (
          <FormattedOutput text={current.value} />
        ) : (
          <p className="text-slate-500 text-sm">Generate {current.label.toLowerCase()} from the brief and source materials.</p>
        )}
      </div>
    </div>
  )
}

/** Simple section formatting: lines starting with ## or ** as headings, double newlines as paragraph breaks. */
function FormattedOutput({ text }: { text: string }) {
  const lines = text.split(/\r?\n/)
  const blocks: { type: 'h2' | 'h3' | 'p'; content: string }[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]!
    if (line.startsWith('## ')) {
      blocks.push({ type: 'h2', content: line.slice(3).trim() })
      i++
      continue
    }
    if (line.startsWith('**') && line.endsWith('**') && line.length > 4) {
      blocks.push({ type: 'h3', content: line.slice(2, -2).trim() })
      i++
      continue
    }
    const para: string[] = []
    while (i < lines.length && lines[i]?.trim() !== '') {
      para.push(lines[i]!)
      i++
    }
    if (para.length) blocks.push({ type: 'p', content: para.join('\n') })
    while (i < lines.length && lines[i]?.trim() === '') i++
  }
  return (
    <div className="text-sm text-slate-300 space-y-3 font-sans">
      {blocks.map((b, idx) =>
        b.type === 'h2' ? (
          <h2 key={idx} className="text-base font-semibold text-slate-100 pt-2 first:pt-0">
            {b.content}
          </h2>
        ) : b.type === 'h3' ? (
          <h3 key={idx} className="text-sm font-medium text-slate-200">
            {b.content}
          </h3>
        ) : (
          <p key={idx} className="whitespace-pre-wrap leading-relaxed">
            {b.content}
          </p>
        )
      )}
    </div>
  )
}
