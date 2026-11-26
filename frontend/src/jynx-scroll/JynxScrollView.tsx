/**
 * Jynx's Scroll — the production surface.
 *
 * The Fox's home is Scene 1 (founder, 2026-11-25: "implement what
 * we built as scene one") — the frozen room at
 * sprites/scroll-rebuild/scene-1/: the room image as ground, the
 * shelf wall tiled from the canonical Penrose deflation
 * (sceneLogic.ts — the same geometry the founder accepted in the
 * composite), and the founder's sheet hanging at the fixture's
 * rect in the middle of the wall. The diamond-lattice case and
 * base bin of the first build are gone; the room IS the shelf.
 *
 * Cubbies: one rhomb cell per top-level item (initiatives and
 * loose items alike — Scene 1 has no bin), assigned
 * deterministically (sceneLogic.assignCubbies). A cubby whose
 * item has nested projects/tasks holds a CLUSTER — the parent's
 * scroll in front, up to three child scrolls tucked behind it
 * (the commission's named rule). Every scroll is the founder's
 * end-on asset, lifted byte-identical (left of the sheet's centre
 * line it faces one way, right of it the mirrored asset — the
 * founder's placement rule); its size is the recorded radius
 * (kind + mass) capped by its cell, and its status stands as a
 * ring band on the end face in the recorded cord colour — a
 * Blocked scroll wears Jynx's violet. NO text stands on any
 * scroll or in the room: no heading, no lettered names, no
 * explanatory copy (the surface rule). Names live in the popup
 * and the chat, never on the parchment.
 *
 * Taps and presses (founder rulings, 2026-11-25):
 *  - TAP a scroll: a small popup stands in the room with the
 *    item's name and a short synopsis composed from recorded
 *    fields only, and the item is staged TENTATIVELY in the chat
 *    through the staged-chip seam — the tap writes nothing
 *    anywhere; tapping elsewhere dismisses both silently.
 *    Tapping the popup's body opens the item on the centre sheet
 *    (the open/unroll path below, walked through its parents so
 *    the back step lands where it came from).
 *  - LONG-PRESS a scroll with children: the WORKTABLE screen —
 *    its children standing end-on along the table, each with its
 *    own cluster; the same tap/popup rules; a back chevron (no
 *    prose) returns to the room. Long-press on a leaf opens it
 *    on the sheet directly.
 *
 * The centre sheet is the first build's sheet, unchanged: the
 * founder's scroll ground (assets/scroll-ground.png, byte-
 * identical, rollers and all) rendered into the fixture's rect,
 * its drawings arriving mark by mark in order (rhyme in paint
 * first) — ONCE each: a drawing draws itself when it first
 * appears on its scroll's sheet, and every later presentation
 * shows the finished ink standing (founder, 2026-11-25: signify
 * permanence; don't repaint). The conversation beside the scene
 * belongs to the open scroll and NEVER swaps (founder,
 * 2026-11-25); a tapped drawing becomes that conversation's
 * SUBJECT — the seat explains the metaphor in words, in the same
 * talk — through the same LiveContext seam the Campaign Board
 * uses. Exactly one subject stands staged at a time: a scroll
 * tap stages the scroll, a drawing tap stages the drawing, each
 * silently replacing the other, and both are tentative — they
 * enter the conversation's record only inside a turn the visitor
 * actually sends.
 *
 * The drawing feed is the read side of the [[chalk]] carriage
 * (scrollApi.ts): GET /conversation/drawings serves the caller's
 * drawings oldest first, and the surface renders the open
 * scroll's OWN drawings on its sheet — the feed is keyed to the
 * open scroll's conversation server-side and filtered again on
 * the served provenance client-side, so a drawing from another
 * conversation never stands here (founder, 2026-11-25). With the
 * carriage's server flag off, no drawings are made and the feed
 * is honestly empty — the unrolled scroll stands blank, with no
 * placeholder art and no invented drawings. The feed stays
 * current without polling: it re-reads when a scroll is opened
 * or stepped back to, when a conversation turn lands beside the
 * scroll (CouncilChat's onTurnSent — the carriage parses Jynx's
 * tail server-side during the turn, so a drawing made in that
 * turn is already persisted when the reply lands), and when the
 * window regains focus or visibility. A drawing that arrives
 * while a scroll is open joins its sheet in place — the sheet
 * does not re-unroll under the visitor, and the visitor's place
 * along the sheet is not moved unless they are resting with the
 * newest drawing, in which case the sheet grows with them.
 *
 * The open scroll is ONE continuous sheet, not pages (founder,
 * 2026-11-25): its drawings stand along it in the order they
 * were made, the earlier ones rolled up compact toward the top,
 * fresh blank parchment below the newest as working space for
 * the next drawing. Rolling moves ALONG the sheet: the sheet's
 * rollers (top toward the older drawings, bottom toward the
 * newer) and the screen's Roll back / Roll forward controls move
 * the sheet's focus (scrollLogic.sheetLayout), never swap
 * sheets, and the sheet's content never unmounts. The sheet
 * unrolls only the first time a scroll is opened in this
 * viewing; a presented drawing's ink never repaints.
 *
 * Presented-ness — which drawings have drawn themselves, which
 * scrolls have unrolled — is session state of this mounted
 * surface, keyed by drawing id / scroll key, held in memory only.
 * It survives rolling, selecting, refreshes, and stepping away
 * within the surface; it does not survive the surface unmounting
 * (a page reload, leaving the seat and returning), because
 * presentation is a viewing, not a record — the store records
 * drawings, not who has watched them arrive. After such a return
 * each drawing draws itself once more on its first presentation,
 * exactly as it did the first time.
 *
 * Talk is the existing council conversation, opened with Jynx
 * (maverick). No separate chat engine. Jynx takes they/them in
 * every reference on this surface.
 */
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import CouncilChat from '../chat/CouncilChat'
import SplitShell from '../components/SplitShell'
import { fetchScrollDrawings, fetchScrollEntities, type ScrollEntities } from './scrollApi'
import {
  buildScrollShelf,
  drawingsForConversation,
  drawingDurationMs,
  flattenShelf,
  markProgressAt,
  scrollChildren,
  sheetLayout,
  JYNX_PURPLE,
  type ScrollDrawing,
  type ScrollMark,
  type SheetLayout,
  type ShelfBay,
  type ShelfScroll,
  type StampName,
} from './scrollLogic'
import {
  CLUSTER_SHOWN,
  FRAME_H,
  FRAME_W,
  SHEET_RECT,
  assignCubbies,
  buildPenroseFabric,
  longPressRoute,
  popupSynopsis,
  scrollKey,
  scrollWidthFor,
  tableRows,
  trailForScroll,
  type CubbyAssignment,
  type FabricRhomb,
  type PenroseFabric,
  type TableRow,
} from './sceneLogic'
import scrollFabric from './assets/scroll-fabric.png'
import scrollGround from './assets/scroll-ground.png'
import scrollRoom from './assets/scroll-room.png'
import scrollEnd from './assets/scroll-end.png'
import scrollEndRight from './assets/scroll-end-right.png'
import scrollTable from './assets/scroll-table.png'
import stampArc from './assets/arc.png'
import stampCaret from './assets/caret.png'
import stampCrescent from './assets/crescent.png'
import stampFork from './assets/fork.png'
import stampFrame from './assets/frame.png'
import stampLeaf from './assets/leaf.png'
import stampRing from './assets/ring.png'
import stampSlash from './assets/slash.png'
import stampTriangle from './assets/triangle.png'
import stampWave from './assets/wave.png'

const INK = '#1a1816'
const WOOD_DARK = '#4a3018'
const WOOD_DEEP = '#3c2712'

/** The founder's ground on its own screen: drawn at its own
 *  aspect (1086×1448), never stretched. The parchment interior —
 *  where drawings may land — is the sheet inside its rollers and
 *  torn edges, as fractions of the image. In Scene 1 the sheet
 *  component is rendered into the fixture's rect by the transform
 *  on the room's sheet group (see RoomScene): the ground's own
 *  rect below maps onto SHEET_RECT exactly (384/340 = 512/453). */
const SCREEN_W = 480
const SCREEN_CX = SCREEN_W / 2
const SHEET_TOP = 96
const GROUND_W = 340
const GROUND_H = 453
const INTERIOR = { x: 0.155, y: 0.125, w: 0.7, h: 0.75 }

const UNROLL_MS = 850
const LONG_PRESS_MS = 450

/** The stencil kit, lifted: name → asset + the PNG's own pixel
 *  size (the placement math needs each stamp's true aspect). */
const STAMPS: Record<StampName, { src: string; w: number; h: number }> = {
  arc: { src: stampArc, w: 308, h: 234 },
  caret: { src: stampCaret, w: 279, h: 257 },
  crescent: { src: stampCrescent, w: 265, h: 283 },
  fork: { src: stampFork, w: 302, h: 296 },
  frame: { src: stampFrame, w: 283, h: 282 },
  leaf: { src: stampLeaf, w: 258, h: 291 },
  ring: { src: stampRing, w: 272, h: 274 },
  slash: { src: stampSlash, w: 289, h: 256 },
  triangle: { src: stampTriangle, w: 271, h: 245 },
  wave: { src: stampWave, w: 297, h: 175 },
}

/** A refetched feed is "the same" when it carries the same
 *  drawings in the same order — ids are the drawings' identity.
 *  Returning the previous list untouched keeps the visitor's
 *  place along the sheet, their selection, and every presented
 *  drawing's standing ink exactly where they were. */
function sameDrawings(a: ScrollDrawing[], b: ScrollDrawing[]): boolean {
  return a.length === b.length && a.every((d, i) => d.id === b[i].id)
}

function prefersReducedMotion(): boolean {
  try {
    return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
      : false
  } catch {
    return false
  }
}

interface StagedAnchor {
  /** Anchor point as percentages of the scene frame. */
  xPct: number
  yPct: number
  /** Place the popup below the anchor (anchors near the top). */
  below: boolean
}

export default function JynxScrollView() {
  const [entities, setEntities] = useState<ScrollEntities | null>(null)
  const [drawings, setDrawings] = useState<ScrollDrawing[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  /** The open scroll's trail: shelf → parent → child … The last
   *  entry is the scroll on the centre sheet; the rest are its
   *  ancestors, so the back step always lands on the parent it
   *  came from. */
  const [openTrail, setOpenTrail] = useState<string[]>([])
  /** The visitor's chosen place along the open sheet, as a band
   *  index — or null, resting with the newest drawing (the sheet
   *  grows under a resting visitor; an explicit place is held). */
  const [focusOverride, setFocusOverride] = useState<number | null>(null)
  const [selectedDrawingId, setSelectedDrawingId] = useState<string | null>(null)
  /** The tentatively staged scroll (a tap): its key, resolved
   *  against the current shelf, and where its popup stands. The
   *  staging is client-side state alone — nothing is written by
   *  a tap, and it leaves this surface only inside a turn the
   *  visitor actually sends. */
  const [stagedKey, setStagedKey] = useState<string | null>(null)
  const [stagedAnchor, setStagedAnchor] = useState<StagedAnchor | null>(null)
  /** The scroll whose children stand on the worktable, by key —
   *  or null, standing in the room. */
  const [tableKey, setTableKey] = useState<string | null>(null)
  /** The surface's clock, in epoch ms, ticking while a scroll is
   *  open. Presentation is computed from it — which drawings are
   *  mid-arrival — never stored as per-drawing state. */
  const [now, setNow] = useState(() => Date.now())
  /** Session presented-ness (see the header): the drawings that
   *  have drawn themselves in this viewing. Their ink stands
   *  finished from then on — no repaint, ever. */
  const [presented, setPresented] = useState<ReadonlySet<string>>(() => new Set())
  /** When each unpresented drawing's one draw-out began (or will
   *  begin — a drawing first seen while its sheet still unrolls
   *  starts as the unroll completes). */
  const drawStartRef = useRef<Map<string, number>>(new Map())
  /** The scrolls that have unrolled in this viewing; a scroll
   *  unrolls once, then stands open. */
  const unrolledRef = useRef<Set<string>>(new Set())
  /** When the currently open scroll began unrolling (meaningful
   *  only while it is not yet in unrolledRef), and which scroll
   *  that start belongs to. */
  const openSinceRef = useRef(0)
  const openSinceKeyRef = useRef<string | null>(null)

  const load = useCallback(async () => {
    try {
      const ents = await fetchScrollEntities()
      setEntities(ents)
      setLoadError(null)
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : 'Could not load your scrolls.')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  /** Re-read ONLY the drawing feed (see the header: the triggers),
   *  keyed to the open scroll's conversation — the feed is that
   *  conversation's drawings, read through the endpoint's filter.
   *  An unchanged feed keeps the previous list object, so nothing
   *  re-renders and the visitor's place is untouched; a grown feed
   *  swaps the list in place — the visitor's place along the sheet
   *  is separate state, so they stay where they were looking and
   *  the new drawing takes its place at the sheet's end. A failed
   *  re-read keeps the drawings already on the surface: the error
   *  screen belongs to the first load alone, and a refresh must
   *  never blank a scroll that loaded fine. On the shelf there is
   *  no sheet and nothing to re-read. */
  const refreshDrawings = useCallback(async (conversationId: string | null) => {
    if (!conversationId) return
    try {
      const draws = await fetchScrollDrawings(conversationId)
      setDrawings((prev) => (sameDrawings(prev, draws) ? prev : draws))
    } catch {
      /* keep what the surface already holds */
    }
  }, [])
  // The conversation the feed is keyed to, mirrored into a ref so
  // the standing triggers (focus, visibility, a landed turn) read
  // the current key without re-binding.
  const feedKeyRef = useRef<string | null>(null)

  // The window waking is a refresh trigger too: Jynx may have
  // drawn in another tab, or on the phone while this pane sat
  // open. No polling — focus and visibility changes only.
  useEffect(() => {
    const onFocus = () => {
      void refreshDrawings(feedKeyRef.current)
    }
    const onVisibility = () => {
      if (document.visibilityState === 'visible') void refreshDrawings(feedKeyRef.current)
    }
    window.addEventListener('focus', onFocus)
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      window.removeEventListener('focus', onFocus)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [refreshDrawings])

  const shelf = useMemo(
    () =>
      entities
        ? buildScrollShelf(entities.initiatives, entities.projects, entities.tasks, entities.ideas)
        : [],
    [entities],
  )
  const allScrolls = useMemo(() => flattenShelf(shelf), [shelf])
  const fabric = useMemo(() => buildPenroseFabric(), [])
  const assignments = useMemo(
    () => (entities ? assignCubbies(shelf, fabric.rhombs) : []),
    [entities, shelf, fabric],
  )
  const byKey = useCallback(
    (key: string | null) =>
      key ? (allScrolls.find((s) => scrollKey(s) === key) ?? null) : null,
    [allScrolls],
  )
  const openKey = openTrail[openTrail.length - 1] ?? null
  const open = byKey(openKey)
  const openChildren = useMemo(
    () => (open ? scrollChildren(shelf, open) : []),
    [shelf, open],
  )
  const staged = byKey(stagedKey)
  const tableParent = byKey(tableKey)
  const tableRowList = useMemo(
    () => (tableParent ? tableRows(shelf, tableParent) : []),
    [shelf, tableParent],
  )

  /* --------------------------- chat wiring --------------------------- */

  // The conversation beside the scroll belongs to the open scroll
  // and NOTHING in the world pane changes it (founder, 2026-11-25):
  // not rolling, not selecting a drawing, not a drawing arriving.
  // A staged subject changes the conversation's SUBJECT (below),
  // never its identity.
  const conversationId = open ? `jynx-scroll:${open.kind}:${open.id}` : 'jynx-scroll:shelf'

  // The open scroll's own drawings: the feed is keyed to this
  // conversation server-side, and the served provenance is
  // filtered again here, so a drawing born anywhere else — another
  // scroll's conversation, the shelf's, a per-drawing conversation
  // of the old wiring — never stands on this sheet.
  const sheetDrawings = useMemo(
    () => (open ? drawingsForConversation(drawings, conversationId) : []),
    [drawings, open, conversationId],
  )
  const selectedDrawing = useMemo(
    () => sheetDrawings.find((d) => d.id === selectedDrawingId) ?? null,
    [sheetDrawings, selectedDrawingId],
  )

  // The sheet's layout: one continuous sheet, its focus resting
  // with the newest drawing unless the visitor has rolled to a
  // place of their own. Rolling never touches the conversation,
  // the selection, or the sheet's membership — only this layout.
  const layout = useMemo(() => {
    const resting = Math.max(0, sheetDrawings.length - 1)
    return sheetLayout(sheetDrawings, focusOverride ?? resting)
  }, [sheetDrawings, focusOverride])

  // One staged subject at a time: a drawing first (it is the
  // sheet's own tap), then a staged scroll, then the open scroll.
  const chatContext: Record<string, unknown> = selectedDrawing
    ? { sheet_type: 'jynx_scroll', entity_type: 'drawing', entity_id: selectedDrawing.id }
    : staged
      ? { sheet_type: 'jynx_scroll', entity_type: staged.kind, entity_id: staged.id }
      : open
        ? { sheet_type: 'jynx_scroll', entity_type: open.kind, entity_id: open.id }
        : { sheet_type: 'jynx_scroll' }

  const stagedLabel = selectedDrawing
    ? (selectedDrawing.title ?? 'a drawing')
    : staged
      ? staged.title
      : null

  /** Setting the staged subject down — from the chat's chip, or
   *  by tapping elsewhere — discards whichever staging stands,
   *  silently. Nothing was written; nothing is unwritten. */
  const clearStaging = useCallback(() => {
    setSelectedDrawingId(null)
    setStagedKey(null)
    setStagedAnchor(null)
  }, [])

  // Opening a scroll (or stepping back to one) re-reads its feed,
  // and the feed key follows the open conversation. Stepping back
  // to the shelf clears the key: no sheet, no feed.
  useEffect(() => {
    feedKeyRef.current = open ? conversationId : null
    if (open) void refreshDrawings(conversationId)
  }, [open, conversationId, refreshDrawings])

  // The surface's clock ticks while a scroll is open; presentation
  // (the unroll, a drawing's one draw-out) is computed from it.
  useEffect(() => {
    if (!openKey) return
    setNow(Date.now())
    const timer = setInterval(() => setNow(Date.now()), 50)
    return () => clearInterval(timer)
  }, [openKey])

  // A scroll unrolls once per viewing: opening one that has not
  // unrolled yet starts its unroll now; one that has stands open.
  useEffect(() => {
    if (!openKey || unrolledRef.current.has(openKey)) return
    if (prefersReducedMotion()) {
      unrolledRef.current.add(openKey)
      return
    }
    if (openSinceKeyRef.current !== openKey) {
      openSinceKeyRef.current = openKey
      openSinceRef.current = Date.now()
    }
  }, [openKey, now])

  const unroll = !openKey
    ? 1
    : unrolledRef.current.has(openKey)
      ? 1
      : Math.min(1, Math.max(0, (now - openSinceRef.current) / UNROLL_MS))

  // Presentation bookkeeping: a drawing first seen on the open
  // sheet begins its one draw-out (as its sheet's unroll completes,
  // if the sheet is still unrolling); when the draw-out has run
  // its course the drawing is presented, and its ink stands
  // finished from then on. Reduced motion presents at once.
  useEffect(() => {
    if (!openKey) return
    const reduced = prefersReducedMotion()
    const unrollEndsAt = unrolledRef.current.has(openKey)
      ? 0
      : openSinceRef.current + UNROLL_MS
    let changed = false
    const next = new Set(presented)
    for (const d of sheetDrawings) {
      if (next.has(d.id)) continue
      if (reduced) {
        next.add(d.id)
        changed = true
        continue
      }
      let start = drawStartRef.current.get(d.id)
      if (start === undefined) {
        start = Math.max(Date.now(), unrollEndsAt)
        drawStartRef.current.set(d.id, start)
      }
      if (now - start >= drawingDurationMs(d)) {
        next.add(d.id)
        drawStartRef.current.delete(d.id)
        changed = true
      }
    }
    if (changed) setPresented(next)
    // The unroll completes into the record of this viewing.
    if (
      !unrolledRef.current.has(openKey) &&
      (reduced || now - openSinceRef.current >= UNROLL_MS)
    ) {
      unrolledRef.current.add(openKey)
    }
  }, [openKey, sheetDrawings, now, presented])

  /** How far one drawing's draw-out has run, in ms — the finished
   *  ink for a presented drawing, nothing yet for one whose start
   *  is still ahead (its sheet still unrolling). */
  const progressFor = useCallback(
    (drawing: ScrollDrawing): number => {
      if (presented.has(drawing.id)) return Number.MAX_SAFE_INTEGER
      const start = drawStartRef.current.get(drawing.id)
      if (start === undefined) return 0
      return Math.max(0, now - start)
    },
    [presented, now],
  )

  /* ------------------------- taps and presses ------------------------ */

  /** Opening a scroll on the centre sheet, walked through its
   *  parents: the trail deepens from the shelf, so the back step
   *  returns through the parent it came from. The place along
   *  the new sheet starts at rest, no drawing is the subject, and
   *  any staging is spent. */
  const openOnSheet = useCallback(
    (scroll: ShelfScroll) => {
      setOpenTrail(trailForScroll(shelf, scroll))
      setFocusOverride(null)
      setSelectedDrawingId(null)
      setStagedKey(null)
      setStagedAnchor(null)
      setTableKey(null)
    },
    [shelf],
  )

  /** A tap on a scroll: its popup stands at the tap's anchor and
   *  the scroll is staged tentatively in the chat. Nothing is
   *  written — the tap's whole effect is this state. A staged
   *  drawing is replaced silently (one staged subject at a time). */
  const tapScroll = useCallback((scroll: ShelfScroll, anchor: StagedAnchor) => {
    setSelectedDrawingId(null)
    setStagedKey(scrollKey(scroll))
    setStagedAnchor(anchor)
  }, [])

  /** A long-press: a scroll with children opens the worktable
   *  standing them; a leaf opens on the sheet directly. */
  const longPressScroll = useCallback(
    (scroll: ShelfScroll) => {
      if (longPressRoute(shelf, scroll) === 'table') {
        setStagedKey(null)
        setStagedAnchor(null)
        setTableKey(scrollKey(scroll))
      } else {
        openOnSheet(scroll)
      }
    },
    [shelf, openOnSheet],
  )

  /** One step back: from the table to the room; in the room, to
   *  the parent scroll, or to the shelf. */
  const goBack = useCallback(() => {
    if (tableKey) {
      setTableKey(null)
      setStagedKey(null)
      setStagedAnchor(null)
      return
    }
    setOpenTrail((trail) => trail.slice(0, -1))
    setFocusOverride(null)
    setSelectedDrawingId(null)
  }, [tableKey])

  /** Opening a child from the open scroll's screen: the trail
   *  deepens, so the back step returns to this parent. */
  const openChild = useCallback((scroll: ShelfScroll) => {
    setOpenTrail((trail) => [...trail, scrollKey(scroll)])
    setFocusOverride(null)
    setSelectedDrawingId(null)
    setStagedKey(null)
    setStagedAnchor(null)
  }, [])

  /** A turn just landed in the conversation beside the scroll.
   *  CouncilChat fires onTurnSent on its success arms only, after
   *  the reply lands — and the carriage persists a turn's drawings
   *  server-side before that reply is served, so a drawing Jynx
   *  made in this turn is already in the feed. Re-read it: this
   *  is the trigger that lands a fresh drawing on a pane that was
   *  open while Jynx drew. */
  const onTurnLanded = useCallback(() => {
    void refreshDrawings(feedKeyRef.current)
  }, [refreshDrawings])

  /** Rolling along the sheet: the focus steps one band toward the
   *  older (delta < 0) or the newer (delta > 0), clamped to the
   *  sheet — its oldest drawing at one end, the blank working
   *  space at the other. The conversation, the selection, and the
   *  sheet's membership are untouched. */
  const rollBy = useCallback(
    (delta: number) => {
      setFocusOverride(
        Math.min(Math.max(0, layout.focus + delta), sheetDrawings.length),
      )
    },
    [layout.focus, sheetDrawings.length],
  )

  /** Tapping a drawing STAGES it as the conversation's subject —
   *  tentatively (founder, 2026-11-25): the tap writes nothing
   *  anywhere. The selection is client-side state alone; the
   *  staged context leaves this surface only inside a turn the
   *  visitor actually sends (CouncilChat carries context in the
   *  turn POST, and in nothing else), and that sent message's
   *  per-message context snapshot is the commit point — the only
   *  moment the drawing enters the conversation's record.
   *  Clicking another drawing replaces the staged subject
   *  silently; tapping the subject again, or the bare sheet,
   *  discards it silently — clicking around never buries the
   *  chat. Staging a drawing sets any staged scroll down (one
   *  staged subject at a time). The talk itself does not move. */
  const handleSelectDrawing = useCallback(
    (drawing: ScrollDrawing | null) => {
      setStagedKey(null)
      setStagedAnchor(null)
      setSelectedDrawingId((prev) =>
        drawing === null || drawing.id === prev ? null : drawing.id,
      )
    },
    [],
  )

  /* ------------------------------ render ----------------------------- */

  if (loadError) {
    return (
      <div className="flex-1 p-6">
        <p className="text-sm text-red-300">{loadError}</p>
        <button
          type="button"
          onClick={() => void load()}
          className="mt-3 min-h-[44px] px-4 rounded-full bg-amber-600 text-amber-50 text-sm font-semibold"
        >
          Try again
        </button>
      </div>
    )
  }
  if (!entities) {
    return (
      <div className="flex-1 p-6">
        <p className="text-sm text-stone-400">Setting out the scrolls…</p>
      </div>
    )
  }

  const drawingCount = layout.bands.length - 1
  const showBack = tableParent !== null || open !== null

  return (
    <SplitShell
      storageKey="jynx-scroll"
      left={
        <div className="p-3 lg:p-5 space-y-3">
          <div className="relative">
            {showBack ? (
              <button
                type="button"
                data-testid="scene-back"
                aria-label="Back"
                onClick={goBack}
                className="absolute left-2 top-2 z-20 flex h-10 w-10 items-center justify-center rounded-full border border-[#b09a6d]/70 bg-[#f7efdb]/90 text-xl leading-none text-[#3a2c1c] shadow"
              >
                ‹
              </button>
            ) : null}
            {tableParent ? (
              <TableScene
                parent={tableParent}
                rows={tableRowList}
                onTapScroll={tapScroll}
                onLongPressScroll={longPressScroll}
                onDismiss={clearStaging}
              />
            ) : (
              <RoomScene
                fabric={fabric}
                assignments={assignments}
                open={open}
                layout={layout}
                unroll={unroll}
                progressFor={progressFor}
                selectedDrawingId={selectedDrawingId}
                onSelectDrawing={handleSelectDrawing}
                onRoll={rollBy}
                onTapScroll={tapScroll}
                onLongPressScroll={longPressScroll}
                onDismiss={clearStaging}
              />
            )}
            {staged && stagedAnchor ? (
              <div
                data-testid="scroll-popup"
                role="button"
                tabIndex={0}
                aria-label={`Open ${staged.title} on the sheet`}
                className="absolute z-10 w-60 max-w-[80%] cursor-pointer rounded-xl border border-[#b09a6d] bg-[#f7efdb] p-3 shadow-xl"
                style={{
                  left: `${stagedAnchor.xPct}%`,
                  top: `${stagedAnchor.yPct}%`,
                  transform: stagedAnchor.below
                    ? 'translate(-50%, 18px)'
                    : 'translate(-50%, calc(-100% - 18px))',
                }}
                onClick={() => openOnSheet(staged)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    openOnSheet(staged)
                  }
                }}
              >
                <p className="text-sm font-semibold text-[#3a2c1c]">{staged.title}</p>
                {popupSynopsis(shelf, staged).map((line) => (
                  <p key={line} className="mt-0.5 text-xs text-[#6b5636]">
                    {line}
                  </p>
                ))}
              </div>
            ) : null}
          </div>

          {/* roll controls — the sheet rolls from the screen's
              chrome, never as marks on the scroll itself. There
              are no page dots: the sheet is one sheet, and its
              place along it is the rolled history standing at the
              top, not a position in a stack of pages. */}
          {!tableParent && open && drawingCount >= 1 ? (
            <div data-testid="sheet-controls" className="flex items-center justify-center gap-3">
              <button
                type="button"
                data-testid="sheet-back"
                disabled={layout.focus === 0}
                onClick={() => rollBy(-1)}
                className="min-h-[40px] px-4 rounded-full border border-stone-600 text-sm text-amber-100/90 disabled:opacity-40"
              >
                ‹ Roll back
              </button>
              <button
                type="button"
                data-testid="sheet-forward"
                disabled={layout.focus >= drawingCount}
                onClick={() => rollBy(1)}
                className="min-h-[40px] px-4 rounded-full border border-stone-600 text-sm text-amber-100/90 disabled:opacity-40"
              >
                Roll forward ›
              </button>
            </div>
          ) : null}

          {/* the open scroll's children — scrolls of their own,
              standing beneath the room (never on the parchment) */}
          {!tableParent && open && openChildren.length > 0 ? (
            <div className="flex flex-wrap gap-2" data-testid="scroll-children">
              {openChildren.map((child) => (
                <button
                  key={scrollKey(child)}
                  type="button"
                  data-child-scroll={scrollKey(child)}
                  onClick={() => openChild(child)}
                  className="min-h-[44px] px-4 rounded-full bg-[#efe6cc] text-[#3a2c1c] border border-[#b09a6d] text-sm font-medium shadow-sm"
                >
                  <span className="mr-2 text-[0.65rem] uppercase tracking-[0.14em] opacity-70">
                    {child.kind}
                  </span>
                  {child.title}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      }
      right={
        <div className="p-3">
          <div className="rounded-2xl border border-stone-700/60 bg-stone-900/70 p-2">
            <CouncilChat
              key={conversationId}
              environment="workspace"
              initialArchetypeId="maverick"
              conversationId={conversationId}
              context={chatContext}
              onTurnSent={onTurnLanded}
              stagedLabel={stagedLabel}
              onStagedClear={clearStaging}
            />
          </div>
        </div>
      }
    />
  )
}

/* ================================================================== */
/* Scene 1 — the room                                                  */
/* ================================================================== */

/** The sheet group's transform: the sheet component's own ground
 *  rect (SCREEN_CX − GROUND_W/2, SHEET_TOP, GROUND_W × GROUND_H)
 *  mapped onto the fixture's sheet rect. */
const SHEET_TRANSFORM =
  `translate(${SHEET_RECT.x} ${SHEET_RECT.y}) ` +
  `scale(${SHEET_RECT.w / GROUND_W}) ` +
  `translate(${-(SCREEN_CX - GROUND_W / 2)} ${-SHEET_TOP})`

function RoomScene({
  fabric,
  assignments,
  open,
  layout,
  unroll,
  progressFor,
  selectedDrawingId,
  onSelectDrawing,
  onRoll,
  onTapScroll,
  onLongPressScroll,
  onDismiss,
}: {
  fabric: PenroseFabric
  assignments: CubbyAssignment[]
  open: ShelfScroll | null
  layout: SheetLayout
  unroll: number
  progressFor: (drawing: ScrollDrawing) => number
  selectedDrawingId: string | null
  onSelectDrawing: (drawing: ScrollDrawing | null) => void
  onRoll: (delta: number) => void
  onTapScroll: (scroll: ShelfScroll, anchor: StagedAnchor) => void
  onLongPressScroll: (scroll: ShelfScroll) => void
  onDismiss: () => void
}) {
  const drawingCount = layout.bands.length - 1
  const focus = layout.focus
  return (
    <section aria-label="Jynx — the Scroll, Scene 1">
      <div className="rounded-2xl overflow-hidden border border-[#4a3018]/70 shadow-lg">
        <svg
          viewBox={`0 0 ${FRAME_W} ${FRAME_H}`}
          className="w-full block"
          role="img"
          aria-label="A sunlit room: a wall of Penrose-tiled shelves holding rolled scrolls, the great scroll hanging at its centre"
        >
          <defs>
            <clipPath id="jynx-fabric-clip">
              <path
                d={
                  `M 105 262 H 1400 V 852 H 105 Z ` +
                  `M 518 366 H 950 V 862 H 518 Z`
                }
                clipRule="evenodd"
              />
            </clipPath>
            <clipPath id="jynx-table-occlusion">
              <rect x={520} y={795} width={425} height={105} />
            </clipPath>
          </defs>
          <image href={scrollRoom} x={0} y={0} width={FRAME_W} height={FRAME_H} />
          {/* tapping the room's bare ground sets the staging down */}
          <rect
            data-testid="scene-background"
            x={0}
            y={0}
            width={FRAME_W}
            height={FRAME_H}
            fill="#ffffff"
            fillOpacity={0}
            onClick={onDismiss}
          />
          {/* the shelf fabric — the frozen builder's own raster
              (assets/scroll-fabric.png, generated from
              build_composite_v4.py's fabric code and verified
              against the frozen composite): the depth reveals and
              the founder's hollow wooden frames over the room's
              plaster, as ONE image. Per-rhomb drawing of any kind
              is a substitution — see sceneLogic's header. */}
          <g clipPath="url(#jynx-fabric-clip)" onClick={onDismiss}>
            <image
              data-testid="scene-fabric"
              href={scrollFabric}
              x={0}
              y={0}
              width={FRAME_W}
              height={FRAME_H}
            />
          </g>
          {/* the cubbies — one per top-level item, clusters within;
              clipped to the wall so no scroll ever spills onto the
              room's floor or across the sheet */}
          <g clipPath="url(#jynx-fabric-clip)">
            {assignments.map((a) => (
              <Cubby
                key={scrollKey(a.unit.head)}
                assignment={a}
                onTapScroll={onTapScroll}
                onLongPressScroll={onLongPressScroll}
              />
            ))}
          </g>
          {/* the centre sheet — the founder's ground standing
              blank, or the open scroll's sheet in its place */}
          {open ? (
            <g transform={SHEET_TRANSFORM}>
              <OpenScroll
                scroll={open}
                layout={layout}
                unroll={unroll}
                progressFor={progressFor}
                selectedDrawingId={selectedDrawingId}
                onSelectDrawing={onSelectDrawing}
              />
              {drawingCount >= 1 ? (
                <>
                  <RollerControl
                    testId="roller-back"
                    label="Roll toward the older drawings"
                    disabled={focus === 0}
                    x={SCREEN_CX - GROUND_W / 2 - 14}
                    y={SHEET_TOP}
                    width={GROUND_W + 28}
                    height={54}
                    onRoll={() => onRoll(-1)}
                  />
                  <RollerControl
                    testId="roller-forward"
                    label="Roll toward the newer drawings"
                    disabled={focus >= drawingCount}
                    x={SCREEN_CX - GROUND_W / 2 - 14}
                    y={SHEET_TOP + GROUND_H - 54}
                    width={GROUND_W + 28}
                    height={54}
                    onRoll={() => onRoll(1)}
                  />
                </>
              ) : null}
            </g>
          ) : (
            <image
              href={scrollGround}
              x={SHEET_RECT.x}
              y={SHEET_RECT.y}
              width={SHEET_RECT.w}
              height={SHEET_RECT.h}
              onClick={onDismiss}
            />
          )}
          {/* the room's low table stands over the sheet's foot,
              exactly as the frozen composite composes it */}
          <g clipPath="url(#jynx-table-occlusion)">
            <image href={scrollRoom} x={0} y={0} width={FRAME_W} height={FRAME_H} />
          </g>
        </svg>
      </div>
    </section>
  )
}



/** A cubby: the head scroll at full cell size in front, its
 *  cluster tucked behind/below it inside the same cell. */
function Cubby({
  assignment,
  onTapScroll,
  onLongPressScroll,
}: {
  assignment: CubbyAssignment
  onTapScroll: (scroll: ShelfScroll, anchor: StagedAnchor) => void
  onLongPressScroll: (scroll: ShelfScroll) => void
}) {
  const { unit, cell, side } = assignment
  const w = scrollWidthFor(unit.head, cell)
  const childW = w * 0.5
  const offsets = [
    { dx: -0.26 * w, dy: 0.16 * w },
    { dx: 0.26 * w, dy: 0.18 * w },
    { dx: 0, dy: 0.3 * w },
  ]
  const shown = unit.cluster.slice(0, CLUSTER_SHOWN)
  return (
    <g data-cubby={scrollKey(unit.head)}>
      {shown.map((child, i) => (
        <SceneScroll
          key={scrollKey(child)}
          scroll={child}
          cx={cell.centre.x + offsets[i].dx}
          cy={cell.centre.y + offsets[i].dy}
          width={childW}
          side={side}
          cluster
          onTapScroll={onTapScroll}
          onLongPressScroll={onLongPressScroll}
        />
      ))}
      <SceneScroll
        scroll={unit.head}
        cx={cell.centre.x}
        cy={cell.centre.y}
        width={w}
        side={side}
        onTapScroll={onTapScroll}
        onLongPressScroll={onLongPressScroll}
      />
    </g>
  )
}

/* ================================================================== */
/* The worktable — a long-press away                                   */
/* ================================================================== */

/** The table screen: the long-pressed scroll's children standing
 *  end-on along the worktable (the founder's table scene), each
 *  with its own cluster tucked behind it. The flip follows the
 *  table half, as the room's flip follows the sheet. */
function TableScene({
  parent,
  rows,
  onTapScroll,
  onLongPressScroll,
  onDismiss,
}: {
  parent: ShelfScroll
  rows: TableRow[]
  onTapScroll: (scroll: ShelfScroll, anchor: StagedAnchor) => void
  onLongPressScroll: (scroll: ShelfScroll) => void
  onDismiss: () => void
}) {
  const n = rows.length
  const y = 505
  const xFor = (i: number) => (n <= 1 ? FRAME_W / 2 : 250 + (i * (FRAME_W - 500)) / (n - 1))
  return (
    <section aria-label={`The worktable of ${parent.title}`}>
      <div className="rounded-2xl overflow-hidden border border-[#4a3018]/70 shadow-lg">
        <svg
          viewBox={`0 0 ${FRAME_W} ${FRAME_H}`}
          className="w-full block"
          role="img"
          aria-label="A worktable in the sunlit room, scrolls standing along it"
          data-testid="worktable"
        >
          <image href={scrollTable} x={0} y={0} width={FRAME_W} height={FRAME_H} />
          <rect
            data-testid="table-background"
            x={0}
            y={0}
            width={FRAME_W}
            height={FRAME_H}
            fill="#ffffff"
            fillOpacity={0}
            onClick={onDismiss}
          />
          {rows.map((row, i) => {
            const cx = xFor(i)
            const side = cx < FRAME_W / 2 ? ('left' as const) : ('right' as const)
            const w = 185
            const childW = w * 0.55
            const offsets = [
              { dx: -0.34 * w, dy: 26 },
              { dx: 0.34 * w, dy: 30 },
              { dx: 0, dy: 48 },
            ]
            return (
              <g key={scrollKey(row.scroll)} data-table-row={scrollKey(row.scroll)}>
                {row.cluster.map((child, j) => (
                  <SceneScroll
                    key={scrollKey(child)}
                    scroll={child}
                    cx={cx + offsets[j].dx}
                    cy={y - 44 + offsets[j].dy}
                    width={childW}
                    side={side}
                    cluster
                    onTapScroll={onTapScroll}
                    onLongPressScroll={onLongPressScroll}
                  />
                ))}
                <SceneScroll
                  scroll={row.scroll}
                  cx={cx}
                  cy={y}
                  width={w}
                  side={side}
                  onTapScroll={onTapScroll}
                  onLongPressScroll={onLongPressScroll}
                />
              </g>
            )
          })}
        </svg>
      </div>
    </section>
  )
}

/* ================================================================== */
/* One end-on scroll, wherever it stands                               */
/* ================================================================== */

/** The founder's end-on scroll asset (709×699): the end disc's
 *  centre sits at (0.337, 0.342) of the image with radius 0.326
 *  of its width (measured from the asset's dark wood), mirrored
 *  for the right asset. The status ring band stands just inside
 *  the disc's rim in the recorded cord colour. */
const END_FACE = { fx: 0.337, fy: 0.342, r: 0.3 }

function SceneScroll({
  scroll,
  cx,
  cy,
  width,
  side,
  cluster = false,
  onTapScroll,
  onLongPressScroll,
}: {
  scroll: ShelfScroll
  cx: number
  cy: number
  width: number
  side: 'left' | 'right'
  cluster?: boolean
  onTapScroll: (scroll: ShelfScroll, anchor: StagedAnchor) => void
  onLongPressScroll: (scroll: ShelfScroll) => void
}) {
  const [pressing, setPressing] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const firedRef = useRef(false)
  const h = (width * 699) / 709
  const ringCx = (side === 'left' ? END_FACE.fx - 0.5 : 0.5 - END_FACE.fx) * width
  const ringCy = (END_FACE.fy - 0.5) * h

  const clearTimer = () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }
  useEffect(() => clearTimer, [])

  const anchorFor = (): StagedAnchor => ({
    xPct: (cx / FRAME_W) * 100,
    yPct: (cy / FRAME_H) * 100,
    below: cy < 300,
  })

  return (
    <g
      data-scroll={scrollKey(scroll)}
      data-cluster={cluster ? 'true' : undefined}
      transform={`translate(${cx} ${cy}) scale(${pressing ? 0.93 : 1})`}
    >
      <image
        href={side === 'left' ? scrollEnd : scrollEndRight}
        x={-width / 2}
        y={-h / 2}
        width={width}
        height={h}
      />
      {/* the status ring band on the end face — colour from
          recorded status only, through the cord rule */}
      <circle
        data-status-ring={scroll.appearance.cord}
        cx={ringCx}
        cy={ringCy}
        r={END_FACE.r * width}
        fill="none"
        stroke={scroll.appearance.cord}
        strokeWidth={Math.max(1.6, width * 0.04)}
      />
      {/* tap / long-press target */}
      <rect
        x={-width / 2 - 5}
        y={-h / 2 - 5}
        width={width + 10}
        height={h + 10}
        fill="#ffffff"
        fillOpacity={0}
        style={{ cursor: 'pointer' }}
        onPointerDown={() => {
          firedRef.current = false
          setPressing(true)
          clearTimer()
          timerRef.current = setTimeout(() => {
            firedRef.current = true
            setPressing(false)
            onLongPressScroll(scroll)
          }, LONG_PRESS_MS)
        }}
        onPointerUp={() => {
          clearTimer()
          setPressing(false)
        }}
        onPointerLeave={() => {
          clearTimer()
          setPressing(false)
        }}
        onClick={(e) => {
          e.stopPropagation()
          if (firedRef.current) {
            firedRef.current = false
            return
          }
          onTapScroll(scroll, anchorFor())
        }}
      />
    </g>
  )
}

/* ================================================================== */
/* The open scroll — the sheet itself, drawings only, no text          */
/* ================================================================== */

function OpenScroll({
  scroll,
  layout,
  unroll,
  progressFor,
  selectedDrawingId,
  onSelectDrawing,
}: {
  scroll: ShelfScroll
  layout: SheetLayout
  unroll: number
  progressFor: (drawing: ScrollDrawing) => number
  selectedDrawingId: string | null
  onSelectDrawing: (drawing: ScrollDrawing | null) => void
}) {
  const imgX = SCREEN_CX - GROUND_W / 2
  const interiorX = imgX + INTERIOR.x * GROUND_W
  const interiorY = SHEET_TOP + INTERIOR.y * GROUND_H
  const interiorW = INTERIOR.w * GROUND_W
  const interiorH = INTERIOR.h * GROUND_H

  return (
    <g
      data-open-scroll={`${scroll.kind}:${scroll.id}`}
      data-sheet=""
      data-sheet-focus={layout.focus}
      data-sheet-offset={layout.focusOffset}
    >
      <defs>
        <clipPath id="jynx-unroll-clip">
          <rect
            x={imgX - 8}
            y={SHEET_TOP - 6}
            width={GROUND_W + 16}
            height={(GROUND_H + 12) * unroll}
          />
        </clipPath>
        <clipPath id="jynx-sheet-clip">
          <rect x={interiorX} y={interiorY} width={interiorW} height={interiorH} />
        </clipPath>
      </defs>
      <g clipPath="url(#jynx-unroll-clip)">
        {/* the founder's ground — the scroll itself. NO text is
            rendered on the sheet: drawings only. */}
        <image href={scrollGround} x={imgX} y={SHEET_TOP} width={GROUND_W} height={GROUND_H} />
        <g clipPath="url(#jynx-sheet-clip)">
          {/* the sheet's own ground: tapping bare parchment
              returns the talk to the scroll itself */}
          <rect
            x={interiorX}
            y={interiorY}
            width={interiorW}
            height={interiorH}
            fill="#ffffff"
            fillOpacity={0}
            onClick={() => onSelectDrawing(null)}
          />
          {/* the one continuous sheet: every band stands mounted
              for as long as the scroll is open — rolling changes
              the layout (which bands stand compact, where each
              stands), never which drawings exist here. A band's
              drawing fits its own space inside the band; bands
              rolled up at the top stand small, the working bands
              full, and the blank band after the newest drawing
              carries nothing at all. */}
          {layout.bands.map((band) => {
            const drawing = band.drawing
            if (!drawing) return null
            // Fit the drawing's own space inside its band.
            const fit = Math.min(interiorW / drawing.space.w, band.height / drawing.space.h)
            const drawnW = drawing.space.w * fit
            const drawnH = drawing.space.h * fit
            const fitX = interiorX + (interiorW - drawnW) / 2
            const fitY = interiorY + band.y + (band.height - drawnH) / 2
            const drawElapsed = progressFor(drawing)
            return (
              <Fragment key={drawing.id}>
                <g
                  data-drawing-id={drawing.id}
                  data-sheet-band={band.index}
                  transform={`translate(${fitX} ${fitY}) scale(${fit})`}
                >
                  {drawing.marks.map((mark, i) => (
                    <DrawingMark
                      key={i}
                      mark={mark}
                      progress={markProgressAt(drawElapsed, drawing, i)}
                    />
                  ))}
                </g>
                {/* the band's tap surface: tapping the picture
                    makes it the conversation's subject — the
                    dashed border is that subjecthood's only sign */}
                <rect
                  data-drawing-hit={drawing.id}
                  x={interiorX}
                  y={interiorY + band.y}
                  width={interiorW}
                  height={band.height}
                  fill="#ffffff"
                  fillOpacity={0}
                  stroke={selectedDrawingId === drawing.id ? JYNX_PURPLE : 'none'}
                  strokeWidth={1.6}
                  strokeDasharray="5 4"
                  style={{ cursor: 'pointer' }}
                  onClick={() => onSelectDrawing(drawing)}
                />
              </Fragment>
            )
          })}
        </g>
      </g>
      {/* the travelling roller band at the unroll's edge */}
      {unroll < 1 ? (
        <rect
          x={imgX - 12}
          y={SHEET_TOP - 6 + (GROUND_H + 12) * unroll - 6}
          width={GROUND_W + 24}
          height={10}
          rx={5}
          fill={WOOD_DARK}
          stroke={WOOD_DEEP}
          strokeWidth={1}
        />
      ) : null}
    </g>
  )
}

/** One of the sheet's rollers as a sheet-movement control: an
 *  invisible, generous hit band over the roller in the founder's
 *  ground. A button in everything but paint — focusable, labelled
 *  for assistive tech (aria labels are not visible text; the
 *  sheet stays text-free), inert at its end of the sheet. */
function RollerControl({
  testId,
  label,
  disabled,
  x,
  y,
  width,
  height,
  onRoll,
}: {
  testId: string
  label: string
  disabled: boolean
  x: number
  y: number
  width: number
  height: number
  onRoll: () => void
}) {
  return (
    <g
      role="button"
      data-testid={testId}
      aria-label={label}
      aria-disabled={disabled}
      tabIndex={disabled ? -1 : 0}
      style={{ cursor: disabled ? 'default' : 'pointer' }}
      onClick={() => {
        if (!disabled) onRoll()
      }}
      onKeyDown={(e) => {
        if (disabled) return
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onRoll()
        }
      }}
    >
      <rect x={x} y={y} width={width} height={height} fill="#ffffff" fillOpacity={0} />
    </g>
  )
}

/** One mark arriving: a stamp fades in at its tier (the film's
 *  placing rhythm); a stroke draws itself along its path. Marks
 *  are always in the sheet — progress is their visibility, so a
 *  mark at progress 0 is present but not yet seen. */
function DrawingMark({ mark, progress }: { mark: ScrollMark; progress: number }) {
  if (mark.type === 'stamp') {
    const stamp = STAMPS[mark.stamp]
    const h = (mark.w * stamp.h) / stamp.w
    return (
      <g
        data-mark="stamp"
        data-stamp={mark.stamp}
        transform={`translate(${mark.cx} ${mark.cy}) rotate(${mark.angle ?? 0}) scale(${mark.flip ? -1 : 1} 1)`}
        opacity={mark.tier * progress}
      >
        <image href={stamp.src} x={-mark.w / 2} y={-h / 2} width={mark.w} height={h} />
      </g>
    )
  }
  return (
    <path
      data-mark="stroke"
      d={mark.d}
      pathLength={1}
      strokeDasharray={1}
      strokeDashoffset={1 - progress}
      stroke={INK}
      strokeWidth={mark.width}
      opacity={mark.tier}
      fill="none"
      strokeLinecap="round"
    />
  )
}
