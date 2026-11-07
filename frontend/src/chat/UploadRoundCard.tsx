/**
 * Upload round card for the one reading the conductor presented in an
 * upload rapid fire round.
 *
 * Contract (upload S1, brief §§7–9): the round item arrives from the
 * server — the turn response carries the rendering, hydration
 * refetches it by id — and card STATE comes from the server record,
 * never client memory. On mount the card reads GET
 * /conversation/upload/item-state (interpretation + outcome +
 * parked/reserved state — the parked/reserved state lives in the
 * round tables, not on the interpretation record, so the bare
 * rendering cannot show it) and renders each record's state:
 * pending → the six menu actions + "Not now" (park); ruled →
 * the decided line ("Ruled. [Verdict label.]") + what was created;
 * parked → the parked line above the pending card (a park
 * suppresses re-presentation, not the decision); reserved → the
 * reserved line + Undo, no decide buttons (the user said "don't
 * remind me" — the card must not keep reminding them).
 *
 * Each menu action opens a confirmation panel first: the verbatim
 * interpretation + the consequence sentence. Only the tap on the
 * panel's Confirm posts — prose assent never writes. The tap itself
 * sends no turn: the next user message advances the round. A tap
 * that returns next_voice switches the active seat for the next
 * turn (via onNextVoice); the switch is the invitation's effect,
 * not a turn.
 */
import { useEffect, useState } from 'react'

export type UploadRoundItem = {
  kind: 'interpretation'
  interpretation_id: string
  document_id?: string
  document_version?: number
  lens?: string
  rendering?: UploadRendering
}

export type UploadRendering = {
  interpretation_id?: string
  document_id?: string
  document_version?: number
  lens?: string
  lens_kind?: string
  text?: string
  attribution?: string
  is_transformation?: boolean
  proposed_outcome?: string | null
  origin?: string
  ungrounded?: boolean
  spans?: Array<{ span_id?: string; text?: string; location?: string; role?: string }>
  observations?: Array<{ observation_id?: string; claim?: string }>
  coverage?: string | null
  uncertain_match?: { kind?: string; prior_interpretation_id?: string } | null
  parentage_options?: Array<{ id?: string; title?: string }>
  parentage_suggestion?: { project_id?: string; reason?: string } | null
}

type UploadOutcome = {
  outcome_id: string
  interpretation_id: string
  kind: string
  status: string
  ve_kind: string | null
  ve_id: string | null
  created_at: string
}

type ReservedMarker = { snooze_until: string | null }

type Props = {
  base: string
  conversationId: string
  messageId: string
  roundItem: UploadRoundItem
  /** The presenting voice's archetype id — the Train seat chooser
   *  defaults to it (the conversation's seat). */
  seatId?: string | null
  /** Archetype id → display name, for the Train seat chooser. */
  seatNames?: Record<string, string>
  /** Called with the next voice's archetype id after a tap that
   *  returns next_voice (talk / artifact / undertaking / train). */
  onNextVoice?: (archetypeId: string) => void
}

type MenuAction = 'keep' | 'talk' | 'artifact' | 'undertaking' | 'train'

const MENU_LABEL: Record<MenuAction, string> = {
  keep: 'Keep it',
  talk: 'Talk it through — Crane',
  artifact: 'Make an artifact — Fox',
  undertaking: 'Mine for projects — Firebrand',
  train: 'Train a model — Weaver',
}

const SEAT_IDS = [
  'mentor',
  'champion',
  'guardian',
  'maverick',
  'ambassador',
  'conductor',
  'skeptic',
] as const

const SEAT_STOCK_NAMES: Record<string, string> = {
  mentor: 'Gardener',
  champion: 'Firebrand',
  guardian: 'Bear',
  maverick: 'Fox',
  ambassador: 'Crane',
  conductor: 'Weaver',
  skeptic: 'Raven',
}

const OUTCOME_KIND_LABEL: Record<string, string> = {
  keep: 'Kept',
  explore: 'Talked through',
  project: 'Project created',
  task: 'Task created',
  idea: 'Idea created',
}

/** The consequence sentence for one menu action (brief §7.2): what
 *  the tap does, in plain words, beside the verbatim reading. */
export function consequenceCopy(
  action: MenuAction,
  item: UploadRendering,
  detail?: { kind?: string; seatName?: string },
): string {
  if (action === 'keep') {
    return 'This keeps the reading as a record. It creates nothing and invites no one.'
  }
  if (action === 'talk') {
    return 'This invites Crane to talk it through with you. The reading is marked decided.'
  }
  if (action === 'artifact') {
    return 'This makes an artifact from the reading. It creates no task, project, or idea.'
  }
  if (action === 'undertaking') {
    const kind = detail?.kind ?? item.proposed_outcome ?? 'task'
    return `This creates a ${kind} in your execution list. The reading is marked decided.`
  }
  const seat = detail?.seatName ?? 'Weaver'
  return (
    `This files the reading as a pending training claim for ${seat}. ` +
    'Nothing trains until you approve that claim.'
  )
}

export default function UploadRoundCard({
  base,
  conversationId,
  messageId,
  roundItem,
  seatId,
  seatNames,
  onNextVoice,
}: Props) {
  const interpretationId = roundItem.interpretation_id
  const [rendering, setRendering] = useState<UploadRendering | null>(
    roundItem.rendering ?? null,
  )
  const [outcome, setOutcome] = useState<UploadOutcome | null>(null)
  const [decided, setDecided] = useState(false)
  const [parked, setParked] = useState(false)
  const [reserved, setReserved] = useState<ReservedMarker | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [panel, setPanel] = useState<MenuAction | null>(null)
  // Mine-for-projects panel: kind chooser (defaults to the proposed
  // outcome) + parentage chooser (pre-populated with the relevance
  // suggestion when present; the suggestion is never applied
  // without acceptance — it is only the chooser's initial value).
  const [undertakingKind, setUndertakingKind] = useState<string>('')
  const [undertakingParent, setUndertakingParent] = useState<string>('')
  // Make-an-artifact panel: the kind is required for a
  // transformation; a kept reading defaults to "kept-reading".
  const [artifactKind, setArtifactKind] = useState<string>('')
  const [artifactText, setArtifactText] = useState<string>('')
  // Train-a-model panel: the seat chooser defaults to the
  // conversation's seat (the presenting voice).
  const [trainSeat, setTrainSeat] = useState<string>(seatId ?? 'conductor')
  // Remind-me-later: the snooze picker — 1 day, 1 week, or never.
  const [reserveDays, setReserveDays] = useState<'1' | '7' | 'never'>('7')

  const stateUrl =
    `${base}/conversation/upload/item-state?conversation_id=${encodeURIComponent(conversationId)}` +
    `&message_id=${encodeURIComponent(messageId)}&interpretation_id=${encodeURIComponent(interpretationId)}`

  const refresh = async () => {
    try {
      const r = await fetch(stateUrl, { credentials: 'include' })
      if (!r.ok) return
      const data = (await r.json()) as {
        item?: { rendering?: UploadRendering }
        outcome?: UploadOutcome | null
        parked?: boolean
        reserved?: ReservedMarker | null
      }
      if (!data.item?.rendering) return
      setRendering(data.item.rendering)
      setOutcome(data.outcome ?? null)
      setDecided(Boolean(data.outcome && data.outcome.status !== 'pending'))
      setParked(Boolean(data.parked))
      setReserved(data.reserved ?? null)
    } catch {
      /* refresh failure is non-fatal: the card keeps its last state */
    }
  }

  useEffect(() => {
    let cancelled = false
    // Hydration: server state first, so reload never reverts a
    // decision — and never reverts a park or a reserve either.
    // Guarded to this interpretation id (the Firebrand guard,
    // re-asserted): the mount fetch cannot clobber the turn's
    // presented item.
    void fetch(stateUrl, { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (cancelled || !data || !data.item?.rendering) return
        if (data.item.interpretation_id !== interpretationId) return
        setRendering(data.item.rendering as UploadRendering)
        setOutcome((data.outcome as UploadOutcome | null) ?? null)
        setDecided(Boolean(data.outcome && data.outcome.status !== 'pending'))
        setParked(Boolean(data.parked))
        setReserved((data.reserved as ReservedMarker | null) ?? null)
      })
      .catch(() => {
        /* item-state failure is non-fatal: the turn's rendering stands */
      })
    return () => {
      cancelled = true
    }
    // Intentionally not depending on rendering: the mount fetch
    // covers hydration; actions refresh explicitly.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base, conversationId, messageId, interpretationId])

  const readDetail = async (r: Response): Promise<string | null> => {
    try {
      const body = (await r.json()) as { detail?: unknown }
      if (typeof body?.detail === 'string' && body.detail) return body.detail
    } catch {
      /* fall through to the generic message */
    }
    return null
  }

  const act = async (action: MenuAction) => {
    if (!rendering || busy) return
    setBusy(true)
    setError(null)
    try {
      const body: Record<string, unknown> = {
        conversation_id: conversationId,
        message_id: messageId,
      }
      if (action === 'undertaking') {
        body.kind = undertakingKind || rendering.proposed_outcome || 'task'
        if (undertakingParent) body.parent_id = undertakingParent
      }
      if (action === 'artifact') {
        body.artifact_kind =
          artifactKind || (rendering.is_transformation ? '' : 'kept-reading')
        body.artifact_text = artifactText.trim() || undefined
      }
      if (action === 'train') {
        body.seat = trainSeat
      }
      const r = await fetch(
        `${base}/conversation/upload/outcomes/${encodeURIComponent(interpretationId)}/${action}`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        },
      )
      if (r.ok) {
        const data = (await r.json()) as {
          outcome?: UploadOutcome
          next_voice?: { archetype_id?: string }
        }
        if (data.outcome) setOutcome(data.outcome)
        setDecided(true)
        setPanel(null)
        if (data.next_voice?.archetype_id) onNextVoice?.(data.next_voice.archetype_id)
        await refresh()
      } else if (r.status === 409) {
        setError((await readDetail(r)) ?? 'Already decided — refresh to see its state.')
        await refresh()
      } else if (r.status === 422) {
        setError((await readDetail(r)) ?? 'That choice needs more detail — check the panel.')
      } else {
        setError('Couldn’t do that — try again.')
      }
    } catch {
      setError('Couldn’t do that — try again.')
    } finally {
      setBusy(false)
    }
  }

  const openPanel = (action: MenuAction) => {
    if (!rendering) return
    setError(null)
    if (action === 'undertaking') {
      setUndertakingKind(rendering.proposed_outcome ?? 'task')
      // The relevance suggestion pre-populates the chooser; it is
      // never applied without acceptance.
      setUndertakingParent(rendering.parentage_suggestion?.project_id ?? '')
    }
    if (action === 'artifact') {
      setArtifactKind(rendering.is_transformation ? '' : 'kept-reading')
      setArtifactText(rendering.text ?? '')
    }
    if (action === 'train') {
      setTrainSeat(seatId ?? 'conductor')
    }
    setPanel(action)
  }

  const skip = async () => {
    if (!rendering || busy) return
    setBusy(true)
    setError(null)
    try {
      const r = await fetch(`${base}/conversation/upload/round/skip`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          conversation_id: conversationId,
          message_id: messageId,
          interpretation_id: interpretationId,
        }),
      })
      if (r.ok) {
        setParked(true)
      } else if (r.status === 409) {
        setError((await readDetail(r)) ?? 'Already decided — refresh to see its state.')
        await refresh()
      } else {
        setError('Couldn’t park this one — try again.')
      }
    } catch {
      setError('Couldn’t park this one — try again.')
    } finally {
      setBusy(false)
    }
  }

  const reserve = async (archive: boolean) => {
    if (!rendering || busy) return
    setBusy(true)
    setError(null)
    try {
      const r = await fetch(`${base}/conversation/upload/round/reserve`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          conversation_id: conversationId,
          message_id: messageId,
          interpretation_id: interpretationId,
          snooze_days: archive ? null : reserveDays === 'never' ? null : Number(reserveDays),
          archive,
        }),
      })
      if (r.ok) {
        const data = (await r.json()) as { marker: ReservedMarker }
        setReserved(data.marker)
      } else if (r.status === 409) {
        setError((await readDetail(r)) ?? 'Already decided — refresh to see its state.')
        await refresh()
      } else {
        setError('Couldn’t set that — try again.')
      }
    } catch {
      setError('Couldn’t set that — try again.')
    } finally {
      setBusy(false)
    }
  }

  const unreserve = async () => {
    if (!rendering || busy) return
    setBusy(true)
    setError(null)
    try {
      const r = await fetch(`${base}/conversation/upload/round/unreserve`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          conversation_id: conversationId,
          message_id: messageId,
          interpretation_id: interpretationId,
        }),
      })
      if (r.ok) {
        setReserved(null)
      } else if (r.status === 409) {
        setError((await readDetail(r)) ?? 'Already decided — refresh to see its state.')
        await refresh()
      } else {
        setError('Couldn’t undo that — try again.')
      }
    } catch {
      setError('Couldn’t undo that — try again.')
    } finally {
      setBusy(false)
    }
  }

  const text = rendering?.text ?? 'No reading recorded'
  const spans = rendering?.spans ?? []
  const observations = rendering?.observations ?? []
  const parentageOptions = rendering?.parentage_options ?? []
  const suggestion = rendering?.parentage_suggestion ?? null
  const outcomeLabel = outcome ? OUTCOME_KIND_LABEL[outcome.kind] ?? outcome.kind : null

  return (
    <div className="max-w-[88%] w-full space-y-2">
      <div className="rounded-2xl border border-stone-700/60 bg-stone-900/70 px-3 py-2 text-sm">
        <p className="text-[11px] uppercase tracking-wide text-stone-500">Upload rapid fire</p>
        {!rendering ? (
          <p className="text-stone-400">Loading this reading…</p>
        ) : decided ? (
          <div className="space-y-1">
            <p className="text-emerald-200">
              Ruled. {outcomeLabel ? `${outcomeLabel}.` : 'Decided.'}
              {outcome?.status === 'creating' ? ' Creating…' : ''}
              {outcome?.status === 'archived' ? ' Archived.' : ''}
            </p>
            <p className="text-xs text-stone-400">
              &ldquo;{text}&rdquo;
            </p>
            <p className="text-[11px] text-stone-500">
              The conductor will bring the next one when you reply.
            </p>
          </div>
        ) : reserved ? (
          <div className="space-y-2">
            <p className="text-stone-300">
              Won&apos;t remind you about this one
              {reserved.snooze_until
                ? ` — back after ${reserved.snooze_until.slice(0, 10)}.`
                : ' — never.'}
            </p>
            <p className="text-xs text-stone-400">&ldquo;{text}&rdquo;</p>
            <button
              type="button"
              disabled={busy}
              onClick={() => void unreserve()}
              className="px-2 py-1 rounded-lg border border-stone-600 text-stone-200 text-xs hover:bg-stone-800 disabled:opacity-50"
            >
              Undo
            </button>
            {error && <p className="text-xs text-red-300">{error}</p>}
          </div>
        ) : panel ? (
          <div className="space-y-2">
            <p className="text-stone-100 font-medium">{MENU_LABEL[panel]}</p>
            <p className="text-xs text-stone-400">The reading, word for word:</p>
            <p className="text-xs text-stone-300 italic">&ldquo;{text}&rdquo;</p>
            <p className="text-xs text-stone-300">
              {consequenceCopy(panel, rendering, {
                kind: undertakingKind || undefined,
                seatName:
                  panel === 'train'
                    ? seatNames?.[trainSeat] ?? SEAT_STOCK_NAMES[trainSeat] ?? trainSeat
                    : undefined,
              })}
            </p>
            {panel === 'undertaking' && (
              <div className="flex flex-wrap gap-2">
                <label className="text-xs text-stone-400">
                  Make a{' '}
                  <select
                    aria-label="Undertaking kind"
                    className="rounded-lg bg-stone-800 border border-stone-700 px-2 py-1 text-stone-100"
                    value={undertakingKind}
                    onChange={(ev) => setUndertakingKind(ev.target.value)}
                  >
                    <option value="task">task</option>
                    <option value="project">project</option>
                    <option value="idea">idea</option>
                  </select>
                </label>
                <label className="text-xs text-stone-400">
                  Under{' '}
                  <select
                    aria-label="Undertaking parent project"
                    className="rounded-lg bg-stone-800 border border-stone-700 px-2 py-1 text-stone-100"
                    value={undertakingParent}
                    onChange={(ev) => setUndertakingParent(ev.target.value)}
                  >
                    <option value="">Top-level</option>
                    {parentageOptions.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.title || p.id}
                      </option>
                    ))}
                  </select>
                </label>
                {suggestion && (
                  <p className="text-xs text-stone-400">
                    Suggested: {suggestion.project_id} — {suggestion.reason}
                  </p>
                )}
              </div>
            )}
            {panel === 'artifact' && (
              <div className="space-y-2">
                <label className="text-xs text-stone-400">
                  Artifact kind{' '}
                  <input
                    aria-label="Artifact kind"
                    className="w-full rounded-lg bg-stone-800 border border-stone-700 px-2 py-1 text-stone-100"
                    value={artifactKind}
                    onChange={(ev) => setArtifactKind(ev.target.value)}
                    placeholder={rendering.is_transformation ? 'e.g. note' : 'kept-reading'}
                  />
                </label>
                <label className="text-xs text-stone-400">
                  Artifact text
                  <textarea
                    aria-label="Artifact text"
                    className="w-full rounded-lg bg-stone-800 border border-stone-700 px-2 py-1 text-stone-100"
                    value={artifactText}
                    onChange={(ev) => setArtifactText(ev.target.value)}
                  />
                </label>
              </div>
            )}
            {panel === 'train' && (
              <label className="text-xs text-stone-400">
                Train{' '}
                <select
                  aria-label="Train seat"
                  className="rounded-lg bg-stone-800 border border-stone-700 px-2 py-1 text-stone-100"
                  value={trainSeat}
                  onChange={(ev) => setTrainSeat(ev.target.value)}
                >
                  {SEAT_IDS.map((id) => (
                    <option key={id} value={id}>
                      {seatNames?.[id] ?? SEAT_STOCK_NAMES[id] ?? id}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {error && <p className="text-xs text-red-300">{error}</p>}
            <div className="flex gap-2">
              <button
                type="button"
                disabled={busy || (panel === 'artifact' && rendering.is_transformation && !artifactKind.trim())}
                onClick={() => void act(panel)}
                className="px-2 py-1 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-xs font-medium"
              >
                Confirm
              </button>
              <button
                type="button"
                onClick={() => setPanel(null)}
                className="px-2 py-1 rounded-lg border border-stone-600 text-stone-200 text-xs hover:bg-stone-800"
              >
                Back
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-2">
            {parked && (
              <p className="text-xs text-amber-300">
                Parked — it&apos;ll come back next round.
              </p>
            )}
            <p className="text-stone-100 font-medium">
              {rendering.attribution ?? 'A reading from your upload'}
            </p>
            <p className="text-stone-100">&ldquo;{text}&rdquo;</p>
            {spans.length > 0 && (
              <div className="space-y-1">
                <p className="text-xs text-stone-400">From the document:</p>
                {spans.map((s) => (
                  <p key={s.span_id ?? s.text} className="text-xs text-stone-300 italic">
                    &ldquo;{s.text}&rdquo;
                    {s.location ? <span className="text-stone-500"> ({s.location})</span> : null}
                  </p>
                ))}
              </div>
            )}
            {observations.length > 0 && (
              <div className="space-y-1">
                <p className="text-xs text-stone-400">Noted alongside:</p>
                {observations.map((o) => (
                  <p key={o.observation_id ?? o.claim} className="text-xs text-stone-300">
                    {o.claim}
                  </p>
                ))}
              </div>
            )}
            {rendering.coverage && (
              <p className="text-xs text-stone-400">{rendering.coverage}</p>
            )}
            {rendering.uncertain_match && (
              <p className="text-xs text-amber-300">
                A similar reading was already ruled on — check it against that one before
                deciding.
              </p>
            )}
            {error && <p className="text-xs text-red-300">{error}</p>}
            <div className="flex flex-wrap gap-2">
              {(['keep', 'talk', 'artifact', 'undertaking', 'train'] as MenuAction[]).map(
                (a) => (
                  <button
                    key={a}
                    type="button"
                    disabled={busy}
                    onClick={() => openPanel(a)}
                    className="px-2 py-1 rounded-lg border border-stone-600 text-stone-200 text-xs hover:bg-stone-800 disabled:opacity-50"
                  >
                    {MENU_LABEL[a]}
                  </button>
                ),
              )}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={() => void skip()}
                className="px-2 py-1 rounded-lg border border-stone-600 text-stone-200 text-xs hover:bg-stone-800 disabled:opacity-50"
              >
                Not now
              </button>
              <label className="text-xs text-stone-400">
                Remind me in{' '}
                <select
                  aria-label="Remind me in"
                  className="rounded-lg bg-stone-800 border border-stone-700 px-2 py-1 text-stone-100"
                  value={reserveDays}
                  onChange={(ev) =>
                    setReserveDays(ev.target.value as '1' | '7' | 'never')
                  }
                >
                  <option value="1">1 day</option>
                  <option value="7">1 week</option>
                  <option value="never">Never</option>
                </select>
              </label>
              <button
                type="button"
                disabled={busy}
                onClick={() => void reserve(false)}
                className="px-2 py-1 rounded-lg border border-stone-600 text-stone-200 text-xs hover:bg-stone-800 disabled:opacity-50"
              >
                Remind me later
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void reserve(true)}
                className="px-2 py-1 rounded-lg border border-stone-600 text-stone-200 text-xs hover:bg-stone-800 disabled:opacity-50"
              >
                Archive it
              </button>
            </div>
            <p className="text-[11px] text-stone-500">
              Tap to rule on this one. The conductor brings the next one when you reply —
              nothing happens until then.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
