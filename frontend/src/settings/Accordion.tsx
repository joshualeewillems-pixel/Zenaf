import { useState, type ReactNode } from 'react'

/**
 * Settings accordion — one section per item, single-open.
 *
 * Follows the app's existing accordion approach (the YOU directory in
 * living-tree/LivingTree.tsx): a single piece of state holds the one
 * open item's id, headers are real buttons carrying aria-expanded, the
 * chevron is a text glyph ('‹' open / '›' closed), and a collapsed
 * item's body is unmounted rather than hidden.
 *
 * Chrome is expressed in the Settings page's own Tailwind/slate
 * language. The body strips the wrapped section's own card frame
 * (border + radius) via a child selector so the section does not draw
 * a second card inside the accordion's frame; the section component
 * itself — its content, background, padding, and behavior — is
 * untouched.
 */

export type AccordionItemSpec = {
  id: string
  title: string
  content: ReactNode
}

type AccordionProps = {
  items: AccordionItemSpec[]
  /** Item expanded on first render. Defaults to the first item. */
  defaultOpenId?: string
}

export function Accordion({ items, defaultOpenId }: AccordionProps) {
  const [openId, setOpenId] = useState<string | null>(
    () => defaultOpenId ?? items[0]?.id ?? null,
  )
  const toggle = (id: string) =>
    setOpenId((current) => (current === id ? null : id))
  return (
    <div className="space-y-4">
      {items.map((item) => (
        <AccordionItem
          key={item.id}
          id={item.id}
          title={item.title}
          open={openId === item.id}
          onToggle={toggle}
        >
          {item.content}
        </AccordionItem>
      ))}
    </div>
  )
}

type AccordionItemProps = {
  id: string
  title: string
  open: boolean
  onToggle: (id: string) => void
  children: ReactNode
}

export function AccordionItem({ id, title, open, onToggle, children }: AccordionItemProps) {
  const headerId = `accordion-header-${id}`
  const bodyId = `accordion-body-${id}`
  return (
    <div className="border border-slate-700 rounded-lg overflow-hidden">
      <button
        type="button"
        id={headerId}
        className="flex w-full items-center justify-between px-4 py-3 text-left"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={() => onToggle(id)}
      >
        <span className="text-lg font-semibold text-slate-100">{title}</span>
        <span aria-hidden="true" className="text-slate-400">
          {open ? '‹' : '›'}
        </span>
      </button>
      {open && (
        <div
          id={bodyId}
          role="region"
          aria-labelledby={headerId}
          className="border-t border-slate-700 [&>section]:border-0 [&>section]:rounded-none"
        >
          {children}
        </div>
      )}
    </div>
  )
}
