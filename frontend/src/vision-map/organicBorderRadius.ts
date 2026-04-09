/**
 * Shared smooth “river stone” outlines: high % elliptical border-radius with edge sums ≥100%
 * so sides stay curved (not capsule flat spans). Cheaper than clip-path polygon facets or SVG path().
 */

export function hash01(seed: string): number {
  let h = 2166136261
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return ((h >>> 0) % 10000) / 10000
}

const bumpRadiusPair = (x: number, y: number): readonly [number, number] => {
  const s = x + y
  if (s >= 100) return [x, y] as const
  const add = (100 - s) / 2
  return [x + add, y + add] as const
}

/**
 * Horizontal % (of box width) and vertical % (of box height) for each corner — same numbers that drive
 * `border-radius: … / …` on the stone mask (`organicEllipticalBorderRadiusFromSeed`).
 */
export function organicEllipticalBorderRadiusArrays(
  hA: number,
  hB: number,
  hC: number,
  hD: number,
  hE: number,
  hF: number,
): Readonly<{ h: readonly [number, number, number, number]; v: readonly [number, number, number, number] }> {
  const t = (u: number, lo: number, hi: number) => lo + (hi - lo) * u

  let a = t(hA, 46.5, 54.5)
  let b = t(hB, 46.5, 54.5)
  let c = t(hC, 46.5, 54.5)
  let d = t(hD, 46.5, 54.5)
  ;[a, b] = bumpRadiusPair(a, b)
  ;[c, d] = bumpRadiusPair(c, d)

  let e = t(hE, 48, 57)
  let f = t(hF, 48, 57)
  let g = t(hC, 48, 57)
  let h = t(hD, 48, 57)
  ;[e, h] = bumpRadiusPair(e, h)
  ;[f, g] = bumpRadiusPair(f, g)

  return { h: [a, b, c, d], v: [e, f, g, h] }
}

export function organicEllipticalBorderRadiusPct(
  hA: number,
  hB: number,
  hC: number,
  hD: number,
  hE: number,
  hF: number,
): string {
  const fmt = (n: number) => (Math.round(n * 10) / 10).toFixed(1).replace(/\.0$/, '')
  const { h, v } = organicEllipticalBorderRadiusArrays(hA, hB, hC, hD, hE, hF)
  return `${fmt(h[0])}% ${fmt(h[1])}% ${fmt(h[2])}% ${fmt(h[3])}% / ${fmt(v[0])}% ${fmt(v[1])}% ${fmt(v[2])}% ${fmt(v[3])}%`
}

export function organicEllipticalBorderRadiusFromSeed(seed: string): string {
  return organicEllipticalBorderRadiusPct(
    hash01(`${seed}:or1`),
    hash01(`${seed}:or2`),
    hash01(`${seed}:or3`),
    hash01(`${seed}:or4`),
    hash01(`${seed}:or5`),
    hash01(`${seed}:or6`),
  )
}
