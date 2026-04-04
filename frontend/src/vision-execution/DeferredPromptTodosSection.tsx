import { useCallback, useEffect, useState } from 'react'
import { fetchDeferredPrompts, postPromptSignal } from './promptSignalsApi'

const SUMMARY_PREVIEW_CHARS = 160

type EntityScope = 'idea' | 'initiative' | 'project' | 'task' | 'workspace'

export function DeferredPromptTodosSection({
  entityType,
  entityId,
  contextTitle,
}: {
  entityType: EntityScope
  entityId: string
  /** e.g. "Project — Northwind rollout" — same convention as thread system prompts */
  contextTitle?: string
}) {
  const [items, setItems] = useState<Awaited<ReturnType<typeof fetchDeferredPrompts>>>([])
  const [err, setErr] = useState<string | null>(null)

  const load = useCallback(() => {
    void (async () => {
      try {
        setErr(null)
        const rows = await fetchDeferredPrompts(entityType, entityId)
        setItems(rows)
      } catch (e) {
        setErr(e instanceof Error ? e.message : 'Could not load reminders')
      }
    })()
  }, [entityType, entityId])

  useEffect(() => {
    load()
  }, [load])

  if (items.length === 0 && !err) return null

  const now = Date.now()

  return (
    <div className="mt-4 pt-3 border-t border-slate-600/80 space-y-2">
      <div className="flex flex-col gap-0.5">
        <h4 data-testid="prompt-reminders-heading" className="text-[10px] font-medium uppercase tracking-wide text-slate-500">
          Prompt reminders
        </h4>
        {contextTitle ? (
          <p
            className="text-[10px] font-semibold text-slate-300 leading-snug"
            data-testid="prompt-reminders-context-title"
          >
            {contextTitle}
          </p>
        ) : null}
        <p className="text-[9px] text-slate-600 leading-snug">
          Short list only — most due first (max 7). Deferred means “revisit later,” not agreement.
        </p>
      </div>
      {err && <p className="text-[10px] text-red-400/90">{err}</p>}
      <ul className="space-y-2">
        {items.map((row) => {
          const due = row.deferred_until ? Date.parse(row.deferred_until) : 0
          const isDue = due > 0 && due <= now
          const fullText = (row.prompt_summary || row.prompt_id || '').trim()
          const preview =
            fullText.length > SUMMARY_PREVIEW_CHARS
              ? `${fullText.slice(0, SUMMARY_PREVIEW_CHARS).trimEnd()}…`
              : fullText
          return (
            <li
              key={row.id}
              className={`rounded-md border px-2 py-1.5 text-[11px] leading-snug ${
                isDue ? 'border-amber-600/45 bg-amber-950/20 text-amber-100/90' : 'border-slate-700 bg-slate-900/40 text-slate-400'
              }`}
            >
              <p className="line-clamp-3 break-words">
                {preview}
                {row.deferred_until ? (
                  <span className="block text-[9px] text-slate-500 mt-0.5">
                    {isDue ? 'Due — revisit when ready' : `After ${new Date(row.deferred_until).toLocaleString()}`}
                  </span>
                ) : null}
              </p>
              <button
                type="button"
                className="mt-1 text-[9px] text-slate-500 hover:text-slate-300 underline"
                onClick={() => {
                  void (async () => {
                    try {
                      await postPromptSignal({
                        prompt_id: row.prompt_id,
                        action: 'dismissed',
                        entity_type: entityType,
                        entity_id: entityId,
                        prompt_summary: row.prompt_summary?.slice(0, 400) ?? '',
                      })
                      load()
                    } catch {
                      /* ignore */
                    }
                  })()
                }}
              >
                Dismiss
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
