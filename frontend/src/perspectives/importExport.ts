/**
 * Import/Export helpers for perspective definitions (plain-text, LLM-friendly).
 * Used by the Perspective Agent Creator form.
 */

import type { PerspectiveAgent } from './types'

/** Form state for export: current field values (strings; arrays as comma-separated). */
export type PerspectiveFormState = {
  name: string
  role: string
  purpose: string
  valuesText: string
  aversionsText: string
  reasoningText: string
  tone: string
  domainText: string
  decisionRule: string
  context: string
  worldview?: string
  constraintsText?: string
  examplePhrasesText?: string
  promptNotes?: string
}

const EXPORT_LABELS = {
  name: 'Name',
  role: 'Role / Perspective Type',
  purpose: 'Core Purpose',
  values: 'Top Values',
  aversions: 'What it avoids',
  reasoningStyle: 'Reasoning Style',
  tone: 'Tone of Voice',
  domain: 'Domain / Use Case',
  decisionRule: 'Decision Rule',
  context: 'Context / Reference Material',
  worldview: 'Worldview notes',
  constraints: 'Constraints / boundaries',
  examplePhrases: 'Example phrases',
  promptNotes: 'Custom prompt notes',
} as const

/** Build form state from a PerspectiveAgent (for export when editing). */
export function agentToFormState(agent: PerspectiveAgent): PerspectiveFormState {
  return {
    name: agent.name ?? '',
    role: agent.role ?? '',
    purpose: agent.purpose ?? '',
    valuesText: (agent.values ?? []).join(', '),
    aversionsText: (agent.aversions ?? []).join(', '),
    reasoningText: (agent.reasoningStyle ?? []).join(', '),
    tone: agent.tone ?? '',
    domainText: (agent.domain ?? []).join(', '),
    decisionRule: agent.decisionRule ?? '',
    context: agent.context ?? '',
    worldview: agent.worldview,
    constraintsText: (agent.constraints ?? []).join(', '),
    examplePhrasesText: (agent.examplePhrases ?? []).join(', '),
    promptNotes: agent.promptNotes,
  }
}

/**
 * Generate a structured plain-text representation of the perspective (current form state).
 * Includes labels so other LLMs understand the structure. Empty fields are left blank.
 */
export function exportPerspective(state: PerspectiveFormState): string {
  const lines: string[] = ['PERSPECTIVE DEFINITION', '']

  const section = (label: string, value: string | undefined) => {
    lines.push(`${label}:`)
    lines.push(value?.trim() ? value.trim() : '(blank)')
    lines.push('')
  }

  section(EXPORT_LABELS.name, state.name)
  section(EXPORT_LABELS.role, state.role)
  section(EXPORT_LABELS.purpose, state.purpose)
  section(EXPORT_LABELS.values, state.valuesText)
  section(EXPORT_LABELS.aversions, state.aversionsText)
  section(EXPORT_LABELS.reasoningStyle, state.reasoningText)
  section(EXPORT_LABELS.tone, state.tone)
  section(EXPORT_LABELS.domain, state.domainText)
  section(EXPORT_LABELS.decisionRule, state.decisionRule)
  section(EXPORT_LABELS.context, state.context)
  section(EXPORT_LABELS.worldview, state.worldview)
  section(EXPORT_LABELS.constraints, state.constraintsText)
  section(EXPORT_LABELS.examplePhrases, state.examplePhrasesText)
  section(EXPORT_LABELS.promptNotes, state.promptNotes)

  return lines.join('\n').trimEnd()
}

/** Labels we recognize when parsing; key = normalized (lowercase, no extra space). */
const IMPORT_LABEL_PATTERNS: { pattern: RegExp; key: keyof PerspectiveAgent }[] = [
  { pattern: /^Name\s*:?\s*$/i, key: 'name' },
  { pattern: /^Role\s*\/\s*Perspective Type\s*:?\s*$/i, key: 'role' },
  { pattern: /^Core Purpose\s*:?\s*$/i, key: 'purpose' },
  { pattern: /^Top Values\s*:?\s*$/i, key: 'values' },
  { pattern: /^What it avoids\s*:?\s*$/i, key: 'aversions' },
  { pattern: /^Reasoning Style\s*:?\s*$/i, key: 'reasoningStyle' },
  { pattern: /^Tone of Voice\s*:?\s*$/i, key: 'tone' },
  { pattern: /^Domain\s*\/\s*Use Case\s*:?\s*$/i, key: 'domain' },
  { pattern: /^Decision Rule\s*:?\s*$/i, key: 'decisionRule' },
  { pattern: /^Context\s*\/\s*Reference Material\s*:?\s*$/i, key: 'context' },
  { pattern: /^Worldview notes\s*:?\s*$/i, key: 'worldview' },
  { pattern: /^Constraints\s*\/\s*boundaries\s*:?\s*$/i, key: 'constraints' },
  { pattern: /^Example phrases\s*:?\s*$/i, key: 'examplePhrases' },
  { pattern: /^Custom prompt notes\s*:?\s*$/i, key: 'promptNotes' },
]

function parseCsv(line: string): string[] {
  return line
    .split(/[,;]/)
    .map((s) => s.trim())
    .filter(Boolean)
}

/**
 * Parse pasted text for known labels. Everything until the next label belongs to that field.
 * Returns partial agent; only keys for which a label was found are set.
 */
export function parsePerspective(text: string): Partial<PerspectiveAgent> {
  const result: Partial<PerspectiveAgent> = {}
  const lines = text.split(/\r?\n/)
  let i = 0

  while (i < lines.length) {
    const line = lines[i]
    let matchedKey: keyof PerspectiveAgent | null = null
    for (const { pattern, key } of IMPORT_LABEL_PATTERNS) {
      if (pattern.test(line.trim())) {
        matchedKey = key
        break
      }
    }
    if (matchedKey) {
      const valueLines: string[] = []
      i += 1
      while (i < lines.length) {
        const next = lines[i]
        const isNextLabel = IMPORT_LABEL_PATTERNS.some(({ pattern }) => pattern.test(next.trim()))
        if (isNextLabel) break
        valueLines.push(next)
        i += 1
      }
      const raw = valueLines.join('\n').trim()
      const value = raw === '(blank)' ? '' : raw
      if (value !== undefined) {
        if (matchedKey === 'values' || matchedKey === 'aversions' || matchedKey === 'reasoningStyle' || matchedKey === 'domain' || matchedKey === 'constraints' || matchedKey === 'examplePhrases') {
          ;(result as Record<string, unknown>)[matchedKey] = parseCsv(value)
        } else {
          ;(result as Record<string, unknown>)[matchedKey] = value
        }
      }
      continue
    }
    i += 1
  }

  return result
}
