/**
 * astro.ts — Living Sky celestial math, ported from the study's
 * `rendering-test-assets/world-sky/astro.js` (the study's single
 * source of truth, shared by its page and its PIL mirror).
 *
 * Solar/lunar positions use Paul Schlyter's low-precision algorithms
 * (sun ~0.01°, moon ~0.1–0.3° with the principal perturbation terms)
 * — painting accuracy, deliberately.
 *
 * PROJECTION (a painting projection, not a planetarium): azimuth
 * maps linearly onto the frame with EAST AT THE RIGHT — the founder's
 * law (sunrise at the right edge, sunset at the left) — and altitude
 * is compressed ~2.75:1 into the painted sky band:
 *   x = 200 − (az − 180) × (400/150)      az 105..255 → x 400..0
 *   y = 300 − alt × 3.267                 alt 0 → 300, alt 90 → 6
 * The SUN does not use alt-az for its drawn path: the founder's arc
 * law (right to left, peaking at noon, endpoints = real sunrise /
 * sunset for the date) governs the disc; its would-be altitude
 * drives the grades.
 *
 * Study-isms changed at the module's edges (port plan §7.1):
 * - the study's fixed DATE (27 Nov 2026) → the viewer's real local
 *   date, passed in as a `Date` (phases advance day to day for free);
 * - the study's fixed TZ (−8) → the viewer's own offset from `Date`
 *   (`-getTimezoneOffset() / 60`, DST-correct by construction);
 * - LAT/LON → parameters with the Aptos default (founder decision
 *   D1's recommended default; the privacy-respecting location
 *   decision is deferred to Increment 2's gate).
 * `bodyTimes` / `tickMarks` results are cached per (date, lat, lon,
 * tz) — the study cached them for its one fixed date.
 */
import { LINES, STARS } from './skyData'

export const APTOS_LAT = 37.0
export const APTOS_LON = -121.9

const MAG_CUT = 3.5

function D2R(d: number): number {
  return (d * Math.PI) / 180
}
function R2D(r: number): number {
  return (r * 180) / Math.PI
}
function rev(x: number): number {
  return x - Math.floor(x / 360) * 360
}
function sinD(d: number): number {
  return Math.sin(D2R(d))
}
function cosD(d: number): number {
  return Math.cos(D2R(d))
}
function smooth(a: number, b: number, x: number): number {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)))
  return t * t * (3 - 2 * t)
}
function lerpC(c1: readonly number[], c2: readonly number[], t: number): number[] {
  return [0, 1, 2].map((i) => Math.round(c1[i] + (c2[i] - c1[i]) * t))
}

/** Local calendar identity + the viewer's UTC offset (hours) for a Date. */
function dayContext(date: Date): { y: number; m: number; d: number; tz: number } {
  return {
    y: date.getFullYear(),
    m: date.getMonth() + 1,
    d: date.getDate(),
    tz: -date.getTimezoneOffset() / 60,
  }
}

/* Schlyter day number for a local-time moment on the given date. */
function dayNum(date: Date, minutesLocal: number): number {
  const { y, m, d, tz } = dayContext(date)
  const utcMin = minutesLocal - tz * 60
  const ms = Date.UTC(y, m - 1, d) + utcMin * 60000
  return ms / 86400000 - 10956.0
}
function utHours(date: Date, minutesLocal: number): number {
  const { tz } = dayContext(date)
  const h = (minutesLocal - tz * 60) / 60
  return ((h % 24) + 24) % 24
}

interface RaDec {
  ra: number
  dec: number
}

/* Sun RA/Dec (degrees; RA in hours) — Schlyter. */
function sunRaDec(d: number): RaDec & { lon: number; M: number; dist: number } {
  const w = 282.9404 + 4.70935e-5 * d
  const e = 0.016709 - 1.151e-9 * d
  const M = 356.047 + 0.9856002585 * d
  const E = M + e * (180 / Math.PI) * sinD(M) * (1 + e * cosD(M))
  const xv = cosD(E) - e
  const yv = Math.sqrt(1 - e * e) * sinD(E)
  const v = R2D(Math.atan2(yv, xv))
  const r = Math.sqrt(xv * xv + yv * yv)
  const lon = rev(v + w)
  const xs = r * cosD(lon)
  const ys = r * sinD(lon)
  const ecl = 23.4393 - 3.563e-7 * d
  const ye = ys * cosD(ecl)
  const ze = ys * sinD(ecl)
  const ra = R2D(Math.atan2(ye, xs)) / 15
  const dec = R2D(Math.atan2(ze, Math.sqrt(xs * xs + ye * ye)))
  return { ra: ((ra % 24) + 24) % 24, dec, lon, M, dist: r }
}

/* Moon RA/Dec + ecliptic lon/lat — Schlyter with principal perturbations. */
function moonRaDec(
  d: number,
  sun: { M: number },
): RaDec & { lon: number; lat: number; dist: number } {
  const N = 125.1228 - 0.0529538083 * d
  const i = 5.1454
  const w = 318.0634 + 0.1643573223 * d
  const a = 60.2666
  const e = 0.0549
  const M = 115.3654 + 13.0649929509 * d
  let E = M + e * (180 / Math.PI) * sinD(M) * (1 + e * cosD(M))
  for (let k = 0; k < 3; k++)
    E = E - (E - e * (180 / Math.PI) * sinD(E) - M) / (1 - e * cosD(E))
  const xv = a * (cosD(E) - e)
  const yv = a * (Math.sqrt(1 - e * e) * sinD(E))
  const v = R2D(Math.atan2(yv, xv))
  const r = Math.sqrt(xv * xv + yv * yv)
  const xh = r * (cosD(N) * cosD(v + w) - sinD(N) * sinD(v + w) * cosD(i))
  const yh = r * (sinD(N) * cosD(v + w) + cosD(N) * sinD(v + w) * cosD(i))
  const zh = r * (sinD(v + w) * sinD(i))
  let lon = rev(R2D(Math.atan2(yh, xh)))
  let lat = R2D(Math.atan2(zh, Math.sqrt(xh * xh + yh * yh)))
  const Ms = sun.M
  const Ls = rev(Ms + 282.9404 + 4.70935e-5 * d)
  const Lm = rev(N + w + M)
  const D = rev(Lm - Ls)
  const F = rev(Lm - N)
  const Mm = M
  lon +=
    -1.274 * sinD(Mm - 2 * D) +
    0.658 * sinD(2 * D) -
    0.186 * sinD(Ms) -
    0.059 * sinD(2 * Mm - 2 * D) -
    0.057 * sinD(Mm - 2 * D + Ms) +
    0.053 * sinD(Mm + 2 * D) +
    0.046 * sinD(2 * D - Ms) +
    0.041 * sinD(Mm - Ms) -
    0.035 * sinD(D) -
    0.031 * sinD(Mm + Ms) -
    0.015 * sinD(2 * F - 2 * D) +
    0.011 * sinD(Mm - 4 * D)
  lat +=
    -0.173 * sinD(F - 2 * D) -
    0.055 * sinD(Mm - F - 2 * D) -
    0.046 * sinD(Mm + F - 2 * D) +
    0.033 * sinD(F + 2 * D) +
    0.017 * sinD(2 * Mm + F)
  const ecl = 23.4393 - 3.563e-7 * d
  const xe = r * cosD(lon) * cosD(lat)
  const ye = r * (sinD(lon) * cosD(lat) * cosD(ecl) - sinD(lat) * sinD(ecl))
  const ze = r * (sinD(lon) * cosD(lat) * sinD(ecl) + sinD(lat) * cosD(ecl))
  const ra = R2D(Math.atan2(ye, xe)) / 15
  const dec = R2D(Math.atan2(ze, Math.sqrt(xe * xe + ye * ye)))
  return { ra: ((ra % 24) + 24) % 24, dec, lon, lat, dist: r }
}

function lstDeg(d: number, date: Date, minutesLocal: number, lon: number): number {
  const sun = sunRaDec(d)
  const gmst0 = rev(rev(sun.M + 282.9404 + 4.70935e-5 * d) + 180)
  return rev(gmst0 + utHours(date, minutesLocal) * 15.0410687 + lon)
}

function altAz(raH: number, dec: number, lst: number, lat: number): { alt: number; az: number } {
  const HA = lst - raH * 15
  const alt = R2D(
    Math.asin(sinD(dec) * sinD(lat) + cosD(dec) * cosD(lat) * cosD(HA)),
  )
  const az =
    R2D(
      Math.atan2(sinD(HA), cosD(HA) * sinD(lat) - Math.tan(D2R(dec)) * cosD(lat)),
    ) + 180
  return { alt, az: rev(az) }
}

function project(alt: number, az: number): { x: number; y: number } {
  return { x: 200 - (az - 180) * (400 / 150), y: 300 - alt * 3.267 }
}

/* Rise/set scan at 2-minute steps over the given local date. */
function crossings(
  bodyFn: (m: number) => number,
  level: number,
): { rise: number | null; set: number | null } {
  let prev: { m: number; a: number } | null = null
  const out: { rise: number | null; set: number | null } = { rise: null, set: null }
  for (let m = 0; m <= 1440; m += 2) {
    const a = bodyFn(m)
    if (prev !== null) {
      if (prev.a < level && a >= level && out.rise === null)
        out.rise = prev.m + ((m - prev.m) * (level - prev.a)) / (a - prev.a)
      if (prev.a >= level && a < level)
        out.set = prev.m + ((m - prev.m) * (level - prev.a)) / (a - prev.a)
    }
    prev = { m, a }
  }
  return out
}

export interface BodyTimes {
  sunrise: number | null
  sunset: number | null
  moonrise: number | null
  moonset: number | null
}

function cacheKey(date: Date, lat: number, lon: number): string {
  const { y, m, d, tz } = dayContext(date)
  return `${y}-${m}-${d}|${lat}|${lon}|${tz}`
}

const bodyTimesCache = new Map<string, BodyTimes>()

/** Rise/set minutes (local) for the sun and moon on the given date. */
export function bodyTimes(
  date: Date,
  lat: number = APTOS_LAT,
  lon: number = APTOS_LON,
): BodyTimes {
  const key = cacheKey(date, lat, lon)
  const hit = bodyTimesCache.get(key)
  if (hit) return hit
  const altOf =
    (body: 'sun' | 'moon') =>
    (m: number): number => {
      const d = dayNum(date, m)
      const sun = sunRaDec(d)
      const lst = lstDeg(d, date, m, lon)
      const rd = body === 'sun' ? sun : moonRaDec(d, sun)
      return altAz(rd.ra, rd.dec, lst, lat).alt
    }
  const sc = crossings(altOf('sun'), -0.583)
  const mc = crossings(altOf('moon'), 0.125)
  const times: BodyTimes = {
    sunrise: sc.rise,
    sunset: sc.set,
    moonrise: mc.rise,
    moonset: mc.set,
  }
  bodyTimesCache.set(key, times)
  return times
}

/* The founder's sun-arc law as a pure function of t in [0,1] across
 * the day: right (sunrise) to left (sunset), peaking at noon. */
export function sunArcPos(t: number): { x: number; y: number } {
  return { x: 384 - t * 368, y: 196 - Math.sin(Math.PI * t) * 118 }
}

export interface TickSeg {
  x1: number
  y1: number
  x2: number
  y2: number
}
export interface TickMarks {
  sun: TickSeg[]
  moon: TickSeg[]
  sunHours: number[]
  moonHours: number[]
}

const tickMarksCache = new Map<string, TickMarks>()

/* Clock ticks: hour marks etched along the sun's arc — one per clock
 * hour from sunrise to sunset, the tick nearest solar noon longest —
 * and a fainter set along the moon's actual projected path for the
 * night hours. Each tick is a segment from the path inward (toward
 * the arc's centre), oriented on the path's tangent normal. Static
 * geometry per date. */
export function tickMarks(
  date: Date,
  lat: number = APTOS_LAT,
  lon: number = APTOS_LON,
): TickMarks {
  const key = cacheKey(date, lat, lon)
  const hit = tickMarksCache.get(key)
  if (hit) return hit
  const T = bodyTimes(date, lat, lon)
  const out: TickMarks = { sun: [], moon: [], sunHours: [], moonHours: [] }
  function seg(
    px: number,
    py: number,
    tx: number,
    ty: number,
    cx: number,
    cy: number,
    len: number,
  ): TickSeg {
    const L = Math.hypot(tx, ty) || 1
    let nx = -ty / L
    let ny = tx / L
    if ((cx - px) * nx + (cy - py) * ny < 0) {
      nx = -nx
      ny = -ny
    }
    return { x1: px, y1: py, x2: px + nx * len, y2: py + ny * len }
  }
  if (T.sunrise !== null && T.sunset !== null) {
    const sunrise = T.sunrise
    const sunset = T.sunset
    const h0 = Math.ceil(sunrise / 60)
    const h1 = Math.floor(sunset / 60)
    const hs: number[] = []
    for (let h = h0; h <= h1; h++) hs.push(h)
    let noonH = hs[0]
    let bestDt = 1e9
    hs.forEach((hh) => {
      const dt = Math.abs((hh * 60 - sunrise) / (sunset - sunrise) - 0.5)
      if (dt < bestDt) {
        bestDt = dt
        noonH = hh
      }
    })
    hs.forEach((hh) => {
      const t = (hh * 60 - sunrise) / (sunset - sunrise)
      const p = sunArcPos(t)
      const pa = sunArcPos(Math.max(0, t - 0.004))
      const pb = sunArcPos(Math.min(1, t + 0.004))
      out.sun.push(seg(p.x, p.y, pb.x - pa.x, pb.y - pa.y, 200, 196, hh === noonH ? 13 : 8))
      out.sunHours.push(hh)
    })
  }
  /* The moon's visible night arc inside the frame on this date:
   * sampled honestly at hour steps — the longest in-frame dark run
   * carries the ticks. */
  {
    const runs: Array<Array<{ m: number; x: number; y: number }>> = []
    let cur: Array<{ m: number; x: number; y: number }> = []
    for (let m2 = 0; m2 <= 1440; m2 += 60) {
      const dd = dayNum(date, m2)
      const sn = sunRaDec(dd)
      const mn = moonRaDec(dd, sn)
      const aa = altAz(mn.ra, mn.dec, lstDeg(dd, date, m2, lon), lat)
      const pr = project(aa.alt, aa.az)
      const dark =
        T.sunrise === null || m2 < T.sunrise - 20 || (T.sunset !== null && m2 > T.sunset + 20)
      if (aa.alt > 2 && pr.x > 6 && pr.x < 394 && dark) cur.push({ m: m2, x: pr.x, y: pr.y })
      else {
        if (cur.length) runs.push(cur)
        cur = []
      }
    }
    if (cur.length) runs.push(cur)
    runs.sort((a, b) => b.length - a.length)
    const run = runs[0] || []
    if (run.length > 1) {
      const cx = (run[0].x + run[run.length - 1].x) / 2
      const cy = (run[0].y + run[run.length - 1].y) / 2
      run.forEach((p, i) => {
        const pa = run[Math.max(0, i - 1)]
        const pb = run[Math.min(run.length - 1, i + 1)]
        out.moon.push(seg(p.x, p.y, pb.x - pa.x, pb.y - pa.y, cx, cy, 6))
        out.moonHours.push(p.m / 60)
      })
    }
  }
  tickMarksCache.set(key, out)
  return out
}

/* Bright-limb direction, exact 3D geometry: the lit hemisphere faces
 * the sun; project the sun's direction onto the moon's tangent plane
 * and express it in the projection's screen basis (right = decreasing
 * azimuth, up = increasing altitude). Returns the SVG rotate angle. */
function enu(alt: number, az: number): [number, number, number] {
  return [cosD(alt) * sinD(az), cosD(alt) * cosD(az), sinD(alt)] // E, N, U
}
function brightLimbDeg(
  moonAA: { alt: number; az: number },
  sunAA: { alt: number; az: number },
): number {
  const m = enu(moonAA.alt, moonAA.az)
  const s = enu(sunAA.alt, sunAA.az)
  const dot = m[0] * s[0] + m[1] * s[1] + m[2] * s[2]
  const b = [s[0] - dot * m[0], s[1] - dot * m[1], s[2] - dot * m[2]]
  const r = [-cosD(moonAA.az), sinD(moonAA.az), 0] // screen right (E,N,U)
  const u = [
    -sinD(moonAA.alt) * sinD(moonAA.az),
    -sinD(moonAA.alt) * cosD(moonAA.az),
    cosD(moonAA.alt),
  ] // screen up
  const br = b[0] * r[0] + b[1] * r[1] + b[2] * r[2]
  const bu = b[0] * u[0] + b[1] * u[1] + b[2] * u[2]
  return R2D(Math.atan2(-bu, br))
}

/* The moon's lit-region boundary in local coords (sun toward +x,
 * r = 1): sampled points, so the page's SVG path and the PIL mirror
 * draw the identical shape. */
export function moonLitPoints(k: number): Array<[number, number]> {
  const pts: Array<[number, number]> = []
  const N = 28
  let i: number
  let th: number
  if (k >= 0.995) {
    for (i = 0; i <= N; i++) {
      th = -Math.PI / 2 + (i / N) * 2 * Math.PI
      pts.push([Math.cos(th), Math.sin(th)])
    }
    return pts
  }
  if (k <= 0.005) return pts
  for (i = 0; i <= N; i++) {
    th = -Math.PI / 2 + (i / N) * Math.PI
    pts.push([Math.cos(th), Math.sin(th)])
  } // lit limb: +x semicircle, top->bottom
  const rx = Math.abs(2 * k - 1)
  const sgn = k > 0.5 ? -1 : 1
  for (i = 1; i <= N; i++) {
    th = Math.PI / 2 - (i / N) * Math.PI
    pts.push([sgn * rx * Math.cos(th), Math.sin(th)])
  } // terminator back up
  return pts
}

export interface SkyStar {
  i: number
  x: number
  y: number
  mag: number
  r: number
}
export interface SkyState {
  minutes: number
  lst: number
  sun: {
    up: boolean
    pos: { x: number; y: number } | null
    elev: number
    core: number[]
    az: number
    alt: number
  }
  moon: {
    up: boolean
    x: number
    y: number
    alt: number
    az: number
    illum: number
    waxing: boolean
    angDeg: number
  }
  stars: SkyStar[]
  lines: Array<Array<[number, number]>>
  grades: {
    nightOp: number
    goldOp: number
    tintOp: number
    nightF: number
    goldF: number
    starF: number
  }
  times: BodyTimes
}

/** Full scene state at a minute of the given local date. */
export function stateAt(
  minutes: number,
  date: Date,
  lat: number = APTOS_LAT,
  lon: number = APTOS_LON,
): SkyState {
  const d = dayNum(date, minutes)
  const sun = sunRaDec(d)
  const moon = moonRaDec(d, sun)
  const lst = lstDeg(d, date, minutes, lon)
  const T = bodyTimes(date, lat, lon)
  const sunAA = altAz(sun.ra, sun.dec, lst, lat)
  const moonAA = altAz(moon.ra, moon.dec, lst, lat)

  /* founder's arc law for the disc; would-be altitude drives grades */
  const sr = T.sunrise
  const ss = T.sunset
  let sunUp = false
  let sunPos: { x: number; y: number } | null = null
  let sunElev: number
  if (sr !== null && ss !== null && minutes >= sr && minutes <= ss) {
    const t = (minutes - sr) / (ss - sr)
    sunPos = sunArcPos(t)
    sunElev = Math.sin(Math.PI * t) * 34.5
    sunUp = true
  } else {
    const nightLen = 1440 - ((ss as number) - (sr as number))
    const into = minutes > (ss as number) ? minutes - (ss as number) : minutes + (1440 - (ss as number))
    sunElev = -Math.sin(Math.PI * (into / nightLen)) * 22
  }
  const warm = sunUp ? Math.max(0, 1 - Math.abs(sunElev) / 16) : 0
  const sunCore = lerpC([255, 220, 163], [255, 138, 44], warm)

  const nightF = smooth(2, 10, -sunElev)
  const goldF = Math.max(0, 1 - Math.abs(sunElev - 1.0) / 7.5) * (sunElev > -5 ? 1 : 0)
  const starF = smooth(0.5, 7, -sunElev)

  const moonScr = project(moonAA.alt, moonAA.az)
  const elong = R2D(
    Math.acos(
      Math.min(
        1,
        Math.max(
          -1,
          sinD(sun.dec) * sinD(moon.dec) +
            cosD(sun.dec) * cosD(moon.dec) * cosD((sun.ra - moon.ra) * 15),
        ),
      ),
    ),
  )
  const illum = (1 - cosD(elong)) / 2 // elong 0 = new (dark), 180 = full (lit)
  const waxing = rev(moon.lon - sun.lon) < 180
  const ang = brightLimbDeg(moonAA, sunAA)

  const stars: SkyStar[] = []
  for (let i = 0; i < STARS.length; i++) {
    const s = STARS[i]
    const aa = altAz(s[0] / 15, s[1], lst, lat)
    if (aa.alt < 0.2) continue
    const p = project(aa.alt, aa.az)
    if (p.x < -6 || p.x > 406) continue
    stars.push({ i, x: p.x, y: p.y, mag: s[2], r: 0.55 + (MAG_CUT - s[2]) * 0.5 })
  }
  const lines: Array<Array<[number, number]>> = []
  for (let i = 0; i < LINES.length; i++) {
    const chain = LINES[i]
    let run: Array<[number, number]> = []
    for (let j = 0; j < chain.length; j++) {
      const aa = altAz(chain[j][0] / 15, chain[j][1], lst, lat)
      if (aa.alt > -2) {
        const p = project(aa.alt, aa.az)
        run.push([p.x, p.y])
      } else {
        if (run.length > 1) lines.push(run)
        run = []
      }
    }
    if (run.length > 1) lines.push(run)
  }

  return {
    minutes,
    lst,
    sun: { up: sunUp, pos: sunPos, elev: sunElev, core: sunCore, az: sunAA.az, alt: sunAA.alt },
    moon: {
      up: moonAA.alt > -1,
      x: moonScr.x,
      y: moonScr.y,
      alt: moonAA.alt,
      az: moonAA.az,
      illum,
      waxing,
      angDeg: ang,
    },
    stars,
    lines,
    grades: {
      nightOp: nightF * 0.82,
      goldOp: goldF * 0.34,
      tintOp: nightF * 0.3,
      nightF,
      goldF,
      starF,
    },
    times: T,
  }
}

/** "HH:MM" for a minute-of-day (the study's fmt). */
export function fmt(min: number | null | undefined): string {
  if (min === null || min === undefined) return '—'
  const m = ((Math.round(min) % 1440) + 1440) % 1440
  const hh = Math.floor(m / 60)
  const mm = m % 60
  return (hh < 10 ? '0' : '') + hh + ':' + (mm < 10 ? '0' : '') + mm
}

/* The ensō turn (founder, 2026-11-16): the sun's ring rotates
 * counter-clockwise CONTINUOUSLY, −6° per minute (a full turn per
 * hour), so the seam is a minute hand passing four landmarks (down
 * :00, right :15, up :30, left :45). The moon's twin ring turns the
 * opposite way, clockwise +6°/min. Pure functions of the minute —
 * transforms on static assets, costing nothing per frame. */
export function ensoAngleDeg(minutes: number): number {
  const deg = (((minutes % 60) + 60) % 60) * 6
  return deg === 0 ? 0 : -deg
}
export function moonRingAngleDeg(minutes: number): number {
  return (((minutes % 60) + 60) % 60) * 6
}

/* Ink-wash dawn/dusk curve (study page JS): goldF's elevation idea,
 * extended — full across elev −3..+2° (the blaze straddles the
 * horizon), cosine fade to nothing at +10 by day and −12 by night. */
export function washF(elev: number): number {
  if (elev >= 10 || elev <= -12) return 0
  if (elev >= -3 && elev <= 2) return 1
  if (elev > 2) return 0.5 + 0.5 * Math.cos((Math.PI * (elev - 2)) / 8)
  return 0.5 + 0.5 * Math.cos((Math.PI * (-3 - elev)) / 9)
}

/* Stars wear the plate's DAY paper at FULL opacity (founder,
 * 2026-11-14): magnitude reads by point size and small value steps
 * within full-strength paper tones — (243,203,148) → (233,183,122)
 * → (218,164,102) across mag −1.5..3.5 — never white, never faded. */
export function starFill(mag: number): string {
  const t = Math.max(0, Math.min(1, (mag + 1.5) / 5))
  const A = [243, 203, 148]
  const B = [233, 183, 122]
  const C = [218, 164, 102]
  let u: number
  let P: number[]
  let Q: number[]
  if (t <= 0.5) {
    u = t / 0.5
    P = A
    Q = B
  } else {
    u = (t - 0.5) / 0.5
    P = B
    Q = C
  }
  return (
    'rgb(' +
    P.map((v, i) => Math.round(v + (Q[i] - v) * u)).join(',') +
    ')'
  )
}
