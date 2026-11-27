/**
 * The Living Palace — the drawn world.
 *
 * Geometry and rendering lifted from the founder-ruled prototype
 * (maeve-s-living-palace-interactive-increment-1): the seven-tongue
 * council flame from a single source, the stone-ring bonfire, the
 * stone hearth, the continuous 2.5D floor plan (rooms sharing walls
 * around a real hall), and the room cutaway whose furniture sits IN
 * the skewed wall planes. The prototype's fixture is not used —
 * every scene renders the live models from palaceLogic.
 *
 * The compound layer is Scene 1 (founder, 2026-11-26): the
 * founder's own three-court plan art with the ivy buildings placed
 * by the ruled placement law — see the CompoundScene section and
 * palaceSceneLogic. The building layer is Scene 2 (founder,
 * 2026-11-26): the room-circles in their relaxed Apollonian
 * spacing — see the BuildingScene section and
 * palaceScene2Logic. The room layer is the founder's furnished
 * chamber (2026-11-26): his rose plate as the room itself, his
 * artifacts standing at the seats he marked in the studies —
 * see the RoomScene section. The floor-plan layer is RETIRED
 * (founder, 2026-11-26 20:07 PT): the dome serves both levels —
 * projects as circles, then the project's tasks as circles in
 * the same dome — see the TaskScene section.
 *
 * Surface rule: the scenes carry no legends, no vocabulary panels,
 * no explanations of themselves. What a tap reveals lives in the
 * view's panels and in Maeve's chat.
 */
import * as React from 'react'
import { useMemo } from 'react'
import type {
  BuildingModel,
  CompoundModel,
  RoomModel,
  TaskLevelModel,
} from './palaceLogic'
import { councilFlameColors, isDoneStatus } from './palaceLogic'
import {
  PALACE_GEOMETRY,
  classForNestedCount,
  indexInteractions,
  interactionKey,
  ivyColorFor,
  ivyStageFor,
  masterAspect,
  planCompoundScene,
  type PalaceClassId,
  type PlacedStructure,
  type SceneStructureInput,
  type SubjectInteraction,
} from './palaceSceneLogic'
import {
  CONTAINER_CLIP_PATH,
  SCENE2_FRAME,
  planBuildingScene,
  planTaskScene,
  taskSizeWeight,
  type RoomPlate,
} from './palaceScene2Logic'
import { useTintedMaster } from './palaceTint'
import { PLATE_URLS, glassColorFor, useGlassPlate } from './palaceGlass'
import planImage from './assets/palace-plan.jpg'
import frontWallImage from './assets/palace-front-wall.png'
import fireImage from './assets/palace-fire.png'
import vesselGoldImage from './assets/palace-vessel-gold.webp'
import vesselPlainImage from './assets/palace-vessel-plain.webp'
import scalesImage from './assets/palace-scales.webp'
import scalesWeighedImage from './assets/palace-scales-weighed.webp'
import chestImage from './assets/palace-chest.webp'
import chestOpenImage from './assets/palace-chest-open.webp'
import drawingTableImage from './assets/palace-drawing-table.webp'
import { BONSAI_ASPECT, BONSAI_BASE_LIFT, useBenchBonsaiImage } from './palacePlant'
import architectureImage from './assets/palace-architecture.webp'
import plateImage from '../assets/living-sky/plate.webp'
import { SEAT_COLORS, type SeatId } from '../council/colors'

/* The prototype's material palette. */
export const PAL = {
  ink: '#4a3f30',
  inkSoft: '#6b5b45',
  wall: '#e8ddc9',
  wallDark: '#d9c8a6',
  roof: '#8a6f4d',
  roofDark: '#755c3e',
  stone: '#b8a888',
  stoneDark: '#9a8a6c',
  wood: '#a97e4f',
  woodDark: '#8a6538',
  maeve: '#ac7c5b',
  paper: '#f7f1e3',
  hall: '#e2d3ae',
  ground: '#e6dcc0',
  groundDark: '#d8caa4',
  sky: '#f3ecda',
}

const WALL_LINE = '#8a7a5c'

function wrapTitle(title: string, per: number, maxLines: number): string[] {
  const words = title.split(/\s+/).filter(Boolean)
  const lines: string[] = []
  let cur = ''
  for (const w of words) {
    const next = cur ? `${cur} ${w}` : w
    if (next.length > per && cur) {
      lines.push(cur)
      cur = w
      if (lines.length === maxLines) break
    } else {
      cur = next
    }
  }
  if (cur && lines.length < maxLines) lines.push(cur)
  if (lines.length === maxLines && words.join(' ').length > lines.join(' ').length) {
    lines[maxLines - 1] = `${lines[maxLines - 1].replace(/…?$/, '')}…`
  }
  return lines
}

/* ------------------------------------------------------------------ */
/* the fire — one source, seven tongues                                */
/* ------------------------------------------------------------------ */

/** One tongue of the council fire — the prototype's path, verbatim:
 *  a lean toward the centre, the tip at (bx + lean, base − hh). */
function tonguePath(bx: number, base: number, ww: number, hh: number, lean: number): string {
  return (
    `M ${bx} ${base}` +
    ` C ${bx - ww} ${base - hh * 0.3}, ${bx - ww * 0.35 + lean} ${base - hh * 0.72}, ${bx + lean} ${base - hh}` +
    ` C ${bx + ww * 0.35 + lean} ${base - hh * 0.72}, ${bx + ww} ${base - hh * 0.3}, ${bx} ${base} Z`
  )
}

/** Every fire in the Palace burns in the seven council colours —
 *  this is the single flame source all of them draw from. Tongue
 *  placement is the prototype's: f = (i − 3)/3 across the fire, the
 *  centre tongue tallest. */
export function CouncilFlames({
  cx,
  base,
  h,
  w,
}: {
  cx: number
  base: number
  h: number
  w: number
}) {
  const colors = councilFlameColors()
  return (
    <g className="flame-flicker" pointerEvents="none">
      {colors.map((col, i) => {
        const f = (i - 3) / 3
        const bx = cx + f * w * 0.46
        const hh = h * (1 - Math.abs(f) * 0.34)
        const ww = w * 0.15 * (1 - Math.abs(f) * 0.12) + 1.2
        const lean = f * h * 0.1
        return <path key={i} d={tonguePath(bx, base, ww, hh, lean)} fill={col} opacity={0.92} />
      })}
    </g>
  )
}

export function Bonfire({ x, y, lit }: { x: number; y: number; lit: boolean }) {
  const stones = Array.from({ length: 9 }, (_, i) => {
    const a = (i / 9) * Math.PI * 2
    return { sx: x + Math.cos(a) * 44, sy: y + 10 + Math.sin(a) * 10 }
  })
  return (
    <g data-testid="palace-bonfire">
      <ellipse cx={x} cy={y + 12} rx={58} ry={16} fill={PAL.groundDark} />
      {lit && <ellipse cx={x} cy={y + 2} rx={40} ry={12} fill="#f2b04a" opacity={0.35} />}
      <g stroke={PAL.woodDark} strokeWidth={5} strokeLinecap="round">
        <line x1={x - 26} y1={y + 8} x2={x + 20} y2={y - 2} />
        <line x1={x + 26} y1={y + 8} x2={x - 20} y2={y - 2} />
        <line x1={x - 6} y1={y + 10} x2={x + 8} y2={y - 6} />
      </g>
      {lit ? (
        <CouncilFlames cx={x} base={y + 4} h={58} w={50} />
      ) : (
        <g fill="#c96a2c">
          <circle cx={x - 8} cy={y + 4} r={3} opacity={0.8} />
          <circle cx={x + 6} cy={y + 6} r={2.4} opacity={0.7} />
          <circle cx={x + 1} cy={y + 1} r={2} opacity={0.6} />
        </g>
      )}
      {stones.map((s, i) => (
        <ellipse key={i} cx={s.sx} cy={s.sy} rx={8} ry={5.5} fill={PAL.stone} stroke={PAL.stoneDark} />
      ))}
    </g>
  )
}

export function PlantGlyph({
  x,
  base,
  state,
  scale = 1,
}: {
  x: number
  base: number
  state: 'growing' | 'fruiting'
  scale?: number
}) {
  const s = scale
  return (
    <g pointerEvents="none" transform={`translate(${x} ${base}) scale(${s})`}>
      <path d="M -9 0 L 9 0 L 6.5 -11 L -6.5 -11 Z" fill="#b06a3b" stroke="#8a4f27" />
      <g stroke="#4f7a3d" strokeWidth={2.2} fill="none" strokeLinecap="round">
        <path d="M 0 -11 C -1 -20, -6 -24, -11 -27" />
        <path d="M 0 -11 C 0 -22, 2 -28, 0 -34" />
        <path d="M 0 -11 C 1 -20, 6 -24, 11 -27" />
      </g>
      <g fill="#5d8a46">
        <ellipse cx={-11} cy={-28} rx={5} ry={2.8} transform="rotate(-24 -11 -28)" />
        <ellipse cx={11} cy={-28} rx={5} ry={2.8} transform="rotate(24 11 -28)" />
        <ellipse cx={0} cy={-35} rx={3} ry={5} />
      </g>
      {state === 'fruiting' && (
        <g fill="#d96f32" stroke="#b3541e" strokeWidth={0.7}>
          <circle cx={-8} cy={-22} r={3.4} />
          <circle cx={7} cy={-25} r={3.4} />
          <circle cx={0} cy={-29} r={3.2} />
        </g>
      )}
    </g>
  )
}

/** A Palace plant: Severine's Bench bonsai, grown and painted by
 *  the Bench's own machinery and placed as an image (palacePlant).
 *  Where canvas painting is unavailable the PlantGlyph stands, as
 *  it always has — no other art is substituted. */
export function PlantMark({
  x,
  base,
  state,
  scale = 1,
}: {
  x: number
  base: number
  state: 'growing' | 'fruiting'
  scale?: number
}) {
  const href = useBenchBonsaiImage(state)
  if (!href) return <PlantGlyph x={x} base={base} state={state} scale={scale} />
  const w = 62 * scale
  const h = w * BONSAI_ASPECT
  return (
    <image
      href={href}
      x={x - w / 2}
      y={base - h * (1 - BONSAI_BASE_LIFT)}
      width={w}
      height={h}
      pointerEvents="none"
    />
  )
}

/** The cairn — the subject as the Vision Map holds it, standing at
 *  its building's door. */
export function CairnGlyph({ x, base }: { x: number; base: number }) {
  return (
    <g pointerEvents="none">
      <ellipse cx={x} cy={base - 4} rx={13} ry={5.5} fill={PAL.stone} stroke={PAL.stoneDark} />
      <ellipse cx={x} cy={base - 12} rx={10} ry={4.6} fill="#c4b294" stroke={PAL.stoneDark} />
      <ellipse cx={x} cy={base - 19} rx={7} ry={3.8} fill={PAL.stone} stroke={PAL.stoneDark} />
      <ellipse cx={x} cy={base - 25} rx={4.4} ry={3} fill="#cdbd9e" stroke={PAL.stoneDark} />
    </g>
  )
}

export function DrawingTable({ x, y, w }: { x: number; y: number; w: number }) {
  return (
    <g pointerEvents="none">
      <rect x={x - w / 2} y={y} width={w} height={9} rx={2} fill={PAL.wood} stroke={PAL.woodDark} />
      <g stroke={PAL.woodDark} strokeWidth={4}>
        <line x1={x - w / 2 + 12} y1={y + 9} x2={x - w / 2 + 6} y2={y + 30} />
        <line x1={x + w / 2 - 12} y1={y + 9} x2={x + w / 2 - 6} y2={y + 30} />
      </g>
      <rect
        x={x - w / 2 + 14}
        y={y - 13}
        width={w - 90}
        height={13}
        fill={PAL.paper}
        stroke={PAL.stoneDark}
        transform={`rotate(-2 ${x} ${y})`}
      />
      <rect
        x={x + w / 2 - 66}
        y={y - 11}
        width={44}
        height={11}
        fill="#efe6cf"
        stroke={PAL.stoneDark}
        transform={`rotate(3 ${x} ${y})`}
      />
    </g>
  )
}

/* ------------------------------------------------------------------ */
/* compound                                                            */
/* ------------------------------------------------------------------ */

/* ------------------------------------------------------------------ */
/* compound — Scene 1 (founder, 2026-11-26: "Implement it")            */
/*                                                                     */
/* The compound layer IS the founder's three-court plan now: his     */
/* art as the ground, the ivy buildings standing in it under the     */
/* placement law (palaceSceneLogic), the council bonfire at the      */
/* plaza, and the front wall — the art's own southern stonework —    */
/* layered over the buildings last, so front foundations stand at    */
/* the full circle's edge correctly occluded. Layer order is the     */
/* brief's: plan → buildings in foundation-depth order → bonfire →   */
/* front wall. Buildings are plain positioned <img> elements (the    */
/* Scroll's structural model) — no per-element SVG transforms.       */
/*                                                                     */
/* What stands in the plan: the compound's structures — initiatives  */
/* as buildings, loose projects and (un-nested) standing projects   */
/* as their own structures. What cannot stand in the plan keeps its  */
/* existing presentation below it: loose tasks as standing stones,   */
/* undeveloped ideas on the drawing table, released projects at the  */
/* south gate. Nothing the compound offered is dropped.              */
/*                                                                     */
/* A tap does what it always did here: an initiative enters its      */
/* building layer; a project enters the dome at task level. The      */
/* scene writes nothing — the chat is the work.                      */
/* ------------------------------------------------------------------ */

const PLAN_W = PALACE_GEOMETRY.width
const PLAN_H = PALACE_GEOMETRY.height

/** The bonfire's place on the plan — the plaza where the three
 *  courts meet (plan coordinates, the brief's numbers). */
// The plaza fire: the founder's own flame (2026-11-26 00:16 PT),
// standing on the lotus at the courts' junction — moved up onto
// the medallion at his direction (2026-11-26 12:09 PT: "The fire
// also needs to move up and please use the fire I gave you").
// Height 118 = the halved size he ruled 2026-11-26 01:19 PT.
const PLAZA_FIRE = { cx: 642, base: 362, h: 118 }

interface SceneBuilding {
  key: string
  klass: PalaceClassId
  stage: 1 | 2 | 3
  colour: string
  testid: string
  title: string
  open: () => void
}

function SceneBuildingImage({
  klass,
  stage,
  colour,
}: {
  klass: PalaceClassId
  stage: 1 | 2 | 3
  colour: string
}) {
  const url = useTintedMaster(klass, stage, colour)
  return <img src={url} alt="" draggable={false} className="block h-auto w-full" />
}

export function CompoundScene({
  model,
  attended,
  onAttend,
  onOpenBuilding,
  onOpenProject,
  onOpenTask,
  onSelectIdea,
  selectedIdeaId,
  interactions,
  projectRoomCounts,
}: {
  model: CompoundModel
  attended: boolean
  onAttend: (on: boolean) => void
  onOpenBuilding: (initiativeId: string) => void
  onOpenProject: (projectId: string) => void
  onOpenTask: (taskId: string) => void
  onSelectIdea: (ideaId: string) => void
  selectedIdeaId: string | null
  /** Per-subject seat-interaction counts (the ivy read); absent or
   *  null while loading or after a failed read — every building
   *  then stands at stage 1 in natural green. */
  interactions?: SubjectInteraction[] | null
  /** Room (task) counts per project id — the class reading for
   *  project structures, from the view's full record set. */
  projectRoomCounts?: Record<string, number>
}) {
  const scene = useMemo(() => {
    const index = indexInteractions(interactions)
    const buildings = new Map<string, SceneBuilding>()
    const inputs: SceneStructureInput[] = []
    const add = (
      entityType: 'initiative' | 'project',
      entityId: string,
      title: string,
      nestedCount: number,
      testid: string,
      open: () => void,
    ) => {
      const key = `${entityType}:${entityId}`
      const interaction = index.get(interactionKey(entityType, entityId))
      const stage = ivyStageFor(interaction?.total ?? 0)
      const klass = classForNestedCount(nestedCount)
      buildings.set(key, {
        key,
        klass,
        stage,
        colour: ivyColorFor(interaction),
        testid,
        title,
        open,
      })
      inputs.push({
        key,
        entityType,
        entityId,
        title,
        nestedCount,
        aspect: masterAspect(klass, stage),
      })
    }
    for (const b of model.buildings) {
      add('initiative', b.initiative.id, b.initiative.title, b.floors.length, `palace-building-${b.initiative.id}`, () =>
        onOpenBuilding(b.initiative.id),
      )
    }
    for (const p of model.looseProjects) {
      add('project', p.id, p.title, projectRoomCounts?.[p.id] ?? 0, `palace-loose-project-${p.id}`, () =>
        onOpenProject(p.id),
      )
    }
    for (const p of model.standingProjects) {
      add('project', p.id, p.title, projectRoomCounts?.[p.id] ?? 0, `palace-standing-project-${p.id}`, () =>
        onOpenProject(p.id),
      )
    }
    let placements: PlacedStructure[] | null = null
    try {
      placements = planCompoundScene(inputs)
    } catch {
      // The law found no lawful plan (a corrupt geometry asset is
      // the only known road here). The buildings still stand and
      // still open — access is never the price of placement.
      placements = null
    }
    return { buildings, placements }
  }, [model, interactions, projectRoomCounts, onOpenBuilding, onOpenProject])

  const { buildings, placements } = scene

  /* The grounds strip: what cannot stand in the plan, in its
   * existing presentation. */
  const tasksRows = Math.ceil(model.looseTasks.length / 3)
  const stripMainH = Math.max(tasksRows ? tasksRows * 96 + 36 : 0, 300)
  const stripReleasedH = model.releasedProjects.length ? 116 : 0
  const stripH = stripMainH + stripReleasedH
  const tableY = stripMainH - 70

  return (
    <div onMouseLeave={() => onAttend(false)}>
      {/* ——— the plan ——— */}
      <div
        className="relative w-full select-none"
        style={{ aspectRatio: `${PLAN_W} / ${PLAN_H}` }}
        role="img"
        aria-label="The Palace compound — the three courts"
      >
        <img
          src={planImage}
          alt=""
          draggable={false}
          className="absolute inset-0 h-full w-full"
        />
        {placements
          ? placements.map((p) => {
              const b = buildings.get(p.key)!
              return (
                <button
                  key={p.key}
                  type="button"
                  data-testid={b.testid}
                  title={b.title}
                  aria-label={b.title}
                  onClick={b.open}
                  onMouseEnter={() => onAttend(true)}
                  className="absolute block cursor-pointer border-0 bg-transparent p-0"
                  style={{
                    left: `${((p.bx - p.w / 2) / PLAN_W) * 100}%`,
                    top: `${((p.by - p.h) / PLAN_H) * 100}%`,
                    width: `${(p.w / PLAN_W) * 100}%`,
                  }}
                >
                  <SceneBuildingImage klass={p.klass} stage={b.stage} colour={b.colour} />
                </button>
              )
            })
          : [...buildings.values()].map((b, i) => (
              <button
                key={b.key}
                type="button"
                data-testid={b.testid}
                title={b.title}
                aria-label={b.title}
                onClick={b.open}
                onMouseEnter={() => onAttend(true)}
                className="absolute block cursor-pointer border-0 bg-transparent p-0"
                style={{
                  left: `${4 + i * 14}%`,
                  bottom: '3%',
                  width: '11%',
                }}
              >
                <SceneBuildingImage klass={b.klass} stage={b.stage} colour={b.colour} />
              </button>
            ))}
        {/* the fire at the plaza: the founder's flame on the lotus,
            over the buildings */}
        <img
          data-testid="palace-fire"
          src={fireImage}
          alt=""
          draggable={false}
          onMouseEnter={() => onAttend(true)}
          className="pointer-events-none absolute block"
          style={{
            left: `${((PLAZA_FIRE.cx - (PLAZA_FIRE.h * 989) / 1530 / 2) / PLAN_W) * 100}%`,
            bottom: `${((PLAN_H - PLAZA_FIRE.base) / PLAN_H) * 100}%`,
            width: `${((PLAZA_FIRE.h * 989) / 1530 / PLAN_W) * 100}%`,
          }}
        />
        {/* the front wall, over everything */}
        <img
          src={frontWallImage}
          alt=""
          draggable={false}
          className="pointer-events-none absolute inset-0 h-full w-full"
        />
      </div>

      {/* ——— the grounds strip ——— */}
      <svg
        viewBox={`0 0 900 ${stripH}`}
        className="block h-auto w-full"
        role="img"
        aria-label="The Palace grounds — loose work and the drawing table"
      >
        <rect x={0} y={0} width={900} height={stripH} fill={PAL.ground} />

        {/* loose tasks — standing stones on the open ground */}
        {model.looseTasks.map((t, i) => {
          const x = 66 + (i % 3) * 110
          const y = 44 + Math.floor(i / 3) * 96
          return (
            <g
              key={t.id}
              data-testid={`palace-loose-task-${t.id}`}
              onClick={() => onOpenTask(t.id)}
              style={{ cursor: 'pointer' }}
            >
              <title>{t.title}</title>
              <path
                d={`M ${x - 17} ${y + 34} C ${x - 19} ${y + 6}, ${x - 8} ${y - 12}, ${x} ${y - 14} C ${x + 9} ${y - 12}, ${x + 18} ${y + 8}, ${x + 16} ${y + 34} Z`}
                fill={isDoneStatus(t.status) ? '#c9b995' : PAL.stone}
                stroke={PAL.stoneDark}
              />
              {wrapTitle(t.title, 13, 2).map((line, li) => (
                <text key={li} x={x} y={y + 50 + li * 12} textAnchor="middle" fontSize={10} fill={PAL.ink}>
                  {line}
                </text>
              ))}
            </g>
          )
        })}

        {/* the drawing table — undeveloped ideas rest on it */}
        <g data-testid="palace-drawing-table">
          <DrawingTable x={560} y={tableY} w={300} />
          {model.ideas.map((idea, i) => {
            const x = 446 + (i % 4) * 76
            const y = tableY - 40 + Math.floor(i / 4) * 4
            const selected = selectedIdeaId === idea.id
            return (
              <g
                key={idea.id}
                data-testid={`palace-idea-${idea.id}`}
                onClick={() => onSelectIdea(idea.id)}
                style={{ cursor: 'pointer' }}
              >
                <title>{idea.title}</title>
                <rect
                  x={x - 34}
                  y={y - 12}
                  width={68}
                  height={24}
                  rx={3}
                  fill={selected ? '#f2dfae' : PAL.paper}
                  stroke={selected ? PAL.maeve : PAL.stoneDark}
                  strokeWidth={selected ? 2 : 1}
                  transform={`rotate(${i % 2 ? 2.5 : -2.5} ${x} ${y})`}
                />
                <text x={x} y={y + 3.5} textAnchor="middle" fontSize={8.6} fill={PAL.ink}>
                  {idea.title.length > 11 ? `${idea.title.slice(0, 10)}…` : idea.title}
                </text>
              </g>
            )
          })}
          <text x={560} y={tableY + 46} textAnchor="middle" fontSize={11} fill={PAL.inkSoft}>
            the drawing table
          </text>
        </g>

        {/* released work at the south gate */}
        {model.releasedProjects.map((p, i) => {
          const x = 120 + i * 170
          const y = stripMainH + 24
          return (
            <g
              key={p.id}
              data-testid={`palace-released-project-${p.id}`}
              onClick={() => onOpenProject(p.id)}
              style={{ cursor: 'pointer' }}
              opacity={0.75}
            >
              <title>{p.title}</title>
              <rect x={x} y={y + 12} width={80} height={40} fill="#ded2b8" stroke={WALL_LINE} strokeWidth={2} />
              <path d={`M ${x - 5} ${y + 12} L ${x + 40} ${y - 6} L ${x + 85} ${y + 12} Z`} fill="#a08b62" stroke={PAL.roofDark} />
              <text x={x + 40} y={y + 68} textAnchor="middle" fontSize={10} fill={PAL.inkSoft}>
                {p.title.length > 15 ? `${p.title.slice(0, 14)}…` : p.title} · released
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* building — Scene 2 (founder, 2026-11-26: "Great build it!"; the   */
/* Apollonian rebuild, founder 2026-11-26 16:27 PT: "Yep! That's    */
/* it")                                                                */
/*                                                                     */
/* The building layer is the composition of room-circles nested in  */
/* the founder's ARCHITECTURE dome — the background he supplied     */
/* 2026-11-26 16:15 PT ("Use this photo as the bg"), its interior   */
/* woven with staircases, galleries and arches, its white surround  */
/* cut to alpha — standing on the Zenaf background (his ruling,     */
/* 2026-11-26 13:44 PT): the Living Sky's plate, imported not       */
/* copied. The composition stands inside it under the relaxed       */
/* Apollonian spacing (palaceScene2Logic; his ruling, 2026-11-26    */
/* 16:19 PT: "Forget gravity and try to space them all as           */
/* relatively apalonian as possible"): the whole dome interior is   */
/* the space; each floor's AREA is its share of the building's      */
/* rooms against that space's area; the largest floor anchors the   */
/* middle and the rest nestle into the pockets between the larger   */
/* ones, sizes clearly differentiated and distributed — never all   */
/* the big ones pooled at the bottom. Rooms only: no filler         */
/* circles, and no text rides the circles (his ruling, 2026-11-26   */
/* 14:03 PT) — a circle is its room, and its identity travels       */
/* through the chat. ONE hearth — the SAME fire as everywhere in    */
/* the Palace (his ruling, 2026-11-26 16:31 PT: "Fire- same         */
/* fire"), the founder's flame standing in the dome's own stone     */
/* ring on its floor. Each floor circle's interior is one of the    */
/* three unfurnished room plates, by size rank cycling rose →       */
/* spiral → tiers (addendum 2026-11-26 13:16 PT), drawn at the      */
/* study's inset so the plate's paper margin never shows and its   */
/* stone rim does (founder, 2026-11-26 16:24 PT: "Not the stone     */
/* color just the paper around it"), and the circles draw           */
/* back-to-front by depth. A floor's STAINED GLASS takes the        */
/* colour of the seat that has been talking about its subject      */
/* (his ruling, 2026-11-26 16:27 PT: "stain glass changes color     */
/* with seat communication"; palaceGlass) — the same               */
/* subject-interactions read that grows Scene 1's ivy. Plain        */
/* positioned DOM throughout (the Scene 1 lesson): no SVG           */
/* transform stacks.                                                */
/*                                                                     */
/* A tap does what it always did here: it descends into that         */
/* floor, with the same chat subject carriage. A floor's earned      */
/* balcony plant stands as a small marker on its circle's rim.       */
/* The hearth is not interactive. The scene writes nothing —         */
/* the chat is the work.                                             */
/* ------------------------------------------------------------------ */

/** The study's palette (build_study_v5.py), in the plates' tones. */
const SCENE2_CIRCLE = '#e7cda4'

/** The plates render at 1/0.91 scale centred inside the circle,
 *  so the visible edge is the plate's own disc rim (frac ~0.455
 *  of the plate): the paper margin never shows, the stone rim
 *  does — the study's treatment (build_study_v21_apollonian.py). */
const PLATE_SCALE = 1 / 0.91

/** A floor's room — the founder's unfurnished plate for its size
 *  rank, its stained glass tinted to the dominant seat's colour
 *  where a seat has been talking about the floor's subject
 *  (palaceGlass; natural glass when none has). */
function FloorPlateImage({ plate, colour }: { plate: RoomPlate; colour: string | null }) {
  const url = useGlassPlate(plate, colour)
  return (
    <img
      src={url}
      alt=""
      draggable={false}
      className="pointer-events-none absolute block object-cover"
      style={{
        width: `${PLATE_SCALE * 100}%`,
        height: `${PLATE_SCALE * 100}%`,
        left: `${-((PLATE_SCALE - 1) / 2) * 100}%`,
        top: `${-((PLATE_SCALE - 1) / 2) * 100}%`,
      }}
    />
  )
}

/** The flame's height in the hearth ring (frame units — 118, as
 *  on the compound; aspect from the shipped asset, as the
 *  compound's fire reads it). It stands static in the ring, its
 *  base at the ring's centre depth. */
const HEARTH_FLAME_H = 118
const FLAME_ASPECT = 989 / 1530

const pct = (units: number) => `${(units / SCENE2_FRAME) * 100}%`

export function BuildingScene({
  model,
  attendedFloorId,
  onAttend,
  onOpenFloor,
  interactions,
}: {
  model: BuildingModel
  attendedFloorId: string | null
  onAttend: (projectId: string | null) => void
  onOpenFloor: (projectId: string) => void
  /** Per-subject seat-interaction counts (the glass read — the
   *  same read that grows Scene 1's ivy); absent or null while
   *  loading or after a failed read — every floor then keeps
   *  its natural glass. */
  interactions?: SubjectInteraction[] | null
}) {
  const layout = useMemo(
    () =>
      planBuildingScene(
        model.floors.map((f) => ({ key: f.project.id, roomCount: f.roomCount })),
      ),
    [model],
  )
  const interactionIndex = useMemo(() => indexInteractions(interactions), [interactions])
  const floorByKey = new Map(model.floors.map((f) => [f.project.id, f]))
  const { hearth } = layout
  return (
    <div style={{ containerType: 'inline-size' }} onMouseLeave={() => onAttend(null)}>
      <div className="pb-1 pt-2 text-center">
        <div style={{ fontSize: '2.2cqw', fontWeight: 600, color: PAL.ink }}>
          {model.initiative.title}
        </div>
        <div style={{ fontSize: '1.55cqw', color: PAL.inkSoft }}>
          each floor is one of its projects — tap a floor to walk it
        </div>
      </div>

      <div
        className="relative w-full select-none"
        style={{ aspectRatio: '1 / 1' }}
        role="img"
        aria-label={`Inside ${model.initiative.title}`}
      >
        {/* the Zenaf background — the Living Sky's plate (no
            tree), cover over the scene box, behind everything */}
        <img
          data-testid="palace-zenaf-background"
          src={plateImage}
          alt=""
          draggable={false}
          className="absolute inset-0 block h-full w-full object-cover"
        />

        {/* the architecture dome — the founder's art (alpha
            cutout) standing in the landscape, the whole 1254
            frame; the composition nests in its interior */}
        <img
          data-testid="palace-architecture"
          src={architectureImage}
          alt=""
          draggable={false}
          className="absolute inset-0 block h-full w-full"
        />

        {/* the composition, clipped to the container's outline —
            the whole space, floor included, so a room is not cut
            at the cavity's back rim; belt-and-braces: the
            spacing law's containment already keeps every circle
            inside the space */}
        <div className="absolute inset-0" style={{ clipPath: CONTAINER_CLIP_PATH }}>

        {/* the floors — one circle each, area = share of the
            rooms, drawn back-to-front by depth (bottom y + r
            ascending: the front rooms paint last) */}
        {[...layout.floors]
          .sort((a, b) => a.y + a.r - (b.y + b.r))
          .map((p) => {
          const floor = floorByKey.get(p.key)!
          const attended = attendedFloorId === floor.project.id
          const glassColour = glassColorFor(
            interactionIndex.get(interactionKey('project', floor.project.id)),
          )
          return (
            <button
              key={floor.project.id}
              type="button"
              data-testid={`palace-floor-${floor.project.id}`}
              title={floor.project.title}
              aria-label={floor.project.title}
              onClick={() => onOpenFloor(floor.project.id)}
              onMouseEnter={() => onAttend(floor.project.id)}
              onMouseLeave={() => onAttend(null)}
              className="absolute block cursor-pointer overflow-hidden rounded-full p-0"
              style={{
                left: pct(p.x - p.r),
                top: pct(p.y - p.r),
                width: pct(2 * p.r),
                aspectRatio: '1 / 1',
                background: SCENE2_CIRCLE,
              }}
            >
              {/* the floor's room — the founder's unfurnished plate
                  for its size rank, clipped to the circle at the
                  study's inset (paper off, stone rim on), its
                  stained glass in the dominant seat's colour */}
              <FloorPlateImage plate={p.plate} colour={glassColour} />
              {/* a soft parchment wash over the art, so the room
                  reads as the building's interior, not a picture */}
              <span
                className="pointer-events-none absolute inset-0 rounded-full"
                style={{
                  background:
                    'radial-gradient(circle at 50% 42%, rgba(243, 234, 214, 0.30), rgba(243, 234, 214, 0.06) 72%)',
                }}
              />
              {/* no text rides the circle (the founder's ruling,
                  2026-11-26 14:03 PT) — the room alone; its name
                  travels through the chat and the button's label */}
              {/* the floor's balcony plant, earned by its rooms —
                  a small marker standing on the circle's rim (just
                  inside it: the button clips its interior now) */}
              {floor.plant && (
                <span
                  className="pointer-events-none absolute"
                  style={{ left: '50%', top: 0, width: '18%', transform: 'translate(-50%, 4%)' }}
                >
                  <svg viewBox="-26 -42 52 44" className="block h-auto w-full" aria-hidden>
                    <PlantMark x={0} base={0} state={floor.plant} scale={0.8} />
                  </svg>
                </span>
              )}
            </button>
          )
        })}
        </div>

        {/* the hearth — one per building: the dome's own stone
            ring on its floor (painted in the architecture art
            itself), and standing in it the SAME fire as
            everywhere in the Palace — the founder's flame,
            static, its base at the ring's centre depth */}
        <div
          data-testid="palace-building-hearth"
          className="pointer-events-none absolute"
          style={{
            left: pct(hearth.x - hearth.r),
            top: pct(hearth.y - hearth.r),
            width: pct(2 * hearth.r),
            aspectRatio: '1 / 1',
          }}
        />
        <img
          data-testid="palace-building-fire"
          src={fireImage}
          alt=""
          draggable={false}
          className="pointer-events-none absolute block"
          style={{
            left: pct(hearth.x - (HEARTH_FLAME_H * FLAME_ASPECT) / 2),
            bottom: pct(SCENE2_FRAME - hearth.y),
            width: pct(HEARTH_FLAME_H * FLAME_ASPECT),
          }}
        />

        {model.floors.length === 0 && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
            <span style={{ fontSize: '1.8cqw', color: PAL.inkSoft }}>
              No floors yet — no projects stand under this initiative.
            </span>
          </div>
        )}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* task level — the dome's second level (founder, 2026-11-26          */
/* 20:07 PT: the floor-plan frame retired, "Build it")                 */
/*                                                                     */
/* The same dome, recomposed: the project's TASKS as circles in      */
/* the same architecture, under the same relaxed Apollonian          */
/* spacing (palaceScene2Logic.planTaskScene), the same one hearth    */
/* — the project frame's one fire. Circle sizes come from            */
/* recorded data: a task's estimate when it has one, else one        */
/* equal unit. Every circle shows the project's chamber plate —      */
/* the room its task opens into (plateForFloor's assignment,         */
/* shared with the chamber itself) — its stained glass in the        */
/* colour of the seat that has been talking about that TASK          */
/* (palaceGlass, the same subject-interactions read).                */
/*                                                                     */
/* The recorded dependencies between the project's tasks shape       */
/* the seating (the founder, same direction: "instead of a door,      */
/* we can set it up to where the room itself moves next to            */
/* another room where it's connected or at least draws a line        */
/* to it"): partners sit as neighbours where the packing can         */
/* achieve it; for every pair it could not, ONE plain stone-toned    */
/* line runs beneath the circles, rim to rim — no labels, no         */
/* arrows. A tap on a task circle stages the task in the chat        */
/* and opens its chamber, exactly as a room tap did on the retired    */
/* floor. No text rides the circles. The scene writes nothing.       */
/* ------------------------------------------------------------------ */

export function TaskScene({
  model,
  plate,
  onOpenTask,
  interactions,
}: {
  model: TaskLevelModel
  /** The project's chamber plate — the plate the project's
   *  rooms open into (plateForFloor); every task circle shows
   *  it, as every floor circle showed its own plate. */
  plate: RoomPlate
  onOpenTask: (taskId: string) => void
  /** Per-subject seat-interaction counts (the glass read);
   *  absent or null while loading or after a failed read —
   *  every task then keeps its natural glass. */
  interactions?: SubjectInteraction[] | null
}) {
  const layout = useMemo(
    () =>
      planTaskScene(
        model.tasks.map((t) => ({ key: t.id, weight: taskSizeWeight(t.estimated_hours) })),
        model.links.map((l) => ({ aKey: l.aId, bKey: l.bId })),
      ),
    [model],
  )
  const interactionIndex = useMemo(() => indexInteractions(interactions), [interactions])
  const taskByKey = new Map(model.tasks.map((t) => [t.id, t]))
  const placedByKey = new Map(layout.tasks.map((p) => [p.key, p]))
  const { hearth } = layout
  return (
    <div style={{ containerType: 'inline-size' }}>
      <div className="pb-1 pt-2 text-center">
        <div style={{ fontSize: '2.2cqw', fontWeight: 600, color: PAL.ink }}>
          {model.project.title}
        </div>
        <div style={{ fontSize: '1.55cqw', color: PAL.inkSoft }}>
          each circle is one of its tasks — tap a task to enter its room
        </div>
      </div>

      <div
        className="relative w-full select-none"
        style={{ aspectRatio: '1 / 1' }}
        role="img"
        aria-label={`Inside ${model.project.title} — its tasks`}
      >
        {/* the Zenaf background and the architecture dome — the
            same frame the project level stands in */}
        <img
          data-testid="palace-zenaf-background"
          src={plateImage}
          alt=""
          draggable={false}
          className="absolute inset-0 block h-full w-full object-cover"
        />
        <img
          data-testid="palace-architecture"
          src={architectureImage}
          alt=""
          draggable={false}
          className="absolute inset-0 block h-full w-full"
        />

        <div className="absolute inset-0" style={{ clipPath: CONTAINER_CLIP_PATH }}>
          {/* the dependency lines — one for every pair the
              packing did not seat as neighbours, drawn beneath
              the circles, rim to rim, in plain stone tone */}
          <svg
            className="pointer-events-none absolute inset-0 block h-full w-full"
            viewBox={`0 0 ${SCENE2_FRAME} ${SCENE2_FRAME}`}
            aria-hidden
          >
            {layout.links.map((l) => {
              const a = placedByKey.get(l.aKey)!
              const b = placedByKey.get(l.bKey)!
              const d = Math.hypot(b.x - a.x, b.y - a.y) || 1
              const ux = (b.x - a.x) / d
              const uy = (b.y - a.y) / d
              return (
                <line
                  key={`${l.aKey}|${l.bKey}`}
                  data-testid="palace-task-link"
                  x1={a.x + ux * a.r}
                  y1={a.y + uy * a.r}
                  x2={b.x - ux * b.r}
                  y2={b.y - uy * b.r}
                  stroke={PAL.stoneDark}
                  strokeWidth={3}
                />
              )
            })}
          </svg>

          {/* the tasks — one circle each, drawn back-to-front
              by depth, as the floors are */}
          {[...layout.tasks]
            .sort((a, b) => a.y + a.r - (b.y + b.r))
            .map((p) => {
              const task = taskByKey.get(p.key)!
              const glassColour = glassColorFor(
                interactionIndex.get(interactionKey('task', task.id)),
              )
              return (
                <button
                  key={task.id}
                  type="button"
                  data-testid={`palace-task-${task.id}`}
                  title={task.title}
                  aria-label={task.title}
                  onClick={() => onOpenTask(task.id)}
                  className="absolute block cursor-pointer overflow-hidden rounded-full p-0"
                  style={{
                    left: pct(p.x - p.r),
                    top: pct(p.y - p.r),
                    width: pct(2 * p.r),
                    aspectRatio: '1 / 1',
                    background: SCENE2_CIRCLE,
                  }}
                >
                  <FloorPlateImage plate={plate} colour={glassColour} />
                  <span
                    className="pointer-events-none absolute inset-0 rounded-full"
                    style={{
                      background:
                        'radial-gradient(circle at 50% 42%, rgba(243, 234, 214, 0.30), rgba(243, 234, 214, 0.06) 72%)',
                    }}
                  />
                </button>
              )
            })}
        </div>

        {/* the hearth — the project frame's one fire, the same
            ring and the same founder flame as the level above */}
        <div
          data-testid="palace-building-hearth"
          className="pointer-events-none absolute"
          style={{
            left: pct(hearth.x - hearth.r),
            top: pct(hearth.y - hearth.r),
            width: pct(2 * hearth.r),
            aspectRatio: '1 / 1',
          }}
        />
        <img
          data-testid="palace-building-fire"
          src={fireImage}
          alt=""
          draggable={false}
          className="pointer-events-none absolute block"
          style={{
            left: pct(hearth.x - (HEARTH_FLAME_H * FLAME_ASPECT) / 2),
            bottom: pct(SCENE2_FRAME - hearth.y),
            width: pct(HEARTH_FLAME_H * FLAME_ASPECT),
          }}
        />

        {model.tasks.length === 0 && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
            <span style={{ fontSize: '1.8cqw', color: PAL.inkSoft }}>
              No tasks yet — no tasks stand in this project.
            </span>
          </div>
        )}
      </div>
    </div>
  )
}

  /* ------------------------------------------------------------------ */
/* room — the furnished chamber (founder, 2026-11-26: "Perfect!      */
/* Implement the palace as we've discussed")                           */
/*                                                                     */
/* The room stops being the drawn cutaway: the room IS one of the    */
/* founder's unfurnished chamber plates, furnished with his          */
/* artifacts at the seats he marked through studies A1–A7            */
/* (room-study-A7-fitted.png). A room takes the chamber of the       */
/* FLOOR it belongs to — the same plate the building scene shows     */
/* for that floor (plateForFloor, the shared plan; founder,          */
/* 2026-11-26 18:55 PT: "Good! Implement it!") — rose, spiral or     */
/* tiers, each with its own seat table (the spiral and tiers seats   */
/* are studies room-study-spiral-A7 / room-study-tiers-A7), and      */
/* the founder's flame stands 1.5× larger in all three chambers      */
/* (his ruling, same message). Unresolvable floor → rose.            */
/* A plate-frame                                                   */
/* composition like BuildingScene: the plate, then plain             */
/* positioned elements, placed by OBJECT bounds (the alpha-bbox      */
/* fractions measured off each asset) — never by canvas bounds:      */
/* the chest's canvas carries empty margin under the object,         */
/* which floated it in the studies until the anchoring was fixed.    */
/*                                                                     */
/* State rules, all existing: the vessel is gold iff the attributed  */
/* read's accepted supersession stands (vesselGold); the scales      */
/* are weighed iff the task carries a recorded estimate; the chest   */
/* stands OPEN iff the room holds recorded material (its held        */
/* list), closed iff it holds none; the founder's flame stands in    */
/* the plate's own hearth ring iff the room is lit (Maeve            */
/* attending), rendered in front of the drawing table; the window    */
/* state reads on the plate's windows — the rose chamber's three      */
/* lancets, or the great round windows of the spiral and tiers       */
/* chambers, whose hearths also carry the plate's front wall back    */
/* over the flame's base so the fire stands in the pit. Every        */
/* testid, handler and staged focus is the old room's.               */
/* ------------------------------------------------------------------ */

const ROOM_FRAME = 1254
const roomPct = (units: number) => `${(units / ROOM_FRAME) * 100}%`

/** An artifact's object bounds within its square canvas, as
 *  fractions of the canvas side, measured off the shipped asset's
 *  alpha: the object's base line, its centre, its right edge. */
interface ObjectExtent {
  base: number
  cx: number
  right: number
}
const VESSEL_OBJECT: ObjectExtent = { base: 0.982, cx: 0.494, right: 0.82 }
const SCALES_OBJECT: ObjectExtent = { base: 0.979, cx: 0.501, right: 0.95 }
const CHEST_OBJECT: ObjectExtent = { base: 0.886, cx: 0.499, right: 0.955 }
const CHEST_OPEN_OBJECT: ObjectExtent = { base: 0.966, cx: 0.493, right: 0.939 }
const TABLE_OBJECT: ObjectExtent = { base: 0.845, cx: 0.496, right: 0.959 }

/** One of the founder's artifacts as a tappable plate-frame
 *  element: the button is the asset's canvas box, positioned so
 *  the OBJECT inside it lands on its seat — its base on the given
 *  line, centred on the given x or with its right edge on it. */
function RoomArt({
  href,
  extent,
  side,
  objCx,
  objRight,
  objBottom,
  testid,
  label,
  onClick,
}: {
  href: string
  extent: ObjectExtent
  /** The canvas side, in frame units (the brief's image height). */
  side: number
  objCx?: number
  objRight?: number
  objBottom: number
  testid: string
  label: string
  onClick: () => void
}) {
  const left = objRight != null ? objRight - extent.right * side : (objCx ?? 0) - extent.cx * side
  const top = objBottom - extent.base * side
  return (
    <button
      type="button"
      data-testid={testid}
      title={label}
      aria-label={label}
      onClick={onClick}
      className="absolute block cursor-pointer p-0"
      style={{
        left: roomPct(left),
        top: roomPct(top),
        width: roomPct(side),
        aspectRatio: '1 / 1',
        background: 'transparent',
        border: 'none',
      }}
    >
      <img src={href} alt="" draggable={false} className="block h-full w-full" />
    </button>
  )
}

/** The mandala — the old room's glyph, unchanged: earned where
 *  recorded edges converge, or standing as Aria's guest object
 *  where she attends. In the chamber it centres on the plate's
 *  great window. */
function MandalaGlyph() {
  return (
    <svg viewBox="-24 -24 48 48" className="block h-full w-full" aria-hidden>
      <g opacity={0.9}>
        <circle r={24} fill="none" stroke={PAL.maeve} strokeWidth={2.2} />
        <circle r={15} fill="none" stroke={PAL.maeve} strokeWidth={1.5} />
        <circle r={5} fill={PAL.maeve} />
        {[0, 60, 120, 180, 240, 300].map((a) => (
          <line
            key={a}
            x1={Math.cos((a * Math.PI) / 180) * 15}
            y1={Math.sin((a * Math.PI) / 180) * 15}
            x2={Math.cos((a * Math.PI) / 180) * 24}
            y2={Math.sin((a * Math.PI) / 180) * 24}
            stroke={PAL.maeve}
            strokeWidth={1.5}
          />
        ))}
      </g>
    </svg>
  )
}

/** The room's plant — Severine's Bench bonsai (palacePlant, as in
 *  PR #463), standing on the floor front-left. Where canvas
 *  painting is unavailable the PlantGlyph stands, as it always
 *  has — no other art is substituted. (This seat is provisional:
 *  it was not among the founder's marked seats.) */
function RoomPlant({
  state,
  onClick,
  cx = 150,
  floorY = 1005,
}: {
  state: 'growing' | 'fruiting'
  onClick: () => void
  /** The seat's centre and floor line, per plate (rose's seat is
   *  the original: centre 150, floor 1005). */
  cx?: number
  floorY?: number
}) {
  const href = useBenchBonsaiImage(state)
  const imgH = 120
  const imgW = imgH / BONSAI_ASPECT
  const imgBottom = floorY + BONSAI_BASE_LIFT * imgH
  return (
    <button
      type="button"
      data-testid="palace-room-plant"
      title="Rumi's plant"
      aria-label="Rumi's plant"
      onClick={onClick}
      className="absolute block cursor-pointer p-0"
      style={{
        left: roomPct(cx - imgW / 2),
        top: roomPct(imgBottom - imgH),
        width: roomPct(imgW),
        height: roomPct(imgH),
        background: 'transparent',
        border: 'none',
      }}
    >
      {href ? (
        <img src={href} alt="" draggable={false} className="block h-full w-full" />
      ) : (
        <svg viewBox="-48 -114 96 114" className="block h-full w-full" aria-hidden>
          <PlantGlyph x={0} base={0} state={state} scale={3} />
        </svg>
      )}
    </button>
  )
}

/** Guest objects — each stands ONLY where the attributed read
 *  shows its seat attending this room's subject (Guests-1); each
 *  keeps its own form, as a guest here. Aria's guest object is
 *  the mandala, not a row piece. The row stands on the floor
 *  front-left of the hearth. */
const GUEST_ROW_ORDER: SeatId[] = ['champion', 'skeptic', 'ambassador', 'maverick', 'mentor']
const GUEST_GLYPHS: Partial<
  Record<SeatId, { title: string; viewBox: string; w: number; h: number; body: React.ReactNode }>
> = {
  champion: {
    title: "Valen's battle plan",
    viewBox: '-31 -23 62 46',
    w: 62,
    h: 46,
    body: (
      <>
        <rect x={-31} y={-23} width={62} height={46} rx={2} fill={PAL.paper} stroke={PAL.stoneDark} strokeWidth={1.6} />
        <polyline points="-21,13 -7,-5 7,7 21,-13" fill="none" stroke={SEAT_COLORS.champion} strokeWidth={2.2} />
        <circle cx={-21} cy={13} r={3.2} fill={SEAT_COLORS.champion} />
        <circle cx={21} cy={-13} r={3.2} fill={SEAT_COLORS.champion} />
      </>
    ),
  },
  skeptic: {
    title: "Severine's lens",
    viewBox: '-18 -18 46 46',
    w: 46,
    h: 46,
    body: (
      <>
        <circle r={15} fill="#eef2f7" opacity={0.6} stroke={PAL.stoneDark} strokeWidth={3} />
        <line x1={10} y1={10} x2={25} y2={25} stroke={PAL.woodDark} strokeWidth={5} strokeLinecap="round" />
      </>
    ),
  },
  ambassador: {
    title: "Lucian's cup",
    viewBox: '-16 -6 34 22',
    w: 34,
    h: 22,
    body: (
      <>
        <ellipse cx={0} cy={11} rx={15} ry={3.4} fill={PAL.stone} stroke={PAL.stoneDark} />
        <path d="M -11 -3 L 11 -3 L 8 9 L -8 9 Z" fill="#eef2f7" stroke={SEAT_COLORS.ambassador} strokeWidth={1.8} />
        <path d="M 11 -1 A 5.5 4.5 0 1 1 11 6" fill="none" stroke={SEAT_COLORS.ambassador} strokeWidth={1.8} />
      </>
    ),
  },
  maverick: {
    title: "Jynx's scroll",
    viewBox: '-25 -7 52 14',
    w: 52,
    h: 14,
    body: (
      <>
        <rect x={-25} y={-7} width={45} height={14} rx={7} fill={PAL.paper} stroke={SEAT_COLORS.maverick} strokeWidth={1.8} />
        <circle cx={20} cy={0} r={7} fill="#e6dcc4" stroke={SEAT_COLORS.maverick} strokeWidth={1.8} />
        <circle cx={20} cy={0} r={2.8} fill="none" stroke={SEAT_COLORS.maverick} strokeWidth={1.4} />
      </>
    ),
  },
  mentor: {
    title: "Rumi's cairn",
    viewBox: '-16 -12 32 23',
    w: 32,
    h: 23,
    body: (
      <>
        <ellipse cx={0} cy={6} rx={16} ry={5} fill={PAL.stone} stroke={PAL.stoneDark} />
        <ellipse cx={0} cy={-1} rx={11.5} ry={4.4} fill="#c4b494" stroke={PAL.stoneDark} />
        <ellipse cx={0} cy={-7.5} rx={7.5} ry={3.8} fill={SEAT_COLORS.mentor} stroke={PAL.stoneDark} />
      </>
    ),
  },
}

/** The rose plate's three lancet windows, in frame units
 *  (measured off the plate): the window state's overlay ground
 *  in the rose chamber. */
const LANCETS = [
  { x: 500, w: 48 },
  { x: 572, w: 68 },
  { x: 696, w: 48 },
]
const LANCET_BOX = { x: 492, y: 442, w: 260, h: 172 }

/** A window-state overlay shape, in frame units: a lancet of the
 *  rose chamber, or one of the great round windows flanking the
 *  spiral and tiers chambers' great window (their tall lancets
 *  stand behind the staircase, so the state reads there). */
type RoomWindowShape =
  | { kind: 'lancet'; x: number; w: number; y: number; h: number }
  | { kind: 'round'; cx: number; cy: number; r: number }

/** One chamber's seat table — every positioned element of the
 *  room, in frame units, placed by OBJECT bounds as the studies
 *  placed them. The flame heights carry the founder's 1.5×
 *  (2026-11-26 18:55 PT). */
interface RoomSeatTable {
  scales: { cx: number; bottom: number; side: number }
  chest: { cx?: number; right?: number; bottom: number; side: number }
  vessel: { cx: number; bottom: number; side: number }
  table: { cx: number; bottom: number; side: number }
  flame: { cx: number; base: number; height: number }
  /** The hearth ring's centre — the tap target stands on it. */
  hearth: { cx: number; cy: number }
  /** The hearth's front-wall band: the plate's own stonework,
   *  rendered back over the flame's base so the fire stands IN
   *  the pit. Null where the chamber needs none (rose — the
   *  approved rose study has none). */
  wallBand: { x0: number; y0: number; x1: number; y1: number } | null
  mandala: { cx: number; cy: number }
  windowBox: { x: number; y: number; w: number; h: number }
  windowShapes: RoomWindowShape[]
  plant: { cx: number; bottom: number }
  guestRow: { startX: number; bottom: number }
  subtaskBottom: number
  threshold: { x: number; y: number; w: number; h: number }
}

const ROOM_SEATS: Record<RoomPlate, RoomSeatTable> = {
  rose: {
    scales: { cx: 282, bottom: 608, side: 195 },
    chest: { right: 1070, bottom: 616, side: 185 },
    vessel: { cx: 975, bottom: 985, side: 205 },
    table: { cx: 695, bottom: 949, side: 315 },
    flame: { cx: 627, base: 972, height: 150 },
    hearth: { cx: 627, cy: 910 },
    wallBand: null,
    mandala: { cx: 627, cy: 268 },
    windowBox: LANCET_BOX,
    windowShapes: LANCETS.map((l) => ({ kind: 'lancet' as const, x: l.x, w: l.w, y: 450, h: 155 })),
    plant: { cx: 150, bottom: 1005 },
    guestRow: { startX: 180, bottom: 1010 },
    subtaskBottom: 1110,
    threshold: { x: 527, y: 1115, w: 200, h: 75 },
  },
  spiral: {
    scales: { cx: 280, bottom: 560, side: 170 },
    chest: { cx: 965, bottom: 560, side: 160 },
    vessel: { cx: 445, bottom: 1085, side: 190 },
    table: { cx: 895, bottom: 1080, side: 260 },
    flame: { cx: 632, base: 998, height: 188 },
    hearth: { cx: 632, cy: 936 },
    wallBand: { x0: 540, y0: 986, x1: 725, y1: 1020 },
    mandala: { cx: 627, cy: 235 },
    windowBox: { x: 345, y: 130, w: 565, h: 170 },
    windowShapes: [
      { kind: 'round', cx: 430, cy: 215, r: 85 },
      { kind: 'round', cx: 825, cy: 215, r: 85 },
    ],
    plant: { cx: 200, bottom: 1100 },
    guestRow: { startX: 180, bottom: 1110 },
    subtaskBottom: 1150,
    threshold: { x: 300, y: 1100, w: 650, h: 80 },
  },
  tiers: {
    scales: { cx: 200, bottom: 522, side: 130 },
    chest: { cx: 1050, bottom: 522, side: 125 },
    vessel: { cx: 375, bottom: 1070, side: 180 },
    table: { cx: 880, bottom: 1065, side: 240 },
    flame: { cx: 620, base: 1078, height: 177 },
    hearth: { cx: 620, cy: 1016 },
    wallBand: { x0: 525, y0: 1062, x1: 720, y1: 1100 },
    mandala: { cx: 627, cy: 180 },
    windowBox: { x: 335, y: 110, w: 585, h: 160 },
    windowShapes: [
      { kind: 'round', cx: 415, cy: 190, r: 80 },
      { kind: 'round', cx: 840, cy: 190, r: 80 },
    ],
    plant: { cx: 190, bottom: 1110 },
    guestRow: { startX: 170, bottom: 1120 },
    subtaskBottom: 1160,
    threshold: { x: 280, y: 1110, w: 700, h: 90 },
  },
}

export function RoomScene({
  model,
  lit,
  onBringFire,
  onThreshold,
  onOpenWaitedOn,
  onFurniture,
  onOpenSubtask,
  vesselGold = false,
  guests = [],
  onGuest,
  plate = 'rose',
}: {
  model: RoomModel
  lit: boolean
  /** The chamber this room stands in — the plate of the floor it
   *  belongs to (plateForFloor, the building scene's own plan).
   *  Rose when the floor cannot be resolved. */
  plate?: RoomPlate
  onBringFire: () => void
  onThreshold: () => void
  onOpenWaitedOn: (taskId: string) => void
  onFurniture: (kind: 'scales' | 'vessel' | 'chest' | 'table' | 'mandala' | 'plant') => void
  onOpenSubtask: (taskId: string) => void
  /** The vessel's gold seam, as the attributed read derives it:
   *  an interpretation reconsidered, its correction accepted. */
  vesselGold?: boolean
  /** Seats the attributed read shows attending this room's subject —
   *  their guest objects stand here, and only theirs (Guests-1). */
  guests?: SeatId[]
  onGuest?: (seat: SeatId) => void
}) {
  const seats = ROOM_SEATS[plate]
  const waited = model.waitsOn[0]
  /** The chest stands open iff the room holds recorded material —
   *  its held list (notes, description, criteria) is non-empty. */
  const chestOpen = model.held != null
  const rowGuests = GUEST_ROW_ORDER.filter((seat) => guests.includes(seat))
  /** The window's reading of the waited-on rooms, on the plate's
   *  windows: a wall still being built tints them the amber tone;
   *  a completed wall leaves them pale and bright; nothing waited
   *  on, no overlay. */
  const windowTone =
    model.windowState === 'building'
      ? 'rgba(216, 164, 65, 0.45)'
      : model.windowState === 'complete'
        ? 'rgba(255, 246, 214, 0.60)'
        : 'transparent'
  const windowBox = seats.windowBox
  return (
    <div
      className="relative w-full select-none"
      style={{ aspectRatio: '1 / 1' }}
      role="img"
      aria-label={`Room — ${model.task.title}`}
    >
      {/* the chamber itself — the founder's plate for this room's
          floor: rose, spiral or tiers */}
      <img
        src={PLATE_URLS[plate]}
        alt=""
        draggable={false}
        className="absolute inset-0 block h-full w-full"
      />

      {/* the window state, read on the plate's windows — the rose
          chamber's three lancets, or the great round windows
          flanking the spiral and tiers chambers' great window.
          The group keeps the old window's tap: it opens the
          waited-on room. */}
      <div
        data-testid="palace-room-window"
        data-window-state={model.windowState ?? 'none'}
        onClick={() => waited && onOpenWaitedOn(waited.id)}
        className="absolute block"
        style={{
          left: roomPct(windowBox.x),
          top: roomPct(windowBox.y),
          width: roomPct(windowBox.w),
          height: roomPct(windowBox.h),
          cursor: waited ? 'pointer' : 'default',
        }}
      >
        {seats.windowShapes.map((shape) =>
          shape.kind === 'lancet' ? (
            <span
              key={`lancet-${shape.x}`}
              className="pointer-events-none absolute block"
              style={{
                left: `${((shape.x - windowBox.x) / windowBox.w) * 100}%`,
                top: `${((shape.y - windowBox.y) / windowBox.h) * 100}%`,
                width: `${(shape.w / windowBox.w) * 100}%`,
                height: `${(shape.h / windowBox.h) * 100}%`,
                background: windowTone,
                borderRadius: '45% 45% 0 0 / 26% 26% 0 0',
              }}
            />
          ) : (
            <span
              key={`round-${shape.cx}`}
              className="pointer-events-none absolute block"
              style={{
                left: `${((shape.cx - shape.r - windowBox.x) / windowBox.w) * 100}%`,
                top: `${((shape.cy - shape.r - windowBox.y) / windowBox.h) * 100}%`,
                width: `${((2 * shape.r) / windowBox.w) * 100}%`,
                height: `${((2 * shape.r) / windowBox.h) * 100}%`,
                background: windowTone,
                borderRadius: '50%',
              }}
            />
          ),
        )}
      </div>

      {/* the mandala — earned where recorded edges converge, or
          standing as Aria's guest object where she attends —
          centred on the plate's great window */}
      {(model.mandala || guests.includes('conductor')) && (
        <button
          type="button"
          data-testid="palace-room-mandala"
          title="The mandala"
          aria-label="The mandala"
          onClick={() => (guests.includes('conductor') && onGuest ? onGuest('conductor') : onFurniture('mandala'))}
          className="absolute block cursor-pointer p-0"
          style={{
            left: roomPct(seats.mandala.cx - 75),
            top: roomPct(seats.mandala.cy - 75),
            width: roomPct(150),
            aspectRatio: '1 / 1',
            background: 'transparent',
            border: 'none',
          }}
        >
          <MandalaGlyph />
        </button>
      )}

      {/* the scales — an instrument; a weight rests in the pan only
          where the room's task carries a recorded estimate. Its
          object stands on its alcove's ledge line. */}
      <RoomArt
        testid="palace-room-scales"
        label="The scales"
        href={model.task.estimated_hours != null ? scalesWeighedImage : scalesImage}
        extent={SCALES_OBJECT}
        side={seats.scales.side}
        objCx={seats.scales.cx}
        objBottom={seats.scales.bottom}
        onClick={() => onFurniture('scales')}
      />

      {/* the chest — the founder's art in its two states: open
          where the room holds recorded material, closed where it
          holds none. Its object stands on its alcove's ledge
          line — in the rose chamber with its right edge at the
          wall, in the spiral and tiers chambers centred. */}
      <RoomArt
        testid="palace-room-chest"
        label="The chest"
        href={chestOpen ? chestOpenImage : chestImage}
        extent={chestOpen ? CHEST_OPEN_OBJECT : CHEST_OBJECT}
        side={seats.chest.side}
        objCx={seats.chest.cx}
        objRight={seats.chest.right}
        objBottom={seats.chest.bottom}
        onClick={() => onFurniture('chest')}
      />

      {/* the drawing table — the founder's art, standing behind
          the fire (the flame below renders in front of it) */}
      <RoomArt
        testid="palace-room-table"
        label="The drawing table"
        href={drawingTableImage}
        extent={TABLE_OBJECT}
        side={seats.table.side}
        objCx={seats.table.cx}
        objBottom={seats.table.bottom}
        onClick={() => onFurniture('table')}
      />

      {/* the hearth's flame — the founder's own flame standing in
          the plate's stone ring at 1.5× (his ruling, 2026-11-26
          18:55 PT), lit only when Maeve attends this room; it
          renders in front of the drawing table */}
      {lit && (
        <img
          src={fireImage}
          alt=""
          draggable={false}
          className="pointer-events-none absolute block"
          style={{
            left: roomPct(seats.flame.cx - (seats.flame.height * FLAME_ASPECT) / 2),
            top: roomPct(seats.flame.base - seats.flame.height),
            width: roomPct(seats.flame.height * FLAME_ASPECT),
          }}
        />
      )}
      {/* the hearth's front wall — the plate's own stonework over
          the flame's base, so the fire stands IN the pit (spiral
          and tiers; the rose chamber needs none). It is the plate
          itself, clipped to the band — nothing new is drawn. */}
      {seats.wallBand && (
        <div
          data-testid="palace-room-hearth-wall"
          aria-hidden
          className="pointer-events-none absolute inset-0"
          style={{
            backgroundImage: `url(${PLATE_URLS[plate]})`,
            backgroundSize: '100% 100%',
            clipPath: `inset(${roomPct(seats.wallBand.y0)} ${roomPct(ROOM_FRAME - seats.wallBand.x1)} ${roomPct(ROOM_FRAME - seats.wallBand.y1)} ${roomPct(seats.wallBand.x0)})`,
          }}
        />
      )}
      {/* the hearth — the plate's own stone ring; tapping it
          brings the fire, as it always did */}
      <button
        type="button"
        data-testid="palace-room-hearth"
        title="The hearth"
        aria-label="The hearth"
        onClick={onBringFire}
        className="absolute block cursor-pointer p-0"
        style={{
          left: roomPct(seats.hearth.cx - 80),
          top: roomPct(seats.hearth.cy - 85),
          width: roomPct(160),
          aspectRatio: '1 / 1',
          background: 'transparent',
          border: 'none',
        }}
      />

      {/* the Kintsugi vessel — the founder's art; gold seams only
          on recorded repair, otherwise the same vessel, unfilled.
          It stands on the floor, at its chamber's seat. */}
      <RoomArt
        testid="palace-room-vessel"
        label="The Kintsugi vessel"
        href={model.vesselGold || vesselGold ? vesselGoldImage : vesselPlainImage}
        extent={VESSEL_OBJECT}
        side={seats.vessel.side}
        objCx={seats.vessel.cx}
        objBottom={seats.vessel.bottom}
        onClick={() => onFurniture('vessel')}
      />

      {/* the plant, earned by the record's own growth reading */}
      {model.growth && (
        <RoomPlant
          state={model.growth}
          cx={seats.plant.cx}
          floorY={seats.plant.bottom}
          onClick={() => onFurniture('plant')}
        />
      )}

      {/* guest objects — a row on the floor front-left of the
          hearth, each standing only where the attributed read
          shows its seat attending this room's subject */}
      {onGuest &&
        rowGuests.map((seat, i) => {
          const glyph = GUEST_GLYPHS[seat]!
          const cx = seats.guestRow.startX + i * 64
          return (
            <button
              key={seat}
              type="button"
              data-testid={`palace-room-guest-${seat}`}
              title={glyph.title}
              aria-label={glyph.title}
              onClick={() => onGuest(seat)}
              className="absolute block cursor-pointer p-0"
              style={{
                left: roomPct(cx - glyph.w / 2),
                top: roomPct(seats.guestRow.bottom - glyph.h),
                width: roomPct(glyph.w),
                height: roomPct(glyph.h),
                background: 'transparent',
                border: 'none',
              }}
            >
              <svg viewBox={glyph.viewBox} className="block h-full w-full" aria-hidden>
                {glyph.body}
              </svg>
            </button>
          )
        })}

      {/* chambers within — the room's own subtasks, standing as
          doorways on the floor's front edge */}
      {model.subtasks.map((sub, i) => (
        <button
          key={sub.id}
          type="button"
          data-testid={`palace-subtask-${sub.id}`}
          title={sub.title}
          aria-label={sub.title}
          onClick={() => onOpenSubtask(sub.id)}
          className="absolute block cursor-pointer p-0"
          style={{
            left: roomPct(180 + i * 64 - 26),
            top: roomPct(seats.subtaskBottom - 86),
            width: roomPct(52),
            height: roomPct(86),
            background: 'transparent',
            border: 'none',
          }}
        >
          <svg viewBox="0 -12 52 86" className="block h-full w-full" aria-hidden>
            <path d="M 0 74 L 0 0 L 26 -12 L 52 0 L 52 74 Z" fill={PAL.woodDark} opacity={0.88} />
          </svg>
        </button>
      ))}

      {/* the entrance — a threshold, and an affordance: its tap
          area stands over the chamber's front steps */}
      <button
        type="button"
        data-testid="palace-room-threshold"
        title="The threshold"
        aria-label="The threshold"
        onClick={onThreshold}
        className="absolute block cursor-pointer p-0"
        style={{
          left: roomPct(seats.threshold.x),
          top: roomPct(seats.threshold.y),
          width: roomPct(seats.threshold.w),
          height: roomPct(seats.threshold.h),
          background: 'transparent',
          border: 'none',
        }}
      />
    </div>
  )
}
