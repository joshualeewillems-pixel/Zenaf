// @vitest-environment jsdom
/**
 * The ResonanceField's dynamism seam — the pulse envelope and the
 * phase read (Atelier dynamism spec §2.2/§4, founder-reviewed
 * 2026-11-25).
 *
 * In jsdom the field is unavailable (no 2d canvas — the engine is
 * fail-soft by design), so these tests exercise the envelope's
 * STATE and the score arithmetic directly: the pure envelope
 * function's gate math, pulse bookkeeping (one envelope per seat,
 * re-pulse restarts, contracted strengths), decay integrated by
 * the field's own frame step, the multiplier landing in the score
 * without overwriting it, and the reduced-motion no-op. On-device
 * perception of the perturbation is the founder's gate, not this
 * suite's.
 */
import { describe, it, expect } from 'vitest'
import {
  ResonanceField,
  PULSE_PEAK,
  PULSE_TAU_SECONDS,
  pulseEnvelope,
} from './waterEngine'

type FieldInternals = {
  stepPhases: (dt: number) => void
  getScore: (t: number) => { A: Float64Array }
}
const internals = (f: ResonanceField) => f as unknown as FieldInternals

/* SEATS order in the engine: valen 0, maeve 1, aria 2, rumi 3,
 * severine 4, lucian 5, jynx 6. */
const ARIA = 2

describe('the pulse envelope — gate mathematics', () => {
  it('uses the corrected time constant the founder’s review required', () => {
    expect(PULSE_TAU_SECONDS).toBe(0.5)
    expect(PULSE_PEAK).toBe(0.3)
  })

  it('starts at 1 and decays exponentially', () => {
    expect(pulseEnvelope(0)).toBe(1)
    expect(pulseEnvelope(-1)).toBe(1)
    expect(pulseEnvelope(0.5)).toBeCloseTo(Math.exp(-1), 10)
    expect(pulseEnvelope(1)).toBeCloseTo(Math.exp(-2), 10)
  })

  it('leaves under 1% residue by 2.5s — the spec gate, consistent with τ', () => {
    // e^(−2.5/0.5) = e^−5 ≈ 0.67%. (Rev 1's τ ≈ 1.2s would leave
    // ≈12.5% here; this assertion is the corrected contract.)
    expect(pulseEnvelope(2.5)).toBeLessThan(0.01)
    expect(pulseEnvelope(2.5)).toBeCloseTo(Math.exp(-5), 10)
  })
})

describe('ResonanceField pulse bookkeeping', () => {
  it('a pulse starts the seat’s envelope at full contracted strength', () => {
    const f = new ResonanceField()
    f.pulse('aria')
    expect(f.pulseOf('aria')).toEqual({ envelope: 1, peak: PULSE_PEAK })
    expect(f.pulseOf('valen')).toEqual({ envelope: 0, peak: 0 })
  })

  it('the rendering-milestone strength is half', () => {
    const f = new ResonanceField()
    f.pulse('lucian', 0.5)
    expect(f.pulseOf('lucian')).toEqual({ envelope: 1, peak: PULSE_PEAK * 0.5 })
  })

  it('envelopes are per-seat and a re-pulse restarts rather than stacks', () => {
    const f = new ResonanceField()
    f.pulse('aria')
    f.pulse('valen')
    internals(f).stepPhases(0.5)
    expect(f.pulseOf('aria')?.envelope).toBeCloseTo(Math.exp(-1), 10)
    expect(f.pulseOf('valen')?.envelope).toBeCloseTo(Math.exp(-1), 10)
    f.pulse('aria')
    expect(f.pulseOf('aria')?.envelope).toBe(1)
    expect(f.pulseOf('aria')?.peak).toBe(PULSE_PEAK)
    expect(f.pulseOf('valen')?.envelope).toBeCloseTo(Math.exp(-1), 10)
  })

  it('the envelope decays inside the frame step and dies outright', () => {
    const f = new ResonanceField()
    f.pulse('jynx')
    internals(f).stepPhases(2.5)
    expect(f.pulseOf('jynx')?.envelope).toBeLessThan(0.01)
    internals(f).stepPhases(1.5)
    expect(f.pulseOf('jynx')).toEqual({ envelope: 0, peak: 0 })
  })

  it('the multiplier lands in the score and never overwrites it', () => {
    const base = new ResonanceField()
    const pulsed = new ResonanceField()
    const baseA = internals(base).getScore(0).A[ARIA]
    pulsed.pulse('aria')
    const pulsedA = internals(pulsed).getScore(0).A[ARIA]
    expect(pulsedA).toBeCloseTo(baseA * (1 + PULSE_PEAK), 10)
    // Once the envelope dies, the score is the score again.
    internals(pulsed).stepPhases(4)
    expect(internals(pulsed).getScore(0).A[ARIA]).toBeCloseTo(baseA, 10)
  })

  it('under reduced motion the pulse is a no-op', () => {
    const f = new ResonanceField()
    f.reducedMotion = true
    f.pulse('aria')
    f.pulse('aria', 0.5)
    expect(f.pulseOf('aria')).toEqual({ envelope: 0, peak: 0 })
  })

  it('unknown voices are refused quietly', () => {
    const f = new ResonanceField()
    expect(() => f.pulse('nobody')).not.toThrow()
    expect(f.pulseOf('nobody')).toBeNull()
    expect(f.phaseOf('nobody')).toBe(0)
  })

  it('phaseOf reads zero on an unavailable field (the §4 degradation)', () => {
    const f = new ResonanceField()
    expect(f.available).toBe(false)
    for (const v of ['rumi', 'valen', 'maeve', 'lucian', 'aria', 'severine', 'jynx']) {
      expect(f.phaseOf(v)).toBe(0)
    }
  })
})
