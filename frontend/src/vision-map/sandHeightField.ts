/**
 * Sand deformation as a clamped height field (not stacked vector strokes).
 *
 * Design note (deliverables):
 * 1) Typed Float32Array is preferred over painting into an offscreen canvas for the *simulation*:
 *    explicit clamp + blend toward a brush target avoids `source-over` additive darkening.
 *    An offscreen canvas is still used only as a cheap blit source for the *visual* pass (ImageData → scale).
 * 2) v1 plan: half-res field, directional stamp per sample, exponential decay = idle fade,
 *    map height → premultiplied RGBA, drawImage upscale to rake layer.
 * 3) Mapping: h≈0 → transparent; h<0 → dark groove alpha ∝ |h|; h>0 → light ridge alpha ∝ h;
 *    optional contour could be |∇h| in a later pass.
 * 4) Zen overlap: skip weak |target| and use min/max by sign so new strokes add furrows/ridges
 *    without lerp-to-flat erasing lines left and right of the path.
 */

const FIELD_SCALE = 0.5
/** Cover outer tines + along-motion envelope (field px) */
const STAMP_RADIUS = 16
/** Convergence per stamp — prevents infinite darkening on overlap */
const STAMP_BLEND = 0.26
/** Ignore brush samples below this |target| so we don’t lerp existing detail toward flat */
const STAMP_TARGET_EPS = 0.01
/** Shorter along track = less “fat” stroke; keeps effect closer to the path */
const SIGMA_ALONG = 2.5

/** Comb perpendicular to motion — spacing in field cells (~2.35 ≈ 4.7 CSS px at 0.5 field scale) */
const COMB_TINES = 7
const COMB_HALF = (COMB_TINES - 1) / 2
const TINE_SPACING = 2.38
/** Narrower tines = less lateral bleed (was reading like a wide eraser) */
const SIGMA_TINE = 0.32
const AMP_TINE = 0.5
/** Between-furrow highlights — keep subtle or they dominate L/R of the path */
const AMP_BETWEEN = 0.045
const SIGMA_BETWEEN = 0.24

export class SandHeightField {
  fw = 0
  fh = 0
  data: Float32Array = new Float32Array(0)

  resize(cssW: number, cssH: number) {
    const nfw = Math.max(2, Math.floor(cssW * FIELD_SCALE))
    const nfh = Math.max(2, Math.floor(cssH * FIELD_SCALE))
    const n = nfw * nfh
    /* Critical: ZenSandCanvas calls resize() on every ResizeObserver tick. Clearing every time
       wiped the field immediately after stamping — rake looked “broken”. Only reset on size change. */
    if (this.fw === nfw && this.fh === nfh && this.data.length === n) {
      return
    }
    const oldFw = this.fw
    const oldFh = this.fh
    const oldData = this.data

    this.fw = nfw
    this.fh = nfh
    const next = new Float32Array(n)
    next.fill(0)

    /* Keep grooves when the map pane resizes (e.g. context panel opens after click — narrower
       canvas). Top-left overlap is the same CSS→field mapping; new margins start flat. */
    if (oldData.length > 0 && oldFw > 0 && oldFh > 0) {
      const copyW = Math.min(oldFw, nfw)
      const copyH = Math.min(oldFh, nfh)
      for (let j = 0; j < copyH; j++) {
        const os = j * oldFw
        const ns = j * nfw
        for (let i = 0; i < copyW; i++) {
          next[ns + i] = oldData[os + i]!
        }
      }
    }

    this.data = next
  }

  clear() {
    this.data.fill(0)
  }

  /** CSS (logical) coords → field cell coords */
  private cssToField(cx: number, cy: number) {
    return { fx: cx * FIELD_SCALE, fy: cy * FIELD_SCALE }
  }

  /**
   * Directional rake stamp: several parallel grooves ⊥ motion (comb), plus light ridges in between.
   * (tux, tuy) unit tangent in CSS space; `across` uses the same length scale as field cells.
   */
  stamp(cxCss: number, cyCss: number, tux: number, tuy: number) {
    const { fx: fcx, fy: fcy } = this.cssToField(cxCss, cyCss)
    const nx = -tuy
    const ny = tux
    const i0 = Math.max(0, Math.floor(fcx - STAMP_RADIUS))
    const i1 = Math.min(this.fw - 1, Math.ceil(fcx + STAMP_RADIUS))
    const j0 = Math.max(0, Math.floor(fcy - STAMP_RADIUS))
    const j1 = Math.min(this.fh - 1, Math.ceil(fcy + STAMP_RADIUS))
    const tineDenom = SIGMA_TINE * SIGMA_TINE
    const betweenDenom = SIGMA_BETWEEN * SIGMA_BETWEEN

    for (let j = j0; j <= j1; j++) {
      const row = j * this.fw
      for (let i = i0; i <= i1; i++) {
        const dx = i + 0.5 - fcx
        const dy = j + 0.5 - fcy
        const along = dx * tux + dy * tuy
        const across = dx * nx + dy * ny
        const envelope = Math.exp(-(along * along) / (SIGMA_ALONG * SIGMA_ALONG))

        let groove = 0
        for (let k = -COMB_HALF; k <= COMB_HALF; k++) {
          const off = k * TINE_SPACING
          const da = across - off
          groove -= AMP_TINE * Math.exp(-(da * da) / tineDenom)
        }

        let between = 0
        for (let k = -COMB_HALF; k < COMB_HALF; k++) {
          const mid = (k + 0.5) * TINE_SPACING
          const da = across - mid
          between += AMP_BETWEEN * Math.exp(-(da * da) / betweenDenom)
        }

        let target = (groove + between) * envelope
        target = Math.max(-1, Math.min(1, target))
        if (Math.abs(target) < STAMP_TARGET_EPS) continue

        const idx = row + i
        const h = this.data[idx]!
        const blended = h + STAMP_BLEND * (target - h)
        /* Carves: only go more negative (deeper). Ridges: only go more positive. Prevents weak
           brush tails from pulling old lines back toward zero. */
        if (target < 0) {
          this.data[idx] = Math.min(h, blended)
        } else {
          this.data[idx] = Math.max(h, blended)
        }
      }
    }
  }

  applyDecay(dtMs: number, fadeMs: number) {
    if (dtMs <= 0 || fadeMs <= 0) return
    const halfLife = fadeMs * 0.55
    const k = Math.exp(-Math.LN2 * (dtMs / halfLife))
    for (let i = 0; i < this.data.length; i++) {
      this.data[i]! *= k
    }
  }

  hasSignificant(eps = 0.0035): boolean {
    for (let i = 0; i < this.data.length; i++) {
      if (Math.abs(this.data[i]!) > eps) return true
    }
    return false
  }

  /** Full-array scan — use sparingly (debug / infrequent logs). */
  getStats(): { min: number; max: number; maxAbs: number } {
    if (this.data.length === 0) return { min: 0, max: 0, maxAbs: 0 }
    let min = this.data[0]!
    let max = min
    for (let i = 1; i < this.data.length; i++) {
      const v = this.data[i]!
      if (v < min) min = v
      if (v > max) max = v
    }
    return { min, max, maxAbs: Math.max(Math.abs(min), Math.abs(max)) }
  }

  /**
   * Debug: blunt heatmap — h=-1 → black, h=0 → mid gray, h=1 → white, opaque everywhere.
   * Values outside [-1,1] clamp for display only.
   */
  blitToImageDataHeatmap(out: ImageData) {
    const d = out.data
    const n = this.data.length
    for (let i = 0; i < n; i++) {
      const v = Math.max(-1, Math.min(1, this.data[i]!))
      const g = Math.round(((v + 1) * 0.5) * 255)
      const o = i * 4
      d[o] = g
      d[o + 1] = g
      d[o + 2] = g
      d[o + 3] = 255
    }
  }

  /** RGBA for rake overlay: transparent where flat */
  blitToImageData(out: ImageData) {
    const d = out.data
    const n = this.data.length
    for (let i = 0; i < n; i++) {
      const v = this.data[i]!
      const o = i * 4
      /* Slightly looser floor + stronger alpha so grooves read on busy grain (was ~invisible). */
      if (Math.abs(v) < 0.0008) {
        d[o] = 0
        d[o + 1] = 0
        d[o + 2] = 0
        d[o + 3] = 0
        continue
      }
      if (v < 0) {
        /* ~1.5× stronger than prior groove alpha; cap below full slab */
        const raw = 0.08 + Math.abs(v) * 0.95
        const a = Math.min(0.93, raw * 1.5)
        d[o] = 30
        d[o + 1] = 34
        d[o + 2] = 42
        d[o + 3] = Math.floor(a * 255)
      } else {
        const a = Math.min(0.34, 0.035 + v * 0.65)
        d[o] = 252
        d[o + 1] = 248
        d[o + 2] = 238
        d[o + 3] = Math.floor(a * 255)
      }
    }
  }

  getFieldSize() {
    return { fw: this.fw, fh: this.fh }
  }
}
