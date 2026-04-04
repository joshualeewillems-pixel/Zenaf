import type { CSSProperties, SVGProps } from 'react'
import type { PerspectiveAgent } from './types'

export type PerspectiveIconId =
  | 'chess'
  | 'gear'
  | 'magnifier'
  | 'scales'
  | 'mask'
  | 'orb'
  | 'spiral'
  | 'map'
  | 'compass'

export const PERSPECTIVE_ICON_OPTIONS: Array<{ id: PerspectiveIconId; label: string; hint: string }> = [
  { id: 'chess', label: 'Chess piece', hint: 'Big picture — direction and leverage' },
  { id: 'gear', label: 'Gear', hint: 'Make it happen — sequencing and systems' },
  { id: 'magnifier', label: 'Magnifying glass', hint: "What's true — evidence and tradeoffs" },
  { id: 'scales', label: 'Scales', hint: 'What are the rules — constraints and guardrails' },
  { id: 'mask', label: 'Theatrical mask', hint: 'New angle — narrative and voice' },
  { id: 'orb', label: 'Orb network', hint: 'How it fits together — synthesis' },
  { id: 'spiral', label: 'Circle spiral', hint: 'Holistic view — patterns across the whole' },
  { id: 'map', label: 'Map', hint: 'Context — terrain and what matters here' },
  { id: 'compass', label: 'Compass', hint: 'Workflow — priorities and next moves' },
]

const DEFAULT_ICON_BY_AGENT_ID: Record<string, PerspectiveIconId> = {
  zenaf: 'spiral',
  thinking_partner: 'spiral',
  strategist: 'chess',
  operator: 'gear',
  analyst: 'magnifier',
  governance: 'scales',
  brand: 'mask',
  skeptic: 'compass',
}

function normalize(text: string): string {
  return text.trim().toLowerCase()
}

export function inferPerspectiveIcon(agent: PerspectiveAgent): PerspectiveIconId {
  if (agent.icon) return agent.icon
  const byId = DEFAULT_ICON_BY_AGENT_ID[normalize(agent.id)]
  if (byId) return byId
  const n = normalize(agent.name)
  const r = normalize(agent.role)
  const combo = `${n} ${r}`
  if (n.includes('thinking partner') || combo.includes('thinking partner')) return 'spiral'
  if (n.includes('big picture') || combo.includes('big picture')) return 'chess'
  if (n.includes('make it happen') || combo.includes('make it happen')) return 'gear'
  if (n.includes("what's true") || n.includes('whats true')) return 'magnifier'
  if (n.includes('what could go wrong') || combo.includes('what could go wrong')) return 'compass'
  if (n.includes('how it fits together') || combo.includes('how it fits together')) return 'orb'
  if (n.includes('new angle') || combo.includes('new angle')) return 'mask'
  if (n.includes('what are the rules') || combo.includes('what are the rules')) return 'scales'
  if (combo.includes('strateg')) return 'chess'
  if (combo.includes('operat') || combo.includes('execution')) return 'gear'
  if (combo.includes('analys') || combo.includes('data') || combo.includes('research')) return 'magnifier'
  if (combo.includes('govern') || combo.includes('compliance') || combo.includes('legal')) return 'scales'
  if (combo.includes('brand') || combo.includes('narrative') || combo.includes('marketing')) return 'mask'
  if (combo.includes('zenaf') || combo.includes('integrat') || combo.includes('synthes')) return 'orb'
  if (combo.includes('holistic') || combo.includes('systems')) return 'spiral'
  if (combo.includes('context')) return 'map'
  if (combo.includes('workflow')) return 'compass'
  return 'orb'
}

export function iconHintFor(agent: PerspectiveAgent): string {
  const id = inferPerspectiveIcon(agent)
  const entry = PERSPECTIVE_ICON_OPTIONS.find((x) => x.id === id)
  return entry?.hint ?? 'Actor icon'
}

export function PerspectiveRoleIcon({
  icon,
  className = '',
  style,
  'aria-hidden': ariaHidden = true,
  ...rest
}: {
  icon: PerspectiveIconId
  className?: string
  style?: CSSProperties
  'aria-hidden'?: boolean
} & Omit<SVGProps<SVGSVGElement>, 'className' | 'children' | 'viewBox' | 'fill' | 'stroke' | 'strokeWidth' | 'aria-hidden'>) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      style={style}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      aria-hidden={ariaHidden}
      {...rest}
    >
      {icon === 'chess' && (
        <>
          <path d="M8 20h8" />
          <path d="M9 17c0-2.3 1.2-3.8 3-5.2 1.8 1.4 3 2.9 3 5.2H9z" />
          <path d="M10 11c0-1.8 1.1-3 2-3s2 1.2 2 3" />
          <circle cx="12" cy="5.5" r="1.6" />
        </>
      )}
      {icon === 'gear' && (
        <>
          <circle cx="12" cy="12" r="3.1" />
          <path d="M12 3.3v2.2M12 18.5v2.2M3.3 12h2.2M18.5 12h2.2M5.8 5.8l1.6 1.6M16.6 16.6l1.6 1.6M18.2 5.8l-1.6 1.6M7.4 16.6l-1.6 1.6" />
        </>
      )}
      {icon === 'magnifier' && (
        <>
          <circle cx="10.5" cy="10.5" r="4.6" />
          <path d="M14 14l5 5" />
        </>
      )}
      {icon === 'scales' && (
        <>
          <path d="M12 4v14M7 20h10M6 8h12" />
          <path d="M8.2 8l-2.2 4h4.4l-2.2-4zM15.8 8l-2.2 4H18l-2.2-4z" />
        </>
      )}
      {icon === 'mask' && (
        <>
          <path d="M4.5 9.5C6.8 6.8 9.5 5.5 12 5.5s5.2 1.3 7.5 4c-.5 4.8-3.1 7.4-7.5 8-4.4-.6-7-3.2-7.5-8z" />
          <path d="M8.3 11.2c.6.4 1.3.4 1.9 0M13.8 11.2c.6.4 1.3.4 1.9 0" />
          <path d="M9 14.6c1.8 1 4.2 1 6 0" />
        </>
      )}
      {icon === 'orb' && (
        <>
          <circle cx="12" cy="12" r="4.1" />
          <circle cx="4.8" cy="12" r="1.6" />
          <circle cx="19.2" cy="12" r="1.6" />
          <circle cx="12" cy="4.8" r="1.6" />
          <circle cx="12" cy="19.2" r="1.6" />
          <path d="M6.4 12h3.5M14.1 12h3.5M12 6.4v3.5M12 14.1v3.5" />
        </>
      )}
      {icon === 'spiral' && (
        <>
          <path d="M12 20c4.4 0 8-3 8-6.8S16.7 6 12.7 6c-3.5 0-6.2 2.2-6.2 5.1 0 2.4 2 4.2 4.5 4.2 2.1 0 3.7-1.4 3.7-3.1 0-1.4-1.2-2.4-2.7-2.4" />
        </>
      )}
      {icon === 'map' && (
        <>
          <path d="M3.8 6.8l5.1-2v12.4l-5.1 2V6.8zM8.9 4.8l6.2 2.3v12.4l-6.2-2.3V4.8zM15.1 7.1l5.1-2v12.4l-5.1 2V7.1z" />
        </>
      )}
      {icon === 'compass' && (
        <>
          <circle cx="12" cy="12" r="7.5" />
          <path d="M15.8 8.2l-2.2 5.4-5.4 2.2 2.2-5.4 5.4-2.2z" />
        </>
      )}
    </svg>
  )
}

