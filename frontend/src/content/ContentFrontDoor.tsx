import { useState, useCallback } from 'react'
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
  const effectiveConfig: ContentConfig = config ?? { apiBase: '', veApiBase: '' }
  const [isContentZeroState, setIsContentZeroState] = useState(false)
  const onZeroState = useCallback((isZero: boolean) => setIsContentZeroState(isZero), [])

  return (
    <div className="flex flex-col min-h-screen bg-slate-900 text-slate-100">
      <header className="shrink-0 border-b border-slate-700 bg-slate-800/80 px-6 py-5">
        <h1 className="text-2xl font-semibold text-slate-100">
          Turn one idea into content and execution in minutes
        </h1>
        <p className="mt-1 text-sm text-slate-400">
          Briefs, generation, and handoff — all in one place.
        </p>
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
          <h2 className="text-sm font-semibold text-slate-300 mb-3">Transcript tools</h2>
          <TranscriptSorter apiBase="" />
        </section>
      )}
    </div>
  )
}
