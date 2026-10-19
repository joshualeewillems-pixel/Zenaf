import { useEffect, useMemo, useState } from 'react'
import type { MapNodePayload } from './ontology'
import type { VisionMapEntityBundle } from './blockersFromVe'
import CouncilChat, { type ConversationMessage } from '../chat/CouncilChat'
import { fetchDeferredPrompts } from '../vision-execution/promptSignalsApi'
import type { Idea, Initiative, Project, Task } from '../vision-execution/types'
import { apiBase } from '../apiBase'

/**
 * The stone sheet — a briefing conversation about the tapped stone.
 *
 * Tap a stone in the garden and the sheet opens with:
 *  1. a synopsis paragraph composed live from the stone's entity state
 *     (where it's at, where it's going, last thing worked on),
 *  2. what's-next chips (the entity's own next steps + suggestion engine
 *     items) that drop into the composer without sending,
 *  3. the skeleton thread for the stone — `stone:{veType}:{id}` — rendered
 *     by the shared CouncilChat. Open questions for the stone arrive as
 *     messages in the thread, not as a separate notification list.
 *
 * Killed here: the INVITES button row (those are chat utterances now), the
 * old-model conversation block, the detail-dump inspector, and the
 * soil/water/fruit abstractions. Growth states stay as data; the sheet
 * speaks plainly: ripening, stalled, done.
 */

type Props = {
  selected: MapNodePayload | null
  entityBundle: VisionMapEntityBundle | null
  onClearSelection: () => void
  canNestSelected?: boolean
  canExpandSelected?: boolean
  onNestSelected?: () => void
  onExpandSelected?: () => void
}

function growthKindLabel(kind: MapNodePayload['kind']): string {
  switch (kind) {
    case 'seed':
      return 'This seed'
    case 'tree':
      return 'This initiative'
    case 'branch':
      return 'This project'
    case 'flower':
      return 'This task'
    case 'fruit':
      return 'This outcome'
    default:
      return 'This item'
  }
}

function truncate(s: string, n: number): string {
  const t = s.trim().replace(/\s+/g, ' ')
  return t.length > n ? `${t.slice(0, n - 1)}…` : t
}

function relativeTime(iso: string | undefined | null): string | null {
  if (!iso) return null
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return null
  const mins = Math.max(0, Math.floor((Date.now() - t) / 60000))
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs} hr ago`
  const days = Math.floor(hrs / 24)
  if (days < 30) return `${days} day${days === 1 ? '' : 's'} ago`
  return `${Math.floor(days / 30)} mo ago`
}

function isDoneStatus(status: string | undefined | null): boolean {
  const s = (status || '').trim().toLowerCase()
  return s === 'done' || s === 'complete' || s === 'completed'
}

/** The VE entity behind the stone, if the bundle carries it. */
function resolveStoneEntity(
  selected: MapNodePayload,
  bundle: VisionMapEntityBundle | null,
):
  | { kind: 'initiative'; e: Initiative }
  | { kind: 'project'; e: Project }
  | { kind: 'task'; e: Task }
  | { kind: 'idea'; e: Idea }
  | null {
  if (!bundle) return null
  const { veType, id } = selected.ref
  if (veType === 'initiative') {
    const e = bundle.initiatives.find((x) => x.id === id)
    return e ? { kind: 'initiative', e } : null
  }
  if (veType === 'project') {
    const e = bundle.projects.find((x) => x.id === id)
    return e ? { kind: 'project', e } : null
  }
  if (veType === 'task') {
    const e = bundle.tasks.find((x) => x.id === id)
    return e ? { kind: 'task', e } : null
  }
  if (veType === 'idea') {
    const e = bundle.ideas.find((x) => x.id === id)
    return e ? { kind: 'idea', e } : null
  }
  return null
}

/**
 * Synopsis sentences, composed client-side from already-loaded entity
 * state. Missing pieces are omitted, never invented.
 */
export function composeSynopsis(selected: MapNodePayload, bundle: VisionMapEntityBundle | null): string[] {
  const parts: string[] = []
  const se = resolveStoneEntity(selected, bundle)
  if (!se) {
    const first = selected.summaryLines.map((l) => l.trim()).find(Boolean)
    if (first) parts.push(truncate(first, 220))
    return parts
  }
  const at: string[] = []
  const going: string[] = []
  const last: string[] = []

  if (se.kind === 'initiative') {
    const projs = bundle?.projects.filter((p) => p.initiative_id === se.e.id) ?? []
    const tasks = bundle?.tasks.filter((t) => projs.some((p) => p.id === t.project_id)) ?? []
    const done = tasks.filter((t) => isDoneStatus(t.status)).length
    at.push(`Status: ${se.e.status || 'unknown'}.`)
    if (projs.length || tasks.length) {
      at.push(
        `${projs.length} project${projs.length === 1 ? '' : 's'}, ${tasks.length} task${tasks.length === 1 ? '' : 's'}` +
          (tasks.length ? `, ${done} done` : '') +
          '.',
      )
    }
    if (se.e.next_step_ai?.trim()) going.push(`Next: ${truncate(se.e.next_step_ai, 160)}`)
    const rel = relativeTime(se.e.updated_at)
    if (rel) last.push(`Last touched ${rel}.`)
  } else if (se.kind === 'project') {
    const tasks = bundle?.tasks.filter((t) => t.project_id === se.e.id) ?? []
    const done = tasks.filter((t) => isDoneStatus(t.status)).length
    at.push(`Status: ${se.e.status || 'unknown'}.`)
    if (tasks.length) at.push(`${tasks.length} task${tasks.length === 1 ? '' : 's'}, ${done} done.`)
    else if (se.e.brief?.trim()) at.push(truncate(se.e.brief, 160))
    if (se.e.next_step_ai?.trim()) going.push(`Next: ${truncate(se.e.next_step_ai, 160)}`)
    const rel = relativeTime(se.e.updated_at)
    if (rel) last.push(`Last touched ${rel}.`)
  } else if (se.kind === 'task') {
    at.push(`Status: ${se.e.status || 'unknown'}.`)
    if (se.e.description?.trim()) at.push(truncate(se.e.description, 160))
    const rel = relativeTime(se.e.updated_at)
    if (rel) last.push(`Last touched ${rel}.`)
  } else {
    if (se.e.summary?.trim()) at.push(truncate(se.e.summary, 180))
    else if (se.e.description?.trim()) at.push(truncate(se.e.description, 180))
    const prog = se.e.checklist_progress
    if (prog && prog.total > 0) at.push(`${prog.done} of ${prog.total} steps done.`)
    const rel = relativeTime(se.e.updated_at)
    if (rel) last.push(`Last touched ${rel}.`)
  }

  if (at.length) parts.push(at.join(' '))
  if (going.length) parts.push(going.join(' '))
  if (last.length) parts.push(last.join(' '))
  return parts
}

type Chip = { label: string; text: string }

export function MapChatShell({
  selected,
  entityBundle,
  onClearSelection,
  canNestSelected,
  canExpandSelected,
  onNestSelected,
  onExpandSelected,
}: Props) {
  const base = apiBase()
  const [chips, setChips] = useState<Chip[]>([])
  const [folded, setFolded] = useState<ConversationMessage[]>([])
  const [prefill, setPrefill] = useState<{ text: string; nonce: number } | null>(null)

  const stoneKey = selected ? `${selected.ref.veType}:${selected.ref.id}` : null
  const conversationId = stoneKey ? `stone:${stoneKey}` : null

  const synopsis = useMemo(
    () => (selected ? composeSynopsis(selected, entityBundle) : []),
    [selected, entityBundle],
  )

  // What's-next chips: the entity's own next steps + open children, then
  // suggestion-engine items for this stone's thread.
  useEffect(() => {
    if (!selected) {
      setChips([])
      return
    }
    let cancelled = false
    const out: Chip[] = []
    const se = resolveStoneEntity(selected, entityBundle)
    if (se && (se.kind === 'initiative' || se.kind === 'project') && se.e.next_step_ai?.trim()) {
      const t = se.e.next_step_ai.trim()
      out.push({ label: `Next: ${truncate(t, 44)}`, text: t })
    }
    if (se && entityBundle) {
      const openChildren: { title: string }[] =
        se.kind === 'initiative'
          ? entityBundle.projects
              .filter((p) => p.initiative_id === se.e.id && !isDoneStatus(p.status))
              .slice(0, 3)
          : se.kind === 'project'
            ? entityBundle.tasks
                .filter((t) => t.project_id === se.e.id && !isDoneStatus(t.status))
                .slice(0, 3)
            : []
      for (const c of openChildren) {
        const title = (c.title || '').trim()
        if (title) out.push({ label: truncate(title, 44), text: `Where does "${title}" stand?` })
      }
    }
    const cid = `stone:${selected.ref.veType}:${selected.ref.id}`
    fetch(`${base}/conversation/suggestions?conversation_id=${encodeURIComponent(cid)}`, {
      credentials: 'include',
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (cancelled || !data) return
        const take = (arr: unknown, pick: (x: Record<string, unknown>) => string | null) => {
          if (!Array.isArray(arr)) return
          for (const raw of arr) {
            if (out.length >= 5 || !raw || typeof raw !== 'object') continue
            const t = pick(raw as Record<string, unknown>)
            if (t && t.trim() && !out.some((c) => c.text === t.trim())) {
              out.push({ label: truncate(t, 44), text: t.trim() })
            }
          }
        }
        take(data.trainable_moments, (x) =>
          typeof x.question === 'string' && x.question.trim()
            ? x.question
            : typeof x.title === 'string'
              ? x.title
              : null,
        )
        take(data.project_proposals, (x) =>
          typeof x.title === 'string' ? `What would it take to start "${x.title}"?` : null,
        )
        take(data.mint_suggestions, (x) =>
          typeof x.title === 'string' ? x.title : typeof x.summary === 'string' ? x.summary : null,
        )
        if (!cancelled) setChips([...out])
      })
      .catch(() => {
        if (!cancelled) setChips([...out])
      })
    // Entity-derived chips show immediately; suggestions merge in when they land.
    setChips([...out])
    return () => {
      cancelled = true
    }
  }, [selected, entityBundle, base])

  // Fold the stone's open questions into the thread (as council-voice
  // messages when the skeleton thread is still empty). No separate card list.
  useEffect(() => {
    if (!selected) {
      setFolded([])
      return
    }
    let cancelled = false
    fetchDeferredPrompts(selected.ref.veType, selected.ref.id)
      .then((items) => {
        if (cancelled) return
        setFolded(
          items
            .map((it) => (it.prompt_summary || '').trim())
            .filter(Boolean)
            .slice(0, 5)
            .map((text) => ({ role: 'voice' as const, content: text, voiceName: 'Council' })),
        )
      })
      .catch(() => {
        if (!cancelled) setFolded([])
      })
    return () => {
      cancelled = true
    }
  }, [stoneKey]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <aside
      data-testid="vision-map-inspector"
      className="map-ui-panel flex flex-col h-full min-h-0 w-full lg:w-[380px] lg:shrink-0 border-t lg:border-t-0 lg:border-l border-stone-800/90 bg-stone-950/85 backdrop-blur-md shadow-[-12px_0_40px_rgba(39,36,31,0.35)]"
    >
      <div className="px-4 py-3 border-b border-stone-700 flex items-start justify-between gap-2 min-w-0">
        <div className="min-w-0 flex-1 pr-2">
          <h2
            data-testid="vision-map-selected-title"
            className="text-sm font-semibold text-stone-100 truncate"
            title={selected?.label}
          >
            {selected?.label?.trim() || 'Vision map'}
          </h2>
          {selected ? (
            <p className="text-[10px] text-stone-500 truncate mt-0.5" title={selected.subtitle}>
              {growthKindLabel(selected.kind)}
              {selected.subtitle?.trim() ? ` · ${selected.subtitle.trim()}` : ''}
            </p>
          ) : (
            <p className="text-[10px] text-stone-500 mt-0.5">Select a node to open its workspace here</p>
          )}
        </div>
        {selected && (
          <button
            type="button"
            onClick={onClearSelection}
            className="shrink-0 h-8 w-8 flex items-center justify-center rounded-lg border border-stone-600 text-stone-400 hover:text-stone-100 hover:bg-stone-800 text-lg leading-none"
            aria-label="Clear map selection"
          >
            ×
          </button>
        )}
      </div>

      {!selected ? (
        <div className="p-4 text-sm text-stone-500 flex-1">
          Select something on the map. Your conversation stays in the main chat.
        </div>
      ) : (
        <div className="flex-1 min-h-0 flex flex-col">
          {(canNestSelected && onNestSelected) || (canExpandSelected && onExpandSelected) ? (
            <div className="px-3 py-2 flex flex-wrap gap-1.5 border-b border-stone-800">
              {canNestSelected && onNestSelected ? (
                <button
                  type="button"
                  onClick={onNestSelected}
                  className="min-h-[44px] text-[11px] px-2 py-1 rounded bg-stone-800 border border-stone-600 hover:bg-stone-700"
                >
                  Nest group
                </button>
              ) : null}
              {canExpandSelected && onExpandSelected ? (
                <button
                  type="button"
                  onClick={onExpandSelected}
                  className="min-h-[44px] text-[11px] px-2 py-1 rounded bg-stone-800 border border-stone-600 hover:bg-stone-700"
                >
                  Expand group
                </button>
              ) : null}
            </div>
          ) : null}

          <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-4">
            {synopsis.length > 0 ? (
              <div className="space-y-1.5" data-testid="stone-synopsis">
                <div className="text-[10px] uppercase tracking-wide text-stone-500">Where this stands</div>
                {synopsis.map((line, i) => (
                  <p key={i} className="text-[13px] text-stone-200 leading-relaxed">
                    {line}
                  </p>
                ))}
              </div>
            ) : null}

            {chips.length > 0 ? (
              <div className="space-y-1.5" data-testid="stone-whats-next">
                <div className="text-[10px] uppercase tracking-wide text-stone-500">What&apos;s next</div>
                <div className="flex gap-1.5 overflow-x-auto pb-1 -mx-1 px-1">
                  {chips.map((chip, i) => (
                    <button
                      key={`${chip.label}-${i}`}
                      type="button"
                      onClick={() =>
                        setPrefill((prev) => ({ text: chip.text, nonce: (prev?.nonce ?? 0) + 1 }))
                      }
                      className="shrink-0 min-h-[44px] max-w-[220px] truncate text-[12px] px-3 rounded-full border border-stone-600 bg-stone-800/70 hover:bg-stone-700 text-stone-200"
                      title={chip.text}
                    >
                      {chip.label}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            <div className="space-y-1.5">
              <div className="text-[10px] uppercase tracking-wide text-stone-500">
                Talk about this {growthKindLabel(selected.kind).toLowerCase().replace(/^this /, '')}
              </div>
              <CouncilChat
                key={conversationId ?? 'stone-chat'}
                environment="sheet"
                conversationId={conversationId}
                context={{
                  sheet_type: 'stone',
                  entity_type: selected.ref.veType,
                  entity_id: selected.ref.id,
                }}
                seedMessages={folded.length > 0 ? folded : null}
                prefill={prefill}
              />
            </div>
          </div>
        </div>
      )}
    </aside>
  )
}
