import type { CSSProperties } from 'react'

/**
 * Desaturated seat-role accents: ring + soft glow only (no full-node fills).
 * Maps `Mandate.id` from mandates.ts → calm material palette.
 */
const RGB = {
  thinking_partner: { r: 228, g: 226, b: 220 }, // Neutral / soft white (stone-200)
  strategist: { r: 105, g: 98, b: 128 }, // Strategy — muted indigo / violet
  operator: { r: 168, g: 93, b: 58 }, // Execution — burnt orange
  analyst: { r: 88, g: 118, b: 145 }, // Evidence — cool blue
  risk: { r: 154, g: 92, b: 86 }, // Risk — muted rust
  integrator: { r: 77, g: 128, b: 122 }, // Integration — teal
  creative: { r: 176, g: 148, b: 88 }, // Creativity — warm gold
  governance: { r: 72, g: 68, b: 78 }, // Governance — charcoal
} as const

export type MandateIdKey = keyof typeof RGB

export function isKnownMandateId(id: string): id is MandateIdKey {
  return id in RGB
}

/** Tailwind arbitrary ring + shadow for crown / seat icon wrapper. */
export function mandateSeatIconAccentClass(mandateId: string | null | undefined): string {
  if (!mandateId || !isKnownMandateId(mandateId)) {
    return 'ring-1 ring-stone-600/55 shadow-[inset_0_0_0_1px_rgba(120,113,105,0.12)]'
  }
  const { r, g, b } = RGB[mandateId]
  return `ring-2 ring-[rgba(${r},${g},${b},0.38)] shadow-[0_0_0_1px_rgba(${r},${g},${b},0.2),0_0_18px_rgba(${r},${g},${b},0.18)]`
}

/** Softer outer-only glow for council seat circle buttons (actor icon inside). */
export function mandateSeatOrbGlowClass(mandateId: string | null | undefined): string {
  if (!mandateId || !isKnownMandateId(mandateId)) return ''
  const { r, g, b } = RGB[mandateId]
  return `shadow-[0_0_14px_rgba(${r},${g},${b},0.2),0_0_0_1px_rgba(${r},${g},${b},0.22)]`
}

/** Inline style for small swatch circles (dropdown rows / trigger). */
export function mandateSwatchStyle(mandateId: string | null | undefined): CSSProperties {
  if (!mandateId || !isKnownMandateId(mandateId)) {
    return { backgroundColor: 'rgba(120, 113, 105, 0.35)', boxShadow: 'inset 0 0 0 1px rgba(255,255,255,0.06)' }
  }
  const { r, g, b } = RGB[mandateId]
  return {
    backgroundColor: `rgb(${r}, ${g}, ${b})`,
    boxShadow: `inset 0 0 0 1px rgba(255,255,255,0.06), 0 0 10px rgba(${r},${g},${b},0.25)`,
  }
}

/** Icon / stroke color for council seat orb (currentColor). Charcoal is lifted slightly for contrast on dark fills. */
export function mandateOrbIconColor(mandateId: string | null | undefined): string | undefined {
  if (!mandateId || !isKnownMandateId(mandateId)) return undefined
  const { r, g, b } = RGB[mandateId]
  if (mandateId === 'governance') {
    const lift = (x: number) => Math.round(x + (255 - x) * 0.36)
    return `rgb(${lift(r)}, ${lift(g)}, ${lift(b)})`
  }
  return `rgb(${r}, ${g}, ${b})`
}

/** Circle outline on council seat orb — matches role, calm opacity. */
export function mandateOrbBorderColor(mandateId: string | null | undefined): string | undefined {
  if (!mandateId || !isKnownMandateId(mandateId)) return undefined
  const { r, g, b } = RGB[mandateId]
  return `rgba(${r}, ${g}, ${b}, 0.58)`
}

/** Border + icon color for seat orb when a mandate is selected (neutral fill unchanged). */
export function mandateOrbStrokeStyle(mandateId: string | null | undefined): CSSProperties | undefined {
  const border = mandateOrbBorderColor(mandateId)
  const color = mandateOrbIconColor(mandateId)
  if (!border || !color) return undefined
  return { borderColor: border, color }
}

/**
 * Map council streaming first-line labels (persona name, “The Context Analyst”, built-in seats, etc.)
 * to canonical mandate ids for shared palette + icons.
 */
export function mandateIdFromCouncilSeatLabel(raw: string): MandateIdKey | null {
  const n = raw
    .replace(/\*+/g, '')
    .replace(/^#+\s*/, '')
    .trim()
    .toLowerCase()
    .replace(/:\s*$/, '')
  if (!n || n.startsWith('zenaf synthesis')) return null
  if (/thinking partner/.test(n)) return 'thinking_partner'
  if (/govern|what are the rules|compliance|legal|risk guardrail/.test(n)) return 'governance'
  if (/operator|execution|make it happen|\bcoo\b/.test(n)) return 'operator'
  if (/analyst|evidence|what'?s true|context analyst|research|data science/.test(n)) return 'analyst'
  if (/strateg|big picture|founder|\bceo\b/.test(n)) return 'strategist'
  if (/brand|new angle|narrative|marketing|creative/.test(n)) return 'creative'
  if (/integrat|holistic practitioner|zenaf(?!\s+synthesis)|how it fits|chief of staff|synthes/.test(n))
    return 'integrator'
  if (/risk|what could go wrong|skeptic/.test(n)) return 'risk'
  if (
    n === 'governance' ||
    n === 'operator' ||
    n === 'analyst' ||
    n === 'strategist' ||
    n === 'brand' ||
    n === 'thinking_partner'
  )
    return n === 'brand' ? 'creative' : (n as MandateIdKey)
  return null
}
