import type { CSSProperties } from 'react'
import type { PerspectiveAgent } from '../perspectives/types'
import { isUserDefined } from '../perspectives/types'
import { inferPerspectiveIcon, PerspectiveRoleIcon } from '../perspectives/roleIcons'

export type AvatarDisplaySize = 'sm' | 'md' | 'lg'

const SIZE_PX: Record<AvatarDisplaySize, number> = {
  sm: 24,
  md: 36,
  lg: 48,
}

function initialsFromName(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length >= 2) {
    return (parts[0]!.slice(0, 1) + parts[1]!.slice(0, 1)).toUpperCase().slice(0, 2)
  }
  const w = parts[0] ?? '?'
  return w.slice(0, 2).toUpperCase() || '?'
}

function isLikelyHexColor(s: string): boolean {
  return /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(s.trim())
}

export function AvatarDisplay({
  agent,
  size = 'sm',
  className = '',
  title,
  style,
}: {
  agent: PerspectiveAgent
  size?: AvatarDisplaySize
  className?: string
  title?: string
  style?: CSSProperties
}) {
  const px = SIZE_PX[size]
  const base: CSSProperties = {
    width: px,
    height: px,
    borderRadius: '9999px',
    flexShrink: 0,
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
    boxSizing: 'border-box',
    ...style,
  }

  const av = agent.avatar
  const tip = title ?? agent.name

  if (av?.kind === 'emoji' && av.value) {
    const glyph = [...av.value.trim()][0] ?? av.value
    const bg = av.bg?.trim() || 'var(--color-surface-raised, #3d3a36)'
    return (
      <span
        className={`border border-[color:var(--color-border)] ${className}`}
        style={{ ...base, background: bg, fontSize: px * 0.55, lineHeight: 1 }}
        title={tip}
        aria-hidden={!tip}
      >
        {glyph}
      </span>
    )
  }

  if (av?.kind === 'initials') {
    const letters = (av.value || initialsFromName(agent.name)).slice(0, 2).toUpperCase() || '?'
    const bg = av.bg?.trim() || 'var(--color-accent, #6b8f71)'
    return (
      <span
        className={`border border-[color:var(--color-border)] font-semibold text-[color:var(--color-white-warm,#f5f2eb)] ${className}`}
        style={{ ...base, background: bg, fontSize: px * 0.38, lineHeight: 1 }}
        title={tip}
      >
        {letters}
      </span>
    )
  }

  if (av?.kind === 'color' && av.value) {
    const cv = av.value.trim()
    if (isLikelyHexColor(cv) || cv.startsWith('var(')) {
      return (
        <span
          className={`border border-[color:var(--color-border)] ${className}`}
          style={{ ...base, background: cv }}
          title={tip}
          aria-hidden
        />
      )
    }
  }

  if (isUserDefined(agent)) {
    const letters = initialsFromName(agent.name)
    return (
      <span
        className={`border border-[color:var(--color-border)] font-semibold text-[color:var(--color-white-warm,#f5f2eb)] ${className}`}
        style={{
          ...base,
          background: 'var(--color-accent, #6b8f71)',
          fontSize: px * 0.38,
          lineHeight: 1,
        }}
        title={tip}
      >
        {letters}
      </span>
    )
  }

  const icon = inferPerspectiveIcon(agent)
  const iconPx = Math.round(px * 0.52)
  return (
    <span
      className={`border border-[color:var(--color-border)] bg-[color:var(--color-surface-sunken,#2a2826)] text-warm-white/90 ${className}`}
      style={base}
      title={tip}
    >
      <PerspectiveRoleIcon icon={icon} className="shrink-0" style={{ width: iconPx, height: iconPx }} />
    </span>
  )
}
