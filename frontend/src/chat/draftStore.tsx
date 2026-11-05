import { createContext, useContext, useEffect, useMemo, useRef, type ReactNode } from 'react'

/**
 * In-memory composer draft store for the Living Tree sheet subtree.
 *
 * One store, owned at App level via DraftStoreProvider, provided ONLY to
 * the Tree sheet subtree (the renderTreeSheetContent path mounting
 * TreeTalkSheet). VoiceConsole and MapChatShell mount CouncilChat
 * outside that subtree and never receive the provider, so their
 * composers stay purely local — provider placement, not key
 * namespacing alone, is the isolation mechanism.
 *
 * Keys are (userId, conversationId, seat) where seat is the active
 * seat's archetype_id, or the reserved 'council' identity when council
 * mode is on (collides with no archetype_id), or the reserved
 * 'unselected' identity when neither a seat is selected nor council
 * mode is on. Mounts with a null conversationId (CouncilChat's 'local'
 * fallback) must never read from or write to the store.
 *
 * The store is React state owned by the provider, never a module-level
 * app-wide singleton, and never browser storage: a page reload
 * destroys it by construction. Draft restore is display-only — a
 * restored draft is never sent until the user presses Send.
 */

export const COUNCIL_DRAFT_SEAT = 'council'
export const UNSELECTED_DRAFT_SEAT = 'unselected'

export type DraftKey = {
  userId: string
  conversationId: string
  seat: string
}

function keyOf(key: DraftKey): string {
  return JSON.stringify([key.userId, key.conversationId, key.seat])
}

/**
 * Pure draft map plus the adoption rule. Kept class-shaped so the
 * store logic is unit-testable without rendering anything.
 *
 * currentUserId is set by the provider on every user change; every
 * read verifies the key's userId against it (a miss on mismatch),
 * and every write is a no-op on mismatch, so a stale key can never
 * surface another user's draft even if a purge was somehow skipped.
 */
export class DraftStore {
  private map = new Map<string, string>()
  currentUserId: string | null = null

  get(key: DraftKey): string | undefined {
    if (key.userId !== this.currentUserId) return undefined
    return this.map.get(keyOf(key))
  }

  set(key: DraftKey, text: string): void {
    if (key.userId !== this.currentUserId) return
    this.map.set(keyOf(key), text)
  }

  clear(key: DraftKey): void {
    if (key.userId !== this.currentUserId) return
    this.map.delete(keyOf(key))
  }

  purgeAll(): void {
    this.map.clear()
  }

  /**
   * Adoption (design §3.7 + verdict C4): moving a draft typed before
   * any seat was picked ('unselected') into a newly selected seat.
   *
   * - Destination already has a saved draft: the saved draft wins and
   *   is returned; the unselected text is preserved independently
   *   (no overwrite, no merge).
   * - Destination empty and an unselected draft exists: the move
   *   happens — the text is written under the destination key and the
   *   unselected entry is cleared, so the same text can never reappear
   *   in an unselected composer after being adopted.
   * - No unselected draft: returns undefined (composer stays empty).
   * - Destination IS 'unselected': no move; returns its own draft.
   */
  adopt(userId: string, conversationId: string, destSeat: string): string | undefined {
    if (destSeat === UNSELECTED_DRAFT_SEAT) {
      return this.get({ userId, conversationId, seat: UNSELECTED_DRAFT_SEAT })
    }
    const existing = this.get({ userId, conversationId, seat: destSeat })
    if (existing !== undefined) return existing
    const unselected = this.get({ userId, conversationId, seat: UNSELECTED_DRAFT_SEAT })
    if (unselected === undefined || unselected === '') return undefined
    this.set({ userId, conversationId, seat: destSeat }, unselected)
    this.clear({ userId, conversationId, seat: UNSELECTED_DRAFT_SEAT })
    return unselected
  }
}

export type DraftStoreContextValue = {
  store: DraftStore
  userId: string | null
}

// Exported for tests only (a probe component that exposes the store to
// assertions); production code reads the context via useDraftStore.
export const DraftStoreContext = createContext<DraftStoreContextValue | null>(null)

export function useDraftStore(): DraftStoreContextValue | null {
  return useContext(DraftStoreContext)
}

export function DraftStoreProvider({
  userId,
  children,
}: {
  userId: string | null
  children: ReactNode
}) {
  const storeRef = useRef<DraftStore | null>(null)
  if (storeRef.current === null) storeRef.current = new DraftStore()
  const store = storeRef.current
  // Assigned during render (idempotent) so a child's mount-time
  // initializer — which runs before effects — already sees the
  // current user. The purge below still runs on every user change.
  store.currentUserId = userId
  const prevUserRef = useRef<string | null | undefined>(undefined)
  useEffect(() => {
    // Auth change (logout, logout→login as a different user, session
    // replacement): purge BEFORE any new conversation mounts. The
    // first mount only records the user; it never purges a fresh store.
    // Key checks make stale entries unreachable in the window between
    // the render-time user switch and this effect.
    if (prevUserRef.current !== undefined && prevUserRef.current !== userId) {
      store.purgeAll()
    }
    prevUserRef.current = userId
  }, [userId, store])
  const value = useMemo(() => ({ store, userId }), [store, userId])
  return <DraftStoreContext.Provider value={value}>{children}</DraftStoreContext.Provider>
}
