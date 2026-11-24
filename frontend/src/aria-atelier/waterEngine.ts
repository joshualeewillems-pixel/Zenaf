/**
 * The Well's water — the Resonance Atelier field engine, ported whole.
 *
 * This is the motion study's rendering itself
 * (~/workspace/ts-spaces/aria-s-resonance-atelier-motion-study/index.html):
 * its SEATS table, its three-movement score, its coupling matrices
 * K1/K2/K3, its phase integration and its field/ink computation, with
 * the study's own parameters — grid 352×465, wavenumber scale 1.35,
 * ink settling 0.7/0.3 — lifted, not re-approximated. The only
 * adaptations are where the field lands: it renders to an offscreen
 * canvas and is blitted, composited over the study's own ground
 * rgb(240,229,203) exactly as the study composites it, into circular
 * water canvases, centre-cropping the 1000×1320 field to the square
 * (all seven seat homes sit inside that band, per the study's own
 * framing note).
 *
 * The engine is fail-soft: where a 2d canvas is unavailable (jsdom),
 * `available` is false and every method is a no-op, so the surface
 * renders its structure without the water rather than crashing.
 */

type SeatDef = {
  id: string
  color: string
  alpha: number
  k: number
  omega: number
  u: [number, number]
  home: [number, number]
  rgb: [number, number, number]
  delta: number
}

function hexRGB(hex: string): [number, number, number] {
  return [
    parseInt(hex.slice(1, 3), 16),
    parseInt(hex.slice(3, 5), 16),
    parseInt(hex.slice(5, 7), 16),
  ]
}

type SeatBase = Omit<SeatDef, 'rgb' | 'delta'>
const SEAT_BASE: SeatBase[] = [
  { id: 'valen', color: '#e24e4e', alpha: 1.0, k: 0.016, omega: 0.83, u: [0.83, -0.55], home: [625, 445] },
  { id: 'maeve', color: '#ac7c5b', alpha: 0.85, k: 0.009, omega: 0.42, u: [0.2, 1.0], home: [445, 735] },
  { id: 'aria', color: '#8892c3', alpha: 0.775, k: 0.013, omega: 0.66, u: [1.0, 0.0], home: [500, 590] },
  { id: 'rumi', color: '#92b692', alpha: 0.7, k: 0.011, omega: 0.5, u: [1.0, 0.25], home: [295, 400] },
  { id: 'severine', color: '#a29ac1', alpha: 0.625, k: 0.034, omega: 1.13, u: [0.6, -0.8], home: [715, 715] },
  { id: 'lucian', color: '#5c9cea', alpha: 0.55, k: 0.014, omega: 0.71, u: [0.94, 0.34], home: [460, 500] },
  { id: 'jynx', color: '#a55cce', alpha: 0.4, k: 0.021, omega: 0.97, u: [-0.45, 0.89], home: [528, 520] },
]
const SEATS: SeatDef[] = SEAT_BASE.map((s, i) => ({
  ...s,
  rgb: hexRGB(s.color),
  delta: i * 1.7,
  k: s.k * 1.35 /* tuned wavenumber scale (renderer delta 1) */,
}))

const N = SEATS.length
const JYNX = 6
const VALEN = 0

/* SCORE — three movements over a ≈40s loop. */
const A_TARGETS: Array<Record<string, number>> = [
  /* M1 Agreement */ { valen: 0.8, maeve: 0.75, aria: 0.7, rumi: 0.8, severine: 0.45, lucian: 0.65, jynx: 0.05 },
  /* M2 Unresolved disagreement */ { valen: 1.0, maeve: 0.95, aria: 0.65, rumi: 0.6, severine: 0.8, lucian: 0.25, jynx: 0.12 },
  /* M3 Transformation */ { valen: 0.8, maeve: 0.85, aria: 0.75, rumi: 0.7, severine: 0.6, lucian: 0.6, jynx: 0.55 },
]
const A_MAT = A_TARGETS.map((t) => SEATS.map((s) => t[s.id]))
/* Jynx's wave itself changes in M3: ω 0.97 → 1.57, k 0.021 → 0.017. */
const JYNX_OMEGA = [0.97, 0.97, 1.57]
const JYNX_K = [0.021 * 1.35, 0.021 * 1.35, 0.017 * 1.35]

function blankK(): Float64Array {
  return new Float64Array(N * N)
}
function setPair(K: Float64Array, a: number, b: number, v: number) {
  K[a * N + b] = v
  K[b * N + a] = v
}
function buildK1(): Float64Array {
  const K = blankK()
  const group = [0, 1, 2, 3, 5] /* rumi, valen, maeve, aria, lucian */
  for (let a = 0; a < group.length; a++)
    for (let b = a + 1; b < group.length; b++) setPair(K, group[a], group[b], 0.9)
  for (let j = 0; j < N; j++) if (j !== 4 && j !== JYNX) setPair(K, 4, j, 0.3) /* severine to all */
  return K /* jynx K = 0 */
}
function buildK2(): Float64Array {
  const K = blankK()
  for (let i = 0; i < N; i++)
    for (let j = 0; j < N; j++) if (i !== j && i !== JYNX && j !== JYNX) K[i * N + j] = 0.3
  for (let j = 0; j < N; j++) if (j !== 2 && j !== JYNX) setPair(K, 2, j, 0.4) /* aria to all +0.4 */
  for (let j = 0; j < N; j++) if (j !== 4 && j !== JYNX) setPair(K, 4, j, 0.2) /* severine +0.2 */
  setPair(K, 2, 4, 0.4) /* aria–severine keeps aria's +0.4 */
  setPair(K, VALEN, 3, -0.8) /* valen–rumi anti */
  setPair(K, VALEN, 1, -2.2) /* valen–maeve strong anti-phase */
  return K
}
function buildK3(): Float64Array {
  const K = blankK()
  for (let i = 0; i < N; i++)
    for (let j = 0; j < N; j++) if (i !== j && i !== JYNX && j !== JYNX) K[i * N + j] = 0.6
  for (let j = 0; j < N; j++) if (j !== JYNX) setPair(K, JYNX, j, 0.8) /* jynx ↔ all +0.8 */
  setPair(K, VALEN, 1, -0.6) /* residue of tension persists */
  return K
}
const K_MATS = [buildK1(), buildK2(), buildK3()]

const LOOP = 40
const T_M2 = 12
const T_M3 = 26
const RAMP = 2.5
function raisedCos(x: number): number {
  if (x <= 0) return 0
  if (x >= 1) return 1
  return 0.5 - 0.5 * Math.cos(Math.PI * x)
}
function lerp(a: number, b: number, f: number): number {
  return a + (b - a) * f
}

const MW = 1000
const MH = 1320
const GW = 352
const GH = 465
const P = GW * GH
/** The study's own ground, composited under the ink exactly as the
 *  study's page composites it. */
export const WATER_GROUND = 'rgb(240, 229, 203)'
/** Source y-offset centre-cropping the 352×465 field to its square. */
const CROP_Y = Math.floor((GH - GW) / 2)

type Score = { A: Float64Array; K: Float64Array; omegaJ: number; kJ: number; movement: number }

export class ResonanceField {
  available = false
  private canvas: HTMLCanvasElement | null = null
  private ctx: CanvasRenderingContext2D | null = null
  private img: ImageData | null = null
  private phi = new Float64Array(N)
  private tAbs = 0
  private settleInit = false
  private sinBase = new Float32Array(N * P)
  private cosBase = new Float32Array(N * P)
  private jynxBaseProj = new Float32Array(P)
  private Sarr = new Float32Array(P)
  private sumW = new Float32Array(P)
  private sumWA = new Float32Array(P)
  private rNum = new Float32Array(P)
  private gNum = new Float32Array(P)
  private bNum = new Float32Array(P)
  private prevR = new Float32Array(P)
  private prevG = new Float32Array(P)
  private prevB = new Float32Array(P)
  private prevA = new Float32Array(P)
  private envArr = new Float32Array(P)
  private _A = new Float64Array(N)
  private _K = new Float64Array(N * N)
  private raf = 0
  private lastStamp: number | null = null
  private lastRender = 0

  constructor() {
    try {
      const canvas = document.createElement('canvas')
      canvas.width = GW
      canvas.height = GH
      const ctx = canvas.getContext('2d')
      if (!ctx) return
      this.canvas = canvas
      this.ctx = ctx
      this.img = ctx.createImageData(GW, GH)
      this.precompute()
      this.resetPhases()
      this.available = true
    } catch {
      this.available = false
    }
  }

  private resetPhases() {
    for (let i = 0; i < N; i++) this.phi[i] = i * 2.39
  }

  private precompute() {
    for (let i = 0; i < N; i++) {
      const s = SEATS[i]
      const baseOff = i * P
      for (let gy = 0; gy < GH; gy++) {
        const py = ((gy + 0.5) / GH) * MH
        for (let gx = 0; gx < GW; gx++) {
          const px = ((gx + 0.5) / GW) * MW
          const proj = s.u[0] * (px - s.home[0]) + s.u[1] * (py - s.home[1])
          const idx = gy * GW + gx
          const ang = s.k * proj
          this.sinBase[baseOff + idx] = Math.sin(ang)
          this.cosBase[baseOff + idx] = Math.cos(ang)
          if (i === JYNX) this.jynxBaseProj[idx] = ang /* = k₀ · proj */
        }
      }
    }
  }

  private getScore(tAbs: number): Score {
    const _A = this._A
    const _K = this._K
    const score: Score = { A: _A, K: _K, omegaJ: 0.97, kJ: 0.021, movement: 0 }
    const tLoop = tAbs % LOOP
    const cycle = Math.floor(tAbs / LOOP)
    const m = tLoop < T_M2 ? 0 : tLoop < T_M3 ? 1 : 2
    let prevM = -1
    let currM = m
    let f = 0
    if (tLoop >= T_M2 && tLoop < T_M2 + RAMP) {
      prevM = 0
      currM = 1
      f = raisedCos((tLoop - T_M2) / RAMP)
    } else if (tLoop >= T_M3 && tLoop < T_M3 + RAMP) {
      prevM = 1
      currM = 2
      f = raisedCos((tLoop - T_M3) / RAMP)
    } else if (tLoop < RAMP && cycle > 0) {
      prevM = 2
      currM = 0
      f = raisedCos(tLoop / RAMP)
    }
    if (prevM >= 0) {
      for (let i = 0; i < N; i++) _A[i] = lerp(A_MAT[prevM][i], A_MAT[currM][i], f)
      for (let i = 0; i < N * N; i++) _K[i] = lerp(K_MATS[prevM][i], K_MATS[currM][i], f)
      score.omegaJ = lerp(JYNX_OMEGA[prevM], JYNX_OMEGA[currM], f)
      score.kJ = lerp(JYNX_K[prevM], JYNX_K[currM], f)
    } else {
      for (let i = 0; i < N; i++) _A[i] = A_MAT[m][i]
      _K.set(K_MATS[m])
      score.omegaJ = JYNX_OMEGA[m]
      score.kJ = JYNX_K[m]
    }
    score.movement = m
    /* Valen enters across the opening ~4s: A 0.55 → 0.80. */
    if (tAbs < 4) _A[VALEN] = lerp(0.55, _A[VALEN], raisedCos(tAbs / 4))
    /* Jynx's brief qualification, ~15s inside M2. */
    if (tLoop >= T_M2 && tLoop < T_M3) {
      const d = (tLoop - 15) / 0.9
      _A[JYNX] = Math.min(1, _A[JYNX] + 0.15 * Math.exp(-d * d))
    }
    return score
  }

  private stepPhases(dt: number) {
    const sc = this.getScore(this.tAbs)
    const K = sc.K
    const dphi = new Float64Array(N)
    for (let i = 0; i < N; i++) {
      const w = i === JYNX ? sc.omegaJ : SEATS[i].omega
      let sum = 0
      for (let j = 0; j < N; j++) {
        if (j === i) continue
        const kij = K[i * N + j]
        if (kij !== 0) sum += kij * Math.sin(this.phi[j] - this.phi[i])
      }
      dphi[i] = w + sum
    }
    for (let i = 0; i < N; i++) this.phi[i] += dphi[i] * dt
    this.tAbs += dt
  }

  /** Fast-forward integration so a seek lands on the same state the
   *  study reaches by integrating from t=0. */
  seek(target: number) {
    if (!this.available) return
    this.resetPhases()
    this.tAbs = 0
    const dt = 1 / 30
    while (this.tAbs < target - 1e-9) this.stepPhases(Math.min(dt, target - this.tAbs))
    this.settleInit = false
    this.render()
  }

  render() {
    if (!this.available || !this.ctx || !this.img) return
    const { Sarr, sumW, sumWA, rNum, gNum, bNum, envArr } = this
    const data = this.img.data
    const sc = this.getScore(this.tAbs)
    const A = sc.A
    Sarr.fill(0)
    sumW.fill(0)
    sumWA.fill(0)
    rNum.fill(0)
    gNum.fill(0)
    bNum.fill(0)

    const cosOff = new Float64Array(N)
    const sinOff = new Float64Array(N)
    const centres: Array<[number, number]> = []
    for (let i = 0; i < N; i++) {
      const s = SEATS[i]
      const dx = 46 * Math.sin(0.31 * this.tAbs + s.delta)
      const dy = 38 * Math.sin(0.43 * this.tAbs + 2 * s.delta)
      centres.push([s.home[0] + dx, s.home[1] + dy])
      const kCur = i === JYNX ? sc.kJ : s.k
      const off = -kCur * (s.u[0] * dx + s.u[1] * dy) + this.phi[i]
      cosOff[i] = Math.cos(off)
      sinOff[i] = Math.sin(off)
    }
    const jynxRatio = sc.kJ / SEATS[JYNX].k
    const jynxOff =
      -sc.kJ *
        (SEATS[JYNX].u[0] * (centres[JYNX][0] - SEATS[JYNX].home[0]) +
          SEATS[JYNX].u[1] * (centres[JYNX][1] - SEATS[JYNX].home[1])) +
      this.phi[JYNX]

    const envX = new Float64Array(GW)
    const envY = new Float64Array(GH)
    for (let i = 0; i < N; i++) {
      const st = SEATS[i]
      const Ai = A[i]
      const al = st.alpha
      const ecx = centres[i][0]
      const ecy = centres[i][1]
      for (let gx = 0; gx < GW; gx++) {
        const exd = ((gx + 0.5) / GW) * MW - ecx
        envX[gx] = Math.exp((-exd * exd) / 186050)
      }
      for (let gy = 0; gy < GH; gy++) {
        const eyd = ((gy + 0.5) / GH) * MH - ecy
        envY[gy] = Math.exp((-eyd * eyd) / 186050)
      }
      for (let gy = 0; gy < GH; gy++) {
        const erow = gy * GW
        const eyv = envY[gy]
        for (let gx = 0; gx < GW; gx++) envArr[erow + gx] = eyv * envX[gx]
      }
      const R = st.rgb[0]
      const G = st.rgb[1]
      const B = st.rgb[2]
      const baseOff = i * P
      const cO = cosOff[i]
      const sO = sinOff[i]
      if (i === JYNX) {
        for (let idx = 0; idx < P; idx++) {
          const ang = this.jynxBaseProj[idx] * jynxRatio + jynxOff
          const sn = Math.sin(ang)
          const cs = Math.cos(ang)
          const w = Ai * (0.35 + 0.65 * envArr[idx]) * (0.5 + 0.5 * cs)
          Sarr[idx] += Ai * sn
          sumW[idx] += w
          const wa = w * al
          sumWA[idx] += wa
          rNum[idx] += wa * R
          gNum[idx] += wa * G
          bNum[idx] += wa * B
        }
      } else {
        for (let idx = 0; idx < P; idx++) {
          const sb = this.sinBase[baseOff + idx]
          const cb = this.cosBase[baseOff + idx]
          const sn2 = sb * cO + cb * sO
          const cs2 = cb * cO - sb * sO
          const w2 = Ai * (0.35 + 0.65 * envArr[idx]) * (0.5 + 0.5 * cs2)
          Sarr[idx] += Ai * sn2
          sumW[idx] += w2
          const wa2 = w2 * al
          sumWA[idx] += wa2
          rNum[idx] += wa2 * R
          gNum[idx] += wa2 * G
          bNum[idx] += wa2 * B
        }
      }
    }

    let sumA = 0
    for (let i = 0; i < N; i++) sumA += A[i]
    const vDen = Math.max(sumA, 1e-6)
    const { prevR, prevG, prevB, prevA } = this
    for (let idx = 0; idx < P; idx++) {
      const Sv = Sarr[idx]
      const V = Sv / vDen
      const bnd = 0.5 + 0.5 * Math.sin(V * Math.PI * 6 + Sv * 0.5)
      const b2 = bnd * bnd
      const b4 = b2 * b2
      const u2 = 0.5 + 0.5 * Math.sin(Sv * 1.4)
      const u2sq = u2 * u2
      const u6 = u2sq * u2sq * u2sq
      const u3 = 0.5 + 0.5 * Math.sin(V * Math.PI)
      const inkVal = b4 * 0.85 + u6 * 0.35 + u3 * u3 * 0.15
      const swa = sumWA[idx]
      const sw = sumW[idx]
      let r = 0
      let g = 0
      let bl = 0
      let a = 0
      if (swa > 1e-6 && sw > 1e-6) {
        r = rNum[idx] / swa
        g = gNum[idx] / swa
        bl = bNum[idx] / swa
        const grey = (r + g + bl) / 3
        r = grey + (r - grey) * 1.35
        g = grey + (g - grey) * 1.35
        bl = grey + (bl - grey) * 1.35
        const darkF = b4 * b4 * b2 * 0.3
        r = r * (1 - darkF) + 43 * darkF
        g = g * (1 - darkF) + 29 * darkF
        bl = bl * (1 - darkF) + 18 * darkF
        r = r < 0 ? 0 : r > 255 ? 255 : r
        g = g < 0 ? 0 : g > 255 ? 255 : g
        bl = bl < 0 ? 0 : bl > 255 ? 255 : bl
        const inkC = inkVal * (0.45 + 0.55 * (swa / sw))
        a = (inkC < 0 ? 0 : inkC > 1 ? 1 : inkC) * 255
      }
      const o = idx * 4
      if (!this.settleInit) {
        prevR[idx] = r
        prevG[idx] = g
        prevB[idx] = bl
        prevA[idx] = a
        data[o] = r
        data[o + 1] = g
        data[o + 2] = bl
        data[o + 3] = a
      } else {
        /* Ink settling: 0.7 new / 0.3 previous. */
        const nr = 0.7 * r + 0.3 * prevR[idx]
        const ng = 0.7 * g + 0.3 * prevG[idx]
        const nb = 0.7 * bl + 0.3 * prevB[idx]
        const na = 0.7 * a + 0.3 * prevA[idx]
        prevR[idx] = nr
        prevG[idx] = ng
        prevB[idx] = nb
        prevA[idx] = na
        data[o] = nr
        data[o + 1] = ng
        data[o + 2] = nb
        data[o + 3] = na
      }
    }
    this.settleInit = true
    this.ctx.putImageData(this.img, 0, 0)
  }

  /** Composite the field into a circular water canvas: the study's
   *  ground first, then the field centre-cropped to the square. */
  blitTo(target: HTMLCanvasElement | null) {
    if (!this.available || !this.canvas || !target) return
    const tctx = target.getContext('2d')
    if (!tctx) return
    const w = target.width
    const h = target.height
    tctx.fillStyle = WATER_GROUND
    tctx.fillRect(0, 0, w, h)
    tctx.drawImage(this.canvas, 0, CROP_Y, GW, GW, 0, 0, w, h)
  }

  /** Run the field at ~30fps, blitting into every target each frame. */
  start(getTargets: () => Array<HTMLCanvasElement | null>) {
    if (!this.available || this.raf) return
    this.lastStamp = null
    this.lastRender = 0
    const frame = (stamp: number) => {
      this.raf = requestAnimationFrame(frame)
      if (this.lastStamp === null) {
        this.lastStamp = stamp
        this.lastRender = stamp
        return
      }
      const elapsed = (stamp - this.lastRender) / 1000
      if (elapsed < 1 / 30) return
      const dt = Math.min(0.1, (stamp - this.lastStamp) / 1000)
      this.lastStamp = stamp
      this.lastRender = stamp
      const n = Math.max(1, Math.ceil(dt / (1 / 30)))
      const sub = dt / n
      for (let s = 0; s < n; s++) this.stepPhases(sub)
      this.render()
      for (const t of getTargets()) this.blitTo(t)
    }
    this.raf = requestAnimationFrame(frame)
  }

  stop() {
    if (this.raf) cancelAnimationFrame(this.raf)
    this.raf = 0
  }
}
