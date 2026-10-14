import { describe, expect, it, vi, afterEach } from 'vitest'
import {
  COUNCIL_PERSONALITY_MODES,
  DEFAULT_COUNCIL_PERSONALITY_MODE,
  fetchCouncilPersonalityMode,
  isCouncilPersonalityMode,
  saveCouncilPersonalityMode,
} from './councilPersonalityMode'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('council personality mode values', () => {
  it('offers exactly base / mirror / blend', () => {
    expect(COUNCIL_PERSONALITY_MODES).toEqual(['base', 'mirror', 'blend'])
    expect(DEFAULT_COUNCIL_PERSONALITY_MODE).toBe('blend')
  })

  it('validates mode values', () => {
    expect(isCouncilPersonalityMode('base')).toBe(true)
    expect(isCouncilPersonalityMode('mirror')).toBe(true)
    expect(isCouncilPersonalityMode('blend')).toBe(true)
    expect(isCouncilPersonalityMode('bogus')).toBe(false)
    expect(isCouncilPersonalityMode(null)).toBe(false)
    expect(isCouncilPersonalityMode(undefined)).toBe(false)
  })
})

describe('fetchCouncilPersonalityMode', () => {
  it('returns the saved mode', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ council_mode: 'mirror' }),
      }),
    )
    expect(await fetchCouncilPersonalityMode()).toBe('mirror')
  })

  it('falls back to blend when the server is unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    expect(await fetchCouncilPersonalityMode()).toBe('blend')
  })

  it('falls back to blend on unknown server values', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ council_mode: 'bogus' }),
      }),
    )
    expect(await fetchCouncilPersonalityMode()).toBe('blend')
  })
})

describe('saveCouncilPersonalityMode', () => {
  it('PUTs the mode to /personality/council-mode', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: true, json: () => Promise.resolve({ council_mode: 'base' }) })
    vi.stubGlobal('fetch', fetchMock)
    expect(await saveCouncilPersonalityMode('base')).toBe(true)
    expect(fetchMock).toHaveBeenCalledWith(
      '/personality/council-mode',
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({ council_mode: 'base' }),
      }),
    )
  })

  it('resolves false on failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    expect(await saveCouncilPersonalityMode('mirror')).toBe(false)
  })
})
