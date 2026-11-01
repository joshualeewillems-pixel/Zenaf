import { describe, expect, it, vi, afterEach } from 'vitest'
import {
  fetchTreePanels,
  treePanelMeta,
  treePanelThreads,
  type TreePanelThread,
} from './archetypes'

afterEach(() => {
  vi.unstubAllGlobals()
})

const ROW: TreePanelThread = {
  id: 'thr-1',
  title: 'The long walk',
  status: 'active',
  latest_confirmed_change: { kind: 'extended', created_at: '2026-10-31T12:00:00+00:00' },
  standing_reading: true,
  proposed_changes: 2,
  confirmed_changes: 1,
}

function okFetch(payload: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({ ok: true, json: async () => payload }),
  )
}

describe('fetchTreePanels', () => {
  it('passes a well-formed panels payload through', async () => {
    okFetch({ panels: { mentor: [ROW], champion: [] } })
    const panels = await fetchTreePanels()
    expect(panels?.mentor).toEqual([ROW])
    expect(panels?.champion).toEqual([])
  })

  it('returns null when signed out or unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 401 }))
    expect(await fetchTreePanels()).toBeNull()
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    expect(await fetchTreePanels()).toBeNull()
  })

  it('returns null for a malformed payload, never partial rows', async () => {
    okFetch({ panels: { mentor: [{ id: 'thr-1' }] } })
    expect(await fetchTreePanels()).toBeNull()
    okFetch({ nope: true })
    expect(await fetchTreePanels()).toBeNull()
    okFetch({ panels: [] })
    expect(await fetchTreePanels()).toBeNull()
  })
})

describe('treePanelThreads', () => {
  it('returns [] for null panels, a missing seat, or an empty list — the no-section contract', () => {
    expect(treePanelThreads(null, 'mentor')).toEqual([])
    expect(treePanelThreads({ champion: [] }, 'mentor')).toEqual([])
    expect(treePanelThreads({ mentor: [] }, 'mentor')).toEqual([])
    expect(treePanelThreads({ mentor: [ROW] }, 'mentor')).toEqual([ROW])
  })
})

describe('treePanelMeta', () => {
  it('carries status, latest confirmed change, standing reading, and awaiting-review count — state only', () => {
    expect(treePanelMeta(ROW)).toBe(
      'active · latest confirmed change: extended (2026-10-31) · standing reading · 2 changes awaiting review',
    )
  })

  it('renders the honest empty state with no completion language', () => {
    const bare: TreePanelThread = {
      ...ROW,
      latest_confirmed_change: null,
      standing_reading: false,
      proposed_changes: 0,
      confirmed_changes: 0,
    }
    expect(treePanelMeta(bare)).toBe('active · no confirmed change yet')
    expect(treePanelMeta(bare)).not.toMatch(/complete|finished|done/)
  })

  it('uses the singular awaiting-review form for one proposed change', () => {
    expect(treePanelMeta({ ...ROW, proposed_changes: 1 })).toContain('1 change awaiting review')
  })
})
