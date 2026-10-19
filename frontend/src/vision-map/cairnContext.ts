import { createContext, useContext } from 'react'

/**
 * Lets stone nodes toggle cairns without prop-drilling through React Flow's
 * static `nodeTypes` map. The view provides both actions: cairn nodes toggle
 * themselves, expanded member stones collapse back, and the initiative
 * (tree) stone collapses every expanded cairn at once.
 */
export const CairnInteractionContext = createContext<{
  onToggleCairn: (cairnId: string) => void
  onCollapseAllCairns: () => void
}>({ onToggleCairn: () => {}, onCollapseAllCairns: () => {} })

export function useCairnInteraction() {
  return useContext(CairnInteractionContext)
}
