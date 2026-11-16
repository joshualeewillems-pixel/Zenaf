/**
 * LivingSkyScene — the accepted Living Sky painting as the Living
 * Tree's visual renderer (port plan §1, §5, §8 Increment 1; founder
 * ruling 2026-11-16 08:53 PT).
 *
 * LivingTreeView remains the home-view controller; this component is
 * only its current visual renderer. It consumes the view's existing
 * data (attention/invitation badges, the user's photo) and routes
 * every tap through the view's existing `onTap` handler — no second
 * tree engine, no separate chat mode. The living model underneath
 * (depth, decay, twigs, panels) is untouched and keeps functioning;
 * the painting is the first visible expression of the tree, not its
 * replacement.
 *
 * Scene (400×660 units, layers bottom → top): world plate → ink-wash
 * dawn/dusk + night/tint grades (plate only) → celestial group
 * (mountain-masked: clock tracks, stars, moon, ensō sun) → painted
 * tree stack → transparent hit overlay carrying the 15 medallion tap
 * groups, the attention/invitation badges, and the user's photo over
 * the YOU disc.
 *
 * Increment 1 scope: weather fixed to Clear (the study's Clear row
 * of every dimmer table); the study's toggles (Ensō turns, Clock
 * ticks, Constellation lines, Wide sky) keep their study defaults —
 * turns ON, ticks ON, lines OFF, Wide OFF — with the toggle UI itself
 * arriving in Increment 3. The paper-moon variant is NOT ported
 * (founder reverted it 2026-11-16 01:11 PT: "purple was better").
 *
 * Animation discipline (the study's): the SVG is built once and
 * mutated via refs from one rAF loop — astronomy recomputed at 1 Hz,
 * the ensō rotations (pure functions of the minute) every frame, and
 * no work at all while the tab is hidden. No raster image sits
 * inside any mask or clipPath (the founder's on-device law).
 */
import { useEffect, useRef } from 'react'
import {
  APTOS_LAT,
  APTOS_LON,
  bodyTimes,
  ensoAngleDeg,
  moonLitPoints,
  moonRingAngleDeg,
  stateAt,
  starFill,
  sunArcPos,
  tickMarks,
  washF,
  type TickSeg,
} from './astro'
import { SKY_PATH_D, STARS } from './skyData'
import { HIT_NODES, PAINTSTACK_TRANSFORM } from './skyGeometry'
import { USER_WEAVE_COLOR } from '../council/colors'
import plateUrl from '../assets/living-sky/plate.webp'
import washUrl from '../assets/living-sky/wash-dawn.webp'
import canopyBackUrl from '../assets/living-sky/canopy-back.webp'
import glowColourUrl from '../assets/living-sky/glow-colour.webp'
import glowWhiteUrl from '../assets/living-sky/glow-white.webp'
import treePaintedUrl from '../assets/living-sky/tree-painted.webp'
import canopyForeUrl from '../assets/living-sky/canopy-fore.webp'
import ensoSunUrl from '../assets/living-sky/enso-sun.webp'
import ensoMoonUrl from '../assets/living-sky/enso-moon.webp'
import moonFaceUrl from '../assets/living-sky/moon-face.webp'

/**
 * One seat's badge state, computed by LivingTreeView from the same
 * live data (archetype status + keystone attention) and the same
 * helpers (`markerTitle`, `invitationIndicatorLabel`) the
 * computational tree used — the scene renders, the view decides.
 */
export interface SkyBadge {
  /** Attention "!" aria label + title; present iff the marker shows. */
  attentionTitle?: string
  /** Invitation aria label; null/absent renders no indicator. */
  inviteLabel?: string | null
  /** Invitation count for the indicator's text (capped at '9+'). */
  inviteCount?: number
}

export interface LivingSkySceneProps {
  /** Badges keyed by archetype id (seats only). */
  badges: Record<string, SkyBadge>
  /** The signed-in user's profile photo for the YOU disc overlay. */
  userAvatarUrl?: string | null
  /** The photo failed to load — the painted YOU disc shows instead. */
  youImgBroken: boolean
  onYouImgError: () => void
  /** The view's existing tap handler, receiving production datum ids. */
  onTap: (id: string) => void
}

const YOU_NODE = HIT_NODES.find((n) => n.id === 'you')!

/* The moon's lit-boundary path in local coords (r = 20, pre-×1.5). */
function moonPathD(k: number, r: number): string {
  const pts = moonLitPoints(k)
  let d = ''
  pts.forEach((p, i) => {
    d += (i ? 'L' : 'M') + (p[0] * r).toFixed(2) + ' ' + (p[1] * r).toFixed(2)
  })
  return pts.length ? d + 'Z' : ''
}
const MOON_DARK_D = moonPathD(1, 20)

/* Clock stations: a tick segment starts ON the body's path at an
 * hour point and runs along the path normal; a station is the
 * crossbar centred on that point (study clock redesign). */
interface Station {
  x: number
  y: number
  nx: number
  ny: number
}
function stationOf(s: TickSeg): Station {
  const dx = s.x2 - s.x1
  const dy = s.y2 - s.y1
  const L = Math.hypot(dx, dy) || 1
  return { x: s.x1, y: s.y1, nx: dx / L, ny: dy / L }
}
function stationSeg(st: Station, len: number): string {
  const h = len / 2
  return (
    'M' +
    (st.x - st.nx * h).toFixed(1) +
    ' ' +
    (st.y - st.ny * h).toFixed(1) +
    'L' +
    (st.x + st.nx * h).toFixed(1) +
    ' ' +
    (st.y + st.ny * h).toFixed(1)
  )
}

export function LivingSkyScene({
  badges,
  userAvatarUrl,
  youImgBroken,
  onYouImgError,
  onTap,
}: LivingSkySceneProps) {
  const washRef = useRef<SVGImageElement | null>(null)
  const gradeNightRef = useRef<SVGRectElement | null>(null)
  const gradeTintRef = useRef<SVGRectElement | null>(null)
  const sunClockRef = useRef<SVGGElement | null>(null)
  const moonClockRef = useRef<SVGGElement | null>(null)
  const sunTrackRef = useRef<SVGPathElement | null>(null)
  const moonTrackRef = useRef<SVGPathElement | null>(null)
  const tickSunRef = useRef<SVGPathElement | null>(null)
  const tickMoonRef = useRef<SVGPathElement | null>(null)
  const tickSunNowRef = useRef<SVGPathElement | null>(null)
  const tickMoonNowRef = useRef<SVGPathElement | null>(null)
  const tickNoonRef = useRef<SVGTextElement | null>(null)
  const starElsRef = useRef<Array<SVGCircleElement | null>>([])
  const moonGRef = useRef<SVGGElement | null>(null)
  const moonRotRef = useRef<SVGGElement | null>(null)
  const moonLitRef = useRef<SVGPathElement | null>(null)
  const moonDarkRef = useRef<SVGPathElement | null>(null)
  const moonRingRef = useRef<SVGImageElement | null>(null)
  const sunGRef = useRef<SVGGElement | null>(null)
  const sunDiscRef = useRef<SVGImageElement | null>(null)

  useEffect(() => {
    let clockKey = ''
    let clock: ReturnType<typeof tickMarks> | null = null
    let sunStations: Station[] = []
    let moonStations: Station[] = []
    let lastLitKey = -1
    let lastSec = -1
    let raf = 0

    /* Static-per-date clock geometry: tracks, stations, the XII. */
    const buildClock = (now: Date) => {
      const TK = tickMarks(now, APTOS_LAT, APTOS_LON)
      clock = TK
      sunStations = TK.sun.map(stationOf)
      moonStations = TK.moon.map(stationOf)
      tickSunRef.current?.setAttribute(
        'd',
        sunStations.map((s) => stationSeg(s, 8)).join(''),
      )
      tickMoonRef.current?.setAttribute(
        'd',
        moonStations.map((s) => stationSeg(s, 8)).join(''),
      )
      let d = ''
      for (let i = 0; i <= 60; i++) {
        const p = sunArcPos(i / 60)
        d += (i ? 'L' : 'M') + p.x.toFixed(1) + ' ' + p.y.toFixed(1)
      }
      sunTrackRef.current?.setAttribute('d', d)
      moonTrackRef.current?.setAttribute(
        'd',
        moonStations
          .map((s, i) => (i ? 'L' : 'M') + s.x.toFixed(1) + ' ' + s.y.toFixed(1))
          .join(''),
      )
      /* The clock's only numeral: XII above the sun's noon station —
       * the hour nearest the day's midpoint. */
      const T = bodyTimes(now, APTOS_LAT, APTOS_LON)
      if (T.sunrise !== null && T.sunset !== null && sunStations.length) {
        const mid = (T.sunrise + T.sunset) / 2
        let best = 1e9
        let noonIdx = 0
        TK.sunHours.forEach((h, i) => {
          const dt = Math.abs(h * 60 - mid)
          if (dt < best) {
            best = dt
            noonIdx = i
          }
        })
        const np = sunStations[noonIdx]
        if (np) {
          tickNoonRef.current?.setAttribute('x', np.x.toFixed(1))
          tickNoonRef.current?.setAttribute('y', (np.y - 10).toFixed(1))
        }
      }
    }

    const nowSeg = (
      el: SVGPathElement | null,
      stations: Station[],
      hours: number[],
      minutes: number,
    ) => {
      if (!el) return
      let idx = -1
      for (let i = 0; i < hours.length; i++) if (hours[i] * 60 <= minutes) idx = i
      el.setAttribute('d', idx < 0 ? '' : stationSeg(stations[idx], 11))
    }

    /* One astronomy step (1 Hz): positions, phases, grades, clocks.
     * Weather is fixed to Clear in Increment 1 — the study's Clear
     * dimmers (moon 1, wash 1) are the constants here. */
    const update = (now: Date) => {
      const minutes =
        now.getHours() * 60 + now.getMinutes() + now.getSeconds() / 60
      const st = stateAt(minutes, now, APTOS_LAT, APTOS_LON)
      const key = `${now.getFullYear()}-${now.getMonth()}-${now.getDate()}`
      if (key !== clockKey) {
        clockKey = key
        buildClock(now)
      }

      /* sun — the founder's arc, masked by the mountains */
      const sunG = sunGRef.current
      if (sunG) {
        if (st.sun.up && st.sun.pos) {
          sunG.setAttribute('opacity', '1')
          sunG.setAttribute(
            'transform',
            `translate(${st.sun.pos.x.toFixed(1)} ${st.sun.pos.y.toFixed(1)})`,
          )
        } else {
          sunG.setAttribute('opacity', '0')
        }
      }

      /* stars: day paper at full opacity once night has fallen
       * (starF gate, not a fade) */
      const night = st.grades.starF > 0.5
      const vis = new Map(st.stars.map((s) => [s.i, s]))
      starElsRef.current.forEach((el, idx) => {
        if (!el) return
        const rec = vis.get(idx)
        if (rec && night) {
          el.setAttribute('cx', rec.x.toFixed(1))
          el.setAttribute('cy', rec.y.toFixed(1))
          el.setAttribute('r', rec.r.toFixed(2))
          el.setAttribute('opacity', '1')
        } else {
          el.setAttribute('opacity', '0')
        }
      })

      /* moon — lavender face clipped by the live terminator */
      const mg = moonGRef.current
      if (mg) {
        if (st.moon.up) {
          mg.setAttribute('opacity', '1')
          mg.setAttribute(
            'transform',
            `translate(${st.moon.x.toFixed(1)} ${st.moon.y.toFixed(1)})`,
          )
          moonRotRef.current?.setAttribute(
            'transform',
            `rotate(${st.moon.angDeg.toFixed(1)})`,
          )
          const litKey = Math.round(st.moon.illum * 40)
          if (litKey !== lastLitKey) {
            lastLitKey = litKey
            moonLitRef.current?.setAttribute('d', moonPathD(st.moon.illum, 20))
          }
          moonDarkRef.current?.setAttribute(
            'opacity',
            (0.16 * (1 - st.moon.illum * 0.5)).toFixed(3),
          )
        } else {
          mg.setAttribute('opacity', '0')
        }
      }

      /* clock discipline: the sun's clock shows while the sun is up
       * or in twilight; the moon's while she is up at night */
      if (sunClockRef.current)
        sunClockRef.current.style.display = st.sun.elev > -12 ? '' : 'none'
      if (moonClockRef.current)
        moonClockRef.current.style.display =
          st.moon.up && st.sun.elev < 0 ? '' : 'none'
      if (clock) {
        nowSeg(tickSunNowRef.current, sunStations, clock.sunHours, minutes)
        nowSeg(tickMoonNowRef.current, moonStations, clock.moonHours, minutes)
      }

      /* grades + ink wash: the plate alone is graded; the wash is
       * baked strong at the sunrise (right) side and mirrors past
       * the day's midpoint so the blaze follows the setting sun */
      const wEl = washRef.current
      if (wEl) {
        wEl.setAttribute('opacity', (washF(st.sun.elev) * 0.88).toFixed(3))
        const T = st.times
        wEl.setAttribute(
          'transform',
          T.sunrise !== null &&
            T.sunset !== null &&
            minutes > (T.sunrise + T.sunset) / 2
            ? 'translate(400 0) scale(-1 1)'
            : '',
        )
      }
      gradeNightRef.current?.setAttribute('opacity', st.grades.nightOp.toFixed(3))
      gradeTintRef.current?.setAttribute('opacity', st.grades.tintOp.toFixed(3))
    }

    /* The ensō rotations are pure functions of the (fractional)
     * minute — applied every frame so the creep stays smooth. */
    const paintRotations = (now: Date) => {
      const minutes =
        now.getHours() * 60 +
        now.getMinutes() +
        now.getSeconds() / 60 +
        now.getMilliseconds() / 60000
      sunDiscRef.current?.setAttribute(
        'transform',
        `rotate(${ensoAngleDeg(minutes).toFixed(2)})`,
      )
      moonRingRef.current?.setAttribute(
        'transform',
        `rotate(${moonRingAngleDeg(minutes).toFixed(2)})`,
      )
    }

    const loop = () => {
      raf = requestAnimationFrame(loop)
      if (typeof document !== 'undefined' && document.hidden) {
        lastSec = -1
        return
      }
      const now = new Date()
      paintRotations(now)
      if (now.getSeconds() !== lastSec) {
        lastSec = now.getSeconds()
        update(now)
      }
    }
    const t0 = new Date()
    update(t0)
    paintRotations(t0)
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [])

  const youPhoto = userAvatarUrl && !youImgBroken ? userAvatarUrl : null

  return (
    <div className="lsky">
      <style>{`
.lsky{position:relative;width:100%;aspect-ratio:400/660;border-radius:6px;overflow:hidden;background:#e7d9b8}
.lsky svg.lsky-sky{position:absolute;inset:0;width:100%;height:100%;display:block}
.lsky-paint{position:absolute;inset:0;pointer-events:none;transform-origin:0 0}
.lsky-paint img{position:absolute;inset:0;width:100%;height:100%}
.lsky-paint .glowwhite{animation:lsky-glowpulse 1.65s ease-in-out infinite}
@keyframes lsky-glowpulse{0%,100%{opacity:.10}50%{opacity:1}}
.lsky svg.lsky-hit{position:absolute;inset:0;width:100%;height:100%;display:block}
.lsky .lnode{cursor:pointer}
.lsky .lnode text{fill:#f5f0e8;text-anchor:middle;pointer-events:none}
      `}</style>
      <svg
        className="lsky-sky"
        viewBox="0 0 400 660"
        preserveAspectRatio="xMidYMid meet"
        aria-hidden="true"
      >
        <defs>
          <mask
            id="lsky-sky-mask"
            maskUnits="userSpaceOnUse"
            x="0"
            y="0"
            width="400"
            height="660"
          >
            <rect x="0" y="0" width="400" height="660" fill="#000" />
            <path d={SKY_PATH_D} fill="#fff" fillRule="evenodd" />
          </mask>
          <radialGradient id="lsky-sun-glow">
            <stop offset="0%" stopColor="#f4a58c" stopOpacity=".5" />
            <stop offset="55%" stopColor="#ee9a7d" stopOpacity=".16" />
            <stop offset="100%" stopColor="#ee9a7d" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="lsky-moon-glow">
            <stop offset="0%" stopColor="#dcbfff" stopOpacity=".3" />
            <stop offset="100%" stopColor="#dcbfff" stopOpacity="0" />
          </radialGradient>
          {/* Moon phase clip: the sampled lit-boundary path clips the
              static face asset, so the terminator crops the face
              itself. Vector path only — no image inside this clip. */}
          <clipPath id="lsky-moon-clip">
            <path ref={moonLitRef} />
          </clipPath>
          <clipPath id="lsky-frame-clip">
            <rect x="0" y="0" width="400" height="660" />
          </clipPath>
        </defs>
        <g clipPath="url(#lsky-frame-clip)">
          <image href={plateUrl} x={-61.3} y={0} width={522.6} height={783.9} />
          {/* Grades paint the PLATE ONLY: the celestial group sits
              above them, so the multiply/tint stack never crushes
              the sun, moon and stars (settled layer order). */}
          <g mask="url(#lsky-sky-mask)">
            <image
              ref={washRef}
              href={washUrl}
              x={0}
              y={0}
              width={400}
              height={250}
              opacity={0}
            />
          </g>
          <rect
            ref={gradeNightRef}
            x={0}
            y={0}
            width={400}
            height={660}
            fill="#2b3c66"
            opacity={0}
            style={{ mixBlendMode: 'multiply' }}
          />
          <rect
            ref={gradeTintRef}
            x={0}
            y={0}
            width={400}
            height={660}
            fill="#26365e"
            opacity={0}
          />
          <g mask="url(#lsky-sky-mask)">
            <g>
              <g ref={sunClockRef}>
                <path
                  ref={sunTrackRef}
                  fill="none"
                  stroke="#a07c2c"
                  strokeWidth={0.8}
                  strokeLinecap="round"
                  strokeDasharray="0.5 2.5"
                  opacity={0.35}
                />
                <path
                  ref={tickSunRef}
                  fill="none"
                  stroke="#a07c2c"
                  strokeWidth={1.3}
                  strokeLinecap="round"
                  opacity={0.75}
                />
                <path
                  ref={tickSunNowRef}
                  fill="none"
                  stroke="#a07c2c"
                  strokeWidth={1.3}
                  strokeLinecap="round"
                />
                <text
                  ref={tickNoonRef}
                  textAnchor="middle"
                  fontFamily="Georgia, 'Times New Roman', serif"
                  fontSize={11}
                  fill="#a07c2c"
                >
                  XII
                </text>
              </g>
              <g ref={moonClockRef}>
                <path
                  ref={moonTrackRef}
                  fill="none"
                  stroke="#bf92f2"
                  strokeWidth={0.8}
                  strokeLinecap="round"
                  strokeDasharray="0.5 2.5"
                  opacity={0.35}
                />
                <path
                  ref={tickMoonRef}
                  fill="none"
                  stroke="#bf92f2"
                  strokeWidth={1.3}
                  strokeLinecap="round"
                  opacity={0.75}
                />
                <path
                  ref={tickMoonNowRef}
                  fill="none"
                  stroke="#bf92f2"
                  strokeWidth={1.3}
                  strokeLinecap="round"
                />
              </g>
            </g>
            {/* Constellation lines: toggle default OFF — the toggle
                UI and the live path arrive in Increment 3. */}
            <path d="" fill="none" stroke="#e9b77a" strokeWidth={0.55} opacity={0} />
            <g>
              {STARS.map((s, i) => (
                <circle
                  key={i}
                  ref={(el) => {
                    starElsRef.current[i] = el
                  }}
                  fill={starFill(s[2])}
                  opacity={0}
                />
              ))}
            </g>
            <g ref={moonGRef} opacity={0}>
              <g transform="scale(1.5)">
                <circle r={42} fill="url(#lsky-moon-glow)" />
                <g ref={moonRotRef}>
                  <path ref={moonDarkRef} d={MOON_DARK_D} fill="#2e1b47" />
                  <image
                    href={moonFaceUrl}
                    x={-20}
                    y={-20}
                    width={40}
                    height={40}
                    opacity={0.05}
                  />
                  <g clipPath="url(#lsky-moon-clip)">
                    <image href={moonFaceUrl} x={-20} y={-20} width={40} height={40} />
                  </g>
                </g>
                <image
                  ref={moonRingRef}
                  href={ensoMoonUrl}
                  x={-31}
                  y={-31}
                  width={62}
                  height={62}
                />
              </g>
            </g>
            <g ref={sunGRef} opacity={0}>
              <circle r={147} fill="url(#lsky-sun-glow)" />
              <image
                ref={sunDiscRef}
                href={ensoSunUrl}
                x={-63}
                y={-63}
                width={126}
                height={126}
              />
            </g>
          </g>
        </g>
      </svg>
      <div className="lsky-paint" style={{ transform: PAINTSTACK_TRANSFORM }}>
        <img src={canopyBackUrl} alt="" />
        <img src={glowColourUrl} alt="" />
        <img className="glowwhite" src={glowWhiteUrl} alt="" />
        <img src={treePaintedUrl} alt="" />
        <img src={canopyForeUrl} alt="" />
      </div>
      <svg
        className="lsky-hit"
        viewBox="0 0 400 660"
        preserveAspectRatio="xMidYMid meet"
        role="group"
        aria-label="Living tree — tap a medallion"
      >
        <defs>
          <clipPath id="lsky-you-clip">
            <circle r={YOU_NODE.discR} />
          </clipPath>
        </defs>
        {HIT_NODES.map((n) => {
          const badge = n.archetypeId ? badges[n.archetypeId] : undefined
          const isYou = n.id === 'you'
          return (
            <g
              key={n.id}
              className="lnode"
              data-node-id={n.id}
              transform={`translate(${n.x},${n.y})`}
              onClick={() => onTap(n.id)}
              role="button"
              aria-label={n.name}
            >
              <circle r={n.hitR} fill="transparent" />
              {isYou && youPhoto ? (
                <image
                  href={youPhoto}
                  x={-n.discR}
                  y={-n.discR}
                  width={n.discR * 2}
                  height={n.discR * 2}
                  clipPath="url(#lsky-you-clip)"
                  preserveAspectRatio="xMidYMid slice"
                  onError={() => onYouImgError()}
                />
              ) : null}
              {badge?.attentionTitle && (
                <g
                  className="attn"
                  transform={`translate(${n.discR * 0.78}, ${-n.discR * 0.78})`}
                  role="img"
                  aria-label={badge.attentionTitle}
                >
                  <title>{badge.attentionTitle}</title>
                  <circle
                    className="attndot"
                    r={7.5}
                    fill={USER_WEAVE_COLOR}
                    stroke="#0b0a09"
                    strokeWidth={1.5}
                  />
                  <text
                    className="attnt"
                    y={3.8}
                    style={{ fontSize: '10.5px', fontWeight: 800, fill: '#0b0a09' }}
                  >
                    !
                  </text>
                </g>
              )}
              {badge?.inviteLabel && (
                <g
                  className="inv"
                  transform={`translate(${-n.discR * 0.78}, ${-n.discR * 0.78})`}
                  role="img"
                  aria-label={badge.inviteLabel}
                >
                  <title>{badge.inviteLabel}</title>
                  <circle
                    className="invdot"
                    r={7.5}
                    fill="#5aa897"
                    stroke="#0b0a09"
                    strokeWidth={1.5}
                  />
                  <text
                    className="invt"
                    y={3.8}
                    style={{ fontSize: '10.5px', fontWeight: 800, fill: '#0b0a09' }}
                  >
                    {(badge.inviteCount ?? 0) > 9 ? '9+' : String(badge.inviteCount ?? 0)}
                  </text>
                </g>
              )}
            </g>
          )
        })}
      </svg>
    </div>
  )
}
