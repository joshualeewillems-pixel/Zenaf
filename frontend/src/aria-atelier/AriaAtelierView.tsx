/**
 * Aria's Atelier — the Well, as a production surface.
 *
 * This view is Aria's landing: tapping her tree node navigates the
 * shell here (LivingTree's SEAT_HOME_NAV; her sheet keeps its
 * own door), and the layout is the shared SplitShell — the world on
 * the left, her conversation on the right, a draggable divider
 * between them, each pane scrolling on its own.
 *
 * Aria's view opens on her garden as the founder painted it
 * (Screen 1, ruled 2026-11-27): the Zenaf sky over raked sand, the
 * stone basin at the centre holding the well of rainbow
 * interference water (the Resonance Atelier field engine, ported
 * whole — ./waterEngine), cairns standing on the sand around it.
 * The live water element sits over the painting's basin ellipse,
 * squashed to its perspective; the cast opens on the second
 * painting (Screen 2) — the same garden from above once a stone
 * is thrown in — with the live water and the formation stack
 * clipped to its well disc, the painting's own ring and lotus
 * standing above the water. The cairns are the user's real
 * Vision-map cairns — the map's own graph build piles each
 * project subtree, and the piles here are rendered by the map's
 * tower layout and sprite component from the same members.
 * Nothing is fixture, nothing is redrawn.
 *
 * The shown set follows the standing display rule (founder,
 * 2026-11-24 — parents and loose items only): one cairn per
 * INITIATIVE (the union of its projects' piles), plus the loose
 * projects and the standalone stones. An initiative's project
 * cairns appear in its fan when the initiative is opened; a
 * project's stones appear in its own fan, as before — every
 * record stays reachable through its parent. The items stand on
 * painted-scene seats (scenePlacements in ./atelierLogic), which
 * guarantees the shown cairns' name labels never overlap, never
 * leave the scene, AND no footprint — pile, label, count line —
 * ever covers the basin ellipse: the water is water, and nothing
 * stands on it (founder, 2026-11-25). The fans are placed under
 * the same rule (fanPositionClear).
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
 * The stack's channels are the founder's rulings, and the imagery
 * is system data (founder, 2026-11-25: "build the real thing..
 * there shouldn't be buttons to press, the imagery is supposed to
 * represent system data"). The formations genuinely DRAW: each
 * voice's ink is a ladder of transparent stage images generated
 * from the canonical geometry in its true growth order (see
 * ./stagegen and stage-manifest.json — every stage a true prefix
 * of the next, the final stage the completed formation, verified
 * against the canonical geometry by hash). When a seat responds,
 * its formation re-draws from nothing to its recorded talk depth
 * about the selected subject, holds there — what stands is the
 * formation drawn to exactly that fraction — then completes, and
 * its fill washes in beneath the ink. Layers are ordered by
 * interaction recency; fill presence is graded per voice from the
 * recorded data alone (who has spoken about this subject, and who
 * spoke last — fillPresence in ./atelierLogic) on a base-e
 * approach inside the ruled 10%–80% band; ink is always at 100%.
 * There are NO manual imagery controls — no Discussion slider, no
 * voice chips; the only interactions are choosing and casting a
 * subject, and the conversation. No paper anywhere: the stages
 * and fills are transparent, and the water shows through.
 *
 * Dynamism (founder-reviewed spec, 2026-11-25): the formations'
 * presence changes the water, and the water reveals their
 * relationships. The field answers EVENTS — a cast landing, a
 * seat responding, a formation arriving pulse the water through
 * that seat's own wave basis (ResonanceField.pulse); a fill
 * wash-in completing answers at half strength, as the rendering
 * milestone it is. The layers also ride their voices' phases
 * (buoyancy — EXPERIMENTAL, kept or removed by the founder's
 * on-device comparison against the ?still=1 stationary cast), and
 * one gated refraction twin stands beneath Lucian's ink
 * (./stageTwins). Nothing here moves on a timer, a hover, or a
 * scroll; under reduced motion none of it moves at all.
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
  SCENE1_BASIN,
  SCENE1_LOTUS_OVERLAY,
  SCENE1_WELL_SCALE_Y,
  SCENE2_DISC,
  SCENE2_LOTUS_OVERLAY,
  STACK_DEFAULT,
  STAGE_COUNT,
  VOICES,
  VOICE_BY_ARCHETYPE,
  bringToFront,
  buoyancyTransform,
  castInitiative,
  castLooseStone,
  castProject,
  castStone,
  chatContextFor,
  conversationIdFor,
  depthProjectId,
  depthsForSubject,
  fanBoxFor,
  fanPositionClear,
  fillMultiplier,
  fillStep,
  gardenFootprint,
  looseCairns,
  ringInitiatives,
  scenePlacements,
  stageForDepth,
  stillComparisonIn,
  twinOffset,
  REPLAY_BASE_MS,
  REPLAY_COMPLETE_MS,
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
import { STAGE_IMAGES } from './stageImages'
import { twinForStage } from './stageTwins'
import { ResonanceField } from './waterEngine'
import SeatGate from '../components/SeatGate'
import { useImagePreloadGate } from '../imagePreload'
import { SEAT_COLORS } from '../council/colors'
import conductorLogo from '../assets/seats/conductor-logo.png'
import { atelierPreloader } from './atelierPreload'
import './atelier.css'

import ariaFill from './assets/layer-aria-fill.png'
import jynxFill from './assets/layer-jynx-fill.png'
import lucianFill from './assets/layer-lucian-fill.png'
import maeveFill from './assets/layer-maeve-fill.png'
import rumiFill from './assets/layer-rumi-fill.png'
import severineFill from './assets/layer-severine-fill.png'
import valenFill from './assets/layer-valen-fill.png'

/* The founder's two paintings (ruled 2026-11-27): Screen 1, the
 * garden with the Zenaf sky and our water composited into the
 * basin; Screen 2, the same garden from above once a stone is
 * thrown in. Neither painting's inner stone ring is carried —
 * the founder ruled the well-within-a-well obstructive — and
 * each painting's lotus rides above the live water as an
 * overlay. */
import gardenScene1 from './assets/garden-scene1.webp'
import gardenScene1Lotus from './assets/garden-scene1-lotus.png'
import gardenScene2 from './assets/garden-scene2.webp'
import gardenScene2Lotus from './assets/garden-scene2-lotus.png'

/** A scene fraction as a CSS percentage string. */
const pct = (f: number): string => `${Math.round(f * 10000) / 100}%`

/** The voices' fill layers (the canonical fills, regenerated by
 *  ./stagegen from build_pure's own construction). The ink above
 *  them is the stage ladder — STAGE_IMAGES — not a single image. */
const FILL_IMAGES: Record<Voice, string> = {
  rumi: rumiFill,
  valen: valenFill,
  maeve: maeveFill,
  lucian: lucianFill,
  aria: ariaFill,
  severine: severineFill,
  jynx: jynxFill,
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
  /* The door (founder, 2026-11-28): the atelier's paintings
   * — every formation stage, fill layer and garden scene —
   * warm behind Aria's pulsing logo before the well paints. */
  const assetsReady = useImagePreloadGate(atelierPreloader)
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
  const [order, setOrder] = useState<Voice[]>(STACK_DEFAULT)
  /** Who spoke last in the subject conversation (recorded data —
   *  the graded fill's recency input), or null when no seat has
   *  spoken about the subject. */
  const [lastVoice, setLastVoice] = useState<Voice | null>(null)
  /** Each voice's currently drawn stage, 0..STAGE_COUNT. At rest
   *  every formation stands complete (STAGE_COUNT); a responding
   *  voice's stage runs the replay: 0 → its depth stage → hold →
   *  complete. */
  const [inkStages, setInkStages] = useState<Record<Voice, number>>(
    Object.fromEntries(VOICES.map((v) => [v, STAGE_COUNT])) as Record<Voice, number>,
  )
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
  const twinImgRefs = useRef(new Map<Voice, HTMLImageElement>())
  /** The last transform string written per layer (and per twin,
   *  keyed `${voice}:twin`) — dynamism style writes happen only
   *  when the value actually changes. */
  const transformWritten = useRef(new Map<string, string>())
  const fillState = useRef<Record<Voice, number>>(
    Object.fromEntries(VOICES.map((v) => [v, 1])) as Record<Voice, number>,
  )
  const stackAnim = useRef<{
    raf: number
    last: number
    replay: {
      voice: Voice
      depth: number
      phase: 'draw' | 'hold' | 'complete'
      startedAt: number
      phaseAt: number
    } | null
    /** Voices whose replay has finished and whose fill is now
     *  washing in: when the fill reaches its graded target, the
     *  wash-in is complete and the water answers at half strength
     *  (the rendering-milestone response, dynamism spec §2.2). */
    wash: Set<Voice>
  }>({ raf: 0, last: 0, replay: null, wash: new Set() })
  const respondedFor = useRef<string | null>(null)
  /* The still comparison (dynamism spec §2.1's perceptual gate):
   * ?still=1, read ONCE at mount — acceptance tooling for the
   * founder's on-device buoyancy verdict, never a control, never
   * persisted. While set, every dynamism rendering is still:
   * buoyancy transforms stay identity and the twin sits at zero
   * offset. The water's own motion predates this pass and is not
   * stilled. */
  const [stillComparison] = useState(
    () => typeof window !== 'undefined' && stillComparisonIn(window.location.search),
  )
  const buoyancyOn = !REDUCED_MOTION && !stillComparison

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
    /* Under reduced motion the field answers nothing (spec §4). */
    field.reducedMotion = REDUCED_MOTION
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

  const lastVoiceRef = useRef<Voice | null>(null)
  useEffect(() => {
    lastVoiceRef.current = lastVoice
  }, [lastVoice])

  const orderRef = useRef(order)
  useEffect(() => {
    orderRef.current = order
  }, [order])

  /* On a cast, load the subject conversation's recorded talk, then
     Aria responds: her layer comes forward and re-draws to her
     recorded depth. */
  useEffect(() => {
    if (!cast) {
      setTurnCounts(null)
      setLastVoice(null)
      respondedFor.current = null
      return
    }
    let cancelled = false
    setTurnCounts(null)
    void fetchSeatTurnCounts(conversationId).then((turns) => {
      if (cancelled) return
      setTurnCounts(turns.counts)
      setLastVoice(turns.lastArchetype ? (VOICE_BY_ARCHETYPE[turns.lastArchetype] ?? null) : null)
    })
    return () => {
      cancelled = true
    }
  }, [cast, conversationId])

  /* A seat responds: its layer comes forward (z-order by recency)
     and its formation re-draws — the stage ladder runs from
     nothing to its recorded depth, holds, then completes, and
     only then does its fill wash in (the animation loop owns the
     fill while a replay runs). Reduced motion: the completed
     formation simply stands, as it already does at rest. */
  const respond = useCallback((voice: Voice) => {
    setOrder((o) => bringToFront(o, voice))
    if (REDUCED_MOTION) return
    // Preload the ladder so the drawing's steps don't flicker
    // while their images arrive.
    for (const src of STAGE_IMAGES[voice]) {
      const im = new Image()
      im.src = src
    }
    setInkStages((s) => ({ ...s, [voice]: 0 }))
    stackAnim.current.replay = {
      voice,
      depth: depthsRef.current[voice],
      phase: 'draw',
      startedAt: performance.now(),
      phaseAt: performance.now(),
    }
    stackAnim.current.wash.delete(voice)
    /* Dynamism, record events (spec §2.2): a seat responding and
     * its formation arriving are this one seam — the response IS
     * the arrival — so the water answers once, at full strength,
     * through the responding seat's own wave basis; the ripple
     * beat fires on the arrival too. */
    fieldRef.current?.pulse(voice, 1)
    setRippleKey((k) => k + 1)
  }, [])

  useEffect(() => {
    if (!cast || turnCounts === null) return
    if (respondedFor.current === conversationId) return
    respondedFor.current = conversationId
    respond('aria')
  }, [cast, turnCounts, conversationId, respond])

  /* --------------------- stack animation loop ----------------------- */
  /* One rAF loop drives both ruled motions while a cast is open:
     the fills' base-e approach toward their graded targets, and
     the responding voice's replay — its stage ladder stepping
     from nothing out to its recorded talk-depth stage, a held
     beat at exactly that stage, then the remaining stages to the
     completed formation, at which point its fill target becomes
     its graded presence and the fill washes in beneath the ink.
     While a voice's replay runs, its fill target is 0: the fill
     belongs to the completed formation (fill completes it). All
     targets derive from the recorded depths + last speaker, read
     through refs — no control state exists to read. */

  useEffect(() => {
    if (!cast) return
    const anim = stackAnim.current
    anim.last = performance.now()
    const step = (now: number) => {
      anim.raf = requestAnimationFrame(step)
      const dt = Math.min(0.1, (now - anim.last) / 1000)
      anim.last = now
      const replay = anim.replay
      const field = fieldRef.current
      for (const v of VOICES) {
        /* Dynamism rendering rides this loop — no loop of its
         * own (spec §3). Buoyancy: the voice's layer rides its
         * own phase in the field, drift scaled by recency rank.
         * The refraction twin (where one stands) additionally
         * carries its phase offset. While the still comparison
         * is in force — or under reduced motion — nothing is
         * written at all: transforms stay identity and the twin
         * sits at zero offset. */
        if (buoyancyOn) {
          const phase = field?.phaseOf(v) ?? 0
          const rankFromFront = VOICES.length - 1 - orderRef.current.indexOf(v)
          const layer = layerRefs.current.get(v)
          if (layer) {
            const t = buoyancyTransform(phase, rankFromFront)
            const str = `translate(${t.dx}px, ${t.dy}px) scale(${t.scale.toFixed(4)})`
            if (transformWritten.current.get(v) !== str) {
              transformWritten.current.set(v, str)
              layer.style.transform = str
            }
          }
          const twin = twinImgRefs.current.get(v)
          if (twin) {
            const o = twinOffset(phase)
            const str = `translate(${o.dx}px, ${o.dy}px)`
            if (transformWritten.current.get(`${v}:twin`) !== str) {
              transformWritten.current.set(`${v}:twin`, str)
              twin.style.transform = str
            }
          }
        }
        const img = fillImgRefs.current.get(v)
        if (!img) continue
        const target =
          replay && replay.voice === v
            ? 0
            : fillMultiplier(v, depthsRef.current, lastVoiceRef.current)
        const next = fillStep(fillState.current[v], target, dt)
        if (next !== fillState.current[v]) {
          fillState.current[v] = next
          img.style.opacity = next.toFixed(3)
        }
        /* The wash-in completing is a RENDERING MILESTONE, not a
         * record event (spec §2.2's event contract): the water
         * answers it at half strength, once, and it is named as a
         * milestone response here so no reader mistakes it for a
         * fourth kind of meaning. */
        if (anim.wash.has(v) && next === target) {
          anim.wash.delete(v)
          field?.pulse(v, 0.5)
        }
      }
      if (replay) {
        const holdStage = stageForDepth(replay.depth)
        let stage: number | null = null
        if (replay.phase === 'draw') {
          const duration = REPLAY_BASE_MS / REPLAY_RATES[replay.voice]
          const p = Math.min(1, (now - replay.startedAt) / duration)
          stage = Math.floor(p * holdStage)
          if (p >= 1) {
            stage = holdStage
            replay.phase = 'hold'
            replay.phaseAt = now
          }
        } else if (replay.phase === 'hold') {
          stage = holdStage
          if (now - replay.phaseAt >= REPLAY_HOLD_MS) {
            replay.phase = 'complete'
            replay.phaseAt = now
          }
        } else {
          const p = Math.min(1, (now - replay.phaseAt) / REPLAY_COMPLETE_MS)
          stage = holdStage + Math.floor(p * (STAGE_COUNT - holdStage))
          if (p >= 1) {
            stage = STAGE_COUNT
            anim.replay = null
            /* The formation stands complete; its fill now washes
             * in, and the wash's completion is tracked for the
             * milestone response above. */
            anim.wash.add(replay.voice)
          }
        }
        if (stage !== null) {
          const s = stage
          const voice = replay.voice
          setInkStages((prev) => (prev[voice] === s ? prev : { ...prev, [voice]: s }))
        }
      }
    }
    anim.raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(anim.raf)
  }, [cast, buoyancyOn])

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
        /* Dynamism, record event (spec §2.2): the cast lands.
         * The water answers through Aria's own wave basis — the
         * cast lands in her well, and her response follows as its
         * own event. Full strength. */
        fieldRef.current?.pulse('aria', 1)
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
    setOrder(STACK_DEFAULT)
    setLastVoice(null)
    stackAnim.current.replay = null
    stackAnim.current.wash.clear()
    setInkStages(
      Object.fromEntries(VOICES.map((v) => [v, STAGE_COUNT])) as Record<Voice, number>,
    )
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
      setLastVoice(voice ?? null)
      if (voice) respond(voice)
    })
  }, [cast, conversationId, respond, data, depthProject])

  /* The ring's shown set — parents + loose only: initiative
     piles, loose project cairns, standalone stones — seated by
     scenePlacements, which guarantees their labels never overlap,
     never leave the scene, and never cover the basin. Memoised on
     the garden: the layout is relaxation work and must not re-run
     on interaction re-renders (drags, picks). */
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
    const placed = scenePlacements(
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
  if (!assetsReady) {
    return (
      <div className="flex-1 p-6">
        <SeatGate
          logo={conductorLogo}
          color={SEAT_COLORS.conductor}
          label="Preparing the Atelier…"
          testId="atelier-preload-gate"
        />
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
            twinImgRefs={twinImgRefs}
            inkStages={inkStages}
            onReturn={returnToGarden}
          />
        ) : (
          <div
            className="atelier-scene"
            data-testid="atelier-garden"
            style={{ backgroundImage: `url(${gardenScene1})` }}
          >
            <button
              ref={wellRef}
              type="button"
              className={`atelier-well${picked || openCairn || openPile ? ' awaiting' : ''}${wellOver ? ' dragover' : ''}`}
              style={{
                left: pct(SCENE1_BASIN.cx),
                top: pct(SCENE1_BASIN.cy),
                width: pct(SCENE1_BASIN.rx * 2),
                transform: `translate(-50%, -50%) scaleY(${SCENE1_WELL_SCALE_Y})`,
              }}
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
            <img
              className="atelier-scene-overlay"
              src={gardenScene1Lotus}
              alt=""
              aria-hidden="true"
              style={{
                left: pct(SCENE1_LOTUS_OVERLAY.left),
                top: pct(SCENE1_LOTUS_OVERLAY.top),
                width: pct(SCENE1_LOTUS_OVERLAY.width),
              }}
            />

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
  const stoneCount =
    (returnTo ? 1 : 0) + (cairn.initiativeId ? 1 : 0) + cairn.stones.length
  const { left: fanX, top: fanTop } = fanPositionClear(anchor, fanBoxFor(stoneCount))
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
  const { left: fanX, top: fanTop } = fanPositionClear(
    anchor,
    fanBoxFor(1 + pile.cairns.length),
  )
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
  twinImgRefs,
  inkStages,
  onReturn,
}: {
  cast: CastTarget
  castSub: string
  formingKey: number
  castWaterRef: React.Ref<HTMLCanvasElement>
  order: Voice[]
  fillImgRefs: { current: Map<Voice, HTMLImageElement> }
  /** Each voice's layer element — the animation loop writes the
   *  buoyancy transform here (dynamism spec §2.1). */
  layerRefs: { current: Map<Voice, HTMLDivElement> }
  /** Each voice's refraction twin element, where one stands —
   *  the loop writes its phase offset here (spec §2.3). */
  twinImgRefs: { current: Map<Voice, HTMLImageElement> }
  /** Each voice's currently drawn stage (0 = nothing drawn yet). */
  inkStages: Record<Voice, number>
  onReturn: () => void
}) {
  return (
    <div>
      <div
        className="atelier-scene"
        data-testid="atelier-cast-scene"
        style={{ backgroundImage: `url(${gardenScene2})` }}
      >
        <button type="button" className="atelier-return" onClick={onReturn}>
          ‹ Garden
        </button>
        <div
          className="atelier-cast-circle forming"
          data-testid="atelier-cast-circle"
          style={{
            left: pct(SCENE2_DISC.cx),
            top: pct(SCENE2_DISC.cy),
            width: pct(SCENE2_DISC.r * 2),
          }}
        >
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
                {VOICES.map((v) => {
                  const twin = inkStages[v] > 0 ? twinForStage(v, inkStages[v]) : undefined
                  return (
                    <div
                      key={v}
                      className="atelier-voice-layer"
                      data-layer={v}
                      style={{ zIndex: order.indexOf(v) + 1 }}
                      ref={(el) => {
                        if (el) layerRefs.current.set(v, el)
                      }}
                    >
                      <img
                        className="fill"
                        src={FILL_IMAGES[v]}
                        alt=""
                        ref={(el) => {
                          if (el) fillImgRefs.current.set(v, el)
                        }}
                      />
                      {twin ? (
                        <img
                          className="ink-twin"
                          src={twin.src}
                          alt=""
                          aria-hidden="true"
                          ref={(el) => {
                            if (el) twinImgRefs.current.set(v, el)
                          }}
                          onError={(e) => {
                            /* The twin is an enhancement layer,
                               never a dependency (spec §2.3): a
                               twin that fails to load hides itself
                               silently and the ink renders alone.
                               A broken-image glyph must never
                               appear. */
                            e.currentTarget.style.display = 'none'
                          }}
                        />
                      ) : null}
                      {inkStages[v] > 0 ? (
                        <img
                          className="ink"
                          src={STAGE_IMAGES[v][inkStages[v] - 1]}
                          alt=""
                        />
                      ) : null}
                    </div>
                  )
                })}
              </div>
            </div>
            <span className="atelier-cast-shade" aria-hidden="true" />
        </div>
        <img
          className="atelier-scene-overlay"
          src={gardenScene2Lotus}
          alt=""
          aria-hidden="true"
          style={{
            left: pct(SCENE2_LOTUS_OVERLAY.left),
            top: pct(SCENE2_LOTUS_OVERLAY.top),
            width: pct(SCENE2_LOTUS_OVERLAY.width),
          }}
        />
      </div>
      <div className="atelier-cast-captions">
        <div className="atelier-cast-subject">{cast.title}</div>
        <div className="atelier-cast-cairn">{castSub}</div>
      </div>
    </div>
  )
}
