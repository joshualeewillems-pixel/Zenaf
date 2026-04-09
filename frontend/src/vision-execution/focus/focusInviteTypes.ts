import type { ActionId } from './types'

export type FocusInviteKind = 'conversational' | 'structured_fill'

export type FocusInviteFlowTier = 'primary' | 'secondary' | 'tertiary'

/** Compact council starter derived from field capability rows (Pass 2 v1). */
export type FocusInvite = {
  id: string
  kind: FocusInviteKind
  sourceAction: ActionId
  label: string
  /** Flow Spine Charter: invite rank within allowed actions (conversational only). */
  flowTier?: FocusInviteFlowTier
}
