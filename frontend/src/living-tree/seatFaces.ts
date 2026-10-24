/**
 * The fellowship faces — Joshua's canonical seat portraits.
 *
 * ("These are the ones… Use these", 2026-10-18.) Split from his 7-panel
 * scenic sumi-e composite: elephant/Gardener, lion/Firebrand, bear/Bear,
 * fox/Fox, crane/Crane, octopus/Weaver, raven/Raven — each in its
 * seat's canonical color.
 *
 * These are the REVEALED faces. They render once the seat's face is
 * revealed (`face_revealed` from GET /council/archetypes/status), which
 * happens by EITHER door: completing the seat's first meeting
 * (keystone 1 — the keystone design makes the meeting the reveal of
 * name, face, and demeanor) or earning the training-depth milestone
 * (AVATAR_DEPTH_THRESHOLD = 10 depth points in
 * local_ai/council/naming.py). Before 2026-10-23 only the depth door
 * existed here, so a completed first meeting revealed nothing — the
 * two unlock systems had never been reconciled. A user-uploaded/
 * generated custom avatar (`avatar_url`) always wins over the
 * fellowship face; customization itself stays depth-gated
 * (`avatar_unlocked`).
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
  /** Revealed by the first meeting or the depth milestone. Optional
   *  for older payloads — falls back to the depth door alone. */
  face_revealed?: boolean
}

function isRevealed(arch: SeatFaceSource): boolean {
  return arch.face_revealed ?? arch.avatar_unlocked
}

/**
 * Resolve the face to render for a seat.
 *
 * Custom user avatar wins; otherwise the fellowship face once revealed
 * (first meeting complete, or the depth milestone); otherwise null and
 * the ??? placeholder stays.
 */
export function resolveSeatFace(arch: SeatFaceSource): string | null {
  if (arch.avatar_url) return arch.avatar_url
  if (isRevealed(arch)) return SEAT_FACES[arch.id] ?? null
  return null
}

/**
 * Full character panel art for a seat — the illustration behind the face.
 * Gated on the same reveal: unrevealed seats show nothing.
 */
export function resolveSeatPanel(arch: SeatFaceSource): string | null {
  if (!isRevealed(arch)) return null
  return SEAT_PANELS[arch.id] ?? null
}
