// @vitest-environment jsdom
/**
 * The Scroll's drawing feed — fetchScrollDrawings against a stubbed
 * GET /conversation/drawings (the read side of the [[chalk]]
 * carriage, OPS-7). The endpoint's items carry carriage provenance
 * beside the ScrollDrawing shape; the seam narrows them to the
 * rendered fields PLUS the conversation key the sheet is sorted
 * by, and the read itself is keyed to one conversation (the
 * endpoint's conversation_id filter). An empty feed is the honest
 * blank; a failed read throws rather than faking one.
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
    expect(String(url)).not.toContain('conversation_id=')
    expect(init).toMatchObject({ credentials: 'include' })
    expect(drawings).toEqual([
      {
        id: 'd1',
        title: 'Icarus, again',
        space: { w: 600, h: 800 },
        marks: ENDPOINT_ITEM.marks,
        conversationId: 'jynx-scroll:project:p1',
      },
    ])
  })

  it('keys the read to one conversation when given its id', async () => {
    const fetchFn = stubFetch({ ok: true, status: 200, body: { drawings: [ENDPOINT_ITEM] } })
    vi.stubGlobal('fetch', fetchFn)
    await fetchScrollDrawings('jynx-scroll:project:p1')
    const [url] = fetchFn.mock.calls[0]
    expect(String(url)).toContain(
      `/conversation/drawings?conversation_id=${encodeURIComponent('jynx-scroll:project:p1')}`,
    )
  })

  it('an item without recorded provenance belongs to no conversation', async () => {
    const bare = { id: 'd9', title: null, space: { w: 600, h: 800 }, marks: [] }
    vi.stubGlobal('fetch', stubFetch({ ok: true, status: 200, body: { drawings: [bare] } }))
    const drawings = await fetchScrollDrawings()
    expect(drawings[0].conversationId).toBeNull()
  })

  it('an owner with no drawings gets an empty list — the honest blank', async () => {
    vi.stubGlobal('fetch', stubFetch({ ok: true, status: 200, body: { drawings: [] } }))
    await expect(fetchScrollDrawings()).resolves.toEqual([])
  })

  it('a failed read throws instead of faking a blank', async () => {
    vi.stubGlobal('fetch', stubFetch({ ok: false, status: 500, body: 'boom' }))
    await expect(fetchScrollDrawings()).rejects.toThrow()
  })

  it('pins the endpoint’s exact served payload shape — a drift fails loudly, never silently', async () => {
    // Exactly what list_chalk_drawings serves (api/routes/
    // conversation_routes.py): the ScrollDrawing fields plus
    // carriage provenance, oldest first.
    const served = {
      id: 'f244edde-9f7a-4260-b204-c68ba257b48c',
      title: 'six flags under glass',
      space: { w: 600, h: 800 },
      marks: [{ type: 'stamp', stamp: 'ring', cx: 300, cy: 350, w: 240, tier: 0.95 }],
      conversation_id: 'jynx-scroll:task:t1',
      subject_type: 'task',
      subject_id: 't1',
      created_at: '2026-11-25T18:17:13+00:00',
    }
    vi.stubGlobal('fetch', stubFetch({ ok: true, status: 200, body: { drawings: [served] } }))
    const drawings = await fetchScrollDrawings()
    expect(drawings).toEqual([
      {
        id: served.id,
        title: served.title,
        space: { w: 600, h: 800 },
        marks: served.marks,
        conversationId: 'jynx-scroll:task:t1',
      },
    ])
    // The narrowed shape carries exactly the rendered fields plus
    // the conversation key.
    expect(Object.keys(drawings[0]).sort()).toEqual([
      'conversationId',
      'id',
      'marks',
      'space',
      'title',
    ])

    // Drift: a flattened space (space_w/space_h instead of the
    // nested {w, h}) is NOT a drawing to this surface — dropped,
    // never repaired into a guess.
    const drifted = { ...served, space: undefined, space_w: 600, space_h: 800 }
    vi.stubGlobal('fetch', stubFetch({ ok: true, status: 200, body: { drawings: [drifted] } }))
    await expect(fetchScrollDrawings()).resolves.toEqual([])
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
