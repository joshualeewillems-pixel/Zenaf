import { createContext, useContext } from 'react'

/**
 * Lets stone nodes drive cairn gestures without prop-drilling through React
 * Flow's static `nodeTypes` map. The view provides the actions: cairn nodes
 * toggle themselves (fan out / stack back / unstack), a member of a fanned
 * cairn stacks its cairn back, an initiative (tree) stone toggles that
 * initiative's stack, a stone's data opens through the same selection a tap
 * produces, and the hold ladder reports its two moments — tier 1 arming a
 * drag (the view tracks the pointer from there) and tier 2 spending the
 * press (its release must not also land as a click).
 */
export const CairnInteractionContext = createContext<{
  onToggleCairn: (cairnId: string) => void
  /** Toggles one initiative's stack: its children as the pile on its stone vs the full subtree. */
  onToggleGardenStack: (treeId: string) => void
  /** Selects a stone, opening its data sheet — exactly what a tap does. */
  onOpenStoneData: (nodeId: string) => void
  /** Hold ladder tier 1: a still touch hold armed drag for this node — the view starts tracking the pointer. */
  onDragArm: (nodeId: string, pointerId: number, clientX: number, clientY: number) => void
  /** Hold ladder tier 2 fired: the press is spent — swallow the click its release produces. */
  onPressSpent: () => void
}>({
  onToggleCairn: () => {},
  onToggleGardenStack: (_treeId: string) => {},
  onOpenStoneData: (_nodeId: string) => {},
  onDragArm: (_nodeId: string, _pointerId: number, _clientX: number, _clientY: number) => {},
  onPressSpent: () => {},
})

export function useCairnInteraction() {
  return useContext(CairnInteractionContext)
}
