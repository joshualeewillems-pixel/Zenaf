// @vitest-environment jsdom
/**
 * The Bench-bonsai bridge (palacePlant): jsdom has no real canvas,
 * so this suite hands the plant a recording-free fake 2d context
 * (a Proxy that absorbs every painter call and returns the few
 * objects the painters read) and a stub toDataURL. That is enough
 * to prove the whole path executes — growTree grows the bonsai,
 * the Bench's own wood painters paint it, and PlantMark stands
 * the resulting image in the plant's slot. On-device painting of
 * the real canvas remains the founder's visual acceptance.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import { PlantMark } from './palaceCanvas'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function fakeContext(): CanvasRenderingContext2D {
  const store: Record<string, unknown> = {}
  return new Proxy(store, {
    get(t, prop) {
      if (prop === 'createLinearGradient' || prop === 'createRadialGradient') {
        return () => ({ addColorStop: () => {} })
      }
      if (prop === 'measureText') return () => ({ width: 0 })
      if (prop === 'getImageData') return () => ({ data: new Uint8ClampedArray(4) })
      if (prop in t) return t[prop as string]
      return () => {}
    },
    set(t, prop, value) {
      t[prop as string] = value
      return true
    },
  }) as unknown as CanvasRenderingContext2D
}

function stubCanvas() {
  const real = document.createElement.bind(document)
  return vi.spyOn(document, 'createElement').mockImplementation(((tag: string) => {
    if (tag === 'canvas') {
      return {
        width: 0,
        height: 0,
        getContext: () => fakeContext(),
        toDataURL: () => 'data:image/png;base64,BONSAI',
      } as unknown as HTMLCanvasElement
    }
    return real(tag)
  }) as typeof document.createElement)
}

function renderPlant(state: 'growing' | 'fruiting'): string {
  const container = document.createElement('div')
  const root = createRoot(container)
  act(() => {
    root.render(
      React.createElement(
        'svg',
        null,
        React.createElement(PlantMark, { x: 100, base: 200, state, scale: 1 }),
      ),
    )
  })
  const html = container.innerHTML
  act(() => root.unmount())
  return html
}

describe('the Palace plant, painted by the Bench', () => {
  afterEach(() => vi.restoreAllMocks())

  it('grows and paints the bonsai and stands it as an image', () => {
    stubCanvas()
    const html = renderPlant('growing')
    expect(html).toContain('<image')
    expect(html).toContain('data:image/png;base64,BONSAI')
  })

  it('paints the fruiting state too (full-density foliage)', () => {
    stubCanvas()
    const html = renderPlant('fruiting')
    expect(html).toContain('data:image/png;base64,BONSAI')
  })

  // The no-canvas fallback (PlantGlyph stands) is pinned in
  // palaceRenderScan.test.ts, which renders whole scenes in
  // jsdom's canvas-less environment — the per-state image cache
  // in palacePlant makes an in-file fallback case order-dependent.
})
