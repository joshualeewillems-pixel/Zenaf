import { useEffect, useState } from 'react'
import { apiBase } from '../apiBase'

/**
 * Today — the morning briefing deck ("the council that runs your day").
 *
 * Consumes GET /today (the today aggregate, which itself consumes the
 * follow-through engine's nudge feed server-side). Deck, not list: up to
 * three cards, a "Next" button pages the rest. Session-stateless: dismissed
 * and engaged ids live in component state for the briefing session only.
 *
 * `mode` (optional): an engine seat key (e.g. 'guardian'). When set, the
 * briefing opens as that seat's rendition of today — the deck re-ranks
 * around the seat from the first fetch. The tree's seat nodes pass their
 * seat; the you-node passes none (the whole council). Mode discovery keeps
 * working on top: engaging a card can still propose a different mode, and
 * clearing returns to the un-moded briefing.
 *
 * ADHD rules (load-bearing): no badge counts, no red dots, no dumps.
 * Every card shows its `why` plainly — traceability is the product.
 */

type NextAction = { code: string; label: string }

type BriefingItem = {
  id: string
  kind: string
  tier: 'must' | 'should' | 'could'
  entity_type: string | null
  entity_id: string | null
  entity_title: string
  why: string
  suggested_seat: string | null
  people_waiting: boolean
  next_action: NextAction
}

type Briefing = {
  items: BriefingItem[]
  has_more: boolean
  cursor: string | null
  suggested_mode: string | null
}

/** Engine seat keys (archetype or fellowship names) -> fellowship display name. */
const SEAT_DISPLAY: Record<string, string> = {
  mentor: 'The Gardener',
  gardener: 'The Gardener',
  champion: 'The Firebrand',
  firebrand: 'The Firebrand',
  guardian: 'The Bear',
  bear: 'The Bear',
  ambassador: 'The Bridge',
  bridge: 'The Bridge',
  conductor: 'The Weaver',
  weaver: 'The Weaver',
  skeptic: 'The Neighbor',
  neighbor: 'The Neighbor',
  maverick: 'The Fox',
  fox: 'The Fox',
}

function seatDisplay(raw: string | null): string | null {
  if (!raw) return null
  const hit = SEAT_DISPLAY[raw.trim().toLowerCase()]
  return hit ?? raw
}

/** Short seat name for the mode question ("Seems like you're in Bear mode?"). */
function seatShort(raw: string | null): string | null {
  const full = seatDisplay(raw)
  return full ? full.replace(/^The /, '') : null
}

const TIER_STYLE: Record<string, { label: string; pill: string }> = {
  must: {
    label: "Can't wait",
    pill: 'bg-amber-500/15 text-amber-200/90 border-amber-500/25',
  },
  should: {
    label: 'Worth a look',
    pill: 'bg-stone-700/60 text-stone-300 border-stone-600/40',
  },
  could: {
    label: "When there's space",
    pill: 'bg-stone-800/40 text-stone-400 border-stone-700/40',
  },
}

async function api(path: string, opts: RequestInit = {}) {
  const r = await fetch(`${apiBase()}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  })
  if (r.status === 401) throw new Error('Please sign in.')
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data.detail || 'Request failed')
  return data
}

function buildQuery(o: {
  cursor?: string | null
  dismissed: string[]
  engagedId?: string | null
  mode?: string | null
}): string {
  const p = new URLSearchParams()
  if (o.cursor) p.set('cursor', o.cursor)
  for (const id of o.dismissed) p.append('dismissed_ids', id)
  if (o.engagedId) p.set('engaged_id', o.engagedId)
  if (o.mode) p.set('mode', o.mode)
  const q = p.toString()
  return q ? `/today?${q}` : '/today'
}

function dateLine(): string {
  return new Date().toLocaleDateString(undefined, {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  })
}

export default function TodayView({ mode: initialMode = null }: { mode?: string | null }) {
  const [items, setItems] = useState<BriefingItem[]>([])
  const [cursor, setCursor] = useState<string | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [dismissedIds, setDismissedIds] = useState<string[]>([])
  const [engagedId, setEngagedId] = useState<string | null>(null)
  const [suggestedModeRaw, setSuggestedModeRaw] = useState<string | null>(null)
  const [proposalOpen, setProposalOpen] = useState(false)
  const [activeModeRaw, setActiveModeRaw] = useState<string | null>(initialMode)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [actingId, setActingId] = useState<string | null>(null)

  async function load(o: {
    cursor?: string | null
    dismissed: string[]
    engagedId?: string | null
    mode?: string | null
  }) {
    setLoading(true)
    setError('')
    try {
      const data: Briefing = await api(buildQuery(o))
      setItems(Array.isArray(data.items) ? data.items : [])
      setCursor(data.cursor ?? null)
      setHasMore(!!data.has_more)
      if (data.suggested_mode) {
        setSuggestedModeRaw(data.suggested_mode)
        setProposalOpen(true)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load the briefing')
    } finally {
      setLoading(false)
    }
  }

  // Fresh briefing on mount. State is session-only by design. When a seat
  // key arrives as `mode`, the briefing opens as that seat's rendition.
  useEffect(() => {
    load({ dismissed: [], mode: initialMode ?? null })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /** Refetch the deck from the top with the current session signals. */
  function refreshDeck(dismissed: string[], engaged: string | null, mode: string | null) {
    setCursor(null)
    load({ dismissed, engagedId: engaged, mode })
  }

  /** "Not now" — out of this briefing; the pattern also steers the deck. */
  function onDismiss(item: BriefingItem) {
    const wasEngaged = item.id === engagedId
    if (wasEngaged) {
      setEngagedId(null)
      setProposalOpen(false)
    }
    const next = [...dismissedIds, item.id]
    setDismissedIds(next)
    refreshDeck(next, wasEngaged ? null : engagedId, activeModeRaw)
  }

  /** "Let's do this" — stop on the card; its seat may propose a mode. */
  function onEngage(item: BriefingItem) {
    setEngagedId(item.id)
    refreshDeck(dismissedIds, item.id, activeModeRaw)
  }

  function onNext() {
    load({ cursor, dismissed: dismissedIds, engagedId, mode: activeModeRaw })
  }

  function onKeepThread() {
    if (!suggestedModeRaw) return
    setActiveModeRaw(suggestedModeRaw)
    setEngagedId(null)
    setProposalOpen(false)
    refreshDeck(dismissedIds, null, suggestedModeRaw)
  }

  function onSomethingElse() {
    setEngagedId(null)
    setProposalOpen(false)
  }

  function onClearMode() {
    setActiveModeRaw(null)
    refreshDeck(dismissedIds, null, null)
  }

  /** The one pre-chewed next action per card. */
  async function onNextAction(item: BriefingItem) {
    const code = item.next_action?.code
    if (code === 'open' || code === 'make_task') {
      // v1: opening / task-creation flows aren't built yet — engaging is the
      // honest action: it surfaces the mode proposal and keeps the card.
      onEngage(item)
      return
    }
    setActingId(item.id)
    try {
      if (code === 'done') {
        await api(`/followthrough/nudges/${encodeURIComponent(item.id)}/ack`, { method: 'POST' })
      } else {
        // snooze ("Let it rest") — rest until tomorrow.
        const until = new Date(Date.now() + 24 * 3600 * 1000).toISOString()
        await api(`/followthrough/nudges/${encodeURIComponent(item.id)}/snooze`, {
          method: 'POST',
          body: JSON.stringify({ until }),
        })
      }
      // Card handled: refill the deck from the top.
      const next = dismissedIds.filter((d) => d !== item.id)
      setDismissedIds(next)
      refreshDeck(next, engagedId === item.id ? null : engagedId, activeModeRaw)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That did not go through — try again')
    } finally {
      setActingId(null)
    }
  }

  const modeShort = seatShort(activeModeRaw)
  const proposalShort = seatShort(suggestedModeRaw)

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-y-auto p-4 max-w-2xl mx-auto w-full">
      <p className="text-[11px] font-medium text-stone-500 uppercase tracking-wide">Today</p>
      <h1 className="text-xl font-bold text-stone-100 mt-0.5">{dateLine()}</h1>
      <p className="text-stone-500 text-sm mt-1 mb-4">
        {activeModeRaw && modeShort
          ? `Through the ${modeShort}'s eyes — its cards first, then the council's. Three at a time, no more.`
          : "Your council's briefing — three cards at a time, no more."}
      </p>

      {error && <p className="text-red-300 text-sm mb-3">{error}</p>}

      {activeModeRaw && modeShort && (
        <div className="flex items-center justify-between rounded-xl border border-stone-700 bg-stone-800/60 px-4 py-3 mb-3">
          <p className="text-stone-300 text-[15px]">
            Thread: <span className="font-semibold text-stone-100">{modeShort} mode</span>
          </p>
          <button
            type="button"
            onClick={onClearMode}
            className="min-h-[44px] px-3 text-stone-400 text-sm underline underline-offset-4"
          >
            Clear
          </button>
        </div>
      )}

      {proposalOpen && suggestedModeRaw && proposalShort && (
        <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 p-4 mb-3">
          <p className="text-stone-100 text-[15px] leading-relaxed mb-3">
            Seems like you're in <span className="font-semibold">{proposalShort} mode</span> — keep
            this thread, or do something else?
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onKeepThread}
              className="flex-1 min-h-[44px] px-4 rounded-xl bg-amber-500/90 text-stone-950 font-semibold text-[15px]"
            >
              Keep this thread
            </button>
            <button
              type="button"
              onClick={onSomethingElse}
              className="flex-1 min-h-[44px] px-4 rounded-xl border border-stone-600 text-stone-200 font-medium text-[15px]"
            >
              Something else
            </button>
          </div>
        </div>
      )}

      {loading && items.length === 0 && (
        <p className="text-stone-500 text-sm">Gathering the briefing…</p>
      )}

      {!loading && items.length === 0 && !error && (
        <div className="flex-1 flex flex-col items-center justify-center text-center px-6">
          <p className="text-stone-200 text-[17px] font-semibold mb-2">Nothing pressing.</p>
          <p className="text-stone-500 text-[15px] leading-relaxed max-w-xs">
            The council's quiet today — enjoy the clear air.
          </p>
        </div>
      )}

      <div className="space-y-3">
        {items.map((item) => {
          const tier = TIER_STYLE[item.tier] ?? TIER_STYLE.should
          const seat = seatDisplay(item.suggested_seat)
          const acting = actingId === item.id
          return (
            <div
              key={item.id}
              className="rounded-2xl border border-stone-700 bg-stone-900/60 p-4"
            >
              <div className="flex items-center justify-between gap-2 mb-2">
                <span
                  className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-semibold ${tier.pill}`}
                >
                  {tier.label}
                </span>
                {seat && <span className="text-stone-500 text-xs">{seat}</span>}
              </div>
              <h2 className="text-stone-100 font-semibold text-[16px] leading-snug mb-1.5">
                {item.entity_title || 'Untitled'}
              </h2>
              {item.why && (
                <p className="text-stone-400 text-sm leading-relaxed mb-1.5">{item.why}</p>
              )}
              {item.people_waiting && (
                <p className="text-stone-300 text-sm mb-1.5">Someone's waiting on this.</p>
              )}
              <button
                type="button"
                disabled={acting}
                onClick={() => onNextAction(item)}
                className="w-full min-h-[44px] mt-2 rounded-xl bg-amber-500/90 text-stone-950 font-semibold text-[15px] disabled:opacity-40"
              >
                {acting ? 'Working…' : item.next_action?.label || 'Open it'}
              </button>
              <div className="flex gap-2 mt-1">
                <button
                  type="button"
                  disabled={acting}
                  onClick={() => onEngage(item)}
                  className="flex-1 min-h-[44px] rounded-xl border border-stone-700 text-stone-200 font-medium text-[15px] disabled:opacity-40"
                >
                  Let's do this
                </button>
                <button
                  type="button"
                  disabled={acting}
                  onClick={() => onDismiss(item)}
                  className="flex-1 min-h-[44px] rounded-xl text-stone-500 text-[15px] underline underline-offset-4 disabled:opacity-40"
                >
                  Not now
                </button>
              </div>
            </div>
          )
        })}
      </div>

      {hasMore && items.length > 0 && (
        <button
          type="button"
          onClick={onNext}
          disabled={loading}
          className="w-full min-h-[48px] mt-4 rounded-xl border border-stone-600 text-stone-100 font-semibold text-[16px] disabled:opacity-40"
        >
          {loading ? 'Loading…' : 'Next'}
        </button>
      )}
    </div>
  )
}
