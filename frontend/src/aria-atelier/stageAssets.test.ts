/**
 * The stage ladders — the generation record, pinned.
 *
 * The ladders were generated from the canonical geometry by
 * stagegen/generate_stages.py, which verified them pixel-by-pixel
 * in PIL (full decode): every ladder's final density is
 * sha256-identical to the canonical geometry-pure array; every
 * density ladder is an elementwise prefix chain; the rendered
 * alpha ladders decrease NOWHERE (stage k's ink is a pixelwise
 * subset of stage k+1's). Those results live in
 * stage-manifest.json; this suite pins the record so a silent
 * regeneration drift fails loudly, and pins the files themselves
 * (PNG signature, IHDR dimensions, byte size == the record).
 *
 * A naturalWidth check is NOT possible in this repo's jsdom:
 * without the node `canvas` package jsdom cannot decode images
 * at all (verified 2026-11-25 — a file:// load never completes,
 * naturalWidth stays 0). The decode verification is the
 * generation record above; on-device painting is the founder's.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { STAGE_IMAGES } from './stageImages'
import { STAGE_TWINS, twinForStage } from './stageTwins'
import { STAGE_COUNT, VOICES, type Voice } from './atelierLogic'
import manifestJson from './stage-manifest.json'

interface VoiceRecord {
  finalDensityMatchesCanonical: boolean
  densityLadderMonotone: boolean
  renderedAlphaMaxDecrease: number
  stageFractions: number[]
  finalVsShippedInk: {
    meanAbsDiff: number
    alphaMeanAbsDiff: number
    pctPxOver8: number
    strongInkMeanAbsDiff: number
    supportIou: number
  }
  finalCompositeVsCanonicalLayerMeanAbsDiff: number
  stageBytes: number[]
  fillBytes: number
}
interface TwinRecord {
  voice: string
  stage: number
  file: string
  size: [number, number]
  bytes: number
  sourceBytes: number
  method: string
}
interface Manifest {
  stagesPerVoice: number
  intermediateSize: [number, number]
  finalSize: [number, number]
  voices: Record<string, VoiceRecord>
  totals: {
    stageBytes: number
    fillBytes: number
    previousInkBytes: number
    previousFillBytes: number
    twinBytes: number
  }
  twins: TwinRecord[]
}
const manifest = manifestJson as unknown as Manifest

/** The stage file read as a latin1 string — one char per byte,
 *  so length is the byte size and charCodeAt reads raw bytes.
 *  (This project's fs typing declares only the utf8 overload of
 *  readFileSync; the runtime accepts any BufferEncoding, so the
 *  true signature is declared here.) */
const readFileBytes = readFileSync as unknown as (url: URL, encoding: 'latin1') => string

function stageFile(voice: Voice, stage: number): string {
  return readFileBytes(
    new URL(`./assets/stages/stage-${voice}-${stage}.png`, import.meta.url),
    'latin1',
  )
}

function expectPng(buf: string, w: number, h: number) {
  const u32 = (o: number) =>
    ((buf.charCodeAt(o) << 24) |
      (buf.charCodeAt(o + 1) << 16) |
      (buf.charCodeAt(o + 2) << 8) |
      buf.charCodeAt(o + 3)) >>>
    0
  expect([0, 1, 2, 3].map((i) => buf.charCodeAt(i))).toEqual([0x89, 0x50, 0x4e, 0x47])
  expect(u32(16)).toBe(w)
  expect(u32(20)).toBe(h)
}

describe('stage ladders — wiring', () => {
  it('every voice carries a full ladder of stage images', () => {
    expect(manifest.stagesPerVoice).toBe(STAGE_COUNT)
    for (const v of VOICES) {
      expect(STAGE_IMAGES[v]).toHaveLength(STAGE_COUNT)
      STAGE_IMAGES[v].forEach((src, i) => {
        expect(src).toContain(`stage-${v}-${i + 1}`)
      })
    }
  })
})

describe('stage ladders — the generation record', () => {
  it('every final density is the canonical geometry (sha256 gate)', () => {
    for (const v of VOICES) {
      expect(manifest.voices[v].finalDensityMatchesCanonical, v).toBe(true)
    }
  })

  it('every ladder is a true prefix chain, in density and in rendered alpha', () => {
    for (const v of VOICES) {
      expect(manifest.voices[v].densityLadderMonotone, v).toBe(true)
      expect(manifest.voices[v].renderedAlphaMaxDecrease, v).toBe(0)
    }
  })

  it('stage fractions track the uniform grid — the depth hold is exact within one stage', () => {
    for (const v of VOICES) {
      const fractions = manifest.voices[v].stageFractions
      expect(fractions).toHaveLength(STAGE_COUNT)
      expect(fractions[STAGE_COUNT - 1]).toBe(1)
      fractions.forEach((f, i) => {
        expect(Math.abs(f - (i + 1) / STAGE_COUNT), `${v} stage ${i + 1}`).toBeLessThanOrEqual(0.01)
      })
    }
  })

  it('final stages reproduce the shipped ink within the stated tolerance', () => {
    // The comparison that matters is alpha + strong-ink colour:
    // the shipped splits were un-composited from the canonical
    // layers, and Rumi's carries fill bleed (his ink colour equals
    // his fill colour — the bleed pixels lie inside his region
    // mask where true ink is ~0; see the build report). Bounds
    // are the measured record plus headroom, per voice worst case:
    // alpha mean |diff| ≤ 1.17 (Rumi), strong-ink ≤ 1.55 (Jynx),
    // support IoU ≥ 0.87 (Maeve).
    for (const v of VOICES) {
      const rec = manifest.voices[v].finalVsShippedInk
      expect(rec.alphaMeanAbsDiff, `${v} alpha`).toBeLessThanOrEqual(1.25)
      expect(rec.strongInkMeanAbsDiff, `${v} strong ink`).toBeLessThanOrEqual(1.6)
      expect(rec.supportIou, `${v} support`).toBeGreaterThanOrEqual(0.86)
    }
  })

  it('every stage file is an intact PNG of the recorded dimensions and bytes', () => {
    for (const v of VOICES) {
      const rec = manifest.voices[v]
      for (let j = 1; j <= STAGE_COUNT; j++) {
        const buf = stageFile(v, j)
        const [w, h] = j === STAGE_COUNT ? manifest.finalSize : manifest.intermediateSize
        expectPng(buf, w, h)
        expect(buf.length, `${v} stage ${j} bytes`).toBe(rec.stageBytes[j - 1])
      }
    }
  })
})

describe('the refraction twin — one prototype, gated (dynamism spec §2.3)', () => {
  it('the manifest carries exactly the one authorized twin, inside the payload gate', () => {
    // The founder's review authorized ONE representative twin,
    // not the batch: the record must show exactly one, and the
    // total twin payload must sit inside the spec's +1.2MB gate.
    expect(manifest.twins).toHaveLength(1)
    const [twin] = manifest.twins
    expect(twin.voice).toBe('lucian')
    expect(twin.stage).toBe(6)
    expect(twin.file).toBe('stage-lucian-6-refr.png')
    expect(manifest.totals.twinBytes).toBe(twin.bytes)
    expect(manifest.totals.twinBytes).toBeLessThanOrEqual(1.2 * 1024 * 1024)
    // The twin is an addition, never a modification: its source
    // stage's recorded bytes are the manifest's own stage record.
    expect(twin.sourceBytes).toBe(manifest.voices.lucian.stageBytes[5])
  })

  it('the twin file is an intact half-resolution PNG of the recorded bytes', () => {
    const [twin] = manifest.twins
    const buf = readFileBytes(
      new URL(`./assets/stages/${twin.file}`, import.meta.url),
      'latin1',
    )
    expectPng(buf, twin.size[0], twin.size[1])
    expect(twin.size).toEqual([
      manifest.intermediateSize[0] / 2,
      manifest.intermediateSize[1] / 2,
    ])
    expect(buf.length).toBe(twin.bytes)
  })

  it('the wiring carries the same one twin, standing from its stage onward', () => {
    expect(STAGE_TWINS).toHaveLength(1)
    const [twin] = STAGE_TWINS
    expect(twin.voice).toBe('lucian')
    expect(twin.stage).toBe(6)
    expect(twin.src).toContain('stage-lucian-6-refr')
    expect(twinForStage('lucian', 5)).toBeUndefined()
    expect(twinForStage('lucian', 6)).toBe(twin)
    expect(twinForStage('lucian', 12)).toBe(twin)
    for (const v of VOICES) {
      if (v !== 'lucian') expect(twinForStage(v, STAGE_COUNT)).toBeUndefined()
    }
  })
})
