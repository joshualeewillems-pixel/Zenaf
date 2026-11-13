// @vitest-environment jsdom
/**
 * VoiceFeedback tests.
 *
 * Static markup tests cover the three states' initial renders; the
 * interaction tests (createRoot + act, fake timers) cover the state
 * machine: inline auto-save, panel Save, minimize, reopen/edit, and
 * collapse-without-save. No @testing-library/react in package.json —
 * the harness follows CouncilChat.test.ts.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import * as React from 'react'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import VoiceFeedback, {
  FEEDBACK_PRESETS,
  NEUTRAL_SLIDER_VALUE,
  SLIDER_FACES,
  faceForValue,
  type InitialFeedback,
} from './VoiceFeedback'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function renderWidget(
  props: Record<string, unknown> = {},
): string {
  return renderToStaticMarkup(
    createElement(VoiceFeedback, {
      messageId: 'm1',
      seat: 'mentor',
      conversationId: 'skeleton',
      ...props,
    }),
  )
}

describe('slider defaults', () => {
  it('defaults to the neutral middle stop', () => {
    expect(NEUTRAL_SLIDER_VALUE).toBe(4)
    expect(faceForValue(4)).toBe('😐')
  })

  it('renders the slider at neutral when expanded', () => {
    const html = renderWidget({ defaultExpanded: true })
    expect(html).toContain('value="4"')
    expect(html).toContain('😐')
    expect(html).toContain('Sounds like me')
    expect(html).toContain('Say more in your own words')
  })

  it('renders the inline row by default, with slider and Say more', () => {
    // The old collapsed "How did this land?" button is gone: the
    // default is the inline slider row. No checkboxes and no Save
    // button until the panel opens; nothing can be sent yet.
    const html = renderWidget({})
    expect(html).toContain('type="range"')
    expect(html).toContain('value="4"')
    expect(html).toContain('😐')
    expect(html).toContain('Say more')
    expect(html).not.toContain('Sounds like me')
    expect(html).not.toContain('Save feedback')
    expect(html).not.toContain('Saved, tap to change')
  })

  it('mounts minimized when a record already exists', () => {
    const html = renderWidget({
      initialFeedback: { slider: 6, checks: ['Helpful'], note: '' },
    })
    expect(html).toContain('😊')
    expect(html).toContain('How did this land? — Saved, tap to change')
    expect(html).not.toContain('type="range"')
    expect(html).not.toContain('Save feedback')
  })

  it('inline row is built to fit narrow widths without overflow', () => {
    // Structural check (jsdom has no layout): the row wraps, the
    // slider shrinks, and the button never shrinks — so at 390 px and
    // 320 px the row fits the max-w-[88%] wrapper, with the button
    // wrapping below the slider as the specified fallback.
    const html = renderWidget({})
    expect(html).toContain('flex flex-wrap items-center gap-2')
    expect(html).toContain('flex-1 min-w-0 accent-amber-600')
    expect(html).toContain('shrink-0')
  })
})

describe('faces and presets', () => {
  it('has seven faces, neutral in the middle', () => {
    expect(SLIDER_FACES).toHaveLength(7)
    expect(SLIDER_FACES[3]).toBe('😐')
    expect(faceForValue(1)).toBe('😞')
    expect(faceForValue(7)).toBe('🤩')
    expect(faceForValue(0)).toBe('😞')
    expect(faceForValue(99)).toBe('🤩')
  })

  it('uses the design doc six presets', () => {
    expect([...FEEDBACK_PRESETS]).toEqual([
      'Sounds like me',
      'Sounds like the seat',
      'Helpful',
      'Missed the mark',
      'Tone feels off',
      'Want more of this',
    ])
  })
})

describe('interaction', () => {
  let container: HTMLDivElement
  let root: Root
  let posts: Array<{ url: string; body: Record<string, unknown> }>
  let fetchImpl: (url: string, init?: RequestInit) => Promise<Response>

  const okResponse = (payload: unknown) =>
    ({ ok: true, status: 200, json: async () => payload }) as Response

  beforeEach(() => {
    vi.useFakeTimers()
    posts = []
    fetchImpl = async (url: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        posts.push({
          url,
          body: JSON.parse(String(init.body ?? '{}')) as Record<string, unknown>,
        })
      }
      return okResponse({ id: 'fb1' })
    }
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => fetchImpl(url, init)),
    )
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  async function flush(times = 8) {
    for (let i = 0; i < times; i++) {
      await act(async () => {})
    }
  }

  function renderInteractive(props: Record<string, unknown> = {}) {
    act(() => {
      root.render(
        React.createElement(VoiceFeedback, {
          messageId: 'm1',
          seat: 'mentor',
          conversationId: 'skeleton',
          ...props,
        } as never),
      )
    })
  }

  function rangeInput(): HTMLInputElement {
    const el = container.querySelector('input[type="range"]')
    if (!el) throw new Error('range input not found')
    return el as HTMLInputElement
  }

  function setRange(value: number) {
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype,
      'value',
    )?.set
    act(() => {
      setter?.call(rangeInput(), String(value))
      rangeInput().dispatchEvent(new window.Event('input', { bubbles: true }))
    })
  }

  function clickButton(text: string): HTMLElement {
    const el = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent?.includes(text),
    )
    if (!el) throw new Error(`button "${text}" not found`)
    return el as HTMLElement
  }

  async function click(el: Element) {
    await act(async () => {
      ;(el as HTMLElement).click()
    })
    await flush()
  }

  function tickCheckbox(label: string) {
    const input = Array.from(container.querySelectorAll('input[type="checkbox"]')).find(
      (c) => c.closest('label')?.textContent?.includes(label),
    )
    if (!input) throw new Error(`checkbox "${label}" not found`)
    act(() => {
      ;(input as HTMLInputElement).click()
    })
  }

  function setNote(text: string) {
    const ta = container.querySelector('textarea')
    if (!ta) throw new Error('note textarea not found')
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype,
      'value',
    )?.set
    act(() => {
      setter?.call(ta, text)
      ta.dispatchEvent(new window.Event('input', { bubbles: true }))
    })
  }

  it('1. default inline row: slider + Say more, no checkbox, no Save, no POST', () => {
    renderInteractive()
    expect(rangeInput().value).toBe('4')
    expect(container.textContent).toContain('😐')
    expect(container.textContent).toContain('Say more')
    expect(container.querySelector('input[type="checkbox"]')).toBeNull()
    expect(container.textContent).not.toContain('Save feedback')
    expect(posts).toHaveLength(0)
  })

  it('2. slider auto-save: one POST on a changed value, then minimized; untouched sends nothing', async () => {
    renderInteractive()
    expect(posts).toHaveLength(0)
    setRange(6)
    await act(async () => {
      vi.advanceTimersByTime(600)
    })
    await flush()
    expect(posts).toHaveLength(1)
    expect(posts[0].url).toContain('/feedback')
    expect(posts[0].body).toEqual({
      response_ref: 'm1',
      conversation_id: 'skeleton',
      seat: 'mentor',
      slider: 6,
      checks: [],
      note: '',
    })
    expect(container.textContent).toContain('😊')
    expect(container.textContent).toContain('Saved, tap to change')
    expect(container.querySelector('input[type="range"]')).toBeNull()
  })

  it('3. Say more opens the panel prefilled with the current slider value', () => {
    renderInteractive()
    setRange(5)
    expect(posts).toHaveLength(0)
    act(() => {
      clickButton('Say more').click()
    })
    expect(rangeInput().value).toBe('5')
    expect(container.textContent).toContain('Sounds like me')
    const ta = container.querySelector('textarea')
    expect(ta).not.toBeNull()
    expect(ta?.getAttribute('placeholder')).toBe('Say more in your own words…')
    expect(container.textContent).toContain('Save feedback')
  })

  it('4. panel Save minimizes and POSTs slider + checks + note', async () => {
    renderInteractive()
    act(() => {
      clickButton('Say more').click()
    })
    tickCheckbox('Helpful')
    setNote('This landed well.')
    await click(clickButton('Save feedback'))
    expect(posts).toHaveLength(1)
    expect(posts[0].body).toEqual({
      response_ref: 'm1',
      conversation_id: 'skeleton',
      seat: 'mentor',
      slider: 4,
      checks: ['Helpful'],
      note: 'This landed well.',
    })
    expect(container.textContent).toContain('😐')
    expect(container.textContent).toContain('Saved, tap to change')
  })

  it('5. reopen/edit: mounts minimized, panel prefilled and enabled, re-save supersedes', async () => {
    const saved: InitialFeedback = {
      slider: 6,
      checks: ['Helpful'],
      note: 'Landed well.',
    }
    renderInteractive({ initialFeedback: saved })
    expect(container.textContent).toContain('😊')
    expect(container.textContent).toContain('Saved, tap to change')
    await click(clickButton('Saved, tap to change'))
    expect(rangeInput().value).toBe('6')
    expect(rangeInput().disabled).toBe(false)
    const helpful = Array.from(
      container.querySelectorAll('input[type="checkbox"]'),
    ).find((c) => c.closest('label')?.textContent?.includes('Helpful'))
    expect((helpful as HTMLInputElement).checked).toBe(true)
    expect((helpful as HTMLInputElement).disabled).toBe(false)
    const ta = container.querySelector('textarea') as HTMLTextAreaElement
    expect(ta.value).toBe('Landed well.')
    expect(ta.disabled).toBe(false)
    tickCheckbox('Want more of this')
    await click(clickButton('Save feedback'))
    // The second record for this response: the first lives in the
    // prefill fixture, this POST supersedes it (latest wins).
    expect(posts).toHaveLength(1)
    expect(posts[0].body).toEqual({
      response_ref: 'm1',
      conversation_id: 'skeleton',
      seat: 'mentor',
      slider: 6,
      checks: ['Helpful', 'Want more of this'],
      note: 'Landed well.',
    })
    expect(container.textContent).toContain('Saved, tap to change')
  })

  it('6. collapse without save: back to minimized, no POST, edit discarded', async () => {
    renderInteractive({
      initialFeedback: { slider: 6, checks: ['Helpful'], note: 'Landed well.' },
    })
    await click(clickButton('Saved, tap to change'))
    tickCheckbox('Missed the mark')
    await click(clickButton('Done'))
    expect(posts).toHaveLength(0)
    expect(container.textContent).toContain('😊')
    expect(container.textContent).toContain('Saved, tap to change')
    // Reopen: the unsaved tick is gone, the saved values stand.
    await click(clickButton('Saved, tap to change'))
    const missed = Array.from(
      container.querySelectorAll('input[type="checkbox"]'),
    ).find((c) => c.closest('label')?.textContent?.includes('Missed the mark'))
    expect((missed as HTMLInputElement).checked).toBe(false)
    const helpful = Array.from(
      container.querySelectorAll('input[type="checkbox"]'),
    ).find((c) => c.closest('label')?.textContent?.includes('Helpful'))
    expect((helpful as HTMLInputElement).checked).toBe(true)
  })

  it('7. panel Save failure: error shown, panel stays open, values retained', async () => {
    fetchImpl = async () => {
      throw new Error('network down')
    }
    renderInteractive()
    act(() => {
      clickButton('Say more').click()
    })
    tickCheckbox('Helpful')
    setNote('Keep this.')
    await click(clickButton('Save feedback'))
    expect(container.textContent).toContain("Couldn't save — try again.")
    expect(container.textContent).toContain('Save feedback')
    expect(container.textContent).not.toContain('Saved, tap to change')
    const ta = container.querySelector('textarea') as HTMLTextAreaElement
    expect(ta.value).toBe('Keep this.')
  })

  it('8. inline auto-save failure: error shown, stays inline, value retained', async () => {
    fetchImpl = async () => {
      throw new Error('network down')
    }
    renderInteractive()
    setRange(6)
    await act(async () => {
      vi.advanceTimersByTime(600)
    })
    await flush()
    expect(container.textContent).toContain("Couldn't save — try again.")
    expect(container.textContent).toContain('Say more')
    expect(container.textContent).not.toContain('Saved, tap to change')
    expect(rangeInput().value).toBe('6')
  })

  it('9. late prefill: a record arriving after mount is adopted while untouched', async () => {
    renderInteractive({ initialFeedback: null })
    expect(container.textContent).toContain('Say more')
    act(() => {
      root.render(
        React.createElement(VoiceFeedback, {
          messageId: 'm1',
          seat: 'mentor',
          conversationId: 'skeleton',
          initialFeedback: { slider: 6, checks: [], note: '' },
        } as never),
      )
    })
    await flush()
    expect(container.textContent).toContain('😊')
    expect(container.textContent).toContain('Saved, tap to change')
  })

  it('10. collapse from inline returns to inline, discarding a pending slider move', () => {
    renderInteractive()
    setRange(6)
    act(() => {
      clickButton('Say more').click()
    })
    act(() => {
      clickButton('Done').click()
    })
    expect(posts).toHaveLength(0)
    expect(rangeInput().value).toBe('4')
    expect(container.textContent).toContain('😐')
    expect(container.textContent).toContain('Say more')
  })
})
