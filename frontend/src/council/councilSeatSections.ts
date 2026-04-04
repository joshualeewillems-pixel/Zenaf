import { stripAtriaSynthesisBlock } from './CouncilTranscript'
import { mandateIdFromCouncilSeatLabel, type MandateIdKey } from '../mandateSeatAccent'

/** Keep in sync with `CouncilTranscript` structural headers. */
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

function normalizeHeaderForLookup(trimmed: string): string {
  return trimmed
    .replace(/\*+/g, '')
    .replace(/^#+\s*/, '')
    .trim()
    .replace(/:\s*$/, '')
    .toLowerCase()
}

function isSeatHeaderLine(trimmed: string): boolean {
  if (!trimmed.endsWith(':') || trimmed.length <= 1) return false
  if (trimmed.toLowerCase().startsWith('atria synthesis')) return false
  const blockedStarts = [
    'Position:',
    'Primary reason:',
    'Main risk:',
    'Required guardrail:',
    'Next step:',
  ]
  if (blockedStarts.some((p) => trimmed.startsWith(p))) return false
  return true
}

export type CouncilSeatSectionParsed = {
  mandateId: MandateIdKey
  headerLine: string
  bodyLines: string[]
}

export function parseCouncilSeatSections(
  text: string,
  stripSynthesis: boolean,
): { preambleLines: string[]; sections: CouncilSeatSectionParsed[] } {
  const source = stripSynthesis ? stripAtriaSynthesisBlock(text) : text
  const lines = source.split('\n')
  const preambleLines: string[] = []
  const sections: CouncilSeatSectionParsed[] = []
  let i = 0

  while (i < lines.length) {
    const trimmed = lines[i].trim()
    if (isSeatHeaderLine(trimmed)) {
      const lookup = normalizeHeaderForLookup(trimmed)
      if (!COUNCIL_STRUCTURAL_HEADERS.has(lookup)) {
        const mandateId = mandateIdFromCouncilSeatLabel(trimmed)
        if (mandateId) {
          const bodyStart = i + 1
          let j = bodyStart
          while (j < lines.length) {
            const t2 = lines[j].trim()
            if (isSeatHeaderLine(t2)) {
              const lk = normalizeHeaderForLookup(t2)
              if (!COUNCIL_STRUCTURAL_HEADERS.has(lk) && mandateIdFromCouncilSeatLabel(t2)) {
                break
              }
            }
            j++
          }
          sections.push({
            mandateId,
            headerLine: trimmed,
            bodyLines: lines.slice(bodyStart, j),
          })
          i = j
          continue
        }
      }
    }
    preambleLines.push(lines[i])
    i++
  }

  return { preambleLines, sections }
}
