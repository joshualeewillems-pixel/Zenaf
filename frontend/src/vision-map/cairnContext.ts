import { createContext, useContext } from 'react'

/**
 * Lets stone nodes toggle cairns without prop-drilling through React Flow's
 * static `nodeTypes` map. The view provides `onToggleCairn`; cairn nodes
 * toggle themselves, expanded member stones collapse back.
 */
export const CairnInteractionContext = createContext<{
  onToggleCairn: (cairnId: string) => void
}>({ onToggleCairn: () => {} })

export function useCairnInteraction() {
  return useContext(CairnInteractionContext)
}
