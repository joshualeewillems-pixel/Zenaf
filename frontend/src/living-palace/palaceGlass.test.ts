/**
 * Palace Scene 2 — the stained glass as tests. The founder's
 * ruling (2026-11-26 16:27 PT): the glass takes the colour of
 * the seat that has been talking about the floor's subject.
 * Pinned here: the colour choice (the dominant seat, ties by
 * seat id, no interaction → natural glass) and the pixel law
 * (the glass key recolours; stone, gold light and shadow never
 * move — the palaceTint discipline, on this scene's key).
 */
import { describe, it, expect } from 'vitest'
import { SEAT_COLORS } from '../council/colors'
import type { SubjectInteraction } from './palaceSceneLogic'
import {
  PLATE_URLS,
  glassColorFor,
  hexToHue,
  isGlassHsl,
  recolourGlassPixels,
  rgbToHsl,
} from './palaceGlass'

function interaction(perSeat: Record<string, number>): SubjectInteraction {
  return {
    entity_type: 'project',
    entity_id: 'p1',
    total: Object.values(perSeat).reduce((s, n) => s + n, 0),
    per_seat: perSeat,
  }
}

describe('palaceGlass — the colour choice', () => {
  it('the dominant seat’s colour wins', () => {
    expect(glassColorFor(interaction({ mentor: 1, champion: 4 }))).toBe(SEAT_COLORS.champion)
    expect(glassColorFor(interaction({ maverick: 7 }))).toBe(SEAT_COLORS.maverick)
  })

  it('ties break by seat id ascending — deterministic', () => {
    // sorted seat ids: champion before mentor; the strictly-
    // greater scan keeps the first seat at the tied count
    expect(glassColorFor(interaction({ mentor: 2, champion: 2 }))).toBe(SEAT_COLORS.champion)
    expect(glassColorFor(interaction({ skeptic: 3, guardian: 3 }))).toBe(SEAT_COLORS.guardian)
  })

  it('no interaction, no counts, or no known seat → natural glass (null)', () => {
    expect(glassColorFor(undefined)).toBeNull()
    expect(glassColorFor(interaction({}))).toBeNull()
    expect(glassColorFor(interaction({ mentor: 0 }))).toBeNull()
    expect(glassColorFor(interaction({ 'not-a-seat': 5 }))).toBeNull()
  })

  it('every room plate has a master to tint', () => {
    expect(Object.keys(PLATE_URLS).sort()).toEqual(['rose', 'spiral', 'tiers'])
    for (const url of Object.values(PLATE_URLS)) expect(url).toContain('palace-room-')
  })
})

describe('palaceGlass — the pixel law', () => {
  const CHAMPION = SEAT_COLORS.champion // #e24e4e, hue ≈ 0

  function pixelAfter(r: number, g: number, b: number, colour = CHAMPION): [number, number, number, number] {
    const px = new Uint8ClampedArray([r, g, b, 255])
    recolourGlassPixels(px, colour)
    return [px[0], px[1], px[2], px[3]]
  }

  it('a glass pixel takes the seat hue at its own lightness, saturation ×0.9', () => {
    // the plates' violet-blue glass family
    const [h0, s0, l0] = rgbToHsl(120, 110, 220)
    expect(isGlassHsl(h0, s0, l0)).toBe(true)
    const [r, g, b, a] = pixelAfter(120, 110, 220)
    const [h, s, l] = rgbToHsl(r, g, b)
    expect(Math.min(h, 360 - h)).toBeLessThan(6) // hue ≈ 0 (champion red)
    expect(s).toBeCloseTo(s0 * 0.9, 1) // (8-bit round-trip tolerance)
    expect(l).toBeCloseTo(l0, 1)
    expect(a).toBe(255)
  })

  it('a pink glass pixel at the key’s edge (hue ~324) also recolours', () => {
    const [h0, s0, l0] = rgbToHsl(220, 120, 180)
    expect(isGlassHsl(h0, s0, l0)).toBe(true)
    const [r, g, b] = pixelAfter(220, 120, 180, SEAT_COLORS.ambassador)
    const [h] = rgbToHsl(r, g, b)
    expect(h).toBeCloseTo(hexToHue(SEAT_COLORS.ambassador), 0)
  })

  it('stone never moves (warm hue, outside the key)', () => {
    expect(pixelAfter(216, 178, 128)).toEqual([216, 178, 128, 255])
    expect(pixelAfter(146, 116, 78)).toEqual([146, 116, 78, 255])
  })

  it('gold light never moves (hue ~45, outside the key)', () => {
    expect(pixelAfter(240, 200, 90)).toEqual([240, 200, 90, 255])
  })

  it('shadow in the glass hue never moves (lightness below the key)', () => {
    const [h, s, l] = rgbToHsl(30, 25, 60)
    expect(h).toBeGreaterThan(190)
    expect(l).toBeLessThan(0.25)
    expect(isGlassHsl(h, s, l)).toBe(false)
    expect(pixelAfter(30, 25, 60)).toEqual([30, 25, 60, 255])
  })

  it('a washed-out blue-grey never moves (saturation below the key)', () => {
    const [h, s, l] = rgbToHsl(170, 175, 190)
    expect(h).toBeGreaterThan(190)
    expect(s).toBeLessThan(0.35)
    expect(isGlassHsl(h, s, l)).toBe(false)
    expect(pixelAfter(170, 175, 190)).toEqual([170, 175, 190, 255])
  })

  it('the key is exactly the brief’s: saturation ≥ 0.35, hue 190–330, lightness ≥ 0.25', () => {
    expect(isGlassHsl(190, 0.35, 0.25)).toBe(true)
    expect(isGlassHsl(330, 0.35, 0.25)).toBe(true)
    expect(isGlassHsl(189.9, 0.5, 0.5)).toBe(false)
    expect(isGlassHsl(330.1, 0.5, 0.5)).toBe(false)
    expect(isGlassHsl(260, 0.349, 0.5)).toBe(false)
    expect(isGlassHsl(260, 0.5, 0.249)).toBe(false)
  })

  it('hexToHue reads the seat colours’ hues', () => {
    expect(hexToHue(SEAT_COLORS.maverick)).toBeCloseTo(278.4, 0) // violet
    expect(hexToHue(SEAT_COLORS.ambassador)).toBeCloseTo(213, 0) // blue
    expect(Math.min(hexToHue(SEAT_COLORS.champion), 360 - hexToHue(SEAT_COLORS.champion))).toBeLessThan(3)
  })
})
