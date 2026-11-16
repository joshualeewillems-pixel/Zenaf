/**
 * astro.ts — the Living Sky celestial port (port plan §8, Increment 1).
 * Painting accuracy is the bar: these tests pin the behaviours the
 * scene's life depends on — the sun riding its arc by day, the night
 * gate opening after dark, the ensō seam turning continuously across
 * the hour boundary, and the moon's illumination cycling through a
 * full lunation without ever leaving [0, 1].
 */
import { describe, it, expect } from 'vitest'
import {
  bodyTimes,
  ensoAngleDeg,
  fmt,
  moonRingAngleDeg,
  stateAt,
  tickMarks,
} from './astro'

/** A mid-November day (the study's season). The astronomy is
 *  relative to a (timezone, longitude) pair — production pairs the
 *  viewer's clock with fixed Aptos longitude (the founder's sky);
 *  the tests pair the runtime's own zone with its matching longitude
 *  so "noon" is solar noon in any environment the suite runs in. */
const DAY = new Date(2026, 10, 16)
const LON = (-DAY.getTimezoneOffset() / 60) * 15

describe('the sun arc', () => {
  it('the sun is up at local noon, riding near the arc peak', () => {
    const st = stateAt(720, DAY, 37.0, LON)
    expect(st.sun.up).toBe(true)
    expect(st.sun.pos).not.toBeNull()
    // Arc law: x from 384 (sunrise) to 16 (sunset), peak y = 78 at noon.
    expect(st.sun.pos!.x).toBeGreaterThan(150)
    expect(st.sun.pos!.x).toBeLessThan(250)
    expect(st.sun.pos!.y).toBeLessThan(100)
  })

  it('the sun is down at midnight and the night gate is open', () => {
    const st = stateAt(0, DAY, 37.0, LON)
    expect(st.sun.up).toBe(false)
    expect(st.grades.starF).toBeGreaterThan(0.5)
    expect(st.grades.nightOp).toBeGreaterThan(0.5)
  })

  it('rise/set times are sane and ordered', () => {
    const T = bodyTimes(DAY, 37.0, LON)
    expect(T.sunrise).not.toBeNull()
    expect(T.sunset).not.toBeNull()
    expect(T.sunrise!).toBeGreaterThan(0)
    expect(T.sunrise!).toBeLessThan(T.sunset!)
    expect(T.sunset!).toBeLessThan(1440)
  })
})

describe('the ensō turn', () => {
  it('the seam passes its four landmarks (down, right, up, left)', () => {
    expect(ensoAngleDeg(0)).toBe(0)
    expect(ensoAngleDeg(15)).toBe(-90)
    expect(ensoAngleDeg(30)).toBe(-180)
    expect(ensoAngleDeg(45)).toBe(-270)
  })

  it('the turn is continuous across the hour boundary', () => {
    const before = ensoAngleDeg(59.9999)
    const after = ensoAngleDeg(60)
    // Angular distance on the circle, not raw subtraction: −359.9994°
    // and 0° are the same seam, a hair apart.
    const dist = Math.abs(((before - after + 540) % 360) - 180)
    expect(dist).toBeLessThan(0.01)
  })

  it("the moon's ring turns the opposite way at the same rate", () => {
    for (const m of [0, 7.5, 15, 33.25, 59]) {
      expect(moonRingAngleDeg(m) + ensoAngleDeg(m)).toBe(0)
    }
    expect(moonRingAngleDeg(15)).toBe(90)
  })
})

describe('the moon across a lunation', () => {
  it('illumination stays in [0, 1] and cycles from new to full and back', () => {
    let min = 1
    let max = 0
    const waxingSeen = new Set<boolean>()
    for (let d = 0; d < 30; d++) {
      const date = new Date(2026, 10, 16 + d)
      // Sample twice a day so no phase extremum is stepped over.
      for (const minutes of [0, 720]) {
        const st = stateAt(minutes, date)
        expect(st.moon.illum).toBeGreaterThanOrEqual(0)
        expect(st.moon.illum).toBeLessThanOrEqual(1)
        min = Math.min(min, st.moon.illum)
        max = Math.max(max, st.moon.illum)
        waxingSeen.add(st.moon.waxing)
      }
    }
    expect(min).toBeLessThan(0.1)
    expect(max).toBeGreaterThan(0.9)
    expect(waxingSeen.size).toBe(2)
  })
})

describe('clock ticks', () => {
  it('hour stations line the sun arc, the noon station longest', () => {
    const TK = tickMarks(DAY, 37.0, LON)
    expect(TK.sun.length).toBeGreaterThanOrEqual(8)
    expect(TK.sunHours.length).toBe(TK.sun.length)
    const lengths = TK.sun.map((s) => Math.hypot(s.x2 - s.x1, s.y2 - s.y1))
    expect(Math.max(...lengths)).toBeCloseTo(13, 0)
    expect(Math.min(...lengths)).toBeCloseTo(8, 0)
  })

  it('fmt renders minutes as HH:MM', () => {
    expect(fmt(0)).toBe('00:00')
    expect(fmt(720)).toBe('12:00')
    expect(fmt(null)).toBe('—')
  })
})
