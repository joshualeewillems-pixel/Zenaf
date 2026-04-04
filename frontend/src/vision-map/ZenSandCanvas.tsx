import {
  forwardRef,
  memo,
  useCallback,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
} from 'react'

import { SandHeightField } from './sandHeightField'

/** Set true to trace pointer → stamp → blit → RAF (heatmap + console + red dots) */
const DEBUG_SAND_FIELD = false

const DEBUG_LOG_INTERVAL_MS = 280
const DEBUG_MAX_DOTS = 512
const debugLogLast = new Map<string, number>()

function sandDebugLog(tag: string, payload: () => Record<string, unknown>) {
  if (!DEBUG_SAND_FIELD) return
  const now = performance.now()
  const prev = debugLogLast.get(tag) ?? 0
  if (now - prev < DEBUG_LOG_INTERVAL_MS) return
  debugLogLast.set(tag, now)
  console.log(`[sand-debug:${tag}]`, payload())
}

export type ZenSandCanvasHandle = {
  trace: (clientX: number, clientY: number) => void
  /** Clear deformation field immediately */
  clearRakePaths: () => void
}

/** Default idle fade (field decays toward flat after this ms since last stamp) */
const DEFAULT_RAKE_FADE_MS = 16000
const MIN_POINT_DIST = 3
const MIN_POINT_MS = 10
/** Fill gaps between samples */
const INTERP_MAX_DIST = 6

type PathPoint = { x: number; y: number }

function interpolateAlongSegment(
  ax: number,
  ay: number,
  bx: number,
  by: number,
  maxStep: number,
): PathPoint[] {
  const dx = bx - ax
  const dy = by - ay
  const dist = Math.hypot(dx, dy)
  if (dist <= maxStep) return [{ x: bx, y: by }]
  const n = Math.ceil(dist / maxStep)
  const out: PathPoint[] = []
  for (let i = 1; i <= n; i++) {
    const u = i / n
    out.push({ x: ax + dx * u, y: ay + dy * u })
  }
  return out
}

function buildGrainPattern(): CanvasPattern | null {
  const oc = document.createElement('canvas')
  const sz = 128
  oc.width = sz
  oc.height = sz
  const octx = oc.getContext('2d')
  if (!octx) return null
  const img = octx.createImageData(sz, sz)
  for (let i = 0; i < img.data.length; i += 4) {
    const n = Math.random()
    let v = 188 + Math.floor(n * 48)
    if (Math.random() < 0.045) v -= 22 + Math.floor(Math.random() * 28)
    if (Math.random() < 0.028) v += 12 + Math.floor(Math.random() * 18)
    const g = Math.max(160, Math.min(248, v))
    const drift = Math.floor((Math.random() - 0.5) * 10)
    img.data[i] = g + drift
    img.data[i + 1] = g - Math.floor(Math.random() * 5) + drift
    img.data[i + 2] = g - Math.floor(Math.random() * 4) + drift
    img.data[i + 3] = 22 + Math.floor(Math.random() * 58)
  }
  octx.putImageData(img, 0, 0)
  return octx.createPattern(oc, 'repeat')
}

/** Finer speckle tile for extra breakup (scaled when drawn) */
function buildSpecklePattern(): CanvasPattern | null {
  const oc = document.createElement('canvas')
  const sz = 96
  oc.width = sz
  oc.height = sz
  const octx = oc.getContext('2d')
  if (!octx) return null
  const img = octx.createImageData(sz, sz)
  for (let i = 0; i < img.data.length; i += 4) {
    const r = Math.random()
    if (r < 0.72) {
      img.data[i + 3] = 0
      continue
    }
    const dark = r < 0.88
    const v = dark ? 40 + Math.floor(Math.random() * 45) : 200 + Math.floor(Math.random() * 35)
    img.data[i] = v
    img.data[i + 1] = v - Math.floor(Math.random() * 4)
    img.data[i + 2] = v - Math.floor(Math.random() * 3)
    img.data[i + 3] = dark ? 28 + Math.floor(Math.random() * 40) : 18 + Math.floor(Math.random() * 32)
  }
  octx.putImageData(img, 0, 0)
  return octx.createPattern(oc, 'repeat')
}

function buildLowFreqPattern(): CanvasPattern | null {
  const oc = document.createElement('canvas')
  const sz = 64
  oc.width = sz
  oc.height = sz
  const octx = oc.getContext('2d')
  if (!octx) return null
  const img = octx.createImageData(sz, sz)
  for (let py = 0; py < sz; py++) {
    for (let px = 0; px < sz; px++) {
      const i = (py * sz + px) * 4
      const nx = px / sz
      const ny = py / sz
      const w =
        Math.sin(nx * 2.1 + ny * 1.4) * 0.5 +
        Math.sin(nx * 4.7 - ny * 3.2) * 0.28 +
        Math.sin((nx + ny) * 3.1) * 0.22
      const base = 218 + w * 22
      const v = Math.max(175, Math.min(242, base + (Math.random() - 0.5) * 14))
      img.data[i] = v
      img.data[i + 1] = v - 2
      img.data[i + 2] = v - 1
      img.data[i + 3] = 40 + Math.floor(Math.random() * 30)
    }
  }
  octx.putImageData(img, 0, 0)
  return octx.createPattern(oc, 'repeat')
}

function drawPassiveSand(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  phase: number,
  breathe: number,
) {
  const valleyA = 0.14 + breathe * 0.07
  ctx.save()
  ctx.lineWidth = 1
  ctx.strokeStyle = `rgba(88, 92, 102, ${valleyA})`
  const step = 26
  for (let y = -24; y < h + 48; y += step) {
    ctx.beginPath()
    for (let x = 0; x <= w; x += 5) {
      const wob =
        Math.sin(x * 0.011 + phase * 0.38) * 2.8 +
        Math.sin(y * 0.007 + phase * 0.22 + x * 0.0035) * 1.6
      const yy = y + wob + Math.sin(phase * 0.12 + y * 0.018) * breathe * 2.5
      if (x === 0) ctx.moveTo(x, yy)
      else ctx.lineTo(x, yy)
    }
    ctx.stroke()
  }

  ctx.globalAlpha = 0.04 + breathe * 0.03
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.32)'
  for (let y = -18; y < h + 40; y += step * 1.15) {
    ctx.beginPath()
    for (let x = 0; x <= w; x += 6) {
      const wob =
        Math.sin(x * 0.009 + phase * 0.28 + 0.4) * 2 +
        Math.sin(y * 0.006 + phase * 0.18) * 1.2
      const yy = y + wob + 3
      if (x === 0) ctx.moveTo(x, yy)
      else ctx.lineTo(x, yy)
    }
    ctx.stroke()
  }

  ctx.restore()
}

type Props = {
  reducedMotion?: boolean
  className?: string
  /** When false, pointer does not deform the sand field */
  rakeEnabled?: boolean
  /** Fade deformation after this many ms since last sample (e.g. 12_000–20_000) */
  rakeFadeAfterMs?: number
}

const ZenSandCanvasInner = forwardRef<ZenSandCanvasHandle, Props>(function ZenSandCanvas(
  { reducedMotion = false, className = '', rakeEnabled = true, rakeFadeAfterMs },
  ref,
) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const bedCanvasRef = useRef<HTMLCanvasElement>(null)
  const rakeCanvasRef = useRef<HTMLCanvasElement>(null)
  const grainPatternRef = useRef<CanvasPattern | null>(null)
  const specklePatternRef = useRef<CanvasPattern | null>(null)
  const lowFreqPatternRef = useRef<CanvasPattern | null>(null)
  const sandFieldRef = useRef<SandHeightField | null>(null)
  const fieldScratchRef = useRef<HTMLCanvasElement | null>(null)
  const fieldImageDataRef = useRef<ImageData | null>(null)
  const lastRef = useRef<{ x: number; y: number; t: number } | null>(null)
  const lastAddTimeRef = useRef<number | null>(null)
  const lastStampMsRef = useRef(0)
  const lastDecayTimeRef = useRef<number | null>(null)
  const rafRef = useRef<number>(0)
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const phaseRef = useRef(0)
  /** Skip redundant pattern rebuilds when CSS size + DPR unchanged (ResizeObserver can fire often). */
  const lastResizeLogicalRef = useRef<{ w: number; h: number; dpr: number } | null>(null)
  const rakeEnabledRef = useRef(rakeEnabled)
  const fadeAfterMsRef = useRef(rakeFadeAfterMs ?? DEFAULT_RAKE_FADE_MS)
  const debugDotsRef = useRef<{ x: number; y: number }[]>([])
  const debugRafTickRef = useRef(0)
  const debugCompositionLoggedRef = useRef(false)

  const ensureSandField = useCallback(() => {
    if (!sandFieldRef.current) sandFieldRef.current = new SandHeightField()
    return sandFieldRef.current
  }, [])

  rakeEnabledRef.current = rakeEnabled
  fadeAfterMsRef.current = rakeFadeAfterMs ?? DEFAULT_RAKE_FADE_MS

  const resize = useCallback(() => {
    const wrap = wrapRef.current
    const bed = bedCanvasRef.current
    const rake = rakeCanvasRef.current
    if (!wrap || !bed || !rake) return
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const { width, height } = wrap.getBoundingClientRect()
    const w = Math.max(1, Math.floor(width))
    const h = Math.max(1, Math.floor(height))
    const prevLogical = lastResizeLogicalRef.current
    if (prevLogical && prevLogical.w === w && prevLogical.h === h && prevLogical.dpr === dpr) {
      return
    }
    lastResizeLogicalRef.current = { w, h, dpr }
    grainPatternRef.current = buildGrainPattern()
    specklePatternRef.current = buildSpecklePattern()
    lowFreqPatternRef.current = buildLowFreqPattern()
    ensureSandField().resize(w, h)
    fieldImageDataRef.current = null
    lastDecayTimeRef.current = null
    if (DEBUG_SAND_FIELD) {
      debugDotsRef.current = []
      const field = sandFieldRef.current
      if (!debugCompositionLoggedRef.current) {
        debugCompositionLoggedRef.current = true
        console.log('[sand-debug:composition]', {
          cssLogicalCss: { w, h },
          dpr,
          bedBackingPx: { w: Math.floor(w * dpr), h: Math.floor(h * dpr) },
          fieldCells: field ? { fw: field.fw, fh: field.fh } : null,
          rakeCanvasOnTop: true,
          note: 'Check parent .map-sand-layer z-index; rake has z-index:1 over bed',
        })
      } else {
        sandDebugLog('resize', () => ({
          cssLogicalCss: { w, h },
          dpr,
          fieldCells: field ? { fw: field.fw, fh: field.fh } : null,
        }))
      }
    }
    const bw = Math.floor(w * dpr)
    const bh = Math.floor(h * dpr)
    for (const c of [bed, rake]) {
      c.width = bw
      c.height = bh
      c.style.width = `${w}px`
      c.style.height = `${h}px`
      const ctx = c.getContext('2d')
      if (ctx) ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
  }, [ensureSandField])

  const drawBed = useCallback(
    (now: number) => {
      const canvas = bedCanvasRef.current
      if (!canvas) return
      const ctx = canvas.getContext('2d')
      if (!ctx) return
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      const w = canvas.width / dpr
      const h = canvas.height / dpr

      ctx.setTransform(1, 0, 0, 1, 0, 0)
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

      const base = ctx.createLinearGradient(0, 0, w * 0.92, h * 1.1)
      base.addColorStop(0, '#cfcbc3')
      base.addColorStop(0.22, '#c8c4bb')
      base.addColorStop(0.5, '#c0bbb2')
      base.addColorStop(0.76, '#b8b3aa')
      base.addColorStop(1, '#b0aaa1')
      ctx.fillStyle = base
      ctx.fillRect(0, 0, w, h)

      const low = lowFreqPatternRef.current
      if (low) {
        ctx.save()
        ctx.globalAlpha = 0.28
        ctx.fillStyle = low
        const sc = 3.15
        ctx.scale(sc, sc)
        ctx.fillRect(0, 0, w / sc + 2, h / sc + 2)
        ctx.restore()
      }

      const pat = grainPatternRef.current
      if (pat) {
        ctx.save()
        ctx.globalAlpha = 0.82
        ctx.fillStyle = pat
        ctx.fillRect(0, 0, w, h)
        ctx.restore()
      }

      const speck = specklePatternRef.current
      if (speck) {
        ctx.save()
        ctx.globalAlpha = 0.16
        ctx.fillStyle = speck
        const sc2 = 2.2
        ctx.scale(sc2, sc2)
        ctx.fillRect(0, 0, w / sc2 + 2, h / sc2 + 2)
        ctx.restore()
      }

      if (!reducedMotion) {
        phaseRef.current += 0.011
        const breathe = Math.sin(now * 0.00028) * 0.5 + 0.5
        drawPassiveSand(ctx, w, h, phaseRef.current, breathe)
      } else {
        ctx.save()
        ctx.globalAlpha = 0.12
        ctx.strokeStyle = 'rgba(100, 105, 118, 0.4)'
        ctx.lineWidth = 1
        const step = 32
        for (let y = 0; y < h; y += step) {
          ctx.beginPath()
          ctx.moveTo(0, y)
          ctx.lineTo(w, y)
          ctx.stroke()
        }
        ctx.restore()
      }
    },
    [reducedMotion],
  )

  const drawRake = useCallback((now: number): boolean => {
    const canvas = rakeCanvasRef.current
    if (!canvas) return false
    const ctx = canvas.getContext('2d')
    if (!ctx) return false
    const field = sandFieldRef.current
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const w = canvas.width / dpr
    const h = canvas.height / dpr

    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

    const fadeMs = fadeAfterMsRef.current
    if (field && field.fw > 0 && field.fh > 0) {
      const prevT = lastDecayTimeRef.current
      lastDecayTimeRef.current = now
      if (prevT !== null) {
        field.applyDecay(now - prevT, fadeMs)
      }

      let scratch = fieldScratchRef.current
      if (!scratch) {
        scratch = document.createElement('canvas')
        fieldScratchRef.current = scratch
      }
      const { fw, fh } = field.getFieldSize()
      if (scratch.width !== fw || scratch.height !== fh) {
        scratch.width = fw
        scratch.height = fh
        fieldImageDataRef.current = null
      }
      const fctx = scratch.getContext('2d')
      if (fctx) {
        let img = fieldImageDataRef.current
        if (!img || img.width !== fw || img.height !== fh) {
          img = fctx.createImageData(fw, fh)
          fieldImageDataRef.current = img
        }
        if (DEBUG_SAND_FIELD) {
          field.blitToImageDataHeatmap(img)
        } else {
          field.blitToImageData(img)
        }
        fctx.putImageData(img, 0, 0)
        ctx.save()
        ctx.imageSmoothingEnabled = true
        ctx.drawImage(scratch, 0, 0, fw, fh, 0, 0, w, h)
        ctx.restore()

        if (DEBUG_SAND_FIELD) {
          ctx.save()
          ctx.fillStyle = 'rgba(255, 0, 0, 0.95)'
          for (const p of debugDotsRef.current) {
            ctx.beginPath()
            ctx.arc(p.x, p.y, 3.5, 0, Math.PI * 2)
            ctx.fill()
          }
          ctx.restore()
        }
      }
    }

    const keepAnimating =
      (field?.hasSignificant() ?? false) || now - lastStampMsRef.current < fadeMs

    if (DEBUG_SAND_FIELD) {
      debugRafTickRef.current += 1
      sandDebugLog('raf', () => {
        const f = sandFieldRef.current
        const stats = f && f.data.length > 0 ? f.getStats() : null
        return {
          rafTick: debugRafTickRef.current,
          keepAnimating,
          fadeMs,
          msSinceStamp: Math.round(now - lastStampMsRef.current),
          fieldSize: f ? { fw: f.fw, fh: f.fh } : null,
          statsAfterDecayAndBlit: stats,
          hasSignificantEps: f?.hasSignificant() ?? null,
        }
      })
    }

    return keepAnimating
  }, [])

  const draw = useCallback(
    (now: number): boolean => {
      drawBed(now)
      return drawRake(now)
    },
    [drawBed, drawRake],
  )

  const tick = useCallback(
    (now: number) => {
      const hasTrails = draw(now)
      if (DEBUG_SAND_FIELD) {
        sandDebugLog('pump-branch', () => ({
          hasTrails,
          reducedMotion,
          next: reducedMotion ? 'timeout→raf' : hasTrails ? 'raf-continuous' : 'timeout→raf',
        }))
      }
      if (reducedMotion) {
        timeoutRef.current = setTimeout(() => {
          timeoutRef.current = null
          rafRef.current = requestAnimationFrame(tick)
        }, 1000)
        return
      }
      if (hasTrails) {
        rafRef.current = requestAnimationFrame(tick)
      } else {
        timeoutRef.current = setTimeout(() => {
          timeoutRef.current = null
          rafRef.current = requestAnimationFrame(tick)
        }, 320)
      }
    },
    [draw, reducedMotion],
  )

  const pump = useCallback(() => {
    if (timeoutRef.current !== null) {
      clearTimeout(timeoutRef.current)
      timeoutRef.current = null
    }
    cancelAnimationFrame(rafRef.current)
    rafRef.current = requestAnimationFrame(tick)
  }, [tick])

  useEffect(() => {
    if (!DEBUG_SAND_FIELD) return
    console.log(
      '[sand-debug:checklist] Red dots ≠ stamp: they only mean the sample was accepted. Confirm deformation with [field-after-stamp] maxAbs>0. (1) sample + dots (2) field-after-stamp (3) raf keepAnimating (4) gray heatmap (5) pump-branch',
    )
  }, [])

  useLayoutEffect(() => {
    const id = requestAnimationFrame(() => {
      resize()
      requestAnimationFrame(() => resize())
    })
    return () => cancelAnimationFrame(id)
  }, [resize])

  useEffect(() => {
    resize()
    rafRef.current = requestAnimationFrame(tick)
    return () => {
      cancelAnimationFrame(rafRef.current)
      if (timeoutRef.current) clearTimeout(timeoutRef.current)
    }
  }, [resize, tick])

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver(() => {
      /* Compare sand *field* grid before/after resize — not getBoundingClientRect rounding.
         Subpixel layout + round-vs-floor mismatches were firing false “size changed” every frame,
         clearing stroke state and (when CSS w/h crossed half-res thresholds) wiping the field. */
      const f0 = sandFieldRef.current
      const fw0 = f0?.fw ?? -1
      const fh0 = f0?.fh ?? -1
      resize()
      const f1 = sandFieldRef.current
      const fw1 = f1?.fw ?? -1
      const fh1 = f1?.fh ?? -1
      if (fw0 !== fw1 || fh0 !== fh1) {
        lastRef.current = null
        lastAddTimeRef.current = null
        lastDecayTimeRef.current = null
      }
      pump()
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [resize, pump])

  const addPoint = useCallback(
    (lx: number, ly: number) => {
      if (!rakeEnabledRef.current) return
      const t = performance.now()
      const last = lastRef.current
      if (last) {
        if (t - last.t < MIN_POINT_MS) return
        const dist = Math.hypot(lx - last.x, ly - last.y)
        if (dist < MIN_POINT_DIST) return
      }

      const field = ensureSandField()
      if (DEBUG_SAND_FIELD) {
        const dots = debugDotsRef.current
        dots.push({ x: lx, y: ly })
        if (dots.length > DEBUG_MAX_DOTS) dots.splice(0, dots.length - DEBUG_MAX_DOTS)
        sandDebugLog('sample', () => ({
          lx: Math.round(lx * 10) / 10,
          ly: Math.round(ly * 10) / 10,
          fieldReady: field.fw > 0 && field.fh > 0,
          /** Red dots = sample accepted only; stamping is separate (see field-after-stamp). */
          hasPriorPointForSegment: !!last,
        }))
      }

      let stampsThisEvent = 0
      if (last) {
        const dx = lx - last.x
        const dy = ly - last.y
        const len = Math.hypot(dx, dy) || 1
        const tux = dx / len
        const tuy = dy / len
        const inserted = interpolateAlongSegment(last.x, last.y, lx, ly, INTERP_MAX_DIST)
        for (const q of inserted) {
          field.stamp(q.x, q.y, tux, tuy)
        }
        stampsThisEvent = inserted.length
      } else {
        /* First accepted sample: no segment yet — still deform so field/maxAbs isn’t stuck at 0 */
        field.stamp(lx, ly, 1, 0)
        stampsThisEvent = 1
      }
      lastStampMsRef.current = t

      if (DEBUG_SAND_FIELD) {
        const s = field.getStats()
        sandDebugLog('field-after-stamp', () => ({
          min: Math.round(s.min * 10000) / 10000,
          max: Math.round(s.max * 10000) / 10000,
          maxAbs: Math.round(s.maxAbs * 10000) / 10000,
          stampsThisEvent,
          mode: last ? 'segment' : 'first-contact',
        }))
      }

      lastAddTimeRef.current = t
      lastRef.current = { x: lx, y: ly, t }
      pump()
    },
    [ensureSandField, pump],
  )

  const clearRakePaths = useCallback(() => {
    sandFieldRef.current?.clear()
    if (DEBUG_SAND_FIELD) debugDotsRef.current = []
    lastRef.current = null
    lastAddTimeRef.current = null
    lastDecayTimeRef.current = null
    pump()
  }, [pump])

  useImperativeHandle(
    ref,
    () => ({
      trace(clientX, clientY) {
        if (!rakeEnabledRef.current) return
        const el = wrapRef.current
        if (!el) return
        const r = el.getBoundingClientRect()
        if (clientX < r.left || clientX > r.right || clientY < r.top || clientY > r.bottom) return
        addPoint(clientX - r.left, clientY - r.top)
      },
      clearRakePaths,
    }),
    [addPoint, clearRakePaths],
  )

  useEffect(() => {
    const onPointerMove = (e: PointerEvent) => {
      if (!rakeEnabledRef.current) return
      /* One rake cursor: ignore secondary pointers (multi-touch). No button requirement — trail follows mouse. */
      if (!e.isPrimary) return
      const wrap = wrapRef.current
      if (!wrap) return
      const r = wrap.getBoundingClientRect()
      const { clientX: x, clientY: y } = e
      if (x < r.left || x > r.right || y < r.top || y > r.bottom) return
      addPoint(x - r.left, y - r.top)
    }
    window.addEventListener('pointermove', onPointerMove, true)
    return () => window.removeEventListener('pointermove', onPointerMove, true)
  }, [addPoint])

  return (
    <div ref={wrapRef} className={`map-sand-wrap map-sand-stack ${className}`.trim()} aria-hidden>
      <canvas ref={bedCanvasRef} className="map-sand-bed-canvas" />
      <canvas ref={rakeCanvasRef} className="map-sand-rake-canvas" />
    </div>
  )
})

ZenSandCanvasInner.displayName = 'ZenSandCanvas'

/** Props are primitives + stable className — safe to memo so parent re-renders (e.g. chat draft) do not reconcile the canvas subtree. */
export const ZenSandCanvas = memo(ZenSandCanvasInner)
