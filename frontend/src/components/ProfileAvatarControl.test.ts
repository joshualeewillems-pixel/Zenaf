// @vitest-environment jsdom
/**
 * Header profile picture → YOU sheet (founder, 2026-11-24: "I should
 * be able to log out clicking on my picture also"). The picture's
 * menu gains "You — account & sign out" as its first item when the
 * shell passes onOpenYou; choosing it fires the callback (App routes
 * home and asks the tree to open the YOU sheet, where Log in / out
 * lives) and closes the menu. The photo items stay untouched.
 *
 * No JSX (vitest includes *.test.ts only): createElement throughout.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import { ProfileAvatarControl } from './ProfileAvatarControl'
import type { CurrentUser } from '../auth/session'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const USER: CurrentUser = {
  id: 'user-1',
  email: 'owner@local.zenaf',
  display_name: 'Owner',
  avatar_data_url: null,
}

let container: HTMLDivElement
let root: Root
let onOpenYou: ReturnType<typeof vi.fn>
let onUserUpdated: ReturnType<typeof vi.fn>

function buttonByText(text: string): HTMLButtonElement | undefined {
  return Array.from(container.querySelectorAll('button')).find((b) =>
    b.textContent?.includes(text),
  ) as HTMLButtonElement | undefined
}

async function click(el: Element) {
  await act(async () => {
    ;(el as HTMLElement).click()
  })
}

beforeEach(() => {
  onOpenYou = vi.fn()
  onUserUpdated = vi.fn()
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
})

describe('ProfileAvatarControl', () => {
  it('clicking the picture opens a menu whose You item fires onOpenYou and closes the menu', async () => {
    act(() => {
      root.render(
        React.createElement(ProfileAvatarControl, { user: USER, onUserUpdated, onOpenYou }),
      )
    })

    const picture = container.querySelector('button[title="Profile photo — click to change"]')
    expect(picture).toBeTruthy()
    expect(buttonByText('You — account & sign out')).toBeUndefined()

    await click(picture as Element)
    const youItem = buttonByText('You — account & sign out')
    expect(youItem).toBeTruthy()
    // The photo behaviour is still there, below the account item.
    expect(buttonByText('Upload photo…')).toBeTruthy()
    expect(onOpenYou).not.toHaveBeenCalled()

    await click(youItem as Element)
    expect(onOpenYou).toHaveBeenCalledTimes(1)
    expect(buttonByText('You — account & sign out')).toBeUndefined()
  })

  it('without onOpenYou the menu keeps its photo-only behaviour', async () => {
    act(() => {
      root.render(React.createElement(ProfileAvatarControl, { user: USER, onUserUpdated }))
    })
    const picture = container.querySelector('button[title="Profile photo — click to change"]')
    await click(picture as Element)
    expect(buttonByText('You — account & sign out')).toBeUndefined()
    expect(buttonByText('Upload photo…')).toBeTruthy()
  })
})
