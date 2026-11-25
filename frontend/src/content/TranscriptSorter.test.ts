// @vitest-environment jsdom
/**
 * TranscriptSorter — jsdom render verification of the parents/loose
 * display rule: candidates default to nested under their topic
 * segment parent; loose candidates (segment matches no topic)
 * show directly; expanding a segment reveals its candidates and
 * collapsing restores the default.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import { TranscriptSorter } from './TranscriptSorter'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const SORT_RESULT = {
  transcript_id: 'tr1',
  topics: [{ segment_id: 'seg_1', topic_title: 'Budget review', substantive: true }],
  candidate_tasks: [
    { candidate_task_id: 'ct1', segment_id: 'seg_1', title: 'Anchored task title', confidence: 'high' },
    { candidate_task_id: 'ct2', segment_id: 'seg_99', title: 'Loose task title', confidence: 'low' },
  ],
  candidate_decisions: [
    { candidate_decision_id: 'cd1', segment_id: 'seg_1', summary: 'Anchored decision summary', confidence: 'high' },
  ],
  candidate_ideas: [
    { candidate_idea_id: 'ci1', segment_id: 'seg_1', summary: 'Anchored idea summary', confidence: 'medium' },
  ],
}

describe('TranscriptSorter (parents/loose)', () => {
  let container: HTMLDivElement
  let root: Root

  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => SORT_RESULT,
        text: async () => '',
      })),
    )
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    vi.unstubAllGlobals()
  })

  async function flush() {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0))
    })
  }

  async function clickEl(el: Element) {
    await act(async () => {
      el.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await flush()
  }

  async function clickTestId(testid: string) {
    const el = container.querySelector(`[data-testid="${testid}"]`)
    expect(el, testid).toBeTruthy()
    await clickEl(el!)
  }

  function inputValues(): string[] {
    return [...container.querySelectorAll('input')].map((i) => (i as HTMLInputElement).value)
  }

  it('defaults to topic parents + loose candidates, un-nests per segment, and collapsing restores the default', async () => {
    await act(async () => {
      root.render(React.createElement(TranscriptSorter, { apiBase: '' }))
    })
    await flush()

    const textarea = container.querySelector('textarea')!
    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')!.set!
    await act(async () => {
      setter.call(textarea, 'Alice: we agreed the budget. Bob: I will send the invoice.')
      textarea.dispatchEvent(new Event('input', { bubbles: true }))
    })
    const runButton = [...container.querySelectorAll('button')].find((b) =>
      b.textContent?.includes('Run transcript sorter'),
    )!
    await clickEl(runButton)
    await flush()
    await flush()

    // Default: the topic parent shows; anchored candidates are
    // nested away; the loose candidate task shows directly.
    expect(container.textContent).toContain('Budget review')
    expect(container.textContent).not.toContain('Anchored decision summary')
    expect(container.textContent).not.toContain('Anchored idea summary')
    expect(inputValues()).toContain('Loose task title')
    expect(inputValues()).not.toContain('Anchored task title')

    // Un-nest the segment in the tasks pane: its task appears.
    await clickTestId('transcript-tasks-segment-seg_1')
    expect(inputValues()).toContain('Anchored task title')

    // Collapsing the segment restores the default.
    await clickTestId('transcript-tasks-segment-seg_1')
    expect(inputValues()).not.toContain('Anchored task title')

    // Expand-all in the decisions pane reveals its candidate;
    // collapse-all restores the default.
    await clickTestId('transcript-decisions-expand-all')
    expect(container.textContent).toContain('Anchored decision summary')
    await clickTestId('transcript-decisions-collapse-all')
    expect(container.textContent).not.toContain('Anchored decision summary')

    // The ideas pane un-nests the same way.
    await clickTestId('transcript-ideas-segment-seg_1')
    expect(container.textContent).toContain('Anchored idea summary')
  })
})
