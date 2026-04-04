import { useCallback, useEffect, useMemo, useState } from 'react'
import type { PerspectiveAgent } from '../perspectives/types'
import { AvatarDisplay } from './AvatarDisplay'

const EMOJI_SUGGESTIONS = [
  '🧠',
  '💡',
  '🎯',
  '🔍',
  '⚖️',
  '🛡️',
  '🌱',
  '🔥',
  '⚡',
  '🎭',
  '🧭',
  '🌊',
  '🏔️',
  '🦁',
  '🦊',
  '🐉',
  '✨',
  '🌙',
  '☀️',
  '🌿',
  '💎',
  '🗺️',
  '🔮',
  '🎪',
  '🧩',
  '🪞',
  '🌀',
  '⚔️',
  '🕊️',
  '🎨',
] as const

export const AVATAR_SWATCHES: { label: string; value: string }[] = [
  { label: 'Surface', value: 'var(--color-surface-raised)' },
  { label: 'Accent', value: 'var(--color-accent)' },
  { label: 'Warm clay', value: '#8b7355' },
  { label: 'Terracotta', value: '#a65d3a' },
  { label: 'Moss', value: '#4a5d4a' },
  { label: 'Stone', value: '#5c5348' },
]

type Tab = 'emoji' | 'initials' | 'color'

function initialsFromName(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length >= 2) {
    return (parts[0]!.slice(0, 1) + parts[1]!.slice(0, 1)).toUpperCase().slice(0, 2)
  }
  const w = parts[0] ?? ''
  return w.slice(0, 2).toUpperCase() || 'A'
}

function normalizeHex(raw: string): string | null {
  const s = raw.trim()
  if (/^#[0-9a-fA-F]{6}$/.test(s)) return s.toLowerCase()
  if (/^#[0-9a-fA-F]{3}$/.test(s)) {
    const r = s[1]!
    const g = s[2]!
    const b = s[3]!
    return `#${r}${r}${g}${g}${b}${b}`.toLowerCase()
  }
  return null
}

function isSuggestedEmoji(s: string): boolean {
  return (EMOJI_SUGGESTIONS as readonly string[]).includes(s)
}

export function AvatarPicker({
  agentName,
  value,
  onChange,
}: {
  agentName: string
  value: PerspectiveAgent['avatar']
  onChange: (next: PerspectiveAgent['avatar'] | undefined) => void
}) {
  const [tab, setTab] = useState<Tab>(() => value?.kind ?? 'emoji')
  const [emojiCustom, setEmojiCustom] = useState('')
  const [initialsText, setInitialsText] = useState(() =>
    value?.kind === 'initials' ? value.value : initialsFromName(agentName),
  )
  const [initialsBg, setInitialsBg] = useState(
    () => (value?.kind === 'initials' && value.bg ? value.bg : AVATAR_SWATCHES[1]!.value),
  )
  const [colorHex, setColorHex] = useState(() =>
    value?.kind === 'color' && typeof value.value === 'string' && value.value.startsWith('#')
      ? value.value
      : '#8b7355',
  )

  useEffect(() => {
    if (value?.kind === 'emoji') {
      setTab('emoji')
      setEmojiCustom(
        value.value.length > 2 || !isSuggestedEmoji(value.value) ? value.value : '',
      )
    } else if (value?.kind === 'initials') {
      setTab('initials')
      setInitialsText(value.value)
      if (value.bg) setInitialsBg(value.bg)
    } else if (value?.kind === 'color') {
      setTab('color')
      if (typeof value.value === 'string' && value.value.startsWith('#')) {
        setColorHex(value.value)
      }
    } else {
      setTab('emoji')
      setEmojiCustom('')
      setInitialsText(initialsFromName(agentName))
    }
  }, [value, agentName])

  useEffect(() => {
    setInitialsText((prev) => {
      if (value?.kind === 'initials') return prev
      return initialsFromName(agentName)
    })
  }, [agentName, value?.kind])

  const previewAgent = useMemo((): PerspectiveAgent => {
    const base: PerspectiveAgent = {
      id: '__picker__',
      name: agentName || 'Actor',
      role: '',
      purpose: '',
      values: [],
      aversions: [],
      reasoningStyle: [],
      tone: '',
      domain: [],
      decisionRule: '',
      createdAt: '',
    }
    if (tab === 'emoji') {
      const v =
        emojiCustom.trim() ||
        (value?.kind === 'emoji' ? value.value : '') ||
        EMOJI_SUGGESTIONS[0]!
      return { ...base, avatar: { kind: 'emoji', value: v } }
    }
    if (tab === 'initials') {
      const v = initialsText.replace(/\s/g, '').slice(0, 2).toUpperCase() || initialsFromName(agentName)
      return { ...base, avatar: { kind: 'initials', value: v, bg: initialsBg } }
    }
    if (value?.kind === 'color' && typeof value.value === 'string' && value.value.startsWith('var(')) {
      return { ...base, avatar: { kind: 'color', value: value.value } }
    }
    const raw = colorHex.trim()
    if (raw.startsWith('var(')) {
      return { ...base, avatar: { kind: 'color', value: raw } }
    }
    const hex = normalizeHex(colorHex) ?? '#8b7355'
    return { ...base, avatar: { kind: 'color', value: hex } }
  }, [tab, emojiCustom, value, initialsText, initialsBg, colorHex, agentName])

  const commitInitials = useCallback(() => {
    const v = initialsText.replace(/\s/g, '').slice(0, 2).toUpperCase() || initialsFromName(agentName)
    onChange({ kind: 'initials', value: v, bg: initialsBg })
  }, [initialsText, initialsBg, agentName, onChange])

  const tabBtn = (t: Tab, label: string) => (
    <button
      key={t}
      type="button"
      onClick={() => setTab(t)}
      className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors ${
        tab === t
          ? 'bg-accent text-[color:var(--color-white-warm)]'
          : 'text-warm-white/55 hover:text-warm-white/85 hover:bg-surface-sunken'
      }`}
    >
      {label}
    </button>
  )

  const selectedColorMatches = (s: string) =>
    value?.kind === 'color' && value.value === s

  return (
    <div className="rounded-lg border border-[color:var(--color-border)] bg-surface-sunken/40 p-3 space-y-3">
      <div className="flex items-start gap-3">
        <AvatarDisplay agent={previewAgent} size="lg" />
        <div className="flex-1 min-w-0 space-y-2">
          <p className="text-[10px] uppercase tracking-wide text-warm-white/45">Logo / avatar</p>
          <div className="flex flex-wrap gap-1 p-0.5 rounded-lg bg-surface-raised/50 border border-[color:var(--color-border)]">
            {tabBtn('emoji', 'Emoji')}
            {tabBtn('initials', 'Initials')}
            {tabBtn('color', 'Color')}
          </div>
        </div>
      </div>

      {tab === 'emoji' && (
        <div className="space-y-2">
          <div className="grid grid-cols-10 gap-1 max-h-[7rem] overflow-y-auto pr-0.5">
            {EMOJI_SUGGESTIONS.map((e) => (
              <button
                key={e}
                type="button"
                className="h-7 w-7 flex items-center justify-center rounded-md text-base hover:bg-surface-raised border border-transparent hover:border-[color:var(--color-border)]"
                onClick={() => {
                  setEmojiCustom('')
                  onChange({ kind: 'emoji', value: e })
                }}
              >
                {e}
              </button>
            ))}
          </div>
          <label className="block text-[10px] text-warm-white/45 mb-0.5">Custom emoji</label>
          <div className="flex gap-2">
            <input
              type="text"
              value={emojiCustom}
              onChange={(e) => setEmojiCustom(e.target.value)}
              placeholder="Paste any emoji"
              className="flex-1 min-w-0 px-2 py-1.5 rounded-md bg-surface-sunken border border-[color:var(--color-border)] text-warm-white text-xs"
            />
            <button
              type="button"
              className="shrink-0 px-2 py-1.5 rounded-md bg-accent/90 text-[color:var(--color-white-warm)] text-xs font-medium hover:opacity-90"
              onClick={() => {
                const g = [...emojiCustom.trim()][0]
                if (g) onChange({ kind: 'emoji', value: g })
              }}
            >
              Apply
            </button>
          </div>
        </div>
      )}

      {tab === 'initials' && (
        <div className="space-y-2">
          <label className="block text-[10px] text-warm-white/45">Letters (1–2)</label>
          <input
            type="text"
            maxLength={2}
            value={initialsText}
            onChange={(e) => setInitialsText(e.target.value.toUpperCase())}
            onBlur={() => commitInitials()}
            className="w-16 px-2 py-1.5 rounded-md bg-surface-sunken border border-[color:var(--color-border)] text-warm-white text-sm text-center font-semibold tracking-wide"
          />
          <p className="text-[10px] text-warm-white/40">Background</p>
          <div className="flex flex-wrap gap-1.5">
            {AVATAR_SWATCHES.map((s) => (
              <button
                key={s.value}
                type="button"
                title={s.label}
                className={`h-7 w-7 rounded-full border-2 shrink-0 ${
                  initialsBg === s.value ? 'border-warm-white/80' : 'border-transparent'
                }`}
                style={{ background: s.value }}
                onClick={() => {
                  setInitialsBg(s.value)
                  const v =
                    initialsText.replace(/\s/g, '').slice(0, 2).toUpperCase() ||
                    initialsFromName(agentName)
                  onChange({ kind: 'initials', value: v, bg: s.value })
                }}
              />
            ))}
          </div>
        </div>
      )}

      {tab === 'color' && (
        <div className="space-y-2">
          <p className="text-[10px] text-warm-white/40">Presets</p>
          <div className="flex flex-wrap gap-1.5">
            {AVATAR_SWATCHES.map((s) => (
              <button
                key={s.value}
                type="button"
                title={s.label}
                className={`h-8 w-8 rounded-full border-2 shrink-0 ${
                  selectedColorMatches(s.value) ? 'border-warm-white/80' : 'border-transparent'
                }`}
                style={{ background: s.value }}
                onClick={() => {
                  onChange({ kind: 'color', value: s.value })
                  if (s.value.startsWith('#')) setColorHex(s.value)
                }}
              />
            ))}
          </div>
          <label className="block text-[10px] text-warm-white/45">Custom hex</label>
          <div className="flex gap-2">
            <input
              type="text"
              value={colorHex.startsWith('var(') ? '' : colorHex}
              onChange={(e) => setColorHex(e.target.value)}
              placeholder="#6b8f71"
              className="flex-1 min-w-0 px-2 py-1.5 rounded-md bg-surface-sunken border border-[color:var(--color-border)] text-warm-white text-xs font-mono"
            />
            <button
              type="button"
              className="shrink-0 px-2 py-1.5 rounded-md bg-accent/90 text-[color:var(--color-white-warm)] text-xs font-medium"
              onClick={() => {
                const h = normalizeHex(colorHex)
                if (h) onChange({ kind: 'color', value: h })
              }}
            >
              Apply
            </button>
          </div>
        </div>
      )}

      <div className="pt-1 border-t border-[color:var(--color-border)]">
        <button
          type="button"
          className="text-[10px] text-warm-white/45 hover:text-warm-white/70 underline-offset-2 hover:underline"
          onClick={() => onChange(undefined)}
        >
          Reset to automatic
        </button>
      </div>
    </div>
  )
}
