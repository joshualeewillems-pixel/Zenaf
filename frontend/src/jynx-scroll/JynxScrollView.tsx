/**
 * Jynx's Scroll — the production surface.
 *
 * The Fox's home is a shelf of scrolls (founder, 2026-11-24): a
 * diamond-lattice wooden case holding one rolled scroll per item
 * of the user's real Vision Execution hierarchy — initiatives,
 * projects, tasks, and each idea as its own scroll — with the
 * unanchored items lying in the open bin at the case's base, and a
 * small wooden scroll stand beside the case. Choosing a scroll
 * places it on the stand, where it unrolls into the drawing
 * surface: Jynx's drawings arrive on it mark by mark, in order
 * (rhyme in paint first), and the conversation beside the scene
 * takes the open scroll — or a tapped drawing — as its subject
 * through the same LiveContext seam the Campaign Board uses. The
 * surface writes nothing anywhere.
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
 * once, section by section). The shelf's drawn case and stand are
 * this surface's own furniture in the app's register, after the
 * founder's two shelf references (diamond-lattice case, base bin,
 * turned-post stand).
 *
 * Every distinction between shelf scrolls is recorded, never
 * decorative (see scrollLogic): size from kind + recorded mass,
 * parchment tone from recorded age, the binding cord's colour from
 * recorded status — a Blocked item wears Jynx's violet, the one
 * scroll that stands out among plain ones.
 *
 * The drawing feed is the seam named in scrollApi.ts: neither the
 * pencil prompt channel nor the designed [[chalk]] carriage can
 * deliver drawing geometry to the frontend today, so the feed
 * resolves empty and the unrolled scroll stands honestly blank —
 * no placeholder art, no invented drawings.
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
  JYNX_PURPLE,
  type ScrollDrawing,
  type ScrollMark,
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
const CASE_W = 488
const CELL_W = 122
const CELL_H = 104
const COLS = 4
const STAND_CX = 724

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

/** The founder's ground as it stands on the stand: drawn at its
 *  own aspect (1086×1448), never stretched. The parchment interior
 *  — where drawings may land — is the sheet inside its rollers and
 *  torn edges, as fractions of the image. */
const GROUND_W = 204
const GROUND_H = 272
const INTERIOR = { x: 0.155, y: 0.125, w: 0.7, h: 0.75 }

const UNROLL_MS = 850

function letterName(title: string, max: number): string {
  const t = (title || '').trim()
  return t.length > max ? `${t.slice(0, max - 1)}…` : t
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
  const [openKey, setOpenKey] = useState<string | null>(null)
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

  const shelf = useMemo(
    () =>
      entities
        ? buildScrollShelf(entities.initiatives, entities.projects, entities.tasks, entities.ideas)
        : [],
    [entities],
  )
  const allScrolls = useMemo(() => flattenShelf(shelf), [shelf])
  const open = useMemo(
    () => allScrolls.find((s) => `${s.kind}:${s.id}` === openKey) ?? null,
    [allScrolls, openKey],
  )
  const visibleDrawing = drawings[Math.min(section, Math.max(0, drawings.length - 1))] ?? null
  const selectedDrawing = useMemo(
    () => drawings.find((d) => d.id === selectedDrawingId) ?? null,
    [drawings, selectedDrawingId],
  )

  // The unroll + the draw-out share one clock: opening a scroll (or
  // rolling to a new section) restarts it — the sheet unrolls, then
  // the section's marks arrive in order. Reduced motion shows the
  // finished sheet at once.
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
  }, [openKey, section, drawings, open])

  const choose = useCallback(
    (scroll: ShelfScroll) => {
      const key = `${scroll.kind}:${scroll.id}`
      // Tapping the scroll that is on the stand puts it back.
      setOpenKey((cur) => (cur === key ? null : key))
      setSection(0)
      setSelectedDrawingId(null)
    },
    [],
  )

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
          <h1 className="text-lg font-semibold text-stone-100">The Shelf of Scrolls</h1>
          {open ? (
            <button
              type="button"
              onClick={() => {
                setOpenKey(null)
                setSelectedDrawingId(null)
              }}
              className="text-sm text-amber-200/90 hover:text-amber-100"
            >
              ← The shelf
            </button>
          ) : null}
        </div>
        <ScrollScene
          shelf={shelf}
          open={open}
          drawing={visibleDrawing}
          drawingCount={drawings.length}
          section={Math.min(section, Math.max(0, drawings.length - 1))}
          elapsed={elapsed}
          selectedDrawingId={selectedDrawingId}
          onChoose={choose}
          onSelectDrawing={(d) => setSelectedDrawingId(d.id)}
          onSection={(next) => {
            setSection(next)
            setSelectedDrawingId(null)
          }}
        />
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
          />
        </div>
      </aside>
    </div>
  )
}

/* ================================================================== */
/* The scene — lattice case, base bin, and the stand                   */
/* ================================================================== */

function ScrollScene({
  shelf,
  open,
  drawing,
  drawingCount,
  section,
  elapsed,
  selectedDrawingId,
  onChoose,
  onSelectDrawing,
  onSection,
}: {
  shelf: ReturnType<typeof buildScrollShelf>
  open: ShelfScroll | null
  drawing: ScrollDrawing | null
  drawingCount: number
  section: number
  elapsed: number
  selectedDrawingId: string | null
  onChoose: (scroll: ShelfScroll) => void
  onSelectDrawing: (drawing: ScrollDrawing) => void
  onSection: (next: number) => void
}) {
  const latticeScrolls = flattenShelf(shelf.filter((b) => b.initiative !== null))
  const binScrolls = flattenShelf(shelf.filter((b) => b.initiative === null))

  // Lattice geometry: at least two rows of compartments stand in
  // the case, even when the shelf is empty — the case itself is
  // furniture of the room; its emptiness is the honest state.
  const cellCount = Math.max(latticeScrolls.length, COLS * 2)
  const rows = Math.ceil(cellCount / COLS)
  const latticeTop = 24
  const latticeH = rows * CELL_H + CELL_H / 2
  const latticeBottom = latticeTop + latticeH

  // Bin geometry: scrolls lie in rows of five along the open base.
  const BIN_PER_ROW = 5
  const binRows = Math.max(1, Math.ceil(binScrolls.length / BIN_PER_ROW))
  const binTop = latticeBottom + 14
  const binH = 30 + binRows * 44
  const caseBottom = binTop + binH

  // Stand geometry: the founder's ground stands at its own aspect
  // between the posts; the base sits below it.
  const sheetTop = 118
  const sheetBottom = sheetTop + GROUND_H
  const standBottom = sheetBottom + 92
  const height = Math.max(caseBottom, standBottom) + 28

  const cellCenter = (index: number): { cx: number; cy: number } => {
    const col = index % COLS
    const row = Math.floor(index / COLS)
    return {
      cx: CASE_X + CELL_W / 2 + col * CELL_W,
      cy: latticeTop + CELL_H / 2 + row * CELL_H + (col % 2 === 1 ? CELL_H / 2 : 0),
    }
  }

  const unroll = Math.min(1, elapsed / UNROLL_MS)
  const drawElapsed = Math.max(0, elapsed - UNROLL_MS)

  return (
    <section aria-label="Jynx — the shelf of scrolls">
      <div className="rounded-2xl overflow-hidden border border-[#4a3018]/70 bg-[#241a12] shadow-lg">
        <svg
          viewBox={`0 0 ${SCENE_W} ${height}`}
          className="w-full block"
          role="img"
          aria-label="A lattice case of rolled scrolls, an open bin at its base, and a scroll stand beside it"
        >
          {/* ------------------------- the case ------------------------- */}
          <g>
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
            {latticeScrolls.map((scroll, i) => {
              const { cx, cy } = cellCenter(i)
              return (
                <RolledScroll
                  key={`${scroll.kind}:${scroll.id}`}
                  scroll={scroll}
                  cx={cx}
                  cy={cy}
                  onStand={open?.kind === scroll.kind && open?.id === scroll.id}
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
              {binScrolls.map((scroll, i) => {
                const row = Math.floor(i / BIN_PER_ROW)
                const col = i % BIN_PER_ROW
                return (
                  <RolledScroll
                    key={`${scroll.kind}:${scroll.id}`}
                    scroll={scroll}
                    cx={CASE_X + 58 + col * 100}
                    cy={binTop + 38 + row * 44}
                    scale={0.82}
                    onStand={open?.kind === scroll.kind && open?.id === scroll.id}
                    onChoose={onChoose}
                  />
                )
              })}
            </g>
          </g>

          {/* ------------------------- the stand ------------------------ */}
          <g>
            {/* turned posts */}
            {[STAND_CX - 122, STAND_CX + 122].map((px) => (
              <g key={px}>
                <rect x={px - 7} y={92} width={14} height={sheetBottom - 92 + 52} rx={7} fill={WOOD} stroke={WOOD_DEEP} strokeWidth={1.5} />
                {[130, 210, 290, 370].map((ky) => (
                  <circle key={ky} cx={px} cy={ky} r={10.5} fill={WOOD} stroke={WOOD_DEEP} strokeWidth={1.5} />
                ))}
              </g>
            ))}
            {/* rods with their discs, behind the sheet */}
            {[sheetTop + 14, sheetBottom - 14].map((ry) => (
              <g key={ry}>
                <rect x={STAND_CX - 122} y={ry - 4.5} width={244} height={9} fill={WOOD_DARK} />
                {[STAND_CX - 122, STAND_CX + 122].map((px) => (
                  <circle key={px} cx={px} cy={ry} r={15} fill={WOOD} stroke={WOOD_DEEP} strokeWidth={1.5} />
                ))}
              </g>
            ))}
            {/* round base */}
            <ellipse cx={STAND_CX} cy={sheetBottom + 62} rx={112} ry={16} fill={WOOD} stroke={WOOD_DEEP} strokeWidth={2} />
            <ellipse cx={STAND_CX} cy={sheetBottom + 57} rx={112} ry={16} fill="#7a5636" stroke={WOOD_DEEP} strokeWidth={1.5} />

            {open ? (
              <OpenScroll
                scroll={open}
                drawing={drawing}
                drawElapsed={drawElapsed}
                unroll={unroll}
                sheetTop={sheetTop}
                selected={drawing != null && selectedDrawingId === drawing.id}
                onSelectDrawing={onSelectDrawing}
              />
            ) : null}

            {/* section controls: the sheet's own rollers roll
                between drawings, as in the film — top roller back,
                bottom roller forward; dots count the sections. */}
            {open && drawingCount > 1 ? (
              <g data-testid="section-controls">
                <rect
                  x={STAND_CX - GROUND_W / 2}
                  y={sheetTop}
                  width={GROUND_W}
                  height={30}
                  fill="#ffffff"
                  fillOpacity={0}
                  style={{ cursor: 'pointer' }}
                  onClick={() => onSection(Math.max(0, section - 1))}
                >
                  <title>Roll back</title>
                </rect>
                <rect
                  x={STAND_CX - GROUND_W / 2}
                  y={sheetBottom - 30}
                  width={GROUND_W}
                  height={30}
                  fill="#ffffff"
                  fillOpacity={0}
                  style={{ cursor: 'pointer' }}
                  onClick={() => onSection(Math.min(drawingCount - 1, section + 1))}
                >
                  <title>Roll forward</title>
                </rect>
                {Array.from({ length: drawingCount }, (_, i) => (
                  <circle
                    key={i}
                    cx={STAND_CX + (i - (drawingCount - 1) / 2) * 15}
                    cy={sheetBottom + 84}
                    r={3.5}
                    fill={i === section ? JYNX_PURPLE : '#8a7a5f'}
                  />
                ))}
              </g>
            ) : null}
          </g>
        </svg>
      </div>
    </section>
  )
}

/* ================================================================== */
/* The open scroll on the stand                                        */
/* ================================================================== */

function OpenScroll({
  scroll,
  drawing,
  drawElapsed,
  unroll,
  sheetTop,
  selected,
  onSelectDrawing,
}: {
  scroll: ShelfScroll
  drawing: ScrollDrawing | null
  drawElapsed: number
  unroll: number
  sheetTop: number
  selected: boolean
  onSelectDrawing: (drawing: ScrollDrawing) => void
}) {
  const imgX = STAND_CX - GROUND_W / 2
  const interiorX = imgX + INTERIOR.x * GROUND_W
  const interiorY = sheetTop + INTERIOR.y * GROUND_H
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
            y={sheetTop - 6}
            width={GROUND_W + 16}
            height={(GROUND_H + 12) * unroll}
          />
        </clipPath>
      </defs>
      <g clipPath="url(#jynx-unroll-clip)">
        {/* the founder's ground — the scroll itself */}
        <image href={scrollGround} x={imgX} y={sheetTop} width={GROUND_W} height={GROUND_H} />
        {/* the open item's name, lettered on the sheet */}
        <text
          x={STAND_CX}
          y={interiorY + 16}
          textAnchor="middle"
          fontSize={12.5}
          fontWeight={600}
          fill={NAME_INK}
        >
          {letterName(scroll.title, 30)}
        </text>
        {drawing ? (
          <g
            data-drawing-id={drawing.id}
            transform={`translate(${fitX} ${fitY + 10}) scale(${fit})`}
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
          >
            <title>{drawing.title ?? 'Jynx’s drawing'}</title>
          </rect>
        ) : null}
      </g>
      {/* the travelling roller band at the unroll's edge */}
      {unroll < 1 ? (
        <rect
          x={imgX - 12}
          y={sheetTop - 6 + (GROUND_H + 12) * unroll - 6}
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
  onStand,
  onChoose,
}: {
  scroll: ShelfScroll
  cx: number
  cy: number
  scale?: number
  onStand: boolean
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
      {/* on the stand: Jynx's violet ring in its cell */}
      {onStand ? (
        <path
          d={`M ${cx} ${cy - CELL_H / 2 + 7} L ${cx + CELL_W / 2 - 7} ${cy} L ${cx} ${cy + CELL_H / 2 - 7} L ${cx - CELL_W / 2 + 7} ${cy} Z`}
          fill="none"
          stroke={JYNX_PURPLE}
          strokeWidth={2}
          strokeDasharray="6 4"
        />
      ) : null}
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
