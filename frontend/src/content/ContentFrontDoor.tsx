import { useState, useCallback } from 'react'
import { ContentNarrativeFrame } from './ContentNarrativeFrame'
import { ContentView } from './ContentView'
import { TranscriptSorter } from './TranscriptSorter'
import type { ContentConfig } from './types'

export interface ContentFrontDoorProps {
  /** API base for /run and transcript tools. Used to build config when config is not provided. */
  apiBase: string
  /** Optional: full config (apiBase + optional veApiBase). When omitted, { apiBase } is used. */
  config?: ContentConfig
}

export function ContentFrontDoor({ apiBase, config }: ContentFrontDoorProps) {
  // Keep content flow calls on same-origin proxy for cookie-auth session compatibility.
  // This includes /run in ContentView by using an empty apiBase when config is not provided.
  // `apiBase` from App is reserved (e.g. parity with intake links); relative paths + Vite proxy are used here.
  void apiBase
  const effectiveConfig: ContentConfig = config ?? { apiBase: '', veApiBase: '' }
  const [isContentZeroState, setIsContentZeroState] = useState(false)
  const onZeroState = useCallback((isZero: boolean) => setIsContentZeroState(isZero), [])

  return (
    <div className="flex flex-col min-h-screen bg-slate-900 text-slate-100">
      <header className="shrink-0 border-b border-slate-700 bg-slate-800/80 px-6 py-5 max-h-[min(52vh,28rem)] overflow-y-auto">
        <h1 className="text-2xl font-semibold text-slate-100">Content — narrative packages and execution handoff</h1>
        <p className="mt-1 text-sm text-slate-400">
          Save structured narrative packages (as <span className="text-slate-300">content briefs</span>), generate drafts,
          and link Vision Execution work — toward a fuller narrative registrar over time.
        </p>
        <ContentNarrativeFrame />
      </header>
      <div className="flex-1 min-h-0 flex flex-col">
        <ContentView
          config={effectiveConfig}
          showTranscriptSorter={false}
          hideHeader
          onZeroState={onZeroState}
        />
      </div>
      {!isContentZeroState && (
        <section className="shrink-0 border-t border-slate-700 bg-slate-800/50 px-6 py-4">
          <h2 className="text-sm font-semibold text-slate-300 mb-1">Transcript tools</h2>
          <p className="text-[11px] text-slate-500 mb-3">
            Capture → sort segments → promote into decisions / tasks; pairs with narrative packages when you promote into a brief.
          </p>
          <TranscriptSorter apiBase="" />
        </section>
      )}
    </div>
  )
}
