/**
 * Jynx's Scroll — the production surface.
 *
 * The Fox's home is a shelf of scrolls (founder, 2026-11-24): a
 * diamond-lattice wooden case holding the user's real Vision
 * Execution work under the standing display rule — parents and
 * loose items only. The lattice holds one scroll per initiative;
 * the open bin at the case's base holds one scroll per unanchored
 * project, per top-level loose task, and per idea. Children are
 * not on the shelf face: choosing a scroll opens its OWN SCREEN
 * (founder, 2026-11-24, superseding the in-scene stand unroll of
 * the first build), where the scroll unrolls full-size into the
 * drawing surface and its children stand beneath it as scrolls of
 * their own, each opening in turn — every record stays reachable
 * through its parent. Jynx's drawings arrive on the sheet mark by
 * mark, in order (rhyme in paint first) — ONCE each: a drawing
 * draws itself when it first appears on its scroll's sheet, and
 * every later presentation shows the finished ink standing
 * (founder, 2026-11-25: signify permanence; don't repaint). The
 * conversation beside the scene belongs to the open scroll and
 * NEVER swaps (founder, 2026-11-25: rolling forward made the
 * conversation he was in disappear); a tapped drawing becomes
 * that conversation's SUBJECT — the seat explains the metaphor in
 * words, in the same talk — through the same LiveContext seam the
 * Campaign Board uses. The drawing scroll itself carries NO text
 * (founder, 2026-11-24): no title lettered on the parchment,
 * nothing on the sheet but the drawings — the subject's name
 * lives in the screen's chrome, never on the scroll. The surface
 * writes nothing anywhere.
 *
 * Assembled from the record's own pieces, not redrawn: the
 * unrolled scroll IS the founder's scroll ground
 * (visual-references-2026-11-18/jynx-scroll-ground-founder, shipped
 * byte-identical as assets/scroll-ground.png, rollers and all);
 * the drawing hand is their stencil kit (rendering-test-assets/
 * jynx-stencil-kit — the same PNG stamps, byte-identical, placed
 * by centre/width/angle/flip/tier exactly as the approved scroll
 * study's generator places them) plus freehand sumi strokes; the
 * unroll and the mark-by-mark arrival follow the approved scroll
 * film's rhythm (the sheet unrolls downward, the painting paints
 * once). The shelf's drawn case is this surface's own furniture
 * in the app's register, after the founder's two shelf references
 * (diamond-lattice case, base bin).
 *
 * Every distinction between shelf scrolls is recorded, never
 * decorative (see scrollLogic): size from kind + recorded mass,
 * parchment tone from recorded age, the binding cord's colour from
 * recorded status — a Blocked item wears Jynx's violet, the one
 * scroll that stands out among plain ones.
 *
 * The drawing feed is the read side of the [[chalk]] carriage
 * (scrollApi.ts): GET /conversation/drawings serves the caller's
 * drawings oldest first, and the surface renders the open
 * scroll's OWN drawings on its sheet — the feed is keyed to the
 * open scroll's conversation server-side and filtered again on
 * the served provenance client-side, so a drawing from another
 * conversation never stands here (founder, 2026-11-25: the scroll
 * was showing a drawing from a previous conversation on an
 * entirely different topic). With the carriage's server flag off,
 * no drawings are made and the feed is honestly empty — the
 * unrolled scroll stands blank, with no placeholder art and no
 * invented drawings. The feed stays current without polling: it
 * re-reads when a scroll is opened or stepped back to, when a
 * conversation turn lands beside the scroll (CouncilChat's
 * onTurnSent — the carriage parses Jynx's tail server-side during
 * the turn, so a drawing made in that turn is already persisted
 * when the reply lands), and when the window regains focus or
 * visibility. A drawing that arrives while a scroll is open joins
 * its sheet in place — the sheet does not re-unroll under the
 * visitor, and the visitor's place along the sheet is not moved
 * unless they are resting with the newest drawing, in which case
 * the sheet grows with them.
 *
 * The open scroll is ONE continuous sheet, not pages (founder,
 * 2026-11-25): its drawings stand along it in the order they were
 * made, the earlier ones rolled up compact toward the top, fresh
 * blank parchment below the newest as working space for the next
 * drawing. Rolling moves ALONG the sheet: the founder's rollers —
 * top toward the older drawings at the top, bottom toward the
 * newer at the bottom — and the screen's Roll back / Roll forward
 * controls move the sheet's focus (scrollLogic.sheetLayout),
 * never swap sheets, and the sheet's content never unmounts. The
 * sheet unrolls only the first time a scroll is opened in this
 * viewing; a presented drawing's ink never repaints.
 *
 * Presented-ness — which drawings have drawn themselves, which
 * scrolls have unrolled — is session state of this mounted
 * surface, keyed by drawing id / scroll key, held in memory only.
 * It survives rolling, selecting, refreshes, and stepping away to
 * the shelf and back within the surface; it does not survive the
 * surface unmounting (a page reload, leaving the seat and
 * returning), because presentation is a viewing, not a record —
 * the store records drawings, not who has watched them arrive.
 * After such a return each drawing draws itself once more on its
 * first presentation, exactly as it did the first time.
 *
 * Talk is the existing council conversation, opened with Jynx
 * (maverick). No separate chat engine. Jynx takes they/them in
 * every reference on this surface.
 */
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import CouncilChat from '../chat/CouncilChat'
import { fetchScrollDrawings, fetchScrollEntities, type ScrollEntities } from './scrollApi'
import {
  buildScrollShelf,
  drawingsForConversation,
  drawingDurationMs,
  flattenShelf,
  markProgressAt,
  scrollChildren,
  sheetLayout,
  shelfTopLevel,
  JYNX_PURPLE,
  type ScrollDrawing,
  type ScrollMark,
  type SheetLayout,
  type ShelfBay,
  type ShelfScroll,
  type StampName,
} from './scrollLogic'
import scrollGround from './assets/scroll-ground.png'
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
const WOOD = '#6b4a2e'
const WOOD_DARK = '#4a3018'
const WOOD_DEEP = '#3c2712'
const CELL_INNER = '#2e2119'
const NAME_INK = '#3a2c1c'

const SCENE_W = 920
const CASE_X = 16
const CASE_W = SCENE_W - CASE_X * 2
const COLS = 6
const CELL_W = CASE_W / COLS
const CELL_H = 104

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

/** The founder's ground on its own screen: drawn at its own
 *  aspect (1086×1448), never stretched, large in the world pane.
 *  The parchment interior — where drawings may land — is the
 *  sheet inside its rollers and torn edges, as fractions of the
 *  image. */
const SCREEN_W = 480
const SCREEN_CX = SCREEN_W / 2
const SHEET_TOP = 96
const GROUND_W = 340
const GROUND_H = 453
const INTERIOR = { x: 0.155, y: 0.125, w: 0.7, h: 0.75 }

const UNROLL_MS = 850

function letterName(title: string, max: number): string {
  const t = (title || '').trim()
  return t.length > max ? `${t.slice(0, max - 1)}…` : t
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

export default function JynxScrollView() {
  const [entities, setEntities] = useState<ScrollEntities | null>(null)
  const [drawings, setDrawings] = useState<ScrollDrawing[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  /** The open scroll's trail: shelf → parent → child … The last
   *  entry is the scroll on screen; the rest are its ancestors,
   *  so the back step always lands on the parent it came from. */
  const [openTrail, setOpenTrail] = useState<string[]>([])
  /** The visitor's chosen place along the open sheet, as a band
   *  index — or null, resting with the newest drawing (the sheet
   *  grows under a resting visitor; an explicit place is held). */
  const [focusOverride, setFocusOverride] = useState<number | null>(null)
  const [selectedDrawingId, setSelectedDrawingId] = useState<string | null>(null)
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
  // Split-shell divider (wide screens), as on the Campaign Board:
  // the conversation pane's width, draggable; portrait stacks.
  const [chatW, setChatW] = useState(380)
  const dividerDrag = useRef<{ pointerId: number } | null>(null)

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
  const openKey = openTrail[openTrail.length - 1] ?? null
  const open = useMemo(
    () => allScrolls.find((s) => `${s.kind}:${s.id}` === openKey) ?? null,
    [allScrolls, openKey],
  )
  const openParent = useMemo(() => {
    const parentKey = openTrail[openTrail.length - 2]
    return parentKey
      ? (allScrolls.find((s) => `${s.kind}:${s.id}` === parentKey) ?? null)
      : null
  }, [allScrolls, openTrail])
  const openChildren = useMemo(
    () => (open ? scrollChildren(shelf, open) : []),
    [shelf, open],
  )
  /* --------------------------- chat wiring --------------------------- */

  // The conversation beside the scroll belongs to the open scroll
  // and NOTHING in the world pane changes it (founder, 2026-11-25):
  // not rolling, not selecting a drawing, not a drawing arriving.
  // A selected drawing changes the conversation's SUBJECT (below),
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

  const chatContext: Record<string, unknown> = selectedDrawing
    ? { sheet_type: 'jynx_scroll', entity_type: 'drawing', entity_id: selectedDrawing.id }
    : open
      ? { sheet_type: 'jynx_scroll', entity_type: open.kind, entity_id: open.id }
      : { sheet_type: 'jynx_scroll' }

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

  /** Choosing a scroll from the shelf opens its own screen. The
   *  drawing feed re-reads on the way in (the open-conversation
   *  effect above) — Jynx may have drawn while this pane sat on
   *  the shelf. The place along the new sheet starts at rest, and
   *  no drawing is the subject until one is tapped. */
  const choose = useCallback((scroll: ShelfScroll) => {
    setOpenTrail([`${scroll.kind}:${scroll.id}`])
    setFocusOverride(null)
    setSelectedDrawingId(null)
  }, [])

  /** Opening a child from the open scroll's screen: the trail
   *  deepens, so the back step returns to this parent. */
  const openChild = useCallback((scroll: ShelfScroll) => {
    setOpenTrail((trail) => [...trail, `${scroll.kind}:${scroll.id}`])
    setFocusOverride(null)
    setSelectedDrawingId(null)
  }, [])

  /** One step back: to the parent scroll, or to the shelf. */
  const goBack = useCallback(() => {
    setOpenTrail((trail) => trail.slice(0, -1))
    setFocusOverride(null)
    setSelectedDrawingId(null)
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
   *  chat. The talk itself does not move. */
  const handleSelectDrawing = useCallback(
    (drawing: ScrollDrawing | null) => {
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

  return (
    <div className="flex-1 flex flex-col lg:flex-row min-h-0 overflow-y-auto lg:overflow-hidden">
      <div className="flex-1 min-w-0 lg:overflow-y-auto p-3 lg:p-5 space-y-3">
        <div className="flex items-center gap-3 px-1 pb-1">
          {open ? (
            <button
              type="button"
              onClick={goBack}
              className="text-sm text-amber-200/90 hover:text-amber-100 min-h-[36px] shrink-0"
            >
              {openParent ? `← ${letterName(openParent.title, 30)}` : '← The shelf'}
            </button>
          ) : null}
          <h1 className="text-lg font-semibold text-stone-100">
            {open ? open.title : 'The Shelf of Scrolls'}
          </h1>
        </div>
        {open ? (
          <OpenScrollScreen
            scroll={open}
            children={openChildren}
            layout={layout}
            unroll={unroll}
            progressFor={progressFor}
            selectedDrawingId={selectedDrawingId}
            onOpenChild={openChild}
            onSelectDrawing={handleSelectDrawing}
            onRoll={rollBy}
          />
        ) : (
          <ScrollScene shelf={shelf} onChoose={choose} />
        )}
      </div>
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize conversation pane"
        className="hidden lg:block w-1.5 shrink-0 cursor-col-resize bg-stone-700/40 hover:bg-amber-600/60 touch-none"
        onPointerDown={(e) => {
          ;(e.currentTarget as Element).setPointerCapture(e.pointerId)
          dividerDrag.current = { pointerId: e.pointerId }
        }}
        onPointerMove={(e) => {
          if (!dividerDrag.current || dividerDrag.current.pointerId !== e.pointerId) return
          const parent = (e.currentTarget as Element).parentElement
          if (!parent) return
          const rect = parent.getBoundingClientRect()
          setChatW(Math.min(560, Math.max(300, rect.right - e.clientX)))
        }}
        onPointerUp={(e) => {
          if (dividerDrag.current?.pointerId === e.pointerId) dividerDrag.current = null
        }}
      />
      <aside
        className="shrink-0 lg:w-[var(--js-chat-w,380px)] lg:overflow-y-auto border-t lg:border-t-0 border-stone-700/60 p-3"
        style={{ ['--js-chat-w' as string]: `${chatW}px` }}
      >
        <div className="rounded-2xl border border-stone-700/60 bg-stone-900/70 p-2">
          <CouncilChat
            key={conversationId}
            environment="workspace"
            initialArchetypeId="maverick"
            conversationId={conversationId}
            context={chatContext}
            onTurnSent={onTurnLanded}
          />
        </div>
      </aside>
    </div>
  )
}

/* ================================================================== */
/* The shelf — lattice case and base bin, parents + loose only         */
/* ================================================================== */

function ScrollScene({
  shelf,
  onChoose,
}: {
  shelf: ShelfBay[]
  onChoose: (scroll: ShelfScroll) => void
}) {
  const { lattice, bin } = shelfTopLevel(shelf)

  // Lattice geometry: at least two rows of compartments stand in
  // the case, even when the shelf is empty — the case itself is
  // furniture of the room; its emptiness is the honest state.
  const cellCount = Math.max(lattice.length, COLS * 2)
  const rows = Math.ceil(cellCount / COLS)
  const latticeTop = 24
  const latticeH = rows * CELL_H + CELL_H / 2
  const latticeBottom = latticeTop + latticeH

  // Bin geometry: scrolls lie in rows along the open base.
  const BIN_PER_ROW = 8
  const binRows = Math.max(1, Math.ceil(bin.length / BIN_PER_ROW))
  const binTop = latticeBottom + 14
  const binH = 30 + binRows * 44
  const caseBottom = binTop + binH
  const height = caseBottom + 28

  const cellCenter = (index: number): { cx: number; cy: number } => {
    const col = index % COLS
    const row = Math.floor(index / COLS)
    return {
      cx: CASE_X + CELL_W / 2 + col * CELL_W,
      cy: latticeTop + CELL_H / 2 + row * CELL_H + (col % 2 === 1 ? CELL_H / 2 : 0),
    }
  }

  return (
    <section aria-label="Jynx — the shelf of scrolls">
      <div className="rounded-2xl overflow-hidden border border-[#4a3018]/70 bg-[#241a12] shadow-lg">
        <svg
          viewBox={`0 0 ${SCENE_W} ${height}`}
          className="w-full block"
          role="img"
          aria-label="A lattice case of rolled scrolls with an open bin at its base"
        >
          {Array.from({ length: cellCount }, (_, i) => {
            const { cx, cy } = cellCenter(i)
            return (
              <path
                key={`cell-${i}`}
                d={`M ${cx} ${cy - CELL_H / 2} L ${cx + CELL_W / 2} ${cy} L ${cx} ${cy + CELL_H / 2} L ${cx - CELL_W / 2} ${cy} Z`}
                fill={CELL_INNER}
                stroke={WOOD}
                strokeWidth={5}
              />
            )
          })}
          {lattice.map((scroll, i) => {
            const { cx, cy } = cellCenter(i)
            return (
              <RolledScroll
                key={`${scroll.kind}:${scroll.id}`}
                scroll={scroll}
                cx={cx}
                cy={cy}
                onChoose={onChoose}
              />
            )
          })}
          <rect
            x={CASE_X - 6}
            y={latticeTop - 10}
            width={CASE_W + 12}
            height={latticeH + 20}
            fill="none"
            stroke={WOOD_DARK}
            strokeWidth={7}
          />
          {/* the open bin at the base */}
          <g>
            <rect
              x={CASE_X - 6}
              y={binTop}
              width={CASE_W + 12}
              height={binH}
              fill="#332416"
              stroke={WOOD_DARK}
              strokeWidth={6}
            />
            {bin.map((scroll, i) => {
              const row = Math.floor(i / BIN_PER_ROW)
              const col = i % BIN_PER_ROW
              return (
                <RolledScroll
                  key={`${scroll.kind}:${scroll.id}`}
                  scroll={scroll}
                  cx={CASE_X + 58 + col * 100}
                  cy={binTop + 38 + row * 44}
                  scale={0.82}
                  onChoose={onChoose}
                />
              )
            })}
          </g>
        </svg>
      </div>
    </section>
  )
}

/* ================================================================== */
/* The open scroll's own screen                                        */
/* ================================================================== */

function OpenScrollScreen({
  scroll,
  children,
  layout,
  unroll,
  progressFor,
  selectedDrawingId,
  onOpenChild,
  onSelectDrawing,
  onRoll,
}: {
  scroll: ShelfScroll
  children: ShelfScroll[]
  layout: SheetLayout
  unroll: number
  progressFor: (drawing: ScrollDrawing) => number
  selectedDrawingId: string | null
  onOpenChild: (scroll: ShelfScroll) => void
  onSelectDrawing: (drawing: ScrollDrawing | null) => void
  onRoll: (delta: number) => void
}) {
  const sheetBottom = SHEET_TOP + GROUND_H
  const height = sheetBottom + 96
  const drawingCount = layout.bands.length - 1
  const focus = layout.focus
  const postX = [SCREEN_CX - GROUND_W / 2 - 26, SCREEN_CX + GROUND_W / 2 + 26]

  return (
    <section aria-label={`The scroll of ${scroll.title}`}>
      <div className="rounded-2xl overflow-hidden border border-[#4a3018]/70 bg-[#241a12] shadow-lg">
        <svg
          viewBox={`0 0 ${SCREEN_W} ${height}`}
          className="w-full block"
          role="img"
          aria-label="An unrolled scroll, large on its stand"
        >
          {/* turned posts */}
          {postX.map((px) => (
            <g key={px}>
              <rect x={px - 8} y={64} width={16} height={sheetBottom - 64 + 52} rx={8} fill={WOOD} stroke={WOOD_DEEP} strokeWidth={1.5} />
              {[150, 250, 350, 450].map((ky) => (
                <circle key={ky} cx={px} cy={ky} r={12} fill={WOOD} stroke={WOOD_DEEP} strokeWidth={1.5} />
              ))}
            </g>
          ))}
          {/* rods with their discs, behind the sheet */}
          {[SHEET_TOP + 16, sheetBottom - 16].map((ry) => (
            <g key={ry}>
              <rect x={postX[0]} y={ry - 5} width={postX[1] - postX[0]} height={10} fill={WOOD_DARK} />
              {postX.map((px) => (
                <circle key={px} cx={px} cy={ry} r={17} fill={WOOD} stroke={WOOD_DEEP} strokeWidth={1.5} />
              ))}
            </g>
          ))}
          {/* round base */}
          <ellipse cx={SCREEN_CX} cy={sheetBottom + 64} rx={128} ry={18} fill={WOOD} stroke={WOOD_DEEP} strokeWidth={2} />
          <ellipse cx={SCREEN_CX} cy={sheetBottom + 58} rx={128} ry={18} fill="#7a5636" stroke={WOOD_DEEP} strokeWidth={1.5} />

          <OpenScroll
            scroll={scroll}
            layout={layout}
            unroll={unroll}
            progressFor={progressFor}
            selectedDrawingId={selectedDrawingId}
            onSelectDrawing={onSelectDrawing}
          />

          {/* the rollers move ALONG the sheet (founder,
              2026-11-25): the ground's top roller rolls toward
              the older drawings rolled up at the top, its bottom
              roller toward the newer and the blank working space
              below — the same sheet movement the chrome controls
              below drive. Nothing is swapped: the sheet's bands
              all stand mounted throughout; only the layout's
              focus moves. The hit bands lie on the rollers
              themselves, clear of the parchment interior, and
              carry no visible text: the rollers are the scroll's
              furniture, not its sheet. At either end of the sheet
              the roller is inert, as the chrome control is. */}
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
        </svg>
      </div>

      {/* roll controls — the sheet rolls from the screen's chrome,
          never as marks on the scroll itself. There are no page
          dots: the sheet is one sheet, and its place along it is
          the rolled history standing at the top, not a position
          in a stack of pages. */}
      {drawingCount >= 1 ? (
        <div data-testid="sheet-controls" className="mt-3 flex items-center justify-center gap-3">
          <button
            type="button"
            data-testid="sheet-back"
            disabled={focus === 0}
            onClick={() => onRoll(-1)}
            className="min-h-[40px] px-4 rounded-full border border-stone-600 text-sm text-amber-100/90 disabled:opacity-40"
          >
            ‹ Roll back
          </button>
          <button
            type="button"
            data-testid="sheet-forward"
            disabled={focus >= drawingCount}
            onClick={() => onRoll(1)}
            className="min-h-[40px] px-4 rounded-full border border-stone-600 text-sm text-amber-100/90 disabled:opacity-40"
          >
            Roll forward ›
          </button>
        </div>
      ) : null}

      {/* the open scroll's children — scrolls of their own, standing
          on the screen beneath the sheet (never on the parchment) */}
      {children.length > 0 ? (
        <div className="mt-4 flex flex-wrap gap-2" data-testid="scroll-children">
          {children.map((child) => (
            <button
              key={`${child.kind}:${child.id}`}
              type="button"
              data-child-scroll={`${child.kind}:${child.id}`}
              onClick={() => onOpenChild(child)}
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
    </section>
  )
}

/** One of the open scroll's rollers as a sheet-movement control:
 *  an invisible, generous hit band over the roller in the
 *  founder's ground. A button in everything but paint —
 *  focusable, labelled for assistive tech (aria labels are not
 *  visible text; the sheet stays text-free), inert at its end of
 *  the sheet. */
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

/* ================================================================== */
/* A rolled scroll on the shelf                                        */
/* ================================================================== */

function RolledScroll({
  scroll,
  cx,
  cy,
  scale = 1,
  onChoose,
}: {
  scroll: ShelfScroll
  cx: number
  cy: number
  scale?: number
  onChoose: (scroll: ShelfScroll) => void
}) {
  const r = scroll.appearance.radius * scale
  const len = r * 3.2
  const thick = r * 1.15
  const fontSize = (scroll.kind === 'initiative' ? 12.5 : scroll.kind === 'task' ? 9.5 : 11) * scale
  const maxChars = scroll.kind === 'initiative' ? 20 : scroll.kind === 'task' ? 15 : 18
  return (
    <g data-scroll={`${scroll.kind}:${scroll.id}`}>
      <title>{scroll.title}</title>
      {/* body */}
      <rect
        x={cx - len / 2}
        y={cy - thick / 2}
        width={len}
        height={thick}
        rx={thick / 2}
        fill={scroll.appearance.parchment}
        stroke="#b09a6d"
        strokeWidth={1.2}
      />
      {/* the rolled end — a spiral cap */}
      <circle cx={cx - len / 2 + thick / 2} cy={cy} r={thick / 2 - 1.5} fill="none" stroke="#a68d5c" strokeWidth={1.4} />
      <circle cx={cx - len / 2 + thick / 2} cy={cy} r={thick / 4.5} fill="none" stroke="#a68d5c" strokeWidth={1.2} />
      {/* binding cords — colour from recorded status only */}
      {[-len / 4, len / 4].map((dx) => (
        <rect
          key={dx}
          x={cx + dx - 1.6}
          y={cy - thick / 2 - 1}
          width={3.2}
          height={thick + 2}
          fill={scroll.appearance.cord}
        />
      ))}
      {/* the name, lettered along the roll */}
      <text
        x={cx + thick / 4}
        y={cy + fontSize / 3}
        textAnchor="middle"
        fontSize={fontSize}
        fill={NAME_INK}
      >
        {letterName(scroll.title, maxChars)}
      </text>
      {/* tap target */}
      <rect
        x={cx - len / 2 - 6}
        y={cy - thick / 2 - 7}
        width={len + 12}
        height={thick + 14}
        fill="#ffffff"
        fillOpacity={0}
        style={{ cursor: 'pointer' }}
        onClick={() => onChoose(scroll)}
      />
    </g>
  )
}
