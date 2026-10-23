import { createContext, useContext } from 'react'

/**
 * Lets stone nodes drive cairn gestures without prop-drilling through React
 * Flow's static `nodeTypes` map. The view provides both actions: cairn nodes
 * toggle themselves, expanded member stones collapse back, an initiative
 * (tree) stone toggles that initiative's stack, and a garden stack unstacks
 * its initiative through the same toggle path as any cairn.
 */
export const CairnInteractionContext = createContext<{
  onToggleCairn: (cairnId: string) => void
  /** Toggles one initiative's stack: its children as the pile on its stone vs the full subtree. */
  onToggleGardenStack: (treeId: string) => void
}>({ onToggleCairn: () => {}, onToggleGardenStack: (_treeId: string) => {} })

export function useCairnInteraction() {
  return useContext(CairnInteractionContext)
}
