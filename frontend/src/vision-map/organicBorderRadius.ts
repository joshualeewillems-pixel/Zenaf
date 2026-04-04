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

export function organicEllipticalBorderRadiusPct(
  hA: number,
  hB: number,
  hC: number,
  hD: number,
  hE: number,
  hF: number,
): string {
  const t = (u: number, lo: number, hi: number) => lo + (hi - lo) * u
  const fmt = (n: number) => (Math.round(n * 10) / 10).toFixed(1).replace(/\.0$/, '')
  const bumpPair = (x: number, y: number) => {
    const s = x + y
    if (s >= 100) return [x, y] as const
    const add = (100 - s) / 2
    return [x + add, y + add] as const
  }

  let a = t(hA, 46.5, 54.5)
  let b = t(hB, 46.5, 54.5)
  let c = t(hC, 46.5, 54.5)
  let d = t(hD, 46.5, 54.5)
  ;[a, b] = bumpPair(a, b)
  ;[c, d] = bumpPair(c, d)

  let e = t(hE, 48, 57)
  let f = t(hF, 48, 57)
  let g = t(hC, 48, 57)
  let h = t(hD, 48, 57)
  ;[e, h] = bumpPair(e, h)
  ;[f, g] = bumpPair(f, g)

  return `${fmt(a)}% ${fmt(b)}% ${fmt(c)}% ${fmt(d)}% / ${fmt(e)}% ${fmt(f)}% ${fmt(g)}% ${fmt(h)}%`
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
