// @vitest-environment jsdom
/**
 * Accordion — the Settings page's single-open section accordion.
 * Covers: a header button per item, exactly one item expanded on
 * first render (the first item), and toggle behavior (opening one
 * item closes the previous; tapping the open header collapses it).
 * No JSX (vitest includes *.test.ts only): createElement throughout.
 */
import { describe, it, expect, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import { Accordion, type AccordionItemSpec } from './Accordion'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLDivElement
let root: Root

const ITEMS: AccordionItemSpec[] = [
  { id: 'one', title: 'First section', content: React.createElement('p', null, 'Body one') },
  { id: 'two', title: 'Second section', content: React.createElement('p', null, 'Body two') },
  { id: 'three', title: 'Third section', content: React.createElement('p', null, 'Body three') },
]

function renderAccordion(props: { defaultOpenId?: string } = {}) {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => {
    root.render(React.createElement(Accordion, { items: ITEMS, ...props }))
  })
}

function headerButtons(): HTMLButtonElement[] {
  return Array.from(container.querySelectorAll('button'))
}

function headerFor(title: string): HTMLButtonElement {
  const button = headerButtons().find((b) => b.textContent?.includes(title))
  if (!button) throw new Error(`Header missing: ${title}`)
  return button
}

afterEach(() => {
  act(() => root.unmount())
  container.remove()
})

describe('Accordion', () => {
  it('renders a header button for every item', () => {
    renderAccordion()
    expect(headerButtons()).toHaveLength(3)
    expect(headerFor('First section')).toBeTruthy()
    expect(headerFor('Second section')).toBeTruthy()
    expect(headerFor('Third section')).toBeTruthy()
  })

  it('expands exactly the first item on load; collapsed bodies are unmounted', () => {
    renderAccordion()
    expect(headerFor('First section').getAttribute('aria-expanded')).toBe('true')
    expect(headerFor('Second section').getAttribute('aria-expanded')).toBe('false')
    expect(headerFor('Third section').getAttribute('aria-expanded')).toBe('false')
    expect(container.textContent).toContain('Body one')
    expect(container.textContent).not.toContain('Body two')
    expect(container.textContent).not.toContain('Body three')
  })

  it('honors defaultOpenId over the first item', () => {
    renderAccordion({ defaultOpenId: 'two' })
    expect(headerFor('Second section').getAttribute('aria-expanded')).toBe('true')
    expect(container.textContent).toContain('Body two')
    expect(container.textContent).not.toContain('Body one')
  })

  it('is single-open: opening another item closes the previous one', () => {
    renderAccordion()
    act(() => {
      headerFor('Third section').click()
    })
    expect(headerFor('Third section').getAttribute('aria-expanded')).toBe('true')
    expect(headerFor('First section').getAttribute('aria-expanded')).toBe('false')
    expect(container.textContent).toContain('Body three')
    expect(container.textContent).not.toContain('Body one')
  })

  it('tapping the open header collapses it, leaving none open', () => {
    renderAccordion()
    act(() => {
      headerFor('First section').click()
    })
    expect(headerFor('First section').getAttribute('aria-expanded')).toBe('false')
    expect(container.textContent).not.toContain('Body one')
  })
})
