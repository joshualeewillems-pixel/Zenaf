import { createContext, useContext } from 'react'

/**
 * Lets stone nodes drive cairn gestures without prop-drilling through React
 * Flow's static `nodeTypes` map. The view provides both actions: cairn nodes
 * toggle themselves, expanded member stones collapse back, the initiative
 * (tree) stone toggles the whole-garden stack, and the mega-cairn unstacks
 * through the same toggle path as any cairn.
 */
export const CairnInteractionContext = createContext<{
  onToggleCairn: (cairnId: string) => void
  /** Toggles the whole-garden stack: one mega-cairn vs the full garden. */
  onToggleGardenStack: () => void
}>({ onToggleCairn: () => {}, onToggleGardenStack: () => {} })

export function useCairnInteraction() {
  return useContext(CairnInteractionContext)
}
