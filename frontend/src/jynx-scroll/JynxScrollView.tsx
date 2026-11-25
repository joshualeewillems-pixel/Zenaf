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
 * mark, in order (rhyme in paint first), and the conversation
 * beside the scene takes the open scroll — or a tapped drawing —
 * as its subject through the same LiveContext seam the Campaign
 * Board uses. The drawing scroll itself carries NO text (founder,
 * 2026-11-24): no title lettered on the parchment, nothing on the
 * sheet but the drawings — the subject's name lives in the
 * screen's chrome, never on the scroll. The surface writes
 * nothing anywhere.
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
 * once, section by section). The shelf's drawn case is this
 * surface's own furniture in the app's register, after the
 * founder's two shelf references (diamond-lattice case, base bin).
 *
 * Every distinction between shelf scrolls is recorded, never
 * decorative (see scrollLogic): size from kind + recorded mass,
 * parchment tone from recorded age, the binding cord's colour from
 * recorded status — a Blocked item wears Jynx's violet, the one
 * scroll that stands out among plain ones.
 *
 * The drawing feed is the read side of the [[chalk]] carriage
 * (scrollApi.ts): GET /conversation/drawings serves the caller's
 * drawings oldest first, and the surface renders them section by
 * section on the open scroll. With the carriage's server flag
 * off, no drawings are made and the feed is honestly empty — the
 * unrolled scroll stands blank, with no placeholder art and no
 * invented drawings. The feed stays current without polling: it
 * re-reads when a scroll is opened or stepped back to, when a
 * conversation turn lands beside the scroll (CouncilChat's
 * onTurnSent — the carriage parses Jynx's tail server-side during
 * the turn, so a drawing made in that turn is already persisted
 * when the reply lands), and when the window regains focus or
 * visibility. A drawing that arrives while a scroll is open joins
 * its sections in place — the sheet does not re-unroll under the
 * visitor. The open scroll's own rollers page its drawings: the
 * top roller rolls back toward the older drawings, the bottom
 * roller forward toward the newer — the same section state the
 * screen's chrome pager drives.
 *
 * Talk is the existing council conversation, opened with Jynx
 * (maverick). No separate chat engine. Jynx takes they/them in
 * every reference on this surface.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import CouncilChat from '../chat/CouncilChat'
import { fetchScrollDrawings, fetchScrollEntities, type ScrollEntities } from './scrollApi'
import {
  buildScrollShelf,
  flattenShelf,
  markProgressAt,
  scrollChildren,
  shelfTopLevel,
  JYNX_PURPLE,
  type ScrollDrawing,
  type ScrollMark,
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
 *  section, selection and unroll clock exactly where they were. */
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
  const [section, setSection] = useState(0)
  const [selectedDrawingId, setSelectedDrawingId] = useState<string | null>(null)
  const [elapsed, setElapsed] = useState(0)
  // Split-shell divider (wide screens), as on the Campaign Board:
  // the conversation pane's width, draggable; portrait stacks.
  const [chatW, setChatW] = useState(380)
  const dividerDrag = useRef<{ pointerId: number } | null>(null)

  const load = useCallback(async () => {
    try {
      const [ents, draws] = await Promise.all([fetchScrollEntities(), fetchScrollDrawings()])
      setEntities(ents)
      setDrawings(draws)
      setLoadError(null)
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : 'Could not load your scrolls.')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  /** Re-read ONLY the drawing feed (see the header: the triggers).
   *  An unchanged feed keeps the previous list object, so nothing
   *  re-renders and the visitor's place is untouched; a grown feed
   *  swaps the list in place — the section state is separate, so
   *  the visitor stays on the drawing they were looking at and
   *  the new one waits at the end of the pager. A failed re-read
   *  keeps the drawings already on the surface: the error screen
   *  belongs to the first load alone, and a refresh must never
   *  blank a scroll that loaded fine. */
  const refreshDrawings = useCallback(async () => {
    try {
      const draws = await fetchScrollDrawings()
      setDrawings((prev) => (sameDrawings(prev, draws) ? prev : draws))
    } catch {
      /* keep what the surface already holds */
    }
  }, [])

  // The window waking is a refresh trigger too: Jynx may have
  // drawn in another tab, or on the phone while this pane sat
  // open. No polling — focus and visibility changes only.
  useEffect(() => {
    const onFocus = () => {
      void refreshDrawings()
    }
    const onVisibility = () => {
      if (document.visibilityState === 'visible') void refreshDrawings()
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
  const visibleDrawing = drawings[Math.min(section, Math.max(0, drawings.length - 1))] ?? null
  const selectedDrawing = useMemo(
    () => drawings.find((d) => d.id === selectedDrawingId) ?? null,
    [drawings, selectedDrawingId],
  )

  // The unroll + the draw-out share one clock: opening a scroll (or
  // rolling to a new section) restarts it — the sheet unrolls, then
  // the section's marks arrive in order. Reduced motion shows the
  // finished sheet at once. The clock deliberately does NOT key on
  // the drawings list: a drawing that arrives mid-viewing (a
  // refresh after Jynx's turn) joins the pager in place instead of
  // re-unrolling the sheet under the visitor — it gets its own
  // unroll when the visitor rolls to its section.
  useEffect(() => {
    setElapsed(0)
    if (!open) return
    if (prefersReducedMotion()) {
      setElapsed(Number.MAX_SAFE_INTEGER)
      return
    }
    const start = Date.now()
    const timer = setInterval(() => setElapsed(Date.now() - start), 50)
    return () => clearInterval(timer)
  }, [openKey, section, open])

  /** Choosing a scroll from the shelf opens its own screen. The
   *  drawing feed re-reads on the way in — Jynx may have drawn
   *  while this pane sat on the shelf. */
  const choose = useCallback(
    (scroll: ShelfScroll) => {
      setOpenTrail([`${scroll.kind}:${scroll.id}`])
      setSection(0)
      setSelectedDrawingId(null)
      void refreshDrawings()
    },
    [refreshDrawings],
  )

  /** Opening a child from the open scroll's screen: the trail
   *  deepens, so the back step returns to this parent. */
  const openChild = useCallback(
    (scroll: ShelfScroll) => {
      setOpenTrail((trail) => [...trail, `${scroll.kind}:${scroll.id}`])
      setSection(0)
      setSelectedDrawingId(null)
      void refreshDrawings()
    },
    [refreshDrawings],
  )

  /** One step back: to the parent scroll, or to the shelf. */
  const goBack = useCallback(() => {
    setOpenTrail((trail) => trail.slice(0, -1))
    setSection(0)
    setSelectedDrawingId(null)
    void refreshDrawings()
  }, [refreshDrawings])

  /** A turn just landed in the conversation beside the scroll.
   *  CouncilChat fires onTurnSent on its success arms only, after
   *  the reply lands — and the carriage persists a turn's drawings
   *  server-side before that reply is served, so a drawing Jynx
   *  made in this turn is already in the feed. Re-read it: this
   *  is the trigger that lands a fresh drawing on a pane that was
   *  open while Jynx drew. */
  const onTurnLanded = useCallback(() => {
    void refreshDrawings()
  }, [refreshDrawings])

  /* --------------------------- chat wiring --------------------------- */

  const conversationId = selectedDrawing
    ? `jynx-scroll:drawing:${selectedDrawing.id}`
    : open
      ? `jynx-scroll:${open.kind}:${open.id}`
      : 'jynx-scroll:shelf'
  const chatContext: Record<string, unknown> = selectedDrawing
    ? { sheet_type: 'jynx_scroll', entity_type: 'drawing', entity_id: selectedDrawing.id }
    : open
      ? { sheet_type: 'jynx_scroll', entity_type: open.kind, entity_id: open.id }
      : { sheet_type: 'jynx_scroll' }

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
            drawing={visibleDrawing}
            drawingCount={drawings.length}
            section={Math.min(section, Math.max(0, drawings.length - 1))}
            elapsed={elapsed}
            selectedDrawingId={selectedDrawingId}
            onOpenChild={openChild}
            onSelectDrawing={(d) => setSelectedDrawingId(d.id)}
            onSection={(next) => {
              setSection(next)
              setSelectedDrawingId(null)
            }}
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
  drawing,
  drawingCount,
  section,
  elapsed,
  selectedDrawingId,
  onOpenChild,
  onSelectDrawing,
  onSection,
}: {
  scroll: ShelfScroll
  children: ShelfScroll[]
  drawing: ScrollDrawing | null
  drawingCount: number
  section: number
  elapsed: number
  selectedDrawingId: string | null
  onOpenChild: (scroll: ShelfScroll) => void
  onSelectDrawing: (drawing: ScrollDrawing) => void
  onSection: (next: number) => void
}) {
  const sheetBottom = SHEET_TOP + GROUND_H
  const height = sheetBottom + 96
  const unroll = Math.min(1, elapsed / UNROLL_MS)
  const drawElapsed = Math.max(0, elapsed - UNROLL_MS)
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
            drawing={drawing}
            drawElapsed={drawElapsed}
            unroll={unroll}
            selected={drawing != null && selectedDrawingId === drawing.id}
            onSelectDrawing={onSelectDrawing}
          />

          {/* the rollers page the drawings (founder, 2026-11-25):
              the ground's top roller rolls back toward the older
              drawings — the scroll's history — and its bottom
              roller rolls forward toward the newer, driving the
              same section state as the chrome pager below. The
              hit bands lie on the rollers themselves, clear of the
              parchment interior, and carry no visible text: the
              rollers are the scroll's furniture, not its sheet.
              At either end the roller is inert, as the pager's
              disabled button is. */}
          {drawingCount > 1 ? (
            <>
              <RollerControl
                testId="roller-back"
                label="Previous drawing"
                disabled={section === 0}
                x={SCREEN_CX - GROUND_W / 2 - 14}
                y={SHEET_TOP}
                width={GROUND_W + 28}
                height={54}
                onRoll={() => onSection(Math.max(0, section - 1))}
              />
              <RollerControl
                testId="roller-forward"
                label="Next drawing"
                disabled={section >= drawingCount - 1}
                x={SCREEN_CX - GROUND_W / 2 - 14}
                y={SHEET_TOP + GROUND_H - 54}
                width={GROUND_W + 28}
                height={54}
                onRoll={() => onSection(Math.min(drawingCount - 1, section + 1))}
              />
            </>
          ) : null}
        </svg>
      </div>

      {/* section controls — the sheet's sections roll from the
          screen's chrome, never as marks on the scroll itself */}
      {drawingCount > 1 ? (
        <div data-testid="section-controls" className="mt-3 flex items-center justify-center gap-3">
          <button
            type="button"
            data-testid="section-back"
            disabled={section === 0}
            onClick={() => onSection(Math.max(0, section - 1))}
            className="min-h-[40px] px-4 rounded-full border border-stone-600 text-sm text-amber-100/90 disabled:opacity-40"
          >
            ‹ Roll back
          </button>
          <span className="flex items-center gap-1.5" aria-hidden="true">
            {Array.from({ length: drawingCount }, (_, i) => (
              <span
                key={i}
                className="inline-block w-2 h-2 rounded-full"
                style={{ background: i === section ? JYNX_PURPLE : '#8a7a5f' }}
              />
            ))}
          </span>
          <button
            type="button"
            data-testid="section-forward"
            disabled={section >= drawingCount - 1}
            onClick={() => onSection(Math.min(drawingCount - 1, section + 1))}
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

/** One of the open scroll's rollers as a paging control: an
 *  invisible, generous hit band over the roller in the founder's
 *  ground. A button in everything but paint — focusable, labelled
 *  for assistive tech (aria labels are not visible text; the sheet
 *  stays text-free), inert at its end of the sections. */
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
  drawing,
  drawElapsed,
  unroll,
  selected,
  onSelectDrawing,
}: {
  scroll: ShelfScroll
  drawing: ScrollDrawing | null
  drawElapsed: number
  unroll: number
  selected: boolean
  onSelectDrawing: (drawing: ScrollDrawing) => void
}) {
  const imgX = SCREEN_CX - GROUND_W / 2
  const interiorX = imgX + INTERIOR.x * GROUND_W
  const interiorY = SHEET_TOP + INTERIOR.y * GROUND_H
  const interiorW = INTERIOR.w * GROUND_W
  const interiorH = INTERIOR.h * GROUND_H

  // Fit the drawing's own space inside the parchment interior.
  const fit = drawing
    ? Math.min(interiorW / drawing.space.w, interiorH / drawing.space.h)
    : 0
  const drawnW = drawing ? drawing.space.w * fit : 0
  const drawnH = drawing ? drawing.space.h * fit : 0
  const fitX = interiorX + (interiorW - drawnW) / 2
  const fitY = interiorY + (interiorH - drawnH) / 2

  return (
    <g data-open-scroll={`${scroll.kind}:${scroll.id}`}>
      <defs>
        <clipPath id="jynx-unroll-clip">
          <rect
            x={imgX - 8}
            y={SHEET_TOP - 6}
            width={GROUND_W + 16}
            height={(GROUND_H + 12) * unroll}
          />
        </clipPath>
      </defs>
      <g clipPath="url(#jynx-unroll-clip)">
        {/* the founder's ground — the scroll itself. NO text is
            rendered on the sheet: drawings only. */}
        <image href={scrollGround} x={imgX} y={SHEET_TOP} width={GROUND_W} height={GROUND_H} />
        {drawing ? (
          <g
            data-drawing-id={drawing.id}
            transform={`translate(${fitX} ${fitY + 14}) scale(${fit})`}
          >
            {drawing.marks.map((mark, i) => (
              <DrawingMark
                key={i}
                mark={mark}
                progress={markProgressAt(drawElapsed, drawing, i)}
              />
            ))}
          </g>
        ) : null}
        {drawing ? (
          <rect
            x={interiorX}
            y={interiorY}
            width={interiorW}
            height={interiorH}
            fill="#ffffff"
            fillOpacity={0}
            stroke={selected ? JYNX_PURPLE : 'none'}
            strokeWidth={1.6}
            strokeDasharray="5 4"
            style={{ cursor: 'pointer' }}
            onClick={() => onSelectDrawing(drawing)}
          />
        ) : null}
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
