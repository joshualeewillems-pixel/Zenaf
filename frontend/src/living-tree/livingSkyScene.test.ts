// @vitest-environment jsdom
/**
 * LivingSkyScene — the painted scene as the Living Tree's renderer
 * (port plan §5, §8 Increment 1). The contract under test is the hit
 * overlay: 15 transparent tap groups at the painted medallion
 * centres, each carrying the production datum id `onTap` has always
 * received; the attention/invitation badges living inside the seat
 * groups with their established classes and aria labels; and the
 * user's photo over the painted YOU disc when one is set.
 *
 * No JSX (vitest includes *.test.ts only): createElement throughout.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import { LivingSkyScene, type SkyBadge } from './LivingSkyScene'
import { HIT_NODES } from './skyGeometry'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const YOU_PHOTO = 'https://example.com/you.jpg'

let container: HTMLDivElement
let root: Root
let taps: string[]

function renderScene(opts?: {
  badges?: Record<string, SkyBadge>
  userAvatarUrl?: string
}) {
  taps = []
  act(() => {
    root.render(
      React.createElement(LivingSkyScene, {
        badges: opts?.badges ?? {},
        userAvatarUrl: opts?.userAvatarUrl,
        youImgBroken: false,
        onYouImgError: () => {},
        onTap: (id: string) => {
          taps.push(id)
        },
      }),
    )
  })
}

function hitGroup(id: string): Element {
  const g = container.querySelector(`g.lnode[data-node-id="${id}"]`)
  if (!g) throw new Error(`hit group "${id}" not found`)
  return g
}

function clickGroup(id: string) {
  act(() => {
    hitGroup(id).dispatchEvent(new window.MouseEvent('click', { bubbles: true }))
  })
}

beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
})

describe('the hit overlay', () => {
  it('carries exactly the 15 painted medallions, by production datum id', () => {
    renderScene()
    const groups = Array.from(container.querySelectorAll('g.lnode'))
    expect(groups).toHaveLength(15)
    expect(groups.map((g) => g.getAttribute('data-node-id'))).toEqual(
      HIT_NODES.map((n) => n.id),
    )
    expect(HIT_NODES.map((n) => n.id)).toEqual([
      'arch-mentor',
      'arch-champion',
      'arch-guardian',
      'arch-maverick',
      'arch-ambassador',
      'arch-conductor',
      'arch-skeptic',
      'you',
      'agent-number',
      'agent-body',
      'agent-word',
      'agent-image',
      'agent-people',
      'agent-sound',
      'agent-self',
    ])
    // Every group is a real tap target: a 30-unit hit circle.
    for (const g of groups) {
      expect(g.querySelector('circle')?.getAttribute('r')).toBe('30')
    }
  })

  it('a tap dispatches the datum id the view has always received', () => {
    renderScene()
    clickGroup('arch-mentor')
    clickGroup('you')
    clickGroup('agent-image')
    clickGroup('arch-skeptic')
    expect(taps).toEqual(['arch-mentor', 'you', 'agent-image', 'arch-skeptic'])
  })

  it('hit groups carry accessible names', () => {
    renderScene()
    expect(hitGroup('arch-mentor').getAttribute('aria-label')).toBe('Mentor')
    expect(hitGroup('you').getAttribute('aria-label')).toBe('You')
    expect(hitGroup('agent-image').getAttribute('aria-label')).toBe('Eye')
  })
})

describe('badges inside the hit groups', () => {
  it('attention and invitation badges render with their classes and labels', () => {
    renderScene({
      badges: {
        mentor: {
          attentionTitle: 'The Gardener wants to meet you.',
          inviteLabel: 'The Gardener has 2 invitations to discuss',
          inviteCount: 2,
        },
      },
    })
    const g = hitGroup('arch-mentor')
    const attn = g.querySelector('g.attn')
    expect(attn).not.toBeNull()
    expect(attn!.getAttribute('aria-label')).toBe('The Gardener wants to meet you.')
    expect(g.querySelector('circle.attndot')).not.toBeNull()
    expect(g.querySelector('text.attnt')?.textContent).toBe('!')
    const inv = g.querySelector('g.inv')
    expect(inv).not.toBeNull()
    expect(inv!.getAttribute('aria-label')).toBe(
      'The Gardener has 2 invitations to discuss',
    )
    expect(g.querySelector('circle.invdot')).not.toBeNull()
    expect(g.querySelector('text.invt')?.textContent).toBe('2')
    // A seat with no badge state carries neither badge.
    const bare = hitGroup('arch-champion')
    expect(bare.querySelector('g.attn')).toBeNull()
    expect(bare.querySelector('g.inv')).toBeNull()
  })

  it('invitation counts cap at 9+', () => {
    renderScene({
      badges: {
        guardian: { inviteLabel: 'The Bear has 12 invitations to discuss', inviteCount: 12 },
      },
    })
    expect(hitGroup('arch-guardian').querySelector('text.invt')?.textContent).toBe('9+')
  })
})

describe('the YOU photo overlay', () => {
  it('the photo renders over the painted YOU disc when set', () => {
    renderScene({ userAvatarUrl: YOU_PHOTO })
    const img = hitGroup('you').querySelector('image')
    expect(img?.getAttribute('href')).toBe(YOU_PHOTO)
  })

  it('no photo, no overlay image — the painted YOU shows', () => {
    renderScene()
    expect(hitGroup('you').querySelector('image')).toBeNull()
  })
})

describe('the painted scene itself', () => {
  it('plate, paint stack and the XII numeral are present', () => {
    renderScene()
    const sky = container.querySelector('svg.lsky-sky')
    expect(sky).not.toBeNull()
    const hrefs = Array.from(sky!.querySelectorAll('image')).map(
      (el) => el.getAttribute('href') ?? '',
    )
    expect(hrefs.some((h) => h.includes('plate'))).toBe(true)
    expect(hrefs.some((h) => h.includes('enso-sun'))).toBe(true)
    expect(hrefs.some((h) => h.includes('moon-face'))).toBe(true)
    const paint = container.querySelector('.lsky-paint')
    expect(paint).not.toBeNull()
    expect(paint!.querySelectorAll('img')).toHaveLength(5)
    expect(sky!.textContent).toContain('XII')
  })
})
