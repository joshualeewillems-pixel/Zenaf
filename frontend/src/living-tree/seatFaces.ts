/**
 * The fellowship faces — Joshua's canonical seat portraits.
 *
 * ("These are the ones… Use these", 2026-10-18.) Split from his 7-panel
 * scenic sumi-e composite: elephant/Gardener, lion/Firebrand, bear/Bear,
 * fox/Fox, crane/Bridge, octopus/Weaver, raven/Neighbor — each in its
 * seat's canonical color.
 *
 * These are the REVEALED faces. They render only once the training-depth
 * unlock is earned (`avatar_unlocked` from GET /council/archetypes/status,
 * threshold AVATAR_DEPTH_THRESHOLD = 10 depth points in
 * local_ai/council/naming.py). The ??? placeholder stays until then — the
 * gate is never weakened here. A user-uploaded/generated custom avatar
 * (`avatar_url`) always wins over the fellowship face.
 */

import mentorAvatar from '../assets/seats/mentor-avatar.jpg'
import championAvatar from '../assets/seats/champion-avatar.jpg'
import guardianAvatar from '../assets/seats/guardian-avatar.jpg'
import maverickAvatar from '../assets/seats/maverick-avatar.jpg'
import ambassadorAvatar from '../assets/seats/ambassador-avatar.jpg'
import conductorAvatar from '../assets/seats/conductor-avatar.jpg'
import skepticAvatar from '../assets/seats/skeptic-avatar.jpg'

import mentorPanel from '../assets/seats/mentor-panel.jpg'
import championPanel from '../assets/seats/champion-panel.jpg'
import guardianPanel from '../assets/seats/guardian-panel.jpg'
import maverickPanel from '../assets/seats/maverick-panel.jpg'
import ambassadorPanel from '../assets/seats/ambassador-panel.jpg'
import conductorPanel from '../assets/seats/conductor-panel.jpg'
import skepticPanel from '../assets/seats/skeptic-panel.jpg'

/** Square avatar crops (160px), keyed by stock archetype id. */
export const SEAT_FACES: Record<string, string> = {
  mentor: mentorAvatar,
  champion: championAvatar,
  guardian: guardianAvatar,
  maverick: maverickAvatar,
  ambassador: ambassadorAvatar,
  conductor: conductorAvatar,
  skeptic: skepticAvatar,
}

/** Full illustration panels (character art), keyed by stock archetype id. */
export const SEAT_PANELS: Record<string, string> = {
  mentor: mentorPanel,
  champion: championPanel,
  guardian: guardianPanel,
  maverick: maverickPanel,
  ambassador: ambassadorPanel,
  conductor: conductorPanel,
  skeptic: skepticPanel,
}

/** Minimal shape needed to resolve a seat's face. */
export interface SeatFaceSource {
  id: string
  avatar_url: string | null | undefined
  avatar_unlocked: boolean
}

/**
 * Resolve the face to render for a seat.
 *
 * Custom user avatar wins; otherwise the fellowship face once the depth
 * unlock is earned; otherwise null and the ??? placeholder stays.
 */
export function resolveSeatFace(arch: SeatFaceSource): string | null {
  if (arch.avatar_url) return arch.avatar_url
  if (arch.avatar_unlocked) return SEAT_FACES[arch.id] ?? null
  return null
}

/**
 * Full character panel art for a seat — the illustration behind the face.
 * Gated on the same unlock: locked seats reveal nothing.
 */
export function resolveSeatPanel(arch: SeatFaceSource): string | null {
  if (!arch.avatar_unlocked) return null
  return SEAT_PANELS[arch.id] ?? null
}
