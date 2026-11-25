/**
 * Aria's Atelier — the Well, as a production surface.
 *
 * This view is Aria's landing: tapping her tree node navigates the
 * shell here (LivingTree's SEAT_HOME_NAV; her sheet keeps its
 * own door), and the layout is the shared SplitShell — the world on
 * the left, her conversation on the right, a draggable divider
 * between them, each pane scrolling on its own.
 *
 * Aria's view opens on the well in the zen rock garden: the circular
 * stone well of rainbow interference water (the Resonance Atelier
 * field engine, ported whole — ./waterEngine), ringed by cairns. The
 * cairns are the user's real Vision-map cairns — the map's own graph
 * build piles each project subtree, and the piles here are rendered
 * by the map's tower layout and sprite component from the same
 * members. Nothing is fixture, nothing is redrawn.
 *
 * The ring follows the standing display rule (founder, 2026-11-24 —
 * parents and loose items only): one cairn per INITIATIVE (the
 * union of its projects' piles), plus the loose projects and the
 * standalone stones. An initiative's project cairns appear in its
 * fan when the initiative is opened; a project's stones appear in
 * its own fan, as before — every record stays reachable through
 * its parent. The ring's layout (gardenLayout) guarantees the
 * shown cairns' name labels never overlap: footprints are placed
 * on the ring and relaxed until no two touch, clear of the well.
 *
 * Casting follows the accepted prototype (seven-interfaces, Aria
 * view): fan a cairn to see its stones; drag a stone to the well —
 * or tap the stone, then the well — to cast it. The cairn itself can
 * be thrown in by its base (the project), and the fan carries the
 * initiative as a castable stone (the whole undertaking). On the
 * cast: a ripple beat, the well grown large, the seven-voice pure
 * layer stack forming on the water inside its rim, and the subject's
 * conversation loaded in Aria's chat through the same CouncilChat
 * context seam the Campaign Board uses — Aria's three-part note
 * (what's going well / what's progressing / the next step) is her
 * conversational behaviour in that grounded conversation, not a
 * stored panel. Quiet return via the rim.
 *
 * The stack's channels are the founder's rulings: layers ordered by
 * interaction recency; fill alpha moment-to-moment on a base-e
 * approach inside the 10%–80% band (the Discussion slider sets the
 * ceiling); ink always at 100%; complexity — how much the user has
 * talked with a seat about the selected subject — presented as
 * emergence replay depth. No emergence video plays inside the rim:
 * those renders are geometry on an opaque paper ground. No paper
 * anywhere — the layers are the transparent splits of the canonical
 * pure-composite exports, and the water shows through.
 *
 * Governing design: zenaf-aria-atelier-language-definitions-2026-11-23.md
 * and the founder's Well specification, 2026-11-24.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import CouncilChat from '../chat/CouncilChat'
import SplitShell from '../components/SplitShell'
import { CairnStoneSprite } from '../vision-map/CairnStoneSprite'
import { CAIRN_SPRITES, UPPER_POOL } from '../vision-map/cairnSprites'
import {
  towerLayoutForMembers,
  type CairnMemberInput,
  type PortedTowerLayout,
} from '../vision-map/cairnTower'
import { fetchAtelierData, fetchSeatTurnCounts, type AtelierData } from './atelierApi'
import {
  FORMATION_SCALE,
  STACK_DEFAULT,
  VOICES,
  VOICE_BY_ARCHETYPE,
  VOICE_COLORS,
  VOICE_HOMES,
  VOICE_NAMES,
  bringToFront,
  castInitiative,
  castLooseStone,
  castProject,
  castStone,
  chatContextFor,
  conversationIdFor,
  depthProjectId,
  depthsForSubject,
  fillStep,
  fillTarget,
  floorMult,
  gardenFootprint,
  gardenLayout,
  looseCairns,
  ringInitiatives,
  ceilingScale,
  REPLAY_BASE_MS,
  REPLAY_HOLD_MS,
  REPLAY_RATES,
  type AtelierCairn,
  type AtelierInitiativePile,
  type AtelierLooseStone,
  type GardenPlacement,
  type AtelierStone,
  type CastTarget,
  type Voice,
} from './atelierLogic'
import { ResonanceField } from './waterEngine'
import './atelier.css'

import ariaFill from './assets/layer-aria-fill.png'
import ariaInk from './assets/layer-aria-ink.png'
import jynxFill from './assets/layer-jynx-fill.png'
import jynxInk from './assets/layer-jynx-ink.png'
import lucianFill from './assets/layer-lucian-fill.png'
import lucianInk from './assets/layer-lucian-ink.png'
import maeveFill from './assets/layer-maeve-fill.png'
import maeveInk from './assets/layer-maeve-ink.png'
import rumiFill from './assets/layer-rumi-fill.png'
import rumiInk from './assets/layer-rumi-ink.png'
import severineFill from './assets/layer-severine-fill.png'
import severineInk from './assets/layer-severine-ink.png'
import valenFill from './assets/layer-valen-fill.png'
import valenInk from './assets/layer-valen-ink.png'

const LAYER_IMAGES: Record<Voice, { fill: string; ink: string }> = {
  rumi: { fill: rumiFill, ink: rumiInk },
  valen: { fill: valenFill, ink: valenInk },
  maeve: { fill: maeveFill, ink: maeveInk },
  lucian: { fill: lucianFill, ink: lucianInk },
  aria: { fill: ariaFill, ink: ariaInk },
  severine: { fill: severineFill, ink: severineInk },
  jynx: { fill: jynxFill, ink: jynxInk },
}

const NEUTRAL_WASH = '#a8a29e'
const REDUCED_MOTION =
  typeof window !== 'undefined' &&
  typeof window.matchMedia === 'function' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches

type Picked =
  | { kind: 'stone'; cairn: AtelierCairn; stone: AtelierStone }
  | { kind: 'initiative'; cairn: AtelierCairn }
  | { kind: 'loose'; stone: AtelierLooseStone }
  | null

type DragPayload =
  | { kind: 'stone'; cairn: AtelierCairn; stone: AtelierStone }
  | { kind: 'cairnBase'; cairn: AtelierCairn }
  | { kind: 'initiative'; cairn: AtelierCairn }
  | { kind: 'initiativePile'; pile: AtelierInitiativePile }
  | { kind: 'fanProject'; cairn: AtelierCairn }
  | { kind: 'loose'; stone: AtelierLooseStone }

type Ghost = { x: number; y: number; title: string; spriteUrl: string; tint: string } | null

/** One item standing in the garden's ring (parents + loose only). */
type RingItem =
  | { key: string; kind: 'initiative'; pile: AtelierInitiativePile }
  | { key: string; kind: 'cairn'; cairn: AtelierCairn }
  | { key: string; kind: 'loose'; stone: AtelierLooseStone }

/** The sprite + tint a pile member wears, read off its tower layout —
 *  a fanned stone wears the same face it wears in the pile. */
function spriteForMember(
  layout: PortedTowerLayout,
  memberId: string,
): { spriteUrl: string; tint: string } {
  const s = layout.stones.find((x) => x.memberId === memberId)
  if (s) return { spriteUrl: s.spriteUrl, tint: s.tint }
  let h = 0
  for (let i = 0; i < memberId.length; i++) h = (h * 31 + memberId.charCodeAt(i)) >>> 0
  const name = UPPER_POOL[h % UPPER_POOL.length]
  return { spriteUrl: CAIRN_SPRITES[name].url, tint: NEUTRAL_WASH }
}

/* ================================================================== */
/* A cairn pile, rendered by the Vision map's tower layout             */
/* ================================================================== */

function PileView({
  pileId,
  members,
  width,
  layoutRef,
}: {
  pileId: string
  members: CairnMemberInput[]
  width: number
  layoutRef?: (layout: PortedTowerLayout) => void
}) {
  const layout = useMemo(
    () => towerLayoutForMembers(pileId, members),
    [pileId, members],
  )
  useEffect(() => {
    layoutRef?.(layout)
  }, [layout, layoutRef])
  const scale = width / layout.width
  return (
    <span
      className="atelier-cairn-pile"
      style={{ width, height: (layout.height + 10) * scale }}
      aria-hidden="true"
    >
      <span
        style={{
          position: 'absolute',
          left: 0,
          top: 0,
          width: layout.width,
          height: layout.height + 10,
          transform: `scale(${scale})`,
          transformOrigin: 'top left',
        }}
      >
        {layout.stones.map((s) => (
          <span
            key={s.seed}
            className="stone-pos"
            style={{
              left: s.left,
              top: s.top,
              width: s.width,
              height: s.height,
              transform: `rotate(${s.rotation}deg)`,
              transformOrigin: `${s.originX}px ${s.originY}px`,
            }}
          >
            <CairnStoneSprite src={s.spriteUrl} tint={s.tint} />
          </span>
        ))}
      </span>
    </span>
  )
}

/* ================================================================== */
/* The view                                                            */
/* ================================================================== */

export default function AriaAtelierView() {
  const [data, setData] = useState<AtelierData | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [openProjectId, setOpenProjectId] = useState<string | null>(null)
  const [openInitiativeId, setOpenInitiativeId] = useState<string | null>(null)
  const [picked, setPicked] = useState<Picked>(null)
  const [cast, setCast] = useState<CastTarget | null>(null)
  const [casting, setCasting] = useState(false)
  const [rippleKey, setRippleKey] = useState(0)
  const [ghost, setGhost] = useState<Ghost>(null)
  const [wellOver, setWellOver] = useState(false)
  const [turnCounts, setTurnCounts] = useState<Record<string, number> | null>(null)
  const [selectedVoice, setSelectedVoice] = useState<Voice | 'all'>('all')
  const [order, setOrder] = useState<Voice[]>(STACK_DEFAULT)
  const [ceiling, setCeiling] = useState(80)
  const [formingKey, setFormingKey] = useState(0)

  const wellRef = useRef<HTMLButtonElement | null>(null)
  const gardenWaterRef = useRef<HTMLCanvasElement | null>(null)
  const castWaterRef = useRef<HTMLCanvasElement | null>(null)
  const fieldRef = useRef<ResonanceField | null>(null)
  const castTimer = useRef<number | null>(null)
  const dragRef = useRef<{
    x: number
    y: number
    moved: boolean
    payload: DragPayload
    ghost: { title: string; spriteUrl: string; tint: string }
  } | null>(null)
  const layoutsRef = useRef(new Map<string, PortedTowerLayout>())
  const fillImgRefs = useRef(new Map<Voice, HTMLImageElement>())
  const layerRefs = useRef(new Map<Voice, HTMLDivElement>())
  const fillState = useRef<Record<Voice, number>>(
    Object.fromEntries(VOICES.map((v) => [v, 1])) as Record<Voice, number>,
  )
  const stackAnim = useRef<{
    raf: number
    last: number
    replay: {
      voice: Voice
      depth: number
      phase: 'reveal' | 'hold' | 'complete'
      startedAt: number
      phaseAt: number
    } | null
  }>({ raf: 0, last: 0, replay: null })
  const respondedFor = useRef<string | null>(null)

  const load = useCallback(async () => {
    setLoadError(null)
    try {
      setData(await fetchAtelierData())
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : 'The garden could not be loaded.')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  /* ------------------------------ water ---------------------------- */

  useEffect(() => {
    if (!data) return
    if (!fieldRef.current) fieldRef.current = new ResonanceField()
    const field = fieldRef.current
    if (!field.available) return
    if (REDUCED_MOTION) {
      field.seek(20) /* the Movement II still */
      field.blitTo(gardenWaterRef.current)
      field.blitTo(castWaterRef.current)
      return
    }
    field.start(() => [gardenWaterRef.current, castWaterRef.current])
    return () => field.stop()
  }, [data])

  /* When the cast opens under reduced motion, the still is blitted
     into the cast water once it exists. */
  useEffect(() => {
    if (!cast || !REDUCED_MOTION) return
    const field = fieldRef.current
    if (field?.available) field.blitTo(castWaterRef.current)
  }, [cast])

  /* --------------------------- cast depths -------------------------- */

  const conversationId = conversationIdFor(cast)
  const chatContext = useMemo(() => chatContextFor(cast), [cast])

  const depthProject = useMemo(() => {
    if (!cast || !data) return null
    return depthProjectId(cast, data.garden)
  }, [cast, data])

  const depths = useMemo<Record<Voice, number>>(() => {
    const keystone = depthProject ? data?.keystoneCounts.get(depthProject) : undefined
    return depthsForSubject(turnCounts ?? {}, keystone)
  }, [turnCounts, depthProject, data])

  const depthsRef = useRef(depths)
  useEffect(() => {
    depthsRef.current = depths
  }, [depths])

  /* On a cast, load the subject conversation's recorded talk, then
     Aria responds: her layer comes forward and re-forms to her depth. */
  useEffect(() => {
    if (!cast) {
      setTurnCounts(null)
      respondedFor.current = null
      return
    }
    let cancelled = false
    setTurnCounts(null)
    void fetchSeatTurnCounts(conversationId).then((turns) => {
      if (cancelled) return
      setTurnCounts(turns.counts)
    })
    return () => {
      cancelled = true
    }
  }, [cast, conversationId])

  const respond = useCallback(
    (voice: Voice) => {
      setSelectedVoice(voice)
      setOrder((o) => bringToFront(o, voice))
      /* Having something to say, made visible: the fill drops to the
         floor and rises again on the base-e curve. */
      fillState.current[voice] = floorMult(voice) * ceilingScale(ceiling)
      if (!REDUCED_MOTION) {
        stackAnim.current.replay = {
          voice,
          depth: depthsRef.current[voice],
          phase: 'reveal',
          startedAt: performance.now(),
          phaseAt: performance.now(),
        }
      }
    },
    [ceiling],
  )

  useEffect(() => {
    if (!cast || turnCounts === null) return
    if (respondedFor.current === conversationId) return
    respondedFor.current = conversationId
    respond('aria')
  }, [cast, turnCounts, conversationId, respond])

  /* --------------------- stack animation loop ----------------------- */
  /* One rAF loop drives both ruled motions while a cast is open:
     the fills' base-e approach toward their targets, and the
     responding layer's replay — a radial re-forming from the seat's
     home, out to its talk-depth fraction, a held beat, then the
     formation completes while the fill rises. (The true-prefix
     emergence frames exist only as opaque-ground video, which never
     plays inside the rim; the replay here is a reveal of the finished
     transparent layer, and is named as such in the report.) */

  useEffect(() => {
    if (!cast) return
    const anim = stackAnim.current
    anim.last = performance.now()
    const step = (now: number) => {
      anim.raf = requestAnimationFrame(step)
      const dt = Math.min(0.1, (now - anim.last) / 1000)
      anim.last = now
      for (const v of VOICES) {
        const img = fillImgRefs.current.get(v)
        if (!img) continue
        const target = fillTarget(v, selectedVoice, ceiling)
        const next = fillStep(fillState.current[v], target, dt)
        if (next !== fillState.current[v]) {
          fillState.current[v] = next
          img.style.opacity = next.toFixed(3)
        }
      }
      const replay = anim.replay
      const layer = replay ? layerRefs.current.get(replay.voice) : null
      if (replay && layer) {
        const home = VOICE_HOMES[replay.voice]
        const rect = layer.getBoundingClientRect()
        const hx = (home[0] / 1000) * rect.width
        const hy = (home[1] / 1320) * rect.height
        const cover = Math.hypot(Math.max(hx, rect.width - hx), Math.max(hy, rect.height - hy))
        const duration = REPLAY_BASE_MS / REPLAY_RATES[replay.voice]
        let frac: number | null = null
        if (replay.phase === 'reveal') {
          const p = Math.min(1, (now - replay.startedAt) / duration)
          frac = replay.depth * p
          if (p >= 1) {
            replay.phase = 'hold'
            replay.phaseAt = now
          }
        } else if (replay.phase === 'hold') {
          frac = replay.depth
          if (now - replay.phaseAt >= REPLAY_HOLD_MS) {
            replay.phase = 'complete'
            replay.phaseAt = now
          }
        } else {
          const p = Math.min(1, (now - replay.phaseAt) / 400)
          frac = replay.depth + (1 - replay.depth) * p
          if (p >= 1) {
            layer.style.maskImage = ''
            layer.style.webkitMaskImage = ''
            anim.replay = null
          }
        }
        if (frac !== null && anim.replay) {
          const r = Math.max(0.5, frac * cover)
          const mask = `radial-gradient(circle at ${hx}px ${hy}px, black 0 ${r}px, transparent ${r + 24}px)`
          layer.style.maskImage = mask
          layer.style.webkitMaskImage = mask
        }
      }
    }
    anim.raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(anim.raf)
  }, [cast, selectedVoice, ceiling])

  /* ------------------------------ casting --------------------------- */

  const doCast = useCallback((target: CastTarget) => {
    setRippleKey((k) => k + 1)
    setCasting(true)
    if (castTimer.current) window.clearTimeout(castTimer.current)
    castTimer.current = window.setTimeout(
      () => {
        setCasting(false)
        setCast(target)
        setFormingKey((k) => k + 1)
        setOpenProjectId(null)
        setOpenInitiativeId(null)
        setPicked(null)
      },
      REDUCED_MOTION ? 60 : 680,
    )
  }, [])

  useEffect(
    () => () => {
      if (castTimer.current) window.clearTimeout(castTimer.current)
    },
    [],
  )

  const returnToGarden = useCallback(() => {
    setCast(null)
    setSelectedVoice('all')
    setOrder(STACK_DEFAULT)
    stackAnim.current.replay = null
    for (const el of layerRefs.current.values()) {
      el.style.maskImage = ''
      el.style.webkitMaskImage = ''
    }
  }, [])

  /* --------------------------- drag grammar -------------------------- */

  const ghostFor = useCallback(
    (payload: DragPayload): { title: string; spriteUrl: string; tint: string } => {
      switch (payload.kind) {
        case 'stone': {
          const layout = layoutsRef.current.get(payload.cairn.cairnId)
          const s = layout
            ? spriteForMember(layout, payload.stone.memberId)
            : { spriteUrl: CAIRN_SPRITES['stone-medium'].url, tint: NEUTRAL_WASH }
          return { title: payload.stone.title, ...s }
        }
        case 'cairnBase':
        case 'fanProject': {
          return {
            title: payload.cairn.projectTitle,
            spriteUrl: CAIRN_SPRITES['cairn-slab'].url,
            tint: NEUTRAL_WASH,
          }
        }
        case 'initiativePile': {
          return {
            title: payload.pile.title,
            spriteUrl: CAIRN_SPRITES['cairn-slab'].url,
            tint: NEUTRAL_WASH,
          }
        }
        case 'initiative': {
          return {
            title: payload.cairn.initiativeTitle ?? payload.cairn.projectTitle,
            spriteUrl: CAIRN_SPRITES['cairn-slab'].url,
            tint: NEUTRAL_WASH,
          }
        }
        case 'loose': {
          const layout = towerLayoutForMembers(
            `atelier-loose-${payload.stone.taskId}`,
            payload.stone.members,
          )
          const s = layout.stones.find((x) => x.role !== 'slab') ?? layout.stones[0]
          return {
            title: payload.stone.title,
            spriteUrl: s?.spriteUrl ?? CAIRN_SPRITES['stone-medium'].url,
            tint: s?.tint ?? NEUTRAL_WASH,
          }
        }
      }
    },
    [],
  )

  const tapPayload = useCallback(
    (payload: DragPayload) => {
      switch (payload.kind) {
        case 'stone':
          setPicked({ kind: 'stone', cairn: payload.cairn, stone: payload.stone })
          break
        case 'initiative':
          setPicked({ kind: 'initiative', cairn: payload.cairn })
          break
        case 'loose':
          setPicked({ kind: 'loose', stone: payload.stone })
          break
        case 'cairnBase':
          setPicked(null)
          setOpenInitiativeId(null)
          setOpenProjectId((cur) => (cur === payload.cairn.projectId ? null : payload.cairn.projectId))
          break
        case 'initiativePile':
          setPicked(null)
          setOpenProjectId(null)
          setOpenInitiativeId((cur) => (cur === payload.pile.initiativeId ? null : payload.pile.initiativeId))
          break
        case 'fanProject':
          // A project opened from its initiative's fan: the fan
          // steps into the project, keeping the initiative open
          // behind it (the fan carries the way back).
          setPicked(null)
          setOpenProjectId(payload.cairn.projectId)
          break
      }
    },
    [],
  )

  const dropPayload = useCallback(
    (payload: DragPayload) => {
      switch (payload.kind) {
        case 'stone':
          doCast(castStone(payload.cairn, payload.stone))
          break
        case 'cairnBase':
        case 'fanProject':
          doCast(castProject(payload.cairn))
          break
        case 'initiativePile': {
          const t = castInitiative(payload.pile.cairns[0])
          if (t) doCast(t)
          break
        }
        case 'initiative': {
          const t = castInitiative(payload.cairn)
          if (t) doCast(t)
          break
        }
        case 'loose':
          doCast(castLooseStone(payload.stone))
          break
      }
    },
    [doCast],
  )

  const dragHandlers = useCallback(
    (payload: DragPayload) => ({
      onPointerDown: (e: React.PointerEvent) => {
        dragRef.current = {
          x: e.clientX,
          y: e.clientY,
          moved: false,
          payload,
          ghost: ghostFor(payload),
        }
        try {
          ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
        } catch {
          /* capture is an enhancement; the tap grammar still works */
        }
      },
      onPointerMove: (e: React.PointerEvent) => {
        const drag = dragRef.current
        if (!drag) return
        if (!drag.moved && Math.hypot(e.clientX - drag.x, e.clientY - drag.y) > 9) {
          drag.moved = true
        }
        if (drag.moved) {
          setGhost({ ...drag.ghost, x: e.clientX, y: e.clientY })
          const wr = wellRef.current?.getBoundingClientRect()
          setWellOver(
            !!wr &&
              e.clientX >= wr.left &&
              e.clientX <= wr.right &&
              e.clientY >= wr.top &&
              e.clientY <= wr.bottom,
          )
        }
      },
      onPointerUp: (e: React.PointerEvent) => {
        const drag = dragRef.current
        dragRef.current = null
        setGhost(null)
        setWellOver(false)
        if (!drag) return
        if (drag.moved) {
          const wr = wellRef.current?.getBoundingClientRect()
          const over =
            !!wr &&
            e.clientX >= wr.left &&
            e.clientX <= wr.right &&
            e.clientY >= wr.top &&
            e.clientY <= wr.bottom
          if (over) dropPayload(drag.payload)
        } else {
          tapPayload(drag.payload)
        }
      },
      onPointerCancel: () => {
        dragRef.current = null
        setGhost(null)
        setWellOver(false)
      },
    }),
    [ghostFor, dropPayload, tapPayload],
  )

  const onWellClick = useCallback(() => {
    if (picked) {
      if (picked.kind === 'stone') doCast(castStone(picked.cairn, picked.stone))
      else if (picked.kind === 'initiative') {
        const t = castInitiative(picked.cairn)
        if (t) doCast(t)
      } else doCast(castLooseStone(picked.stone))
      return
    }
    if (openProjectId && data) {
      const cairn = data.garden.cairns.find((c) => c.projectId === openProjectId)
      if (cairn) doCast(castProject(cairn))
      return
    }
    if (openInitiativeId && data) {
      const pile = ringInitiatives(data.garden).find((p) => p.initiativeId === openInitiativeId)
      const t = pile ? castInitiative(pile.cairns[0]) : null
      if (t) doCast(t)
    }
  }, [picked, openProjectId, openInitiativeId, data, doCast])

  /* After a turn lands in the subject conversation, re-read its
     recorded talk: depths refresh, and the seat who just spoke comes
     forward and re-forms. */
  const onTurnSent = useCallback(() => {
    if (!cast) return
    void fetchSeatTurnCounts(conversationId).then((turns) => {
      setTurnCounts(turns.counts)
      const keystone = depthProject ? data?.keystoneCounts.get(depthProject) : undefined
      depthsRef.current = depthsForSubject(turns.counts, keystone)
      const voice = turns.lastArchetype ? VOICE_BY_ARCHETYPE[turns.lastArchetype] : null
      if (voice) respond(voice)
    })
  }, [cast, conversationId, respond, data, depthProject])

  /* The ring's shown set — parents + loose only: initiative
     piles, loose project cairns, standalone stones — laid out by
     gardenLayout, which guarantees their labels never overlap.
     Memoised on the garden: the layout is relaxation work and
     must not re-run on interaction re-renders (drags, picks). */
  const gardenData = data?.garden ?? null
  const { ringItems, placements } = useMemo(() => {
    if (!gardenData) return { ringItems: [] as RingItem[], placements: [] as GardenPlacement[] }
    const items: RingItem[] = [
      ...ringInitiatives(gardenData).map(
        (pile): RingItem => ({ key: `ini-${pile.initiativeId}`, kind: 'initiative', pile }),
      ),
      ...looseCairns(gardenData).map(
        (cairn): RingItem => ({ key: cairn.cairnId, kind: 'cairn', cairn }),
      ),
      ...gardenData.looseStones.map(
        (stone): RingItem => ({ key: `loose-${stone.taskId}`, kind: 'loose', stone }),
      ),
    ]
    const placed = gardenLayout(
      items.map((item) => {
        if (item.kind === 'loose') {
          const layout = towerLayoutForMembers(
            `atelier-loose-${item.stone.taskId}`,
            item.stone.members,
          )
          return gardenFootprint({
            title: item.stone.title,
            pileWidthPx: 54,
            pileHeightPx: (layout.height + 10) * (54 / layout.width),
            showCount: false,
          })
        }
        const pileId = item.kind === 'initiative' ? item.pile.pileId : item.cairn.cairnId
        const members = item.kind === 'initiative' ? item.pile.members : item.cairn.members
        const layout = towerLayoutForMembers(pileId, members)
        return gardenFootprint({
          title: item.kind === 'initiative' ? item.pile.title : item.cairn.projectTitle,
          pileWidthPx: 104,
          pileHeightPx: (layout.height + 10) * (104 / layout.width),
          showCount: true,
        })
      }),
    )
    return { ringItems: items, placements: placed }
  }, [gardenData])

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
  if (!data) {
    return (
      <div className="flex-1 p-6">
        <p className="text-sm text-stone-400">Walking to the well…</p>
      </div>
    )
  }

  const garden = data.garden
  const openCairn = openProjectId
    ? (garden.cairns.find((c) => c.projectId === openProjectId) ?? null)
    : null
  const initiativePiles = ringInitiatives(garden)
  const openPile = openInitiativeId
    ? (initiativePiles.find((p) => p.initiativeId === openInitiativeId) ?? null)
    : null

  /* The ring's shown set + layout come from the memo above the
     early returns (ringItems / placements). */
  const anchorOf = (key: string): { x: number; y: number } => {
    const i = ringItems.findIndex((r) => r.key === key)
    return placements[i] ?? { x: 50, y: 16 }
  }
  const openAnchor = openCairn
    ? anchorOf(
        openCairn.initiativeId && openInitiativeId === openCairn.initiativeId
          ? `ini-${openCairn.initiativeId}`
          : openCairn.cairnId,
      )
    : openPile
      ? anchorOf(`ini-${openPile.initiativeId}`)
      : null
  const castSub =
    cast?.scope === 'task'
      ? cast.cairn.projectTitle
      : cast?.scope === 'project'
        ? `The whole cairn — all ${cast.cairn.stones.length} stones`
        : cast?.scope === 'initiative'
          ? `The whole undertaking — ${garden.cairns.filter((c) => c.initiativeId === cast.initiativeId).length} cairns`
          : cast
            ? 'A single stone'
            : ''

  return (
    <>
      <SplitShell
        storageKey="aria-atelier"
        left={
          <div className="p-3 lg:p-5 space-y-3">
        {cast ? (
          <CastView
            cast={cast}
            castSub={castSub}
            formingKey={formingKey}
            castWaterRef={castWaterRef}
            order={order}
            fillImgRefs={fillImgRefs}
            layerRefs={layerRefs}
            selectedVoice={selectedVoice}
            ceiling={ceiling}
            setCeiling={setCeiling}
            onSelectVoice={(v) => {
              if (v === 'all') {
                setSelectedVoice('all')
                setOrder(STACK_DEFAULT)
                stackAnim.current.replay = null
                for (const el of layerRefs.current.values()) {
                  el.style.maskImage = ''
                  el.style.webkitMaskImage = ''
                }
              } else {
                respond(v)
              }
            }}
            onReturn={returnToGarden}
          />
        ) : (
          <div className="atelier-garden" data-testid="atelier-garden">
            <span className="atelier-garden-rock" style={{ left: '4%', top: '66%', width: 52, height: 34 }} />
            <span className="atelier-garden-rock" style={{ left: '88%', top: '70%', width: 40, height: 27 }} />
            <span className="atelier-garden-moss" style={{ left: '2%', top: '60%', width: 90, height: 44 }} />
            <span className="atelier-garden-moss" style={{ left: '84%', top: '64%', width: 80, height: 40 }} />
            <button
              ref={wellRef}
              type="button"
              className={`atelier-well${picked || openCairn || openPile ? ' awaiting' : ''}${wellOver ? ' dragover' : ''}`}
              aria-label="The well"
              onClick={onWellClick}
            >
              <canvas ref={gardenWaterRef} className="atelier-water" width={352} height={352} aria-hidden="true" />
              {casting || rippleKey > 0 ? (
                <>
                  <span key={`r1-${rippleKey}`} className={`atelier-well-ring${casting ? ' go' : ''}`} />
                  <span
                    key={`r2-${rippleKey}`}
                    className={`atelier-well-ring${casting ? ' go' : ''}`}
                    style={{ animationDelay: '.18s' }}
                  />
                </>
              ) : null}
            </button>

            {ringItems.map((item, i) => {
              const pos = placements[i]
              if (item.kind === 'initiative') {
                const pile = item.pile
                const isOpen = openInitiativeId === pile.initiativeId
                return (
                  <div
                    key={item.key}
                    className={`atelier-cairn${isOpen ? ' open' : ''}`}
                    style={{
                      left: `${pos.x}%`,
                      top: `${pos.y}%`,
                      transform: `translate(-50%, -56%) scale(${pos.scale})`,
                    }}
                    data-initiative={pile.initiativeId}
                  >
                    <button
                      type="button"
                      className="atelier-cairn-stack"
                      aria-expanded={isOpen}
                      aria-label={pile.title}
                      {...dragHandlers({ kind: 'initiativePile', pile })}
                    >
                      <PileView pileId={pile.pileId} members={pile.members} width={104} />
                      <span className="atelier-cairn-name">{pile.title}</span>
                      <span className="atelier-cairn-count">
                        {pile.stoneCount} {pile.stoneCount === 1 ? 'stone' : 'stones'}
                      </span>
                    </button>
                  </div>
                )
              }
              if (item.kind === 'loose') {
                const layout = towerLayoutForMembers(
                  `atelier-loose-${item.stone.taskId}`,
                  item.stone.members,
                )
                const stone = layout.stones.find((x) => x.role !== 'slab') ?? layout.stones[0]
                const scale = 54 / layout.width
                return (
                  <button
                    key={`loose-${item.stone.taskId}`}
                    type="button"
                    className="atelier-loose"
                    style={{
                      left: `${pos.x}%`,
                      top: `${pos.y}%`,
                      transform: `translate(-50%, -56%) scale(${pos.scale})`,
                    }}
                    aria-label={item.stone.title}
                    {...dragHandlers({ kind: 'loose', stone: item.stone })}
                  >
                    <span
                      style={{
                        position: 'relative',
                        display: 'block',
                        width: 54,
                        height: (layout.height + 10) * scale,
                      }}
                    >
                      {stone ? (
                        <span
                          className="stone-pos"
                          style={{
                            left: stone.left * scale,
                            top: stone.top * scale,
                            width: stone.width * scale,
                            height: stone.height * scale,
                          }}
                        >
                          <CairnStoneSprite src={stone.spriteUrl} tint={stone.tint} />
                        </span>
                      ) : null}
                    </span>
                    <span className="atelier-cairn-name">{item.stone.title}</span>
                  </button>
                )
              }
              const cairn = item.cairn
              const isOpen = openProjectId === cairn.projectId
              return (
                <div
                  key={item.key}
                  className={`atelier-cairn${isOpen ? ' open' : ''}`}
                  style={{
                    left: `${pos.x}%`,
                    top: `${pos.y}%`,
                    transform: `translate(-50%, -56%) scale(${pos.scale})`,
                  }}
                  data-cairn={cairn.projectId}
                >
                  <button
                    type="button"
                    className="atelier-cairn-stack"
                    aria-expanded={isOpen}
                    aria-label={cairn.projectTitle}
                    {...dragHandlers({ kind: 'cairnBase', cairn })}
                  >
                    <PileView
                      pileId={cairn.cairnId}
                      members={cairn.members}
                      width={104}
                      layoutRef={(l) => layoutsRef.current.set(cairn.cairnId, l)}
                    />
                    <span className="atelier-cairn-name">{cairn.projectTitle}</span>
                    <span className="atelier-cairn-count">
                      {cairn.stones.length} {cairn.stones.length === 1 ? 'stone' : 'stones'}
                    </span>
                  </button>
                </div>
              )
            })}

            {openCairn ? (
              <FanView
                cairn={openCairn}
                anchor={openAnchor ?? { x: 50, y: 16 }}
                returnTo={
                  openPile && openCairn.initiativeId === openPile.initiativeId ? openPile : null
                }
                onReturn={() => setOpenProjectId(null)}
                picked={picked}
                dragHandlers={dragHandlers}
                layout={layoutsRef.current.get(openCairn.cairnId) ?? null}
              />
            ) : openPile ? (
              <InitiativeFan
                pile={openPile}
                anchor={openAnchor ?? { x: 50, y: 16 }}
                picked={picked}
                dragHandlers={dragHandlers}
              />
            ) : null}

            {ringItems.length === 0 ? (
              <p
                className="text-sm"
                style={{
                  position: 'absolute',
                  left: '50%',
                  bottom: '6%',
                  transform: 'translateX(-50%)',
                  color: '#5c5546',
                }}
              >
                The garden is empty.
              </p>
            ) : null}
          </div>
        )}
          </div>
        }
        right={
          <div className="p-3">
            <div className="rounded-2xl border border-stone-700/60 bg-stone-900/70 p-2">
              <CouncilChat
                key={conversationId}
                environment="workspace"
                initialArchetypeId="conductor"
                conversationId={conversationId}
                context={chatContext}
                onTurnSent={onTurnSent}
              />
            </div>
          </div>
        }
      />

      {ghost ? (
        <div className="atelier-drag-ghost" style={{ left: ghost.x, top: ghost.y }} aria-hidden="true">
          <span style={{ position: 'relative', display: 'block', width: 44, height: 30 }}>
            <CairnStoneSprite src={ghost.spriteUrl} tint={ghost.tint} />
          </span>
          <span>{ghost.title}</span>
        </div>
      ) : null}
    </>
  )
}

/* ================================================================== */
/* The fans — a cairn opened beside itself; an initiative opened to    */
/* its projects                                                        */
/* ================================================================== */

/** Where a fan sits relative to its ring anchor: centred on the
 *  anchor, below it — or above it when the anchor stands low. */
function fanPosition(anchor: { x: number; y: number }): { left: number; top: number } {
  return {
    left: Math.max(38, Math.min(62, anchor.x)),
    top: anchor.y > 70 ? anchor.y - 24 : anchor.y + 7,
  }
}

function FanView({
  cairn,
  anchor,
  returnTo,
  onReturn,
  picked,
  dragHandlers,
  layout,
}: {
  cairn: AtelierCairn
  anchor: { x: number; y: number }
  /** The initiative this fan was reached through, if any — the
   *  fan carries the way back to its fan. */
  returnTo: AtelierInitiativePile | null
  onReturn: () => void
  picked: Picked
  dragHandlers: (p: DragPayload) => React.HTMLAttributes<HTMLButtonElement>
  layout: PortedTowerLayout | null
}) {
  const { left: fanX, top: fanTop } = fanPosition(anchor)
  const pileLayout = layout ?? towerLayoutForMembers(cairn.cairnId, cairn.members)
  const initiative = castInitiative(cairn)
  return (
    <div className="atelier-fan-layer">
      <div className="atelier-fan" style={{ left: `${fanX}%`, top: `${fanTop}%` }}>
        {returnTo ? (
          <button
            type="button"
            className="atelier-fan-stone"
            aria-label={`Back to ${returnTo.title}`}
            onClick={onReturn}
          >
            <span>‹ {returnTo.title}</span>
          </button>
        ) : null}
        {initiative ? (
          <button
            type="button"
            className={`atelier-fan-stone${picked?.kind === 'initiative' && picked.cairn.projectId === cairn.projectId ? ' picked' : ''}`}
            aria-label={`${cairn.initiativeTitle} — the whole undertaking, from ${cairn.projectTitle}`}
            {...dragHandlers({ kind: 'initiative', cairn })}
          >
            <span className="stone-sprite" style={{ width: 52, height: 25 }}>
              <CairnStoneSprite src={CAIRN_SPRITES['cairn-slab'].url} tint={NEUTRAL_WASH} />
            </span>
            <span>{cairn.initiativeTitle}</span>
          </button>
        ) : null}
        {cairn.stones.map((stone) => {
          const s = spriteForMember(pileLayout, stone.memberId)
          return (
            <button
              key={stone.taskId}
              type="button"
              className={`atelier-fan-stone${picked?.kind === 'stone' && picked.stone.taskId === stone.taskId ? ' picked' : ''}`}
              aria-label={`${stone.title} — from ${cairn.projectTitle}`}
              {...dragHandlers({ kind: 'stone', cairn, stone })}
            >
              <span className="stone-sprite" style={{ width: 40, height: 32 }}>
                <CairnStoneSprite src={s.spriteUrl} tint={s.tint} />
              </span>
              <span>{stone.title}</span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

/**
 * An initiative opened: its project cairns laid out as fan stones,
 * headed by the undertaking itself as a castable stone. Tapping a
 * project steps the fan into that project (fanProject); dragging
 * any stone to the well casts its scope, as everywhere here.
 */
function InitiativeFan({
  pile,
  anchor,
  picked,
  dragHandlers,
}: {
  pile: AtelierInitiativePile
  anchor: { x: number; y: number }
  picked: Picked
  dragHandlers: (p: DragPayload) => React.HTMLAttributes<HTMLButtonElement>
}) {
  const { left: fanX, top: fanTop } = fanPosition(anchor)
  const representative = pile.cairns[0]
  return (
    <div className="atelier-fan-layer">
      <div className="atelier-fan" style={{ left: `${fanX}%`, top: `${fanTop}%` }}>
        <button
          type="button"
          className={`atelier-fan-stone${picked?.kind === 'initiative' && picked.cairn.projectId === representative.projectId ? ' picked' : ''}`}
          aria-label={`${pile.title} — the whole undertaking`}
          {...dragHandlers({ kind: 'initiative', cairn: representative })}
        >
          <span className="stone-sprite" style={{ width: 52, height: 25 }}>
            <CairnStoneSprite src={CAIRN_SPRITES['cairn-slab'].url} tint={NEUTRAL_WASH} />
          </span>
          <span>{pile.title}</span>
        </button>
        {pile.cairns.map((cairn) => (
          <button
            key={cairn.projectId}
            type="button"
            className="atelier-fan-stone"
            aria-label={cairn.projectTitle}
            {...dragHandlers({ kind: 'fanProject', cairn })}
          >
            <span className="stone-sprite" style={{ width: 52, height: 25 }}>
              <CairnStoneSprite src={CAIRN_SPRITES['cairn-slab'].url} tint={NEUTRAL_WASH} />
            </span>
            <span>{cairn.projectTitle}</span>
            <span>
              {cairn.stones.length} {cairn.stones.length === 1 ? 'stone' : 'stones'}
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}

/* ================================================================== */
/* The cast — the well grown large, the stack forming on its water     */
/* ================================================================== */

function CastView({
  cast,
  castSub,
  formingKey,
  castWaterRef,
  order,
  fillImgRefs,
  layerRefs,
  selectedVoice,
  ceiling,
  setCeiling,
  onSelectVoice,
  onReturn,
}: {
  cast: CastTarget
  castSub: string
  formingKey: number
  castWaterRef: React.Ref<HTMLCanvasElement>
  order: Voice[]
  fillImgRefs: { current: Map<Voice, HTMLImageElement> }
  layerRefs: { current: Map<Voice, HTMLDivElement> }
  selectedVoice: Voice | 'all'
  ceiling: number
  setCeiling: (n: number) => void
  onSelectVoice: (v: Voice | 'all') => void
  onReturn: () => void
}) {
  return (
    <div>
      <div className="atelier-cast">
        <div className="atelier-cast-rim">
          <button type="button" className="atelier-return" onClick={onReturn}>
            ‹ Garden
          </button>
          <div className="atelier-cast-circle forming" data-testid="atelier-cast-circle">
            <canvas ref={castWaterRef} className="atelier-water" width={352} height={352} aria-hidden="true" />
            <div
              className="atelier-geometry"
              key={formingKey}
              role="img"
              aria-label="Seven layers, forming in the well."
            >
              <div
                className="atelier-layer-stack"
                style={{ height: `${FORMATION_SCALE * 100}%` }}
              >
                {VOICES.map((v) => (
                  <div
                    key={v}
                    className="atelier-voice-layer"
                    data-layer={v}
                    ref={(el) => {
                      if (el) layerRefs.current.set(v, el)
                    }}
                    style={{ zIndex: order.indexOf(v) + 1 }}
                  >
                    <img
                      className="fill"
                      src={LAYER_IMAGES[v].fill}
                      alt=""
                      ref={(el) => {
                        if (el) fillImgRefs.current.set(v, el)
                      }}
                    />
                    <img className="ink" src={LAYER_IMAGES[v].ink} alt="" />
                  </div>
                ))}
              </div>
            </div>
            <span className="atelier-cast-shade" aria-hidden="true" />
          </div>
        </div>
        <div className="atelier-cast-subject">{cast.title}</div>
        <div className="atelier-cast-cairn">{castSub}</div>
      </div>

      <div className="atelier-controls">
        <div className="atelier-slider-row">
          <span>Discussion</span>
          <input
            type="range"
            min={10}
            max={80}
            value={ceiling}
            aria-label="Discussion"
            onChange={(e) => setCeiling(Number(e.target.value))}
          />
          <span>{ceiling}%</span>
        </div>
        <div className="atelier-voice-chips">
          <button
            type="button"
            aria-pressed={selectedVoice === 'all'}
            onClick={() => onSelectVoice('all')}
          >
            <span className="dot" style={{ background: '#9a917e' }} />
            All seven
          </button>
          {VOICES.map((v) => (
            <button
              key={v}
              type="button"
              aria-pressed={selectedVoice === v}
              onClick={() => onSelectVoice(v)}
              style={{ '--voice': VOICE_COLORS[v] } as React.CSSProperties}
            >
              <span className="dot" style={{ background: VOICE_COLORS[v] }} />
              {VOICE_NAMES[v]}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
