// @vitest-environment jsdom
/**
 * Scene 1 harness — renders the room against a shelf shaped like
 * the staging owner's real one (8 initiatives, several with
 * nested project/task bays, plus loose items), and writes the
 * rendered scene to standalone HTML files (assets inlined) for a
 * screenshot render check. The files land at SCENE_HARNESS_OUT
 * (default /tmp/scene-one-room.html and /tmp/scene-one-open.html).
 * The assertions pin the room's composition; the screenshots are
 * the visual evidence attached to the build's PR — founder
 * on-device acceptance remains his, separately.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import { readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

vi.mock('../chat/CouncilChat', async () => {
  const ReactMod = await import('react')
  return {
    default: () => ReactMod.createElement('div', { 'data-testid': 'jynx-chat' }),
  }
})
vi.mock('./scrollApi', async (importOriginal) => {
  const orig = await importOriginal<typeof import('./scrollApi')>()
  return { ...orig, fetchScrollDrawings: async () => [] }
})

import JynxScrollView from './JynxScrollView'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const base = {
  brief: '', owner_id: null, supporting_owner_ids: [], priority: '',
  start_date: null, end_date: null, estimated_weekly_hours: null,
  next_step_ai: '', notes: '', created_at: '2026-02-01T00:00:00', updated_at: '2026-02-01T00:00:00',
}
const ibase = {
  brief: '', owner_id: null, evaluation_priority: null, estimated_cost_ai: '',
  estimated_timeframe_ai: '', philosophical_alignment_ai: '', next_step_ai: '',
  required_assets: [], dependencies: '', risks: '', recommendation: '',
  kill_criteria: '', notes: '', updated_at: '2026-01-01T00:00:00',
}
const tbase = {
  parent_task_id: null, description: '', assignee_id: null, priority: '',
  estimated_hours: null, due_date: null, dependency_ids: [],
  completion_criteria: '', notes: '', created_at: '2026-03-01T00:00:00', updated_at: '2026-03-01T00:00:00',
}

/** Eight initiatives in the staging shelf's shape: the build
 *  tree with its tier projects and their tasks, the council
 *  chain, and a spread of smaller and leaf initiatives. */
function stubFetch() {
  const initiatives = [
    { ...ibase, id: 'i-build', title: 'Zenaf build directions', status: 'Active', source_idea_id: null, created_at: '2026-01-01T00:00:00' },
    { ...ibase, id: 'i-council', title: 'Meet your council', status: 'Active', source_idea_id: null, created_at: '2026-01-03T00:00:00' },
    { ...ibase, id: 'i-out', title: 'Zenaf — outsourced executive function', status: 'Active', source_idea_id: null, created_at: '2026-01-05T00:00:00' },
    { ...ibase, id: 'i-capture', title: 'Meeting capture quality', status: 'Active', source_idea_id: null, created_at: '2026-01-08T00:00:00' },
    { ...ibase, id: 'i-garden', title: 'The garden year', status: 'Active', source_idea_id: null, created_at: '2026-01-11T00:00:00' },
    { ...ibase, id: 'i-money', title: 'Money, honestly', status: 'Blocked', source_idea_id: null, created_at: '2026-01-14T00:00:00' },
    { ...ibase, id: 'i-house', title: 'House and kin', status: 'Active', source_idea_id: null, created_at: '2026-01-17T00:00:00' },
    { ...ibase, id: 'i-quiet', title: 'A quieter practice', status: 'Active', source_idea_id: null, created_at: '2026-01-20T00:00:00' },
  ]
  const projects = [
    { ...base, id: 'bp0', initiative_id: 'i-build', title: 'T0 — foundations', status: 'Active' },
    { ...base, id: 'bp1', initiative_id: 'i-build', title: 'T1 — first meetings', status: 'Active' },
    { ...base, id: 'bp2', initiative_id: 'i-build', title: 'T2 — the worlds', status: 'Draft' },
    { ...base, id: 'bp3', initiative_id: 'i-build', title: 'T3 — memory', status: 'Active' },
    { ...base, id: 'bp4', initiative_id: 'i-build', title: 'T4 — later', status: 'Draft' },
    { ...base, id: 'cp1', initiative_id: 'i-council', title: 'Meet the Bear', status: 'Blocked' },
    { ...base, id: 'cp2', initiative_id: 'i-council', title: 'Meet the Fox', status: 'Active' },
    { ...base, id: 'op1', initiative_id: 'i-out', title: 'The promise, plainly', status: 'Active' },
    { ...base, id: 'mp1', initiative_id: 'i-money', title: 'Storage and bills', status: 'Blocked' },
    { ...base, id: 'lp1', initiative_id: null, title: 'Fix the gate latch', status: 'Active' },
  ]
  const tasks = [
    { ...tbase, id: 'bt1', project_id: 'bp0', title: 'Owner isolation', status: 'Done' },
    { ...tbase, id: 'bt2', project_id: 'bp0', title: 'Erasure coverage', status: 'Todo' },
    { ...tbase, id: 'bt3', project_id: 'bp1', title: 'Six-seat first meetings (December)', status: 'Active' },
    { ...tbase, id: 'bt4', project_id: 'bp1', title: 'Rapid fire rounds', status: 'Done' },
    { ...tbase, id: 'bt5', project_id: 'bp2', title: 'Scene 1 — the Scroll', status: 'Active' },
    { ...tbase, id: 'bt6', project_id: 'bp3', title: 'Dismissal coverage', status: 'Done' },
    { ...tbase, id: 'ct1', project_id: 'cp1', title: 'Bear step one', status: 'Todo' },
    { ...tbase, id: 'ct2', project_id: 'cp1', title: 'Bear step two', status: 'Todo' },
    { ...tbase, id: 'ct3', project_id: 'cp2', title: 'Fox step one', status: 'Todo' },
    { ...tbase, id: 'ot1', project_id: 'op1', title: 'One paragraph, true', status: 'Todo' },
    { ...tbase, id: 'lt1', project_id: 'lp1', title: 'Hinges', status: 'Todo' },
    { ...tbase, id: 'lt2', project_id: null, title: 'Loose thought', status: 'Todo' },
  ]
  const data: Record<string, unknown> = {
    '/vision-execution/ideas': [
      { id: 'idea1', title: 'A loose idea', summary: '', description: '', status: 'Captured', tags: [], created_by: '', notes: '', created_at: '2025-12-01T00:00:00', updated_at: '2025-12-01T00:00:00' },
    ],
    '/vision-execution/initiatives': initiatives,
    '/vision-execution/projects': projects,
    '/vision-execution/tasks': tasks,
    '/vision-execution/persons': [],
    '/vision-execution/assets': [],
  }
  return vi.fn(async (url: string) => ({
    ok: true,
    status: 200,
    json: async () => data[url] ?? [],
    text: async () => '',
  }))
}

const ASSETS_DIR = join(dirname(fileURLToPath(import.meta.url)), 'assets')

function inlineAssets(html: string): string {
  return html.replace(/(href|src)="([^"]+)"/g, (m, attr: string, url: string) => {
    const name = url.split('/').pop() ?? ''
    if (!name.endsWith('.png')) return m
    try {
      const b64 = readFileSync(join(ASSETS_DIR, name)).toString('base64')
      return `${attr}="data:image/png;base64,${b64}"`
    } catch {
      return m
    }
  })
}

function standalone(sceneHtml: string, title: string): string {
  return `<!doctype html><html><head><meta charset="utf-8"><title>${title}</title>
<style>body{margin:0;background:#171310;display:flex;justify-content:center;padding:24px}
.frame{width:1100px}svg{width:100%;height:auto;display:block}</style></head>
<body><div class="frame">${sceneHtml}</div></body></html>`
}

describe('Scene 1 harness render', () => {
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

  it('renders the room with the staging-shaped shelf and writes the harness pages', async () => {
    await act(async () => {
      root.render(React.createElement(JynxScrollView))
    })
    await flush()
    await flush()

    const scene = container.querySelector('section[aria-label^="Jynx — the Scroll"]')
    expect(scene).not.toBeNull()
    // Eight initiatives in cubbies, plus the loose face.
    expect(container.querySelectorAll('[data-cubby]')).toHaveLength(11)
    // The build tree's cubby clusters: head + 3 shown of its nest.
    const build = container.querySelector('[data-cubby="initiative:i-build"]')
    expect(build!.querySelectorAll('[data-scroll]')).toHaveLength(4)
    // The fabric stands: the four soft depth bands for each of the
    // 230 rhombs, and one wooden frame image laid on every rhomb.
    expect(scene!.querySelectorAll('polygon').length).toBe(920)
    expect(scene!.querySelectorAll('image[transform^="matrix"]').length).toBe(230)

    const outRoom = process.env.SCENE_HARNESS_OUT ?? '/tmp/scene-one-room.html'
    writeFileSync(outRoom, standalone(inlineAssets(scene!.outerHTML), 'Scene 1 — the room'))

    // Open the build tree's first tier project on the sheet:
    // tap its cluster scroll in the cubby, then the popup.
    const hit = [...build!.querySelectorAll('[data-scroll="project:bp0"] rect')].find(
      (r) => r.getAttribute('fill-opacity') === '0',
    )
    await act(async () => {
      hit!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await flush()
    const popup = container.querySelector('[data-testid="scroll-popup"]')
    expect(popup).not.toBeNull()
    await act(async () => {
      popup!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await flush()
    expect(container.querySelector('[data-open-scroll="project:bp0"]')).not.toBeNull()
    // Let the sheet's one unroll run its course before the page
    // is serialized — the render shows the scroll standing open.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 1300))
    })
    await flush()
    const outOpen = outRoom.replace(/\.html$/, '-open.html')
    writeFileSync(outOpen, standalone(inlineAssets(scene!.outerHTML), 'Scene 1 — a scroll open'))
    // The full room render (920 depth bands + 230 frame images +
    // inlined assets) is genuinely slow under jsdom — the
    // assertions are the gate, not the default 5s clock.
  }, 60000)
})
