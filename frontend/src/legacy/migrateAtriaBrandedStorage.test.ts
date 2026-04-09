import { describe, expect, it, vi } from 'vitest'
import { migrateAtriaBrandedBrowserStorage } from './migrateAtriaBrandedStorage'

function mockStorage(initial: Record<string, string>) {
  const m = { ...initial }
  return {
    get length() {
      return Object.keys(m).length
    },
    key(i: number) {
      return Object.keys(m)[i] ?? null
    },
    getItem(k: string) {
      return m[k] ?? null
    },
    setItem(k: string, v: string) {
      m[k] = v
    },
    removeItem(k: string) {
      delete m[k]
    },
    _dump: () => ({ ...m }),
  }
}

describe('migrateAtriaBrandedBrowserStorage', () => {
  it('copies exact localStorage keys when zenaf slot empty', () => {
    const ls = mockStorage({ 'atria-perspective-agents': '[{"id":"x"}]' })
    const ss = mockStorage({})
    vi.stubGlobal('window', {
      localStorage: ls as unknown as Storage,
      sessionStorage: ss as unknown as Storage,
    })
    migrateAtriaBrandedBrowserStorage()
    expect(ls._dump()['zenaf-perspective-agents']).toBe('[{"id":"x"}]')
    expect(ls._dump()['atria-perspective-agents']).toBeUndefined()
    vi.unstubAllGlobals()
  })

  it('migrates prefixed core profile conversation keys', () => {
    const ls = mockStorage({
      'atria-core-profile-conversation-abc': '[]',
    })
    const ss = mockStorage({})
    vi.stubGlobal('window', {
      localStorage: ls as unknown as Storage,
      sessionStorage: ss as unknown as Storage,
    })
    migrateAtriaBrandedBrowserStorage()
    expect(ls._dump()['zenaf-core-profile-conversation-abc']).toBe('[]')
    expect(ls._dump()['atria-core-profile-conversation-abc']).toBeUndefined()
    vi.unstubAllGlobals()
  })
})
