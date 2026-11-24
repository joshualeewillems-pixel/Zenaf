/**
 * Atelier reads — the Vision map's own data path, reused whole:
 * the same entity fetch, the same studio council runs, the same
 * node-vitality and strand-weighting reads (each degrading exactly
 * as the map's load degrades them), and the same graph build, whose
 * cairn index is the garden. No new endpoints, no writes anywhere.
 *
 * Talk depth reads the subject conversation through the same GET
 * /conversation seam CouncilChat hydrates from, counting each seat's
 * messages. A failed or absent conversation counts as no talk —
 * silence, never an invented depth.
 */
import { apiBase } from '../apiBase'
import { CAIRN_NARROW_THRESHOLD } from '../vision-map/cairn'
import {
  keystoneConversationCountsByProject,
  type SeatConversationCounts,
} from '../vision-map/conversationColour'
import { fetchStudioCouncilRuns } from '../vision-map/fetchStudioCouncilRuns'
import { buildLiveVisionMapGraph } from '../vision-map/liveProjection'
import {
  fetchNodeVitalityMap,
  fetchStrandWeightings,
  fetchVisionMapEntities,
} from '../vision-map/veMapApi'
import { buildGarden, type AtelierGarden } from './atelierLogic'

export interface AtelierData {
  garden: AtelierGarden
  /** Per-project completed keystone arcs by seat (archetype id) —
   *  the conversation-colour counts, one talk-depth input. */
  keystoneCounts: Map<string, SeatConversationCounts>
}

export async function fetchAtelierData(): Promise<AtelierData> {
  const [entities, runs, serverVitality, strandWeights] = await Promise.all([
    fetchVisionMapEntities(),
    fetchStudioCouncilRuns(80),
    fetchNodeVitalityMap().catch(() => undefined),
    fetchStrandWeightings().catch(() => undefined),
  ])
  const g = buildLiveVisionMapGraph(entities, runs, serverVitality, {
    cairnThreshold: CAIRN_NARROW_THRESHOLD,
    strandWeights,
  })
  return {
    garden: buildGarden(entities, g.cairnIndex),
    keystoneCounts: keystoneConversationCountsByProject(entities.tasks),
  }
}

export interface SeatTurns {
  /** Seat messages per archetype id in the conversation. */
  counts: Record<string, number>
  /** The archetype of the most recent seat message, if any. */
  lastArchetype: string | null
}

/**
 * Count each seat's messages in one conversation (archetype id →
 * count), via the read CouncilChat hydrates from. Any failure —
 * absent conversation, signed out, malformed body — resolves to an
 * empty count rather than failing the surface.
 */
export async function fetchSeatTurnCounts(conversationId: string): Promise<SeatTurns> {
  try {
    const res = await fetch(
      `${apiBase()}/conversation?conversation_id=${encodeURIComponent(conversationId)}&limit=200`,
      { credentials: 'include' },
    )
    if (!res.ok) return { counts: {}, lastArchetype: null }
    const data: unknown = await res.json()
    const messages = (data as { messages?: unknown }).messages
    if (!Array.isArray(messages)) return { counts: {}, lastArchetype: null }
    const counts: Record<string, number> = {}
    let lastArchetype: string | null = null
    for (const m of messages) {
      if (!m || typeof m !== 'object') continue
      const row = m as Record<string, unknown>
      if (row.role === 'user') continue
      const aid = typeof row.archetype_id === 'string' ? row.archetype_id : null
      if (!aid) continue
      if (typeof row.body === 'string' && !row.body.trim()) continue
      counts[aid] = (counts[aid] ?? 0) + 1
      lastArchetype = aid
    }
    return { counts, lastArchetype }
  } catch {
    return { counts: {}, lastArchetype: null }
  }
}
