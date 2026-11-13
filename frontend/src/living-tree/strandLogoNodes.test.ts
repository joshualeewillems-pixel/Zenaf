// @vitest-environment jsdom
/**
 * Strand logos + text removals on the Living Tree (founder, 2026-11-12):
 * the seven strand root nodes wear their strand logos (cropped from the
 * founder's strand logo concept sheet) instead of their two-letter
 * monograms — always, with no reveal gate — while their name pills stay.
 * The "YOU · TAP FOR OPTIONS" pill under the center node is removed
 * (the photo node itself stays the tap target and still opens the YOU
 * menu), and the "Training first, rent later" footer text is removed.
 *
 * No JSX (vitest includes *.test.ts only): createElement throughout.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import { LivingTreeView } from './LivingTree'
import {
  STRANDS,
  STRAND_LOGOS,
  TAXONOMY_TO_DESIGN,
  resolveStrandLogo,
  type DesignStrandKey,
} from './strands'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function ok(payload: unknown) {
  return { ok: true, status: 200, json: async () => payload } as Response
}

function seat(partial: Record<string, unknown>) {
  return {
    id: 'mentor',
    display_name: 'Mentor',
    strand_weights: { self: 0.5, word: 0.5 },
    depth: 40,
    band: 'developing',
    prompt_frame: 'The long view.',
    twigs: [],
    is_skeptic: false,
    avatar_url: null,
    avatar_unlocked: false,
    avatar_signals_to_unlock: 10,
    face_revealed: false,
    ...partial,
  }
}

let container: HTMLDivElement
let root: Root

function installFetch() {
  const fetchMock = vi.fn((url: string) => {
    if (url.includes('/council/archetypes/status')) {
      return Promise.resolve(
        ok({
          archetypes: [
            seat({ face_revealed: true }),
            seat({
              id: 'champion',
              display_name: 'Champion',
              strand_weights: { body: 1 },
              depth: 0,
              band: 'not yet trained',
              prompt_frame: 'Courage, action.',
              face_revealed: false,
            }),
          ],
        }),
      )
    }
    if (url.includes('/vision-execution/keystone-attention')) {
      return Promise.resolve(ok({ seeded: true, markers: {} }))
    }
    return Promise.resolve(ok({}))
  })
  vi.stubGlobal('fetch', fetchMock)
}

/** Same flush discipline as seatLogoNodes.test.ts. */
async function flush() {
  for (let i = 0; i < 8; i++) {
    await act(async () => {})
  }
  await act(async () => {
    await new Promise((r) => setTimeout(r, 200))
  })
}

function renderTree() {
  act(() => {
    root.render(
      React.createElement(LivingTreeView, {
        onNavigate: () => {},
        currentUserId: 'user-1',
      } as never),
    )
  })
}

/** The hrefs of every <image> inside a tree node. */
function nodeImageHrefs(): string[] {
  return Array.from(container.querySelectorAll('g.lnode image')).map(
    (el) => el.getAttribute('href') ?? '',
  )
}

/** The initials text of every tree node that shows letters. */
function nodeInitials(): string[] {
  return Array.from(container.querySelectorAll('g.lnode text.nm')).map(
    (el) => el.textContent ?? '',
  )
}

beforeEach(() => {
  installFetch()
  ;(window.Element.prototype as unknown as { scrollIntoView: () => void }).scrollIntoView =
    () => {}
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.unstubAllGlobals()
})

describe('strand logo resolution', () => {
  it('every strand resolves to its own logo asset, with no gate', () => {
    const designKeys = Object.keys(STRAND_LOGOS) as DesignStrandKey[]
    expect(designKeys.sort()).toEqual(
      ['compass', 'ear', 'eye', 'hands', 'heart', 'logic', 'voice'].sort(),
    )
    for (const s of STRANDS) {
      const logo = resolveStrandLogo(s.key)
      expect(logo).toBeTruthy()
      expect(logo).toContain(`${TAXONOMY_TO_DESIGN[s.key]}-logo`)
      expect(logo).toBe(STRAND_LOGOS[TAXONOMY_TO_DESIGN[s.key]])
    }
  })
})

describe('strand logos on the tree', () => {
  it('all seven strand roots show their logos instead of monograms', async () => {
    renderTree()
    await flush()
    const hrefs = nodeImageHrefs()
    for (const name of ['heart', 'hands', 'logic', 'voice', 'ear', 'compass', 'eye']) {
      expect(hrefs.some((h) => h.includes(`${name}-logo`))).toBe(true)
    }
    const initials = nodeInitials()
    for (const mono of ['HE', 'HA', 'LO', 'VO', 'EA', 'CO', 'EY']) {
      expect(initials).not.toContain(mono)
    }
  })

  it('the strand name pills stay beside the logo nodes', async () => {
    renderTree()
    await flush()
    for (const name of ['Heart', 'Hands', 'Logic', 'Voice', 'Ear', 'Compass', 'Eye']) {
      expect(container.textContent).toContain(name)
    }
  })
})

describe('founder text removals', () => {
  it('the YOU pill and the footer text are absent', async () => {
    renderTree()
    await flush()
    expect(container.textContent).not.toContain('TAP FOR OPTIONS')
    expect(container.textContent).not.toContain('YOU · TAP FOR OPTIONS')
    expect(container.textContent).not.toContain('Training first')
    expect(container.textContent).not.toContain('rent later')
    expect(container.textContent).not.toContain('marketplace is a lens')
    expect(container.querySelector('.lfoot')).toBeNull()
  })

  it('the you-node itself still taps open the YOU menu', async () => {
    renderTree()
    await flush()
    // The menu is closed before the tap.
    expect(container.textContent).not.toContain("The council's briefing")
    const youText = Array.from(container.querySelectorAll('g.lnode text.nm')).find(
      (el) => el.textContent === 'YOU',
    )
    expect(youText).toBeTruthy()
    const youNode = youText!.closest('g.lnode')!
    act(() => {
      youNode.dispatchEvent(new window.MouseEvent('click', { bubbles: true }))
    })
    await flush()
    expect(container.textContent).toContain("The council's briefing")
  })
})
