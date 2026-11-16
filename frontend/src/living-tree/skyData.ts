/**
 * Living Sky — static sky data (port of the study's injected data).
 *
 * Copied verbatim from `rendering-test-assets/world-sky/`:
 * - `sky-data/stars.json` — d3-celestial bright-star catalogue,
 *   mag ≤ 3.5, 288 stars as [raDeg, decDeg, mag] (BSD-3-Clause,
 *   © Olaf Frohn; underlying data: Yale Bright Star Catalogue).
 * - `sky-data/lines.json` — constellation figures as chains of
 *   [raDeg, decDeg] points (same source).
 * - `sky-data/sky-path.json` — the mountain silhouette as a traced
 *   VECTOR path (gen-sky-path.py). Settled law from the founder's
 *   on-device find: no raster image ever sits inside a mask or
 *   clipPath (WKWebView painted a "?" glyph inside the sun when a
 *   mask held a PNG).
 *
 * The sun's clock track is NOT stored data: it is sampled from
 * `sunArcPos` in astro.ts, the same function the study page samples
 * (the study's sun-track.json is a cache of those samples).
 */
import starsJson from './sky-data/stars.json'
import linesJson from './sky-data/lines.json'
import skyPathJson from './sky-data/sky-path.json'

/** [raDeg, decDeg, magnitude] per star. */
export type StarDatum = readonly [number, number, number]

export const STARS: StarDatum[] = starsJson as unknown as StarDatum[]

/** Constellation figures: chains of [raDeg, decDeg] points. */
export const LINES: ReadonlyArray<ReadonlyArray<readonly [number, number]>> =
  linesJson as unknown as ReadonlyArray<ReadonlyArray<readonly [number, number]>>

/** Mountain silhouette path (evenodd fill), 400×660 scene units. */
export const SKY_PATH_D: string = (skyPathJson as { d: string }).d
