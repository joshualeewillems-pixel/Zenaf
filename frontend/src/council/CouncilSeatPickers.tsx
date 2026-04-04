import { useEffect, useRef, useState } from 'react'
import type { Mandate } from '../mandates'
import type { PerspectiveAgent } from '../perspectives/types'
import { AvatarDisplay } from '../components/AvatarDisplay'
import { mandateSwatchStyle } from '../mandateSeatAccent'

function useCloseOnOutsideClick(open: boolean, onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose
  useEffect(() => {
    if (!open) return
    const fn = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) onCloseRef.current()
    }
    document.addEventListener('mousedown', fn)
    return () => document.removeEventListener('mousedown', fn)
  }, [open])
  return ref
}

function Swatch({ mandateId }: { mandateId: string | null }) {
  return (
    <span
      className="inline-block h-3.5 w-3.5 shrink-0 rounded-full"
      style={mandateSwatchStyle(mandateId)}
      aria-hidden
    />
  )
}

export function CouncilMandatePicker({
  value,
  onChange,
  mandates,
  idPrefix,
}: {
  value: string
  onChange: (mandateId: string) => void
  mandates: Mandate[]
  idPrefix: string
}) {
  const [open, setOpen] = useState(false)
  const ref = useCloseOnOutsideClick(open, () => setOpen(false))
  const selected = value ? mandates.find((m) => m.id === value) : undefined
  const label = selected?.name ?? 'Role…'

  return (
    <div ref={ref} className="relative min-w-0 flex-1">
      <button
        type="button"
        id={`${idPrefix}-mandate-trigger`}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={`${idPrefix}-mandate-list`}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 rounded-lg border border-stone-600 bg-stone-900 px-2 py-1.5 text-left text-[11px] text-stone-100 hover:border-stone-500 focus:outline-none focus:ring-1 focus:ring-stone-500"
      >
        <Swatch mandateId={value || null} />
        <span className="min-w-0 flex-1 truncate">{label}</span>
        <span className="text-stone-500" aria-hidden>
          ▾
        </span>
      </button>
      {open && (
        <ul
          id={`${idPrefix}-mandate-list`}
          role="listbox"
          aria-labelledby={`${idPrefix}-mandate-trigger`}
          className="absolute left-0 right-0 top-full z-50 mt-1 max-h-48 overflow-auto rounded-lg border border-stone-600 bg-stone-900 py-1 shadow-lg"
        >
          <li role="option" className="px-0">
            <button
              type="button"
              className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-[11px] text-stone-300 hover:bg-stone-800"
              onClick={() => {
                onChange('')
                setOpen(false)
              }}
            >
              <Swatch mandateId={null} />
              <span>Role…</span>
            </button>
          </li>
          {mandates.map((m) => (
            <li key={m.id} role="option" className="px-0">
              <button
                type="button"
                className={`flex w-full items-center gap-2 px-2 py-1.5 text-left text-[11px] hover:bg-stone-800 ${
                  value === m.id ? 'bg-stone-800/80 text-stone-100' : 'text-stone-300'
                }`}
                onClick={() => {
                  onChange(m.id)
                  setOpen(false)
                }}
              >
                <Swatch mandateId={m.id} />
                <span className="min-w-0 flex-1 truncate">{m.name}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function CouncilPerspectivePicker({
  value,
  onChange,
  agents,
  idPrefix,
}: {
  value: string | null
  onChange: (perspectiveId: string | null) => void
  agents: PerspectiveAgent[]
  idPrefix: string
}) {
  const [open, setOpen] = useState(false)
  const ref = useCloseOnOutsideClick(open, () => setOpen(false))
  const selected = value ? agents.find((a) => a.id === value) : undefined

  return (
    <div ref={ref} className="relative w-full">
      <button
        type="button"
        id={`${idPrefix}-perspective-trigger`}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={`${idPrefix}-perspective-list`}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 rounded-lg border border-stone-500 bg-stone-900 px-3 py-2 text-left text-sm font-semibold text-stone-100 hover:border-stone-400 focus:outline-none focus:ring-1 focus:ring-stone-500"
      >
        {selected ? (
          <AvatarDisplay agent={selected} size="sm" className="shrink-0 text-stone-200" />
        ) : (
          <span className="flex h-4 w-4 shrink-0 items-center justify-center text-stone-500" aria-hidden>
            —
          </span>
        )}
        <span className="min-w-0 flex-1 truncate">{selected ? selected.name : '— Empty —'}</span>
        <span className="text-stone-500" aria-hidden>
          ▾
        </span>
      </button>
      {open && (
        <ul
          id={`${idPrefix}-perspective-list`}
          role="listbox"
          aria-labelledby={`${idPrefix}-perspective-trigger`}
          className="absolute left-0 right-0 top-full z-50 mt-1 max-h-64 overflow-auto rounded-lg border border-stone-600 bg-stone-900 py-1.5 pb-3 shadow-lg [scrollbar-gutter:stable]"
        >
          <li role="option" className="px-0">
            <button
              type="button"
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-stone-300 hover:bg-stone-800"
              onClick={() => {
                onChange(null)
                setOpen(false)
              }}
            >
              <span className="flex h-4 w-4 shrink-0 items-center justify-center text-stone-500" aria-hidden>
                —
              </span>
              <span>— Empty —</span>
            </button>
          </li>
          {agents.map((a) => (
            <li key={a.id} role="option" className="px-0">
              <button
                type="button"
                className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-stone-800 ${
                  value === a.id ? 'bg-stone-800/80 text-stone-100' : 'text-stone-300'
                }`}
                onClick={() => {
                  onChange(a.id)
                  setOpen(false)
                }}
              >
                <AvatarDisplay agent={a} size="sm" className="shrink-0 text-stone-200" />
                <span className="min-w-0 flex-1 truncate">{a.name}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
