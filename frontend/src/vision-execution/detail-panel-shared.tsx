/**
 * Shared components for Vision Execution detail panels: sections, multi-selects, metadata, confirm modal.
 */

import { useState } from 'react'

const inputBase = 'w-full px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-sm'
const inputTextarea = inputBase + ' resize-y'

export function DetailSection({
  title,
  children,
  defaultOpen = true,
}: {
  title: string
  children: React.ReactNode
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border-b border-slate-700 last:border-0">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between py-2 text-left text-xs font-medium text-slate-400 uppercase tracking-wide hover:text-slate-200"
      >
        {title}
        <span className="text-slate-500">{open ? '▼' : '▶'}</span>
      </button>
      {open && <div className="pb-3 space-y-2">{children}</div>}
    </div>
  )
}

export function DetailField({
  label,
  value,
  onChange,
  textarea = false,
  rows = 2,
  type = 'text',
  options,
  placeholder,
  readOnly = false,
}: {
  label: string
  value: string | number
  onChange: (v: string) => void
  textarea?: boolean
  rows?: number
  type?: 'text' | 'number'
  options?: { value: string; label: string }[]
  placeholder?: string
  readOnly?: boolean
}) {
  const id = `field-${label.replace(/\s/g, '-')}`
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-xs font-medium text-slate-400">
        {label}
      </label>
      {options ? (
        <select
          id={id}
          value={String(value ?? '')}
          onChange={(e) => !readOnly && onChange(e.target.value)}
          className={inputBase + (readOnly ? ' opacity-75 pointer-events-none' : '')}
          disabled={readOnly}
        >
          <option value="">{placeholder ?? 'None'}</option>
          {options.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      ) : textarea ? (
        <textarea
          id={id}
          value={value ?? ''}
          onChange={(e) => !readOnly && onChange(e.target.value)}
          rows={rows}
          className={inputTextarea + (readOnly ? ' opacity-75 cursor-not-allowed' : '')}
          placeholder={placeholder}
          readOnly={readOnly}
        />
      ) : (
        <input
          id={id}
          type={type}
          value={value ?? ''}
          onChange={(e) => !readOnly && onChange(e.target.value)}
          className={inputBase + (readOnly ? ' opacity-75 cursor-not-allowed' : '')}
          placeholder={placeholder}
          readOnly={readOnly}
        />
      )}
    </div>
  )
}

/** Multi-select for entity IDs: searchable dropdown that builds a list of selected IDs (chips). */
export function EntityMultiSelect<T extends { id: string }>({
  label,
  selectedIds,
  onChange,
  options,
  getLabel,
  placeholder = 'Search or select…',
}: {
  label: string
  selectedIds: string[]
  onChange: (ids: string[]) => void
  options: T[]
  getLabel: (item: T) => string
  placeholder?: string
}) {
  const [search, setSearch] = useState('')
  const [open, setOpen] = useState(false)
  const filtered = search.trim()
    ? options.filter((o) => getLabel(o).toLowerCase().includes(search.trim().toLowerCase())).slice(0, 15)
    : options.slice(0, 15)
  const add = (id: string) => {
    if (!selectedIds.includes(id)) onChange([...selectedIds, id])
    setOpen(false)
    setSearch('')
  }
  const remove = (id: string) => onChange(selectedIds.filter((x) => x !== id))
  return (
    <div className="space-y-1">
      <label className="block text-xs font-medium text-slate-400">{label}</label>
      <div className="flex flex-wrap gap-1.5 mb-1">
        {selectedIds.map((id) => {
          const item = options.find((o) => o.id === id)
          return (
            <span
              key={id}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-slate-700 text-slate-200 text-xs"
            >
              {item ? getLabel(item) : id}
              <button type="button" onClick={() => remove(id)} className="text-slate-400 hover:text-red-300">×</button>
            </span>
          )
        })}
      </div>
      <div className="relative">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          placeholder={placeholder}
          className={inputBase}
        />
        {open && filtered.length > 0 && (
          <ul className="absolute z-10 mt-0.5 w-full max-h-40 overflow-y-auto rounded bg-slate-800 border border-slate-600 shadow-lg py-1">
            {filtered.map((o) => (
              <li key={o.id}>
                <button
                  type="button"
                  onMouseDown={(e) => { e.preventDefault(); add(o.id) }}
                  className="w-full text-left px-2 py-1.5 text-sm text-slate-200 hover:bg-slate-700"
                >
                  {getLabel(o)}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

/** Collapsible metadata / debug section for raw IDs and timestamps. */
export function MetadataSection({ data }: { data: Record<string, unknown> }) {
  const [open, setOpen] = useState(false)
  const keys = Object.keys(data).filter((k) => ['id', 'created_at', 'updated_at', 'created_by', 'user_id'].includes(k) || k.endsWith('_id') && typeof data[k] === 'string')
  if (keys.length === 0) return null
  return (
    <div className="border-t border-slate-700 mt-2 pt-2">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="text-xs text-slate-500 hover:text-slate-400"
      >
        {open ? '▼' : '▶'} Metadata / debug
      </button>
      {open && (
        <pre className="mt-1 text-xs text-slate-500 overflow-x-auto whitespace-pre-wrap break-all">
          {keys.map((k) => `${k}: ${JSON.stringify(data[k])}`).join('\n')}
        </pre>
      )}
    </div>
  )
}

export function ConfirmModal({
  title,
  message,
  confirmLabel,
  variant = 'danger',
  onConfirm,
  onCancel,
}: {
  title: string
  message: string
  confirmLabel: string
  variant?: 'danger' | 'warning'
  onConfirm: () => void
  onCancel: () => void
}) {
  const btnClass = variant === 'danger'
    ? 'bg-red-600 hover:bg-red-500 text-white'
    : 'bg-amber-600 hover:bg-amber-500 text-white'
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onCancel}>
      <div
        className="rounded-xl border border-slate-600 bg-slate-800 p-4 max-w-sm shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h4 className="text-sm font-medium text-slate-200 mb-1">{title}</h4>
        <p className="text-xs text-slate-400 mb-4">{message}</p>
        <div className="flex gap-2 justify-end">
          <button type="button" onClick={onCancel} className="px-3 py-1.5 rounded-lg bg-slate-600 text-slate-200 text-sm">
            Cancel
          </button>
          <button type="button" onClick={onConfirm} className={`px-3 py-1.5 rounded-lg text-sm ${btnClass}`}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

/** 1–5 slider with label. */
export function Slider1To5({
  label,
  value,
  onChange,
  readOnly = false,
  hint,
}: {
  label: string
  value: number | null
  onChange: (v: number | null) => void
  /** When true, value is display-only (e.g. evaluation-derived scores). */
  readOnly?: boolean
  /** Optional line below the slider (e.g. override vs model). */
  hint?: string
}) {
  const n = value == null ? 0 : Math.max(0, Math.min(5, Math.round(Number(value))))
  return (
    <div className="space-y-1">
      <label className="block text-xs font-medium text-slate-400">{label}</label>
      <div className="flex items-center gap-2">
        <input
          type="range"
          min={0}
          max={5}
          step={1}
          value={n}
          disabled={readOnly}
          onChange={(e) => onChange(Number(e.target.value) || null)}
          className={`flex-1 h-2 rounded bg-slate-700 accent-amber-500 ${readOnly ? 'opacity-60 cursor-not-allowed' : ''}`}
        />
        <span className="text-slate-300 text-sm w-5">{n}</span>
      </div>
      {hint ? <p className="text-[10px] text-slate-500 leading-snug">{hint}</p> : null}
    </div>
  )
}
