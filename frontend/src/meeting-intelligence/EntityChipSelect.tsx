/**
 * Searchable multi-select with chips: click to add/remove, no Ctrl/Cmd required.
 * Used for People and Assets assignment on review cards.
 */

import { useState, useMemo } from 'react'

export interface EntityOption {
  id: string
  name: string
}

export interface EntityChipSelectProps {
  label: string
  options: EntityOption[]
  selectedIds: string[]
  onChange: (ids: string[]) => void
  placeholder?: string
  maxHeight?: string
}

export function EntityChipSelect({
  label,
  options,
  selectedIds,
  onChange,
  placeholder = 'Search…',
  maxHeight = '10rem',
}: EntityChipSelectProps) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)

  const selected = useMemo(
    () => options.filter((o) => selectedIds.includes(o.id)),
    [options, selectedIds]
  )
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return options.slice(0, 30)
    return options.filter((o) => o.name.toLowerCase().includes(q)).slice(0, 30)
  }, [options, query])

  const add = (id: string) => {
    if (!selectedIds.includes(id)) onChange([...selectedIds, id])
    setQuery('')
    setOpen(false)
  }
  const remove = (id: string) => {
    onChange(selectedIds.filter((x) => x !== id))
  }

  return (
    <div className="space-y-1">
      <label className="text-slate-500 block text-xs font-medium">{label}</label>
      <div className="flex flex-wrap gap-1.5 mb-1">
        {selected.map((o) => (
          <span
            key={o.id}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-slate-700 text-slate-200 text-xs border border-slate-600"
          >
            <span className="truncate max-w-[120px]" title={o.name}>{o.name}</span>
            <button
              type="button"
              onClick={() => remove(o.id)}
              className="text-slate-400 hover:text-red-300 shrink-0"
              aria-label={`Remove ${o.name}`}
            >
              ×
            </button>
          </span>
        ))}
      </div>
      <div className="relative">
        <input
          type="text"
          value={query}
          onChange={(e) => { setQuery(e.target.value); setOpen(true) }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          placeholder={placeholder}
          className="w-full px-2 py-1 rounded bg-slate-900 border border-slate-600 text-slate-100 text-sm"
        />
        {open && filtered.length > 0 && (
          <ul
            className="absolute z-10 left-0 right-0 mt-0.5 py-1 rounded border border-slate-600 bg-slate-800 shadow-lg overflow-y-auto"
            style={{ maxHeight }}
          >
            {filtered.map((o) => (
              <li key={o.id}>
                <button
                  type="button"
                  onMouseDown={(e) => { e.preventDefault(); add(o.id) }}
                  className={`w-full text-left px-2 py-1.5 text-sm truncate ${
                    selectedIds.includes(o.id) ? 'text-emerald-400 bg-slate-700/50' : 'text-slate-200 hover:bg-slate-700'
                  }`}
                  title={o.name}
                >
                  {o.name}
                  {selectedIds.includes(o.id) ? ' ✓' : ''}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
