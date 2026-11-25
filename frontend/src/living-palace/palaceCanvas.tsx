/**
 * The Living Palace — the drawn world.
 *
 * Geometry and rendering lifted from the founder-ruled prototype
 * (maeve-s-living-palace-interactive-increment-1): the seven-tongue
 * council flame from a single source, the stone-ring bonfire, the
 * stone hearth, buildings in three-quarter register with roofs
 * seated on their wall lines, the continuous 2.5D floor plan (rooms
 * sharing walls around a real hall), and the room cutaway whose
 * furniture sits IN the skewed wall planes. The prototype's fixture
 * is not used — every scene renders the live models from
 * palaceLogic.
 *
 * Surface rule: the scenes carry no legends, no vocabulary panels,
 * no explanations of themselves. What a tap reveals lives in the
 * view's panels and in Maeve's chat.
 */
import * as React from 'react'
import type {
  BuildingModel,
  CompoundModel,
  FloorModel,
  RoomModel,
} from './palaceLogic'
import { councilFlameColors, isDoneStatus } from './palaceLogic'
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

/** The stone hearth — surround, mantel, firebox; lit carries the
 *  seven tongues, unlit keeps embers. */
export function HearthGlyph({
  x,
  base,
  w,
  h,
  lit,
}: {
  x: number
  base: number
  w: number
  h: number
  lit: boolean
}) {
  const fbW = w * 0.52
  const fbH = h * 0.52
  return (
    <g pointerEvents="none">
      <rect x={x - w / 2} y={base - h} width={w} height={h} fill={PAL.stone} stroke={PAL.stoneDark} />
      <rect x={x - w / 2 - 3} y={base - h - 5} width={w + 6} height={7} fill={PAL.woodDark} />
      <rect
        x={x - fbW / 2}
        y={base - fbH}
        width={fbW}
        height={fbH}
        fill={lit ? '#5a3a22' : '#4c4034'}
      />
      {lit ? (
        <CouncilFlames cx={x} base={base - 1} h={fbH * 0.92} w={Math.max(10, fbH * 0.92 * 0.95)} />
      ) : (
        <g fill="#c96a2c">
          <circle cx={x - 3} cy={base - 3} r={1.8} opacity={0.85} />
          <circle cx={x + 4} cy={base - 2} r={1.4} opacity={0.7} />
        </g>
      )}
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

const CW = 900

interface Placed {
  x: number
  y: number
  w: number
  h: number
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
}: {
  model: CompoundModel
  attended: boolean
  onAttend: (on: boolean) => void
  onOpenBuilding: (initiativeId: string) => void
  onOpenProject: (projectId: string) => void
  onOpenTask: (taskId: string) => void
  onSelectIdea: (ideaId: string) => void
  selectedIdeaId: string | null
}) {
  // Flow the buildings in rows, biggest first (the model sorts them).
  const placed: { building: CompoundModel['buildings'][number]; box: Placed }[] = []
  let cx = 26
  let cy = 96
  let rowH = 0
  for (const b of model.buildings) {
    const w = Math.min(320, Math.max(200, 180 + b.roomCount * 3))
    const h = (b.form === 'pagoda' ? 168 : 128) + b.floors.length * 14
    if (cx + w > CW - 20 && cx > 26) {
      cx = 26
      cy += rowH + 64
      rowH = 0
    }
    placed.push({ building: b, box: { x: cx, y: cy, w, h } })
    cx += w + 30
    rowH = Math.max(rowH, h)
  }
  const buildingsBottom = placed.length ? cy + rowH : 130
  const groundsY = buildingsBottom + 44
  const H = groundsY + 400

  return (
    <svg
      viewBox={`0 0 ${CW} ${H}`}
      className="w-full h-auto block"
      role="img"
      aria-label="The Palace compound"
      onMouseLeave={() => onAttend(false)}
    >
      <rect x={0} y={0} width={CW} height={H} fill={PAL.sky} />
      <rect x={0} y={groundsY - 60} width={CW} height={H - groundsY + 60} fill={PAL.ground} />
      {/* paths from the gate to the buildings */}
      <path
        d={`M 450 ${H - 8} C 440 ${groundsY + 200}, 460 ${groundsY + 120}, 450 ${groundsY + 96}`}
        stroke={PAL.groundDark}
        strokeWidth={20}
        fill="none"
        opacity={0.7}
      />
      {placed.map(({ building: b, box }) => {
        const { x, y, w, h } = box
        const base = y + h
        const tiers = b.form === 'pagoda' ? 3 : 1
        return (
          <g
            key={b.initiative.id}
            data-testid={`palace-building-${b.initiative.id}`}
            onClick={() => onOpenBuilding(b.initiative.id)}
            onMouseEnter={() => onAttend(true)}
            style={{ cursor: 'pointer' }}
          >
            <title>{b.initiative.title}</title>
            <rect x={x - 6} y={base - 4} width={w + 12} height={8} fill={PAL.groundDark} />
            <rect x={x} y={y + 34} width={w} height={h - 34} fill={PAL.wall} stroke={WALL_LINE} strokeWidth={2} />
            {/* floors read as bands on the facade */}
            {b.floors.map((_, fi) => (
              <line
                key={fi}
                x1={x}
                x2={x + w}
                y1={y + 34 + ((h - 34) / Math.max(1, b.floors.length)) * (fi + 1)}
                y2={y + 34 + ((h - 34) / Math.max(1, b.floors.length)) * (fi + 1)}
                stroke={PAL.wallDark}
                strokeWidth={2}
              />
            ))}
            {/* windows */}
            {Array.from({ length: Math.max(2, Math.floor(w / 56)) }, (_, wi) => (
              <rect
                key={wi}
                x={x + 18 + wi * 56}
                y={y + 58}
                width={20}
                height={26}
                fill="#f6e7bd"
                stroke={WALL_LINE}
              />
            ))}
            {/* roof — seated on the wall lines; pagoda tiers at 40+ rooms */}
            {Array.from({ length: tiers }, (_, ti) => {
              const inset = ti * (w * 0.13)
              const ry = y + 34 - ti * 16
              return (
                <path
                  key={ti}
                  d={`M ${x + inset - 10} ${ry} L ${x + w / 2} ${ry - 26} L ${x + w - inset + 10} ${ry} Z`}
                  fill={ti === tiers - 1 ? PAL.roofDark : PAL.roof}
                  stroke={PAL.roofDark}
                />
              )
            })}
            {/* door + the map's cairn at the door */}
            <rect x={x + w / 2 - 13} y={base - 34} width={26} height={34} fill={PAL.woodDark} />
            <CairnGlyph x={x + w / 2 + 34} base={base} />
            {wrapTitle(b.initiative.title, 24, 2).map((line, li) => (
              <text
                key={li}
                x={x + w / 2}
                y={base + 22 + li * 15}
                textAnchor="middle"
                fontSize={13.5}
                fontWeight={600}
                fill={PAL.ink}
              >
                {line}
              </text>
            ))}
            <text x={x + w / 2} y={base + 22 + 30} textAnchor="middle" fontSize={10.5} fill={PAL.inkSoft}>
              {b.floors.length} floor{b.floors.length === 1 ? '' : 's'} · {b.roomCount} room{b.roomCount === 1 ? '' : 's'}
            </text>
          </g>
        )
      })}

      {/* the bonfire at the centre of the grounds */}
      <g onMouseEnter={() => onAttend(true)}>
        <Bonfire x={450} y={groundsY + 96} lit={attended} />
      </g>
      <text x={450} y={groundsY + 140} textAnchor="middle" fontSize={11} fill={PAL.inkSoft}>
        the council fire
      </text>

      {/* loose projects — their own structures on the grounds */}
      {model.looseProjects.map((p, i) => {
        const x = 36 + (i % 3) * 118
        const y = groundsY + 26 + Math.floor(i / 3) * 108
        return (
          <g
            key={p.id}
            data-testid={`palace-loose-project-${p.id}`}
            onClick={() => onOpenProject(p.id)}
            style={{ cursor: 'pointer' }}
          >
            <title>{p.title}</title>
            <rect x={x} y={y + 16} width={92} height={52} fill={PAL.wall} stroke={WALL_LINE} strokeWidth={2} />
            <path d={`M ${x - 6} ${y + 16} L ${x + 46} ${y - 8} L ${x + 98} ${y + 16} Z`} fill={PAL.roof} stroke={PAL.roofDark} />
            <rect x={x + 36} y={y + 40} width={18} height={28} fill={PAL.woodDark} />
            {wrapTitle(p.title, 15, 2).map((line, li) => (
              <text key={li} x={x + 46} y={y + 84 + li * 12} textAnchor="middle" fontSize={10.5} fill={PAL.ink}>
                {line}
              </text>
            ))}
          </g>
        )
      })}

      {/* loose tasks — standing stones on the open ground */}
      {model.looseTasks.map((t, i) => {
        const x = 596 + (i % 3) * 100
        const y = groundsY + 30 + Math.floor(i / 3) * 96
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

      {/* un-nested: the buildings' projects also stand on the grounds */}
      {model.standingProjects.map((p, i) => {
        const x = 36 + (i % 6) * 142
        const y = groundsY + 268 + Math.floor(i / 6) * 10
        return (
          <g
            key={p.id}
            data-testid={`palace-standing-project-${p.id}`}
            onClick={() => onOpenProject(p.id)}
            style={{ cursor: 'pointer' }}
          >
            <title>{p.title}</title>
            <rect x={x} y={y} width={118} height={30} fill={PAL.wall} stroke={WALL_LINE} strokeDasharray="4 3" />
            <text x={x + 59} y={y + 19} textAnchor="middle" fontSize={10} fill={PAL.ink}>
              {p.title.length > 17 ? `${p.title.slice(0, 16)}…` : p.title}
            </text>
          </g>
        )
      })}

      {/* the drawing table — undeveloped ideas rest on it */}
      <g data-testid="palace-drawing-table">
        <DrawingTable x={450} y={groundsY + 236} w={300} />
        {model.ideas.map((idea, i) => {
          const x = 336 + (i % 4) * 76
          const y = groundsY + 196 + Math.floor(i / 4) * 4
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
        <text x={450} y={groundsY + 282} textAnchor="middle" fontSize={11} fill={PAL.inkSoft}>
          the drawing table
        </text>
      </g>

      {/* released work at the south gate */}
      {model.releasedProjects.map((p, i) => {
        const x = 120 + i * 170
        const y = H - 64
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
  )
}

/* ------------------------------------------------------------------ */
/* building                                                            */
/* ------------------------------------------------------------------ */

export function BuildingScene({
  model,
  attendedFloorId,
  onAttend,
  onOpenFloor,
}: {
  model: BuildingModel
  attendedFloorId: string | null
  onAttend: (projectId: string | null) => void
  onOpenFloor: (projectId: string) => void
}) {
  const W = 720
  const storeyH = 98
  const top = 118
  const H = top + model.floors.length * storeyH + 56
  const x = 84
  const w = 552
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto block" role="img" aria-label={`Inside ${model.initiative.title}`}>
      <rect x={0} y={0} width={W} height={H} fill={PAL.sky} />
      <rect x={0} y={H - 40} width={W} height={40} fill={PAL.ground} />
      {/* roof seated on the wall lines */}
      <path d={`M ${x - 14} ${top} L ${x + w / 2} ${top - 58} L ${x + w + 14} ${top} Z`} fill={PAL.roof} stroke={PAL.roofDark} strokeWidth={2} />
      {model.floors.map((floor, i) => {
        const y = top + i * storeyH
        const lit = attendedFloorId === floor.project.id
        return (
          <g
            key={floor.project.id}
            data-testid={`palace-floor-${floor.project.id}`}
            onClick={() => onOpenFloor(floor.project.id)}
            onMouseEnter={() => onAttend(floor.project.id)}
            onMouseLeave={() => onAttend(null)}
            style={{ cursor: 'pointer' }}
          >
            <title>{floor.project.title}</title>
            <rect x={x} y={y} width={w} height={storeyH} fill={i % 2 ? '#eee2cb' : PAL.wall} stroke={WALL_LINE} strokeWidth={2} />
            {/* the floor's hearth, in the side wall's frame */}
            <g transform={`translate(${x + w - 58} ${y + storeyH - 12})`}>
              <HearthGlyph x={0} base={0} w={52} h={62} lit={lit} />
            </g>
            {/* the balcony ledge and what the floor's rooms earn onto it */}
            <rect x={x + w - 128} y={y + storeyH - 10} width={120} height={6} fill={PAL.woodDark} />
            {floor.plant && <PlantGlyph x={x + w - 108} base={y + storeyH - 10} state={floor.plant} scale={0.8} />}
            {/* hanging sign: floor number, name, room count */}
            <g transform={`translate(${x + 26} ${y + 16})`}>
              <line x1={10} y1={-14} x2={10} y2={0} stroke={PAL.stoneDark} strokeWidth={2} />
              <line x1={150} y1={-14} x2={150} y2={0} stroke={PAL.stoneDark} strokeWidth={2} />
              <rect x={0} y={0} width={252} height={52} rx={4} fill={PAL.paper} stroke={PAL.stoneDark} />
              <text x={12} y={21} fontSize={12.5} fontWeight={600} fill={PAL.ink}>
                Floor {model.floors.length - i} · {floor.project.title.length > 26 ? `${floor.project.title.slice(0, 25)}…` : floor.project.title}
              </text>
              <text x={12} y={40} fontSize={11} fill={PAL.inkSoft}>
                {floor.roomCount} room{floor.roomCount === 1 ? '' : 's'}
                {floor.released ? ' · released' : ''}
              </text>
            </g>
            {/* windows along the storey */}
            {[0, 1, 2].map((wi) => (
              <rect key={wi} x={x + 306 + wi * 52} y={y + 26} width={24} height={32} fill="#f6e7bd" stroke={WALL_LINE} />
            ))}
          </g>
        )
      })}
      {model.floors.length === 0 && (
        <text x={W / 2} y={top + 40} textAnchor="middle" fontSize={13} fill={PAL.inkSoft}>
          No floors yet — no projects stand under this initiative.
        </text>
      )}
      <text x={W / 2} y={30} textAnchor="middle" fontSize={16} fontWeight={600} fill={PAL.ink}>
        {model.initiative.title}
      </text>
      <text x={W / 2} y={52} textAnchor="middle" fontSize={11.5} fill={PAL.inkSoft}>
        each floor is one of its projects — tap a floor to walk it
      </text>
    </svg>
  )
}

/* ------------------------------------------------------------------ */
/* floor                                                               */
/* ------------------------------------------------------------------ */

export function FloorScene({
  model,
  onOpenRoom,
  onThreshold,
  onScales,
  guests = [],
  onGuest,
}: {
  model: FloorModel
  onOpenRoom: (taskId: string) => void
  onThreshold: () => void
  onScales: () => void
  /** Seats the attributed read shows attending this floor's subject
   *  — their marks stand in the hall, and only theirs. */
  guests?: SeatId[]
  onGuest?: (seat: SeatId) => void
}) {
  const W = 640
  const pad = 14
  const hallL = 272
  const hallR = 368
  const rowH = 118
  const rows = Math.max(1, Math.ceil(model.rooms.length / 2))
  const planH = rows * rowH
  const top = 16
  const H = top + planH + 118
  const roomW = hallL - pad
  const doorwayPairs = new Map<string, string>()
  for (const d of model.doorways) {
    doorwayPairs.set(d.aId, d.bId)
    doorwayPairs.set(d.bId, d.aId)
  }
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto block" role="img" aria-label={`Floor plan — ${model.project.title}`}>
      <rect x={0} y={0} width={W} height={H} fill={PAL.sky} />
      {/* the hall */}
      <rect x={hallL} y={top} width={hallR - hallL} height={planH} fill={PAL.hall} />
      {/* rooms */}
      {model.rooms.map((room) => {
        const rx = room.col === 0 ? pad : hallR
        const ry = top + room.row * rowH
        return (
          <g
            key={room.task.id}
            data-testid={`palace-room-${room.task.id}`}
            onClick={() => onOpenRoom(room.task.id)}
            style={{ cursor: 'pointer' }}
          >
            <title>{room.task.title}</title>
            <rect x={rx} y={ry} width={roomW} height={rowH} fill={PAL.wall} stroke={WALL_LINE} strokeWidth={3} />
            {/* exterior window */}
            <rect
              x={room.col === 0 ? rx + 2 : rx + roomW - 14}
              y={ry + 30}
              width={12}
              height={44}
              fill={room.waitsOn.length ? '#f2dfae' : '#f6e7bd'}
              stroke={WALL_LINE}
            />
            {/* door leaf + swing, off the hall */}
            <g stroke={PAL.woodDark} strokeWidth={2.5} fill="none">
              <line
                x1={room.col === 0 ? rx + roomW : rx}
                y1={ry + rowH - 12}
                x2={room.col === 0 ? rx + roomW - 30 : rx + 30}
                y2={ry + rowH - 12}
              />
              <path
                d={
                  room.col === 0
                    ? `M ${rx + roomW - 30} ${ry + rowH - 12} A 30 30 0 0 1 ${rx + roomW} ${ry + rowH - 42}`
                    : `M ${rx + 30} ${ry + rowH - 12} A 30 30 0 0 0 ${rx} ${ry + rowH - 42}`
                }
                strokeWidth={1.2}
                opacity={0.6}
              />
            </g>
            {wrapTitle(room.task.title, 21, 2).map((line, li) => (
              <text key={li} x={rx + roomW / 2} y={ry + 40 + li * 16} textAnchor="middle" fontSize={13} fontWeight={600} fill={PAL.ink}>
                {line}
              </text>
            ))}
            <text x={rx + roomW / 2} y={ry + 82} textAnchor="middle" fontSize={10.5} fill={PAL.inkSoft}>
              {room.task.status}
              {room.subtaskCount ? ` · ${room.subtaskCount} within` : ''}
            </text>
            {room.growth && <PlantGlyph x={rx + roomW - 30} base={ry + rowH - 8} state={room.growth} scale={0.62} />}
            {room.holdsMaterial && (
              <g transform={`translate(${rx + 26} ${ry + rowH - 24})`}>
                <rect x={-11} y={-9} width={22} height={15} rx={2} fill={PAL.wood} stroke={PAL.woodDark} />
                <rect x={-11} y={-13} width={22} height={6} rx={2} fill={PAL.woodDark} />
              </g>
            )}
          </g>
        )
      })}
      {/* labelled dependency doorways in shared partitions */}
      {model.doorways.map((d) => {
        const a = model.rooms.find((r) => r.task.id === d.aId)
        const b = model.rooms.find((r) => r.task.id === d.bId)
        if (!a || !b) return null
        const upper = a.row < b.row ? a : b
        const rx = upper.col === 0 ? pad : hallR
        const yMid = top + (upper.row + 1) * rowH
        return (
          <g key={`${d.aId}-${d.bId}`} pointerEvents="none">
            <rect x={rx + roomW / 2 - 21} y={yMid - 4} width={42} height={8} fill={PAL.hall} />
            <g stroke={PAL.woodDark} strokeWidth={2.4}>
              <line x1={rx + roomW / 2 - 20} y1={yMid} x2={rx + roomW / 2 - 20} y2={yMid - 22} />
              <line x1={rx + roomW / 2 + 20} y1={yMid} x2={rx + roomW / 2 + 20} y2={yMid - 22} />
            </g>
            <text x={rx + roomW / 2} y={yMid + 16} textAnchor="middle" fontSize={8.6} letterSpacing={0.6} fill={PAL.inkSoft}>
              RECORDED EDGE · DOORWAY
            </text>
          </g>
        )
      })}
      {/* the floor's ONE hearth, set into the hall's north wall */}
      <g data-testid="palace-floor-hearth">
        <HearthGlyph x={(hallL + hallR) / 2} base={top + 44} w={46} h={44} lit />
      </g>
      {/* hall furniture, each piece earned */}
      {model.cabinets && (
        <g pointerEvents="none">
          <rect x={hallL + 8} y={top + 120} width={26} height={54} fill={PAL.wood} stroke={PAL.woodDark} />
          <line x1={hallL + 21} y1={top + 120} x2={hallL + 21} y2={top + 174} stroke={PAL.woodDark} />
        </g>
      )}
      {model.mosaic && (
        <g pointerEvents="none" opacity={0.85}>
          <circle cx={(hallL + hallR) / 2} cy={top + planH / 2 + 26} r={17} fill="none" stroke={PAL.maeve} strokeWidth={2} />
          <circle cx={(hallL + hallR) / 2} cy={top + planH / 2 + 26} r={10} fill="none" stroke={PAL.maeve} strokeWidth={1.4} />
          <circle cx={(hallL + hallR) / 2} cy={top + planH / 2 + 26} r={3.4} fill={PAL.maeve} />
        </g>
      )}
      {model.scalesFigures && (
        <g
          data-testid="palace-floor-scales"
          onClick={onScales}
          style={{ cursor: 'pointer' }}
          transform={`translate(${hallR - 24} ${top + 132})`}
        >
          <title>The floor's scales</title>
          <circle cx={0} cy={-8} r={30} fill="transparent" />
          <ScalesGlyph scale={0.8} />
        </g>
      )}
      {/* gathering table in the hall — recorded people, empty places */}
      <g pointerEvents="none" transform={`translate(${(hallL + hallR) / 2} ${top + planH - 44})`}>
        <ellipse cx={0} cy={0} rx={34} ry={13} fill={PAL.wood} stroke={PAL.woodDark} />
        {Array.from({ length: Math.max(4, model.people.length) }, (_, i) => {
          const a = (i / Math.max(4, model.people.length)) * Math.PI * 2
          const px = Math.cos(a) * 42
          const py = Math.sin(a) * 18
          const person = model.people[i]
          return person ? (
            <g key={i}>
              <circle cx={px} cy={py} r={8} fill={PAL.maeve} />
              <text x={px} y={py + 3.4} textAnchor="middle" fontSize={8.5} fill="#fff">
                {person.name.slice(0, 1)}
              </text>
            </g>
          ) : (
            <circle key={i} cx={px} cy={py} r={7.5} fill="none" stroke={PAL.stoneDark} strokeDasharray="3 2.4" />
          )
        })}
      </g>
      {/* the drawing table stands on every floor */}
      <DrawingTable x={(hallL + hallR) / 2} y={top + planH + 30} w={120} />
      {/* guest marks in the hall — a seat's token stands here only
          where the attributed read shows that seat attending this
          floor's subject (Guests-1) */}
      {onGuest &&
        guests.map((seat, i) => {
          const cx = (hallL + hallR) / 2 + (i - (guests.length - 1) / 2) * 30
          const cy = top + planH + 84
          return (
            <g
              key={seat}
              data-testid={`palace-floor-guest-${seat}`}
              onClick={() => onGuest(seat)}
              style={{ cursor: 'pointer' }}
            >
              <title>A guest attends this floor</title>
              <circle cx={cx} cy={cy} r={12} fill={SEAT_COLORS[seat]} stroke="#fffaf0" strokeWidth={2} />
              <circle cx={cx} cy={cy} r={12} fill="none" stroke={PAL.stoneDark} strokeWidth={0.8} />
            </g>
          )
        })}
      {/* the entrance — a threshold, and an affordance */}
      <g
        data-testid="palace-floor-threshold"
        onClick={onThreshold}
        style={{ cursor: 'pointer' }}
      >
        <title>The threshold</title>
        <rect x={(hallL + hallR) / 2 - 30} y={top + planH} width={60} height={10} fill="transparent" />
        <rect x={(hallL + hallR) / 2 - 27} y={top + planH + 1} width={54} height={7} rx={2} fill={PAL.stone} stroke={PAL.stoneDark} />
        <g stroke={PAL.woodDark} strokeWidth={2.6}>
          <line x1={(hallL + hallR) / 2 - 24} y1={top + planH} x2={(hallL + hallR) / 2 - 24} y2={top + planH - 26} />
          <line x1={(hallL + hallR) / 2 + 24} y1={top + planH} x2={(hallL + hallR) / 2 + 24} y2={top + planH - 26} />
        </g>
      </g>
      {model.rooms.length === 0 && (
        <text x={W / 2} y={top + 60} textAnchor="middle" fontSize={13} fill={PAL.inkSoft}>
          An empty floor — no tasks stand here yet.
        </text>
      )}
    </svg>
  )
}

/** Scales with empty pans — an instrument, unweighed. */
export function ScalesGlyph({ scale = 1 }: { scale?: number }) {
  return (
    <g transform={`scale(${scale})`} pointerEvents="none">
      <line x1={0} y1={-26} x2={0} y2={10} stroke={PAL.inkSoft} strokeWidth={2.6} />
      <line x1={-24} y1={-22} x2={24} y2={-22} stroke={PAL.inkSoft} strokeWidth={2.6} />
      <circle cx={0} cy={-28} r={3.4} fill={PAL.inkSoft} />
      {[-24, 24].map((px) => (
        <g key={px}>
          <line x1={px} y1={-22} x2={px - 8} y2={-8} stroke={PAL.inkSoft} strokeWidth={1.3} />
          <line x1={px} y1={-22} x2={px + 8} y2={-8} stroke={PAL.inkSoft} strokeWidth={1.3} />
          <path d={`M ${px - 11} -8 A 11 5 0 0 0 ${px + 11} -8 Z`} fill={PAL.stone} stroke={PAL.stoneDark} />
        </g>
      ))}
      <rect x={-10} y={10} width={20} height={5} rx={2} fill={PAL.stoneDark} />
    </g>
  )
}

/* ------------------------------------------------------------------ */
/* room                                                                */
/* ------------------------------------------------------------------ */

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
}: {
  model: RoomModel
  lit: boolean
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
  const W = 640
  const H = 430
  const waited = model.waitsOn[0]
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto block" role="img" aria-label={`Room — ${model.task.title}`}>
      {/* back wall + floor */}
      <rect x={70} y={56} width={500} height={264} fill={PAL.wall} />
      <path d={`M 70 320 L 570 320 L 626 402 L 14 402 Z`} fill="#d9c8a6" stroke={WALL_LINE} />
      {/* side walls, so furniture sits IN the planes */}
      <polygon points="14,402 70,320 70,56 14,120" fill="#e6dbc0" />
      <polygon points="626,402 570,320 570,56 626,120" fill="#e6dbc0" />
      <rect x={70} y={56} width={500} height={264} fill="none" stroke={WALL_LINE} strokeWidth={2} />

      {/* the window in the right wall — the waited-on room's state */}
      <g
        data-testid="palace-room-window"
        onClick={() => waited && onOpenWaitedOn(waited.id)}
        style={{ cursor: waited ? 'pointer' : 'default' }}
        transform="matrix(-1 0.44 0 1 640 -158)"
      >
        <rect x={26} y={252} width={34} height={66} fill="#f3e9cd" stroke={WALL_LINE} strokeWidth={2} />
        {model.windowState === 'building' && (
          <g stroke="#8a7a5c" strokeWidth={1.6}>
            <line x1={28} y1={292} x2={58} y2={292} />
            <line x1={28} y1={282} x2={52} y2={282} />
            <line x1={28} y1={272} x2={46} y2={272} />
          </g>
        )}
        {model.windowState === 'complete' && (
          <g stroke="#8a7a5c" strokeWidth={1.6}>
            <line x1={28} y1={296} x2={58} y2={296} />
            <line x1={28} y1={286} x2={58} y2={286} />
            <line x1={28} y1={276} x2={58} y2={276} />
            <line x1={28} y1={266} x2={58} y2={266} />
          </g>
        )}
        {!model.windowState && (
          <g>
            <circle cx={43} cy={272} r={4} fill="#e8b64c" />
            <line x1={28} y1={300} x2={58} y2={300} stroke="#9db38a" strokeWidth={2.4} />
          </g>
        )}
      </g>
      {model.growth && (
        <g data-testid="palace-room-plant" onClick={() => onFurniture('plant')} style={{ cursor: 'pointer' }}>
          <circle cx={556} cy={292} r={30} fill="transparent" />
          <PlantGlyph x={556} base={316} state={model.growth} scale={0.9} />
        </g>
      )}

      {/* hearth in the left wall */}
      <g
        data-testid="palace-room-hearth"
        onClick={onBringFire}
        style={{ cursor: 'pointer' }}
        transform="matrix(1 0.44 0 1 0 -158)"
      >
        <title>The hearth</title>
        <rect x={19} y={310} width={48} height={92} fill="transparent" />
        <HearthGlyph x={43} base={402} w={44} h={86} lit={lit} />
      </g>

      {/* the doorway, with its threshold slab */}
      <g data-testid="palace-room-threshold" onClick={onThreshold} style={{ cursor: 'pointer' }}>
        <title>The threshold</title>
        <g transform="matrix(-1 0.44 0 1 640 -158)">
          <rect x={86} y={238} width={40} height={164} fill="#cbb691" opacity={0} />
          <path d="M 92 402 L 92 268 L 120 252 L 120 402 Z" fill={PAL.woodDark} opacity={0.9} />
        </g>
        <rect x={492} y={392} width={64} height={9} rx={2} fill={PAL.stone} stroke={PAL.stoneDark} />
      </g>

      {/* chambers within — the room's own subtasks, behind doorways */}
      {model.subtasks.map((sub, i) => {
        const x = 150 + i * 92
        return (
          <g
            key={sub.id}
            data-testid={`palace-subtask-${sub.id}`}
            onClick={() => onOpenSubtask(sub.id)}
            style={{ cursor: 'pointer' }}
          >
            <title>{sub.title}</title>
            <path d={`M ${x} 320 L ${x} 246 L ${x + 26} 234 L ${x + 52} 246 L ${x + 52} 320 Z`} fill={PAL.woodDark} opacity={0.88} />
            <text x={x + 26} y={338} textAnchor="middle" fontSize={9.5} fill={PAL.ink}>
              {sub.title.length > 12 ? `${sub.title.slice(0, 11)}…` : sub.title}
            </text>
          </g>
        )
      })}

      {/* the mandala — earned where recorded edges converge, or
          standing as Aria's guest object where she attends */}
      {(model.mandala || guests.includes('conductor')) && (
        <g
          data-testid="palace-room-mandala"
          onClick={() => (guests.includes('conductor') && onGuest ? onGuest('conductor') : onFurniture('mandala'))}
          style={{ cursor: 'pointer' }}
        >
          <g transform="translate(320 366)" opacity={0.9}>
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
        </g>
      )}

      {/* the gathering table — recorded people, empty places */}
      <g data-testid="palace-room-table" onClick={() => onFurniture('table')} style={{ cursor: 'pointer' }}>
        <g transform="translate(268 356)">
          <ellipse cx={0} cy={10} rx={86} ry={20} fill={PAL.wood} stroke={PAL.woodDark} strokeWidth={2} />
          <ellipse cx={0} cy={4} rx={86} ry={20} fill="#bd9260" stroke={PAL.woodDark} strokeWidth={2} />
          {Array.from({ length: Math.max(4, model.people.length) }, (_, i) => {
            const n = Math.max(4, model.people.length)
            const a = (i / n) * Math.PI * 2 + 0.5
            const px = Math.cos(a) * 96
            const py = Math.sin(a) * 26 + 4
            const person = model.people[i]
            return person ? (
              <g key={i}>
                <circle cx={px} cy={py} r={11} fill={PAL.maeve} stroke="#8a6248" />
                <text x={px} y={py + 4} textAnchor="middle" fontSize={10} fill="#fff">
                  {person.name.slice(0, 1)}
                </text>
              </g>
            ) : (
              <circle key={i} cx={px} cy={py} r={10} fill="none" stroke={PAL.stoneDark} strokeWidth={1.6} strokeDasharray="3.4 2.6" />
            )
          })}
        </g>
      </g>

      {/* the scales — an instrument, its pans empty */}
      <g data-testid="palace-room-scales" onClick={() => onFurniture('scales')} style={{ cursor: 'pointer' }}>
        <circle cx={452} cy={362} r={36} fill="transparent" />
        <g transform="translate(452 372)">
          <ScalesGlyph scale={1.15} />
        </g>
      </g>

      {/* the chest — ajar only where the task holds recorded material */}
      <g data-testid="palace-room-chest" onClick={() => onFurniture('chest')} style={{ cursor: 'pointer' }}>
        <g transform="translate(120 384)">
          <rect x={-34} y={-16} width={68} height={34} rx={3} fill={PAL.wood} stroke={PAL.woodDark} strokeWidth={2} />
          {model.held ? (
            <path d="M -34 -16 L -40 -30 L 28 -30 L 34 -16 Z" fill={PAL.woodDark} />
          ) : (
            <rect x={-34} y={-24} width={68} height={10} rx={3} fill={PAL.woodDark} />
          )}
          <rect x={-5} y={-6} width={10} height={12} fill="#d8b25c" stroke="#a97e2f" />
        </g>
      </g>

      {/* the Kintsugi vessel — whole and empty; gold only on recorded repair */}
      <g data-testid="palace-room-vessel" onClick={() => onFurniture('vessel')} style={{ cursor: 'pointer' }}>
        <g transform="translate(520 388)">
          <path
            d="M -16 14 C -20 -2, -14 -14, -6 -20 L 6 -20 C 14 -14, 20 -2, 16 14 C 10 20, -10 20, -16 14 Z"
            fill="#e6dcc4"
            stroke={PAL.stoneDark}
            strokeWidth={1.8}
          />
          <ellipse cx={0} cy={-20} rx={7} ry={2.6} fill="#d9cbaa" stroke={PAL.stoneDark} />
          {(model.vesselGold || vesselGold) && (
            <path d="M -8 -18 C -2 -6, 2 4, -3 16" stroke="#d4af37" strokeWidth={2.2} fill="none" />
          )}
        </g>
      </g>

      {/* guest objects — each stands ONLY where the attributed read
          shows its seat attending this room's subject (Guests-1);
          each keeps its own form, as a guest here */}
      {onGuest && guests.includes('champion') && (
        <g data-testid="palace-room-guest-champion" onClick={() => onGuest('champion')} style={{ cursor: 'pointer' }}>
          <title>Valen's battle plan</title>
          <g transform="translate(452 108)">
            <rect x={-31} y={-23} width={62} height={46} rx={2} fill={PAL.paper} stroke={PAL.stoneDark} strokeWidth={1.6} />
            <polyline points="-21,13 -7,-5 7,7 21,-13" fill="none" stroke={SEAT_COLORS.champion} strokeWidth={2.2} />
            <circle cx={-21} cy={13} r={3.2} fill={SEAT_COLORS.champion} />
            <circle cx={21} cy={-13} r={3.2} fill={SEAT_COLORS.champion} />
          </g>
        </g>
      )}
      {onGuest && guests.includes('skeptic') && (
        <g data-testid="palace-room-guest-skeptic" onClick={() => onGuest('skeptic')} style={{ cursor: 'pointer' }}>
          <title>Severine's lens</title>
          <g transform="translate(140 205)">
            <circle r={15} fill="#eef2f7" opacity={0.6} stroke={PAL.stoneDark} strokeWidth={3} />
            <line x1={10} y1={10} x2={25} y2={25} stroke={PAL.woodDark} strokeWidth={5} strokeLinecap="round" />
          </g>
        </g>
      )}
      {onGuest && guests.includes('ambassador') && (
        <g data-testid="palace-room-guest-ambassador" onClick={() => onGuest('ambassador')} style={{ cursor: 'pointer' }}>
          <title>Lucian's cup</title>
          <g transform="translate(200 340)">
            <ellipse cx={0} cy={11} rx={15} ry={3.4} fill={PAL.stone} stroke={PAL.stoneDark} />
            <path d="M -11 -3 L 11 -3 L 8 9 L -8 9 Z" fill="#eef2f7" stroke={SEAT_COLORS.ambassador} strokeWidth={1.8} />
            <path d="M 11 -1 A 5.5 4.5 0 1 1 11 6" fill="none" stroke={SEAT_COLORS.ambassador} strokeWidth={1.8} />
          </g>
        </g>
      )}
      {onGuest && guests.includes('maverick') && (
        <g data-testid="palace-room-guest-maverick" onClick={() => onGuest('maverick')} style={{ cursor: 'pointer' }}>
          <title>Jynx's scroll</title>
          <g transform="translate(202 398)">
            <rect x={-25} y={-7} width={45} height={14} rx={7} fill={PAL.paper} stroke={SEAT_COLORS.maverick} strokeWidth={1.8} />
            <circle cx={20} cy={0} r={7} fill="#e6dcc4" stroke={SEAT_COLORS.maverick} strokeWidth={1.8} />
            <circle cx={20} cy={0} r={2.8} fill="none" stroke={SEAT_COLORS.maverick} strokeWidth={1.4} />
          </g>
        </g>
      )}
      {onGuest && guests.includes('mentor') && (
        <g data-testid="palace-room-guest-mentor" onClick={() => onGuest('mentor')} style={{ cursor: 'pointer' }}>
          <title>Rumi's cairn</title>
          <g transform="translate(448 396)">
            <ellipse cx={0} cy={6} rx={16} ry={5} fill={PAL.stone} stroke={PAL.stoneDark} />
            <ellipse cx={0} cy={-1} rx={11.5} ry={4.4} fill="#c4b494" stroke={PAL.stoneDark} />
            <ellipse cx={0} cy={-7.5} rx={7.5} ry={3.8} fill={SEAT_COLORS.mentor} stroke={PAL.stoneDark} />
          </g>
        </g>
      )}

      {/* the name plate */}
      <g pointerEvents="none">
        {wrapTitle(model.task.title, 30, 2).map((line, li) => (
          <text key={li} x={84} y={92 + li * 21} fontSize={17} fontWeight={600} fill={PAL.ink}>
            {line}
          </text>
        ))}
        <text x={84} y={92 + 48} fontSize={11.5} fill={PAL.inkSoft}>
          {model.task.status}
          {model.project ? ` · ${model.project.title}` : ' · standing on the grounds'}
          {model.initiative ? ` · ${model.initiative.title}` : ''}
        </text>
      </g>
    </svg>
  )
}
