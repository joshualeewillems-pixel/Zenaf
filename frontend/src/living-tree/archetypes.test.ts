import { describe, expect, it } from 'vitest'
import { STOCK_ARCHETYPE_FALLBACK } from './archetypes'

/**
 * The seed fallback must mirror the backend verbatim. Source of truth:
 * local_ai/council/archetypes.py STOCK_ARCHETYPES (prompt_frame +
 * strand_weights, with PLAIN_TO_KEY applied: Compass->self, Logic->number,
 * Voice->word, Heart->people, Eye->image, Ear->sound, Hands->body).
 *
 * This test pins the FRONTEND side of the match only — it cannot read
 * Python. If the backend text changes, update the backend and this file
 * together; a frontend-only edit re-opens the 5-of-7 drift this fallback
 * had before 2026-10-24 (mentor, champion, guardian, maverick,
 * ambassador prompt_frames all differed; conductor and skeptic matched).
 * The Skeptic's weights are uniform here because the backend computes
 * them per-user (strand_weights=None); only its prompt_frame is pinned.
 */
const EXPECTED: Record<string, { prompt_frame: string; strand_weights: Record<string, number> }> = {
  mentor: {
    prompt_frame:
      'The long view, the cultivator. You create the conditions for insight — read the terrain, name what matters, and let the user arrive at their own answer rather than handing it to them. Patient and unhurried; you see seasons, not days.',
    strand_weights: { self: 0.35, number: 0.3, word: 0.15, people: 0.1, image: 0.05, sound: 0.03, body: 0.02 },
  },
  champion: {
    prompt_frame:
      "You pick the hill, and you name the price. You fight for what costs something — cheap fights don't interest you, and you will tell the user when a hill isn't worth dying on. Fierce and direct: when a fight is real, you refuse to let them dither; when it isn't, you refuse to manufacture one.",
    strand_weights: { body: 0.35, self: 0.3, number: 0.15, people: 0.1, word: 0.05, image: 0.03, sound: 0.02 },
  },
  guardian: {
    prompt_frame:
      "You stand watch over what the user needs in order to flourish — time, money, body, people, the future they're building. You ask what must be protected and what protection would cost, because safety that's too tight starves growth. Steady and sheltering; slow to move, impossible to move once moved.",
    strand_weights: { people: 0.35, body: 0.25, self: 0.2, word: 0.1, image: 0.05, number: 0.03, sound: 0.02 },
  },
  maverick: {
    prompt_frame:
      'You hunt locked doors — rules followed out of habit, fear, or social pressure that nobody chose. You ask who the rule serves, and you refuse to confuse established order with necessary order. Independent and restless, allergic to captivity that calls itself normal.',
    strand_weights: { word: 0.3, image: 0.25, number: 0.2, self: 0.15, sound: 0.05, people: 0.03, body: 0.02 },
  },
  ambassador: {
    prompt_frame:
      "You translate between worlds — other people, the user's own warring inner voices, perspectives that can't hear each other. You hold that different views can be legitimately true at once, without forcing them to become one view. Patient, curious about the other side, unwilling to trade truth for agreement.",
    strand_weights: { word: 0.3, image: 0.25, people: 0.2, self: 0.15, number: 0.05, sound: 0.03, body: 0.02 },
  },
  conductor: {
    prompt_frame:
      "Synthesizes after the others speak. You weave the council's voices into something coherent — not a compromise, but the shape underneath the disagreement. Balanced, integrative, oriented toward what actually works.",
    strand_weights: { self: 0.25, number: 0.2, word: 0.15, people: 0.15, image: 0.1, body: 0.1, sound: 0.05 },
  },
  skeptic: {
    prompt_frame:
      "Names what's being avoided. You voice the worry nobody's saying out loud — the risk everyone's stepping around, the flaw in the favored plan, the question that makes the room uncomfortable. Not contrarian for sport: you go where the user isn't looking, because that's where the blind spots live.",
    strand_weights: {
      word: 1 / 7,
      number: 1 / 7,
      image: 1 / 7,
      sound: 1 / 7,
      body: 1 / 7,
      people: 1 / 7,
      self: 1 / 7,
    },
  },
}

describe('STOCK_ARCHETYPE_FALLBACK mirrors backend STOCK_ARCHETYPES', () => {
  it('covers exactly the 7 stock seats, in backend order', () => {
    expect(STOCK_ARCHETYPE_FALLBACK.map((a) => a.id)).toEqual([
      'mentor',
      'champion',
      'guardian',
      'maverick',
      'ambassador',
      'conductor',
      'skeptic',
    ])
  })

  it.each(Object.keys(EXPECTED))('seat %s: prompt_frame matches backend verbatim', (id) => {
    const found = STOCK_ARCHETYPE_FALLBACK.find((a) => a.id === id)!
    expect(found.prompt_frame).toBe(EXPECTED[id].prompt_frame)
  })

  it.each(Object.keys(EXPECTED))('seat %s: strand_weights match backend', (id) => {
    const found = STOCK_ARCHETYPE_FALLBACK.find((a) => a.id === id)!
    expect(found.strand_weights).toEqual(EXPECTED[id].strand_weights)
  })

  it('is honest seed state: every seat at 0 depth with no twigs', () => {
    for (const a of STOCK_ARCHETYPE_FALLBACK) {
      expect(a.depth).toBe(0)
      expect(a.twigs).toEqual([])
    }
  })
})
