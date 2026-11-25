// @vitest-environment jsdom
/**
 * ContentView briefs list — jsdom render verification of the
 * parents/loose display rule: the default listing shows only
 * top-level parents (initiatives, loose projects) and loose
 * briefs; children appear only when their parent is un-nested,
 * and collapsing restores the default.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import { ContentView } from './ContentView'
import { DEFAULT_BRIEF_PAYLOAD } from './types'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function apiBrief(id: string, title: string, links: { linked_initiative_id?: string; linked_project_id?: string }) {
  return {
    id,
    title,
    status: 'draft',
    payload: {
      ...DEFAULT_BRIEF_PAYLOAD,
      title,
      linked_initiative_id: links.linked_initiative_id ?? '',
      linked_project_id: links.linked_project_id ?? '',
    },
  }
}

const BRIEFS = [
  apiBrief('b1', 'Nested script brief', { linked_project_id: 'p1' }),
  apiBrief('b2', 'Direct initiative brief', { linked_initiative_id: 'i1' }),
  apiBrief('b3', 'Loose project brief', { linked_project_id: 'p2' }),
  apiBrief('b4', 'Loose brief', {}),
]

function stubFetch() {
  const data: Record<string, unknown> = {
    '/vision-execution/content-briefs': BRIEFS,
    '/vision-execution/initiatives': [{ id: 'i1', title: 'Alpha Initiative' }],
    '/vision-execution/projects': [
      { id: 'p1', initiative_id: 'i1', title: 'Alpha Project' },
      { id: 'p2', initiative_id: null, title: 'Loose Project' },
    ],
  }
  return vi.fn(async (url: string) => ({
    ok: true,
    status: 200,
    json: async () => data[url] ?? [],
    text: async () => '',
  }))
}

describe('ContentView briefs list (parents/loose)', () => {
  let container: HTMLDivElement
  let root: Root

  beforeEach(() => {
    vi.stubGlobal('fetch', stubFetch())
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

  function listText(): string {
    return container.querySelector('[data-testid="briefs-list"]')?.textContent ?? ''
  }

  async function click(testid: string) {
    const el = container.querySelector(`[data-testid="${testid}"]`)
    expect(el, testid).toBeTruthy()
    await act(async () => {
      el!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await flush()
  }

  it('defaults to parents + loose only, un-nests in place, and collapsing restores the default', async () => {
    await act(async () => {
      root.render(React.createElement(ContentView, { config: { apiBase: '', veApiBase: '' }, showTranscriptSorter: false }))
    })
    await flush()
    await flush()

    // Default: parents + loose only — no child briefs, and the
    // project under the initiative is itself a nested parent.
    expect(listText()).toContain('Alpha Initiative')
    expect(listText()).toContain('Loose Project')
    expect(listText()).toContain('Loose brief')
    expect(listText()).not.toContain('Alpha Project')
    expect(listText()).not.toContain('Nested script brief')
    expect(listText()).not.toContain('Direct initiative brief')
    expect(listText()).not.toContain('Loose project brief')

    // Un-nest the initiative: its project parent and direct brief appear.
    await click('brief-parent-initiative-i1')
    expect(listText()).toContain('Alpha Project')
    expect(listText()).toContain('Direct initiative brief')
    expect(listText()).not.toContain('Nested script brief')

    // Un-nest the project: its brief appears.
    await click('brief-parent-project-p1')
    expect(listText()).toContain('Nested script brief')

    // Collapsing the initiative restores the nested default.
    await click('brief-parent-initiative-i1')
    expect(listText()).not.toContain('Alpha Project')
    expect(listText()).not.toContain('Nested script brief')
    expect(listText()).not.toContain('Direct initiative brief')

    // Expand-all reaches every child, including under the loose project.
    await click('briefs-expand-all')
    expect(listText()).toContain('Nested script brief')
    expect(listText()).toContain('Direct initiative brief')
    expect(listText()).toContain('Loose project brief')

    // Collapse-all restores the default again.
    await click('briefs-collapse-all')
    expect(listText()).not.toContain('Nested script brief')
    expect(listText()).not.toContain('Loose project brief')
    expect(listText()).toContain('Loose brief')
  })
})
