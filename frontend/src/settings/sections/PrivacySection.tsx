import { useState } from 'react'
import type { AtriaPrivacyMode } from '../../ai-actions/privacyModeBridge'
import { readPrivacyMode, writePrivacyMode } from '../../ai-actions/privacyModeBridge'

const OPTIONS: { value: AtriaPrivacyMode; label: string; hint: string }[] = [
  { value: 'normal', label: 'Normal', hint: 'Default execution and traces (this device only).' },
  { value: 'protected', label: 'Protected', hint: 'Stricter allowlists; trace input snapshots redacted.' },
  { value: 'restricted', label: 'Restricted', hint: 'Local-friendly allowlist, no cloud fallbacks in chain; stricter traces.' },
  { value: 'local_only', label: 'Local only', hint: 'Require local providers only; strongest trace suppression.' },
]

export function PrivacySection() {
  const [mode, setMode] = useState<AtriaPrivacyMode>(() => readPrivacyMode())
  const hint = OPTIONS.find((o) => o.value === mode)?.hint ?? ''

  return (
    <section className="rounded-xl border border-slate-600/80 bg-slate-800/40 p-5 space-y-3">
      <div>
        <h2 className="text-lg font-medium text-slate-100">Privacy mode</h2>
        <p className="text-sm text-slate-400 mt-1">
          Stored in this browser only. Affects which models can run and how AI action traces redact content.
        </p>
      </div>
      <div className="flex flex-col sm:flex-row sm:items-center gap-3">
        <label htmlFor="atria-privacy-mode" className="text-sm text-slate-300 shrink-0">
          Mode
        </label>
        <select
          id="atria-privacy-mode"
          className="rounded-lg border border-slate-600 bg-slate-900 text-slate-100 text-sm px-3 py-2 max-w-md"
          value={mode}
          onChange={(e) => {
            const next = e.target.value as AtriaPrivacyMode
            writePrivacyMode(next)
            setMode(next)
          }}
        >
          {OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
      {hint ? <p className="text-xs text-slate-500">{hint}</p> : null}
    </section>
  )
}
