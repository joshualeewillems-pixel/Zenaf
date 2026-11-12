import { useCallback, useEffect, useRef, useState } from 'react'
import { apiBase } from '../apiBase'
import { useAutoGrowTextarea } from '../components/useAutoGrowTextarea'
import { isCoarsePointer } from '../components/isCoarsePointer'
import { WeaveText, voiceColor } from '../components/VoiceWeave'
import SeatChips, { SEAT_ORDER, useSeatMeta } from './SeatChips'
import TaskProposalCards from './TaskProposalCards'
import RoundProposalCard, { type RoundItem } from './RoundProposalCard'
import UploadRoundCard, { type UploadRoundItem } from './UploadRoundCard'
import WeaverRoundClaimCard from './WeaverRoundClaimCard'
import { stripCorrectionDraft, stripRoundOfferMarker, type WeaverRoundItem } from './weaverRound'
import { stripTaskProposalBlocks } from './taskProposals'
import VoiceFeedback, { type InitialFeedback } from './VoiceFeedback'
import {
  useDraftStore,
  COUNCIL_DRAFT_SEAT,
  UNSELECTED_DRAFT_SEAT,
} from './draftStore'

/**
 * One message in the persistent conversation. Voice turns carry the
 * responding seat's attribution so the thread stays readable as seats
 * change — history is shared across the whole conversation, never
 * partitioned per seat.
 */
export type ConversationMessage = {
  role: 'user' | 'voice'
  content: string
  voiceId?: string | null
  voiceName?: string
  voiceColor?: string
  /** Stable response reference for feedback: the server message id on
   *  the store path, a session-scoped `local-` ref otherwise. Absent for
   *  seed/initial messages and failure notices — those get no widget. */
  messageId?: string | null
  /** Firebrand lightning round (S1): the item this voice message
   *  presented. Live turns carry the full proposal from the turn
   *  response; hydration carries only kind + id, and the card
   *  refetches the proposal by id. Absent on every other message.
   *  Weaver rapid fire (S1): the same field carries a
   *  meeting-impression item instead (kind + agent + claim id, and
   *  the deterministic rendering on live turns). */
  roundItem?: RoundItem | WeaverRoundItem | UploadRoundItem | null
  /** Weaver rapid fire (S1): the round state this turn recorded
   *  ("item" | "checkpoint" | "closing" | "offered" | "ended").
   *  Carried from the turn response; absent on other turns. */
  roundState?: string | null
}

/** Server message row → thread message. Shared by hydration and
 *  load-earlier so both paths map identically. */
function mapServerMessages(
  rows: unknown,
  names: Record<string, string>,
): ConversationMessage[] {
  const mapped: ConversationMessage[] = []
  if (!Array.isArray(rows)) return mapped
  for (const m of rows) {
    if (!m || typeof m !== 'object') continue
    // Strip the [[round-offer]] marker from display (live + hydrated
    // messages): the marker records the offer server-side; it is not
    // part of the reply the user reads. Applied here at render and
    // at turn receipt, so both paths agree.
    const body = stripRoundOfferMarker(String((m as Record<string, unknown>).body ?? ''))
    if (!body) continue
    const role = (m as Record<string, unknown>).role === 'user' ? 'user' : 'voice'
    const aid =
      typeof (m as Record<string, unknown>).archetype_id === 'string'
        ? ((m as Record<string, unknown>).archetype_id as string)
        : null
    // Firebrand lightning round (S1): the assistant message's
    // context_json carries the round marker — kind + presented
    // proposal id. The card refetches the proposal by id; the
    // marker is the authority, never message text. Weaver rapid
    // fire (S1): the same marker shape carries kind + presented
    // claim id + agent id; the card refetches the claim by id and
    // the live turn's rendering rides the turn response.
    const ctx = (m as Record<string, unknown>).context
    const roundCtx =
      ctx && typeof ctx === 'object' ? (ctx as Record<string, unknown>) : null
    const roundProposalId =
      roundCtx && typeof roundCtx.round_proposal_id === 'string'
        ? (roundCtx.round_proposal_id as string)
        : null
    const roundClaimId =
      roundCtx && typeof roundCtx.round_claim_id === 'string'
        ? (roundCtx.round_claim_id as string)
        : null
    const roundAgentId =
      roundCtx && typeof roundCtx.round_agent_id === 'string'
        ? (roundCtx.round_agent_id as string)
        : null
    const roundInterpretationId =
      roundCtx && typeof roundCtx.round_interpretation_id === 'string'
        ? (roundCtx.round_interpretation_id as string)
        : null
    const roundItem =
      roundCtx?.round_kind === 'firebrand' && roundProposalId
        ? { kind: 'task_proposal', proposal_id: roundProposalId }
        : roundCtx?.round_kind === 'weaver' && roundClaimId && roundAgentId
          ? {
              kind: 'meeting_impression' as const,
              agent_id: roundAgentId,
              claim_id: roundClaimId,
              claim_type: 'meeting_impression',
            }
          : roundCtx?.round_kind === 'upload' && roundInterpretationId
            ? {
                kind: 'interpretation' as const,
                interpretation_id: roundInterpretationId,
              }
            : null
    mapped.push({
      role,
      content: body,
      messageId:
        typeof (m as Record<string, unknown>).id === 'string'
          ? ((m as Record<string, unknown>).id as string)
          : null,
      voiceId: role === 'voice' ? aid : null,
      voiceName: role === 'voice' ? names[aid ?? ''] ?? aid ?? undefined : undefined,
      voiceColor: role === 'voice' && aid ? voiceColor(aid) : undefined,
      roundItem,
    })
  }
  return mapped
}

/** Session-scoped response ref for threads that live in component state
 *  only (no server message id exists there). The `local-` prefix never
 *  collides with server ids, which are bare hex. */
function newLocalRef(): string {
  const rand =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2)}`
  return `local-${rand}`
}

/**
 * The unified 1:1 conversation — one voice at a time, everywhere.
 *
 * Conversation model: ONE persistent conversation per user (the skeleton)
 * with persona branches. Tapping a seat chip branches the ongoing
 * conversation to that seat; the message list is never cleared on switch.
 * The 7+ persona threads the system maintains in the background are not
 * overt separate chats the user manages — this component shows the one
 * thread, with per-message voice attribution.
 *
 * Persistence: when `conversationId` is present, the thread hydrates from
 * GET /conversation and each turn persists via POST /conversation/turn
 * (carrying the sheet's live `context`). Without it, the thread lives in
 * component state and sends go to POST /voice/chat with client history.
 * Tree Talk (Slice A) always passes a `talk-` conversation id resolved
 * through GET /conversation/list, so Tree threads are server-backed;
 * the workspace console still mounts without one and keeps client history.
 *
 * - Sheet seat tab → pre-selected seat (character header rendered above by
 *   the sheet, from PR #147's merged Talk+Character tab).
 * - Sheet you-node → chips with no pre-selection: an invitation to pick.
 *
 * Choose multiple (Joshua, 2026-11-12 — supersedes "Ask the council",
 * 2026-10-23): having two chats was confusing, so the workspace
 * console's conversational power lives here now — multi-seat fan-out.
 * The "choose multiple" control opens checkboxes on the seat chips
 * above; the send fans out to exactly the checked seats through the
 * same per-seat turn path, and each reply lands in this one thread
 * under its seat's name. Entering the mode checks every seat, so the
 * old all-seats behaviour is the starting point — the user unchecks
 * to narrow. The workspace console remains a deliberation console
 * (folder runs, synthesis, recorded insights) — talking lives here.
 */
export default function CouncilChat({
  environment,
  initialArchetypeId = null,
  lockArchetypeId = null,
  displayName,
  conversationId = null,
  initialMessages,
  context = null,
  prefill = null,
  seedMessages = null,
  onTurnSent = () => {},
}: {
  /** 'sheet' = compact. 'workspace' = roomier. */
  environment: 'sheet' | 'workspace'
  /** Pre-selected seat (seat-branch sheets). Omit → chips, no selection. */
  initialArchetypeId?: string | null
  /** Weaver strand interviews (rev2): when set, the chat is locked to
   *  this seat — SeatChips and "choose multiple" are hidden, the seat
   *  can never change, and the draft is keyed to the locked seat. */
  lockArchetypeId?: string | null
  /** Seat fellowship name override for the composer placeholder. */
  displayName?: string
  /** Backend conversation-store key. When present, the thread hydrates from
   *  GET /conversation and turns persist via POST /conversation/turn. */
  conversationId?: string | null
  /** Hydration seam: messages a future backend store hands back. */
  initialMessages?: ConversationMessage[]
  /** Skeleton-store live context carried on every turn (sheet + entity in
   *  focus). Only sent when conversationId is present. */
  context?: Record<string, unknown> | null
  /** External draft injection: when nonce changes, the composer takes this
   *  text. Never sends on its own. */
  prefill?: { text: string; nonce: number } | null
  /** Messages folded into the thread when the store thread is empty (e.g.
   *  open questions). Client-side only; the store stays the source of truth
   *  once it has turns. */
  seedMessages?: ConversationMessage[] | null
  /** Capability C visible-UX slice: invoked on SUCCESS arms of the send
   *  handler only (council-results and single-seat), after the reply
   *  lands — never on 'auth', never in the catch arm, never on a
   *  target-mismatch early return. The sheet uses it to refetch the
   *  invitation list, observing a join by the entry disappearing. */
  onTurnSent?: () => void
}) {
  const base = apiBase()
  const { names } = useSeatMeta()
  // Draft store (Tree sheet subtree only; null on workspace/console
  // mounts, which keep purely local composer state). When present,
  // the store is the SOLE restore path for this composer: mount-time
  // initialization reads it, every keystroke writes through to it,
  // and the prefill prop never restores over it.
  const draftCtx = useDraftStore()
  const draftUserId = draftCtx?.userId ?? null

  // The persistent thread — initialized once from the hydration seam.
  // Switching seats never touches this list.
  const [messages, setMessages] = useState<ConversationMessage[]>(initialMessages ?? [])
  const [activeId, setActiveId] = useState<string | null>(lockArchetypeId ?? initialArchetypeId ?? null)
  /** Ask-the-council fan-out: the next send goes to every seat at once. */
  const [councilMode, setCouncilMode] = useState(false)
  /**
   * "choose multiple" (founder, 2026-11-12 — replaces "Ask the
   * council"): checkbox mode on the seat chips; the send fans out to
   * exactly the checked seats instead of all of them. Entering the
   * mode checks every seat (the old all-seats behaviour is the
   * starting point); the user unchecks to narrow. councilMode stays
   * the send-path flag — it is true exactly while checkbox mode is on.
   */
  const [chooseMultiple, setChooseMultiple] = useState(false)
  const [checkedSeatIds, setCheckedSeatIds] = useState<string[]>([])
  // A locked seat stays locked: the chips (the only UI path that calls
  // setActiveId) are hidden when locked, and this effect re-forces the
  // lock if anything else ever moves it.
  useEffect(() => {
    if (lockArchetypeId) setActiveId(lockArchetypeId)
  }, [lockArchetypeId])
  // Mount-time initialization from the draft store, never an effect
  // restore: on every remount (seat/conversation switch, sheet reopen,
  // invitation shortcut) the composer starts from the store entry for
  // (user, conversation, initial seat) — or the adopted unselected
  // draft when the mount arrives with no seat selected. Mounts with a
  // null conversationId ('local') never touch the store.
  const [input, setInput] = useState(() => {
    if (!draftCtx || !draftCtx.userId || !conversationId) return ''
    return (
      draftCtx.store.adopt(
        draftCtx.userId,
        conversationId,
        lockArchetypeId ?? initialArchetypeId ?? UNSELECTED_DRAFT_SEAT,
      ) ?? ''
    )
  })
  const [loading, setLoading] = useState(false)
  /**
   * Voice: always the canonical seat (base). The Zenaf/You switch and
   * the workspace trained/base toggle were removed 2026-11-12 (UI
   * cleanup): the trained echo does not exist yet, so there is nothing
   * to switch to. A training-threshold unlock gate is a future open
   * item, not built here. The backend still defaults `mode` to
   * "trained", so the base choice is sent explicitly on every turn.
   */
  const chatMode: 'trained' | 'base' = 'base'
  const [signedOut, setSignedOut] = useState(false)
  const chatEndRef = useRef<HTMLDivElement | null>(null)

  // The store key rides along for the next build; today it only identifies
  // the thread for future hydration (call sites key on it when it exists).
  const conversationKey = conversationId ?? 'local'

  /** Saved feedback, latest row per response_ref, for prefilling the
   *  widgets. One GET /feedback per conversation load — never one per
   *  message. A failed or malformed response is silent: widgets mount
   *  unanswered, exactly as if no record existed. */
  const [feedbackByResponse, setFeedbackByResponse] = useState<
    Record<string, InitialFeedback>
  >({})
  useEffect(() => {
    let cancelled = false
    setFeedbackByResponse({})
    fetch(
      `${base}/feedback?conversation_id=${encodeURIComponent(conversationKey)}&limit=200`,
      { credentials: 'include' },
    )
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return (await r.json()) as Record<string, unknown>
      })
      .then((data) => {
        if (cancelled) return
        const records = (data as { records?: unknown }).records
        if (!Array.isArray(records)) return
        // Newest first: the first row per response_ref is the latest.
        const map: Record<string, InitialFeedback> = {}
        for (const rec of records) {
          if (!rec || typeof rec !== 'object') continue
          const ref = (rec as Record<string, unknown>).response_ref
          if (typeof ref !== 'string' || ref in map) continue
          const slider = (rec as Record<string, unknown>).slider
          const checks = (rec as Record<string, unknown>).checks
          const note = (rec as Record<string, unknown>).note
          if (typeof slider !== 'number') continue
          map[ref] = {
            slider,
            checks: Array.isArray(checks)
              ? checks.filter((c): c is string => typeof c === 'string')
              : [],
            note: typeof note === 'string' ? note : '',
          }
        }
        setFeedbackByResponse(map)
      })
      .catch(() => {
        // Silent: prefill is a convenience, not a load-bearing read.
      })
    return () => {
      cancelled = true
    }
  }, [conversationKey, base])

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages.length, loading])

  // Skeleton-store hydration: when a conversationId is present, the thread
  // is the server's. Hydrate once per key; an empty store thread falls back
  // to seedMessages (folded-in open questions), then to initialMessages.
  // Seeds apply only while the user hasn't written yet — never clobbering.
  //
  // Send gating (Slice A, correction C2): send is disabled while
  // hydrating, enabled on success or on a confirmed empty thread, and
  // disabled on hydration failure until a SUCCESSFUL retry — never
  // merely because the error was acknowledged. A failed hydration must
  // never present as an empty thread, and a late response for a
  // previous conversation must never overwrite the current one
  // (request sequence + cleanup invalidation).
  const namesRef = useRef(names)
  namesRef.current = names
  const conversationIdRef = useRef(conversationId)
  conversationIdRef.current = conversationId
  // Latest composer text for the send-failure restore decision (the
  // send closure's `input` is the pre-send value, not the current
  // one). Updated SYNCHRONOUSLY by setComposer at every write site —
  // a passive-effect mirror would lag by one flush, and the failure
  // restore would read stale text.
  const inputRef = useRef(input)
  const setComposer = (v: string) => {
    inputRef.current = v
    setInput(v)
  }
  const composerRef = useAutoGrowTextarea(input)
  // Auth change while mounted: the provider purges the store, so the
  // composer must not keep displaying the previous user's text.
  const draftUserRef = useRef<string | null | undefined>(draftUserId)
  useEffect(() => {
    if (draftCtx && draftUserRef.current !== draftUserId) {
      draftUserRef.current = draftUserId
      setComposer('')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftCtx, draftUserId])
  const hydrateSeqRef = useRef(0)
  const sendSeqRef = useRef(0)
  const [storeEmpty, setStoreEmpty] = useState<boolean | null>(null)
  const [hydrating, setHydrating] = useState(false)
  const [hydrateError, setHydrateError] = useState(false)
  const [hydrateNonce, setHydrateNonce] = useState(0)
  const [totalMessages, setTotalMessages] = useState<number | null>(null)
  const [loadingEarlier, setLoadingEarlier] = useState(false)
  const [loadEarlierError, setLoadEarlierError] = useState(false)
  useEffect(() => {
    if (!conversationId) return
    const seq = ++hydrateSeqRef.current
    let cancelled = false
    // A new conversation starts from its own server thread, never from
    // the previous conversation's displayed messages.
    setMessages([])
    setStoreEmpty(null)
    setHydrateError(false)
    setSignedOut(false)
    setHydrating(true)
    setTotalMessages(null)
    fetch(
      `${base}/conversation?conversation_id=${encodeURIComponent(conversationId)}&limit=200`,
      { credentials: 'include' },
    )
      .then(async (r) => {
        if (r.status === 401) return { auth: true as const }
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return (await r.json()) as Record<string, unknown>
      })
      .then((data) => {
        if (cancelled || hydrateSeqRef.current !== seq) return
        if ((data as { auth?: boolean }).auth) {
          setSignedOut(true)
          setHydrateError(true)
          setHydrating(false)
          return
        }
        const mapped = mapServerMessages(
          (data as { messages?: unknown }).messages,
          namesRef.current,
        )
        if (mapped.length > 0) {
          setMessages(mapped)
          setStoreEmpty(false)
        } else {
          setStoreEmpty(true)
        }
        setTotalMessages(
          typeof (data as { total?: unknown }).total === 'number'
            ? ((data as { total: number }).total as number)
            : null,
        )
        setHydrating(false)
      })
      .catch(() => {
        if (cancelled || hydrateSeqRef.current !== seq) return
        // Failure is NOT an empty thread: banner + retry, send stays
        // disabled until a retry succeeds.
        setHydrateError(true)
        setHydrating(false)
      })
    return () => {
      cancelled = true
    }
  }, [conversationId, base, hydrateNonce])

  useEffect(() => {
    if (!conversationId || storeEmpty !== true) return
    if (!seedMessages || seedMessages.length === 0) return
    if (messages.some((m) => m.role === 'user')) return
    setMessages((prev) => (prev.length === 0 ? seedMessages : prev))
  }, [conversationId, storeEmpty, seedMessages, messages])

  /** Load earlier messages via the stable (created_at, id) cursor:
   *  the oldest displayed server message. New arrivals can never
   *  shift, duplicate, or skip rows in earlier pages; merges dedupe
   *  by server id as a second guard. */
  const loadEarlier = useCallback(async () => {
    if (!conversationId || loadingEarlier) return
    const oldest = messages.find((m) => m.messageId && !m.messageId.startsWith('local-'))
    if (!oldest?.messageId) return
    setLoadingEarlier(true)
    setLoadEarlierError(false)
    try {
      const r = await fetch(
        `${base}/conversation?conversation_id=${encodeURIComponent(conversationId)}&limit=200&before=${encodeURIComponent(oldest.messageId)}`,
        { credentials: 'include' },
      )
      if (r.status === 401) {
        setSignedOut(true)
        return
      }
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const data = (await r.json()) as Record<string, unknown>
      const mapped = mapServerMessages(data.messages, namesRef.current)
      const seen = new Set(messages.map((m) => m.messageId).filter(Boolean))
      const fresh = mapped.filter((m) => !m.messageId || !seen.has(m.messageId))
      setMessages((prev) => [...fresh, ...prev])
      if (typeof data.total === 'number') setTotalMessages(data.total)
    } catch {
      setLoadEarlierError(true)
    } finally {
      setLoadingEarlier(false)
    }
  }, [conversationId, messages, loadingEarlier, base])
  const prefillNonce = prefill?.nonce ?? 0
  useEffect(() => {
    // Single-owner rule: when the draft store is present (Tree sheet
    // mounts) the store is the sole restore path, so prefill never
    // restores over a stored draft or newer typing. Workspace/console
    // mounts have no store, and prefill works exactly as before.
    if (!draftCtx && prefill && prefillNonce > 0) setComposer(prefill.text)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefillNonce])

  /** Synchronous composer swap for a seat/council switch (store mounts
   *  only; without a store the input is shared, exactly as today).
   *  The outgoing draft is already saved by write-through; this only
   *  LOADS the incoming key's draft (or ''). When the outgoing
   *  identity is 'unselected', the first selection adopts its text
   *  (a move — see DraftStore.adopt) instead of a plain load. */
  const swapComposer = (destSeat: string) => {
    if (!draftCtx || !draftCtx.userId || !conversationId) return
    const outgoing = councilMode
      ? COUNCIL_DRAFT_SEAT
      : (activeId ?? UNSELECTED_DRAFT_SEAT)
    if (outgoing === UNSELECTED_DRAFT_SEAT) {
      setComposer(draftCtx.store.adopt(draftCtx.userId, conversationId, destSeat) ?? '')
    } else {
      setComposer(
        draftCtx.store.get({
          userId: draftCtx.userId,
          conversationId,
          seat: destSeat,
        }) ?? '',
      )
    }
  }

  const activeName =
    displayName ?? (activeId ? names[activeId] ?? activeId : null) ?? 'a voice'

  /** One seat's turn through whichever path this mount uses (skeleton
   *  store when conversationId is present, client-history otherwise).
   *  Returns 'auth' on 401 so callers can settle quietly; throws on
   *  other failures. */
  const askSeat = useCallback(
    async (seatId: string, text: string): Promise<ConversationMessage | 'auth'> => {
      const useStore = Boolean(conversationId)
      const r = await fetch(useStore ? `${base}/conversation/turn` : `${base}/voice/chat`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(
          useStore
            ? {
                conversation_id: conversationId,
                archetype_id: seatId,
                message: text,
                mode: chatMode,
                ...(context ? { context } : {}),
              }
            : {
                archetype_id: seatId,
                message: text,
                history: messages.map((m) => ({ role: m.role, content: m.content })),
                mode: chatMode,
              },
        ),
      })
      if (r.status === 401) return 'auth'
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const data = await r.json()
      // The turn echoes its conversation_id: a reply for another thread
      // must never land in this one.
      if (useStore && data.conversation_id && data.conversation_id !== conversationId) {
        throw new Error('conversation mismatch')
      }
      return {
        role: 'voice',
        // Strip the [[round-offer]] marker at receipt (the render
        // path strips it too, so live + hydrated messages agree).
        content: stripRoundOfferMarker(data.reply),
        // Store path: the server's message id. Local path: no server id
        // exists, so mint a session-scoped ref at receipt time.
        messageId: useStore ? (data.message_id ?? null) : newLocalRef(),
        voiceId: data.archetype_id ?? seatId,
        voiceName:
          data.display_name ?? (seatId === activeId ? activeName : names[seatId] ?? seatId),
        voiceColor: data.voice_color ?? undefined,
        // Firebrand lightning round (S1): the item this reply
        // presented, if any — the card renders from it. Weaver
        // rapid fire (S1): the same field carries the claim item,
        // and round_state says what the turn did for the round.
        roundItem: data.round_item ?? null,
        roundState: data.round_state ?? null,
      }
    },
    [base, conversationId, context, chatMode, messages, names, activeId, activeName],
  )

  const send = useCallback(async () => {
    const text = input.trim()
    if (loading) return
    if (!councilMode && !activeId) return
    // Checkbox mode with nothing checked sends nowhere — the button
    // is disabled too; this is the Enter-key path.
    if (chooseMultiple && checkedSeatIds.length === 0) return
    if (!text) return
    // The Enter key path bypasses the disabled button: enforce the
    // hydration gate here too — never send into a thread whose
    // history hasn't loaded.
    if (conversationId && (hydrating || hydrateError)) return
    // A send must never target a stale conversation: capture the
    // thread this send belongs to, and only append its results while
    // the user is still on it.
    const targetId = conversationIdRef.current
    const seq = ++sendSeqRef.current
    // C3 precise send boundary: capture the draft key (and the raw
    // composer text) WHEN Send is pressed. A later completion — success
    // or failure — acts only on this captured key, never on whichever
    // draft happens to be active when the response lands. Nothing is
    // cleared before the request has been accepted for persistence.
    const sendDraftKey =
      draftCtx && draftCtx.userId && conversationId
        ? {
            userId: draftCtx.userId,
            conversationId,
            seat: councilMode
              ? COUNCIL_DRAFT_SEAT
              : (activeId ?? UNSELECTED_DRAFT_SEAT),
          }
        : null
    const sentRaw = input
    const clearSentDraftIfUnchanged = () => {
      if (!sendDraftKey || !draftCtx) return
      // Only clear when the store still holds exactly what was sent:
      // text typed while the response was in flight must survive.
      if (draftCtx.store.get(sendDraftKey) === sentRaw) {
        draftCtx.store.clear(sendDraftKey)
      }
    }
    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setComposer('')
    setLoading(true)
    setSignedOut(false)
    try {
      if (councilMode) {
        // Fan out to the checked seats (checkbox mode) or to every
        // seat. A seat that fails gets a quiet, honestly-labelled
        // bubble — the others still answer.
        const targets = chooseMultiple
          ? SEAT_ORDER.filter((s) => checkedSeatIds.includes(s))
          : SEAT_ORDER
        const results = await Promise.all(
          targets.map(async (seatId) => {
            try {
              return await askSeat(seatId, text)
            } catch {
              return {
                role: 'voice' as const,
                content: "I couldn't reach my voice just now — try again in a moment.",
                voiceId: seatId,
                voiceName: names[seatId] ?? seatId,
              }
            }
          }),
        )
        const accepted = !results.every((x) => x === 'auth')
        if (accepted) clearSentDraftIfUnchanged()
        if (conversationIdRef.current !== targetId) return
        if (!accepted) {
          setSignedOut(true)
          setMessages((prev) => prev.slice(0, -1))
          return
        }
        setMessages((prev) => [
          ...prev,
          ...results.filter((x): x is ConversationMessage => x !== 'auth'),
        ])
        onTurnSent()
      } else if (activeId) {
        const reply = await askSeat(activeId, text)
        if (reply !== 'auth') clearSentDraftIfUnchanged()
        if (conversationIdRef.current !== targetId) return
        if (reply === 'auth') {
          setSignedOut(true)
          setMessages((prev) => prev.slice(0, -1))
          return
        }
        setMessages((prev) => [...prev, reply])
        onTurnSent()
      }
    } catch {
      if (conversationIdRef.current !== targetId) return
      // Failed submission clears nothing: the sent draft stays in the
      // store. Restore it into the composer only when the composer is
      // currently empty and the active key is still the captured key,
      // so a stale restore never overwrites in-flight typing and a
      // switch-while-pending leaves the new draft intact.
      if (sendDraftKey && draftCtx) {
        const currentSeat = councilMode
          ? COUNCIL_DRAFT_SEAT
          : (activeId ?? UNSELECTED_DRAFT_SEAT)
        if (
          inputRef.current === '' &&
          currentSeat === sendDraftKey.seat &&
          conversationIdRef.current === sendDraftKey.conversationId
        ) {
          const saved = draftCtx.store.get(sendDraftKey)
          if (saved !== undefined) setComposer(saved)
        }
      }
      if (!councilMode && activeId) {
        setMessages((prev) => [
          ...prev,
          {
            role: 'voice',
            content: "I couldn't reach my voice just now — try again in a moment.",
            voiceId: activeId,
            voiceName: activeName,
          },
        ])
      }
    } finally {
      if (sendSeqRef.current === seq) setLoading(false)
    }
  }, [input, loading, activeId, councilMode, chooseMultiple, checkedSeatIds, askSeat, activeName, names, conversationId, hydrating, hydrateError, onTurnSent, draftCtx, setComposer])

  const sendDisabled =
    loading ||
    (!activeId && !councilMode) ||
    (chooseMultiple && checkedSeatIds.length === 0) ||
    !input.trim() ||
    (conversationId ? hydrating || hydrateError : false)

  return (
    <div className="flex flex-col gap-3" data-conversation={conversationKey}>
      {/* Seat switcher — tapping branches the ongoing conversation.
          Hidden when the chat is locked to one seat (strand interviews):
          there is nothing to switch to, and no fan-out. */}
      {!lockArchetypeId && (
        <>
          <SeatChips
            activeId={chooseMultiple ? null : activeId}
            checkable={chooseMultiple}
            checkedIds={checkedSeatIds}
            onToggleCheck={(id) =>
              setCheckedSeatIds((prev) =>
                prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id],
              )
            }
            onSelect={(id) => {
              swapComposer(id)
              setActiveId(id)
              setCouncilMode(false)
            }}
          />

          {/* choose multiple — checkboxes on the seat chips above; the
              send fans out to exactly the checked seats. Tapping again
              exits checkbox mode and clears the checked set. */}
          <div className="flex flex-wrap items-center gap-3 -mt-1">
            <button
              type="button"
              onClick={() => {
                if (chooseMultiple) {
                  // Exit: back to the active seat, or 'unselected'
                  // when no seat is picked.
                  swapComposer(activeId ?? UNSELECTED_DRAFT_SEAT)
                  setChooseMultiple(false)
                  setCouncilMode(false)
                  setCheckedSeatIds([])
                } else {
                  // Enter: every seat checked (the old all-seats
                  // behaviour is the starting point); uncheck to narrow.
                  swapComposer(COUNCIL_DRAFT_SEAT)
                  setChooseMultiple(true)
                  setCouncilMode(true)
                  setCheckedSeatIds([...SEAT_ORDER])
                }
              }}
              aria-pressed={chooseMultiple}
              className={`min-h-[44px] px-4 rounded-full border text-sm font-medium ${
                chooseMultiple
                  ? 'bg-amber-950/40 text-amber-300 border-amber-700/50'
                  : 'border-stone-700 text-stone-400'
              }`}
            >
              {chooseMultiple ? '✓ choose multiple' : 'choose multiple'}
            </button>
            {chooseMultiple && (
              <p className="text-[11px] text-stone-500">
                {checkedSeatIds.length === 0
                  ? 'Choose at least one seat above — nothing is checked yet.'
                  : 'One message — only the checked seats answer here, under their own names.'}
              </p>
            )}
          </div>
        </>
      )}

      {/* Hydration failure is not an empty thread: banner + retry, and
       *  send stays disabled until a retry succeeds. */}
      {conversationId && hydrateError && (
        <div className="rounded-2xl border border-red-800/60 bg-red-950/30 px-3 py-2 text-sm text-red-200">
          Couldn&apos;t load this conversation — sending is disabled until it loads.
          <button
            type="button"
            onClick={() => setHydrateNonce((n) => n + 1)}
            className="ml-2 underline font-medium"
          >
            Retry
          </button>
        </div>
      )}
      {conversationId && hydrating && (
        <p className="text-xs text-stone-500">Loading conversation…</p>
      )}

      {/* The persistent thread. */}
      <div
        className={`${
          environment === 'workspace' ? 'max-h-[420px]' : 'max-h-[300px]'
        } overflow-y-auto space-y-2`}
        aria-live="polite"
      >
        {conversationId &&
          totalMessages !== null &&
          messages.length < totalMessages &&
          !hydrating && (
            <div className="px-1 py-1">
              <button
                type="button"
                onClick={loadEarlier}
                disabled={loadingEarlier}
                className="text-xs text-stone-400 underline disabled:opacity-40"
              >
                {loadingEarlier ? 'Loading earlier…' : 'Load earlier messages'}
              </button>
              {loadEarlierError && (
                <span className="text-xs text-red-300 ml-2">
                  Couldn&apos;t load earlier messages — try again.
                </span>
              )}
            </div>
          )}
        {!activeId && !councilMode && (
          <p className="text-sm text-stone-400 leading-relaxed px-1 py-2">
            Pick a voice above to begin — one conversation, tap a seat to
            branch it whenever you like. Or ask the whole council at once.
          </p>
        )}
        {messages.map((m, i) =>
          m.role === 'user' ? (
            <div key={i} className="flex justify-end">
              <div className="max-w-[88%] rounded-2xl px-3 py-2 text-sm leading-snug bg-stone-700 text-stone-100">
                {m.content || <span className="text-stone-400 italic">(asked for a question)</span>}
              </div>
            </div>
          ) : (
            <div key={i} className="flex flex-col items-start gap-1">
              <div
                className="max-w-[88%] rounded-2xl px-3 py-2 text-sm leading-snug bg-stone-800/80 border text-stone-200"
                style={
                  m.voiceColor
                    ? {
                        borderColor: `${m.voiceColor}55`,
                        borderLeftWidth: 3,
                        borderLeftColor: m.voiceColor,
                      }
                    : undefined
                }
              >
                {m.voiceName && (
                  <div
                    className="text-xs font-semibold mb-1"
                    style={m.voiceColor ? { color: m.voiceColor } : undefined}
                  >
                    {m.voiceName}
                  </div>
                )}
                {/* Store path only: fenced proposal blocks are replaced
                    by cards below; the raw JSON is never chat text.
                    Client-history path keeps the full text (no cards
                    there in this slice). */}
                <WeaveText
                  text={
                    conversationId && m.messageId && !m.messageId.startsWith('local-')
                      ? stripCorrectionDraft(
                          stripRoundOfferMarker(stripTaskProposalBlocks(m.content)),
                        )
                      : m.content
                  }
                />
              </div>
              {conversationId && m.messageId && !m.messageId.startsWith('local-') && m.voiceId && (
                <TaskProposalCards
                  base={base}
                  conversationId={conversationId}
                  messageId={m.messageId}
                  seat={m.voiceId}
                  content={m.content}
                />
              )}
              {/* Firebrand lightning round (S1): the item this reply
                  presented, rendered from the server's round_item —
                  never from message text. Store path only. */}
              {conversationId && m.messageId && !m.messageId.startsWith('local-') && m.roundItem && 'proposal_id' in m.roundItem && (
                <RoundProposalCard
                  base={base}
                  conversationId={conversationId}
                  messageId={m.messageId}
                  roundItem={m.roundItem}
                />
              )}
              {/* Weaver rapid fire (S1): the impression this reply
                  presented, rendered from the server's round_item —
                  never from message text. Store path only. */}
              {conversationId && m.messageId && !m.messageId.startsWith('local-') && m.roundItem && 'claim_id' in m.roundItem && (
                <WeaverRoundClaimCard
                  base={base}
                  conversationId={conversationId}
                  messageId={m.messageId}
                  roundItem={m.roundItem}
                  messageContent={m.content}
                />
              )}
              {/* Upload rapid fire (S1): the reading this reply
                  presented, rendered from the server's round_item —
                  never from message text. Store path only. */}
              {conversationId && m.messageId && !m.messageId.startsWith('local-') && m.roundItem && 'interpretation_id' in m.roundItem && (
                <UploadRoundCard
                  base={base}
                  conversationId={conversationId}
                  messageId={m.messageId}
                  roundItem={m.roundItem}
                  seatId={m.voiceId}
                  seatNames={names}
                  onNextVoice={(id) => setActiveId(id)}
                />
              )}
              {m.messageId && m.voiceId && (
                <div className="max-w-[88%] w-full">
                  <VoiceFeedback
                    messageId={m.messageId}
                    seat={m.voiceId}
                    conversationId={conversationKey}
                    initialFeedback={feedbackByResponse[m.messageId] ?? null}
                  />
                </div>
              )}
            </div>
          ),
        )}
        {loading && (
          <div className="text-xs text-stone-500">
            {councilMode ? 'asking the council…' : 'thinking…'}
          </div>
        )}
        {signedOut && (
          <div className="text-sm text-stone-400">Please sign in to talk to your voices.</div>
        )}
        <div ref={chatEndRef} />
      </div>

      {(activeId || councilMode) && (
        <div className="rounded-2xl border border-stone-700/60 bg-stone-900/70 p-2 space-y-2">
          <div className="flex gap-2">
            <textarea
              ref={composerRef}
              value={input}
              onChange={(e) => {
                const v = e.target.value
                setComposer(v)
                // Write-through: every keystroke lands under the
                // CURRENT key synchronously. There is no save-on-
                // unmount step (one could overwrite a newer draft).
                if (draftCtx && draftCtx.userId && conversationId) {
                  draftCtx.store.set(
                    {
                      userId: draftCtx.userId,
                      conversationId,
                      seat: councilMode
                        ? COUNCIL_DRAFT_SEAT
                        : (activeId ?? UNSELECTED_DRAFT_SEAT),
                    },
                    v,
                  )
                }
              }}
              onKeyDown={(e) => {
                // Desktop: Enter sends, Shift+Enter inserts a newline.
                // Phone/tablet (coarse pointer): there is no Shift key,
                // so Enter inserts a newline and only Send sends.
                if (e.key === 'Enter' && !e.shiftKey && !isCoarsePointer()) {
                  e.preventDefault()
                  send()
                }
              }}
              placeholder={
                councilMode
                  ? chooseMultiple
                    ? checkedSeatIds.length === 0
                      ? 'Choose seats above…'
                      : 'Ask the checked seats…'
                    : 'Ask the whole council…'
                  : `Talk to ${activeName}…`
              }
              maxLength={2000}
              rows={1}
              aria-label={
                councilMode
                  ? chooseMultiple
                    ? 'Message the checked seats'
                    : 'Message the whole council'
                  : `Message ${activeName}`
              }
              className="flex-1 min-w-0 resize-none overflow-y-auto bg-stone-950 border border-stone-700 rounded-2xl px-4 py-2.5 min-h-[44px] text-sm text-stone-200 outline-none focus:border-amber-500/60"
            />
            <button
              type="button"
              onClick={send}
              disabled={sendDisabled}
              className="shrink-0 self-end min-h-[44px] px-4 rounded-full bg-amber-600 text-amber-50 text-sm font-semibold disabled:opacity-40"
            >
              Send
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
