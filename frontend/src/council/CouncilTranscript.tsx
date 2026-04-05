import type { ReactNode } from 'react'
import type { PerspectiveIconId } from '../perspectives/roleIcons'
import {
  EntityMentionText,
  councilRowHasLinkableEntityMarker,
  type EntityMentionOpenPayload,
} from '../components/EntityMentionText'
import { PerspectiveRoleIcon } from '../perspectives/roleIcons'
import {
  mandateIdFromCouncilSeatLabel,
  mandateOrbIconColor,
  type MandateIdKey,
} from '../mandateSeatAccent'

/** Section labels inside a seat body — not the seat “call name” line. */
const COUNCIL_STRUCTURAL_HEADERS = new Set(
  [
    'position',
    'primary reason',
    'main risk',
    'required guardrail',
    'next step',
    'next action',
    'response',
    'core move',
    'pushback',
    'candidates',
    'option a',
    'option b',
    'thread separation',
    'job',
    'anti-copy',
    'disagreement',
    'recommended action',
    'primary',
    'secondary',
    'required body shape',
    'weak grounding',
  ].map((s) => s.toLowerCase()),
)

export function stripAtriaSynthesisBlock(text: string): string {
  return text.replace(/\n?Atria synthesis:\s*[\s\S]*$/i, '').trimEnd()
}

function normalizeHeaderForLookup(trimmed: string): string {
  return trimmed
    .replace(/\*+/g, '')
    .replace(/^#+\s*/, '')
    .trim()
    .replace(/:\s*$/, '')
    .toLowerCase()
}

function iconForMandate(id: MandateIdKey): PerspectiveIconId {
  switch (id) {
    case 'thinking_partner':
      return 'spiral'
    case 'strategist':
      return 'chess'
    case 'operator':
      return 'gear'
    case 'analyst':
      return 'magnifier'
    case 'risk':
      return 'compass'
    case 'integrator':
      return 'orb'
    case 'creative':
      return 'mask'
    case 'governance':
      return 'scales'
    default:
      return 'orb'
  }
}

type CouncilTranscriptProps = {
  text: string
  /** When true (default), remove integrator synthesis block from display. */
  stripAtriaSynthesis?: boolean
  /** When true (default), color + icon for seat call lines (e.g. “Governance:”). */
  decorateSeatHeaders?: boolean
  /** When set, UUID / labeled entity mentions in body lines become chips that open a scoped sub-thread. */
  onOpenEntity?: (p: EntityMentionOpenPayload) => void
}

export function CouncilTranscript({
  text,
  stripAtriaSynthesis = true,
  decorateSeatHeaders = true,
  onOpenEntity,
}: CouncilTranscriptProps) {
  const source = stripAtriaSynthesis ? stripAtriaSynthesisBlock(text) : text
  const lines = source.split('\n')
  return (
    <div className="whitespace-pre-wrap font-sans text-xs">
      {lines.map((line, idx) => {
        const trimmed = line.trim()
        // Lines with [ID:…] must use EntityMentionText (cyan chips). A trailing ":" alone is a weak
        // header signal — Zenaf often writes "Here are the options:" plus numbered lines; some models
        // also end list rows with ":". Never treat these as seat headers.
        const hasEntityIdMarker = councilRowHasLinkableEntityMarker(line)
        const isNumberedListLine = /^\d+\.\s/.test(trimmed)
        const isHeader =
          !hasEntityIdMarker &&
          !isNumberedListLine &&
          trimmed.endsWith(':') &&
          trimmed.length > 1 &&
          !trimmed.toLowerCase().startsWith('atria synthesis') &&
          !trimmed.startsWith('Position:') &&
          !trimmed.startsWith('Primary reason:') &&
          !trimmed.startsWith('Main risk:') &&
          !trimmed.startsWith('Required guardrail:') &&
          !trimmed.startsWith('Next step:')

        if (!isHeader) {
          const body: ReactNode = onOpenEntity ? (
            <EntityMentionText
              text={line}
              onOpenEntity={onOpenEntity}
              className="text-stone-200 whitespace-pre-wrap"
            />
          ) : (
            line
          )
          return (
            <div key={idx} className="text-stone-200 whitespace-pre-wrap">
              {body}
            </div>
          )
        }

        const lookup = normalizeHeaderForLookup(trimmed)
        if (COUNCIL_STRUCTURAL_HEADERS.has(lookup)) {
          return (
            <div key={idx}>
              <span className="font-semibold text-stone-400">{trimmed}</span>
            </div>
          )
        }

        const mandateId = decorateSeatHeaders ? mandateIdFromCouncilSeatLabel(trimmed) : null
        const color = mandateId ? mandateOrbIconColor(mandateId) : undefined
        const icon = mandateId ? iconForMandate(mandateId) : null

        if (decorateSeatHeaders && mandateId && icon && color) {
          return (
            <div key={idx} className="flex items-center gap-1.5 min-h-[1.25rem]">
              <PerspectiveRoleIcon icon={icon} className="h-3.5 w-3.5 shrink-0" style={{ color }} aria-hidden />
              <span className="font-semibold" style={{ color }}>
                {trimmed}
              </span>
            </div>
          )
        }

        return (
          <div key={idx}>
            <span className="font-semibold text-amber-200/90">{trimmed}</span>
          </div>
        )
      })}
    </div>
  )
}
