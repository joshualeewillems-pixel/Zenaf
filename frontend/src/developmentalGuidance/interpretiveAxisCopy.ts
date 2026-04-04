/**
 * Loads canonical interpretive-axis copy from interpretive_axis_copy.json.
 *
 * Runtime-only language helpers for the developmental-guidance read layer — not persisted,
 * not a user model, not profile truth. Future durable judgment artifacts would be a separate
 * design (versioned records + evidence + review), not a freeze of this wording.
 */
import raw from './interpretive_axis_copy.json'

type CopyShape = {
  _doc?: string
  axisNames: {
    clarityAmbiguity: string
    actionIdeation: string
    followThroughDropoff: string
    structureExploration: string
    integrationFragmentation: string
  }
  tilts: Record<string, string>
  labels: {
    packetSectionTitle: string
    panelSectionTitle: string
    guideSentenceLeadIn: string
    panelCollapsibleTitle: string
    panelIntro: string
  }
}

export const interpretiveAxisCopy = raw as CopyShape

/** Canonical axis display names — same strings the server whitelist allows. */
export const INTERPRETIVE_AXIS_NAMES = interpretiveAxisCopy.axisNames
