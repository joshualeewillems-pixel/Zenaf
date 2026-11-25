// @vitest-environment jsdom
/**
 * The Scroll's drawing feed — fetchScrollDrawings against a stubbed
 * GET /conversation/drawings (the read side of the [[chalk]]
 * carriage, OPS-7). The endpoint's items carry carriage provenance
 * beside the ScrollDrawing shape; the seam narrows them to exactly
 * what the surface renders. An empty feed is the honest blank; a
 * failed read throws rather than faking one.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { fetchScrollDrawings } from './scrollApi'

const ENDPOINT_ITEM = {
  id: 'd1',
  title: 'Icarus, again',
  space: { w: 600, h: 800 },
  marks: [
    { type: 'stamp', stamp: 'ring', cx: 300, cy: 300, w: 400, tier: 0.6 },
    { type: 'stroke', d: 'M100 600 Q300 560 500 620', width: 3, tier: 0.32 },
  ],
  conversation_id: 'jynx-scroll:project:p1',
  subject_type: 'project',
  subject_id: 'p1',
  created_at: '2026-11-25T00:00:00Z',
}

function stubFetch(response: { ok: boolean; status: number; body: unknown }) {
  return vi.fn(async (_url: string, _init?: RequestInit) => ({
    ok: response.ok,
    status: response.status,
    json: async () => response.body,
    text: async () => (typeof response.body === 'string' ? response.body : JSON.stringify(response.body)),
  }))
}

describe('fetchScrollDrawings', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('reads the endpoint and narrows items to the ScrollDrawing shape', async () => {
    const fetchFn = stubFetch({ ok: true, status: 200, body: { drawings: [ENDPOINT_ITEM] } })
    vi.stubGlobal('fetch', fetchFn)
    const drawings = await fetchScrollDrawings()
    expect(fetchFn).toHaveBeenCalledTimes(1)
    const [url, init] = fetchFn.mock.calls[0]
    expect(String(url)).toContain('/conversation/drawings')
    expect(init).toMatchObject({ credentials: 'include' })
    expect(drawings).toEqual([
      {
        id: 'd1',
        title: 'Icarus, again',
        space: { w: 600, h: 800 },
        marks: ENDPOINT_ITEM.marks,
      },
    ])
  })

  it('an owner with no drawings gets an empty list — the honest blank', async () => {
    vi.stubGlobal('fetch', stubFetch({ ok: true, status: 200, body: { drawings: [] } }))
    await expect(fetchScrollDrawings()).resolves.toEqual([])
  })

  it('a failed read throws instead of faking a blank', async () => {
    vi.stubGlobal('fetch', stubFetch({ ok: false, status: 500, body: 'boom' }))
    await expect(fetchScrollDrawings()).rejects.toThrow()
  })

  it('items that are not drawings are dropped, never repaired', async () => {
    vi.stubGlobal(
      'fetch',
      stubFetch({
        ok: true,
        status: 200,
        body: { drawings: [ENDPOINT_ITEM, { id: 'broken' }, null, 'nope'] },
      }),
    )
    const drawings = await fetchScrollDrawings()
    expect(drawings.map((d) => d.id)).toEqual(['d1'])
  })
})
