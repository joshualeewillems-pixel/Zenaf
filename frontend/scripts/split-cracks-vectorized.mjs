/**
 * Split cracks_vectorized.svg (5 filled paths) into decal-edge-01…05 with tight viewBoxes.
 * Default source: src/vision-map/crackSvgs/source-cracks_vectorized.svg
 * Usage: node scripts/split-cracks-vectorized.mjs [path-to-source.svg]
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const outDir = path.join(__dirname, '..', 'src', 'vision-map', 'crackSvgs')
const defaultSrc = path.join(outDir, 'source-cracks_vectorized.svg')
const src = process.argv[2] || defaultSrc

function bboxFromPathD(d) {
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  const re = /[ML]\s*([\d.-]+)\s*,\s*([\d.-]+)/gi
  let m
  while ((m = re.exec(d)) !== null) {
    const x = parseFloat(m[1])
    const y = parseFloat(m[2])
    minX = Math.min(minX, x)
    minY = Math.min(minY, y)
    maxX = Math.max(maxX, x)
    maxY = Math.max(maxY, y)
  }
  if (!Number.isFinite(minX)) throw new Error('no points in path')
  return { minX, minY, maxX, maxY }
}

function padBox({ minX, minY, maxX, maxY }, p) {
  return {
    minX: minX - p,
    minY: minY - p,
    w: maxX - minX + 2 * p,
    h: maxY - minY + 2 * p,
  }
}

const xml = fs.readFileSync(src, 'utf8')
const paths = [...xml.matchAll(/<path\s+d="([^"]+)"\s+fill="#111111"\s*\/>/g)].map((m) => m[1])

if (paths.length !== 5) {
  console.error('Expected 5 paths, got', paths.length)
  process.exit(1)
}

paths.forEach((d, i) => {
  const raw = bboxFromPathD(d)
  const span = Math.max(raw.maxX - raw.minX, raw.maxY - raw.minY)
  const pad = Math.max(12, Math.round(span * 0.035))
  const { minX, minY, w, h } = padBox(raw, pad)
  const name = `decal-edge-0${i + 1}.svg`
  const out = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${minX} ${minY} ${w} ${h}" fill="none" aria-hidden="true">
  <path d="${d}" fill="currentColor"/>
</svg>
`
  fs.writeFileSync(path.join(outDir, name), out, 'utf8')
  console.log(name, 'viewBox', minX.toFixed(0), minY.toFixed(0), w.toFixed(0), h.toFixed(0))
})
