import { describe, expect, it, vi, afterEach } from 'vitest'
import { fetchPendingReviewCount } from './reviewQueue'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('fetchPendingReviewCount', () => {
  it('returns the number of pending agents', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => [{ id: 'a1' }, { id: 'a2' }, { id: 'a3' }],
      }),
    )
    expect(await fetchPendingReviewCount('')).toBe(3)
  })

  it('returns 0 for an empty queue', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, json: async () => [] }),
    )
    expect(await fetchPendingReviewCount('')).toBe(0)
  })

  it('returns null when signed out (401)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 401 }))
    expect(await fetchPendingReviewCount('')).toBeNull()
  })

  it('returns null on network failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    expect(await fetchPendingReviewCount('')).toBeNull()
  })

  it('returns null for a non-list payload', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, json: async () => ({ error: 'weird' }) }),
    )
    expect(await fetchPendingReviewCount('')).toBeNull()
  })
})
